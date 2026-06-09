import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Tag, Tooltip, Steps, Table, Empty, Space, Typography, Button } from 'antd'
import {
  RobotOutlined, SafetyCertificateOutlined, ApiOutlined,
  ThunderboltOutlined, NodeIndexOutlined, FileSearchOutlined,
  CheckOutlined, LoadingOutlined, CloseOutlined, UserOutlined,
} from '@ant-design/icons'
import type { AuditLog, SkillInvocation } from '../api/client'

export type WorkflowRunRow = {
  id?: string
  node_id?: string
  node_label?: string
  status?: string
  detail?: Record<string, unknown> | null
  created_at?: string
}

const TASK_STAGES = [
  { key: 'running', title: '数据导入/规则执行' },
  { key: 'pending_review', title: '待复核' },
  { key: 'processing', title: '处理中' },
  { key: 'pending_verification', title: '待验证' },
  { key: 'reporting', title: '报告输出' },
  { key: 'closed', title: '已关闭' },
]

const STAGE_ORDER: Record<string, number> = {
  draft: 0, running: 0, pending_review: 1, processing: 2,
  pending_verification: 3, reporting: 4, closed: 5, failed: 0,
}

export function TaskStageStepper({ status }: { status: string }) {
  const current = STAGE_ORDER[status] ?? 0
  return (
    <Steps
      size="small"
      current={current}
      status={status === 'failed' ? 'error' : current >= 5 ? 'finish' : 'process'}
      items={TASK_STAGES.map((s) => ({ title: s.title }))}
    />
  )
}

/** 与后端 WORKFLOW_NODES 对齐的自动化 + 人工流程节点（工作台 / 对话流程说明共用） */
export const EXECUTION_PIPELINE = [
  { id: 'import', label: '加载数据' },
  { id: 'ontology', label: '实体与规则' },
  { id: 'mapping', label: '字段映射' },
  { id: 'detect', label: '差异识别' },
  { id: 'ai_explain', label: '异常解释' },
  { id: 'review', label: '复核流转' },
  { id: 'verify', label: '再次验证' },
  { id: 'report', label: '报告生成' },
] as const

const AUTO_PIPELINE_END_IDX = EXECUTION_PIPELINE.findIndex((n) => n.id === 'ai_explain')
const REVIEW_PIPELINE_IDX = EXECUTION_PIPELINE.findIndex((n) => n.id === 'review')
const VERIFY_PIPELINE_IDX = EXECUTION_PIPELINE.findIndex((n) => n.id === 'verify')
const REPORT_PIPELINE_IDX = EXECUTION_PIPELINE.findIndex((n) => n.id === 'report')

const TASK_STATUS_RANK: Record<string, number> = {
  draft: 0, running: 1, failed: 1,
  pending_review: 4, processing: 4,
  pending_verification: 5, reporting: 6, closed: 7,
}

const MANUAL_STEP_HINT: Record<string, Partial<Record<string, string>>> = {
  review: {
    pending_review: '等待人工复核差异',
    processing: '差异处理中',
  },
  verify: {
    pending_verification: '等待执行再次验证',
  },
  report: {
    reporting: '可生成 PDF 报告',
    closed: '报告已输出，任务已关闭',
  },
}

export type WorkflowStepItem = {
  title: string
  description?: string
  descriptionLines?: string[]
  status?: 'wait' | 'process' | 'finish' | 'error'
  /** 流程角色标记：用于极简条展示系统 / AI / 人工节点 */
  role?: 'system' | 'ai' | 'human'
}

type StepItem = WorkflowStepItem

