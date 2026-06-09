# difference_detect — 差异识别

## 元信息

- **skill_id**: skill-difference_detect
- **fangtai_ref**: FT-SKILL-003
- **name**: 差异识别
- **type**: 能力型
- **category**: 收入核对
- **description**: 执行方太收入核对规则集，识别金额差异、重复数据、主数据/映射异常，产出差异清单
- **tags**: [对账, 规则引擎, 差异检测]
- **version**: 1.0.0
- **status**: 已发布

## 接口定义

### 输入

```json
{
  "task_id": "FT-2026-06-001",
  "mapping_id": "map-20260604-001",
  "rule_version_id": "rv-fangtai-default"
}
```

### 输出

```json
{
  "count": 128,
  "by_type": {
    "amount_mismatch": 45,
    "duplicate_record": 23,
    "mapping_anomaly": 60
  },
  "rules_applied": 12,
  "rule_names": ["金额差异", "重复数据", "映射异常"],
  "diff_ids": ["D-20260604-001"],
  "status": "ok"
}
```

## 执行逻辑

1. 加载已发布业务中心绑定的 `RuleConfig`（与后台规则引擎一致）
2. 按业务键（发票号 / 结算单 + 客户 + 日期）分组比对 SAP 与 DMS
3. 逐条执行规则：金额容差、重复组合键、MDM/办事处映射一致性
4. 写入 `differences` 表，更新任务进度
5. 返回按类型汇总的差异统计

## 依赖

- `difference_detector` / Workflow detect 节点
- `RuleConfig` + `rule_version_id`
- 方太质量检查（`fangtai_quality_inspector`）

## 配置参数

见 `config.yaml`

## 工作流位置

收入核对 Workflow 第 3 步 → 供 `anomaly_explain` / `review_flow` 消费
