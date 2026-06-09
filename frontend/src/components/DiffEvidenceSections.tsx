import type { Difference } from '../api/client'
import {
  formatAmountInText,
  labelEvidenceAction,
  labelEvidenceStage,
  parseExplainText,
  splitProseParagraphs,
  type ExplainBlock,
} from '../utils/formatDiffText'

function ExplainBlocks({ blocks }: { blocks: ExplainBlock[] }) {
  if (!blocks.length) return null
  return (
    <div className="diff-explain-blocks">
      {blocks.map((b, i) => {
        if (b.type === 'title') {
          return (
            <div key={i} className="diff-explain-blocks__title">
              {b.text}
            </div>
          )
        }
        if (b.type === 'paragraph') {
          return <p key={i} className="diff-explain-blocks__p">{b.text}</p>
        }
        if (b.type === 'numbered') {
          return (
            <div key={i} className="diff-explain-blocks__item">
              <span className="diff-explain-blocks__idx">{b.index}</span>
              <div className="diff-explain-blocks__item-body">
                {b.category && (
                  <span className="diff-explain-blocks__cat">{b.category}</span>
                )}
                <p>{b.text}</p>
              </div>
            </div>
          )
        }
        if (b.type === 'facts') {
          return (
            <div key={i} className="diff-explain-blocks__facts">
              <span className="diff-explain-blocks__facts-label">差异事实</span>
              <div className="diff-explain-blocks__facts-grid">
                {b.items.map((item, j) => (
                  <div key={j} className="diff-explain-blocks__fact">
                    <span className="diff-explain-blocks__fact-k">{item.label}</span>
                    <span className="diff-explain-blocks__fact-v">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )
        }
        return null
      })}
    </div>
  )
}

function EvidenceStep({
  stage,
  action,
  result,
  compact,
}: {
  stage: string
  action: string
  result: string
  compact?: boolean
}) {
  const stageLabel = labelEvidenceStage(stage)
  const actionLabel = labelEvidenceAction(action)
  const isLong = result.length > 80
  const blocks = !compact && isLong ? parseExplainText(result) : []
  const summary = compact
    ? '已生成大模型解释，详见下方「规则解释与建议」。'
    : blocks.length === 0
      ? (result.length > 100 ? `${result.slice(0, 100)}…` : result)
      : ''

  return (
    <div className="diff-evidence-step">
      <div className="diff-evidence-step__rail">
        <span className="diff-evidence-step__dot" />
      </div>
      <div className="diff-evidence-step__content">
        <div className="diff-evidence-step__head">
          <span className="diff-evidence-step__stage">{stageLabel}</span>
          <span className="diff-evidence-step__arrow">→</span>
          <span className="diff-evidence-step__action">{actionLabel}</span>
        </div>
        {blocks.length > 0 ? (
          <ExplainBlocks blocks={blocks} />
        ) : summary ? (
          <p className={`diff-evidence-step__summary${compact ? ' diff-evidence-step__summary--hint' : ''}`}>
            {compact ? summary : formatAmountInText(summary)}
          </p>
        ) : null}
      </div>
    </div>
  )
}

/** 三、规则与证据 */
export function DiffRuleEvidenceSection({ diff }: { diff: Difference }) {
  const hits = diff.rule_hits || []
  const chain = diff.evidence_chain || []

  return (
    <div className="diff-detail-section">
      {hits.length > 0 && (
        <ul className="diff-detail-hits">
          {hits.map((h, i) => {
            const msg = String((h as { message?: string }).message || JSON.stringify(h))
            return <li key={i}>{formatAmountInText(msg)}</li>
          })}
        </ul>
      )}
      {chain.length > 0 && (
        <div className="diff-evidence-chain">
          {chain.map((s, i) => {
            const stage = String(s.stage || '')
            const action = String(s.action || '')
            const result = String(s.result || '')
            const compact = stage === 'ai_analysis' && result.length > 40
            return (
              <EvidenceStep
                key={i}
                stage={stage}
                action={action}
                result={result}
                compact={compact}
              />
            )
          })}
        </div>
      )}
      {!hits.length && !chain.length && (
        <p className="diff-detail-empty">暂无规则命中与证据链记录</p>
      )}
    </div>
  )
}

/** 四、规则解释与建议 · 正文 */
export function DiffExplanationProse({
  explanation,
  suggestion,
}: {
  explanation?: string | null
  suggestion?: string | null
}) {
  const explainText = (explanation || '').trim()
  const blocks = explainText.length > 60 ? parseExplainText(explainText) : []
  const paragraphs = blocks.length === 0 ? splitProseParagraphs(explainText) : []

  return (
    <div className="diff-explanation-prose">
      {blocks.length > 0 ? (
        <ExplainBlocks blocks={blocks} />
      ) : (
        paragraphs.map((p, i) => (
          <p key={i} className="diff-explanation-prose__p">{p}</p>
        ))
      )}
      {(suggestion || '').trim() && (
        <div className="diff-explanation-prose__suggestion">
          <span className="diff-explanation-prose__suggestion-label">处置建议</span>
          <p>{formatAmountInText(String(suggestion).trim())}</p>
        </div>
      )}
    </div>
  )
}
