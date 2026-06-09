# 方太收入核对 · Skill 包

## 标准目录结构

```text
<skill_code>/
├── skill.md          # 说明书 + 接口 + 执行逻辑（主文档）
├── skill.yaml        # 机器可读元信息（中台 API 加载）
├── config.yaml       # 可配置参数
├── execute.py        # 可执行逻辑（可选）
├── references/       # 参考数据（可选）
└── scripts/          # 自定义脚本（可选）
```

## 七个 Workflow Skill（调用顺序）

| 序号 | code | 说明 |
|------|------|------|
| ① | `data_import` | 数据导入 |
| ② | `field_mapping` | 字段映射 |
| ③ | `difference_detect` | 差异识别 |
| ④ | `anomaly_explain` | 异常解释（仅有差异时） |
| ⑤ | `review_flow` | 复核流转 |
| ⑥ | `re_verify` | 再次验证（退回后） |
| ⑦ | `report_gen` | 报告生成 |

另：`query_tasks` 为对话内任务查询 Skill，不参与 Workflow 七步链路。

## API

- 列表：`GET /api/v1/skill-packages`
- 详情（含 skill.md 全文）：`GET /api/v1/skill-packages/{code}`
