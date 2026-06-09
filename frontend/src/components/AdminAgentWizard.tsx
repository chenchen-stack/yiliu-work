import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button, Col, Form, Input, Modal, Progress, Row, Space, Tag, Typography, message,
} from 'antd'
import {
  BookOutlined, CheckOutlined, CheckCircleOutlined, DatabaseOutlined, ReadOutlined,
  RightOutlined, RobotOutlined, SafetyCertificateOutlined, SettingOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import {
  createAdminAgentTemplate, getAdminLlmConfig, updateAdminAgent, type AgentConfigItem, type LlmConfig,
} from '../api/client'
import { formatApiError } from '../api/errors'
import {
  ANIME_AVATARS, avatarImageUrl, getAnimeAvatar, resolveAvatarId,
} from '../utils/agentAvatars'
import {
  FixedAssetPanel, KB_PANEL_ICON, KB_SUMMARY_ICON,
  ModelRouteHint, OriginBlankVisual, OriginPresetVisual, SKILL_SUMMARY_ICON,
  SummaryRow, TABLE_PAIR_ICON, TARGET_ICON, WF_PANEL_ICON, WF_SUMMARY_ICON,
  WIZARD_DS_ICONS, WIZARD_MODEL_ICONS, WIZARD_SKILL_ICONS, WIZARD_STATUS_ICONS,
  WizardOptionIcon, type WizardIconTone,
} from './agentWizardVisuals'
import { AgentAssetConfigModal } from './AgentAssetConfigModal'
import { buildAdminTabUrl, resolveAgentAsset } from '../utils/agentAssetConfig'

const { TextArea } = Input
const { Text, Title } = Typography

/** 方太 POC 固定业务资产 */
const FANGTAI_WORKFLOW_ID = 'wf-revenue-reconciliation-v1'
const FANGTAI_KB_ID = 'kb-fangtai-cases'
const FANGTAI_KNOWLEDGE_SCOPE = 'revenue_reconciliation'
const FANGTAI_SKILL_IDS = ['skill-anomaly_explain', 'skill-query_tasks'] as const

const FANGTAI_SKILL_CARDS = [
  { value: 'skill-anomaly_explain', label: '异常解释', desc: '差异原因 · 规则命中说明' },
  { value: 'skill-query_tasks', label: '任务查询', desc: '对账任务进度与批次' },
]

const FANGTAI_DATA_SCOPES = [
  { value: 'sap_billing', label: 'SAP 发货开票', desc: '方太发货开票明细' },
  { value: 'dms_ledger', label: 'DMS 收入台账', desc: '方太收入台账明细' },
]

const KNOWLEDGE_BASE_OPTIONS = [
  {
    value: 'kb-fangtai-cases',
    label: '方太历史案例库',
    desc: '差异复核沉淀；对话解释差异时引用',
    iconTone: 'orange' as const,
  },
  {
    value: 'revenue_reconciliation',
    label: '收入核对知识',
    desc: '登记表/Excel 对账经验；自然语言问答检索',
    iconTone: 'blue' as const,
  },
  {
    value: 'kb-compliance',
    label: '合规与校验要点',
    desc: '合规口径与复核要点',
    iconTone: 'green' as const,
  },
]

const KB_OPTION_ICONS: Record<string, ReactNode> = {
  'kb-fangtai-cases': <BookOutlined />,
  'revenue_reconciliation': <ReadOutlined />,
  'kb-compliance': <SafetyCertificateOutlined />,
}

const DEEPSEEK_UI_VALUE = 'deepseek-v4-pro'

function isDeepSeekRoute(route?: string | null) {
  return !!route && route !== 'mock-ai'
}

function toFormModelRoute(route?: string | null) {
  return isDeepSeekRoute(route) ? DEEPSEEK_UI_VALUE : 'mock-ai'
}

function toPayloadModelRoute(formValue: string, platformModel?: string) {
  if (formValue === 'mock-ai') return 'mock-ai'
  return platformModel || DEEPSEEK_UI_VALUE
}

const FANGTAI_MODEL_CARDS = [
  { value: 'mock-ai', label: 'Mock 演示', desc: '本地 POC 联调' },
  { value: DEEPSEEK_UI_VALUE, label: 'DeepSeek', desc: '复杂差异推理' },
]

const FANGTAI_AVATAR_IDS = ANIME_AVATARS.slice(0, 8).map((a) => a.id)

const FANGTAI_PRESET = {
  starter_id: 'preset-fangtai',
  name: '方太收入对账分析助手',
  description:
    '面向方太财资 POC：解释 SAP 发货开票与 DMS 收入台账差异，查询对账任务并引导进入收入核对工作台。',
  persona:
    '你是方太收入核对分析助手。基于 SAP 发货开票、DMS 收入台账及方太排查规则，解释差异原因；可查询对账任务并引导用户进入正式 Workflow 处理。',
  allowed_skill_ids: [...FANGTAI_SKILL_IDS],
  knowledge_scope: FANGTAI_KNOWLEDGE_SCOPE,
  knowledge_base_ids: [FANGTAI_KB_ID, 'revenue_reconciliation'],
  data_source_scope: ['sap_billing', 'dms_ledger'],
  linked_workflow_id: FANGTAI_WORKFLOW_ID,
  output_format: 'natural',
  fallback_strategy: 'ask_user',
  model_route_simple: 'mock-ai',
  model_route_complex: 'mock-ai',
  visibility: 'team_published',
  scope: 'team_published',
  avatar_id: 'anime-04',
}

type WizardStep = { key: string; title: string; subtitle: string }

const CREATE_STEPS: WizardStep[] = [
  { key: 'origin', title: '选择起点', subtitle: '方太收入核对 POC 推荐配置' },
  { key: 'identity', title: '基础设定', subtitle: '头像 · 方太助手身份与人设' },
  { key: 'knowledge', title: '知识与模型', subtitle: '挂载知识库 · 演示/推理模型' },
  { key: 'capabilities', title: '能力挂载', subtitle: 'Skill · 双源数据 · 收入核对 Workflow' },
  { key: 'confirm', title: '确认创建', subtitle: '方太 POC 挂载摘要' },
]

const EDIT_STEPS: WizardStep[] = CREATE_STEPS.filter((s) => s.key !== 'origin')

type PickOption = {
  value: string
  label: string
  desc?: string
  extra?: ReactNode
  icon?: ReactNode
  iconTone?: WizardIconTone
}

function PickCardGrid({
  options,
  value,
  onChange,
  multiple,
  columns = 3,
  compact,
  onTraceAsset,
}: {
  options: PickOption[]
  value?: string | string[]
  onChange?: (v: string | string[]) => void
  multiple?: boolean
  columns?: number
  compact?: boolean
  onTraceAsset?: (assetKey: string) => void
}) {
  const selected = multiple
    ? (Array.isArray(value) ? value : [])
    : [value == null || value === '' ? '' : String(value)]
  const toggle = (v: string) => {
    if (multiple) {
      const arr = selected
      onChange?.(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])
    } else {
      onChange?.(v)
    }
  }
  return (
    <div className={`agent-wizard-pick-grid agent-wizard-pick-grid--cols-${columns}${compact ? ' agent-wizard-pick-grid--compact' : ''}`}>
      {options.map((o) => {
        const on = selected.includes(o.value)
        return (
          <button
            key={o.value}
            type="button"
            className={`agent-wizard-pick-card${compact ? ' agent-wizard-pick-card--compact' : ''}${on ? ' is-selected' : ''}`}
            onClick={() => toggle(o.value)}
          >
            {on && <CheckOutlined className="agent-wizard-pick-card__check" />}
            {(o.icon || o.iconTone) && (
              <WizardOptionIcon tone={o.iconTone || 'orange'}>
                {o.icon}
              </WizardOptionIcon>
            )}
            <div className="agent-wizard-pick-card__text">
              <span className="agent-wizard-pick-card__title">{o.label}</span>
              {o.desc && <span className="agent-wizard-pick-card__desc">{o.desc}</span>}
            </div>
            {onTraceAsset && (
              <button
                type="button"
                className="agent-wizard-pick-card__trace"
                title="查看配置"
                onClick={(e) => {
                  e.stopPropagation()
                  onTraceAsset(o.value)
                }}
              >
                <SettingOutlined />
              </button>
            )}
          </button>
        )
      })}
    </div>
  )
}

