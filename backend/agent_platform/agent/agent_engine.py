# File: agent_platform/agent/agent_engine.py
"""
LangGraph ReAct agent — skills exposed as tools (create_react_agent when model available).

Falls back to AgentLoop (LiteLLM planner JSON) when ChatOpenAI is not configured.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

from sqlalchemy.orm import Session

from agent_platform.agent.agent_loop import AgentLoop
from agent_platform.agent.prompt_builder import build_system_prompt
from agent_platform.agent.tool_bridge import build_tool_catalog, invoke_tool
from agent_platform.config import platform_settings
from agent_platform.core.registry import skill_registry
from agent_platform.logging_setup import get_logger
from agent_platform.workflow.checkpoint import get_workflow_checkpointer
from agent_platform.workflow.state import AgentGraphState

logger = get_logger("agent_engine")


def _build_langchain_tools(db: Session | None, runtime: "PlatformAgentEngine | None" = None):
    """Wrap Skill registry + invoke_tool as LangChain StructuredTools."""
    from langchain_core.tools import StructuredTool

    tools = []

    async def _query_trace(trace_id: str = "", diff_id: str = "") -> dict:
        chat_ctx = runtime._runtime_context if runtime else None
        return await invoke_tool(
            db,
            "query_trace",
            {"trace_id": trace_id, "diff_id": diff_id},
            agent_session_id=runtime.session_id if runtime else None,
            chat_context=chat_ctx,
        )

    tools.append(
        StructuredTool.from_function(
            coroutine=_query_trace,
            name="query_trace",
            description="按 trace_id 或 diff_id 查询执行 Trace",
        )
    )

    for meta in skill_registry.list_all():
        code = meta.package_code
        desc = meta.description or meta.name

        def _make_runner(skill_code: str):
            async def _run_skill(**kwargs: Any) -> dict:
                chat_ctx = runtime._runtime_context if runtime else None
                return await invoke_tool(
                    db,
                    skill_code,
                    kwargs,
                    agent_session_id=runtime.session_id if runtime else None,
                    chat_context=chat_ctx,
                )

            return _run_skill

        tools.append(
            StructuredTool.from_function(
                coroutine=_make_runner(code),
                name=code,
                description=desc,
            )
        )
    return tools


def _chat_model(db: Session | None = None):
    """Return LangChain chat model from platform LLM config (DB → .env)."""
    from app.services.llm_config_service import get_effective_llm_config, llm_runtime_ready

    cfg = get_effective_llm_config(db)
    if not llm_runtime_ready(cfg):
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        logger.warning(f"langchain_openai unavailable: {exc}")
        return None

    return ChatOpenAI(
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url or None,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )


def build_react_agent(
    db: Session | None = None,
    *,
    checkpointer=None,
    extra_instructions: str = "",
    runtime: "PlatformAgentEngine | None" = None,
):
    """Compile LangGraph ReAct agent (skills → tools)."""
    from langgraph.prebuilt import create_react_agent

    model = _chat_model(db)
    if model is None:
        return None
    tools = _build_langchain_tools(db, runtime=runtime)
    cp = checkpointer if checkpointer is not None else get_workflow_checkpointer()
    try:
        return create_react_agent(
            model,
            tools,
            state_schema=AgentGraphState,
            checkpointer=cp,
            prompt=build_system_prompt(extra_instructions=extra_instructions),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"LangGraph create_react_agent failed: {exc}")
        return None


class PlatformAgentEngine:
    """Agent chat — LangGraph ReAct with AgentLoop fallback."""

    def __init__(
        self,
        db: Session | None = None,
        *,
        use_langgraph: bool | None = None,
        extra_instructions: str = "",
    ) -> None:
        self.db = db
        self.session_id = str(uuid.uuid4())
        self._extra_instructions = extra_instructions
        self._runtime_context: dict[str, Any] = {}
        use_lg = (
            platform_settings.use_langgraph_agent
            if use_langgraph is None
            else use_langgraph
        )
        self._graph = (
            build_react_agent(db, extra_instructions=extra_instructions, runtime=self)
            if use_lg
            else None
        )

    def _bind_runtime_context(self, context: dict[str, Any] | None, workflow_task_id: str | None) -> None:
        self._runtime_context = dict(context or {})
        if workflow_task_id:
            self._runtime_context.setdefault("task_id", workflow_task_id)

    async def run(self, user_message: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self._bind_runtime_context(context, context.get("task_id") if context else None)
        if self._graph is None:
            loop = AgentLoop(self.db)
            loop.session_id = self.session_id
            out = await loop.run(
                user_message,
                context=context,
                extra_instructions=self._extra_instructions,
            )
            return {**out, "engine": "agent_loop"}

        config = {"configurable": {"thread_id": self.session_id}}
        if context and context.get("task_id"):
            user_message = f"[任务上下文 task_id={context['task_id']}]\n{user_message}"

        result = await self._graph.ainvoke(
            {"messages": [{"role": "user", "content": user_message}], "session_id": self.session_id},
            config,
        )
        messages = result.get("messages") or []
        answer = messages[-1].content if messages else ""
        return {
            "session_id": self.session_id,
            "answer": answer if isinstance(answer, str) else str(answer),
            "engine": "langgraph_react",
            "raw": result,
        }

    async def stream_events(
        self,
        user_message: str,
        *,
        context: dict[str, Any] | None = None,
        workflow_task_id: str | None = None,
    ) -> AsyncIterator[str]:
        """SSE payloads aligned with prompt spec (thinking / tool_call / done)."""
        self._bind_runtime_context(context, workflow_task_id)
        if workflow_task_id and self.db is not None:
            from agent_platform.workflow.engine import PlatformWorkflowEngine

            try:
                wf_state = await PlatformWorkflowEngine(self.db).get_checkpoint_state(workflow_task_id)
                user_message = (
                    f"[当前Workflow上下文]\n任务: {workflow_task_id}\n"
                    f"状态: {wf_state.get('status')}\n差异数: {wf_state.get('diff_count', 0)}\n\n"
                    f"用户问题: {user_message}"
                )
            except Exception:  # noqa: BLE001
                pass

        if self._graph is None:
            loop = AgentLoop(self.db)
            loop.session_id = self.session_id
            result = await loop.run(
                user_message,
                context=context,
                extra_instructions=self._extra_instructions,
            )
            for step in result.get("steps") or []:
                thought = step.get("thought")
                if thought:
                    yield _sse({"type": "thinking", "content": str(thought)})
                action = step.get("action")
                if isinstance(action, dict) and action.get("action") == "call_tool":
                    tool = action.get("tool") or action.get("skill") or ""
                    yield _sse({"type": "tool_call_start", "skill": tool})
                    obs = step.get("observation")
                    if obs is not None:
                        yield _sse({
                            "type": "tool_call_end",
                            "skill": tool,
                            "output": obs if isinstance(obs, (dict, list)) else str(obs)[:2000],
                        })
            yield _sse({"type": "answer", "content": result.get("answer", "")})
            yield _sse({"type": "done"})
            return

        config = {"configurable": {"thread_id": self.session_id}}
        answer_buf: list[str] = []
        async for event in self._graph.astream_events(
            {"messages": [{"role": "user", "content": user_message}]},
            config,
            version="v2",
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                content = getattr(chunk, "content", "") if chunk else ""
                if content:
                    answer_buf.append(content if isinstance(content, str) else str(content))
                    yield _sse({"type": "thinking", "content": content})
            elif kind == "on_tool_start":
                yield _sse({"type": "tool_call_start", "skill": event.get("name")})
            elif kind == "on_tool_end":
                out = event.get("data", {}).get("output")
                preview = str(out)[:2000] if out is not None else ""
                yield _sse({"type": "tool_call_end", "skill": event.get("name"), "output": preview})
        if answer_buf:
            yield _sse({"type": "answer", "content": "".join(answer_buf)})
        yield _sse({"type": "done"})


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
