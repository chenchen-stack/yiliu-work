"""A客户（方太）收入对账领域 — 语义层种子数据（设计文档对齐）。"""

from __future__ import annotations

from typing import Any

DOMAIN = "revenue_reconciliation"

# Excel Sheet 名 → 标准实体（Layer 1 + Layer 2）
SHEET_TO_ENTITY: dict[str, dict[str, Any]] = {
    "DMS收入台账明细": {
        "datasource_code": "dms_pg",
        "schema_name": "public",
        "table_name": "dms_revenue_ledger",
        "label": "DMS收入台账",
        "description": "DMS 经销商收入台账明细；财务侧主核对表，按订单行记录含税/不含税收入。",
        "aliases": ["DMS台账", "收入台账", "dms_revenue_ledger", "结算单编码", "MDMID"],
        "source_type": "EXCEL",
    },
    "DMS结算单明细": {
        "datasource_code": "dms_pg",
        "schema_name": "public",
        "table_name": "dms_settlement_order",
        "label": "DMS结算单",
        "description": "DMS 结算单头：法人客户、MDM、结算单编号与含税开票总金额。",
        "aliases": ["结算单", "dms_settlement_order", "TCH结算单"],
        "source_type": "EXCEL",
    },
    "DMS订单明细": {
        "datasource_code": "dms_pg",
        "schema_name": "public",
        "table_name": "dms_order",
        "label": "DMS订单明细",
        "description": "DMS 订单行与结算状态、台账收入金额。",
        "aliases": ["dms_order", "订单行"],
        "source_type": "EXCEL",
    },
    "SAP收入总额": {
        "datasource_code": "sap_pg",
        "schema_name": "public",
        "table_name": "sap_revenue",
        "label": "SAP收入凭证",
        "description": "SAP FI 收入总额/凭证行，用于与 DMS、帆软汇总交叉验证。",
        "aliases": ["SAP凭证", "sap_revenue", "凭证编号"],
        "source_type": "EXCEL",
    },
    "SAP结算单明细": {
        "datasource_code": "sap_pg",
        "schema_name": "public",
        "table_name": "sap_settlement",
        "label": "SAP结算单",
        "description": "SAP 侧 DMS 结算订单视图：客户、办事处、结算/开票状态。",
        "aliases": ["sap_settlement", "DMS结算订单"],
        "source_type": "EXCEL",
    },
    "SAP结算行明细": {
        "datasource_code": "sap_pg",
        "schema_name": "public",
        "table_name": "sap_settlement_line",
        "label": "SAP结算行",
        "description": "SAP 结算行明细；业务侧主核对表，含 DRP 订单金额、开票凭证。",
        "aliases": ["SAP结算行", "sap_settlement_line", "DRP订单金额", "业务侧"],
        "source_type": "EXCEL",
    },
    "SAP结算单对应的订单行明细": {
        "datasource_code": "sap_pg",
        "schema_name": "public",
        "table_name": "sap_settlement_line_order",
        "label": "SAP结算单订单行",
        "description": "SAP 结算单下钻至订单行粒度，用于与 DMS 行级比对。",
        "aliases": ["订单行明细", "DRP客户编号"],
        "source_type": "EXCEL",
    },
    "帆软对账平台": {
        "datasource_code": "fanruan_pg",
        "schema_name": "public",
        "table_name": "fanruan_reconciliation",
        "label": "帆软对账平台",
        "description": "帆软 BI 汇总对账结果；当前财务手工核对主界面，含四系统收入确认金额与差异标识。",
        "aliases": ["帆软", "fanruan", "收入确认差异", "对账平台"],
        "source_type": "EXCEL",
    },
}


def entity_key(datasource_code: str, schema_name: str, table_name: str) -> str:
    return f"{datasource_code}.{schema_name}.{table_name}"


