import { useCallback, useEffect, useState } from 'react'
import {
  Button, Form, Input, InputNumber, Select, Space, Switch, Tag, Typography, message, Spin,
} from 'antd'
import {
  ArrowLeftOutlined, EditOutlined, ReloadOutlined,
} from '@ant-design/icons'
import {
  getAdminLlmConfig, updateAdminLlmConfig, testAdminLlmConfig, LlmConfig,
} from '../api/client'
import { formatApiError } from '../api/errors'
import { LlmProviderLogo } from './LlmProviderLogo'

const PROVIDER_LABEL: Record<string, string> = {
  deepseek: 'DeepSeek',
}

const SKILL_LABEL: Record<string, string> = {
  anomaly_explain: '差异归因 Skill',
}

type Props = {
  onSaved?: () => void
}

type View = 'overview' | 'edit'

type TestMeta = {
  ok: boolean
  latencyMs: number
  message: string
}

export function AdminLlmHub({ onSaved }: Props) {
  const [view, setView] = useState<View>('overview')
  const [config, setConfig] = useState<LlmConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [testing, setTesting] = useState(false)
  const [testMeta, setTestMeta] = useState<TestMeta | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const c = await getAdminLlmConfig()
      setConfig(c)
    } catch (e) {
      const err = e as { response?: { status?: number } }
      const msg = err.response?.status === 404
        ? '大模型配置接口未就绪，请重启后端服务（uvicorn app.main:app --reload --port 8000）'
        : formatApiError(e)
      setLoadError(msg)
      message.error(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load().catch(console.error) }, [load])

  const runTest = async () => {
    setTesting(true)
    const t0 = performance.now()
    try {
      const res = await testAdminLlmConfig()
      const meta: TestMeta = {
        ok: res.ok,
        latencyMs: Math.round(performance.now() - t0),
        message: res.message,
      }
      setTestMeta(meta)
      if (res.ok) message.success(res.message)
      else message.error(res.message)
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setTesting(false)
    }
  }

  const statusOf = (c: LlmConfig) => {
    if (c.runtime_ready) return { label: '运行中', color: 'success' as const }
    if (c.use_mock) return { label: '模拟模式', color: 'default' as const }
    return { label: '未测试', color: 'warning' as const }
  }

  if (loading && !config) {
    return (
      <div className="admin-llm-hub-loading admin-llm-hub-loading--fill">
        <Spin />
      </div>
    )
  }

  if (view === 'edit' && config) {
    return (
      <AdminLlmConfigForm
        config={config}
        onBack={() => setView('overview')}
        onSaved={async () => {
          await load()
          onSaved?.()
          setView('overview')
        }}
      />
    )
  }

  if (!config) {
    return (
      <div className="admin-llm-hub admin-llm-hub--fill">
        <div className="admin-llm-hub__bar">
          <Typography.Title level={5} style={{ margin: 0 }}>大模型</Typography.Title>
        </div>
        <div className="admin-llm-hub__canvas">
          <Typography.Paragraph type="secondary">
            {loadError || '暂时无法加载大模型配置'}
          </Typography.Paragraph>
          <Button icon={<ReloadOutlined />} onClick={() => load().catch(console.error)}>重试</Button>
        </div>
      </div>
    )
  }

  const st = statusOf(config)
  const provider = PROVIDER_LABEL[config.provider] || config.provider
  const linked = (config.linked_skill_codes || []).map((c) => SKILL_LABEL[c] || c).join('、') || '—'
  const ac = config.agent_chat || { enabled: true, use_langgraph: false, diff_explain_via_agent: true }
  const agentModeLabel = ac.enabled
    ? (ac.diff_explain_via_agent ? '开放问答 + 差异解释' : '仅开放问答')
    : '关闭（走经典 runtime）'
  const keyUpdated = config.updated_at
    ? new Date(config.updated_at).toLocaleDateString('zh-CN')
    : '—'

  return (
    <div className="admin-llm-hub admin-llm-hub--fill">
      <div className="admin-llm-hub__bar">
        <div>
          <Typography.Title level={5} style={{ margin: 0 }}>大模型</Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            平台已接入模型与 Skill 绑定关系
          </Typography.Text>
        </div>
        <Button type="primary" className="admin-llm-hub-edit-btn" onClick={() => setView('edit')}>
          编辑配置
        </Button>
      </div>

      <div className="admin-llm-hub__canvas">
      <div className="admin-llm-model-card admin-llm-model-card--wide">
        <div className="admin-llm-model-card__top">
          <div className="admin-llm-model-card__brand">
            <LlmProviderLogo provider={config.provider} className="admin-llm-model-card__logo" />
            <div>
              <div className="admin-llm-model-card__name-row">
                <Typography.Text strong className="admin-llm-model-card__name">
                  {provider} · {config.model}
                </Typography.Text>
                <Tag>{provider}</Tag>
                <Tag color={st.color}>{st.label}</Tag>
              </div>
              <Typography.Text code className="admin-llm-model-card__id">{config.model}</Typography.Text>
              <Typography.Text type="secondary" className="admin-llm-model-card__url">
                {config.base_url}
              </Typography.Text>
            </div>
          </div>
          <Space size={4} className="admin-llm-model-card__ops">
            <Button
              type="text"
              icon={<ReloadOutlined spin={testing} />}
              aria-label="测试连接"
              onClick={runTest}
              disabled={testing}
            />
            <Button
              type="text"
              icon={<EditOutlined />}
              aria-label="编辑配置"
              onClick={() => setView('edit')}
            />
          </Space>
        </div>

        <div className="admin-llm-model-card__meta">
          <div className="admin-llm-model-card__meta-item">
            <span>认证</span>
            <strong>{config.api_key_set ? '已配置' : '未配置'}</strong>
          </div>
          <div className="admin-llm-model-card__meta-item">
            <span>密钥更新</span>
            <strong>{keyUpdated}</strong>
          </div>
          <div className="admin-llm-model-card__meta-item">
            <span>调用范围</span>
            <strong>异常解释</strong>
          </div>
          <div className="admin-llm-model-card__meta-item">
            <span>延迟</span>
            <strong>{testMeta?.latencyMs != null ? `${testMeta.latencyMs}ms` : '—'}</strong>
          </div>
          <div className="admin-llm-model-card__meta-item">
            <span>绑定 Skill</span>
            <strong>{linked}</strong>
          </div>
          <div className="admin-llm-model-card__meta-item">
            <span>对话 Agent</span>
            <strong>{agentModeLabel}</strong>
          </div>
          <div className="admin-llm-model-card__meta-item">
            <span>LangGraph</span>
            <strong>{ac.use_langgraph ? '原生 Tool' : 'JSON 规划器'}</strong>
          </div>
        </div>

        {testMeta && (
          <Typography.Text
            type={testMeta.ok ? 'success' : 'danger'}
            className="admin-llm-model-card__test-msg"
          >
            {testMeta.message}
          </Typography.Text>
        )}
      </div>
      </div>
    </div>
  )
}

