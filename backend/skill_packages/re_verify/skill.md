# re_verify — 再次验证

## 元信息

- **skill_id**: skill-re_verify
- **fangtai_ref**: FT-SKILL-006
- **name**: 再次验证
- **type**: 能力型
- **category**: 收入核对
- **description**: 财务退回或修正源数据后，用处理后数据集重新跑规则比对，验证差异是否闭环
- **tags**: [重新比对, 数据修正, 闭环验证]
- **version**: 1.0.0
- **status**: 已发布

## 接口定义

### 输入

```json
{
  "task_id": "FT-2026-06-001",
  "diff_id": "D-20260604-001",
  "corrected_dataset_path": "/data/fangtai/202606/corrected/",
  "correction_reason": "已补录 DMS 漏记收入行"
}
```

### 输出

```json
{
  "diff_id": "D-20260604-001",
  "resolved": true,
  "remaining_diffs": 12,
  "retry_round": 1,
  "verify_status": "passed",
  "message": "该差异已消除，任务剩余 12 条待处理"
}
```

## 执行逻辑

1. 接收财务修正后的业务/财务侧文件或数据集 ID
2. 替换任务上下文中的比对数据
3. 重新执行 `difference_detect` 规则集
4. 若差异消除 → 标记 resolved；否则返回待再次修正（最多 N 轮）
5. 更新任务 `verification` 记录

## 依赖

- Workflow verify 节点
- `sample-data/dataset_full/corrected/` 演示数据
- 规则引擎、`differences` 表

## 配置参数

见 `config.yaml`

## 工作流位置

复核「退回」后触发；闭环后进入 `report_gen`
