"""平台大模型配置：DB 优先，.env 兜底。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LlmConfig

PLATFORM_LLM_ID = "platform-default"
DEFAULT_LINKED_SKILLS = ["anomaly_explain"]

DEFAULT_SYSTEM_PROMPT = """你是方太财务部收入对账专家。根据 SAP/DMS/对账单数据，分析差异根因。
必须只返回 JSON，不要 markdown，字段：
- root_cause: string 中文原因说明
- confidence: number 0-1
- responsible_party: string，取值 finance / sales / mdm_team / logistics 之一
- evidence: string[] 支持性证据列表"""

DEEPSEEK_MODEL_PRESETS = [
    "deepseek-v4-pro",
    "deepseek-chat",
    "deepseek-reasoner",
]


@dataclass
class EffectiveLlmConfig:
    provider: str
    api_key: str
    base_url: str
    model: str
    use_mock: bool
    temperature: float
    max_tokens: int
    system_prompt: str
    linked_skill_codes: list[str]
    api_key_source: str  # database | environment | none
    config_source: str  # database | environment


def mask_api_key(key: str | None) -> str | None:
    if not key or len(key) < 8:
        return None
    return f"{key[:4]}...{key[-4:]}"


def _default_system_prompt() -> str:
    return DEFAULT_SYSTEM_PROMPT


def ensure_llm_config(db: Session) -> LlmConfig:
    row = db.query(LlmConfig).filter(LlmConfig.id == PLATFORM_LLM_ID).first()
    if row:
        if getattr(row, "agent_chat_json", None) is None:
            from app.services.agent_chat_settings import DEFAULT_AGENT_CHAT

            row.agent_chat_json = dict(DEFAULT_AGENT_CHAT)
            row.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(row)
        return row

    has_env_key = bool(settings.deepseek_api_key.strip())
    row = LlmConfig(
        id=PLATFORM_LLM_ID,
        provider="deepseek",
        api_key=settings.deepseek_api_key.strip() or None,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        use_mock=settings.use_mock_ai or not has_env_key,
        temperature=0.2,
        max_tokens=2048,
        system_prompt=_default_system_prompt(),
        linked_skill_codes=DEFAULT_LINKED_SKILLS,
        agent_chat_json=None,
        updated_at=datetime.utcnow(),
    )
    from app.services.agent_chat_settings import DEFAULT_AGENT_CHAT

    row.agent_chat_json = dict(DEFAULT_AGENT_CHAT)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_effective_llm_config(db: Session | None = None) -> EffectiveLlmConfig:
    if db is not None:
        row = ensure_llm_config(db)
        db_key = (row.api_key or "").strip()
        env_key = settings.deepseek_api_key.strip()
        api_key = db_key or env_key
        api_key_source = "database" if db_key else ("environment" if env_key else "none")

        use_mock = row.use_mock
        if not use_mock and not api_key:
            use_mock = True

        return EffectiveLlmConfig(
            provider=row.provider or "deepseek",
            api_key=api_key,
            base_url=row.base_url or settings.deepseek_base_url,
            model=row.model or settings.deepseek_model,
            use_mock=use_mock,
            temperature=float(row.temperature if row.temperature is not None else 0.2),
            max_tokens=int(row.max_tokens or 800),
            system_prompt=(row.system_prompt or _default_system_prompt()).strip(),
            linked_skill_codes=list(row.linked_skill_codes or DEFAULT_LINKED_SKILLS),
            api_key_source=api_key_source,
            config_source="database",
        )

    env_key = settings.deepseek_api_key.strip()
    use_mock = settings.use_mock_ai or not env_key
    return EffectiveLlmConfig(
        provider="deepseek",
        api_key=env_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        use_mock=use_mock,
        temperature=0.2,
        max_tokens=2048,
        system_prompt=_default_system_prompt(),
        linked_skill_codes=DEFAULT_LINKED_SKILLS,
        api_key_source="environment" if env_key else "none",
        config_source="environment",
    )


MOCK_MODEL_IDS = frozenset({"mock-ai", "mock", ""})


def llm_runtime_ready(cfg: EffectiveLlmConfig) -> bool:
    """平台大模型中心已关闭 Mock 且 API Key 可用。"""
    return not cfg.use_mock and bool((cfg.api_key or "").strip())


def is_mock_model_route(model_id: str | None) -> bool:
    return not model_id or model_id in MOCK_MODEL_IDS


def resolve_agent_model_route(agent, *, intent: str, has_diff: bool) -> str | None:
    """读取 Agent 后台 model_route 配置。"""
    mc = agent.model_config_json or {}
    route = mc.get("model_route") or {}
    if not route:
        return None
    simple_model = route.get("simple")
    complex_model = route.get("complex")
    complex_intents = {"difference_explain", "dialog", "analyze", "agent_capabilities"}
    if has_diff or intent in complex_intents:
        return complex_model or simple_model
    return simple_model or complex_model


def agent_llm_invocation_ready(agent, db: Session, *, intent: str, has_diff: bool) -> tuple[EffectiveLlmConfig | None, str]:
    """Agent 选用真实大模型且平台已就绪时，返回平台 EffectiveLlmConfig（模型名以平台为准）。"""
    route_id = resolve_agent_model_route(agent, intent=intent, has_diff=has_diff) or "mock-ai"
    if is_mock_model_route(route_id):
        return None, route_id
    platform = get_effective_llm_config(db)
    if not llm_runtime_ready(platform):
        return None, route_id
    return platform, platform.model


def llm_config_to_out(row: LlmConfig, effective: EffectiveLlmConfig) -> dict[str, Any]:
    db_key = (row.api_key or "").strip()
    return {
        "id": row.id,
        "provider": row.provider,
        "base_url": row.base_url,
        "model": row.model,
        "use_mock": row.use_mock,
        "temperature": row.temperature,
        "max_tokens": row.max_tokens,
        "system_prompt": row.system_prompt or _default_system_prompt(),
        "linked_skill_codes": row.linked_skill_codes or DEFAULT_LINKED_SKILLS,
        "api_key_set": bool(effective.api_key),
        "api_key_preview": mask_api_key(effective.api_key),
        "api_key_source": effective.api_key_source,
        "effective_mode": "mock-ai" if effective.use_mock or not effective.api_key else effective.model,
        "runtime_ready": not effective.use_mock and bool(effective.api_key),
        "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
        "updated_by": row.updated_by,
        "model_presets": DEEPSEEK_MODEL_PRESETS,
        "agent_chat": _agent_chat_out(row),
    }


def _agent_chat_out(row: LlmConfig) -> dict[str, Any]:
    from app.services.agent_chat_settings import DEFAULT_AGENT_CHAT, _merge_agent_chat

    return _merge_agent_chat(getattr(row, "agent_chat_json", None) or DEFAULT_AGENT_CHAT)


def update_llm_config(db: Session, payload: dict[str, Any], user_id: str | None) -> tuple[LlmConfig, EffectiveLlmConfig]:
    row = ensure_llm_config(db)

    if "provider" in payload and payload["provider"]:
        row.provider = payload["provider"]
    if "base_url" in payload and payload["base_url"]:
        row.base_url = payload["base_url"].strip()
    if "model" in payload and payload["model"]:
        row.model = payload["model"].strip()
    if "use_mock" in payload and payload["use_mock"] is not None:
        row.use_mock = bool(payload["use_mock"])
    if "temperature" in payload and payload["temperature"] is not None:
        row.temperature = float(payload["temperature"])
    if "max_tokens" in payload and payload["max_tokens"] is not None:
        row.max_tokens = int(payload["max_tokens"])
    if "system_prompt" in payload and payload["system_prompt"] is not None:
        row.system_prompt = payload["system_prompt"].strip() or _default_system_prompt()
    if "linked_skill_codes" in payload and payload["linked_skill_codes"] is not None:
        row.linked_skill_codes = list(payload["linked_skill_codes"])
    if "agent_chat" in payload and payload["agent_chat"] is not None:
        from app.services.agent_chat_settings import DEFAULT_AGENT_CHAT

        current = dict(getattr(row, "agent_chat_json", None) or DEFAULT_AGENT_CHAT)
        incoming = payload["agent_chat"]
        if isinstance(incoming, dict):
            current.update({k: v for k, v in incoming.items() if v is not None})
        row.agent_chat_json = current

    if "api_key" in payload:
        raw = payload["api_key"]
        if raw is None:
            pass
        elif raw == "":
            row.api_key = None
        else:
            row.api_key = str(raw).strip()

    row.updated_by = user_id
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    effective = get_effective_llm_config(db)
    return row, effective


async def test_llm_connection(cfg: EffectiveLlmConfig) -> dict[str, Any]:
    if cfg.use_mock:
        return {
            "ok": True,
            "mode": "mock",
            "message": "当前为模拟模式，不会发起真实 API 调用",
            "model": "mock-ai",
        }
    if not cfg.api_key:
        return {
            "ok": False,
            "mode": "unconfigured",
            "message": "未配置 API Key，请填写 DeepSeek API Key 或开启模拟模式",
        }

    url = f"{cfg.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": "你是测试助手，仅回复 OK。"},
            {"role": "user", "content": "ping"},
        ],
        "stream": False,
        "max_tokens": 16,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
        content = (
            (body.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            or (body.get("choices") or [{}])[0]
            .get("message", {})
            .get("reasoning_content", "")
        )
        return {
            "ok": True,
            "mode": "real",
            "message": f"连接成功，模型 {cfg.model} 已响应",
            "model": cfg.model,
            "sample_reply": str(content).strip()[:120],
        }
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300] if exc.response is not None else str(exc)
        return {
            "ok": False,
            "mode": "error",
            "message": f"HTTP {exc.response.status_code}: {detail}",
            "model": cfg.model,
        }
    except Exception as exc:
        return {
            "ok": False,
            "mode": "error",
            "message": str(exc),
            "model": cfg.model,
        }
