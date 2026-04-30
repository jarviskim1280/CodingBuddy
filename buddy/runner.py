"""Runner — spawns and coordinates worker + reviewer agents."""
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

from buddy.agents.backend import BackendAgent
from buddy.agents.frontend import FrontendAgent
from buddy.agents.reviewer import ReviewerAgent
from buddy.agents.tester import TesterAgent
from buddy.config import settings
from buddy.db.models import Agent, Project, Task
from buddy.db.ops import (
    SessionLocal,
    create_agent,
    get_project,
    get_task,
    latest_review,
    list_tasks,
    update_agent,
    update_project,
    update_task,
)
from buddy.github_client import PullRequest, get_github_client


AGENT_CLASSES = {
    "backend": BackendAgent,
    "frontend": FrontendAgent,
    "tests": TesterAgent,
}


def _extract_pr_number(pr_url: str) -> int:
    """Parse the PR number from a mock://pr/N or GitHub PR URL."""
    match = re.search(r"/(\d+)$", pr_url.rstrip("/"))
    return int(match.group(1)) if match else 0


class ProjectRunner:
    """Orchestrates all agents for a single project."""

    def __init__(
        self,
        project_id: int,
        broadcast_fn: Optional[Callable] = None,
    ):
        self.project_id = project_id
        self.broadcast_fn = broadcast_fn
        self.github = get_github_client()

    # ── Full pipeline (new project) ───────────────────────────────────────────

    async def run(self, plan: dict):
        """Run the full pipeline: clone → parallel workers → review loop → merge."""
        with SessionLocal() as session:
            project = get_project(session, self.project_id)
            stack = project.stack or {}
            tasks = list_tasks(session, self.project_id)
            session.expunge_all()

        clone_url = self.github.clone_url(project.repo_url)
        workspace = settings.repo_workspace / f"project_{self.project_id}"
        workspace.mkdir(parents=True, exist_ok=True)

        # Run agents fully sequentially to stay under rate limits
        ordered = (
            [t for t in tasks if t.type == "backend"]
            + [t for t in tasks if t.type == "frontend"]
            + [t for t in tasks if t.type == "tests"]
        )
        for t in ordered:
            await self._run_worker(t, clone_url, workspace, stack)

        with SessionLocal() as session:
            update_project(session, self.project_id, status="done")

        await self._broadcast({"type": "project_done", "project_id": self.project_id})

    # ── Resume (restart from last known good state) ───────────────────────────

    async def resume(self):
        """Resume a partially completed project without redoing finished work."""
        with SessionLocal() as session:
            project = get_project(session, self.project_id)
            if not project:
                raise ValueError(f"Project {self.project_id} not found")
            stack = project.stack or {}
            repo_url = project.repo_url
            tasks = list_tasks(session, self.project_id)
            session.expunge_all()

        clone_url = self.github.clone_url(repo_url)
        workspace = settings.repo_workspace / f"project_{self.project_id}"
        workspace.mkdir(parents=True, exist_ok=True)

        to_restart: list[Task] = []   # pending / in_progress / failed → re-run from scratch
        to_review: list[Task] = []    # review → PR exists, re-enter review loop

        for task in tasks:
            if task.status == "done":
                continue
            elif task.pr_url and task.branch:
                # PR is already open (review state, or failed after PR was opened)
                # — re-enter the review loop instead of redoing the work
                to_review.append(task)
            else:
                # pending / in_progress / failed with no PR yet → reset and re-run
                with SessionLocal() as session:
                    update_task(session, task.id, status="pending", assigned_agent_id=None)
                to_restart.append(task)

        await self._broadcast({
            "type": "resume",
            "project_id": self.project_id,
            "restarting": len(to_restart),
            "resuming_review": len(to_review),
            "skipped_done": sum(1 for t in tasks if t.status == "done"),
        })

        # Restart crashed/pending tasks (backend first)
        backend_restart = [t for t in to_restart if t.type == "backend"]
        other_restart = [t for t in to_restart if t.type != "backend"]

        for bt in backend_restart:
            await self._run_worker(bt, clone_url, workspace, stack)

        # Run sequentially to stay under rate limits
        ordered_restart = (
            [t for t in to_restart if t.type == "backend"]
            + [t for t in to_restart if t.type == "frontend"]
            + [t for t in to_restart if t.type == "tests"]
        )
        for t in ordered_restart:
            await self._run_worker(t, clone_url, workspace, stack)

        for t in to_review:
            await self._resume_review_loop(t, clone_url, workspace, repo_url, stack)

        all_tasks_now = []
        with SessionLocal() as session:
            all_tasks_now = list_tasks(session, self.project_id)
            session.expunge_all()

        if all(t.status == "done" for t in all_tasks_now):
            with SessionLocal() as session:
                update_project(session, self.project_id, status="done")
            await self._broadcast({"type": "project_done", "project_id": self.project_id})

    async def _resume_review_loop(
        self,
        task: Task,
        clone_url: str,
        workspace: Path,
        repo_url: str,
        stack: dict,
    ):
        """Re-enter the review loop for a task whose PR is already open."""
        agent_type = task.type
        AgentClass = AGENT_CLASSES.get(agent_type)
        if not AgentClass:
            return

        with SessionLocal() as session:
            agent_rec = create_agent(session, self.project_id, agent_type)
            agent_id = agent_rec.id
            update_task(session, task.id, assigned_agent_id=agent_id)

        worker: BackendAgent = AgentClass(agent_id, self.project_id)
        worker.broadcast_fn = self.broadcast_fn
        worker.set_status("waiting", task.id)
        worker.log(f"Resuming review loop for existing PR: {task.pr_url}")

        repo_dir = workspace / agent_type
        try:
            worker.clone_repo(clone_url, repo_dir)
            worker.checkout_branch(repo_dir, task.branch)
        except Exception as exc:
            worker.log(f"Could not checkout branch {task.branch}: {exc}", level="error")
            return

        pr = PullRequest(
            number=_extract_pr_number(task.pr_url),
            url=task.pr_url,
            title=f"[{agent_type}] {task.description[:60]}",
            head=task.branch,
        )

        # Figure out which review round to start from
        with SessionLocal() as session:
            last_review = latest_review(session, task.id)
            next_round = (last_review.round_number + 1) if last_review else 1

        worker.log(f"Resuming from review round {next_round}")
        await self._review_loop(worker, task, pr, repo_dir, repo_url, stack, start_round=next_round)

    # ── Worker lifecycle ──────────────────────────────────────────────────────

    async def _run_worker(
        self,
        task: Task,
        clone_url: str,
        workspace: Path,
        stack: dict,
    ):
        agent_type = task.type
        AgentClass = AGENT_CLASSES[agent_type]

        with SessionLocal() as session:
            agent_rec = create_agent(session, self.project_id, agent_type)
            agent_id = agent_rec.id
            task_id = task.id
            update_task(session, task_id, assigned_agent_id=agent_id, status="in_progress")

        agent: BackendAgent = AgentClass(agent_id, self.project_id)
        agent.broadcast_fn = self.broadcast_fn

        agent.set_status("working", task_id)
        agent.log(f"Starting task: {task.description}")

        repo_dir = workspace / agent_type
        try:
            agent.clone_repo(clone_url, repo_dir)

            branch = f"{agent_type}/task-{task_id}"
            agent.create_branch(repo_dir, branch)

            with SessionLocal() as session:
                update_task(session, task_id, branch=branch)

            with SessionLocal() as session:
                task_fresh = get_task(session, task_id)
                session.expunge(task_fresh)

            summary = await agent.do_work(task_fresh, repo_dir, stack)
            agent.log(f"Work complete: {summary}")

            commit_msg = f"feat({agent_type}): {task.description[:72]}"
            agent.commit_and_push(repo_dir, branch, commit_msg)

            with SessionLocal() as session:
                proj = get_project(session, self.project_id)
                repo_url_local = proj.repo_url
                session.expunge(proj)

            pr = self.github.create_pr(
                repo_url=repo_url_local,
                head=branch,
                base="main",
                title=f"[{agent_type}] {task.description[:60]}",
                body=f"Automated PR by CodingBuddy {agent_type} agent.\n\n{summary}",
            )

            with SessionLocal() as session:
                update_task(session, task_id, pr_url=pr.url, status="review")

            agent.log(f"Opened PR: {pr.url}")
            agent.set_status("waiting", task_id)

            await self._review_loop(agent, task_fresh, pr, repo_dir, repo_url_local, stack)

        except Exception as exc:
            import traceback
            agent.log(f"ERROR: {exc}\n{traceback.format_exc()}", level="error")
            with SessionLocal() as session:
                update_task(session, task_id, status="failed")
                update_agent(session, agent_id, status="failed")
            raise

    # ── Review loop ───────────────────────────────────────────────────────────

    async def _review_loop(
        self,
        worker_agent: BackendAgent,
        task: Task,
        pr: PullRequest,
        repo_dir: Path,
        repo_url: str,
        stack: dict,
        start_round: int = 1,
    ):
        with SessionLocal() as session:
            reviewer_rec = create_agent(session, self.project_id, "reviewer")
            reviewer_id = reviewer_rec.id

        reviewer = ReviewerAgent(reviewer_id, self.project_id)
        reviewer.broadcast_fn = self.broadcast_fn
        reviewer.set_status("working", task.id)

        previous_comments: list = []

        for round_num in range(start_round, settings.max_review_rounds + 1):
            reviewer.log(f"Review round {round_num} for PR {pr.url}")

            diff = self.github.get_pr_diff(repo_url, pr, repo_dir)
            review = await reviewer.review_pr(task, diff, round_num, previous_comments or None)

            if review.status == "approved" or round_num >= settings.max_review_rounds:
                if round_num >= settings.max_review_rounds and review.status != "approved":
                    reviewer.log("Max review rounds reached — auto-approving.")

                reviewer.log("PR approved — merging.")
                self.github.merge_pr(repo_url, pr, repo_dir)
                self.github.post_review_comment(repo_url, pr, f"✅ PR approved and merged (round {round_num}).")

                with SessionLocal() as session:
                    update_task(session, task.id, status="done")
                    update_agent(session, worker_agent.agent_db_id, status="done")
                    update_agent(session, reviewer_id, status="done")

                worker_agent.log("Task done.")
                reviewer.set_status("done")
                return

            comments = review.comments or []
            previous_comments = comments

            comment_body = (
                f"**🔍 Review round {round_num} — changes requested ({len(comments)} issues):**\n\n"
                + "\n".join(
                    f"- `{c.get('file', '?')}` — {c.get('issue', '')}. "
                    f"*Suggestion: {c.get('suggestion', '')}*"
                    for c in comments
                )
            )
            self.github.post_review_comment(repo_url, pr, comment_body)
            reviewer.log(f"Posted {len(comments)} review comments — handing back to worker.")
            reviewer.set_status("waiting")

            worker_agent.set_status("working", task.id)
            worker_agent.log(f"Checking out branch '{pr.head}' to address review comments (round {round_num})")

            try:
                worker_agent.checkout_branch(repo_dir, pr.head)
            except Exception as exc:
                worker_agent.log(f"Failed to checkout branch '{pr.head}': {exc}", level="error")
                raise

            worker_agent.log(f"Addressing {len(comments)} review comments…")
            summary = await worker_agent.do_address_comments(task, repo_dir, stack, comments)
            worker_agent.log(f"Address comments complete: {summary}")

            try:
                worker_agent.commit_and_push(
                    repo_dir, pr.head,
                    f"fix: address review comments round {round_num}\n\n"
                    + "\n".join(f"- {c.get('issue', '')}" for c in comments[:10])
                )
            except Exception as exc:
                worker_agent.log(f"Failed to push addressing commit: {exc}", level="error")
                raise

            self.github.post_review_comment(
                repo_url, pr,
                f"✏️ Round {round_num} comments addressed — pushed fixes to `{pr.head}`."
            )
            worker_agent.set_status("waiting", task.id)
            reviewer.set_status("working", task.id)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _broadcast(self, event: dict):
        if self.broadcast_fn:
            await self.broadcast_fn(event)
