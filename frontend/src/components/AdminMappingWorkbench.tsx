import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Button, Card, Col, Dropdown, Input, Modal, Popconfirm, Radio, Row, Select, Space, Table,
  Tag, Tooltip, Typography, Upload, message, Form,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, PlayCircleOutlined, SaveOutlined,
  UploadOutlined, DatabaseOutlined, ThunderboltOutlined, QuestionCircleOutlined,
  UndoOutlined,
} from '@ant-design/icons'
import {
  OntologyMapping, FieldMappingRowIn, saveFieldMappings, dryRunMapping, MappingDryRunResult,
  AdminDataSource, getAdminDatasources, uploadDatasource, importDatasourcesFromExcel, deleteDatasource,
  DataSourcePreview, previewDatasource, autoMapFields, getReconciliationLaunchOptions,
} from '../api/client'
import { formatApiError } from '../api/errors'
import { REVENUE_CENTER_CODE } from '../utils/pageModules'
import {
  buildCanonicalPairs,
  partnerFinanceIdForBusiness,
  partnerBusinessIdForFinance,
  isCanonicalPair,
} from '../utils/datasourcePair'
import {
  classifyDatasource,
  type DatasourceCatalog,
  CATALOG_META,
} from '../utils/datasourceCatalog'
import { buildDatasourceClusters, DatasourceBrandIcon } from '../utils/datasourceBranding'
import { DatasourceClusterView } from './DatasourceClusterView'

type WorkbenchView = 'datasources' | 'mapping'

type Props = {
  data: OntologyMapping
  view?: WorkbenchView
  onSaved?: () => void
}

const SIDE_LABELS: Record<string, string> = { business: '业务侧', finance: '财务侧' }
const TYPE_LABELS: Record<string, string> = {
  sap: 'SAP', dms: 'DMS', bank: '银企直联', fanruan: '帆软', other: '其他',
}

const TRANSFORM_OPTIONS = [
  { value: 'rename', label: '直接重命名' },
  { value: 'mdm', label: 'MDM 主数据匹配' },
  { value: 'fuzzy_customer', label: '模糊客户匹配' },
  { value: 'amount', label: '金额归一' },
  { value: 'date', label: '日期窗口对齐' },
  { value: 'constant', label: '常量填充' },
]

/** 方太 POC 主核对表对：SAP结算行明细 ↔ DMS收入台账明细 */
const BILLING_LEDGER_FIELD_PAIRS: FieldMappingRowIn[] = [
  { unified_field: 'order_id', unified_label: '单据编号', business_column: 'DMS结算订单', finance_column: '结算单编码', transform: 'rename', enabled: true },
  { unified_field: 'sales_amount', unified_label: '金额', business_column: 'DRP订单金额', finance_column: '收入含税金额', transform: 'amount', enabled: true },
  { unified_field: 'invoice_num', unified_label: '发票号', business_column: '开票凭证', finance_column: '结算单编码', transform: 'rename', enabled: true },
  { unified_field: 'business_date', unified_label: '业务日期', business_column: '处理日期', finance_column: '', transform: 'date', enabled: true },
  { unified_field: 'mdm_code', unified_label: 'MDM编码', business_column: 'DMS行唯一ID', finance_column: 'MDMID', transform: 'mdm', enabled: true },
]

const STANDARD_FIELD_PAIRS = BILLING_LEDGER_FIELD_PAIRS

/** 演示集英文列对照（与 field_mapping.yaml / demo_field_mappings 对齐） */
const DEMO_FIELD_PAIRS: FieldMappingRowIn[] = [
  { unified_field: 'customer_id', unified_label: '客户编码', business_column: 'CUSTOMER', finance_column: 'client_id', transform: 'rename', enabled: true },
  { unified_field: 'order_id', unified_label: '单据编号', business_column: 'VBELN', finance_column: 'order_num', transform: 'rename', enabled: true },
  { unified_field: 'order_date', unified_label: '业务日期', business_column: 'ERDAT', finance_column: 'create_date', transform: 'date', enabled: true },
  { unified_field: 'sales_amount', unified_label: '金额', business_column: 'NETWR', finance_column: 'net_amount', transform: 'amount', enabled: true },
  { unified_field: 'product_code', unified_label: '产品编码', business_column: 'MATNR', finance_column: 'sku', transform: 'rename', enabled: true },
  { unified_field: 'invoice_num', unified_label: '发票号', business_column: 'INVOICE', finance_column: 'invoice_no', transform: 'rename', enabled: true },
]

const STANDARD_LABEL_BY_FIELD = Object.fromEntries(
  STANDARD_FIELD_PAIRS.map((r) => [r.unified_field, r.unified_label]),
)
const STANDARD_FIELD_BY_LABEL = Object.fromEntries(
  STANDARD_FIELD_PAIRS.map((r) => [r.unified_label, r.unified_field]),
)

function resolveUnifiedLabel(field: string, ...candidates: (string | undefined | null)[]): string {
  for (const c of candidates) {
    if (c?.trim()) return c.trim()
  }
  return STANDARD_LABEL_BY_FIELD[field] || field
}

