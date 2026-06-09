import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Alert, Button, Card, Col, Descriptions, Drawer, Input, Modal, Popconfirm, Popover, Row,
  Select, Space, Statistic, Table, Tabs, Tag, Timeline, Typography, message,
} from 'antd'
import {
  QuestionCircleOutlined, PlusOutlined, LinkOutlined,
  DeleteOutlined, CommentOutlined, RobotOutlined,
  SendOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ExperimentOutlined, ThunderboltOutlined, DatabaseOutlined,
  BookOutlined, BranchesOutlined,
} from '@ant-design/icons'
import {
  adminAgentLifecycle, chatWithContext, deleteAdminAgent, getAdminAgentInsights,
  getAdminAgentRunDetail, getAdminAgentStats, getAdminBusinessCenters, getAdminSkills,
  listAdminAgentRuns, listAdminAgents, shouldOfferReconciliationUi, type AgentConfigItem,
} from '../api/client'
import { AiAssistantMessage, type ChatUiBlock } from './ChatActionCards'
import AdminAgentWizard from './AdminAgentWizard'
import { CatalogToolbar } from './CatalogToolbar'
import { dedupeAssistantContent } from '../utils/parseAssistantReply'
import { formatApiError } from '../api/errors'
import { avatarImageUrl, resolveAvatarId } from '../utils/agentAvatars'

const { Text } = Typography

/** 平台种子 Agent，不可删除 */
const PROTECTED_AGENT_ID = 'agent-revenue-diff-explain'

const STATUS_MAP: Record<string, { label: string; tone: string }> = {
  draft: { label: '草稿', tone: 'draft' },
  pending_review: { label: '待审核', tone: 'review' },
  published: { label: '已发布', tone: 'published' },
  offline: { label: '已下架', tone: 'offline' },
}

function isMyAgent(agent: AgentConfigItem, userId?: string) {
  if (agent.scope === 'personal') return true
  if (userId && agent.owner_id === userId) return true
  return false
}

const ASSET_LAYERS = ['Skill库', '知识库', '规则引擎', '本体翻译', '数据接入', '大模型']

const ASSET_MOUNT_HELP = `Agent ← 挂载 → 中台资产（仅授权引用）
├─ Skills          → Skill库
├─ KnowledgeBases  → 知识库
├─ DataSources     → 数据接入层
├─ Ontology        → 本体翻译 / 规则
├─ ModelRoute      → 大模型管理
└─ LinkedWorkflow  → 已发布 Workflow（引导进入正式任务）`

const PERMISSION_HELP = (
  <ul className="admin-agent-help-list">
    <li><strong>超管</strong>：管理所有 Agent、全部日志、审核发布</li>
    <li><strong>Agent 管理员</strong>：模板、审核、监控</li>
    <li><strong>团队长</strong>：本团队 Agent、审批发布</li>
    <li><strong>用户</strong>：个人 Agent、使用已发布 Agent</li>
  </ul>
)

const COMPLIANCE_HELP = (
  <ul className="admin-agent-help-list">
    <li>高风险 Skill（删除/修改/外发）需二次确认</li>
    <li>对话记录金额/账号自动脱敏</li>
    <li>调用频率限制防刷</li>
    <li>数据隔离：仅访问授权数据范围</li>
  </ul>
)

function HoverHelp({
  label,
  title,
  children,
  wide,
}: {
  label: string
  title: string
  children: ReactNode
  wide?: boolean
}) {
  return (
    <Popover
      title={title}
      content={<div className="admin-agent-help-pop">{children}</div>}
      trigger="hover"
      placement="bottom"
      overlayClassName={wide ? 'admin-agent-help-overlay admin-agent-help-overlay--wide' : 'admin-agent-help-overlay'}
    >
      <button type="button" className="admin-agent-help-trigger">
        <span>{label}</span>
        <QuestionCircleOutlined />
      </button>
    </Popover>
  )
}

function PanoramaHelpContent() {
  return (
    <div className="admin-agent-panorama admin-agent-panorama--popover">
      <div className="admin-agent-panorama__pillars">
        <div className="admin-agent-panorama__pillar">
          <strong>Agent 配置</strong>
          <span>创建阶段 · 闭环①</span>
        </div>
        <div className="admin-agent-panorama__pillar">
          <strong>Agent 运营</strong>
          <span>运行阶段 · 闭环②③</span>
        </div>
        <div className="admin-agent-panorama__pillar">
          <strong>Agent 治理</strong>
          <span>管理阶段 · 闭环④</span>
        </div>
      </div>
      <div className="admin-agent-panorama__connector" />
      <div className="admin-agent-panorama__assets-label">全部挂载在中台能力资产之上（Agent 仅授权引用，不拥有资产）</div>
      <div className="admin-agent-panorama__assets">
        {ASSET_LAYERS.map((layer) => (
          <span key={layer} className="admin-agent-panorama__asset-chip">{layer}</span>
        ))}
      </div>
    </div>
  )
}

