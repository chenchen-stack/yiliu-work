import { Button, Table, Tag, Typography } from 'antd'
import type { BusinessCenter, WorkflowNode } from '../api/client'
import { ensureWorkflowNodes } from '../utils/workflowNodes'

type Props = {
  center: BusinessCenter
  workflowId?: string
  onOpenWorkflow?: () => void
}

function nodeRoleTag(id: string) {
  if (id === 'ai_explain') return <Tag color="orange">AI</Tag>
  if (id === 'review') return <Tag color="purple">人工</Tag>
  return <Tag color="blue">系统</Tag>
}

export function WorkflowSummaryEmbed({ center, workflowId, onOpenWorkflow }: Props) {
  const wf = center.workflow
  const nodes: WorkflowNode[] = ensureWorkflowNodes(wf?.nodes || [])
  const wfLabel = wf?.name || workflowId || 'Workflow'

  return (
    <div className="agent-asset-wf-embed">
      <div className="agent-asset-wf-embed__head">
        <div>
          <Typography.Text strong>{wfLabel}</Typography.Text>
          <Typography.Text type="secondary" className="agent-asset-wf-embed__sub">
            v{wf?.version ?? 1} · {wf?.status === 'published' ? '已发布' : wf?.status || '—'}
            {' · '}{nodes.filter((n) => n.enabled !== false).length}/{nodes.length} 节点启用
          </Typography.Text>
        </div>
        {onOpenWorkflow && (
          <Button size="small" type="primary" ghost onClick={onOpenWorkflow}>
            在流程编排中编辑
          </Button>
        )}
      </div>
      <Table
        size="small"
        pagination={false}
        rowKey="id"
        dataSource={nodes}
        className="agent-asset-wf-embed__table"
        columns={[
          {
            title: '#',
            width: 40,
            render: (_, __, i) => i + 1,
          },
          {
            title: '节点',
            dataIndex: 'label',
            render: (label, row) => (
              <span>
                <strong>{label || row.id}</strong>
                <Typography.Text type="secondary" style={{ marginLeft: 6, fontSize: 11 }}>
                  {row.id}
                </Typography.Text>
              </span>
            ),
          },
          {
            title: '类型',
            width: 72,
            render: (_, row) => nodeRoleTag(row.id),
          },
          {
            title: 'Skill',
            width: 120,
            ellipsis: true,
            render: (_, row) => row.skill_code || row.skill || '—',
          },
          {
            title: '状态',
            width: 64,
            render: (_, row) => (
              <Tag bordered={false} color={row.enabled !== false ? 'success' : 'default'}>
                {row.enabled !== false ? '开' : '关'}
              </Tag>
            ),
          },
        ]}
      />
      <Typography.Paragraph type="secondary" className="agent-asset-wf-embed__hint">
        各节点详细配置（接入、映射、规则、模型等）请在「流程编排」画布中点击节点打开，与 Workflow 节点内嵌配置一致。
      </Typography.Paragraph>
    </div>
  )
}
