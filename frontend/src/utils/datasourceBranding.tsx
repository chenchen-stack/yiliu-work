import { useState } from 'react'
import { DatabaseOutlined } from '@ant-design/icons'
import type { AdminDataSource } from '../api/client'
import {
  type DatasourceCatalog,
  CATALOG_META,
  groupDatasourcesByCatalog,
} from './datasourceCatalog'
/** 官方/正版来源：SAP·SimpleIcons(#0FAAFF)、帆软·fanruan.com favicon、方太·fotile.com favicon(DMS)、PostgreSQL·SimpleIcons、Excel·SimpleIcons */
import sapLogo from '../assets/brand/sap-icon.svg'
import dmsLogo from '../assets/brand/fotile-official.ico'
import fanruanLogo from '../assets/brand/fanruan-official.png'
import postgresqlLogo from '../assets/brand/postgresql-icon.svg'
import knowledgeLogo from '../assets/brand/knowledge-icon.svg'
import excelLogo from '../assets/brand/excel-official.svg'

export type DbEngineId = 'postgresql' | 'sap' | 'dms' | 'fanruan' | 'excel' | 'knowledge'

/** 有品牌资产的可视化键；generic 仅回退通用数据库图标 */
export type DatasourceVisualKey = DatasourceCatalog | 'knowledge' | 'generic'

export type DatasourceCluster = {
  id: string
  catalog: DatasourceCatalog
  dbTitle: string
  engineLabel: string
  engineId: DbEngineId
  sideLabel: string
  items: AdminDataSource[]
  tableCount: number
  totalRows: number
}

export type BrandLogoSet = {
  brandUrl: string
  engineUrl?: string
  brandAlt: string
  fallback: string
}

const CATALOG_DB: Record<DatasourceCatalog, { dbTitle: string; engineLabel: string; engineId: DbEngineId }> = {
  sap: { dbTitle: 'SAP 业务库', engineLabel: 'PostgreSQL', engineId: 'postgresql' },
  dms: { dbTitle: 'DMS 财务库', engineLabel: 'PostgreSQL', engineId: 'postgresql' },
  fanruan: { dbTitle: '帆软数据平台', engineLabel: 'BI 数据集', engineId: 'fanruan' },
  other: { dbTitle: '本地接入', engineLabel: 'CSV / Excel', engineId: 'excel' },
}

/** 本地品牌资产：系统品牌 + 可选底层引擎角标 */
export const CATALOG_BRANDS: Record<DatasourceCatalog | 'knowledge', BrandLogoSet> = {
  sap: {
    brandUrl: sapLogo,
    engineUrl: postgresqlLogo,
    brandAlt: 'SAP',
    fallback: 'SAP',
  },
  dms: {
    brandUrl: dmsLogo,
    engineUrl: postgresqlLogo,
    brandAlt: '方太 DMS',
    fallback: 'FT',
  },
  fanruan: {
    brandUrl: fanruanLogo,
    brandAlt: '帆软',
    fallback: 'FR',
  },
  other: {
    brandUrl: excelLogo,
    brandAlt: '文件',
    fallback: 'XL',
  },
  knowledge: {
    brandUrl: knowledgeLogo,
    brandAlt: '知识库',
    fallback: 'KB',
  },
}

const SIDE_BY_CATALOG: Record<DatasourceCatalog, string> = {
  sap: '业务侧',
  dms: '财务侧',
  fanruan: '报表',
  other: '其他',
}

const ONTOLOGY_LAYER_CATALOG: Record<string, DatasourceVisualKey> = {
  sap_pg: 'sap',
  dms_pg: 'dms',
  fanruan_pg: 'fanruan',
  knowledge: 'knowledge',
}

export function getBrandLogos(catalog: DatasourceCatalog | 'knowledge'): BrandLogoSet {
  return CATALOG_BRANDS[catalog] || CATALOG_BRANDS.other
}

/** 统一解析：对话 kind / 本体 code / 数据源元信息 → 可视化键 */
export function resolveDatasourceVisualKey(input: {
  kind?: string
  system_type?: string
  detected_profile?: string
  datasource_code?: string
  name?: string
  side?: string
}): DatasourceVisualKey {
  const kind = (input.kind || '').toLowerCase()
  if (kind === 'sap' || kind === 'dms' || kind === 'fanruan') return kind
  if (kind === 'knowledge' || kind === 'kb') return 'knowledge'

  if (input.datasource_code) {
    const layer = ONTOLOGY_LAYER_CATALOG[input.datasource_code]
    if (layer) return layer
    const meta = ontologyDatasourceMeta(input.datasource_code)
    if (meta.catalog === 'knowledge') return 'knowledge'
    if (meta.catalog !== 'other') return meta.catalog
  }

  const probe = `${input.system_type || ''} ${input.detected_profile || ''} ${input.name || ''}`.toLowerCase()
  if (/帆软|fanruan|对账平台|报表/.test(probe)) return 'fanruan'
  if (/sap|结算行|billing|revenue_total/.test(probe)) return 'sap'
  if (/dms|台账|ledger|订单明细/.test(probe)) return 'dms'
  if (input.side === 'business') return 'sap'
  if (input.side === 'finance') return 'dms'
  return 'generic'
}

export function ontologyLayerVisualKey(layerKey: string): DatasourceVisualKey {
  return ONTOLOGY_LAYER_CATALOG[layerKey] || resolveDatasourceVisualKey({ datasource_code: layerKey })
}

