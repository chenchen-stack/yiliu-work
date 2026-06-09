"""复核流转：通知审批人、汇总复核进度、审批通过后推进 Workflow。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Difference, DifferenceStatus, Task, TaskStatus, User, UserRole, WorkflowNotification
from app.services.audit_service import log_audit
from app.services.state_machine import assert_task_transition

REVIEW_OPEN_DIFF = {
    DifferenceStatus.PENDING_REVIEW.value,
    DifferenceStatus.IDENTIFIED.value,
}
REVIEW_BLOCKING_PROCESS = {
    DifferenceStatus.ASSIGNED.value,
    DifferenceStatus.PROCESSING.value,
}


def review_progress(db: Session, task_id: str) -> dict[str, Any]:
    diffs = db.query(Difference).filter(Difference.task_id == task_id).all()
    pending = sum(1 for d in diffs if d.status in REVIEW_OPEN_DIFF)
    blocking = sum(1 for d in diffs if d.status in REVIEW_BLOCKING_PROCESS)
    confirmed = sum(1 for d in diffs if d.status == DifferenceStatus.CONFIRMED.value)
    rejected = sum(1 for d in diffs if d.status == DifferenceStatus.REJECTED.value)
    return {
        "total": len(diffs),
        "pending_review": pending,
        "blocking_processing": blocking,
        "confirmed": confirmed,
        "rejected": rejected,
        "ready_for_approval": pending == 0 and blocking == 0 and len(diffs) > 0,
    }


def can_approve_review(db: Session, task: Task) -> tuple[bool, str]:
    if task.status not in (TaskStatus.PENDING_REVIEW.value, TaskStatus.PROCESSING.value):
        return False, f"任务状态「{task.status}」不在复核阶段"
    stats = review_progress(db, task.id)
    if stats["total"] == 0:
        return False, "任务无差异，无需复核审批"
    if stats["pending_review"] > 0:
        return False, f"仍有 {stats['pending_review']} 条差异待复核处置"
    if stats["blocking_processing"] > 0:
        return False, f"仍有 {stats['blocking_processing']} 条差异在责任处理中"
    if not stats["ready_for_approval"]:
        return False, "复核尚未完成"
    return True, ""


def notify_review_pending(db: Session, task: Task, *, kind: str = "review_pending") -> int:
    """向管理员/上级发送复核待办通知。"""
    approvers = (
        db.query(User)
        .filter(User.role.in_([UserRole.ADMIN.value, UserRole.MANAGER.value]))
        .all()
    )
    stats = review_progress(db, task.id)
    if kind == "review_ready":
        title = f"【待审批】{task.name}"
        message = (
            f"任务「{task.name}」差异复核已完成（共 {stats['total']} 条），"
            f"请审批通过后进入再次验证。"
        )
    else:
        title = f"【待复核】{task.name}"
        message = (
            f"任务「{task.name}」识别到 {stats['total']} 条差异，"
            f"请安排复核或在差异处理完成后审批。"
        )
    created = 0
    for u in approvers:
        exists = (
            db.query(WorkflowNotification)
            .filter(
                WorkflowNotification.task_id == task.id,
                WorkflowNotification.user_id == u.id,
                WorkflowNotification.kind == kind,
                WorkflowNotification.read.is_(False),
            )
            .first()
        )
        if exists:
            continue
        db.add(
            WorkflowNotification(
                id=str(uuid.uuid4()),
                user_id=u.id,
                task_id=task.id,
                kind=kind,
                title=title,
                message=message,
                read=False,
            )
        )
        created += 1
    return created


def sync_task_review_summary(db: Session, task: Task) -> dict[str, Any]:
    """更新任务 summary 中的复核进度，并在就绪时通知审批人。"""
    stats = review_progress(db, task.id)
    task.summary = {**(task.summary or {}), "review_progress": stats}
    if stats["ready_for_approval"] and task.status in (
        TaskStatus.PENDING_REVIEW.value,
        TaskStatus.PROCESSING.value,
    ):
        notify_review_pending(db, task, kind="review_ready")
    return stats


def mark_task_notifications_read(db: Session, task_id: str, user_id: str) -> None:
    rows = (
        db.query(WorkflowNotification)
        .filter(
            WorkflowNotification.task_id == task_id,
            WorkflowNotification.user_id == user_id,
            WorkflowNotification.read.is_(False),
        )
        .all()
    )
    for row in rows:
        row.read = True


async def approve_review_and_advance(
    db: Session,
    task: Task,
    user: User,
    *,
    auto_verify: bool = True,
) -> dict[str, Any]:
    """管理员/上级审批复核，通过后进入再次验证并可自动执行验证 Skill。"""
    if user.role not in (UserRole.ADMIN.value, UserRole.MANAGER.value):
        raise HTTPException(403, "仅管理员或上级可审批复核流转")

    ok, reason = can_approve_review(db, task)
    if not ok:
        raise HTTPException(400, reason)

    diffs = db.query(Difference).filter(Difference.task_id == task.id).all()
    promoted = 0
    for d in diffs:
        if d.status == DifferenceStatus.CONFIRMED.value:
            d.status = DifferenceStatus.PENDING_VERIFICATION.value
            promoted += 1

    before_status = task.status
    assert_task_transition(before_status, TaskStatus.PENDING_VERIFICATION.value)
    task.status = TaskStatus.PENDING_VERIFICATION.value
    task.progress = 88
    task.summary = {
        **(task.summary or {}),
        "review_approved_by": user.id,
        "review_approved_at": datetime.utcnow().isoformat(),
        "review_progress": review_progress(db, task.id),
    }

    from app.services.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(db, task)
    engine._run_log(
        "review",
        "复核流转",
        "completed",
        {
            "message": "复核审批通过",
            "approver": user.display_name,
            "approver_id": user.id,
            "promoted_to_verify": promoted,
        },
    )
    engine._record_invocation(
        node_code="review",
        node_label="复核流转",
        skill_code="review_flow",
        input_summary={"diff_count": len(diffs)},
        output_summary={"approved": True, "promoted": promoted},
        status="completed",
        started_at=datetime.utcnow(),
    )

    log_audit(
        db,
        user=user,
        trace_id=task.trace_id,
        object_type="task",
        object_id=task.id,
        action="review_approved",
        before_data={"status": before_status},
        after_data={"status": task.status, "promoted": promoted},
    )
    mark_task_notifications_read(db, task.id, user.id)

    reviewed_payload = [
        {
            "diff_id": d.id,
            "review_status": "returned" if d.status == DifferenceStatus.RETURNED.value else "confirmed",
            "status": d.status,
        }
        for d in diffs
    ]
    from app.services.workflow_facade import resume_after_review

    langgraph_resume: dict[str, Any] | None = None
    try:
        langgraph_resume = await resume_after_review(db, task, reviewed_diffs=reviewed_payload)
    except Exception:  # noqa: BLE001 — 不阻断 legacy 再次验证
        langgraph_resume = None

    verify_result: dict[str, Any] | None = None
    if langgraph_resume:
        verify_result = {"langgraph": langgraph_resume}
    elif auto_verify:
        paths = task.data_sources or {}
        if paths.get("business") or paths.get("sap"):
            verify_result = await engine.run_verification(paths, user.id)
        else:
            task.summary = {**(task.summary or {}), "verify_skipped": "missing_data_sources"}

    task.updated_at = datetime.utcnow()
    return {
        "task_status": task.status,
        "progress": task.progress,
        "promoted_to_verify": promoted,
        "verify_result": verify_result,
    }
