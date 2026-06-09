# File: agent_platform/workflow/graph_builder.py
"""
从 DB Workflow.nodes 动态编译 LangGraph（与 legacy WorkflowEngine 节点顺序对齐）。

默认关闭（use_dynamic_workflow_graph=false），方太 POC 仍用 build_fangtai_workflow 硬编码图。
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from agent_platform.logging_setup import get_logger
from agent_platform.workflow.engine import build_fangtai_workflow

logger = get_logger("workflow.graph_builder")

# 参与自动化流水线、且由 SkillExecutor 执行的节点（review_flow 单独 interrupt）
_SKILL_NODE_CODES = frozenset({
    "data_import",
    "ontology_context",
    "field_mapping",
    "difference_detect",
    "anomaly_explain",
    "re_verify",
    "report_gen",
})


def _skill_code(node: dict) -> str | None:
    code = (node.get("skill_code") or node.get("skill") or "").strip()
    return code or None


def ordered_skill_codes_from_db(nodes: list[dict]) -> list[str]:
    """按 DB 节点顺序提取 enabled 的 skill_code 列表。"""
    codes: list[str] = []
    for node in nodes:
        if node.get("enabled") is False:
            continue
        code = _skill_code(node)
        if not code or code == "review_flow":
            continue
        if code in _SKILL_NODE_CODES and code not in codes:
            codes.append(code)
    return codes


def build_workflow_from_db_nodes(
    db: Session,
    nodes: list[dict],
    *,
    skill_context_factory: Callable[[], Any],
    checkpointer=None,
):
    """
    根据 Workflow.nodes 构建 LangGraph（P2 进行中）。

    当前：记录 DB 节点顺序并回退到方太硬编码图，避免未验证的边导致生产故障。
    待办：ontology_context 入图、与 transitions 对齐的条件边。
    """
    codes = ordered_skill_codes_from_db(nodes)
    logger.info(
        "dynamic workflow graph: fallback to fangtai hardcoded",
        extra_fields={"db_skill_codes": codes},
    )
    return build_fangtai_workflow(
        db,
        skill_context_factory=skill_context_factory,
        checkpointer=checkpointer,
    )
