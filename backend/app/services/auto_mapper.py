"""AI 自动字段映射：根据两侧列名推荐统一字段、中文标签和翻译规则。"""

from __future__ import annotations

import json
from app.config import settings

KNOWN_MAPPINGS: dict[str, dict] = {
    "CUSTOMER":           {"unified": "customer_id",    "label": "客户编码",   "transform": "mdm",    "fin": ["client_id", "cust_id", "customer_code", "客户编码", "客户号"]},
    "KUNNR":              {"unified": "customer_id",    "label": "客户编码",   "transform": "mdm",    "fin": ["client_id", "cust_id"]},
    "VBELN":              {"unified": "order_id",       "label": "单据编号",   "transform": "rename", "fin": ["order_num", "order_no", "doc_num", "单据号"]},
    "BELNR":              {"unified": "source_doc_no",  "label": "凭证号",     "transform": "rename", "fin": ["doc_no", "voucher_no", "交易号"]},
    "ERDAT":              {"unified": "order_date",     "label": "业务日期",   "transform": "date",   "fin": ["create_date", "order_date", "biz_date", "日期", "交易时间"]},
    "BLDAT":              {"unified": "business_date",  "label": "记账日期",   "transform": "date",   "fin": ["posting_date", "交易时间"]},
    "NETWR":              {"unified": "sales_amount",   "label": "金额",       "transform": "amount", "fin": ["net_amount", "amount", "金额", "交易金额"]},
    "DMBTR":              {"unified": "sales_amount",   "label": "本币金额",   "transform": "amount", "fin": ["amount", "net_amount", "金额"]},
    "WAERK":              {"unified": "currency",       "label": "币种",       "transform": "rename", "fin": ["currency", "ccy", "币种"]},
    "MATNR":              {"unified": "product_code",   "label": "产品编码",   "transform": "rename", "fin": ["sku", "product", "material", "product_code", "物料号"]},
    "INVOICE":            {"unified": "invoice_num",    "label": "发票号",     "transform": "rename", "fin": ["invoice_no", "inv_no", "发票号"]},
    "BUKRS":              {"unified": "company_code",   "label": "公司代码",   "transform": "rename", "fin": ["company", "org_code"]},
    "settlement_status":  {"unified": "settlement_status", "label": "结算状态", "transform": "rename", "fin": ["status", "settle_status", "状态"]},
    "MDM_ID":             {"unified": "mdm_id",         "label": "MDM主数据ID","transform": "mdm",    "fin": ["mdm_id", "master_id"]},
    # 方太 POC 中文列（sap_revenue_total / dms_settlement_detail）
    "客户":               {"unified": "customer_id",    "label": "客户编码",   "transform": "mdm",    "fin": ["法人客户编码", "client_id", "cust_id"]},
    "DRP客户ID":          {"unified": "mdm_code",         "label": "MDM编码",    "transform": "mdm",    "fin": ["MDM编码", "mdm_id", "MDMID"]},
    "本位币金额":         {"unified": "sales_amount",   "label": "金额",       "transform": "amount", "fin": ["含税开票总金额", "net_amount", "金额"]},
    "金额":               {"unified": "sales_amount",   "label": "金额",       "transform": "amount", "fin": ["含税开票总金额", "net_amount", "收入含税金额"]},
    "开票凭证":           {"unified": "invoice_num",    "label": "发票号",     "transform": "rename", "fin": ["结算单编号", "invoice_no", "发票号"]},
    "凭证编号":           {"unified": "order_id",       "label": "单据编号",   "transform": "rename", "fin": ["结算单编号", "order_num", "结算单编码"]},
    "法人客户编码":       {"unified": "customer_id",    "label": "客户编码",   "transform": "mdm",    "fin": []},
    "含税开票总金额":     {"unified": "sales_amount",   "label": "金额",       "transform": "amount", "fin": []},
    "结算单编号":         {"unified": "order_id",       "label": "单据编号",   "transform": "rename", "fin": []},
    "MDM编码":            {"unified": "mdm_code",         "label": "MDM编码",    "transform": "mdm",    "fin": []},
    # 方太 POC：发货开票 ↔ 收入台账
    "DMS结算订单":        {"unified": "order_id",       "label": "单据编号",   "transform": "rename", "fin": ["结算单编码", "order_num", "结算单编号"]},
    "DRP订单金额":        {"unified": "sales_amount",   "label": "金额",       "transform": "amount", "fin": ["收入含税金额", "net_amount", "金额"]},
    "DMS行唯一ID":        {"unified": "mdm_code",         "label": "MDM编码",    "transform": "mdm",    "fin": ["MDMID", "MDM编码", "mdm_id"]},
    "处理日期":           {"unified": "business_date",  "label": "业务日期",   "transform": "date",   "fin": ["create_date", "交易时间"]},
    "结算单编码":         {"unified": "order_id",       "label": "单据编号",   "transform": "rename", "fin": []},
    "收入含税金额":       {"unified": "sales_amount",   "label": "金额",       "transform": "amount", "fin": []},
    "MDMID":              {"unified": "mdm_code",         "label": "MDM编码",    "transform": "mdm",    "fin": []},
}

