# File: agent_platform/workflow/engine.py
"""LangGraph workflow orchestration — Fangtai reconciliation (7 skills, conditional branches)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from agent_platform.config import platform_settings
from agent_platform.core.executor import SkillExecutor
from agent_platform.exceptions import WorkflowNotFoundError, WorkflowStateError
from agent_platform.logging_setup import get_logger
from agent_platform.models.trace import PlatformWorkflowORM
from agent_platform.workflow.checkpoint import get_workflow_checkpointer
from agent_platform.workflow.nodes import make_re_verify_node, make_skill_node, review_flow_node
from agent_platform.workflow.router import route_after_detect, route_after_review
from agent_platform.workflow.state import WorkflowGraphState
from app.models import Task, TaskStatus
from app.services.skill_registry import SkillContext
from app.services.workflow_engine import WorkflowEngine, current_ai_mode

logger = get_logger("workflow.engine")

NODE_DATA_IMPORT = "data_import"
NODE_FIELD_MAPPING = "field_mapping"
NODE_DIFFERENCE_DETECT = "difference_detect"
NODE_ANOMALY_EXPLAIN = "anomaly_explain"
NODE_REVIEW_FLOW = "review_flow"
NODE_RE_VERIFY = "re_verify"
NODE_REPORT_GEN = "report_gen"


def build_fangtai_workflow(
    db: Session,
    *,
    skill_context_factory: Callable[[], SkillContext | None],
    checkpointer=None,
):
    """
    Build方太对账 LangGraph:
    data_import → field_mapping → difference_detect
      → (has_diffs) anomaly_explain → review_flow → (all_confirmed) report_gen
      → (no_diffs) report_gen
      → (has_returned) re_verify → review_flow
    """
    graph = StateGraph(WorkflowGraphState)

    graph.add_node(NODE_DATA_IMPORT, make_skill_node(db, package_code=NODE_DATA_IMPORT, skill_context_factory=skill_context_factory))
    graph.add_node(NODE_FIELD_MAPPING, make_skill_node(db, package_code=NODE_FIELD_MAPPING, skill_context_factory=skill_context_factory))
    graph.add_node(NODE_DIFFERENCE_DETECT, make_skill_node(db, package_code=NODE_DIFFERENCE_DETECT, skill_context_factory=skill_context_factory))
    graph.add_node(NODE_ANOMALY_EXPLAIN, make_skill_node(db, package_code=NODE_ANOMALY_EXPLAIN, skill_context_factory=skill_context_factory))
    graph.add_node(NODE_REVIEW_FLOW, review_flow_node)
    graph.add_node(NODE_RE_VERIFY, make_re_verify_node(db, skill_context_factory=skill_context_factory))
    graph.add_node(NODE_REPORT_GEN, make_skill_node(db, package_code=NODE_REPORT_GEN, skill_context_factory=skill_context_factory))

    graph.set_entry_point(NODE_DATA_IMPORT)
    graph.add_edge(NODE_DATA_IMPORT, NODE_FIELD_MAPPING)
    graph.add_edge(NODE_FIELD_MAPPING, NODE_DIFFERENCE_DETECT)
    graph.add_conditional_edges(
        NODE_DIFFERENCE_DETECT,
        route_after_detect,
        {"has_diffs": NODE_ANOMALY_EXPLAIN, "no_diffs": NODE_REPORT_GEN},
    )
    graph.add_edge(NODE_ANOMALY_EXPLAIN, NODE_REVIEW_FLOW)
    graph.add_conditional_edges(
        NODE_REVIEW_FLOW,
        route_after_review,
        {"all_confirmed": NODE_REPORT_GEN, "has_returned": NODE_RE_VERIFY},
    )
    graph.add_edge(NODE_RE_VERIFY, NODE_REVIEW_FLOW)
    graph.add_edge(NODE_REPORT_GEN, END)

    cp = checkpointer if checkpointer is not None else get_workflow_checkpointer()
    return graph.compile(
        checkpointer=cp,
        interrupt_before=[NODE_REVIEW_FLOW],
    )


class PlatformWorkflowEngine:
    """Run reconciliation workflow via LangGraph + SkillExecutor (production facade target)."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._ctx: SkillContext | None = None
        self._legacy: WorkflowEngine | None = None
        self._compiled = None

    def _task(self, task_id: str) -> Task:
        task = self.db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise WorkflowStateError(task_id, f"任务不存在: {task_id}")
        return task

    def _ensure_legacy(self, task: Task) -> WorkflowEngine:
        if self._legacy is None or self._legacy.task.id != task.id:
            self._legacy = WorkflowEngine(self.db, task)
        return self._legacy

    def _build_context(self, task: Task, file_paths: dict[str, str]) -> SkillContext:
        legacy = self._ensure_legacy(task)
        ctx = SkillContext(
            db=self.db,
            task=task,
            file_paths=file_paths,
            rules=legacy._get_rules(),
            ai_mode=current_ai_mode(self.db),
        )
        ctx.on_rule_hit = legacy._audit_rule_hit
        ctx.on_difference_built = legacy._persist_difference
        self._ctx = ctx
        return ctx

    def _compile_graph(self, task: Task, file_paths: dict[str, str]):
        self._build_context(task, file_paths)
        ctx_factory = lambda: self._ctx  # noqa: E731
        if platform_settings.use_dynamic_workflow_graph:
            from agent_platform.workflow.graph_builder import build_workflow_from_db_nodes

            legacy = self._ensure_legacy(task)
            nodes = legacy._ordered_nodes()
            self._compiled = build_workflow_from_db_nodes(
                self.db,
                nodes,
                skill_context_factory=ctx_factory,
            )
        else:
            self._compiled = build_fangtai_workflow(self.db, skill_context_factory=ctx_factory)
        return self._compiled

    def _initial_state(
        self,
        *,
        wf_id: str,
        task_id: str,
        paths: dict[str, str],
        graph_name: str,
    ) -> WorkflowGraphState:
        return {
            "workflow_id": wf_id,
            "task_id": task_id,
            "workflow_type": graph_name,
            "status": "running",
            "current_node": NODE_DATA_IMPORT,
            "nodes_completed": [],
            "file_paths": paths,
            "diff_count": 0,
            "diff_list": [],
            "reviewed_diffs": [],
            "waiting_for_review": False,
            "errors": [],
            "warnings": [],
            "node_outputs": {},
        }

    async def start(
        self,
        *,
        task_id: str,
        file_paths: dict[str, str] | None = None,
        graph_name: str | None = None,
    ) -> dict[str, Any]:
        """Start workflow; pauses before review_flow when diffs need human review."""
        graph_name = graph_name or platform_settings.workflow_default_graph
        task = self._task(task_id)
        paths = file_paths or (task.summary or {}).get("file_paths") or task.data_sources or {}
        wf_id = str(uuid.uuid4())

        row = PlatformWorkflowORM(
            id=wf_id,
            task_id=task_id,
            graph_name=graph_name,
            status="running",
            state_json={"file_paths": paths},
            current_node=NODE_DATA_IMPORT,
        )
        self.db.add(row)
        task.status = TaskStatus.RUNNING.value
        task.progress = 5
        self.db.commit()

        compiled = self._compile_graph(task, paths)
        initial = self._initial_state(wf_id=wf_id, task_id=task_id, paths=paths, graph_name=graph_name)
        config = {"configurable": {"thread_id": wf_id}}

        try:
            final = await compiled.ainvoke(initial, config)
            await self._post_pipeline(task, final)
            self._persist_row(wf_id, task, final)
            return self.get_status(wf_id)
        except Exception as exc:  # noqa: BLE001
            row = self.db.get(PlatformWorkflowORM, wf_id)
            if row:
                row.status = "failed"
                row.error = str(exc)
            task.status = TaskStatus.FAILED.value
            task.error_message = str(exc)
            self.db.commit()
            raise

    def _persist_row(self, wf_id: str, task: Task, final: WorkflowGraphState) -> None:
        row = self.db.get(PlatformWorkflowORM, wf_id)
        if not row:
            return
        row.state_json = dict(final)
        row.current_node = final.get("current_node")
        st = final.get("status") or "running"
        if st in ("waiting_review", "paused"):
            row.status = "paused"
            task.status = TaskStatus.PENDING_REVIEW.value
            task.progress = 85
        elif st == "completed":
            row.status = "completed"
            task.status = TaskStatus.REPORTING.value
            task.progress = 95
        else:
            row.status = "running"
        row.updated_at = datetime.utcnow()
        self.db.commit()

    async def _post_pipeline(self, task: Task, state: WorkflowGraphState) -> None:
        if not self._ctx:
            return
        legacy = self._ensure_legacy(task)
        type_counts: dict[str, int] = {}
        total_amount = 0.0
        for d in self._ctx.raw_diffs:
            type_counts[d["type"]] = type_counts.get(d["type"], 0) + 1
            total_amount += float(d.get("amount_diff") or 0)

        task.summary = {
            **(task.summary or {}),
            "total": len(self._ctx.raw_diffs),
            "by_type": type_counts,
            "total_difference_amount": total_amount,
            "business_rows": len(self._ctx.business_records),
            "finance_rows": len(self._ctx.finance_records),
            "ai_mode": current_ai_mode(self.db),
            "platform_workflow_id": state.get("workflow_id"),
            "file_paths": state.get("file_paths") or task.data_sources,
        }

        if int(state.get("diff_count") or len(self._ctx.raw_diffs)) == 0:
            legacy._advance_zero_diff_to_reporting(trigger="langgraph")
            state["status"] = "completed"
        elif len(self._ctx.raw_diffs) > 0:
            state["status"] = "waiting_review"
            from app.services.review_flow_service import notify_review_pending, review_progress

            stats = review_progress(self.db, task.id)
            task.summary = {**(task.summary or {}), "review_progress": stats}
            notify_review_pending(self.db, task, kind="review_pending")
            legacy._run_log("review", "复核流转", "waiting", {"message": "等待人工复核"})

    async def resume(
        self,
        workflow_id: str,
        *,
        reviewed_diffs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Resume after human review — may run re_verify loop then report_gen."""
        row = self.db.get(PlatformWorkflowORM, workflow_id)
        if not row:
            raise WorkflowNotFoundError(workflow_id)
        if row.status not in ("paused", "running", "waiting_review"):
            raise WorkflowStateError(workflow_id, f"当前状态不可恢复: {row.status}")

        task = self._task(row.task_id or "")
        paths = (row.state_json or {}).get("file_paths") or task.data_sources or {}
        self._compile_graph(task, paths)
        config = {"configurable": {"thread_id": workflow_id}}

        compiled = self._compiled
        if compiled is None:
            raise WorkflowStateError(workflow_id, "Workflow 图未编译")

        if reviewed_diffs is not None:
            await compiled.aupdate_state(
                config,
                {
                    "reviewed_diffs": reviewed_diffs,
                    "waiting_for_review": False,
                    "status": "running",
                },
            )

        final = await compiled.ainvoke(None, config)
        if final:
            await self._post_report_phase(task, final)
            self._persist_row(workflow_id, task, final)
        return self.get_status(workflow_id)

    async def _post_report_phase(self, task: Task, state: WorkflowGraphState) -> None:
        out = (state.get("node_outputs") or {}).get(NODE_REPORT_GEN, {})
        payload = out.get("output") if isinstance(out, dict) else {}
        if isinstance(payload, dict) and payload.get("report_path"):
            task.summary = {**(task.summary or {}), "report_path": payload["report_path"]}
            state["report_url"] = payload.get("report_url") or payload["report_path"]
        state["status"] = "completed"

    async def get_checkpoint_state(self, workflow_id: str) -> dict[str, Any]:
        """Read live LangGraph state from checkpointer."""
        row = self.db.get(PlatformWorkflowORM, workflow_id)
        if not row:
            raise WorkflowNotFoundError(workflow_id)
        task = self._task(row.task_id or "")
        paths = (row.state_json or {}).get("file_paths") or {}
        self._compile_graph(task, paths)
        config = {"configurable": {"thread_id": workflow_id}}
        snap = await self._compiled.aget_state(config)
        return snap.values if snap else {}

    async def get_trace(self, workflow_id: str) -> list[dict[str, Any]]:
        """Full state history from LangGraph checkpointer."""
        row = self.db.get(PlatformWorkflowORM, workflow_id)
        if not row:
            raise WorkflowNotFoundError(workflow_id)
        task = self._task(row.task_id or "")
        paths = (row.state_json or {}).get("file_paths") or {}
        self._compile_graph(task, paths)
        config = {"configurable": {"thread_id": workflow_id}}
        history: list[dict[str, Any]] = []
        async for snap in self._compiled.aget_state_history(config):
            history.append(
                {
                    "node": (snap.values or {}).get("current_node"),
                    "status": (snap.values or {}).get("status"),
                    "values": snap.values,
                    "created_at": getattr(snap, "created_at", None),
                }
            )
        return history

    def get_status(self, workflow_id: str) -> dict[str, Any]:
        row = self.db.get(PlatformWorkflowORM, workflow_id)
        if not row:
            raise WorkflowNotFoundError(workflow_id)
        from agent_platform.core.tracer import SkillTracer

        traces = SkillTracer(self.db).list_by_workflow(workflow_id)
        return {
            "workflow_id": row.id,
            "task_id": row.task_id,
            "graph_name": row.graph_name,
            "status": row.status,
            "current_node": row.current_node,
            "state": row.state_json,
            "error": row.error,
            "traces": traces,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
