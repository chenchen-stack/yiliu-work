/** 本体 / 语义配置页：技术字段 → 业务用户可读文案 */

export type RuleTypeMeta = {
  label: string
  color: string
  hint: string
}

export const RULE_TYPE_META: Record<string, RuleTypeMeta> = {
  DEFINITION: {
    label: '数据约定',
    color: 'blue',
    hint: '说明单据格式、字段口径怎么理解',
  },
  INVARIANT: {
    label: '平衡校验',
    color: 'cyan',
    hint: '对账时金额、合计必须满足的业务约束',
  },
  HEURISTIC: {
    label: '经验提示',
    color: 'default',
    hint: '常见情况的判断参考，帮助解释差异原因',
  },
  ANOMALY: {
    label: '异常判定',
    color: 'orange',
    hint: '出现差异时如何定性、是否需人工复核',
  },
  DETECT: {
    label: '自动检测',
    color: 'volcano',
    hint: '系统按登记表自动执行的检测逻辑',
  },
}

export const RULE_STATUS_META: Record<string, { label: string; color: string }> = {
  PUBLISHED: { label: '已生效', color: 'success' },
  DRAFT: { label: '草稿', color: 'default' },
  ARCHIVED: { label: '已停用', color: 'default' },
}

export const RULE_SOURCE_META: Record<string, { label: string; color: string; hint: string }> = {
  rule_engine: {
    label: '登记表导入',
    color: 'orange',
    hint: '来自《收入/回款异常问题登记表》Excel',
  },
  ontology: {
    label: '业务配置',
    color: 'processing',
    hint: '由管理员在语义配置中维护的口径与规则',
  },
}

const RELATION_DESC_MAP: Record<string, string> = {
  '主核对键：结算单维度（与本体翻译工作台一致）': '按结算单号对齐两边数据，是对账时最主要的对齐方式',
  '主核对键：结算单维度对齐（与本体翻译工作台一致）': '按结算单号对齐两边数据，是对账时最主要的对齐方式',
  'MDM/行级辅助匹配键': '行级辅助对齐：客户编码可能不一致，但主数据编号应相同',
  'MDM 行级辅助匹配；同一客户编码在 SAP/DMS 可能不同但 MDMID 一致':
    '行级辅助对齐：SAP 与 DMS 客户编码可能不同，但主数据编号（MDMID）应一致',
  '金额比对字段（需金额归一规则）': '两边比金额的字段，比较前需统一含税/不含税等口径',
  '台账行归属结算单头': '台账里每一行收入，归属哪一张结算单',
  '帆软汇总金额应等于 DMS 台账行合计（不变量校验）':
    '帆软报表汇总的 DMS 金额，应等于台账各行金额之和',
  '帆软 SAP 确认 vs SAP 结算行 DRP 金额': '帆软里的 SAP 确认金额，对应 SAP 结算行的 DRP 订单金额',
}

const RULE_CONTENT_REPLACEMENTS: Array<[RegExp, string]> = [
  [/dms_revenue_ledger/gi, 'DMS收入台账'],
  [/fanruan_reconciliation/gi, '帆软对账平台'],
  [/sap_settlement_line/gi, 'SAP结算行'],
  [/dms_settlement_order/gi, 'DMS结算单'],
  [/review_flow/gi, '复核流程'],
  [/re_verify\s*Skill/gi, '重验能力'],
  [/Workflow/gi, '工作流程'],
  [/MDM\/行级/gi, '主数据/行级'],
  [/MDMID/g, '主数据编号'],
  [/MDM/g, '主数据'],
  [/≠/g, '不等于'],
  [/→/g, '对应'],
]

export function ruleTypeLabel(ruleType?: string): string {
  if (!ruleType) return '—'
  return RULE_TYPE_META[ruleType]?.label || ruleType
}

export function ruleTypeMeta(ruleType?: string): RuleTypeMeta {
  return RULE_TYPE_META[ruleType || ''] || {
    label: ruleType || '—',
    color: 'default',
    hint: '',
  }
}

export function ruleStatusLabel(status?: string): string {
  if (!status) return '—'
  return RULE_STATUS_META[status]?.label || status
}

export function ruleStatusMeta(status?: string) {
  return RULE_STATUS_META[status || ''] || { label: status || '—', color: 'default' }
}

export function ruleSourceLabel(bindSource?: string | null): string {
  if (bindSource === 'rule_engine') return RULE_SOURCE_META.rule_engine.label
  return RULE_SOURCE_META.ontology.label
}

export function ruleSourceMeta(bindSource?: string | null) {
  return bindSource === 'rule_engine' ? RULE_SOURCE_META.rule_engine : RULE_SOURCE_META.ontology
}

export function humanizeRelationDescription(desc?: string | null): string {
  const raw = (desc || '').trim()
  if (!raw) return '—'
  if (RELATION_DESC_MAP[raw]) return RELATION_DESC_MAP[raw]
  return raw
    .replace(/主核对键/g, '主要对齐方式')
    .replace(/本体翻译工作台/g, '字段映射配置')
    .replace(/不变量校验/g, '合计必须一致')
    .replace(/MDM\/行级辅助匹配键/g, '主数据行级辅助对齐')
}

export function humanizeRuleContent(content?: string | null): string {
  let text = (content || '').trim()
  if (!text) return '—'
  for (const [pattern, replacement] of RULE_CONTENT_REPLACEMENTS) {
    text = text.replace(pattern, replacement)
  }
  return text
}

export function shortenEntityKey(entityKey?: string): string {
  const key = (entityKey || '').trim()
  if (!key) return '—'
  const table = key.split('.').pop() || key
  const friendly: Record<string, string> = {
    dms_revenue_ledger: 'DMS收入台账',
    dms_order: 'DMS订单明细',
    dms_settlement_order: 'DMS结算单',
    sap_settlement_line: 'SAP结算行',
    sap_settlement: 'SAP结算单',
    sap_revenue: 'SAP收入凭证',
    fanruan_reconciliation: '帆软对账平台',
    exception_register: '异常问题登记',
  }
  return friendly[table] || table.replace(/_/g, ' ')
}
