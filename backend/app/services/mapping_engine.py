"""本体映射引擎 — 字段翻译 / 对象识别 / 关系键 / 可对接 Workflow field_mapping 节点。"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from sqlalchemy.orm import Session

from app.config import CONFIG_DIR
from app.models import MappingConfig
from app.services.data_loader import ConfigLoader, load_dataframe
from app.services.mdm_service import build_mdm_lookup

# 列名探测 → 数据源画像
PROFILE_SIGNATURES: dict[str, set[str]] = {
    "sap_fi": {"KUNNR", "BELNR", "DMBTR", "BLDAT", "BUKRS"},
    "bank_direct": {"交易时间", "交易号", "摘要", "方向"},
    "sap": {"CUSTOMER", "VBELN", "NETWR", "INVOICE"},
    "dms": {"client_id", "order_num", "net_amount", "invoice_no"},
}

_POC_PROFILES: dict[str, dict] | None = None


def _load_poc_profiles() -> dict[str, dict]:
    global _POC_PROFILES
    if _POC_PROFILES is not None:
        return _POC_PROFILES
    path = CONFIG_DIR / "poc_chinese_mapping.yaml"
    if not path.exists():
        _POC_PROFILES = {}
        return _POC_PROFILES
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    _POC_PROFILES = raw.get("profiles") or {}
    return _POC_PROFILES


def get_poc_profile(profile: str) -> dict | None:
    return _load_poc_profiles().get(profile)


def _is_valid_match_key(key: str | None) -> bool:
    if not key:
        return False
    stripped = key.replace("|", "").replace(":", "").strip()
    return bool(stripped)


@dataclass
class FieldMappingRow:
    unified_field: str
    business_column: str | None = None
    finance_column: str | None = None
    bank_column: str | None = None
    transform: str = "rename"
    label: str = ""


@dataclass
class MappingRegistry:
    business_center_id: str
    rows: list[FieldMappingRow] = field(default_factory=list)
    object_types: dict[str, str] = field(default_factory=dict)
    match_keys: list[str] = field(default_factory=lambda: ["customer_id", "amount", "business_date"])
    amount_field: str = "sales_amount"
    date_tolerance_days: int = 3

    @classmethod
    def load(cls, db: Session | None, business_center_id: str) -> MappingRegistry:
        reg = cls(business_center_id=business_center_id)
        reg._load_yaml_defaults()
        if db:
            reg._merge_db(db)
        return reg

    def _load_yaml_defaults(self) -> None:
        demo = ConfigLoader.field_mapping().get("standard_fields", {})
        for uf, cfg in demo.items():
            self.rows.append(
                FieldMappingRow(
                    unified_field=uf,
                    business_column=cfg.get("sap_field"),
                    finance_column=cfg.get("dms_field"),
                    transform="rename",
                    label=uf,
                )
            )
        path = CONFIG_DIR / "revenue_ontology_mapping.yaml"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                rev = yaml.safe_load(f) or {}
            for m in rev.get("field_mappings", []):
                uf = m.get("unified_field", "")
                if not uf:
                    continue
                existing = next((r for r in self.rows if r.unified_field == uf), None)
                row = FieldMappingRow(
                    unified_field=uf,
                    business_column=m.get("sap_field"),
                    bank_column=m.get("bank_field"),
                    finance_column=m.get("bank_field") if "金额" in str(m.get("bank_field", "")) else None,
                    transform=_normalize_transform(m.get("transform", "")),
                    label=m.get("unified_label", uf),
                )
                if existing:
                    if row.bank_column:
                        existing.bank_column = row.bank_column
                    if not existing.transform or existing.transform == "rename":
                        existing.transform = row.transform or existing.transform
                else:
                    self.rows.append(row)
            for ot in rev.get("object_types", []):
                self.object_types[ot.get("source", "")] = ot.get("ontology_object", "")
            rel = (rev.get("relationships") or [{}])[0]
            self.match_keys = list(rel.get("match_keys") or self.match_keys)
        if "sales_amount" not in {r.unified_field for r in self.rows}:
            self.amount_field = "sales_amount"
        else:
            self.amount_field = "sales_amount"

    def _merge_db(self, db: Session) -> None:
        configs = (
            db.query(MappingConfig)
            .filter(
                MappingConfig.business_center_id == self.business_center_id,
                MappingConfig.enabled.is_(True),
            )
            .all()
        )
        for c in configs:
            spec = _parse_transform_rule(c.transform_rule)
            fin_col = spec.get("finance_column") or spec.get("dms") or None
            bank_col = spec.get("bank_column") or None
            row = FieldMappingRow(
                unified_field=c.target_field,
                business_column=c.source_field or spec.get("business_column"),
                finance_column=fin_col,
                bank_column=bank_col,
                transform=spec.get("transform", "rename"),
                label=spec.get("label", c.target_field),
            )
            idx = next((i for i, r in enumerate(self.rows) if r.unified_field == row.unified_field), None)
            if idx is not None:
                self.rows[idx] = row
            else:
                self.rows.append(row)

    def profile_for_side(self, profile: str) -> list[FieldMappingRow]:
        if profile in ("sap", "sap_fi"):
            return [r for r in self.rows if r.business_column]
        return [r for r in self.rows if r.finance_column or r.bank_column]


def _normalize_transform(t: str) -> str:
    t = (t or "").lower()
    if "模糊" in t or "fuzzy" in t:
        return "fuzzy_customer"
    if "mdm" in t:
        return "mdm"
    if "常量" in t or "constant" in t:
        return "constant"
    if "日期" in t:
        return "date"
    if "数值" in t or "金额" in t:
        return "amount"
    return "rename"


def _parse_transform_rule(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        parts = {}
        for seg in raw.split(","):
            if ":" in seg:
                k, v = seg.split(":", 1)
                parts[k.strip()] = v.strip()
        return parts


def detect_data_profile(df: pd.DataFrame) -> str:
    cols = set(df.columns.astype(str))
    poc_scores: dict[str, int] = {}
    for name, cfg in _load_poc_profiles().items():
        sig = set(cfg.get("signatures") or [])
        if sig:
            poc_scores[name] = len(sig & cols)
    if poc_scores:
        best_poc = max(poc_scores, key=poc_scores.get)
        if poc_scores[best_poc] >= 2:
            return best_poc
    scores = {name: len(sig & cols) for name, sig in PROFILE_SIGNATURES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "unknown"


BANK_HEADER_ALIASES: dict[str, str] = {
    "金额": "amount",
    "交易时间": "business_date",
    "交易号": "source_doc_no",
    "摘要": "summary",
    "方向": "direction",
    "币种": "currency",
}


def _resolve_poc_column(columns: list[str] | pd.Index, target: str) -> str | None:
    """精确或模糊匹配 POC CSV 列名（兼容导出差异）。"""
    cols = [str(c) for c in columns]
    if target in cols:
        return target
    normalized = target.replace(" ", "")
    for c in cols:
        if c.replace(" ", "") == normalized:
            return c
    aliases: dict[str, list[str]] = {
        "法人客户编码": ["核算客户编码", "入账客户编码"],
        "含税开票总金额": ["含税发票总金额"],
        "结算单编码": ["结算单名称"],
        "开票凭证": ["发票凭证"],
        "DRP订单金额": ["金额"],
        "处理日期": ["创建日期"],
    }
    for alt in aliases.get(target, []):
        if alt in cols:
            return alt
    return None


def _poc_rename_map(profile: str, columns: list[str] | pd.Index | None = None) -> dict[str, str]:
    cfg = get_poc_profile(profile)
    if not cfg:
        return {}
    rename: dict[str, str] = {}
    for field in cfg.get("fields") or []:
        uf = field.get("unified_field")
        col = field.get("business_column") or field.get("finance_column")
        if not uf or not col:
            continue
        if columns is not None:
            resolved = _resolve_poc_column(columns, col)
            if resolved:
                rename[resolved] = uf
        else:
            rename[col] = uf
    return rename


def aggregate_records(records: list[dict], group_keys: list[str], amount_field: str = "sales_amount") -> list[dict]:
    if not group_keys or not records:
        return records
    buckets: dict[tuple, dict] = {}
    for rec in records:
        key_parts = []
        for k in group_keys:
            val = rec.get(k)
            if val is None and k == "invoice_num":
                val = rec.get("source_doc_no")
            key_parts.append(str(val or ""))
        key = tuple(key_parts)
        if key not in buckets:
            buckets[key] = dict(rec)
            buckets[key][amount_field] = float(rec.get(amount_field) or rec.get("amount") or 0)
        else:
            buckets[key][amount_field] = float(buckets[key].get(amount_field) or 0) + float(
                rec.get(amount_field) or rec.get("amount") or 0
            )
    return list(buckets.values())


def translate_dataframe(df: pd.DataFrame, profile: str, registry: MappingRegistry) -> pd.DataFrame:
    out = df.copy()
    rename: dict[str, str] = dict(_poc_rename_map(profile, out.columns))
    if profile == "bank_direct":
        for src, uf in BANK_HEADER_ALIASES.items():
            if src in out.columns:
                rename[src] = uf
    for row in registry.rows:
        src = None
        if profile in ("sap", "sap_fi"):
            src = row.business_column
        elif profile == "dms":
            src = row.finance_column
        elif profile == "bank_direct":
            src = row.bank_column if row.bank_column in out.columns else None
            if not src and row.bank_column and "金额" in row.bank_column and "金额" in out.columns:
                rename.setdefault("金额", "amount")
            continue
        if src and src in out.columns and row.unified_field and src not in rename:
            rename[src] = row.unified_field
    out = out.rename(columns=rename)
    if registry.amount_field not in out.columns and "amount" in out.columns:
        out["sales_amount"] = pd.to_numeric(out["amount"], errors="coerce")
    elif "sales_amount" in out.columns:
        out["sales_amount"] = pd.to_numeric(out["sales_amount"], errors="coerce")
    for col in ["customer_id", "order_id", "product_code", "invoice_num", "source_doc_no", "business_date", "currency", "mdm_code"]:
        if col not in out.columns:
            out[col] = None
    out["_source_profile"] = profile
    out["_ontology_object"] = registry.object_types.get(
        "sap_fi" if profile == "sap_fi" else profile,
        registry.object_types.get("sap" if profile in ("sap", "sap_fi") else "bank_direct", "记录"),
    )
    return out


def _profile_match_keys(profile: str, registry: MappingRegistry) -> list[str]:
    cfg = get_poc_profile(profile)
    if cfg and cfg.get("match_keys"):
        return list(cfg["match_keys"])
    return registry.match_keys


def enrich_records(
    records: list[dict],
    profile: str,
    registry: MappingRegistry,
    *,
    match_keys: list[str] | None = None,
) -> list[dict]:
    mdm = build_mdm_lookup()
    name_to_mdm: dict[str, str] = {}
    for row in ConfigLoader.mdm_table():
        name_to_mdm[str(row.get("customer_name", "")).strip()] = row.get("mdm_id", "")

    keys = match_keys or _profile_match_keys(profile, registry)
    enriched: list[dict] = []
    for rec in records:
        r = dict(rec)
        cid = r.get("customer_id") or r.get("KUNNR")
        if cid and "customer_id" not in r:
            r["customer_id"] = cid
        mdm_code = r.get("mdm_code")
        if mdm_code and not r.get("mdm_id"):
            for side in ("dms", "sap"):
                m = mdm.get(side, {}).get(str(mdm_code))
                if m:
                    r["mdm_id"] = m.get("mdm_id")
                    r["customer_name"] = m.get("customer_name")
                    break
            if not r.get("mdm_id"):
                r["mdm_id"] = str(mdm_code)
        if profile in ("sap", "sap_fi", "dms", "sap_revenue_total", "sap_billing_detail", "dms_settlement", "dms_revenue_ledger") and cid:
            side = "sap" if profile.startswith("sap") or profile in ("sap", "sap_fi") else "dms"
            m = mdm.get(side, {}).get(str(cid))
            if m:
                r["mdm_id"] = m.get("mdm_id")
                r["customer_name"] = m.get("customer_name")
        if profile == "bank_direct":
            summary = str(r.get("summary") or r.get("摘要") or "")
            if summary and not r.get("mdm_id"):
                for name, mid in name_to_mdm.items():
                    if name and name in summary:
                        r["mdm_id"] = mid
                        r["customer_id"] = mid
                        r["customer_name"] = name
                        r["_fuzzy_match"] = True
                        break
            direction = str(r.get("方向") or r.get("direction") or "")
            if "贷" in direction:
                r["settlement_status"] = "credit_in"
        if profile == "sap_fi":
            st = str(r.get("settlement_status") or r.get("status") or "")
            if "未收" in st:
                r["settlement_status"] = "uncollected"
        amt = r.get("sales_amount") or r.get("amount")
        if amt is not None:
            r["sales_amount"] = float(amt)
        r["_match_key"] = _build_match_key(r, registry, match_keys=keys, profile=profile)
        enriched.append(r)
    return enriched


def _build_match_key(
    rec: dict,
    registry: MappingRegistry,
    *,
    match_keys: list[str] | None = None,
    profile: str | None = None,
) -> str:
    keys = match_keys or registry.match_keys
    cfg = get_poc_profile(profile) if profile else None
    mode = (cfg or {}).get("match_key_mode", "auto")
    parts = []
    for k in keys:
        if k == "amount":
            parts.append(str(rec.get("sales_amount") or rec.get("amount") or ""))
        elif k == "customer_id":
            parts.append(str(rec.get("mdm_id") or rec.get("mdm_code") or rec.get("customer_id") or rec.get("KUNNR") or ""))
        elif k == "mdm_code":
            parts.append(str(rec.get("mdm_code") or rec.get("mdm_id") or ""))
        else:
            parts.append(str(rec.get(k) or ""))
    if mode == "relation" or (mode == "auto" and "order_id" not in keys and rec.get("order_id") is None):
        if any(parts):
            return f"rel:{'|'.join(parts)}"
    if "order_id" in keys and rec.get("order_id"):
        return f"order:{rec.get('order_id')}"
    if rec.get("order_id") and mode == "auto":
        return f"order:{rec.get('order_id')}"
    # 发票-收款：按 MDM/客户 + 金额 + 日期对齐，不按单号硬绑
    if rec.get("mdm_id") or rec.get("customer_id") or rec.get("KUNNR"):
        return f"rel:{'|'.join(parts)}"
    if rec.get("source_doc_no"):
        return f"doc:{rec.get('source_doc_no')}|{'|'.join(parts)}"
    joined = "|".join(parts)
    return joined if _is_valid_match_key(joined) else ""


def run_mapping_pipeline(
    business_records: list[dict],
    finance_records: list[dict],
    *,
    business_profile: str = "sap",
    finance_profile: str = "dms",
    registry: MappingRegistry,
) -> dict[str, Any]:
    """字段翻译 + 对象识别 + 关系键生成（供 field_mapping Skill 与后台试运行）。"""
    biz_cfg = get_poc_profile(business_profile) or {}
    fin_cfg = get_poc_profile(finance_profile) or {}
    biz_raw = list(business_records)
    fin_raw = list(finance_records)
    if biz_cfg.get("aggregate_by"):
        biz_raw = aggregate_records(
            biz_raw,
            biz_cfg["aggregate_by"],
            amount_field=biz_cfg.get("amount_field", "sales_amount"),
        )
    if fin_cfg.get("aggregate_by"):
        fin_raw = aggregate_records(
            fin_raw,
            fin_cfg["aggregate_by"],
            amount_field=fin_cfg.get("amount_field", "sales_amount"),
        )
    biz = enrich_records(biz_raw, business_profile, registry)
    fin = enrich_records(fin_raw, finance_profile, registry)

    fin_index: dict[str, dict] = {}
    fin_by_invoice: dict[str, list[dict]] = {}
    for r in fin:
        mk = r.get("_match_key") or ""
        if _is_valid_match_key(mk):
            fin_index[mk] = r
        oid = r.get("order_id")
        if oid:
            fin_index[f"order:{oid}"] = r
        inv = r.get("invoice_num")
        if inv:
            fin_by_invoice.setdefault(str(inv), []).append(r)

    matched_fin_ids: set[int] = set()
    pairs: list[dict] = []
    unmatched_biz: list[dict] = []
    unmatched_fin: list[dict] = []
    for b in biz:
        mk = b.get("_match_key", "")
        fin_rec = fin_index.get(mk) if _is_valid_match_key(mk) else None
        if not fin_rec and b.get("order_id"):
            fin_rec = fin_index.get(f"order:{b.get('order_id')}")
        if not fin_rec and b.get("invoice_num"):
            candidates = fin_by_invoice.get(str(b["invoice_num"]), [])
            candidates = [c for c in candidates if id(c) not in matched_fin_ids]
            if candidates:
                fin_rec = candidates[0]
        if fin_rec:
            matched_fin_ids.add(id(fin_rec))
            b_amt = float(b.get("sales_amount") or 0)
            f_amt = float(fin_rec.get("sales_amount") or 0)
            inv = b.get("invoice_num") or fin_rec.get("invoice_num") or ""
            pairs.append({
                "business_key": b.get("order_id") or b.get("invoice_num") or b.get("source_doc_no") or mk,
                "invoice_num": str(inv),
                "customer_id": b.get("customer_id"),
                "mdm_id": b.get("mdm_id"),
                "business_amount": b_amt,
                "finance_amount": f_amt,
                "amount_diff": abs(b_amt - f_amt),
                "matched": abs(b_amt - f_amt) < 0.01,
                "relation": "发票-收款匹配",
            })
        else:
            unmatched_biz.append({
                "business_key": b.get("order_id") or b.get("invoice_num") or mk or "unknown",
                "record": b,
            })

    for r in fin:
        if id(r) not in matched_fin_ids:
            mk = r.get("_match_key") or ""
            unmatched_fin.append({
                "finance_key": r.get("order_id") or r.get("invoice_num") or mk or "unknown",
                "record": r,
            })

    biz_object = biz_cfg.get("object_type") or registry.object_types.get(
        "sap_fi" if business_profile == "sap_fi" else "sap", "业务记录"
    )
    fin_object = fin_cfg.get("object_type") or registry.object_types.get(
        "bank_direct" if finance_profile == "bank_direct" else "dms", "财务记录"
    )

    return {
        "business_profile": business_profile,
        "finance_profile": finance_profile,
        "business_object": biz_object,
        "finance_object": fin_object,
        "mapped_business_rows": len(biz),
        "mapped_finance_rows": len(fin),
        "match_pairs": pairs,
        "matched_count": sum(1 for p in pairs if p.get("matched")),
        "unmatched_business": unmatched_biz[:50],
        "unmatched_finance": unmatched_fin[:50],
        "unmatched_business_count": len(unmatched_biz),
        "unmatched_finance_count": len(unmatched_fin),
        "match_keys": registry.match_keys,
        "field_mapping_count": len(registry.rows),
    }


def load_and_translate_file(path: str | Path, side: str, registry: MappingRegistry) -> tuple[list[dict], str]:
    df = load_dataframe(path)
    profile = detect_data_profile(df)
    if profile == "unknown":
        profile = "sap_fi" if side == "business" else "dms"
        if side == "finance" and any(c in df.columns for c in ("摘要", "交易时间")):
            profile = "bank_direct"
    translated = translate_dataframe(df, profile, registry)
    records = translated.where(pd.notnull(translated), None).to_dict(orient="records")
    return enrich_records(records, profile, registry), profile


def invalidate_mapping_cache() -> None:
    ConfigLoader._field_mapping = None


# ── 多 Sheet Excel 自动分类 ─────────────────────────────────────────────

_PROFILE_ROLES: dict[str, dict] | None = None


def _load_profile_roles() -> dict[str, dict]:
    global _PROFILE_ROLES
    if _PROFILE_ROLES is not None:
        return _PROFILE_ROLES
    path = CONFIG_DIR / "poc_chinese_mapping.yaml"
    if not path.exists():
        _PROFILE_ROLES = {}
        return _PROFILE_ROLES
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    _PROFILE_ROLES = raw.get("profile_roles") or {}
    return _PROFILE_ROLES


def classify_excel_sheets(
    file_path: str | Path,
) -> dict[str, list[tuple[str, pd.DataFrame, str, int]]]:
    """将多 Sheet Excel 按 poc_chinese_mapping 的 profile_roles 分类到数据槽位。

    返回 {slot_name: [(sheet_name, dataframe, profile, priority), ...]}，
    每个 slot 内按 priority 降序排列。
    """
    from app.services.data_loader import load_all_sheets

    sheets = load_all_sheets(file_path)
    roles = _load_profile_roles()
    result: dict[str, list[tuple[str, pd.DataFrame, str, int]]] = {}

    for sheet_name, df in sheets.items():
        profile = detect_data_profile(df)
        role_cfg = roles.get(profile, {})
        slot = role_cfg.get("slot", "")
        priority = role_cfg.get("priority", 0)
        if not slot:
            if profile == "unknown":
                continue
            slot = "extra"
            priority = 0
        result.setdefault(slot, []).append((sheet_name, df, profile, priority))

    for slot in result:
        result[slot].sort(key=lambda x: (-x[3], -len(x[1])))

    return result


def split_combined_excel(
    file_path: str | Path,
    registry: MappingRegistry,
) -> dict[str, tuple[list[dict], str]]:
    """将多 Sheet Excel 自动分类并翻译为各槽位的标准化记录。

    返回 {slot_name: (records, profile)}。同一槽位有多个 Sheet 时合并记录。
    """
    classified = classify_excel_sheets(file_path)
    output: dict[str, tuple[list[dict], str]] = {}

    for slot, entries in classified.items():
        if slot == "extra":
            continue
        all_records: list[dict] = []
        primary_profile = entries[0][2] if entries else "unknown"
        for _sheet_name, df, profile, _priority in entries:
            translated = translate_dataframe(df, profile, registry)
            records = translated.where(pd.notnull(translated), None).to_dict(orient="records")
            enriched = enrich_records(records, profile, registry)
            all_records.extend(enriched)
            if not output.get(slot):
                primary_profile = profile
        output[slot] = (all_records, primary_profile)

    return output
