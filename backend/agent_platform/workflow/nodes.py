# File: agent_platform/workflow/nodes.py
"""Workflow node implementations — each node invokes SkillExecutor and updates WorkflowGraphState."""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from agent_platform.core.executor import SkillExecutor
from agent_platform.logging_setup import get_logger
from agent_platform.workflow.state import WorkflowGraphState

logger = get_logger("workflow.nodes")


def _default_input(state: WorkflowGraphState) -> dict[str, Any]:
    return {
        "task_id": state.get("task_id"),
        "file_paths": state.get("file_paths") or {},
    }


def _re_verify_input(state: WorkflowGraphState) -> dict[str, Any]:
    base = _default_input(state)
    returned = [
        d
        for d in (state.get("reviewed_diffs") or [])
        if (d.get("review_status") or d.get("status")) == "returned"
    ]
    base["returned_diffs"] = returned
    if returned and returned[0].get("diff_id"):
        base["diff_id"] = returned[0]["diff_id"]
    return base


def _metrics_from_context(ctx: Any) -> dict[str, Any]:
    """Map SkillContext reconciliation results into workflow state fields."""
    if ctx is None:
        return {"diff_count": 0, "diff_list": []}
    raw = getattr(ctx, "raw_diffs", None) or []
    diff_list = [
        {
            "diff_id": d.get("id") or d.get("diff_id"),
            "type": d.get("type"),
            "business_amount": d.get("business_amount"),
            "finance_amount": d.get("finance_amount"),
            "amount_diff": d.get("amount_diff"),
            "failed_rule": d.get("failed_rule"),
            "attribution": d.get("ai_explanation") or d.get("attribution"),
            "confidence": d.get("confidence"),
        }
        for d in raw
    ]
    business = getattr(ctx, "business_records", None) or []
    finance = getattr(ctx, "finance_records", None) or []
    total = max(len(business), len(finance), len(raw))
    matched = max(0, total - len(raw)) if total else 0
    return {
        "diff_count": len(raw),
        "diff_list": diff_list,
        "total_compared": total,
        "matched_count": matched,
        "mapped_count": len(business) + len(finance),
    }


def _append_completed(state: WorkflowGraphState, node: str) -> list[str]:
    done = list(state.get("nodes_completed") or [])
    if node not in done:
        done.append(node)
    return done


def make_skill_node(
    db: Session,
    *,
    package_code: str,
    skill_context_factory: Callable[[], Any],
    input_builder: Callable[[WorkflowGraphState], dict[str, Any]] | None = None,
) -> Callable[[WorkflowGraphState], dict[str, Any]]:
    """Return async node that runs one skill package via SkillExecutor."""

    async def _node(state: WorkflowGraphState) -> dict[str, Any]:
        wf_id = state.get("workflow_id", "")
        params = (input_builder or _default_input)(state)
        ctx = skill_context_factory()
        executor = SkillExecutor(db)
        result = await executor.run(
            package_code,
            params,
            workflow_id=wf_id,
            node_name=package_code,
            skill_context=ctx,
        )
        outputs = dict(state.get("node_outputs") or {})
        outputs[package_code] = result
        patch: dict[str, Any] = {
            "current_node": package_code,
            "node_outputs": outputs,
            "status": "running",
            "nodes_completed": _append_completed(state, package_code),
        }
        if package_code in ("difference_detect", "anomaly_explain", "field_mapping", "data_import"):
            patch.update(_metrics_from_context(ctx))
        if package_code == "data_import" and result.get("output"):
            out = result["output"]
            if isinstance(out, dict) and out.get("import_id"):
                patch["import_id"] = out["import_id"]
        logger.info("node done", extra_fields={"node": package_code, "workflow_id": wf_id})
        return patch

    return _node


def review_flow_node(state: WorkflowGraphState) -> dict[str, Any]:
    """Pause for human review — LangGraph interrupt_before enters before this node runs."""
    logger.info("review gate", extra_fields={"workflow_id": state.get("workflow_id")})
    return {
        "current_node": "review_flow",
        "status": "waiting_review",
        "waiting_for_review": True,
        "nodes_completed": _append_completed(state, "review_flow"),
    }


def make_re_verify_node(
    db: Session,
    *,
    skill_context_factory: Callable[[], Any],
) -> Callable[[WorkflowGraphState], dict[str, Any]]:
    """Node: re_verify — rerun rules for returned diffs."""
    return make_skill_node(
        db,
        package_code="re_verify",
        skill_context_factory=skill_context_factory,
        input_builder=_re_verify_input,
    )
