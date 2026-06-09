import type { WorkflowNode } from '../api/client'

export type WorkflowNodeTemplate = WorkflowNode & {
  role: 'system' | 'ai' | 'human'
  description?: string
}

/** 可加入流程编排的节点模板（与后端 WORKFLOW_NODES 对齐） */
export const WORKFLOW_NODE_CATALOG: WorkflowNodeTemplate[] = [
  {
    id: 'import',
    label: '数据导入',
    skill: 'data_import',
    skill_code: 'data_import',
    enabled: true,
    role: 'system',
    description: '加载业务/财务数据源',
  },
  {
    id: 'ontology',
    label: '实体与规则',
    skill: 'ontology_context',
    skill_code: 'ontology_context',
    enabled: true,
    role: 'system',
    description: '加载本体与已发布规则',
  },
  {
    id: 'mapping',
    label: '字段映射',
    skill: 'field_mapping',
    skill_code: 'field_mapping',
    enabled: true,
    role: 'system',
    description: '语义字段对齐',
  },
  {
    id: 'detect',
    label: '差异识别',
    skill: 'difference_detect',
    skill_code: 'difference_detect',
    enabled: true,
    role: 'system',
    description: '规则引擎排查差异',
  },
  {
    id: 'ai_explain',
    label: '异常解释',
    skill: 'anomaly_explain',
    skill_code: 'anomaly_explain',
    enabled: true,
    role: 'ai',
    description: '大模型解释异常',
  },
  {
    id: 'query_tasks',
    label: '任务查询',
    skill: 'query_tasks',
    skill_code: 'query_tasks',
    enabled: true,
    role: 'system',
    description: '查询任务状态',
  },
  {
    id: 'review',
    label: '复核流转',
    skill: 'review_flow',
    skill_code: 'review_flow',
    enabled: true,
    role: 'human',
    description: '人工复核与流转',
  },
  {
    id: 'verify',
    label: '再次验证',
    skill: 're_verify',
    skill_code: 're_verify',
    enabled: true,
    role: 'system',
    description: '闭环后复验',
  },
  {
    id: 'report',
    label: '报告生成',
    skill: 'report_gen',
    skill_code: 'report_gen',
    enabled: true,
    role: 'system',
    description: '生成对账报告',
  },
]

const CATALOG_BY_ID = Object.fromEntries(
  WORKFLOW_NODE_CATALOG.map((t) => [t.id, t]),
) as Record<string, WorkflowNodeTemplate>

export function templateForNodeId(id: string): WorkflowNodeTemplate | undefined {
  return CATALOG_BY_ID[id]
}

export function listAddableNodeTemplates(existingIds: Set<string>): WorkflowNodeTemplate[] {
  return WORKFLOW_NODE_CATALOG.filter((t) => !existingIds.has(t.id))
}

export function cloneTemplate(template: WorkflowNodeTemplate): WorkflowNode {
  const { role: _r, description: _d, ...node } = template
  return { ...node, enabled: true }
}
