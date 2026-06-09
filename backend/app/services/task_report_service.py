"""任务 PDF 报告生成（供 API 与 Workflow 引擎共用）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Difference, DifferenceStatus, Report, Task, TaskStatus, User, WorkflowRun
from app.services.audit_service import log_audit
from app.services.report_generator import generate_pdf_report


def create_task_pdf_report(
    db: Session,
    task: Task,
    *,
    user: User | None = None,
    write_workflow_run: bool = True,
) -> Report:
    if task.status != TaskStatus.REPORTING.value:
        raise ValueError("仅“报告输出”状态可生成报告")

    open_count = (
        db.query(Difference)
        .filter(
            Difference.task_id == task.id,
            Difference.status.in_([
                DifferenceStatus.PENDING_REVIEW.value,
                DifferenceStatus.ASSIGNED.value,
                DifferenceStatus.PROCESSING.value,
                DifferenceStatus.PENDING_VERIFICATION.value,
                DifferenceStatus.RETURNED.value,
            ]),
        )
        .count()
    )
    if open_count > 0:
        raise ValueError(f"仍有 {open_count} 条差异未完成处理/验证")

    diffs = db.query(Difference).filter(Difference.task_id == task.id).all()
    diff_dicts = [
        {
            "type": d.type,
            "amount_diff": d.amount_diff,
            "confidence": d.confidence,
            "review_decision": d.review_decision or d.status,
            "sap_record": d.sap_record,
            "ai_recommendation": d.ai_recommendation,
        }
        for d in diffs
    ]
    report_path = generate_pdf_report(
        {"id": task.id, "name": task.name, "summary": task.summary, "period": task.period},
        diff_dicts,
    )
    report = Report(
        id=str(uuid.uuid4()),
        task_id=task.id,
        report_type="batch_reconciliation",
        file_url=report_path,
    )
    db.add(report)
    if write_workflow_run:
        db.add(
            WorkflowRun(
                id=str(uuid.uuid4()),
                task_id=task.id,
                workflow_id=(task.summary or {}).get("workflow_id") or "",
                node_id="report",
                node_label="报告生成",
                status="completed",
                detail={"message": "PDF 报告已生成", "report_path": report_path},
            )
        )
    task.status = TaskStatus.REPORTING.value
    task.progress = 100
    summary = {**(task.summary or {}), "report_path": report_path}
    summary.pop("report_error", None)
    task.summary = summary
    task.updated_at = datetime.utcnow()
    log_audit(
        db,
        user=user,
        user_id=(user.id if user else task.creator_id),
        trace_id=task.trace_id,
        object_type="task",
        object_id=task.id,
        action="generate_report",
        after_data={"report_id": report.id, "path": report_path, "auto": user is None},
    )
    return report
