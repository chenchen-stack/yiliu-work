"""Rule engine wrapper — delegates to task rule configs."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from agent_platform.logging_setup import get_logger

logger = get_logger("rule_engine")


def load_rules_for_task(db: Session, task_id: str) -> list[dict[str, Any]]:
    """Load enabled RuleConfig rows for a task's business center."""
    from app.models import RuleConfig, Task

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return []
    q = db.query(RuleConfig)
    if task.business_center_id:
        q = q.filter(RuleConfig.business_center_id == task.business_center_id)
    rows = q.all()
    rules: list[dict[str, Any]] = []
    for r in rows:
        rules.append(
            {
                "id": r.id,
                "name": r.name,
                "rule_type": r.rule_type,
                "enabled": r.enabled,
                "threshold": r.threshold,
                "params": r.params or {},
            }
        )
    logger.info("rules loaded", extra_fields={"task_id": task_id, "count": len(rules)})
    return rules


def evaluate_rule_hits(diff_item: dict[str, Any], rules: list[dict[str, Any]]) -> list[str]:
    """Return human-readable rule hit labels for a difference item."""
    hits: list[str] = []
    dtype = diff_item.get("type") or diff_item.get("difference_type") or ""
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        rt = rule.get("rule_type") or ""
        if rt and rt in str(dtype):
            hits.append(rule.get("name") or rt)
    if not hits and dtype:
        hits.append(f"规则:{dtype}")
    return hits
