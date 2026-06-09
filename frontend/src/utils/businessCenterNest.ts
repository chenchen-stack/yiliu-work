import type { AgentConfigItem, AdminRuleConfig, BusinessCenter, OntologyMapping, WorkflowNode } from '../api/client'
import type { SemanticsSubTab } from '../components/AdminSemanticsHub'
import { ensureWorkflowNodes } from './workflowNodes'
import { resolveWorkflowNodePanel } from './workflowNodeConfig'

export type BcNestAction =
  | { type: 'workflow_node'; nodeId: string }
  | { type: 'asset'; assetKey: string }
  | { type: 'navigate'; tab: string; semSub?: SemanticsSubTab; skill?: string }

/** 业务中心嵌套表格行 */
export type BcTreeRow = {
  key: string
  name: string
  type: string
  status?: string
  remark?: string
  action?: BcNestAction
  children?: BcTreeRow[]
}

function row(
  key: string,
  name: string,
  type: string,
  opts: Partial<Omit<BcTreeRow, 'key' | 'name' | 'type'>> = {},
): BcTreeRow {
  return { key, name, type, ...opts }
}

const MODULE_LABELS: Record<string, string> = {
  today_summary: '今日概览',
  create_task: '新建任务',
  task_batches: '任务批次',
  difference_handling: '差异处理',
  pending_review: '待复核',
  processing_progress: '处理进度',
  re_verification: '再次验证',
  reconciliation_report: '报告输出',
  audit_trace: '审计追溯',
  audit_trace_skills: '技能记录',
  audit_trace_workflow: '流程节点',
  audit_trace_logs: '操作日志',
}

