# File: app/services/chat_agent_bridge.py
"""
生产对话 SSE 桥接：在保留 agent_runtime（UI 块 / 意图）前提下，接入 PlatformAgentEngine 流式事件。

优先级说明见 agent_platform/README.md § 改造路线图
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from agent_platform.agent.agent_engine import PlatformAgentEngine
from app.models import Conversation, Difference, Task, User
from app.schemas import ChatRequest
from app.services.agent_chat_settings import get_effective_agent_chat_settings
from app.services.agent_runtime import run_agent_turn
from app.services.agent_ui_blocks import (
    build_agent_capability_turn_blocks,
    build_difference_explain_block,
    build_skill_invoke_block,
    build_task_detail_block,
    build_task_list_block,
    reply_looks_like_markdown_table,
    short_intro_from_reply,
    strip_markdown_tables,
)
from app.services.chat_actions import execute_reconciliation_from_chat, wants_execute_recommended
from app.services.llm_config_service import llm_runtime_ready, get_effective_llm_config


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _map_platform_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """将 platform agent 事件映射为对话 SSE 协议（对齐 SkillTestChat）。"""
    t = payload.get("type")
    if t == "tool_call_start":
        skill = payload.get("skill") or ""
        return {"type": "tool_call", "skill_id": skill, "skill_name": skill, "input": {}}
    if t == "tool_call_end":
        skill = payload.get("skill") or ""
        preview = str(payload.get("output") or "")
        failed = any(
            mark in preview
            for mark in ("Skill 执行失败", "SkillExecutionFailed", "SkillExecutionError", "'error'")
        )
        return {
            "type": "tool_call",
            "skill_id": skill,
            "skill_name": skill,
            "output": {"preview": preview},
            "success": not failed,
        }
    if t == "thinking":
        return {"type": "thinking", "content": payload.get("content") or ""}
    if t == "answer":
        return {"type": "reply", "content": payload.get("content") or ""}
    if t == "done":
        return {"type": "done"}
    return payload


def _reply_looks_like_skill_dump(text: str) -> bool:
    """Platform Agent 常输出 Markdown 表格描述 Skill 结果，应由 UI 卡片替代。"""
    import re

    t = (text or "").strip()
    if len(t) < 60:
        return False
    if re.search(r"\|[^\n]+\|", t) and re.search(r"字段|任务名称|当前状态|流水线|建议下一步", t):
        return True
    return bool(re.search(r"query_tasks|review_flow|anomaly_explain", t, re.I) and "---" in t)


def _summarize_tool_preview(preview: str) -> str:
    """将 tool 原始输出转为简短摘要，避免 UI 展示 JSON 字符串。"""
    import re

    raw = (preview or "").strip()
    if not raw:
        return "执行完成"
    m = re.search(r'"total"\s*:\s*(\d+)', raw)
    if m:
        return f"返回 {m.group(1)} 条任务"
    if len(raw) > 80:
        return "执行完成"
    return raw


def _ui_blocks_from_platform_tools(
    db: Session,
    user: User,
    tool_events: list[dict[str, Any]],
    *,
    task_id: str | None,
    task: Task | None,
) -> list[dict]:
    from app.services.agent_runtime import _fetch_tasks

    invoked_by_code: dict[str, dict[str, Any]] = {}
    for ev in tool_events:
        out = ev.get("output") or {}
        if not out:
            continue
        skill_raw = str(ev.get("skill_id") or ev.get("skill_name") or "")
        code = skill_raw.replace("skill-", "")
        if not code or ev.get("success") is False:
            continue
        preview = str(out.get("preview") or "")
        invoked_by_code[code] = {
            "skill_code": code,
            "skill_id": skill_raw if skill_raw.startswith("skill-") else f"skill-{code}",
            "success": True,
            "summary": _summarize_tool_preview(preview),
        }
    invoked = list(invoked_by_code.values())
    if not invoked:
        return []
    blocks: list[dict] = [build_skill_invoke_block(invoked)]
    focus = task
    if not focus and task_id:
        focus = db.query(Task).filter(Task.id == task_id).first()
    if focus:
        blocks.append(build_task_detail_block(focus))
    else:
        tasks = _fetch_tasks(db, user, limit=6)
        if tasks:
            blocks.append(build_task_list_block(tasks))
    return blocks


def _parse_sse_data_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _should_use_platform_stream(
    db: Session,
    *,
    body: ChatRequest,
    has_diff_context: bool,
    client_action: str | None,
) -> bool:
    """开放问答与（可选）差异解释走 PlatformAgentEngine；对账卡片等仍走 agent_runtime。"""
    from app.services.agent_runtime import (
        _needs_open_qa_runtime,
        _topic_wants_capability_card,
        _wants_knowledge_query,
        classify_intent_by_rules,
    )

    agent_cfg = get_effective_agent_chat_settings(db)
    if not agent_cfg.enabled:
        return False
    if not llm_runtime_ready(get_effective_llm_config(db)):
        return False
    if client_action:
        return False
    if wants_execute_recommended(body.message):
        return False
    # 知识库检索、任务列表、能力清单等由 agent_runtime 真实编排（含检索命中卡片）
    msg = (body.message or "").strip()
    if _topic_wants_capability_card(msg) or _needs_open_qa_runtime(msg):
        return False
    rule_intent, _ = classify_intent_by_rules(
        msg,
        has_diff_context=has_diff_context,
        client_action=client_action,
    )
    if rule_intent in (
        "knowledge_query",
        "query_tasks",
        "agent_capabilities",
        "start_reconciliation",
        "faq_workflow",
        "faq_diff_types",
        "onboarding",
        "upload",
    ):
        return False
    if has_diff_context:
        return agent_cfg.diff_explain_via_agent
    return True


def _agent_extra_instructions(diff: Difference | None) -> str:
    base = (
        "禁止在回复中使用 Markdown 表格（| 列 | 形式）。能力说明由系统 UI 卡片展示，"
        "你只需简短自然语言导语。"
    )
    if not diff:
        return base
    return (
        f"{base}"
        "当前对话已绑定工作台差异，解释/归因/证据/处理建议类问题必须优先调用 "
        f"anomaly_explain(diff_id={diff.id})；需要原始事实时可调用 query_trace(diff_id={diff.id})。"
        "回答须与 Skill 返回一致，勿臆造未在 Observation 中出现的数据。"
    )


def _enrich_user_message_for_agent(
    message: str,
    *,
    context: dict | None,
    diff: Difference | None,
    task: Task | None,
) -> str:
    if not diff:
        if context and context.get("task_id"):
            return f"[任务上下文 task_id={context['task_id']}]\n{message}"
        return message
    lines = [
        "[差异上下文 — 已绑定工作台]",
        f"difference_id={diff.id}",
        f"task_id={diff.task_id or (task.id if task else '')}",
        f"type={diff.type}",
        f"business_key={diff.business_key or ''}",
        f"business_amount={diff.business_amount}",
        f"finance_amount={diff.finance_amount}",
        f"amount_diff={diff.amount_diff}",
    ]
    if diff.ai_explanation:
        lines.append(f"已有归因摘要={diff.ai_explanation[:200]}")
    lines.append(f"\n用户问题：{message}")
    return "\n".join(lines)


def _diff_explain_ui_blocks(
    db: Session,
    diff: Difference | None,
    task: Task | None,
) -> list[dict]:
    if not diff:
        return []
    row = db.query(Difference).filter(Difference.id == diff.id).first()
    if not row:
        return []
    evidence: list[str] = []
    if isinstance(row.evidence, dict):
        raw = row.evidence.get("items") or row.evidence.get("chain")
        if isinstance(raw, list):
            evidence = [str(x) for x in raw[:8]]
    rec = {
        "root_cause": row.ai_explanation or "",
        "suggested_action": row.suggestion or "",
        "confidence": float(row.confidence or 0),
        "responsible_party": row.responsible_party or "",
        "evidence": evidence,
        "model": "agent-anomaly_explain",
    }
    if not rec["root_cause"] and not rec["suggested_action"]:
        return []
    return [build_difference_explain_block(row, rec, task)]


async def stream_chat_turn(
    db: Session,
    user: User,
    body: ChatRequest,
    *,
    background_tasks: BackgroundTasks,
    build_context,
    ensure_conversation,
    append_messages,
    period_from_context,
    log_and_commit,
) -> AsyncIterator[str]:
    """
    流式对话：yield SSE 行（data: {...}\\n\\n）。
    build_context / ensure_conversation / append_messages 由 chat.py 注入，避免循环依赖。
    """
    context, task, diff, effective_task_id = build_context(body)

    conv = ensure_conversation(body, task)
    yield _sse({"type": "session", "conversation_id": conv.id, "agent_id": conv.agent_id})

    reply = ""
    intent: str | None = None
    ui_blocks: list = []
    task_id: str | None = None
    plan_steps: list = []
    active_agent_id = body.agent_id
    history = [m.model_dump() for m in body.history]
    has_diff_context = bool(diff)
    msg_stripped = (body.message or "").strip()
    from app.services.agent_runtime import (
        _needs_open_qa_runtime,
        _topic_wants_capability_card,
        _topic_wants_task_card,
        _wants_invoke_skills,
    )

    prefer_runtime = bool(
        body.client_action
        or _wants_invoke_skills(msg_stripped)
        or _topic_wants_capability_card(msg_stripped)
        or _topic_wants_task_card(msg_stripped)
        or _needs_open_qa_runtime(msg_stripped)
    )
    try:
        if not has_diff_context and wants_execute_recommended(body.message):
            period = period_from_context(body.message, history)
            from app.services.agent_config_service import resolve_agent

            agent = resolve_agent(db, agent_id=body.agent_id, user=user)
            active_agent_id = agent.id
            task, reply, ui_blocks = execute_reconciliation_from_chat(
                db,
                user,
                business_datasource_id=None,
                finance_datasource_id=None,
                demo_dataset_id=None,
                period=period,
                name=None,
                background_tasks=background_tasks,
                agent=agent,
            )
            intent = "execute_reconciliation"
            task_id = task.id
            if ui_blocks:
                yield _sse({"type": "ui_blocks", "blocks": ui_blocks})
            yield _sse({"type": "reply", "content": reply})
        elif not prefer_runtime and _should_use_platform_stream(
            db,
            body=body,
            has_diff_context=has_diff_context,
            client_action=body.client_action,
        ):
            from app.services.agent_config_service import resolve_agent

            agent = resolve_agent(db, agent_id=body.agent_id, user=user)
            active_agent_id = agent.id
            intent = "platform_agent_diff" if has_diff_context else "platform_agent"
            agent_cfg = get_effective_agent_chat_settings(db)
            engine = PlatformAgentEngine(
                db,
                use_langgraph=agent_cfg.use_langgraph,
                extra_instructions=_agent_extra_instructions(diff),
            )
            engine.session_id = conv.id or str(uuid.uuid4())

            ctx = {"task_id": effective_task_id, "user_id": user.id}
            if context:
                ctx.update({k: v for k, v in context.items() if v is not None})
            if diff:
                ctx["difference_id"] = diff.id

            user_msg = _enrich_user_message_for_agent(
                body.message,
                context=ctx,
                diff=diff,
                task=task,
            )

            platform_reply = ""
            reply_sent = False
            tool_events: list[dict[str, Any]] = []
            async for chunk in engine.stream_events(
                user_msg,
                context=ctx,
                workflow_task_id=effective_task_id,
            ):
                for line in chunk.split("\n"):
                    payload = _parse_sse_data_line(line)
                    if not payload:
                        continue
                    mapped = _map_platform_payload(payload)
                    if mapped.get("type") == "reply":
                        platform_reply = mapped.get("content") or ""
                        yield _sse(mapped)
                        reply_sent = True
                    elif mapped.get("type") == "thinking":
                        yield _sse(mapped)
                    elif mapped.get("type") == "tool_call":
                        tool_events.append(mapped)
                        if mapped.get("output"):
                            yield _sse(mapped)
                    elif mapped.get("type") not in ("done",):
                        yield _sse(mapped)
                    if payload.get("type") == "done":
                        break

            tool_blocks = _ui_blocks_from_platform_tools(
                db,
                user,
                tool_events,
                task_id=effective_task_id,
                task=task,
            )
            ui_blocks = tool_blocks or []
            platform_reply = platform_reply.strip()

            if reply_looks_like_markdown_table(platform_reply):
                cap_blocks = build_agent_capability_turn_blocks(
                    agent, db, has_diff=has_diff_context,
                )
                has_cap_ui = any(
                    b.get("type") in ("agent_capability_overview", "capability_list")
                    for b in ui_blocks
                )
                if not has_cap_ui:
                    ui_blocks = cap_blocks + ui_blocks
                intro = short_intro_from_reply(platform_reply)
                reply = intro or "我的能力见下方卡片，可直接点击发起操作。"
            elif tool_blocks:
                if _reply_looks_like_skill_dump(platform_reply):
                    reply = "已调用 Skill，结果见下方卡片。"
                else:
                    reply = strip_markdown_tables(platform_reply) or "已调用 Skill，结果见下方卡片。"
            else:
                reply = strip_markdown_tables(platform_reply) or "（暂无回复）"

            if ui_blocks:
                yield _sse({"type": "ui_blocks", "blocks": ui_blocks})
            if reply_sent and reply != platform_reply:
                yield _sse({"type": "reply", "content": reply})
            if has_diff_context:
                diff_blocks = _diff_explain_ui_blocks(db, diff, task)
                if diff_blocks:
                    ui_blocks = (ui_blocks or []) + diff_blocks
                    yield _sse({"type": "ui_blocks", "blocks": ui_blocks})
            if not reply_sent:
                yield _sse({"type": "reply", "content": reply})
        else:
            from app.services.agent_config_service import resolve_agent

            agent = resolve_agent(db, agent_id=body.agent_id, user=user)
            active_agent_id = agent.id
            reply, intent, ui_blocks, plan_steps = await run_agent_turn(
                db,
                agent=agent,
                user=user,
                message=body.message,
                history=history,
                context=context,
                conversation_id=conv.id,
                client_action=body.client_action,
            )
            if plan_steps:
                yield _sse({"type": "plan", "steps": plan_steps})
            if ui_blocks:
                yield _sse({"type": "ui_blocks", "blocks": ui_blocks})
            yield _sse({"type": "reply", "content": reply})

        append_messages(
            conv,
            body.message,
            reply,
            ui_blocks=ui_blocks or None,
            task_id=task_id,
            plan_steps=plan_steps or None,
        )
        if task_id:
            conv.task_id = task_id
        elif task and not conv.task_id:
            conv.task_id = task.id

        log_and_commit(conv, body, intent, task_id, task)

        yield _sse({
            "type": "done",
            "conversation_id": conv.id,
            "intent": intent,
            "task_id": task_id,
            "agent_id": conv.agent_id or active_agent_id,
            "engine": "platform" if str(intent or "").startswith("platform_agent") else "runtime",
        })
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        yield _sse({"type": "error", "error": str(exc)})
        yield _sse({"type": "done", "conversation_id": conv.id})
