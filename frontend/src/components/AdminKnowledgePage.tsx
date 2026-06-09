import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Button, Empty, Input, Tag, Typography, Descriptions, Upload, message,
} from 'antd'
import {
  ArrowLeftOutlined, BookOutlined, FileTextOutlined, ReadOutlined,
  SafetyCertificateOutlined, SearchOutlined, SettingOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import type { CaseAsset } from '../api/client'
import { uploadKnowledgeExcel } from '../api/client'
import { CenterDetailModal } from './CenterDetailModal'

export type KnowledgeBaseDef = {
  id: string
  name: string
  desc: string
  icon: ReactNode
}

export const KNOWLEDGE_BASES: KnowledgeBaseDef[] = [
  {
    id: 'kb-fangtai-cases',
    name: '方太历史案例库',
    desc: '差异处理沉淀条目，供异常解释 Skill 与对话 Agent 引用',
    icon: <BookOutlined />,
  },
  {
    id: 'kb-compliance',
    name: '合规与校验要点',
    desc: '合规校验口径与复核要点（条目持续沉淀中）',
    icon: <SafetyCertificateOutlined />,
  },
  {
    id: 'revenue_reconciliation',
    name: '收入核对知识',
    desc: '收入核对领域标准说明与业务口径',
    icon: <ReadOutlined />,
  },
]

export const CASE_TYPE_FILTERS = [
  { key: 'all', label: '全部' },
  { key: '金额差异', label: '金额差异' },
  { key: '重复数据', label: '重复数据' },
  { key: '主数据/映射异常', label: '映射异常' },
  { key: '接口/同步异常', label: '同步异常' },
] as const

function truncate(text: string | undefined, max: number): string {
  const t = (text || '').trim()
  if (!t) return '—'
  return t.length > max ? `${t.slice(0, max)}…` : t
}

export function filterCases(
  cases: CaseAsset[],
  opts: { typeFilter: string; keyword: string; kbId?: string },
): CaseAsset[] {
  const kw = opts.keyword.trim().toLowerCase()
  return cases
    .filter((c) => !opts.kbId || caseBelongsToKb(c, opts.kbId))
    .filter((c) => {
      if (opts.typeFilter === 'all') return true
      if (opts.typeFilter === '映射异常') return c.confirmed_type?.includes('映射')
      if (opts.typeFilter === '同步异常') {
        return c.confirmed_type?.includes('同步') || c.confirmed_type?.includes('接口')
      }
      return c.confirmed_type === opts.typeFilter
    })
    .filter((c) => {
      if (!kw) return true
      const hay = [
        c.confirmed_type,
        c.root_cause,
        c.handling_result,
        c.reusable_rule_suggestion,
      ].join(' ').toLowerCase()
      return hay.includes(kw)
    })
}

/** 知识库条目 · 居中弹层详情 */
export function AdminCaseDetailModal({
  caseItem,
  open,
  onClose,
  onGenerateRule,
  onNavigateCases,
  showCasesLink = false,
}: {
  caseItem: CaseAsset | null
  open: boolean
  onClose: () => void
  onGenerateRule?: (caseItem: CaseAsset) => void
  onNavigateCases?: (caseId?: string) => void
  showCasesLink?: boolean
}) {
  return (
    <CenterDetailModal
      open={open}
      onClose={onClose}
      title={caseItem?.confirmed_type || '知识库条目'}
      subtitle={caseItem?.root_cause}
      extra={
        caseItem && onGenerateRule ? (
          <Button
            type="primary"
            size="small"
            className="catalog-upload-btn"
            onClick={() => onGenerateRule(caseItem)}
          >
            生成规则
          </Button>
        ) : null
      }
      width={640}
    >
      {caseItem && (
        <div className="admin-kb-detail">
          <div className="admin-kb-detail__tags">
            <span className="admin-kb-detail__type">{caseItem.confirmed_type}</span>
            <Tag bordered={false} className="admin-kb-detail__status">
              {caseItem.status || '已沉淀'}
            </Tag>
            <span className="admin-kb-detail__id">{caseItem.id.slice(0, 8)}</span>
          </div>
          <Descriptions column={1} size="small" bordered className="admin-kb-detail__desc">
            <Descriptions.Item label="根因分析">{caseItem.root_cause || '—'}</Descriptions.Item>
            <Descriptions.Item label="处理结果">{caseItem.handling_result || '—'}</Descriptions.Item>
            <Descriptions.Item label="可复用建议">{caseItem.reusable_rule_suggestion || '—'}</Descriptions.Item>
            <Descriptions.Item label="来源">
              {caseItem.source_kind === 'kb_upload'
                ? `资料上传 · ${caseItem.source_file || '—'}`
                : `任务沉淀 · ${caseItem.source_task_id?.slice(0, 8) || '—'}`}
            </Descriptions.Item>
            <Descriptions.Item label="沉淀时间">
              {caseItem.created_at ? new Date(caseItem.created_at).toLocaleString('zh-CN') : '—'}
            </Descriptions.Item>
          </Descriptions>
          {showCasesLink && (
            <button
              type="button"
              className="admin-kb-link"
              onClick={() => {
                onNavigateCases?.(caseItem.id)
                onClose()
              }}
            >
              在经验案例中查看 →
            </button>
          )}
        </div>
      )}
    </CenterDetailModal>
  )
}

/** @deprecated 侧栏抽屉，请用 AdminCaseDetailModal */
export function AdminCaseDetailDrawer(props: Parameters<typeof AdminCaseDetailModal>[0]) {
  return <AdminCaseDetailModal {...props} />
}

/** 案例条目 · 知识库专用卡片 */
export function AdminCaseEntryGrid({
  items,
  onOpen,
  showGenerateRule = false,
  onGenerateRule,
}: {
  items: CaseAsset[]
  onOpen: (item: CaseAsset) => void
  showGenerateRule?: boolean
  onGenerateRule?: (item: CaseAsset) => void
}) {
  if (!items.length) return null
  return (
    <div className="admin-kb-entry-grid">
      {items.map((c) => (
        <article
          key={c.id}
          className="admin-kb-card"
          role="button"
          tabIndex={0}
          onClick={() => onOpen(c)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onOpen(c)
            }
          }}
        >
          <div className="admin-kb-card__icon">
            <FileTextOutlined />
          </div>
          <div className="admin-kb-card__body">
            <h4 className="admin-kb-card__title">{c.confirmed_type || '未分类'}</h4>
            <p className="admin-kb-card__text">{truncate(c.root_cause, 64)}</p>
            <div className="admin-kb-card__meta">
              <span className="admin-kb-card__chip">{c.id.slice(0, 8)}</span>
              <span className="admin-kb-card__chip">处理 · {truncate(c.handling_result, 12)}</span>
            </div>
          </div>
          {showGenerateRule && (
            <button
              type="button"
              className="admin-kb-card__gear"
              aria-label="生成规则"
              onClick={(e) => {
                e.stopPropagation()
                onGenerateRule?.(c)
              }}
            >
              <SettingOutlined />
            </button>
          )}
        </article>
      ))}
    </div>
  )
}

