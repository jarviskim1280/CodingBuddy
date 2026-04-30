"""Runner — spawns and coordinates worker + reviewer agents."""
import asyncio
import json
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
        self._tasks: list[asyncio.Task] = []

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(self, plan: dict):
        """Run the full pipeline: clone → parallel workers → review loop → merge."""
        with SessionLocal() as session:
            project = get_project(session, self.project_id)
            repo_url = project.repo_url
            stack = project.stack or {}
            tasks = list_tasks(session, self.project_id)
            # detach
            session.expunge_all()

        # clone url may need token injection
        clone_url = self.github.clone_url(repo_url)

        # workspace for this project
        workspace = settings.repo_workspace / f"project_{self.project_id}"
        workspace.mkdir(parents=True, exist_ok=True)

        # spawn one async task per worker agent type
        coros = []
        for task in tasks:
            if task.type in AGENT_CLASSES:
                coros.append(self._run_worker(task, clone_url, workspace, stack))

        # run backend first (frontend + tests might depend on it)
        backend_tasks = [t for t in tasks if t.type == "backend"]
        other_tasks = [t for t in tasks if t.type != "backend"]

        for bt in backend_tasks:
            await self._run_worker(bt, clone_url, workspace, stack)

        if other_tasks:
            await asyncio.gather(
                *[self._run_worker(t, clone_url, workspace, stack) for t in other_tasks]
            )

        with SessionLocal() as session:
            update_project(session, self.project_id, status="done")

        await self._broadcast({"type": "project_done", "project_id": self.project_id})

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

        # create agent record
        with SessionLocal() as session:
            agent_rec = create_agent(session, self.project_id, agent_type)
            agent_id = agent_rec.id
            task_id = task.id
            update_task(session, task_id, assigned_agent_id=agent_id, status="in_progress")

        agent: BackendAgent = AgentClass(agent_id, self.project_id)
        agent.broadcast_fn = self.broadcast_fn

        agent.set_status("working", task_id)
        agent.log(f"Starting task: {task.description}")

        # each agent works in its own directory clone
        repo_dir = workspace / agent_type
        try:
            agent.clone_repo(clone_url, repo_dir)

            branch = f"{agent_type}/task-{task_id}"
            agent.create_branch(repo_dir, branch)

            with SessionLocal() as session:
                update_task(session, task_id, branch=branch)

            # refresh task with branch set
            with SessionLocal() as session:
                task_fresh = get_task(session, task_id)
                session.expunge(task_fresh)

            summary = await agent.do_work(task_fresh, repo_dir, stack)
            agent.log(f"Work complete: {summary}")

            commit_msg = f"feat({agent_type}): {task.description[:72]}"
            agent.commit_and_push(repo_dir, branch, commit_msg)

            # open PR
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

            # run review loop
            await self._review_loop(agent, task_fresh, pr, repo_dir, repo_url_local, stack)

        except Exception as exc:
            agent.log(f"ERROR: {exc}", level="error")
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
    ):
        with SessionLocal() as session:
            reviewer_rec = create_agent(session, self.project_id, "reviewer")
            reviewer_id = reviewer_rec.id

        reviewer = ReviewerAgent(reviewer_id, self.project_id)
        reviewer.broadcast_fn = self.broadcast_fn
        reviewer.set_status("working", task.id)

        previous_comments: list = []

        for round_num in range(1, settings.max_review_rounds + 1):
            reviewer.log(f"Review round {round_num} for PR {pr.url}")

            diff = self.github.get_pr_diff(repo_url, pr, repo_dir)
            review = await reviewer.review_pr(task, diff, round_num, previous_comments or None)

            if review.status == "approved" or round_num >= settings.max_review_rounds:
                if round_num >= settings.max_review_rounds and review.status != "approved":
                    reviewer.log("Max review rounds reached — auto-approving.")

                reviewer.log("PR approved — merging.")
                self.github.merge_pr(repo_url, pr, repo_dir)

                review_comment = f"✅ PR approved and merged (round {round_num})."
                self.github.post_review_comment(repo_url, pr, review_comment)

                with SessionLocal() as session:
                    update_task(session, task.id, status="done")
                    update_agent(session, worker_agent.agent_db_id, status="done")
                    update_agent(session, reviewer_id, status="done")

                worker_agent.log("Task done.")
                reviewer.set_status("done")
                return

            # changes requested
            comments = review.comments or []
            previous_comments = comments

            comment_body = "**Changes requested:**\n" + "\n".join(
                f"- `{c.get('file', '?')}`: {c.get('issue', '')} — {c.get('suggestion', '')}"
                for c in comments
            )
            self.github.post_review_comment(repo_url, pr, comment_body)

            reviewer.log(f"Sent {len(comments)} review comments to worker.")
            reviewer.set_status("waiting")
            worker_agent.set_status("working", task.id)
            worker_agent.log(f"Addressing {len(comments)} review comments (round {round_num})")

            # worker addresses comments
            worker_agent.checkout_branch(repo_dir, pr.head)
            await worker_agent.do_address_comments(task, repo_dir, stack, comments)
            worker_agent.commit_and_push(
                repo_dir, pr.head, f"fix: address review comments round {round_num}"
            )

            worker_agent.set_status("waiting", task.id)
            reviewer.set_status("working", task.id)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _broadcast(self, event: dict):
        if self.broadcast_fn:
            await self.broadcast_fn(event)
