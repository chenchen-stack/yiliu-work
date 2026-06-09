import { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Col, Input, Popover, Row, Space, Statistic, Table, Tabs, Tag, Tooltip, Typography, message, Drawer,
} from 'antd'
import {
  ReloadOutlined, SearchOutlined, NodeIndexOutlined, BookOutlined, ApiOutlined, InfoCircleOutlined,
  SafetyCertificateOutlined, LinkOutlined,
} from '@ant-design/icons'
import {
  getOntologyStats, listOntologyEntities, listOntologyRelations, listOntologyRules,
  reloadOntologyFromFangtai, searchOntologySimilar, getOntologyPromptPreview, getOntologyGraph,
  type OntologyEntityRow,
  type OntologyGraphPayload,
} from '../api/client'
import { formatApiError } from '../api/errors'
import { OntologyGraphPanel } from './OntologyGraphCanvas'
import { DatasourceDbBadge } from '../utils/datasourceBranding'
import {
  humanizeRelationDescription,
  humanizeRuleContent,
  ruleSourceMeta,
  ruleStatusMeta,
  ruleTypeMeta,
  shortenEntityKey,
} from '../utils/ontologyUserLabels'

const ONTOLOGY_EXTRACT_HINT = (
  <>
    使用「收入对账-POC数据(1).xlsx」抽取列结构，实体名对齐 A 客户设计（如 dms_revenue_ledger、sap_settlement_line）。
    <br />
    请将文件放到 <Typography.Text code>backend/data/samples/</Typography.Text> 或配置环境变量{' '}
    <Typography.Text code>FANGTAI_POC_XLSX</Typography.Text>。
    <br />
    与「数据语义 → 字段映射」互补。
  </>
)

export type OntologyExplorerSection = 'full' | 'graph' | 'catalog'

type ExplorerProps = {
  /** full=原多 Tab；graph=仅图谱；catalog=实体/关系/规则（无图谱 Tab） */
  section?: OntologyExplorerSection
  onNavigateToRuleEngine?: () => void
}

const RULE_ENGINE_FLOW_HINT = (
  <>
    <strong>推荐流程：</strong>
    在「规则引擎」上传《收入/回款异常问题登记表》Excel → 自动生成「自动检测」类规则 → 同步到本页「核对规则」。
    「数据约定」「平衡校验」类规则，可通过「从方太样本重新抽取」或手工维护。
  </>
)

