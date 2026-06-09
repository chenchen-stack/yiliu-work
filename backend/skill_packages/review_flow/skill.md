# review_flow — 复核流转

## 元信息

- **skill_id**: skill-review_flow
- **fangtai_ref**: FT-SKILL-005
- **name**: 复核流转
- **type**: 流程型
- **category**: 收入核对
- **description**: 将差异清单及 AI 解释推送到工作台待复核，支持财务确认 / 退回 / 指派，记录复核动作
- **tags**: [人工确认, 流程流转, 待复核]
- **version**: 1.0.0
- **status**: 已发布

## 接口定义

### 输入

```json
{
  "task_id": "FT-2026-06-001",
  "reviewer_id": "user-finance-001",
  "reviewer_name": "方太财务-李会计"
}
```

### 输出

```json
{
  "pending_count": 128,
  "confirmed_count": 0,
  "returned_count": 0,
  "assigned_count": 0,
  "task_status": "review",
  "items": [
    {
      "diff_id": "D-20260604-001",
      "action": "pending",
      "severity": "high"
    }
  ]
}
```

## 执行逻辑

1. 查询任务下全部 `differences`（状态 pending_review）
2. 按严重程度排序（high → medium → low）
3. 推送待复核列表到工作台 `/workbench/reconciliation`
4. 处理用户操作：确认 / 退回 / 指派（`review_flow_service`）
5. 全部复核完成后更新任务状态，可进入再次验证或报告

## 依赖

- 前端工作台复核页
- `review_flow_service`、`differences` API
- 审计日志 `audit_service`

## 配置参数

见 `config.yaml`

## 工作流位置

收入核对 Workflow 第 5 步
