"""方太 POC 扩展质检：帆软四列勾稽、状态/接口同步、回款域。"""
from __future__ import annotations

import re
from typing import Any

from app.models import DifferenceType

# 帆软对账平台列名（与 Excel 导出一致）
FANRUAN_COL_ALIASES = {
    "biz_type": ["业务", "业务类型"],
    "doc_no": ["单据号", "数据号"],
    "customer_no": ["客户NO", "客户编码"],
    "mdm_id": ["MDMID", "MDM编码"],
    "period": ["过账时间", "期间"],
    "sap_amount": ["SAP收入确认金额", "SAP确认金额"],
    "drp_amount": ["DRP收入确认金额", "DRP确认金额"],
    "ltc_amount": ["LTC收入确认金额", "LTC确认金额"],
    "dms_amount": ["DMS收入确认金额", "DMS确认金额"],
    "variance": ["收入确认金额差异", "确认金额差异"],
    "flag": ["差异标识", "差异标志"],
    "remark": ["Unnamed: 14", "备注"],
}

STATUS_OK_TOKENS = ("成功", "1", "s", "已过账", "过账成功", "已确认")
STATUS_BAD_POSTING = ("过账中", "过账失败", "未过账", "记账中")
STATUS_BAD_INVOICE = ("开票中", "未开票", "开票失败")
SYNC_FAIL_TOKENS = ("报错", "失败", "超时", "未回传", "未更新", "未同步", "接收成功但实际")


def _pick(rec: dict, *keys: str) -> Any:
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return None


def _float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def normalize_fanruan_row(raw: dict) -> dict:
    """将帆软 Sheet 行规范为统一字段。"""
    out: dict[str, Any] = dict(raw)
    for uf, aliases in FANRUAN_COL_ALIASES.items():
        for col in aliases:
            if col in raw:
                out[uf] = raw[col]
                break
    doc = str(out.get("doc_no") or "").strip()
    mdm = str(out.get("mdm_id") or "").strip()
    out["business_key"] = f"{doc}|{mdm}" if mdm else doc
    out["sales_amount"] = _float(out.get("sap_amount"))
    return out


def detect_fanruan_matrix_diffs(
    statement_records: list[dict],
    rules: dict[str, dict],
) -> list[dict[str, Any]]:
    rule = rules.get("fanruan_summary") or rules.get("amount_mismatch", {})
    if not rule.get("enabled", True) or not statement_records:
        return []

    tolerance = float(rule.get("threshold") or 0.01)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in statement_records:
        row = normalize_fanruan_row(raw)
        key = row.get("business_key") or ""
        if not key or key in seen:
            continue

        sap_a = _float(row.get("sap_amount"))
        drp_a = _float(row.get("drp_amount"))
        ltc_a = _float(row.get("ltc_amount"))
        dms_a = _float(row.get("dms_amount"))
        var_a = _float(row.get("variance"))
        flag = str(row.get("flag") or "")
        remark = str(row.get("remark") or "")

        channels = [("SAP", sap_a), ("DRP", drp_a), ("LTC", ltc_a), ("DMS", dms_a)]
        non_zero = [(n, a) for n, a in channels if abs(a) > tolerance]
        mismatch = False
        reasons: list[str] = []

        if "有差异" in flag or "差异" in flag:
            mismatch = True
            reasons.append(f"帆软差异标识：{flag}")

        if abs(var_a) > tolerance:
            mismatch = True
            reasons.append(f"收入确认金额差异列={var_a:,.2f}")

        if len(non_zero) >= 2:
            ref_name, ref_amt = non_zero[0]
            for name, amt in non_zero[1:]:
                if abs(amt - ref_amt) > tolerance:
                    mismatch = True
                    reasons.append(f"{ref_name}({ref_amt:,.2f}) vs {name}({amt:,.2f})")
                    break

        if not mismatch:
            continue

        seen.add(key)
        desc = "；".join(reasons[:4])
        if remark:
            desc += f"。备注：{remark[:120]}"

        out.append({
            "type": DifferenceType.FANRUAN_SUMMARY.value,
            "rule_id": "fanruan_summary",
            "rule_name": "帆软多系统汇总差异规则",
            "description": desc,
            "business_key": key,
            "business_amount": sap_a,
            "finance_amount": dms_a,
            "amount_diff": abs(var_a) if abs(var_a) > tolerance else abs(sap_a - dms_a),
            "confidence": float(rule.get("confidence", 0.92)),
            "responsible_party": rule.get("responsible_party", "finance"),
            "sap_record": {n: a for n, a in channels},
            "dms_record": {"dms_amount": dms_a, "remark": remark},
            "statement_record": row,
            "rule_hits": [{"sub_rule": "fanruan_matrix", "message": desc}],
        })
    return out


def _status_text(rec: dict) -> str:
    parts = []
    for k, v in rec.items():
        if v is None:
            continue
        ks = str(k)
        if any(t in ks for t in ("状态", "回传", "开票", "过账", "消息")):
            parts.append(f"{ks}={v}")
    return " ".join(parts)


