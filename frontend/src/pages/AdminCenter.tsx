import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Table, Tag, Typography, Button, Descriptions, Alert, Modal, Input, message,
  Space, Spin, Empty, Switch, InputNumber, Form, Menu, Badge, Tooltip, Popover,
} from 'antd'
import {
  DatabaseOutlined, NodeIndexOutlined, BankOutlined, AppstoreOutlined,
  SafetyCertificateOutlined, ThunderboltOutlined, BookOutlined,
  FileSearchOutlined, ReloadOutlined, CloudUploadOutlined,
  RocketOutlined, StopOutlined,   RollbackOutlined, QuestionCircleOutlined,
  DashboardOutlined, PlusCircleOutlined, UnorderedListOutlined,
  SyncOutlined, FilePdfOutlined, CheckOutlined, AuditOutlined, EditOutlined,
  BranchesOutlined, RobotOutlined, ArrowLeftOutlined, CommentOutlined,
  ReadOutlined, ApiOutlined, PartitionOutlined,
} from '@ant-design/icons'
import type { MenuProps } from 'antd'
import {
  getAdminBusinessCenter, getAdminBusinessCenters, publishCenter, rollbackCenter,
  offlineCenter, updatePageModules, getAdminSkillInvocations,
  getAdminRules, getAdminCases, getAdminAuditLogs, createRuleVersion, listAdminAgents,
  getAdminOntologyMapping, OntologyMapping,
  getAdminLlmConfig, LlmConfig,
  listAdminAgentRuns,
  BusinessCenter, SkillInvocation, AdminRuleConfig, AgentConfigItem,
  type AgentRunSummary,
} from '../api/client'
import { formatApiError } from '../api/errors'
import { AdminExecutionRecords } from '../components/AdminExecutionRecords'
import {
  AdminSemanticsHub,
  SEMANTICS_LEGACY_TAB,
  type SemanticsSubTab,
} from '../components/AdminSemanticsHub'
import { AdminRuleDrawer } from '../components/AdminRuleDrawer'
import { AdminRuleImportPanel } from '../components/AdminRuleImportPanel'
import { AdminSkillsPage } from '../components/AdminSkillsPage'
import { AdminKnowledgePage, AdminCasesPage } from '../components/AdminKnowledgePage'
import { AdminLlmHub } from '../components/AdminLlmHub'
import AdminAgentsPage from '../components/AdminAgentsPage'
import { AdminBusinessCenterHub } from '../components/AdminBusinessCenterHub'
import { AdminWorkflowEditor } from '../components/AdminWorkflowEditor'
import { usePublishedCenter } from '../context/PublishedCenterContext'

const BC_ID = 'bc-revenue-reconciliation'

type ModuleDef = { key: string; label: string; icon: ReactNode }

const MODULE_GROUPS: Array<{ key: string; title: string; modules: ModuleDef[] }> = [
  {
    key: 'workbench',
    title: '工作台',
    modules: [
      { key: 'today_summary', label: '今日概览', icon: <DashboardOutlined /> },
      { key: 'create_task', label: '新建任务', icon: <PlusCircleOutlined /> },
      { key: 'task_batches', label: '任务批次', icon: <UnorderedListOutlined /> },
    ],
  },
  {
    key: 'task-flow',
    title: '任务处理',
    modules: [
      { key: 'difference_handling', label: '差异处理', icon: <FileSearchOutlined /> },
      { key: 'pending_review', label: '待复核', icon: <AuditOutlined /> },
      { key: 'processing_progress', label: '处理进度', icon: <SyncOutlined /> },
      { key: 're_verification', label: '再次验证', icon: <SafetyCertificateOutlined /> },
    ],
  },
  {
    key: 'output',
    title: '输出与追溯',
    modules: [
      { key: 'reconciliation_report', label: '报告输出', icon: <FilePdfOutlined /> },
      { key: 'audit_trace', label: '审计追溯', icon: <NodeIndexOutlined /> },
    ],
  },
  {
    key: 'audit-sub',
    title: '审计详情',
    modules: [
      { key: 'audit_trace_skills', label: '技能记录', icon: <ThunderboltOutlined /> },
      { key: 'audit_trace_workflow', label: '流程节点', icon: <NodeIndexOutlined /> },
      { key: 'audit_trace_logs', label: '操作日志', icon: <FileSearchOutlined /> },
    ],
  },
]

