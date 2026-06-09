import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Collapse, Input, message } from 'antd'
import {
  ClearOutlined, SendOutlined,
  RobotOutlined, LoadingOutlined, CheckCircleOutlined,
  CloseCircleOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import {
  clearSkillTestSession,
  fetchSkillTestPresets,
  fetchSkillTestSkills,
  streamSkillTestChat,
  streamSkillTestPreset,
  type SkillTestChatEvent,
  type SkillTestPreset,
  type SkillTestSkillSummary,
} from '../api/skillTestChat'
import { formatApiError } from '../api/errors'

export type SkillTestChatMessage =
  | { id: string; kind: 'system'; content: string }
  | { id: string; kind: 'user'; content: string; ts: number }
  | { id: string; kind: 'thinking'; content: string; collapsed?: boolean }
  | {
      id: string
      kind: 'tool_call'
      skillId: string
      skillName: string
      summary: string
      durationMs: number
      success: boolean
      input?: Record<string, unknown>
      output?: Record<string, unknown>
    }
  | { id: string; kind: 'reply'; content: string; ts: number }
  | { id: string; kind: 'error'; content: string; skillId?: string }

type SkillRunStatus = 'idle' | 'running' | 'ok' | 'fail' | 'skip'

type Props = {
  focusSkill?: string
  skillName?: string
  embedded?: boolean
}

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function createSessionId() {
  return crypto.randomUUID?.() ?? `st-${Date.now()}`
}

export function SkillTestChat({ focusSkill, skillName, embedded = false }: Props) {
  const [sessionId, setSessionId] = useState<string>(() => createSessionId())
  const [messages, setMessages] = useState<SkillTestChatMessage[]>([
    {
      id: newId(),
      kind: 'system',
      content: focusSkill
        ? `正在测试「${skillName || focusSkill}」。用自然语言描述你想验证的场景，我会像 Agent 一样自动调用 Skill 并回复结果。`
        : '用自然语言描述对账或 Skill 验证需求，我会自动选择并调用合适的 Skill。',
    },
  ])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [presets, setPresets] = useState<SkillTestPreset[]>([])
  const [skills, setSkills] = useState<SkillTestSkillSummary[]>([])
  const [skillStatus, setSkillStatus] = useState<Record<string, SkillRunStatus>>({})
  const messagesRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchSkillTestPresets().then(setPresets).catch(() => {})
    fetchSkillTestSkills().then((list) => {
      setSkills(list)
      const init: Record<string, SkillRunStatus> = {}
      for (const s of list) init[s.code] = 'idle'
      setSkillStatus(init)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    const el = messagesRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages, sending])

  const formatReply = (content: string) => {
    const t = content.trim()
    if (t.startsWith('{') && t.includes('"answer"')) {
      try {
        const o = JSON.parse(t) as { answer?: string }
        if (typeof o.answer === 'string') {
          return o.answer.replace(/^\(演示模式\)\s*/i, '').trim()
        }
      } catch {
        /* keep raw */
      }
    }
    return t.replace(/^\(演示模式\)\s*/i, '').trim()
  }

  const appendThinking = useCallback((content: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last?.kind === 'thinking') {
        return [
          ...prev.slice(0, -1),
          { ...last, content: `${last.content}\n${content}` },
        ]
      }
      return [...prev, { id: newId(), kind: 'thinking', content, collapsed: false }]
    })
  }, [])

  const handleEvent = useCallback((evt: SkillTestChatEvent) => {
    if (evt.type === 'session' && evt.session_id) {
      setSessionId(evt.session_id)
      if (evt.task_id) {
        setMessages((prev) => {
          const first = prev[0]
          if (first?.kind !== 'system') return prev
          const base = first.content.split('。')[0] || first.content
          return [
            { ...first, content: `${base}。已绑定任务执行（真实 Skill 调用）。` },
            ...prev.slice(1),
          ]
        })
      }
      return
    }
    if (evt.type === 'thinking' && evt.content) {
      appendThinking(evt.content)
      return
    }
    if (evt.type === 'tool_call') {
      const code = evt.skill_id || 'unknown'
      setSkillStatus((s) => ({ ...s, [code]: 'running' }))
      setMessages((prev) => {
        const filtered = prev.filter((m) => m.kind !== 'thinking' || !m.collapsed)
        return [
          ...filtered,
          {
            id: newId(),
            kind: 'tool_call',
            skillId: code,
            skillName: evt.skill_name || code,
            summary: evt.summary || '执行完成',
            durationMs: evt.duration_ms ?? 0,
            success: evt.success !== false,
            input: evt.input,
            output: evt.output,
          },
        ]
      })
      setSkillStatus((s) => ({
        ...s,
        [code]: evt.success !== false ? 'ok' : 'fail',
      }))
      return
    }
    if (evt.type === 'error') {
      if (evt.skill_id) {
        setSkillStatus((s) => ({ ...s, [evt.skill_id!]: 'fail' }))
      }
      setMessages((prev) => [
        ...prev.filter((m) => m.kind !== 'thinking'),
        {
          id: newId(),
          kind: 'error',
          content: evt.error || '执行失败',
          skillId: evt.skill_id,
        },
      ])
      return
    }
    if (evt.type === 'reply' && evt.content) {
      setMessages((prev) => [
        ...prev.filter((m) => m.kind !== 'thinking'),
        { id: newId(), kind: 'reply', content: evt.content!, ts: Date.now() },
      ])
    }
  }, [appendThinking])

  const runStream = useCallback(async (fn: () => Promise<void>) => {
    setSending(true)
    try {
      await fn()
    } catch (e) {
      message.error(formatApiError(e))
      setMessages((prev) => [
        ...prev,
        { id: newId(), kind: 'error', content: formatApiError(e) },
      ])
    } finally {
      setSending(false)
    }
  }, [])

  const sendMessage = useCallback(async (text?: string) => {
    const msg = (text ?? input).trim()
    if (!msg || sending) return
    setInput('')
    setMessages((prev) => [...prev, { id: newId(), kind: 'user', content: msg, ts: Date.now() }])
    await runStream(() =>
      streamSkillTestChat(sessionId, msg, handleEvent, focusSkill),
    )
  }, [input, sending, sessionId, focusSkill, handleEvent, runStream])

  const runPreset = useCallback(async (presetId: string) => {
    const preset = presets.find((p) => p.id === presetId)
    if (!preset || sending) return
    setMessages((prev) => [
      ...prev,
      { id: newId(), kind: 'user', content: preset.message, ts: Date.now() },
    ])
    await runStream(() => streamSkillTestPreset(sessionId, presetId, handleEvent))
  }, [presets, sending, sessionId, handleEvent, runStream])

  const handleClear = async () => {
    try {
      await clearSkillTestSession(sessionId)
    } catch {
      /* ignore */
    }
    const sid = createSessionId()
    setSessionId(sid)
    setMessages([
      {
        id: newId(),
        kind: 'system',
        content: focusSkill
          ? `会话已清空。继续测试「${skillName || focusSkill}」请直接输入需求。`
          : '会话已清空，请用自然语言开始测试。',
      },
    ])
    setSkillStatus((prev) => {
      const next = { ...prev }
      for (const k of Object.keys(next)) next[k] = 'idle'
      return next
    })
  }

  const monitorSkills = useMemo(() => {
    if (skills.length) return skills
    return [
      { code: 'data_import', name: '数据导入', skill_id: '', type: '', category: '' },
      { code: 'field_mapping', name: '字段映射', skill_id: '', type: '', category: '' },
      { code: 'difference_detect', name: '差异识别', skill_id: '', type: '', category: '' },
      { code: 'anomaly_explain', name: '异常解释', skill_id: '', type: '', category: '' },
      { code: 'review_flow', name: '复核流转', skill_id: '', type: '', category: '' },
      { code: 're_verify', name: '再次验证', skill_id: '', type: '', category: '' },
      { code: 'report_gen', name: '报告生成', skill_id: '', type: '', category: '' },
    ]
  }, [skills])

  const statusIcon = (st: SkillRunStatus) => {
    if (st === 'running') return <LoadingOutlined spin className="skill-test-chat__status-ico--run" />
    if (st === 'ok') return <CheckCircleOutlined className="skill-test-chat__status-ico--ok" />
    if (st === 'fail') return <CloseCircleOutlined className="skill-test-chat__status-ico--fail" />
    return <ClockCircleOutlined className="skill-test-chat__status-ico--idle" />
  }

  const statusLabel = (st: SkillRunStatus) => {
    if (st === 'running') return '运行中'
    if (st === 'ok') return '已完成'
    if (st === 'fail') return '失败'
    return '等待'
  }

  return (
    <div className={`skill-test-chat${embedded ? ' skill-test-chat--embedded' : ''}`}>
      <div className="skill-test-chat__toolbar">
        <span className="skill-test-chat__toolbar-hint">对话测试</span>
        <Button type="text" size="small" className="skill-test-chat__clear" icon={<ClearOutlined />} onClick={() => { void handleClear() }}>
          清空
        </Button>
      </div>

      {presets.length > 0 && (
        <div className="skill-test-chat__presets">
          {presets.map((p) => (
            <button
              key={p.id}
              type="button"
              className="skill-test-chat__preset"
              disabled={sending}
              onClick={() => { void runPreset(p.id) }}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}

      <div className="skill-test-chat__body">
        <div className="skill-test-chat__main">
          <div className="skill-test-chat__messages" ref={messagesRef}>
            {messages.map((m) => {
              if (m.kind === 'system') {
                return (
                  <div key={m.id} className="skill-test-chat__system">
                    <RobotOutlined /> {m.content}
                  </div>
                )
              }
              if (m.kind === 'user') {
                return (
                  <div key={m.id} className="skill-test-chat__user">
                    <div className="skill-test-chat__bubble skill-test-chat__bubble--user">
                      {m.content}
                    </div>
                  </div>
                )
              }
              if (m.kind === 'thinking') {
                return (
                  <div key={m.id} className="skill-test-chat__thinking">
                    <Collapse
                      ghost
                      size="small"
                      defaultActiveKey={['1']}
                      items={[{
                        key: '1',
                        label: <span><span className="skill-test-chat__emoji">🧠</span> 思考过程</span>,
                        children: <pre className="skill-test-chat__thinking-body">{m.content}</pre>,
                      }]}
                    />
                  </div>
                )
              }
              if (m.kind === 'tool_call') {
                return (
                  <div key={m.id} className={`skill-test-chat__tool${m.success ? '' : ' skill-test-chat__tool--fail'}`}>
                    <div className="skill-test-chat__tool-head">
                      <span className="skill-test-chat__tool-name">调用 {m.skillName}</span>
                      <span className="skill-test-chat__tool-ms">{m.durationMs} ms</span>
                    </div>
                    <div className="skill-test-chat__tool-summary">{m.summary}</div>
                    {(m.input || m.output) && (
                      <Collapse
                        ghost
                        size="small"
                        items={[{
                          key: 'json',
                          label: '查看完整入参 / 返回',
                          children: (
                            <div className="skill-test-chat__tool-json">
                              {m.input && (
                                <>
                                  <div className="skill-test-chat__json-label">输入</div>
                                  <pre>{JSON.stringify(m.input, null, 2)}</pre>
                                </>
                              )}
                              {m.output && (
                                <>
                                  <div className="skill-test-chat__json-label">输出</div>
                                  <pre>{JSON.stringify(m.output, null, 2)}</pre>
                                </>
                              )}
                            </div>
                          ),
                        }]}
                      />
                    )}
                  </div>
                )
              }
              if (m.kind === 'error') {
                return (
                  <div key={m.id} className="skill-test-chat__error">
                    {m.skillId ? `[${m.skillId}] ` : ''}{m.content}
                  </div>
                )
              }
              return (
                <div key={m.id} className="skill-test-chat__reply">
                  <div className="skill-test-chat__bubble skill-test-chat__bubble--assistant">
                    {formatReply(m.content)}
                  </div>
                </div>
              )
            })}
            {sending && (
              <div className="skill-test-chat__typing">
                <span className="dot-pulse" />
              </div>
            )}
          </div>

          <div className="skill-test-chat__input">
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="例如：帮我执行方太 5 月份对账 / 分析这 11 条差异的原因…"
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={sending}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  void sendMessage()
                }
              }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={sending}
              onClick={() => { void sendMessage() }}
            >
              发送
            </Button>
          </div>
        </div>

        <aside className="skill-test-chat__aside">
          <div className="skill-test-chat__aside-title">Skill 执行状态</div>
          <ul className="skill-test-chat__status-list">
            {monitorSkills.map((s) => {
              const st = skillStatus[s.code] ?? 'idle'
              return (
                <li key={s.code} className={`skill-test-chat__status-item skill-test-chat__status-item--${st}`}>
                  {statusIcon(st)}
                  <span className="skill-test-chat__status-name">{s.name}</span>
                  <span className="skill-test-chat__status-meta">{statusLabel(st)}</span>
                </li>
              )
            })}
          </ul>
        </aside>
      </div>
    </div>
  )
}