export function AdminOntologyExplorer({ section = 'full', onNavigateToRuleEngine }: ExplorerProps) {
  const showGraph = section === 'full' || section === 'graph'
  const showCatalog = section === 'full' || section === 'catalog'
  const catalogDefaultKey = section === 'catalog' ? 'entities' : 'graph'
  const [stats, setStats] = useState<Awaited<ReturnType<typeof getOntologyStats>> | null>(null)
  const [entities, setEntities] = useState<OntologyEntityRow[]>([])
  const [relations, setRelations] = useState<Awaited<ReturnType<typeof listOntologyRelations>>>([])
  const [rules, setRules] = useState<Awaited<ReturnType<typeof listOntologyRules>>>([])
  const [loading, setLoading] = useState(true)
  const [reloadBusy, setReloadBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [similar, setSimilar] = useState<Array<{ entity_key: string; label: string; score: number }>>([])
  const [detail, setDetail] = useState<OntologyEntityRow | null>(null)
  const [promptMd, setPromptMd] = useState('')
  const [graph, setGraph] = useState<OntologyGraphPayload | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, ent, rel, rul, md, g] = await Promise.all([
        getOntologyStats(),
        listOntologyEntities({ domain: 'revenue_reconciliation' }),
        listOntologyRelations(),
        listOntologyRules({ domain: 'revenue_reconciliation' }),
        getOntologyPromptPreview(),
        getOntologyGraph({ view: 'full' }),
      ])
      setStats(s)
      setEntities(ent)
      setRelations(rel)
      setRules(rul)
      setPromptMd(md)
      setGraph(g)
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleReload = async () => {
    setReloadBusy(true)
    try {
      const res = await reloadOntologyFromFangtai()
      message.success(
        res.message || `抽取完成：${res.data.entities_upserted} 实体，${res.data.rules_upserted} 规则`,
      )
      if (res.data.errors?.length) {
        message.warning(res.data.errors.join('; '))
      }
      await load()
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setReloadBusy(false)
    }
  }

  const handleSearch = async () => {
    if (!query.trim()) return
    try {
      const hits = await searchOntologySimilar(query.trim())
      setSimilar(hits)
    } catch (e) {
      message.error(formatApiError(e))
    }
  }

  const entityColumns = [
    {
      title: '表 / Sheet',
      dataIndex: 'label',
      render: (_: string, r: OntologyEntityRow) => (
        <Button type="link" style={{ padding: 0 }} onClick={() => setDetail(r)}>
          {r.label}
        </Button>
      ),
    },
    {
      title: '来源系统',
      dataIndex: 'datasource_code',
      width: 200,
      render: (v: string) => <DatasourceDbBadge code={v} />,
    },
    {
      title: '字段数',
      key: 'cols',
      width: 72,
      render: (_: unknown, r: OntologyEntityRow) => r.columns?.length || 0,
    },
    {
      title: '归属',
      dataIndex: 'entity_key',
      width: 140,
      ellipsis: true,
      render: (v: string) => (
        <Tooltip title={`技术编号：${v}`}>
          <span>{shortenEntityKey(v)}</span>
        </Tooltip>
      ),
    },
  ]

  return (
    <div className="ontology-explorer">
      <div className="ontology-explorer__toolbar">
        <div className="ontology-explorer__toolbar-hints">
          <Tooltip title={ONTOLOGY_EXTRACT_HINT} placement="bottomLeft" styles={{ root: { maxWidth: 400 } }}>
            <span className="ontology-explorer__hint-trigger" role="button" tabIndex={0}>
              <InfoCircleOutlined />
              <span>数据来源说明</span>
            </span>
          </Tooltip>
          {showCatalog && (
            <Popover
              trigger="hover"
              placement="bottomLeft"
              overlayClassName="ontology-explorer__rule-hint-overlay"
              content={(
                <div className="ontology-explorer__rule-hint-pop">
                  <div className="ontology-explorer__rule-hint-pop__title">核对规则与登记表绑定</div>
                  <Typography.Paragraph type="secondary" style={{ fontSize: 13, marginBottom: 8 }}>
                    {RULE_ENGINE_FLOW_HINT}
                  </Typography.Paragraph>
                  {onNavigateToRuleEngine && (
                    <Button
                      type="link"
                      size="small"
                      icon={<LinkOutlined />}
                      style={{ padding: 0, height: 'auto' }}
                      onClick={onNavigateToRuleEngine}
                    >
                      前往规则引擎上传登记表
                    </Button>
                  )}
                </div>
              )}
            >
              <span className="ontology-explorer__hint-trigger" role="button" tabIndex={0}>
                <SafetyCertificateOutlined />
                <span>规则引擎绑定</span>
              </span>
            </Popover>
          )}
        </div>
        <Button
          type="primary"
          className="catalog-upload-btn"
          icon={<ReloadOutlined />}
          loading={reloadBusy}
          onClick={handleReload}
        >
          从方太样本重新抽取
        </Button>
      </div>

      {showCatalog && stats && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}><Card size="small"><Statistic title="业务数据表" value={stats.entity_count} prefix={<DatabaseIcon />} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="字段" value={stats.column_count} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="字段对应" value={stats.relation_count} prefix={<NodeIndexOutlined />} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="生效规则" value={stats.published_rule_count} prefix={<BookOutlined />} /></Card></Col>
        </Row>
      )}

      {showCatalog && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space.Compact style={{ width: '100%' }}>
            <Input
              placeholder="自然语言探索，如：SAP结算行与DMS台账如何对齐？"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onPressEnter={handleSearch}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>语义匹配</Button>
          </Space.Compact>
          {similar.length > 0 && (
            <div style={{ marginTop: 12 }}>
              {similar.map((h) => (
                <Tag
                  key={h.entity_key}
                  color="blue"
                  style={{ cursor: 'pointer', marginBottom: 4 }}
                  onClick={() => {
                    const ent = entities.find((e) => e.entity_key === h.entity_key)
                    if (ent) setDetail(ent)
                  }}
                >
                  {h.label} ({h.score})
                </Tag>
              ))}
            </div>
          )}
        </Card>
      )}

      {section === 'graph' && (
        graph ? (
          <OntologyGraphPanel
            fullNodes={graph.nodes}
            fullEdges={graph.edges}
            layers={graph.layers}
            onNodeClick={(n) => {
              const ent = entities.find((e) => e.entity_key === n.id)
              if (ent) setDetail(ent)
            }}
          />
        ) : (
          <Typography.Text type="secondary">加载图谱…</Typography.Text>
        )
      )}

      {(section === 'full' || section === 'catalog') && (
        <Tabs
          defaultActiveKey={catalogDefaultKey}
          items={[
            ...(showGraph
              ? [{
                  key: 'graph',
                  label: '关系图谱',
                  children: graph ? (
                    <OntologyGraphPanel
                      fullNodes={graph.nodes}
                      fullEdges={graph.edges}
                      layers={graph.layers}
                      onNodeClick={(n) => {
                        const ent = entities.find((e) => e.entity_key === n.id)
                        if (ent) setDetail(ent)
                      }}
                    />
                  ) : (
                    <Typography.Text type="secondary">加载图谱…</Typography.Text>
                  ),
                }]
              : []),
            {
              key: 'entities',
              label: `业务数据表 (${entities.length})`,
              children: (
                <Table
                  rowKey="entity_key"
                  loading={loading}
                  dataSource={entities}
                  columns={entityColumns}
                  size="small"
                  pagination={{ pageSize: 8 }}
                />
              ),
            },
            {
              key: 'relations',
              label: `字段对应 (${relations.length})`,
              children: (
                <Table
                  rowKey="id"
                  loading={loading}
                  dataSource={relations}
                  size="small"
                  columns={[
                    { title: '来源字段', dataIndex: 'from_column', ellipsis: true },
                    { title: '→', render: () => '→', width: 40 },
                    { title: '对应字段', dataIndex: 'to_column', ellipsis: true },
                    {
                      title: '用途说明',
                      dataIndex: 'description',
                      ellipsis: true,
                      render: (v: string) => (
                        <Tooltip title={v}>
                          <span>{humanizeRelationDescription(v)}</span>
                        </Tooltip>
                      ),
                    },
                  ]}
                  pagination={false}
                />
              ),
            },
            {
              key: 'rules',
              label: `核对规则 (${rules.length})`,
              children: (
                <Table
                  rowKey="id"
                  loading={loading}
                  dataSource={rules}
                  size="small"
                  columns={[
                    {
                      title: '来源',
                      key: 'bind',
                      width: 116,
                      render: (_: unknown, r) => {
                        const src = ruleSourceMeta(r.bind_source)
                        return (
                          <Tooltip title={src.hint}>
                            <Tag color={src.color} icon={r.bind_source === 'rule_engine' ? <SafetyCertificateOutlined /> : undefined}>
                              {src.label}
                            </Tag>
                          </Tooltip>
                        )
                      },
                    },
                    {
                      title: '规则类型',
                      dataIndex: 'rule_type',
                      width: 100,
                      render: (v: string) => {
                        const meta = ruleTypeMeta(v)
                        return (
                          <Tooltip title={meta.hint}>
                            <Tag color={meta.color}>{meta.label}</Tag>
                          </Tooltip>
                        )
                      },
                    },
                    {
                      title: '状态',
                      dataIndex: 'effective_status',
                      width: 88,
                      render: (v: string) => {
                        const meta = ruleStatusMeta(v)
                        return <Tag color={meta.color}>{meta.label}</Tag>
                      },
                    },
                    {
                      title: '规则说明',
                      dataIndex: 'rule_content',
                      ellipsis: true,
                      render: (v: string, r) => {
                        const friendly = humanizeRuleContent(v)
                        const tip = r.rule_engine_name
                          ? `检测项：${r.rule_engine_name}${v !== friendly ? `\n原文：${v}` : ''}`
                          : (v !== friendly ? v : '')
                        return (
                          <Tooltip title={tip || undefined}>
                            <span>{friendly}</span>
                          </Tooltip>
                        )
                      },
                    },
                  ]}
                  pagination={{ pageSize: 10 }}
                />
              ),
            },
            {
              key: 'prompt',
              label: '助手须知预览',
              children: (
                <pre style={{ maxHeight: 400, overflow: 'auto', fontSize: 12, background: '#f8fafc', padding: 12 }}>
                  {promptMd || '加载中…'}
                </pre>
              ),
            },
          ]}
        />
      )}

      <Drawer
        title={detail?.label}
        open={!!detail}
        onClose={() => setDetail(null)}
        width={560}
      >
        {detail && (
          <>
            <Typography.Paragraph type="secondary">{detail.description}</Typography.Paragraph>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              技术编号（日常使用可忽略）：<Typography.Text code style={{ fontSize: 11 }}>{detail.entity_key}</Typography.Text>
            </Typography.Text>
            <div style={{ marginTop: 12 }}>
              {(detail.aliases || []).map((a) => <Tag key={a}>{a}</Tag>)}
            </div>
            <Table
              size="small"
              style={{ marginTop: 16 }}
              rowKey="name"
              dataSource={detail.columns}
              pagination={false}
              columns={[
                { title: '字段', dataIndex: 'name' },
                { title: '数据类型', dataIndex: 'data_type', width: 90 },
                {
                  title: '样例',
                  dataIndex: 'sample_values',
                  render: (v: string[]) => (v?.length ? v.join(', ') : '—'),
                },
              ]}
            />
          </>
        )}
      </Drawer>
    </div>
  )
}

function DatabaseIcon() {
  return <ApiOutlined />
}
