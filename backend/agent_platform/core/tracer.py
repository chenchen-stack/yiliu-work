"""Full-chain trace recording (DB persistence)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from agent_platform.logging_setup import get_logger
from agent_platform.models.trace import PlatformTraceORM, TraceRecord

logger = get_logger("tracer")


class SkillTracer:
    """Create and finalize TraceRecord rows in platform_traces."""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def start(
        self,
        *,
        skill_id: str,
        node_name: str,
        input_data: dict[str, Any],
        workflow_id: str | None = None,
        agent_session_id: str | None = None,
    ) -> TraceRecord:
        record = TraceRecord.new(
            skill_id=skill_id,
            node_name=node_name,
            input_data=input_data,
            workflow_id=workflow_id,
            agent_session_id=agent_session_id,
        )
        if self.db is not None:
            row = PlatformTraceORM(
                id=record.trace_id,
                workflow_id=workflow_id,
                agent_session_id=agent_session_id,
                skill_id=skill_id,
                node_name=node_name,
                input_json=input_data,
                output_json={},
                status="running",
                start_time=record.start_time or datetime.utcnow(),
            )
            self.db.add(row)
            self.db.commit()
        logger.info(
            "trace started",
            extra_fields={
                "trace_id": record.trace_id,
                "skill_id": skill_id,
                "node": node_name,
            },
        )
        return record

    def finish(
        self,
        record: TraceRecord,
        *,
        output: dict[str, Any],
        status: str = "success",
        error: str | None = None,
    ) -> TraceRecord:
        record.output = output
        record.status = status
        record.error = error
        record.end_time = datetime.utcnow()
        if record.start_time:
            delta = record.end_time - record.start_time
            record.duration_ms = int(delta.total_seconds() * 1000)

        if self.db is not None:
            row = self.db.get(PlatformTraceORM, record.trace_id)
            if row:
                row.output_json = output
                row.status = status
                row.error = error
                row.end_time = record.end_time
                row.duration_ms = record.duration_ms
                self.db.commit()

        logger.info(
            "trace finished",
            extra_fields={
                "trace_id": record.trace_id,
                "status": status,
                "duration_ms": record.duration_ms,
            },
        )
        return record

    def list_by_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        if self.db is None:
            return []
        rows = (
            self.db.query(PlatformTraceORM)
            .filter(PlatformTraceORM.workflow_id == workflow_id)
            .order_by(PlatformTraceORM.start_time)
            .all()
        )
        return [_row_to_dict(r) for r in rows]

    def get(self, trace_id: str) -> dict[str, Any] | None:
        if self.db is None:
            return None
        row = self.db.get(PlatformTraceORM, trace_id)
        return _row_to_dict(row) if row else None


def _row_to_dict(row: PlatformTraceORM) -> dict[str, Any]:
    return {
        "trace_id": row.id,
        "workflow_id": row.workflow_id,
        "agent_session_id": row.agent_session_id,
        "skill_id": row.skill_id,
        "node_name": row.node_name,
        "input": row.input_json,
        "output": row.output_json,
        "status": row.status,
        "error": row.error,
        "start_time": row.start_time.isoformat() if row.start_time else None,
        "end_time": row.end_time.isoformat() if row.end_time else None,
        "duration_ms": row.duration_ms,
    }
