"""CRUD helpers for all DB models."""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from buddy.db.models import Agent, AgentLog, AgentMessage, PRReview, Project, Task, engine
from sqlalchemy.orm import sessionmaker

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Session:
    return SessionLocal()


# ── Projects ──────────────────────────────────────────────────────────────────

def create_project(session: Session, name: str, description: str) -> Project:
    project = Project(name=name, description=description)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def get_project(session: Session, project_id: int) -> Optional[Project]:
    return session.get(Project, project_id)


def list_projects(session: Session) -> list[Project]:
    return session.query(Project).order_by(Project.created_at.desc()).all()


def update_project(session: Session, project_id: int, **kwargs) -> Optional[Project]:
    project = session.get(Project, project_id)
    if project:
        for k, v in kwargs.items():
            setattr(project, k, v)
        session.commit()
        session.refresh(project)
    return project


# ── Tasks ─────────────────────────────────────────────────────────────────────

def create_task(
    session: Session,
    project_id: int,
    type: str,
    description: str,
) -> Task:
    task = Task(project_id=project_id, type=type, description=description)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def get_task(session: Session, task_id: int) -> Optional[Task]:
    return session.get(Task, task_id)


def list_tasks(session: Session, project_id: int) -> list[Task]:
    return (
        session.query(Task)
        .filter(Task.project_id == project_id)
        .order_by(Task.id)
        .all()
    )


def update_task(session: Session, task_id: int, **kwargs) -> Optional[Task]:
    task = session.get(Task, task_id)
    if task:
        kwargs["updated_at"] = datetime.utcnow()
        for k, v in kwargs.items():
            setattr(task, k, v)
        session.commit()
        session.refresh(task)
    return task


def next_pending_task(session: Session, project_id: int, task_type: str) -> Optional[Task]:
    return (
        session.query(Task)
        .filter(
            Task.project_id == project_id,
            Task.type == task_type,
            Task.status == "pending",
        )
        .first()
    )


# ── Agents ────────────────────────────────────────────────────────────────────

def create_agent(session: Session, project_id: int, agent_type: str) -> Agent:
    agent = Agent(project_id=project_id, type=agent_type)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


def get_agent(session: Session, agent_id: int) -> Optional[Agent]:
    return session.get(Agent, agent_id)


def list_agents(session: Session, project_id: Optional[int] = None) -> list[Agent]:
    q = session.query(Agent)
    if project_id:
        q = q.filter(Agent.project_id == project_id)
    return q.order_by(Agent.id).all()


def update_agent(session: Session, agent_id: int, **kwargs) -> Optional[Agent]:
    agent = session.get(Agent, agent_id)
    if agent:
        kwargs["last_heartbeat"] = datetime.utcnow()
        for k, v in kwargs.items():
            setattr(agent, k, v)
        session.commit()
        session.refresh(agent)
    return agent


# ── AgentLogs ─────────────────────────────────────────────────────────────────

def add_log(
    session: Session,
    agent_id: int,
    message: str,
    level: str = "info",
) -> AgentLog:
    log = AgentLog(agent_id=agent_id, message=message, level=level)
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


def get_logs(
    session: Session,
    agent_id: int,
    limit: int = 200,
) -> list[AgentLog]:
    return (
        session.query(AgentLog)
        .filter(AgentLog.agent_id == agent_id)
        .order_by(AgentLog.timestamp.desc())
        .limit(limit)
        .all()
    )


# ── PRReview ──────────────────────────────────────────────────────────────────

def create_review(
    session: Session,
    task_id: int,
    pr_url: str,
    round_number: int,
) -> PRReview:
    review = PRReview(task_id=task_id, pr_url=pr_url, round_number=round_number)
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def update_review(session: Session, review_id: int, **kwargs) -> Optional[PRReview]:
    review = session.get(PRReview, review_id)
    if review:
        for k, v in kwargs.items():
            setattr(review, k, v)
        session.commit()
        session.refresh(review)
    return review


def latest_review(session: Session, task_id: int) -> Optional[PRReview]:
    return (
        session.query(PRReview)
        .filter(PRReview.task_id == task_id)
        .order_by(PRReview.round_number.desc())
        .first()
    )


# ── AgentMessages ──────────────────────────────────────────────────────────────

def post_agent_message(
    session: Session,
    sender_agent_id: int,
    recipient_agent_id: int,
    subject: str,
    body: str,
    kind: str = "notification",
) -> AgentMessage:
    msg = AgentMessage(
        sender_agent_id=sender_agent_id,
        recipient_agent_id=recipient_agent_id,
        kind=kind,
        subject=subject,
        body=body,
    )
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


def get_unread_messages(session: Session, agent_id: int) -> list[AgentMessage]:
    return (
        session.query(AgentMessage)
        .filter(AgentMessage.recipient_agent_id == agent_id, AgentMessage.read == False)
        .order_by(AgentMessage.created_at)
        .all()
    )


def mark_messages_read(session: Session, agent_id: int) -> None:
    session.query(AgentMessage).filter(
        AgentMessage.recipient_agent_id == agent_id, AgentMessage.read == False
    ).update({"read": True})
    session.commit()


def active_agents_with_tasks(
    session: Session,
    project_id: int,
    exclude_agent_id: Optional[int] = None,
) -> list[tuple[Agent, Task]]:
    """Return (Agent, Task) pairs for every in-progress agent that has a current task."""
    rows = (
        session.query(Agent, Task)
        .join(Task, Agent.current_task_id == Task.id)
        .filter(
            Agent.project_id == project_id,
            Agent.status.in_(["working", "waiting"]),
        )
    )
    if exclude_agent_id:
        rows = rows.filter(Agent.id != exclude_agent_id)
    return rows.all()
