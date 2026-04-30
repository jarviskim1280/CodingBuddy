"""Orchestrator agent — analyzes project description and creates a plan."""
import json
import re

import anthropic

from buddy.config import settings
from buddy.db.models import Project
from buddy.db.ops import SessionLocal, create_task, update_project

PLAN_TOOLS = [
    {
        "name": "create_project_plan",
        "description": "Create a structured project plan with tech stack and task breakdown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Short slug-friendly project name (lowercase, hyphens)",
                },
                "tech_stack": {
                    "type": "object",
                    "description": "Technologies to use",
                    "properties": {
                        "frontend": {"type": "string", "description": "e.g. React, Vue, None"},
                        "backend": {"type": "string", "description": "e.g. FastAPI, Express"},
                        "database": {"type": "string", "description": "e.g. SQLite, PostgreSQL"},
                        "other": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["frontend", "backend", "database"],
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["backend", "frontend", "tests"],
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed task description for the worker agent",
                            },
                        },
                        "required": ["type", "description"],
                    },
                },
            },
            "required": ["project_name", "tech_stack", "tasks"],
        },
    },
]

ORCHESTRATOR_SYSTEM = """You are a software architect. Given a project description, produce:
1. A clean project name (snake_case or kebab-case).
2. The best tech stack for the project (default to React frontend + FastAPI backend + SQLite unless something else clearly fits better).
3. A list of tasks for each agent type:
   - backend: implement all backend API endpoints, database models, business logic
   - frontend: implement the full UI connected to the backend API
   - tests: write tests for backend and frontend

Keep tasks descriptive enough that a developer reading just the task description knows exactly what to build.
Always call `create_project_plan` — do not respond with plain text.
"""


async def plan_project(description: str) -> dict:
    """Call Claude to analyze description and return a structured plan."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    response = await client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=ORCHESTRATOR_SYSTEM,
        tools=PLAN_TOOLS,
        tool_choice={"type": "any"},
        messages=[
            {
                "role": "user",
                "content": f"Plan this project: {description}",
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "create_project_plan":
            return block.input

    # fallback if somehow no tool call
    return {
        "project_name": _slugify(description[:40]),
        "tech_stack": {"frontend": "React", "backend": "FastAPI", "database": "SQLite", "other": []},
        "tasks": [
            {"type": "backend", "description": f"Implement backend for: {description}"},
            {"type": "frontend", "description": f"Implement frontend for: {description}"},
            {"type": "tests", "description": f"Write tests for: {description}"},
        ],
    }


def apply_plan_to_db(project: Project, plan: dict) -> list:
    """Store tasks from the plan into the DB and return them."""
    with SessionLocal() as session:
        tasks = []
        for task_def in plan.get("tasks", []):
            task = create_task(
                session,
                project_id=project.id,
                type=task_def["type"],
                description=task_def["description"],
            )
            tasks.append(task)

        update_project(
            session,
            project.id,
            stack=plan.get("tech_stack", {}),
            status="active",
        )

    return tasks


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:50]
