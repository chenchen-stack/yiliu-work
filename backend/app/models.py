import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TaskStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PENDING_REVIEW = "pending_review"
    PROCESSING = "processing"
    PENDING_VERIFICATION = "pending_verification"
    REPORTING = "reporting"
    CLOSED = "closed"
    FAILED = "failed"


class DifferenceStatus(str, enum.Enum):
    IDENTIFIED = "identified"
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    ASSIGNED = "assigned"
    PROCESSING = "processing"
    PENDING_VERIFICATION = "pending_verification"
    RESOLVED = "resolved"
    RETURNED = "returned"
    CLOSED = "closed"


class DifferenceType(str, enum.Enum):
    AMOUNT_MISMATCH = "金额差异"
    DUPLICATE_RECORD = "重复数据"
    MAPPING_ANOMALY = "主数据/映射异常"
    STATUS_MISMATCH = "状态不一致"
    SYNC_FAILURE = "接口/同步异常"
    PAYMENT_MISMATCH = "回款差异"
    FANRUAN_SUMMARY = "帆软汇总差异"


class ReviewActionType(str, enum.Enum):
    CONFIRM = "confirm"
    REJECT = "reject"
    ASSIGN = "assign"
    COMMENT = "comment"


class BusinessCenterStatus(str, enum.Enum):
    DRAFT = "draft"
    TESTING = "testing"
    PUBLISHED = "published"
    OFFLINE = "offline"


class AssetStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class UserRole(str, enum.Enum):
    FINANCE = "finance"
    MANAGER = "manager"
    OPS = "ops"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.FINANCE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BusinessCenter(Base):
    __tablename__ = "business_centers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=BusinessCenterStatus.DRAFT.value)
    workflow_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workflows.id"), nullable=True)
    enabled_skill_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rule_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    page_modules: Mapped[list | None] = mapped_column(JSON, nullable=True)
    allowed_roles: Mapped[list | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    nodes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    transitions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(20))
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dependencies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="published")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RuleVersion(Base):
    __tablename__ = "rule_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_center_id: Mapped[str] = mapped_column(String(36), ForeignKey("business_centers.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="published")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    system_type: Mapped[str] = mapped_column(String(50))
    side: Mapped[str] = mapped_column(String(20), default="business")
    file_path: Mapped[str] = mapped_column(String(500))
    detected_columns: Mapped[list | None] = mapped_column(JSON, nullable=True)
    detected_profile: Mapped[str | None] = mapped_column(String(50), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MappingConfig(Base):
    __tablename__ = "mapping_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_center_id: Mapped[str] = mapped_column(String(36), ForeignKey("business_centers.id"))
    source_field: Mapped[str] = mapped_column(String(100))
    target_field: Mapped[str] = mapped_column(String(100))
    transform_rule: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(default=True)


class RuleConfig(Base):
    __tablename__ = "rule_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_center_id: Mapped[str] = mapped_column(String(36), ForeignKey("business_centers.id"))
    rule_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("rule_versions.id"))
    rule_type: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    enabled: Mapped[bool] = mapped_column(default=True)
    # 金额差异容差阈值：|business-finance| <= threshold 视为不计差异（默认 0 = 严格相等）
    threshold: Mapped[float] = mapped_column(Float, default=0.0)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_skill_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    knowledge_scope: Mapped[str | None] = mapped_column(String(200), nullable=True)
    knowledge_base_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    data_source_scope: Mapped[list | None] = mapped_column(JSON, nullable=True)
    linked_workflow_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workflows.id"), nullable=True)
    output_format: Mapped[str] = mapped_column(String(30), default="natural")
    prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scope: Mapped[str] = mapped_column(String(30), default="team_published")
    owner_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="published")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentRun(Base):
    """对话 Agent 单次执行的规划与审计记录。"""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=True, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_configs.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    user_input: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan_steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    final_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills_called: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LlmConfig(Base):
    """平台级大模型配置（异常解释等 Skill 运行时读取）。"""

    __tablename__ = "llm_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), default="deepseek")
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), default="https://api.deepseek.com")
    model: Mapped[str] = mapped_column(String(100), default="deepseek-v4-pro")
    use_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_skill_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    agent_chat_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    business_center_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("business_centers.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    period: Mapped[str | None] = mapped_column(String(50), nullable=True)
    initiator: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=TaskStatus.DRAFT.value)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    creator_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    business_input_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    finance_input_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    statement_input_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_sources: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    demo_dataset_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    creator: Mapped["User"] = relationship("User")
    differences: Mapped[list["Difference"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class Difference(Base):
    __tablename__ = "differences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    business_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    type: Mapped[str] = mapped_column(String(50))
    difference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    business_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    finance_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_diff: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default=DifferenceStatus.IDENTIFIED.value)
    review_decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    responsible_party: Mapped[str | None] = mapped_column(String(50), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sap_record: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dms_record: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    statement_record: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rule_hits: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_recommendation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    evidence_chain: Mapped[list | None] = mapped_column(JSON, nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped["Task"] = relationship(back_populates="differences")


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    difference_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("differences.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProcessingRecord(Base):
    __tablename__ = "processing_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    difference_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("differences.id"), index=True)
    assignee: Mapped[str] = mapped_column(String(36))
    action_description: Mapped[str] = mapped_column(Text)
    attachment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VerificationRecord(Base):
    __tablename__ = "verification_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    difference_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("differences.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    verification_result: Mapped[str] = mapped_column(String(30))
    remaining_difference: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified_by: Mapped[str] = mapped_column(String(36))
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    report_type: Mapped[str] = mapped_column(String(50))
    file_url: Mapped[str] = mapped_column(String(500))
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    workflow_id: Mapped[str] = mapped_column(String(36))
    node_id: Mapped[str] = mapped_column(String(50))
    node_label: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30))
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SkillInvocation(Base):
    """每次 Workflow 节点经 SkillRegistry 调度真实 Skill handler 的运行记录。"""

    __tablename__ = "skill_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_code: Mapped[str] = mapped_column(String(50))
    node_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    skill_code: Mapped[str] = mapped_column(String(50))
    skill_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    object_type: Mapped[str] = mapped_column(String(50))
    object_id: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50))
    operator: Mapped[str | None] = mapped_column(String(100), nullable=True)
    before_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # legacy compat fields
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


class CaseAsset(Base):
    __tablename__ = "case_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_task_id: Mapped[str] = mapped_column(String(36))
    source_difference_id: Mapped[str] = mapped_column(String(36))
    confirmed_type: Mapped[str] = mapped_column(String(50))
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    handling_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    reusable_rule_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=AssetStatus.PUBLISHED.value)
    knowledge_base_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    source_kind: Mapped[str] = mapped_column(String(20), default="diff_archive")
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    difference_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    messages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowNotification(Base):
    """复核流转等 Workflow 节点触发的站内待办通知。"""

    __tablename__ = "workflow_notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50), default="review_pending")
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