function AvatarPicker({ value, onChange }: { value?: string; onChange?: (v: string) => void }) {
  const list = ANIME_AVATARS.filter((a) => FANGTAI_AVATAR_IDS.includes(a.id))
  return (
    <div className="agent-wizard-avatar-grid agent-wizard-avatar-grid--compact">
      {list.map((av) => {
        const on = value === av.id
        return (
          <button
            key={av.id}
            type="button"
            className={`agent-wizard-avatar-card agent-wizard-avatar-card--compact${on ? ' is-selected' : ''}`}
            onClick={() => onChange?.(av.id)}
            title={av.label}
          >
            <img src={avatarImageUrl(av.id)} alt={av.label} className="agent-wizard-avatar-card__img" />
            <span className="agent-wizard-avatar-card__label">{av.label}</span>
          </button>
        )
      })}
    </div>
  )
}

function defaultFormValues() {
  return { ...FANGTAI_PRESET, starter_id: 'preset-fangtai' }
}

function agentToFormValues(row: AgentConfigItem) {
  const mr = row.model_route || row.asset_mounts?.model_route || {}
  const wf = row.linked_workflow_id || FANGTAI_WORKFLOW_ID
  const skills = (row.allowed_skill_ids || []).filter((id) =>
    (FANGTAI_SKILL_IDS as readonly string[]).includes(id),
  )
  const dataScope = (row.data_source_scope || []).filter((d) =>
    ['sap_billing', 'dms_ledger'].includes(d),
  )
  return {
    starter_id: 'preset-fangtai',
    avatar_id: resolveAvatarId(row),
    name: row.name,
    description: row.description,
    persona: row.persona,
    allowed_skill_ids: skills.length ? skills : [...FANGTAI_SKILL_IDS],
    knowledge_scope: row.knowledge_scope || FANGTAI_KNOWLEDGE_SCOPE,
    knowledge_base_ids: row.knowledge_base_ids?.length
      ? row.knowledge_base_ids
      : [FANGTAI_KB_ID, 'revenue_reconciliation'],
    data_source_scope: dataScope.length ? dataScope : ['sap_billing', 'dms_ledger'],
    linked_workflow_id: wf,
    output_format: row.output_format || 'natural',
    fallback_strategy: row.fallback_strategy || 'ask_user',
    visibility: row.visibility || row.scope || 'team_published',
    scope: row.scope || 'team_published',
    status: row.status,
    model_route_simple: mr.simple || 'mock-ai',
    model_route_complex: toFormModelRoute(mr.complex),
  }
}

