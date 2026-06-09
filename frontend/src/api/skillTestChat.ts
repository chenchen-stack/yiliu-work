/** Skill 对话测试 — SSE 流式 API */

export type SkillTestChatEventType =
  | 'session'
  | 'thinking'
  | 'tool_call'
  | 'reply'
  | 'error'
  | 'done'

export interface SkillTestChatEvent {
  type: SkillTestChatEventType
  session_id?: string
  task_id?: string
  content?: string
  skill_id?: string
  skill_name?: string
  input?: Record<string, unknown>
  output?: Record<string, unknown>
  duration_ms?: number
  success?: boolean
  summary?: string
  error?: string
}

export interface SkillTestPreset {
  id: string
  label: string
  message: string
}

export interface SkillTestSkillSummary {
  skill_id: string
  code: string
  name: string
  type: string
  category: string
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('token')
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) h.Authorization = `Bearer ${token}`
  return h
}

function parseSseChunk(buffer: string, onEvent: (e: SkillTestChatEvent) => void): string {
  const parts = buffer.split('\n\n')
  const rest = parts.pop() ?? ''
  for (const block of parts) {
    for (const line of block.split('\n')) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6)) as SkillTestChatEvent
        onEvent(data)
      } catch {
        /* ignore malformed */
      }
    }
  }
  return rest
}

function httpErrorMessage(status: number, body: string): string {
  try {
    const j = JSON.parse(body) as { detail?: unknown }
    if (typeof j.detail === 'string' && j.detail) return j.detail
  } catch {
    /* ignore */
  }
  if (status === 404) {
    return '对话测试接口未就绪，请重启后端（backend\\run_dev.bat）后再试'
  }
  return body.trim() || `HTTP ${status}`
}

async function consumeSse(
  res: Response,
  onEvent: (e: SkillTestChatEvent) => void,
): Promise<void> {
  if (!res.ok) {
    const text = await res.text()
    throw new Error(httpErrorMessage(res.status, text))
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

export async function streamSkillTestChat(
  sessionId: string,
  message: string,
  onEvent: (e: SkillTestChatEvent) => void,
  focusSkill?: string,
): Promise<void> {
  const res = await fetch(`/api/v1/skill-test/sessions/${encodeURIComponent(sessionId)}/chat`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ message, focus_skill: focusSkill || null }),
  })
  await consumeSse(res, onEvent)
}

export async function streamSkillTestPreset(
  sessionId: string,
  presetId: string,
  onEvent: (e: SkillTestChatEvent) => void,
): Promise<void> {
  const res = await fetch(`/api/v1/skill-test/sessions/${encodeURIComponent(sessionId)}/preset`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ preset: presetId }),
  })
  await consumeSse(res, onEvent)
}

export async function fetchSkillTestPresets(): Promise<SkillTestPreset[]> {
  const res = await fetch('/api/v1/skill-test/presets', { headers: authHeaders() })
  if (!res.ok) throw new Error(await res.text())
  const data = (await res.json()) as { presets: SkillTestPreset[] }
  return data.presets
}

export async function fetchSkillTestSkills(): Promise<SkillTestSkillSummary[]> {
  const res = await fetch('/api/v1/skill-test/skills', { headers: authHeaders() })
  if (!res.ok) throw new Error(await res.text())
  const data = (await res.json()) as { skills: SkillTestSkillSummary[] }
  return data.skills
}

export async function clearSkillTestSession(sessionId: string): Promise<void> {
  await fetch(`/api/v1/skill-test/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
}