function buildExecutionSteps(
  taskStatus: string,
  runs: WorkflowRunRow[],
  invocations: SkillInvocation[],
  summary?: Record<string, unknown>,
  diffCount = 0,
): { items: StepItem[]; current: number; headline: string } {
  const runByNode = new Map<string, WorkflowRunRow>()
  for (const r of dedupeWorkflowRuns(runs)) {
    if (r.node_id) runByNode.set(r.node_id, r)
  }
  const invByNode = new Map<string, SkillInvocation>()
  for (const inv of invocations) invByNode.set(inv.node_code, inv)

  const rank = TASK_STATUS_RANK[taskStatus] ?? 0
  const hasReport = !!summary?.report_path
  let activeIdx = 0
  let failedIdx = -1

  const items: StepItem[] = EXECUTION_PIPELINE.map((node, idx) => {
    const run = runByNode.get(node.id)
    const inv = invByNode.get(node.id)
    const descParts: string[] = []

    if (run?.detail && Object.keys(run.detail).length) {
      descParts.push(...summarizeRunDetail(run.detail))
    } else if (inv?.output_summary && Object.keys(inv.output_summary).length) {
      descParts.push(...summarizeRunDetail(inv.output_summary))
    } else if (inv?.input_summary && Object.keys(inv.input_summary).length && node.id === 'detect') {
      descParts.push(...summarizeRunDetail(inv.input_summary))
    }

    const hint = MANUAL_STEP_HINT[node.id]?.[taskStatus]
    if (hint) descParts.push(hint)

    let status: StepItem['status'] = 'wait'

    if (run?.status === 'failed' || inv?.status === 'failed') {
      status = 'error'
      failedIdx = idx
    } else if (run?.status === 'running') {
      status = 'process'
      activeIdx = idx
    } else if (run?.status === 'waiting' && rank <= idx) {
      status = 'process'
      activeIdx = idx
    } else if (run?.status === 'completed') {
      status = 'finish'
    } else if (taskStatus === 'failed' && idx <= AUTO_PIPELINE_END_IDX && !run) {
      status = idx === activeIdx ? 'error' : 'wait'
    } else if (taskStatus === 'closed') {
      status = 'finish'
    } else if (idx <= AUTO_PIPELINE_END_IDX && rank >= REVIEW_PIPELINE_IDX) {
      status = 'finish'
    } else if (idx === REVIEW_PIPELINE_IDX && rank >= VERIFY_PIPELINE_IDX) {
      status = 'finish'
    } else if (idx === VERIFY_PIPELINE_IDX && rank >= REPORT_PIPELINE_IDX) {
      status = 'finish'
    } else if (idx === REPORT_PIPELINE_IDX && (taskStatus === 'closed' || hasReport)) {
      status = 'finish'
    } else if (taskStatus === 'running' && idx <= AUTO_PIPELINE_END_IDX) {
      const autoIds = EXECUTION_PIPELINE.slice(0, AUTO_PIPELINE_END_IDX + 1).map((n) => n.id)
      const firstOpen = autoIds.findIndex((id) => {
        const r = runByNode.get(id)
        return !r || r.status !== 'completed'
      })
      if (firstOpen === idx) {
        status = run?.status === 'completed' ? 'finish' : 'process'
        activeIdx = idx
      } else if (firstOpen > idx || firstOpen === -1) {
        status = 'finish'
      }
    } else if (
      (taskStatus === 'pending_review' || taskStatus === 'processing') && idx === REVIEW_PIPELINE_IDX
    ) {
      status = 'process'
      activeIdx = idx
    } else if (taskStatus === 'pending_verification' && idx === VERIFY_PIPELINE_IDX) {
      status = 'process'
      activeIdx = idx
    } else if (taskStatus === 'reporting' && idx === REPORT_PIPELINE_IDX && !hasReport) {
      status = 'process'
      activeIdx = idx
    }

    if (status === 'process') activeIdx = idx
    if (status === 'error') failedIdx = idx

    return {
      title: node.label,
      descriptionLines: descParts.filter(Boolean),
      description: descParts.filter(Boolean).join(' · ') || undefined,
      status,
    }
  })

  if (taskStatus === 'closed') activeIdx = EXECUTION_PIPELINE.length - 1
  else if (failedIdx >= 0) activeIdx = failedIdx
  else {
    const processingIdx = items.findIndex((it) => it.status === 'process')
    if (processingIdx >= 0) activeIdx = processingIdx
    else {
      const lastFinish = items.reduce((acc, it, i) => (it.status === 'finish' ? i : acc), -1)
      activeIdx = Math.min(lastFinish + 1, EXECUTION_PIPELINE.length - 1)
    }
  }

  const active = items[activeIdx]
  const activeNodeId = EXECUTION_PIPELINE[activeIdx]?.id
  const manualStep = activeNodeId === 'review' || activeNodeId === 'verify' || activeNodeId === 'report'

  let headline = '流程执行'
  if (taskStatus === 'closed') headline = '流程已完成'
  else if (taskStatus === 'failed') headline = '执行失败'
  else if (taskStatus === 'reporting' && summary?.report_path) headline = '报告已生成，可下载或关闭任务'
  else if (taskStatus === 'reporting' && summary?.zero_diff_auto_pass) headline = '核对通过，正在生成报告…'
  else if (taskStatus === 'pending_review' && diffCount === 0) headline = '自动化已完成 · 继续 Workflow'
  else if (taskStatus === 'pending_review' && activeNodeId === 'review') headline = '等待人工复核'
  else if (taskStatus === 'processing' && activeNodeId === 'review') headline = '差异处理中'
  else if (taskStatus === 'pending_verification' && activeNodeId === 'verify') headline = '等待再次验证'
  else if (taskStatus === 'reporting' && activeNodeId === 'report') headline = '等待生成报告'
  else if (active?.status === 'process' && taskStatus === 'running' && !manualStep) {
    headline = `正在执行：${active.title}`
  } else if (active?.status === 'process' && manualStep) headline = `当前阶段：${active.title}`
  else if (active?.status === 'process') headline = `正在执行：${active.title}`
  else if (active?.title) headline = `当前阶段：${active.title}`

  return { items, current: activeIdx, headline }
}

