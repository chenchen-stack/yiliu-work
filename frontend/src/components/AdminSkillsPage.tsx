import { useEffect, useMemo, useState } from 'react'
import {
  Button, Empty, Input, Modal, Space, Spin, Tooltip, Typography, Upload, message,
} from 'antd'
import {
  ThunderboltOutlined, SearchOutlined, SettingOutlined,
  RobotOutlined, BranchesOutlined,
  UploadOutlined, InboxOutlined,
} from '@ant-design/icons'
import { CenterDetailModal } from './CenterDetailModal'
import { SkillPackagePanel } from './SkillPackagePanel'
import {
  getAdminSkills, listSkillPackages, skillPackageLifecycle, uploadSkillPackage,
  LlmConfig,
  type SkillPackageDetail,
  type SkillPackageItem,
} from '../api/client'
import { formatApiError } from '../api/errors'
import type { AdminSkillRow } from '../types/adminSkill'
import { CatalogToolbar } from './CatalogToolbar'

export type { AdminSkillRow } from '../types/adminSkill'

type WorkflowNode = { id: string; label?: string; skill?: string; skill_code?: string }

const SKILL_TYPE_LABEL: Record<string, string> = {
  ability: '能力型',
  knowledge: '知识型',
  process: '流程型',
  flow: '流程型',
}

const TYPE_HINTS: Record<string, string> = {
  all: '全部 Skill：流程型、能力型、知识型统一浏览',
  process: '流程型：封装端到端业务流程，如月结流程、合同审批流程',
  ability: '能力型：封装领域知识与判断规则，如税务合规校验、行业最佳实践',
  knowledge: '知识型：封装外部系统对接能力，如调用 ERP 取数、调用 CRM 写入',
}

const SKILL_STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  pending_review: '待审核',
  published: '已发布',
  offline: '已下架',
  testing: '测试中',
}

const TYPE_FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'process', label: '流程型' },
  { key: 'ability', label: '能力型' },
  { key: 'knowledge', label: '知识型' },
] as const

function normalizeSkillType(type?: string): string {
  if (type === 'flow' || type === 'process') return 'process'
  if (type === 'knowledge') return 'knowledge'
  return 'ability'
}

const SKILL_META: Record<string, {
  desc: string
  configTab?: 'mapping' | 'rules' | 'llm'
  configLabel?: string
}> = {
  data_import: {
    desc: '读取任务绑定的业务侧 / 财务侧数据源，解析 Excel 并写入执行上下文。',
  },
  field_mapping: {
    desc: '按字段映射配置翻译列名、生成匹配键，供差异识别使用。',
    configTab: 'mapping',
    configLabel: '数据语义',
  },
  ontology_context: {
    desc: '加载已发布实体与领域规则到任务上下文，不产出差异。',
    configTab: 'mapping',
    configLabel: '实体与规则',
  },
  difference_detect: {
    desc: '执行检测规则，产出差异事实清单（不由大模型判定）。',
    configTab: 'rules',
    configLabel: '检测规则',
  },
  anomaly_explain: {
    desc: '对每条差异调用大模型（DeepSeek）生成归因、证据与处理建议。',
    configTab: 'llm',
    configLabel: '大模型',
  },
  review_flow: {
    desc: '财务人工确认 / 退回 / 指派处理，Workflow 人工节点。',
  },
  re_verify: {
    desc: '修正数据后重跑规则，验证差异是否清零。',
  },
  report_gen: {
    desc: '生成 PDF 核对报告并支持任务关闭。',
  },
}

type Props = {
  enabledSkills: AdminSkillRow[]
  workflowNodes?: WorkflowNode[]
  llmConfig?: LlmConfig | null
  initialSkillCode?: string | null
  onNavigate?: (tab: string) => void
  onInitialSkillHandled?: () => void
  /** 前台：支持上传 Skill 包 zip */
  allowUpload?: boolean
  /** 前台技能中心：页内 Tab + 胶囊分类 + 显眼上传 */
  compact?: boolean
  uploadOpen?: boolean
  onUploadOpenChange?: (open: boolean) => void
}

function pkgToSkillRow(p: SkillPackageItem): AdminSkillRow {
  return {
    id: p.id,
    code: p.code,
    name: p.name,
    type: p.type,
    version: p.version,
    status: p.status,
  }
}

