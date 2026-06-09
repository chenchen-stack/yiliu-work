"""Ontology auto-extraction — Excel (方太 POC) + merge into DB without overwriting semantics."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.ontology_config import ontology_settings, resolve_poc_xlsx
from app.ontology_models import OntologyDomainRule, OntologyEntity, OntologyRelation
from app.services.ontology_a_customer_seed import (
    DOMAIN,
    SHEET_TO_ENTITY,
    entity_key as a_entity_key,
    seed_domain_rules,
    seed_entities,
    seed_relations,
)

logger = logging.getLogger("ontology.extractor")

DS_EXCEPTION = "fangtai_exception"
DOMAIN_REVENUE = DOMAIN


@dataclass
class ExtractorStats:
    entities_upserted: int = 0
    relations_upserted: int = 0
    rules_upserted: int = 0
    errors: list[str] = field(default_factory=list)


def _entity_key(datasource: str, table: str, schema: str = "poc") -> str:
    return f"{datasource}.{schema}.{table}"


def _is_sensitive_col(name: str) -> bool:
    low = name.lower()
    return any(p in low for p in ontology_settings.sensitive_field_patterns)


def _sample_values(series: pd.Series, col: str, limit: int) -> list[str]:
    if _is_sensitive_col(col):
        return []
    vals: list[str] = []
    for v in series.dropna().astype(str).unique()[:50]:
        s = str(v).strip()
        if not s or s == "nan":
            continue
        if any(p in col for p in ontology_settings.sensitive_amount_fields):
            try:
                n = float(s.replace(",", ""))
                vals.append(f"~{int(n):,}")
            except ValueError:
                vals.append("***")
        else:
            vals.append(s[:80])
        if len(vals) >= limit:
            break
    return vals


def _columns_from_df(df: pd.DataFrame) -> list[dict[str, Any]]:
    cols: list[dict[str, Any]] = []
    for name in df.columns:
        cname = str(name).strip()
        if not cname or cname.startswith("Unnamed"):
            continue
        dtype = str(df[cname].dtype)
        cols.append(
            {
                "name": cname,
                "data_type": dtype,
                "label": cname,
                "description": "",
                "sensitivity": "restricted" if _is_sensitive_col(cname) else "internal",
                "sample_values": _sample_values(df[cname], cname, ontology_settings.sample_value_limit),
            }
        )
    return cols


def extract_fangtai_poc_excel(path: Path | None = None) -> list[dict[str, Any]]:
    """从「收入对账-POC数据(1).xlsx」抽取列结构，映射为 A 客户标准实体名。"""
    xlsx = resolve_poc_xlsx(path)
    logger.info("ontology poc excel", extra={"path": str(xlsx)})

    entities: list[dict[str, Any]] = []
    xl = pd.ExcelFile(xlsx)
    for sheet in xl.sheet_names:
        spec = SHEET_TO_ENTITY.get(sheet)
        if not spec:
            logger.warning("skip unknown sheet", extra={"sheet": sheet})
            continue
        df = pd.read_excel(xlsx, sheet_name=sheet)
        key = a_entity_key(spec["datasource_code"], spec["schema_name"], spec["table_name"])
        row_count = len(df)
        entities.append(
            {
                "datasource_code": spec["datasource_code"],
                "source_type": "EXCEL",
                "schema_name": spec["schema_name"],
                "table_name": spec["table_name"],
                "entity_key": key,
                "label": spec["label"],
                "description": f"{spec['description']}（样本 {row_count} 行，来源 {xlsx.name}）",
                "columns": _columns_from_df(df),
                "aliases": list(spec.get("aliases", [])) + [sheet],
                "domain": DOMAIN_REVENUE,
                "data_sensitivity": "internal_finance",
            }
        )
    return entities


def extract_fangtai_exception_excel(path: Path | None = None) -> tuple[list[dict], list[dict]]:
    """从异常问题登记表抽取实体 + 领域规则候选。"""
    xlsx = path or ontology_settings.fangtai_exception_xlsx
    if not xlsx.is_file():
        raise FileNotFoundError(f"方太异常样本不存在: {xlsx}")

    entities: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    xl = pd.ExcelFile(xlsx)

    for sheet in xl.sheet_names:
        df = pd.read_excel(xlsx, sheet_name=sheet)
        if sheet.startswith("收入") or "问题登记" in sheet:
            reg_key = a_entity_key("knowledge", "register", "exception_register")
            entities.append(
                {
                    "datasource_code": "knowledge",
                    "source_type": "EXCEL",
                    "schema_name": "register",
                    "table_name": "exception_register",
                    "entity_key": reg_key,
                    "label": "异常问题登记",
                    "description": f"方太收入/回款异常登记 · {sheet}，{len(df)} 行。",
                    "columns": _columns_from_df(df),
                    "aliases": ["异常登记", "回款问题", "收入问题", sheet],
                    "domain": DOMAIN_REVENUE,
                    "data_sensitivity": "internal",
                }
            )
            for _, row in df.iterrows():
                desc = str(row.get("问题详细描述") or row.get("问题归并") or "").strip()
                cause = str(row.get("原因分析") or "").strip()
                if len(desc) < 8 or not cause or cause == "nan":
                    continue
                rules.append(
                    {
                        "domain": DOMAIN_REVENUE,
                        "entity_key": reg_key,
                        "rule_type": "HEURISTIC",
                        "rule_content": f"{desc[:120]} → 常见原因: {cause[:200]}",
                        "priority": 6,
                        "risk_level": "LOW",
                        "examples": [
                            {
                                "scenario": desc[:200],
                                "correct_judgment": cause[:200],
                                "wrong_judgment": "",
                            }
                        ],
                    }
                )
        else:
            entities.append(
                {
                    "datasource_code": DS_EXCEPTION,
                    "source_type": "EXCEL",
                    "schema_name": "exception",
                    "table_name": sheet,
                    "entity_key": _entity_key(DS_EXCEPTION, sheet, "exception"),
                    "label": sheet,
                    "description": "DMS-SAP 异常单样例表（结构待清洗列名）。",
                    "columns": _columns_from_df(df),
                    "aliases": [sheet, "异常结算单", "异常回款单"],
                    "domain": DOMAIN_REVENUE,
                    "data_sensitivity": "internal",
                }
            )

    return entities, rules[:80]


def merge_entities_into_db(db: Session, entities: list[dict[str, Any]], *, operator: str = "system") -> int:
    """写入实体；仅更新结构字段，保留 label/description/aliases。"""
    count = 0
    for raw in entities:
        key = raw["entity_key"]
        existing = db.query(OntologyEntity).filter(OntologyEntity.entity_key == key).first()
        cols_json = json.dumps(raw.get("columns") or [], ensure_ascii=False)

        if existing:
            old_cols = json.loads(existing.columns_json or "[]")
            merged = _merge_columns_structure(old_cols, raw.get("columns") or [])
            existing.columns_json = json.dumps(merged, ensure_ascii=False)
            existing.update_time = datetime.utcnow()
            existing.update_by = operator
            # 不覆盖人工/种子语义，仅补充描述与别名
            if raw.get("description") and "样本" in str(raw.get("description", "")):
                existing.description = raw["description"]
            if raw.get("aliases"):
                old_aliases = json.loads(existing.aliases_json or "[]")
                merged_aliases = list(dict.fromkeys(old_aliases + raw.get("aliases", [])))
                existing.aliases_json = json.dumps(merged_aliases, ensure_ascii=False)
        else:
            ent = OntologyEntity(
                id=str(uuid.uuid4()),
                datasource_code=raw["datasource_code"],
                source_type=raw.get("source_type", "EXCEL"),
                schema_name=raw.get("schema_name"),
                table_name=raw["table_name"],
                entity_key=key,
                label=raw.get("label", raw["table_name"]),
                description=raw.get("description"),
                columns_json=cols_json,
                aliases_json=json.dumps(raw.get("aliases") or [], ensure_ascii=False),
                domain=raw.get("domain"),
                data_sensitivity=raw.get("data_sensitivity", "internal"),
                create_by=operator,
            )
            db.add(ent)
        count += 1
    db.commit()
    return count


def _merge_columns_structure(old: list, new: list) -> list:
    old_by_name = {c.get("name"): c for c in old if c.get("name")}
    out: list[dict] = []
    for ncol in new:
        name = ncol.get("name")
        ocol = old_by_name.get(name, {})
        out.append(
            {
                "name": name,
                "data_type": ncol.get("data_type") or ocol.get("data_type"),
                "label": ocol.get("label") or ncol.get("label") or name,
                "description": ocol.get("description") or ncol.get("description") or "",
                "sensitivity": ocol.get("sensitivity") or ncol.get("sensitivity"),
                "sample_values": ncol.get("sample_values") or ocol.get("sample_values") or [],
            }
        )
    return out


def merge_relations_into_db(db: Session, relations: list[dict[str, Any]]) -> int:
    n = 0
    for r in relations:
        exists = (
            db.query(OntologyRelation)
            .filter(
                OntologyRelation.from_entity == r["from_entity"],
                OntologyRelation.to_entity == r["to_entity"],
                OntologyRelation.from_column == r["from_column"],
            )
            .first()
        )
        if exists:
            continue
        db.add(
            OntologyRelation(
                id=str(uuid.uuid4()),
                from_entity=r["from_entity"],
                to_entity=r["to_entity"],
                from_column=r["from_column"],
                to_column=r["to_column"],
                relation_type=r.get("relation_type", "MANUAL"),
                description=r.get("description"),
            )
        )
        n += 1
    db.commit()
    return n


def merge_rules_into_db(db: Session, rules: list[dict[str, Any]]) -> int:
    n = 0
    for r in rules:
        content = r.get("rule_content", "")
        dup = (
            db.query(OntologyDomainRule)
            .filter(
                OntologyDomainRule.domain == r.get("domain"),
                OntologyDomainRule.rule_content == content,
            )
            .first()
        )
        if dup:
            continue
        db.add(
            OntologyDomainRule(
                id=str(uuid.uuid4()),
                domain=r.get("domain", DOMAIN_REVENUE),
                entity_key=r.get("entity_key"),
                rule_type=r.get("rule_type", "HEURISTIC"),
                rule_content=content,
                priority=r.get("priority", 5),
                risk_level=r.get("risk_level", "LOW"),
                effective_status=r.get("effective_status", "DRAFT"),
                version=1,
                examples_json=json.dumps(r.get("examples") or [], ensure_ascii=False),
            )
        )
        n += 1
    db.commit()
    return n


def _archive_legacy_entities(db: Session) -> None:
    """下线旧版 fangtai_poc.* 实体键，避免与 dms_pg/sap_pg 标准键重复展示。"""
    for ent in db.query(OntologyEntity).filter(OntologyEntity.status == 1).all():
        if ent.entity_key.startswith(("fangtai_poc.", "fangtai_exception.")):
            ent.status = 0
    db.commit()


def extract_all_fangtai_sources(db: Session) -> ExtractorStats:
    """种子数据 + 收入对账-POC数据(1).xlsx 列结构 + 异常登记表。"""
    stats = ExtractorStats()
    _archive_legacy_entities(db)

    stats.entities_upserted += merge_entities_into_db(db, seed_entities())
    stats.relations_upserted += merge_relations_into_db(db, seed_relations())
    stats.rules_upserted += merge_rules_into_db(db, seed_domain_rules())

    try:
        poc_entities = extract_fangtai_poc_excel()
        stats.entities_upserted += merge_entities_into_db(db, poc_entities)
    except Exception as exc:  # noqa: BLE001
        stats.errors.append(f"poc: {exc}")
        logger.exception("fangtai poc extract failed")

    try:
        exc_entities, exc_rules = extract_fangtai_exception_excel()
        stats.entities_upserted += merge_entities_into_db(db, exc_entities)
        stats.rules_upserted += merge_rules_into_db(db, exc_rules)
    except Exception as exc:  # noqa: BLE001
        stats.errors.append(f"exception: {exc}")
        logger.warning("exception xlsx optional: %s", exc)

    return stats