type StatusNotice = {
  tone: 'neutral' | 'info' | 'success' | 'warning'
  message: string
  action?: ReactNode
}

function resolveStatusNotice(
  status: string,
  diffCount: number,
  summary?: Record<string, unknown>,
  reportAction?: ReactNode,
  downloadAction?: ReactNode,
): StatusNotice | null {
  if (status === 'pending_review' && diffCount === 0) {
    return {
      tone: 'info',
      message: '未识别到差异，系统将自动跳过复核与验证，并生成 PDF 报告。',
    }
  }
  // pending_review 且有差异时：说明改由任务详情页状态 Tag 悬停展示，避免重复占行
  if (status === 'pending_review' && diffCount > 0) {
    return null
  }
  if (status === 'reporting' && summary?.report_path) {
    return {
      tone: 'success',
      message: 'PDF 报告已生成。',
      action: downloadAction,
    }
  }
  if (status === 'reporting' && summary?.report_error) {
    return {
      tone: 'warning',
      message: `报告生成失败：${summary.report_error}。请手动重试。`,
      action: reportAction,
    }
  }
  if (status === 'reporting' && diffCount === 0 && summary?.zero_diff_auto_pass) {
    return {
      tone: 'success',
      message: 'Workflow 已自动完成复核与验证，正在生成 PDF 报告…',
    }
  }
  if (status === 'reporting') {
    return {
      tone: 'info',
      message: '请生成 PDF 报告后继续关闭任务。',
      action: reportAction,
    }
  }
  return null
}

function resolveCardTone(
  status: string,
  notice: StatusNotice | null,
  live: boolean,
): string {
  if (status === 'failed') return 'error'
  if (notice?.tone === 'success') return 'success'
  if (notice?.tone === 'warning') return 'warning'
  if (live || notice?.tone === 'info') return 'active'
  if (status === 'closed') return 'done'
  return 'default'
}

type TaskExecutionPanelProps = {
  status: string
  progress: number
  summary?: Record<string, unknown>
  runs: WorkflowRunRow[]
  invocations: SkillInvocation[]
  live?: boolean
  diffCount?: number
  onGenerateReport?: () => void
  showReportAction?: boolean
  reportGenerating?: boolean
  hasReport?: boolean
  onDownloadReport?: () => void
}

