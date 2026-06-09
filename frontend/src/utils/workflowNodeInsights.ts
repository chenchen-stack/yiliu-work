import type { LlmConfig, OntologyMapping, WorkflowNode } from '../api/client'
import type { AdminRuleConfig } from '../api/client'
import { templateForNodeId } from './workflowNodeCatalog'

export type WorkflowNodeInsight = {
  roleLabel: string
  skillLabel: string
  skillType?: string
  desc: string
  lines: string[]
  pills: string[]
  bindingRulePills: string[]
  configHint: string
}

const ROLE_LABEL = { system: '系统', ai: 'AI', human: '人工' } as const

export function buildWorkflowNodeInsight(
  node: WorkflowNode,
  index: number,
  ctx: {
    ontology: OntologyMapping | null
    ontologyStats: { entity_count: number; published_rule_count: number } | null
    rules: AdminRuleConfig[]
    llmConfig: LlmConfig | null
    skillName: (code?: string) => string | undefined
    configLabel?: string
  },
): WorkflowNodeInsight {
  const code = node.skill_code || node.skill || ''
  const tpl = templateForNodeId(node.id)
  const role = tpl?.role || (node.id === 'ai_explain' ? 'ai' : node.id === 'review' ? 'human' : 'system')
  const enabled = node.enabled !== false
  const lines: string[] = []
  const pills: string[] = []

  pills.push(enabled ? '已启用' : '已停用')
  if (['import', 'ontology', 'mapping', 'detect'].includes(node.id)) pills.push('核心')
  if (role === 'ai') pills.push('大模型')
  if (role === 'human') pills.push('人工')

  lines.push(`第 ${index + 1} 步`)

  const ont = ctx.ontology
  const dsCount = ont?.data_sources?.length ?? 0
  const mappingCount = ont?.field_mappings?.length ?? 0
  const enabledRules = ctx.rules.filter((r) => r.enabled).length

  switch (node.id) {
    case 'import':
      lines.push(`数据源 ${dsCount} 个`)
      lines.push('业务侧 + 财务侧接入')
      break
    case 'ontology':
      if (ctx.ontologyStats) {
        lines.push(`${ctx.ontologyStats.entity_count} 实体 · ${ctx.ontologyStats.published_rule_count} 已发布规则`)
      }
      lines.push('先建语义模型，再供映射挂接')
      break
    case 'mapping':
      lines.push(`字段映射 ${mappingCount} 条`)
      lines.push('物理列挂接实体 · 生成匹配键')
      break
    case 'detect':
      lines.push(`检测规则 ${enabledRules} 条启用`)
      if ((node.rule_bindings?.length ?? 0) > 0) {
        lines.push(`Workflow 绑定 ${node.rule_bindings!.length} 条`)
      }
      break
    case 'ai_explain':
      if (ctx.llmConfig?.runtime_ready) {
        lines.push(`模型 · ${ctx.llmConfig.effective_mode || '已就绪'}`)
      } else if (ctx.llmConfig?.use_mock) {
        lines.push('当前 · 模拟模式')
      } else {
        lines.push('待配置 API Key')
      }
      lines.push('仅解释异常，不参与算差异')
      break
    case 'review':
      lines.push('财务确认 / 退回 / 指派')
      break
    case 'verify':
      lines.push('修正后复跑规则验证')
      break
    case 'report':
      lines.push('生成 PDF 核对报告')
      break
    default:
      if (tpl?.description) lines.push(tpl.description)
  }

  const bindingNames = (node.rule_bindings || []).slice(0, 3).map((r) => r.name)

  return {
    roleLabel: ROLE_LABEL[role],
    skillLabel: ctx.skillName(code) || code || '—',
    skillType: code,
    desc: tpl?.description || '',
    lines,
    pills,
    bindingRulePills: bindingNames,
    configHint: ctx.configLabel || '打开配置',
  }
}
