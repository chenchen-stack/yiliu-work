import type { AdminDataSource } from '../api/client'

const LAST_PAIR_KEY = 'yiliu_last_datasource_pair_v3'

/** 客户固定核对表对：业务侧名称模式 → 财务侧名称模式（不可随意交叉） */
export const CANONICAL_DATASOURCE_PAIRS: Array<{
  id: string
  biz: RegExp
  fin: RegExp
  shortLabel: string
}> = [
  {
    id: 'billing-ledger',
    biz: /SAP(结算行明细|发货开票明细|结算单对应的订单行明细)/,
    fin: /DMS收入台账明细/,
    shortLabel: '结算行↔收入台账',
  },
  { id: 'revenue-settlement', biz: /SAP收入总额/, fin: /DMS结算单明细/, shortLabel: '收入总额↔结算单' },
]

/** @deprecated 内部兼容 */
const PREFERRED_PAIRS = CANONICAL_DATASOURCE_PAIRS.map(({ biz, fin }) => ({ biz, fin }))

/** 凭证级↔结算单级：需完成中文列映射后方可绑定，不作为默认演示表对 */
export function isWeakDatasourcePair(biz?: AdminDataSource, fin?: AdminDataSource): boolean {
  if (!biz || !fin) return false
  return /SAP收入总额/.test(biz.name) && /DMS结算单明细/.test(fin.name)
}

export function pickPreferredDatasource(
  list: AdminDataSource[],
  side: 'business' | 'finance',
): string | undefined {
  const filtered = list.filter((d) => d.side === side)
  if (!filtered.length) return undefined
  const preferredProfile = side === 'business' ? 'sap' : 'dms'
  const scored = filtered.map((d) => {
    const cols = d.detected_columns || []
    const englishCols = cols.filter((c) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(c)).length
    const profileBonus = d.detected_profile === preferredProfile ? 20 : 0
    const pocBonus = /结算行|收入台账/.test(d.name) ? 25 : 0
    return { id: d.id, score: englishCols * 2 + profileBonus + pocBonus + cols.length * 0.01 }
  })
  scored.sort((a, b) => b.score - a.score)
  return scored[0]?.id
}

export function loadLastDatasourcePair(): { bizId?: string; finId?: string } {
  try {
    const raw = localStorage.getItem(LAST_PAIR_KEY)
    if (!raw) return {}
    return JSON.parse(raw) as { bizId?: string; finId?: string }
  } catch {
    return {}
  }
}

export function saveLastDatasourcePair(bizId: string, finId: string) {
  localStorage.setItem(LAST_PAIR_KEY, JSON.stringify({ bizId, finId }))
}

export type ResolvedDatasourcePair = {
  pairId: string
  biz: AdminDataSource
  fin: AdminDataSource
  label: string
}

/** 当前库中实际存在、且符合固定配对规则的全部表对 */
export function buildCanonicalPairs(list: AdminDataSource[]): ResolvedDatasourcePair[] {
  const bizList = list.filter((d) => d.side === 'business')
  const finList = list.filter((d) => d.side === 'finance')
  const out: ResolvedDatasourcePair[] = []
  for (const rule of CANONICAL_DATASOURCE_PAIRS) {
    const biz = bizList.find((d) => rule.biz.test(d.name))
    const fin = finList.find((d) => rule.fin.test(d.name))
    if (biz && fin) {
      out.push({
        pairId: rule.id,
        biz,
        fin,
        label: rule.shortLabel,
      })
    }
  }
  return out
}

export function partnerFinanceIdForBusiness(
  businessId: string | undefined,
  list: AdminDataSource[],
): string | undefined {
  const biz = list.find((d) => d.id === businessId)
  if (!biz) return undefined
  const finList = list.filter((d) => d.side === 'finance')
  for (const rule of CANONICAL_DATASOURCE_PAIRS) {
    if (rule.biz.test(biz.name)) {
      const fin = finList.find((d) => rule.fin.test(d.name))
      if (fin) return fin.id
    }
  }
  return undefined
}

export function partnerBusinessIdForFinance(
  financeId: string | undefined,
  list: AdminDataSource[],
): string | undefined {
  const fin = list.find((d) => d.id === financeId)
  if (!fin) return undefined
  const bizList = list.filter((d) => d.side === 'business')
  for (const rule of CANONICAL_DATASOURCE_PAIRS) {
    if (rule.fin.test(fin.name)) {
      const biz = bizList.find((d) => rule.biz.test(d.name))
      if (biz) return biz.id
    }
  }
  return undefined
}

export function isCanonicalPair(
  businessId: string | undefined,
  financeId: string | undefined,
  list: AdminDataSource[],
): boolean {
  if (!businessId || !financeId) return false
  return partnerFinanceIdForBusiness(businessId, list) === financeId
}

function findPairByPattern(
  bizList: AdminDataSource[],
  finList: AdminDataSource[],
): { bizId?: string; finId?: string } {
  for (const rule of PREFERRED_PAIRS) {
    const biz = bizList.find((d) => rule.biz.test(d.name))
    const fin = finList.find((d) => rule.fin.test(d.name))
    if (biz && fin) return { bizId: biz.id, finId: fin.id }
  }
  return {}
}

export function resolveDefaultPair(list: AdminDataSource[]): { bizId?: string; finId?: string } {
  const pairs = buildCanonicalPairs(list)
  if (pairs.length) {
    const preferred = pairs.find((p) => p.pairId === 'billing-ledger') || pairs[0]
    return { bizId: preferred.biz.id, finId: preferred.fin.id }
  }

  const bizList = list.filter((d) => d.side === 'business')
  const finList = list.filter((d) => d.side === 'finance')
  if (!bizList.length || !finList.length) return {}

  const patterned = findPairByPattern(bizList, finList)
  if (patterned.bizId && patterned.finId) return patterned

  const last = loadLastDatasourcePair()
  if (last.bizId && last.finId) {
    const biz = bizList.find((d) => d.id === last.bizId)
    const fin = finList.find((d) => d.id === last.finId)
    if (biz && fin && !isWeakDatasourcePair(biz, fin)) {
      return { bizId: last.bizId, finId: last.finId }
    }
  }

  return {
    bizId: pickPreferredDatasource(list, 'business'),
    finId: pickPreferredDatasource(list, 'finance'),
  }
}
