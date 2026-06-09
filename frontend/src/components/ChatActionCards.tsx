import type { ReactNode } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Descriptions, Drawer, Modal, Progress, Select, Table, Tag, Typography, message } from 'antd'
import {
  AccountBookOutlined, ApartmentOutlined, BookOutlined, CheckCircleFilled,
  CloudUploadOutlined, CopyOutlined, DatabaseOutlined, ExclamationCircleFilled,
  LoadingOutlined, PlayCircleOutlined, RightOutlined, SwapOutlined,
  ThunderboltOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import {
  DatasourceBrandIcon, DatasourcePairIcons, DatasourceVisualIcon,
} from '../utils/datasourceBranding'
import { avatarImageUrl } from '../utils/agentAvatars'
import { enrichWelcomeCapAction, sanitizeWelcomeBlockData, type WelcomeCapItem } from '../utils/agentChatProfile'
import { Link } from 'react-router-dom'
import type { Difference } from '../api/client'
import {
  chatConnectDemoDatasources, chatExecuteReconciliation, chatImportDatasourcesFromExcel,
  chatKnowledgeEntryDetail, chatPreviewDatasource, chatSkillDetail, chatUploadDatasource,
  getDifferences, getTask, reviewDifference, resumeTaskExecution,
  type CaseAsset, type ChatReconciliationOptions, type ChatSkillDetail,
  type DataSourcePreview, type Task,
} from '../api/client'
import { AdminCaseDetailDrawer } from './AdminKnowledgePage'
import { flattenAssistantText } from './ChatWorkbenchCards'
import { ChatDifferenceExplainCard, type DifferenceExplainCardData } from './ChatDifferenceExplainCard'
import {
  ChatAgentTrace, ChatExecutionProcess, dedupeTraceFromReply, type ChatAgentTraceItem,
} from './ChatAgentTrace'
import { ReconciliationSystemSummary } from './TrustDiffUI'
import { EXECUTION_PIPELINE, WorkflowStepsPipeline, type WorkflowStepItem } from './TrustComponents'

export type ChatUiBlock = {
  type: string
  data: Record<string, unknown>
}

const KB_REFS_PREVIEW = 2

/** 正文已有知识库卡片时，去掉重复的「来源引用」长列表 */
export function stripKnowledgeSourcesSection(text: string): string {
  const trimmed = text.trim()
  if (!trimmed) return trimmed
  const idx = trimmed.search(/\n\s*(来源引用|—\s*来源\s*—)/)
  if (idx >= 0) return trimmed.slice(0, idx).trim()
  return trimmed.replace(/\n?点击对话下方卡片[\s\S]*$/, '').trim()
}

function truncateLine(text: string, max = 72): string {
  const t = text.replace(/\s+/g, ' ').trim()
  if (t.length <= max) return t
  return `${t.slice(0, max)}…`
}

type SystemItem = {
  id: string
  name: string
  side: string
  kind: string
  system_label: string
  last_sync: string
  status: string
  status_label: string
  row_count?: number
}

/** 图形卡片类型：只渲染卡片，不显示文字气泡 */
export const GRAPHICAL_BLOCK_TYPES = new Set([
  'welcome_caps', 'faq_workflow', 'faq_diff_types', 'datasource_confirm', 'task_progress',
  'reconciliation_result', 'review_prompt', 'review_inline', 'capability_list',
  'agent_capability_overview',
  'workflow_cta', 'agent_cta', 'intent_card', 'task_list', 'task_detail', 'skill_invoke',
  'quick_actions', 'agent_plan',
  'outcome_preview', 'difference_explain', 'difference_list', 'knowledge_refs', 'clarify_form',
])

/** 不参与「主结果」判定的附属块（执行过程、快捷按钮等） */
const CHAT_CHROME_BLOCK_TYPES = new Set([
  'agent_plan', 'quick_actions', 'intent_card', 'outcome_preview',
])

const SUBSTANTIVE_BLOCK_TYPES = new Set([
  'difference_explain', 'difference_list', 'reconciliation_result',
  'datasource_confirm', 'faq_workflow', 'faq_diff_types', 'task_progress',
  'review_prompt', 'review_inline', 'task_list', 'task_detail', 'skill_invoke', 'capability_list',
  'agent_capability_overview',
  'welcome_caps', 'workflow_cta', 'agent_cta', 'knowledge_refs', 'clarify_form',
])

export function looksLikeMarkdownSkillDump(text: string | undefined): boolean {
  const t = (text || '').trim()
  if (!t || t.length < 40) return false
  if (!/\|[^\n]+\|/.test(t)) return false
  if (/字段|任务名称|当前状态|流水线|建议下一步/.test(t)) return true
  if (/能力|说明|数据导入|字段映射|差异检测|异常归因|复核流转|报告生成|任务查询/.test(t)) {
    return true
  }
  return /query_tasks|review_flow|anomaly_explain/i.test(t) && t.includes('---')
}

function substantiveBlocks(blocks?: ChatUiBlock[]): ChatUiBlock[] {
  return (blocks ?? []).filter((b) => SUBSTANTIVE_BLOCK_TYPES.has(b.type))
}

function isContentRedundantWithBlocks(content: string | undefined, blocks?: ChatUiBlock[]): boolean {
  const trimmed = content?.trim() || ''
  if (!trimmed || !blocks?.length) return false
  if (blocks.some(
    (b) => b.type === 'datasource_confirm' && String(b.data.intro || '').trim() === trimmed,
  )) {
    return true
  }
  if (blocks.some(
    (b) => b.type === 'clarify_form' && String(b.data.intro || '').trim() === trimmed,
  )) {
    return true
  }
  if (blocks.some((b) => b.type === 'difference_explain') && trimmed.length < 140) {
    return true
  }
  if (blocks.some((b) => b.type === 'difference_list') && trimmed.length < 200) {
    return true
  }
  if (blocks.some((b) => b.type === 'agent_capability_overview' || b.type === 'capability_list')) {
    if (trimmed.length > 0 && (looksLikeMarkdownSkillDump(trimmed) || trimmed.length < 220)) {
      return true
    }
  }
  if (blocks.some((b) => ['task_detail', 'skill_invoke', 'task_list'].includes(b.type))) {
    if (looksLikeMarkdownSkillDump(trimmed)) return true
    if (blocks.some((b) => b.type === 'task_detail' || b.type === 'skill_invoke') && trimmed.length < 100) {
      return true
    }
  }
  return false
}

function isCardOnlyReply(blocks?: ChatUiBlock[], content?: string) {
  const main = substantiveBlocks(blocks)
  if (!main.length) return false
  if (isContentRedundantWithBlocks(content, blocks)) {
    return main.every((b) => GRAPHICAL_BLOCK_TYPES.has(b.type))
  }
  if (content?.trim()) return false
  return main.every((b) => GRAPHICAL_BLOCK_TYPES.has(b.type))
}

function formatTime(iso?: string) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

/** AI 回复：纯文本气泡 或 图形化面板（文本 + 交互组件） */
export function AiAssistantMessage({
  content,
  diff,
  ui_blocks,
  conversationId,
  onExecuted,
  onTaskCompleted,
  onStartReview,
  onReviewDone,
  onQuickAction,
  onClarifyPick,
  onDiffFeedbackDone,
  disabled,
  time,
  agentId,
  executionTrace,
  streamingTrace,
}: {
  content: string
  diff?: Difference | null
  ui_blocks?: ChatUiBlock[]
  conversationId?: string
  onExecuted?: (reply: string, blocks: ChatUiBlock[], taskId?: string) => void
  onTaskCompleted?: (taskId: string) => void
  onStartReview?: (taskId: string) => void
  onReviewDone?: (taskId: string) => void
  onQuickAction?: (prompt: string, clientAction?: string) => void
  onClarifyPick?: (taskId: string, differenceId: string) => void
  onDiffFeedbackDone?: (diffId: string, action: 'confirm' | 'question' | 'correct') => void
  disabled?: boolean
  time?: string
  agentId?: string
  executionTrace?: ChatAgentTraceItem[]
  streamingTrace?: boolean
}) {
  const blocks = ui_blocks ?? []
  const hasPlanBlock = blocks.some((b) => b.type === 'agent_plan')
  const hasSkillInvokeUi = blocks.some((b) => b.type === 'skill_invoke')
  const traceItems = hasSkillInvokeUi
    ? (executionTrace ?? []).filter((t) => t.kind !== 'tool_call')
    : (executionTrace ?? [])
  const showTrace = !hasPlanBlock && traceItems.length > 0
  const hasKbRefs = blocks.some((b) => b.type === 'knowledge_refs')
  let rawText = hasKbRefs
    ? stripKnowledgeSourcesSection(flattenAssistantText(content, diff))
    : flattenAssistantText(content, diff)
  if (showTrace && traceItems.length) {
    rawText = dedupeTraceFromReply(rawText, traceItems)
  }
  const planBlocks = blocks.filter((b) => b.type === 'agent_plan')
  const contentBlocks = blocks.filter((b) => !CHAT_CHROME_BLOCK_TYPES.has(b.type))
  const hasRich = blocks.length > 0 || showTrace
  const cardOnly = isCardOnlyReply(ui_blocks, content)
  const hasSubstantiveUi = substantiveBlocks(blocks).length > 0

  const planObservations = new Set(
    planBlocks.flatMap((b) =>
      ((b.data?.steps || []) as Array<{ observation?: string; thought?: string }>)
        .flatMap((s) => [s.observation, s.thought].filter(Boolean) as string[])
        .map((o) => o.trim())
        .filter((o) => o.length > 10),
    ),
  )
  const rawTrim = rawText.trim()
  const text = hasSubstantiveUi && [...planObservations].some(
    (o) => o === rawTrim || (rawTrim.length > 40 && (rawTrim.includes(o) || o.includes(rawTrim))),
  ) ? '' : rawText

  const blockHandlers = {
    conversationId,
    onExecuted,
    onTaskCompleted,
    onStartReview,
    onReviewDone,
    onQuickAction,
    onClarifyPick,
    onDiffFeedbackDone,
    disabled,
    agentId,
  }

  if (!hasRich) {
    return (
      <div className="chat-msg-stack chat-msg-stack--assistant">
        <div className="chat-fs-bubble chat-fs-bubble--assistant chat-fs-bubble--compact">{text}</div>
        {time && <span className="chat-fs-time">{formatTime(time)}</span>}
      </div>
    )
  }

  return (
    <div className="chat-msg-stack chat-msg-stack--assistant">
      <div className={`chat-rich-panel ${cardOnly ? 'chat-rich-panel--card-only' : ''}`}>
        {showTrace && (
          <div className="chat-rich-panel__plan">
            <ChatAgentTrace items={traceItems} streaming={streamingTrace} />
          </div>
        )}
        {planBlocks.length > 0 && (
          <div className="chat-rich-panel__plan">
            <ChatUiBlocks blocks={planBlocks} {...blockHandlers} />
          </div>
        )}
        {!cardOnly && text && <p className="chat-rich-panel__lead">{text}</p>}
        {contentBlocks.length > 0 && (
          <ChatUiBlocks blocks={contentBlocks} {...blockHandlers} />
        )}
        {!hasSubstantiveUi && !text && planBlocks.length > 0 && (
          <p className="chat-rich-panel__lead chat-rich-panel__lead--muted">
            分析已完成，请展开上方「执行过程」查看详情；若仍无结果卡片，请刷新后重试。
          </p>
        )}
      </div>
      {time && <span className="chat-fs-time">{formatTime(time)}</span>}
    </div>
  )
}

export function ChatUiBlocks({
  blocks,
  conversationId,
  onExecuted,
  onTaskCompleted,
  onStartReview,
  onReviewDone,
  onQuickAction,
  onClarifyPick,
  onDiffFeedbackDone,
  disabled,
  agentId,
}: {
  blocks: ChatUiBlock[]
  conversationId?: string
  onExecuted?: (reply: string, blocks: ChatUiBlock[], taskId?: string) => void
  onTaskCompleted?: (taskId: string) => void
  onStartReview?: (taskId: string) => void
  onReviewDone?: (taskId: string) => void
  onQuickAction?: (prompt: string, clientAction?: string) => void
  onClarifyPick?: (taskId: string, differenceId: string) => void
  onDiffFeedbackDone?: (diffId: string, action: 'confirm' | 'question' | 'correct') => void
  disabled?: boolean
  agentId?: string
}) {
  let welcomeRendered = false
  return (
    <>
      {blocks.map((block, i) => {
        if (block.type === 'welcome_caps') {
          if (welcomeRendered) return null
          welcomeRendered = true
          return (
            <ChatWelcomeCaps
              key={`wc-${i}`}
              data={block.data}
              onCapAction={onQuickAction}
              disabled={disabled}
            />
          )
        }
        if (block.type === 'faq_workflow') {
          return <ChatFaqWorkflow key={`fw-${i}`} data={block.data} />
        }
        if (block.type === 'faq_diff_types') {
          return <ChatFaqDiffTypes key={`fd-${i}`} data={block.data} />
        }
        if (block.type === 'knowledge_refs') {
          return <ChatKnowledgeRefs key={`kr-${i}`} data={block.data} agentId={agentId} />
        }
        if (block.type === 'clarify_form') {
          return (
            <ChatClarifyForm
              key={`cf-${i}`}
              data={block.data}
              disabled={disabled}
              onPick={onClarifyPick}
              onAltAction={onQuickAction}
            />
          )
        }
        if (block.type === 'difference_explain') {
          const diffId = String((block.data as DifferenceExplainCardData).difference_id || '')
          return (
            <ChatDifferenceExplainCard
              key={`de-${i}`}
              data={block.data as DifferenceExplainCardData}
              disabled={disabled}
              onFeedbackDone={(action) => {
                if (diffId) onDiffFeedbackDone?.(diffId, action)
              }}
            />
          )
        }
        if (block.type === 'difference_list') {
          return <ChatDifferenceList key={`dl-${i}`} data={block.data} />
        }
        if (block.type === 'datasource_confirm') {
          return (
            <ChatDatasourceConfirm
              key={`ds-${i}`}
              data={block.data}
              conversationId={conversationId}
              agentId={agentId}
              onExecuted={onExecuted}
              disabled={disabled}
            />
          )
        }
        if (block.type === 'task_progress') {
          return (
            <ChatTaskProgress
              key={`tp-${i}`}
              data={block.data}
              onTaskCompleted={onTaskCompleted}
            />
          )
        }
        if (block.type === 'reconciliation_result') {
          return <ChatReconciliationResult key={`rr-${i}`} data={block.data} />
        }
        if (block.type === 'review_prompt') {
          return (
            <ChatReviewPrompt
              key={`rp-${i}`}
              data={block.data}
              onStartReview={onStartReview}
              disabled={disabled}
            />
          )
        }
        if (block.type === 'review_inline') {
          return (
            <ChatReviewInline
              key={`ri-${i}`}
              data={block.data}
              onReviewDone={onReviewDone}
              disabled={disabled}
            />
          )
        }
        if (block.type === 'workflow_cta') {
          return <ChatWorkflowCta key={`wcta-${i}`} data={block.data} />
        }
        if (block.type === 'agent_cta') {
          return <ChatAgentCta key={`acta-${i}`} data={block.data} />
        }
        if (block.type === 'intent_card') return null
        if (block.type === 'agent_capability_overview') {
          return (
            <ChatAgentCapabilityOverview
              key={`aco-${i}`}
              data={block.data}
              agentId={agentId}
              onQuickAction={onQuickAction}
              disabled={disabled}
            />
          )
        }
        if (block.type === 'capability_list') {
          return <ChatCapabilityList key={`cl-${i}`} data={block.data} agentId={agentId} />
        }
        if (block.type === 'task_list') {
          return <ChatTaskList key={`tl-${i}`} data={block.data} />
        }
        if (block.type === 'skill_invoke') {
          return <ChatSkillInvoke key={`si-${i}`} data={block.data} />
        }
        if (block.type === 'task_detail') {
          return (
            <ChatTaskDetail
              key={`td-${i}`}
              data={block.data}
              onQuickAction={onQuickAction}
              disabled={disabled}
            />
          )
        }
        if (block.type === 'quick_actions') {
          return (
            <ChatQuickActions
              key={`qa-${i}`}
              data={block.data}
              onAction={onQuickAction}
              disabled={disabled}
            />
          )
        }
        if (block.type === 'agent_plan') {
          return <ChatAgentPlan key={`ap-${i}`} data={block.data} />
        }
        if (block.type === 'outcome_preview') return null
        return null
      })}
    </>
  )
}

type CapItem = {
  icon?: string
  title: string
  desc: string
  kind?: string
  skill_id?: string
}

const MOUNT_CAP_ICON: Record<string, ReactNode> = {
  list: <UnorderedListOutlined />,
  diff: <ThunderboltOutlined />,
  play: <PlayCircleOutlined />,
  flow: <ApartmentOutlined />,
  upload: <CloudUploadOutlined />,
}

function formatSchemaSummary(schema: Record<string, unknown> | undefined): string {
  if (!schema || typeof schema !== 'object') return '—'
  const props = schema.properties as Record<string, unknown> | undefined
  if (props && typeof props === 'object') {
    const keys = Object.keys(props)
    return keys.length ? keys.join('、') : '—'
  }
  const flatKeys = Object.keys(schema).filter((k) => {
    const v = schema[k]
    return v && typeof v === 'object' && ('type' in (v as object) || 'description' in (v as object))
  })
  if (flatKeys.length) return flatKeys.join('、')
  const required = schema.required as string[] | undefined
  if (Array.isArray(required) && required.length) return required.join('、')
  return '—'
}

function ChatSkillDetailDrawer({
  skill,
  open,
  onClose,
}: {
  skill: ChatSkillDetail | null
  open: boolean
  onClose: () => void
}) {
  return (
    <Drawer title="Skill 详情" width={560} open={open} onClose={onClose} className="admin-kb-drawer">
      {skill && (
        <div className="admin-kb-detail">
          <div className="admin-kb-detail__hero">
            <span className="admin-kb-type-pill admin-kb-type-pill--lg">{skill.name}</span>
            <Tag bordered={false} color="blue">{skill.type_label}</Tag>
            <Tag bordered={false} color={skill.status === 'published' ? 'success' : 'default'}>
              {skill.status}
            </Tag>
          </div>
          <Descriptions column={1} size="small" bordered className="admin-kb-detail__desc">
            <Descriptions.Item label="标识">
              <Typography.Text code>{skill.code}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="版本">v{skill.version}</Descriptions.Item>
            {skill.category ? (
              <Descriptions.Item label="分类">{skill.category}</Descriptions.Item>
            ) : null}
            <Descriptions.Item label="能力说明">{skill.description || '—'}</Descriptions.Item>
            <Descriptions.Item label="使用方式">{skill.usage_hint || '—'}</Descriptions.Item>
            <Descriptions.Item label="输入字段">{formatSchemaSummary(skill.input_schema)}</Descriptions.Item>
            <Descriptions.Item label="输出字段">{formatSchemaSummary(skill.output_schema)}</Descriptions.Item>
            <Descriptions.Item label="调用方式">
              {skill.execution_label
                || (skill.has_executor
                  ? 'Skill 包 execute.py（Workflow / 在线测试）'
                  : '平台已登记')}
            </Descriptions.Item>
            {skill.registry_registered != null ? (
              <Descriptions.Item label="注册状态">
                {skill.registry_registered ? '已在 SkillRegistry 注册' : '未注册运行时'}
              </Descriptions.Item>
            ) : null}
          </Descriptions>
        </div>
      )}
    </Drawer>
  )
}

function MountCapabilityCard({
  item,
  onOpenSkill,
  loadingSkillId,
}: {
  item: CapItem
  onOpenSkill?: (skillId: string) => void
  loadingSkillId?: string | null
}) {
  const iconKind = item.icon || 'generic'
  const isSkill = item.kind === 'skill' && Boolean(item.skill_id)
  const clickable = isSkill && Boolean(onOpenSkill)

  const inner = (
    <>
      <div className={`chat-mount-card__icon chat-mount-card__icon--${iconKind}`}>
        {MOUNT_CAP_ICON[iconKind] || <DatabaseOutlined />}
      </div>
      <div className="chat-mount-card__body">
        <div className="chat-mount-card__head">
          <div className="chat-mount-card__title">{item.title}</div>
          {clickable ? (
            <span className="chat-mount-card__detail-link">
              {loadingSkillId === item.skill_id ? '加载中…' : '详情'}
            </span>
          ) : null}
        </div>
        {item.desc ? <div className="chat-mount-card__desc">{item.desc}</div> : null}
      </div>
    </>
  )

  if (!clickable) {
    return <div className="chat-mount-card">{inner}</div>
  }

  return (
    <div
      className="chat-mount-card chat-mount-card--clickable"
      role="button"
      tabIndex={0}
      onClick={() => onOpenSkill!(item.skill_id!)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpenSkill!(item.skill_id!)
        }
      }}
    >
      {inner}
    </div>
  )
}

