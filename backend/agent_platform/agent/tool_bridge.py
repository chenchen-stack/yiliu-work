"""Convert SkillRegistry entries into Agent tools (OpenAI function schema)."""

from __future__ import annotations

from typing import Any

from agent_platform.core.executor import SkillExecutor
from agent_platform.core.registry import skill_registry
from agent_platform.models.skill import SkillMeta


def _json_schema_from_example(schema: dict[str, Any]) -> dict[str, Any]:
    """Build OpenAI parameters schema from skill.md example object."""
    if not schema:
        return {"type": "object", "properties": {}, "additionalProperties": True}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for key, val in schema.items():
        prop: dict[str, Any] = {"description": f"参数 {key}"}
        if isinstance(val, bool):
            prop["type"] = "boolean"
        elif isinstance(val, int):
            prop["type"] = "integer"
        elif isinstance(val, float):
            prop["type"] = "number"
        elif isinstance(val, dict):
            prop["type"] = "object"
        elif isinstance(val, list):
            prop["type"] = "array"
        else:
            prop["type"] = "string"
        properties[key] = prop
        required.append(key)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


def skill_to_tool_definition(meta: SkillMeta) -> dict[str, Any]:
    """Map one SkillMeta to OpenAI tool / function definition."""
    tool_name = meta.package_code
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": meta.description or meta.name,
            "parameters": _json_schema_from_example(meta.input_schema),
        },
    }


def build_tool_catalog() -> list[dict[str, Any]]:
    """All skills as tool definitions for the Agent."""
    tools = [skill_to_tool_definition(m) for m in skill_registry.list_all()]
    tools.append(_query_trace_tool())
    return tools


def _query_trace_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "query_trace",
            "description": "按 trace_id 或 diff_id 查询执行 Trace 与差异上下文",
            "parameters": {
                "type": "object",
                "properties": {
                    "trace_id": {"type": "string"},
                    "diff_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    }


def _resolve_skill_context(
    db,
    arguments: dict[str, Any],
    skill_context: Any | None,
    *,
    chat_context: dict[str, Any] | None = None,
) -> Any | None:
    if skill_context is not None:
        return skill_context
    chat = chat_context or {}
    task_id = arguments.get("task_id") or chat.get("task_id")
    user_id = arguments.get("user_id") or chat.get("user_id")
    if not db:
        return None
    from app.services.skill_platform_runner import build_chat_skill_context

    return build_chat_skill_context(
        db,
        user_id=str(user_id) if user_id else None,
        task_id=str(task_id) if task_id else None,
    )


def _merge_tool_arguments(
    arguments: dict[str, Any],
    chat_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """把对话上下文中的 task_id / diff_id / user_id 注入工具参数。"""
    merged = dict(arguments or {})
    chat = chat_context or {}
    if chat.get("task_id") and not merged.get("task_id"):
        merged["task_id"] = chat["task_id"]
    if chat.get("difference_id") and not merged.get("diff_id"):
        merged["diff_id"] = chat["difference_id"]
    if chat.get("user_id") and not merged.get("user_id"):
        merged["user_id"] = chat["user_id"]
    return merged


async def invoke_tool(
    db,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    agent_session_id: str | None = None,
    skill_context: Any | None = None,
    chat_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute tool — Skill Executor or query_trace."""
    args = _merge_tool_arguments(arguments, chat_context)
    if tool_name == "query_trace":
        return await _invoke_query_trace(db, args)

    ctx = _resolve_skill_context(db, args, skill_context, chat_context=chat_context)
    executor = SkillExecutor(db)
    return await executor.run(
        tool_name,
        args,
        agent_session_id=agent_session_id,
        skill_context=ctx,
    )


async def _invoke_query_trace(db, args: dict[str, Any]) -> dict[str, Any]:
    from agent_platform.core.tracer import SkillTracer
    from app.models import Difference

    tracer = SkillTracer(db)
    if args.get("trace_id"):
        hit = tracer.get(args["trace_id"])
        return {"trace": hit}

    diff_id = args.get("diff_id")
    if diff_id and db is not None:
        row = db.query(Difference).filter(Difference.id == diff_id).first()
        if row:
            return {
                "diff": {
                    "id": row.id,
                    "type": row.type,
                    "business_key": row.business_key,
                    "business_amount": row.business_amount,
                    "finance_amount": row.finance_amount,
                    "ai_explanation": row.ai_explanation,
                    "evidence_chain": row.evidence_chain,
                },
            }
    return {"error": "未找到 trace 或 diff"}
