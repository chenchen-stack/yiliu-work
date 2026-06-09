/** 差异规则 / 证据 / 解释文本格式化 */

const STAGE_LABELS: Record<string, string> = {
  detection: '规则检测',
  rule_analysis: '规则分析',
  ai_analysis: '大模型分析',
  ingestion: '数据接入',
  mapping: '字段映射',
}

const ACTION_LABELS: Record<string, string> = {
  rules_applied: '应用核对规则',
  matched: '命中差异',
  rule_based_explain: '规则引擎解释',
  llm_invoked: '调用大模型',
  no_match: '未命中',
}

export function labelEvidenceStage(stage: string): string {
  return STAGE_LABELS[stage] || stage
}

export function labelEvidenceAction(action: string): string {
  return ACTION_LABELS[action] || action
}

/** 文本中的大数字格式化为千分位 + 最多 2 位小数 */
export function formatAmountInText(text: string): string {
  return text.replace(/(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+\.\d+|-?\d+)/g, (match) => {
    const normalized = match.replace(/,/g, '')
    const n = Number(normalized)
    if (!Number.isFinite(n)) return match
    if (Math.abs(n) < 1000 && !normalized.includes('.')) return match
    return n.toLocaleString('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 0 })
  })
}

export type ExplainBlock =
  | { type: 'title'; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'numbered'; index: number; category?: string; text: string }
  | { type: 'facts'; items: Array<{ label: string; value: string }> }

/** 将规则/大模型长文本解析为结构化块 */
export function parseExplainText(raw: string): ExplainBlock[] {
  const text = formatAmountInText(raw.trim())
  if (!text) return []

  const blocks: ExplainBlock[] = []

  const factsIdx = text.indexOf('差异事实')
  let main = text
  let factsPart = ''
  if (factsIdx >= 0) {
    main = text.slice(0, factsIdx).trim()
    factsPart = text.slice(factsIdx).trim()
  }

  const titleMatch = main.match(/^【([^】]+)】(.+)/s)
  if (titleMatch) {
    blocks.push({ type: 'title', text: titleMatch[1].trim() })
    main = titleMatch[2].trim()
  }

  const numberedParts = main.split(/(?=\d+\.\s*(?:\[|【))/).filter(Boolean)
  const hasNumbered = numberedParts.some((p) => /^\d+\./.test(p.trim()))

  if (hasNumbered) {
    const intro = numberedParts[0]?.trim()
    if (intro && !/^\d+\./.test(intro)) {
      blocks.push({ type: 'paragraph', text: intro })
    }
    for (const part of numberedParts) {
      const m = part.trim().match(/^(\d+)\.\s*(?:\[([^\]]+)\]|【([^】]+)】)\s*([\s\S]*)$/)
      if (m) {
        blocks.push({
          type: 'numbered',
          index: parseInt(m[1], 10),
          category: (m[2] || m[3] || '').trim(),
          text: m[4].trim(),
        })
      } else if (/^\d+\./.test(part.trim())) {
        const m2 = part.trim().match(/^(\d+)\.\s*([\s\S]*)$/)
        if (m2) {
          blocks.push({ type: 'numbered', index: parseInt(m2[1], 10), text: m2[2].trim() })
        }
      }
    }
  } else {
    const paragraphs = main.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
    if (paragraphs.length <= 1) {
      const sentences = main.split(/(?<=[。！？])\s*/).map((s) => s.trim()).filter(Boolean)
      if (sentences.length > 1) {
        for (const s of sentences) blocks.push({ type: 'paragraph', text: s })
      } else if (main) {
        blocks.push({ type: 'paragraph', text: main })
      }
    } else {
      for (const p of paragraphs) blocks.push({ type: 'paragraph', text: p })
    }
  }

  if (factsPart) {
    const items: Array<{ label: string; value: string }> = []
    const body = factsPart.replace(/^差异事实[：:]\s*/, '')
    const segments = body.split(/[；;]/).map((s) => s.trim()).filter(Boolean)
    for (const seg of segments) {
      if (seg.includes('业务键')) {
        items.push({ label: '业务键', value: seg.replace(/.*业务键\s*/, '').split(/[，,]/)[0] || seg })
      } else if (/业务侧/.test(seg)) {
        items.push({ label: '业务侧', value: seg.replace(/.*业务侧\s*/, '') })
      } else if (/财务侧/.test(seg)) {
        items.push({ label: '财务侧', value: seg.replace(/.*财务侧\s*/, '') })
      } else if (/差异/.test(seg)) {
        items.push({ label: '差异额', value: seg.replace(/.*差异\s*/, '') })
      }
    }
    if (items.length) {
      blocks.push({ type: 'facts', items })
    } else {
      blocks.push({ type: 'paragraph', text: factsPart })
    }
  }

  return blocks
}

export function splitProseParagraphs(text: string): string[] {
  const trimmed = text.trim()
  if (!trimmed) return []
  const byBreak = trimmed.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
  if (byBreak.length > 1) return byBreak
  const bySentence = trimmed.split(/(?<=[。！？])\s+/).map((p) => p.trim()).filter(Boolean)
  return bySentence.length > 1 ? bySentence : [trimmed]
}
