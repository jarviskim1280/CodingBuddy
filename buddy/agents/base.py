"""Base agent — Claude tool-loop + git + logging + mid-task exception handling."""
import asyncio
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import anthropic

from buddy.config import settings
from buddy.db.models import Agent, Task
from buddy.db.ops import (
    SessionLocal,
    active_agents_with_tasks,
    add_log,
    create_task,
    post_agent_message,
    update_agent,
    update_task,
)


# ── File tools Claude can call ─────────────────────────────────────────────────

FILE_TOOLS = [
    {
        "name": "write_file",
        "description": "Write (or overwrite) a file inside the repo. Path is relative to repo root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path, e.g. src/main.py"},
                "content": {"type": "string", "description": "Full file content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from the repo. Returns the content as a string.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and directories at a given path (relative to repo root).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path, default '.'"},
            },
            "required": [],
        },
    },
    {
        "name": "report_unexpected_work",
        "description": (
            "Call this when you encounter work or issues that were NOT part of your original task. "
            "The system will route it: handle inline, notify another active agent, or create a new task."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "finding": {
                    "type": "string",
                    "description": "Detailed description of the unexpected work or issue found.",
                },
                "can_handle_inline": {
                    "type": "boolean",
                    "description": (
                        "True if you can fully address this within your current task scope "
                        "without significant scope creep. False if it's new standalone work."
                    ),
                },
                "inline_plan": {
                    "type": "string",
                    "description": "If can_handle_inline=true, briefly describe what you will do.",
                },
            },
            "required": ["finding", "can_handle_inline"],
        },
    },
    {
        "name": "finish",
        "description": "Signal that all code has been written and the task is complete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Brief description of what was implemented"},
            },
            "required": ["summary"],
        },
    },
]


