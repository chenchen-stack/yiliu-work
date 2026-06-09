import { useState } from 'react'
import { Button, Input, Modal, Progress, Radio, Space, Typography, message } from 'antd'
import {
  CheckOutlined, CloseOutlined, QuestionCircleOutlined,
  SafetyCertificateOutlined, RobotOutlined, UserOutlined,
} from '@ant-design/icons'
import { submitDiffFeedback } from '../api/client'
import { formatApiError } from '../api/errors'
import { EXECUTION_PIPELINE, WorkflowStepsPipeline, type WorkflowStepItem } from './TrustComponents'

const LOW_CONFIDENCE = 0.6

const REVIEWABLE_STATUSES = new Set(['pending_review', 'identified'])

function isReviewableStatus(status?: string | null): boolean {
  return !status || REVIEWABLE_STATUSES.has(status)
}

const PIPELINE_ROLE: Record<string, 'system' | 'ai' | 'human'> = {
  import: 'system',
  mapping: 'system',
  ontology: 'system',
  detect: 'system',
  ai_explain: 'ai',
  review: 'human',
  verify: 'system',
  report: 'system',
}

/** 仅展示流程角色：系统 / 人 / AI，无说明文案 */
export function ProductHardLineBanner({ compact = false }: { compact?: boolean }) {
  const items: WorkflowStepItem[] = EXECUTION_PIPELINE.map((n) => ({
    title: n.label,
    status: 'wait' as const,
    role: PIPELINE_ROLE[n.id] || 'system',
  }))

  return (
    <div className={`execution-role-strip${compact ? ' execution-role-strip--compact' : ''}`}>
      <WorkflowStepsPipeline items={items} showRole />
    </div>
  )
}

export function ConfidenceBar({
  value,
  showLabel = true,
}: {
  value?: number | null
  showLabel?: boolean
}) {
  const pct = value == null ? 0 : Math.round(Math.max(0, Math.min(1, value)) * 100)
  const low = pct < LOW_CONFIDENCE * 100
  const unknown = (value ?? 0) <= 0.01 && !low
  const stroke = unknown ? '#94a3b8' : low ? '#f59e0b' : '#10b981'
  return (
    <div className={`trust-confidence${low ? ' trust-confidence--low' : ''}${unknown ? ' trust-confidence--unknown' : ''}`}>
      {showLabel && (
        <div className="trust-confidence__label">
          <span>置信度</span>
          <span>{unknown ? '信息不足' : `${pct}%`}</span>
        </div>
      )}
      <Progress
        percent={unknown ? 8 : pct}
        showInfo={false}
        strokeColor={stroke}
        trailColor="#e2e8f0"
        size="small"
      />
    </div>
  )
}

