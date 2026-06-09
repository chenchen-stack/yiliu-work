"""为已存在库补齐 Agent 配置字段（不重建整库）。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AgentConfig
from app.services.platform_seed import IDS


def upgrade_default_agent(db: Session) -> None:
    agent = db.query(AgentConfig).filter(AgentConfig.id == IDS["agent"]).first()
    if not agent:
        return
    changed = False
    if not agent.persona or "方太" not in (agent.persona or ""):
        agent.persona = (
            "你是方太收入核对分析助手（亿流 Work 收入核对中心），"
            "专注 SAP 发货开票与 DMS 收入台账之间的三类差异解释与任务查询。"
            "用户发起对账时须在对话内弹出数据源确认并引导一键执行，不要仅让用户自行去工作台。"
        )
        changed = True
    if not agent.description or "方太" not in (agent.description or ""):
        agent.description = (
            "方太财资收入核对分析助手：基于 SAP/DMS 双源数据解释差异、查询任务、对话内发起核对。"
        )
        changed = True
    mc = dict(agent.model_config_json or {})
    route = dict(mc.get("model_route") or {})
    if route.get("complex") in ("deepseek", "mock-ai", None, ""):
        from app.services.llm_config_service import get_effective_llm_config, llm_runtime_ready
        platform = get_effective_llm_config(db)
        route["complex"] = platform.model if llm_runtime_ready(platform) else "deepseek-v4-pro"
        route.setdefault("simple", "mock-ai")
        mc["model_route"] = route
        agent.model_config_json = mc
        changed = True
    if not agent.linked_workflow_id:
        agent.linked_workflow_id = IDS["workflow"]
        changed = True
    ids = agent.allowed_skill_ids or []
    for sk in ("skill-query_tasks",):
        if sk not in ids:
            ids.append(sk)
            changed = True
    kb_ids = list(agent.knowledge_base_ids or [])
    if "revenue_reconciliation" not in kb_ids and (
        agent.knowledge_scope == "revenue_reconciliation" or "revenue" in (agent.code or "")
    ):
        kb_ids.append("revenue_reconciliation")
        agent.knowledge_base_ids = kb_ids
        changed = True
    if changed:
        agent.allowed_skill_ids = ids
        mc = dict(agent.model_config_json or {})
        mc.setdefault("fallback_strategy", "ask_user")
        agent.model_config_json = mc
        db.commit()


def ensure_chat_agent_available(db: Session) -> None:
    """若库内无已发布 Agent，自动恢复默认模板为 published，保证前台对话可挂载后台配置。"""
    pub_count = db.query(AgentConfig).filter(AgentConfig.status == "published").count()
    if pub_count > 0:
        return
    agent = db.query(AgentConfig).filter(AgentConfig.id == IDS["agent"]).first()
    if not agent:
        return
    agent.status = "published"
    if not agent.data_source_scope:
        agent.data_source_scope = ["sap_billing", "dms_ledger"]
    if not agent.knowledge_base_ids:
        agent.knowledge_base_ids = ["kb-fangtai-cases", "revenue_reconciliation"]
    elif "revenue_reconciliation" not in (agent.knowledge_base_ids or []):
        if agent.knowledge_scope == "revenue_reconciliation" or "revenue" in (agent.code or ""):
            agent.knowledge_base_ids = list(agent.knowledge_base_ids or []) + ["revenue_reconciliation"]
    if not agent.allowed_skill_ids:
        agent.allowed_skill_ids = ["skill-anomaly_explain", "skill-query_tasks"]
    db.commit()
