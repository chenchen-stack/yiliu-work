"""Dialogue with optional task/difference context."""

from sqlalchemy.orm import Session

from app.services.chat_service import (
    LLM_UNAVAILABLE_MSG,
    _deepseek_chat,
    call_deepseek_chat,
    llm_failure_reply,
    llm_api_ready,
)
from app.services.llm_config_service import EffectiveLlmConfig, get_effective_llm_config

SYSTEM = """你是亿流 Work 收入差异解释 Agent。
你只能基于已给出的结构化差异事实、规则命中和证据链进行解释，不得臆造差异数据。
禁止输出「【异常卡片】」或编造差异编号、ERP/OMS 单据号；禁止声称「已展示全部 N 条」或编造差异条数。
详细内容以界面卡片为准。
回答简洁专业，使用中文。有结构化卡片时 1～2 句摘要；无卡片时 2～4 句完整引导。
仅当用户明确要对账时才说明将弹出数据源确认卡片；禁止编造带方括号占位符的伪表单（如 [请选择…]）。不要重复卡片字段。

输出格式（必须遵守，禁止使用 Markdown）：
- 不要使用 **、#、-、* 等 Markdown 符号
- 不要输出长列表或伪卡片文本块"""


async def chat_with_context(
    message: str,
    history: list[dict],
    context: dict | None = None,
    db: Session | None = None,
    *,
    system_prompt: str | None = None,
) -> tuple[str, str | None]:
    cfg = get_effective_llm_config(db)
    sys_text = (system_prompt or "").strip() or SYSTEM

    if not llm_api_ready(cfg):
        intent = "difference_explain" if context and context.get("difference_id") else "general"
        return LLM_UNAVAILABLE_MSG, intent

    try:
        if context and context.get("difference_id"):
            ctx_text = _format_context(context)
            enriched = f"{ctx_text}\n\n用户问题：{message}"
            reply = await _deepseek_context_chat(enriched, history, cfg, sys_text)
            return reply, "difference_explain"
        reply = await _deepseek_chat(message, history, cfg, system_prompt=sys_text)
        return reply, "general"
    except Exception as exc:
        intent = "difference_explain" if context and context.get("difference_id") else "general"
        return llm_failure_reply(exc), intent


def _format_context(ctx: dict) -> str:
    lines = [
        f"任务：{ctx.get('task_name')} ({ctx.get('task_id', '')[:8]})",
        f"核对周期：{ctx.get('task_period')}",
        f"差异编号：{str(ctx.get('difference_id', ''))[:8]}",
        f"差异类型：{ctx.get('difference_type')}",
        f"业务键：{ctx.get('business_key')}",
        f"规则命中：{ctx.get('rule_hits')}",
        f"证据：{ctx.get('evidence')}",
        f"已有 AI 解释：{ctx.get('ai_explanation')}",
    ]
    return "\n".join(lines)


async def _deepseek_context_chat(
    message: str,
    history: list[dict],
    cfg: EffectiveLlmConfig,
    system_prompt: str | None = None,
) -> str:
    messages = [{"role": "system", "content": system_prompt or SYSTEM}]
    for h in history[-4:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})
    return await call_deepseek_chat(cfg, messages)
