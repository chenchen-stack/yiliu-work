import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.config import UPLOAD_DIR
from app.database import SessionLocal, get_db
from app.models import (
    BusinessCenter,
    BusinessCenterStatus,
    DataSource,
    Difference,
    DifferenceStatus,
    Report,
    RuleConfig,
    RuleVersion,
    Task,
    TaskStatus,
    User,
    UserRole,
    Workflow,
    WorkflowRun,
)
from app.schemas import (
    AuditLogOut,
    DemoDatasetOut,
    DifferenceOut,
    ProcessingRecordCreate,
    ProcessingRecordOut,
    ReportOut,
    ReviewRequest,
    SkillInvocationOut,
    TaskOut,
    VerificationRecordOut,
    WorkflowRunOut,
)
from app.services.audit_service import log_audit
from app.services.mapping_binding import assert_launch_datasource_pair
from app.services.platform_seed import get_published_business_center
from app.services.state_machine import assert_task_not_closed
from app.services.workflow_engine import WorkflowEngine
from app.services.workflow_facade import execute_through_review, resume_after_review

router = APIRouter(prefix="/tasks", tags=["tasks"])

SAMPLE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "sample-data"

from app.services.fangtai_paths import attach_fangtai_auxiliary_datasources as _attach_fangtai_auxiliary_datasources


def _require_published_center(db: Session):
    bc = get_published_business_center(db)
    if not bc or bc.status != BusinessCenterStatus.PUBLISHED.value:
        raise HTTPException(403, "收入核对中心尚未发布，请联系管理员在后台发布后再使用")
    return bc


def _resolve_demo_paths(dataset_id: str) -> dict[str, str]:
    manifest_path = SAMPLE_ROOT / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, "演示数据 manifest 不存在")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ds = next((d for d in manifest.get("datasets", []) if d["id"] == dataset_id), None)
    if not ds:
        raise HTTPException(404, f"演示数据集 {dataset_id} 不存在")
    files = ds.get("files", {})
    paths: dict[str, str] = {}
    if "business" in files:
        paths["business"] = str(SAMPLE_ROOT / files["business"])
        paths["sap"] = paths["business"]
    if "finance" in files:
        paths["finance"] = str(SAMPLE_ROOT / files["finance"])
        paths["dms"] = paths["finance"]
    if "statement" in files:
        paths["statement"] = str(SAMPLE_ROOT / files["statement"])
        paths["fanruan"] = paths["statement"]
    return paths


async def _save_upload(upload: UploadFile, task_id: str, name: str) -> str:
    suffix = Path(upload.filename or "data.csv").suffix or ".csv"
    dest = UPLOAD_DIR / f"{task_id}_{name}{suffix}"
    content = await upload.read()
    dest.write_bytes(content)
    return str(dest)


