"""字段映射与数据源对绑定：前台任务仅能使用后台已配置并校验通过的表对。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import DATA_DIR
from app.models import DataSource, MappingConfig

BINDING_FILE = DATA_DIR / "mapping_binding.json"

# 核对最少需具备映射的核心字段
CORE_UNIFIED_FIELDS = ("sales_amount", "order_id", "invoice_num", "customer_id")


@dataclass
class PairValidation:
    ready: bool
    message: str = ""
    missing: list[str] = field(default_factory=list)
    mapping_row_count: int = 0
    core_mapped: int = 0


def _norm_cols(cols: list[str] | None) -> set[str]:
    return {str(c).strip().lower() for c in (cols or []) if str(c).strip()}


def _load_all_bindings() -> dict[str, dict[str, Any]]:
    if not BINDING_FILE.exists():
        return {}
    try:
        with open(BINDING_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def get_mapping_binding(business_center_id: str) -> dict[str, Any] | None:
    return _load_all_bindings().get(business_center_id)


def set_mapping_binding(
    business_center_id: str,
    *,
    business_datasource_id: str,
    finance_datasource_id: str,
    mapping_row_count: int,
    validated: bool,
    message: str = "",
) -> dict[str, Any]:
    all_data = _load_all_bindings()
    entry = {
        "business_center_id": business_center_id,
        "business_datasource_id": business_datasource_id,
        "finance_datasource_id": finance_datasource_id,
        "mapping_row_count": mapping_row_count,
        "validated": validated,
        "message": message,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    all_data[business_center_id] = entry
    BINDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BINDING_FILE, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    return entry


def _mapping_rows_from_db(db: Session, business_center_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in (
        db.query(MappingConfig)
        .filter(
            MappingConfig.business_center_id == business_center_id,
            MappingConfig.enabled.is_(True),
        )
        .all()
    ):
        spec: dict[str, Any] = {}
        raw_rule = c.transform_rule or ""
        if raw_rule.strip().startswith("{"):
            try:
                spec = json.loads(raw_rule)
            except json.JSONDecodeError:
                spec = {}
        finance_col = (spec.get("finance_column") or spec.get("dms") or "").strip()
        if not finance_col and raw_rule:
            for part in raw_rule.split(","):
                token = part.strip()
                if token.lower().startswith("dms:"):
                    finance_col = token.split(":", 1)[1].strip()
                    break
        rows.append(
            {
                "unified_field": c.target_field,
                "business_column": (c.source_field or "").strip(),
                "finance_column": finance_col,
                "enabled": c.enabled,
            }
        )
    return rows


def validate_datasource_pair(
    db: Session,
    business_center_id: str,
    biz_ds: DataSource,
    fin_ds: DataSource,
) -> PairValidation:
    if biz_ds.side != "business" or fin_ds.side != "finance":
        return PairValidation(False, "业务侧与财务侧数据源类型不正确")

    map_rows = _mapping_rows_from_db(db, business_center_id)
    if not map_rows:
        return PairValidation(False, "请先在管理后台「字段映射」配置并保存列对照")

    biz_cols = _norm_cols(biz_ds.detected_columns)
    fin_cols = _norm_cols(fin_ds.detected_columns)
    missing: list[str] = []
    core_ok = 0

    for uf in CORE_UNIFIED_FIELDS:
        row = next((r for r in map_rows if r["unified_field"] == uf), None)
        if not row or not row.get("business_column") or not row.get("finance_column"):
            continue
        bc = row["business_column"].lower()
        fc = row["finance_column"].lower()
        if bc not in biz_cols:
            missing.append(f"业务侧缺少列「{row['business_column']}」（{uf}）")
        if fc not in fin_cols:
            missing.append(f"财务侧缺少列「{row['finance_column']}」（{uf}）")
        if bc in biz_cols and fc in fin_cols:
            core_ok += 1

    amount_row = next((r for r in map_rows if r["unified_field"] == "sales_amount"), None)
    if not amount_row or not amount_row.get("business_column") or not amount_row.get("finance_column"):
        missing.append("未配置「金额」字段映射（sales_amount）")
    elif amount_row["business_column"].lower() not in biz_cols or amount_row["finance_column"].lower() not in fin_cols:
        if amount_row["business_column"].lower() not in biz_cols:
            missing.append(f"业务侧缺少金额列「{amount_row['business_column']}」")
        if amount_row["finance_column"].lower() not in fin_cols:
            missing.append(f"财务侧缺少金额列「{amount_row['finance_column']}」")

    key_ok = any(
        r["unified_field"] in ("order_id", "invoice_num")
        and r.get("business_column")
        and r.get("finance_column")
        and r["business_column"].lower() in biz_cols
        and r["finance_column"].lower() in fin_cols
        for r in map_rows
    )
    if not key_ok:
        missing.append("未配置可用的业务键映射（order_id 或 invoice_num）")

    ready = len(missing) == 0 and core_ok >= 1 and amount_row is not None
    msg = "映射校验通过" if ready else "；".join(missing[:4])
    if not ready and len(missing) > 4:
        msg += "…"
    return PairValidation(
        ready=ready,
        message=msg,
        missing=missing,
        mapping_row_count=len(map_rows),
        core_mapped=core_ok,
    )


def list_launch_datasource_pairs(
    db: Session,
    business_center_id: str,
    *,
    strict_binding: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """返回前台可选的数据源对。strict_binding=True 时仅返回后台绑定的表对。"""
    binding = get_mapping_binding(business_center_id)
    meta = {
        "mapping_configured": bool(binding),
        "binding": binding,
        "mapping_ready": False,
        "hint": "",
    }

    if not binding:
        meta["hint"] = "请管理员在「流程编排 → 字段映射」选择业务/财务表并保存映射后再创建任务"
        return [], meta

    biz = db.query(DataSource).filter(DataSource.id == binding.get("business_datasource_id")).first()
    fin = db.query(DataSource).filter(DataSource.id == binding.get("finance_datasource_id")).first()
    if not biz or not fin:
        meta["hint"] = "绑定的数据源已删除，请重新在管理后台配置字段映射"
        return [], meta

    validation = validate_datasource_pair(db, business_center_id, biz, fin)
    if not validation.ready:
        meta["hint"] = validation.message
        return [], meta

    pair = {
        "business_datasource_id": biz.id,
        "finance_datasource_id": fin.id,
        "business_name": biz.name,
        "finance_name": fin.name,
        "business_row_count": biz.row_count,
        "finance_row_count": fin.row_count,
        "is_default": True,
        "mapping_row_count": validation.mapping_row_count,
    }
    meta["mapping_ready"] = True
    meta["hint"] = "仅可使用管理后台已绑定并完成列校验的数据源对"

    if strict_binding:
        return [pair], meta

    # 非严格模式：所有校验通过的表对（预留）
    pairs = [pair]
    for b in db.query(DataSource).filter(DataSource.side == "business", DataSource.status == "active").all():
        for f in db.query(DataSource).filter(DataSource.side == "finance", DataSource.status == "active").all():
            if b.id == biz.id and f.id == fin.id:
                continue
            v = validate_datasource_pair(db, business_center_id, b, f)
            if v.ready:
                pairs.append(
                    {
                        "business_datasource_id": b.id,
                        "finance_datasource_id": f.id,
                        "business_name": b.name,
                        "finance_name": f.name,
                        "business_row_count": b.row_count,
                        "finance_row_count": f.row_count,
                        "is_default": False,
                        "mapping_row_count": v.mapping_row_count,
                    }
                )
    return pairs, meta


def assert_launch_datasource_pair(
    db: Session,
    business_center_id: str,
    business_datasource_id: str,
    finance_datasource_id: str,
) -> None:
    """创建任务前校验：必须为管理后台已绑定且列校验通过的表对。"""
    binding = get_mapping_binding(business_center_id)
    if not binding:
        raise HTTPException(
            400,
            "请管理员先在「流程编排 → 字段映射」选择业务/财务表并保存映射后再创建任务",
        )
    if (
        binding.get("business_datasource_id") != business_datasource_id
        or binding.get("finance_datasource_id") != finance_datasource_id
    ):
        raise HTTPException(
            400,
            "所选数据源对与管理后台字段映射绑定不一致，请使用已配置的表对",
        )
    biz = db.query(DataSource).filter(DataSource.id == business_datasource_id).first()
    fin = db.query(DataSource).filter(DataSource.id == finance_datasource_id).first()
    if not biz or not fin:
        raise HTTPException(404, "绑定的数据源不存在，请重新保存字段映射")
    validation = validate_datasource_pair(db, business_center_id, biz, fin)
    if not validation.ready:
        raise HTTPException(400, validation.message)
