from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    CaseAsset,
    Difference,
    DifferenceStatus,
    ProcessingRecord,
    ReviewAction,
    Task,
    TaskStatus,
    User,
    WorkflowRun,
)
from app.schemas import (
    CaseAssetCreate,
    CaseAssetOut,
    DiffFeedbackRequest,
    DifferenceOut,
    ProcessingRecordCreate,
    ProcessingRecordOut,
    ReviewRequest,
)
from app.services.ai_analyzer import build_evidence_chain, analyze_difference, diff_item_from_model
from app.services.workflow_engine import current_ai_mode
from app.services.audit_service import log_audit
from app.services.state_machine import assert_task_not_closed

router = APIRouter(prefix="/differences", tags=["differences"])


@router.get("/{diff_id}", response_model=DifferenceOut)
def get_difference(diff_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    diff = db.query(Difference).filter(Difference.id == diff_id).first()
    if not diff:
        raise HTTPException(404, "差异不存在")
    return diff


@router.post("/{diff_id}/feedback", response_model=DifferenceOut)
def difference_feedback(
    diff_id: str,
    body: DiffFeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """用户质疑或修正 AI 归因，不替代正式复核，但会留痕并回到待复核。"""
    diff = db.query(Difference).filter(Difference.id == diff_id).first()
    if not diff:
        raise HTTPException(404, "差异不存在")
    task = db.query(Task).filter(Task.id == diff.task_id).first()
    if task:
        assert_task_not_closed(task.status)

    prev_ai = (diff.ai_explanation or "").strip()
    prev_rec = diff.ai_recommendation or {}
    prev_cause = str(prev_rec.get("root_cause") or prev_ai or "—")

    if body.action == "question":
        parts = ["用户质疑 AI 归因"]
        if body.reason_category:
            parts.append(f"类别:{body.reason_category}")
        if body.reason_text:
            parts.append(body.reason_text.strip())
        diff.review_comment = " · ".join(parts)
        diff.status = DifferenceStatus.PENDING_REVIEW.value
        diff.review_decision = "comment"
    else:
        corrected = (body.corrected_cause or "").strip()
        if not corrected:
            raise HTTPException(400, "修正时请填写正确的归因说明")
        diff.review_comment = f"AI判定:{prev_cause} → 用户修正为:{corrected}"
        diff.ai_explanation = corrected
        rec = dict(prev_rec) if isinstance(prev_rec, dict) else {}
        rec["root_cause"] = corrected
        rec["user_corrected"] = True
        rec["previous_root_cause"] = prev_cause
        diff.ai_recommendation = rec
        diff.status = DifferenceStatus.PENDING_REVIEW.value
        diff.review_decision = "comment"

    diff.reviewed_by = user.id
    diff.reviewed_at = datetime.utcnow()
    log_audit(
        db,
        user=user,
        trace_id=task.trace_id if task else None,
        object_type="difference",
        object_id=diff_id,
        action="diff_feedback",
        detail={
            "feedback_action": body.action,
            "reason_category": body.reason_category,
            "corrected_cause": body.corrected_cause,
        },
    )
    db.commit()
    db.refresh(diff)
    return diff


@router.post("/{diff_id}/review", response_model=DifferenceOut)
def review_difference(
    diff_id: str,
    body: ReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    diff = db.query(Difference).filter(Difference.id == diff_id).first()
    if not diff:
        raise HTTPException(404, "差异不存在")
    task = db.query(Task).filter(Task.id == diff.task_id).first()
    if task:
        assert_task_not_closed(task.status)
    # 仅“待复核 / 已识别”差异可被复核处置（confirm/reject/assign），其余状态拒绝
    if body.decision in ("confirm", "reject", "assign"):
        if diff.status in (
            DifferenceStatus.CONFIRMED.value,
            DifferenceStatus.REJECTED.value,
        ):
            raise HTTPException(400, "该差异已完成复核，无法重复操作")
        if diff.status == DifferenceStatus.ASSIGNED.value:
            raise HTTPException(
                400,
                "差异已指派处理中，请待处理方提交反馈后再操作；如需调整请先刷新页面",
            )
        if diff.status not in (
            DifferenceStatus.PENDING_REVIEW.value,
            DifferenceStatus.IDENTIFIED.value,
        ):
            raise HTTPException(400, f"当前差异状态「{diff.status}」不可复核处置")
    before_status = diff.status

    status_map = {
        "confirm": DifferenceStatus.CONFIRMED.value,
        "reject": DifferenceStatus.REJECTED.value,
        "assign": DifferenceStatus.ASSIGNED.value,
        "comment": DifferenceStatus.PENDING_REVIEW.value,
    }
    diff.review_decision = body.decision
    diff.review_comment = body.comment
    diff.status = status_map.get(body.decision, diff.status)
    if body.decision == "assign":
        if not body.assignee_id:
            raise HTTPException(400, "指派需指定 assignee_id")
        diff.assignee_id = body.assignee_id
        diff.status = DifferenceStatus.ASSIGNED.value
        diff.responsible_party = body.responsible_party or "ops"
    if body.responsible_party:
        diff.responsible_party = body.responsible_party
    diff.reviewed_by = user.id
    diff.reviewed_at = datetime.utcnow()

    db.add(
        ReviewAction(
            id=__import__("uuid").uuid4().__str__(),
            difference_item_id=diff_id,
            reviewer=user.id,
            action=body.decision,
            comment=body.comment,
            assignee=body.assignee_id,
        )
    )

    item = {
        "rule_id": (diff.rule_hits or [{}])[0].get("rule_id") if diff.rule_hits else None,
        "type": diff.type,
        "confidence": diff.confidence,
        "responsible_party": diff.responsible_party,
        "description": body.comment or diff.type,
        "sap_record": diff.sap_record,
        "dms_record": diff.dms_record,
    }
    diff.evidence_chain = build_evidence_chain(
        item,
        diff.ai_recommendation or {},
        {"decision": body.decision, "user_id": user.id, "user_name": user.display_name, "comment": body.comment},
    )

    log_audit(
        db,
        user=user,
        trace_id=task.trace_id if task else None,
        object_type="difference",
        object_id=diff_id,
        action=body.decision,
        before_data={"status": before_status},
        after_data={"status": diff.status, "comment": body.comment},
    )

    if body.decision == "assign" and task:
        task.status = TaskStatus.PROCESSING.value
        log_audit(
            db,
            user=user,
            trace_id=task.trace_id,
            object_type="task",
            object_id=task.id,
            action="assign_processing",
            after_data={"assignee_id": body.assignee_id},
        )
    elif task and body.decision in ("confirm", "reject"):
        from app.services.review_flow_service import sync_task_review_summary

        sync_task_review_summary(db, task)

    db.commit()
    db.refresh(diff)
    return diff


@router.post("/{diff_id}/re-explain", response_model=DifferenceOut)
async def re_explain_difference(
    diff_id: str,
    prefer_llm: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """默认按检测规则重生成解释；prefer_llm=true 且已配置 Key 时使用大模型。"""
    diff = db.query(Difference).filter(Difference.id == diff_id).first()
    if not diff:
        raise HTTPException(404, "差异不存在")
    task = db.query(Task).filter(Task.id == diff.task_id).first()
    if task:
        assert_task_not_closed(task.status)

    if prefer_llm:
        from app.services.llm_config_service import get_effective_llm_config

        cfg = get_effective_llm_config(db)
        if cfg.use_mock or not cfg.api_key:
            raise HTTPException(
                400,
                "大模型未就绪：请在管理后台「系统配置 → 大模型」关闭模拟模式并配置 API Key",
            )

    item = diff_item_from_model(diff)
    recommendation = await analyze_difference(item, db=db, task=task, prefer_llm=prefer_llm)
    evidence = build_evidence_chain(item, recommendation)

    diff.ai_recommendation = recommendation
    diff.ai_explanation = recommendation.get("root_cause", "")
    diff.suggestion = recommendation.get("suggested_action") or recommendation.get("root_cause", "")
    diff.evidence_chain = evidence
    if recommendation.get("responsible_party"):
        diff.responsible_party = recommendation["responsible_party"]
    if recommendation.get("confidence") is not None:
        diff.confidence = float(recommendation["confidence"])

    if task:
        task.summary = {
            **(task.summary or {}),
            "ai_mode": current_ai_mode(db),
        }
        log_audit(
            db,
            user=user,
            trace_id=task.trace_id,
            object_type="difference",
            object_id=diff_id,
            action="ai_explain",
            detail={
                "model_mode": "rule"
                if str(recommendation.get("model", "")).startswith("rule")
                else "llm",
                "model_name": recommendation.get("model"),
                "configured_ai_mode": current_ai_mode(db),
                "prompt_version": recommendation.get("prompt_version"),
                "provider": recommendation.get("provider"),
                "fallback_reason": recommendation.get("fallback_reason"),
                "re_explain": True,
            },
        )

    db.commit()
    db.refresh(diff)
    return diff


@router.post("/{diff_id}/archive-case", response_model=CaseAssetOut)
def archive_case(
    diff_id: str,
    body: CaseAssetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    diff = db.query(Difference).filter(Difference.id == diff_id).first()
    if not diff:
        raise HTTPException(404, "差异不存在")
    task = db.query(Task).filter(Task.id == diff.task_id).first()
    if not task or task.status != TaskStatus.CLOSED.value:
        raise HTTPException(400, "仅已关闭任务的可确认差异可沉淀为案例")

    existing = db.query(CaseAsset).filter(CaseAsset.source_difference_id == diff_id).first()
    if existing:
        return existing

    asset = CaseAsset(
        id=__import__("uuid").uuid4().__str__(),
        source_task_id=diff.task_id,
        source_difference_id=diff_id,
        confirmed_type=diff.type,
        root_cause=body.root_cause or diff.ai_explanation or (diff.ai_recommendation or {}).get("root_cause"),
        handling_result=body.handling_result or diff.review_comment,
        reusable_rule_suggestion=body.reusable_rule_suggestion,
        status="published",
        knowledge_base_id="kb-fangtai-cases",
        source_kind="diff_archive",
    )
    db.add(asset)
    log_audit(
        db,
        user=user,
        trace_id=task.trace_id,
        object_type="case_asset",
        object_id=asset.id,
        action="archive_case",
        after_data={"source_difference_id": diff_id},
    )
    db.commit()
    db.refresh(asset)
    return asset


processing_router = APIRouter(prefix="/processing-records", tags=["processing"])


@processing_router.post("", response_model=ProcessingRecordOut)
def create_processing_record(
    body: ProcessingRecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    diff = db.query(Difference).filter(Difference.id == body.difference_item_id).first()
    if not diff:
        raise HTTPException(404, "差异不存在")
    parent = db.query(Task).filter(Task.id == diff.task_id).first()
    if parent:
        assert_task_not_closed(parent.status)
    if diff.status not in (DifferenceStatus.ASSIGNED.value, DifferenceStatus.PROCESSING.value, DifferenceStatus.RETURNED.value):
        raise HTTPException(400, f"当前差异状态 {diff.status} 不可提交处理反馈（需先被指派）")
    if diff.assignee_id and diff.assignee_id != user.id and user.role not in ("admin", "manager"):
        raise HTTPException(403, "仅指派的责任人可提交处理反馈")

    record = ProcessingRecord(
        id=__import__("uuid").uuid4().__str__(),
        difference_item_id=body.difference_item_id,
        assignee=user.id,
        action_description=body.action_description,
        attachment=body.attachment,
        status="completed",
    )
    before = diff.status
    diff.status = DifferenceStatus.PENDING_VERIFICATION.value
    db.add(record)

    task = db.query(Task).filter(Task.id == diff.task_id).first()
    if task:
        from app.services.review_flow_service import sync_task_review_summary

        sync_task_review_summary(db, task)
        log_audit(
            db,
            user=user,
            trace_id=task.trace_id,
            object_type="difference",
            object_id=diff.id,
            action="processing_feedback",
            before_data={"status": before},
            after_data={"status": diff.status, "description": body.action_description[:200]},
        )
    db.commit()
    db.refresh(record)
    return record


@processing_router.get("", response_model=list[ProcessingRecordOut])
def list_processing_records(
    difference_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(ProcessingRecord)
    if difference_id:
        q = q.filter(ProcessingRecord.difference_item_id == difference_id)
    return q.order_by(ProcessingRecord.created_at.desc()).all()