def _is_bad_status_combo(text: str) -> tuple[bool, str]:
    lower = text.lower()
    if any(t in text for t in STATUS_BAD_POSTING):
        return True, "结算/过账状态异常（过账中或失败）"
    if "过账成功" in text or "过账成功" in lower:
        if any(t in text for t in STATUS_BAD_INVOICE):
            return True, "过账已成功但开票状态仍为进行中或失败"
    if any(t in text for t in SYNC_FAIL_TOKENS):
        return True, "存在接口回传/同步失败迹象"
    confirm = _pick_from_text(text, "DMS收入确认回传", "收入确认回传")
    if confirm is not None:
        cs = str(confirm).strip()
        if cs and cs not in STATUS_OK_TOKENS and not cs.startswith("成功"):
            return True, f"收入确认回传异常：{cs}"
    return False, ""


def _pick_from_text(text: str, *labels: str) -> Any:
    for lab in labels:
        if lab in text:
            m = re.search(rf"{re.escape(lab)}[=:]\s*(\S+)", text)
            if m:
                return m.group(1)
    return None


def detect_status_sync_diffs(
    business_records: list[dict],
    finance_records: list[dict],
    *,
    sap_settlement_records: list[dict] | None = None,
    rules: dict[str, dict],
) -> list[dict[str, Any]]:
    status_rule = rules.get("status_mismatch", {})
    sync_rule = rules.get("sync_failure", {})
    if not status_rule.get("enabled", True) and not sync_rule.get("enabled", True):
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _emit(rec: dict, side: str, rule_key: str, rule_name: str, diff_type: str, reason: str, conf: float, party: str):
        oid = str(rec.get("order_id") or rec.get("DMS结算订单") or rec.get("结算单编码") or rec.get("结算单编号") or "")
        inv = str(rec.get("invoice_num") or rec.get("开票凭证") or "")
        bk = oid or inv or str(rec.get("_match_key") or rec.get("business_key") or "")[:40]
        if not bk:
            return
        sig = f"{rule_key}|{side}|{bk}"
        if sig in seen:
            return
        seen.add(sig)
        out.append({
            "type": diff_type,
            "rule_id": rule_key,
            "rule_name": rule_name,
            "description": f"{side}：{reason}",
            "business_key": bk,
            "business_amount": _float(rec.get("sales_amount") or rec.get("DRP订单金额")),
            "finance_amount": None,
            "amount_diff": 0.0,
            "confidence": conf,
            "responsible_party": party,
            "sap_record": rec if side.startswith("SAP") or side == "业务侧" else {},
            "dms_record": rec if "DMS" in side or side == "财务侧" else {},
            "rule_hits": [{"sub_rule": rule_key, "message": reason}],
        })

    all_recs: list[tuple[str, dict]] = []
    for r in business_records:
        all_recs.append(("SAP业务侧", r))
    for r in finance_records:
        all_recs.append(("DMS财务侧", r))
    for r in sap_settlement_records or []:
        all_recs.append(("SAP结算单", r))

    for side, rec in all_recs:
        text = _status_text(rec)
        if not text.strip():
            continue
        bad, reason = _is_bad_status_combo(text)
        if not bad:
            continue
        is_sync = any(t in reason for t in ("回传", "同步", "接口"))
        if is_sync and sync_rule.get("enabled", True):
            _emit(
                rec, side, "sync_failure", "方太·接口/同步异常规则",
                DifferenceType.SYNC_FAILURE.value, reason,
                float(sync_rule.get("confidence", 0.9)),
                sync_rule.get("responsible_party", "business"),
            )
        elif status_rule.get("enabled", True):
            _emit(
                rec, side, "status_mismatch", "方太·状态不一致规则",
                DifferenceType.STATUS_MISMATCH.value, reason,
                float(status_rule.get("confidence", 0.88)),
                status_rule.get("responsible_party", "finance"),
            )

    # 跨侧：同结算单号 SAP 已确认回传成功 vs DMS 行结算状态
    fin_by_order: dict[str, dict] = {}
    for r in finance_records:
        oid = str(r.get("order_id") or r.get("结算单编码") or r.get("结算单编号") or "")
        if oid:
            fin_by_order[oid] = r

    for rec in business_records:
        oid = str(rec.get("order_id") or rec.get("DMS结算订单") or "")
        if not oid or oid not in fin_by_order:
            continue
        fin = fin_by_order[oid]
        biz_confirm = str(rec.get("DMS收入确认回传") or rec.get("收入确认回传") or "")
        fin_status = str(fin.get("settlement_status") or fin.get("结算状态") or "")
        if biz_confirm in ("1", "成功") and fin_status in STATUS_BAD_POSTING:
            sig = f"cross|{oid}"
            if sig in seen:
                continue
            seen.add(sig)
            reason = f"SAP侧回传已成功，DMS结算状态仍为「{fin_status}」"
            if sync_rule.get("enabled", True):
                out.append({
                    "type": DifferenceType.SYNC_FAILURE.value,
                    "rule_id": "sync_failure",
                    "rule_name": "方太·接口/同步异常规则",
                    "description": reason,
                    "business_key": oid,
                    "business_amount": _float(rec.get("sales_amount")),
                    "finance_amount": _float(fin.get("sales_amount")),
                    "amount_diff": 0.0,
                    "confidence": float(sync_rule.get("confidence", 0.9)),
                    "responsible_party": "business",
                    "sap_record": rec,
                    "dms_record": fin,
                    "rule_hits": [{"sub_rule": "sap_dms_sync", "message": reason}],
                })

    return out