GENERIC_LABEL_MAP: dict[str, str] = {
    "client_id": "客户编码", "order_num": "单据编号", "create_date": "日期",
    "net_amount": "金额", "sku": "产品编码", "invoice_no": "发票号",
    "source_line": "来源行号", "settlement_id": "结算单号", "mdm_id": "MDM编码",
    "交易时间": "交易时间", "金额": "金额", "摘要": "摘要", "交易号": "交易号",
    "方向": "收支方向", "币种": "币种", "账号": "账号",
    "法人客户编码": "客户编码", "MDM编码": "MDM编码", "结算单编号": "单据编号",
    "含税开票总金额": "金额", "开票凭证": "发票号", "凭证编号": "单据编号",
    "DRP客户ID": "MDM编码", "客户": "客户编码",
}


def _poc_billing_ledger_preset(biz_cols: list[str], fin_cols: list[str]) -> list[dict] | None:
    """SAP发货开票明细 + DMS收入台账：与 seed_fangtai_poc_closure 一致。"""
    biz_set = set(biz_cols)
    fin_set = set(fin_cols)
    if not ({"DMS结算订单", "DRP订单金额", "开票凭证"} <= biz_set and {"结算单编码", "收入含税金额"} <= fin_set):
        return None

    rows: list[dict] = []
    pairs = [
        ("order_id", "单据编号", "DMS结算订单", "结算单编码", "rename"),
        ("sales_amount", "金额", "DRP订单金额", "收入含税金额", "amount"),
        ("invoice_num", "发票号", "开票凭证", "结算单编码", "rename"),
        ("business_date", "业务日期", "处理日期", None, "date"),
        ("mdm_code", "MDM编码", "DMS行唯一ID", "MDMID", "mdm"),
    ]
    for uf, label, bc, fc, transform in pairs:
        if bc not in biz_set:
            continue
        if fc and fc not in fin_set:
            fc = None
        rows.append({
            "unified_field": uf,
            "unified_label": label,
            "business_column": bc,
            "finance_column": fc,
            "transform": transform,
            "enabled": True,
        })
    if not any(r["unified_field"] == "sales_amount" and r.get("finance_column") for r in rows):
        return None
    if not any(
        r["unified_field"] in ("order_id", "invoice_num") and r.get("finance_column")
        for r in rows
    ):
        return None
    return rows


def _poc_revenue_settlement_preset(biz_cols: list[str], fin_cols: list[str]) -> list[dict] | None:
    """SAP收入总额 + DMS结算单：与 poc_chinese_mapping.yaml 一致的核心对照。"""
    biz_set = set(biz_cols)
    fin_set = set(fin_cols)
    if not ({"开票凭证", "客户"} <= biz_set and {"结算单编号", "含税开票总金额", "法人客户编码"} <= fin_set):
        return None

    def pick(*names: str) -> str | None:
        for n in names:
            if n in biz_set:
                return n
        return None

    amount_biz = pick("本位币金额", "金额", "总帐金额")
    rows: list[dict] = []
    pairs = [
        ("customer_id", "客户编码", "客户", "法人客户编码", "mdm"),
        ("sales_amount", "金额", amount_biz, "含税开票总金额", "amount"),
        ("order_id", "单据编号", pick("凭证编号", "开票凭证"), "结算单编号", "rename"),
        ("invoice_num", "发票号", "开票凭证", None, "rename"),
        ("mdm_code", "MDM编码", "DRP客户ID", "MDM编码", "mdm"),
    ]
    for uf, label, bc, fc, transform in pairs:
        if not bc or bc not in biz_set:
            continue
        if fc and fc not in fin_set:
            fc = None
        rows.append({
            "unified_field": uf,
            "unified_label": label,
            "business_column": bc,
            "finance_column": fc,
            "transform": transform,
            "enabled": True,
        })
    if not any(r["unified_field"] == "sales_amount" and r.get("finance_column") for r in rows):
        return None
    if not any(
        r["unified_field"] in ("order_id", "invoice_num") and r.get("finance_column")
        for r in rows
    ):
        return None
    return rows