def _copy_demo_files(task_id: str, paths: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("business", "finance", "statement"):
        src = paths.get(key)
        if not src:
            continue
        suffix = Path(src).suffix
        dest = UPLOAD_DIR / f"{task_id}_{key}{suffix}"
        shutil.copy2(src, dest)
        out[key] = str(dest)
        if key == "business":
            out["sap"] = str(dest)
        if key == "finance":
            out["dms"] = str(dest)
        if key == "statement":
            out["fanruan"] = str(dest)
    return out


@router.get("", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Task)
    if user.role not in ("admin", "manager"):
        q = q.filter(Task.creator_id == user.id)
    return q.order_by(Task.created_at.desc()).all()


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


async def _execute_task_bg(task_id: str, file_paths: dict[str, str], user_id: str):
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if task and user:
            await _execute_task(db, task, file_paths, user)
    finally:
        db.close()


def _is_stuck_running_task(task: Task, *, min_idle_seconds: int = 90) -> bool:
    if task.status != TaskStatus.RUNNING.value or task.progress >= 85:
        return False
    if not task.updated_at:
        return True
    idle = (datetime.utcnow() - task.updated_at).total_seconds()
    return idle >= min_idle_seconds


def _prepare_task_rerun(db: Session, task: Task) -> None:
    db.query(Difference).filter(Difference.task_id == task.id).delete()
    task.error_message = None
    task.status = TaskStatus.RUNNING.value
    db.commit()


async def resume_stuck_tasks_on_startup(*, min_idle_seconds: int = 90) -> int:
    """服务启动后恢复因 reload/崩溃中断的 running 任务。"""
    import asyncio

    await asyncio.sleep(2)
    db = SessionLocal()
    resumed = 0
    try:
        stuck = (
            db.query(Task)
            .filter(Task.status == TaskStatus.RUNNING.value, Task.progress < 85)
            .all()
        )
        for task in stuck:
            if not _is_stuck_running_task(task, min_idle_seconds=min_idle_seconds):
                continue
            paths = task.data_sources or {}
            user_id = task.creator_id
            if not paths or not user_id:
                continue
            _prepare_task_rerun(db, task)
            asyncio.create_task(_execute_task_bg(task.id, paths, user_id))
            resumed += 1
    finally:
        db.close()
    return resumed


@router.post("", response_model=TaskOut)
async def create_task(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    period: str = Form("2024-05"),
    demo_dataset_id: str | None = Form(None),
    business_datasource_id: str | None = Form(None),
    finance_datasource_id: str | None = Form(None),
    sap_file: UploadFile | None = File(None),
    dms_file: UploadFile | None = File(None),
    fanruan_file: UploadFile | None = File(None),
    business_file: UploadFile | None = File(None),
    finance_file: UploadFile | None = File(None),
    combined_file: UploadFile | None = File(None),
    auto_execute: str = Form("true"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bc = _require_published_center(db)
    task_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())

    file_paths: dict[str, str] = {}
    biz_ds = fin_ds = None

    _has_combined = (
        combined_file is not None
        and getattr(combined_file, "filename", None)
        and str(combined_file.filename).strip()
    )
    if _has_combined:
        saved = await _save_upload(combined_file, task_id, "combined")  # type: ignore[arg-type]
        file_paths["combined"] = saved
        file_paths["business"] = saved
        file_paths["sap"] = saved
        file_paths["finance"] = saved
        file_paths["dms"] = saved
    elif business_datasource_id and finance_datasource_id:
        biz_ds = db.query(DataSource).filter(DataSource.id == business_datasource_id).first()
        fin_ds = db.query(DataSource).filter(DataSource.id == finance_datasource_id).first()
        if not biz_ds or not fin_ds:
            raise HTTPException(404, "指定的数据源不存在")
        assert_launch_datasource_pair(db, bc.id, business_datasource_id, finance_datasource_id)
        file_paths["business"] = biz_ds.file_path
        file_paths["sap"] = biz_ds.file_path
        file_paths["finance"] = fin_ds.file_path
        file_paths["dms"] = fin_ds.file_path
        _attach_fangtai_auxiliary_datasources(db, file_paths)
    elif demo_dataset_id:
        demo_paths = _resolve_demo_paths(demo_dataset_id)
        file_paths = _copy_demo_files(task_id, demo_paths)
    else:
        biz = business_file or sap_file
        fin = finance_file or dms_file
        if not biz or not fin:
            raise HTTPException(400, "请上传业务侧与财务侧数据、综合数据文件，或选择演示数据集")
        file_paths["business"] = await _save_upload(biz, task_id, "business")
        file_paths["sap"] = file_paths["business"]
        file_paths["finance"] = await _save_upload(fin, task_id, "finance")
        file_paths["dms"] = file_paths["finance"]
        if fanruan_file and fanruan_file.filename:
            file_paths["statement"] = await _save_upload(fanruan_file, task_id, "statement")
            file_paths["fanruan"] = file_paths["statement"]

    wf = db.query(Workflow).filter(Workflow.id == bc.workflow_id).first() if bc.workflow_id else None

    task_summary: dict = {
        "workflow_id": bc.workflow_id,
        "rule_version": bc.rule_version_id,
        "data_source_mode": (
            "datasource" if biz_ds
            else "combined" if _has_combined
            else "demo" if demo_dataset_id
            else "upload"
        ),
    }
    if biz_ds and fin_ds:
        task_summary.update({
            "business_datasource_id": biz_ds.id,
            "finance_datasource_id": fin_ds.id,
            "business_datasource_name": biz_ds.name,
            "finance_datasource_name": fin_ds.name,
        })
    if demo_dataset_id:
        task_summary["demo_dataset_id"] = demo_dataset_id

    task = Task(
        id=task_id,
        business_center_id=bc.id,
        name=name,
        period=period,
        initiator=user.id,
        status=TaskStatus.DRAFT.value,
        progress=0,
        creator_id=user.id,
        business_input_file=file_paths.get("business"),
        finance_input_file=file_paths.get("finance"),
        statement_input_file=file_paths.get("statement"),
        data_sources=file_paths,
        workflow_version=wf.version if wf else 1,
        rule_version_id=bc.rule_version_id,
        demo_dataset_id=demo_dataset_id,
        trace_id=trace_id,
        summary=task_summary,
    )
    db.add(task)
    log_audit(
        db,
        user=user,
        trace_id=trace_id,
        object_type="task",
        object_id=task_id,
        action="create_task",
        after_data={
            "name": name,
            "period": period,
            "demo_dataset_id": demo_dataset_id,
            "business_datasource_id": business_datasource_id,
            "finance_datasource_id": finance_datasource_id,
        },
    )
    db.commit()
    db.refresh(task)

    should_execute = auto_execute.lower() in ("true", "1", "yes", "on")
    if should_execute:
        task.status = TaskStatus.RUNNING.value
        db.commit()
        background_tasks.add_task(_execute_task_bg, task_id, file_paths, user.id)
        db.refresh(task)

    return task


async def _execute_task(db: Session, task: Task, file_paths: dict[str, str], user: User):
    task.status = TaskStatus.RUNNING.value
    db.commit()
    log_audit(
        db,
        user=user,
        trace_id=task.trace_id,
        object_type="task",
        object_id=task.id,
        action="upload_data",
        detail={"files": list(file_paths.keys())},
    )
    db.commit()
    await execute_through_review(db, task, file_paths, user)


@router.post("/{task_id}/execute", response_model=TaskOut)
async def execute_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status not in (TaskStatus.DRAFT.value, TaskStatus.FAILED.value):
        raise HTTPException(400, f"当前状态 {task.status} 不可执行")
    task.status = TaskStatus.RUNNING.value
    db.commit()
    background_tasks.add_task(_execute_task_bg, task_id, task.data_sources or {}, user.id)
    db.refresh(task)
    return task


@router.post("/{task_id}/resume-execution", response_model=TaskOut)
async def resume_task_execution(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """恢复卡在 running 且长时间无进展的任务（常见于服务 reload 中断后台流水线）。"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status == TaskStatus.FAILED.value:
        _prepare_task_rerun(db, task)
    elif not _is_stuck_running_task(task, min_idle_seconds=30):
        raise HTTPException(400, "任务仍在正常执行中，请稍候刷新")
    else:
        _prepare_task_rerun(db, task)
    paths = task.data_sources or {}
    if not paths.get("business") and not paths.get("sap"):
        raise HTTPException(400, "任务缺少数据源，无法恢复执行")
    background_tasks.add_task(_execute_task_bg, task_id, paths, user.id)
    log_audit(
        db,
        user=user,
        trace_id=task.trace_id,
        object_type="task",
        object_id=task.id,
        action="resume_execution",
        detail={"progress_before": task.progress},
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}/differences", response_model=list[DifferenceOut])
def list_differences(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.query(Task).filter(Task.id == task_id).first():
        raise HTTPException(404, "任务不存在")
    return db.query(Difference).filter(Difference.task_id == task_id).all()


@router.get("/{task_id}/workflow-runs", response_model=list[WorkflowRunOut])
def workflow_runs(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(WorkflowRun).filter(WorkflowRun.task_id == task_id).order_by(WorkflowRun.created_at).all()


@router.get("/{task_id}/skill-invocations", response_model=list[SkillInvocationOut])
def task_skill_invocations(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import SkillInvocation

    if not db.query(Task).filter(Task.id == task_id).first():
        raise HTTPException(404, "任务不存在")
    return (
        db.query(SkillInvocation)
        .filter(SkillInvocation.task_id == task_id)
        .order_by(SkillInvocation.started_at)
        .all()
    )


@router.get("/{task_id}/audit-logs", response_model=list[AuditLogOut])
def task_audit_logs(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import AuditLog
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    q = db.query(AuditLog).filter(
        (AuditLog.object_id == task_id) | (AuditLog.trace_id == task.trace_id)
    )
    return q.order_by(AuditLog.created_at).all()


@router.post("/{task_id}/verify")
async def verify_task(
    task_id: str,
    demo_dataset_id: str = Form("dataset_fangtai_real"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    assert_task_not_closed(task.status)
    # 仅 pending_verification 可执行再次验证：pending_review 不允许直接 verify（§11）
    if task.status != TaskStatus.PENDING_VERIFICATION.value:
        raise HTTPException(
            400,
            "仅“待验证”状态可执行再次验证；请先完成复核与责任处理（pending_review 不能直接验证）",
        )
    paths = task.data_sources or {}
    if not paths.get("business") and not paths.get("sap"):
        demo_paths = _resolve_demo_paths(demo_dataset_id)
        paths = demo_paths
    engine = WorkflowEngine(db, task)
    result = await engine.run_verification(paths, user.id)
    return result


@router.post("/{task_id}/approve-review")
async def approve_task_review(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上级/管理员审批复核流转，通过后自动进入再次验证。"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    assert_task_not_closed(task.status)
    from app.services.review_flow_service import approve_review_and_advance

    result = await approve_review_and_advance(db, task, user, auto_verify=True)
    db.commit()
    db.refresh(task)
    return {"task": TaskOut.model_validate(task), **result}


@router.post("/{task_id}/report", response_model=ReportOut)
def generate_report(
    task_id: str,
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.task_report_service import create_task_pdf_report

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    assert_task_not_closed(task.status)
    if task.status != TaskStatus.REPORTING.value:
        raise HTTPException(
            400,
            "仅“报告输出”状态可生成报告；请先完成再次验证（pending_review / processing 不能直接生成报告）",
        )
    if (task.summary or {}).get("report_path") and not force:
        existing = db.query(Report).filter(Report.task_id == task_id).order_by(Report.generated_at.desc()).first()
        if existing:
            return existing
    try:
        report = create_task_pdf_report(db, task, user=user)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    db.refresh(report)
    return report


@router.post("/{task_id}/close", response_model=TaskOut)
def close_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status != TaskStatus.REPORTING.value:
        raise HTTPException(400, "请先生成报告后再关闭任务")
    before = task.status
    task.status = TaskStatus.CLOSED.value
    task.progress = 100
    task.closed_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    db.add(
        WorkflowRun(
            id=str(uuid.uuid4()),
            task_id=task_id,
            workflow_id=(task.summary or {}).get("workflow_id") or "",
            node_id="report",
            node_label="报告生成",
            status="completed",
            detail={"message": "任务已关闭，流程结束"},
        )
    )
    for d in db.query(Difference).filter(Difference.task_id == task_id).all():
        if d.status not in (DifferenceStatus.REJECTED.value, DifferenceStatus.CLOSED.value):
            d.status = DifferenceStatus.CLOSED.value
    log_audit(
        db,
        user=user,
        trace_id=task.trace_id,
        object_type="task",
        object_id=task_id,
        action="close_task",
        before_data={"status": before},
        after_data={"status": TaskStatus.CLOSED.value},
    )
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.models import CaseAsset, ProcessingRecord, ReviewAction, SkillInvocation, VerificationRecord

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    if user.role not in ("admin", "manager") and task.creator_id != user.id:
        raise HTTPException(403, "无权删除此任务")
    if task.status == TaskStatus.RUNNING.value:
        raise HTTPException(400, "执行中的任务不可删除，请稍后再试")
    if db.query(CaseAsset).filter(CaseAsset.source_task_id == task_id).first():
        raise HTTPException(400, "任务已沉淀案例，不可删除")

    diff_ids = [d.id for d in db.query(Difference).filter(Difference.task_id == task_id).all()]
    if diff_ids:
        db.query(ReviewAction).filter(ReviewAction.difference_item_id.in_(diff_ids)).delete(
            synchronize_session=False
        )
        db.query(ProcessingRecord).filter(ProcessingRecord.difference_item_id.in_(diff_ids)).delete(
            synchronize_session=False
        )
        db.query(VerificationRecord).filter(VerificationRecord.difference_item_id.in_(diff_ids)).delete(
            synchronize_session=False
        )

    db.query(VerificationRecord).filter(VerificationRecord.task_id == task_id).delete(synchronize_session=False)
    db.query(WorkflowRun).filter(WorkflowRun.task_id == task_id).delete(synchronize_session=False)
    db.query(SkillInvocation).filter(SkillInvocation.task_id == task_id).delete(synchronize_session=False)
    db.query(Report).filter(Report.task_id == task_id).delete(synchronize_session=False)
    db.query(Difference).filter(Difference.task_id == task_id).delete(synchronize_session=False)

    log_audit(
        db,
        user=user,
        trace_id=task.trace_id,
        object_type="task",
        object_id=task_id,
        action="delete_task",
        before_data={"name": task.name, "status": task.status},
    )

    task_dir = UPLOAD_DIR / task_id
    if task_dir.is_dir():
        shutil.rmtree(task_dir, ignore_errors=True)

    db.delete(task)
    db.commit()


@router.post("/{task_id}/continue-workflow", response_model=TaskOut)
async def continue_workflow(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """继续 Workflow：无差异时自动跳过复核/验证；待验证时执行再次验证。"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status == TaskStatus.RUNNING.value:
        raise HTTPException(400, "任务仍在执行中，请稍候刷新")
    if task.status == TaskStatus.CLOSED.value:
        raise HTTPException(400, "任务已关闭")

    engine = WorkflowEngine(db, task)
    diff_count = db.query(Difference).filter(Difference.task_id == task_id).count()

    if task.status == TaskStatus.PENDING_REVIEW.value and diff_count == 0:
        engine._advance_zero_diff_to_reporting(trigger="continue_api", user_id=user.id)
    elif task.status == TaskStatus.PENDING_VERIFICATION.value:
        paths = task.data_sources or {}
        if not paths.get("business") and not paths.get("sap"):
            raise HTTPException(400, "任务缺少数据源，无法再次验证")
        await engine.run_verification(paths, user.id)
    elif task.status == TaskStatus.REPORTING.value:
        if not (task.summary or {}).get("report_path"):
            from app.services.task_report_service import create_task_pdf_report

            try:
                create_task_pdf_report(db, task, user=user)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
    else:
        raise HTTPException(
            400,
            f"当前状态「{task.status}」不可继续；有差异时请先在「待复核」中处理",
        )

    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task
