from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: str

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str
    password: str


class BusinessCenterOut(BaseModel):
    id: str
    name: str
    code: str
    status: str
    workflow_id: Optional[str] = None
    enabled_skill_ids: Optional[list] = None
    rule_version_id: Optional[str] = None
    page_modules: Optional[list] = None
    allowed_roles: Optional[list] = None
    version: int

    class Config:
        from_attributes = True


class BusinessCenterDetail(BusinessCenterOut):
    workflow: Optional[dict] = None
    skills: Optional[list] = None
    rule_version: Optional[dict] = None


class WorkflowOut(BaseModel):
    id: str
    name: str
    code: str
    version: int
    status: str
    nodes: Optional[list] = None
    transitions: Optional[list] = None

    class Config:
        from_attributes = True


class WorkflowNodePositionPatch(BaseModel):
    x: float
    y: float


class WorkflowNodePatch(BaseModel):
    id: str
    enabled: Optional[bool] = None
    label: Optional[str] = None
    position: Optional[WorkflowNodePositionPatch] = None


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    nodes: Optional[list[WorkflowNodePatch]] = None
    node_order: Optional[list[str]] = None


class SkillOut(BaseModel):
    id: str
    name: str
    code: str
    type: str
    status: str
    version: int

    class Config:
        from_attributes = True


class RuleConfigOut(BaseModel):
    id: str
    rule_type: str
    name: str
    condition: Optional[str] = None
    severity: str
    enabled: bool
    threshold: Optional[float] = 0
    params: Optional[dict] = None
    version: int
    rule_version_id: str

    class Config:
        from_attributes = True


class RuleConfigUpdate(BaseModel):
    name: Optional[str] = None
    condition: Optional[str] = None
    severity: Optional[str] = None
    enabled: Optional[bool] = None
    threshold: Optional[float] = None
    params: Optional[dict] = None


class TroubleshootingPatternOut(BaseModel):
    rule_type: str
    name: str
    condition: str
    severity: str
    threshold: Optional[float] = None
    troubleshooting_steps: str = ""
    sample_count: int = 0


class TroubleshootingPresetOut(BaseModel):
    title: str
    source_file: str
    extracted_at: Optional[str] = None
    total_patterns: int
    consolidated_rules: list[TroubleshootingPatternOut]


class WorkflowRuleBindOut(BaseModel):
    workflow_id: str
    node_id: str = "detect"
    bound_count: int = 0
    rule_bindings: list[dict] = []


class OntologyRuleBindOut(BaseModel):
    bound_count: int = 0
    bindings: list[dict] = []
    register_entity_key: Optional[str] = None
    message: str = ""


class RuleImportResultOut(BaseModel):
    total_patterns: int
    source_file: Optional[str] = None
    ai_enhanced: bool = False
    applied: list[dict] = []
    consolidated_rules: list[TroubleshootingPatternOut] = []
    workflow_bind: Optional[WorkflowRuleBindOut] = None
    ontology_bind: Optional[OntologyRuleBindOut] = None


class ApplyTroubleshootingPresetIn(BaseModel):
    rule_version_id: str
    business_center_id: Optional[str] = None


class MappingConfigOut(BaseModel):
    id: str
    source_field: str
    target_field: str
    transform_rule: Optional[str] = None
    enabled: bool

    class Config:
        from_attributes = True


class FieldMappingRowIn(BaseModel):
    unified_field: str
    unified_label: Optional[str] = None
    business_column: Optional[str] = None
    finance_column: Optional[str] = None
    bank_column: Optional[str] = None
    transform: Optional[str] = "rename"
    enabled: bool = True


class FieldMappingsSave(BaseModel):
    rows: list[FieldMappingRowIn]
    business_datasource_id: Optional[str] = None
    finance_datasource_id: Optional[str] = None


class DatasourcePairOut(BaseModel):
    business_datasource_id: str
    finance_datasource_id: str
    business_name: str
    finance_name: str
    business_row_count: Optional[int] = None
    finance_row_count: Optional[int] = None
    is_default: bool = True
    mapping_row_count: int = 0


class ReconciliationLaunchOptionsOut(BaseModel):
    mapping_configured: bool = False
    mapping_ready: bool = False
    hint: str = ""
    datasource_pairs: list[DatasourcePairOut] = []
    binding: Optional[dict] = None


class MappingDryRunOut(BaseModel):
    business_profile: str
    finance_profile: str
    business_object: str
    finance_object: str
    mapped_business_rows: int
    mapped_finance_rows: int
    matched_count: int
    match_keys: list[str]
    field_mapping_count: int
    match_pairs: list[dict]
    unmatched_business: list[dict]
    sample_business: list[dict] = []
    sample_finance: list[dict] = []


