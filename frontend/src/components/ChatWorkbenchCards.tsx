import { RobotOutlined, FileSearchOutlined } from '@ant-design/icons'
import { Difference, Task } from '../api/client'
import {
  parseAssistantReply, dedupeAssistantContent,
} from '../utils/parseAssistantReply'

function formatExplainParagraphs(text: string): string[] {
  const trimmed = text.trim()
  if (!trimmed) return []
  const parts = trimmed
    .split(/(?<=[。！？])\s*/)
    .map((p) => p.trim())
    .filter(Boolean)
  if (parts.length <= 1 && trimmed.length > 120) {
    return [trimmed]
  }
  return parts.length ? parts : [trimmed]
}

function pickExplainText(diff: Difference, chain: Array<Record<string, unknown>>): string {
  if (diff.ai_explanation?.trim()) return diff.ai_explanation.trim()
  const explainStep = [...chain].reverse().find((s) => {
    const stage = String(s.stage || '')
    const result = String(s.result || '')
    return (stage === 'rule_analysis' || stage === 'ai_analysis') && result.length > 20
  })
  return explainStep ? String(explainStep.result) : ''
}

/** 差异上下文 · 单卡聚合（事实 + 规则 + 证据） */
export function DiffContextCard({
  diff,
  task,
  aiMode,
}: {
  diff: Difference
  task?: Task | null
  aiMode?: string
}) {
  const hits = diff.rule_hits || []
  const chain = diff.evidence_chain || []
  const explainText = pickExplainText(diff, chain)
  const explainParagraphs = formatExplainParagraphs(explainText)

  return (
    <div className="chat-diff-unified">
      <div className="chat-diff-unified__bar">
        <span className="chat-diff-unified__meta">
          {task ? `${task.name} · ${task.period}` : '核对任务'}
        </span>
        <span className="chat-diff-unified__tag">差异事实</span>
      </div>

      <div className="chat-diff-unified__hero">
        <h3 className="chat-diff-unified__title">{diff.type}</h3>
        <p className="chat-diff-unified__subtitle">业务键 {diff.business_key || '—'}</p>
      </div>

      <div className="chat-wb-metrics chat-wb-metrics--unified">
        <div className="chat-wb-metric">
          <span className="label">业务键</span>
          <span className="value">{diff.business_key || '—'}</span>
        </div>
        <div className="chat-wb-metric">
          <span className="label">业务侧</span>
          <span className="value accent">{diff.business_amount?.toLocaleString() ?? '—'}</span>
        </div>
        <div className="chat-wb-metric">
          <span className="label">财务侧</span>
          <span className="value accent">{diff.finance_amount?.toLocaleString() ?? '—'}</span>
        </div>
        <div className="chat-wb-metric highlight">
          <span className="label">差异额</span>
          <span className="value accent">{diff.amount_diff?.toLocaleString() ?? '—'}</span>
        </div>
      </div>

      <div className="chat-wb-card-foot chat-wb-card-foot--unified">
        <span className="chat-wb-pill chat-wb-pill--brand">{diff.type}</span>
        {diff.risk_level && (
          <span className="chat-wb-pill chat-wb-pill--muted">{diff.risk_level}</span>
        )}
        {aiMode && (
          <span className="chat-wb-pill chat-wb-pill--ai" title="差异事实由规则计算；解释由大模型或规则引擎生成">
            <RobotOutlined />
            {String(aiMode).startsWith('rule') ? '规则解释' : `大模型解释 · ${aiMode}`}
          </span>
        )}
      </div>

      {(hits.length > 0 || explainParagraphs.length > 0) && (
        <div className="chat-diff-unified__sections">
          {hits.length > 0 && (
            <section className="chat-diff-unified__section">
              <h4 className="chat-diff-unified__section-title">规则命中</h4>
              <ul className="chat-diff-unified__lines">
                {hits.map((h, i) => (
                  <li key={i}>
                    {String((h as { message?: string }).message || JSON.stringify(h))}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {explainParagraphs.length > 0 && (
            <section className="chat-diff-unified__section">
              <h4 className="chat-diff-unified__section-title">分析说明</h4>
              <div className="chat-diff-unified__prose">
                {explainParagraphs.map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </div>
            </section>
          )}

        </div>
      )}
    </div>
  )
}

export function DiffFactCard({ diff, task, aiMode, embedded }: { diff: Difference; task?: Task | null; aiMode?: string; embedded?: boolean }) {
  const inner = (
    <>
      <div className="chat-wb-metrics">
        <div className="chat-wb-metric">
          <span className="label">业务键</span>
          <span className="value">{diff.business_key || '—'}</span>
        </div>
        <div className="chat-wb-metric">
          <span className="label">业务侧</span>
          <span className="value accent">{diff.business_amount?.toLocaleString() ?? '—'}</span>
        </div>
        <div className="chat-wb-metric">
          <span className="label">财务侧</span>
          <span className="value accent">{diff.finance_amount?.toLocaleString() ?? '—'}</span>
        </div>
        <div className="chat-wb-metric highlight">
          <span className="label">差异额</span>
          <span className="value accent">{diff.amount_diff?.toLocaleString() ?? '—'}</span>
        </div>
      </div>
      {!embedded && (
        <div className="chat-wb-card-foot">
          <span className="chat-wb-pill chat-wb-pill--brand">{diff.type}</span>
          {diff.risk_level && (
            <span className="chat-wb-pill chat-wb-pill--muted">{diff.risk_level}</span>
          )}
          {aiMode && (
            <span className="chat-wb-pill chat-wb-pill--ai" title="差异事实由规则计算；解释由大模型补充生成">
              <RobotOutlined />
              大模型解释 · {aiMode}
            </span>
          )}
        </div>
      )}
    </>
  )
  if (embedded) return inner
  return (
    <div className="chat-agent-card chat-agent-card--fact">
      <div className="chat-agent-card__bar">
        <span className="chat-agent-card__bar-meta">
          {task ? `${task.name} · ${task.period}` : '核对任务'}
        </span>
        <span className="chat-agent-card__bar-tag">差异事实</span>
      </div>
      <div className="chat-agent-card__hero">
        <h3 className="chat-agent-card__title">{diff.type}</h3>
        <p className="chat-agent-card__subtitle">业务键 {diff.business_key || '—'}</p>
      </div>
      <div className="chat-agent-card__body">{inner}</div>
    </div>
  )
}

export function RuleHitsCard({ hits, embedded }: { hits: Array<Record<string, unknown>>; embedded?: boolean }) {
  if (!hits.length) return null
  if (embedded) {
    return (
      <section className="chat-reply-section chat-reply-section--evidence">
        <div className="chat-reply-section-head">
          <span className="chat-reply-section-icon"><FileSearchOutlined /></span>
          <h4 className="chat-reply-section-title">规则命中</h4>
        </div>
        <ul className="chat-wb-list">
          {hits.map((h, i) => (
            <li key={i}>{String((h as { message?: string }).message || JSON.stringify(h))}</li>
          ))}
        </ul>
      </section>
    )
  }
  return (
    <div className="chat-agent-card chat-agent-card--rule">
      <div className="chat-agent-card__bar">
        <span className="chat-agent-card__bar-meta">规则引擎</span>
        <span className="chat-agent-card__bar-tag">规则命中</span>
      </div>
      <div className="chat-agent-card__body chat-agent-card__body--plain">
        <ul className="chat-wb-list chat-wb-list--rule">
          {hits.map((h, i) => (
            <li key={i}>{String((h as { message?: string }).message || JSON.stringify(h))}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export function EvidenceChainCard({ chain, embedded }: { chain: Array<Record<string, unknown>>; embedded?: boolean }) {
  if (!chain.length) return null
  const timeline = (
    <div className="chat-wb-timeline">
      {chain.map((s, i) => (
        <div key={i} className="chat-wb-timeline-item">
          <span className="stage">{String(s.stage || '')}</span>
          <span className="action">{String(s.action || '')}</span>
          {s.result != null && <span className="result">→ {String(s.result)}</span>}
        </div>
      ))}
    </div>
  )
  if (embedded) {
    return (
      <section className="chat-reply-section chat-reply-section--evidence">
        <div className="chat-reply-section-head">
          <span className="chat-reply-section-icon"><FileSearchOutlined /></span>
          <h4 className="chat-reply-section-title">证据链</h4>
        </div>
        {timeline}
      </section>
    )
  }
  return (
    <div className="chat-agent-card chat-agent-card--audit">
      <div className="chat-agent-card__bar">
        <span className="chat-agent-card__bar-meta">审计追踪</span>
        <span className="chat-agent-card__bar-tag">证据链</span>
      </div>
      <div className="chat-agent-card__body chat-agent-card__body--plain">{timeline}</div>
    </div>
  )
}

/** 助手回复：简约气泡（直接展示正文，不再 parse 后拼接，避免重复） */
export function flattenAssistantText(content: string, diff?: Difference | null): string {
  let text = dedupeAssistantContent(content)
  if (diff?.ai_explanation && !text.includes(diff.ai_explanation.slice(0, 24))) {
    text = text ? `${text}\n\n${diff.ai_explanation}` : diff.ai_explanation
  }
  if (diff?.suggestion && !text.includes(diff.suggestion.slice(0, 24))) {
    text = text ? `${text}\n\n${diff.suggestion}` : diff.suggestion
  }
  return text
}

/** 助手回复：简约气泡 */
export function AiReplyBubble({ content, diff }: { content: string; diff?: Difference | null }) {
  const text = flattenAssistantText(content, diff)
  return (
    <div className="chat-fs-bubble chat-fs-bubble--assistant chat-fs-bubble--compact">
      {text}
    </div>
  )
}

/** @deprecated 使用 AiReplyBubble */
export function AiReplyCards(props: { content: string; diff?: Difference | null }) {
  return <AiReplyBubble {...props} />
}

export function parseReplySections(text: string) {
  const { sections } = parseAssistantReply(text)
  return sections.map((s) => ({ title: s.title, body: s.body, items: s.steps }))
}