type ClarifyChoice = {
  task_id: string
  task_name?: string
  task_period?: string
  difference_id: string
  business_key?: string
  type_label?: string
  amount_diff?: number
  badge?: string
}

function ChatClarifyForm({
  data,
  disabled,
  onPick,
  onAltAction,
}: {
  data: Record<string, unknown>
  disabled?: boolean
  onPick?: (taskId: string, differenceId: string) => void
  onAltAction?: (prompt: string, clientAction?: string) => void
}) {
  const choices = (data.choices as ClarifyChoice[]) || []
  const alts = (data.alt_actions as Array<{ label: string; prompt: string; client_action?: string }>) || []
  const [selected, setSelected] = useState<string>(
    choices[0] ? `${choices[0].task_id}:${choices[0].difference_id}` : '',
  )
  const selectedChoice = choices.find(
    (c) => `${c.task_id}:${c.difference_id}` === selected,
  )

  const formatAmount = (n?: number) => {
    if (n == null || Number.isNaN(n)) return '—'
    return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  }

  return (
    <div className="chat-clarify-form">
      <div className="chat-clarify-form__head">
        <span className="chat-clarify-form__title">{String(data.title || '请补充信息')}</span>
        {data.subtitle ? (
          <span className="chat-clarify-form__subtitle">{String(data.subtitle)}</span>
        ) : null}
      </div>
      {data.intro ? <p className="chat-clarify-form__intro">{String(data.intro)}</p> : null}
      {choices.length ? (
        <div className="chat-clarify-form__choices" role="radiogroup" aria-label="选择差异条目">
          {choices.map((c) => {
            const key = `${c.task_id}:${c.difference_id}`
            const active = selected === key
            return (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={active}
                className={`chat-clarify-form__choice${active ? ' is-active' : ''}`}
                disabled={disabled}
                onClick={() => setSelected(key)}
              >
                <span className="chat-clarify-form__radio" aria-hidden />
                <span className="chat-clarify-form__choice-body">
                  <span className="chat-clarify-form__choice-top">
                    <span className="chat-clarify-form__tag">{c.type_label || '差异'}</span>
                    {c.badge ? <span className="chat-clarify-form__badge">{c.badge}</span> : null}
                    <span className="chat-clarify-form__amount">差额 {formatAmount(c.amount_diff)}</span>
                  </span>
                  <span className="chat-clarify-form__task">
                    {c.task_name || '对账任务'}
                    {c.task_period ? ` · ${c.task_period}` : ''}
                  </span>
                  {c.business_key ? (
                    <code className="chat-clarify-form__key">{c.business_key}</code>
                  ) : null}
                </span>
              </button>
            )
          })}
        </div>
      ) : (
        <div className="chat-clarify-form__empty">暂无匹配任务，可先发起对账或查看任务列表。</div>
      )}
      <div className="chat-clarify-form__actions">
        <button
          type="button"
          className="chat-clarify-form__submit"
          disabled={disabled || !selectedChoice || !onPick}
          onClick={() => {
            if (selectedChoice && onPick) {
              onPick(selectedChoice.task_id, selectedChoice.difference_id)
            }
          }}
        >
          {String(data.submit_label || '确认并继续')}
        </button>
        {alts.map((a) => (
          <button
            key={a.label}
            type="button"
            className="chat-clarify-form__alt"
            disabled={disabled}
            onClick={() => onAltAction?.(a.prompt, a.client_action)}
          >
            {a.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function ChatKnowledgeRefs({
  data,
  agentId,
}: {
  data: Record<string, unknown>
  agentId?: string
}) {
  const items = (data.items as Array<{
    id?: string
    type_label?: string
    registration_ref?: string
    source_label?: string
    summary?: string
    handling?: string
    rule_suggestion?: string
    relevance_score?: number
  }>) || []
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState<CaseAsset | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [loadingId, setLoadingId] = useState<string | null>(null)
  const count = Number(data.count ?? items.length) || items.length
  const showAll = expanded || items.length <= KB_REFS_PREVIEW
  const visible = showAll ? items : items.slice(0, KB_REFS_PREVIEW)
  const hiddenCount = Math.max(0, items.length - visible.length)

  const openDetail = async (caseId: string) => {
    if (!caseId || loadingId) return
    setLoadingId(caseId)
    try {
      const full = await chatKnowledgeEntryDetail(caseId, agentId)
      setDetail(full)
      setDrawerOpen(true)
    } catch {
      message.error('无法加载条目详情，请确认后端已启动或稍后重试')
    } finally {
      setLoadingId(null)
    }
  }

  if (!items.length) return null
  return (
    <>
      <div className="chat-kb-refs">
        <div className="chat-kb-refs__head">
          <BookOutlined className="chat-kb-refs__icon" aria-hidden />
          <span className="chat-kb-refs__title">知识库引用</span>
          <span className="chat-kb-refs__badge">{count}</span>
        </div>
        <ul className="chat-kb-refs__list">
          {visible.map((it, i) => {
            const canOpen = Boolean(it.id)
            const busy = loadingId === it.id
            return (
              <li key={it.id || i}>
                <button
                  type="button"
                  className={`chat-kb-refs__item${canOpen ? '' : ' chat-kb-refs__item--static'}`}
                  disabled={!canOpen || busy}
                  onClick={canOpen ? () => openDetail(it.id!) : undefined}
                >
                  <span className="chat-kb-refs__idx">{i + 1}</span>
                  <span className="chat-kb-refs__body">
                    <span className="chat-kb-refs__row">
                      <span className="chat-kb-refs__tag">{it.type_label || '条目'}</span>
                      {it.registration_ref ? (
                        <code className="chat-kb-refs__ref">{it.registration_ref}</code>
                      ) : null}
                      {it.id ? (
                        <span className="chat-kb-refs__cid">#{it.id.slice(0, 8)}</span>
                      ) : null}
                      {canOpen ? (
                        <RightOutlined className="chat-kb-refs__arrow" aria-hidden />
                      ) : null}
                    </span>
                    <span className="chat-kb-refs__summary">
                      {truncateLine(it.summary || '—')}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
        {hiddenCount > 0 ? (
          <button
            type="button"
            className="chat-kb-refs__more"
            onClick={() => setExpanded(true)}
          >
            展开其余 {hiddenCount} 条
          </button>
        ) : expanded && items.length > KB_REFS_PREVIEW ? (
          <button
            type="button"
            className="chat-kb-refs__more"
            onClick={() => setExpanded(false)}
          >
            收起
          </button>
        ) : null}
      </div>
      <AdminCaseDetailDrawer
        caseItem={detail}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false)
          setDetail(null)
        }}
      />
    </>
  )
}

function ChatMinList({
  title,
  items,
  hint,
}: {
  title?: string
  items: Array<{ title: string; desc?: string }>
  hint?: string
}) {
  return (
    <div className="chat-min-block">
      {title && <p className="chat-min-block__title">{title}</p>}
      <ul className="chat-min-list">
        {items.map((item) => (
          <li key={item.title}>
            <span className="chat-min-list__label">{item.title}</span>
            {item.desc ? <span className="chat-min-list__desc">{item.desc}</span> : null}
          </li>
        ))}
      </ul>
      {hint ? <p className="chat-min-block__hint">{hint}</p> : null}
    </div>
  )
}

type CapOverviewSection = {
  key?: string
  label?: string
  text?: string
  items?: Array<{ skill_id?: string; title?: string; desc?: string }>
}

function ChatAgentCapabilityOverview({
  data,
  agentId,
  onQuickAction,
  disabled,
}: {
  data: Record<string, unknown>
  agentId?: string
  onQuickAction?: (prompt: string, clientAction?: string) => void
  disabled?: boolean
}) {
  const agentName = String(data.agent_name || '助手')
  const centerName = String(data.center_name || '')
  const tagline = String(data.tagline || '').trim()
  const workbenchPath = String(data.workbench_path || '/workbench/reconciliation')
  const sections = (Array.isArray(data.sections) ? data.sections : []) as CapOverviewSection[]
  const cta = data.cta as { label?: string; prompt?: string } | undefined
  const [skillDetail, setSkillDetail] = useState<ChatSkillDetail | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [loadingSkillId, setLoadingSkillId] = useState<string | null>(null)

  const openSkill = async (skillId: string) => {
    if (!skillId || loadingSkillId) return
    setLoadingSkillId(skillId)
    try {
      setSkillDetail(await chatSkillDetail(skillId, agentId))
      setDrawerOpen(true)
    } catch {
      message.error('无法加载 Skill 详情')
    } finally {
      setLoadingSkillId(null)
    }
  }

  return (
    <>
      <div className="chat-cap-overview">
        <header className="chat-cap-overview__hero">
          <h3 className="chat-cap-overview__name">{agentName}</h3>
          {centerName ? (
            <p className="chat-cap-overview__meta">
              {centerName}
              <Link to={workbenchPath} className="chat-cap-overview__link">
                工作台
              </Link>
            </p>
          ) : null}
          {tagline ? <p className="chat-cap-overview__tagline">{tagline}</p> : null}
        </header>
        <dl className="chat-cap-overview__rows">
          {sections.map((sec) => (
            <div key={sec.key || sec.label} className="chat-cap-overview__row">
              <dt>{sec.label}</dt>
              <dd>
                {sec.items?.length ? (
                  <ul className="chat-cap-overview__skill-list">
                    {sec.items.map((it) => (
                      <li key={it.skill_id || it.title}>
                        {it.skill_id ? (
                          <button
                            type="button"
                            className="chat-cap-overview__skill-btn"
                            disabled={disabled || loadingSkillId === it.skill_id}
                            onClick={() => openSkill(it.skill_id!)}
                          >
                            <span className="chat-cap-overview__skill-title">{it.title}</span>
                            {it.desc ? (
                              <span className="chat-cap-overview__skill-desc">{it.desc}</span>
                            ) : null}
                          </button>
                        ) : (
                          <>
                            <span className="chat-cap-overview__skill-title">{it.title}</span>
                            {it.desc ? (
                              <span className="chat-cap-overview__skill-desc">{it.desc}</span>
                            ) : null}
                          </>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span>{sec.text || '—'}</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
        {cta?.prompt ? (
          <button
            type="button"
            className="chat-cap-overview__cta"
            disabled={disabled}
            onClick={() => onQuickAction?.(cta.prompt!, 'start_reconciliation')}
          >
            {cta.label || '发起对账示例'}
          </button>
        ) : null}
      </div>
      <ChatSkillDetailDrawer
        skill={skillDetail}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false)
          setSkillDetail(null)
        }}
      />
    </>
  )
}

function ChatCapabilityList({
  data,
  agentId,
}: {
  data: Record<string, unknown>
  agentId?: string
}) {
  const title = String(data.title || '')
  const items = (Array.isArray(data.items) ? data.items : []) as CapItem[]
  const [skillDetail, setSkillDetail] = useState<ChatSkillDetail | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [loadingSkillId, setLoadingSkillId] = useState<string | null>(null)

  const openSkillDetail = async (skillId: string) => {
    if (!skillId || loadingSkillId) return
    setLoadingSkillId(skillId)
    try {
      const full = await chatSkillDetail(skillId, agentId)
      setSkillDetail(full)
      setDrawerOpen(true)
    } catch {
      message.error('无法加载 Skill 详情，请确认后端已启动或稍后重试')
    } finally {
      setLoadingSkillId(null)
    }
  }

  if (!items.length) return null
  const gridClass = items.length <= 2 ? ' chat-mount-grid--pair' : items.length <= 3 ? ' chat-mount-grid--triple' : ''
  return (
    <>
      <div className="chat-mount-block">
        {title ? <p className="chat-mount-block__title">{title}</p> : null}
        <div className={`chat-mount-grid${gridClass}`}>
          {items.map((item) => (
            <MountCapabilityCard
              key={item.skill_id || item.title}
              item={item}
              onOpenSkill={item.kind === 'skill' && item.skill_id ? openSkillDetail : undefined}
              loadingSkillId={loadingSkillId}
            />
          ))}
        </div>
      </div>
      <ChatSkillDetailDrawer
        skill={skillDetail}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false)
          setSkillDetail(null)
        }}
      />
    </>
  )
}

function ChatSkillInvoke({ data }: { data: Record<string, unknown> }) {
  const title = String(data.title || 'Skill 调用结果')
  const rawItems = (Array.isArray(data.items) ? data.items : []) as Array<Record<string, unknown>>
  const seen = new Set<string>()
  const items = rawItems.filter((it) => {
    const code = String(it.skill_code || it.skill_id || '').replace(/^skill-/, '')
    if (!code || seen.has(code)) return false
    seen.add(code)
    return true
  })
  if (!items.length) return null
  return (
    <div className="chat-skill-invoke">
      <p className="chat-skill-invoke__title">{title}</p>
      <div className="chat-skill-invoke__list">
        {items.map((it) => {
          const code = String(it.skill_code || it.skill_id || '').replace(/^skill-/, '')
          const ok = it.success !== false
          const summary = String(it.summary || '')
          const displaySummary = summary.length > 80 && /[{[]/.test(summary) ? '执行完成' : summary
          return (
            <div key={code} className={`chat-skill-invoke__item${ok ? ' chat-skill-invoke__item--ok' : ' chat-skill-invoke__item--fail'}`}>
              <span className="chat-skill-invoke__badge">{ok ? '✓' : '×'}</span>
              <div className="chat-skill-invoke__body">
                <span className="chat-skill-invoke__code">{code}</span>
                {displaySummary ? <span className="chat-skill-invoke__summary">{displaySummary}</span> : null}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

type PipelineStep = { skill?: string; label?: string; state?: string }

function ChatTaskDetail({
  data,
  onQuickAction,
  disabled,
}: {
  data: Record<string, unknown>
  onQuickAction?: (prompt: string, clientAction?: string) => void
  disabled?: boolean
}) {
  const taskId = String(data.task_id || '')
  const name = String(data.name || '对账任务')
  const period = String(data.period || '—')
  const statusLabel = String(data.status_label || data.status || '')
  const progress = Number(data.progress) || 0
  const pending = Number(data.pending_review) || 0
  const diffTotal = Number(data.diff_total) || 0
  const workbenchPath = String(data.workbench_path || `/workbench/reconciliation/tasks/${taskId}`)
  const pipeline = (Array.isArray(data.pipeline) ? data.pipeline : []) as PipelineStep[]
  const nextAction = (data.next_action || null) as Record<string, string> | null

  const statusColor: Record<string, string> = {
    draft: '#94a3b8',
    running: '#2563eb',
    processing: '#2563eb',
    pending_review: '#ca8a04',
    pending_verification: '#ca8a04',
    reporting: '#7c3aed',
    closed: '#16a34a',
    failed: '#dc2626',
  }
  const color = statusColor[String(data.status)] || '#64748b'

  return (
    <div className="chat-task-detail">
      <div className="chat-task-detail__head">
        <div>
          <h4 className="chat-task-detail__name">{name}</h4>
          <p className="chat-task-detail__meta">{period} · <span style={{ color }}>{statusLabel}</span></p>
        </div>
        <Link to={workbenchPath} className="chat-task-detail__link">工作台 →</Link>
      </div>
      <Progress
        percent={progress}
        size="small"
        strokeColor={color}
        showInfo
        className="chat-task-detail__bar"
      />
      <div className="chat-task-detail__stats">
        {pending > 0 ? <span>待复核 {pending}</span> : null}
        {diffTotal > 0 ? <span>差异 {diffTotal} 条</span> : null}
      </div>
      {pipeline.length > 0 && (
        <div className="chat-task-detail__pipeline">
          <p className="chat-task-detail__pipeline-title">当前流水线</p>
          <div className="chat-task-detail__steps">
            {pipeline.map((step) => {
              const st = step.state || 'pending'
              return (
                <div key={step.skill || step.label} className={`chat-task-detail__step chat-task-detail__step--${st}`}>
                  <span className="chat-task-detail__step-dot" />
                  <span className="chat-task-detail__step-label">{step.label || step.skill}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
      {nextAction?.label && (
        <div className="chat-task-detail__actions">
          {nextAction.workbench_path ? (
            <Link to={nextAction.workbench_path} className="chat-task-detail__cta chat-task-detail__cta--primary">
              {nextAction.label}
            </Link>
          ) : null}
          {nextAction.prompt && onQuickAction ? (
            <button
              type="button"
              className="chat-task-detail__cta chat-task-detail__cta--ghost"
              disabled={disabled}
              onClick={() => onQuickAction(nextAction.prompt!)}
            >
              调用 {nextAction.skill || 'Skill'}
            </button>
          ) : null}
        </div>
      )}
    </div>
  )
}

function ChatTaskList({ data }: { data: Record<string, unknown> }) {
  const title = String(data.title || '近期对账任务')
  const rawItems = (Array.isArray(data.items) ? data.items : []) as Array<Record<string, unknown>>
  const seen = new Set<string>()
  const items = rawItems.filter((t) => {
    const id = String(t.task_id || '')
    const key = id || `${String(t.name)}|${String(t.period)}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  if (data.empty || !items.length) {
    return (
      <div className="chat-widget">
        <div className="chat-widget__title">{title}</div>
        <p className="chat-widget-intro">暂无任务，可点击「发起对账」创建。</p>
      </div>
    )
  }
  const statusColor: Record<string, string> = {
    draft: '#94a3b8',
    running: '#2563eb',
    processing: '#2563eb',
    pending_review: '#ca8a04',
    pending_verification: '#ca8a04',
    reporting: '#7c3aed',
    closed: '#16a34a',
    failed: '#dc2626',
  }
  return (
    <div className="chat-task-block">
      {title && <p className="chat-task-block__title">{title}</p>}
      <div className={`chat-task-grid${items.length <= 2 ? ' chat-task-grid--pair' : ''}`}>
        {items.map((t) => (
          <Link
            key={String(t.task_id)}
            to={`/workbench/reconciliation/tasks/${t.task_id}`}
            className="chat-task-card"
          >
            <div className="chat-task-card__head">
              <span className="chat-task-card__name">{String(t.name)}</span>
              <span
                className="chat-task-card__status"
                style={{ color: statusColor[String(t.status)] || '#64748b' }}
              >
                {String(t.status_label)}
              </span>
            </div>
            <div className="chat-task-card__meta">
              {String(t.period)} · 进度 {Number(t.progress) || 0}%
            </div>
            <div className="chat-task-card__foot">
              {Number(t.pending_review) > 0 ? `待复核 ${t.pending_review}` : '—'}
              {Number(t.diff_total) > 0 ? ` · 差异 ${t.diff_total} 条` : ''}
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}

function ChatQuickActions({
  data,
  onAction,
  disabled,
}: {
  data: Record<string, unknown>
  onAction?: (prompt: string, clientAction?: string) => void
  disabled?: boolean
}) {
  const actions = (Array.isArray(data.actions) ? data.actions : []) as Array<Record<string, string>>
  return (
    <div className="chat-quick-actions">
      {actions.map((a) => (
        <button
          key={a.label}
          type="button"
          className={`chat-quick-pill${a.variant === 'primary' ? ' chat-quick-pill--primary' : ' chat-quick-pill--ghost'}`}
          disabled={disabled}
          onClick={() => onAction?.(a.prompt, a.client_action)}
        >
          {a.label}
        </button>
      ))}
    </div>
  )
}

function ChatAgentPlan({ data }: { data: Record<string, unknown> }) {
  const steps = (Array.isArray(data.steps) ? data.steps : []) as Array<Record<string, string>>
  return <ChatExecutionProcess steps={steps} />
}

function WelcomeCapCard({
  cap,
  onCapAction,
  disabled,
}: {
  cap: WelcomeCapItem
  onCapAction?: (prompt: string, clientAction?: string) => void
  disabled?: boolean
}) {
  const inner = (
    <>
      <span className="chat-cap-card__num">{cap.n}</span>
      <div className="chat-cap-card__body">
        <div className="chat-cap-card__title">{cap.title}</div>
        <div className="chat-cap-card__desc">{cap.desc}</div>
      </div>
    </>
  )
  const linkClass = 'chat-cap-card chat-cap-card--link'

  if (cap.prompt && onCapAction) {
    return (
      <button
        key={cap.n}
        type="button"
        className={`${linkClass} chat-cap-card--action`}
        disabled={disabled}
        onClick={() => onCapAction(cap.prompt!, cap.client_action || (cap.kb_id ? 'query_knowledge' : undefined))}
      >
        {inner}
      </button>
    )
  }
  if (cap.href) {
    return (
      <Link key={cap.n} to={cap.href} className={linkClass}>
        {inner}
      </Link>
    )
  }
  if (cap.kb_id && onCapAction) {
    const fTitle = cap.title || '知识库'
    return (
      <button
        key={cap.n}
        type="button"
        className={`${linkClass} chat-cap-card--action`}
        disabled={disabled}
        onClick={() => onCapAction(
          `请检索${fTitle}，说明常见收入/回款异常场景的排查要点`,
          'query_knowledge',
        )}
      >
        {inner}
      </button>
    )
  }
  if (cap.kb_id) {
    return (
      <Link
        key={cap.n}
        to={`/admin?tab=knowledge&kb=${encodeURIComponent(cap.kb_id)}`}
        className={linkClass}
      >
        {inner}
      </Link>
    )
  }
  return (
    <div key={cap.n} className="chat-cap-card">
      {inner}
    </div>
  )
}

export function ChatWelcomeCaps({
  data,
  layout = 'card',
  onCapAction,
  disabled,
}: {
  data: Record<string, unknown>
  layout?: 'card' | 'landing'
  onCapAction?: (prompt: string, clientAction?: string) => void
  disabled?: boolean
}) {
  const safe = sanitizeWelcomeBlockData(data)
  const agentName = String(safe.agent_name || '收入核对助手')
  const avatarId = String(safe.avatar_id || 'anime-04')
  const description = String(safe.description || '').trim()
  const isLanding = layout === 'landing'
  const items = (Array.isArray(safe.items) ? safe.items : []) as WelcomeCapItem[]
  const mountTags = Array.isArray(safe.mount_tags) ? (safe.mount_tags as string[]) : []
  const fallback: WelcomeCapItem[] = [
    enrichWelcomeCapAction({ n: 1, title: '查看对账任务', desc: '了解进度、待复核与最近批次' }),
    enrichWelcomeCapAction({ n: 2, title: '差异智能解释', desc: '说明差异原因与处理建议' }),
    enrichWelcomeCapAction({ n: 3, title: '对话内发起核对', desc: '选择 SAP 发货开票与 DMS 收入台账进行比对' }),
    enrichWelcomeCapAction({ n: 4, title: '进入收入核对工作台', desc: '进入正式任务，完成复核与报告' }),
  ]
  const caps = items.length ? items : fallback
  const descText = description || '帮您查任务、解释差异、发起核对，并可引导进入正式收入核对流程。'
  return (
    <div className={`chat-welcome-card${isLanding ? ' chat-welcome-card--landing' : ''}`}>
      {!isLanding && (
        <div className="chat-welcome-card__hero">
          <img className="chat-welcome-card__avatar" src={avatarImageUrl(avatarId)} alt="" />
          <div className="chat-welcome-card__hero-text">
            <h3 className="chat-welcome-card__name">{agentName}</h3>
            <p className="chat-welcome-card__desc">{descText}</p>
          </div>
        </div>
      )}
      <div className="chat-cap-grid">
        {caps.map((cap) => (
          <WelcomeCapCard
            key={cap.n}
            cap={cap}
            onCapAction={onCapAction}
            disabled={disabled}
          />
        ))}
      </div>
      {!isLanding && mountTags.length > 0 && (
        <div className="chat-welcome-mounts" aria-label="已具备能力">
          {mountTags.map((tag) => (
            <span key={tag} className="chat-welcome-mount-tag">{tag}</span>
          ))}
        </div>
      )}
      {!isLanding && (
        <p className="chat-welcome-hint">点击上方能力卡片，或在输入框描述需求。</p>
      )}
    </div>
  )
}

type FaqStep = { title: string; desc: string }

const FAQ_PIPELINE_DESC: Record<string, string> = {
  import: '读取已接入的业务侧、财务侧数据源（SAP / DMS 等）。',
  mapping: '按管理后台「数据语义 → 字段映射」配置的列对照与翻译规则对齐。',
  ontology: '加载已发布实体与领域规则，供识别与解释引用。',
  detect: '按规则引擎识别金额差异、重复数据、主数据/映射异常。',
  ai_explain: '大模型结合规则与证据链生成差异解释。',
  review: '在「待复核」中确认、退回或指派处理。',
  verify: '处理完成后重新跑批，验证是否闭环。',
  report: '生成 PDF 对账报告并归档。',
}

function faqStepsToPipelineItems(steps: FaqStep[]): WorkflowStepItem[] {
  return EXECUTION_PIPELINE.map((node, i) => {
    const fromApi = steps[i]
    const desc = (fromApi?.desc || '').trim() || FAQ_PIPELINE_DESC[node.id] || ''
    return {
      title: node.label,
      descriptionLines: desc ? [desc] : undefined,
      status: 'wait' as const,
    }
  })
}

function ChatFaqWorkflow({ data }: { data: Record<string, unknown> }) {
  const title = String(data.title || '收入核对标准流程')
  const steps = (Array.isArray(data.steps) ? data.steps : []) as FaqStep[]
  const hint = String(data.hint || '')
  const pipelineItems = faqStepsToPipelineItems(steps)
  return (
    <div className="chat-faq-flow">
      <div className="chat-faq-flow__head">
        <span className="chat-faq-flow__badge">Workflow</span>
        <h4 className="chat-faq-flow__title">{title}</h4>
      </div>
      <WorkflowStepsPipeline items={pipelineItems} />
      {hint ? <p className="chat-faq-hint">{hint}</p> : null}
      {data.workbench_path ? (
        <Link to={String(data.workbench_path)} className="chat-min-link">进入工作台 →</Link>
      ) : null}
    </div>
  )
}

function ChatWorkflowCta({ data }: { data: Record<string, unknown> }) {
  const path = String(data.path || '/workbench/reconciliation/tasks/new')
  const hint = String(data.hint || '')
  return (
    <p className="chat-min-inline">
      <Link to={path} className="chat-min-link">{String(data.title || '进入收入核对工作台')} →</Link>
      {hint ? <span className="chat-min-list__desc"> {hint}</span> : null}
    </p>
  )
}

function ChatAgentCta({ data }: { data: Record<string, unknown> }) {
  return (
    <p className="chat-min-inline">
      <span className="chat-min-list__desc">{String(data.label || '转人工处理')}</span>
    </p>
  )
}

type FaqDiffItem = {
  kind: string
  label: string
  severity?: string
  definition: string
  action: string
  owner?: string
  troubleshooting?: string
  rule_id?: string
}

const FAQ_DIFF_ICON: Record<string, ReactNode> = {
  amount: <AccountBookOutlined />,
  duplicate: <CopyOutlined />,
  mapping: <SwapOutlined />,
  payment: <AccountBookOutlined />,
  sync: <DatabaseOutlined />,
  status: <SwapOutlined />,
  fanruan: <DatasourceBrandIcon catalog="fanruan" size={18} showEngine={false} />,
}

function ChatFaqDiffTypes({ data }: { data: Record<string, unknown> }) {
  const title = String(data.title || '三类核心差异')
  const items = (Array.isArray(data.items) ? data.items : []) as FaqDiffItem[]
  const hint = String(data.hint || '')
  const ruleVersionId = data.rule_version_id ? String(data.rule_version_id) : ''
  const fromRuleEngine = data.source === 'rule_engine' || Boolean(ruleVersionId)
  return (
    <div className="chat-faq-diff">
      <div className="chat-faq-diff__head">
        <span className="chat-faq-diff__badge">{fromRuleEngine ? '规则引擎' : '差异类型'}</span>
        <h4 className="chat-faq-diff__title">{title}</h4>
        {ruleVersionId ? (
          <span className="chat-faq-diff__version">版本 {ruleVersionId.slice(0, 8)}</span>
        ) : null}
      </div>
      <div className={`chat-faq-diff__grid${items.length > 3 ? ' chat-faq-diff__grid--multi' : ''}`}>
        {items.map((item) => (
          <div key={item.rule_id || item.kind || item.label} className="chat-faq-diff__card">
            <div className="chat-faq-diff__card-top">
              <span className={`chat-faq-diff__icon chat-faq-diff__icon--${item.kind || 'generic'}`}>
                {FAQ_DIFF_ICON[item.kind] || <DatabaseOutlined />}
              </span>
              <div className="chat-faq-diff__labels">
                <span className="chat-faq-diff__name">{item.label}</span>
                {item.severity ? (
                  <span
                    className={`chat-faq-diff__sev chat-faq-diff__sev--${
                      item.severity === '高' || item.severity === 'high' ? 'high' : 'mid'
                    }`}
                  >
                    {item.severity}
                  </span>
                ) : null}
              </div>
            </div>
            <p className="chat-faq-diff__def">{item.definition}</p>
            {item.troubleshooting ? (
              <pre className="chat-faq-diff__troubleshooting">{item.troubleshooting}</pre>
            ) : null}
            {item.action ? (
              <p className="chat-faq-diff__action">
                <span className="chat-faq-diff__action-label">处置</span>
                {item.action}
              </p>
            ) : null}
            {item.owner ? <span className="chat-faq-diff__owner">责任：{item.owner}</span> : null}
          </div>
        ))}
      </div>
      {hint ? <p className="chat-faq-hint">{hint}</p> : null}
    </div>
  )
}

function systemCardSideClass(system: SystemItem): string {
  if (system.side === 'finance' || system.kind === 'dms') return 'chat-sys-card--finance'
  if (system.side === 'business' || system.kind === 'sap') return 'chat-sys-card--business'
  return 'chat-sys-card--generic'
}

function SystemCard({
  system,
  selected,
  onOpen,
}: {
  system: SystemItem
  selected?: boolean
  onOpen?: () => void
}) {
  const ok = system.status === 'ok' || system.status === 'connected' || system.status === 'ready'
  return (
    <div
      className={`chat-sys-card chat-sys-card--clickable ${systemCardSideClass(system)}${selected ? ' is-selected' : ''}`}
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen?.() } }}
    >
      <div className={`chat-sys-card__icon chat-sys-card__icon--${system.kind || 'generic'}`}>
        <DatasourceVisualIcon kind={system.kind} size={32} showEngine={system.kind === 'sap' || system.kind === 'dms'} />
      </div>
      <div className="chat-sys-card__content">
        <div className="chat-sys-card__name">{system.system_label}</div>
        <div className="chat-sys-card__sync">
          最近同步 · {system.last_sync}
          {system.row_count != null ? ` · ${system.row_count} 行` : ''}
        </div>
        <div className={`chat-sys-card__status${ok ? ' is-ok' : ''}`}>
          {ok ? <CheckCircleFilled /> : <ExclamationCircleFilled />}
          <span>{system.status_label || (ok ? '连接正常' : '待检查')}</span>
        </div>
        <div className="chat-sys-card__hint">点击查看后台数据</div>
      </div>
    </div>
  )
}

function ChatDatasourcePreviewModal({
  open,
  loading,
  preview,
  onClose,
}: {
  open: boolean
  loading: boolean
  preview: DataSourcePreview | null
  onClose: () => void
}) {
  return (
    <Modal
      title={preview ? `${preview.name}（共 ${preview.total_rows} 行）` : '数据源预览'}
      open={open}
      onCancel={onClose}
      footer={null}
      width={920}
      destroyOnClose
    >
      <Table
        size="small"
        loading={loading}
        pagination={{ pageSize: 20, size: 'small', showTotal: (t) => `预览前 ${t} 行 / 共 ${preview?.total_rows ?? 0} 行` }}
        scroll={{ x: Math.max((preview?.columns.length || 1) * 140, 600) }}
        rowKey={(r) => (preview?.columns || []).map((c) => String(r[c] ?? '')).join('|')}
        dataSource={preview?.rows || []}
        columns={(preview?.columns || []).map((col) => ({
          title: col,
          dataIndex: col,
          key: col,
          ellipsis: true,
          width: 140,
        }))}
      />
    </Modal>
  )
}

function applyChatReconciliationOptions(
  data: Record<string, unknown>,
  opts: ChatReconciliationOptions,
): Record<string, unknown> {
  const rec = opts.recommended
  return {
    ...data,
    systems: opts.systems,
    recommended_business_id: rec.business_datasource_id,
    recommended_finance_id: rec.finance_datasource_id,
    recommended_display_ids: rec.display_ids || [],
    has_datasource_pair: opts.has_datasource_pair,
    has_uploaded_pair: opts.has_uploaded_pair,
    mapping_ready: opts.mapping_ready,
    mapping_hint: opts.mapping_hint || '',
    demo_dataset_id: opts.demo_dataset_id,
  }
}

function ChatDatasourceConfirm({
  data,
  conversationId,
  agentId,
  onExecuted,
  disabled,
}: {
  data: Record<string, unknown>
  conversationId?: string
  agentId?: string
  onExecuted?: (reply: string, blocks: ChatUiBlock[], taskId?: string) => void
  disabled?: boolean
}) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [cardData, setCardData] = useState(data)
  const [tab, setTab] = useState<'recommended' | 'custom'>('recommended')
  const [executing, setExecuting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [preview, setPreview] = useState<DataSourcePreview | null>(null)
  const systems = (cardData.systems as SystemItem[]) || []
  const period = String(cardData.period || '2024-05')
  const recBiz = String(cardData.recommended_business_id || '')
  const recFin = String(cardData.recommended_finance_id || '')
  const displayIds = (cardData.recommended_display_ids as string[]) || []
  const hasDatasourcePair = Boolean(cardData.has_datasource_pair)
  const mappingHint = String(cardData.mapping_hint || '')
  const demoDatasetId = String(cardData.demo_dataset_id || 'dataset_fangtai_real')
  const [bizId, setBizId] = useState(recBiz)
  const [finId, setFinId] = useState(recFin)

  useEffect(() => {
    setCardData(data)
    setBizId(String(data.recommended_business_id || ''))
    setFinId(String(data.recommended_finance_id || ''))
  }, [data])

  const effectiveAgentId = String(cardData.agent_id || agentId || '').trim() || undefined

  const mergeOptions = (opts: ChatReconciliationOptions) => {
    const next = applyChatReconciliationOptions(cardData, opts)
    setCardData(next)
    setBizId(String(next.recommended_business_id || ''))
    setFinId(String(next.recommended_finance_id || ''))
  }

  const handleUploadFiles = async (files: FileList | File[] | null) => {
    const file = files?.[0]
    if (!file || uploading) return
    const lower = file.name.toLowerCase()
    setUploading(true)
    try {
      if (/\.(xlsx|xls|xlsm)$/.test(lower)) {
        const res = await chatImportDatasourcesFromExcel(file, effectiveAgentId)
        message.success(res.message || 'Excel 导入完成')
        if (res.bind_message) message.info(res.bind_message)
        mergeOptions(res.options)
      } else {
        const res = await chatUploadDatasource(file, effectiveAgentId)
        message.success(`已上传「${res.name}」（${res.row_count} 行）`)
        mergeOptions(res.options)
      }
    } catch {
      message.error('上传失败，请确认文件为 xlsx / csv 且大小不超过 25MB')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleConnectDemo = async () => {
    if (connecting) return
    setConnecting(true)
    try {
      const res = await chatConnectDemoDatasources(effectiveAgentId)
      message.success(res.message)
      mergeOptions(res.options)
    } catch {
      message.error('连接演示库失败，请稍后重试')
    } finally {
      setConnecting(false)
    }
  }

  const bizOptions = useMemo(
    () => systems.filter((s) => s.side === 'business').map((s) => ({ value: s.id, label: s.name })),
    [systems],
  )
  const finOptions = useMemo(
    () => systems.filter((s) => s.side === 'finance').map((s) => ({ value: s.id, label: s.name })),
    [systems],
  )

  const displaySystems = useMemo(() => {
    if (tab === 'recommended') {
      if (displayIds.length) {
        const map = new Map(systems.map((s) => [s.id, s]))
        return displayIds.map((id) => map.get(id)).filter(Boolean) as SystemItem[]
      }
      return systems.filter((s) => s.id === recBiz || s.id === recFin)
    }
    const ids = new Set([bizId, finId].filter(Boolean))
    return systems.filter((s) => ids.has(s.id))
  }, [tab, systems, displayIds, recBiz, recFin, bizId, finId])

  const selectedIds = new Set(tab === 'recommended' ? displayIds : [bizId, finId].filter(Boolean))

  const openPreview = async (system: SystemItem) => {
    setPreviewOpen(true)
    setPreviewLoading(true)
    setPreview(null)
    try {
      const dataPreview = await chatPreviewDatasource(system.id, effectiveAgentId)
      setPreview(dataPreview)
    } catch (e) {
      console.error('datasource preview failed', e)
      message.error('无法打开数据源，请确认该数据源已在后台配置且当前 Agent 已授权')
      setPreviewOpen(false)
    } finally {
      setPreviewLoading(false)
    }
  }

  const run = async () => {
    setExecuting(true)
    try {
      const useDemo = tab === 'recommended' && !hasDatasourcePair
      const res = await chatExecuteReconciliation({
        conversation_id: conversationId,
        agent_id: effectiveAgentId,
        period,
        use_recommended: tab === 'recommended' && hasDatasourcePair,
        business_datasource_id: tab === 'custom' ? bizId : undefined,
        finance_datasource_id: tab === 'custom' ? finId : undefined,
        demo_dataset_id: useDemo ? demoDatasetId : undefined,
      })
      onExecuted?.(res.reply, res.ui_blocks || [], res.task_id)
    } catch {
      message.error('发起核对失败，请确认业务中心已发布且数据源可用')
    } finally {
      setExecuting(false)
    }
  }

  const gridClass = displaySystems.length <= 2 ? ' chat-sys-grid--pair' : ''

  const intro = String(cardData.intro || '').trim()
  const canRunRecommended = tab === 'recommended' && (hasDatasourcePair || demoDatasetId)
  const runDisabled = disabled || executing || uploading || connecting
    || (tab === 'custom' && (!bizId || !finId))
    || (tab === 'recommended' && !canRunRecommended)

  return (
    <div className="chat-widget chat-widget--datasource">
      {intro && <p className="chat-widget-intro">{intro}</p>}
      {mappingHint && !hasDatasourcePair ? (
        <p className="chat-widget-hint">{mappingHint}</p>
      ) : null}
      <div className="chat-widget__head chat-widget__head--ds">
        <span className="chat-widget__title">数据来源 · {period}</span>
        <div className="chat-seg-tabs">
          <button
            type="button"
            className={`chat-seg-tab${tab === 'recommended' ? ' is-active' : ''}`}
            onClick={() => setTab('recommended')}
          >
            推荐方案
          </button>
          <button
            type="button"
            className={`chat-seg-tab${tab === 'custom' ? ' is-active' : ''}`}
            onClick={() => setTab('custom')}
          >
            自定义方案
          </button>
        </div>
      </div>

      {tab === 'custom' && (
        <div className="chat-widget-custom">
          <div className="chat-widget-custom-row">
            <label>业务侧</label>
            <Select size="small" placeholder="选择业务侧数据源" value={bizId || undefined} options={bizOptions} onChange={setBizId} />
          </div>
          <div className="chat-widget-custom-row">
            <label>财务侧</label>
            <Select size="small" placeholder="选择财务侧数据源" value={finId || undefined} options={finOptions} onChange={setFinId} />
          </div>
        </div>
      )}

      <div className={`chat-sys-grid${gridClass}`}>
        {displaySystems.map((s) => (
          <SystemCard key={s.id} system={s} selected={selectedIds.has(s.id)} onOpen={() => openPreview(s)} />
        ))}
        {displaySystems.length === 0 && (
          <div className="chat-widget-empty">
            <p>暂无已接入数据源。可上传方太 POC Excel，或连接 SAP / DMS 演示库后直接对账。</p>
            <div className="chat-widget-empty__actions">
              <Button
                size="small"
                icon={<DatasourcePairIcons size={16} />}
                loading={connecting}
                disabled={runDisabled}
                onClick={handleConnectDemo}
              >
                连接 SAP / DMS 演示库
              </Button>
            </div>
          </div>
        )}
      </div>

      <ChatDatasourcePreviewModal
        open={previewOpen}
        loading={previewLoading}
        preview={preview}
        onClose={() => { setPreviewOpen(false); setPreview(null) }}
      />

      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.xls,.xlsm,.csv"
        className="chat-widget-upload-input"
        onChange={(e) => { void handleUploadFiles(e.target.files) }}
      />
      <div
        className={`chat-widget-upload-zone${uploading ? ' is-busy' : ''}`}
        role="button"
        tabIndex={0}
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={(e) => { if (e.key === 'Enter') fileInputRef.current?.click() }}
        onDragOver={(e) => { e.preventDefault(); e.stopPropagation() }}
        onDrop={(e) => {
          e.preventDefault()
          e.stopPropagation()
          void handleUploadFiles(e.dataTransfer.files)
        }}
      >
        <CloudUploadOutlined className="chat-widget-upload-zone__icon" />
        <p className="chat-widget-upload-zone__title">
          {uploading ? '正在导入数据…' : '拖拽文件到此处，或点击上传'}
        </p>
        <p className="chat-widget-upload-zone__desc">支持方太 POC 多 Sheet Excel、csv 单表</p>
        <button
          type="button"
          className="chat-widget-upload-zone__link"
          disabled={uploading}
          onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click() }}
        >
          上传新文件
        </button>
      </div>

      {displaySystems.length > 0 && !hasDatasourcePair ? (
        <div className="chat-widget-connect-row">
          <Button
            type="link"
            size="small"
            icon={<DatasourcePairIcons size={14} />}
            loading={connecting}
            disabled={runDisabled}
            onClick={handleConnectDemo}
          >
            或连接 SAP / DMS 演示库
          </Button>
        </div>
      ) : null}

      <Button
        type="primary"
        block
        size="large"
        className="chat-widget-run"
        loading={executing}
        disabled={runDisabled}
        onClick={run}
      >
        {hasDatasourcePair ? '使用推荐方案进行对账分析' : '使用演示数据开始对账'}
      </Button>
    </div>
  )
}

function ChatTaskProgress({
  data,
  onTaskCompleted,
}: {
  data: Record<string, unknown>
  onTaskCompleted?: (taskId: string) => void
}) {
  const taskId = String(data.task_id || '')
  const [task, setTask] = useState<Task | null>(null)
  const [resuming, setResuming] = useState(false)
  const resumeAttempted = useRef(false)
  const completedNotified = useRef(false)

  useEffect(() => {
    if (!taskId) return
    getTask(taskId).then(setTask).catch(() => {})
    const timer = setInterval(() => {
      getTask(taskId).then(setTask).catch(() => {})
    }, 3000)
    return () => clearInterval(timer)
  }, [taskId])

  const progress = task?.progress ?? Number(data.progress) ?? 0
  const status = task?.status || String(data.status || 'running')
  const failed = status === 'failed'
  const done = status === 'pending_review' || status === 'pending_verification' || status === 'reporting' || status === 'closed' || progress >= 85
  const stuck = !done && !failed && status === 'running' && progress <= 60

  useEffect(() => {
    if (!taskId || !done || failed || completedNotified.current) return
    completedNotified.current = true
    onTaskCompleted?.(taskId)
  }, [taskId, done, failed, onTaskCompleted])

  useEffect(() => {
    if (!taskId || done || failed || resuming || resumeAttempted.current) return
    const timer = window.setTimeout(async () => {
      const latest = await getTask(taskId).catch(() => null)
      if (!latest || latest.status !== 'running' || latest.progress >= 85) return
      resumeAttempted.current = true
      setResuming(true)
      try {
        const resumed = await resumeTaskExecution(taskId)
        setTask(resumed)
      } catch {
        resumeAttempted.current = false
      } finally {
        setResuming(false)
      }
    }, 120000)
    return () => window.clearTimeout(timer)
  }, [taskId, done, failed, resuming])

  const handleResume = async () => {
    if (!taskId || resuming) return
    setResuming(true)
    try {
      const resumed = await resumeTaskExecution(taskId)
      setTask(resumed)
      resumeAttempted.current = true
    } finally {
      setResuming(false)
    }
  }

  return (
    <div className="chat-widget chat-widget--progress">
      <div className="chat-widget-progress-head">
        {failed ? <ExclamationCircleFilled className="warn" /> : done ? <CheckCircleFilled className="ok" /> : <LoadingOutlined spin={!resuming} />}
        <div>
          <div className="chat-widget-progress-title">
            {failed ? '对账分析失败，请重试' : done ? '三系统对账分析已完成，待复核' : resuming ? '检测到任务中断，正在恢复执行…' : '已收到，正在进行三系统对账分析，请稍候…'}
          </div>
          <div className="chat-widget-progress-sub">
            {failed ? (task?.error_message || '后台执行异常') : done ? '分析完成，结果摘要如下' : '预计 1–3 分钟完成字段映射、差异识别与 AI 解释'}
          </div>
        </div>
      </div>
      <Progress
        percent={failed ? progress : done ? 100 : Math.max(progress, 8)}
        status={failed ? 'exception' : done ? 'success' : 'active'}
        strokeColor={failed ? '#ef4444' : done ? '#16a34a' : '#f97316'}
        showInfo
        size="small"
      />
      {stuck && !resuming && (
        <Button type="link" size="small" className="chat-widget-resume-btn" onClick={handleResume}>
          进度长时间未更新？点击继续执行
        </Button>
      )}
      {taskId && !done && (
        <Link to={`/workbench/reconciliation/tasks/${taskId}`} className="chat-widget-task-link">
          查看任务详情 →
        </Link>
      )}
    </div>
  )
}

type ResultSample = {
  id: string
  business_key?: string
  type: string
  amount_diff?: number
  ai_explanation?: string
}

function ChatDifferenceList({ data }: { data: Record<string, unknown> }) {
  const taskId = String(data.task_id || '')
  const title = String(data.title || '差异清单')
  const total = Number(data.total) || 0
  const offset = Number(data.offset) || 0
  const items = (data.items as ResultSample[]) || []
  const byType = (data.by_type as Record<string, number>) || {}
  const period = String(data.period || '')
  const typeEntries = Object.entries(byType)

  return (
    <div className="chat-widget chat-widget--result">
      <div className="chat-widget__head">
        <span className="chat-widget__title">{title}</span>
        <span className="chat-widget__period">
          {period ? `${period} · ` : ''}共 {total} 条{offset > 0 ? ` · 从第 ${offset + 1} 条起` : ''}
        </span>
      </div>
      {typeEntries.length > 0 && (
        <div className="chat-result-types">
          {typeEntries.map(([type, count]) => (
            <span key={type} className="chat-result-type-tag">{type} {count}</span>
          ))}
        </div>
      )}
      {items.length > 0 ? (
        <div className="chat-result-samples">
          {items.map((s, idx) => (
            <div key={s.id} className="chat-result-sample-row">
              <div className="chat-result-sample-row__head">
                <span className="chat-result-sample-row__idx">{offset + idx + 1}</span>
                <span className="chat-result-sample-row__key">{s.business_key || '—'}</span>
                <span className="chat-result-sample-row__type">{s.type}</span>
                {s.amount_diff != null && (
                  <span className="chat-result-sample-row__amt">¥{Number(s.amount_diff).toLocaleString()}</span>
                )}
              </div>
              {s.ai_explanation && (
                <div className="chat-result-sample-row__ai">{s.ai_explanation}</div>
              )}
              {taskId && (
                <Link
                  to={`/chat?task_id=${taskId}&difference_id=${s.id}`}
                  className="chat-min-link chat-result-sample-row__link"
                >
                  解释本条差异 →
                </Link>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="chat-widget__hint">暂无更多差异条目。</p>
      )}
      {taskId && (
        <Link to={`/workbench/reconciliation/tasks/${taskId}`} className="chat-widget-task-link">
          在工作台查看完整差异清单 →
        </Link>
      )}
    </div>
  )
}

function ChatReconciliationResult({ data }: { data: Record<string, unknown> }) {
  const taskId = String(data.task_id || '')
  const total = Number(data.total) || 0
  const byType = (data.by_type as Record<string, number>) || {}
  const totalAmount = Number(data.total_difference_amount) || 0
  const samples = (data.samples as ResultSample[]) || []
  const period = String(data.period || '')
  const businessRows = data.business_rows as number | undefined
  const financeRows = data.finance_rows as number | undefined
  const matched = Number(data.matched_count) || undefined

  const typeEntries = Object.entries(byType)

  return (
    <div className="chat-widget chat-widget--result">
      <div className="chat-widget__head">
        <span className="chat-widget__title">对账结果摘要</span>
        <span className="chat-widget__period">{period} 核对周期</span>
      </div>
      <ReconciliationSystemSummary
        businessRows={businessRows}
        financeRows={financeRows}
        diffCount={total}
        matchedEstimate={matched}
        title="对账结果"
        extraMetrics={[
          {
            label: '差异金额合计',
            value: totalAmount >= 10000 ? `${(totalAmount / 10000).toFixed(1)}万` : totalAmount.toLocaleString(),
            tone: 'accent',
          },
          ...typeEntries.map(([type, count]) => ({ label: type, value: count })),
        ]}
      />
      {samples.length > 0 && (
        <div className="chat-result-samples">
          <div className="chat-result-samples__title">主要差异（前 {samples.length} 条）</div>
          {samples.map((s) => (
            <div key={s.id} className="chat-result-sample-row">
              <div className="chat-result-sample-row__head">
                <span className="chat-result-sample-row__key">{s.business_key || '—'}</span>
                <span className="chat-result-sample-row__type">{s.type}</span>
                {s.amount_diff != null && (
                  <span className="chat-result-sample-row__amt">¥{Number(s.amount_diff).toLocaleString()}</span>
                )}
              </div>
              {s.ai_explanation && (
                <div className="chat-result-sample-row__ai">{s.ai_explanation}</div>
              )}
            </div>
          ))}
        </div>
      )}
      {taskId && (
        <Link to={`/workbench/reconciliation/tasks/${taskId}`} className="chat-widget-task-link">
          查看完整差异列表 →
        </Link>
      )}
    </div>
  )
}

function ChatReviewPrompt({
  data,
  onStartReview,
  disabled,
}: {
  data: Record<string, unknown>
  onStartReview?: (taskId: string) => void
  disabled?: boolean
}) {
  const taskId = String(data.task_id || '')
  const pendingCount = Number(data.pending_count) || 0

  return (
    <div className="chat-widget chat-widget--review-prompt">
      <p className="chat-review-prompt__question">
        {pendingCount > 0
          ? `共 ${pendingCount} 条差异待复核，是否现在开始？您可以在对话中逐条确认，或稍后在任务中心处理。`
          : '本次核对未发现差异，可进入任务详情查看报告或继续后续流程。'}
      </p>
      <div className="chat-review-prompt__actions">
        {pendingCount > 0 && (
          <Button
            type="primary"
            className="chat-review-prompt__primary"
            disabled={disabled}
            onClick={() => onStartReview?.(taskId)}
          >
            现在开始复核
          </Button>
        )}
        <Link to={`/workbench/reconciliation/tasks/${taskId}`}>
          <Button disabled={disabled}>打开任务详情</Button>
        </Link>
      </div>
    </div>
  )
}

function ChatReviewInline({
  data,
  onReviewDone,
  disabled,
}: {
  data: Record<string, unknown>
  onReviewDone?: (taskId: string) => void
  disabled?: boolean
}) {
  const taskId = String(data.task_id || '')
  const diffId = String(data.difference_id || '')
  const index = Number(data.index) || 1
  const total = Number(data.total) || 1
  const [submitting, setSubmitting] = useState(false)

  const runReview = async (decision: 'confirm' | 'reject') => {
    if (!diffId || submitting) return
    setSubmitting(true)
    try {
      await reviewDifference(diffId, decision, decision === 'confirm' ? '对话内确认' : '对话内退回')
      message.success(decision === 'confirm' ? '已确认该差异' : '已退回该差异')
      onReviewDone?.(taskId)
    } catch {
      message.error('复核操作失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="chat-widget chat-widget--review-inline">
      <div className="chat-review-inline__badge">复核 {index}/{total}</div>
      <div className="chat-review-inline__head">
        <span className="chat-review-inline__key">{String(data.business_key || '—')}</span>
        <span className="chat-review-inline__type">{String(data.type || '')}</span>
        {data.amount_diff != null && (
          <span className="chat-review-inline__amt">¥{Number(data.amount_diff).toLocaleString()}</span>
        )}
      </div>
      {Boolean(data.ai_explanation) && (
        <div className="chat-review-inline__ai">{String(data.ai_explanation)}</div>
      )}
      <div className="chat-review-inline__actions">
        <Button type="primary" loading={submitting} disabled={disabled || submitting} onClick={() => runReview('confirm')}>
          确认差异
        </Button>
        <Button danger loading={submitting} disabled={disabled || submitting} onClick={() => runReview('reject')}>
          退回
        </Button>
      </div>
    </div>
  )
}

export function UserMessageStack({ content, time }: { content: string; time?: string }) {
  return (
    <div className="chat-msg-stack chat-msg-stack--user">
      <div className="chat-fs-bubble chat-fs-bubble--user chat-fs-bubble--compact">{content}</div>
      {time && <span className="chat-fs-time">{formatTime(time)}</span>}
    </div>
  )
}
