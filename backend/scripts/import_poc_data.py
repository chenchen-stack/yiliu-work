"""
将方太真实 POC Excel 转为 CSV 并注册到 DataSource，构建真实业务闭环。
数据源名称与 Excel Sheet 名完全一致，不自行改名。

用法:
  cd backend
  .venv/Scripts/Activate.ps1
  python -m scripts.import_poc_data
"""
from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import UPLOAD_DIR
from app.database import SessionLocal, engine, Base
from app.models import DataSource
from app.services.mapping_engine import detect_data_profile

# 方太客户最新 POC 数据（微信附件）
SRC_XLSX_CANDIDATES = [
    Path(
        r"c:\Users\10250\Documents\xwechat_files\wxid_pxwz921zq21g12_6ab0\msg\attach\508cb889fb0d2b71bd491b0166d9ae16\2026-06\Rec\837681d23baa49d1\F\0\收入对账-POC数据(1).xlsx"
    ),
    Path(
        r"c:\Users\10250\Documents\xwechat_files\wxid_pxwz921zq21g12_6ab0\msg\file\2026-06\收入对账-POC数据.xlsx"
    ),
]
SAMPLE_ROOT = Path(__file__).resolve().parent.parent.parent / "sample-data"
DEST_DIR = SAMPLE_ROOT / "dataset_fangtai_real"

# 旧演示数据集目录（合成数据，全部废弃）
LEGACY_DATASET_DIRS = (
    "dataset_fangtai",
    "dataset_full",
    "dataset_revenue",
)

# 历史英文别名 CSV（与 Sheet 名不一致，删除避免混用）
STALE_CSV_NAMES = {
    "dms_payment_detail.csv",
    "dms_settlement_detail.csv",
    "dms_shipping_ledger.csv",
    "sap_billing_detail.csv",
    "sap_revenue_total.csv",
    "reconciliation_summary.csv",
    "SAP发货开票明细.csv",
}


def _csv_name_for_sheet(sheet: str) -> str:
    safe = sheet.replace("/", "_").replace("\\", "_")
    return f"{safe}.csv"


POC_DATASOURCES = [
    {"sheet": "帆软对账平台", "system_type": "fanruan", "side": "business"},
    {"sheet": "DMS收入台账明细", "system_type": "dms", "side": "finance"},
    {"sheet": "DMS结算单明细", "system_type": "dms", "side": "finance"},
    {"sheet": "DMS订单明细", "system_type": "dms", "side": "finance"},
    {"sheet": "SAP收入总额", "system_type": "sap", "side": "business"},
    {"sheet": "SAP结算行明细", "system_type": "sap", "side": "business"},
    {"sheet": "SAP结算单明细", "system_type": "sap", "side": "business"},
    {"sheet": "SAP结算单对应的订单行明细", "system_type": "sap", "side": "business"},
]

CANONICAL_SHEET_NAMES = {cfg["sheet"] for cfg in POC_DATASOURCES}

# 历史 DataSource 名称 → 当前 Sheet 名
LEGACY_NAME_MAP = {
    "方太收入对账平台（汇总）": "帆软对账平台",
    "方太SAP收入总额": "SAP收入总额",
    "方太SAP发货开票明细": "SAP结算行明细",
    "SAP发货开票明细": "SAP结算行明细",
    "方太DMS发货台账明细": "DMS收入台账明细",
    "方太DMS回款明细": "DMS订单明细",
    "方太DMS结算单明细": "DMS结算单明细",
    "方太SAP收入凭证（演示）": None,
    "方太DMS收入台账（演示）": None,
}


def _resolve_src_xlsx() -> Path | None:
    for p in SRC_XLSX_CANDIDATES:
        if p.exists():
            return p
    dest_xlsx = next(DEST_DIR.glob("*.xlsx"), None) if DEST_DIR.exists() else None
    return dest_xlsx


def _resolve_sheet_name(sheet_names: list[str], canonical: str) -> str | None:
    if canonical in sheet_names:
        return canonical
    for sn in sheet_names:
        if canonical in sn or sn in canonical:
            return sn
    if canonical == "SAP结算行明细":
        for sn in sheet_names:
            if "结算行" in sn and "SAP" in sn:
                return sn
    return None


def purge_legacy_sample_files() -> None:
    for dirname in LEGACY_DATASET_DIRS:
        d = SAMPLE_ROOT / dirname
        if d.exists():
            shutil.rmtree(d)
            print(f"[purge] 已删除旧演示目录 {dirname}/")

    if not DEST_DIR.exists():
        return
    keep = {_csv_name_for_sheet(s) for s in CANONICAL_SHEET_NAMES}
    for csv in DEST_DIR.glob("*.csv"):
        if csv.name not in keep or csv.name in STALE_CSV_NAMES:
            csv.unlink(missing_ok=True)
            print(f"[purge] 已删除旧 CSV {csv.name}")


