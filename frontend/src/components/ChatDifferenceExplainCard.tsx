import { Link } from 'react-router-dom'
import { Typography } from 'antd'
import { CheckCircleFilled } from '@ant-design/icons'
import {
  ConfidenceBar,
  DiffTrustActions,
  EvidenceSourceList,
  SystemVsAiBlock,
} from './TrustDiffUI'
import { reviewDifference } from '../api/client'
import { DiffExplanationProse } from './DiffEvidenceSections'

export type DifferenceExplainCardData = {
  verified?: boolean
  difference_id?: string
  task_id?: string
  task_name?: string
  task_period?: string
  diff_label?: string
  type?: string
  business_key?: string
  business_amount?: number
  finance_amount?: number
  amount_diff?: number
  status?: string
  responsible_party?: string
  related_docs?: string[]
  root_cause?: string
  evidence?: string[]
  suggestion?: string
  model?: string
  confidence?: number
  rule_hits?: Array<Record<string, unknown>>
  workbench_path?: string
  case_refs?: Array<{ id: string; label: string }>
}

function formatAmount(v?: number) {
  if (v == null || Number.isNaN(v)) return '—'
  const prefix = v > 0 ? '+' : ''
  return `${prefix}¥${Number(v).toLocaleString()}`
}

function diffRate(biz?: number, fin?: number, diff?: number) {
  const base = Math.max(Math.abs(biz ?? 0), Math.abs(fin ?? 0), 1)
  const d = Math.abs(diff ?? 0)
  return `${((d / base) * 100).toFixed(1)}%`
}

/** 与工作台差异详情同源；强调「系统算 / AI 说」分离 */
export function ChatDifferenceExplainCard({
  data,
  onFeedbackDone,
  disabled,
}: {
  data: DifferenceExplainCardData
  onFeedbackDone?: (action: 'confirm' | 'question' | 'correct') => void
  disabled?: boolean
}) {
  const hits = data.rule_hits || []
  const evidence = data.evidence || []
  const path = data.workbench_path || (data.task_id ? `/workbench/reconciliation/tasks/${data.task_id}` : '')
  const aiText = data.root_cause || ''
  const unknown = /信息不足|无法判断|不确定/.test(aiText)
  const systemLines = [
    `差异类型：${data.type || '—'}`,
    `业务键 ${data.business_key || '—'} · 业务 ${data.business_amount?.toLocaleString() ?? '—'} → 财务 ${data.finance_amount?.toLocaleString() ?? '—'}`,
    `差异金额 ${formatAmount(data.amount_diff)}（约 ${diffRate(data.business_amount, data.finance_amount, data.amount_diff)}）`,
    ...hits.slice(0, 3).map((h) => String((h as { message?: string }).message || '')),
  ].filter(Boolean)

  const evidenceItems = [
    ...(data.case_refs || []).map((c) => ({
      label: c.label,
      caseId: c.id,
    })),
    ...evidence.map((line, i) => ({ label: line, href: undefined, key: `ev-${i}` })),
  ]

  return (
    <div className="chat-diff-explain-card chat-diff-trust">
      <div className="chat-diff-explain-card__bar">
        <span className="chat-diff-explain-card__meta">
          {data.task_name ? `${data.task_name} · ${data.task_period || ''}` : '核对任务'}
          {data.diff_label ? ` · ${data.diff_label}` : ''}
        </span>
        {data.verified && (
          <span className="chat-diff-explain-card__verified">
            <CheckCircleFilled /> 规则已校验
          </span>
        )}
      </div>

      <SystemVsAiBlock
        systemLines={systemLines}
        aiText={aiText}
        confidence={data.confidence}
        isUnknown={unknown}
      />

      <section className="chat-diff-explain-card__section">
        <h4 className="chat-diff-explain-card__section-title">依据来源</h4>
        <EvidenceSourceList
          items={evidenceItems.map((it) => ({
            label: it.label,
            caseId: 'caseId' in it ? it.caseId : undefined,
          }))}
          onOpenCase={(id) => {
            window.open(`/admin?tab=cases&caseId=${id}`, '_blank')
          }}
        />
      </section>

      {data.suggestion && (
        <section className="chat-diff-explain-card__section">
          <h4 className="chat-diff-explain-card__section-title">处理建议</h4>
          <DiffExplanationProse explanation="" suggestion={data.suggestion} />
        </section>
      )}

      {unknown && <span className="chat-diff-trust__priority-tag">高优先级</span>}

      {data.difference_id && (
        <DiffTrustActions
          diffId={data.difference_id}
          confidence={data.confidence}
          status={data.status}
          disabled={disabled}
          onConfirm={async () => {
            await reviewDifference(data.difference_id!, 'confirm', '对话内确认 AI 分析')
          }}
          onDone={onFeedbackDone}
        />
      )}

      {path && (
        <Link to={path} className="chat-min-link chat-diff-explain-card__link">
          在工作台查看完整差异详情 →
        </Link>
      )}
    </div>
  )
}
