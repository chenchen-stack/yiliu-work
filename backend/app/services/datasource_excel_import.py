"""从 Excel 工作簿批量注册数据源（方太 POC：一文件多 Sheet → 多张表）。"""

from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.config import UPLOAD_DIR
from app.models import DataSource
from app.services.mapping_engine import detect_data_profile

# 与 scripts/import_poc_data.py · 方太 POC 对齐
POC_SHEET_CONFIGS: list[dict[str, str]] = [
    {"sheet": "帆软对账平台", "system_type": "fanruan", "side": "business"},
    {"sheet": "DMS收入台账明细", "system_type": "dms", "side": "finance"},
    {"sheet": "DMS结算单明细", "system_type": "dms", "side": "finance"},
    {"sheet": "DMS订单明细", "system_type": "dms", "side": "finance"},
    {"sheet": "SAP收入总额", "system_type": "sap", "side": "business"},
    {"sheet": "SAP结算行明细", "system_type": "sap", "side": "business"},
    {"sheet": "SAP结算单明细", "system_type": "sap", "side": "business"},
    {"sheet": "SAP结算单对应的订单行明细", "system_type": "sap", "side": "business"},
]


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


def _infer_config_for_sheet(sheet_name: str) -> dict[str, str] | None:
    for cfg in POC_SHEET_CONFIGS:
        if cfg["sheet"] == sheet_name:
            return cfg
    sn = sheet_name.upper()
    if "帆软" in sheet_name:
        return {"sheet": sheet_name, "system_type": "fanruan", "side": "business"}
    if "DMS" in sn or "台账" in sheet_name or "订单" in sheet_name:
        side = "finance"
        return {"sheet": sheet_name, "system_type": "dms", "side": side}
    if "SAP" in sn or "结算" in sheet_name or "收入" in sheet_name:
        return {"sheet": sheet_name, "system_type": "sap", "side": "business"}
    return None


def _upsert_dataframe(
    db: Session,
    ds_name: str,
    system_type: str,
    side: str,
    df: pd.DataFrame,
) -> str:
    """返回 created | updated"""
    profile = detect_data_profile(df)
    detected_profile = profile if profile != "unknown" else system_type
    columns = list(df.columns.astype(str))

    existing = db.query(DataSource).filter(DataSource.name == ds_name).first()
    if existing:
        existing.system_type = system_type
        existing.side = side
        existing.row_count = len(df)
        existing.detected_columns = columns
        existing.detected_profile = detected_profile
        existing.status = "active"
        upload_dest = Path(existing.file_path) if existing.file_path else UPLOAD_DIR / f"ds_{existing.id}.csv"
        if not upload_dest.parent.exists():
            upload_dest = UPLOAD_DIR / f"ds_{existing.id}.csv"
            existing.file_path = str(upload_dest)
        df.to_csv(upload_dest, index=False, encoding="utf-8-sig")
        return "updated"

    ds_id = str(uuid.uuid4())
    upload_dest = UPLOAD_DIR / f"ds_{ds_id}.csv"
    df.to_csv(upload_dest, index=False, encoding="utf-8-sig")
    db.add(
        DataSource(
            id=ds_id,
            name=ds_name,
            system_type=system_type,
            side=side,
            file_path=str(upload_dest),
            detected_columns=columns,
            detected_profile=detected_profile,
            row_count=len(df),
            status="active",
        )
    )
    return "created"


def import_excel_workbook(
    db: Session,
    content: bytes,
    filename: str = "workbook.xlsx",
) -> dict[str, Any]:
    """
    将 Excel 中每个 Sheet 注册为独立 DataSource（名称 = Sheet 名）。
    优先按方太 POC 标准 Sheet 名匹配；其余 Sheet 按名称启发式分类。
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in (".xlsx", ".xls", ".xlsm"):
        raise ValueError("仅支持 Excel 工作簿（.xlsx / .xls）")

    bio = BytesIO(content)
    xls = pd.ExcelFile(bio)
    sheet_names = list(xls.sheet_names)

    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    used_sheets: set[str] = set()

    for cfg in POC_SHEET_CONFIGS:
        sheet = _resolve_sheet_name(sheet_names, cfg["sheet"])
        if not sheet:
            skipped.append({"sheet": cfg["sheet"], "reason": "工作簿中未找到该 Sheet"})
            continue
        used_sheets.add(sheet)
        df = pd.read_excel(xls, sheet_name=sheet)
        if df.empty:
            skipped.append({"sheet": sheet, "reason": "Sheet 为空"})
            continue
        action = _upsert_dataframe(db, cfg["sheet"], cfg["system_type"], cfg["side"], df)
        imported.append({
            "name": cfg["sheet"],
            "sheet": sheet,
            "row_count": len(df),
            "column_count": len(df.columns),
            "system_type": cfg["system_type"],
            "side": cfg["side"],
            "action": action,
        })

    for sheet in sheet_names:
        if sheet in used_sheets:
            continue
        cfg = _infer_config_for_sheet(sheet)
        if not cfg:
            skipped.append({"sheet": sheet, "reason": "无法识别分类，请用「单表上传」手动指定"})
            continue
        df = pd.read_excel(xls, sheet_name=sheet)
        if df.empty:
            skipped.append({"sheet": sheet, "reason": "Sheet 为空"})
            continue
        ds_name = cfg["sheet"]
        action = _upsert_dataframe(db, ds_name, cfg["system_type"], cfg["side"], df)
        imported.append({
            "name": ds_name,
            "sheet": sheet,
            "row_count": len(df),
            "column_count": len(df.columns),
            "system_type": cfg["system_type"],
            "side": cfg["side"],
            "action": action,
        })
        used_sheets.add(sheet)

    return {
        "filename": filename,
        "sheet_count": len(sheet_names),
        "imported": imported,
        "skipped": skipped,
        "message": f"已从「{filename}」导入 {len(imported)} 张表"
        + (f"，跳过 {len(skipped)} 项" if skipped else ""),
    }
