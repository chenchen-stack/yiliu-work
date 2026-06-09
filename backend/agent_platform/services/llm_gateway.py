"""Unified LLM gateway via LiteLLM (with mock fallback)."""

from __future__ import annotations

import json
from typing import Any

from agent_platform.config import platform_settings
from agent_platform.logging_setup import get_logger

logger = get_logger("llm_gateway")

# 场景 → 模型路由（LiteLLM）
ROUTE_MAP: dict[str, str] = {
    "anomaly_explain": "deepseek/deepseek-chat",
    "field_suggestion": "qwen/qwen-max",
    "default": "deepseek/deepseek-chat",
}


def resolve_model(purpose: str | None = None, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    if purpose and purpose in ROUTE_MAP:
        return ROUTE_MAP[purpose]
    return platform_settings.litellm_model or ROUTE_MAP["default"]


async def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Call LLM and return assistant text content."""
    from app.config import settings as app_settings

    use_mock = platform_settings.use_mock_llm or app_settings.use_mock_ai
    if use_mock and not (platform_settings.litellm_api_key or app_settings.deepseek_api_key):
        return _mock_reply(messages)

    try:
        import litellm
    except ImportError:
        logger.error("litellm 未安装，请执行: pip install -r requirements.txt")
        return (
            "（演示模式）未安装 litellm 依赖，无法调用大模型。"
            "请在 backend 目录执行：.venv\\Scripts\\pip install litellm"
        )

    api_key = platform_settings.litellm_api_key or app_settings.deepseek_api_key
    api_base = platform_settings.litellm_api_base or app_settings.deepseek_base_url
    chosen = resolve_model(explicit=model)

    kwargs: dict[str, Any] = {
        "model": chosen,
        "messages": messages,
        "temperature": temperature,
        "api_key": api_key or None,
    }
    if api_base:
        kwargs["api_base"] = api_base
    if response_format:
        kwargs["response_format"] = response_format

    resp = await litellm.acompletion(**kwargs)
    content = resp.choices[0].message.content or ""
    logger.info("llm completion", extra_fields={"model": chosen, "chars": len(content)})
    return content


async def json_completion(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """Request JSON object from model."""
    text = await chat_completion(
        messages,
        model=model,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _mock_reply(messages: list[dict[str, str]]) -> str:
    last = messages[-1].get("content", "") if messages else ""
    if "json" in last.lower() or "JSON" in last:
        return json.dumps(
            {"thought": "mock", "action": "finish", "answer": "（演示模式）已根据 Skill 结果生成说明。"},
            ensure_ascii=False,
        )
    return "（演示模式）这是 LiteLLM 关闭时的占位回复。请配置 DEEPSEEK_API_KEY 并设置 USE_MOCK_LLM=false。"
