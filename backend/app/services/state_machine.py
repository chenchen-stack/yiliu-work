"""任务 / 差异状态机：集中定义合法流转，拒绝非法跳转（审计报告 §11）。"""

from __future__ import annotations

from fastapi import HTTPException

from app.models import DifferenceStatus as DS
from app.models import TaskStatus as TS

# 任务合法流转
TASK_TRANSITIONS: dict[str, set[str]] = {
    TS.DRAFT.value: {TS.RUNNING.value},
    TS.RUNNING.value: {TS.PENDING_REVIEW.value, TS.REPORTING.value, TS.FAILED.value},
    TS.PENDING_REVIEW.value: {TS.PROCESSING.value, TS.PENDING_VERIFICATION.value, TS.REPORTING.value},
    TS.PROCESSING.value: {TS.PENDING_VERIFICATION.value},
    TS.PENDING_VERIFICATION.value: {TS.REPORTING.value, TS.PROCESSING.value},
    TS.REPORTING.value: {TS.CLOSED.value},
    TS.FAILED.value: {TS.RUNNING.value},
    TS.CLOSED.value: set(),
}

# 差异合法流转
DIFF_TRANSITIONS: dict[str, set[str]] = {
    DS.IDENTIFIED.value: {DS.PENDING_REVIEW.value},
    DS.PENDING_REVIEW.value: {DS.CONFIRMED.value, DS.REJECTED.value, DS.ASSIGNED.value},
    DS.CONFIRMED.value: {DS.CLOSED.value},
    DS.REJECTED.value: {DS.CLOSED.value},
    DS.ASSIGNED.value: {DS.PROCESSING.value, DS.PENDING_VERIFICATION.value},
    DS.PROCESSING.value: {DS.PENDING_VERIFICATION.value},
    DS.PENDING_VERIFICATION.value: {DS.RESOLVED.value, DS.RETURNED.value},
    DS.RESOLVED.value: {DS.CLOSED.value},
    DS.RETURNED.value: {DS.PROCESSING.value, DS.PENDING_VERIFICATION.value},
    DS.CLOSED.value: set(),
}

_TASK_LABELS = {
    TS.DRAFT.value: "草稿",
    TS.RUNNING.value: "执行中",
    TS.PENDING_REVIEW.value: "待复核",
    TS.PROCESSING.value: "处理中",
    TS.PENDING_VERIFICATION.value: "待验证",
    TS.REPORTING.value: "报告输出",
    TS.CLOSED.value: "已关闭",
    TS.FAILED.value: "执行失败",
}


def can_task_transition(frm: str, to: str) -> bool:
    return to in TASK_TRANSITIONS.get(frm, set())


def assert_task_transition(frm: str, to: str):
    if not can_task_transition(frm, to):
        raise HTTPException(
            400,
            f"非法任务状态流转：{_TASK_LABELS.get(frm, frm)} → {_TASK_LABELS.get(to, to)}",
        )


def assert_task_not_closed(status: str):
    if status == TS.CLOSED.value:
        raise HTTPException(400, "任务已关闭，不可再修改或操作")


def can_diff_transition(frm: str, to: str) -> bool:
    return to in DIFF_TRANSITIONS.get(frm, set())


def assert_diff_transition(frm: str, to: str):
    if not can_diff_transition(frm, to):
        raise HTTPException(400, f"非法差异状态流转：{frm} → {to}")
