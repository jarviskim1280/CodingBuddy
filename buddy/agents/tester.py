from pathlib import Path

from buddy.agents.base import BaseAgent
from buddy.db.models import Task


class TesterAgent(BaseAgent):
    agent_type = "tester"

    def build_system_prompt(self, task: Task, stack: dict) -> str:
        backend = stack.get("backend", "FastAPI")
        return f"""You are a senior QA engineer writing tests for a {backend} application.

Rules:
- Write pytest tests for the backend (use httpx.AsyncClient for FastAPI).
- Write React Testing Library tests for the frontend.
- Aim for high coverage of core business logic.
- Put backend tests in `tests/backend/`, frontend tests in `tests/frontend/`.
- Always call `finish` when done.
- If you find a bug, missing feature, or untestable code that the implementation agent
  should fix, call `report_unexpected_work` (can_handle_inline=false) — don't silently skip it.
"""

    def build_user_prompt(self, task: Task, stack: dict, extra_context: str = "") -> str:
        return f"""Write comprehensive tests for the following:

TASK: {task.description}

Project context:
- Stack: {stack}
{extra_context}

Instructions:
1. Call `list_files` on "." to understand the project structure.
2. Read the backend source files to understand what to test.
3. Read the frontend source files to understand what to test.
4. Write backend pytest tests covering all API endpoints and business logic.
5. Write frontend React Testing Library tests for key components.
6. Add a `tests/requirements.txt` if needed.
7. Call `finish` when done with a summary of what you tested.
"""
