from pathlib import Path

from buddy.agents.base import BaseAgent
from buddy.db.models import Task


class BackendAgent(BaseAgent):
    agent_type = "backend"

    def build_system_prompt(self, task: Task, stack: dict) -> str:
        backend = stack.get("backend", "FastAPI")
        db = stack.get("database", "SQLite")
        return f"""You are a senior backend engineer implementing a {backend} + {db} application.

Rules:
- Write production-quality, well-structured code.
- Use {backend} conventions and best practices.
- Include a requirements.txt with all dependencies pinned.
- Create a README section for running the backend.
- Always call `finish` when done — never leave work half-done.
- Do NOT write tests (the tester agent handles that).
- Structure: put all backend code in a `backend/` directory.
- If you encounter something unexpected (e.g. a missing dependency, a conflicting interface,
  security issue, or work outside your task scope), call `report_unexpected_work` immediately.
  Set can_handle_inline=true only if it's a trivial addition within your task scope.
"""

    def build_user_prompt(self, task: Task, stack: dict, extra_context: str = "") -> str:
        backend = stack.get("backend", "FastAPI")
        db = stack.get("database", "SQLite")
        return f"""Implement the following backend task for a {backend} + {db} application:

TASK: {task.description}

Project context:
- Stack: {stack}
{extra_context}

Instructions:
1. First call `list_files` on "." to see what already exists.
2. Read any relevant existing files before writing.
3. Implement the full backend: models, routes, services, database setup.
4. Add a `backend/main.py` entry point that starts the server.
5. Write a `backend/requirements.txt`.
6. After writing all files, call `finish` with a brief summary.
"""
