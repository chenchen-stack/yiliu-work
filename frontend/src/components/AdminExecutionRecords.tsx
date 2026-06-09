import { useMemo, useState } from 'react'
import {
  Alert, Button, Descriptions, Empty, Modal, Space, Table, Tag, Timeline, Typography,
} from 'antd'
import { CommentOutlined, NodeIndexOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { AgentConfigItem, AgentRunSummary, SkillInvocation } from '../api/client'
import { getAdminAgentRunDetail } from '../api/client'
import { formatApiError } from '../api/errors'

export type ExecutionRecordRow = {
  id: string
  source: 'workflow' | 'agent'
  sortAt: number
  scene: string
  skillOrIntent: string
  wfVersion: string
  status: string
  inputText: string
  outputText: string
  errorMessage?: string
  agentRunId?: string
  taskId?: string
}

const STATUS_LABEL: Record<string, string> = {
  completed: '已完成',
  running: '运行中',
  failed: '失败',
  waiting: '等待中',
}

const INTENT_LABEL: Record<string, string> = {
  dialog: '对话',
  explain_diff: '差异解释',
  query_tasks: '查任务',
  start_reconciliation: '发起核对',
  knowledge: '知识检索',
}

function summarizeAgentOutput(run: AgentRunSummary): string {
  if (run.final_output?.trim()) return run.final_output.trim()
  const steps = run.plan_steps || []
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const obs = steps[i]?.observation?.trim()
    if (obs) return obs
  }
  const skills = run.skills_called || []
  if (skills.length) return `调用：${skills.join('、')}`
  return '—'
}

function summarizeSkillJson(value?: Record<string, unknown> | null): string {
  if (!value || !Object.keys(value).length) return '—'
  const parts: string[] = []
  if (value.message) parts.push(String(value.message))
  if (value.explained != null) parts.push(`已解释 ${value.explained} 条`)
  if (value.ai_mode) parts.push(String(value.ai_mode))
  if (value.mapped_business_rows != null) parts.push(`映射 ${value.mapped_business_rows} 行`)
  if (value.matched_count != null) parts.push(`匹配 ${value.matched_count} 对`)
  if (value.count != null) parts.push(`差异 ${value.count} 条`)
  if (value.rule_count != null) parts.push(`规则 ${value.rule_count} 条`)
  if (value.status) parts.push(String(value.status))
  if (parts.length) return parts.join(' · ')
  try {
    const raw = JSON.stringify(value)
    return raw.length > 120 ? `${raw.slice(0, 117)}…` : raw
  } catch {
    return '—'
  }
}

export function buildExecutionRecords(
  invocations: SkillInvocation[],
  agentRuns: AgentRunSummary[],
  agentNames: Record<string, string>,
): ExecutionRecordRow[] {
  const rows: ExecutionRecordRow[] = []

  for (const inv of invocations) {
    const t = inv.started_at ? new Date(inv.started_at).getTime() : 0
    rows.push({
      id: `wf-${inv.id}`,
      source: 'workflow',
      sortAt: t,
      scene: inv.node_label || inv.node_code,
      skillOrIntent: inv.skill_code,
      wfVersion: inv.workflow_version != null ? `v${inv.workflow_version}` : '—',
      status: inv.status,
      inputText: summarizeSkillJson(inv.input_summary),
      outputText: inv.error_message
        ? `失败：${inv.error_message}`
        : summarizeSkillJson(inv.output_summary),
      errorMessage: inv.error_message,
      taskId: inv.task_id,
    })
  }

  for (const run of agentRuns) {
    const t = run.created_at ? new Date(run.created_at).getTime() : 0
    const agentName = agentNames[run.agent_id] || 'Agent'
    const intentLabel = INTENT_LABEL[run.intent || ''] || run.intent || '对话'
    const skills = (run.skills_called || []).filter(Boolean)
    rows.push({
      id: `ag-${run.id}`,
      source: 'agent',
      sortAt: t,
      scene: run.user_input?.trim() || '—',
      skillOrIntent: skills.length
        ? `${agentName} · ${skills.join('、')}`
        : `${agentName} · ${intentLabel}`,
      wfVersion: '—',
      status: 'completed',
      inputText: run.user_input?.trim() || '—',
      outputText: summarizeAgentOutput(run),
      agentRunId: run.id,
      taskId: undefined,
    })
  }

  return rows.sort((a, b) => b.sortAt - a.sortAt)
}

type Props = {
  invocations: SkillInvocation[]
  agentRuns: AgentRunSummary[]
  agents?: AgentConfigItem[]
}

function EllipsisText({ text, maxWidth = 220 }: { text: string; maxWidth?: number }) {
  return (
    <Typography.Text
      ellipsis={{ tooltip: text }}
      style={{ fontSize: 12, maxWidth, display: 'block' }}
    >
      {text}
    </Typography.Text>
  )
}