def detect_payment_diffs(
    payment_records: list[dict],
    rules: dict[str, dict],
) -> list[dict[str, Any]]:
    rule = rules.get("payment_mismatch", {})
    if not rule.get("enabled", True) or not payment_records:
        return []

    tolerance = float(rule.get("threshold") or 0.01)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    by_settlement: dict[str, list[dict]] = {}
    for rec in payment_records:
        code = str(
            rec.get("order_id")
            or rec.get("结算单编码")
            or rec.get("结算单编号")
            or rec.get("settlement_id")
            or ""
        ).strip()
        if code:
            by_settlement.setdefault(code, []).append(rec)

    for code, rows in by_settlement.items():
        total = sum(_float(r.get("sales_amount") or r.get("台账收入含税金额") or r.get("收入含税金额")) for r in rows)
        statuses = {str(r.get("settlement_status") or r.get("结算状态") or "") for r in rows}
        if len(rows) >= 2 and len(statuses) > 1:
            sig = f"pay|status|{code}"
            if sig not in seen:
                seen.add(sig)
                out.append({
                    "type": DifferenceType.PAYMENT_MISMATCH.value,
                    "rule_id": "payment_mismatch",
                    "rule_name": "方太·回款/结算状态差异规则",
                    "description": f"结算单 {code} 在 DMS 订单/台账明细中存在多种结算状态：{', '.join(s for s in statuses if s)}",
                    "business_key": code,
                    "business_amount": total,
                    "finance_amount": None,
                    "amount_diff": 0.0,
                    "confidence": float(rule.get("confidence", 0.85)),
                    "responsible_party": rule.get("responsible_party", "finance"),
                    "dms_record": {"rows": len(rows), "statuses": list(statuses)},
                    "rule_hits": [{"sub_rule": "payment_status_split", "message": "同单多状态"}],
                })

        for r in rows:
            amt = _float(r.get("sales_amount") or r.get("台账收入含税金额"))
            drp = _float(r.get("DRP订单金额") or r.get("drp_amount"))
            if drp and abs(amt - drp) > tolerance:
                sig = f"pay|amt|{code}|{r.get('订单编码', '')}"
                if sig in seen:
                    continue
                seen.add(sig)
                out.append({
                    "type": DifferenceType.PAYMENT_MISMATCH.value,
                    "rule_id": "payment_mismatch",
                    "rule_name": "方太·回款/付款金额差异规则",
                    "description": f"结算单 {code} 台账金额 {amt:,.2f} 与 DRP/订单金额 {drp:,.2f} 不一致",
                    "business_key": code,
                    "business_amount": drp,
                    "finance_amount": amt,
                    "amount_diff": abs(amt - drp),
                    "confidence": float(rule.get("confidence", 0.87)),
                    "responsible_party": rule.get("responsible_party", "finance"),
                    "dms_record": r,
                    "rule_hits": [{"sub_rule": "payment_amount", "message": "台账与订单金额不等"}],
                })

    return out


def merge_fangtai_quality_diffs(
    base_results: list[dict],
    *,
    statement_records: list[dict],
    payment_records: list[dict] | None,
    sap_settlement_records: list[dict] | None,
    business_records: list[dict],
    finance_records: list[dict],
    rules: dict[str, dict],
    build_item_fn,
) -> list[dict]:
    """将扩展质检结果合并进 detect_differences 输出（复用 _build_item）。"""
    extra: list[dict] = []
    extra.extend(detect_fanruan_matrix_diffs(statement_records, rules))
    extra.extend(
        detect_status_sync_diffs(
            business_records,
            finance_records,
            sap_settlement_records=sap_settlement_records,
            rules=rules,
        )
    )
    extra.extend(detect_payment_diffs(payment_records or [], rules))

    merged = list(base_results)
    for item in extra:
        merged.append(
            build_item_fn(
                diff_type=item["type"],
                rule_id=item["rule_id"],
                rule_name=item["rule_name"],
                description=item["description"],
                business_key=item["business_key"],
                business_amount=item.get("business_amount") or 0,
                finance_amount=item.get("finance_amount"),
                amount_diff=item.get("amount_diff") or 0,
                confidence=item.get("confidence", 0.85),
                responsible_party=item.get("responsible_party", "finance"),
                biz=item.get("sap_record") or {},
                fin=item.get("dms_record") or {},
                statement=item.get("statement_record"),
                extra_evidence={"rule_hits": item.get("rule_hits")},
                rule_hits=item.get("rule_hits"),
            )
        )
    return merged
