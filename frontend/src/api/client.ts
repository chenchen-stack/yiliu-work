import axios from 'axios'
import { formatApiError } from './errors'

const api = axios.create({ baseURL: '/api/v1' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401 && !window.location.pathname.includes('/login')) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

export interface User {
  id: string
  username: string
  display_name: string
  role: string
}

export interface BusinessCenter {
  id: string
  name: string
  code: string
  status: string
  workflow_id?: string
  enabled_skill_ids?: string[]
  rule_version_id?: string
  page_modules?: string[]
  allowed_roles?: string[]
  version: number
  workflow?: {
    id?: string
    name?: string
    version?: number
    status?: string
    nodes?: Array<{ id: string; label: string; skill?: string; skill_code?: string }>
    transitions?: Array<{ from: string; to: string }>
  }
  skills?: Array<{ id?: string; name?: string; code?: string; type?: string; version?: number; status?: string }>
  rule_version?: { id?: string; version?: number; status?: string; description?: string }
}

export interface WorkflowRuleBinding {
  id: string
  name: string
  rule_type: string
  severity?: string
}

export interface WorkflowNodePosition {
  x: number
  y: number
}

export interface WorkflowNode {
  id: string
  label?: string
  skill?: string
  skill_code?: string
  enabled?: boolean
  position?: WorkflowNodePosition
  rule_version_id?: string
  rule_bindings?: WorkflowRuleBinding[]
  rule_synced_at?: string
}

export interface WorkflowDetail {
  id: string
  name: string
  code: string
  version: number
  status: string
  nodes?: WorkflowNode[]
  transitions?: Array<{ from: string; to: string }>
}

export interface Task {
  id: string
  business_center_id?: string
  name: string
  period?: string
  status: string
  progress: number
  creator_id: string
  workflow_version?: number
  rule_version_id?: string
  demo_dataset_id?: string
  summary?: Record<string, unknown>
  error_message?: string
  trace_id?: string
  created_at: string
  updated_at: string
  closed_at?: string
}

export interface Difference {
  id: string
  task_id: string
  business_key?: string
  type: string
  business_amount?: number
  finance_amount?: number
  amount_diff?: number
  confidence: number
  status: string
  review_decision?: string
  responsible_party?: string
  assignee_id?: string
  sap_record?: Record<string, unknown>
  dms_record?: Record<string, unknown>
  rule_hits?: Array<Record<string, unknown>>
  evidence?: Record<string, unknown>
  ai_recommendation?: { root_cause?: string; evidence?: string[] }
  ai_explanation?: string
  suggestion?: string
  risk_level?: string
  evidence_chain?: Array<Record<string, unknown>>
  review_comment?: string
}

export interface DashboardStats {
  period_tasks: number
  difference_count: number
  difference_amount: number
  pending_review_count: number
  closed_count: number
  pending_tasks?: number
  reviewing_tasks?: number
  completed_tasks?: number
  pending_reviews?: number
  total_differences?: number
}

export interface DemoDataset {
  id: string
  name: string
  description: string
  expected?: Record<string, number>
}

export interface AuditLog {
  id: string
  trace_id?: string
  object_type: string
  object_id: string
  action: string
  operator?: string
  before_data?: Record<string, unknown>
  after_data?: Record<string, unknown>
  detail?: Record<string, unknown>
  created_at: string
}

export interface CaseAsset {
  id: string
  source_task_id: string
  source_difference_id: string
  confirmed_type: string
  root_cause?: string
  handling_result?: string
  reusable_rule_suggestion?: string
  status: string
  knowledge_base_id?: string | null
  source_kind?: string
  source_file?: string | null
  created_at: string
}

export interface KnowledgeUploadResult {
  knowledge_base_id: string
  source_file: string
  entries_created: number
  total_patterns: number
  title?: string
}

export async function login(username: string, password: string) {
  const { data } = await api.post<{ access_token: string; user: User }>('/auth/login', { username, password })
  localStorage.setItem('token', data.access_token)
  localStorage.setItem('user', JSON.stringify(data.user))
  return data
}

export async function getMe() {
  const { data } = await api.get<User>('/auth/me')
  return data
}

export async function getUsers() {
  const { data } = await api.get<User[]>('/auth/users')
  return data
}

export async function getStats() {
  const { data } = await api.get<DashboardStats>('/dashboard/stats')
  return data
}

export async function getPublishedCenters() {
  const { data } = await api.get<BusinessCenter[]>('/business-centers')
  return data
}

/** 已发布业务中心详情（含 page_modules），与后台配置发布结果一致 */
export async function getBusinessCenterByCode(code: string) {
  const { data } = await api.get<BusinessCenter>(`/business-centers/${code}`)
  return data
}

export async function getDemoDatasets() {
  const { data } = await api.get<DemoDataset[]>('/demo-datasets')
  return data
}

export async function getAdminBusinessCenters() {
  const { data } = await api.get<BusinessCenter[]>('/admin/business-centers')
  return data
}

export async function getAdminBusinessCenter(id: string) {
  const { data } = await api.get<BusinessCenter>(`/admin/business-centers/${id}`)
  return data
}

export async function updateAdminWorkflow(
  workflowId: string,
  body: {
    name?: string
    nodes?: Array<{ id: string; enabled?: boolean; label?: string; position?: WorkflowNodePosition }>
    node_order?: string[]
  },
) {
  const { data } = await api.patch<WorkflowDetail>(`/admin/workflows/${workflowId}`, body)
  return data
}

export async function publishCenter(id: string) {
  const { data } = await api.post<BusinessCenter>(`/admin/business-centers/${id}/publish`)
  return data
}

export async function rollbackCenter(id: string) {
  const { data } = await api.post<BusinessCenter>(`/admin/business-centers/${id}/rollback`)
  return data
}

export async function offlineCenter(id: string) {
  const { data } = await api.post<BusinessCenter>(`/admin/business-centers/${id}/offline`)
  return data
}

export async function updatePageModules(id: string, page_modules: string[]) {
  const { data } = await api.post<BusinessCenter>(`/admin/business-centers/${id}/page-modules`, { page_modules })
  return data
}

export interface SkillInvocation {
  id: string
  trace_id?: string
  task_id: string
  workflow_id?: string
  workflow_version?: number
  node_code: string
  node_label?: string
  skill_code: string
  skill_version?: number
  input_summary?: Record<string, unknown>
  output_summary?: Record<string, unknown>
  status: string
  error_message?: string
  started_at: string
  completed_at?: string
}

export async function getTaskSkillInvocations(taskId: string) {
  const { data } = await api.get<SkillInvocation[]>(`/tasks/${taskId}/skill-invocations`)
  return data
}

export async function getAdminSkillInvocations(params?: { task_id?: string; limit?: number }) {
  const { data } = await api.get<SkillInvocation[]>('/admin/skill-invocations', { params })
  return data
}

export async function getSkillRegistry() {
  const { data } = await api.get<{ registered_codes: string[]; automated_skills: string[]; skills: Array<Record<string, unknown>> }>('/admin/skill-registry')
  return data
}

export async function getAdminSkills() {
  const { data } = await api.get<Array<Record<string, unknown>>>('/admin/skills')
  return data
}

export interface AdminRuleConfig {
  id: string
  rule_type: string
  name: string
  condition?: string
  severity: string
  enabled: boolean
  threshold?: number
  params?: Record<string, unknown>
  version: number
  rule_version_id: string
}

export async function getAdminRules(params?: { rule_version_id?: string }) {
  const { data } = await api.get<AdminRuleConfig[]>('/admin/rule-configs', { params })
  return data
}

export async function getAdminRule(id: string) {
  const { data } = await api.get<AdminRuleConfig>(`/admin/rule-configs/${id}`)
  return data
}

export async function updateAdminRule(id: string, body: Partial<Pick<AdminRuleConfig, 'name' | 'condition' | 'severity' | 'enabled' | 'threshold' | 'params'>>) {
  const { data } = await api.patch<AdminRuleConfig>(`/admin/rule-configs/${id}`, body)
  return data
}

export interface TroubleshootingPattern {
  rule_type: string
  name: string
  condition: string
  severity: string
  threshold?: number
  troubleshooting_steps?: string
  sample_count?: number
}

export interface TroubleshootingPreset {
  title: string
  source_file: string
  extracted_at?: string
  total_patterns: number
  consolidated_rules: TroubleshootingPattern[]
}

export interface WorkflowRuleBind {
  workflow_id: string
  node_id: string
  bound_count: number
  rule_bindings: WorkflowRuleBinding[]
}

export interface OntologyRuleBind {
  bound_count: number
  bindings: Array<{
    ontology_rule_id: string
    rule_config_id: string
    rule_type: string
    name: string
    action: string
    effective_status: string
  }>
  register_entity_key?: string
  message: string
}

export interface RuleImportResult {
  total_patterns: number
  source_file?: string
  ai_enhanced: boolean
  applied: Array<{ rule_id: string; rule_type: string; name: string }>
  consolidated_rules: TroubleshootingPattern[]
  workflow_bind?: WorkflowRuleBind | null
  ontology_bind?: OntologyRuleBind | null
}

export async function getTroubleshootingPreset() {
  const { data } = await api.get<TroubleshootingPreset>('/admin/rule-import/preset')
  return data
}

export async function applyTroubleshootingPreset(ruleVersionId: string, businessCenterId?: string) {
  const { data } = await api.post<RuleImportResult>('/admin/rule-import/apply', {
    rule_version_id: ruleVersionId,
    business_center_id: businessCenterId,
  })
  return data
}

export async function bindRulesToWorkflow(ruleVersionId: string, businessCenterId?: string) {
  const { data } = await api.post<RuleImportResult>('/admin/rule-import/bind-workflow', {
    rule_version_id: ruleVersionId,
    business_center_id: businessCenterId,
  })
  return data
}

/** 将规则引擎当前版本绑定到数据语义 · 领域规则 */
export async function bindRulesToOntology(ruleVersionId: string, businessCenterId?: string) {
  const { data } = await api.post<RuleImportResult>('/admin/rule-import/bind-ontology', {
    rule_version_id: ruleVersionId,
    business_center_id: businessCenterId,
  })
  return data
}

export async function importTroubleshootingExcel(
  file: File,
  opts: {
    rule_version_id: string
    business_center_id?: string
    apply?: boolean
    use_ai?: boolean
  },
) {
  const form = new FormData()
  form.append('file', file)
  form.append('rule_version_id', opts.rule_version_id)
  if (opts.business_center_id) form.append('business_center_id', opts.business_center_id)
  form.append('apply', String(opts.apply !== false))
  form.append('use_ai', String(!!opts.use_ai))
  const { data } = await api.post<RuleImportResult>('/admin/rule-import/excel', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export interface OntologyMapping {
  scenario_title: string
  scenario_summary: string
  mvp_note: string
  data_sources: Array<{
    id: string
    name: string
    system_type: string
    connector: string
    status: string
    role?: string
  }>
  raw_examples: Array<{
    side: string
    title: string
    fields: Array<{ label: string; value: string }>
  }>
  pipeline_steps: Array<{
    step: number
    key: string
    title: string
    subtitle: string
    description: string
  }>
  field_mappings: Array<{
    unified_field: string
    unified_label: string
    sap_field: string
    bank_field: string
    transform?: string
  }>
  object_types: Array<{ source: string; ontology_object: string; identifier_fields: string[] }>
  relationships: Array<{
    from_object: string
    to_object: string
    relation_type: string
    match_keys: string[]
    tolerance: string
  }>
  match_rules: Array<{ name: string; checks: string[]; result_ok: string }>
  demo_field_mappings: Array<Record<string, string>>
  db_mapping_configs: Array<{ id: string; source_field: string; target_field: string; transform_rule?: string; enabled: boolean }>
}

export async function getAdminOntologyMapping() {
  const { data } = await api.get<OntologyMapping>('/admin/ontology-mapping')
  return data
}

export interface FieldMappingRowIn {
  unified_field: string
  unified_label?: string
  business_column?: string
  finance_column?: string
  bank_column?: string
  transform?: string
  enabled?: boolean
}

export interface ReconciliationLaunchOptions {
  mapping_configured: boolean
  mapping_ready: boolean
  hint: string
  datasource_pairs: Array<{
    business_datasource_id: string
    finance_datasource_id: string
    business_name: string
    finance_name: string
    business_row_count?: number
    finance_row_count?: number
    is_default: boolean
    mapping_row_count: number
  }>
  binding?: Record<string, unknown>
}

export async function getReconciliationLaunchOptions(centerCode: string) {
  const { data } = await api.get<ReconciliationLaunchOptions>(
    `/business-centers/${centerCode}/launch-options`,
  )
  return data
}

export async function saveFieldMappings(
  rows: FieldMappingRowIn[],
  opts?: { business_datasource_id?: string; finance_datasource_id?: string },
) {
  const { data } = await api.put<MappingConfigOut[]>('/admin/field-mappings', {
    rows,
    business_datasource_id: opts?.business_datasource_id,
    finance_datasource_id: opts?.finance_datasource_id,
  })
  return data
}

export interface MappingDryRunResult {
  business_profile: string
  finance_profile: string
  business_object: string
  finance_object: string
  mapped_business_rows: number
  mapped_finance_rows: number
  matched_count: number
  match_keys: string[]
  field_mapping_count: number
  match_pairs: Array<Record<string, unknown>>
  unmatched_business: Array<Record<string, unknown>>
  sample_business?: Array<Record<string, unknown>>
  sample_finance?: Array<Record<string, unknown>>
}

export async function dryRunMapping(params?: {
  dataset_id?: string
  business_datasource_id?: string
  finance_datasource_id?: string
}) {
  const { data } = await api.post<MappingDryRunResult>(
    '/admin/mapping-engine/dry-run',
    {},
    { params: params || { dataset_id: 'dataset_fangtai_real' } },
  )
  return data
}

interface MappingConfigOut {
  id: string
  source_field: string
  target_field: string
  transform_rule?: string
  enabled: boolean
}

// ── DataSource CRUD ──

export interface AdminDataSource {
  id: string
  name: string
  system_type: string
  side: string
  file_path: string
  detected_columns: string[] | null
  detected_profile: string | null
  row_count: number
  status: string
  created_at: string
}

export async function getAdminDatasources() {
  const { data } = await api.get<AdminDataSource[]>('/admin/datasources')
  return data
}

export async function uploadDatasource(params: { name: string; system_type: string; side: string; file: File }) {
  const form = new FormData()
  form.append('name', params.name)
  form.append('system_type', params.system_type)
  form.append('side', params.side)
  form.append('file', params.file)
  const { data } = await api.post<AdminDataSource>('/admin/datasources/upload', form)
  return data
}

export interface ExcelDatasourceImportItem {
  name: string
  sheet: string
  row_count: number
  column_count: number
  system_type: string
  side: string
  action: 'created' | 'updated'
}

export interface ExcelDatasourceImportResult {
  filename: string
  sheet_count: number
  imported: ExcelDatasourceImportItem[]
  skipped: Array<{ sheet: string; reason: string }>
  message: string
}

/** 方太 POC Excel：一个文件多 Sheet → 批量注册数据源 */
export async function importDatasourcesFromExcel(file: File) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<ExcelDatasourceImportResult>('/admin/datasources/import-excel', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function deleteDatasource(id: string) {
  await api.delete(`/admin/datasources/${id}`)
}

export interface DataSourcePreview {
  id: string
  name: string
  columns: string[]
  total_rows: number
  rows: Record<string, unknown>[]
}

export interface AutoMapRow {
  unified_field: string
  unified_label: string
  business_column: string | null
  finance_column: string | null
  transform: string
  enabled: boolean
}

export async function autoMapFields(businessColumns: string[], financeColumns: string[]) {
  const { data } = await api.post<{ rows: AutoMapRow[] }>('/admin/auto-map-fields', {
    business_columns: businessColumns,
    finance_columns: financeColumns,
  })
  return data.rows
}

export async function previewDatasource(id: string, limit = 50) {
  const { data } = await api.get<DataSourcePreview>(`/admin/datasources/preview/${id}`, { params: { limit } })
  return data
}

export async function getAdminCases(knowledgeBaseId?: string) {
  const { data } = await api.get<CaseAsset[]>('/admin/cases', {
    params: knowledgeBaseId ? { knowledge_base_id: knowledgeBaseId } : undefined,
  })
  return data
}

export async function uploadKnowledgeExcel(file: File, knowledgeBaseId: string) {
  const form = new FormData()
  form.append('file', file)
  form.append('knowledge_base_id', knowledgeBaseId)
  const { data } = await api.post<KnowledgeUploadResult>('/admin/knowledge/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function getAdminAuditLogs(params?: { object_type?: string; object_id?: string; limit?: number }) {
  const { data } = await api.get<AuditLog[]>('/admin/audit-logs', { params })
  return data
}

export interface AgentChatSettings {
  enabled: boolean
  use_langgraph: boolean
  diff_explain_via_agent: boolean
}

export interface LlmConfig {
  id: string
  provider: string
  base_url: string
  model: string
  use_mock: boolean
  temperature: number
  max_tokens: number
  system_prompt: string
  linked_skill_codes: string[]
  agent_chat: AgentChatSettings
  api_key_set: boolean
  api_key_preview?: string | null
  api_key_source: string
  effective_mode: string
  runtime_ready: boolean
  updated_at?: string | null
  updated_by?: string | null
  model_presets: string[]
}

export async function getAdminLlmConfig() {
  const { data } = await api.get<LlmConfig>('/admin/llm-config')
  return data
}

export async function updateAdminLlmConfig(body: Partial<{
  provider: string
  api_key: string | null
  base_url: string
  model: string
  use_mock: boolean
  temperature: number
  max_tokens: number
  system_prompt: string
  linked_skill_codes: string[]
  agent_chat: Partial<AgentChatSettings>
}>) {
  const { data } = await api.put<LlmConfig>('/admin/llm-config', body)
  return data
}

export async function testAdminLlmConfig() {
  const { data } = await api.post<{ ok: boolean; mode: string; message: string; model?: string; sample_reply?: string }>(
    '/admin/llm-config/test',
  )
  return data
}

export interface RuleOverride {
  rule_type: string
  enabled?: boolean
  threshold?: number
  severity?: string
}

export async function createRuleVersion(body: { description: string; reusable_rule_suggestion: string; source_case_id?: string; rule_overrides?: RuleOverride[] }) {
  const { data } = await api.post<{ rule_version_id: string; version: number; rule_overrides?: RuleOverride[] }>('/admin/rule-configs/new-version', body)
  return data
}

export async function getTasks() {
  const { data } = await api.get<Task[]>('/tasks')
  return data
}

export async function getTask(id: string) {
  const { data } = await api.get<Task>(`/tasks/${id}`)
  return data
}

export async function deleteTask(id: string) {
  await api.delete(`/tasks/${id}`)
}

export async function continueWorkflow(taskId: string) {
  const { data } = await api.post<Task>(`/tasks/${taskId}/continue-workflow`)
  return data
}

export async function resumeTaskExecution(taskId: string) {
  const { data } = await api.post<Task>(`/tasks/${taskId}/resume-execution`)
  return data
}

export interface WorkflowNotification {
  id: string
  user_id: string
  task_id: string
  kind: string
  title: string
  message: string
  read: boolean
  created_at: string
}

export interface LlmStatus {
  runtime_ready: boolean
  use_mock: boolean
  model: string
  effective_mode: string
  api_key_set: boolean
  hint: string
}

export async function getLlmStatus() {
  const { data } = await api.get<LlmStatus>('/dashboard/llm-status')
  return data
}

export async function getNotifications(unreadOnly = false) {
  const { data } = await api.get<WorkflowNotification[]>('/auth/notifications', {
    params: { unread_only: unreadOnly },
  })
  return data
}

export async function markNotificationRead(id: string) {
  const { data } = await api.post<WorkflowNotification>(`/auth/notifications/${id}/read`)
  return data
}

export async function approveTaskReview(taskId: string) {
  const { data } = await api.post<{ task: Task; task_status: string; progress: number; verify_result?: Record<string, unknown> }>(
    `/tasks/${taskId}/approve-review`,
  )
  return data
}

export async function createTask(params: {
  name: string
  period: string
  demo_dataset_id?: string
  business_datasource_id?: string
  finance_datasource_id?: string
  sap?: File
  dms?: File
  fanruan?: File
  combined?: File
}) {
  const form = new FormData()
  form.append('name', params.name)
  form.append('period', params.period)
  form.append('auto_execute', 'true')
  if (params.demo_dataset_id) form.append('demo_dataset_id', params.demo_dataset_id)
  if (params.business_datasource_id) form.append('business_datasource_id', params.business_datasource_id)
  if (params.finance_datasource_id) form.append('finance_datasource_id', params.finance_datasource_id)
  if (params.combined) form.append('combined_file', params.combined)
  if (params.sap) form.append('sap_file', params.sap)
  if (params.dms) form.append('dms_file', params.dms)
  if (params.fanruan) form.append('fanruan_file', params.fanruan)
  const { data } = await api.post<Task>('/tasks', form)
  return data
}

export async function getDifferences(taskId: string) {
  const { data } = await api.get<Difference[]>(`/tasks/${taskId}/differences`)
  return data
}

export async function getTaskAuditLogs(taskId: string) {
  const { data } = await api.get<AuditLog[]>(`/tasks/${taskId}/audit-logs`)
  return data
}

export async function getWorkflowRuns(taskId: string) {
  const { data } = await api.get<Array<Record<string, unknown>>>(`/tasks/${taskId}/workflow-runs`)
  return data
}

export async function reExplainDifference(id: string, preferLlm = false) {
  const { data } = await api.post<Difference>(`/differences/${id}/re-explain`, null, {
    params: preferLlm ? { prefer_llm: true } : undefined,
  })
  return data
}

export async function submitDiffFeedback(
  id: string,
  body: {
    action: 'question' | 'correct'
    reason_category?: string
    reason_text?: string
    corrected_cause?: string
  },
) {
  const { data } = await api.post<Difference>(`/differences/${id}/feedback`, body)
  return data
}

export async function reviewDifference(id: string, decision: string, comment?: string, assignee_id?: string) {
  const { data } = await api.post<Difference>(`/differences/${id}/review`, { decision, comment, assignee_id })
  return data
}

export async function submitProcessing(difference_item_id: string, action_description: string) {
  const { data } = await api.post('/processing-records', { difference_item_id, action_description })
  return data
}

export async function verifyTask(taskId: string, demo_dataset_id = 'dataset_fangtai_real') {
  const form = new FormData()
  form.append('demo_dataset_id', demo_dataset_id)
  const { data } = await api.post(`/tasks/${taskId}/verify`, form)
  return data
}

export async function generateReport(taskId: string, force = false) {
  const { data } = await api.post(`/tasks/${taskId}/report`, null, { params: force ? { force: true } : {} })
  return data
}

export async function closeTask(taskId: string) {
  const { data } = await api.post<Task>(`/tasks/${taskId}/close`)
  return data
}

export async function archiveCase(diffId: string, body: { reusable_rule_suggestion?: string; root_cause?: string; handling_result?: string }) {
  const { data } = await api.post<CaseAsset>(`/differences/${diffId}/archive-case`, body)
  return data
}

export interface ConversationListItem {
  id: string
  task_id?: string
  difference_item_id?: string
  title: string
  preview: string
  updated_at: string
  message_count: number
}

export interface ConversationDetail {
  id: string
  task_id?: string
  difference_item_id?: string
  messages?: Array<{ role: string; content: string; at?: string; ui_blocks?: Array<{ type: string; data: Record<string, unknown> }>; task_id?: string }>
  created_at: string
  updated_at?: string
}

export async function getChatConversations(limit = 30) {
  const { data } = await api.get<ConversationListItem[]>('/chat/conversations', { params: { limit } })
  return data
}

export async function getChatConversation(id: string) {
  const { data } = await api.get<ConversationDetail>(`/chat/conversations/${id}`)
  return data
}

export interface AgentAssetMounts {
  skills: Array<{ id: string; code?: string; name: string; desc?: string; layer: string; type?: string }>
  knowledge_bases: Array<{ id: string; name: string; layer: string }>
  data_sources: Array<{ id: string; name: string; layer: string }>
  ontology: Array<{ id: string; name: string; layer: string }>
  model_route: Record<string, string>
  linked_workflow?: string | null
  linked_workflow_name?: string | null
  note?: string
}

export interface AgentConfigItem {
  id: string
  name: string
  code: string
  description?: string
  persona?: string
  allowed_skill_ids: string[]
  knowledge_scope?: string | null
  knowledge_base_ids?: string[]
  data_source_scope?: string[]
  linked_workflow_id?: string | null
  output_format?: string
  scope?: string
  visibility?: string
  allowed_roles?: string[]
  owner_id?: string | null
  status?: string
  version?: number
  fallback_strategy?: string
  model_route?: Record<string, string>
  is_template?: boolean
  version_history?: Array<{ version: number; saved_at: string; note?: string }>
  asset_mounts?: AgentAssetMounts
  avatar_id?: string
  model_config_json?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export async function listAgents() {
  const { data } = await api.get<AgentConfigItem[]>('/agents')
  return data
}

export async function getAgent(id: string) {
  const { data } = await api.get<AgentConfigItem>(`/agents/${id}`)
  return data
}

export async function createAgent(body: Partial<AgentConfigItem> & { name: string }) {
  const { data } = await api.post<AgentConfigItem>('/agents', body)
  return data
}

export async function updateAgent(id: string, body: Partial<AgentConfigItem> & { publish?: boolean }) {
  const { data } = await api.put<AgentConfigItem>(`/agents/${id}`, body)
  return data
}

export async function listAdminAgents() {
  const { data } = await api.get<AgentConfigItem[]>('/admin/agents')
  return data
}

export async function createAdminAgentTemplate(body: Partial<AgentConfigItem> & { name: string }) {
  const { data } = await api.post<AgentConfigItem>('/admin/agents', body)
  return data
}

export async function updateAdminAgent(id: string, body: Partial<AgentConfigItem> & { publish?: boolean }) {
  const { data } = await api.put<AgentConfigItem>(`/admin/agents/${id}`, body)
  return data
}

export async function deleteAdminAgent(id: string) {
  try {
    const { data } = await api.delete<{ ok: boolean; id: string }>(`/admin/agents/${id}`)
    return data
  } catch (e) {
    const status = (e as { response?: { status?: number } })?.response?.status
    if (status === 405) {
      const { data } = await api.post<{ ok: boolean; id: string }>(`/admin/agents/${id}/delete`)
      return data
    }
    throw e
  }
}

export async function getAdminAgentStats() {
  const { data } = await api.get<{
    total_conversations: number
    total_runs: number
    runs_last_7d: number
    top_intents: Array<{ intent: string; count: number }>
    top_agents: Array<{ agent_id: string; name: string; count: number }>
    ops_metrics?: {
      avg_turns_estimate: number
      success_rate_estimate: number
      skill_call_hotspots: Array<{ skill: string; count: number }>
      agents_by_status: Array<{ status: string; label: string; count: number }>
    }
  }>('/admin/agents/stats/summary')
  return data
}

export async function adminAgentLifecycle(
  agentId: string,
  action: 'publish' | 'offline' | 'submit_review' | 'rollback' | 'duplicate',
  opts?: { gray?: boolean; new_name?: string },
) {
  const { data } = await api.post<AgentConfigItem>(`/admin/agents/${agentId}/lifecycle`, {
    action,
    gray: opts?.gray,
    new_name: opts?.new_name,
  })
  return data
}

export async function getAdminAgentInsights() {
  const { data } = await api.get<{ items: Array<{ type: string; level: string; title: string; detail: string }> }>(
    '/admin/agents/insights',
  )
  return data.items
}

export async function getAdminAgentRunDetail(runId: string) {
  const { data } = await api.get<{
    run: Record<string, unknown>
    conversation_messages: Array<Record<string, unknown>>
  }>(`/admin/agents/runs/${runId}`)
  return data
}

export interface AgentRunSummary {
  id: string
  agent_id: string
  conversation_id?: string
  intent?: string
  user_input: string
  plan_steps?: Array<{ thought?: string; action?: string; observation?: string }>
  skills_called?: string[]
  final_output?: string
  created_at?: string
}

export async function listAdminAgentRuns(limit = 50) {
  const { data } = await api.get<AgentRunSummary[]>('/admin/agents/runs', { params: { limit } })
  return data
}

export async function chatWithContext(body: {
  message: string
  history: Array<{ role: string; content: string }>
  task_id?: string
  difference_item_id?: string
  conversation_id?: string
  agent_id?: string
  client_action?: string
}) {
  const { data } = await api.post<{
    reply: string
    conversation_id?: string
    intent?: string
    ui_blocks?: Array<{ type: string; data: Record<string, unknown> }>
    task_id?: string
    agent_id?: string
    plan_steps?: Array<{ thought: string; action: string; observation: string }>
  }>('/chat', body)
  return data
}

export type ChatReconciliationOptions = {
  systems: Array<Record<string, unknown>>
  recommended: {
    business_datasource_id?: string
    finance_datasource_id?: string
    display_ids?: string[]
  }
  has_datasource_pair: boolean
  has_uploaded_pair?: boolean
  mapping_ready?: boolean
  mapping_hint?: string
  demo_dataset_id: string
}

export async function getChatReconciliationOptions(agentId?: string) {
  const { data } = await api.get<ChatReconciliationOptions>(
    '/chat/reconciliation-options',
    { params: agentId ? { agent_id: agentId } : undefined },
  )
  return data
}

export async function chatImportDatasourcesFromExcel(file: File, agentId?: string) {
  const form = new FormData()
  form.append('file', file)
  if (agentId) form.append('agent_id', agentId)
  const { data } = await api.post<{
    message: string
    bind_message?: string
    import: ExcelDatasourceImportResult
    options: ChatReconciliationOptions
  }>('/chat/datasources/import-excel', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function chatUploadDatasource(file: File, agentId?: string, meta?: {
  name?: string
  system_type?: string
  side?: string
}) {
  const form = new FormData()
  form.append('file', file)
  if (agentId) form.append('agent_id', agentId)
  if (meta?.name) form.append('name', meta.name)
  if (meta?.system_type) form.append('system_type', meta.system_type)
  if (meta?.side) form.append('side', meta.side)
  const { data } = await api.post<{
    datasource_id: string
    name: string
    row_count: number
    options: ChatReconciliationOptions
  }>('/chat/datasources/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function chatConnectDemoDatasources(agentId?: string) {
  const { data } = await api.post<{
    message: string
    options: ChatReconciliationOptions
    seed?: { mapping_ready?: boolean; steps?: string[]; errors?: string[] }
  }>('/chat/datasources/connect-demo', {}, {
    params: agentId ? { agent_id: agentId } : undefined,
  })
  return data
}

export async function chatPreviewDatasource(dsId: string, agentId?: string, limit = 50) {
  const { data } = await api.get<DataSourcePreview>(`/chat/datasources/${dsId}/preview`, {
    params: { limit, ...(agentId ? { agent_id: agentId } : {}) },
  })
  return data
}

export async function chatKnowledgeEntryDetail(caseId: string, agentId?: string) {
  const { data } = await api.get<CaseAsset>(`/chat/knowledge-entries/${caseId}`, {
    params: agentId ? { agent_id: agentId } : undefined,
  })
  return data
}

export interface ChatSkillDetail {
  id: string
  code: string
  name: string
  type: string
  type_label: string
  description: string
  status: string
  version: number
  category?: string | null
  has_executor: boolean
  registry_registered?: boolean
  execution_mode?: string
  execution_label?: string
  input_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
  dependencies?: Record<string, unknown>
  usage_hint?: string
  package_id?: string
}

export async function chatSkillDetail(skillId: string, agentId?: string) {
  const { data } = await api.get<ChatSkillDetail>(`/chat/skills/${encodeURIComponent(skillId)}`, {
    params: agentId ? { agent_id: agentId } : undefined,
  })
  return data
}

export { buildWelcomeCapsBlock } from '../utils/agentChatProfile'

export function datasourceConfirmIntro(period: string) {
  return (
    `好的，已为您准备「${period}」收入核对。请在下方案块确认 SAP / DMS 数据来源与核对周期；`
    + '确认后点击「使用推荐方案进行对账分析」，系统将自动执行字段映射、差异识别与 AI 解释，'
    + '约 1–3 分钟可在对话中查看结果摘要与待复核清单。'
  )
}

export function buildDatasourceConfirmBlock(
  opts: Awaited<ReturnType<typeof getChatReconciliationOptions>>,
  period = '2024-05',
  intro?: string,
  agentId?: string,
) {
  const rec = opts.recommended
  return {
    type: 'datasource_confirm',
    data: {
      period,
      intro: intro || datasourceConfirmIntro(period),
      systems: opts.systems,
      recommended_business_id: rec.business_datasource_id,
      recommended_finance_id: rec.finance_datasource_id,
      recommended_display_ids: rec.display_ids || [],
      has_datasource_pair: opts.has_datasource_pair,
      has_uploaded_pair: opts.has_uploaded_pair,
      mapping_ready: opts.mapping_ready,
      mapping_hint: opts.mapping_hint || '',
      demo_dataset_id: opts.demo_dataset_id,
      agent_id: agentId,
    },
  }
}

export function inferReconciliationPeriod(message: string): string {
  const ymd = message.match(/(20\d{2})[-年/](\d{1,2})/)
  if (ymd) return `${ymd[1]}-${String(Number(ymd[2])).padStart(2, '0')}`
  const m = message.match(/(\d{1,2})\s*月/)
  if (m) return `2024-${String(Number(m[1])).padStart(2, '0')}`
  return '2024-05'
}

/** 是否应弹出「数据来源确认」卡片（仅显式发起核对，避免流程/知识类问题误判） */
export function shouldOfferReconciliationUi(message: string) {
  if (/帮我(核对|对账|查|比对)|发起对账|开始对账|执行核对|核对一下/.test(message)) return true
  if (/(我要|想要|需要|打算).{0,6}(对账|核对)/.test(message)) return true
  if (/^(对账|核对)(一下|吧|呢)?$/.test(message.trim())) return true
  if (/(发起|开始|执行).{0,8}(对账|核对)/.test(message)) return true
  if (/(核对|对账).{0,12}\d{1,2}\s*月/.test(message)) return true
  if (/\d{1,2}\s*月.{0,20}(收入|数据).{0,12}(核对|对账|SAP|DMS)/.test(message)) return true
  if (/(比较|比对).*(SAP|DMS)/.test(message)) return true
  return false
}

/** 后端未返回 difference_explain 块时，用当前差异上下文在前端补全卡片 */
export function buildDifferenceExplainBlockFromDiff(
  task: Task,
  diff: Difference,
  brief?: string,
): { type: 'difference_explain'; data: Record<string, unknown> } {
  const rec = diff.ai_recommendation || {}
  const root = String(rec.root_cause || diff.ai_explanation || brief || '').trim()
  const evidence = Array.isArray(rec.evidence)
    ? rec.evidence.map(String)
    : []
  return {
    type: 'difference_explain',
    data: {
      verified: true,
      source: 'client_fallback',
      difference_id: diff.id,
      task_id: task.id,
      task_name: task.name,
      task_period: task.period || '',
      diff_label: `${diff.id.slice(0, 8)}…`,
      type: diff.type,
      business_key: diff.business_key || '',
      business_amount: diff.business_amount,
      finance_amount: diff.finance_amount,
      amount_diff: diff.amount_diff,
      status: diff.status,
      responsible_party: diff.responsible_party || '待确认',
      root_cause: root,
      evidence,
      suggestion: diff.suggestion || '',
      model: 'rule-engine',
      confidence: diff.confidence ?? 0,
      rule_hits: diff.rule_hits || [],
      workbench_path: `/workbench/reconciliation/tasks/${task.id}`,
    },
  }
}

function insertBlockBeforePlan(
  blocks: Array<{ type: string; data: Record<string, unknown> }>,
  insert: { type: string; data: Record<string, unknown> },
) {
  const plans = blocks.filter((b) => b.type === 'agent_plan')
  const rest = blocks.filter((b) => b.type !== 'agent_plan')
  return [...rest, insert, ...plans]
}

export function ensureDifferenceExplainUiBlocks(
  blocks: Array<{ type: string; data: Record<string, unknown> }> | undefined,
  task: Task | null | undefined,
  diff: Difference | null | undefined,
  brief?: string,
) {
  if (!task || !diff || blocks?.some((b) => b.type === 'difference_explain')) {
    return blocks
  }
  const explain = buildDifferenceExplainBlockFromDiff(task, diff, brief)
  return blocks?.length ? insertBlockBeforePlan(blocks, explain) : [explain]
}

export function buildReconciliationResultBlock(task: Task, diffs: Difference[]) {
  const byType: Record<string, number> = {}
  let totalAmount = 0
  for (const d of diffs) {
    byType[d.type] = (byType[d.type] || 0) + 1
    totalAmount += Math.abs(Number(d.amount_diff) || 0)
  }
  const samples = diffs.slice(0, 5).map((d) => ({
    id: d.id,
    business_key: d.business_key,
    type: d.type,
    amount_diff: d.amount_diff,
    ai_explanation: d.ai_explanation || d.ai_recommendation?.root_cause || '',
    responsible_party: d.responsible_party,
  }))
  return {
    type: 'reconciliation_result',
    data: {
      task_id: task.id,
      task_name: task.name,
      period: task.period,
      total: diffs.length,
      by_type: byType,
      total_difference_amount: totalAmount,
      business_rows: (task.summary?.business_rows as number) ?? undefined,
      finance_rows: (task.summary?.finance_rows as number) ?? undefined,
      samples,
    },
  }
}

export function buildReviewPromptBlock(taskId: string, pendingCount: number) {
  return {
    type: 'review_prompt',
    data: { task_id: taskId, pending_count: pendingCount },
  }
}

export function buildReviewInlineBlock(taskId: string, diff: Difference, index: number, total: number) {
  return {
    type: 'review_inline',
    data: {
      task_id: taskId,
      difference_id: diff.id,
      index,
      total,
      business_key: diff.business_key,
      type: diff.type,
      amount_diff: diff.amount_diff,
      ai_explanation: diff.ai_explanation || diff.ai_recommendation?.root_cause || '',
    },
  }
}

export async function chatExecuteReconciliation(body: {
  conversation_id?: string
  agent_id?: string
  period?: string
  name?: string
  business_datasource_id?: string
  finance_datasource_id?: string
  demo_dataset_id?: string
  use_recommended?: boolean
}) {
  const { data } = await api.post<{
    reply: string
    conversation_id?: string
    ui_blocks?: Array<{ type: string; data: Record<string, unknown> }>
    task_id?: string
  }>('/chat/execute', { action: 'start_reconciliation', ...body })
  return data
}

export function getReportUrl(taskId: string) {
  return `/api/v1/reports/${taskId}`
}

/* ---- Skill Package API ---- */

export interface SkillPackageItem {
  id: string
  code: string
  name: string
  description: string
  type: string
  version: number
  status: string
  creator: string
  has_executor: boolean
  platform_executable?: boolean
  test_count: number
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  config_schema: Record<string, unknown>
  dependencies: Record<string, unknown>
}

export interface SkillPackageDetail extends SkillPackageItem {
  created_at: string
  tests: Array<{ name: string; input: Record<string, unknown>; expected: Record<string, unknown> }>
  skill_md?: string | null
  has_skill_md?: boolean
  sample_input?: Record<string, unknown>
}

export interface SkillExecuteResult {
  success: boolean
  output: Record<string, unknown>
  duration_ms: number
  error: string | null
  skill_code: string
  skill_version: number
}

export interface SkillTestResult {
  name: string
  passed: boolean
  expected: Record<string, unknown>
  actual: Record<string, unknown>
  duration_ms: number
  error: string | null
}

export async function listSkillPackages() {
  const { data } = await api.get<SkillPackageItem[]>('/skill-packages')
  return data
}

export async function getSkillPackage(code: string) {
  const { data } = await api.get<SkillPackageDetail>(`/skill-packages/${code}`)
  return data
}

export async function executeSkillPackage(
  code: string,
  inputData: Record<string, unknown>,
  config?: Record<string, unknown>,
  taskId?: string,
) {
  const { data } = await api.post<SkillExecuteResult>(`/skill-packages/${code}/execute`, {
    input_data: inputData,
    config: config || null,
    task_id: taskId || inputData.task_id || null,
  })
  return data
}

export async function testSkillPackage(code: string) {
  const { data } = await api.post<SkillTestResult[]>(`/skill-packages/${code}/test`)
  return data
}

export interface SkillUploadResult {
  code: string
  name: string
  version: number
  message: string
}

export async function skillPackageLifecycle(
  code: string,
  action: 'submit_review' | 'publish' | 'offline' | 'rollback',
) {
  const { data } = await api.post<{ code: string; status: string; message: string }>(
    `/skill-packages/${encodeURIComponent(code)}/lifecycle`,
    { action },
  )
  return data
}

export async function uploadSkillPackage(file: File) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<SkillUploadResult>('/skill-packages/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

/* ── 企业数据语义层（本体探索） ── */

export interface OntologyApiResponse<T> {
  code: number
  data: T
  message: string
}

export interface OntologyEntityRow {
  id: string
  entity_key: string
  datasource_code: string
  source_type: string
  table_name: string
  label: string
  description?: string
  columns: Array<{
    name: string
    data_type: string
    label?: string
    sample_values?: string[]
    sensitivity?: string
  }>
  aliases: string[]
  domain?: string
  data_sensitivity: string
}

export interface OntologyStats {
  entity_count: number
  column_count: number
  relation_count: number
  rule_count: number
  published_rule_count: number
}

export async function getOntologyStats() {
  const { data } = await api.get<OntologyApiResponse<OntologyStats>>('/admin/ontology/stats')
  return data.data
}

export async function listOntologyEntities(params?: { domain?: string; datasource_code?: string }) {
  const { data } = await api.get<OntologyApiResponse<OntologyEntityRow[]>>('/ontology/entities', { params })
  return data.data
}

export async function listOntologyRelations(from_entity?: string) {
  const { data } = await api.get<OntologyApiResponse<Array<{
    id: string
    from_entity: string
    to_entity: string
    from_column: string
    to_column: string
    description?: string
  }>>>('/ontology/relations', { params: from_entity ? { from_entity } : {} })
  return data.data
}

export interface OntologyDomainRuleRow {
  id: string
  domain?: string
  entity_key?: string
  rule_type: string
  rule_content: string
  effective_status: string
  priority: number
  risk_level?: string
  version?: number
  rule_config_id?: string | null
  bind_source?: string | null
  rule_engine_type?: string | null
  rule_engine_name?: string | null
}

export async function listOntologyRules(params?: { domain?: string; effective_status?: string }) {
  const { data } = await api.get<OntologyApiResponse<OntologyDomainRuleRow[]>>('/ontology/rules', { params })
  return data.data
}

export async function runSemanticsDemoSeed() {
  const { data } = await api.post<{
    ok: boolean
    steps: string[]
    errors: string[]
    mapping_ready: boolean
  }>('/admin/semantics/demo-seed')
  return data
}

export async function reloadOntologyFromFangtai() {
  const { data } = await api.post<OntologyApiResponse<{
    entities_upserted: number
    relations_upserted: number
    rules_upserted: number
    errors: string[]
  }>>('/admin/ontology/reload')
  return data
}

export async function searchOntologySimilar(query: string, top_k = 5) {
  const { data } = await api.post<OntologyApiResponse<Array<{
    entity_key: string
    label: string
    score: number
  }>>>('/ontology/similar', { query, top_k })
  return data.data
}

export interface OntologyGraphPayload {
  nodes: Array<{
    id: string
    label: string
    table_name: string
    datasource_code: string
    description?: string
    column_count?: number
  }>
  edges: Array<{
    id: string
    source: string
    target: string
    from_column: string
    to_column: string
    relation_type?: string
    label?: string
    description?: string
  }>
  layers: Array<{ key: string; title: string; color: string }>
  view: string
}

export async function getOntologyGraph(params?: { domain?: string; view?: 'core' | 'full' }) {
  const { data } = await api.get<OntologyApiResponse<OntologyGraphPayload>>('/ontology/graph', { params })
  return data.data
}

export async function getOntologyPromptPreview(domain = 'revenue_reconciliation') {
  const { data } = await api.get<OntologyApiResponse<{ markdown: string }>>('/ontology/prompt-preview', {
    params: { domain },
  })
  return data.data.markdown
}

export default api