/** 构建业务中心嵌套表格数据（单层根 → 可无限展开 children） */
export function buildBusinessCenterTree(
  center: BusinessCenter,
  ontology: OntologyMapping | null,
  rules: AdminRuleConfig[],
  agents: AgentConfigItem[],
): BcTreeRow[] {
  const wf = center.workflow
  const wfNodes = ensureWorkflowNodes((wf?.nodes || []) as WorkflowNode[])
  const enabledRules = rules.filter((r) => r.enabled !== false)
  const dsList = ontology?.data_sources ?? []
  const entities = ontology?.object_types ?? []
  const mappings = ontology?.field_mappings ?? []
  const linkedAgents = agents.filter(
    (a) => a.linked_workflow_id === center.workflow_id || a.linked_workflow_id === wf?.id,
  )

  const dataAccessChildren: BcTreeRow[] = dsList.map((ds) =>
    row(`ds-${ds.id}`, ds.name, '数据源', {
      status: ds.status === 'connected' ? '已连接' : ds.status || '—',
      remark: `${ds.system_type || ''} · ${ds.connector || ''}`.trim(),
      action: { type: 'asset', assetKey: 'bc-sem-datasources' },
    }),
  )

  const entityChildren: BcTreeRow[] = entities.map((e, i) =>
    row(`ent-${i}`, e.ontology_object || e.source, '实体', {
      remark: (e.identifier_fields || []).join(' · ') || e.source,
      action: { type: 'asset', assetKey: 'bc-sem-entities' },
    }),
  )

  const mappingChildren: BcTreeRow[] = mappings.slice(0, 20).map((m, i) =>
    row(`map-${i}`, m.unified_label || m.unified_field, '映射字段', {
      remark: `SAP ${m.sap_field || '—'} ↔ ${m.bank_field || '—'}`,
      action: { type: 'asset', assetKey: 'bc-sem-mapping' },
    }),
  )
  if (mappings.length > 20) {
    mappingChildren.push(
      row('map-more', `… 另有 ${mappings.length - 20} 条`, '映射字段', {
        action: { type: 'asset', assetKey: 'bc-sem-mapping' },
      }),
    )
  }

  const ruleChildren: BcTreeRow[] = rules.map((r) =>
    row(`rule-${r.id}`, r.name, '检测规则', {
      status: r.enabled !== false ? '启用' : '停用',
      remark: r.rule_type || r.severity || '',
      action: { type: 'asset', assetKey: 'bc-rules' },
    }),
  )

  const wfNodeRows: BcTreeRow[] = wfNodes.map((n, i) => {
    const panel = resolveWorkflowNodePanel(n.id, n.skill_code || n.skill, n.label)
    const skillCode = n.skill_code || n.skill
    const children: BcTreeRow[] = skillCode
      ? [row(`wf-skill-${n.id}`, skillCode, 'Skill', {
          remark: panel.subtitle,
          action: { type: 'navigate', tab: 'skills', skill: skillCode },
        })]
      : []
    return row(`wf-${n.id}`, n.label || n.id, '流程节点', {
      status: n.enabled !== false ? `步骤 ${i + 1}` : '已禁用',
      remark: panel.subtitle,
      action: { type: 'workflow_node', nodeId: n.id },
      children: children.length ? children : undefined,
    })
  })

  const agentRows: BcTreeRow[] = linkedAgents.length
    ? linkedAgents.map((a) =>
        row(`agent-${a.id}`, a.name, 'Agent', {
          status: a.status === 'published' ? '已发布' : a.status || '—',
          remark: '对话探索 · 挂载本 Workflow',
          action: { type: 'navigate', tab: 'agents' },
        }),
      )
    : [row('agent-empty', 'Agent 管理', 'Agent', {
        remark: '挂载本 Workflow 的对话助手',
        action: { type: 'navigate', tab: 'agents' },
      })]

  const modules = center.page_modules || []
  const moduleRows: BcTreeRow[] = modules.map((key) =>
    row(`mod-${key}`, MODULE_LABELS[key] || key, '前台模块', {
      status: '已启用',
      action: { type: 'navigate', tab: 'modules' },
    }),
  )

  return [
    row('group-assets', '能力资产', '分组', {
      remark: '数据语义 → 规则 → 模型',
      children: [
        row('sem-group', '数据语义', '分组', {
          children: [
            row('sem-ds', '数据接入', '配置项', {
              status: dsList.length ? `${dsList.length} 个数据源` : '待配置',
              action: { type: 'asset', assetKey: 'bc-sem-datasources' },
              children: dataAccessChildren.length ? dataAccessChildren : undefined,
            }),
            row('sem-ent', '实体与规则', '配置项', {
              status: entities.length ? `${entities.length} 个实体` : '待配置',
              action: { type: 'asset', assetKey: 'bc-sem-entities' },
              children: entityChildren.length ? entityChildren : undefined,
            }),
            row('sem-map', '字段映射', '配置项', {
              status: mappings.length ? `${mappings.length} 条映射` : '待配置',
              action: { type: 'asset', assetKey: 'bc-sem-mapping' },
              children: mappingChildren.length ? mappingChildren : undefined,
            }),
            row('sem-graph', '关系图谱', '配置项', {
              status: '图谱视图',
              action: { type: 'asset', assetKey: 'bc-sem-graph' },
            }),
          ],
        }),
        row('rules', '规则引擎', '配置项', {
          status: `v${center.rule_version?.version ?? '—'} · ${enabledRules.length}/${rules.length} 启用`,
          action: { type: 'asset', assetKey: 'bc-rules' },
          children: ruleChildren.length ? ruleChildren : undefined,
        }),
        row('llm', '大模型', '配置项', {
          remark: '异常解释 / Agent 路由',
          action: { type: 'asset', assetKey: 'bc-llm' },
        }),
        row('kb', '知识库', '配置项', {
          remark: '案例与领域知识',
          action: { type: 'asset', assetKey: 'kb-fangtai-cases' },
        }),
      ],
    }),
    row('group-runtime', '运行编排', '分组', {
      remark: 'Workflow · Agent',
      children: [
        row('workflow-root', wf?.name || '收入核对 Workflow', 'Workflow', {
          status: `v${wf?.version ?? 1}`,
          remark: `${wfNodes.length} 个节点`,
          action: { type: 'navigate', tab: 'workflow' },
          children: [...wfNodeRows, ...agentRows],
        }),
      ],
    }),
    row('group-front', '发布与前台', '分组', {
      remark: '发布后工作台生效',
      children: [
        row('modules-all', '前台布局', '布局', {
          status: `${modules.length} 个模块`,
          action: { type: 'navigate', tab: 'modules' },
          children: moduleRows.length ? moduleRows : undefined,
        }),
      ],
    }),
  ]
}

/** @deprecated 使用 buildBusinessCenterTree */
export type BcNestNode = {
  id: string
  label: string
  sub?: string
  tone: 'root' | 'asset' | 'runtime' | 'front' | 'link'
  action?: BcNestAction
  done?: boolean
  badge?: string
}

export type BcNestLayer = {
  id: string
  title: string
  hint: string
  nodes: BcNestNode[]
  chain?: boolean
}

export function buildBusinessCenterLayers(
  center: BusinessCenter,
  ontology: OntologyMapping | null,
  rules: AdminRuleConfig[],
  agents: AgentConfigItem[],
): BcNestLayer[] {
  void center
  void ontology
  void rules
  void agents
  return []
}
