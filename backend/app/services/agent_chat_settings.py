"""对话 Agent 模式：DB（大模型配置）优先，agent_platform 环境变量兜底。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from agent_platform.config import platform_settings
from app.services.llm_config_service import ensure_llm_config

DEFAULT_AGENT_CHAT: dict[str, Any] = {
    "enabled": True,
    "use_langgraph": True,
    "diff_explain_via_agent": True,
}


@dataclass
class EffectiveAgentChatSettings:
    enabled: bool
    use_langgraph: bool
    diff_explain_via_agent: bool
    config_source: str  # database | environment


def _merge_agent_chat(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(DEFAULT_AGENT_CHAT)
    if raw:
        base.update({k: v for k, v in raw.items() if v is not None})
    return base


def get_effective_agent_chat_settings(db: Session | None = None) -> EffectiveAgentChatSettings:
    if db is None:
        return EffectiveAgentChatSettings(
            enabled=platform_settings.use_platform_chat_sse,
            use_langgraph=platform_settings.use_langgraph_agent,
            diff_explain_via_agent=True,
            config_source="environment",
        )

    row = ensure_llm_config(db)
    merged = _merge_agent_chat(getattr(row, "agent_chat_json", None))
    return EffectiveAgentChatSettings(
        enabled=bool(merged.get("enabled", platform_settings.use_platform_chat_sse)),
        use_langgraph=bool(merged.get("use_langgraph", platform_settings.use_langgraph_agent)),
        diff_explain_via_agent=bool(merged.get("diff_explain_via_agent", True)),
        config_source="database",
    )
