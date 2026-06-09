import type { SemanticsSubTab } from '../components/AdminSemanticsHub'

export type AgentAssetPanelKind =
  | 'knowledge_base'
  | 'llm'
  | 'skill'
  | 'semantics'
  | 'workflow'
  | 'skill_group'
  | 'rules'

export type AgentAssetPanelTarget = {
  kind: AgentAssetPanelKind
  title: string
  subtitle: string
  adminTab: string
  semSub?: SemanticsSubTab
  kbId?: string
  skillCode?: string
  skillIds?: string[]
  workflowId?: string
}

const SKILL_CODE_MAP: Record<string, string> = {
  'skill-anomaly_explain': 'anomaly_explain',
  'skill-query_tasks': 'query_tasks',
}

export function normalizeSkillCode(id: string): string {
  return SKILL_CODE_MAP[id] || id.replace(/^skill-/, '')
}

const PRESET: Record<string, AgentAssetPanelTarget> = {
  'kb-fangtai-cases': {
    kind: 'knowledge_base',
    title: '方太历史案例库',
    subtitle: '案例条目、上传与检索配置（能力资产 · 知识库）',
    adminTab: 'knowledge',
    kbId: 'kb-fangtai-cases',
  },
  revenue_reconciliation: {
    kind: 'knowledge_base',
    title: '收入核对知识',
    subtitle: '领域知识与 Excel 条目（能力资产 · 知识库）',
    adminTab: 'knowledge',
    kbId: 'revenue_reconciliation',
  },
  'kb-compliance': {
    kind: 'knowledge_base',
    title: '合规与校验要点',
    subtitle: '合规口径条目（能力资产 · 知识库）',
    adminTab: 'knowledge',
    kbId: 'kb-compliance',
  },
  'mock-ai': {
    kind: 'llm',
    title: 'Mock 演示模型',
    subtitle: '大模型中心 · 模拟联调配置',
    adminTab: 'llm',
  },
  'deepseek-v4-pro': {
    kind: 'llm',
    title: 'DeepSeek 推理',
    subtitle: '大模型中心 · API 与异常解释 Skill 联动',
    adminTab: 'llm',
  },
  'skill-anomaly_explain': {
    kind: 'skill',
    title: '异常解释',
    subtitle: 'Skill 包 · 提示词与在线测试',
    adminTab: 'skills',
    skillCode: 'anomaly_explain',
  },
  'skill-query_tasks': {
    kind: 'skill',
    title: '任务查询',
    subtitle: 'Skill 包 · 任务查询能力配置',
    adminTab: 'skills',
    skillCode: 'query_tasks',
  },
  sap_billing: {
    kind: 'semantics',
    title: 'SAP 发货开票',
    subtitle: '数据接入 · 方太发货开票数据源',
    adminTab: 'semantics',
    semSub: 'datasources',
  },
  dms_ledger: {
    kind: 'semantics',
    title: 'DMS 收入台账',
    subtitle: '数据接入 · 方太收入台账数据源',
    adminTab: 'semantics',
    semSub: 'datasources',
  },
  table_pair: {
    kind: 'semantics',
    title: '主表对 · 字段映射',
    subtitle: '数据语义 · SAP ↔ DMS 映射与匹配键',
    adminTab: 'semantics',
    semSub: 'mapping',
  },
  'wf-revenue-reconciliation-v1': {
    kind: 'workflow',
    title: '收入核对 Workflow',
    subtitle: '流程编排 · 节点顺序与节点级配置',
    adminTab: 'workflow',
    workflowId: 'wf-revenue-reconciliation-v1',
  },
  'bc-sem-datasources': {
    kind: 'semantics',
    title: '数据接入',
    subtitle: '业务中心绑定 · SAP / DMS 等数据源',
    adminTab: 'semantics',
    semSub: 'datasources',
  },
  'bc-sem-mapping': {
    kind: 'semantics',
    title: '字段映射',
    subtitle: '业务中心绑定 · 双源对齐与匹配键',
    adminTab: 'semantics',
    semSub: 'mapping',
  },
  'bc-sem-entities': {
    kind: 'semantics',
    title: '实体与规则',
    subtitle: '业务中心绑定 · 本体实体与领域规则',
    adminTab: 'semantics',
    semSub: 'entities',
  },
  'bc-sem-graph': {
    kind: 'semantics',
    title: '关系图谱',
    subtitle: '业务中心绑定 · 实体关系与对账路径',
    adminTab: 'semantics',
    semSub: 'graph',
  },
  'bc-rules': {
    kind: 'rules',
    title: '规则引擎',
    subtitle: '业务中心绑定的规则版本与检测规则',
    adminTab: 'rules',
  },
  'bc-llm': {
    kind: 'llm',
    title: '大模型',
    subtitle: '平台模型路由 · Workflow 与 Agent 共用',
    adminTab: 'llm',
  },
  'agent-skills-summary': {
    kind: 'skill_group',
    title: '已授权 Skill',
    subtitle: '对话侧开放的 Skill 包（可逐项查看配置）',
    adminTab: 'skills',
    skillIds: ['skill-anomaly_explain', 'skill-query_tasks'],
  },
  'agent-kb-summary': {
    kind: 'knowledge_base',
    title: '挂载知识库',
    subtitle: '在能力资产 · 知识库中维护条目',
    adminTab: 'knowledge',
    kbId: 'kb-fangtai-cases',
  },
  'agent-ds-summary': {
    kind: 'semantics',
    title: '数据范围',
    subtitle: 'SAP / DMS 双源接入配置',
    adminTab: 'semantics',
    semSub: 'datasources',
  },
}

export function resolveAgentAsset(assetKey: string): AgentAssetPanelTarget {
  const hit = PRESET[assetKey]
  if (hit) return hit
  if (assetKey.startsWith('skill-')) {
    const code = normalizeSkillCode(assetKey)
    return {
      kind: 'skill',
      title: assetKey,
      subtitle: 'Skill 包配置',
      adminTab: 'skills',
      skillCode: code,
    }
  }
  if (assetKey.startsWith('kb-') || assetKey === 'revenue_reconciliation') {
    return {
      kind: 'knowledge_base',
      title: assetKey,
      subtitle: '知识库条目配置',
      adminTab: 'knowledge',
      kbId: assetKey,
    }
  }
  return {
    kind: 'semantics',
    title: assetKey,
    subtitle: '能力资产配置',
    adminTab: 'semantics',
    semSub: 'datasources',
  }
}

export function buildAdminTabUrl(target: AgentAssetPanelTarget): string {
  const params = new URLSearchParams({ tab: target.adminTab })
  if (target.kind === 'knowledge_base' && target.kbId) {
    params.set('kb', target.kbId)
  }
  if (target.kind === 'semantics' && target.semSub) {
    params.set('tab', 'semantics')
    params.set('sem', target.semSub)
  }
  if (target.kind === 'skill' && target.skillCode) {
    params.set('tab', 'skills')
    params.set('skill', target.skillCode)
  }
  if (target.kind === 'workflow') {
    params.set('tab', 'workflow')
  }
  return `/admin?${params.toString()}`
}