function buildPayload(v: Record<string, unknown>, editing: boolean, platformModel?: string) {
  const complex = toPayloadModelRoute(String(v.model_route_complex || 'mock-ai'), platformModel)
  return {
    name: v.name as string,
    description: v.description as string,
    persona: v.persona as string,
    allowed_skill_ids: v.allowed_skill_ids as string[],
    knowledge_scope: FANGTAI_KNOWLEDGE_SCOPE,
    knowledge_base_ids: (v.knowledge_base_ids as string[] | undefined)?.length
      ? (v.knowledge_base_ids as string[])
      : [FANGTAI_KB_ID, 'revenue_reconciliation'],
    data_source_scope: v.data_source_scope as string[],
    linked_workflow_id: (v.linked_workflow_id as string) || FANGTAI_WORKFLOW_ID,
    output_format: 'natural',
    fallback_strategy: 'ask_user',
    visibility: 'team_published',
    allowed_roles: [] as string[],
    scope: 'team_published',
    model_route: { simple: 'mock-ai', complex },
    model_config_json: {
      avatar_id: (v.avatar_id as string) || 'anime-04',
    },
    ...(editing && v.status ? { status: v.status as string } : {}),
  }
}

type Props = {
  open: boolean
  editing: AgentConfigItem | null
  agents: AgentConfigItem[]
  skillOpts: Array<{ value: string; label: string }>
  workflowOpts: Array<{ value: string; label: string }>
  onClose: () => void
  onSuccess: () => void
}

