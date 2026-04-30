from fastapi import APIRouter
from pydantic import BaseModel

from buddy.db.ops import SessionLocal, list_tasks

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskOut(BaseModel):
    id: int
    project_id: int
    type: str
    description: str
    status: str
    branch: str
    pr_url: str
    assigned_agent_id: int | None


@router.get("/")
def get_tasks(project_id: int):
    with SessionLocal() as session:
        tasks = list_tasks(session, project_id)
        return [
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
        ]
