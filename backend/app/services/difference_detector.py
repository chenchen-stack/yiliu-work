import uuid
from typing import Any

from app.models import DifferenceType
from app.services.data_loader import ConfigLoader
from app.services.mdm_service import build_mdm_lookup, check_mdm_consistency


def _rules_from_db_or_yaml(db_rules: list[dict] | None = None) -> dict[str, dict]:
    yaml_rules = ConfigLoader.rules()
    if db_rules:
        out: dict[str, dict] = {}
        for r in db_rules:
            key = r.get("rule_type") or r.get("name", "")
            params = r.get("params") or {}
            yaml_default = yaml_rules.get(key, {})
            out[key] = {
                "enabled": r.get("enabled", True),
                "confidence": float(params.get("confidence", yaml_default.get("confidence", 0.9 if r.get("severity") == "high" else 0.75))),
                "responsible_party": params.get("responsible_party") or yaml_default.get("responsible_party", "finance"),
                "description": r.get("condition") or r.get("name"),
                "threshold": float(r.get("threshold") or 0),
                "params": params,
            }
        return out
    rules = ConfigLoader.rules()
    return {
        "amount_mismatch": rules.get("amount_mismatch", {"enabled": True, "confidence": 0.95, "responsible_party": "finance"}),
        "duplicate_record": rules.get("duplicate_record", rules.get("duplicate_amount", {"enabled": True, "confidence": 1.0, "responsible_party": "finance"})),
        "mapping_anomaly": rules.get("mapping_anomaly", {"enabled": True, "confidence": 0.85, "responsible_party": "mdm_team"}),
        "status_mismatch": rules.get("status_mismatch", {"enabled": True, "confidence": 0.88, "responsible_party": "finance"}),
        "sync_failure": rules.get("sync_failure", {"enabled": True, "confidence": 0.9, "responsible_party": "business"}),
        "payment_mismatch": rules.get("payment_mismatch", {"enabled": True, "confidence": 0.87, "responsible_party": "finance"}),
        "fanruan_summary": rules.get("fanruan_summary", {"enabled": True, "confidence": 0.92, "responsible_party": "finance", "threshold": 0.01}),
    }