def seed_entities() -> list[dict[str, Any]]:
    """设计文档规定的 8+ 实体骨架（列由 Excel 抽取覆盖）。"""
    entities: list[dict[str, Any]] = []
    for sheet_meta in SHEET_TO_ENTITY.values():
        key = entity_key(sheet_meta["datasource_code"], sheet_meta["schema_name"], sheet_meta["table_name"])
        entities.append(
            {
                "datasource_code": sheet_meta["datasource_code"],
                "source_type": sheet_meta.get("source_type", "POSTGRES"),
                "schema_name": sheet_meta["schema_name"],
                "table_name": sheet_meta["table_name"],
                "entity_key": key,
                "label": sheet_meta["label"],
                "description": sheet_meta["description"],
                "aliases": sheet_meta.get("aliases", []),
                "columns": _default_columns(sheet_meta["table_name"]),
                "domain": DOMAIN,
                "data_sensitivity": "internal_finance",
            }
        )
    entities.append(
        {
            "datasource_code": "knowledge",
            "source_type": "EXCEL",
            "schema_name": "register",
            "table_name": "exception_register",
            "entity_key": entity_key("knowledge", "register", "exception_register"),
            "label": "异常问题登记",
            "description": "收入/回款异常问题登记表，沉淀原因分析与处理方案，供 RAG 与 HEURISTIC 规则。",
            "aliases": ["异常登记", "exception_register", "回款问题"],
            "columns": [],
            "domain": DOMAIN,
            "data_sensitivity": "internal",
        }
    )
    return entities


def _default_columns(table_name: str) -> list[dict[str, Any]]:
    """设计文档字段口径（无 Excel 时的默认列定义）。"""
    presets: dict[str, list[dict[str, Any]]] = {
        "dms_revenue_ledger": [
            _col("客户编码", "text", "DMS 客户编码，与 SAP 客户编号可能不同"),
            _col("MDMID", "text", "MDM 主数据唯一标识，跨系统对齐主键"),
            _col("结算单编码", "text", "DMS 结算单号，格式 TCH+日期+序号"),
            _col("收入含税金额", "numeric", "含税收入金额（元）"),
            _col("收入不含税金额", "numeric", "不含税收入；应满足 含税≈不含税×(1+税率)"),
        ],
        "dms_settlement_order": [
            _col("法人客户编码", "text", "法人主体客户编码"),
            _col("MDM编码", "text", "MDM 编码"),
            _col("结算单编号", "text", "结算单头编号"),
            _col("含税开票总金额", "numeric", "结算单含税开票合计"),
        ],
        "sap_settlement_line": [
            _col("DMS结算订单", "text", "关联 DMS 结算单编码"),
            _col("DMS行唯一ID", "text", "行级唯一键"),
            _col("DRP订单金额", "numeric", "DRP 口径订单金额"),
            _col("开票凭证", "text", "SAP 开票凭证号，通常 9 位数字"),
        ],
        "fanruan_reconciliation": [
            _col("客户NO", "text", "对账展示客户号"),
            _col("MDMID", "text", "MDM 标识"),
            _col("SAP收入确认金额", "numeric", "帆软侧 SAP 确认收入"),
            _col("DMS收入确认金额", "numeric", "帆软侧 DMS 确认收入"),
            _col("收入确认金额差异", "numeric", "差异金额，≠0 需排查"),
            _col("差异标识", "text", "是否差异/备注"),
        ],
    }
    return presets.get(table_name, [])


def _col(name: str, data_type: str, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "data_type": data_type,
        "label": name,
        "description": description,
        "sensitivity": "internal",
        "sample_values": [],
    }


def seed_relations() -> list[dict[str, Any]]:
    sap_line = entity_key("sap_pg", "public", "sap_settlement_line")
    dms_ledger = entity_key("dms_pg", "public", "dms_revenue_ledger")
    dms_order = entity_key("dms_pg", "public", "dms_settlement_order")
    fanruan = entity_key("fanruan_pg", "public", "fanruan_reconciliation")
    return [
        {
            "from_entity": sap_line,
            "to_entity": dms_ledger,
            "from_column": "DMS结算订单",
            "to_column": "结算单编码",
            "relation_type": "MANUAL",
            "description": "主核对键：结算单维度（与本体翻译工作台一致）",
        },
        {
            "from_entity": sap_line,
            "to_entity": dms_ledger,
            "from_column": "DMS行唯一ID",
            "to_column": "MDMID",
            "relation_type": "MANUAL",
            "description": "MDM 行级辅助匹配；同一客户编码在 SAP/DMS 可能不同但 MDMID 一致",
        },
        {
            "from_entity": dms_ledger,
            "to_entity": dms_order,
            "from_column": "结算单编码",
            "to_column": "结算单编号",
            "relation_type": "FK",
            "description": "台账行归属结算单头",
        },
        {
            "from_entity": fanruan,
            "to_entity": dms_ledger,
            "from_column": "DMS收入确认金额",
            "to_column": "收入含税金额",
            "relation_type": "MANUAL",
            "description": "帆软汇总金额应等于 DMS 台账行合计（不变量校验）",
        },
        {
            "from_entity": fanruan,
            "to_entity": sap_line,
            "from_column": "SAP收入确认金额",
            "to_column": "DRP订单金额",
            "relation_type": "MANUAL",
            "description": "帆软 SAP 确认 vs SAP 结算行 DRP 金额",
        },
    ]