function AgentPageHelpBar() {
  return (
    <div className="admin-agent-help-bar">
      <Text type="secondary" className="admin-agent-help-bar__hint">说明</Text>
      <HoverHelp label="管理全景" title="Agent 管理全景" wide>
        <PanoramaHelpContent />
      </HoverHelp>
      <HoverHelp label="资产关联" title="与中台资产关联">
        <pre className="admin-agent-panorama__mono">{ASSET_MOUNT_HELP}</pre>
      </HoverHelp>
      <HoverHelp label="权限层级" title="权限层级">
        {PERMISSION_HELP}
      </HoverHelp>
      <HoverHelp label="安全合规" title="安全与合规">
        {COMPLIANCE_HELP}
      </HoverHelp>
    </div>
  )
}

function AssetMountsPanel({ mounts }: { mounts?: AgentConfigItem['asset_mounts'] }) {
  if (!mounts) return <Text type="secondary">保存后展示挂载关系</Text>
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="Skill 库">
          {(mounts.skills || []).map((s) => (
            <Tag key={s.id}>{s.name} ({s.type || 'capability'})</Tag>
          ))}
        </Descriptions.Item>
        <Descriptions.Item label="知识库">
          {(mounts.knowledge_bases || []).map((k) => <Tag key={k.id}>{k.name}</Tag>)}
        </Descriptions.Item>
        <Descriptions.Item label="数据接入">
          {(mounts.data_sources || []).length
            ? mounts.data_sources.map((d) => <Tag key={d.id}>{d.name}</Tag>)
            : <Text type="secondary">继承角色 / 未单独指定</Text>}
        </Descriptions.Item>
        <Descriptions.Item label="本体翻译">
          {(mounts.ontology || []).map((o) => <Tag key={o.id}>{o.name}</Tag>)}
        </Descriptions.Item>
        <Descriptions.Item label="模型路由">
          simple → {mounts.model_route?.simple || '—'}；complex → {mounts.model_route?.complex || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="关联 Workflow">
          {mounts.linked_workflow || '未绑定'}
        </Descriptions.Item>
      </Descriptions>
    </Space>
  )
}

/* ─────────────────────────────────────────────────
   Agent 测试面板：左侧对话 + 右侧资产调用审计
   ───────────────────────────────────────────────── */

type ChatMsg = {
  role: 'user' | 'assistant'
  content: string
  ts: number
  ui_blocks?: ChatUiBlock[]
  task_id?: string
}
type AssetCall = {
  ts: number
  type: 'skill' | 'knowledge' | 'model' | 'datasource' | 'workflow' | 'permission'
  label: string
  detail: string
  ok: boolean
}