function skillIcon(type?: string) {
  if (type === 'knowledge') return <RobotOutlined />
  if (type === 'process') return <BranchesOutlined />
  return <ThunderboltOutlined />
}

export function AdminSkillsPage({
  enabledSkills,
  workflowNodes = [],
  llmConfig,
  initialSkillCode,
  onNavigate,
  onInitialSkillHandled,
  allowUpload = false,
  compact = false,
  uploadOpen: uploadOpenProp,
  onUploadOpenChange,
}: Props) {
  const [allSkills, setAllSkills] = useState<AdminSkillRow[]>([])
  const [loading, setLoading] = useState(true)
  const [uploadOpenLocal, setUploadOpenLocal] = useState(false)
  const [uploading, setUploading] = useState(false)
  const uploadOpen = uploadOpenProp ?? uploadOpenLocal
  const setUploadOpen = onUploadOpenChange ?? setUploadOpenLocal
  const [tab, setTab] = useState<'mine' | 'all'>('mine')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [keyword, setKeyword] = useState('')
  const [detailSkill, setDetailSkill] = useState<AdminSkillRow | null>(null)
  const [detailPkg, setDetailPkg] = useState<SkillPackageDetail | null>(null)

  const reloadSkills = () => {
    setLoading(true)
    Promise.all([
      getAdminSkills().catch(() => [] as Array<Record<string, unknown>>),
      allowUpload ? listSkillPackages().catch(() => [] as SkillPackageItem[]) : Promise.resolve([]),
    ])
      .then(([dbRows, pkgs]) => {
        const rows = Array.isArray(dbRows) ? (dbRows as AdminSkillRow[]) : []
        const packages = Array.isArray(pkgs) ? pkgs : []
        const byCode = new Map<string, AdminSkillRow>()
        for (const r of rows) {
          if (r?.code) byCode.set(r.code, r)
        }
        for (const p of packages) {
          if (p?.code) byCode.set(p.code, pkgToSkillRow(p))
        }
        setAllSkills([...byCode.values()])
      })
      .catch((e) => message.error(formatApiError(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    reloadSkills()
  }, [allowUpload])

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const res = await uploadSkillPackage(file)
      message.success(res.message || `已安装 ${res.name}`)
      setUploadOpen(false)
      reloadSkills()
      window.dispatchEvent(new CustomEvent('agents-refresh'))
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setUploading(false)
    }
    return false
  }

  useEffect(() => {
    if (!initialSkillCode) return
    const pool = [...enabledSkills, ...allSkills]
    const hit = pool.find((s) => s.code === initialSkillCode)
    if (hit) {
      const meta = SKILL_META[hit.code || '']
      if (meta?.configTab === 'llm' && onNavigate) onNavigate('llm')
      else if (hit.code) setDetailSkill(hit)
    }
    onInitialSkillHandled?.()
  }, [initialSkillCode, enabledSkills, allSkills, onInitialSkillHandled, onNavigate])

  const enabledCodes = useMemo(
    () => new Set(enabledSkills.map((s) => s.code).filter(Boolean)),
    [enabledSkills],
  )

  const list = compact || tab === 'all' ? allSkills : enabledSkills

  const matchKeyword = (s: AdminSkillRow, kw: string) => {
    if (!kw) return true
    const hay = `${s.name || ''} ${s.code || ''} ${SKILL_META[s.code || '']?.desc || ''}`.toLowerCase()
    return hay.includes(kw)
  }

  const kw = keyword.trim().toLowerCase()

  const listForPills = useMemo(
    () => list.filter((s) => matchKeyword(s, kw)),
    [list, kw],
  )

  const filtered = useMemo(() => {
    return listForPills.filter((s) => {
      if (typeFilter !== 'all' && normalizeSkillType(s.type) !== typeFilter) return false
      return true
    })
  }, [listForPills, typeFilter])

  const skillTabs = useMemo(
    () => [
      { key: 'mine', label: '我的技能', count: enabledSkills.length },
      { key: 'all', label: '全部技能', count: allSkills.length || enabledSkills.length },
    ],
    [enabledSkills.length, allSkills.length],
  )

  const skillPills = useMemo(
    () => TYPE_FILTERS.map((f) => {
      const n = f.key === 'all'
        ? listForPills.length
        : listForPills.filter((s) => normalizeSkillType(s.type) === f.key).length
      return { key: f.key, label: f.label, count: n }
    }),
    [listForPills],
  )

  const uploadAction = allowUpload ? (
    <Button
      type="primary"
      className="catalog-upload-btn"
      icon={<UploadOutlined />}
      onClick={() => setUploadOpen(true)}
    >
      上传 Skill
    </Button>
  ) : null

  const runSkillLifecycle = async (
    code: string,
    action: 'submit_review' | 'publish' | 'offline' | 'rollback',
  ) => {
    try {
      const res = await skillPackageLifecycle(code, action)
      message.success(res.message || '操作成功')
      reloadSkills()
      window.dispatchEvent(new CustomEvent('agents-refresh'))
    } catch (e) {
      message.error(formatApiError(e))
    }
  }

  const nodeOf = (code?: string) =>
    workflowNodes.find((n) => (n.skill_code || n.skill) === code)

  const openConfig = (skill: AdminSkillRow) => {
    const meta = SKILL_META[skill.code || '']
    if (meta?.configTab && onNavigate) {
      onNavigate(meta.configTab)
      return
    }
    setDetailSkill(skill)
  }

  const renderSkillCard = (skill: AdminSkillRow) => {
    const meta = SKILL_META[skill.code || ''] || { desc: 'Workflow 内置 Skill' }
    const code = skill.code || ''
    const hasConfig = !!meta.configTab
    const isEnabled = enabledCodes.has(code)
    const skillStatus = (skill.status || 'published').toLowerCase()
    const node = nodeOf(code)

    return (
      <div
        key={skill.id || code}
        className="admin-skill-card admin-skill-card--clickable"
        role="button"
        tabIndex={0}
        onClick={() => setDetailSkill(skill)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setDetailSkill(skill)
          }
        }}
      >
        <div className="admin-skill-card__head">
          <div className="admin-skill-card__icon">{skillIcon(skill.type)}</div>
          <div className="admin-skill-card__main">
            <div className="admin-skill-card__title-line">
              <span className="admin-skill-card__title">{skill.name || code}</span>
              <span className={`admin-skill-card__status admin-skill-card__status--${skillStatus}`}>
                {SKILL_STATUS_LABEL[skillStatus] || skillStatus}
              </span>
            </div>
            <p className="admin-skill-card__desc">{meta.desc}</p>
            <div className="admin-skill-card__foot">
              <span className="admin-skill-card__chip admin-skill-card__chip--code">{code}</span>
              <span className="admin-skill-card__chip">
                {SKILL_TYPE_LABEL[normalizeSkillType(skill.type)] || skill.type}
              </span>
              {skill.version != null && (
                <span className="admin-skill-card__chip">v{skill.version}</span>
              )}
              {node?.label && (
                <span className="admin-skill-card__chip admin-skill-card__chip--node">
                  <BranchesOutlined /> {node.label}
                </span>
              )}
              {tab === 'all' && isEnabled && (
                <span className="admin-skill-card__chip admin-skill-card__chip--ok">已启用</span>
              )}
            </div>
          </div>
          <div className="admin-skill-card__aside">
            {hasConfig && onNavigate && (
              <Tooltip title={`${meta.configLabel || '配置'}`}>
                <button
                  type="button"
                  className="admin-skill-card__gear"
                  aria-label="业务配置"
                  onClick={(e) => {
                    e.stopPropagation()
                    openConfig(skill)
                  }}
                >
                  <SettingOutlined />
                </button>
              </Tooltip>
            )}
          </div>
        </div>

      </div>
    )
  }

  return (
    <div className={`admin-skills-page${compact ? ' admin-skills-page--compact' : ''}`}>
      {!compact && (
        <div className="admin-skills-head">
          <Typography.Title level={5} style={{ margin: 0 }}>技能</Typography.Title>
          <Input
            allowClear
            prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
            placeholder="搜索技能名称或说明"
            className="admin-skills-search"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </div>
      )}

      <CatalogToolbar
        tabs={skillTabs}
        activeTab={tab}
        onTabChange={(k) => setTab(k as 'mine' | 'all')}
        pills={skillPills}
        activePill={typeFilter}
        onPillChange={setTypeFilter}
        hint={TYPE_HINTS[typeFilter] || TYPE_HINTS.all}
        action={uploadAction}
      />

      <Modal
        title="上传 Skill 包"
        open={uploadOpen}
        onCancel={() => !uploading && setUploadOpen(false)}
        footer={null}
        width={480}
        destroyOnClose
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
          上传 .zip，内含 skill.yaml（及可选 skill.md、execute.py、config.yaml）。目录名或 code 字段作为 Skill 标识。
        </Typography.Paragraph>
        <Upload.Dragger
          accept=".zip"
          maxCount={1}
          showUploadList={false}
          disabled={uploading}
          beforeUpload={(file) => {
            void handleUpload(file as File)
            return false
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽 zip 到此处</p>
          <p className="ant-upload-hint">最大 20MB</p>
        </Upload.Dragger>
        {uploading && <div style={{ textAlign: 'center', marginTop: 12 }}><Spin /></div>}
      </Modal>

      {loading && !filtered.length ? (
        <Typography.Text type="secondary">加载中…</Typography.Text>
      ) : filtered.length === 0 ? (
        <Empty
          className="catalog-empty"
          description={typeFilter === 'all' ? '当前分类下暂无技能' : `暂无${TYPE_FILTERS.find((f) => f.key === typeFilter)?.label || ''} Skill`}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        >
          {allowUpload && (
            <Button type="primary" className="catalog-upload-btn" icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
              上传 Skill 包
            </Button>
          )}
        </Empty>
      ) : (
        <div className="admin-skills-grid">
          {filtered.map((skill) => renderSkillCard(skill))}
        </div>
      )}

      <CenterDetailModal
        open={!!detailSkill}
        onClose={() => {
          setDetailSkill(null)
          setDetailPkg(null)
        }}
        title={detailSkill?.name || detailSkill?.code || 'Skill'}
        subtitle={detailSkill ? SKILL_META[detailSkill.code || '']?.desc : undefined}
        extra={
          detailSkill && SKILL_META[detailSkill.code || '']?.configTab && onNavigate ? (
            <Button type="primary" size="small" className="catalog-upload-btn" onClick={() => openConfig(detailSkill)}>
              {SKILL_META[detailSkill.code || '']?.configLabel || '业务配置'}
            </Button>
          ) : null
        }
        width={960}
      >
        {detailSkill?.code && (
          <>
            <SkillPackagePanel
              modalMode
              skillCode={detailSkill.code}
              skillRow={detailSkill}
              nodeLabel={nodeOf(detailSkill.code)?.label}
              pkgDetail={detailPkg}
              setPkgDetail={setDetailPkg}
              onConfig={
                SKILL_META[detailSkill.code || '']?.configTab && onNavigate
                  ? () => { openConfig(detailSkill); setDetailSkill(null); setDetailPkg(null) }
                  : undefined
              }
            />
            {allowUpload && (
              <div className="admin-skill-card__lifecycle admin-skill-card__lifecycle--modal">
                {(detailSkill.status || 'published').toLowerCase() === 'draft' && (
                  <Button type="link" size="small" onClick={() => { void runSkillLifecycle(detailSkill.code!, 'submit_review') }}>
                    提交审核
                  </Button>
                )}
                {(detailSkill.status || '').toLowerCase() === 'pending_review' && (
                  <>
                    <Button type="link" size="small" onClick={() => { void runSkillLifecycle(detailSkill.code!, 'publish') }}>
                      发布
                    </Button>
                    <Button type="link" size="small" onClick={() => { void runSkillLifecycle(detailSkill.code!, 'rollback') }}>
                      撤回
                    </Button>
                  </>
                )}
                {(detailSkill.status || 'published').toLowerCase() === 'published' && (
                  <Button type="link" size="small" onClick={() => { void runSkillLifecycle(detailSkill.code!, 'offline') }}>
                    下架
                  </Button>
                )}
                {(detailSkill.status || '').toLowerCase() === 'offline' && (
                  <Button type="link" size="small" onClick={() => { void runSkillLifecycle(detailSkill.code!, 'publish') }}>
                    重新发布
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </CenterDetailModal>
    </div>
  )
}
