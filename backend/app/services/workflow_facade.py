# File: app/services/workflow_facade.py
"""
Unified workflow entry — LangGraph (agent_platform) or legacy WorkflowEngine.

Set USE_LANGGRAPH_WORKFLOW=true in .env to route production tasks through LangGraph.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from agent_platform.config import platform_settings
from app.models import Task, User
from app.services.workflow_engine import WorkflowEngine


def use_langgraph_workflow() -> bool:
    return platform_settings.use_langgraph_workflow


async def execute_through_review(
    db: Session,
    task: Task,
    file_paths: dict[str, str],
    user: User | None = None,
) -> dict[str, Any]:
    """
    Run reconciliation pipeline until human review pause (or completion when no diffs).
    """
    if use_langgraph_workflow():
        from agent_platform.workflow.engine import PlatformWorkflowEngine

        engine = PlatformWorkflowEngine(db)
        result = await engine.start(task_id=task.id, file_paths=file_paths)
        return {"engine": "langgraph", **result}

    legacy = WorkflowEngine(db, task)
    await legacy.execute_through_review(file_paths)
    return {"engine": "legacy", "task_id": task.id, "status": task.status}


async def resume_after_review(
    db: Session,
    task: Task,
    reviewed_diffs: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Resume LangGraph after review approval; no-op for legacy-only tasks."""
    wf_id = (task.summary or {}).get("platform_workflow_id")
    if not wf_id or not use_langgraph_workflow():
        return None
    from agent_platform.workflow.engine import PlatformWorkflowEngine

    engine = PlatformWorkflowEngine(db)
    return await engine.resume(wf_id, reviewed_diffs=reviewed_diffs)