function AgentTestPanel({ agent }: { agent: AgentConfigItem }) {
  const [inputVal, setInputVal] = useState('')
  const [chatHistory, setChatHistory] = useState<ChatMsg[]>([])
  const [assetCalls, setAssetCalls] = useState<AssetCall[]>([])
  const [sending, setSending] = useState(false)
  const [convId, setConvId] = useState<string | undefined>(undefined)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const selectedAgent = agent.id

  useEffect(() => {
    if (chatEndRef.current) chatEndRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [chatHistory])

  const parsePlanSteps = (steps: Array<{ thought: string; action: string; observation: string }>) => {
    const calls: AssetCall[] = []
    const now = Date.now()

    for (const step of steps) {
      const action = step.action || ''
      const thought = step.thought || ''

      if (action.startsWith('call_skill:')) {
        const skillName = action.replace('call_skill:', '')
        calls.push({
          ts: now, type: 'skill', label: skillName,
          detail: step.observation || thought,
          ok: !thought.includes('授权校验'),
        })
      } else if (action === 'permission_denied') {
        calls.push({
          ts: now, type: 'permission', label: '授权拒绝',
          detail: thought, ok: false,
        })
      } else if (action.startsWith('retrieve_kb:')) {
        const kbIds = action.replace('retrieve_kb:', '')
        calls.push({
          ts: now, type: 'knowledge', label: `知识库: ${kbIds}`,
          detail: step.observation || '', ok: true,
        })
      } else if (action === 'model_route') {
        calls.push({
          ts: now, type: 'model', label: thought,
          detail: step.observation?.substring(0, 100) || '', ok: true,
        })
      } else if (action === 'datasource_confirm') {
        calls.push({
          ts: now, type: 'datasource', label: '数据源确认',
          detail: step.observation || '', ok: true,
        })
      } else if (action === 'workflow_guide') {
        calls.push({
          ts: now, type: 'workflow', label: 'Workflow 流程加载',
          detail: step.observation || '', ok: true,
        })
      } else if (action === 'classify_intent' || action.startsWith('classify_intent_')) {
        const viaLlm = action === 'classify_intent_llm'
        const viaRules = action === 'classify_intent_rules'
        calls.push({
          ts: now,
          type: 'skill',
          label: viaLlm ? '意图识别（大模型）' : viaRules ? '意图识别（规则回退）' : '意图识别',
          detail: step.observation || '',
          ok: true,
        })
      } else if (action === 'render_ui') {
        calls.push({
          ts: now, type: 'skill', label: 'UI 渲染',
          detail: step.observation || thought, ok: true,
        })
      }
    }
    return calls
  }

  const traceFromUiBlocks = (blocks: ChatUiBlock[]) => {
    const now = Date.now()
    const calls: AssetCall[] = []
    for (const b of blocks) {
      if (b.type === 'agent_plan') continue
      if (b.type === 'datasource_confirm') {
        calls.push({
          ts: now, type: 'datasource', label: '数据源确认卡片',
          detail: `周期 ${String(b.data.period || '—')}`, ok: true,
        })
      } else if (b.type === 'task_list') {
        calls.push({ ts: now, type: 'skill', label: 'query_tasks', detail: '任务列表卡片', ok: true })
      } else if (b.type === 'task_progress') {
        calls.push({
          ts: now, type: 'workflow', label: 'Workflow 执行',
          detail: String(b.data.task_id || b.data.name || ''), ok: true,
        })
      } else if (b.type === 'capability_list') {
        calls.push({
          ts: now, type: 'skill', label: '能力清单',
          detail: String(b.data.title || ''), ok: true,
        })
      } else if (b.type === 'faq_workflow') {
        calls.push({ ts: now, type: 'workflow', label: '流程说明卡片', detail: '', ok: true })
      } else if (b.type === 'reconciliation_result') {
        calls.push({ ts: now, type: 'workflow', label: '对账结果', detail: '差异汇总', ok: true })
      } else if (b.type === 'quick_actions') {
        calls.push({ ts: now, type: 'skill', label: '快捷操作', detail: '交互入口', ok: true })
      }
    }
    return calls
  }

  const appendAssetTraces = (
    planSteps?: Array<{ thought: string; action: string; observation: string }>,
    uiBlocks?: ChatUiBlock[],
  ) => {
    const batch: AssetCall[] = []
    if (planSteps?.length) batch.push(...parsePlanSteps(planSteps))
    if (uiBlocks?.length) batch.push(...traceFromUiBlocks(uiBlocks))
    if (batch.length) setAssetCalls((prev) => [...batch, ...prev])
  }

  const sendMessage = useCallback(async (text?: string, clientAction?: string) => {
    const msg = (text ?? inputVal).trim()
    if (!msg || sending) return

    const userMsg: ChatMsg = { role: 'user', content: msg, ts: Date.now() }
    setChatHistory((prev) => [...prev, userMsg])
    if (!text) setInputVal('')
    setSending(true)

    try {
      const history = [...chatHistory, userMsg].map((m) => ({ role: m.role, content: m.content }))
      const res = await chatWithContext({
        message: msg,
        history,
        agent_id: selectedAgent,
        conversation_id: convId,
        client_action: clientAction || (shouldOfferReconciliationUi(msg) ? 'start_reconciliation' : undefined),
      })

      const blocks = (res.ui_blocks || []) as ChatUiBlock[]
      const assistantMsg: ChatMsg = {
        role: 'assistant',
        content: dedupeAssistantContent(res.reply || ''),
        ts: Date.now(),
        ui_blocks: blocks.length ? blocks : undefined,
        task_id: res.task_id,
      }
      setChatHistory((prev) => [...prev, assistantMsg])
      if (res.conversation_id) setConvId(res.conversation_id)
      appendAssetTraces(res.plan_steps, blocks)
    } catch (e) {
      setChatHistory((prev) => [...prev, {
        role: 'assistant',
        content: `调用失败: ${formatApiError(e)}`,
        ts: Date.now(),
      }])
    } finally {
      setSending(false)
    }
  }, [chatHistory, convId, inputVal, selectedAgent, sending])

  const handleSend = () => { void sendMessage() }

  const handleExecuted = (reply: string, blocks: ChatUiBlock[], taskId?: string) => {
    setChatHistory((prev) => [
      ...prev,
      { role: 'user', content: '确认数据源并发起对账', ts: Date.now() },
      {
        role: 'assistant',
        content: reply || '',
        ts: Date.now(),
        ui_blocks: blocks.length ? blocks : undefined,
        task_id: taskId,
      },
    ])
    setAssetCalls((prev) => [{
      ts: Date.now(),
      type: 'workflow',
      label: '执行对账 Workflow',
      detail: taskId ? `task_id=${taskId}` : '已触发',
      ok: true,
    }, ...prev])
    if (blocks.length) {
      setAssetCalls((prev) => [...traceFromUiBlocks(blocks), ...prev])
    }
  }

  const handleTaskCompleted = (taskId: string) => {
    setAssetCalls((prev) => [{
      ts: Date.now(),
      type: 'workflow',
      label: '对账任务完成',
      detail: taskId,
      ok: true,
    }, ...prev])
  }

  const handleClear = () => { setChatHistory([]); setAssetCalls([]); setConvId(undefined) }

  const ASSET_ICON: Record<string, ReactNode> = {
    skill: <ThunderboltOutlined />,
    knowledge: <BookOutlined />,
    model: <RobotOutlined />,
    datasource: <DatabaseOutlined />,
    workflow: <BranchesOutlined />,
    permission: <CloseCircleOutlined />,
  }

  const ASSET_COLOR: Record<string, string> = {
    skill: '#f97316', knowledge: '#8b5cf6', model: '#3b82f6',
    datasource: '#10b981', workflow: '#6366f1', permission: '#ef4444',
  }

  const agentAvatarSrc = avatarImageUrl(resolveAvatarId(agent))
  const agentName = agent.name || 'Agent'

  const boundAssets = useMemo(() => {
    const items: Array<{ type: string; label: string; id: string }> = []
    for (const sid of agent.allowed_skill_ids || []) {
      items.push({ type: 'skill', label: sid.replace(/^skill-/, ''), id: sid })
    }
    for (const kid of agent.knowledge_base_ids || []) {
      items.push({ type: 'knowledge', label: kid, id: kid })
    }
    for (const ds of agent.data_source_scope || []) {
      items.push({ type: 'datasource', label: ds, id: ds })
    }
    if (agent.linked_workflow_id) {
      items.push({ type: 'workflow', label: agent.linked_workflow_id, id: agent.linked_workflow_id })
    }
    if (agent.model_route) {
      for (const [k, v] of Object.entries(agent.model_route)) {
        items.push({ type: 'model', label: `${k}: ${v}`, id: k })
      }
    }
    return items
  }, [agent])

  return (
    <div className="agent-test-panel agent-test-panel--modal">
      <div className="agent-test-toolbar">
        <img src={agentAvatarSrc} className="agent-test-toolbar__avatar" alt="" />
        <span className="agent-test-toolbar__name">{agentName}</span>
        <Button size="small" onClick={handleClear}>清空</Button>
        {convId && (
          <Tag color="blue" style={{ marginLeft: 'auto', fontSize: 11 }}>{convId.slice(0, 8)}</Tag>
        )}
      </div>

      <div className="agent-test-body">
        <div className="agent-test-chat">
          <div className="agent-test-chat__messages">
            {chatHistory.length === 0 && (
              <div className="agent-test-chat__empty">
                <img src={agentAvatarSrc} className="agent-test-chat__empty-avatar" alt="" />
                <Typography.Text strong style={{ marginTop: 12, fontSize: 15 }}>{agentName}</Typography.Text>
                <Typography.Text type="secondary" style={{ marginTop: 4, fontSize: 12 }}>
                  {agent.description || '发送消息开始测试'}
                </Typography.Text>
                <div style={{ marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
                  {['查看任务', '帮我核对5月份', '你能干什么'].map((q) => (
                    <Button key={q} size="small" shape="round" style={{ fontSize: 12 }}
                      disabled={sending}
                      onClick={() => { void sendMessage(q) }}>{q}</Button>
                  ))}
                </div>
              </div>
            )}
            {chatHistory.map((m, i) => (
              <div
                key={i}
                className={`agent-test-msg agent-test-msg--${m.role}${m.ui_blocks?.length ? ' agent-test-msg--rich' : ''}`}
              >
                {m.role === 'assistant' && (
                  <img src={agentAvatarSrc} className="agent-test-msg__avatar" alt="" />
                )}
                <div className={`agent-test-msg__body${m.ui_blocks?.length ? ' agent-test-msg__body--rich' : ''}`}>
                  {m.role === 'user' ? (
                    <>
                      <div className="agent-test-msg__bubble agent-test-msg__bubble--user">{m.content}</div>
                      <span className="agent-test-msg__time">
                        {new Date(m.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </>
                  ) : (
                    <AiAssistantMessage
                      content={m.content}
                      ui_blocks={m.ui_blocks}
                      conversationId={convId}
                      agentId={selectedAgent}
                      onExecuted={handleExecuted}
                      onTaskCompleted={handleTaskCompleted}
                      onQuickAction={(prompt, action) => { void sendMessage(prompt, action) }}
                      disabled={sending}
                      time={new Date(m.ts).toISOString()}
                    />
                  )}
                </div>
              </div>
            ))}
            {sending && (
              <div className="agent-test-msg agent-test-msg--assistant">
                <img src={agentAvatarSrc} className="agent-test-msg__avatar" alt="" />
                <div className="agent-test-msg__body">
                  <div className="agent-test-msg__bubble agent-test-msg__bubble--assistant agent-test-msg__typing">
                    <span className="dot-pulse" />
                  </div>
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
          <div className="agent-test-chat__input">
            <Input
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              onPressEnter={handleSend}
              placeholder="输入消息测试 Agent..."
              disabled={sending}
              suffix={
                <Button type="text" icon={<SendOutlined />} onClick={handleSend}
                  loading={sending} style={{ color: '#f97316' }} />
              }
            />
          </div>
        </div>

        {/* 右侧：资产面板 */}
        <div className="agent-test-audit">
          {/* 已绑定资产 */}
          {boundAssets.length > 0 && (
            <div className="ata-section ata-bound">
              <div className="ata-section__title">
                <span className="ata-section__dot" />已绑定资产
                <span className="ata-section__count">{boundAssets.length}</span>
              </div>
              <div className="ata-bound__grid">
                {boundAssets.map((a, i) => (
                  <div key={i} className="ata-chip" style={{ '--chip-color': ASSET_COLOR[a.type] || '#94a3b8' } as React.CSSProperties}>
                    <span className="ata-chip__icon">{ASSET_ICON[a.type]}</span>
                    <span className="ata-chip__label">{a.label}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 调用记录 */}
          <div className="ata-section ata-calls">
            <div className="ata-section__title">
              <span className="ata-section__dot ata-section__dot--live" />调用追踪
              {assetCalls.length > 0 && <span className="ata-section__count">{assetCalls.length}</span>}
            </div>
            <div className="ata-calls__list">
              {assetCalls.length === 0 && (
                <div className="ata-calls__empty">
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    对话后实时展示资产调用链路
                  </Typography.Text>
                </div>
              )}
              {assetCalls.map((call, i) => (
                <div key={i} className={`ata-trace ${call.ok ? '' : 'ata-trace--fail'}`}
                  style={{ animationDelay: `${i * 60}ms`, '--trace-color': ASSET_COLOR[call.type] || '#94a3b8' } as React.CSSProperties}>
                  <div className="ata-trace__head">
                    <span className="ata-trace__icon" style={{ color: ASSET_COLOR[call.type] }}>{ASSET_ICON[call.type]}</span>
                    <span className="ata-trace__name">{call.label}</span>
                    <span className={`ata-trace__badge ${call.ok ? 'ata-trace__badge--ok' : 'ata-trace__badge--fail'}`}>
                      {call.ok ? 'OK' : 'FAIL'}
                    </span>
                  </div>
                  {call.detail && <div className="ata-trace__detail">{call.detail.substring(0, 120)}</div>}
                  <div className="ata-trace__time">{new Date(call.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

type AdminAgentsPageProps = {
  /** 前台对话侧：仅 Agent 配置，无运营/治理 Tab */
  frontOnly?: boolean
}

export default function AdminAgentsPage({ frontOnly = false }: AdminAgentsPageProps = {}) {
  const currentUser = useMemo(() => {
    try {
      return JSON.parse(localStorage.getItem('user') || '{}') as { id?: string; role?: string }
    } catch {
      return {}
    }
  }, [])
  const [agentScope, setAgentScope] = useState<'mine' | 'team'>('mine')
  const [agents, setAgents] = useState<AgentConfigItem[]>([])
  const [stats, setStats] = useState<Awaited<ReturnType<typeof getAdminAgentStats>> | null>(null)
  const [runs, setRuns] = useState<Awaited<ReturnType<typeof listAdminAgentRuns>>>([])
  const [insights, setInsights] = useState<Awaited<ReturnType<typeof getAdminAgentInsights>>>([])
  const [skillOpts, setSkillOpts] = useState<Array<{ value: string; label: string }>>([])
  const [workflowOpts, setWorkflowOpts] = useState<Array<{ value: string; label: string }>>([])
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('config')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<AgentConfigItem | null>(null)
  const [mountsAgent, setMountsAgent] = useState<AgentConfigItem | null>(null)
  const [runDetailOpen, setRunDetailOpen] = useState(false)
  const [runDetail, setRunDetail] = useState<Awaited<ReturnType<typeof getAdminAgentRunDetail>> | null>(null)
  const [testAgent, setTestAgent] = useState<AgentConfigItem | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const base = await Promise.all([
        listAdminAgents(),
        getAdminSkills(),
        getAdminBusinessCenters(),
      ])
      const [a, skills, centers] = base
      setAgents(a)
      if (!frontOnly) {
        const [s, r, ins] = await Promise.all([
          getAdminAgentStats(),
          listAdminAgentRuns(40),
          getAdminAgentInsights(),
        ])
        setStats(s)
        setRuns(r)
        setInsights(ins)
      }
      setSkillOpts(
        skills.map((sk) => ({
          value: String(sk.id || sk.code),
          label: `${sk.name || sk.code} (${sk.type || 'capability'})`,
        })),
      )
      const wf: Array<{ value: string; label: string }> = []
      for (const bc of centers) {
        const wid = bc.workflow_id || bc.workflow?.id
        if (wid) wf.push({ value: wid, label: `${bc.name} · Workflow` })
      }
      setWorkflowOpts(wf)
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setLoading(false)
    }
  }, [frontOnly])

  useEffect(() => { load() }, [load])

  const templates = useMemo(() => agents.filter((a) => a.is_template), [agents])
  const instances = useMemo(() => agents.filter((a) => !a.is_template), [agents])

  const { mineAgents, teamAgents } = useMemo(() => {
    const mine: AgentConfigItem[] = []
    const team: AgentConfigItem[] = []
    for (const a of agents) {
      if (isMyAgent(a, currentUser.id)) mine.push(a)
      else team.push(a)
    }
    return { mineAgents: mine, teamAgents: team }
  }, [agents, currentUser.id])

  const openCreate = () => {
    setEditing(null)
    setModalOpen(true)
  }

  const openEdit = (row: AgentConfigItem) => {
    setEditing(row)
    setModalOpen(true)
  }

  const runLifecycle = async (agentId: string, action: Parameters<typeof adminAgentLifecycle>[1], opts?: { gray?: boolean }) => {
    try {
      await adminAgentLifecycle(agentId, action, opts)
      message.success('操作成功')
      load()
    } catch (e) {
      message.error(formatApiError(e))
    }
  }

  const handleDelete = async (row: AgentConfigItem) => {
    try {
      await deleteAdminAgent(row.id)
      message.success(`已删除「${row.name}」`)
      if (editing?.id === row.id) {
        setModalOpen(false)
        setEditing(null)
      }
      if (mountsAgent?.id === row.id) setMountsAgent(null)
      load()
    } catch (e) {
      const msg = formatApiError(e, '删除失败')
      if (msg.includes('不可删除') || msg.includes('预置')) {
        message.warning(msg)
      } else if ((e as { response?: { status?: number } })?.response?.status === 405) {
        message.error('删除接口不可用，请重启后端（run_dev.bat）后重试')
      } else {
        message.error(msg)
      }
    }
  }

  const openRunReplay = async (runId: string) => {
    try {
      const detail = await getAdminAgentRunDetail(runId)
      setRunDetail(detail)
      setRunDetailOpen(true)
    } catch (e) {
      message.error(formatApiError(e))
    }
  }

  const statusTag = (status?: string) => {
    const m = STATUS_MAP[status || 'published'] || { label: status || '—', tone: 'draft' }
    return <span className={`agent-card__status agent-card__status--${m.tone}`}>{m.label}</span>
  }

  const AgentCard = ({ agent, showLifecycle = false }: { agent: AgentConfigItem; showLifecycle?: boolean }) => {
    const m = STATUS_MAP[agent.status || 'draft'] || { label: agent.status || '—', tone: 'draft' }
    const st = (agent.status || 'draft').toLowerCase()
    const skillCount = (agent.allowed_skill_ids || []).length
    const kbCount = (agent.knowledge_base_ids || []).length
    const toolCount = (agent.data_source_scope || []).length
    const avatarSrc = avatarImageUrl(resolveAvatarId(agent))

    return (
      <div className="agent-card">
        <div className="agent-card__header">
          <img
            src={avatarSrc}
            alt=""
            className="agent-card__avatar"
          />
          <div className="agent-card__status-row">
            {agent.is_template && <span className="agent-card__type-tag agent-card__type-tag--tpl">模板</span>}
            {!agent.is_template && agent.scope === 'personal' && (
              <span className="agent-card__type-tag">个人</span>
            )}
            {!agent.is_template && agent.scope === 'team_published' && (
              <span className="agent-card__type-tag agent-card__type-tag--team">团队</span>
            )}
            <span className={`agent-card__status agent-card__status--${m.tone}`}>{m.label}</span>
          </div>
        </div>

        <div className="agent-card__body">
          <Typography.Title level={5} className="agent-card__name">
            {agent.name}
          </Typography.Title>
          <Typography.Paragraph
            type="secondary"
            className="agent-card__desc"
            ellipsis={{ rows: 3 }}
          >
            {agent.description || agent.persona || `编码：${agent.code}`}
          </Typography.Paragraph>

          <div className="agent-card__skills">
            {(agent.allowed_skill_ids || []).slice(0, 6).map((id) => (
              <Tag key={id} className="agent-card__skill-tag">{id.replace(/^skill-/, '')}</Tag>
            ))}
          </div>

          <div className="agent-card__meta">
            <Tag>Skill {skillCount}</Tag>
            <Tag>Tool {toolCount}</Tag>
            <Tag>KB {kbCount}</Tag>
            {agent.fallback_strategy && <Tag>{agent.fallback_strategy === 'auto' ? '自动' : agent.fallback_strategy}</Tag>}
          </div>

          {showLifecycle && (
            <div className="agent-card__lifecycle">
              {st === 'draft' && (
                <Button type="link" size="small" onClick={() => { void runLifecycle(agent.id, 'submit_review') }}>
                  提交审核
                </Button>
              )}
              {st === 'pending_review' && (
                <Button type="link" size="small" onClick={() => { void runLifecycle(agent.id, 'publish') }}>
                  发布
                </Button>
              )}
              {st === 'published' && (
                <Button type="link" size="small" onClick={() => { void runLifecycle(agent.id, 'offline') }}>
                  下架
                </Button>
              )}
              {st === 'offline' && (
                <Button type="link" size="small" onClick={() => { void runLifecycle(agent.id, 'publish') }}>
                  重新发布
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="agent-card__actions">
          <Button
            type="primary"
            size="small"
            icon={<CommentOutlined />}
            onClick={() => openEdit(agent)}
          >
            编辑
          </Button>
          <Button
            size="small"
            icon={<ExperimentOutlined />}
            onClick={() => setTestAgent(agent)}
            style={{ color: '#f97316', borderColor: '#f97316' }}
          >
            测试
          </Button>
          <Button
            size="small"
            icon={<LinkOutlined />}
            onClick={() => setMountsAgent(agent)}
          >
            挂载
          </Button>
          {agent.id !== PROTECTED_AGENT_ID && (
            <Popconfirm
              title="确定删除该 Agent？"
              description="删除后不可恢复，关联运行记录将一并清除。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleDelete(agent)}
            >
              <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          )}
        </div>
      </div>
    )
  }

  const opsMetrics = stats?.ops_metrics

  const displayAgents = frontOnly
    ? (agentScope === 'mine' ? mineAgents : teamAgents)
    : (templates.length ? templates : agents)

  const agentTabs = useMemo(
    () => [
      { key: 'mine', label: '我的 Agent', count: mineAgents.length },
      { key: 'team', label: '团队 Agent', count: teamAgents.length },
    ],
    [mineAgents.length, teamAgents.length],
  )

  const configTab = (
    <Space direction="vertical" size={frontOnly ? 'middle' : 'large'} style={{ width: '100%' }}>
      {frontOnly ? (
        <CatalogToolbar
          tabs={agentTabs}
          activeTab={agentScope}
          onTabChange={(k) => setAgentScope(k as 'mine' | 'team')}
          hint={
            agentScope === 'mine'
              ? '个人 Agent：创建草稿 → 提交审核 → 发布后可在对话侧选用'
              : '团队 Agent：已发布模板与共享配置，供全员对话与 Workflow 引用'
          }
          action={(
            <Button type="primary" className="catalog-upload-btn" icon={<PlusOutlined />} onClick={openCreate}>
              新建 Agent
            </Button>
          )}
        />
      ) : (
        <div className="agent-cards-header">
          <Typography.Title level={5} style={{ margin: 0 }}>Agent 模板</Typography.Title>
          <Button type="primary" className="catalog-upload-btn" size="small" icon={<PlusOutlined />} onClick={openCreate}>
            新建
          </Button>
        </div>
      )}
      <Row gutter={[12, 12]} className="agent-cards-grid">
        {displayAgents.map((agent) => (
          <Col xs={24} sm={12} md={8} lg={6} xl={6} key={agent.id}>
            <AgentCard agent={agent} showLifecycle={frontOnly && agentScope === 'mine'} />
          </Col>
        ))}
        {displayAgents.length === 0 && (
          <Col span={24}>
            <div className="agent-cards-empty">
              <RobotOutlined className="agent-cards-empty__icon" />
              <Text type="secondary" className="agent-cards-empty__hint">
                {frontOnly && agentScope === 'mine'
                  ? '暂无个人 Agent，点击「新建」创建草稿'
                  : '暂无团队 Agent'}
              </Text>
            </div>
          </Col>
        )}
      </Row>
      {!frontOnly && instances.length > 0 && (
        <>
          <Typography.Title level={5} style={{ marginTop: 8 }}>Agent 实例</Typography.Title>
          <Row gutter={[12, 12]} className="agent-cards-grid">
            {instances.map((agent) => (
              <Col xs={24} sm={12} md={8} lg={6} xl={6} key={agent.id}>
                <AgentCard agent={agent} showLifecycle />
              </Col>
            ))}
          </Row>
        </>
      )}
    </Space>
  )

  const opsTab = (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Row gutter={16}>
        <Col span={6}><Card><Statistic title="对话会话" value={stats?.total_conversations ?? 0} /></Card></Col>
        <Col span={6}><Card><Statistic title="调用总量" value={stats?.total_runs ?? 0} /></Card></Col>
        <Col span={6}><Card><Statistic title="近 7 日调用" value={stats?.runs_last_7d ?? 0} /></Card></Col>
        <Col span={6}>
          <Card>
            <Statistic title="成功率（估）" value={((opsMetrics?.success_rate_estimate ?? 0) * 100).toFixed(0)} suffix="%" />
          </Card>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={12}>
          <Card title="发布状态分布" size="small">
            {(opsMetrics?.agents_by_status || []).map((x) => (
              <div key={x.status} style={{ marginBottom: 6 }}>
                {statusTag(x.status)} <Text>{x.count} 个</Text>
              </div>
            ))}
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Skill 调用热点" size="small">
            {(opsMetrics?.skill_call_hotspots || []).slice(0, 6).map((x) => (
              <div key={x.skill}>{x.skill}: {x.count}</div>
            ))}
            {!opsMetrics?.skill_call_hotspots?.length && <Text type="secondary">暂无调用数据</Text>}
          </Card>
        </Col>
      </Row>
      <Card title="② 发布与版本管理" size="small">
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={agents}
          expandable={{
            expandedRowRender: (row) => (
              <div>
                <Text strong>版本历史</Text>
                {(row.version_history || []).length === 0 ? (
                  <div><Text type="secondary">发布 / 变更后将自动快照</Text></div>
                ) : (
                  <Timeline
                    style={{ marginTop: 12 }}
                    items={(row.version_history || []).map((h) => ({
                      children: `v${h.version} · ${h.saved_at}${h.note ? ` · ${h.note}` : ''}`,
                    }))}
                  />
                )}
              </div>
            ),
          }}
          columns={[
            { title: 'Agent', dataIndex: 'name' },
            { title: '版本', dataIndex: 'version', width: 64 },
            { title: '状态', dataIndex: 'status', width: 96, render: (s: string) => statusTag(s) },
            {
              title: '生命周期',
              width: 320,
              render: (_: unknown, row: AgentConfigItem) => (
                <Space wrap size="small">
                  {row.status === 'draft' && (
                    <Button size="small" onClick={() => runLifecycle(row.id, 'submit_review')}>提交审核</Button>
                  )}
                  {row.status === 'pending_review' && (
                    <Button size="small" type="primary" onClick={() => runLifecycle(row.id, 'publish')}>发布</Button>
                  )}
                  {row.status === 'published' && (
                    <>
                      <Button size="small" onClick={() => runLifecycle(row.id, 'publish', { gray: true })}>灰度</Button>
                      <Button size="small" onClick={() => runLifecycle(row.id, 'offline')}>下架</Button>
                    </>
                  )}
                  {row.status === 'offline' && (
                    <Button size="small" type="primary" onClick={() => runLifecycle(row.id, 'publish')}>重新发布</Button>
                  )}
                  <Button size="small" onClick={() => runLifecycle(row.id, 'rollback')}>回滚</Button>
                  <Button size="small" onClick={() => runLifecycle(row.id, 'duplicate')}>复制</Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <Card title="热门 Agent / 意图" size="small">
        <Row gutter={24}>
          <Col span={12}>
            {(stats?.top_agents || []).map((x) => (
              <div key={x.agent_id}>{x.name}: {x.count}</div>
            ))}
          </Col>
          <Col span={12}>
            {(stats?.top_intents || []).map((x) => (
              <div key={x.intent}>{x.intent}: {x.count}</div>
            ))}
          </Col>
        </Row>
      </Card>
    </Space>
  )

  const governanceTab = (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div className="admin-evolution-insights">
        <div className="admin-evolution-insights__trigger">
          <span className="admin-evolution-insights__title">④ 沉淀进化建议（运营 → 配置）</span>
          <span className="admin-evolution-insights__hint">悬停查看详情</span>
        </div>
        <div className="admin-evolution-insights__panel">
          {insights.map((item, i) => (
            <Alert
              key={i}
              style={{ marginBottom: i < insights.length - 1 ? 8 : 0 }}
              type={item.level === 'warning' ? 'warning' : item.level === 'success' ? 'success' : 'info'}
              message={item.title}
              description={item.detail}
              showIcon
            />
          ))}
        </div>
      </div>
      <Card title="调用日志与回放" size="small">
        <Table
          rowKey="id"
          size="small"
          dataSource={runs}
          pagination={{ pageSize: 8 }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 170 },
            { title: '意图', dataIndex: 'intent', width: 100 },
            { title: '用户输入', dataIndex: 'user_input', ellipsis: true },
            {
              title: '链路摘要',
              dataIndex: 'plan_steps',
              render: (steps: Array<{ action?: string; thought?: string }>) =>
                (steps || []).map((s) => s.action || s.thought).filter(Boolean).join(' → ') || '—',
            },
            {
              title: '操作',
              width: 80,
              render: (_: unknown, row: { id: string }) => (
                <Button type="link" size="small" onClick={() => openRunReplay(row.id)}>回放</Button>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )

  const sharedModals = (
    <>
      <Drawer title={`资产挂载 · ${mountsAgent?.name}`} open={!!mountsAgent} onClose={() => setMountsAgent(null)} width={480}>
        {mountsAgent && <AssetMountsPanel mounts={mountsAgent.asset_mounts} />}
      </Drawer>

      <AdminAgentWizard
        open={modalOpen}
        editing={editing}
        agents={agents}
        skillOpts={skillOpts}
        workflowOpts={workflowOpts}
        onClose={() => { setModalOpen(false); setEditing(null) }}
        onSuccess={() => {
          message.success(editing ? '已更新 Agent' : '已创建 Agent 模板')
          load()
          window.dispatchEvent(new CustomEvent('agents-refresh'))
        }}
      />

      <Modal
        title="会话链路回放"
        open={runDetailOpen}
        onCancel={() => { setRunDetailOpen(false); setRunDetail(null) }}
        footer={null}
        width={720}
      >
        {runDetail?.run && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="会话 ID">{String(runDetail.run.conversation_id || '—')}</Descriptions.Item>
              <Descriptions.Item label="Agent">
                {String(runDetail.run.agent_name)} v{String(runDetail.run.agent_version ?? '?')}
              </Descriptions.Item>
              <Descriptions.Item label="用户输入">{String(runDetail.run.user_input)}</Descriptions.Item>
            </Descriptions>
            <Timeline
              items={((runDetail.run.plan_steps as Array<Record<string, string>>) || []).map((step, i) => ({
                color: step.action ? 'blue' : 'gray',
                children: (
                  <div key={i}>
                    {step.thought && <div><Text type="secondary">[思考]</Text> {step.thought}</div>}
                    {step.action && <div><Text strong>[行动]</Text> {step.action}</div>}
                    {step.observation && <div><Text type="secondary">[观察]</Text> {step.observation}</div>}
                  </div>
                ),
              }))}
            />
            {runDetail.run.final_output && (
              <Alert type="success" message="最终输出" description={String(runDetail.run.final_output)} />
            )}
          </Space>
        )}
      </Modal>

      {/* Agent 测试弹窗 */}
      <Modal
        open={!!testAgent}
        onCancel={() => setTestAgent(null)}
        footer={null}
        width={920}
        centered
        destroyOnClose
        className="agent-test-modal"
        title={null}
        closable
      >
        {testAgent && <AgentTestPanel agent={testAgent} />}
      </Modal>
    </>
  )

  if (frontOnly) {
    return (
      <div className="admin-agents-front">
        {configTab}
        {sharedModals}
      </div>
    )
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <AgentPageHelpBar />

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: 'config', label: 'Agent 配置', children: configTab },
          { key: 'ops', label: 'Agent 运营', children: opsTab },
          { key: 'governance', label: 'Agent 治理', children: governanceTab },
        ]}
      />

      {sharedModals}
    </Space>
  )
}
