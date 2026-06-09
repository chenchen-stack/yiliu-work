"""对话式 Skill 测试 Agent — ReAct 规划 + 流式事件。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, AsyncGenerator

from sqlalchemy.orm import Session

from agent_platform.core.registry import skill_registry
from agent_platform.services.llm_gateway import chat_completion, json_completion
from app.config import settings as app_settings
from agent_platform.config import platform_settings
from app.services.skill_platform_runner import execute_skill_unified, get_sample_input
from app.services.skill_test_chat_context import ChatContext, chat_store, resolve_skill_test_task_id

_PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "agent_platform"
    / "agent"
    / "prompts"
    / "test_agent_system_prompt.md"
)

PRESET_MESSAGES: dict[str, str] = {
    "full_reconciliation": (
        "帮我执行方太2026年5月份的对账，数据在 /data/fangtai/202605/ 目录下"
    ),
    "diff_only": "导入批次 imp-20260604-001 的对账跑完了吗？只给我看看差异的部分",
    "single_attribution": "帮我分析一下差异 D-20260604-001 是什么原因",
    "review_simulation": (
        "差异 D-001 确认是手续费，D-003 我质疑——看起来更像是汇率差异"
    ),
    "generate_report": "帮我把这次对账的结果生成一份 PDF 报告",
}

_SKILL_CHAIN = ["data_import", "field_mapping", "difference_detect"]


def _load_system_prompt() -> str:
    if _PROMPT_PATH.is_file():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return "你是方太对账 Skill 测试助手。"


def _skill_catalog_lines(focus: str | None) -> str:
    lines = []
    for meta in skill_registry.list_all():
        code = meta.package_code
        if focus and code not in (focus, *_SKILL_CHAIN) and focus not in _SKILL_CHAIN:
            if code != focus and focus not in ("anomaly_explain", "review_flow", "re_verify", "report_gen"):
                continue
        lines.append(f"- {code}: {meta.name} — {meta.description or ''}")
    return "\n".join(lines) or "- （无已注册 Skill）"


def _summarize_output(skill_code: str, output: dict[str, Any]) -> str:
    if output.get("mode") == "dry_run":
        return "未绑定有效任务，请先在「工作台」创建对账任务后再测试。"
    inner = output.get("result") if isinstance(output.get("result"), dict) else output
    if not isinstance(inner, dict):
        inner = output

    if skill_code == "data_import":
        biz = inner.get("business_rows") or inner.get("records", {}).get("sap_invoice")
        fin = inner.get("finance_rows") or inner.get("records", {}).get("bank_receipt")
        iid = inner.get("import_id", "")
        return f"导入完成 import_id={iid}；业务侧 {biz or '—'} 条，财务侧 {fin or '—'} 条"
    if skill_code == "field_mapping":
        return (
            f"映射 {inner.get('mapped_count', inner.get('mapped', '—'))} 条，"
            f"未映射 {inner.get('unmapped_count', inner.get('unmapped', 0))} 条"
        )
    if skill_code == "difference_detect":
        return (
            f"比对 {inner.get('total_compared', '—')} 条："
            f"匹配 {inner.get('matched', '—')}，差异 {inner.get('differences', inner.get('difference_count', '—'))} 条"
        )
    if skill_code == "anomaly_explain":
        return (
            f"归因：{inner.get('attribution') or inner.get('root_cause', '—')}，"
            f"置信度 {inner.get('confidence', '—')}"
        )
    if skill_code == "report_gen":
        return f"报告已生成：{inner.get('report_url') or inner.get('report_id', '—')}"
    status = inner.get("status") or output.get("status")
    return f"执行完成（status={status or 'ok'}）"


def _mock_plan(user_message: str, ctx: ChatContext) -> dict[str, Any]:
    """无 LLM 时的规则规划。"""
    msg = user_message.lower()
    actions: list[dict[str, Any]] = []

    if any(k in msg for k in ("报告", "pdf", "导出")):
        actions.append({
            "type": "call_skill",
            "skill_id": "report_gen",
            "params": {"import_id": ctx.import_id or "imp-20260604-001", "format": "pdf"},
            "reasoning": "用户需要生成对账报告",
        })
    elif any(k in msg for k in ("复核", "确认", "退回", "质疑")):
        actions.append({
            "type": "call_skill",
            "skill_id": "review_flow",
            "params": {"import_id": ctx.import_id, "reviewer": "finance_demo"},
            "reasoning": "模拟财务复核流转",
        })
    elif any(k in msg for k in ("归因", "分析", "原因", "解释")) and (
        "差异" in msg or "d-" in msg or ctx.diff_ids
    ):
        diff_id = ctx.diff_ids[0] if ctx.diff_ids else "D-20260604-001"
        actions.append({
            "type": "call_skill",
            "skill_id": "anomaly_explain",
            "params": {"diff_id": diff_id, "top_k_rag": 5},
            "reasoning": "对差异做归因分析",
        })
    elif any(k in msg for k in ("差异", "不匹配", "只对")) and "导入" not in msg:
        actions.append({
            "type": "call_skill",
            "skill_id": "difference_detect",
            "params": {"import_id": ctx.import_id, "rule_set": "fangtai_default"},
            "reasoning": "用户只关心差异结果",
        })
    elif any(k in msg for k in ("对账", "核对", "5月", "五月", "月份", "导入", "执行")):
        sample = get_sample_input("data_import")
        actions.extend([
            {
                "type": "call_skill",
                "skill_id": "data_import",
                "params": sample or {"task_id": ctx.task_id},
                "reasoning": "先导入业务与财务数据",
            },
            {
                "type": "call_skill",
                "skill_id": "field_mapping",
                "params": {"mapping_config": "fangtai_v1"},
                "reasoning": "统一字段口径",
            },
            {
                "type": "call_skill",
                "skill_id": "difference_detect",
                "params": {"rule_set": "fangtai_default"},
                "reasoning": "识别差异",
            },
        ])
    elif ctx.focus_skill:
        sample = get_sample_input(ctx.focus_skill)
        actions.append({
            "type": "call_skill",
            "skill_id": ctx.focus_skill,
            "params": sample or {},
            "reasoning": f"按当前测试 Skill「{ctx.focus_skill}」执行",
        })
    else:
        return {
            "thinking": "暂未识别明确操作，先确认你的目标。",
            "actions": [],
            "ask_user": "你是想跑完整对账、只看差异、做单条归因，还是生成报告？可以直接说自然语言需求。",
        }

    return {
        "thinking": "已匹配方太对账测试路径，将按顺序调用 Skill。",
        "actions": actions,
        "ask_user": None,
    }


class SkillTestAgent:
    """对话式 Skill 测试 Agent。"""

    def __init__(self, db: Session | None) -> None:
        self.db = db
        if not skill_registry.list_all():
            skill_registry.reload()

    async def chat(
        self,
        session_id: str,
        user_message: str,
        *,
        focus_skill: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        ctx = chat_store.get_or_create(session_id, focus_skill=focus_skill)
        if self.db and not ctx.task_id:
            tid = resolve_skill_test_task_id(self.db)
            if tid:
                ctx.task_id = tid
        ctx.extract_from_user_message(user_message)
        if self.db and (not ctx.task_id or ctx.task_id.upper().startswith("FT-")):
            tid = resolve_skill_test_task_id(self.db)
            if tid:
                ctx.task_id = tid
        ctx.append_message("user", user_message)

        yield {
            "type": "session",
            "session_id": ctx.session_id,
            "task_id": ctx.task_id,
        }

        yield {"type": "thinking", "content": "正在理解你的需求…"}
        plan = await self._plan(user_message, ctx)
        thinking = plan.get("thinking") or ""
        if thinking:
            yield {"type": "thinking", "content": thinking}

        ask = plan.get("ask_user")
        if ask and not plan.get("actions"):
            ctx.append_message("assistant", ask)
            yield {"type": "reply", "content": ask}
            return

        actions = plan.get("actions") or []
        for action in actions:
            if action.get("type") != "call_skill":
                continue
            skill_id = action.get("skill_id") or action.get("skill_code")
            if not skill_id:
                continue
            try:
                meta = skill_registry.get(skill_id)
                skill_name = meta.name
                package_code = meta.package_code
            except Exception:  # noqa: BLE001
                package_code = str(skill_id)
                skill_name = package_code

            reason = action.get("reasoning") or f"需要执行 {skill_name}"
            yield {"type": "thinking", "content": reason}

            params = ctx.merge_params(package_code, dict(action.get("params") or {}))
            start = time.perf_counter()
            try:
                result = await execute_skill_unified(
                    self.db,
                    package_code,
                    params,
                    task_id=ctx.task_id,
                )
                duration_ms = int((time.perf_counter() - start) * 1000)
                out_payload = result.output if result.success else {"error": result.error}
                if result.success:
                    ctx.ingest_skill_output(package_code, out_payload)
                summary = _summarize_output(package_code, out_payload)
                if result.error:
                    summary = f"执行失败：{result.error}"

                yield {
                    "type": "tool_call",
                    "skill_id": package_code,
                    "skill_name": skill_name,
                    "input": params,
                    "output": out_payload,
                    "success": result.success,
                    "duration_ms": duration_ms,
                    "summary": summary,
                }
                ctx.append_message(
                    "tool",
                    summary,
                    skill_id=package_code,
                    output=out_payload,
                )
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.perf_counter() - start) * 1000)
                err_msg = str(exc)
                yield {
                    "type": "error",
                    "skill_id": package_code,
                    "error": err_msg,
                    "duration_ms": duration_ms,
                }
                ctx.append_message("tool", err_msg, skill_id=package_code, error=err_msg)

        yield {"type": "thinking", "content": "正在整理回复…"}
        reply = await self._final_reply(ctx, user_message)
        ctx.append_message("assistant", reply)
        yield {"type": "reply", "content": reply}

    async def _plan(self, user_message: str, ctx: ChatContext) -> dict[str, Any]:
        use_mock = platform_settings.use_mock_llm or app_settings.use_mock_ai
        if use_mock and not (platform_settings.litellm_api_key or app_settings.deepseek_api_key):
            return _mock_plan(user_message, ctx)

        system = _load_system_prompt()
        catalog = _skill_catalog_lines(ctx.focus_skill)
        focus_line = ""
        if ctx.focus_skill:
            focus_line = f"\n当前在 Skill 库中测试「{ctx.focus_skill}」，优先满足与此 Skill 相关的请求。\n"
        user_block = (
            f"对话上下文：{ctx.context_hint()}\n"
            f"{focus_line}\n"
            f"已注册 Skill：\n{catalog}\n\n"
            f"用户消息：{user_message}\n\n"
            "请输出规划 JSON（thinking, actions, ask_user）。"
        )
        try:
            data = await json_completion(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_block},
                ],
            )
            if isinstance(data, dict) and (data.get("actions") is not None or data.get("ask_user")):
                return data
        except Exception:  # noqa: BLE001
            pass
        return _mock_plan(user_message, ctx)

    async def _final_reply(self, ctx: ChatContext, user_message: str) -> str:
        tool_msgs = [
            m for m in ctx.messages if m.get("role") == "tool"
        ]
        if not tool_msgs:
            return "我还没有执行任何操作。你可以描述想完成的步骤，例如「帮我跑 5 月份对账」或「分析刚才的差异」。"

        observations = "\n".join(f"- {m.get('content', '')}" for m in tool_msgs[-8:])
        use_mock = platform_settings.use_mock_llm or app_settings.use_mock_ai
        if use_mock and not (platform_settings.litellm_api_key or app_settings.deepseek_api_key):
            last = tool_msgs[-1].get("content", "")
            if "差异" in observations and "anomaly" not in user_message.lower():
                return (
                    f"{observations}\n\n"
                    "以上是根据 Skill 执行结果的摘要。需要我对差异逐条做归因分析吗？"
                )
            return f"已完成处理。\n\n{observations}\n\n还需要我继续做什么？"

        prompt = (
            "根据以下 Skill 执行观察，用简洁中文回复用户。不要暴露 JSON 字段名。\n"
            f"用户原话：{user_message}\n"
            f"观察：\n{observations}\n"
        )
        text = await chat_completion(
            [
                {"role": "system", "content": "你是方太对账助手，只根据观察如实总结。"},
                {"role": "user", "content": prompt},
            ],
        )
        return text.strip() or observations
