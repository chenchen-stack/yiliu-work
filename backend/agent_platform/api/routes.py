# File: agent_platform/api/routes.py
"""Agent platform HTTP routes — Workflow / Agent / Skills (LangGraph-backed)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agent_platform.agent.agent_engine import PlatformAgentEngine
from agent_platform.agent.agent_loop import AgentLoop
from agent_platform.config import platform_settings
from agent_platform.core.registry import skill_registry
from agent_platform.exceptions import PlatformError, error_response
from agent_platform.workflow.engine import PlatformWorkflowEngine
from app.database import get_db

router = APIRouter(tags=["agent-platform"])


class SkillExecuteBody(BaseModel):
    skill_id: str
    input_params: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunBody(BaseModel):
    task_id: str
    file_paths: dict[str, str] | None = None
    graph_name: str = "fangtai_reconciliation"


class WorkflowResumeBody(BaseModel):
    reviewed_diffs: list[dict[str, Any]] = Field(default_factory=list)


class AgentChatBody(BaseModel):
    message: str
    context: dict[str, Any] | None = None
    workflow_task_id: str | None = None
    stream: bool = False


def _handle_platform_error(exc: PlatformError) -> HTTPException:
    return HTTPException(status_code=400, detail=error_response(exc))


@router.get("/skills")
def list_skills(
    category: str | None = None,
    skill_type: str | None = None,
):
    if category or skill_type:
        items = skill_registry.query(category=category, skill_type=skill_type)
        from agent_platform.models.skill import skill_meta_to_dict

        return {"items": [skill_meta_to_dict(m, include_execution=False) for m in items]}
    return {"items": skill_registry.to_api_list()}


@router.get("/skills/{skill_id}")
def get_skill(skill_id: str):
    try:
        return skill_registry.to_api_detail(skill_id)
    except PlatformError as exc:
        raise _handle_platform_error(exc) from exc


@router.post("/admin/skills/reload")
def reload_skills():
    count = skill_registry.reload()
    return {"reloaded": count}


@router.post("/skills/execute")
async def execute_skill(body: SkillExecuteBody, db: Session = Depends(get_db)):
    from agent_platform.core.executor import SkillExecutor
    from agent_platform.exceptions import SkillExecutionFailed, SkillNotFoundError

    try:
        executor = SkillExecutor(db)
        return await executor.run(body.skill_id, body.input_params)
    except (SkillNotFoundError, SkillExecutionFailed) as exc:
        raise _handle_platform_error(exc) from exc


@router.post("/workflow/run")
async def run_workflow(body: WorkflowRunBody, db: Session = Depends(get_db)):
    engine = PlatformWorkflowEngine(db)
    try:
        return await engine.start(
            task_id=body.task_id,
            file_paths=body.file_paths,
            graph_name=body.graph_name,
        )
    except PlatformError as exc:
        raise _handle_platform_error(exc) from exc


@router.get("/workflow/{workflow_id}")
def get_workflow(workflow_id: str, db: Session = Depends(get_db)):
    engine = PlatformWorkflowEngine(db)
    try:
        return engine.get_status(workflow_id)
    except PlatformError as exc:
        raise _handle_platform_error(exc) from exc


@router.get("/workflow/{workflow_id}/status")
async def get_workflow_checkpoint_status(workflow_id: str, db: Session = Depends(get_db)):
    engine = PlatformWorkflowEngine(db)
    try:
        values = await engine.get_checkpoint_state(workflow_id)
        return {"workflow_id": workflow_id, "values": values}
    except PlatformError as exc:
        raise _handle_platform_error(exc) from exc


@router.get("/workflow/{workflow_id}/trace")
async def get_workflow_trace(workflow_id: str, db: Session = Depends(get_db)):
    engine = PlatformWorkflowEngine(db)
    try:
        trace = await engine.get_trace(workflow_id)
        return {"workflow_id": workflow_id, "trace": trace}
    except PlatformError as exc:
        raise _handle_platform_error(exc) from exc


@router.post("/workflow/{workflow_id}/resume")
async def resume_workflow(
    workflow_id: str,
    body: WorkflowResumeBody | None = None,
    db: Session = Depends(get_db),
):
    engine = PlatformWorkflowEngine(db)
    try:
        reviewed = body.reviewed_diffs if body else []
        return await engine.resume(workflow_id, reviewed_diffs=reviewed)
    except PlatformError as exc:
        raise _handle_platform_error(exc) from exc


@router.post("/agent/chat")
async def agent_chat(body: AgentChatBody, db: Session = Depends(get_db)):
    if body.stream:
        engine = PlatformAgentEngine(db)

        async def _gen():
            async for chunk in engine.stream_events(
                body.message,
                context=body.context,
                workflow_task_id=body.workflow_task_id,
            ):
                yield chunk

        return StreamingResponse(_gen(), media_type="text/event-stream")

    if platform_settings.use_langgraph_agent:
        engine = PlatformAgentEngine(db)
        return await engine.run(body.message, context=body.context)

    loop = AgentLoop(db)
    return await loop.run(body.message, context=body.context)


@router.get("/platform/config")
def platform_config():
    return {
        "use_langgraph_workflow": platform_settings.use_langgraph_workflow,
        "use_langgraph_agent": platform_settings.use_langgraph_agent,
        "workflow_default_graph": platform_settings.workflow_default_graph,
        "skills_dir": str(platform_settings.skills_dir),
    }
