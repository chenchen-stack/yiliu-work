import type { AdminDataSource } from '../api/client'

/** 管理后台数据源展示分类 */
export type DatasourceCatalog = 'sap' | 'dms' | 'fanruan' | 'other'

export const CATALOG_META: Record<
  DatasourceCatalog,
  { label: string; desc: string; tagColor: string; order: number }
> = {
  sap: {
    label: 'SAP · 业务侧',
    desc: '方太 POC：结算行明细、收入总额、结算单等（业务侧）',
    tagColor: 'blue',
    order: 0,
  },
  dms: {
    label: 'DMS · 财务侧',
    desc: '方太 POC：收入台账、订单、结算单等（财务侧）',
    tagColor: 'cyan',
    order: 1,
  },
  fanruan: {
    label: '帆软 / 报表',
    desc: '方太 POC：对账平台差异汇总',
    tagColor: 'geekblue',
    order: 2,
  },
  other: {
    label: '其他',
    desc: '未归入上述类别的接入数据',
    tagColor: 'default',
    order: 3,
  },
}

const CATALOG_ORDER: DatasourceCatalog[] = ['sap', 'dms', 'fanruan', 'other']

export function classifyDatasource(ds: AdminDataSource): DatasourceCatalog {
  const name = ds.name || ''
  const st = (ds.system_type || '').toLowerCase()
  const prof = (ds.detected_profile || '').toLowerCase()

  if (st === 'fanruan' || prof.includes('fanruan') || /帆软|fanruan|对账平台|报表/.test(name)) {
    return 'fanruan'
  }
  if (
    st === 'sap'
    || prof.includes('sap')
    || /SAP|结算行|收入总额|结算单|billing|revenue_total/i.test(name)
  ) {
    return 'sap'
  }
  if (
    st === 'dms'
    || prof.includes('dms')
    || /DMS|收入台账|台账明细|结算单|订单明细|回款/.test(name)
  ) {
    return 'dms'
  }

  if (ds.side === 'finance') return 'dms'
  if (ds.side === 'business') return 'sap'
  return 'other'
}

export type DatasourceCatalogSection = {
  catalog: DatasourceCatalog
  label: string
  desc: string
  tagColor: string
  items: AdminDataSource[]
}

export function groupDatasourcesByCatalog(list: AdminDataSource[]): DatasourceCatalogSection[] {
  const buckets = new Map<DatasourceCatalog, AdminDataSource[]>()
  for (const key of CATALOG_ORDER) buckets.set(key, [])
  for (const ds of list) {
    const cat = classifyDatasource(ds)
    buckets.get(cat)!.push(ds)
  }
  return CATALOG_ORDER
    .map((catalog) => ({
      catalog,
      label: CATALOG_META[catalog].label,
      desc: CATALOG_META[catalog].desc,
      tagColor: CATALOG_META[catalog].tagColor,
      items: buckets.get(catalog) || [],
    }))
    .filter((s) => s.items.length > 0)
}

export function catalogBadgeLabel(catalog: DatasourceCatalog): string {
  const map: Record<DatasourceCatalog, string> = {
    sap: 'SAP',
    dms: 'DMS',
    fanruan: '帆软',
    other: '其他',
  }
  return map[catalog]
}
