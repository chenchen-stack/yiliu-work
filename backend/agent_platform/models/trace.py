"""Trace record dataclass and SQLAlchemy persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


@dataclass
class TraceRecord:
    """In-memory trace representation."""

    trace_id: str
    skill_id: str
    node_name: str
    input: dict[str, Any]
    output: dict[str, Any]
    status: str  # running | success | failed | waiting
    workflow_id: Optional[str] = None
    agent_session_id: Optional[str] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None

    @classmethod
    def new(
        cls,
        *,
        skill_id: str,
        node_name: str,
        input_data: dict[str, Any],
        workflow_id: str | None = None,
        agent_session_id: str | None = None,
    ) -> TraceRecord:
        return cls(
            trace_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            agent_session_id=agent_session_id,
            skill_id=skill_id,
            node_name=node_name,
            input=input_data,
            output={},
            status="running",
            start_time=datetime.utcnow(),
        )


class PlatformTraceORM(Base):
    """Persisted skill/workflow trace rows."""

    __tablename__ = "platform_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), index=True)
    agent_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    skill_id: Mapped[str] = mapped_column(String(80), index=True)
    node_name: Mapped[str] = mapped_column(String(80))
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="running")
    error: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class PlatformWorkflowORM(Base):
    """LangGraph workflow run persistence."""

    __tablename__ = "platform_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    graph_name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="running")  # running|paused|completed|failed
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    current_node: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
