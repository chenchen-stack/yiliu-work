"""任务列表展示辅助：对话卡片去重等。"""
from __future__ import annotations

import re
from datetime import datetime

from app.models import Task


def _norm_period(period: str | None) -> str:
    raw = (period or "").strip()
    if not raw:
        return ""
    m = re.match(r"(20\d{2})[-年/](\d{1,2})", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return raw


def task_business_key(task: Task) -> tuple[str, str]:
    name = (task.name or "").strip()
    name = re.sub(r"20(\d{2})年0?(\d{1,2})月", r"20\1年\2月", name)
    return (name, _norm_period(task.period))


def dedupe_tasks_for_display(tasks: list[Task]) -> list[Task]:
    """同名同周期只保留最近更新的一条。"""
    ordered = sorted(
        tasks,
        key=lambda t: t.updated_at or datetime.min,
        reverse=True,
    )
    seen: set[tuple[str, str]] = set()
    out: list[Task] = []
    for t in ordered:
        key = task_business_key(t)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out