function AdminLlmConfigForm({
  config,
  onBack,
  onSaved,
}: {
  config: LlmConfig
  onBack: () => void
  onSaved: () => void | Promise<void>
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [apiKeyTouched, setApiKeyTouched] = useState(false)
  const [showPrompt, setShowPrompt] = useState(false)

  useEffect(() => {
    const ac = config.agent_chat || { enabled: true, use_langgraph: false, diff_explain_via_agent: true }
    form.setFieldsValue({
      base_url: config.base_url,
      model: config.model,
      use_mock: config.use_mock,
      temperature: config.temperature,
      max_tokens: config.max_tokens,
      system_prompt: config.system_prompt,
      api_key: '',
      agent_chat_enabled: ac.enabled,
      agent_chat_langgraph: ac.use_langgraph,
      agent_chat_diff: ac.diff_explain_via_agent,
    })
    setApiKeyTouched(false)
  }, [config, form])

  const handleSave = async () => {
    const vals = await form.validateFields()
    setSaving(true)
    try {
      const body: Record<string, unknown> = {
        provider: config.provider,
        base_url: vals.base_url,
        model: vals.model,
        use_mock: vals.use_mock,
        temperature: vals.temperature,
        max_tokens: vals.max_tokens,
        system_prompt: vals.system_prompt,
        agent_chat: {
          enabled: vals.agent_chat_enabled,
          use_langgraph: vals.agent_chat_langgraph,
          diff_explain_via_agent: vals.agent_chat_diff,
        },
      }
      if (apiKeyTouched) body.api_key = vals.api_key || ''
      await updateAdminLlmConfig(body)
      message.success('已保存')
      await onSaved()
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      if (apiKeyTouched) await handleSave()
      const res = await testAdminLlmConfig()
      if (res.ok) message.success(res.message)
      else message.error(res.message)
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="admin-llm-edit admin-llm-edit--fill">
      <div className="admin-llm-edit__bar">
        <button type="button" className="admin-llm-edit-back" onClick={onBack}>
          <ArrowLeftOutlined /> 返回概览
        </button>
        <div className="admin-llm-edit-actions admin-llm-edit-actions--bar">
          <Button type="primary" loading={saving} onClick={handleSave}>保存</Button>
          <Button loading={testing} onClick={handleTest}>测试连接</Button>
        </div>
      </div>

      <div className="admin-llm-edit__canvas">
      <div className="admin-llm-edit-head">
        <LlmProviderLogo provider={config.provider} size={40} className="admin-llm-edit-logo" />
        <div>
          <Typography.Title level={5} className="admin-llm-edit-title">编辑模型配置</Typography.Title>
          <Typography.Text type="secondary" className="admin-llm-edit-sub">
            {PROVIDER_LABEL[config.provider] || config.provider} · 供 anomaly_explain 调用
          </Typography.Text>
        </div>
      </div>

      <Form form={form} layout="vertical" className="admin-llm-edit-form" requiredMark={false}>
        <div className="admin-llm-edit-grid">
          <div className="admin-llm-edit-card">
            <Form.Item name="base_url" label="API 地址" rules={[{ required: true }]}>
              <Input placeholder="https://api.deepseek.com" />
            </Form.Item>
            <Form.Item name="model" label="模型" rules={[{ required: true }]}>
              <Select
                showSearch
                options={(config.model_presets || []).map((m) => ({ value: m, label: m }))}
                placeholder="选择模型"
              />
            </Form.Item>
            <Form.Item label="API Key">
              <Form.Item name="api_key" noStyle>
                <Input.Password
                  placeholder={config.api_key_set ? '留空不修改' : 'sk-...'}
                  onChange={() => setApiKeyTouched(true)}
                  autoComplete="new-password"
                />
              </Form.Item>
              {config.api_key_preview && (
                <Typography.Text type="secondary" className="admin-llm-edit-hint">
                  当前 {config.api_key_preview}
                </Typography.Text>
              )}
            </Form.Item>
          </div>

          <div className="admin-llm-edit-card admin-llm-edit-card--params">
            <Form.Item name="use_mock" label="模拟模式" valuePropName="checked" className="admin-llm-edit-inline">
              <Switch size="small" />
            </Form.Item>
            <Typography.Text type="secondary" className="admin-llm-edit-section-label">
              对话 Agent 模式
            </Typography.Text>
            <Form.Item
              name="agent_chat_enabled"
              label="启用 Skill Agent（SSE / ReAct）"
              valuePropName="checked"
              className="admin-llm-edit-inline"
            >
              <Switch size="small" />
            </Form.Item>
            <Form.Item
              name="agent_chat_diff"
              label="差异解释走 Agent + anomaly_explain"
              valuePropName="checked"
              className="admin-llm-edit-inline"
            >
              <Switch size="small" />
            </Form.Item>
            <Form.Item
              name="agent_chat_langgraph"
              label="LangGraph 原生 Tool Calling"
              valuePropName="checked"
              className="admin-llm-edit-inline"
            >
              <Switch size="small" />
            </Form.Item>
            <Form.Item name="temperature" label="Temperature" rules={[{ required: true }]}>
              <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="max_tokens" label="Max Tokens" rules={[{ required: true }]}>
              <InputNumber min={128} max={4096} step={64} style={{ width: '100%' }} />
            </Form.Item>
            <button
              type="button"
              className="admin-llm-edit-advanced"
              onClick={() => setShowPrompt((v) => !v)}
            >
              {showPrompt ? '收起' : '展开'} 系统 Prompt
            </button>
          </div>
        </div>

        {showPrompt && (
          <div className="admin-llm-edit-card admin-llm-edit-card--prompt">
            <Form.Item name="system_prompt" style={{ marginBottom: 0 }}>
              <Input.TextArea rows={8} placeholder="异常解释 JSON 输出要求" />
            </Form.Item>
          </div>
        )}

        <div className="admin-llm-edit-actions admin-llm-edit-actions--foot">
          <Button type="text" onClick={onBack}>取消</Button>
        </div>
      </Form>
      </div>
    </div>
  )
}

/** @deprecated 使用 AdminLlmHub */
export function AdminLlmConfig(props: Props) {
  return <AdminLlmHub {...props} />
}
