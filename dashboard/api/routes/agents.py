from fastapi import APIRouter
from pydantic import BaseModel

from buddy.db.ops import SessionLocal, list_agents, get_logs

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentOut(BaseModel):
    id: int
    project_id: int
    type: str
    status: str
    current_task_id: int | None
    last_heartbeat: str | None


class LogOut(BaseModel):
    id: int
    agent_id: int
    timestamp: str
    level: str
    message: str


def _fmt_dt(dt) -> str:
    return dt.isoformat() if dt else ""


@router.get("/", response_model=list[AgentOut])
def get_agents(project_id: int | None = None):
    with SessionLocal() as session:
        agents = list_agents(session, project_id)
        return [
            AgentOut(
                id=a.id,
                project_id=a.project_id,
                type=a.type,
                status=a.status,
                current_task_id=a.current_task_id,
                last_heartbeat=_fmt_dt(a.last_heartbeat),
            )
            for a in agents
        ]


@router.get("/logs", response_model=list[LogOut])
def get_agent_logs(agent_id: int, limit: int = 200):
    with SessionLocal() as session:
        logs = get_logs(session, agent_id, limit)
        return [
            LogOut(
                id=l.id,
                agent_id=l.agent_id,
                timestamp=_fmt_dt(l.timestamp),
                level=l.level,
                message=l.message,
            )
            for l in reversed(logs)
        ]