const ALL_MODULES: Array<{ key: string; label: string }> = MODULE_GROUPS.flatMap(
  (g) => g.modules.map((m) => ({ key: m.key, label: m.label })),
)

const MODULES_HELP = (
  <>
    点击模块卡片切换显隐，勾选后显示在前台工作台与侧栏。
    「保存草稿」仅暂存；「发布生效」后前台才更新。
    「审计详情」三项分别控制任务详情页内的技能记录 / 流程节点 / 操作日志（需先启用「审计追溯」）。
  </>
)

const RULE_TYPES: Array<{ key: string; label: string }> = [
  { key: 'amount_mismatch', label: '金额差异' },
  { key: 'duplicate_record', label: '重复数据' },
  { key: 'mapping_anomaly', label: '主数据/映射异常' },
]

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿', testing: '测试中', published: '已发布', offline: '已下架',
}

type MenuItem = Required<MenuProps>['items'][number]

/** 能力资产层 — 中台统一维护；Workflow / Agent 仅授权引用，不拥有资产 */
const ASSET_TAB_KEYS = ['skills', 'knowledge', 'rules', 'semantics', 'llm'] as const
/** 旧链接 ?tab=mapping|datasources|ontology_explore 仍可用 */
const LEGACY_ASSET_TABS = ['mapping', 'ontology_explore', 'datasources'] as const
/** 运行编排层 — 建立在能力资产之上 */
const RUNTIME_TAB_KEYS = ['workflow', 'agents'] as const

const menuItems: MenuItem[] = [
  {
    key: 'grp-assets',
    label: '能力资产',
    type: 'group',
    children: [
      { key: 'skills', icon: <ThunderboltOutlined />, label: 'Skill 库' },
      { key: 'knowledge', icon: <ReadOutlined />, label: '知识库' },
      { key: 'rules', icon: <SafetyCertificateOutlined />, label: '规则引擎' },
      { key: 'semantics', icon: <PartitionOutlined />, label: '数据语义' },
      { key: 'llm', icon: <RobotOutlined />, label: '大模型' },
    ],
  },
  {
    key: 'grp-runtime',
    label: '运行编排',
    type: 'group',
    children: [
      {
        key: 'workflow',
        icon: <BranchesOutlined />,
        label: '流程编排',
      },
      {
        key: 'agents',
        icon: <CommentOutlined />,
        label: 'Agent 管理',
      },
    ],
  },
  {
    key: 'grp-config',
    label: '系统配置',
    type: 'group',
    children: [
      { key: 'bc', icon: <BankOutlined />, label: '业务中心' },
      { key: 'modules', icon: <AppstoreOutlined />, label: '前台布局' },
    ],
  },
  {
    key: 'grp-ops',
    label: '运维监控',
    type: 'group',
    children: [
      { key: 'invocations', icon: <ThunderboltOutlined />, label: '运行记录' },
      { key: 'cases', icon: <BookOutlined />, label: '经验案例' },
      { key: 'audit', icon: <FileSearchOutlined />, label: '操作日志' },
    ],
  },
]

