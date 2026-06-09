"""Agent 意图识别：优先大模型语义路由，规则仅作 client_action 与 LLM 不可用时的回退。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import AgentConfig
from app.services.agent_ui_blocks import build_agent_grounding_context
from app.services.chat_service import call_deepseek_chat
from app.services.llm_config_service import agent_llm_invocation_ready, is_mock_model_route

log = logging.getLogger(__name__)

VALID_INTENTS = frozenset({
    "onboarding",
    "agent_capabilities",
    "knowledge_query",
    "start_reconciliation",
    "query_tasks",
    "workflow_guide",
    "faq_diff_types",
    "difference_explain",
    "list_differences",
    "upload",
    "dialog",
    "operate",
    "chitchat",
    "analyze",
    "progress",
})

_INTENT_CLASSIFY_SYSTEM = """你是企业财资 Agent 中台的「意图路由器」。根据用户最新一条消息（及简短对话上下文）判断应触发的处理分支。

只输出一个 JSON 对象，不要 Markdown、不要解释。格式：
{"intent":"<intent>","user_need":"<一句话概括用户诉求>"}

可选 intent（必须且只能选一个）：
- onboarding：纯打招呼、寒暄、在吗
- agent_capabilities：问 Agent 能做什么、有哪些 Skill、你是谁、能力清单
- knowledge_query：查知识库/历史案例/登记表/排查规则；或问「某人是谁/负责什么」（如责任人、@姓名，须先在知识库检索）
- start_reconciliation：要发起/执行/跑收入核对、比对 SAP 与 DMS、核对某月数据
- query_tasks：查对账任务列表、进度、待复核、完成了吗
- workflow_guide：问标准核对流程、操作步骤、工作流程
- faq_diff_types：问金额差异/重复数据/映射异常三类差异怎么处理（规则说明类，非查案例库）
- difference_explain：【仅当 has_diff_context=true】解释当前差异根因、处理建议、证据链
- list_differences：查看某任务差异清单、还有多少条差异
- upload：上传/导入 Excel/CSV、接入批次数据
- dialog：其它业务问答、口径差异讨论、无法归类的闲聊

硬约束：
1. has_diff_context=false 时禁止 difference_explain
2. 「三类差异怎么处理」应选 faq_diff_types；问具体人员/责任人且可能在案例中出现时选 knowledge_query
3. 用户仅寒暄或问能力时不要选 knowledge_query
4. user_need 用中文，不超过 40 字"""


def _intent_from_client_action(client_action: str | None) -> tuple[str, str] | None:
    if not client_action:
        return None
    mapping = {
        "faq_workflow": ("workflow_guide", "了解标准核对流程"),
        "faq_diff_types": ("faq_diff_types", "了解三类差异处理方式"),
        "start_reconciliation": ("start_reconciliation", "发起对账并确认数据源"),
        "query_tasks": ("query_tasks", "查询任务进度与状态"),
        "query_knowledge": ("knowledge_query", "检索挂载的知识库"),
        "explain_difference": ("difference_explain", "解释当前差异归因"),
    }
    return mapping.get(client_action)


def _build_classify_user_payload(
    message: str,
    history: list[dict] | None,
    *,
    has_diff_context: bool,
    agent: AgentConfig,
    db: Session,
) -> str:
    lines = [
        f"has_diff_context={'true' if has_diff_context else 'false'}",
        "",
        "【Agent 后台事实】",
        build_agent_grounding_context(agent, db)[:2400],
        "",
    ]
    hist = (history or [])[-6:]
    if hist:
        lines.append("【近期对话】")
        for h in hist:
            role = h.get("role", "user")
            content = (h.get("content") or "")[:200]
            if content:
                lines.append(f"{role}: {content}")
        lines.append("")
    lines.append(f"【用户最新消息】\n{message.strip()}")
    return "\n".join(lines)


def _parse_intent_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[^{}]*\"intent\"[^{}]*\}", text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _sanitize_llm_intent(
    intent: str,
    *,
    has_diff_context: bool,
) -> str:
    key = (intent or "dialog").strip().lower()
    if key not in VALID_INTENTS:
        key = "dialog"
    if not has_diff_context and key == "difference_explain":
        key = "dialog"
    if key in ("chitchat", "analyze", "progress", "operate"):
        key = "dialog" if key != "operate" else "start_reconciliation"
    return key


async def classify_intent_with_llm(
    message: str,
    *,
    agent: AgentConfig,
    db: Session,
    has_diff_context: bool,
    history: list[dict] | None = None,
) -> tuple[str, str] | None:
    """大模型语义意图识别。失败返回 None。"""
    chat_cfg, route_id = agent_llm_invocation_ready(agent, db, intent="dialog", has_diff=has_diff_context)
    if not chat_cfg or is_mock_model_route(route_id):
        return None

    user_payload = _build_classify_user_payload(
        message, history, has_diff_context=has_diff_context, agent=agent, db=db,
    )
    messages = [
        {"role": "system", "content": _INTENT_CLASSIFY_SYSTEM},
        {"role": "user", "content": user_payload},
    ]
    try:
        raw = await call_deepseek_chat(chat_cfg, messages, max_tokens=256, allow_retry=False)
    except Exception as exc:
        log.warning("intent classify LLM failed: %s", exc)
        return None

    data = _parse_intent_json(raw)
    if not data:
        log.warning("intent classify parse failed: %s", (raw or "")[:200])
        return None

    intent = _sanitize_llm_intent(str(data.get("intent") or "dialog"), has_diff_context=has_diff_context)
    user_need = str(data.get("user_need") or "").strip() or "理解用户诉求"
    if len(user_need) > 80:
        user_need = user_need[:80]
    return intent, user_need


async def resolve_intent(
    message: str,
    *,
    agent: AgentConfig,
    db: Session,
    has_diff_context: bool,
    client_action: str | None = None,
    history: list[dict] | None = None,
) -> tuple[str, str, str]:
    """返回 (intent, user_need, source)。source: action | llm | rules。"""
    action_hit = _intent_from_client_action(client_action)
    if action_hit:
        return action_hit[0], action_hit[1], "action"

    if not has_diff_context:
        from app.services.agent_runtime import _wants_knowledge_query, classify_intent_by_rules

        if _wants_knowledge_query(message):
            rule_intent, rule_need = classify_intent_by_rules(
                message,
                has_diff_context=has_diff_context,
                client_action=client_action,
                history=history,
            )
            if rule_intent == "knowledge_query":
                return rule_intent, rule_need, "rules"

    llm_hit = await classify_intent_with_llm(
        message,
        agent=agent,
        db=db,
        has_diff_context=has_diff_context,
        history=history,
    )
    if llm_hit:
        return llm_hit[0], llm_hit[1], "llm"

    from app.services.agent_runtime import classify_intent_by_rules

    intent, user_need = classify_intent_by_rules(
        message,
        has_diff_context=has_diff_context,
        client_action=client_action,
        history=history,
    )
    return intent, user_need, "rules"
