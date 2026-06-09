import type { BusinessCenter } from '../api/client'

/** 与后台 AdminCenter ALL_MODULES 的 key 一致 */
export const PAGE_MODULE_KEYS = {
  todaySummary: 'today_summary',
  createTask: 'create_task',
  taskBatches: 'task_batches',
  differenceHandling: 'difference_handling',
  pendingReview: 'pending_review',
  processingProgress: 'processing_progress',
  reVerification: 're_verification',
  reconciliationReport: 'reconciliation_report',
  auditTrace: 'audit_trace',
  auditTraceSkills: 'audit_trace_skills',
  auditTraceWorkflow: 'audit_trace_workflow',
  auditTraceLogs: 'audit_trace_logs',
} as const

export type PageModuleKey = (typeof PAGE_MODULE_KEYS)[keyof typeof PAGE_MODULE_KEYS]

/**
 * 已发布业务中心的 page_modules 驱动前台显隐。
 * - 无已发布中心：配置项不展示（避免误以为「全量展示=配置无效」）
 * - page_modules 为 null：兼容种子数据，展示全部
 */
export function createShowModule(center: BusinessCenter | null | undefined) {
  return (key: string): boolean => {
    if (!center) return false
    const modules = center.page_modules
    if (modules == null) return true
    return modules.includes(key)
  }
}

/** 审计追溯子模块：后台可分别配置技能记录 / 流程节点 / 操作日志 */
export function createShowAuditSection(center: BusinessCenter | null | undefined) {
  const showModule = createShowModule(center)
  return (sectionKey: string): boolean => {
    if (!showModule(PAGE_MODULE_KEYS.auditTrace)) return false
    const modules = center?.page_modules
    if (!modules) return true
    const granular = modules.some((m) => m.startsWith('audit_trace_'))
    if (!granular) return true
    return modules.includes(sectionKey)
  }
}

export const REVENUE_CENTER_CODE = 'revenue_reconciliation'