def detect_differences(
    business_records: list[dict],
    finance_records: list[dict],
    statement_records: list[dict] | None = None,
    db_rules: list[dict] | None = None,
    *,
    mapping_report: dict | None = None,
    payment_records: list[dict] | None = None,
    sap_settlement_records: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Programmatic detection — AI must NOT judge facts."""
    results: list[dict[str, Any]] = []
    rules = _rules_from_db_or_yaml(db_rules)
    mdm_lookup = build_mdm_lookup()
    statement_records = statement_records or []

    finance_by_order: dict[str, dict] = {}
    finance_by_match_key: dict[str, dict] = {}
    finance_by_invoice_agg: dict[str, dict] = {}
    finance_invoice_rows: dict[str, list[dict]] = {}
    for r in finance_records:
        oid = r.get("order_id")
        if oid:
            finance_by_order[str(oid)] = r
        mk = r.get("_match_key")
        if mk:
            finance_by_match_key[str(mk)] = r
        inv = r.get("invoice_num")
        if inv:
            finance_invoice_rows.setdefault(str(inv), []).append(r)

    for inv, rows in finance_invoice_rows.items():
        base = dict(rows[0])
        base["sales_amount"] = sum(float(row.get("sales_amount") or 0) for row in rows)
        if len(rows) > 1:
            base["_finance_rows"] = rows
            base["_merged_invoice_rows"] = len(rows)
        finance_by_invoice_agg[inv] = base

    def _resolve_finance(biz: dict) -> dict | None:
        oid = biz.get("order_id")
        if oid and str(oid) in finance_by_order:
            return finance_by_order[str(oid)]
        mk = biz.get("_match_key")
        if mk and str(mk) in finance_by_match_key:
            return finance_by_match_key[str(mk)]
        inv = biz.get("invoice_num")
        if inv:
            agg = finance_by_invoice_agg.get(str(inv))
            if agg:
                return agg
        if oid:
            return finance_by_order.get(str(oid))
        return None

    seen_amount: set[str] = set()
    seen_dup: set[str] = set()
    seen_map: set[str] = set()

    # Rule 1: Amount mismatch — same business_key, different amounts
    # 容差阈值由规则版本决定：|business-finance| <= threshold 不计差异（threshold=0 时退化为浮点严格相等）
    amount_rule = rules.get("amount_mismatch", {})
    if amount_rule.get("enabled", True):
        amount_threshold = float(amount_rule.get("threshold", 0) or 0)
        amount_tolerance = amount_threshold if amount_threshold > 0 else 0.01
        for biz in business_records:
            order_id = biz.get("order_id")
            invoice_num = biz.get("invoice_num")
            business_key = str(order_id or invoice_num or biz.get("source_doc_no") or biz.get("_match_key") or "")
            if not business_key:
                continue
            fin = _resolve_finance(biz)
            if not fin:
                continue
            b_amt = float(biz.get("sales_amount") or 0)
            f_amt = float(fin.get("sales_amount") or 0)
            if abs(b_amt - f_amt) > amount_tolerance:
                sig = f"amt|{invoice_num or business_key}"
                if sig in seen_amount:
                    continue
                seen_amount.add(sig)
                diff_amt = abs(b_amt - f_amt)
                results.append(_build_item(
                    diff_type=DifferenceType.AMOUNT_MISMATCH.value,
                    rule_id="amount_mismatch",
                    rule_name="金额差异规则",
                    description=f"业务键 {business_key} 业务侧 {b_amt} 与财务侧 {f_amt} 不一致",
                    business_key=business_key,
                    business_amount=b_amt,
                    finance_amount=f_amt,
                    amount_diff=diff_amt,
                    confidence=rules["amount_mismatch"]["confidence"],
                    responsible_party=rules["amount_mismatch"].get("responsible_party", "finance"),
                    biz=biz,
                    fin=fin,
                    statement=_find_statement(statement_records, biz),
                    extra_evidence={"difference_amount": diff_amt},
                ))

    # Rule 1b: 映射配对后金额不一致（来自 field_mapping 报告）
    if mapping_report and amount_rule.get("enabled", True):
        amount_threshold = float(amount_rule.get("threshold", 0) or 0)
        amount_tolerance = amount_threshold if amount_threshold > 0 else 0.01
        for pair in mapping_report.get("match_pairs") or []:
            if pair.get("matched"):
                continue
            b_amt = float(pair.get("business_amount") or 0)
            f_amt = float(pair.get("finance_amount") or 0)
            if abs(b_amt - f_amt) <= amount_tolerance:
                continue
            business_key = str(pair.get("business_key") or pair.get("invoice_num") or "")
            if not business_key:
                continue
            sig = f"pair|{business_key}"
            if sig in seen_amount:
                continue
            seen_amount.add(sig)
            diff_amt = abs(b_amt - f_amt)
            results.append(_build_item(
                diff_type=DifferenceType.AMOUNT_MISMATCH.value,
                rule_id="amount_mismatch",
                rule_name="金额差异规则",
                description=f"配对键 {business_key} 业务侧 {b_amt} 与财务侧 {f_amt} 不一致",
                business_key=business_key,
                business_amount=b_amt,
                finance_amount=f_amt,
                amount_diff=diff_amt,
                confidence=rules["amount_mismatch"]["confidence"],
                responsible_party=rules["amount_mismatch"].get("responsible_party", "finance"),
                biz={"business_key": business_key, "sales_amount": b_amt},
                fin={"sales_amount": f_amt},
                statement=None,
                extra_evidence={"difference_amount": diff_amt, "source": "mapping_pair"},
            ))

    # Rule 1c: 未匹配记录（仅一侧存在）
    unmatched_rule = rules.get("unmatched_record", {"enabled": True, "confidence": 0.9, "responsible_party": "finance"})
    if mapping_report and unmatched_rule.get("enabled", True):
        seen_unmatched: set[str] = set()
        for item in mapping_report.get("unmatched_business") or []:
            rec = item.get("record") or {}
            key = str(item.get("business_key") or rec.get("order_id") or rec.get("invoice_num") or "")
            if not key or key in seen_unmatched:
                continue
            seen_unmatched.add(key)
            b_amt = float(rec.get("sales_amount") or 0)
            results.append(_build_item(
                diff_type=DifferenceType.AMOUNT_MISMATCH.value,
                rule_id="unmatched_record",
                rule_name="未匹配记录规则",
                description=f"业务侧记录 {key} 在财务侧无对应匹配",
                business_key=key,
                business_amount=b_amt,
                finance_amount=None,
                amount_diff=abs(b_amt),
                confidence=unmatched_rule.get("confidence", 0.9),
                responsible_party=unmatched_rule.get("responsible_party", "finance"),
                biz=rec,
                fin=None,
                statement=_find_statement(statement_records, rec),
                extra_evidence={"unmatched_side": "business"},
            ))
        for item in mapping_report.get("unmatched_finance") or []:
            rec = item.get("record") or {}
            key = str(item.get("finance_key") or rec.get("order_id") or rec.get("invoice_num") or "")
            if not key or key in seen_unmatched:
                continue
            seen_unmatched.add(key)
            f_amt = float(rec.get("sales_amount") or 0)
            results.append(_build_item(
                diff_type=DifferenceType.AMOUNT_MISMATCH.value,
                rule_id="unmatched_record",
                rule_name="未匹配记录规则",
                description=f"财务侧记录 {key} 在业务侧无对应匹配",
                business_key=key,
                business_amount=0,
                finance_amount=f_amt,
                amount_diff=abs(f_amt),
                confidence=unmatched_rule.get("confidence", 0.9),
                responsible_party=unmatched_rule.get("responsible_party", "finance"),
                biz={},
                fin=rec,
                statement=None,
                extra_evidence={"unmatched_side": "finance"},
            ))

    # Rule 2: Duplicate records on business or finance side
    if rules.get("duplicate_record", {}).get("enabled", True):
        def _scan_duplicates(side: str, records: list[dict]) -> None:
            index: dict[tuple, list[dict]] = {}
            for rec in records:
                key = (rec.get("order_id"), rec.get("invoice_num"), rec.get("customer_id"))
                index.setdefault(key, []).append(rec)
            for key, rows in index.items():
                if len(rows) < 2 or not key[0]:
                    continue
                sig = f"dup|{side}|{key[0]}|{key[1]}"
                if sig in seen_dup:
                    continue
                seen_dup.add(sig)
                amounts = [float(r.get("sales_amount") or 0) for r in rows]
                deduped = amounts[0] if amounts else 0
                label = "业务侧" if side == "business" else "财务侧"
                fin_ref = finance_by_order.get(str(key[0])) if side == "business" else rows[0]
                results.append(_build_item(
                    diff_type=DifferenceType.DUPLICATE_RECORD.value,
                    rule_id="duplicate_record",
                    rule_name="重复数据规则",
                    description=f"订单 {key[0]} {label}重复 {len(rows)} 次，去重后金额 {deduped}",
                    business_key=str(key[0]),
                    business_amount=sum(amounts),
                    finance_amount=deduped,
                    amount_diff=sum(amounts) - deduped,
                    confidence=rules["duplicate_record"]["confidence"],
                    responsible_party=rules["duplicate_record"].get("responsible_party", "finance"),
                    biz=rows[0],
                    fin=fin_ref,
                    statement=_find_statement(statement_records, rows[0]),
                    extra_evidence={
                        "duplicate_count": len(rows),
                        "duplicate_rows": rows,
                        "deduped_amount": deduped,
                        "duplicate_side": side,
                    },
                ))

        _scan_duplicates("business", business_records)
        _scan_duplicates("finance", finance_records)

    # Rule 3: Mapping anomaly — MDM + product encoding
    if rules.get("mapping_anomaly", {}).get("enabled", True):
        for biz in business_records:
            order_id = biz.get("order_id")
            invoice_num = biz.get("invoice_num")
            if not order_id and not invoice_num:
                continue
            fin = _resolve_finance(biz)
            if not fin:
                continue
            hits: list[dict] = []
            fin_rows = fin.get("_finance_rows") or [fin]
            ok, reason = check_mdm_consistency(biz, fin_rows[0], mdm_lookup)
            if not ok and reason:
                hits.append({"sub_rule": "mdm_mapping", "message": reason})
            mdm_ids = {str(r.get("mdm_id") or r.get("customer_id") or "") for r in fin_rows if r.get("mdm_id") or r.get("customer_id")}
            biz_mdm = str(biz.get("mdm_id") or biz.get("customer_id") or "")
            if len(fin_rows) > 1 and len(mdm_ids) > 1:
                hits.append({
                    "sub_rule": "invoice_split_mdm",
                    "message": f"发票 {biz.get('invoice_num')} 在财务侧拆分为 {len(fin_rows)} 行且对应多个 MDM 客户",
                })
            elif biz_mdm and mdm_ids and biz_mdm not in mdm_ids and len(mdm_ids) == 1:
                only = next(iter(mdm_ids))
                if biz_mdm != only:
                    hits.append({
                        "sub_rule": "mdm_mapping",
                        "message": f"业务 MDM {biz_mdm} 与财务侧 MDM {only} 不一致",
                    })
            sap_prod = biz.get("product_code")
            fin_prod = fin.get("product_code")
            if sap_prod and fin_prod and str(sap_prod) != str(fin_prod):
                hits.append({
                    "sub_rule": "product_encoding",
                    "message": f"产品编码不一致: 业务={sap_prod}, 财务={fin_prod}",
                    "source_code": str(sap_prod),
                    "target_code": str(fin_prod),
                })
            if not hits:
                continue
            sig = f"map|{invoice_num or order_id}|{hits[0].get('sub_rule')}"
            if sig in seen_map:
                continue
            seen_map.add(sig)
            b_amt = float(biz.get("sales_amount") or 0)
            f_amt = float(fin.get("sales_amount") or 0)
            results.append(_build_item(
                diff_type=DifferenceType.MAPPING_ANOMALY.value,
                rule_id="mapping_anomaly",
                rule_name="主数据/映射异常规则",
                description="; ".join(h["message"] for h in hits),
                business_key=str(order_id),
                business_amount=b_amt,
                finance_amount=f_amt,
                amount_diff=abs(b_amt - f_amt),
                confidence=rules["mapping_anomaly"]["confidence"],
                responsible_party=rules["mapping_anomaly"].get("responsible_party", "mdm_team"),
                biz=biz,
                fin=fin,
                statement=_find_statement(statement_records, biz),
                extra_evidence={"mapping_hits": hits},
                rule_hits=hits,
            ))

    from app.services.fangtai_quality_inspector import merge_fangtai_quality_diffs

    return merge_fangtai_quality_diffs(
        results,
        statement_records=statement_records or [],
        payment_records=payment_records,
        sap_settlement_records=sap_settlement_records,
        business_records=business_records,
        finance_records=finance_records,
        rules=rules,
        build_item_fn=_build_item,
    )


def detect_for_verification(
    business_records: list[dict],
    finance_records: list[dict],
    business_keys: list[str],
    db_rules: list[dict] | None = None,
) -> dict[str, bool]:
    """Return {business_key: resolved} after re-run on corrected data."""
    all_diffs = detect_differences(business_records, finance_records, db_rules=db_rules)
    still_bad = {d["business_key"] for d in all_diffs if d.get("business_key")}
    return {k: k not in still_bad for k in business_keys}


def _build_item(
    *,
    diff_type: str,
    rule_id: str,
    rule_name: str,
    description: str,
    business_key: str,
    business_amount: float,
    finance_amount: float | None,
    amount_diff: float,
    confidence: float,
    responsible_party: str,
    biz: dict,
    fin: dict | None,
    statement: dict | None,
    extra_evidence: dict,
    rule_hits: list | None = None,
) -> dict[str, Any]:
    hits = rule_hits or [{"rule_id": rule_id, "rule_name": rule_name, "message": description}]
    return {
        "id": str(uuid.uuid4()),
        "type": diff_type,
        "difference_type": diff_type,
        "business_key": business_key,
        "business_amount": business_amount,
        "finance_amount": finance_amount,
        "amount_diff": amount_diff,
        "confidence": confidence,
        "responsible_party": responsible_party,
        "sap_record": biz,
        "dms_record": fin,
        "statement_record": statement,
        "rule_id": rule_id,
        "description": description,
        "rule_hits": hits,
        "evidence": {
            "business_record": biz,
            "finance_record": fin,
            "statement_record": statement,
            **extra_evidence,
        },
        "risk_level": "high" if amount_diff > 50000 else "medium" if amount_diff > 10000 else "low",
    }


def _find_statement(records: list[dict], biz: dict) -> dict | None:
    order_id = biz.get("order_id")
    for rec in records:
        if str(rec.get("order_id")) == str(order_id):
            return rec
    return None