const PAGE_TITLES: Record<string, { title: string; desc: string }> = {
  skills: {
    title: 'Skill 库',
    desc: '平台级能力目录：流程型 / 能力型 / 知识型 Skill 统一注册与发布。Workflow 节点与 Agent 均通过授权引用，不在此重复定义能力。',
  },
  knowledge: { title: '知识库', desc: '' },
  rules: {
    title: '规则引擎',
    desc: '差异检测、质检与可复用规则版本。Workflow 绑定规则集执行；Agent 只读引用规则结论，不复制规则资产。',
  },
  semantics: { title: '数据语义', desc: '' },
  llm: {
    title: '大模型',
    desc: '平台模型路由、Key 与场景策略（简单 / 复杂）。Workflow 异常解释与 Agent 对话共用，按路由策略分流。',
  },
  workflow: {
    title: '流程编排',
    desc: '标准链路：数据接入 → 实体与规则 → 字段映射 → 差异识别 → …。引用能力资产，驱动前台工作台任务。',
  },
  agents: { title: 'Agent 管理', desc: '' },
  bc: {
    title: '业务中心',
    desc: '发布单元：嵌套展示数据语义 → 规则 → Workflow → Agent → 前台模块全链路，节点可内嵌配置',
  },
  modules: { title: '前台布局', desc: '' },
  invocations: { title: '运行记录', desc: 'Workflow 节点 Skill 调用与前台 Agent 对话 Trace 统一汇总' },
  cases: { title: '经验案例', desc: '差异处理沉淀；可反哺规则引擎与知识库条目' },
  audit: { title: '操作日志', desc: '追溯所有管理操作的完整记录' },
}

const KNOWLEDGE_PAGE_HELP = {
  title: '知识库为平台能力资产，与 Workflow / Agent 解耦',
  body: '条目在此统一维护；Workflow 通过知识型 Skill 引用，Agent 在配置阶段多选知识域与知识库 ID。下方为已沉淀的差异处理案例，可作为知识条目来源。',
}

function AdminHoverHelp({ label, title, body }: { label: string; title: string; body: string }) {
  return (
    <Popover
      title={title}
      content={<div className="admin-agent-help-pop" style={{ maxWidth: 360 }}>{body}</div>}
      trigger="hover"
      placement="bottomLeft"
      overlayClassName="admin-agent-help-overlay"
    >
      <button type="button" className="admin-agent-help-trigger">
        <span>{label}</span>
        <QuestionCircleOutlined />
      </button>
    </Popover>
  )
}

const ADMIN_TAB_KEYS = new Set([
  ...ASSET_TAB_KEYS,
  ...RUNTIME_TAB_KEYS,
  ...LEGACY_ASSET_TABS,
  'bc', 'modules', 'cases', 'audit', 'ontology', 'overview',
])