class BaseAgent:
    agent_type: str = "base"

    def __init__(self, agent_db_id: int, project_id: int):
        self.agent_db_id = agent_db_id
        self.project_id = project_id
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        # injected by runner to push WS events
        self.broadcast_fn: Optional[Any] = None

    # ── Logging ───────────────────────────────────────────────────────────────

    def log(self, message: str, level: str = "info"):
        with SessionLocal() as session:
            add_log(session, self.agent_db_id, message, level)
        if self.broadcast_fn:
            asyncio.create_task(
                self.broadcast_fn({
                    "type": "log",
                    "agent_id": self.agent_db_id,
                    "level": level,
                    "message": message,
                    "timestamp": datetime.utcnow().isoformat(),
                })
            )

    def set_status(self, status: str, current_task_id: Optional[int] = None):
        with SessionLocal() as session:
            kwargs: dict = {"status": status}
            if current_task_id is not None:
                kwargs["current_task_id"] = current_task_id
            update_agent(session, self.agent_db_id, **kwargs)
        if self.broadcast_fn:
            asyncio.create_task(
                self.broadcast_fn({
                    "type": "agent_status",
                    "agent_id": self.agent_db_id,
                    "status": status,
                })
            )

    # ── Git helpers ───────────────────────────────────────────────────────────

    def _git(self, repo_path: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = f"CodingBuddy/{self.agent_type}"
        env["GIT_AUTHOR_EMAIL"] = "buddy@local"
        env["GIT_COMMITTER_NAME"] = f"CodingBuddy/{self.agent_type}"
        env["GIT_COMMITTER_EMAIL"] = "buddy@local"
        return subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True, text=True, env=env, check=check,
        )

    def clone_repo(self, clone_url: str, dest: Path) -> Path:
        if dest.exists():
            import shutil
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", clone_url, str(dest)], check=True, capture_output=True)
        self._git(dest, "config", "user.email", "buddy@local")
        self._git(dest, "config", "user.name", f"CodingBuddy/{self.agent_type}")
        return dest

    def create_branch(self, repo_path: Path, branch: str):
        self._git(repo_path, "fetch", "origin")
        self._git(repo_path, "checkout", "main")
        self._git(repo_path, "pull", "origin", "main")
        self._git(repo_path, "checkout", "-b", branch)

    def commit_and_push(self, repo_path: Path, branch: str, message: str):
        self._git(repo_path, "add", "-A")
        result = self._git(repo_path, "diff", "--cached", "--quiet")
        if result.returncode == 0:
            self.log("Nothing to commit — skipping push.")
            return
        self._git(repo_path, "commit", "-m", message, check=True)
        self._git(repo_path, "push", "origin", branch, check=True)

    def checkout_branch(self, repo_path: Path, branch: str):
        self._git(repo_path, "fetch", "origin")
        self._git(repo_path, "checkout", branch)
        self._git(repo_path, "pull", "origin", branch)

    # ── File tool handlers ────────────────────────────────────────────────────

    def _write_file(self, repo_path: Path, rel_path: str, content: str) -> str:
        target = (repo_path / rel_path).resolve()
        if not str(target).startswith(str(repo_path.resolve())):
            return "Error: path escapes repo root"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.log(f"  wrote {rel_path} ({len(content)} chars)")
        return f"OK: wrote {rel_path}"

    def _read_file(self, repo_path: Path, rel_path: str) -> str:
        target = (repo_path / rel_path).resolve()
        if not str(target).startswith(str(repo_path.resolve())):
            return "Error: path escapes repo root"
        if not target.exists():
            return f"Error: {rel_path} not found"
        return target.read_text(encoding="utf-8")

    def _list_files(self, repo_path: Path, rel_path: str = ".") -> str:
        target = (repo_path / rel_path).resolve()
        if not target.exists():
            return "Error: path not found"
        entries = []
        for p in sorted(target.iterdir()):
            entries.append(("DIR " if p.is_dir() else "    ") + p.name)
        return "\n".join(entries) or "(empty)"

    # ── Mid-task exception handling ───────────────────────────────────────────
    #
    # When an agent calls report_unexpected_work, the 3-step decision flow:
    #
    # 1. Can I handle inline? → agent said so; log and let it continue.
    # 2. Relevant to another active agent? → Claude relevance check → post message.
    # 3. New standalone work? → create a sub-task in the DB.

    async def _handle_unexpected_work(
        self,
        finding: str,
        can_handle_inline: bool,
        inline_plan: str,
    ) -> str:
        # ── Step 1: inline ────────────────────────────────────────────────────
        if can_handle_inline:
            self.log(f"[unexpected-work] handling inline: {inline_plan or finding[:80]}")
            return f"OK: handle inline — {inline_plan or 'proceed within current scope'}"

        self.log(f"[unexpected-work] finding: {finding[:120]}", level="warning")

        # ── Step 2: relevance check against active agents ─────────────────────
        with SessionLocal() as session:
            active = active_agents_with_tasks(session, self.project_id, exclude_agent_id=self.agent_db_id)
            # detach objects so they're usable outside session
            active_snapshot = [
                {"agent_id": a.id, "agent_type": a.type, "task": t.description}
                for a, t in active
            ]
            agent_id_map = {a.id: a for a, _ in active}

        notified: list[int] = []
        if active_snapshot:
            notified = await self._relevance_check(finding, active_snapshot)

        if notified:
            for aid in notified:
                with SessionLocal() as session:
                    post_agent_message(
                        session,
                        sender_agent_id=self.agent_db_id,
                        recipient_agent_id=aid,
                        subject=finding[:200],
                        body=finding,
                        kind="notification",
                    )
                self.log(f"[unexpected-work] notified agent #{aid} about relevant finding")
            return (
                f"Notified agent(s) {notified} about this finding. "
                "Continue your own task — they will handle it."
            )

        # ── Step 3: create new sub-task ───────────────────────────────────────
        task_type = self._infer_task_type(finding)
        with SessionLocal() as session:
            new_task = create_task(
                session,
                project_id=self.project_id,
                type=task_type,
                description=f"[Auto-created] {finding[:300]}",
            )
            new_task_id = new_task.id

        self.log(
            f"[unexpected-work] created new {task_type} task #{new_task_id} for standalone finding"
        )
        return (
            f"Created new task #{new_task_id} ({task_type}) for this work. "
            "It will be picked up by the assignment flow. Continue your current task."
        )

    async def _relevance_check(
        self,
        finding: str,
        active_agents: list[dict],
    ) -> list[int]:
        """Ask Claude which (if any) active agents are directly affected by this finding."""
        context = json.dumps(active_agents, indent=2)
        response = await self.client.messages.create(
            model=settings.claude_model,
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"An agent encountered this unexpected finding while working on a task:\n\n"
                        f"FINDING:\n{finding}\n\n"
                        f"ACTIVE AGENTS AND THEIR CURRENT TASKS:\n{context}\n\n"
                        "Which agent_ids (if any) are DIRECTLY affected by this finding — "
                        "meaning it would change or break something they are currently implementing? "
                        "Only include agents whose work would be materially impacted. "
                        "If no agents are directly affected, return an empty list.\n\n"
                        'Respond with ONLY a JSON object: {"relevant_agent_ids": [...]}'
                    ),
                }
            ],
        )

        try:
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            # extract JSON from response
            import re
            match = re.search(r'\{[^}]+\}', text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return [int(i) for i in data.get("relevant_agent_ids", [])]
        except Exception:
            pass
        return []

    def _infer_task_type(self, finding: str) -> str:
        """Heuristic: pick backend/frontend/tests based on keywords in finding."""
        lower = finding.lower()
        if any(w in lower for w in ["test", "spec", "coverage", "assert"]):
            return "tests"
        if any(w in lower for w in ["ui", "component", "css", "style", "react", "frontend", "html"]):
            return "frontend"
        return "backend"

    # ── API call with rate-limit backoff ──────────────────────────────────────

    async def _api_call_with_backoff(self, **kwargs):
        """Call the Anthropic API, retrying on 429 rate-limit errors with exponential backoff."""
        import anthropic as _anthropic
        delays = [15, 30, 60, 120]  # seconds between retries
        for attempt, delay in enumerate(delays + [None]):
            try:
                return await self.client.messages.create(**kwargs)
            except _anthropic.RateLimitError as e:
                if delay is None:
                    raise
                self.log(f"Rate limit hit — retrying in {delay}s (attempt {attempt + 1})", level="warning")
                await asyncio.sleep(delay)
            except _anthropic.APIStatusError as e:
                if e.status_code == 529:  # overloaded
                    wait = delays[min(attempt, len(delays) - 1)]
                    self.log(f"API overloaded — retrying in {wait}s", level="warning")
                    await asyncio.sleep(wait)
                else:
                    raise

    # ── Claude tool loop ──────────────────────────────────────────────────────

    async def run_tool_loop(
        self,
        repo_path: Path,
        system: str,
        user_prompt: str,
        extra_tools: Optional[list] = None,
    ) -> str:
        """Run the Claude tool loop, writing files until `finish` is called."""
        tools = FILE_TOOLS + (extra_tools or [])
        messages: list[dict] = [{"role": "user", "content": user_prompt}]
        summary = ""

        for iteration in range(40):
            # Small pause between iterations to reduce token/min rate
            if iteration > 0:
                await asyncio.sleep(3)

            response = await self._api_call_with_backoff(
                model=settings.claude_model,
                max_tokens=8096,
                system=system,
                tools=tools,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            done = False

            for block in response.content:
                if block.type != "tool_use":
                    continue
                name = block.name
                inp = block.input

                if name == "write_file":
                    result = self._write_file(repo_path, inp["path"], inp["content"])
                elif name == "read_file":
                    result = self._read_file(repo_path, inp["path"])
                elif name == "list_files":
                    result = self._list_files(repo_path, inp.get("path", "."))
                elif name == "report_unexpected_work":
                    # Run the 3-step decision flow asynchronously
                    result = await self._handle_unexpected_work(
                        finding=inp["finding"],
                        can_handle_inline=inp.get("can_handle_inline", False),
                        inline_plan=inp.get("inline_plan", ""),
                    )
                elif name == "finish":
                    summary = inp.get("summary", "")
                    result = "Task marked complete."
                    done = True
                else:
                    result = f"Unknown tool: {name}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

            if done or response.stop_reason == "end_turn":
                break

        return summary

    # ── Address review comments (called on worker agents by the runner) ────────

    async def do_address_comments(
        self,
        task: Task,
        repo_path: Path,
        stack: dict,
        comments: list,
    ) -> str:
        """Fix the code based on reviewer comments. Called on the worker agent."""
        import json as _json
        comments_text = _json.dumps(comments, indent=2)
        system = self.build_system_prompt(task, stack)
        prompt = f"""You are addressing code review feedback for task: {task.description}

REVIEW COMMENTS TO ADDRESS:
{comments_text}

IMPORTANT RULES:
- You MUST call `write_file` for every file that needs changes — even tiny fixes must be written.
- Do NOT just read files and call `finish` — that is wrong. You must write the fixes.
- Address every single comment. Do not skip any.
- After writing all fixes, call `finish` with a summary of what you changed and why.

Workflow:
1. Call `list_files` on "." to understand the project structure.
2. For each comment: call `read_file` on the relevant file, then call `write_file` with the fix applied.
3. Once all comments are addressed with actual file writes, call `finish`.
"""
        return await self.run_tool_loop(repo_path, system, prompt)

    # ── Subclass interface ────────────────────────────────────────────────────

    def build_system_prompt(self, task: Task, stack: dict) -> str:
        raise NotImplementedError

    def build_user_prompt(self, task: Task, stack: dict, extra_context: str = "") -> str:
        raise NotImplementedError

    async def do_work(self, task: Task, repo_path: Path, stack: dict) -> str:
        system = self.build_system_prompt(task, stack)
        prompt = self.build_user_prompt(task, stack)
        return await self.run_tool_loop(repo_path, system, prompt)
