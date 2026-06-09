"""Agent 配置与运行统计 API（前台智能体中心 + 管理后台）。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.database import get_db
from app.models import AgentConfig, AgentRun, Conversation, User, UserRole
from app.services.agent_config_service import (
    agent_to_dict,
    create_agent,
    list_agents_for_user,
    resolve_agent,
    update_agent,
)
from app.services.audit_service import log_audit

router = APIRouter(prefix="/agents", tags=["agents"])
admin_router = APIRouter(prefix="/admin/agents", tags=["admin-agents"])


class AgentConfigOut(BaseModel):
    id: str
    name: str
    code: str
    description: str = ""
    persona: str = ""
    allowed_skill_ids: list[str] = []
    knowledge_scope: str | None = None
    knowledge_base_ids: list[str] = []
    data_source_scope: list[str] = []
    linked_workflow_id: str | None = None
    output_format: str = "natural"
    prompt_template: str | None = None
    model_config_json: dict = {}
    model_route: dict = {}
    fallback_strategy: str = "ask_user"
    scope: str = "team_published"
    owner_id: str | None = None
    status: str = "published"
    version: int = 1
    is_template: bool = False
    visibility: str = "team_published"
    allowed_roles: list[str] = []
    version_history: list[dict] = Field(default_factory=list)
    avatar_id: str = "anime-01"
    asset_mounts: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AgentConfigCreate(BaseModel):
    name: str
    code: str | None = None
    description: str = ""
    persona: str = ""
    allowed_skill_ids: list[str] = Field(default_factory=lambda: ["skill-anomaly_explain", "skill-query_tasks"])
    knowledge_scope: str | None = "revenue_reconciliation"
    knowledge_base_ids: list[str] = Field(default_factory=list)
    data_source_scope: list[str] = Field(default_factory=list)
    linked_workflow_id: str | None = None
    output_format: str = "natural"
    prompt_template: str | None = None
    model_config_json: dict = Field(default_factory=dict)
    model_route: dict = Field(default_factory=dict)
    fallback_strategy: str = "ask_user"
    visibility: str = "team_published"
    allowed_roles: list[str] = Field(default_factory=list)
    scope: str = "personal"
    is_template: bool = False


class AgentConfigUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    persona: str | None = None
    allowed_skill_ids: list[str] | None = None
    knowledge_scope: str | None = None
    knowledge_base_ids: list[str] | None = None
    data_source_scope: list[str] | None = None
    linked_workflow_id: str | None = None
    output_format: str | None = None
    prompt_template: str | None = None
    model_config_json: dict | None = None
    model_route: dict | None = None
    fallback_strategy: str | None = None
    visibility: str | None = None
    allowed_roles: list[str] | None = None
    scope: str | None = None
    status: str | None = None
    publish: bool = False


class AgentLifecycleAction(BaseModel):
    action: str = Field(..., description="publish | offline | submit_review | rollback | duplicate")
    gray: bool = False
    new_name: str | None = None


class AgentStatsOut(BaseModel):
    total_conversations: int
    total_runs: int
    runs_last_7d: int
    top_intents: list[dict]
    top_agents: list[dict]
    ops_metrics: dict | None = None


def _out(agent: AgentConfig, db: Session) -> AgentConfigOut:
    return AgentConfigOut.model_validate(agent_to_dict(agent, db))


@router.get("", response_model=list[AgentConfigOut])
def list_my_agents(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return [_out(a, db) for a in list_agents_for_user(db, user)]


@router.get("/{agent_id}", response_model=AgentConfigOut)
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = resolve_agent(db, agent_id=agent_id, user=user)
    return _out(agent, db)


@router.post("", response_model=AgentConfigOut)
def create_my_agent(
    body: AgentConfigCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = create_agent(
        db,
        user,
        name=body.name,
        code=body.code,
        description=body.description,
        persona=body.persona,
        allowed_skill_ids=body.allowed_skill_ids,
        knowledge_scope=body.knowledge_scope,
        knowledge_base_ids=body.knowledge_base_ids,
        data_source_scope=body.data_source_scope,
        linked_workflow_id=body.linked_workflow_id,
        output_format=body.output_format,
        prompt_template=body.prompt_template,
        model_config_json={
            **(body.model_config_json or {}),
            "model_route": body.model_route,
            "fallback_strategy": body.fallback_strategy,
            "visibility": body.visibility,
            "allowed_roles": body.allowed_roles,
        },
        scope=body.scope,
    )
    log_audit(db, user=user, object_type="agent_config", object_id=agent.id, action="create_agent")
    db.commit()
    db.refresh(agent)
    return _out(agent, db)


@router.put("/{agent_id}", response_model=AgentConfigOut)
def update_my_agent(
    agent_id: str,
    body: AgentConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = resolve_agent(db, agent_id=agent_id, user=user)
    update_agent(db, agent, user, body.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(agent)
    return _out(agent, db)


@admin_router.get("", response_model=list[AgentConfigOut])
def admin_list_agents(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    return [_out(a, db) for a in db.query(AgentConfig).order_by(AgentConfig.name).all()]


@admin_router.post("", response_model=AgentConfigOut)
def admin_create_template(
    body: AgentConfigCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    agent = create_agent(
        db,
        user,
        name=body.name,
        code=body.code,
        description=body.description,
        persona=body.persona,
        allowed_skill_ids=body.allowed_skill_ids,
        knowledge_scope=body.knowledge_scope,
        knowledge_base_ids=body.knowledge_base_ids,
        data_source_scope=body.data_source_scope,
        linked_workflow_id=body.linked_workflow_id,
        output_format=body.output_format,
        prompt_template=body.prompt_template,
        model_config_json={
            **(body.model_config_json or {}),
            "model_route": body.model_route,
            "fallback_strategy": body.fallback_strategy,
            "visibility": body.visibility,
            "allowed_roles": body.allowed_roles,
            "is_template": True,
        },
        as_template=True,
    )
    log_audit(db, user=user, object_type="agent_config", object_id=agent.id, action="create_agent_template")
    db.commit()
    db.refresh(agent)
    return _out(agent, db)


def _admin_delete_agent_impl(agent_id: str, db: Session, user: User) -> dict:
    from app.services.agent_governance_service import delete_agent

    agent = db.query(AgentConfig).filter(AgentConfig.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent 不存在")
    name = agent.name
    delete_agent(db, agent)
    log_audit(
        db,
        user=user,
        object_type="agent_config",
        object_id=agent_id,
        action="delete_agent",
        detail={"name": name},
    )
    db.commit()
    return {"ok": True, "id": agent_id}


@admin_router.delete("/{agent_id}")
def admin_delete_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    return _admin_delete_agent_impl(agent_id, db, user)


@admin_router.post("/{agent_id}/delete")
def admin_delete_agent_post(
    agent_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """POST 删除：兼容未注册 DELETE 的旧进程或仅允许 GET/POST 的代理。"""
    return _admin_delete_agent_impl(agent_id, db, user)


@admin_router.put("/{agent_id}", response_model=AgentConfigOut)
def admin_update_agent(
    agent_id: str,
    body: AgentConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    agent = db.query(AgentConfig).filter(AgentConfig.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent 不存在")
    update_agent(db, agent, user, body.model_dump(exclude_unset=True), admin=True)
    db.commit()
    db.refresh(agent)
    return _out(agent, db)


@admin_router.get("/stats/summary", response_model=AgentStatsOut)
def admin_agent_stats(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    since = datetime.utcnow() - timedelta(days=7)
    total_conv = db.query(func.count(Conversation.id)).scalar() or 0
    total_runs = db.query(func.count(AgentRun.id)).scalar() or 0
    runs_7d = (
        db.query(func.count(AgentRun.id)).filter(AgentRun.created_at >= since).scalar() or 0
    )
    intent_rows = (
        db.query(AgentRun.intent, func.count(AgentRun.id))
        .group_by(AgentRun.intent)
        .order_by(func.count(AgentRun.id).desc())
        .limit(8)
        .all()
    )
    agent_rows = (
        db.query(AgentRun.agent_id, func.count(AgentRun.id))
        .group_by(AgentRun.agent_id)
        .order_by(func.count(AgentRun.id).desc())
        .limit(8)
        .all()
    )
    agent_names = {
        a.id: a.name for a in db.query(AgentConfig).filter(AgentConfig.id.in_([r[0] for r in agent_rows])).all()
    }
    from app.services.agent_governance_service import compute_ops_metrics

    ops = compute_ops_metrics(db)
    return AgentStatsOut(
        total_conversations=total_conv,
        total_runs=total_runs,
        runs_last_7d=runs_7d,
        top_intents=[{"intent": i or "unknown", "count": c} for i, c in intent_rows],
        top_agents=[{"agent_id": aid, "name": agent_names.get(aid, aid), "count": c} for aid, c in agent_rows],
        ops_metrics=ops,
    )


@admin_router.get("/runs")
def admin_list_agent_runs(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    rows = (
        db.query(AgentRun)
        .order_by(AgentRun.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [
        {
            "id": r.id,
            "agent_id": r.agent_id,
            "conversation_id": r.conversation_id,
            "intent": r.intent,
            "user_input": r.user_input[:500],
            "plan_steps": r.plan_steps,
            "skills_called": r.skills_called,
            "final_output": (r.final_output or "")[:500] or None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@admin_router.get("/runs/{run_id}")
def admin_agent_run_detail(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    from app.services.agent_governance_service import run_detail

    detail = run_detail(db, run_id)
    if not detail:
        raise HTTPException(404, "执行记录不存在")
    return detail


@admin_router.get("/insights")
def admin_agent_insights(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    from app.services.agent_governance_service import compute_evolution_insights

    return {"items": compute_evolution_insights(db)}


@admin_router.post("/{agent_id}/lifecycle", response_model=AgentConfigOut)
def admin_agent_lifecycle(
    agent_id: str,
    body: AgentLifecycleAction,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    from app.services.agent_governance_service import (
        duplicate_as_template,
        offline_agent,
        publish_agent,
        rollback_agent,
        submit_for_review,
    )

    agent = db.query(AgentConfig).filter(AgentConfig.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent 不存在")
    if body.action == "publish":
        publish_agent(agent, gray=body.gray)
    elif body.action == "offline":
        offline_agent(agent)
    elif body.action == "submit_review":
        submit_for_review(agent)
    elif body.action == "rollback":
        if not rollback_agent(agent):
            raise HTTPException(400, "无可用历史版本回滚")
    elif body.action == "duplicate":
        agent = duplicate_as_template(db, agent, new_name=body.new_name or f"{agent.name} 副本")
    else:
        raise HTTPException(400, f"未知操作: {body.action}")
    log_audit(db, user=user, object_type="agent_config", object_id=agent.id, action=f"agent_{body.action}")
    db.commit()
    db.refresh(agent)
    return _out(agent, db)