function resolveUnifiedField(label: string, existing?: string): string {
  if (existing?.trim()) return existing.trim()
  return STANDARD_FIELD_BY_LABEL[label.trim()] || label.trim().replace(/\s+/g, '_').toLowerCase()
}

function parseTransformRule(raw?: string | null): Partial<FieldMappingRowIn> {
  if (!raw) return {}
  try {
    const j = JSON.parse(raw)
    if (typeof j === 'object' && j) {
      return {
        unified_label: j.label,
        finance_column: j.finance_column || j.bank_column || '',
        transform: j.transform || 'rename',
      }
    }
  } catch { /* plain text rule */ }
  return { transform: _normalizeTransform(raw) }
}

function columnsOf(ds: AdminDataSource | undefined): string[] {
  return ds?.detected_columns || []
}

function columnsMismatch(
  mappingRows: FieldMappingRowIn[],
  bCols: string[],
  fCols: string[],
): boolean {
  if (!bCols.length && !fCols.length) return false
  return mappingRows.some(
    (r) => (r.business_column && bCols.length && !bCols.includes(r.business_column))
      || (r.finance_column && fCols.length && !fCols.includes(r.finance_column)),
  )
}

function presetRowsForPair(
  pairId: string | undefined,
  bCols: string[],
  fCols: string[],
): FieldMappingRowIn[] | null {
  const base = pairId === 'billing-ledger' ? BILLING_LEDGER_FIELD_PAIRS : null
  if (!base) return null
  const bSet = new Set(bCols)
  const fSet = new Set(fCols)
  const rows = base
    .map((r) => ({
      ...r,
      business_column: r.business_column && bSet.has(r.business_column) ? r.business_column : '',
      finance_column: r.finance_column && fSet.has(r.finance_column) ? r.finance_column : '',
    }))
    .filter((r) => r.business_column || r.finance_column)
  const hasAmount = rows.some(
    (r) => r.unified_field === 'sales_amount' && r.business_column && r.finance_column,
  )
  const hasKey = rows.some(
    (r) => ['order_id', 'invoice_num'].includes(r.unified_field) && r.business_column && r.finance_column,
  )
  return hasAmount && hasKey ? rows : null
}

function _normalizeTransform(v: string | undefined): string {
  if (!v) return 'rename'
  const lower = v.toLowerCase()
  if (lower.startsWith('{') || lower.startsWith('"')) {
    try {
      const parsed = JSON.parse(v)
      const t = (typeof parsed === 'object' ? parsed.transform : v) || 'rename'
      return TRANSFORM_OPTIONS.some((o) => o.value === t) ? t : 'rename'
    } catch { /* fallback */ }
  }
  if (TRANSFORM_OPTIONS.some((o) => o.value === lower)) return lower
  if (lower.includes('mdm') || lower.includes('主数据')) return 'mdm'
  if (lower.includes('模糊') || lower.includes('fuzzy')) return 'fuzzy_customer'
  if (lower.includes('金额') || lower.includes('数值') || lower.includes('amount')) return 'amount'
  if (lower.includes('日期') || lower.includes('date')) return 'date'
  if (lower.includes('常量') || lower.includes('constant')) return 'constant'
  return 'rename'
}

function buildRows(data: OntologyMapping, pairId?: string): FieldMappingRowIn[] {
  const merged = new Map<string, FieldMappingRowIn>()

  const basePreset = pairId === 'billing-ledger'
    ? BILLING_LEDGER_FIELD_PAIRS
    : DEMO_FIELD_PAIRS
  const hasDb = (data.db_mapping_configs?.length ?? 0) > 0
  if (!hasDb) {
    for (const row of basePreset) {
      merged.set(row.unified_field, { ...row })
    }
  }

  if (pairId !== 'billing-ledger' && pairId !== 'revenue-settlement') {
    for (const m of data.demo_field_mappings) {
      const key = String(m.unified_field)
      const prev = merged.get(key)
      merged.set(key, {
        unified_field: key,
        unified_label: resolveUnifiedLabel(key, prev?.unified_label),
        business_column: String(m.sap_field || prev?.business_column || ''),
        finance_column: String(m.finance_field || prev?.finance_column || ''),
        transform: prev?.transform || 'rename',
        enabled: true,
      })
    }
  }

  for (const db of data.db_mapping_configs) {
    const parsed = parseTransformRule(db.transform_rule)
    const prev = merged.get(db.target_field)
    merged.set(db.target_field, {
      unified_field: db.target_field,
      unified_label: resolveUnifiedLabel(
        db.target_field,
        parsed.unified_label,
        prev?.unified_label,
      ),
      business_column: db.source_field || prev?.business_column || '',
      finance_column: parsed.finance_column || prev?.finance_column || '',
      transform: parsed.transform || prev?.transform || 'rename',
      enabled: db.enabled,
    })
  }

  return Array.from(merged.values())
}

