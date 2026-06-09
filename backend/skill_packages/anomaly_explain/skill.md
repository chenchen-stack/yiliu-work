# anomaly_explain — 异常解释

## 元信息

- **skill_id**: skill-anomaly_explain
- **fangtai_ref**: FT-SKILL-004
- **name**: 异常解释
- **type**: 能力型
- **category**: 收入核对
- **description**: 对每条差异调用大模型进行归因分析，结合方太知识库 RAG 与规则命中证据链，输出解释与置信度
- **tags**: [AI归因, 大模型, RAG, 差异分析]
- **version**: 1.0.0
- **status**: 已发布

## 接口定义

### 输入

```json
{
  "diff_id": "D-20260604-001",
  "difference_item": {
    "id": "uuid",
    "type": "amount_mismatch",
    "business_key": "INV-001/客户A",
    "business_amount": 100000,
    "finance_amount": 98000,
    "amount_diff": 2000
  },
  "model": "deepseek-chat",
  "top_k_rag": 5
}
```

### 输出

```json
{
  "root_cause": "可能为 DMS 台账滞后或部分开票未同步",
  "suggested_action": "核对 SAP 结算行与 DMS 同键明细，确认过账日期",
  "confidence": 0.82,
  "evidence_chain": ["规则:金额差异", "案例:回款分款客户选错"],
  "model_used": "deepseek-chat",
  "status": "ok"
}
```

## 执行逻辑

1. 从 `differences` 加载差异上下文与规则命中信息
2. 构造 RAG Query：`{客户} {差异类型} 差额{amount_diff}`
3. 检索方太历史案例库 / 收入对账知识域（top_k）
4. 组装 Prompt，调用大模型（`ai_analyzer.analyze_difference`）
5. 解析 JSON/结构化字段，写入 `ai_explanation` 与对话卡片

## 依赖

- 大模型中心（Agent `model_route` → complex 模型）
- 知识库 `kb-fangtai-cases`、`revenue_reconciliation`
- `ai_analyzer`、对话 `difference_explain` UI 块

## 配置参数

见 `config.yaml`

## 工作流位置

收入核对 Workflow 第 4 步（仅处理有差异记录）