export function AdminCaseEntriesPanel({
  title,
  subtitle,
  cases,
  typeFilter,
  onTypeFilterChange,
  keyword,
  onKeywordChange,
  emptyDescription,
  onOpen,
  showGenerateRule,
  onGenerateRule,
  hideTitle,
}: {
  title: string
  subtitle?: string
  cases: CaseAsset[]
  typeFilter: string
  onTypeFilterChange: (key: string) => void
  keyword: string
  onKeywordChange: (value: string) => void
  emptyDescription: string
  onOpen: (item: CaseAsset) => void
  showGenerateRule?: boolean
  onGenerateRule?: (item: CaseAsset) => void
  hideTitle?: boolean
}) {
  return (
    <div className="admin-kb-panel">
      {!hideTitle && (title || subtitle) ? (
        <div className="admin-kb-panel__head">
          {title ? <Typography.Text strong>{title}</Typography.Text> : null}
          {subtitle ? <Typography.Text type="secondary">{subtitle}</Typography.Text> : null}
        </div>
      ) : subtitle ? (
        <div className="admin-kb-panel__head admin-kb-panel__head--sub-only">
          <Typography.Text type="secondary">{subtitle}</Typography.Text>
        </div>
      ) : null}

      <div className="catalog-pills admin-kb-filters">
        {CASE_TYPE_FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            className={`catalog-pill${typeFilter === f.key ? ' catalog-pill--active' : ''}`}
            onClick={() => onTypeFilterChange(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {cases.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyDescription} className="catalog-empty" />
      ) : (
        <AdminCaseEntryGrid
          items={cases}
          onOpen={onOpen}
          showGenerateRule={showGenerateRule}
          onGenerateRule={onGenerateRule}
        />
      )}
    </div>
  )
}

export function caseBelongsToKb(caseItem: CaseAsset, kbId: string): boolean {
  if (kbId === 'kb-fangtai-cases') {
    if (caseItem.knowledge_base_id && caseItem.knowledge_base_id !== 'kb-fangtai-cases') return false
    return caseItem.source_kind !== 'kb_upload' || caseItem.knowledge_base_id === 'kb-fangtai-cases'
  }
  return caseItem.knowledge_base_id === kbId
}

function resolveKbId(id: string | null | undefined): string | null {
  if (!id) return null
  return KNOWLEDGE_BASES.some((k) => k.id === id) ? id : null
}

type Props = {
  cases: CaseAsset[]
  initialKbId?: string | null
  initialCaseId?: string | null
  onNavigateCases?: (caseId?: string) => void
  onGenerateRule?: (caseItem: CaseAsset) => void
  onInitialHandled?: () => void
  onCasesRefresh?: () => void | Promise<void>
}

export function AdminKnowledgePage({
  cases,
  initialKbId,
  initialCaseId,
  onNavigateCases,
  onGenerateRule,
  onInitialHandled,
  onCasesRefresh,
}: Props) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const kbFromUrl = resolveKbId(searchParams.get('kb'))
  const [viewKbId, setViewKbId] = useState<string | null>(
    () => resolveKbId(initialKbId) || kbFromUrl,
  )
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [keyword, setKeyword] = useState('')
  const [detail, setDetail] = useState<CaseAsset | null>(null)
  const [uploading, setUploading] = useState(false)

  const handleUpload = async (file: File) => {
    if (!viewKbId) return
    setUploading(true)
    try {
      const res = await uploadKnowledgeExcel(file, viewKbId)
      message.success(`已解析入库 ${res.entries_created} 条（${res.source_file}）`)
      await onCasesRefresh?.()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      message.error(err.response?.data?.detail || err.message || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const syncKbUrl = useCallback((kbId: string | null) => {
    const params = new URLSearchParams(searchParams)
    params.set('tab', 'knowledge')
    if (kbId) params.set('kb', kbId)
    else params.delete('kb')
    params.delete('caseId')
    navigate(`/admin?${params.toString()}`, { replace: true })
  }, [navigate, searchParams])

  const openKb = useCallback((kbId: string) => {
    setViewKbId(kbId)
    setTypeFilter('all')
    setKeyword('')
    syncKbUrl(kbId)
  }, [syncKbUrl])

  const backToList = useCallback(() => {
    setViewKbId(null)
    setTypeFilter('all')
    setKeyword('')
    syncKbUrl(null)
  }, [syncKbUrl])

  useEffect(() => {
    const next = resolveKbId(initialKbId) || kbFromUrl
    if (next) setViewKbId(next)
    else if (!initialKbId && !kbFromUrl) setViewKbId(null)
  }, [initialKbId, kbFromUrl])

  useEffect(() => {
    if (!initialCaseId || !cases.length) return
    const hit = cases.find((c) => c.id === initialCaseId)
    if (hit) {
      setViewKbId('kb-fangtai-cases')
      setDetail(hit)
    }
    onInitialHandled?.()
  }, [initialCaseId, cases, onInitialHandled])

  const kbCounts = useMemo(() => {
    const map: Record<string, number> = {}
    for (const kb of KNOWLEDGE_BASES) {
      map[kb.id] = cases.filter((c) => caseBelongsToKb(c, kb.id)).length
    }
    return map
  }, [cases])

  const selectedKb = KNOWLEDGE_BASES.find((k) => k.id === viewKbId)

  const filteredCases = useMemo(
    () => (viewKbId ? filterCases(cases, { typeFilter, keyword, kbId: viewKbId }) : []),
    [cases, viewKbId, typeFilter, keyword],
  )

  if (!viewKbId || !selectedKb) {
    return (
      <div className="admin-kb-page">
        <div className="admin-skills-head admin-kb-head">
          <Typography.Title level={5} style={{ margin: 0 }}>知识库</Typography.Title>
          <Typography.Text type="secondary">选择知识库查看条目</Typography.Text>
        </div>

        <div className="admin-kb-kb-grid">
          {KNOWLEDGE_BASES.map((kb) => {
            const count = kbCounts[kb.id] ?? 0
            return (
              <button
                key={kb.id}
                type="button"
                className="admin-kb-kb-card"
                onClick={() => openKb(kb.id)}
              >
                <div className="admin-kb-kb-card__icon">{kb.icon}</div>
                <div className="admin-kb-kb-card__body">
                  <span className="admin-kb-kb-card__title">{kb.name}</span>
                  <span className="admin-kb-kb-card__desc">{kb.desc}</span>
                  <span className="admin-kb-kb-card__count">{count} 条</span>
                </div>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div className="admin-kb-page admin-kb-page--detail">
      <div className="admin-kb-detail-head">
        <Button
          type="link"
          className="admin-kb-back"
          icon={<ArrowLeftOutlined />}
          onClick={backToList}
        >
          知识库
        </Button>
        <div className="admin-kb-detail-head__main">
          <Typography.Title level={5} style={{ margin: 0 }}>{selectedKb.name}</Typography.Title>
          <Typography.Text type="secondary">{selectedKb.desc}</Typography.Text>
        </div>
        <div className="admin-kb-detail-head__tools">
          <Input
            allowClear
            prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
            placeholder="搜索根因、处理结果或建议"
            className="admin-skills-search admin-kb-search"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <Upload
            accept=".xlsx,.xls"
            showUploadList={false}
            disabled={uploading}
            beforeUpload={(file) => {
              void handleUpload(file as File)
              return false
            }}
          >
            <Button type="primary" className="catalog-upload-btn" icon={<UploadOutlined />} loading={uploading}>
              上传 Excel
            </Button>
          </Upload>
        </div>
      </div>

      <AdminCaseEntriesPanel
        title=""
        subtitle={`共 ${filteredCases.length} 条可检索条目`}
        cases={filteredCases}
        typeFilter={typeFilter}
        onTypeFilterChange={setTypeFilter}
        keyword={keyword}
        onKeywordChange={setKeyword}
        emptyDescription={
          viewKbId === 'kb-fangtai-cases'
            ? '暂无案例条目，完成差异复核后可沉淀，或上传 Excel 补充'
            : '暂无条目，请上传 Excel 对账经验表（如收入/回款异常问题登记表）'
        }
        onOpen={setDetail}
        hideTitle
      />

      <AdminCaseDetailModal
        caseItem={detail}
        open={!!detail}
        onClose={() => setDetail(null)}
        onGenerateRule={onGenerateRule}
        onNavigateCases={onNavigateCases}
        showCasesLink
      />
    </div>
  )
}

/** 经验案例页 */
export function AdminCasesPage({
  cases,
  initialCaseId,
  onInitialHandled,
  onGenerateRule,
}: {
  cases: CaseAsset[]
  initialCaseId?: string | null
  onInitialHandled?: () => void
  onGenerateRule?: (caseItem: CaseAsset) => void
}) {
  const [typeFilter, setTypeFilter] = useState('all')
  const [keyword, setKeyword] = useState('')
  const [detail, setDetail] = useState<CaseAsset | null>(null)

  useEffect(() => {
    if (!initialCaseId || !cases.length) return
    const hit = cases.find((c) => c.id === initialCaseId)
    if (hit) setDetail(hit)
    onInitialHandled?.()
  }, [initialCaseId, cases, onInitialHandled])

  const filtered = useMemo(
    () => filterCases(cases, { typeFilter, keyword }),
    [cases, typeFilter, keyword],
  )

  return (
    <div className="admin-kb-page">
      <div className="admin-skills-head admin-kb-head">
        <Typography.Title level={5} style={{ margin: 0 }}>经验案例</Typography.Title>
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
          placeholder="搜索根因、处理结果或建议"
          className="admin-skills-search admin-kb-search"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      <AdminCaseEntriesPanel
        title="全部沉淀案例"
        subtitle={`共 ${filtered.length} 条`}
        cases={filtered}
        typeFilter={typeFilter}
        onTypeFilterChange={setTypeFilter}
        keyword={keyword}
        onKeywordChange={setKeyword}
        emptyDescription="暂无案例，差异复核归档后将出现在此"
        onOpen={setDetail}
        showGenerateRule
        onGenerateRule={onGenerateRule}
      />

      <AdminCaseDetailModal
        caseItem={detail}
        open={!!detail}
        onClose={() => setDetail(null)}
        onGenerateRule={onGenerateRule}
      />
    </div>
  )
}