export function AdminMappingWorkbench({ data, view = 'datasources', onSaved }: Props) {
  const showDatasources = view === 'datasources'
  const showMapping = view === 'mapping'
  const [rows, setRows] = useState<FieldMappingRowIn[]>([])
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<MappingDryRunResult | null>(null)

  const [datasources, setDatasources] = useState<AdminDataSource[]>([])
  const [uploadModalOpen, setUploadModalOpen] = useState(false)
  const [uploadMode, setUploadMode] = useState<'workbook' | 'single'>('workbook')
  const [uploading, setUploading] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadForm] = Form.useForm()

  const [dryRunSource, setDryRunSource] = useState<'demo' | 'datasource'>('demo')
  const [dryRunDatasetId, setDryRunDatasetId] = useState('dataset_fangtai_real')
  const [dryRunBizDsId, setDryRunBizDsId] = useState<string>()
  const [dryRunFinDsId, setDryRunFinDsId] = useState<string>()

  const [preview, setPreview] = useState<DataSourcePreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [autoMapping, setAutoMapping] = useState(false)
  const [mapBizDsId, setMapBizDsId] = useState<string>()
  const [mapFinDsId, setMapFinDsId] = useState<string>()
  const [dsCatalogFilter, setDsCatalogFilter] = useState<DatasourceCatalog | 'all'>('all')
  const lastAutoFixKey = useRef('')

  useEffect(() => {
    const pairs = buildCanonicalPairs(datasources)
    const pairId = pairs.find(
      (p) => p.biz.id === mapBizDsId && p.fin.id === mapFinDsId,
    )?.pairId
    setRows(buildRows(data, pairId).map((r) => ({
      ...r,
      unified_label: resolveUnifiedLabel(r.unified_field, r.unified_label),
    })))
  }, [data, datasources, mapBizDsId, mapFinDsId])

  const loadDatasources = useCallback(async () => {
    try { setDatasources(await getAdminDatasources()) } catch { /* ignore */ }
  }, [])
  useEffect(() => { loadDatasources() }, [loadDatasources])

  const canonicalPairs = useMemo(
    () => buildCanonicalPairs(datasources),
    [datasources],
  )

  const applyPair = useCallback((bizId: string, finId: string) => {
    setMapBizDsId(bizId)
    setMapFinDsId(finId)
  }, [])

  useEffect(() => {
    if (!datasources.length) return
    let cancelled = false
    ;(async () => {
      try {
        const opts = await getReconciliationLaunchOptions(REVENUE_CENTER_CODE)
        const bound = opts.datasource_pairs?.[0]
        if (!cancelled && bound) {
          applyPair(bound.business_datasource_id, bound.finance_datasource_id)
          return
        }
      } catch { /* 无绑定则走固定表对 */ }
      if (cancelled) return
      const pairs = buildCanonicalPairs(datasources)
      if (pairs.length) {
        const preferred =
          pairs.find((p) => p.pairId === 'billing-ledger')
          || pairs.find((p) => p.pairId === 'billing-ledger')
          || pairs[0]
        applyPair(preferred.biz.id, preferred.fin.id)
      }
    })()
    return () => { cancelled = true }
  }, [datasources, applyPair])

  const onBusinessDsChange = (bizId: string) => {
    const finId = partnerFinanceIdForBusiness(bizId, datasources)
    if (!finId) {
      message.warning('该业务表未配置标准财务侧配对，请从「固定表对」中选择')
      return
    }
    applyPair(bizId, finId)
  }

  const onFinanceDsChange = (finId: string) => {
    const bizId = partnerBusinessIdForFinance(finId, datasources)
    if (!bizId) {
      message.warning('该财务表未配置标准业务侧配对，请从「固定表对」中选择')
      return
    }
    applyPair(bizId, finId)
  }

  const refreshRowsFromColumns = useCallback(async (
    bCols: string[],
    fCols: string[],
    hint?: string,
  ) => {
    if (!bCols.length && !fCols.length) return
    setAutoMapping(true)
    try {
      const aiRows = await autoMapFields(bCols, fCols)
      if (!aiRows?.length) return
      setRows(aiRows.map((r) => ({
        unified_field: r.unified_field,
        unified_label: r.unified_label,
        business_column: r.business_column || '',
        finance_column: r.finance_column || '',
        transform: r.transform || 'rename',
        enabled: r.enabled ?? true,
      })))
      message.info(hint || `已按当前数据源列名生成 ${aiRows.length} 条映射，请核对后保存`)
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setAutoMapping(false)
    }
  }, [])

  const applyRowsForCurrentPair = useCallback((
    pairId: string | undefined,
    bCols: string[],
    fCols: string[],
    label?: string,
  ) => {
    const preset = presetRowsForPair(pairId, bCols, fCols)
    if (preset?.length) {
      setRows(preset)
      message.info(label || '已加载方太 POC 中文列映射，请核对后保存')
      return true
    }
    void refreshRowsFromColumns(
      bCols,
      fCols,
      label || '映射表已按实际列名刷新，请核对后保存',
    )
    return false
  }, [refreshRowsFromColumns])

  const onCanonicalPairChange = (pairId: string) => {
    const hit = canonicalPairs.find((p) => p.pairId === pairId)
    if (!hit) return
    lastAutoFixKey.current = ''
    applyPair(hit.biz.id, hit.fin.id)
    const bCols = hit.biz.detected_columns || []
    const fCols = hit.fin.detected_columns || []
    applyRowsForCurrentPair(
      pairId,
      bCols,
      fCols,
      `已切换为「${hit.label}」，映射已按 POC 列名刷新，请核对后保存`,
    )
  }

  const activePairId = useMemo(() => {
    if (!mapBizDsId || !mapFinDsId) return undefined
    return canonicalPairs.find(
      (p) => p.biz.id === mapBizDsId && p.fin.id === mapFinDsId,
    )?.pairId
  }, [canonicalPairs, mapBizDsId, mapFinDsId])

  const pairMismatch = Boolean(
    mapBizDsId && mapFinDsId && !isCanonicalPair(mapBizDsId, mapFinDsId, datasources),
  )

  const bizList = canonicalPairs.map((p) => p.biz)
  const finListForBiz = useMemo(() => {
    const finId = partnerFinanceIdForBusiness(mapBizDsId, datasources)
    const fin = datasources.find((d) => d.id === finId)
    return fin ? [fin] : []
  }, [mapBizDsId, datasources])

  const mapBizDs = datasources.find((d) => d.id === mapBizDsId)
  const mapFinDs = datasources.find((d) => d.id === mapFinDsId)

  const bizCols = columnsOf(mapBizDs)
  const finCols = columnsOf(mapFinDs)

  useEffect(() => {
    if (!showMapping || !mapBizDsId || !mapFinDsId || !bizCols.length || !finCols.length) return
    const key = `${mapBizDsId}:${mapFinDsId}`
    if (lastAutoFixKey.current === key) return
    if (!columnsMismatch(rows, bizCols, finCols)) return
    applyRowsForCurrentPair(
      activePairId,
      bizCols,
      finCols,
      activePairId === 'billing-ledger'
        ? '检测到旧版英文列名，已自动替换为方太 POC 中文映射'
        : '当前映射列名与数据源不一致，已按实际列名刷新',
    )
    lastAutoFixKey.current = key
  }, [showMapping, mapBizDsId, mapFinDsId, bizCols, finCols, activePairId, rows, applyRowsForCurrentPair])

  const bizColTitle = mapBizDs
    ? `业务侧列（${TYPE_LABELS[mapBizDs.system_type] || mapBizDs.system_type}）`
    : '业务侧列'
  const finColTitle = mapFinDs
    ? `财务侧列（${TYPE_LABELS[mapFinDs.system_type] || mapFinDs.system_type}）`
    : '财务侧列'

  useEffect(() => {
    if (!showMapping) return
    if (mapBizDsId) setDryRunBizDsId(mapBizDsId)
    if (mapFinDsId) setDryRunFinDsId(mapFinDsId)
    if (mapBizDsId && mapFinDsId) setDryRunSource('datasource')
  }, [showMapping, mapBizDsId, mapFinDsId])

  const updateRow = (idx: number, patch: Partial<FieldMappingRowIn>) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }
  const addRow = () => setRows((prev) => [...prev, { unified_field: '', unified_label: '', business_column: '', enabled: true }])
  const removeRow = (idx: number) => setRows((prev) => prev.filter((_, i) => i !== idx))

  const handleSave = async () => {
    const valid = rows
      .filter((r) => (r.unified_label || r.unified_field).trim())
      .map((r) => {
        const label = (r.unified_label || STANDARD_LABEL_BY_FIELD[r.unified_field] || r.unified_field).trim()
        return {
          ...r,
          unified_label: label,
          unified_field: resolveUnifiedField(label, r.unified_field),
        }
      })
    if (!valid.length) return message.warning('至少需要一行映射')
    if (!mapBizDsId || !mapFinDsId) {
      return message.warning('请先在上方选择固定核对表对，再保存映射')
    }
    if (!isCanonicalPair(mapBizDsId, mapFinDsId, datasources)) {
      return message.warning('当前表对不符合客户固定配对规则，请从下拉列表重新选择')
    }
    setSaving(true)
    try {
      await saveFieldMappings(valid, {
        business_datasource_id: mapBizDsId,
        finance_datasource_id: mapFinDsId,
      })
      message.success('字段映射与数据源对已绑定，前台新建任务将仅可使用该表对')
      onSaved?.()
    } catch (e) {
      const msg = formatApiError(e)
      if (msg.includes('列校验') || msg.includes('缺少列')) {
        message.error(
          `${msg}。请点击「AI 映射」或重新选择「发货开票↔收入台账」表对以刷新中文列名后再保存。`,
          8,
        )
      } else {
        message.error(msg)
      }
    }
    finally { setSaving(false) }
  }

  const handleDryRun = async (opts?: {
    source?: 'demo' | 'datasource'
    datasetId?: string
    bizId?: string
    finId?: string
  }) => {
    const source = opts?.source ?? dryRunSource
    const bizId = opts?.bizId ?? dryRunBizDsId ?? mapBizDsId
    const finId = opts?.finId ?? dryRunFinDsId ?? mapFinDsId
    const datasetId = opts?.datasetId ?? dryRunDatasetId
    setRunning(true)
    try {
      const params = source === 'datasource' && bizId && finId
        ? { business_datasource_id: bizId, finance_datasource_id: finId }
        : { dataset_id: datasetId }
      const res = await dryRunMapping(params)
      setResult(res)
      message.success(`试跑完成：${res.matched_count} 对匹配`)
    } catch (e) { message.error(formatApiError(e)) }
    finally { setRunning(false) }
  }

  const resolveUploadFile = (): File | null => {
    if (!uploadFile) return null
    if (uploadFile instanceof File) return uploadFile
    const rc = uploadFile as File & { originFileObj?: File }
    return rc.originFileObj instanceof File ? rc.originFileObj : null
  }

  const resetUploadModal = () => {
    setUploadModalOpen(false)
    setUploadMode('workbook')
    if (uploadMode === 'single') uploadForm.resetFields()
    setUploadFile(null)
  }

  const handleUpload = async () => {
    const file = resolveUploadFile()
    if (!file) return message.warning('请选择文件')
    setUploading(true)
    try {
      if (uploadMode === 'workbook') {
        const res = await importDatasourcesFromExcel(file)
        message.success(
          `${res.message}。字段映射请选「SAP结算行明细」↔「DMS收入台账明细」。`,
          6,
        )
        if (res.skipped?.length) {
          message.warning(
            `未导入：${res.skipped.map((s) => `${s.sheet}（${s.reason}）`).join('；')}`,
            8,
          )
        }
        resetUploadModal()
        await loadDatasources()
        return
      }
      const vals = await uploadForm.validateFields()
      const ds = await uploadDatasource({
        name: vals.name,
        system_type: vals.system_type,
        side: vals.side,
        file,
      })
      message.success(`数据源「${ds.name}」已上传，检测到 ${ds.detected_columns?.length || 0} 列 / ${ds.row_count} 行`)
      resetUploadModal()
      await loadDatasources()
    } catch (e) { message.error(formatApiError(e)) }
    finally { setUploading(false) }
  }

  const handleDeleteDs = async (id: string) => {
    try {
      await deleteDatasource(id)
      message.success('已删除')
      await loadDatasources()
    } catch (e) { message.error(formatApiError(e)) }
  }

  const handleAutoMap = async () => {
    if (bizCols.length === 0 && finCols.length === 0) {
      return message.warning('请先选择业务侧与财务侧数据源')
    }
    setAutoMapping(true)
    try {
      const aiRows = await autoMapFields(bizCols, finCols)
      if (!aiRows?.length) {
        message.warning('未生成映射建议，请检查所选数据源是否包含列名')
        return
      }
      setRows(aiRows.map((r) => ({
        unified_field: r.unified_field,
        unified_label: r.unified_label,
        business_column: r.business_column || '',
        finance_column: r.finance_column || '',
        transform: r.transform || 'rename',
        enabled: r.enabled ?? true,
      })))
      message.success(`AI 已生成 ${aiRows.length} 条映射建议`)
    } catch (e) { message.error(formatApiError(e)) }
    finally { setAutoMapping(false) }
  }

  const handlePreview = async (ds: AdminDataSource) => {
    setPreviewLoading(true)
    try {
      const data = await previewDatasource(ds.id)
      setPreview(data)
    } catch (e) { message.error(formatApiError(e)) }
    finally { setPreviewLoading(false) }
  }

  const colOptions = (side: 'business' | 'finance', current?: string) => {
    const cols = side === 'business' ? bizCols : finCols
    const set = new Set(cols)
    if (current?.trim()) set.add(current.trim())
    return set.size > 0 ? Array.from(set).map((c) => ({ label: c, value: c })) : undefined
  }

  const pairingHelp = (
    <>
      客户核对场景使用<strong>固定表对</strong>（如方太 SAP 凭证 ↔ 方太 DMS 台账），不可随意交叉组合。
      选择业务表后财务表将自动匹配；也可直接切换「固定表对」。保存后前台新建任务仅可使用该绑定对。
    </>
  )
  const dsLabel = (d: AdminDataSource) => `${d.name} · ${d.detected_columns?.length || 0}列`

  const filteredDatasources = useMemo(() => (
    dsCatalogFilter === 'all'
      ? datasources
      : datasources.filter((d) => classifyDatasource(d) === dsCatalogFilter)
  ), [datasources, dsCatalogFilter])

  const clusterCount = useMemo(
    () => buildDatasourceClusters(filteredDatasources).length,
    [filteredDatasources],
  )

  return (
    <div>
      {showDatasources && (
        <>
          <div className="admin-ds-page-head">
            <Typography.Title level={5} style={{ margin: 0 }}>已接入数据源</Typography.Title>
            <Button
              icon={<UploadOutlined />}
              type="primary"
              className="catalog-upload-btn"
              onClick={() => setUploadModalOpen(true)}
            >
              上传数据源
            </Button>
          </div>

          {datasources.length > 0 && (
            <div className="admin-ds-filters">
              <button
                type="button"
                className={`admin-ds-filter${dsCatalogFilter === 'all' ? ' admin-ds-filter--on' : ''}`}
                onClick={() => setDsCatalogFilter('all')}
              >
                全部 ({datasources.length})
              </button>
              {(Object.keys(CATALOG_META) as DatasourceCatalog[])
                .filter((k) => datasources.some((d) => classifyDatasource(d) === k))
                .sort((a, b) => CATALOG_META[a].order - CATALOG_META[b].order)
                .map((k) => (
                  <button
                    key={k}
                    type="button"
                    className={`admin-ds-filter${dsCatalogFilter === k ? ' admin-ds-filter--on' : ''}`}
                    onClick={() => setDsCatalogFilter(k)}
                  >
                    <DatasourceBrandIcon catalog={k} size={16} showEngine={false} />
                    {CATALOG_META[k].label} ({datasources.filter((d) => classifyDatasource(d) === k).length})
                  </button>
                ))}
            </div>
          )}

          {datasources.length === 0 && (
            <Card size="small" style={{ marginBottom: 16, textAlign: 'center', color: '#94a3b8' }}>
              <DatabaseOutlined style={{ fontSize: 28, marginBottom: 8 }} />
              <div>暂无数据源。方太 POC 请用「Excel 工作簿」一次导入多 Sheet；单张 CSV 用「单表上传」</div>
            </Card>
          )}

          {filteredDatasources.length > 0 && (
            <DatasourceClusterView
              datasources={filteredDatasources}
              onPreview={handlePreview}
              onDelete={handleDeleteDs}
            />
          )}
          {datasources.length > 0 && filteredDatasources.length === 0 && (
            <Card size="small" style={{ textAlign: 'center', color: '#94a3b8' }}>
              当前筛选下无数据
            </Card>
          )}
          {clusterCount > 0 && dsCatalogFilter !== 'all' && (
            <Typography.Text type="secondary" className="admin-ds-filter-hint">
              {clusterCount} 个数据库实例 · {filteredDatasources.length} 张表
            </Typography.Text>
          )}
        </>
      )}

      {showMapping && (
        <div className="mapping-workbench">
          <div className="mapping-toolbar">
            <div className="mapping-toolbar-pair">
              <Tooltip title={pairingHelp} placement="bottomLeft">
                <QuestionCircleOutlined className="mapping-help-icon" />
              </Tooltip>
              {canonicalPairs.length > 0 && (
                <Select
                  size="small"
                  placeholder="固定表对"
                  className="mapping-ds-select mapping-ds-select--pair"
                  value={activePairId}
                  onChange={onCanonicalPairChange}
                  options={canonicalPairs.map((p) => ({
                    value: p.pairId,
                    label: p.label,
                  }))}
                />
              )}
              <Select
                size="small"
                placeholder={bizList.length ? `业务侧（${bizList.length}）` : '无可用业务表'}
                className="mapping-ds-select"
                value={mapBizDsId}
                onChange={onBusinessDsChange}
                options={bizList.map((d) => ({ value: d.id, label: dsLabel(d) }))}
              />
              <span className="mapping-pair-arrow">↔</span>
              <Select
                size="small"
                placeholder="自动匹配财务表"
                className="mapping-ds-select"
                value={mapFinDsId}
                onChange={onFinanceDsChange}
                disabled={!mapBizDsId}
                options={finListForBiz.map((d) => ({ value: d.id, label: dsLabel(d) }))}
              />
              {pairMismatch && (
                <Typography.Text type="danger" style={{ fontSize: 11 }}>
                  表对不匹配
                </Typography.Text>
              )}
            </div>
            <Space size={8} wrap className="mapping-toolbar-actions">
              <Tooltip title="恢复为系统默认字段对照">
                <Button type="text" size="small" icon={<UndoOutlined />}
                  onClick={() => setRows(buildRows(data))} />
              </Tooltip>
              <Tooltip title="根据所选表列名 AI 推荐映射">
                <Button size="small" icon={<ThunderboltOutlined />} loading={autoMapping}
                  onClick={handleAutoMap} className="mapping-ai-btn">
                  AI 映射
                </Button>
              </Tooltip>
              <Tooltip title="添加一行对照">
                <Button size="small" icon={<PlusOutlined />} onClick={addRow} />
              </Tooltip>
              <Tooltip title={
                bizCols.length === 0 || finCols.length === 0
                  ? '请先在数据源管理上传并选择业务侧、财务侧表'
                  : '保存后新任务执行时生效'
              }>
                <Button
                  type="primary"
                  size="small"
                  className="catalog-upload-btn"
                  icon={<SaveOutlined />}
                  loading={saving}
                  disabled={bizCols.length === 0 || finCols.length === 0}
                  onClick={handleSave}
                >
                  保存
                </Button>
              </Tooltip>
              <Dropdown
                menu={{
                  items: [
                    {
                      key: 'current',
                      label: '当前表对',
                      disabled: !mapBizDsId || !mapFinDsId,
                    },
                    { type: 'divider' },
                    { key: 'dataset_fangtai_real', label: '方太 POC 真实数据' },
                  ],
                  onClick: ({ key }) => {
                    if (key === 'current') {
                      handleDryRun({ source: 'datasource', bizId: mapBizDsId, finId: mapFinDsId })
                    } else {
                      handleDryRun({ source: 'demo', datasetId: key })
                    }
                  },
                }}
              >
                <Tooltip title="试跑映射规则，不写入任务">
                  <Button size="small" type="text" icon={<PlayCircleOutlined />} loading={running}>
                    试跑
                  </Button>
                </Tooltip>
              </Dropdown>
              {result && (
                <Typography.Text type="secondary" className="mapping-run-badge">
                  {result.matched_count}/{result.match_pairs.length} 匹配
                </Typography.Text>
              )}
            </Space>
          </div>

          <Table
            className="mapping-table"
            size="small"
            pagination={false}
            rowKey={(r) => r.unified_field || `${r.business_column}-${r.finance_column}`}
            dataSource={rows}
            scroll={{ x: 680 }}
            columns={[
          {
            title: '中文标签', dataIndex: 'unified_label', width: 120,
            render: (v: string, _: FieldMappingRowIn, i: number) => (
              <Input size="small" value={v || ''} placeholder="如：客户编码" style={{ width: '100%' }}
                onChange={(e) => updateRow(i, { unified_label: e.target.value })} />
            ),
          },
          {
            title: bizColTitle, dataIndex: 'business_column', width: 150,
            render: (v: string, _: FieldMappingRowIn, i: number) => {
              const opts = colOptions('business', v)
              return opts ? (
                <Select size="small" value={v || undefined} placeholder="选择列" style={{ width: '100%' }}
                  showSearch allowClear options={opts}
                  onChange={(val) => updateRow(i, { business_column: val })} />
              ) : (
                <Input size="small" value={v || ''} placeholder="SAP 列名"
                  onChange={(e) => updateRow(i, { business_column: e.target.value })} />
              )
            },
          },
          {
            title: finColTitle, dataIndex: 'finance_column', width: 150,
            render: (v: string, _: FieldMappingRowIn, i: number) => {
              const opts = colOptions('finance', v)
              return opts ? (
                <Select size="small" value={v || undefined} placeholder="选择列" style={{ width: '100%' }}
                  showSearch allowClear options={opts}
                  onChange={(val) => updateRow(i, { finance_column: val })} />
              ) : (
                <Input size="small" value={v || ''} placeholder="DMS/银企列名"
                  onChange={(e) => updateRow(i, { finance_column: e.target.value })} />
              )
            },
          },
          {
            title: '翻译规则', dataIndex: 'transform', width: 150,
            render: (v: string, _: FieldMappingRowIn, i: number) => {
              const normalized = _normalizeTransform(v)
              return (
                <Select size="small" value={normalized} style={{ width: '100%' }}
                  onChange={(val) => updateRow(i, { transform: val })}
                  options={TRANSFORM_OPTIONS}
                />
              )
            },
          },
          {
            title: '', width: 40,
            render: (_: unknown, __: FieldMappingRowIn, i: number) => (
              <Popconfirm title="删除?" onConfirm={() => removeRow(i)}>
                <Button type="text" size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            ),
          },
            ]}
          />

          {result && (
            <Table
              className="mapping-result-table"
              size="small"
              rowKey={(r) => String(r.business_key || r.invoice_num || '')}
              pagination={false}
              dataSource={result.match_pairs}
              scroll={{ x: 640 }}
              columns={[
              { title: '业务键', dataIndex: 'business_key', width: 88 },
              { title: '业务金额', dataIndex: 'business_amount', width: 96, render: (v: number) => v?.toLocaleString() },
              { title: '财务金额', dataIndex: 'finance_amount', width: 96, render: (v: number) => v?.toLocaleString() },
              { title: '差异', dataIndex: 'amount_diff', width: 80, render: (v: number) => v?.toLocaleString() },
              {
                title: '结果', dataIndex: 'matched', width: 72,
                render: (v: boolean) => v
                  ? <Tag color="success" style={{ margin: 0 }}>匹配</Tag>
                  : <Tag color="warning" style={{ margin: 0 }}>差异</Tag>,
              },
            ]}
            footer={result.unmatched_business.length > 0
              ? () => <Typography.Text type="secondary" style={{ fontSize: 12 }}>未匹配 {result.unmatched_business.length} 条</Typography.Text>
              : undefined}
          />
          )}
        </div>
      )}

      {showDatasources && (
      <Modal
        title={preview ? `${preview.name}（共 ${preview.total_rows} 行）` : '数据预览'}
        open={!!preview}
        onCancel={() => setPreview(null)}
        footer={null}
        width="90vw"
        style={{ top: 24 }}
        styles={{ body: { maxHeight: '75vh', overflow: 'auto' } }}
        loading={previewLoading}
      >
        {preview && (
          <Table
            size="small"
            pagination={{ pageSize: 20, size: 'small', showTotal: (t) => `预览前 ${t} 行 / 共 ${preview.total_rows} 行` }}
            scroll={{ x: Math.max(preview.columns.length * 140, 600) }}
            rowKey={(r) => preview.columns.map((c) => String(r[c] ?? '')).join('|')}
            dataSource={preview.rows}
            columns={preview.columns.map((col) => ({
              title: col,
              dataIndex: col,
              key: col,
              width: 140,
              ellipsis: true,
              render: (v: unknown) => <span style={{ fontSize: 12 }}>{v == null ? '' : String(v)}</span>,
            }))}
          />
        )}
      </Modal>
      )}

      {showDatasources && (
      <Modal
        title="上传数据源"
        open={uploadModalOpen}
        onCancel={resetUploadModal}
        onOk={handleUpload}
        confirmLoading={uploading}
        okText={uploadMode === 'workbook' ? '导入全部 Sheet' : '上传'}
        width={560}
        destroyOnHidden
      >
        <Radio.Group
          value={uploadMode}
          onChange={(e) => { setUploadMode(e.target.value); setUploadFile(null) }}
          optionType="button"
          buttonStyle="solid"
          style={{ marginBottom: 16, width: '100%', display: 'flex' }}
        >
          <Radio.Button value="workbook" style={{ flex: 1, textAlign: 'center' }}>
            Excel 工作簿（推荐）
          </Radio.Button>
          <Radio.Button value="single" style={{ flex: 1, textAlign: 'center' }}>
            单表上传
          </Radio.Button>
        </Radio.Group>

        {uploadMode === 'workbook' ? (
          <>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
              方太 POC（如「收入对账-POC数据(1).xlsx」）含多张 Sheet，将按表名自动拆成多条数据源：
              帆软对账平台、DMS收入台账明细、DMS结算单明细、DMS订单明细、SAP收入总额、SAP结算行明细、SAP结算单明细、SAP结算单对应的订单行明细。
            </Typography.Text>
            <Form.Item label="Excel 工作簿" required style={{ marginBottom: 0 }}>
              <Upload.Dragger
                beforeUpload={(f) => { setUploadFile(f); return false }}
                maxCount={1}
                accept=".xlsx,.xls,.xlsm"
                fileList={uploadFile ? [{ uid: '-1', name: uploadFile.name, status: 'done' }] : []}
                onRemove={() => setUploadFile(null)}
              >
                <p style={{ fontSize: 24, color: '#f97316' }}><UploadOutlined /></p>
                <p>拖入或选择 .xlsx（一个文件 → 多张表）</p>
              </Upload.Dragger>
            </Form.Item>
          </>
        ) : (
          <Form form={uploadForm} layout="vertical" initialValues={{ system_type: 'sap', side: 'business' }}>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
              仅上传一张表（一个 CSV，或 Excel 中的单个 Sheet 另存为文件）。SAP 为业务侧、DMS 为财务侧。
            </Typography.Text>
            <Form.Item name="name" label="数据源名称" rules={[{ required: true, message: '请填写名称' }]}>
              <Input placeholder="如：SAP结算行明细、DMS收入台账明细" />
            </Form.Item>
            <Form.Item name="system_type" label="数据分类" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'sap', label: 'SAP · 业务侧（ERP 发货/收入等）' },
                  { value: 'dms', label: 'DMS · 财务侧（台账/订单/结算等）' },
                  { value: 'fanruan', label: '帆软 · 报表/对账平台' },
                  { value: 'bank', label: '银企直联' },
                  { value: 'other', label: '其他' },
                ]}
                onChange={(v) => {
                  if (v === 'sap') uploadForm.setFieldsValue({ side: 'business' })
                  if (v === 'dms') uploadForm.setFieldsValue({ side: 'finance' })
                }}
              />
            </Form.Item>
            <Form.Item name="side" label="数据角色" rules={[{ required: true }]}>
              <Select options={[
                { value: 'business', label: '业务侧（常与 SAP 对应）' },
                { value: 'finance', label: '财务侧（常与 DMS 对应）' },
              ]} />
            </Form.Item>
            <Form.Item label="上传文件" required>
              <Upload.Dragger
                beforeUpload={(f) => { setUploadFile(f); return false }}
                maxCount={1}
                accept=".csv,.xlsx,.xls"
                fileList={uploadFile ? [{ uid: '-1', name: uploadFile.name, status: 'done' }] : []}
                onRemove={() => setUploadFile(null)}
              >
                <p style={{ fontSize: 24, color: '#f97316' }}><UploadOutlined /></p>
                <p>拖入或点击选择 CSV / Excel 单表文件</p>
              </Upload.Dragger>
            </Form.Item>
          </Form>
        )}
      </Modal>
      )}
    </div>
  )
}
