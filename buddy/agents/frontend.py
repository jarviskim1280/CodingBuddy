from pathlib import Path

from buddy.agents.base import BaseAgent
from buddy.db.models import Task


class FrontendAgent(BaseAgent):
    agent_type = "frontend"

    def build_system_prompt(self, task: Task, stack: dict) -> str:
        frontend = stack.get("frontend", "React")
        return f"""You are a senior frontend engineer implementing a {frontend} application.

Rules:
- Write clean, modern {frontend} code with TypeScript.
- Use Tailwind CSS for styling (dark-friendly, responsive).
- Keep components small and focused.
- Put all frontend code in a `frontend/` directory.
- Include package.json with all dependencies.
- Always call `finish` when done.
- If you encounter unexpected work (API shape mismatch, missing backend endpoint,
  conflicting state, security concern), call `report_unexpected_work`.
  Use can_handle_inline=true only for trivial UI-only additions.
"""

    def build_user_prompt(self, task: Task, stack: dict, extra_context: str = "") -> str:
        frontend = stack.get("frontend", "React")
        backend_url = "http://localhost:8000"
        return f"""Implement the following frontend task using {frontend} + TypeScript + Tailwind:

TASK: {task.description}

Project context:
- Stack: {stack}
- Backend API base URL: {backend_url}
{extra_context}

Instructions:
1. Call `list_files` on "." to see what already exists.
2. Read any relevant existing files first.
3. Implement the full UI: components, pages, API hooks, routing.
4. Create a `frontend/package.json` with all needed dependencies (react, react-dom, vite, tailwindcss, etc.).
5. Create a `frontend/vite.config.ts` with a proxy for the backend API.
6. Create `frontend/index.html` as the Vite entry point.
7. Put source under `frontend/src/`.
8. After writing all files, call `finish` with a brief summary.
"""
