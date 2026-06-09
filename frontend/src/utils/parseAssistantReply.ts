export type ReplySectionVariant = 'amount' | 'duplicate' | 'mapping' | 'process' | 'evidence' | 'default'

export type ReplySection = {
  key: string
  index?: number
  title: string
  body?: string
  steps?: string[]
  variant: ReplySectionVariant
}

export type ParsedAssistantReply = {
  lead?: string
  sections: ReplySection[]
}

const VARIANT_RULES: Array<{ test: RegExp; variant: ReplySectionVariant }> = [
  { test: /金额/, variant: 'amount' },
  { test: /重复/, variant: 'duplicate' },
  { test: /映射|主数据/, variant: 'mapping' },
  { test: /处理|说明|建议/, variant: 'process' },
  { test: /归因|证据/, variant: 'evidence' },
]

function detectVariant(title: string): ReplySectionVariant {
  for (const r of VARIANT_RULES) {
    if (r.test.test(title)) return r.variant
  }
  return 'default'
}

/** 移除 Markdown 表格行（前端不渲染表格，避免露出 | --- | 原文） */
export function stripMarkdownTables(raw: string): string {
  const kept: string[] = []
  for (const line of raw.replace(/\r\n/g, '\n').split('\n')) {
    const t = line.trim()
    if (/^\|.+\|$/.test(t)) continue
    if (/^\|[-:|\s]+\|$/.test(t)) continue
    if (t === '---' || t === '***' || t === '___') continue
    kept.push(line)
  }
  return kept.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

/** 去除 Markdown，保留可读纯文本 */
export function stripMarkdown(raw: string): string {
  return stripMarkdownTables(
    raw
      .replace(/\r\n/g, '\n')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/__([^_]+)__/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/^>\s?/gm, '')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1'),
  ).trim()
}

/** 去掉助手回复中重复的段落/半段重复（LLM 或解析拼接导致） */
export function dedupeAssistantContent(raw: string): string {
  const text = stripMarkdown(raw).trim()
  if (!text) return text

  if (text.length > 120) {
    const mid = Math.floor(text.length / 2)
    const first = text.slice(0, mid).trim()
    const second = text.slice(mid).trim()
    const n1 = first.replace(/\s+/g, ' ')
    const n2 = second.replace(/\s+/g, ' ')
    const probe = n1.slice(0, Math.min(72, n1.length))
    if (probe.length >= 24 && n2.startsWith(probe)) {
      return first
    }
  }

  const paragraphs = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
  if (paragraphs.length <= 1) return text

  const out: string[] = []
  const seen = new Set<string>()
  for (const p of paragraphs) {
    const key = p.replace(/\s+/g, ' ').slice(0, 160)
    if (seen.has(key)) continue
    if (out.some((prev) => prev.replace(/\s+/g, ' ') === p.replace(/\s+/g, ' '))) continue
    seen.add(key)
    out.push(p)
  }
  return out.join('\n\n')
}

function splitBodyAndSteps(block: string): { body?: string; steps?: string[] } {
  const lines = block.split('\n').map((l) => l.trim()).filter(Boolean)
  const steps: string[] = []
  const bodyLines: string[] = []
  for (const line of lines) {
    const num = line.match(/^(\d+)[.、)]\s*(.+)$/)
    const bullet = line.match(/^[-–•]\s*(.+)$/)
    const circled = line.match(/^[①②③④⑤⑥⑦⑧⑨⑩]\s*(.+)$/)
    if (num) steps.push(num[2].trim())
    else if (bullet) steps.push(bullet[1].trim())
    else if (circled) steps.push(circled[1].trim())
    else bodyLines.push(line)
  }
  return {
    body: bodyLines.length ? bodyLines.join('\n') : undefined,
    steps: steps.length ? steps : undefined,
  }
}

function pushSection(
  sections: ReplySection[],
  title: string,
  block: string,
  index?: number,
) {
  const t = title.trim()
  if (!t) return
  const { body, steps } = splitBodyAndSteps(block.trim())
  sections.push({
    key: `${index ?? ''}-${t}`,
    index,
    title: t,
    body,
    steps,
    variant: detectVariant(t),
  })
}

/** 将 AI 纯文本解析为：摘要 + 分块（用于单气泡内可视化） */
export function parseAssistantReply(raw: string): ParsedAssistantReply {
  const text = stripMarkdown(raw)
  if (!text) return { sections: [] }

  const sections: ReplySection[] = []

  // ① ② ③ 或 1. 2. 3. 分段
  const numberedParts = text.split(/(?=(?:^|\n)(?:[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.、)]))\s*/m).filter(Boolean)
  let lead = ''

  const tryNumbered = (chunk: string) => {
    const circled = chunk.match(/^([①②③④⑤⑥⑦⑧⑨⑩])\s*([^\n]+)\n?([\s\S]*)$/)
    if (circled) {
      const idx = '①②③④⑤⑥⑦⑧⑨⑩'.indexOf(circled[1]) + 1
      pushSection(sections, circled[2], circled[3] || '', idx)
      return true
    }
    const num = chunk.match(/^(\d+)[.、)]\s*([^\n]+)\n?([\s\S]*)$/)
    if (num) {
      pushSection(sections, num[2], num[3] || '', parseInt(num[1], 10))
      return true
    }
    return false
  }

  for (const part of numberedParts) {
    const p = part.trim()
    if (!p) continue
    if (tryNumbered(p)) continue
    if (!sections.length && !lead) lead = p
    else if (sections.length) {
      const last = sections[sections.length - 1]
      last.body = (last.body ? `${last.body}\n` : '') + p
    } else {
      lead = lead ? `${lead}\n${p}` : p
    }
  }

  if (sections.length > 0) {
    return { lead: lead || undefined, sections }
  }

  // 【标题】或 **标题** 分段
  const bracketParts = text.split(/(?=【[^】]+】)/).filter(Boolean)
  if (bracketParts.length > 1) {
    for (const part of bracketParts) {
      const m = part.match(/^【([^】]+)】\s*([\s\S]*)$/)
      if (m) pushSection(sections, m[1], m[2])
      else if (!lead) lead = part.trim()
    }
    if (sections.length) return { lead: lead || undefined, sections }
  }

  // 按空行拆成多段，短标题行 + 正文
  const paragraphs = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)
  if (paragraphs.length >= 2) {
    for (const para of paragraphs) {
      const lines = para.split('\n')
      const first = lines[0]
      const rest = lines.slice(1).join('\n')
      if (first.length <= 24 && rest) {
        pushSection(sections, first.replace(/[:：]\s*$/, ''), rest)
      } else if (!lead) {
        lead = para
      } else {
        pushSection(sections, '补充说明', para)
      }
    }
    if (sections.length) return { lead: lead || undefined, sections }
  }

  // 单段：尝试按句号拆成步骤
  const single = splitBodyAndSteps(text)
  if (single.steps && single.steps.length >= 2) {
    return {
      lead: single.body,
      sections: single.steps.map((step, i) => ({
        key: `step-${i}`,
        index: i + 1,
        title: `步骤 ${i + 1}`,
        body: step,
        variant: 'default' as const,
      })),
    }
  }

  return {
    sections: [{
      key: 'main',
      title: '说明',
      body: text,
      variant: 'default',
    }],
  }
}
