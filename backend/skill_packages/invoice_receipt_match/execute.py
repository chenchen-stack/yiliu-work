"""发票收款匹配 Skill — 真实执行体

输入: 发票列表 + 收款流水列表
输出: 匹配结果列表 + 统计

铁律: JSON 进、JSON 出；不做数据库写入。
"""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher


def fuzzy_match(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, str(a).lower(), str(b).lower()).ratio()


def _parse_date(val) -> datetime | None:
    if isinstance(val, datetime):
        return val
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(str(val).strip()[:10], fmt)
        except ValueError:
            continue
    return None


def execute(input_data: dict, config: dict | None = None) -> dict:
    """Skill 执行入口 — 中台引擎统一调用此函数。"""

    cfg = config or {}
    amount_tolerance = float(cfg.get("金额容忍阈值", 0.05))
    date_window = int(cfg.get("日期窗口天数", 3))

    invoices = input_data.get("发票列表") or []
    receipts = input_data.get("收款流水列表") or []

    results = []
    stats = {"总发票数": len(invoices), "完全匹配数": 0, "部分匹配数": 0, "未匹配数": 0}

    used_receipts: set[int] = set()

    for invoice in invoices:
        inv_customer = str(invoice.get("客户ID") or "")
        inv_amount = float(invoice.get("金额") or 0)
        inv_date = _parse_date(invoice.get("日期"))
        inv_no = str(invoice.get("发票号") or "")

        # 候选筛选：按客户 ID 精确 + 模糊
        candidates: list[tuple[int, dict, float]] = []
        for idx, receipt in enumerate(receipts):
            if idx in used_receipts:
                continue
            payer = str(receipt.get("付款方") or "")
            if payer == inv_customer:
                candidates.append((idx, receipt, 1.0))
            elif fuzzy_match(payer, inv_customer) > 0.8:
                candidates.append((idx, receipt, fuzzy_match(payer, inv_customer)))

        if not candidates:
            results.append({
                "发票号": inv_no,
                "匹配流水号": "",
                "匹配状态": "未匹配",
                "差异详情": {
                    "差异类型": "客户不匹配",
                    "差异值": inv_amount,
                    "差异描述": f"发票 {inv_no} 客户 {inv_customer} 无匹配收款流水",
                },
            })
            stats["未匹配数"] += 1
            continue

        best_match = None
        best_idx = -1
        min_diff = float("inf")

        for idx, candidate, _score in candidates:
            r_amount = float(candidate.get("金额") or 0)
            r_date = _parse_date(candidate.get("交易日期"))

            if inv_amount > 0:
                pct_diff = abs(r_amount - inv_amount) / inv_amount
            else:
                pct_diff = abs(r_amount - inv_amount)

            if inv_date and r_date:
                days_diff = abs((r_date - inv_date).days)
            else:
                days_diff = 0

            if pct_diff <= amount_tolerance and days_diff <= date_window:
                if pct_diff < min_diff:
                    min_diff = pct_diff
                    best_match = candidate
                    best_idx = idx

        if best_match and min_diff == 0:
            used_receipts.add(best_idx)
            results.append({
                "发票号": inv_no,
                "匹配流水号": str(best_match.get("摘要") or best_match.get("来源账号") or ""),
                "匹配状态": "完全匹配",
                "差异详情": {
                    "差异类型": "无差异",
                    "差异值": 0,
                    "差异描述": "金额完全一致",
                },
            })
            stats["完全匹配数"] += 1
        elif best_match:
            used_receipts.add(best_idx)
            r_amount = float(best_match.get("金额") or 0)
            diff_val = round(abs(inv_amount - r_amount), 2)
            r_date = _parse_date(best_match.get("交易日期"))
            days = abs((r_date - inv_date).days) if inv_date and r_date else 0

            if days > date_window:
                dtype = "日期超窗"
                desc = f"日期差 {days} 天超过窗口 {date_window} 天"
            else:
                dtype = "金额差异"
                desc = f"发票 {inv_amount} vs 流水 {r_amount}，差异 {diff_val}"

            results.append({
                "发票号": inv_no,
                "匹配流水号": str(best_match.get("摘要") or best_match.get("来源账号") or ""),
                "匹配状态": "部分匹配",
                "差异详情": {
                    "差异类型": dtype,
                    "差异值": diff_val,
                    "差异描述": desc,
                },
            })
            stats["部分匹配数"] += 1
        else:
            results.append({
                "发票号": inv_no,
                "匹配流水号": "",
                "匹配状态": "未匹配",
                "差异详情": {
                    "差异类型": "日期超窗",
                    "差异值": inv_amount,
                    "差异描述": f"候选流水均超出日期窗口 {date_window} 天或金额容忍 {amount_tolerance*100}%",
                },
            })
            stats["未匹配数"] += 1

    return {
        "匹配结果列表": results,
        "统计": stats,
    }
