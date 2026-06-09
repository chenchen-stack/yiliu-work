"""Agent ReAct loop — Thought → Action (Tool/Skill) → Observation."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from agent_platform.agent.prompt_builder import build_system_prompt
from agent_platform.agent.tool_bridge import build_tool_catalog, invoke_tool
from agent_platform.logging_setup import get_logger
from agent_platform.services.llm_gateway import chat_completion

logger = get_logger("agent_loop")

_MAX_STEPS = 8


class AgentLoop:
    """Lightweight ReAct agent; all capabilities via Skill tools."""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db
        self.session_id = str(uuid.uuid4())

    async def run(
        self,
        user_message: str,
        *,
        context: dict[str, Any] | None = None,
        extra_instructions: str = "",
    ) -> dict[str, Any]:
        """Run ReAct until final answer or max steps."""
        system = build_system_prompt(extra_instructions=extra_instructions)
        tools = build_tool_catalog()
        tool_names = {t["function"]["name"] for t in tools}

        history: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        steps: list[dict[str, Any]] = []

        for step_idx in range(1, _MAX_STEPS + 1):
            planner_prompt = _planner_user_prompt(history, tools, step_idx)
            raw = await chat_completion(
                [{"role": "system", "content": _planner_system()}, {"role": "user", "content": planner_prompt}],
            )
            decision = _parse_decision(raw)
            steps.append({"step": step_idx, "thought": decision.get("thought"), "action": decision})

            if decision.get("action") == "finish":
                answer = decision.get("answer") or decision.get("content") or raw
                return {
                    "session_id": self.session_id,
                    "answer": answer,
                    "steps": steps,
                }

            tool_name = decision.get("tool") or decision.get("skill")
            if tool_name and tool_name in tool_names | {"query_trace"}:
                args = decision.get("arguments") or decision.get("input") or {}
                if context:
                    if context.get("task_id") and "task_id" not in args:
                        args.setdefault("task_id", context["task_id"])
                    if context.get("difference_id") and "diff_id" not in args:
                        args.setdefault("diff_id", context["difference_id"])
                    if context.get("user_id") and "user_id" not in args:
                        args.setdefault("user_id", context["user_id"])
                try:
                    obs = await invoke_tool(
                        self.db,
                        tool_name,
                        args,
                        agent_session_id=self.session_id,
                        chat_context=context,
                    )
                except Exception as exc:  # noqa: BLE001
                    obs = {"error": str(exc)}
                steps[-1]["observation"] = obs
                history.append(
                    {
                        "role": "assistant",
                        "content": json.dumps(decision, ensure_ascii=False),
                    }
                )
                history.append(
                    {
                        "role": "user",
                        "content": f"Observation: {json.dumps(obs, ensure_ascii=False)[:4000]}",
                    }
                )
                continue

            # No valid tool — treat model text as final
            return {
                "session_id": self.session_id,
                "answer": raw,
                "steps": steps,
            }

        return {
            "session_id": self.session_id,
            "answer": "已达到最大推理步数，请缩小问题范围后重试。",
            "steps": steps,
        }


def _planner_system() -> str:
    return (
        "你是规划器。仅输出 JSON，字段：thought, action, tool(可选), arguments(可选), answer(当 action=finish)。"
        "action 取值：call_tool | finish。"
    )


def _planner_user_prompt(history: list[dict[str, str]], tools: list[dict], step: int) -> str:
    tool_list = ", ".join(t["function"]["name"] for t in tools)
    hist = "\n".join(f"{m['role']}: {m['content'][:800]}" for m in history[-6:])
    return (
        f"Step {step}. 可用工具: {tool_list}, query_trace.\n"
        f"对话历史:\n{hist}\n"
        "若信息足够请 action=finish 并填写 answer；否则 action=call_tool 并指定 tool 与 arguments。"
    )


def _parse_decision(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if data.get("action") == "call_tool":
                data.setdefault("tool", data.get("skill"))
            return data
    except json.JSONDecodeError:
        pass
    return {"thought": raw, "action": "finish", "answer": raw}
