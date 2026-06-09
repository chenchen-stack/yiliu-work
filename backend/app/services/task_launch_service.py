"""从对话或 API 发起核对任务（复用任务创建逻辑）。"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.config import UPLOAD_DIR
from app.database import SessionLocal
from app.models import BusinessCenterStatus, DataSource, Task, TaskStatus, User, Workflow
from app.services.audit_service import log_audit
from app.services.mapping_binding import assert_launch_datasource_pair
from app.services.platform_seed import get_published_business_center
from app.services.fangtai_paths import attach_fangtai_auxiliary_datasources
from app.services.workflow_facade import execute_through_review

SAMPLE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "sample-data"


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


async def _execute_task_bg(task_id: str, file_paths: dict[str, str], user_id: str):
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        user = db.query(User).filter(User.id == user_id).first()
        if task and user:
            await _execute_task(db, task, file_paths, user)
    finally:
        db.close()


def launch_reconciliation_task(
    db: Session,
    user: User,
    *,
    name: str,
    period: str,
    business_datasource_id: str | None = None,
    finance_datasource_id: str | None = None,
    demo_dataset_id: str | None = None,
    background_tasks: BackgroundTasks | None = None,
    auto_execute: bool = True,
    workflow_id: str | None = None,
) -> Task:
    bc = get_published_business_center(db)
    if not bc or bc.status != BusinessCenterStatus.PUBLISHED.value:
        raise HTTPException(403, "收入核对中心尚未发布，请联系管理员在后台发布后再使用")

    task_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    file_paths: dict[str, str] = {}
    biz_ds = fin_ds = None

    if business_datasource_id and finance_datasource_id:
        biz_ds = db.query(DataSource).filter(DataSource.id == business_datasource_id).first()
        fin_ds = db.query(DataSource).filter(DataSource.id == finance_datasource_id).first()
        if not biz_ds or not fin_ds:
            raise HTTPException(404, "指定的数据源不存在")
        assert_launch_datasource_pair(db, bc.id, business_datasource_id, finance_datasource_id)
        file_paths["business"] = biz_ds.file_path
        file_paths["sap"] = biz_ds.file_path
        file_paths["finance"] = fin_ds.file_path
        file_paths["dms"] = fin_ds.file_path
        attach_fangtai_auxiliary_datasources(db, file_paths)
    elif demo_dataset_id:
        demo_paths = _resolve_demo_paths(demo_dataset_id)
        file_paths = _copy_demo_files(task_id, demo_paths)
    else:
        raise HTTPException(400, "请指定数据源或演示数据集")

    effective_wf_id = workflow_id or (bc.workflow_id if bc else None)
    wf = db.query(Workflow).filter(Workflow.id == effective_wf_id).first() if effective_wf_id else None
    task_summary: dict = {
        "workflow_id": effective_wf_id,
        "rule_version": bc.rule_version_id,
        "data_source_mode": "datasource" if biz_ds else "demo",
        "launch_source": "chat",
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
            "launch_source": "chat",
            "business_datasource_id": business_datasource_id,
            "finance_datasource_id": finance_datasource_id,
            "demo_dataset_id": demo_dataset_id,
        },
    )
    db.commit()
    db.refresh(task)

    if auto_execute:
        task.status = TaskStatus.RUNNING.value
        db.commit()
        if background_tasks is not None:
            background_tasks.add_task(_execute_task_bg, task_id, file_paths, user.id)
        db.refresh(task)

    return task