class TaskOut(BaseModel):
    id: str
    business_center_id: Optional[str] = None
    name: str
    period: Optional[str] = None
    status: str
    progress: int
    creator_id: str
    initiator: Optional[str] = None
    workflow_version: Optional[int] = None
    rule_version_id: Optional[str] = None
    demo_dataset_id: Optional[str] = None
    summary: Optional[dict] = None
    error_message: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DifferenceOut(BaseModel):
    id: str
    task_id: str
    business_key: Optional[str] = None
    type: str
    difference_type: Optional[str] = None
    business_amount: Optional[float] = None
    finance_amount: Optional[float] = None
    amount_diff: Optional[float] = None
    confidence: float
    status: str
    review_decision: Optional[str] = None
    responsible_party: Optional[str] = None
    assignee_id: Optional[str] = None
    sap_record: Optional[dict] = None
    dms_record: Optional[dict] = None
    statement_record: Optional[dict] = None
    rule_hits: Optional[list] = None
    evidence: Optional[dict] = None
    ai_recommendation: Optional[dict] = None
    ai_explanation: Optional[str] = None
    suggestion: Optional[str] = None
    risk_level: Optional[str] = None
    evidence_chain: Optional[list] = None
    review_comment: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(confirm|reject|assign|comment)$")
    comment: Optional[str] = None
    assignee_id: Optional[str] = None
    responsible_party: Optional[str] = None


class DiffFeedbackRequest(BaseModel):
    """用户对 AI 归因的质疑或修正（写入复核意见并留痕）。"""
    action: str = Field(..., pattern="^(question|correct)$")
    reason_category: Optional[str] = None
    reason_text: Optional[str] = None
    corrected_cause: Optional[str] = None


class ProcessingRecordCreate(BaseModel):
    difference_item_id: str
    action_description: str
    attachment: Optional[str] = None


class ProcessingRecordOut(BaseModel):
    id: str
    difference_item_id: str
    assignee: str
    action_description: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class VerificationRecordOut(BaseModel):
    id: str
    difference_item_id: str
    task_id: str
    verification_result: str
    remaining_difference: Optional[float] = None
    verified_by: str
    verified_at: datetime

    class Config:
        from_attributes = True


class CaseAssetOut(BaseModel):
    id: str
    source_task_id: str
    source_difference_id: str
    confirmed_type: str
    root_cause: Optional[str] = None
    handling_result: Optional[str] = None
    reusable_rule_suggestion: Optional[str] = None
    status: str
    knowledge_base_id: Optional[str] = None
    source_kind: Optional[str] = "diff_archive"
    source_file: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class KnowledgeUploadResultOut(BaseModel):
    knowledge_base_id: str
    source_file: str
    entries_created: int
    total_patterns: int
    title: Optional[str] = None


class CaseAssetCreate(BaseModel):
    root_cause: Optional[str] = None
    handling_result: Optional[str] = None
    reusable_rule_suggestion: Optional[str] = None


class RuleOverride(BaseModel):
    rule_type: str
    enabled: Optional[bool] = None
    threshold: Optional[float] = None
    severity: Optional[str] = None


class RuleVersionCreate(BaseModel):
    description: str
    reusable_rule_suggestion: str
    source_case_id: Optional[str] = None
    # 可选：对指定规则类型的阈值 / 启停 / 严重度做调整，使新版本真实改变检测行为
    rule_overrides: Optional[list[RuleOverride]] = None


class AuditLogOut(BaseModel):
    id: str
    trace_id: Optional[str] = None
    object_type: str
    object_id: str
    action: str
    operator: Optional[str] = None
    before_data: Optional[dict] = None
    after_data: Optional[dict] = None
    detail: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WorkflowRunOut(BaseModel):
    id: str
    node_id: str
    node_label: str
    status: str
    detail: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SkillInvocationOut(BaseModel):
    id: str
    trace_id: Optional[str] = None
    task_id: str
    workflow_id: Optional[str] = None
    workflow_version: Optional[int] = None
    node_code: str
    node_label: Optional[str] = None
    skill_code: str
    skill_version: Optional[int] = None
    input_summary: Optional[dict] = None
    output_summary: Optional[dict] = None
    status: str
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReportOut(BaseModel):
    id: str
    task_id: str
    report_type: str
    file_url: str
    generated_at: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    period_tasks: int
    difference_count: int
    difference_amount: float
    pending_review_count: int
    closed_count: int
    pending_tasks: int = 0
    reviewing_tasks: int = 0
    completed_tasks: int = 0
    pending_reviews: int = 0
    total_differences: int = 0


