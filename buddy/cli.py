"""CodingBuddy CLI — buddy new / buddy dashboard / buddy list / buddy status."""
import asyncio
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="CodingBuddy — AI-powered side project generator")
console = Console()


def _ensure_db():
    from buddy.db import init_db
    init_db()


@app.command()
def new(
    description: str = typer.Argument(..., help='Project description, e.g. "build a todo app"'),
    no_dashboard: bool = typer.Option(False, "--no-dashboard", help="Don't open dashboard"),
):
    """Spin up a new AI-generated side project."""
    _ensure_db()
    asyncio.run(_new_project(description, no_dashboard))


async def _new_project(description: str, no_dashboard: bool):
    from buddy.config import settings
    from buddy.db.ops import SessionLocal, create_project, update_project
    from buddy.github_client import get_github_client
    from buddy.orchestrator import apply_plan_to_db, plan_project, _slugify
    from buddy.runner import ProjectRunner

    if not settings.anthropic_api_key:
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY is not set. Add it to .env")
        raise typer.Exit(1)

    console.print(f"\n[bold cyan]CodingBuddy[/bold cyan] — planning: [italic]{description}[/italic]\n")

    # 1. Call orchestrator to plan
    console.print("🤔 Analyzing project description...")
    plan = await plan_project(description)
    project_name = plan["project_name"]
    stack = plan["tech_stack"]

    console.print(f"📋 Project: [bold]{project_name}[/bold]")
    console.print(f"   Stack: {stack['backend']} + {stack['frontend']} + {stack['database']}")
    console.print(f"   Tasks: {len(plan['tasks'])} agent tasks planned")

    # 2. Create project in DB
    with SessionLocal() as session:
        project = create_project(session, project_name, description)
        project_id = project.id

    # 3. Create GitHub repo
    github = get_github_client()
    if settings.mock_github:
        console.print("⚠️  No GITHUB_TOKEN — using local mock git repos")
    else:
        console.print(f"🐙 Creating GitHub repo: {settings.github_owner}/{project_name}")

    repo_url = github.create_repo(project_name, description)

    with SessionLocal() as session:
        update_project(session, project_id, repo_url=repo_url)

    console.print(f"   Repo: {repo_url}")

    # 4. Store tasks from plan
    tasks = apply_plan_to_db(
        type("Obj", (), {"id": project_id})(),  # minimal duck-typed Project
        plan,
    )

    console.print(f"\n🚀 Launching {len(tasks)} agents...\n")

    # 5. Run agents (optionally open dashboard first)
    if not no_dashboard:
        _start_dashboard_background(settings.dashboard_port)

    runner = ProjectRunner(project_id, broadcast_fn=None)

    # Refresh project with repo_url
    with SessionLocal() as session:
        from buddy.db.ops import get_project
        project_full = get_project(session, project_id)
        session.expunge(project_full)

    try:
        await runner.run(plan)
        console.print(f"\n✅ [green]Project '{project_name}' complete![/green]")
        console.print(f"   Dashboard: http://localhost:{settings.dashboard_port}/projects/{project_id}")
    except Exception as exc:
        console.print(f"\n[red]Error running agents:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def dashboard(
    port: int = typer.Option(None, "--port", "-p", help="Dashboard port"),
):
    """Start the CodingBuddy dashboard (FastAPI + React)."""
    _ensure_db()
    from buddy.config import settings
    p = port or settings.dashboard_port
    console.print(f"[bold cyan]Starting CodingBuddy dashboard on port {p}...[/bold cyan]")
    console.print(f"Open: http://localhost:{p}\n")

    subprocess.run(
        [sys.executable, "-m", "uvicorn", "dashboard.api.main:app", "--host", "0.0.0.0", "--port", str(p), "--reload"],
        check=True,
    )


@app.command("list")
def list_projects():
    """List all projects."""
    _ensure_db()
    from buddy.db.ops import SessionLocal, list_projects as db_list
    with SessionLocal() as session:
        projects = db_list(session)

    if not projects:
        console.print("No projects yet. Run [bold]buddy new \"description\"[/bold] to create one.")
        return

    table = Table(title="CodingBuddy Projects")
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Description")
    table.add_column("Created")

    STATUS_COLORS = {"planning": "yellow", "active": "cyan", "done": "green", "failed": "red"}
    for p in projects:
        color = STATUS_COLORS.get(p.status, "white")
        table.add_row(
            str(p.id),
            p.name,
            f"[{color}]{p.status}[/{color}]",
            p.description[:60],
            p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "",
        )

    console.print(table)


@app.command()
def status(project_id: int = typer.Argument(..., help="Project ID")):
    """Show detailed status of a project."""
    _ensure_db()
    from buddy.db.ops import SessionLocal, get_project, list_tasks, list_agents
    with SessionLocal() as session:
        project = get_project(session, project_id)
        if not project:
            console.print(f"[red]Project {project_id} not found.[/red]")
            raise typer.Exit(1)

        tasks = list_tasks(session, project_id)
        agents = list_agents(session, project_id)

    console.print(f"\n[bold]{project.name}[/bold] — {project.status}")
    console.print(f"  {project.description}\n")

    if tasks:
        task_table = Table(title="Tasks")
        task_table.add_column("ID")
        task_table.add_column("Type")
        task_table.add_column("Status")
        task_table.add_column("Branch")
        task_table.add_column("PR")
        STATUS_COLORS = {"pending": "yellow", "in_progress": "cyan", "review": "blue", "done": "green", "failed": "red"}
        for t in tasks:
            color = STATUS_COLORS.get(t.status, "white")
            task_table.add_row(
                str(t.id), t.type,
                f"[{color}]{t.status}[/{color}]",
                t.branch or "-",
                t.pr_url or "-",
            )
        console.print(task_table)

    if agents:
        agent_table = Table(title="Agents")
        agent_table.add_column("ID")
        agent_table.add_column("Type")
        agent_table.add_column("Status")
        agent_table.add_column("Last Heartbeat")
        for a in agents:
            agent_table.add_row(
                str(a.id), a.type, a.status,
                a.last_heartbeat.strftime("%H:%M:%S") if a.last_heartbeat else "-",
            )
        console.print(agent_table)


def _start_dashboard_background(port: int):
    """Fire-and-forget dashboard start in background process."""
    subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "dashboard.api.main:app",
            "--host", "0.0.0.0",
            "--port", str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    app()
