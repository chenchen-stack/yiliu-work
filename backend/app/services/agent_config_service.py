"""Agent 配置读写与可见性（个人 / 团队发布 / 管理模板）。"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import AgentConfig, User, UserRole
from app.services.platform_seed import IDS


def agent_to_dict(agent: AgentConfig, db: Session | None = None) -> dict[str, Any]:
    mc = agent.model_config_json or {}
    out = {
        "id": agent.id,
        "name": agent.name,
        "code": agent.code,
        "description": agent.description or "",
        "persona": agent.persona or agent.prompt_template or "",
        "allowed_skill_ids": agent.allowed_skill_ids or [],
        "knowledge_scope": agent.knowledge_scope,
        "knowledge_base_ids": agent.knowledge_base_ids or [],
        "data_source_scope": agent.data_source_scope or [],
        "linked_workflow_id": agent.linked_workflow_id or mc.get("linked_workflow_id"),
        "output_format": agent.output_format or "natural",
        "prompt_template": agent.prompt_template,
        "model_config_json": mc,
        "model_route": mc.get("model_route") or {"simple": "mock-ai", "complex": "deepseek-v4-pro"},
        "fallback_strategy": mc.get("fallback_strategy") or "ask_user",
        "scope": agent.scope or "team_published",
        "visibility": mc.get("visibility") or agent.scope or "team_published",
        "allowed_roles": mc.get("allowed_roles") or [],
        "owner_id": agent.owner_id,
        "status": agent.status,
        "version": agent.version,
        "is_template": bool(mc.get("is_template") or (not agent.owner_id and agent.scope == "team_published")),
        "version_history": mc.get("version_history") or [],
        "avatar_id": mc.get("avatar_id") or "anime-01",
        "created_at": agent.created_at.isoformat() if getattr(agent, "created_at", None) else None,
        "updated_at": agent.updated_at.isoformat() if getattr(agent, "updated_at", None) else None,
    }
    if db:
        from app.services.agent_governance_service import build_asset_mounts

        out["asset_mounts"] = build_asset_mounts(agent, db)
    return out


def list_agents_for_user(db: Session, user: User) -> list[AgentConfig]:
    q = db.query(AgentConfig).filter(AgentConfig.status == "published")
    if user.role in (UserRole.ADMIN.value, UserRole.MANAGER.value):
        rows = q.order_by(AgentConfig.name).all()
    else:
        rows = q.filter(
            (AgentConfig.scope == "team_published")
            | ((AgentConfig.scope == "personal") & (AgentConfig.owner_id == user.id))
        ).order_by(AgentConfig.name).all()
    if rows:
        return rows
    # 无已发布 Agent 时，回退到平台默认 Agent，避免前台对话空白/硬编码欢迎页
    fallback = db.query(AgentConfig).filter(AgentConfig.id == IDS["agent"]).first()
    return [fallback] if fallback else []


def resolve_agent(
    db: Session,
    *,
    agent_id: str | None = None,
    agent_code: str | None = None,
    user: User | None = None,
) -> AgentConfig:
    agent = None
    if agent_id:
        agent = db.query(AgentConfig).filter(AgentConfig.id == agent_id).first()
    elif agent_code:
        agent = db.query(AgentConfig).filter(AgentConfig.code == agent_code).first()
    if not agent:
        agent = db.query(AgentConfig).filter(AgentConfig.id == IDS["agent"]).first()
    if not agent:
        raise HTTPException(404, "Agent 不存在")
    if agent.status != "published" and user and user.role not in (
        UserRole.ADMIN.value,
        UserRole.MANAGER.value,
    ):
        if agent.owner_id != user.id:
            raise HTTPException(403, "无权使用该 Agent")
    return agent


def create_agent(
    db: Session,
    user: User,
    *,
    name: str,
    code: str | None = None,
    description: str = "",
    persona: str = "",
    allowed_skill_ids: list[str] | None = None,
    knowledge_scope: str | None = None,
    knowledge_base_ids: list[str] | None = None,
    data_source_scope: list[str] | None = None,
    linked_workflow_id: str | None = None,
    output_format: str = "natural",
    prompt_template: str | None = None,
    model_config_json: dict | None = None,
    scope: str = "personal",
    as_template: bool = False,
) -> AgentConfig:
    if as_template and user.role not in (UserRole.ADMIN.value, UserRole.MANAGER.value):
        raise HTTPException(403, "仅管理员可创建团队模板")
    slug = code or f"agent_{uuid.uuid4().hex[:8]}"
    if db.query(AgentConfig).filter(AgentConfig.code == slug).first():
        raise HTTPException(400, f"Agent 编码 {slug} 已存在")
    mc = dict(model_config_json or {})
    if linked_workflow_id:
        mc["linked_workflow_id"] = linked_workflow_id
    if model_config_json:
        mc.update(model_config_json)
    mc.setdefault("model_route", mc.get("model_route") or {"simple": "mock-ai", "complex": "deepseek-v4-pro"})
    mc.setdefault("fallback_strategy", mc.get("fallback_strategy") or "ask_user")
    mc.setdefault("visibility", mc.get("visibility") or scope)
    if as_template:
        mc["is_template"] = True
    initial_status = "draft" if as_template else ("draft" if scope == "personal" else "published")
    agent = AgentConfig(
        id=str(uuid.uuid4()),
        name=name.strip(),
        code=slug,
        description=description,
        persona=persona or description,
        allowed_skill_ids=allowed_skill_ids or ["skill-anomaly_explain"],
        knowledge_scope=knowledge_scope,
        knowledge_base_ids=knowledge_base_ids or [],
        data_source_scope=data_source_scope or [],
        linked_workflow_id=linked_workflow_id or IDS.get("workflow"),
        output_format=output_format,
        prompt_template=prompt_template or persona,
        model_config_json=mc,
        scope="team_published" if as_template else scope,
        owner_id=None if as_template else user.id,
        status=initial_status,
        version=1,
    )
    db.add(agent)
    return agent


def update_agent(
    db: Session,
    agent: AgentConfig,
    user: User,
    patch: dict[str, Any],
    *,
    admin: bool = False,
) -> AgentConfig:
    if not admin and agent.owner_id and agent.owner_id != user.id:
        if user.role not in (UserRole.ADMIN.value, UserRole.MANAGER.value):
            raise HTTPException(403, "无权修改该 Agent")
    for key in (
        "name", "description", "persona", "knowledge_scope", "output_format",
        "prompt_template", "linked_workflow_id", "scope", "status",
    ):
        if key in patch and patch[key] is not None:
            setattr(agent, key, patch[key])
    if "allowed_skill_ids" in patch and patch["allowed_skill_ids"] is not None:
        agent.allowed_skill_ids = patch["allowed_skill_ids"]
    if "knowledge_base_ids" in patch and patch["knowledge_base_ids"] is not None:
        agent.knowledge_base_ids = patch["knowledge_base_ids"]
    if "data_source_scope" in patch and patch["data_source_scope"] is not None:
        agent.data_source_scope = patch["data_source_scope"]
    if "model_config_json" in patch and patch["model_config_json"] is not None:
        agent.model_config_json = {**(agent.model_config_json or {}), **patch["model_config_json"]}
    if "fallback_strategy" in patch and patch["fallback_strategy"] is not None:
        mc = {**(agent.model_config_json or {}), "fallback_strategy": patch["fallback_strategy"]}
        agent.model_config_json = mc
    if "model_route" in patch and patch["model_route"] is not None:
        mc = {**(agent.model_config_json or {}), "model_route": patch["model_route"]}
        agent.model_config_json = mc
    if "visibility" in patch and patch["visibility"] is not None:
        mc = {**(agent.model_config_json or {}), "visibility": patch["visibility"]}
        agent.model_config_json = mc
    if "allowed_roles" in patch and patch["allowed_roles"] is not None:
        mc = {**(agent.model_config_json or {}), "allowed_roles": patch["allowed_roles"]}
        agent.model_config_json = mc
    if patch.get("publish"):
        from app.services.agent_governance_service import publish_agent

        publish_agent(agent)
        if agent.scope == "personal":
            agent.scope = "team_published"
        return agent
    if patch.get("status") and patch["status"] != agent.status:
        from app.services.agent_governance_service import set_agent_status

        set_agent_status(agent, patch["status"], note="管理后台更新")
        return agent
    agent.version = (agent.version or 1) + 1
    return agent
