# data_import — 数据导入

## 元信息

- **skill_id**: skill-data_import
- **fangtai_ref**: FT-SKILL-001
- **name**: 数据导入
- **type**: 流程型
- **category**: 收入核对
- **description**: 读取任务绑定的业务侧 SAP 发货开票与财务侧 DMS 收入台账（及可选帆软报表），校验格式后入库
- **tags**: [数据接入, 格式校验, SAP, DMS]
- **version**: 1.0.0
- **status**: 已发布

## 接口定义

### 输入

```json
{
  "task_id": "FT-2026-06-001",
  "data_sources": [
    {
      "type": "sap_billing",
      "path": "/data/fangtai/202606/sap_settlement_lines.xlsx",
      "format": "xlsx",
      "side": "business"
    },
    {
      "type": "dms_ledger",
      "path": "/data/fangtai/202606/dms_income_ledger.xlsx",
      "format": "xlsx",
      "side": "finance"
    },
    {
      "type": "fanruan_statement",
      "path": "/data/fangtai/202606/fanruan_summary.xlsx",
      "format": "xlsx",
      "side": "statement"
    }
  ]
}
```

### 输出

```json
{
  "import_id": "imp-20260604-001",
  "business_rows": 5183,
  "finance_rows": 8178,
  "statement_rows": 0,
  "business_profile": "sap",
  "finance_profile": "dms",
  "warnings": [],
  "status": "ok"
}
```

## 执行逻辑

1. 校验文件格式（xlsx/csv）与文件大小上限
2. 校验必填字段（客户/办事处、金额、日期、发票号或结算单号等）
3. 按业务键组合去重（客户 + 单据号 + 日期）
4. 写入任务绑定的标准化记录池（业务侧 / 财务侧分表）
5. 返回导入统计与异常告警列表

## 依赖

- 数据接入层（`data_loader` / 文件上传目录）
- 方太 POC 数据集配置（`mapping_engine` profiles）
- SQLite / 任务执行上下文

## 配置参数

见 `config.yaml`：`max_file_size_mb`、`allow_empty_amount`、`dedup_keys`

## 工作流位置

收入核对 Workflow 第 1 步 → 供 `field_mapping` 消费
