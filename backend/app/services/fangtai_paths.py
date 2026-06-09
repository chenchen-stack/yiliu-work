"""方太 POC 任务文件路径：主表对 + 帆软/回款/结算单辅助数据源。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import DataSource

AUX_DATASOURCES = (
    ("帆软对账平台", "statement", "fanruan"),
    ("DMS订单明细", "payment", None),
    ("SAP结算单明细", "sap_settlement", None),
)


def attach_fangtai_auxiliary_datasources(db: Session, file_paths: dict[str, str]) -> None:
    for ds_name, path_key, alias in AUX_DATASOURCES:
        if path_key in file_paths:
            continue
        ds = db.query(DataSource).filter(DataSource.name == ds_name).first()
        if not ds or not ds.file_path:
            continue
        file_paths[path_key] = ds.file_path
        if alias:
            file_paths[alias] = ds.file_path