export default function AdminAgentWizard({
  open, editing, workflowOpts, onClose, onSuccess,
}: Props) {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [saving, setSaving] = useState(false)
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null)
  const [assetConfigKey, setAssetConfigKey] = useState<string | null>(null)
  const [form] = Form.useForm()

  const openAssetConfig = useCallback((key: string) => {
    setAssetConfigKey(key)
  }, [])

  const openAssetFullscreen = useCallback((key: string) => {
    const target = resolveAgentAsset(key)
    navigate(buildAdminTabUrl(target))
    setAssetConfigKey(null)
    onClose()
  }, [navigate, onClose])

  const steps = editing ? EDIT_STEPS : CREATE_STEPS
  const current = steps[step]
  const progressPct = Math.round(((step + 1) / steps.length) * 100)

  const fangtaiWorkflow = useMemo(() => {
    const hit = workflowOpts.find(
      (w) => w.value === FANGTAI_WORKFLOW_ID || /收入核对|方太|revenue/i.test(w.label),
    )
    return hit || { value: FANGTAI_WORKFLOW_ID, label: '方太收入核对 Workflow' }
  }, [workflowOpts])

  const watchName = Form.useWatch('name', form)
  const watchDesc = Form.useWatch('description', form)
  const watchPersona = Form.useWatch('persona', form)
  const watchAvatarId = Form.useWatch('avatar_id', form)

  useEffect(() => {
    if (!open) return
    getAdminLlmConfig().then(setLlmConfig).catch(() => setLlmConfig(null))
  }, [open])

  useEffect(() => {
    if (!open) setAssetConfigKey(null)
  }, [open])

  useEffect(() => {
    if (!open) return
    setStep(0)
    form.resetFields()
    if (editing) {
      form.setFieldsValue(agentToFormValues(editing))
    } else {
      form.setFieldsValue({
        ...defaultFormValues(),
        linked_workflow_id: fangtaiWorkflow.value,
        model_route_complex: llmConfig?.runtime_ready ? DEEPSEEK_UI_VALUE : 'mock-ai',
      })
    }
  }, [open, editing, form, fangtaiWorkflow.value, llmConfig?.runtime_ready])

  const applyStarter = (starterId: string) => {
    form.setFieldValue('starter_id', starterId)
    if (starterId === 'blank') {
      form.setFieldsValue({
        ...defaultFormValues(),
        starter_id: 'blank',
        name: '',
        description: '',
        persona: '',
        avatar_id: 'anime-01',
      })
      return
    }
    form.setFieldsValue({
      ...defaultFormValues(),
      starter_id: 'preset-fangtai',
      linked_workflow_id: fangtaiWorkflow.value,
    })
  }

  const stepFieldNames = (idx: number): string[] => {
    const key = steps[idx]?.key
    if (key === 'origin') return []
    if (key === 'identity') return ['name', 'avatar_id']
    if (key === 'knowledge') return ['knowledge_base_ids', 'model_route_complex']
    if (key === 'capabilities') return ['allowed_skill_ids', 'data_source_scope']
    return []
  }

  const goNext = async () => {
    const names = stepFieldNames(step)
    if (names.length) await form.validateFields(names)
    if (step < steps.length - 1) setStep(step + 1)
  }

  const goPrev = () => {
    if (step > 0) setStep(step - 1)
  }

  const handleSubmit = async () => {
    try {
      await form.validateFields()
      const v = form.getFieldsValue(true)
      const body = buildPayload(v, !!editing, llmConfig?.model)
      setSaving(true)
      if (editing) {
        await updateAdminAgent(editing.id, body)
      } else {
        await createAdminAgentTemplate(body)
      }
      onSuccess()
      onClose()
    } catch (e) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(formatApiError(e))
    } finally {
      setSaving(false)
    }
  }

  const skillCards: PickOption[] = FANGTAI_SKILL_CARDS.map((s) => ({
    ...s,
    icon: WIZARD_SKILL_ICONS[s.value]?.icon,
    iconTone: WIZARD_SKILL_ICONS[s.value]?.tone,
  }))

  const modelCards: PickOption[] = FANGTAI_MODEL_CARDS.map((m) => ({
    ...m,
    desc: m.value === DEEPSEEK_UI_VALUE
      ? (llmConfig?.runtime_ready
        ? `联动 ${llmConfig.model} · 异常解释 Skill`
        : '需在大模型中心配置 API Key')
      : m.desc,
    icon: WIZARD_MODEL_ICONS[m.value]?.icon,
    iconTone: WIZARD_MODEL_ICONS[m.value]?.tone,
  }))

  const dataScopeCards: PickOption[] = FANGTAI_DATA_SCOPES.map((d) => ({
    ...d,
    icon: WIZARD_DS_ICONS[d.value]?.icon,
    iconTone: WIZARD_DS_ICONS[d.value]?.tone,
  }))

  const kbCards: PickOption[] = KNOWLEDGE_BASE_OPTIONS.map((k) => ({
    value: k.value,
    label: k.label,
    desc: k.desc,
    icon: KB_OPTION_ICONS[k.value],
    iconTone: k.iconTone,
  }))

  const statusCards: PickOption[] = [
    { value: 'draft', label: '草稿', icon: WIZARD_STATUS_ICONS.draft.icon, iconTone: WIZARD_STATUS_ICONS.draft.tone },
    { value: 'pending_review', label: '待审核', icon: WIZARD_STATUS_ICONS.pending_review.icon, iconTone: WIZARD_STATUS_ICONS.pending_review.tone },
    { value: 'published', label: '已发布', icon: WIZARD_STATUS_ICONS.published.icon, iconTone: WIZARD_STATUS_ICONS.published.tone },
    { value: 'offline', label: '已下架', icon: WIZARD_STATUS_ICONS.offline.icon, iconTone: WIZARD_STATUS_ICONS.offline.tone },
  ]

  const renderOrigin = () => {
    const starter = form.getFieldValue('starter_id')
    return (
      <div className="agent-wizard-origin-grid agent-wizard-origin-grid--compact">
        <button
          type="button"
          className={`agent-wizard-origin-card agent-wizard-origin-card--preset agent-wizard-origin-card--compact${
            starter === 'preset-fangtai' ? ' is-selected' : ''
          }`}
          onClick={() => applyStarter('preset-fangtai')}
        >
          <div className="agent-wizard-origin-card__top">
            <img src={avatarImageUrl('anime-04')} alt="" className="agent-wizard-origin-card__avatar" />
            <OriginPresetVisual />
          </div>
          <Text strong className="agent-wizard-origin-card__title">方太收入对账助手</Text>
          <Text type="secondary" className="agent-wizard-origin-card__meta">
            推荐 · 开箱即用 POC 预置配置
          </Text>
        </button>
        <button
          type="button"
          className={`agent-wizard-origin-card agent-wizard-origin-card--blank agent-wizard-origin-card--compact${
            starter === 'blank' ? ' is-selected' : ''
          }`}
          onClick={() => applyStarter('blank')}
        >
          <OriginBlankVisual />
          <Text strong className="agent-wizard-origin-card__title">空白自定义</Text>
          <Text type="secondary" className="agent-wizard-origin-card__meta">仍限定方太 POC 资产范围</Text>
        </button>
        <Form.Item name="starter_id" hidden><Input /></Form.Item>
      </div>
    )
  }

  const renderIdentity = () => (
    <Row gutter={16}>
      <Col span={14}>
        <Form.Item
          name="avatar_id"
          label={(
            <span className="agent-wizard-avatar-section">
              <WizardOptionIcon tone="cyan"><RobotOutlined /></WizardOptionIcon>
              助手头像
            </span>
          )}
          rules={[{ required: true, message: '请选择头像' }]}
        >
          <AvatarPicker />
        </Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="方太收入对账分析助手" />
        </Form.Item>
        <Form.Item name="description" label="能力说明">
          <TextArea rows={2} placeholder="面向方太财资：差异解释、任务查询、引导进入工作台" />
        </Form.Item>
        <Form.Item name="persona" label="人设 / System Prompt">
          <TextArea rows={3} placeholder="方太 SAP 发货开票与 DMS 收入台账差异分析…" />
        </Form.Item>
      </Col>
      <Col span={10}>
        <div className="agent-wizard-preview agent-wizard-preview--compact">
          <Text type="secondary" className="agent-wizard-preview__label">预览</Text>
          <div className="agent-wizard-preview__card">
            <img src={avatarImageUrl(watchAvatarId)} alt="" className="agent-wizard-preview__avatar-img" />
            <Text strong style={{ display: 'block', marginTop: 6 }}>{watchName || '方太助手'}</Text>
            <Tag color="orange" style={{ marginTop: 4 }}>方太 POC</Tag>
            <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
              {watchDesc || '—'}
            </Text>
            {watchPersona && (
              <Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 11 }}>
                {String(watchPersona).slice(0, 80)}
                {String(watchPersona).length > 80 ? '…' : ''}
              </Text>
            )}
          </div>
        </div>
      </Col>
    </Row>
  )

  const renderKnowledge = () => (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div>
        <div className="agent-wizard-section-head">
          <WizardOptionIcon tone="orange">{KB_PANEL_ICON}</WizardOptionIcon>
          <div>
            <Text strong>挂载知识库</Text>
            <Text type="secondary" className="agent-wizard-section-sub">
              对话时按问题检索条目并注入回复上下文（不复制条目）
            </Text>
          </div>
        </div>
        <Form.Item
          name="knowledge_base_ids"
          rules={[{ required: true, message: '请至少选择一个知识库' }]}
          style={{ marginTop: 8, marginBottom: 0 }}
        >
          <PickCardGrid compact multiple columns={3} options={kbCards} onTraceAsset={openAssetConfig} />
        </Form.Item>
      </div>
      <div>
        <div className="agent-wizard-section-head">
          <WizardOptionIcon tone="blue"><RobotOutlined /></WizardOptionIcon>
          <div>
            <Text strong>推理模型</Text>
            <ModelRouteHint
              runtimeReady={llmConfig?.runtime_ready}
              platformModel={llmConfig?.model}
              useMock={llmConfig?.use_mock}
            />
          </div>
        </div>
        <Form.Item name="model_route_complex" style={{ marginTop: 8, marginBottom: 0 }}>
          <PickCardGrid compact columns={2} options={modelCards} onTraceAsset={openAssetConfig} />
        </Form.Item>
        <Form.Item name="model_route_simple" hidden><Input /></Form.Item>
        <Form.Item name="knowledge_scope" hidden><Input /></Form.Item>
        <Form.Item name="fallback_strategy" hidden><Input /></Form.Item>
      </div>
    </Space>
  )

  const renderCapabilities = () => (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div>
        <div className="agent-wizard-section-head">
          <WizardOptionIcon tone="amber"><ThunderboltOutlined /></WizardOptionIcon>
          <div>
            <Text strong>Skill 授权</Text>
            <Text type="secondary" className="agent-wizard-section-sub">对话侧仅开放以下两项</Text>
          </div>
        </div>
        <Form.Item
          name="allowed_skill_ids"
          rules={[{ required: true, message: '请勾选 Skill' }]}
          style={{ marginTop: 8, marginBottom: 0 }}
        >
          <PickCardGrid compact multiple columns={2} options={skillCards} onTraceAsset={openAssetConfig} />
        </Form.Item>
      </div>
      <div>
        <div className="agent-wizard-section-head">
          <WizardOptionIcon tone="indigo"><DatabaseOutlined /></WizardOptionIcon>
          <div>
            <Text strong>数据范围</Text>
            <Text type="secondary" className="agent-wizard-section-sub">方太主表对</Text>
          </div>
        </div>
        <Form.Item
          name="data_source_scope"
          rules={[{ required: true, message: '请勾选数据范围' }]}
          style={{ marginTop: 8, marginBottom: 0 }}
        >
          <PickCardGrid compact multiple columns={2} options={dataScopeCards} onTraceAsset={openAssetConfig} />
        </Form.Item>
      </div>
      <FixedAssetPanel
        tone="purple"
        icon={WF_PANEL_ICON}
        title="关联 Workflow"
        tag={<Tag>{fangtaiWorkflow.label}</Tag>}
        desc="对话探索后引导进入「收入核对」工作台正式任务。"
        onTrace={() => openAssetConfig(fangtaiWorkflow.value)}
      />
      <Form.Item name="linked_workflow_id" hidden initialValue={fangtaiWorkflow.value}>
        <Input />
      </Form.Item>
      <Form.Item name="output_format" hidden><Input /></Form.Item>
    </Space>
  )

  const renderConfirm = () => {
    const v = form.getFieldsValue(true)
    const av = getAnimeAvatar(v.avatar_id)
    const modelLabel = FANGTAI_MODEL_CARDS.find((m) => m.value === v.model_route_complex)?.label || v.model_route_complex
    const kbLabels = (v.knowledge_base_ids as string[] | undefined)?.map((id) =>
      KNOWLEDGE_BASE_OPTIONS.find((k) => k.value === id)?.label || id,
    ).join('、') || '—'
    return (
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {editing && (
          <div>
            <div className="agent-wizard-section-head">
              <WizardOptionIcon tone="slate"><CheckCircleOutlined /></WizardOptionIcon>
              <Text strong>发布状态</Text>
            </div>
            <Form.Item name="status" style={{ marginTop: 8, marginBottom: 0 }}>
              <PickCardGrid compact columns={4} options={statusCards} />
            </Form.Item>
          </div>
        )}
        <Form.Item name="visibility" hidden><Input /></Form.Item>
        <div className="agent-wizard-summary agent-wizard-summary--with-avatar agent-wizard-summary--compact">
          <div className="agent-wizard-summary__head">
            <img src={avatarImageUrl(v.avatar_id)} alt="" className="agent-wizard-summary__avatar" />
            <div>
              <Text strong>{v.name}</Text>
              <div><Tag>{av.label}</Tag> <Tag color="orange">方太 POC</Tag></div>
            </div>
          </div>
          <div className="agent-wizard-summary-grid">
            <SummaryRow tone="rose" icon={TARGET_ICON} label="定位" value={v.description || '—'} />
            <SummaryRow tone="indigo" icon={TABLE_PAIR_ICON} label="表对" value="SAP 发货开票 ↔ DMS 收入台账" onTrace={() => openAssetConfig('table_pair')} />
            <SummaryRow tone="amber" icon={SKILL_SUMMARY_ICON} label="Skill" value="异常解释、任务查询" onTrace={() => openAssetConfig('agent-skills-summary')} />
            <SummaryRow
              tone="orange"
              icon={KB_SUMMARY_ICON}
              label="知识库"
              value={kbLabels}
              onTrace={() => openAssetConfig(
                ((v.knowledge_base_ids as string[] | undefined)?.[0]) || FANGTAI_KB_ID,
              )}
            />
            <SummaryRow tone="blue" icon={<RobotOutlined />} label="推理模型" value={modelLabel} onTrace={() => openAssetConfig(String(v.model_route_complex || 'mock-ai'))} />
            <SummaryRow tone="purple" icon={WF_SUMMARY_ICON} label="Workflow" value={fangtaiWorkflow.label} onTrace={() => openAssetConfig(fangtaiWorkflow.value)} />
          </div>
        </div>
      </Space>
    )
  }

  const renderStepBody = () => {
    switch (current?.key) {
      case 'origin': return renderOrigin()
      case 'identity': return renderIdentity()
      case 'knowledge': return renderKnowledge()
      case 'capabilities': return renderCapabilities()
      case 'confirm': return renderConfirm()
      default: return null
    }
  }

  const nextLabel = step < steps.length - 1
    ? `下一步：${steps[step + 1]?.title}`
    : (editing ? '保存' : '创建 Agent')

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={920}
      destroyOnClose
      className="agent-wizard-modal"
      title={null}
      closable
    >
      <div className="agent-wizard agent-wizard--compact">
        <div className="agent-wizard__head">
          <div className="agent-wizard__step-badge">{String(step + 1).padStart(2, '0')}</div>
          <div className="agent-wizard__head-text">
            <Title level={5} style={{ margin: 0 }}>{editing ? `编辑 · ${editing.name}` : current?.title}</Title>
            <Text type="secondary" style={{ fontSize: 12 }}>{current?.subtitle}</Text>
          </div>
          <div className="agent-wizard__progress-meta">
            <Text type="secondary" style={{ fontSize: 12 }}>{step + 1} / {steps.length}</Text>
            <Progress percent={progressPct} size="small" showInfo={false} strokeColor="#f97316" />
          </div>
        </div>

        <Form form={form} layout="vertical" className="agent-wizard__body" size="small">
          {renderStepBody()}
        </Form>

        <div className="agent-wizard__foot">
          <Text type="secondary" className="agent-wizard__foot-hint">
            {current?.key === 'origin' && '推荐直接使用方太 POC 预置，减少重复配置。'}
            {current?.key === 'capabilities' && '能力均引用中台资产；点击卡片右上角可查看配置。'}
            {current?.key === 'knowledge' && '点击卡片右上角可查看知识库与大模型配置。'}
          </Text>
          <Space>
            {step > 0 && <Button size="small" onClick={goPrev}>上一步</Button>}
            {step < steps.length - 1 ? (
              <Button type="primary" size="small" onClick={goNext}>
                {nextLabel} <RightOutlined />
              </Button>
            ) : (
              <Button type="primary" size="small" loading={saving} onClick={handleSubmit}>
                {nextLabel}
              </Button>
            )}
          </Space>
        </div>
      </div>

      <AgentAssetConfigModal
        open={!!assetConfigKey}
        assetKey={assetConfigKey}
        onClose={() => setAssetConfigKey(null)}
        onOpenInAssets={openAssetFullscreen}
        onTraceSkill={openAssetConfig}
      />
    </Modal>
  )
}