def seed_domain_rules() -> list[dict[str, Any]]:
    """设计文档 A 客户规则示例（≥10 条，四类齐全）。"""
    sap_line = entity_key("sap_pg", "public", "sap_settlement_line")
    return [
        {
            "domain": DOMAIN,
            "rule_type": "DEFINITION",
            "rule_content": "DMS结算单编码格式为 TCH+年月日+序号（如 TCH202604160001）；SAP 开票凭证通常为 9 位数字。",
            "priority": 1,
            "effective_status": "PUBLISHED",
        },
        {
            "domain": DOMAIN,
            "rule_type": "DEFINITION",
            "rule_content": "DMS 收入含税金额 = 收入不含税金额 × (1+税率)，差异超过 1 元视为口径异常。",
            "priority": 2,
            "effective_status": "PUBLISHED",
        },
        {
            "domain": DOMAIN,
            "entity_key": sap_line,
            "rule_type": "DEFINITION",
            "rule_content": "MDMID 为 MDM 主数据唯一标识；同一客户在 DMS 与 SAP 中 MDMID 一致但客户编码可能不同（如 601488 vs 10023391）。",
            "priority": 3,
            "effective_status": "PUBLISHED",
        },
        {
            "domain": DOMAIN,
            "rule_type": "INVARIANT",
            "rule_content": "同一张 DMS 结算单在 dms_revenue_ledger 按订单行拆分后，不含税金额合计应等于帆软 fanruan_reconciliation 的 DMS 收入确认金额。",
            "priority": 1,
            "risk_level": "MEDIUM",
            "effective_status": "PUBLISHED",
        },
        {
            "domain": DOMAIN,
            "rule_type": "INVARIANT",
            "rule_content": "SAP 收入确认金额应等于开票凭证金额且与 DRP 订单金额合计一致，差异超过 0.01 元需人工核查。",
            "priority": 2,
            "risk_level": "MEDIUM",
            "effective_status": "PUBLISHED",
        },
        {
            "domain": DOMAIN,
            "rule_type": "HEURISTIC",
            "rule_content": "广东分公司代运营：统筹结算单同一办事处不同 MDMID 汇总出现差异，常为组织架构调整而非系统错误。",
            "priority": 5,
            "effective_status": "PUBLISHED",
        },
        {
            "domain": DOMAIN,
            "rule_type": "HEURISTIC",
            "rule_content": "DMS 结算单状态「过账成功」但开票状态「开票中」：多为接口延迟，建议 24 小时后重查。",
            "priority": 6,
            "effective_status": "PUBLISHED",
        },
        {
            "domain": DOMAIN,
            "rule_type": "ANOMALY",
            "rule_content": "收入确认金额差异≠0 且备注为空或不可解释时，判定为「待排查差异」，触发人工复核 Workflow。",
            "priority": 3,
            "risk_level": "HIGH",
            "effective_status": "PUBLISHED",
        },
        {
            "domain": DOMAIN,
            "rule_type": "ANOMALY",
            "rule_content": "同一结算单多系统金额差异>1000 元且连续 3 个月出现，倾向系统对接问题而非偶发异常。",
            "priority": 4,
            "risk_level": "HIGH",
            "effective_status": "PUBLISHED",
        },
        {
            "domain": DOMAIN,
            "rule_type": "ANOMALY",
            "rule_content": "异常登记表中「未闭环」项不得自动核销，须走 review_flow / re_verify Skill。",
            "priority": 5,
            "risk_level": "HIGH",
            "effective_status": "PUBLISHED",
        },
    ]
