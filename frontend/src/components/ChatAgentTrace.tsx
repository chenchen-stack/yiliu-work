import { useState } from 'react'
import {
  CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
} from '@ant-design/icons'

export type ChatAgentTraceItem =
  | { id: string; kind: 'thinking'; content: string }
  | {
      id: string
      kind: 'tool_call'
      skillId: string
      skillName: string
      summary: string
      success: boolean
      durationMs?: number
      input?: Record<string, unknown>
      output?: Record<string, unknown>
    }

export type ExecutionStep = {
  thought?: string
  action?: string
  observation?: string
  success?: boolean
}

/** 执行过程已展示推理时，去掉正文中重复的推理段落 */
export function dedupeTraceFromReply(reply: string, items: ChatAgentTraceItem[]): string {
  const thinking = items
    .filter((t): t is Extract<ChatAgentTraceItem, { kind: 'thinking' }> => t.kind === 'thinking')
    .map((t) => t.content)
    .join('\n')
    .trim()
  const body = (reply || '').trim()
  if (!body || !thinking) return body
  if (body === thinking) return ''
  const head = thinking.slice(0, Math.min(160, thinking.length))
  if (head.length >= 40 && body.startsWith(head)) {
    return body.slice(head.length).trim() || body
  }
  return body
}

type ExecutionPanelProps = {
  steps: ExecutionStep[]
  note?: string
  streaming?: boolean
  defaultOpen?: boolean
}

/** 统一的「执行过程」折叠面板（agent_runtime plan / LangGraph trace 共用） */
export function ChatExecutionProcess({
  steps,
  note,
  streaming,
  defaultOpen = false,
}: ExecutionPanelProps) {
  const [open, setOpen] = useState(defaultOpen)
  if (!steps.length && !streaming) return null

  return (
    <div className={`chat-agent-plan${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="chat-agent-plan__toggle"
        onClick={() => setOpen(!open)}
      >
        <span>{open ? '收起执行过程' : '执行过程'}</span>
        <span className="chat-agent-plan__chev" aria-hidden />
      </button>
      {open && (
        <>
          {note ? <p className="chat-agent-plan__note">{note}</p> : null}
          {steps.length > 0 && (
            <ol className="chat-agent-plan__list">
              {steps.map((s, i) => {
                const obs = (s.observation || '').trim()
                const longObs = obs.length > 100 || obs.includes('\n')
                return (
                  <li key={i}>
                    <span className="chat-agent-plan__step-idx">{i + 1}</span>
                    <span className="chat-agent-plan__step-main">
                      {s.success === false ? (
                        <CloseCircleOutlined className="chat-agent-plan__ico--fail" />
                      ) : s.success === true ? (
                        <CheckCircleOutlined className="chat-agent-plan__ico--ok" />
                      ) : null}
                      {s.thought || s.action}
                    </span>
                    {obs ? (
                      longObs
                        ? <pre className="chat-agent-plan__detail">{obs}</pre>
                        : <span className="chat-agent-plan__obs">{obs}</span>
                    ) : null}
                  </li>
                )
              })}
            </ol>
          )}
        </>
      )}
      {streaming && (
        <p className="chat-agent-plan__live">
          <LoadingOutlined spin /> 正在处理…
        </p>
      )}
    </div>
  )
}

type Props = {
  items: ChatAgentTraceItem[]
  streaming?: boolean
}

export function ChatAgentTrace({ items, streaming }: Props) {
  if (!items.length && !streaming) return null

  const hasTool = items.some((m) => m.kind === 'tool_call')
  const thinking = items
    .filter((m): m is Extract<ChatAgentTraceItem, { kind: 'thinking' }> => m.kind === 'thinking')
    .map((m) => m.content)
    .join('\n')
    .trim()

  const toolSeen = new Set<string>()
  const steps: ExecutionStep[] = items
    .filter((m): m is Extract<ChatAgentTraceItem, { kind: 'tool_call' }> => m.kind === 'tool_call')
    .filter((m) => {
      const key = m.skillId || m.skillName || ''
      if (!key || toolSeen.has(key)) return false
      toolSeen.add(key)
      return true
    })
    .map((m) => ({
      thought: `调用 ${m.skillName || m.skillId}`,
      observation: [
        m.summary,
        m.durationMs != null ? `${m.durationMs} ms` : '',
      ].filter(Boolean).join(' · '),
      success: m.success,
    }))

  if (thinking) {
    steps.push({
      thought: hasTool ? '补充推理' : '分析推理',
      observation: thinking,
    })
  }

  const note = !hasTool && thinking && !streaming
    ? '本次未调用 Skill，直接基于内置能力回答。'
    : undefined

  return (
    <ChatExecutionProcess
      steps={steps}
      note={note}
      streaming={streaming}
      defaultOpen={Boolean(streaming)}
    />
  )
}
