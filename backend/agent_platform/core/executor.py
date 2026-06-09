"""Skill Executor — strategy by skill_type, retries, trace."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.orm import Session

from agent_platform.config import platform_settings
from agent_platform.core.registry import skill_registry
from agent_platform.core.tracer import SkillTracer
from agent_platform.exceptions import SkillExecutionFailed
from agent_platform.logging_setup import get_logger
from agent_platform.models.skill import SkillMeta
from agent_platform.services import rag_service
from agent_platform.services.llm_gateway import chat_completion

logger = get_logger("executor")


class SkillExecutor:
    """Execute skills via process / ability / knowledge strategies."""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db
        self.tracer = SkillTracer(db)

    async def run(
        self,
        skill_id: str,
        input_params: dict[str, Any],
        *,
        workflow_id: str | None = None,
        agent_session_id: str | None = None,
        node_name: str | None = None,
        skill_context: Any | None = None,
    ) -> dict[str, Any]:
        """Run skill with retries and trace."""
        meta = skill_registry.get(skill_id)
        node = node_name or meta.package_code
        trace = self.tracer.start(
            skill_id=meta.skill_id,
            node_name=node,
            input_data=input_params,
            workflow_id=workflow_id,
            agent_session_id=agent_session_id,
        )

        last_err: str | None = None
        max_retries = platform_settings.skill_executor_max_retries
        for attempt in range(1, max_retries + 1):
            try:
                output = await self._dispatch(meta, input_params, skill_context=skill_context)
                self.tracer.finish(trace, output=output, status="success")
                return {"skill_id": meta.skill_id, "output": output, "trace_id": trace.trace_id}
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                logger.warning(
                    "skill attempt failed",
                    extra_fields={
                        "skill_id": meta.skill_id,
                        "attempt": attempt,
                        "error": last_err,
                    },
                )
                if attempt < max_retries:
                    await asyncio.sleep(platform_settings.skill_executor_retry_delay_sec)

        self.tracer.finish(trace, output={}, status="failed", error=last_err)
        raise SkillExecutionFailed(meta.skill_id, last_err or "unknown")

    async def _dispatch(
        self,
        meta: SkillMeta,
        params: dict[str, Any],
        *,
        skill_context: Any | None,
    ) -> dict[str, Any]:
        if meta.skill_type == "knowledge":
            return await self._run_knowledge(meta, params)
        if meta.skill_type == "process":
            return await self._run_process(meta, params, skill_context=skill_context)
        return await self._run_ability(meta, params, skill_context=skill_context)

    async def _run_process(
        self,
        meta: SkillMeta,
        params: dict[str, Any],
        *,
        skill_context: Any | None,
    ) -> dict[str, Any]:
        """Process type: record each step, delegate final work to handler."""
        steps_trace: list[dict[str, Any]] = []
        for idx, step in enumerate(meta.execution_steps or ["执行"], start=1):
            steps_trace.append({"step": idx, "description": step, "status": "done"})

        handler_out = await self._invoke_handler(meta.package_code, params, skill_context=skill_context)
        return {
            "type": "process",
            "steps": steps_trace,
            "result": handler_out,
        }

    async def _run_ability(
        self,
        meta: SkillMeta,
        params: dict[str, Any],
        *,
        skill_context: Any | None,
    ) -> dict[str, Any]:
        code = meta.package_code

        if code == "anomaly_explain":
            return await self._ability_anomaly_explain(params)

        if code == "query_tasks":
            return await self._ability_query_tasks(params, skill_context=skill_context)

        result = await self._invoke_handler(code, params, skill_context=skill_context)
        return {"type": "ability", "result": result}

    async def _run_knowledge(self, meta: SkillMeta, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query") or params.get("q") or ""
        top_k = int(params.get("top_k") or params.get("top_k_rag") or 5)
        kb_ids = params.get("knowledge_base_ids")
        hits = await rag_service.search(
            query,
            top_k=top_k,
            knowledge_base_ids=kb_ids,
            db=self.db,
        )
        return {"type": "knowledge", "query": query, "hits": hits, "count": len(hits)}

    async def _invoke_handler(
        self,
        package_code: str,
        params: dict[str, Any],
        *,
        skill_context: Any | None,
    ) -> dict[str, Any]:
        from app.services.skill_registry import SkillContext, SkillExecutionError, get_handler, is_async

        if skill_context is None:
            raise SkillExecutionFailed(
                package_code,
                "流程/能力型 Skill 需要 SkillContext（请通过 Workflow 引擎调用）",
            )

        if not hasattr(skill_context, "task"):
            raise SkillExecutionFailed(package_code, "无效的 SkillContext")

        try:
            handler = get_handler(package_code)
        except SkillExecutionError as exc:
            raise SkillExecutionFailed(package_code, str(exc)) from exc

        if is_async(package_code):
            return await handler(skill_context)
        return handler(skill_context)

    async def _ability_query_tasks(
        self,
        params: dict[str, Any],
        *,
        skill_context: Any | None,
    ) -> dict[str, Any]:
        """对话内任务列表查询 — 可在无 Workflow 上下文时仅用 DB 执行。"""
        from app.services.skill_platform_runner import build_chat_skill_context
        from app.services.skill_registry import skill_query_tasks

        ctx = skill_context
        if ctx is None and self.db is not None:
            ctx = build_chat_skill_context(
                self.db,
                user_id=params.get("user_id"),
                task_id=params.get("task_id"),
            )
        if ctx is None:
            raise SkillExecutionFailed("query_tasks", "无法构建 SkillContext")
        result = skill_query_tasks(ctx)
        return {"type": "ability", "result": result}

    async def _ability_anomaly_explain(self, params: dict[str, Any]) -> dict[str, Any]:
        """Single diff explain — RAG + LLM or existing analyzer."""
        diff_id = params.get("diff_id")
        if self.db and diff_id:
            from app.models import Difference
            from app.services.ai_analyzer import analyze_difference, build_evidence_chain

            row = self.db.query(Difference).filter(Difference.id == diff_id).first()
            if row:
                item = {
                    "id": row.id,
                    "type": row.type,
                    "business_key": row.business_key,
                    "business_amount": row.business_amount,
                    "finance_amount": row.finance_amount,
                    "amount_diff": (row.business_amount or 0) - (row.finance_amount or 0),
                }
                top_k = int(params.get("top_k_rag") or 5)
                query = f"{row.business_key} {row.type} 差额{item['amount_diff']}"
                hits = await rag_service.search(query, top_k=top_k, db=self.db)
                rec = await analyze_difference(item, db=self.db)
                evidence = build_evidence_chain(item, rec)
                return {
                    "diff_id": diff_id,
                    "root_cause": rec.get("root_cause") or rec.get("attribution"),
                    "suggested_action": rec.get("suggested_action"),
                    "confidence": rec.get("confidence", 0.0),
                    "evidence_chain": evidence,
                    "rag_hits": len(hits),
                    "status": "ok",
                }

        # Fallback prompt-only path
        prompt = (
            f"请对以下差异做归因分析，返回 JSON 含 attribution, confidence, reasoning:\n"
            f"{params}"
        )
        text = await chat_completion(
            [{"role": "user", "content": prompt}],
            model=params.get("model"),
        )
        return {"diff_id": diff_id, "raw": text, "status": "ok"}