class WorkflowNotificationOut(BaseModel):
    id: str
    user_id: str
    task_id: str
    kind: str
    title: str
    message: str
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class DemoDatasetOut(BaseModel):
    id: str
    name: str
    description: str
    expected: Optional[dict] = None


class ConversationOut(BaseModel):
    id: str
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    difference_item_id: Optional[str] = None
    messages: Optional[list] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConversationListItem(BaseModel):
    id: str
    task_id: Optional[str] = None
    difference_item_id: Optional[str] = None
    title: str
    preview: str
    updated_at: datetime
    message_count: int = 0


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    task_id: Optional[str] = None
    difference_item_id: Optional[str] = None
    conversation_id: Optional[str] = None
    agent_id: Optional[str] = None
    client_action: Optional[str] = None  # start_reconciliation


class ChatResponse(BaseModel):
    reply: str
    intent: str | None = None
    conversation_id: str | None = None
    ui_blocks: list[dict] = []
    task_id: str | None = None
    agent_id: Optional[str] = None
    plan_steps: list[dict] = []


class ChatExecuteRequest(BaseModel):
    action: str = "start_reconciliation"
    conversation_id: str | None = None
    agent_id: str | None = None
    period: str = "2024-05"
    name: str | None = None
    business_datasource_id: str | None = None
    finance_datasource_id: str | None = None
    demo_dataset_id: str | None = None
    use_recommended: bool = True


class DataSourceItemOut(BaseModel):
    id: str
    name: str
    system_type: str
    connector: str
    status: str
    role: Optional[str] = None


class DataSourceOut(BaseModel):
    id: str
    name: str
    system_type: str
    side: str
    file_path: str
    detected_columns: Optional[list] = None
    detected_profile: Optional[str] = None
    row_count: int = 0
    status: str = "active"
    created_at: datetime

    class Config:
        from_attributes = True


class RawExampleFieldOut(BaseModel):
    label: str
    value: str


class RawExampleOut(BaseModel):
    side: str
    title: str
    fields: list[RawExampleFieldOut]


class PipelineStepOut(BaseModel):
    step: int
    key: str
    title: str
    subtitle: str
    description: str


class RevenueFieldMappingOut(BaseModel):
    unified_field: str
    unified_label: str
    sap_field: str
    bank_field: str
    transform: Optional[str] = None


class ObjectTypeOut(BaseModel):
    source: str
    ontology_object: str
    identifier_fields: list[str]


class RelationshipOut(BaseModel):
    from_object: str
    to_object: str
    relation_type: str
    match_keys: list[str]
    tolerance: str


class MatchRuleOut(BaseModel):
    name: str
    checks: list[str]
    result_ok: str


class OntologyMappingOut(BaseModel):
    scenario_title: str
    scenario_summary: str
    mvp_note: str
    data_sources: list[DataSourceItemOut]
    raw_examples: list[RawExampleOut]
    pipeline_steps: list[PipelineStepOut]
    field_mappings: list[RevenueFieldMappingOut]
    object_types: list[ObjectTypeOut]
    relationships: list[RelationshipOut]
    match_rules: list[MatchRuleOut]
    demo_field_mappings: list[dict] = []
    db_mapping_configs: list[MappingConfigOut] = []


class AgentChatSettingsOut(BaseModel):
    enabled: bool = True
    use_langgraph: bool = False
    diff_explain_via_agent: bool = True


class LlmConfigOut(BaseModel):
    id: str
    provider: str
    base_url: str
    model: str
    use_mock: bool
    temperature: float
    max_tokens: int
    system_prompt: str
    linked_skill_codes: list[str]
    agent_chat: AgentChatSettingsOut = Field(default_factory=AgentChatSettingsOut)
    api_key_set: bool
    api_key_preview: Optional[str] = None
    api_key_source: str
    effective_mode: str
    runtime_ready: bool
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    model_presets: list[str] = []


class LlmConfigUpdate(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    use_mock: Optional[bool] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    system_prompt: Optional[str] = None
    linked_skill_codes: Optional[list[str]] = None
    agent_chat: Optional[AgentChatSettingsOut] = None


class LlmStatusOut(BaseModel):
    """前台差异解释等能力可读的大模型就绪状态（不含密钥）。"""
    runtime_ready: bool
    use_mock: bool
    model: str
    effective_mode: str
    api_key_set: bool
    hint: str = ""


class LlmConfigTestResult(BaseModel):
    ok: bool
    mode: str
    message: str
    model: Optional[str] = None
    sample_reply: Optional[str] = None


TokenResponse.model_rebuild()
