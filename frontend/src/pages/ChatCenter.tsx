import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams, Link, useLocation, useNavigate } from 'react-router-dom'
import { Button } from 'antd'
import { ArrowLeftOutlined, ArrowUpOutlined } from '@ant-design/icons'
import {
  chatWithContext, getTask, getDifferences, getChatConversation, Difference, Task,
  ensureDifferenceExplainUiBlocks,
  getChatReconciliationOptions, buildDatasourceConfirmBlock,
  buildReconciliationResultBlock, buildReviewPromptBlock, buildReviewInlineBlock,
  datasourceConfirmIntro,
  inferReconciliationPeriod, shouldOfferReconciliationUi, listAgents, getAgent, type AgentConfigItem,
} from '../api/client'
import {
  DiffContextCard,
} from '../components/ChatWorkbenchCards'
import { ChatAvatar } from '../components/ChatAvatar'
import ChatAgentPicker from '../components/ChatAgentPicker'
import {
  AiAssistantMessage, ChatUiBlock, ChatWelcomeCaps, UserMessageStack, looksLikeMarkdownSkillDump,
} from '../components/ChatActionCards'
import { stripMarkdownTables } from '../utils/parseAssistantReply'
import {
  agentAssistantAvatarUrl,
  buildChipsFromAgent,
  buildWelcomeCapsBlock,
  sortAgentsForChat,
} from '../utils/agentChatProfile'
import { avatarImageUrl } from '../utils/agentAvatars'
import { dedupeAssistantContent } from '../utils/parseAssistantReply'
import { streamChatTurn, type ChatStreamEvent } from '../api/chatStream'
import { dedupeTraceFromReply, type ChatAgentTraceItem } from '../components/ChatAgentTrace'

function isWelcomeOnlyAssistant(m: Msg): boolean {
  if (m.role !== 'assistant') return false
  const blocks = m.ui_blocks || []
  if (!blocks.length) return !m.content?.trim()
  return blocks.every((b) => b.type === 'welcome_caps')
}

type Msg =
  | { id: string; role: 'user'; content: string; at?: string }
  | {
      id: string
      role: 'assistant'
      content: string
      ui_blocks?: ChatUiBlock[]
      task_id?: string
      at?: string
      agent_trace?: ChatAgentTraceItem[]
    }
  | { id: string; role: 'context' }

const CONTEXT_CHIPS: Array<{ label: string; prompt: string }> = [
  { label: '解释归因', prompt: '请解释当前差异的归因结论与证据链' },
  { label: '处理说明', prompt: '请生成该差异的处理说明建议' },
]

let msgSeq = 0
const nextId = () => `m-${Date.now()}-${++msgSeq}`

function normalizeAssistantContent(content: string, ui_blocks?: ChatUiBlock[]) {
  const trimmed = content?.trim() || ''
  if (!trimmed || !ui_blocks?.length) return content
  const dsIntro = ui_blocks.find((b) => b.type === 'datasource_confirm')?.data?.intro
  if (dsIntro && trimmed === String(dsIntro).trim()) return ''
  if (ui_blocks.some((b) => b.type === 'difference_explain') && trimmed.length < 140) return ''
  if (ui_blocks.some((b) => b.type === 'difference_list') && trimmed.length < 200) return ''
  if (
    ui_blocks.some((b) => b.type === 'agent_capability_overview' || b.type === 'capability_list')
    && trimmed.length > 0
  ) {
    return ''
  }
  const clarifyIntro = ui_blocks.find((b) => b.type === 'clarify_form')?.data?.intro
  if (clarifyIntro && trimmed === String(clarifyIntro).trim()) return ''
  return content
}

function resolveChatTaskId(urlTaskId: string | undefined, messages: Msg[]): string | undefined {
  if (urlTaskId) return urlTaskId
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role !== 'assistant') continue
    if (m.task_id) return m.task_id
    for (const b of m.ui_blocks || []) {
      if (
        b.type === 'reconciliation_result'
        || b.type === 'difference_list'
        || b.type === 'review_prompt'
      ) {
        const tid = b.data?.task_id
        if (tid) return String(tid)
      }
    }
  }
  return undefined
}

function dedupeDisplayMessages(messages: Msg[]) {
  let seenWelcome = false
  let lastAssistantContent = ''
  return messages.filter((m) => {
    if (m.role !== 'assistant') {
      lastAssistantContent = ''
      return true
    }
    const isWelcome = m.ui_blocks?.some((b) => b.type === 'welcome_caps')
    if (isWelcome) {
      if (seenWelcome) return false
      seenWelcome = true
    }
    const ct = (m.content || '').trim()
    if (ct && ct === lastAssistantContent) return false
    if (ct) lastAssistantContent = ct
    return true
  })
}