def _heuristic_map(biz_cols: list[str], fin_cols: list[str]) -> list[dict]:
    """基于已知映射表和列名相似度的智能匹配。"""
    for preset_fn in (_poc_billing_ledger_preset, _poc_revenue_settlement_preset):
        preset = preset_fn(biz_cols, fin_cols)
        if preset:
            return preset

    used_fin: set[str] = set()
    rows: list[dict] = []

    for bc in biz_cols:
        bc_upper = bc.strip().upper()
        known = KNOWN_MAPPINGS.get(bc) or KNOWN_MAPPINGS.get(bc_upper)
        if known:
            matched_fin = None
            for candidate in known["fin"]:
                if candidate in fin_cols and candidate not in used_fin:
                    matched_fin = candidate
                    break
            if matched_fin:
                used_fin.add(matched_fin)
            rows.append({
                "unified_field": known["unified"],
                "unified_label": known["label"],
                "business_column": bc,
                "finance_column": matched_fin,
                "transform": known["transform"],
                "enabled": True,
            })
        else:
            lower = bc.lower().replace("_", "").replace("-", "")
            matched_fin = None
            for fc in fin_cols:
                if fc in used_fin:
                    continue
                fc_lower = fc.lower().replace("_", "").replace("-", "")
                if lower == fc_lower or lower in fc_lower or fc_lower in lower:
                    matched_fin = fc
                    break
            if matched_fin:
                used_fin.add(matched_fin)
            label = GENERIC_LABEL_MAP.get(bc, GENERIC_LABEL_MAP.get(matched_fin or "", bc))
            rows.append({
                "unified_field": bc.lower(),
                "unified_label": label,
                "business_column": bc,
                "finance_column": matched_fin,
                "transform": "rename",
                "enabled": True,
            })

    for fc in fin_cols:
        if fc in used_fin:
            continue
        label = GENERIC_LABEL_MAP.get(fc, fc)
        rows.append({
            "unified_field": fc.lower(),
            "unified_label": label,
            "business_column": None,
            "finance_column": fc,
            "transform": "rename",
            "enabled": True,
        })

    return rows


async def _ai_map(biz_cols: list[str], fin_cols: list[str]) -> list[dict]:
    """调用 DeepSeek 大模型进行智能字段映射。"""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    prompt = f"""你是一位财务数据集成专家。现在有两个数据源需要做字段映射对照：

业务侧列名（SAP/ERP）：{json.dumps(biz_cols, ensure_ascii=False)}
财务侧列名（DMS/银行/台账）：{json.dumps(fin_cols, ensure_ascii=False)}

请为每对列生成映射建议，返回 JSON 数组，每个元素包含：
- unified_field: 统一字段英文名（snake_case）
- unified_label: 中文标签（简洁，如"客户编码""金额""发票号"）
- business_column: 业务侧原始列名（可为 null）
- finance_column: 财务侧原始列名（可为 null）
- transform: 翻译规则，取值：rename（直接重命名）、mdm（MDM主数据匹配）、amount（金额归一）、date（日期对齐）、fuzzy_customer（模糊客户匹配）、constant（常量填充）
- enabled: true

规则：
1. 尽量将两侧语义相同的列配对
2. 客户编码类字段用 mdm 规则，金额类用 amount，日期类用 date
3. 没有配对的列也要列出（另一侧为 null）
4. 只返回 JSON 数组，不要其他文字"""

    resp = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=2000,
    )
    text = resp.choices[0].message.content or "[]"
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    try:
        rows = json.loads(text)
        if isinstance(rows, list):
            return rows
    except json.JSONDecodeError:
        pass
    return _heuristic_map(biz_cols, fin_cols)


async def auto_map(biz_cols: list[str], fin_cols: list[str]) -> list[dict]:
    if not settings.use_mock_ai and settings.deepseek_api_key:
        try:
            return await _ai_map(biz_cols, fin_cols)
        except Exception:
            pass
    return _heuristic_map(biz_cols, fin_cols)
