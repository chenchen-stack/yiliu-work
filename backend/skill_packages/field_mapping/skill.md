# field_mapping — 字段映射

## 元信息

- **skill_id**: skill-field_mapping
- **fangtai_ref**: FT-SKILL-002
- **name**: 字段映射
- **type**: 能力型
- **category**: 收入核对
- **description**: 按管理后台「本体翻译」字段映射配置，将 SAP 结算行与 DMS 收入台账翻译为统一实体与比对键
- **tags**: [本体翻译, 字段映射, 数据标准化]
- **version**: 1.0.0
- **status**: 已发布

## 接口定义

### 输入

```json
{
  "task_id": "FT-2026-06-001",
  "import_id": "imp-20260604-001",
  "mapping_config": "fangtai_revenue_v1",
  "business_profile": "sap",
  "finance_profile": "dms"
}
```

### 输出

```json
{
  "mapping_id": "map-20260604-001",
  "match_pairs": 4120,
  "unmatched_business": 63,
  "unmatched_finance": 102,
  "business_count": 5183,
  "finance_count": 8178,
  "mapping_report": "见任务日志",
  "status": "ok"
}
```

## 执行逻辑

1. 读取业务中心绑定的 `MappingConfig` / `field_mapping_config`
2. 逐字段执行 SAP → 统一键、DMS → 统一键（见 `references/sap_dms_field_map.csv`）
3. 办事处 / MDMID / 产品编码等通过主数据别名表统一
4. 输出配对候选与未匹配行清单
5. 写入 Workflow 上下文供 `difference_detect` 使用

## 依赖

- `mapping_engine.MappingRegistry`
- 管理后台字段映射保存接口
- 方太主数据 / 办事处映射（`mdm_service`）

## 配置参数

见 `config.yaml`：`mapping_mode`、`fuzzy_threshold`、`missing_field_action`

## 工作流位置

收入核对 Workflow 第 2 步
