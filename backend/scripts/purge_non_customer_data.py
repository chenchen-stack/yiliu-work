"""
清理与客户 POC 无关的历史演示数据：旧任务、上传文件、报告、会话及非方太数据源。

用法:
  cd backend
  .venv/Scripts/python.exe -m scripts.purge_non_customer_data
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import REPORT_DIR, UPLOAD_DIR
from app.database import SessionLocal, engine, Base
from app.models import (
    AgentRun, AuditLog, CaseAsset, Conversation, DataSource, Difference,
    ProcessingRecord, Report, ReviewAction, SkillInvocation, Task, VerificationRecord,
    WorkflowRun,
)
from scripts.import_poc_data import CANONICAL_SHEET_NAMES, purge_legacy_datasources, run as import_poc

LEGACY_DEMO_DATASET_IDS = frozenset({
    "dataset_full",
    "dataset_fangtai",
    "dataset_revenue",
    "dataset_corrected",
})


def _unlink(path: str | None) -> bool:
    if not path:
        return False
    p = Path(path)
    if not p.is_file():
        return False
    p.unlink(missing_ok=True)
    return True


def _delete_task_artifacts(task: Task) -> None:
    ds = task.data_sources or {}
    for key in ("business", "finance", "statement", "sap", "dms", "fanruan", "combined"):
        _unlink(ds.get(key))
    for suffix in ("_business.csv", "_finance.csv", "_statement.csv", "_combined.xlsx", "_combined.xls"):
        _unlink(str(UPLOAD_DIR / f"{task.id}{suffix}"))
    task_dir = UPLOAD_DIR / task.id
    if task_dir.is_dir():
        shutil.rmtree(task_dir, ignore_errors=True)


def purge_tasks_and_related(db) -> dict[str, int]:
    stats = {
        "tasks": 0,
        "differences": 0,
        "reports": 0,
        "conversations": 0,
        "agent_runs": 0,
        "case_assets": 0,
        "upload_files": 0,
        "report_files": 0,
    }

    task_ids = [t.id for t in db.query(Task).all()]
    if task_ids:
        diff_ids = [d.id for d in db.query(Difference).filter(Difference.task_id.in_(task_ids)).all()]
        if diff_ids:
            db.query(ReviewAction).filter(ReviewAction.difference_item_id.in_(diff_ids)).delete(synchronize_session=False)
            db.query(ProcessingRecord).filter(ProcessingRecord.difference_item_id.in_(diff_ids)).delete(synchronize_session=False)
            db.query(VerificationRecord).filter(VerificationRecord.difference_item_id.in_(diff_ids)).delete(synchronize_session=False)
        db.query(VerificationRecord).filter(VerificationRecord.task_id.in_(task_ids)).delete(synchronize_session=False)
        db.query(WorkflowRun).filter(WorkflowRun.task_id.in_(task_ids)).delete(synchronize_session=False)
        db.query(SkillInvocation).filter(SkillInvocation.task_id.in_(task_ids)).delete(synchronize_session=False)

        reports = db.query(Report).filter(Report.task_id.in_(task_ids)).all()
        for rep in reports:
            if _unlink(rep.file_url):
                stats["report_files"] += 1
        stats["reports"] = db.query(Report).filter(Report.task_id.in_(task_ids)).delete(synchronize_session=False)

        stats["differences"] = db.query(Difference).filter(Difference.task_id.in_(task_ids)).delete(synchronize_session=False)
        stats["case_assets"] = db.query(CaseAsset).filter(CaseAsset.source_task_id.in_(task_ids)).delete(synchronize_session=False)

        for task in db.query(Task).filter(Task.id.in_(task_ids)).all():
            _delete_task_artifacts(task)
            stats["upload_files"] += 1
            db.delete(task)
            stats["tasks"] += 1

    stats["conversations"] = db.query(Conversation).delete(synchronize_session=False)
    stats["agent_runs"] = db.query(AgentRun).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.object_type.in_(["task", "difference", "conversation"])).delete(synchronize_session=False)
    return stats


def purge_orphan_uploads(db) -> int:
    keep: set[str] = set()
    for row in db.query(DataSource).all():
        if row.file_path:
            keep.add(str(Path(row.file_path).resolve()))

    removed = 0
    if not UPLOAD_DIR.exists():
        return 0
    for f in UPLOAD_DIR.iterdir():
        if not f.is_file():
            continue
        if str(f.resolve()) in keep:
            continue
        f.unlink(missing_ok=True)
        removed += 1
    return removed


def purge_orphan_reports(db) -> int:
    keep = {str(Path(r.file_url).resolve()) for r in db.query(Report).all() if r.file_url}
    removed = 0
    if not REPORT_DIR.exists():
        return 0
    for f in REPORT_DIR.glob("*.pdf"):
        if str(f.resolve()) in keep:
            continue
        f.unlink(missing_ok=True)
        removed += 1
    return removed


def purge_non_canonical_datasources(db) -> int:
    removed = 0
    canonical = set(CANONICAL_SHEET_NAMES)
    for row in db.query(DataSource).all():
        if row.name in canonical:
            continue
        if _unlink(row.file_path):
            pass
        db.delete(row)
        removed += 1
        print(f"[purge] 删除非 POC DataSource「{row.name}」")
    return removed


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        print("[1/4] 清理历史任务、差异、报告、会话…")
        stats = purge_tasks_and_related(db)
        db.commit()
        for k, v in stats.items():
            if v:
                print(f"      {k}: {v}")

        print("[2/4] 清理非方太 POC 数据源…")
        n_ds = purge_non_canonical_datasources(db)
        n_legacy = purge_legacy_datasources(db)
        db.commit()
        print(f"      非 POC 数据源: {n_ds}，历史/演示: {n_legacy}")

        print("[3/4] 清理孤立上传与报告文件…")
        n_up = purge_orphan_uploads(db)
        n_rep = purge_orphan_reports(db)
        print(f"      上传文件: {n_up}，报告 PDF: {n_rep}")

        db.commit()
    finally:
        db.close()

    print("[4/4] 重新导入方太 POC Excel…")
    import_poc()

    from app.models import MappingConfig
    from app.services.mapping_binding import set_mapping_binding, validate_datasource_pair
    from app.services.platform_seed import IDS
    from scripts.seed_fangtai_poc_closure import BILLING_LEDGER_MAPPING, _seed_billing_mapping

    db = SessionLocal()
    try:
        _seed_billing_mapping(db)
        biz = db.query(DataSource).filter(DataSource.name == "SAP结算行明细").first()
        fin = db.query(DataSource).filter(DataSource.name == "DMS收入台账明细").first()
        if biz and fin:
            v = validate_datasource_pair(db, IDS["business_center"], biz, fin)
            set_mapping_binding(
                IDS["business_center"],
                business_datasource_id=biz.id,
                finance_datasource_id=fin.id,
                mapping_row_count=db.query(MappingConfig).filter(
                    MappingConfig.business_center_id == IDS["business_center"]
                ).count(),
                validated=v.ready,
                message=v.message,
            )
        db.commit()
        print(f"\n[done] 仅保留方太 POC 真实数据（{len(CANONICAL_SHEET_NAMES)} 张表）。")
        print("     映射行数:", len(BILLING_LEDGER_MAPPING))
        if biz and fin:
            print(f"     默认表对: {biz.name} <-> {fin.name}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
