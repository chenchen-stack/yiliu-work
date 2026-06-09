import type { SemanticsSubTab } from '../components/AdminSemanticsHub'

export type WorkflowNodePanelKind =
  | 'semantics'
  | 'rules'
  | 'llm'
  | 'skill'

export type WorkflowNodePanelTarget = {
  kind: WorkflowNodePanelKind
  title: string
  subtitle: string
  semSub?: SemanticsSubTab
  skillCode?: string
}

const NODE_PANEL: Record<string, WorkflowNodePanelTarget> = {
  import: {
    kind: 'semantics',
    title: '数据导入',
    subtitle: '配置业务/财务数据源接入',
    semSub: 'datasources',
  },
  mapping: {
    kind: 'semantics',
    title: '字段映射',
    subtitle: '语义字段对齐与匹配键',
    semSub: 'mapping',
  },
  ontology: {
    kind: 'semantics',
    title: '实体与规则',
    subtitle: '本体实体与已发布领域规则',
    semSub: 'entities',
  },
  detect: {
    kind: 'rules',
    title: '差异识别',
    subtitle: '检测规则与 Workflow 绑定',
  },
  ai_explain: {
    kind: 'llm',
    title: '异常解释',
    subtitle: '大模型参数与调用策略',
  },
  review: {
    kind: 'skill',
    title: '复核流转',
    subtitle: '人工复核 Skill 包',
    skillCode: 'review_flow',
  },
  verify: {
    kind: 'skill',
    title: '再次验证',
    subtitle: '复验 Skill 包',
    skillCode: 're_verify',
  },
  report: {
    kind: 'skill',
    title: '报告生成',
    subtitle: '报告 Skill 包',
    skillCode: 'report_gen',
  },
  query_tasks: {
    kind: 'skill',
    title: '任务查询',
    subtitle: '任务查询 Skill 包',
    skillCode: 'query_tasks',
  },
}

export function resolveWorkflowNodePanel(
  nodeId: string,
  skillCode?: string,
  label?: string,
): WorkflowNodePanelTarget {
  const preset = NODE_PANEL[nodeId]
  if (preset) return preset
  const code = skillCode || nodeId
  return {
    kind: 'skill',
    title: label || nodeId,
    subtitle: 'Skill 包配置与在线测试',
    skillCode: code,
  }
}
