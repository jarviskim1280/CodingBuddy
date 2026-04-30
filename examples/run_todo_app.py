"""
Demo: run the full CodingBuddy pipeline for a todo app.

Usage:
    cd /Users/nick/Projects/CodingBuddy
    uv sync
    python examples/run_todo_app.py
"""
import asyncio
import sys
from pathlib import Path

# make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from buddy.db import init_db
from buddy.db.ops import SessionLocal, create_project, update_project
from buddy.github_client import get_github_client
from buddy.orchestrator import apply_plan_to_db, plan_project
from buddy.runner import ProjectRunner
from buddy.config import settings


async def main():
    print("=" * 60)
    print("CodingBuddy — Demo: Todo App")
    print("=" * 60)

    if not settings.anthropic_api_key:
        print("\nERROR: ANTHROPIC_API_KEY not set.")
        print("Copy .env.example → .env and add your key.")
        sys.exit(1)

    if settings.mock_github:
        print("\nNote: GITHUB_TOKEN not set — using local mock git repos.")
    else:
        print(f"\nGitHub owner: {settings.github_owner}")

    init_db()

    description = "A simple todo app with task creation, completion, and deletion. Users can add tasks with a title and optional due date, mark them as complete, and delete them. The backend should expose a REST API and the frontend should be a clean single-page app."

    print(f"\nDescription: {description}\n")

    # ── Step 1: orchestrate ────────────────────────────────────────────────────
    print("Step 1/4: Planning project with Claude...")
    plan = await plan_project(description)
    project_name = plan["project_name"]
    stack = plan["tech_stack"]

    print(f"  Project name : {project_name}")
    print(f"  Stack        : {stack}")
    print(f"  Tasks planned: {len(plan['tasks'])}")
    for t in plan["tasks"]:
        print(f"    [{t['type']}] {t['description'][:70]}")

    # ── Step 2: create repo ────────────────────────────────────────────────────
    print("\nStep 2/4: Creating repository...")
    github = get_github_client()
    repo_url = github.create_repo(project_name, description)
    print(f"  Repo: {repo_url}")

    # ── Step 3: store in DB ────────────────────────────────────────────────────
    print("\nStep 3/4: Storing project in database...")
    with SessionLocal() as session:
        project = create_project(session, project_name, description)
        project_id = project.id
        update_project(session, project_id, repo_url=repo_url)

    tasks = apply_plan_to_db(
        type("P", (), {"id": project_id})(),
        plan,
    )
    print(f"  Project ID: {project_id}")
    print(f"  Tasks stored: {len(tasks)}")

    # ── Step 4: run agents ─────────────────────────────────────────────────────
    print(f"\nStep 4/4: Running agents (this takes a few minutes)...")
    print("  Dashboard will be available at http://localhost:8080 once running.\n")

    runner = ProjectRunner(project_id, broadcast_fn=None)
    await runner.run(plan)

    print("\n" + "=" * 60)
    print(f"Done! Project '{project_name}' generated.")
    print(f"  Repo : {repo_url}")
    print(f"  DB ID: {project_id}")
    print("\nTo view logs and status:")
    print("  buddy dashboard")
    print(f"  open http://localhost:8080/projects/{project_id}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