def purge_legacy_datasources(db) -> int:
    removed = 0
    canonical_rows = {
        row.name: row
        for row in db.query(DataSource).filter(DataSource.name.in_(list(CANONICAL_SHEET_NAMES))).all()
    }

    for old_name, new_name in LEGACY_NAME_MAP.items():
        row = db.query(DataSource).filter(DataSource.name == old_name).first()
        if not row:
            continue
        if new_name is None:
            fp = Path(row.file_path) if row.file_path else None
            db.delete(row)
            if fp and fp.exists() and str(fp).startswith(str(UPLOAD_DIR)):
                fp.unlink(missing_ok=True)
            removed += 1
            print(f"[purge] 已删除演示 DataSource「{old_name}」")
            continue
        if new_name in canonical_rows and canonical_rows[new_name].id != row.id:
            fp = Path(row.file_path) if row.file_path else None
            db.delete(row)
            if fp and fp.exists() and str(fp).startswith(str(UPLOAD_DIR)):
                fp.unlink(missing_ok=True)
            removed += 1
            print(f"[purge] 已删除重复 DataSource「{old_name}」（已由「{new_name}」替代）")
            continue
        row.name = new_name
        removed += 1
        print(f"[ok] 重命名 DataSource: {old_name} → {new_name}")

    demo_rows = db.query(DataSource).filter(DataSource.name.like("%演示%")).all()
    for row in demo_rows:
        fp = Path(row.file_path) if row.file_path else None
        db.delete(row)
        if fp and fp.exists() and str(fp).startswith(str(UPLOAD_DIR)):
            fp.unlink(missing_ok=True)
        removed += 1
        print(f"[purge] 已删除演示 DataSource「{row.name}」")

    return removed


def _upsert_datasource(db, cfg: dict, df: pd.DataFrame, csv_path: Path) -> None:
    ds_name = cfg["sheet"]
    profile = detect_data_profile(df)
    detected_profile = profile if profile != "unknown" else cfg["system_type"]
    columns = list(df.columns.astype(str))

    for legacy in LEGACY_NAME_MAP:
        if LEGACY_NAME_MAP[legacy] != ds_name:
            continue
        old = db.query(DataSource).filter(DataSource.name == legacy).first()
        if old:
            db.delete(old)

    existing = db.query(DataSource).filter(DataSource.name == ds_name).first()
    if existing:
        existing.system_type = cfg["system_type"]
        existing.side = cfg["side"]
        existing.row_count = len(df)
        existing.detected_columns = columns
        existing.detected_profile = detected_profile
        existing.status = "active"
        upload_dest = Path(existing.file_path)
        if not upload_dest.parent.exists():
            upload_dest = UPLOAD_DIR / f"ds_{existing.id}.csv"
            existing.file_path = str(upload_dest)
        shutil.copy2(csv_path, upload_dest)
        print(f"     [update] DataSource「{ds_name}」({len(df)} 行, profile={detected_profile})")
        return

    ds_id = str(uuid.uuid4())
    upload_dest = UPLOAD_DIR / f"ds_{ds_id}.csv"
    shutil.copy2(csv_path, upload_dest)
    db.add(
        DataSource(
            id=ds_id,
            name=ds_name,
            system_type=cfg["system_type"],
            side=cfg["side"],
            file_path=str(upload_dest),
            detected_columns=columns,
            detected_profile=detected_profile,
            row_count=len(df),
            status="active",
        )
    )
    print(f"     [ok] DataSource「{ds_name}」({len(df)} 行, profile={detected_profile})")


def run():
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    purge_legacy_sample_files()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        n = purge_legacy_datasources(db)
        if n:
            db.commit()
            print(f"[info] 已清理 {n} 条历史/演示数据源\n")

        src = _resolve_src_xlsx()
        if not src:
            print("[error] 未找到方太 POC Excel，请确认附件路径。")
            return

        dest_xlsx = DEST_DIR / src.name
        if not dest_xlsx.exists() or src.stat().st_mtime > dest_xlsx.stat().st_mtime:
            shutil.copy2(src, dest_xlsx)
            print(f"[ok] Excel 已复制到 sample-data: {dest_xlsx.name}")

        xls = pd.ExcelFile(src)
        print(f"[info] 使用 Excel: {src}")
        print(f"[info] Sheets: {xls.sheet_names}\n")

        exported_csvs: set[str] = set()
        for cfg in POC_DATASOURCES:
            canonical = cfg["sheet"]
            sheet = _resolve_sheet_name(xls.sheet_names, canonical)
            if not sheet:
                print(f"[warn] Sheet「{canonical}」不存在，跳过")
                continue
            if sheet != canonical:
                print(f"[info] Sheet「{canonical}」→ 读取「{sheet}」")

            df = pd.read_excel(src, sheet_name=sheet)
            csv_path = DEST_DIR / _csv_name_for_sheet(canonical)
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            exported_csvs.add(csv_path.name)
            print(f"[ok] {canonical} → {csv_path.name}  ({df.shape[0]} 行 × {df.shape[1]} 列)")
            _upsert_datasource(db, cfg, df, csv_path)

        for csv in DEST_DIR.glob("*.csv"):
            if csv.name not in exported_csvs:
                csv.unlink(missing_ok=True)
                print(f"[purge] 移除未使用 CSV {csv.name}")

        db.commit()
        print("\n[done] 方太真实 POC 数据已全部导入并注册为 DataSource。")
    finally:
        db.close()


if __name__ == "__main__":
    run()
