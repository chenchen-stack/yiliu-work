# File: agent_platform/workflow/router.py
"""Conditional routing for Fangtai reconciliation LangGraph workflow."""

from __future__ import annotations

from agent_platform.workflow.state import WorkflowGraphState


def route_after_detect(state: WorkflowGraphState) -> str:
    """After difference_detect: branch to anomaly_explain or skip to report_gen."""
    if int(state.get("diff_count") or 0) > 0:
        return "has_diffs"
    return "no_diffs"


def route_after_review(state: WorkflowGraphState) -> str:
    """After review_flow: all confirmed → report; any returned → re_verify loop."""
    reviewed = state.get("reviewed_diffs") or []
    returned = [d for d in reviewed if (d.get("review_status") or d.get("status")) == "returned"]
    if returned:
        return "has_returned"
    return "all_confirmed"
