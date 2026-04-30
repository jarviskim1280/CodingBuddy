import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from buddy.db.ops import (
    SessionLocal,
    create_project,
    get_project,
    list_projects,
    list_tasks,
    list_agents,
    update_project,
)
from buddy.github_client import get_github_client
from buddy.orchestrator import apply_plan_to_db, plan_project
from buddy.runner import ProjectRunner
from dashboard.api.ws import broadcast_event

router = APIRouter(prefix="/projects", tags=["projects"])


# ── Shared serialisers ────────────────────────────────────────────────────────

def _fmt_dt(dt) -> str:
    return dt.isoformat() if dt else ""


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    repo_url: str
    stack: dict
    status: str
    created_at: str


class TaskOut(BaseModel):
    id: int
    project_id: int
    type: str
    description: str
    status: str
    branch: str
    pr_url: str
    assigned_agent_id: int | None


class AgentOut(BaseModel):
    id: int
    project_id: int
    type: str
    status: str
    current_task_id: int | None
    last_heartbeat: str | None


class ProjectDetailOut(ProjectOut):
    tasks: list[TaskOut]
    agents: list[AgentOut]


# ── GET /projects/ ────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ProjectOut])
def get_projects():
    with SessionLocal() as session:
        projects = list_projects(session)
        return [
            ProjectOut(
                id=p.id,
                name=p.name,
                description=p.description,
                repo_url=p.repo_url or "",
                stack=p.stack or {},
                status=p.status,
                created_at=_fmt_dt(p.created_at),
            )
            for p in projects
        ]


# ── GET /projects/{id} ────────────────────────────────────────────────────────

@router.get("/{project_id}", response_model=ProjectDetailOut)
def get_project_detail(project_id: int):
    with SessionLocal() as session:
        project = get_project(session, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        tasks = list_tasks(session, project_id)
        agents = list_agents(session, project_id)

        return ProjectDetailOut(
            id=project.id,
            name=project.name,
            description=project.description,
            repo_url=project.repo_url or "",
            stack=project.stack or {},
            status=project.status,
            created_at=_fmt_dt(project.created_at),
            tasks=[
                TaskOut(
                    id=t.id,
                    project_id=t.project_id,
                    type=t.type,
                    description=t.description,
                    status=t.status,
                    branch=t.branch or "",
                    pr_url=t.pr_url or "",
                    assigned_agent_id=t.assigned_agent_id,
                )
                for t in tasks
            ],
            agents=[
                AgentOut(
                    id=a.id,
                    project_id=a.project_id,
                    type=a.type,
                    status=a.status,
                    current_task_id=a.current_task_id,
                    last_heartbeat=_fmt_dt(a.last_heartbeat),
                )
                for a in agents
            ],
        )


# ── POST /projects/ ───────────────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    description: str


async def _run_pipeline(project_id: int, plan: dict):
    """Background task: run agents and broadcast events."""
    runner = ProjectRunner(project_id, broadcast_fn=broadcast_event)
    try:
        await runner.run(plan)
    except Exception as exc:
        await broadcast_event({
            "type": "project_error",
            "project_id": project_id,
            "error": str(exc),
        })


@router.post("/", response_model=ProjectOut, status_code=201)
async def create_new_project(body: CreateProjectRequest):
    if not body.description.strip():
        raise HTTPException(status_code=400, detail="Description cannot be empty")

    # 1. Plan with Claude
    await broadcast_event({"type": "pipeline_status", "step": "planning", "message": "Planning project with Claude…"})
    plan = await plan_project(body.description)
    project_name = plan["project_name"]

    # 2. Create DB record
    with SessionLocal() as session:
        project = create_project(session, project_name, body.description)
        project_id = project.id

    # 3. Create repo
    await broadcast_event({"type": "pipeline_status", "step": "repo", "message": f"Creating repo: {project_name}…"})
    github = get_github_client()
    repo_url = github.create_repo(project_name, body.description)

    with SessionLocal() as session:
        update_project(session, project_id, repo_url=repo_url)

    # 4. Store tasks from plan
    apply_plan_to_db(type("P", (), {"id": project_id})(), plan)

    await broadcast_event({
        "type": "project_created",
        "project_id": project_id,
        "name": project_name,
        "message": f"Project '{project_name}' created — launching agents…",
    })

    # 5. Kick off agents as a non-blocking asyncio task on the running loop
    asyncio.create_task(_run_pipeline(project_id, plan))

    with SessionLocal() as session:
        project = get_project(session, project_id)
        return ProjectOut(
            id=project.id,
            name=project.name,
            description=project.description,
            repo_url=project.repo_url or "",
            stack=project.stack or {},
            status=project.status,
            created_at=_fmt_dt(project.created_at),
        )