export default function ChatCenter() {
  const location = useLocation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const quickPrompt = (location.state as { prompt?: string } | null)?.prompt
  const newChatToken = params.get('_new')
  const taskId = params.get('task_id') || undefined
  const diffId = params.get('difference_id') || undefined
  const convIdParam = params.get('conversation_id') || undefined
  const agentIdParam = params.get('agent_id') || undefined

  const [task, setTask] = useState<Task | null>(null)
  const [agents, setAgents] = useState<AgentConfigItem[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState<string | undefined>(agentIdParam)
  const [diff, setDiff] = useState<Difference | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string>()
  const messagesScrollRef = useRef<HTMLDivElement>(null)
  const quickSentRef = useRef(false)
  const restoredConvRef = useRef<string | null>(null)
  const welcomeShownRef = useRef(false)
  const resultShownRef = useRef(new Set<string>())

  const aiMode = (task?.summary?.ai_mode as string) || 'mock-ai'
  const hasContext = !!diff
  const chatAgents = useMemo(() => sortAgentsForChat(agents), [agents])
  const selectedAgent = useMemo(
    () => chatAgents.find((a) => a.id === selectedAgentId) ?? chatAgents[0] ?? undefined,
    [chatAgents, selectedAgentId],
  )
  const assistantAvatarSrc = agentAssistantAvatarUrl(selectedAgent)
  const chips = useMemo(
    () => buildChipsFromAgent(selectedAgent, hasContext),
    [selectedAgent, hasContext],
  )
  const displayMessages = useMemo(() => dedupeDisplayMessages(messages), [messages])

  const lastAssistantRowKey = useMemo(() => {
    for (let i = displayMessages.length - 1; i >= 0; i--) {
      const m = displayMessages[i]
      if (m.role === 'assistant' && !isWelcomeOnlyAssistant(m)) {
        return `${m.id}-${i}`
      }
    }
    return null
  }, [displayMessages])

  const isLandingMode = useMemo(() => {
    if (hasContext || taskId) return false
    if (displayMessages.some((m) => m.role === 'user')) return false
    const assistants = displayMessages.filter((m) => m.role === 'assistant')
    if (!assistants.length) return true
    return assistants.every(isWelcomeOnlyAssistant)
  }, [displayMessages, hasContext, taskId])

  const welcomeBlockData = useMemo(
    () => buildWelcomeCapsBlock(selectedAgent).data,
    [selectedAgent],
  )

  const resetToNewChat = useCallback(() => {
    restoredConvRef.current = null
    resultShownRef.current = new Set()
    quickSentRef.current = false
    setConversationId(undefined)
    setInput('')
    setLoading(false)
    setTask(null)
    setDiff(null)
    const agent = chatAgents.find((a) => a.id === selectedAgentId) || chatAgents[0]
    setMessages([{
      id: nextId(),
      role: 'assistant',
      content: '',
      ui_blocks: [buildWelcomeCapsBlock(agent)],
      at: new Date().toISOString(),
    }])
    welcomeShownRef.current = true
  }, [chatAgents, selectedAgentId])

  useEffect(() => {
    if (!newChatToken) return
    resetToNewChat()
    const keepPrompt = quickPrompt
      ? { state: { prompt: quickPrompt } as { prompt: string } }
      : undefined
    navigate('/chat', { replace: true, ...keepPrompt })
  }, [newChatToken, resetToNewChat, navigate, quickPrompt])

  const reloadAgentList = useCallback(() => {
    listAgents().then((list) => {
      const sorted = sortAgentsForChat(list)
      setAgents(sorted)
      if (!selectedAgentId && sorted.length) {
        const def = sorted.find((a) => a.code === 'revenue_diff_explain') || sorted[0]
        setSelectedAgentId(agentIdParam || def.id)
      }
    }).catch(console.error)
  }, [selectedAgentId, agentIdParam])

  useEffect(() => {
    reloadAgentList()
  }, [reloadAgentList])

  useEffect(() => {
    const onAgentsRefresh = () => reloadAgentList()
    window.addEventListener('agents-refresh', onAgentsRefresh)
    return () => window.removeEventListener('agents-refresh', onAgentsRefresh)
  }, [reloadAgentList])

  useEffect(() => {
    if (!agentIdParam) return
    setSelectedAgentId(agentIdParam)
    getAgent(agentIdParam).then((agent) => {
      setAgents((prev) => {
        if (prev.some((a) => a.id === agent.id)) return prev
        return sortAgentsForChat([...prev, agent])
      })
    }).catch(() => {})
  }, [agentIdParam])

  useEffect(() => {
    if (!selectedAgent || hasContext || conversationId || convIdParam) return
    setMessages((prev) => {
      const welcomeOnly = prev.length <= 1 && prev.every((m) => m.role === 'assistant' && isWelcomeOnlyAssistant(m))
      if (!welcomeOnly) return prev
      const wb = prev[0]?.role === 'assistant'
        ? prev[0].ui_blocks?.find((b) => b.type === 'welcome_caps')
        : undefined
      if (wb?.data?.agent_id === selectedAgent.id && (wb.data.mount_tags as string[] | undefined)?.length) {
        return prev
      }
      return [{
        id: prev[0]?.id || nextId(),
        role: 'assistant',
        content: '',
        ui_blocks: [buildWelcomeCapsBlock(selectedAgent)],
        at: prev[0]?.at || new Date().toISOString(),
      }]
    })
  }, [selectedAgent, hasContext, conversationId, convIdParam])

  const handleAgentChange = (agentId: string) => {
    setSelectedAgentId(agentId)
    const q = new URLSearchParams(params)
    q.set('agent_id', agentId)
    if (conversationId) q.set('conversation_id', conversationId)
    if (taskId) q.set('task_id', taskId)
    if (diffId) q.set('difference_id', diffId)
    navigate(`/chat?${q.toString()}`, { replace: true })
    if (hasContext || conversationId) return
    const agent = chatAgents.find((a) => a.id === agentId)
    setMessages((prev) => {
      const rest = prev.filter(
        (m) => !(m.role === 'assistant' && m.ui_blocks?.some((b) => b.type === 'welcome_caps')),
      )
      return [...rest, {
        id: nextId(),
        role: 'assistant',
        content: '',
        ui_blocks: [buildWelcomeCapsBlock(agent)],
        at: new Date().toISOString(),
      }]
    })
    welcomeShownRef.current = true
  }

  useEffect(() => {
    if (taskId) getTask(taskId).then(setTask).catch(console.error)
    if (taskId && diffId) {
      getDifferences(taskId).then((ds) => setDiff(ds.find((d) => d.id === diffId) || null)).catch(console.error)
    } else {
      setDiff(null)
    }
  }, [taskId, diffId])

  useEffect(() => {
    if (!task || !diff) return
    setMessages((prev) => {
      let targetIdx = -1
      for (let i = prev.length - 1; i >= 0; i--) {
        const m = prev[i]
        if (m.role !== 'assistant' || !m.ui_blocks?.length) continue
        if (m.ui_blocks.some((b) => b.type === 'difference_explain')) break
        const plan = m.ui_blocks.find((b) => b.type === 'agent_plan')
        if (plan?.data?.intent === 'difference_explain') {
          targetIdx = i
          break
        }
      }
      if (targetIdx < 0) return prev
      const m = prev[targetIdx]
      if (m.role !== 'assistant') return prev
      const fixed = ensureDifferenceExplainUiBlocks(m.ui_blocks, task, diff, m.content)
      if (!fixed || fixed === m.ui_blocks) return prev
      const next = [...prev]
      next[targetIdx] = { ...m, ui_blocks: fixed as ChatUiBlock[] }
      return next
    })
  }, [task, diff])

  useEffect(() => {
    if (!convIdParam || newChatToken) {
      restoredConvRef.current = null
      if (!convIdParam) setConversationId(undefined)
      return
    }
    if (restoredConvRef.current === convIdParam) return
    const loadId = convIdParam
    restoredConvRef.current = convIdParam
    let cancelled = false
    getChatConversation(convIdParam).then((conv) => {
      if (cancelled || loadId !== convIdParam) return
      setConversationId(conv.id)
      const restored: Msg[] = []
      if (conv.difference_item_id) {
        restored.push({ id: nextId(), role: 'context' })
      }
      for (const m of conv.messages || []) {
        if (m.role === 'user') {
          restored.push({ id: nextId(), role: 'user', content: m.content, at: m.at })
        } else if (m.role === 'assistant') {
          let ui_blocks = m.ui_blocks as ChatUiBlock[] | undefined
          let content = m.content
          const dsIntro = ui_blocks?.find((b) => b.type === 'datasource_confirm')?.data?.intro
          if (dsIntro && String(content || '').trim() === String(dsIntro).trim()) {
            content = ''
          }
          if (ui_blocks?.some((b) => b.type === 'difference_explain') && String(content || '').trim().length < 140) {
            content = ''
          }
          restored.push({
            id: nextId(),
            role: 'assistant',
            content,
            ui_blocks,
            task_id: m.task_id,
            at: m.at,
          })
        }
      }
      setMessages(restored)
      welcomeShownRef.current = true
    }).catch((err: unknown) => {
      if (cancelled || loadId !== convIdParam) return
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        restoredConvRef.current = null
        setConversationId(undefined)
        setMessages([])
        welcomeShownRef.current = false
        const next = new URLSearchParams(params)
        next.delete('conversation_id')
        navigate({ pathname: '/chat', search: next.toString() ? `?${next}` : '' }, { replace: true })
        return
      }
      console.error(err)
    })
    return () => { cancelled = true }
  }, [convIdParam, newChatToken, navigate, params])

  useEffect(() => {
    if (convIdParam) return
    if (diff) {
      setMessages([{ id: nextId(), role: 'context' }])
      setConversationId(undefined)
      welcomeShownRef.current = true
    } else if (!conversationId && !welcomeShownRef.current) {
      setMessages((prev) => {
        const hasWelcome = prev.some(
          (m) => m.role === 'assistant' && m.ui_blocks?.some((b) => b.type === 'welcome_caps'),
        )
        if (hasWelcome) {
          welcomeShownRef.current = true
          return prev
        }
        welcomeShownRef.current = true
        return [{
          id: nextId(),
          role: 'assistant',
          content: '',
          ui_blocks: [buildWelcomeCapsBlock(selectedAgent)],
          at: new Date().toISOString(),
        }]
      })
    }
  }, [diff?.id, convIdParam, conversationId, selectedAgent])

  const scrollMessagesToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const el = messagesScrollRef.current
    if (!el) return
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior })
    })
  }, [])

  useEffect(() => {
    if (isLandingMode) return
    scrollMessagesToBottom(loading ? 'auto' : 'smooth')
  }, [messages, loading, isLandingMode, lastAssistantRowKey, scrollMessagesToBottom])

  useEffect(() => {
    if (isLandingMode || !loading) return
    const inner = messagesScrollRef.current?.firstElementChild
    if (!inner) return
    const ro = new ResizeObserver(() => scrollMessagesToBottom('auto'))
    ro.observe(inner)
    return () => ro.disconnect()
  }, [loading, isLandingMode, scrollMessagesToBottom])

  useEffect(() => {
    for (const m of messages) {
      if (m.role !== 'assistant') continue
      for (const b of m.ui_blocks || []) {
        if (b.type === 'reconciliation_result' && b.data.task_id) {
          resultShownRef.current.add(String(b.data.task_id))
        }
      }
    }
  }, [messages])

  const appendAssistant = (content: string, ui_blocks?: ChatUiBlock[], task_id?: string) => {
    const normalized = dedupeAssistantContent(normalizeAssistantContent(content, ui_blocks))
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (
        last?.role === 'assistant' &&
        (last.content || '').trim() === (normalized || '').trim() &&
        normalized.trim()
      ) {
        return prev
      }
      return [...prev, {
        id: nextId(),
        role: 'assistant',
        content: normalized,
        ui_blocks,
        task_id,
        at: new Date().toISOString(),
      }]
    })
  }

  const patchAssistant = useCallback((
    assistantId: string,
    patch: Partial<Extract<Msg, { role: 'assistant' }>>,
  ) => {
    setMessages((prev) => prev.map((m) => (
      m.id === assistantId && m.role === 'assistant' ? { ...m, ...patch } : m
    )))
  }, [])

  const summarizeToolCall = (evt: ChatStreamEvent): string => {
    if (evt.summary) return evt.summary
    const out = evt.output
    if (!out) return evt.success === false ? '执行失败' : '已完成'
    const err = typeof out.error === 'string' ? out.error : undefined
    if (err) return err
    const previewRaw = out.preview ?? out.output ?? out.result ?? out
    if (typeof previewRaw === 'string') {
      if (/Skill 执行失败|SkillExecutionFailed|error/i.test(previewRaw)) {
        return previewRaw.slice(0, 160)
      }
      const totalMatch = previewRaw.match(/"total"\s*:\s*(\d+)/)
      if (totalMatch) return `返回 ${totalMatch[1]} 条任务`
      if (previewRaw.length > 80) return '执行完成'
    }
    const preview = previewRaw as Record<string, unknown>
    if (typeof preview === 'object' && preview) {
      if ('count' in preview) return `返回 ${String(preview.count)} 条结果`
      const nested = preview.result as Record<string, unknown> | undefined
      if (nested && typeof nested.total === 'number') {
        return `返回 ${nested.total} 条任务`
      }
    }
    return evt.success === false ? '执行失败' : 'Skill 执行完成'
  }

  type SendContextOverride = { taskId?: string; diffId?: string }

  const runStreamTurn = async (
    msg: string,
    history: Array<{ role: string; content: string }>,
    effectiveTaskId: string | undefined,
    effectiveDiffId: string | undefined,
    inferredAction: string | undefined,
    assistantId: string,
  ) => {
    let reply = ''
    let uiBlocks: ChatUiBlock[] | undefined
    let taskIdOut: string | undefined
    let conversationIdOut: string | undefined
    const trace: ChatAgentTraceItem[] = []

    const upsertTrace = () => patchAssistant(assistantId, { agent_trace: [...trace], content: reply })

    await streamChatTurn({
      message: msg,
      history,
      task_id: effectiveTaskId,
      difference_item_id: effectiveDiffId,
      conversation_id: conversationId,
      agent_id: selectedAgentId,
      client_action: inferredAction,
    }, (evt) => {
      if (evt.type === 'session' && evt.conversation_id) {
        conversationIdOut = evt.conversation_id
        setConversationId(evt.conversation_id)
      }
      if (evt.type === 'thinking' && evt.content) {
        const last = trace[trace.length - 1]
        if (last?.kind === 'thinking') {
          last.content = `${last.content}\n${evt.content}`
        } else {
          trace.push({ id: nextId(), kind: 'thinking', content: evt.content })
        }
        upsertTrace()
      }
      if (evt.type === 'tool_call') {
        const skillId = evt.skill_id || ''
        const summary = summarizeToolCall(evt)
        const last = trace[trace.length - 1]
        if (
          last?.kind === 'tool_call'
          && last.skillId === skillId
          && !last.output
          && evt.output
        ) {
          last.summary = summary
          last.success = evt.success !== false
          last.output = evt.output
        } else if (
          trace.some((t) => t.kind === 'tool_call' && t.skillId === skillId && t.output)
        ) {
          /* 同一 Skill 已记录完成结果，跳过重复事件 */
        } else if (!evt.output) {
          /* 仅 start 事件：暂不入 trace，等待 end 合并 */
        } else {
          trace.push({
            id: nextId(),
            kind: 'tool_call',
            skillId,
            skillName: evt.skill_name || skillId,
            summary,
            success: evt.success !== false,
            input: evt.input,
            output: evt.output,
          })
        }
        upsertTrace()
      }
      if (evt.type === 'plan' && evt.steps?.length) {
        const planBlock: ChatUiBlock = {
          type: 'agent_plan',
          data: { steps: evt.steps, intent: evt.intent || 'dialog' },
        }
        const rest = (uiBlocks || []).filter((b) => b.type !== 'agent_plan')
        uiBlocks = [...rest, planBlock]
        patchAssistant(assistantId, { ui_blocks: uiBlocks, agent_trace: [...trace], content: reply })
      }
      if (evt.type === 'ui_blocks' && evt.blocks?.length) {
        uiBlocks = evt.blocks as ChatUiBlock[]
      }
      if (evt.type === 'reply' && evt.content) {
        reply = evt.content
        patchAssistant(assistantId, { content: reply, agent_trace: [...trace] })
      }
      if (evt.type === 'done') {
        taskIdOut = evt.task_id
      }
      if (evt.type === 'error') {
        reply = evt.error || '对话出错'
        patchAssistant(assistantId, { content: reply })
      }
    })

    let blocks = ensureDifferenceExplainUiBlocks(
      uiBlocks,
      task,
      diff,
      reply,
    ) as ChatUiBlock[] | undefined
    const thinkingText = trace
      .filter((t): t is Extract<ChatAgentTraceItem, { kind: 'thinking' }> => t.kind === 'thinking')
      .map((t) => t.content)
      .join('\n')
      .trim()
    const dedupedReply = dedupeTraceFromReply(reply, trace)
    const hasCapabilityUi = blocks?.some(
      (b) => b.type === 'agent_capability_overview' || b.type === 'capability_list',
    )
    const rawReply = (dedupedReply || reply).trim()
    const hasSkillResultUi = blocks?.some(
      (b) => b.type === 'task_detail' || b.type === 'skill_invoke' || b.type === 'task_list',
    )
    let finalContent = stripMarkdownTables(rawReply || thinkingText || '（暂无回复）')
    if (hasCapabilityUi && (!rawReply || looksLikeMarkdownSkillDump(rawReply))) {
      finalContent = stripMarkdownTables(rawReply).slice(0, 200) || ''
    } else if (hasSkillResultUi && looksLikeMarkdownSkillDump(rawReply)) {
      finalContent = ''
    } else {
      finalContent = finalContent.trim() || '（暂无回复）'
    }

    const hasPlan = blocks?.some((b) => b.type === 'agent_plan')
    patchAssistant(assistantId, {
      content: finalContent,
      ui_blocks: blocks?.length ? blocks : undefined,
      task_id: taskIdOut,
      agent_trace: hasPlan ? undefined : (trace.length ? trace : undefined),
    })
    return {
      reply,
      uiBlocks: blocks,
      taskId: taskIdOut,
      conversationId: conversationIdOut,
    }
  }

  const sendingRef = useRef(false)
  const send = async (text?: string, clientAction?: string, ctx?: SendContextOverride) => {
    const msg = text || input.trim()
    if (!msg || loading || sendingRef.current) return
    sendingRef.current = true
    setInput('')
    const now = new Date().toISOString()
    const userMsg: Msg = { id: nextId(), role: 'user', content: msg, at: now }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)
    try {
      const history = [...messages, userMsg]
        .filter((m): m is Extract<Msg, { role: 'user' | 'assistant' }> => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({ role: m.role, content: m.content }))
      const effectiveTaskId = ctx?.taskId ?? resolveChatTaskId(taskId, [...messages, userMsg])
      const effectiveDiffId = ctx?.diffId ?? diffId
      const inferredAction = clientAction
        || (!hasContext && !effectiveDiffId && shouldOfferReconciliationUi(msg) ? 'start_reconciliation' : undefined)
      const isReconCard = !hasContext && inferredAction === 'start_reconciliation'

      if (isReconCard) {
        const opts = await getChatReconciliationOptions(selectedAgentId)
        const period = inferReconciliationPeriod(msg)
        const localIntro = datasourceConfirmIntro(period)
        const blocks = [buildDatasourceConfirmBlock(opts, period, localIntro, selectedAgentId)] as ChatUiBlock[]
        const data = await chatWithContext({
          message: msg,
          history,
          task_id: effectiveTaskId,
          difference_item_id: effectiveDiffId,
          conversation_id: conversationId,
          agent_id: selectedAgentId,
          client_action: 'start_reconciliation',
        })
        if (data.conversation_id) {
          setConversationId(data.conversation_id)
          const q = new URLSearchParams()
          const tid = data.task_id || effectiveTaskId
          if (tid) q.set('task_id', tid)
          if (effectiveDiffId) q.set('difference_id', effectiveDiffId)
          q.set('conversation_id', data.conversation_id)
          navigate(`/chat?${q.toString()}`, { replace: true })
        }
        const finalBlocks = (data.ui_blocks?.length ? data.ui_blocks : blocks) as ChatUiBlock[]
        if (finalBlocks[0]?.type === 'datasource_confirm') {
          finalBlocks[0].data.intro = String(
            finalBlocks[0].data.intro || data.reply || blocks[0].data.intro || localIntro,
          )
        }
        appendAssistant(data.reply || localIntro, finalBlocks, data.task_id)
        window.dispatchEvent(new Event('chat-history-refresh'))
        return
      }

      const assistantId = nextId()
      setMessages((prev) => [...prev, {
        id: assistantId,
        role: 'assistant',
        content: '',
        agent_trace: [],
        at: new Date().toISOString(),
      }])

      const streamed = await runStreamTurn(
        msg, history, effectiveTaskId, effectiveDiffId, inferredAction, assistantId,
      )
      const convId = streamed.conversationId || conversationId
      if (convId) {
        const q = new URLSearchParams()
        const tid = streamed.taskId || effectiveTaskId
        if (tid) q.set('task_id', tid)
        if (effectiveDiffId) q.set('difference_id', effectiveDiffId)
        q.set('conversation_id', convId)
        navigate(`/chat?${q.toString()}`, { replace: true })
      }
      const boundTaskId = effectiveTaskId || taskId
      const boundDiffId = effectiveDiffId || diffId
      if (boundTaskId && boundDiffId && streamed.uiBlocks?.some((b) => b.type === 'difference_explain')) {
        getDifferences(boundTaskId)
          .then((ds) => setDiff(ds.find((d) => d.id === boundDiffId) || null))
          .catch(console.error)
      }
      window.dispatchEvent(new Event('chat-history-refresh'))
    } catch {
      appendAssistant('请求失败，请确认后端已启动。')
    } finally {
      setLoading(false)
      sendingRef.current = false
    }
  }

  const handleExecuted = (reply: string, blocks: ChatUiBlock[], task_id?: string) => {
    setMessages((prev) => [...prev, {
      id: nextId(),
      role: 'user',
      content: '使用推荐方案进行对账分析',
      at: new Date().toISOString(),
    }])
    appendAssistant('', blocks, task_id)
    window.dispatchEvent(new Event('chat-history-refresh'))
  }

  const handleTaskCompleted = async (completedTaskId: string) => {
    if (resultShownRef.current.has(completedTaskId)) return
    resultShownRef.current.add(completedTaskId)

    try {
      const [task, diffs] = await Promise.all([
        getTask(completedTaskId),
        getDifferences(completedTaskId),
      ])
      const pending = diffs.filter((d) => ['pending_review', 'identified'].includes(d.status))
      const lead = diffs.length > 0
        ? `对账分析已完成。共识别 ${diffs.length} 条差异${pending.length ? `，其中 ${pending.length} 条待复核` : ''}，详情如下：`
        : '对账分析已完成，本次核对未发现差异。'
      appendAssistant(
        lead,
        [
          buildReconciliationResultBlock(task, diffs) as ChatUiBlock,
          buildReviewPromptBlock(completedTaskId, pending.length) as ChatUiBlock,
        ],
        completedTaskId,
      )
      window.dispatchEvent(new Event('chat-history-refresh'))
    } catch {
      appendAssistant('对账已完成，但加载结果摘要失败，请点击任务详情查看。', undefined, completedTaskId)
    }
  }

  const handleStartReview = async (reviewTaskId: string) => {
    setMessages((prev) => [...prev, {
      id: nextId(),
      role: 'user',
      content: '现在开始复核差异',
      at: new Date().toISOString(),
    }])
    try {
      const diffs = await getDifferences(reviewTaskId)
      const pending = diffs.filter((d) => ['pending_review', 'identified'].includes(d.status))
      if (!pending.length) {
        appendAssistant('所有差异已复核完毕，可前往任务详情继续后续验证与报告输出。', undefined, reviewTaskId)
        return
      }
      appendAssistant(
        `好的，我们从第 1 条开始。共 ${pending.length} 条待复核，您可在此确认或退回，也可随时打开任务详情进行完整复核。`,
        [buildReviewInlineBlock(reviewTaskId, pending[0], 1, pending.length) as ChatUiBlock],
        reviewTaskId,
      )
    } catch {
      appendAssistant('加载差异列表失败，请从任务详情进入复核。')
    }
  }

  const handleReviewDone = async (reviewTaskId: string) => {
    try {
      const diffs = await getDifferences(reviewTaskId)
      const pending = diffs.filter((d) => ['pending_review', 'identified'].includes(d.status))
      if (!pending.length) {
        appendAssistant(
          '本批差异已全部复核完毕。如需审批流转与再次验证，请前往任务详情继续操作。',
          undefined,
          reviewTaskId,
        )
        return
      }
      const reviewed = diffs.length - pending.length
      appendAssistant(
        `已处理 ${reviewed} 条，还剩 ${pending.length} 条待复核。继续下一条：`,
        [buildReviewInlineBlock(reviewTaskId, pending[0], reviewed + 1, diffs.length) as ChatUiBlock],
        reviewTaskId,
      )
    } catch {
      appendAssistant('刷新差异状态失败，请稍后重试。')
    }
  }

  const handleDiffFeedbackDone = async (
    feedbackDiffId: string,
    action: 'confirm' | 'question' | 'correct',
  ) => {
    const statusAfter = action === 'confirm' ? 'confirmed' : 'pending_review'
    setMessages((prev) => prev.map((m) => {
      if (m.role !== 'assistant' || !m.ui_blocks?.length) return m
      let touched = false
      const ui_blocks = m.ui_blocks.map((b) => {
        if (b.type !== 'difference_explain') return b
        if (String(b.data?.difference_id || '') !== feedbackDiffId) return b
        touched = true
        return {
          ...b,
          data: { ...b.data, status: statusAfter },
        }
      })
      return touched ? { ...m, ui_blocks } : m
    }))

    const tid = taskId || resolveChatTaskId(undefined, messages)
    if (tid) {
      try {
        const ds = await getDifferences(tid)
        const row = ds.find((d) => d.id === feedbackDiffId)
        if (row && (diffId === feedbackDiffId || diff?.id === feedbackDiffId)) {
          setDiff(row)
        }
      } catch {
        /* ignore refresh errors */
      }
    }
  }

  useEffect(() => {
    if (quickPrompt && !quickSentRef.current) {
      quickSentRef.current = true
      const t = setTimeout(() => { send(quickPrompt) }, 300)
      return () => clearTimeout(t)
    }
  }, [quickPrompt])

  const agentDesc = selectedAgent?.description?.trim()
    || '帮您查任务、解释差异、发起核对，并可引导进入正式收入核对流程。'

  const composer = (
    <div className={isLandingMode ? 'chat-fs-landing__composer' : 'chat-fs-composer-inner chat-fs-composer-inner--wide'}>
      <div className={`chat-fs-chips${isLandingMode ? ' chat-fs-chips--landing' : ''}`}>
        {chips.map((chip) => (
          <button
            key={chip.label}
            type="button"
            className="chat-fs-chip"
            disabled={loading}
            onClick={() => send(chip.prompt, chip.action)}
          >
            {chip.label}
          </button>
        ))}
      </div>
      <div className={`chat-fs-input-box chat-fs-input-box--compact${isLandingMode ? ' chat-fs-input-box--landing' : ''}`}>
        <textarea
          className="chat-fs-textarea"
          placeholder={isLandingMode ? '输入问题…（Enter 发送，Shift+Enter 换行）' : '输入问题，Enter 发送，Shift+Enter 换行'}
          value={input}
          rows={isLandingMode ? 2 : 1}
          disabled={loading}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        <div className="chat-fs-input-bar chat-fs-input-bar--with-agent">
          {!hasContext && chatAgents.length > 0 && (
            <ChatAgentPicker
              agents={chatAgents}
              value={selectedAgentId}
              onChange={handleAgentChange}
              disabled={loading}
            />
          )}
          <div className="chat-fs-input-bar__actions">
            <Button
              type="primary"
              className="chat-fs-send chat-fs-send--labeled"
              icon={<ArrowUpOutlined />}
              loading={loading}
              onClick={() => send()}
            >
              发送
            </Button>
          </div>
        </div>
      </div>
    </div>
  )

  return (
    <div className={`chat-fullscreen${isLandingMode ? ' chat-fullscreen--landing' : ''}`}>
      {!isLandingMode && (
      <header className="chat-fs-header chat-fs-header--compact">
        <div className="chat-fs-header-title">
          <h1>{hasContext ? '收入差异解释' : (selectedAgent?.name || '收入核对助手')}</h1>
          {hasContext && diff && (
            <p>{task?.name || '核对任务'} · {diff.business_key} · {diff.type}</p>
          )}
        </div>
        <div className="chat-fs-header-actions">
          <Link to="/agents"><Button type="text" size="small">智能体中心</Button></Link>
          {taskId && (
            <Link to={`/workbench/reconciliation/tasks/${taskId}`}>
              <Button type="text" size="small" icon={<ArrowLeftOutlined />}>返回任务</Button>
            </Link>
          )}
        </div>
      </header>
      )}

      {isLandingMode ? (
        <div className="chat-fs-landing">
          <div className="chat-fs-landing__top">
            <div className="chat-fs-landing__inner chat-fs-landing__inner--intro">
              <div className="chat-fs-landing__hero">
                <img
                  className="chat-fs-landing__avatar"
                  src={assistantAvatarSrc || avatarImageUrl('anime-04')}
                  alt=""
                />
                <h2 className="chat-fs-landing__title">{selectedAgent?.name || '收入核对助手'}</h2>
                <p className="chat-fs-landing__desc">{agentDesc}</p>
              </div>
              <ChatWelcomeCaps
                data={welcomeBlockData}
                layout="landing"
                onCapAction={(prompt, clientAction) => { void send(prompt, clientAction) }}
                disabled={loading}
              />
            </div>
          </div>
          <div className="chat-fs-landing__bottom">
            {composer}
          </div>
        </div>
      ) : (
      <div className="chat-fs-body chat-fs-body--wide">
        <div className="chat-fs-messages" ref={messagesScrollRef}>
          <div className="chat-fs-messages-inner chat-fs-messages-inner--wide">
            {displayMessages.map((m, idx) => {
              const rowKey = `${m.id}-${idx}`
              if (m.role === 'context' && diff) {
                return (
                  <div key={rowKey} className="chat-fs-row chat-fs-row--assistant chat-fs-row--cards">
                    <ChatAvatar role="assistant" assistantSrc={assistantAvatarSrc} />
                    <div className="chat-fs-cards-wrap">
                      <DiffContextCard diff={diff} task={task} aiMode={aiMode} />
                    </div>
                  </div>
                )
              }
              if (m.role === 'user') {
                return (
                  <div key={rowKey} className="chat-fs-row chat-fs-row--user">
                    <UserMessageStack content={m.content} time={m.at} />
                    <ChatAvatar role="user" />
                  </div>
                )
              }
              if (m.role === 'assistant') {
                if (isWelcomeOnlyAssistant(m)) return null
                const anchorLastAssistant = rowKey === lastAssistantRowKey
                const hasRichAssistant = (m.ui_blocks?.length ?? 0) > 0 || (m.agent_trace?.length ?? 0) > 0
                return (
                  <div
                    key={rowKey}
                    className={`chat-fs-row chat-fs-row--assistant ${hasRichAssistant ? 'chat-fs-row--rich' : ''}`}
                  >
                    <ChatAvatar role="assistant" assistantSrc={assistantAvatarSrc} />
                    <div
                      className={`chat-fs-bubble-wrap chat-fs-bubble-wrap--assistant${hasRichAssistant ? ' chat-fs-bubble-wrap--wide' : ''}`}
                    >
                      <AiAssistantMessage
                        content={m.content}
                        diff={diff}
                        ui_blocks={m.ui_blocks}
                        conversationId={conversationId}
                        agentId={selectedAgentId}
                        executionTrace={m.agent_trace}
                        streamingTrace={loading && anchorLastAssistant && !m.content?.trim()}
                        onExecuted={handleExecuted}
                        onTaskCompleted={handleTaskCompleted}
                        onStartReview={handleStartReview}
                        onReviewDone={handleReviewDone}
                        onDiffFeedbackDone={(id, action) => { void handleDiffFeedbackDone(id, action) }}
                        onQuickAction={(prompt, clientAction) => send(prompt, clientAction)}
                        onClarifyPick={(tid, did) => {
                          const q = new URLSearchParams()
                          q.set('task_id', tid)
                          q.set('difference_id', did)
                          if (conversationId) q.set('conversation_id', conversationId)
                          navigate(`/chat?${q.toString()}`, { replace: true })
                          void send(
                            '请解释这条差异的归因原因与处理建议',
                            'explain_difference',
                            { taskId: tid, diffId: did },
                          )
                        }}
                        disabled={loading}
                        time={m.at}
                      />
                    </div>
                  </div>
                )
              }
              return null
            })}
            {loading && !displayMessages.some(
              (m) => m.role === 'assistant' && m.agent_trace !== undefined && !m.content?.trim(),
            ) && (
              <div className="chat-fs-row chat-fs-row--assistant">
                <ChatAvatar role="assistant" assistantSrc={assistantAvatarSrc} />
                <div className="chat-fs-bubble-wrap chat-fs-bubble-wrap--assistant">
                  <div className="chat-fs-bubble chat-fs-bubble--assistant chat-fs-bubble--compact chat-fs-bubble--typing">
                    <span className="chat-fs-dot" /><span className="chat-fs-dot" /><span className="chat-fs-dot" />
                  </div>
                </div>
              </div>
            )}
            <div aria-hidden className="chat-fs-messages-anchor" />
          </div>
        </div>
      </div>
      )}

      {!isLandingMode && (
      <footer className="chat-fs-composer">
        {composer}
      </footer>
      )}
    </div>
  )
}
