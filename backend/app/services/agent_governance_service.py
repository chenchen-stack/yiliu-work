"""Agent 运营与治理：发布生命周期、版本快照、运营洞察。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.models import AgentConfig, AgentRun, Conversation, Skill
from app.services.agent_config_service import agent_to_dict
from app.services.platform_seed import IDS

AGENT_STATUSES = ("draft", "pending_review", "published", "offline")

STATUS_LABEL = {
    "draft": "草稿",
    "pending_review": "待审核",
    "published": "已发布",
    "offline": "已下架",
}


def _mc(agent: AgentConfig) -> dict:
    return dict(agent.model_config_json or {})


def _save_mc(agent: AgentConfig, mc: dict) -> None:
    agent.model_config_json = mc


def snapshot_agent(agent: AgentConfig) -> dict:
    return agent_to_dict(agent)


def append_version_history(agent: AgentConfig, *, note: str = "") -> None:
    mc = _mc(agent)
    history = list(mc.get("version_history") or [])
    history.append({
        "version": agent.version,
        "snapshot": snapshot_agent(agent),
        "saved_at": datetime.utcnow().isoformat(timespec="seconds"),
        "note": note,
    })
    mc["version_history"] = history[-20:]
    _save_mc(agent, mc)


def set_agent_status(agent: AgentConfig, status: str, *, note: str = "") -> None:
    if status not in AGENT_STATUSES:
        raise ValueError(f"无效状态: {status}")
    append_version_history(agent, note=f"状态→{status}: {note}")
    agent.status = status
    agent.version = (agent.version or 1) + 1


def publish_agent(agent: AgentConfig, *, gray: bool = False) -> None:
    mc = _mc(agent)
    if gray:
        mc["gray_release"] = True
        _save_mc(agent, mc)
    set_agent_status(agent, "published", note="发布" + ("（灰度）" if gray else ""))


def offline_agent(agent: AgentConfig) -> None:
    set_agent_status(agent, "offline", note="下架")


def submit_for_review(agent: AgentConfig) -> None:
    set_agent_status(agent, "pending_review", note="提交审核")


def rollback_agent(agent: AgentConfig) -> bool:
    mc = _mc(agent)
    history = list(mc.get("version_history") or [])
    if len(history) < 2:
        return False
    prev = history[-2].get("snapshot") or {}
    for key in (
        "name", "description", "persona", "allowed_skill_ids", "knowledge_scope",
        "knowledge_base_ids", "data_source_scope", "linked_workflow_id", "output_format",
    ):
        if key in prev:
            setattr(agent, key, prev[key])
    if prev.get("prompt_template"):
        agent.prompt_template = prev["prompt_template"]
    agent.version = (agent.version or 1) + 1
    mc["rolled_back_from"] = history[-1].get("version")
    _save_mc(agent, mc)
    return True


def delete_agent(db: Session, agent: AgentConfig) -> None:
    """删除 Agent 配置；清除关联运行记录，会话 agent_id 置空。"""
    if agent.id == IDS.get("agent"):
        raise HTTPException(400, "平台预置 Agent 不可删除，可改为下架")
    db.query(AgentRun).filter(AgentRun.agent_id == agent.id).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.agent_id == agent.id).update(
        {Conversation.agent_id: None},
        synchronize_session=False,
    )
    db.delete(agent)


def duplicate_as_template(db: Session, agent: AgentConfig, *, new_name: str) -> AgentConfig:
    import uuid

    slug = f"tpl_{uuid.uuid4().hex[:8]}"
    snap = snapshot_agent(agent)
    mc = dict(snap.get("model_config_json") or {})
    mc["is_template"] = True
    mc["source_agent_id"] = agent.id
    dup = AgentConfig(
        id=str(uuid.uuid4()),
        name=new_name,
        code=slug,
        description=agent.description,
        persona=agent.persona,
        allowed_skill_ids=list(agent.allowed_skill_ids or []),
        knowledge_scope=agent.knowledge_scope,
        knowledge_base_ids=list(agent.knowledge_base_ids or []),
        data_source_scope=list(agent.data_source_scope or []),
        linked_workflow_id=agent.linked_workflow_id,
        output_format=agent.output_format,
        prompt_template=agent.prompt_template,
        model_config_json=mc,
        scope="team_published",
        owner_id=None,
        status="draft",
        version=1,
    )
    db.add(dup)
    return dup


_DS_LABELS = {
    "sap_billing": "SAP 发货开票",
    "dms_ledger": "DMS 收入台账",
    "inherit_role": "继承角色权限",
}
_KB_LABELS = {
    "kb-fangtai-cases": "方太历史案例库",
    "revenue_reconciliation": "收入对账知识域",
    "kb-compliance": "合规校验条目",
}
_SCOPE_LABELS = {
    "revenue_reconciliation": "收入对账知识域",
}


def _enrich_model_route(db: Session, agent: AgentConfig) -> dict[str, Any]:
    from app.services.llm_config_service import get_effective_llm_config, llm_runtime_ready

    route = dict(_mc(agent).get("model_route") or {"simple": "mock-ai", "complex": "deepseek-v4-pro"})
    platform = get_effective_llm_config(db)
    route["platform_model"] = platform.model
    route["platform_provider"] = platform.provider
    route["platform_runtime_ready"] = llm_runtime_ready(platform)
    route["platform_use_mock"] = platform.use_mock
    return route


def build_asset_mounts(agent: AgentConfig, db: Session) -> dict[str, Any]:
    from app.models import Workflow
    from app.services.agent_ui_blocks import _resolve_skill_item

    skills = []
    for sid in agent.allowed_skill_ids or []:
        detail = _resolve_skill_item(db, sid)
        sk = db.query(Skill).filter((Skill.id == sid) | (Skill.code == sid)).first()
        skills.append({
            "id": sid,
            "code": detail.get("code") or (sk.code if sk else sid.replace("skill-", "")),
            "name": detail["title"],
            "desc": detail["desc"],
            "layer": "Skill库",
            "type": detail.get("type") or (sk.type if sk else "ability"),
        })
    kb_rows = []
    for kid in agent.knowledge_base_ids or []:
        kb_rows.append({
            "id": kid,
            "name": _KB_LABELS.get(kid, kid),
            "layer": "知识库",
        })
    if not kb_rows and agent.knowledge_scope:
        kb_rows.append({
            "id": agent.knowledge_scope,
            "name": _SCOPE_LABELS.get(agent.knowledge_scope, agent.knowledge_scope),
            "layer": "知识库",
        })
    wf_name = None
    if agent.linked_workflow_id:
        wf = db.query(Workflow).filter(Workflow.id == agent.linked_workflow_id).first()
        wf_name = wf.name if wf else agent.linked_workflow_id
    return {
        "skills": skills,
        "knowledge_bases": kb_rows,
        "data_sources": [
            {
                "id": ds,
                "name": _DS_LABELS.get(ds, ds),
                "layer": "数据接入",
            }
            for ds in (agent.data_source_scope or [])
        ],
        "ontology": [{"id": "mapping", "name": "方太字段映射 / 排查规则", "layer": "本体翻译"}],
        "model_route": _enrich_model_route(db, agent),
        "linked_workflow": agent.linked_workflow_id,
        "linked_workflow_name": wf_name,
        "note": "Agent 不拥有资产，仅授权引用中台统一管理的 Skill / 知识库 / 数据源 / 本体 / 大模型 / Workflow。",
    }


def compute_ops_metrics(db: Session) -> dict[str, Any]:
    from datetime import timedelta

    since_7d = datetime.utcnow() - timedelta(days=7)
    total_runs = db.query(func.count(AgentRun.id)).scalar() or 0
    runs_7d = (
        db.query(func.count(AgentRun.id)).filter(AgentRun.created_at >= since_7d).scalar() or 0
    )
    conv_count = db.query(func.count(Conversation.id)).scalar() or 0

    skill_calls: dict[str, int] = {}
    for row in db.query(AgentRun.skills_called).filter(AgentRun.skills_called.isnot(None)).all():
        for sk in row[0] or []:
            skill_calls[sk] = skill_calls.get(sk, 0) + 1

    by_status = (
        db.query(AgentConfig.status, func.count(AgentConfig.id))
        .group_by(AgentConfig.status)
        .all()
    )
    return {
        "total_runs": total_runs,
        "runs_last_7d": runs_7d,
        "total_conversations": conv_count,
        "avg_turns_estimate": round(total_runs / max(conv_count, 1), 1),
        "success_rate_estimate": min(0.95, 0.7 + 0.05 * min(total_runs, 6)),
        "skill_call_hotspots": sorted(
            [{"skill": k, "count": v} for k, v in skill_calls.items()],
            key=lambda x: -x["count"],
        )[:10],
        "agents_by_status": [
            {"status": s, "label": STATUS_LABEL.get(s, s), "count": c} for s, c in by_status
        ],
    }


def compute_evolution_insights(db: Session) -> list[dict[str, str]]:
    insights: list[dict[str, str]] = []
    all_skills = {s.code for s in db.query(Skill).all()}
    called: set[str] = set()
    for row in db.query(AgentRun.skills_called).all():
        for sk in row[0] or []:
            called.add(sk)
    unused = all_skills - called
    if unused:
        insights.append({
            "type": "skill",
            "level": "info",
            "title": "低频 Skill",
            "detail": f"以下 Skill 在对话中未被调用：{', '.join(sorted(unused)[:5])}。可考虑下架或补充到 Agent 授权。",
        })

    pending = db.query(AgentConfig).filter(AgentConfig.status == "pending_review").count()
    if pending:
        insights.append({
            "type": "publish",
            "level": "warning",
            "title": "待审核发布",
            "detail": f"有 {pending} 个 Agent 等待审核发布。",
        })

    offline_high = db.query(AgentConfig).filter(AgentConfig.status == "offline").count()
    if offline_high:
        insights.append({
            "type": "lifecycle",
            "level": "info",
            "title": "已下架 Agent",
            "detail": f"{offline_high} 个 Agent 已下架，不影响历史会话，但前台不可新建对话。",
        })

    if not insights:
        insights.append({
            "type": "ok",
            "level": "success",
            "title": "运营正常",
            "detail": "暂无异常告警；持续积累对话 Trace 后将自动提炼 Few-shot 与知识库建议。",
        })
    return insights


def run_detail(db: Session, run_id: str) -> dict | None:
    run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
    if not run:
        return None
    agent = db.query(AgentConfig).filter(AgentConfig.id == run.agent_id).first()
    conv = None
    if run.conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == run.conversation_id).first()
    return {
        "run": {
            "id": run.id,
            "agent_id": run.agent_id,
            "agent_name": agent.name if agent else run.agent_id,
            "agent_version": agent.version if agent else None,
            "conversation_id": run.conversation_id,
            "user_input": run.user_input,
            "intent": run.intent,
            "plan_steps": run.plan_steps or [],
            "final_output": run.final_output,
            "skills_called": run.skills_called or [],
            "created_at": run.created_at.isoformat() if run.created_at else None,
        },
        "conversation_messages": (conv.messages or []) if conv else [],
    }
