/** 生产对话 SSE — Skill Agent（thinking / tool_call / reply / ui_blocks） */

export type ChatStreamEventType =
  | 'session'
  | 'thinking'
  | 'tool_call'
  | 'plan'
  | 'ui_blocks'
  | 'reply'
  | 'error'
  | 'done'

export interface ChatStreamEvent {
  type: ChatStreamEventType
  conversation_id?: string
  agent_id?: string
  content?: string
  skill_id?: string
  skill_name?: string
  input?: Record<string, unknown>
  output?: Record<string, unknown>
  success?: boolean
  summary?: string
  steps?: Array<{ thought?: string; action?: string; observation?: string }>
  blocks?: Array<{ type: string; data: Record<string, unknown> }>
  error?: string
  intent?: string
  task_id?: string
  engine?: string
}

export interface ChatStreamRequest {
  message: string
  history: Array<{ role: string; content: string }>
  task_id?: string
  difference_item_id?: string
  conversation_id?: string
  agent_id?: string
  client_action?: string
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('token')
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) h.Authorization = `Bearer ${token}`
  return h
}

function parseSseChunk(buffer: string, onEvent: (e: ChatStreamEvent) => void): string {
  const parts = buffer.split('\n\n')
  const rest = parts.pop() ?? ''
  for (const block of parts) {
    for (const line of block.split('\n')) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6)) as ChatStreamEvent
        onEvent(data)
      } catch {
        /* ignore malformed */
      }
    }
  }
  return rest
}

export async function streamChatTurn(
  body: ChatStreamRequest,
  onEvent: (e: ChatStreamEvent) => void,
): Promise<void> {
  const res = await fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    let detail = text
    try {
      const j = JSON.parse(text) as { detail?: unknown }
      if (typeof j.detail === 'string') detail = j.detail
    } catch {
      /* keep raw */
    }
    throw new Error(detail || `HTTP ${res.status}`)
  }
  const reader = res.body?.getReader()
  if (!reader) throw new Error('无法读取响应流')
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    buf = parseSseChunk(buf, onEvent)
  }
  if (buf.trim()) parseSseChunk(buf + '\n\n', onEvent)
}