export function buildDatasourceClusters(list: AdminDataSource[]): DatasourceCluster[] {
  return groupDatasourcesByCatalog(list).map((section) => {
    const meta = CATALOG_DB[section.catalog]
    return {
      id: section.catalog,
      catalog: section.catalog,
      dbTitle: meta.dbTitle,
      engineLabel: meta.engineLabel,
      engineId: meta.engineId,
      sideLabel: CATALOG_META[section.catalog].label.split('·')[0]?.trim() || SIDE_BY_CATALOG[section.catalog],
      items: section.items,
      tableCount: section.items.length,
      totalRows: section.items.reduce((sum, d) => sum + (d.row_count || 0), 0),
    }
  })
}

export type OntologyDatasourceMeta = {
  dbTitle: string
  engineLabel: string
  catalog: DatasourceCatalog | 'knowledge'
  engineId: DbEngineId
}

const ONTOLOGY_DS: Record<string, OntologyDatasourceMeta> = {
  sap_pg: { dbTitle: 'SAP 业务库', engineLabel: 'PostgreSQL', catalog: 'sap', engineId: 'postgresql' },
  dms_pg: { dbTitle: 'DMS 财务库', engineLabel: 'PostgreSQL', catalog: 'dms', engineId: 'postgresql' },
  fanruan_pg: { dbTitle: '帆软数据平台', engineLabel: 'BI', catalog: 'fanruan', engineId: 'fanruan' },
  knowledge: { dbTitle: '异常知识库', engineLabel: '知识条目', catalog: 'knowledge', engineId: 'knowledge' },
  fangtai_poc: { dbTitle: '方太 POC', engineLabel: '样本', catalog: 'other', engineId: 'excel' },
  fangtai_exception: { dbTitle: '方太异常库', engineLabel: '样本', catalog: 'other', engineId: 'excel' },
}

export function ontologyDatasourceMeta(code: string): OntologyDatasourceMeta {
  if (ONTOLOGY_DS[code]) return ONTOLOGY_DS[code]
  if (code.includes('sap')) return ONTOLOGY_DS.sap_pg
  if (code.includes('dms')) return ONTOLOGY_DS.dms_pg
  if (code.includes('fanruan')) return ONTOLOGY_DS.fanruan_pg
  if (code.includes('knowledge')) return ONTOLOGY_DS.knowledge
  return { dbTitle: code, engineLabel: '—', catalog: 'other', engineId: 'excel' }
}

function RemoteLogoImg({
  src,
  alt,
  className,
  size,
}: {
  src: string
  alt: string
  className?: string
  size: number
}) {
  const [failed, setFailed] = useState(false)
  if (failed) return null
  return (
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      className={className}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
    />
  )
}

export function DatasourceBrandIcon({
  catalog,
  size = 28,
  showEngine = true,
}: {
  catalog: DatasourceCatalog | 'knowledge'
  size?: number
  /** SAP/DMS 显示 PostgreSQL 引擎角标；帆软/知识库/文件不显示 */
  showEngine?: boolean
}) {
  const brand = getBrandLogos(catalog)
  const [mainFailed, setMainFailed] = useState(false)

  return (
    <span className="ds-brand-icon" style={{ width: size, height: size }} data-catalog={catalog}>
      {!mainFailed ? (
        <img
          src={brand.brandUrl}
          alt={brand.brandAlt}
          width={size}
          height={size}
          className="ds-brand-icon__main"
          loading="lazy"
          decoding="async"
          onError={() => setMainFailed(true)}
        />
      ) : (
        <span className="ds-brand-icon__fallback">{brand.fallback}</span>
      )}
      {showEngine && brand.engineUrl && (
        <span className="ds-brand-icon__engine-wrap">
          <RemoteLogoImg
            src={brand.engineUrl}
            alt=""
            size={Math.max(12, Math.round(size * 0.46))}
            className="ds-brand-icon__engine"
          />
        </span>
      )}
    </span>
  )
}

/** 对话/任务等场景：按 kind 或 code 自动选品牌或通用库图标 */
export function DatasourceVisualIcon({
  kind,
  datasourceCode,
  size = 28,
  showEngine = true,
}: {
  kind?: string
  datasourceCode?: string
  size?: number
  showEngine?: boolean
}) {
  const visualKey = resolveDatasourceVisualKey({ kind, datasource_code: datasourceCode })
  if (visualKey === 'generic') {
    return (
      <span className="ds-brand-icon ds-brand-icon--generic" style={{ width: size, height: size }}>
        <DatabaseOutlined style={{ fontSize: Math.round(size * 0.5), color: '#94a3b8' }} />
      </span>
    )
  }
  return <DatasourceBrandIcon catalog={visualKey} size={size} showEngine={showEngine} />
}

/** SAP + DMS 并排，用于「连接演示库」等双系统操作 */
export function DatasourcePairIcons({ size = 18 }: { size?: number }) {
  return (
    <span className="ds-pair-icons" aria-hidden>
      <DatasourceBrandIcon catalog="sap" size={size} showEngine={false} />
      <DatasourceBrandIcon catalog="dms" size={size} showEngine={false} />
    </span>
  )
}

/** @deprecated 使用 DatasourceBrandIcon */
export function DatasourceDbLogo({
  catalog,
  size = 28,
}: {
  catalog: DatasourceCatalog | 'knowledge'
  engineId?: DbEngineId
  size?: number
}) {
  return <DatasourceBrandIcon catalog={catalog} size={size} />
}

export function DatasourceDbBadge({
  code,
  showEngine = true,
}: {
  code: string
  showEngine?: boolean
}) {
  const meta = ontologyDatasourceMeta(code)
  return (
    <span className="ds-db-badge">
      <DatasourceBrandIcon catalog={meta.catalog} size={26} showEngine={showEngine} />
      <span className="ds-db-badge__text">
        <span className="ds-db-badge__title">{meta.dbTitle}</span>
        {showEngine && <span className="ds-db-badge__engine">{meta.engineLabel}</span>}
      </span>
    </span>
  )
}