function useAnimatedNumber(target: number, duration = 520) {
  const [display, setDisplay] = useState(target)
  const fromRef = useRef(target)
  const rafRef = useRef<number>()

  useEffect(() => {
    const from = fromRef.current
    const to = target
    if (from === to) return

    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - (1 - t) ** 3
      setDisplay(Math.round(from + (to - from) * eased))
      if (t < 1) rafRef.current = requestAnimationFrame(tick)
      else fromRef.current = to
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [target, duration])

  return display
}

/** 横向流程条（与任务详情 TaskExecutionPanel 一致） */
function roleIcon(role?: WorkflowStepItem['role']) {
  if (role === 'ai') return <RobotOutlined />
  if (role === 'human') return <UserOutlined />
  if (role === 'system') return <SafetyCertificateOutlined />
  return null
}

export function WorkflowStepsPipeline({
  items,
  live = false,
  failed = false,
  showRole = false,
}: {
  items: WorkflowStepItem[]
  live?: boolean
  failed?: boolean
  showRole?: boolean
}) {
  return (
    <div className={`task-exec-pipeline${live ? ' task-exec-pipeline--live' : ''}${failed ? ' task-exec-pipeline--failed' : ''}${showRole ? ' task-exec-pipeline--roles' : ''}`}>
      {items.map((item, i) => {
        const st = item.status || 'wait'
        const next = items[i + 1]
        const railDone = st === 'finish'
        const railFlow = railDone && (next?.status === 'process' || next?.status === 'wait')
        const railClass = railDone
          ? (railFlow && live ? 'task-exec-rail--flow' : 'task-exec-rail--done')
          : 'task-exec-rail--idle'
        const roleCls = item.role ? ` task-exec-node--role-${item.role}` : ''

        return (
          <Fragment key={item.title}>
            <div className={`task-exec-node task-exec-node--${st}${roleCls}`}>
              <div className="task-exec-node__ring" aria-hidden />
              <div className="task-exec-node__icon">
                {st === 'finish' && <CheckOutlined />}
                {st === 'process' && (live ? <LoadingOutlined spin /> : <span className="task-exec-node__dot" />)}
                {st === 'error' && <CloseOutlined />}
                {st === 'wait' && (showRole && item.role ? roleIcon(item.role) : <span className="task-exec-node__num">{i + 1}</span>)}
              </div>
              <div className="task-exec-node__title">{item.title}</div>
              {(item.descriptionLines?.length || item.description) && (
                <div className="task-exec-node__desc">
                  {(item.descriptionLines?.length ? item.descriptionLines : [item.description!]).map((line, li) => (
                    <div key={`${line}-${li}`} className="task-exec-node__desc-line">{line}</div>
                  ))}
                </div>
              )}
            </div>
            {i < items.length - 1 && (
              <div className={`task-exec-rail ${railClass}`} aria-hidden>
                <span className="task-exec-rail__flow" />
              </div>
            )}
          </Fragment>
        )
      })}
    </div>
  )
}

/** 任务详情顶部：Workflow 进度 + 状态说明（合一卡片） */
export function TaskExecutionPanel({
  status, progress, summary, runs, invocations, live = false,
  diffCount = 0, onGenerateReport, showReportAction = false,
  reportGenerating = false, hasReport = false, onDownloadReport,
}: TaskExecutionPanelProps) {
  const reportAction = showReportAction && onGenerateReport && !hasReport ? (
    <Button
      type="link"
      size="small"
      className="task-execution-action"
      loading={reportGenerating}
      onClick={onGenerateReport}
    >
      生成报告
    </Button>
  ) : undefined
  const downloadAction = hasReport && onDownloadReport ? (
    <Button type="link" size="small" className="task-execution-action" onClick={onDownloadReport}>
      下载报告
    </Button>
  ) : undefined

  const { items, headline } = buildExecutionSteps(
    status, runs, invocations, summary, diffCount,
  )
  const notice = resolveStatusNotice(status, diffCount, summary, reportAction, downloadAction)
  const cardTone = resolveCardTone(status, notice, live || reportGenerating)
  const dsBiz = summary?.business_datasource_name as string | undefined
  const dsFin = summary?.finance_datasource_name as string | undefined
  const showPulse = live || reportGenerating || (status === 'pending_review' && diffCount === 0)
  const animatedProgress = useAnimatedNumber(progress)
  const prevInvRef = useRef(invocations.length)
  const [invBump, setInvBump] = useState(false)
  const nearlyDone = progress >= 90 && status !== 'closed' && !hasReport

  useEffect(() => {
    if (invocations.length > prevInvRef.current) {
      setInvBump(true)
      const t = window.setTimeout(() => setInvBump(false), 600)
      prevInvRef.current = invocations.length
      return () => window.clearTimeout(t)
    }
    prevInvRef.current = invocations.length
  }, [invocations.length])

  return (
    <div className={`task-execution-card task-execution-card--${cardTone}${live ? ' task-execution-live' : ''}${nearlyDone ? ' task-execution-card--nearly' : ''}`}>
      <div className="task-exec-progress-track" aria-hidden>
        <div
          className="task-exec-progress-fill"
          style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
        />
        {(live || nearlyDone) && <span className="task-exec-progress-shimmer" />}
      </div>
      <div className="task-execution-head">
        <div className="task-execution-head-main">
          <div className="task-execution-title-row">
            {showPulse && <span className="task-execution-pulse" aria-hidden />}
            <Typography.Text className="task-execution-title">{headline}</Typography.Text>
          </div>
          {notice && (
            <p className={`task-execution-notice task-execution-notice--${notice.tone}`}>
              {notice.message}
              {notice.action}
            </p>
          )}
          {dsBiz && dsFin && (
            <Typography.Text type="secondary" className="task-execution-ds">
              {dsBiz} ↔ {dsFin}
            </Typography.Text>
          )}
        </div>
        <div className="task-execution-meta">
          <span className="task-exec-progress-pct">{animatedProgress}%</span>
          {invocations.length > 0 && (
            <span className={`task-exec-inv-badge${invBump ? ' task-exec-inv-badge--bump' : ''}`}>
              <ThunderboltOutlined />
              {invocations.length} 次技能调用
            </span>
          )}
        </div>
      </div>
      <div className="task-execution-body">
        <WorkflowStepsPipeline items={items} live={live || nearlyDone} failed={status === 'failed'} />
        {!runs.length && status === 'running' && (
          <Typography.Text type="secondary" className="task-execution-hint">
            自动化流水线启动中，节点状态将实时更新…
          </Typography.Text>
        )}
      </div>
    </div>
  )
}

/** 解释来源标识：规则引擎 / 大模型 */
export function AiModeBadge({ mode }: { mode?: string }) {
  const m = mode || 'rule-engine'
  const isRule = m.startsWith('rule')
  const isMock = m.startsWith('mock')
  if (isRule) {
    return (
      <Tooltip title="解释由当前检测规则与方太登记表排查要点自动生成，与差异识别规则一致">
        <Tag icon={<SafetyCertificateOutlined />} color="orange">规则引擎解释</Tag>
      </Tooltip>
    )
  }
  if (isMock) {
    return (
      <Tooltip title="历史任务可能仍为旧版话术，请点「重新生成规则解释」刷新">
        <Tag icon={<RobotOutlined />} color="default">待刷新解释</Tag>
      </Tooltip>
    )
  }
  return (
    <Tooltip title="差异事实由规则计算；解释由大模型补充生成">
      <Tag icon={<RobotOutlined />} color="green">大模型解释 · {m}</Tag>
    </Tooltip>
  )
}

export function VersionBadges({
  bcVersion, workflowVersion, ruleVersion, aiMode,
}: { bcVersion?: number; workflowVersion?: number; ruleVersion?: string; aiMode?: string }) {
  return (
    <Space size={4} wrap>
      {bcVersion != null && <Tag icon={<SafetyCertificateOutlined />} color="orange">业务中心 v{bcVersion}</Tag>}
      {workflowVersion != null && <Tag icon={<ApiOutlined />} color="gold">Workflow v{workflowVersion}</Tag>}
      {ruleVersion && <Tag color="volcano">规则 {ruleVersion.length > 10 ? ruleVersion.slice(0, 8) : ruleVersion}</Tag>}
      <AiModeBadge mode={aiMode} />
    </Space>
  )
}

const STATUS_COLOR: Record<string, string> = {
  completed: 'green', failed: 'red', running: 'orange', waiting: 'default',
}

const STATUS_LABEL: Record<string, string> = {
  completed: '已完成', failed: '失败', running: '执行中', waiting: '等待中',
}

const AUDIT_ACTION_LABEL: Record<string, string> = {
  create_task: '创建任务',
  upload_data: '导入数据',
  workflow_step: '流程推进',
  skill_invoke: '技能调用',
  rule_hit: '规则命中',
  review: '人工复核',
  verify: '再次验证',
  generate_report: '生成报告',
  close_task: '关闭任务',
  publish: '发布配置',
  save_field_mappings: '保存字段映射',
}

const AUDIT_OBJECT_LABEL: Record<string, string> = {
  task: '任务',
  difference: '差异项',
  skill_invocation: '技能调用',
  datasource: '数据源',
  mapping_config: '字段映射',
  business_center: '业务中心',
}

function formatJsonSummary(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function formatJsonPretty(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      return value
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** 长文本/JSON 截断展示，hover 查看完整内容 */
export function EllipsisDetail({
  text,
  maxWidth = 300,
  monospace = false,
}: {
  text?: string | null
  maxWidth?: number
  monospace?: boolean
}) {
  if (!text) return <>—</>
  const tooltipBody = monospace ? formatJsonPretty(text) : text
  return (
    <Tooltip
      title={(
        <pre style={{
          margin: 0,
          maxWidth: 520,
          maxHeight: 360,
          overflow: 'auto',
          fontSize: 11,
          lineHeight: 1.5,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
        >
          {tooltipBody}
        </pre>
      )}
      placement="topLeft"
      styles={{ root: { maxWidth: 540 } }}
    >
      <Typography.Text
        ellipsis
        style={{
          fontSize: 12,
          maxWidth,
          display: 'block',
          cursor: 'default',
          fontFamily: monospace ? 'Consolas, monospace' : undefined,
        }}
      >
        {text}
      </Typography.Text>
    </Tooltip>
  )
}

function JsonSummaryCell(props: { value?: Record<string, unknown> | null; maxWidth?: number }) {
  return <SkillSummaryCell {...props} />
}

function summarizeSkillSummary(value?: Record<string, unknown> | null): string {
  if (!value || !Object.keys(value).length) return ''
  const parts = summarizeRunDetail(value)
  if (parts.length) return parts.join(' · ')
  const extras: string[] = []
  if (value.rule_count != null) extras.push(`规则 ${value.rule_count} 条`)
  if (value.rules_applied != null) extras.push(`应用 ${value.rules_applied} 条`)
  if (value.business_profile) extras.push(`业务 ${value.business_profile}`)
  if (value.finance_profile) extras.push(`财务 ${value.finance_profile}`)
  if (value.status) extras.push(String(value.status))
  if (value.promoted != null) extras.push(`推进验证 ${value.promoted} 条`)
  if (value.approved != null) extras.push(value.approved ? '已审批' : '未审批')
  if (extras.length) return extras.join(' · ')
  return formatJsonSummary(value)
}

function SkillSummaryCell({
  value,
  maxWidth = 260,
}: {
  value?: Record<string, unknown> | null
  maxWidth?: number
}) {
  if (!value || !Object.keys(value).length) return <>—</>
  const text = summarizeSkillSummary(value)
  const pretty = formatJsonPretty(value)
  return (
    <Tooltip
      title={(
        <pre style={{
          margin: 0,
          maxWidth: 520,
          maxHeight: 360,
          overflow: 'auto',
          fontSize: 11,
          lineHeight: 1.5,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
        >
          {pretty}
        </pre>
      )}
      placement="topLeft"
      styles={{ root: { maxWidth: 540 } }}
    >
      <Typography.Text
        ellipsis={{ tooltip: false }}
        style={{ fontSize: 12, maxWidth, display: 'block', cursor: 'default' }}
      >
        {text}
      </Typography.Text>
    </Tooltip>
  )
}

export function SkillInvocationList({ data }: { data: SkillInvocation[] }) {
  if (!data.length) return <Empty description="暂无 Skill 调用记录（任务执行后生成）" />
  const hasError = data.some((r) => r.error_message)
  return (
    <Table
      size="small"
      rowKey="id"
      dataSource={data}
      pagination={false}
      scroll={{ x: hasError ? 980 : 860 }}
      className="skill-invocation-table"
      columns={[
        { title: '节点', dataIndex: 'node_label', width: 108, ellipsis: true, render: (v, r) => v || r.node_code },
        {
          title: 'Skill',
          dataIndex: 'skill_code',
          width: 148,
          render: (v, r) => (
            <Space size={4}>
              <Tag color="cyan">{v}</Tag>
              {r.skill_version != null && <span style={{ color: '#94a3b8', fontSize: 12 }}>v{r.skill_version}</span>}
            </Space>
          ),
        },
        { title: 'WF版本', dataIndex: 'workflow_version', width: 76, render: (v) => (v != null ? `v${v}` : '—') },
        {
          title: '状态',
          dataIndex: 'status',
          width: 80,
          render: (s: string) => <Tag color={STATUS_COLOR[s] || 'default'}>{STATUS_LABEL[s] || s}</Tag>,
        },
        {
          title: '输入摘要',
          dataIndex: 'input_summary',
          width: 180,
          render: (o: Record<string, unknown>) => <SkillSummaryCell value={o} maxWidth={168} />,
        },
        {
          title: '输出摘要',
          dataIndex: 'output_summary',
          width: 260,
          render: (o: Record<string, unknown>) => <SkillSummaryCell value={o} maxWidth={248} />,
        },
        ...(hasError ? [{
          title: '错误',
          dataIndex: 'error_message',
          width: 140,
          render: (msg?: string) => (msg ? <EllipsisDetail text={msg} maxWidth={128} /> : '—'),
        }] : []),
        {
          title: '时间',
          dataIndex: 'started_at',
          width: 92,
          fixed: 'right' as const,
          render: (t: string) => new Date(t).toLocaleTimeString('zh-CN'),
        },
      ]}
    />
  )
}

function summarizeRunDetail(detail?: Record<string, unknown> | null): string[] {
  if (!detail) return []
  const parts: string[] = []
  if (detail.message) parts.push(String(detail.message))
  if (detail.business_rows != null) parts.push(`业务 ${detail.business_rows} 行`)
  if (detail.finance_rows != null) parts.push(`财务 ${detail.finance_rows} 行`)
  if (detail.statement_rows != null) parts.push(`流水 ${detail.statement_rows} 行`)
  if (detail.mapped_business_rows != null) parts.push(`映射 ${detail.mapped_business_rows} 行`)
  if (detail.matched_count != null) parts.push(`匹配 ${detail.matched_count} 对`)
  if (detail.count != null) parts.push(`差异 ${detail.count} 条`)
  if (detail.by_type && typeof detail.by_type === 'object') {
    const typed = Object.entries(detail.by_type as Record<string, number>)
      .map(([k, v]) => `${k} ${v}条`)
      .join('、')
    if (typed) parts.push(typed)
  }
  if (detail.explained != null) parts.push(`已解释 ${detail.explained} 条`)
  if (detail.ai_mode) parts.push(String(detail.ai_mode))
  if (detail.rule_count != null) parts.push(`规则 ${detail.rule_count} 条`)
  if (detail.rules_applied != null) parts.push(`应用 ${detail.rules_applied} 条`)
  if (Array.isArray(detail.rule_names) && detail.rule_names.length) {
    const names = (detail.rule_names as string[]).map((n) => n.replace(/^方太·/, '')).join('、')
    parts.push(names)
  }
  if (detail.resolved != null && detail.total != null) parts.push(`解决 ${detail.resolved}/${detail.total}`)
  if (parts.length) return parts
  const raw = formatJsonSummary(detail)
  return raw ? [raw] : []
}

function dedupeWorkflowRuns(runs: WorkflowRunRow[]): WorkflowRunRow[] {
  const order: string[] = []
  const map = new Map<string, WorkflowRunRow>()
  for (const r of runs) {
    const key = String(r.node_id || r.node_label || r.id)
    if (!map.has(key)) order.push(key)
    map.set(key, r)
  }
  return order.map((k) => map.get(k)!)
}

export function WorkflowRunList({ data }: { data: WorkflowRunRow[] }) {
  const rows = dedupeWorkflowRuns(data)
  if (!rows.length) return <Empty description="暂无流程执行记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  return (
    <Table
      size="small"
      rowKey={(r) => String(r.id || r.node_id)}
      dataSource={rows}
      pagination={false}
      tableLayout="fixed"
      columns={[
        { title: '流程节点', dataIndex: 'node_label', width: 140, ellipsis: true },
        {
          title: '状态', dataIndex: 'status', width: 88,
          render: (s: string) => <Tag color={STATUS_COLOR[s] || 'default'}>{STATUS_LABEL[s] || s}</Tag>,
        },
        {
          title: '执行摘要', dataIndex: 'detail',
          render: (d: Record<string, unknown>) => {
            if (!d || !Object.keys(d).length) return '—'
            const summary = summarizeRunDetail(d).join(' · ')
            const hasHeavy = Object.keys(d).length > 3 || Array.isArray(d.unmatched_business)
            if (hasHeavy) {
              return (
                <Tooltip
                  title={(
                    <pre style={{ margin: 0, maxWidth: 520, maxHeight: 360, overflow: 'auto', fontSize: 11, whiteSpace: 'pre-wrap' }}>
                      {formatJsonPretty(d)}
                    </pre>
                  )}
                  placement="topLeft"
                >
                  <Typography.Text ellipsis style={{ maxWidth: 420, fontSize: 12, cursor: 'default' }}>
                    {summary}
                  </Typography.Text>
                </Tooltip>
              )
            }
            return summary
          },
        },
        {
          title: '时间', dataIndex: 'created_at', width: 96,
          render: (t?: string) => (t ? new Date(t).toLocaleTimeString('zh-CN') : '—'),
        },
      ]}
    />
  )
}

export function AuditLogTable({ data }: { data: AuditLog[] }) {
  if (!data.length) return <Empty description="暂无操作日志" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  return (
    <Table
      size="small"
      rowKey="id"
      dataSource={data}
      pagination={{ pageSize: 10, size: 'small', showTotal: (t) => `共 ${t} 条` }}
      tableLayout="fixed"
      columns={[
        {
          title: '时间', dataIndex: 'created_at', width: 168,
          render: (t: string) => new Date(t).toLocaleString('zh-CN'),
        },
        {
          title: '操作', dataIndex: 'action', width: 120,
          render: (a: string) => AUDIT_ACTION_LABEL[a] || a,
        },
        {
          title: '对象', width: 140,
          render: (_: unknown, r: AuditLog) => {
            const label = AUDIT_OBJECT_LABEL[r.object_type] || r.object_type
            return `${label} · ${r.object_id.slice(0, 8)}`
          },
        },
        { title: '操作人', dataIndex: 'operator', width: 100, render: (v?: string) => v || '系统' },
        {
          title: '说明', dataIndex: 'detail',
          render: (d?: Record<string, unknown>) => (d && Object.keys(d).length
            ? <JsonSummaryCell value={d} maxWidth={280} />
            : '—'),
        },
      ]}
    />
  )
}

type AuditTracePanelProps = {
  invocations: SkillInvocation[]
  runs: WorkflowRunRow[]
  logs: AuditLog[]
  showSkills?: boolean
  showWorkflow?: boolean
  showLogs?: boolean
}

export function AuditTracePanel({
  invocations, runs, logs, showSkills = true, showWorkflow = true, showLogs = true,
}: AuditTracePanelProps) {
  const sections = [
    showSkills && {
      key: 'skills',
      icon: <ThunderboltOutlined />,
      title: '自动化技能记录',
      desc: 'Workflow 经 SkillRegistry 调度的各节点执行结果',
      content: <SkillInvocationList data={invocations} />,
    },
    showWorkflow && {
      key: 'workflow',
      icon: <NodeIndexOutlined />,
      title: '流程节点执行',
      desc: '任务从数据导入到复核的各阶段状态',
      content: <WorkflowRunList data={runs} />,
    },
    showLogs && {
      key: 'logs',
      icon: <FileSearchOutlined />,
      title: '操作审计日志',
      desc: '本任务相关的操作与规则命中记录',
      content: <AuditLogTable data={logs} />,
    },
  ].filter(Boolean) as Array<{ key: string; icon: React.ReactNode; title: string; desc: string; content: React.ReactNode }>

  if (!sections.length) {
    return (
      <Empty description="后台未启用任何审计追溯子模块" image={Empty.PRESENTED_IMAGE_SIMPLE}>
        <Typography.Text type="secondary">请在管理后台 → 前台布局 中勾选「自动化技能记录 / 流程节点执行 / 操作审计日志」并发布。</Typography.Text>
      </Empty>
    )
  }

  return (
    <div className="audit-trace-panel">
      {sections.map((s) => (
        <section key={s.key} className="audit-trace-section">
          <div className="audit-trace-section-head">
            <span className="audit-trace-section-icon">{s.icon}</span>
            <div>
              <Typography.Title level={5} style={{ margin: 0 }}>{s.title}</Typography.Title>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>{s.desc}</Typography.Text>
            </div>
          </div>
          <div className="audit-trace-section-body">{s.content}</div>
        </section>
      ))}
    </div>
  )
}

export function PlanningTag() {
  return <Tag color="default">规划中 · 未开放</Tag>
}

export function OpenedTag() {
  return <Tag color="success">已开放</Tag>
}

export function EmptyState({ description, children }: { description: string; children?: React.ReactNode }) {
  return <Empty description={description}>{children}</Empty>
}
