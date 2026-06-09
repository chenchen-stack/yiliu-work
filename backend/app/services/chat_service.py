"""Dialogue mode — Agent chat via DeepSeek."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.services.llm_config_service import EffectiveLlmConfig, get_effective_llm_config, llm_runtime_ready

SYSTEM = """你是亿流 Work 企业财资 Agent 中台的智能助手。
当前 MVP 支持：收入核对中心（三类差异：金额差异、重复数据、主数据/映射异常）。
你可以帮助用户：查询对账进度、解释差异原因、引导上传数据、说明复核流程。
回答简洁专业，使用中文。

输出格式（必须遵守，禁止使用 Markdown）：
- 首行写一句摘要（无符号装饰）
- 多个要点用「1. 标题」换行后写正文；正文可用「1. 2. 3.」列步骤
- 不要使用 **、#、-、* 等 Markdown 符号
- 必须写完整：若提到「步骤如下」「分别如下」，必须列出全部要点，不可只写引导句"""

INTENTS = {
    "对账": "reconciliation",
    "核对": "reconciliation",
    "差异": "difference",
    "进度": "progress",
    "上传": "upload",
    "复核": "review",
}

CHAT_MIN_MAX_TOKENS = 1500

LLM_UNAVAILABLE_MSG = (
    "大模型未配置，请在管理后台「大模型中心」填写 API Key 并关闭模拟模式后重试。"
)

LLM_FAILURE_PREFIX = "大模型调用失败"


def format_llm_error(exc: BaseException) -> str:
    """将 httpx / CancelledError 等空消息异常转为可读中文说明。"""
    if isinstance(exc, asyncio.CancelledError):
        return "请求已中断（常见于后端热重载或页面刷新），请重新发送消息。"
    msg = str(exc).strip()
    if not msg:
        if isinstance(exc, httpx.TimeoutException):
            return "大模型接口超时，请稍后重试。"
        if isinstance(exc, httpx.ConnectError):
            return "无法连接大模型服务，请检查网络或大模型中心中的 API 地址。"
        return "大模型调用失败（未返回详细原因），请稍后重试。"
    if "返回空内容" in msg:
        return "大模型未返回可用正文，请检查模型名称与 API Key 或稍后重试。"
    return msg


def llm_failure_reply(exc: BaseException) -> str:
    return f"{LLM_FAILURE_PREFIX}：{format_llm_error(exc)}"


def llm_api_ready(cfg: EffectiveLlmConfig) -> bool:
    """对话/解释场景：平台大模型中心须关闭 Mock 且配置 Key。"""
    return llm_runtime_ready(cfg)


def extract_message_content(message: dict[str, Any]) -> str:
    content = (message.get("content") or "").strip()
    if content:
        return content
    return (message.get("reasoning_content") or "").strip()


async def call_deepseek_chat(
    cfg: EffectiveLlmConfig,
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    allow_retry: bool = True,
) -> str:
    limit = max(max_tokens or cfg.max_tokens, CHAT_MIN_MAX_TOKENS)
    url = f"{cfg.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": messages,
        "stream": False,
        "max_tokens": limit,
        "temperature": cfg.temperature,
    }
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        body = resp.json()

    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = extract_message_content(message)
    finish_reason = choice.get("finish_reason")

    if finish_reason == "length" and allow_retry and limit < 4096:
        return await call_deepseek_chat(
            cfg,
            messages,
            max_tokens=min(limit * 2, 4096),
            allow_retry=False,
        )
    if not content:
        raise ValueError("DeepSeek 返回空内容")
    return content


async def chat_with_agent(
    message: str,
    history: list[dict],
    db: Session | None = None,
) -> tuple[str, str | None]:
    intent = next((v for k, v in INTENTS.items() if k in message), "general")
    cfg = get_effective_llm_config(db)

    if not llm_api_ready(cfg):
        return LLM_UNAVAILABLE_MSG, intent

    try:
        return await _deepseek_chat(message, history, cfg), intent
    except Exception as exc:
        return llm_failure_reply(exc), intent


async def _deepseek_chat(
    message: str,
    history: list[dict],
    cfg: EffectiveLlmConfig,
    *,
    system_prompt: str | None = None,
) -> str:
    messages = [{"role": "system", "content": system_prompt or SYSTEM}]
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})
    return await call_deepseek_chat(cfg, messages)