export default function AdminCenter() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const { refresh: refreshPublishedCenter } = usePublishedCenter()
  const [activeKey, setActiveKey] = useState('semantics')
  const [semSubTab, setSemSubTab] = useState<SemanticsSubTab>('datasources')
  const [menuOpenKeys, setMenuOpenKeys] = useState<string[]>([])
  const [center, setCenter] = useState<BusinessCenter | null>(null)
  const [rules, setRules] = useState<AdminRuleConfig[]>([])
  const [cases, setCases] = useState<Awaited<ReturnType<typeof getAdminCases>>>([])
  const [logs, setLogs] = useState<Awaited<ReturnType<typeof getAdminAuditLogs>>>([])
  const [invocations, setInvocations] = useState<SkillInvocation[]>([])
  const [agentRuns, setAgentRuns] = useState<AgentRunSummary[]>([])
  const [ontology, setOntology] = useState<OntologyMapping | null>(null)
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null)
  const [skillDrawerCode, setSkillDrawerCode] = useState<string | null>(null)
  const [knowledgeKbId, setKnowledgeKbId] = useState<string | null>(null)
  const [knowledgeCaseId, setKnowledgeCaseId] = useState<string | null>(null)
  const [casesHighlightId, setCasesHighlightId] = useState<string | null>(null)
  const [moduleSel, setModuleSel] = useState<string[]>([])
  const [agents, setAgents] = useState<AgentConfigItem[]>([])
  const [ruleV2Open, setRuleV2Open] = useState(false)
  const [editingRule, setEditingRule] = useState<AdminRuleConfig | null>(null)
  const [ruleForm] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const centers = await getAdminBusinessCenters()
      if (!centers.length) {
        setError('未找到业务中心种子数据，请确认后端已启动并完成初始化')
        return
      }
      const id = centers[0].id || BC_ID
      const [c, ru, ca, lg, inv, runs, ont, llm, ag] = await Promise.all([
        getAdminBusinessCenter(id),
        getAdminRules({ rule_version_id: centers[0].rule_version_id }),
        getAdminCases(),
        getAdminAuditLogs({ limit: 50 }),
        getAdminSkillInvocations({ limit: 80 }),
        listAdminAgentRuns(80).catch(() => []),
        getAdminOntologyMapping(),
        getAdminLlmConfig().catch(() => null),
        listAdminAgents().catch(() => []),
      ])
      setCenter(c)
      setRules(ru)
      setAgents(ag)
      setCases(ca)
      setLogs(lg)
      setInvocations(inv)
      setAgentRuns(runs)
      setOntology(ont)
      setLlmConfig(llm)
      setModuleSel(c.page_modules || [])
    } catch (e) {
      const msg = formatApiError(e, '加载失败')
      setError(`${msg}。请确认后端服务已启动。`)
      message.error(msg)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load().catch(console.error) }, [])

  useEffect(() => {
    const tab = searchParams.get('tab')
    const sem = searchParams.get('sem') as SemanticsSubTab | null
    if (tab && ADMIN_TAB_KEYS.has(tab)) {
      const legacy = SEMANTICS_LEGACY_TAB[tab]
      if (legacy) {
        setActiveKey('semantics')
        const subOk = sem && (['mapping', 'datasources', 'graph', 'entities'] as const).includes(sem as SemanticsSubTab)
        setSemSubTab(subOk ? (sem as SemanticsSubTab) : legacy)
      } else {
        setActiveKey(tab)
        if (tab === 'semantics' && sem && (['mapping', 'datasources', 'graph', 'entities'] as const).includes(sem as SemanticsSubTab)) {
          setSemSubTab(sem as SemanticsSubTab)
        }
      }
    }
    const kb = searchParams.get('kb')
    if (kb) setKnowledgeKbId(kb)
    const skill = searchParams.get('skill')
    if (skill) setSkillDrawerCode(skill)
    const caseId = searchParams.get('caseId')
    if (caseId) {
      setKnowledgeCaseId(caseId)
      if (tab === 'cases') setCasesHighlightId(caseId)
    }
  }, [searchParams])

  if (user.role !== 'admin' && user.role !== 'manager') {
    return <Alert type="warning" message="管理后台仅管理员/经理可访问" showIcon />
  }

  const handlePublish = async () => {
    if (!center) return
    try {
      await publishCenter(center.id)
      message.success('业务中心已发布')
      await load()
      await refreshPublishedCenter()
    } catch (e) { message.error(formatApiError(e)) }
  }

  const handleRollback = async () => {
    if (!center) return
    try {
      await rollbackCenter(center.id)
      message.success('已回滚至测试状态')
      load()
    } catch (e) { message.error(formatApiError(e)) }
  }

  const handleOffline = async () => {
    if (!center) return
    Modal.confirm({
      title: '确认下架',
      content: '下架后前台工作台将不再显示该业务中心。',
      okText: '确认下架',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await offlineCenter(center.id)
          message.success('业务中心已下架')
          load()
        } catch (e) { message.error(formatApiError(e)) }
      },
    })
  }

  const handleSaveModules = async () => {
    if (!center) return
    try {
      await updatePageModules(center.id, moduleSel)
      message.success('布局已保存为草稿，需发布后前台才会更新')
      load()
    } catch (e) { message.error(formatApiError(e)) }
  }

  const handlePublishModules = async () => {
    if (!center) return
    try {
      await updatePageModules(center.id, moduleSel)
      await publishCenter(center.id)
      message.success('前台布局已发布生效')
      await load()
      await refreshPublishedCenter()
    } catch (e) { message.error(formatApiError(e)) }
  }

  const toggleModule = (key: string) => {
    setModuleSel((prev) => {
      const on = prev.includes(key)
      if (on) {
        let next = prev.filter((k) => k !== key)
        if (key === 'audit_trace') {
          next = next.filter((k) => !k.startsWith('audit_trace_'))
        }
        return next
      }
      if (key === 'audit_trace') {
        return [...prev, key, 'audit_trace_skills', 'audit_trace_workflow', 'audit_trace_logs']
      }
      return [...prev, key]
    })
  }

  const auditTraceOn = moduleSel.includes('audit_trace')
  const selectedCount = moduleSel.length
  const totalCount = ALL_MODULES.length

  const submitRuleV2 = async () => {
    const vals = await ruleForm.validateFields()
    const overrides = RULE_TYPES.map((rt) => ({
      rule_type: rt.key,
      enabled: vals[`${rt.key}_enabled`],
      threshold: rt.key === 'amount_mismatch' ? Number(vals.amount_threshold || 0) : undefined,
    }))
    try {
      const res = await createRuleVersion({
        description: vals.description || '管理员手动创建规则版本',
        reusable_rule_suggestion: vals.suggestion || '规则版本调整',
        rule_overrides: overrides,
      })
      message.success(`已创建规则 v${res.version}，发布后新任务将采用`)
      setRuleV2Open(false)
      ruleForm.resetFields()
      load()
    } catch (e) { message.error(formatApiError(e)) }
  }

  const handleRuleFromCase = (caseItem: typeof cases[0]) => {
    Modal.confirm({
      title: '基于案例优化检测规则',
      content: (
        <Input.TextArea
          id="rule-suggestion"
          defaultValue={caseItem.reusable_rule_suggestion || '加强金额差异阈值校验'}
          rows={3}
        />
      ),
      okText: '创建新版本',
      onOk: async () => {
        const el = document.getElementById('rule-suggestion') as HTMLTextAreaElement
        await createRuleVersion({
          description: `基于案例 ${caseItem.id.slice(0, 8)} 优化`,
          reusable_rule_suggestion: el?.value || '',
          source_case_id: caseItem.id,
        })
        message.success('已创建规则新版本')
        load()
      },
    })
  }

  const statusColor: Record<string, string> = {
    draft: 'default', testing: 'processing', published: 'success', offline: 'error',
  }

  const wf = center?.workflow
  const pageInfo = PAGE_TITLES[activeKey] || { title: '', desc: '' }

  const goWorkflowNavigate = (tab: string, skillCode?: string, semSub?: string) => {
    if (skillCode) setSkillDrawerCode(skillCode)
    if (tab === 'semantics' && semSub && (['datasources', 'entities', 'mapping', 'graph'] as const).includes(semSub as SemanticsSubTab)) {
      setActiveKey('semantics')
      setSemSubTab(semSub as SemanticsSubTab)
      return
    }
    const legacy = SEMANTICS_LEGACY_TAB[tab]
    if (legacy) {
      setActiveKey('semantics')
      setSemSubTab(legacy)
      return
    }
    setActiveKey(tab)
  }

  const renderContent = () => {
    if (loading) return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large">
          <div style={{ padding: 24, color: '#94a3b8' }}>加载中...</div>
        </Spin>
      </div>
    )
    if (error) return <Alert type="error" message={error} showIcon action={<Button onClick={load}>重试</Button>} style={{ margin: 24 }} />
    if (!center) return <Empty description="暂无数据" style={{ padding: 80 }} />

    switch (activeKey) {
      case 'semantics':
        return ontology ? (
          <AdminSemanticsHub
            ontology={ontology}
            activeSubTab={semSubTab}
            onSubTabChange={(key) => {
              setSemSubTab(key)
              setSearchParams((prev) => {
                const next = new URLSearchParams(prev)
                next.set('tab', 'semantics')
                next.set('sem', key)
                return next
              })
            }}
            onSaved={() => load().catch(console.error)}
            onNavigateToRuleEngine={() => setActiveKey('rules')}
          />
        ) : null

      case 'bc':
        return (
          <AdminBusinessCenterHub
            center={center}
            ontology={ontology}
            rules={rules}
            agents={agents}
            onReload={() => load().catch(console.error)}
            onNavigate={goWorkflowNavigate}
            onCreateRuleVersion={() => setRuleV2Open(true)}
            onPublish={handlePublish}
            onRollback={handleRollback}
            onOffline={handleOffline}
          />
        )

      case 'workflow':
        return (
          <AdminWorkflowEditor
            workflowId={center.workflow_id || wf?.id}
            workflow={wf}
            skills={center.skills}
            center={center}
            ontology={ontology}
            rules={rules}
            llmConfig={llmConfig}
            onSaved={() => load().catch(console.error)}
            onNavigate={goWorkflowNavigate}
            onCreateRuleVersion={() => setRuleV2Open(true)}
          />
        )

      case 'skills':
        return (
          <AdminSkillsPage
            enabledSkills={(center.skills || []) as Parameters<typeof AdminSkillsPage>[0]['enabledSkills']}
            workflowNodes={wf?.nodes || []}
            llmConfig={llmConfig}
            initialSkillCode={skillDrawerCode}
            onInitialSkillHandled={() => setSkillDrawerCode(null)}
            onNavigate={(tab) => {
              if (tab === 'llm') setActiveKey('llm')
              else goWorkflowNavigate(tab)
            }}
          />
        )

      case 'llm':
        return <AdminLlmHub onSaved={() => load().catch(console.error)} />

      case 'agents':
        return <AdminAgentsPage />

      case 'modules':
        return (
          <div className="page-modules-editor">
            <div className="page-modules-toolbar">
              <Space size={8}>
                <Tooltip title={MODULES_HELP} placement="bottomLeft">
                  <QuestionCircleOutlined className="page-modules-help" />
                </Tooltip>
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  已选 {selectedCount}/{totalCount}
                </Typography.Text>
              </Space>
              <Space size={8}>
                <Button size="small" onClick={handleSaveModules}>保存草稿</Button>
                <Button size="small" type="primary" onClick={handlePublishModules}>发布生效</Button>
              </Space>
            </div>

            {MODULE_GROUPS.map((group) => {
              const isAuditSub = group.key === 'audit-sub'
              if (isAuditSub && !auditTraceOn) return null
              return (
                <section key={group.key} className={`page-modules-group${isAuditSub ? ' page-modules-group-sub' : ''}`}>
                  <Typography.Text type="secondary" className="page-modules-group-title">
                    {group.title}
                  </Typography.Text>
                  <div className="page-modules-grid">
                    {group.modules.map((m) => {
                      const active = moduleSel.includes(m.key)
                      const disabled = isAuditSub && !auditTraceOn
                      return (
                        <button
                          key={m.key}
                          type="button"
                          disabled={disabled}
                          className={`page-module-tile${active ? ' active' : ''}${disabled ? ' disabled' : ''}`}
                          onClick={() => toggleModule(m.key)}
                        >
                          {active && <CheckOutlined className="page-module-check" />}
                          <span className="page-module-icon">{m.icon}</span>
                          <span className="page-module-label">{m.label}</span>
                        </button>
                      )
                    })}
                  </div>
                </section>
              )
            })}
          </div>
        )

      case 'knowledge':
        return (
          <AdminKnowledgePage
            cases={cases}
            initialKbId={knowledgeKbId}
            initialCaseId={knowledgeCaseId}
            onInitialHandled={() => {
              setKnowledgeKbId(null)
              setKnowledgeCaseId(null)
            }}
            onNavigateCases={(caseId) => {
              setActiveKey('cases')
              if (caseId) setCasesHighlightId(caseId)
            }}
            onGenerateRule={handleRuleFromCase}
            onCasesRefresh={async () => {
              const ca = await getAdminCases()
              setCases(ca)
            }}
          />
        )

      case 'rules':
        return (
          <>
            <AdminRuleImportPanel
              ruleVersionId={center.rule_version_id}
              businessCenterId={center.id}
              versionLabel={center.rule_version_id?.slice(0, 8)}
              onCreateVersion={() => setRuleV2Open(true)}
              onApplied={() => load().catch(console.error)}
            />
            <Table
              className="admin-rules-table"
              dataSource={rules}
              rowKey="id"
              pagination={false}
              size="middle"
              tableLayout="fixed"
              style={{ marginTop: 16 }}
              columns={[
              { title: '规则名称', dataIndex: 'name', width: 240, ellipsis: true,
                render: (v: string, row: AdminRuleConfig) => (
                  <Tooltip title={v}>
                    <Button type="link" className="admin-rule-name-link" onClick={() => setEditingRule(row)}>
                      <span className="admin-rule-name-text">{v}</span>
                    </Button>
                  </Tooltip>
                ),
              },
              { title: '类型', dataIndex: 'rule_type', width: 120,
                render: (v: string) => {
                  const labels: Record<string, string> = {
                    amount_mismatch: '金额差异', duplicate_record: '重复数据', mapping_anomaly: '映射异常',
                  }
                  return labels[v] || v
                },
              },
              { title: '检测逻辑', dataIndex: 'condition', ellipsis: true,
                render: (v?: string) => (
                  <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                    {v || '—'}
                  </Typography.Text>
                ),
              },
              { title: '容差阈值', dataIndex: 'threshold', width: 100,
                render: (v?: number) => v ? `¥${v}` : '—',
              },
              { title: '严重程度', dataIndex: 'severity', width: 90,
                render: (v: string) => {
                  const c: Record<string, string> = { high: 'red', medium: 'orange', low: 'blue' }
                  const l: Record<string, string> = { high: '高', medium: '中', low: '低' }
                  return <Tag color={c[v] || 'default'}>{l[v] || v}</Tag>
                },
              },
              { title: '状态', dataIndex: 'enabled', width: 80,
                render: (v: boolean) => v
                  ? <Badge status="success" text="启用" />
                  : <Badge status="default" text="停用" />,
              },
              { title: '', key: 'action', width: 72, align: 'right' as const,
                render: (_: unknown, row: AdminRuleConfig) => (
                  <Button type="text" size="small" icon={<EditOutlined />} onClick={() => setEditingRule(row)}>
                    编辑
                  </Button>
                ),
              },
            ]} />
          </>
        )

      case 'invocations':
        return (
          <AdminExecutionRecords
            invocations={invocations}
            agentRuns={agentRuns}
            agents={agents}
          />
        )

      case 'cases':
        return (
          <AdminCasesPage
            cases={cases}
            initialCaseId={casesHighlightId}
            onInitialHandled={() => setCasesHighlightId(null)}
            onGenerateRule={handleRuleFromCase}
          />
        )

      case 'audit':
        return (
          <Table dataSource={logs} rowKey="id" size="middle" columns={[
            { title: '时间', dataIndex: 'created_at', width: 180,
              render: (d: string) => new Date(d).toLocaleString('zh-CN'),
            },
            { title: '操作', dataIndex: 'action', width: 160,
              render: (v: string) => {
                const labels: Record<string, string> = {
                  upload: '上传数据', delete: '删除', publish: '发布', offline: '下架',
                  rollback: '回滚', update_page_modules: '更新布局',
                  save_field_mappings: '保存映射', create_rule_version: '创建规则版本',
                  update_rule_config: '更新检测规则',
                }
                return labels[v] || v
              },
            },
            { title: '对象', render: (_: unknown, r: typeof logs[0]) => {
              const labels: Record<string, string> = {
                business_center: '业务中心', datasource: '数据源', mapping_config: '字段映射',
                rule_version: '规则版本', rule_config: '检测规则',
              }
              return `${labels[r.object_type] || r.object_type} / ${r.object_id.slice(0, 8)}`
            }},
            { title: '操作人', dataIndex: 'operator', width: 100 },
          ]} />
        )

      default:
        return <Empty />
    }
  }

  return (
    <div className="admin-layout">
      <div className="admin-sidebar">
        <div className="admin-sidebar-header">
          <SafetyCertificateOutlined style={{ fontSize: 20, color: 'var(--brand)' }} />
          <div>
            <div className="admin-sidebar-title">管理后台</div>
            <div className="admin-sidebar-sub">能力资产 · 运行编排</div>
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[activeKey]}
          openKeys={menuOpenKeys}
          onOpenChange={setMenuOpenKeys}
          onClick={({ key }) => {
            if (String(key).startsWith('grp-')) return
            const k = String(key)
            setActiveKey(k)
            if (k === 'knowledge') navigate('/admin?tab=knowledge', { replace: true })
          }}
          items={menuItems}
          className="admin-sidebar-menu"
          style={{ border: 'none', background: 'transparent' }}
        />
        <div className="admin-sidebar-footer">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/workbench/reconciliation')}
            block
            style={{ textAlign: 'left', color: '#64748b', marginBottom: 4 }}
          >
            返回工作台
          </Button>
          <Button
            type="text"
            icon={<ReloadOutlined />}
            onClick={load}
            block
            style={{ textAlign: 'left', color: '#64748b' }}
          >
            刷新数据
          </Button>
        </div>
      </div>

      <div className="admin-main">
        {activeKey !== 'workflow' && activeKey !== 'llm' && activeKey !== 'agents' && (
          <div className="admin-page-header admin-page-header--compact">
            <Space align="center" size="small" wrap>
              <Typography.Title level={4} style={{ margin: 0 }}>{pageInfo.title}</Typography.Title>
              {pageInfo.desc ? (
                <AdminHoverHelp
                  label="说明"
                  title={pageInfo.title}
                  body={pageInfo.desc}
                />
              ) : null}
              {activeKey === 'knowledge' && (
                <AdminHoverHelp
                  label="说明"
                  title={KNOWLEDGE_PAGE_HELP.title}
                  body={KNOWLEDGE_PAGE_HELP.body}
                />
              )}
            </Space>
          </div>
        )}
        <div className={`admin-page-body${
          activeKey === 'workflow' ? ' admin-page-body--workflow' : ''
        }${activeKey === 'llm' ? ' admin-page-body--llm' : ''}${
          activeKey === 'agents' ? ' admin-page-body--agents' : ''
        }`}>
          {renderContent()}
        </div>
      </div>

      <Modal
        title="创建检测规则新版本"
        open={ruleV2Open}
        onOk={submitRuleV2}
        onCancel={() => setRuleV2Open(false)}
        okText="创建版本"
        width={520}
      >
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message="新版本创建后需发布才会对新任务生效，历史任务不受影响。" />
        <Form form={ruleForm} layout="vertical" initialValues={{
          amount_mismatch_enabled: true, duplicate_record_enabled: true, mapping_anomaly_enabled: true,
          amount_threshold: 0,
        }}>
          <Form.Item name="description" label="版本说明">
            <Input placeholder="如：上调金额差异容差阈值" />
          </Form.Item>
          {RULE_TYPES.map((rt) => (
            <Form.Item key={rt.key} name={`${rt.key}_enabled`} label={rt.label} valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          ))}
          <Form.Item name="amount_threshold" label="金额容差阈值（差异金额 ≤ 阈值时不计为差异）">
            <InputNumber min={0} style={{ width: '100%' }} prefix="¥" />
          </Form.Item>
          <Form.Item name="suggestion" label="优化建议备注">
            <Input.TextArea rows={2} placeholder="可选，记录本次规则调整的原因" />
          </Form.Item>
        </Form>
      </Modal>

      <AdminRuleDrawer
        rule={editingRule}
        open={!!editingRule}
        onClose={() => setEditingRule(null)}
        onSaved={() => {
          message.success('规则已保存')
          load()
        }}
      />
    </div>
  )
}
