from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from buddy.db.ops import (
    SessionLocal,
    get_project,
    list_projects,
    list_tasks,
    list_agents,
)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    repo_url: str
    stack: dict
    status: str
    created_at: str

    class Config:
        from_attributes = True


class TaskOut(BaseModel):
    id: int
    project_id: int
    type: str
    description: str
    status: str
    branch: str
    pr_url: str
    assigned_agent_id: int | None

    class Config:
        from_attributes = True


class AgentOut(BaseModel):
    id: int
    project_id: int
    type: str
    status: str
    current_task_id: int | None
    last_heartbeat: str | None

    class Config:
        from_attributes = True


class ProjectDetailOut(ProjectOut):
    tasks: list[TaskOut]
    agents: list[AgentOut]


def _fmt_dt(dt) -> str:
    return dt.isoformat() if dt else ""


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
