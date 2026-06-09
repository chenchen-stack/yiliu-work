# report_gen — 报告生成

## 元信息

- **skill_id**: skill-report_gen
- **fangtai_ref**: FT-SKILL-007
- **name**: 报告生成
- **type**: 流程型
- **category**: 收入核对
- **description**: 生成 PDF 收入核对报告，含匹配统计、差异明细、AI 归因、复核记录，支持下载归档
- **tags**: [报告, PDF, 归档]
- **version**: 1.0.0
- **status**: 已发布

## 接口定义

### 输入

```json
{
  "task_id": "FT-2026-06-001",
  "format": "pdf",
  "include_fields": ["summary", "diff_detail", "attribution", "review_log"]
}
```

### 输出

```json
{
  "report_id": "rpt-20260604-001",
  "file_path": "/reports/FT-2026-06-001_reconciliation.pdf",
  "download_url": "/api/v1/tasks/.../report/download",
  "page_count": 18,
  "generated_at": "2026-06-04T10:30:00Z",
  "status": "ok"
}
```

## 执行逻辑

1. 汇总任务：差异统计、规则命中、复核记录
2. 渲染 Jinja2 HTML 模板 → PDF（`report_generator.generate_pdf_report`）
3. 写入 `reports/` 目录并返回下载链接
4. 可选：任务状态更新为 `closed` / 归档

## 依赖

- `task_report_service`
- `report_generator`（WeasyPrint / 内置 PDF）
- 文件存储（本地上传目录）

## 配置参数

见 `config.yaml`

## 工作流位置

收入核对 Workflow 第 7 步（全部确认后）