export function AdminExecutionRecords({ invocations, agentRuns, agents = [] }: Props) {
  const [replayOpen, setReplayOpen] = useState(false)
  const [replayLoading, setReplayLoading] = useState(false)
  const [runDetail, setRunDetail] = useState<Awaited<ReturnType<typeof getAdminAgentRunDetail>> | null>(null)

  const agentNames = useMemo(() => {
    const m: Record<string, string> = {}
    for (const a of agents) m[a.id] = a.name
    return m
  }, [agents])

  const rows = useMemo(
    () => buildExecutionRecords(invocations, agentRuns, agentNames),
    [invocations, agentRuns, agentNames],
  )

  const wfCount = invocations.length
  const agCount = agentRuns.length

  const openReplay = async (runId: string) => {
    setReplayOpen(true)
    setReplayLoading(true)
    setRunDetail(null)
    try {
      const detail = await getAdminAgentRunDetail(runId)
      setRunDetail(detail)
    } catch (e) {
      setReplayOpen(false)
      Modal.error({ title: '加载失败', content: formatApiError(e) })
    } finally {
      setReplayLoading(false)
    }
  }

  const columns: ColumnsType<ExecutionRecordRow> = [
    {
      title: '来源',
      dataIndex: 'source',
      width: 108,
      render: (src: ExecutionRecordRow['source']) => (
        src === 'workflow' ? (
          <Tag className="exec-rec__tag exec-rec__tag--wf" icon={<NodeIndexOutlined />}>Workflow</Tag>
        ) : (
          <Tag className="exec-rec__tag exec-rec__tag--agent" icon={<CommentOutlined />}>Agent 对话</Tag>
        )
      ),
    },
    {
      title: '场景',
      dataIndex: 'scene',
      width: 200,
      ellipsis: true,
      render: (v: string) => <EllipsisText text={v} maxWidth={188} />,
    },
    {
      title: 'Skill / 意图',
      dataIndex: 'skillOrIntent',
      width: 160,
      ellipsis: true,
      render: (v: string) => <span className="exec-rec__skill">{v}</span>,
    },
    { title: 'WF版本', dataIndex: 'wfVersion', width: 72 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (s: string) => (
        <Tag className={`exec-rec__status exec-rec__status--${s}`}>
          {STATUS_LABEL[s] || s}
        </Tag>
      ),
    },
    {
      title: '输入摘要',
      dataIndex: 'inputText',
      width: 180,
      render: (v: string) => <EllipsisText text={v} maxWidth={168} />,
    },
    {
      title: '输出摘要',
      dataIndex: 'outputText',
      width: 240,
      render: (v: string) => <EllipsisText text={v} maxWidth={228} />,
    },
    {
      title: '时间',
      dataIndex: 'sortAt',
      width: 168,
      render: (t: number) => (t ? new Date(t).toLocaleString('zh-CN') : '—'),
    },
    {
      title: '',
      key: 'action',
      width: 72,
      align: 'right',
      render: (_: unknown, row) => (
        row.source === 'agent' && row.agentRunId ? (
          <Button type="link" size="small" className="exec-rec__link" onClick={() => { void openReplay(row.agentRunId!) }}>
            回放
          </Button>
        ) : null
      ),
    },
  ]

  if (!rows.length) {
    return (
      <Empty
        description="暂无运行记录。Workflow 任务执行或前台 Agent 对话后将在此汇总展示。"
      />
    )
  }

  return (
    <div className="exec-rec">
      <div className="exec-rec__meta">
        <Typography.Text type="secondary">
          共 {rows.length} 条 · Workflow {wfCount} · Agent 对话 {agCount}
        </Typography.Text>
      </div>
      <Table
        className="exec-rec__table"
        size="small"
        rowKey="id"
        dataSource={rows}
        columns={columns}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        scroll={{ x: 1100 }}
      />

      <Modal
        title="Agent 对话回放"
        open={replayOpen}
        onCancel={() => { setReplayOpen(false); setRunDetail(null) }}
        footer={null}
        width={720}
        destroyOnClose
      >
        {replayLoading && <Typography.Text type="secondary">加载中…</Typography.Text>}
        {!replayLoading && runDetail?.run && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Agent">
                {String(runDetail.run.agent_name)} v{String(runDetail.run.agent_version ?? '?')}
              </Descriptions.Item>
              <Descriptions.Item label="意图">{String(runDetail.run.intent || '—')}</Descriptions.Item>
              <Descriptions.Item label="用户输入">{String(runDetail.run.user_input)}</Descriptions.Item>
            </Descriptions>
            <Timeline
              items={((runDetail.run.plan_steps as Array<Record<string, string>>) || []).map((step, i) => ({
                color: step.action ? 'orange' : 'gray',
                children: (
                  <div key={i}>
                    {step.thought && <div><Typography.Text type="secondary">思考</Typography.Text> {step.thought}</div>}
                    {step.action && <div><Typography.Text strong>行动</Typography.Text> {step.action}</div>}
                    {step.observation && <div><Typography.Text type="secondary">观察</Typography.Text> {step.observation}</div>}
                  </div>
                ),
              }))}
            />
            {runDetail.run.final_output && (
              <Alert type="info" showIcon={false} message="回复" description={String(runDetail.run.final_output)} />
            )}
          </Space>
        )}
      </Modal>
    </div>
  )
}
