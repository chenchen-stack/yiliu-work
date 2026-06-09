# File: agent_platform/workflow/state.py
"""Unified LangGraph state — Workflow (deterministic) + Agent (ReAct)."""

from __future__ import annotations

from typing import Annotated, Any, NotRequired, TypedDict

from langgraph.graph.message import add_messages
from langgraph.managed import RemainingSteps


class WorkflowGraphState(TypedDict, total=False):
    """
    Workflow deterministic mode — shared between LangGraph nodes.
    Persisted via checkpointer + mirrored to platform_workflows.state_json.
    """

    workflow_id: str
    task_id: str
    workflow_type: str
    status: str  # running | waiting_review | paused | completed | failed
    current_node: str
    nodes_completed: list[str]
    file_paths: dict[str, str]
    rules: list[dict[str, Any]]
    ai_mode: str
    node_outputs: dict[str, Any]
    error: str | None

    import_id: str | None
    mapped_count: int | None
    total_compared: int | None
    matched_count: int | None
    diff_count: int
    diff_list: list[dict[str, Any]]

    waiting_for_review: bool
    reviewed_diffs: list[dict[str, Any]]

    errors: list[str]
    warnings: list[str]
    report_url: str | None

    messages: Annotated[list, add_messages]


class AgentGraphState(TypedDict, total=False):
    """Agent dynamic mode — ReAct loop state."""

    messages: Annotated[list, add_messages]
    remaining_steps: NotRequired[RemainingSteps]
    session_id: str
    user_id: str
    available_skills: list[dict[str, Any]]
    ontology_context: str
    current_task_id: str | None
    current_diff_id: str | None
    iteration_count: int
    max_iterations: int
