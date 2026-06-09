"""方太 POC 数据语义 0→1 演示种子（API 可调用）。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.models import DataSource, MappingConfig, User
from app.services.mapping_binding import set_mapping_binding, validate_datasource_pair
from app.services.ontology_extractor import extract_all_fangtai_sources
from app.services.platform_seed import IDS, seed_platform
from app.services.rule_import_service import apply_preset

SAMPLE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "sample-data"
DEST_DIR = SAMPLE_ROOT / "dataset_fangtai_real"

BILLING_LEDGER_MAPPING = [
    ("order_id", "单据编号", "DMS结算订单", "结算单编码", "rename"),
    ("sales_amount", "金额", "DRP订单金额", "收入含税金额", "amount"),
    ("invoice_num", "发票号", "开票凭证", "结算单编码", "rename"),
    ("business_date", "业务日期", "处理日期", None, "date"),
    ("mdm_code", "MDM编码", "DMS行唯一ID", "MDMID", "mdm"),
]

POC_SHEETS = [
    {"sheet": "帆软对账平台", "system_type": "fanruan", "side": "business"},
    {"sheet": "DMS收入台账明细", "system_type": "dms", "side": "finance"},
    {"sheet": "DMS结算单明细", "system_type": "dms", "side": "finance"},
    {"sheet": "DMS订单明细", "system_type": "dms", "side": "finance"},
    {"sheet": "SAP收入总额", "system_type": "sap", "side": "business"},
    {"sheet": "SAP结算行明细", "system_type": "sap", "side": "business"},
    {"sheet": "SAP结算单明细", "system_type": "sap", "side": "business"},
    {"sheet": "SAP结算单对应的订单行明细", "system_type": "sap", "side": "business"},
]


def _csv_path(sheet: str) -> Path:
    safe = sheet.replace("/", "_").replace("\\", "_")
    return DEST_DIR / f"{safe}.csv"


def _upsert_from_csv(db: Session, cfg: dict) -> str | None:
    from app.config import UPLOAD_DIR
    from app.services.mapping_engine import detect_data_profile
    import shutil

    csv_path = _csv_path(cfg["sheet"])
    if not csv_path.is_file():
        return f"缺少 CSV: {csv_path.name}"

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    ds_name = cfg["sheet"]
    profile = detect_data_profile(df)
    detected_profile = profile if profile != "unknown" else cfg["system_type"]
    columns = list(df.columns.astype(str))

    existing = db.query(DataSource).filter(DataSource.name == ds_name).first()
    if existing:
        existing.system_type = cfg["system_type"]
        existing.side = cfg["side"]
        existing.row_count = len(df)
        existing.detected_columns = columns
        existing.detected_profile = detected_profile
        existing.status = "active"
        upload_dest = Path(existing.file_path) if existing.file_path else UPLOAD_DIR / f"ds_{existing.id}.csv"
        if not upload_dest.parent.exists():
            upload_dest = UPLOAD_DIR / f"ds_{existing.id}.csv"
            existing.file_path = str(upload_dest)
        shutil.copy2(csv_path, upload_dest)
        return None

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
    return None


def _seed_billing_mapping(db: Session) -> int:
    bc = IDS["business_center"]
    db.query(MappingConfig).filter(MappingConfig.business_center_id == bc).delete()
    n = 0
    for uf, label, biz_col, fin_col, transform in BILLING_LEDGER_MAPPING:
        if not biz_col and not fin_col:
            continue
        spec = json.dumps(
            {"label": label, "finance_column": fin_col, "transform": transform},
            ensure_ascii=False,
        )
        db.add(
            MappingConfig(
                id=str(uuid.uuid4()),
                business_center_id=bc,
                source_field=(biz_col or "").strip(),
                target_field=uf,
                transform_rule=spec,
                version=1,
                enabled=True,
            )
        )
        n += 1
    return n


def _bind_billing_ledger(db: Session) -> str:
    biz = db.query(DataSource).filter(DataSource.name == "SAP结算行明细").first()
    fin = db.query(DataSource).filter(DataSource.name == "DMS收入台账明细").first()
    if not biz or not fin:
        return "未找到 SAP结算行明细 / DMS收入台账明细，请先导入数据源"
    v = validate_datasource_pair(db, IDS["business_center"], biz, fin)
    set_mapping_binding(
        IDS["business_center"],
        business_datasource_id=biz.id,
        finance_datasource_id=fin.id,
        mapping_row_count=db.query(MappingConfig).filter(
            MappingConfig.business_center_id == IDS["business_center"],
        ).count(),
        validated=v.ready,
        message=v.message,
    )
    return f"已绑定 {biz.name} ↔ {fin.name}（{'可发起核对' if v.ready else v.message}）"


def run_semantics_demo_seed(db: Session, user: User | None) -> dict:
    """一键：方太 sample-data → 数据源 → 映射 → 检测规则预设 → 本体抽取。"""
    steps: list[str] = []
    errors: list[str] = []
    mapping_ready = False

    seed_platform(db)
    db.commit()
    steps.append("平台种子（业务中心 / Workflow）")

    if not DEST_DIR.is_dir():
        errors.append(f"sample-data 目录不存在: {DEST_DIR}")
    else:
        imported = 0
        for cfg in POC_SHEETS:
            err = _upsert_from_csv(db, cfg)
            if err:
                errors.append(err)
            else:
                imported += 1
        db.commit()
        steps.append(f"注册方太 POC 数据源（{imported} 张表）")

    nmap = _seed_billing_mapping(db)
    db.commit()
    steps.append(f"写入中文列映射（{nmap} 行）")

    bind_msg = _bind_billing_ledger(db)
    db.commit()
    steps.append(bind_msg)
    mapping_ready = "可发起核对" in bind_msg

    if user:
        try:
            res = apply_preset(
                db,
                rule_version_id=IDS["rule_version_v1"],
                business_center_id=IDS["business_center"],
                user=user,
            )
            steps.append(f"应用方太排查规则预设（{len(res.get('applied', []))} 条）")
            db.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"规则预设: {exc}")

    try:
        stats = extract_all_fangtai_sources(db)
        db.commit()
        steps.append(
            f"本体抽取：{stats.entities_upserted} 实体、"
            f"{stats.relations_upserted} 关系、{stats.rules_upserted} 规则",
        )
        errors.extend(stats.errors or [])
    except Exception as exc:  # noqa: BLE001
        errors.append(f"本体抽取: {exc}")

    return {
        "ok": len(errors) == 0,
        "steps": steps,
        "errors": errors,
        "mapping_ready": mapping_ready,
    }
