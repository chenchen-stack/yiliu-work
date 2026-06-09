import type { ReactNode } from 'react'
import { Table, Tag } from 'antd'
import type {
  AdminRuleConfig,
  BusinessCenter,
  LlmConfig,
  OntologyMapping,
} from '../api/client'
import { AdminLlmHub } from './AdminLlmHub'
import { AdminRuleImportPanel } from './AdminRuleImportPanel'
import { AdminSemanticsPane } from './AdminSemanticsHub'
import type { AdminSkillRow } from './AdminSkillsPage'
import { WorkflowSkillEmbed } from './WorkflowSkillEmbed'
import { resolveWorkflowNodePanel } from '../utils/workflowNodeConfig'

type Props = {
  nodeId: string
  nodeLabel?: string
  skillCode?: string
  ontology: OntologyMapping | null
  center: BusinessCenter
  rules: AdminRuleConfig[]
  skills: AdminSkillRow[]
  onReload: () => void
  onCreateRuleVersion: () => void
  /** 居中弹层内嵌：去掉外层滚动壳 */
  embedded?: boolean
}

export function WorkflowNodeConfigPanel({
  nodeId,
  nodeLabel,
  skillCode,
  ontology,
  center,
  rules,
  skills,
  onReload,
  onCreateRuleVersion,
  embedded = false,
}: Props) {
  const target = resolveWorkflowNodePanel(nodeId, skillCode, nodeLabel)
  const wrap = (child: ReactNode) => (
    embedded ? <div className="wf-node-panel__embed">{child}</div> : (
      <div className="wf-node-panel__scroll">{child}</div>
    )
  )

  if (target.kind === 'semantics') {
    if (!ontology || !target.semSub) {
      return <p className="wf-node-panel__empty">语义配置加载中…</p>
    }
    return wrap(
      <AdminSemanticsPane sub={target.semSub} ontology={ontology} onSaved={onReload} />,
    )
  }

  if (target.kind === 'rules') {
    return wrap(
      <>
        <AdminRuleImportPanel
          ruleVersionId={center.rule_version_id}
          businessCenterId={center.id}
          versionLabel={center.rule_version_id?.slice(0, 8)}
          onCreateVersion={onCreateRuleVersion}
          onApplied={onReload}
        />
        <Table
          className="admin-rules-table wf-node-panel__rules-table"
          dataSource={rules}
          rowKey="id"
          pagination={false}
          size="small"
          style={{ marginTop: 12 }}
          columns={[
            { title: '规则', dataIndex: 'name', ellipsis: true },
            { title: '类型', dataIndex: 'rule_type', width: 100 },
            {
              title: '状态',
              width: 72,
              render: (_, r) => (
                <Tag color={r.enabled ? 'success' : 'default'} bordered={false}>
                  {r.enabled ? '启用' : '停用'}
                </Tag>
              ),
            },
          ]}
        />
      </>,
    )
  }

  if (target.kind === 'llm') {
    return wrap(<div className="wf-node-panel__llm"><AdminLlmHub onSaved={onReload} /></div>)
  }

  const code = target.skillCode || skillCode || ''
  return wrap(
    <WorkflowSkillEmbed skillCode={code} skills={skills} nodeLabel={nodeLabel} />,
  )
}