export function SystemVsAiBlock({
  systemTitle = '系统',
  systemLines,
  aiTitle = 'AI',
  aiText,
  confidence,
  isUnknown,
}: {
  systemTitle?: string
  systemLines: string[]
  aiTitle?: string
  aiText?: string | null
  confidence?: number | null
  isUnknown?: boolean
}) {
  const unknown = isUnknown || /信息不足|无法判断|不确定/.test(aiText || '')
  return (
    <div className="trust-split">
      <section className="trust-split__system">
        <div className="trust-split__badge trust-split__badge--system">
          <SafetyCertificateOutlined /> {systemTitle}
        </div>
        <ul className="trust-split__lines">
          {systemLines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>
      <section className={`trust-split__ai${unknown ? ' trust-split__ai--unknown' : ''}`}>
        <div className="trust-split__badge trust-split__badge--ai">
          <RobotOutlined /> {aiTitle}
        </div>
        {unknown ? (
          <span className="trust-split__unknown-tag">信息不足</span>
        ) : (
          <p className="trust-split__ai-text">{aiText || '—'}</p>
        )}
        <ConfidenceBar value={confidence} />
      </section>
    </div>
  )
}

export function EvidenceSourceList({
  items,
  onOpenCase,
}: {
  items: Array<{ label: string; href?: string; caseId?: string }>
  onOpenCase?: (caseId: string) => void
}) {
  if (!items.length) return <span className="trust-evidence-list--empty">—</span>
  return (
    <ul className="trust-evidence-list">
      {items.map((it) => (
        <li key={it.label}>
          {it.caseId && onOpenCase ? (
            <button type="button" className="trust-evidence-list__link" onClick={() => onOpenCase(it.caseId!)}>
              {it.label}
            </button>
          ) : it.href ? (
            <a href={it.href} className="trust-evidence-list__link">{it.label}</a>
          ) : (
            it.label
          )}
        </li>
      ))}
    </ul>
  )
}

const QUESTION_OPTIONS = [
  { value: 'fee', label: '手续费' },
  { value: 'fx', label: '汇率差异' },
  { value: 'data_entry', label: '数据录入错误' },
  { value: 'timing', label: '系统时间差' },
  { value: 'other', label: '其他' },
]

export function DiffTrustActions({
  diffId,
  confidence,
  status,
  onConfirm,
  onDone,
  disabled,
}: {
  diffId: string
  confidence?: number | null
  status?: string | null
  onConfirm: () => Promise<void>
  onDone?: (action: 'confirm' | 'question' | 'correct') => void
  disabled?: boolean
}) {
  const [loading, setLoading] = useState<string | null>(null)
  const [qOpen, setQOpen] = useState(false)
  const [cOpen, setCOpen] = useState(false)
  const [qCat, setQCat] = useState('fee')
  const [qText, setQText] = useState('')
  const [corrected, setCorrected] = useState('')

  const low = (confidence ?? 1) < LOW_CONFIDENCE
  const confirmLabel = low ? '建议人工核实' : '确认 AI 分析'
  const reviewable = isReviewableStatus(status)
  const actionDisabled = disabled || !!loading || !reviewable

  const run = async (action: 'confirm' | 'question' | 'correct', fn: () => Promise<void>) => {
    if (!reviewable) {
      message.warning('当前差异状态不可复核，请在工作台任务详情中操作')
      return
    }
    setLoading(action)
    try {
      await fn()
      if (action === 'confirm') message.success('已确认 AI 分析')
      onDone?.(action)
    } catch (e: unknown) {
      message.error(formatApiError(e, '操作失败，请重试'))
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="trust-actions">
      {!reviewable && (
        <Typography.Text type="secondary" className="trust-actions__hint">
          该差异已处置，无法再次确认/质疑/修正；可前往工作台查看详情。
        </Typography.Text>
      )}
      <Space wrap>
        <Button
          type="primary"
          icon={<CheckOutlined />}
          loading={loading === 'confirm'}
          disabled={actionDisabled}
          onClick={() => run('confirm', onConfirm)}
        >
          {confirmLabel}
        </Button>
        <Button
          icon={<QuestionCircleOutlined />}
          disabled={actionDisabled}
          onClick={() => setQOpen(true)}
        >
          质疑
        </Button>
        <Button
          icon={<CloseOutlined />}
          disabled={actionDisabled}
          onClick={() => setCOpen(true)}
        >
          修正
        </Button>
      </Space>

      <Modal
        title="质疑 AI 归因"
        open={qOpen}
        getContainer={() => document.body}
        zIndex={2000}
        destroyOnClose
        onCancel={() => setQOpen(false)}
        confirmLoading={loading === 'question'}
        onOk={async () => {
          await run('question', async () => {
            await submitDiffFeedback(diffId, {
              action: 'question',
              reason_category: qCat,
              reason_text: qText,
            })
            setQOpen(false)
            setQText('')
            message.success('已提交质疑，差异回到待复核')
          })
        }}
        okText="提交质疑并回到待排查"
      >
        <Typography.Paragraph type="secondary">
          差异将回到待复核，系统会记录您的判断供下次分析参考。
        </Typography.Paragraph>
        <Radio.Group value={qCat} onChange={(e) => setQCat(e.target.value)} style={{ marginBottom: 12 }}>
          <Space direction="vertical">
            {QUESTION_OPTIONS.map((o) => (
              <Radio key={o.value} value={o.value}>{o.label}</Radio>
            ))}
          </Space>
        </Radio.Group>
        <Input.TextArea
          rows={3}
          placeholder="补充说明（选填）"
          value={qText}
          onChange={(e) => setQText(e.target.value)}
        />
      </Modal>

      <Modal
        title="修正 AI 归因"
        open={cOpen}
        getContainer={() => document.body}
        zIndex={2000}
        destroyOnClose
        onCancel={() => setCOpen(false)}
        confirmLoading={loading === 'correct'}
        onOk={async () => {
          await run('correct', async () => {
            await submitDiffFeedback(diffId, {
              action: 'correct',
              corrected_cause: corrected,
            })
            setCOpen(false)
            setCorrected('')
            message.success('已保存修正归因')
          })
        }}
        okText="保存修正"
        okButtonProps={{ disabled: !corrected.trim() }}
      >
        <Typography.Paragraph type="secondary">
          修正记录可作为领域规则草稿，由管理员在「数据语义 → 实体与规则」中审核发布。
        </Typography.Paragraph>
        <Input.TextArea
          rows={4}
          placeholder="您认为正确的差异原因，如：汇率差异导致尾差"
          value={corrected}
          onChange={(e) => setCorrected(e.target.value)}
        />
      </Modal>
    </div>
  )
}

export type ReconciliationSummaryMetric = {
  label: string
  value: string | number
  tone?: 'default' | 'ok' | 'warn' | 'accent'
}

export function ReconciliationSystemSummary({
  businessRows,
  financeRows,
  diffCount,
  matchedEstimate,
  extraMetrics = [],
  title = '对账摘要',
}: {
  businessRows?: number
  financeRows?: number
  diffCount: number
  matchedEstimate?: number
  /** 与主指标合并展示（如影响金额、分类型统计） */
  extraMetrics?: ReconciliationSummaryMetric[]
  title?: string
}) {
  const biz = businessRows ?? 0
  const fin = financeRows ?? 0
  const total = Math.max(biz, fin, diffCount)
  const matched = matchedEstimate ?? Math.max(0, total - diffCount)

  const metrics: ReconciliationSummaryMetric[] = [
    { label: '匹配', value: matched.toLocaleString(), tone: 'ok' },
    { label: '差异', value: diffCount, tone: 'warn' },
  ]
  if (biz > 0) metrics.push({ label: '业务行', value: biz })
  if (fin > 0) metrics.push({ label: '财务行', value: fin })
  for (const m of extraMetrics) metrics.push(m)

  return (
    <div className="trust-system-summary">
      <div className="trust-system-summary__head">
        <SafetyCertificateOutlined className="trust-system-summary__icon" aria-hidden />
        <span className="trust-system-summary__title">{title}</span>
      </div>
      <div className="trust-system-summary__grid">
        {metrics.map((m) => (
          <div
            key={m.label}
            className={`trust-system-summary__cell${m.tone ? ` trust-system-summary__cell--${m.tone}` : ''}`}
          >
            <span className="trust-system-summary__val">{m.value}</span>
            <span className="trust-system-summary__lbl">{m.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
