import json
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship

from buddy.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    repo_url = Column(String(500), default="")
    stack = Column(JSON, default=dict)
    status = Column(String(50), default="planning")  # planning/active/done/failed
    created_at = Column(DateTime, default=datetime.utcnow)

    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    agents = relationship("Agent", back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    type = Column(String(50), nullable=False)  # backend/frontend/tests/review
    description = Column(Text, nullable=False)
    status = Column(String(50), default="pending")  # pending/in_progress/review/done/failed
    branch = Column(String(200), default="")
    pr_url = Column(String(500), default="")
    assigned_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="tasks")
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id])
    reviews = relationship("PRReview", back_populates="task", cascade="all, delete-orphan")


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    type = Column(String(50), nullable=False)  # backend/frontend/tests/reviewer
    status = Column(String(50), default="idle")  # idle/working/waiting/done/failed
    current_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="agents")
    current_task = relationship("Task", foreign_keys=[current_task_id])
    logs = relationship("AgentLog", back_populates="agent", cascade="all, delete-orphan")


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    level = Column(String(20), default="info")  # info/warning/error/debug
    message = Column(Text, nullable=False)

    agent = relationship("Agent", back_populates="logs")


class PRReview(Base):
    __tablename__ = "pr_reviews"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    pr_url = Column(String(500), default="")
    round_number = Column(Integer, default=1)
    status = Column(String(50), default="pending")  # pending/changes_requested/approved
    comments = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="reviews")


class AgentMessage(Base):
    """Inter-agent message queue for mid-task notifications."""
    __tablename__ = "agent_messages"

    id = Column(Integer, primary_key=True, index=True)
    recipient_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    sender_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    # "notification" (heads-up) or "new_task" (spawned sub-task reference)
    kind = Column(String(50), default="notification")
    subject = Column(String(500), default="")  # one-liner
    body = Column(Text, default="")            # full finding description
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    recipient = relationship("Agent", foreign_keys=[recipient_agent_id])
    sender = relationship("Agent", foreign_keys=[sender_agent_id])
