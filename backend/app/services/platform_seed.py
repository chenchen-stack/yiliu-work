"""Seed MVP platform config, users, and demo business center."""

from __future__ import annotations

import uuid

import yaml
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import CONFIG_DIR
from app.models import (
    AgentConfig,
    BusinessCenter,
    BusinessCenterStatus,
    MappingConfig,
    RuleConfig,
    RuleVersion,
    Skill,
    User,
    UserRole,
    Workflow,
)
from app.services.workflow_engine import WORKFLOW_NODES, WORKFLOW_TRANSITIONS

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEMO_USERS = [
    ("lili", "小李", "finance123", UserRole.FINANCE),
    ("wangzong", "王总", "manager123", UserRole.MANAGER),
    ("ops1", "运营张三", "ops123", UserRole.OPS),
    ("admin", "系统管理员", "admin123", UserRole.ADMIN),
]

# Stable IDs for references across seeds
IDS = {
    "workflow": "wf-revenue-reconciliation-v1",
    "business_center": "bc-revenue-reconciliation",
    "rule_version_v1": "rv-revenue-v1",
    "agent": "agent-revenue-diff-explain",
}


def seed_users(db: Session):
    for username, display_name, password, role in DEMO_USERS:
        if db.query(User).filter(User.username == username).first():
            continue
        db.add(
            User(
                id=str(uuid.uuid4()),
                username=username,
                display_name=display_name,
                password_hash=pwd_context.hash(password),
                role=role.value,
            )
        )
    db.commit()


def seed_platform(db: Session):
    if db.query(BusinessCenter).filter(BusinessCenter.code == "revenue_reconciliation").first():
        return

    skill_defs = [
        ("data_import", "数据导入 Skill", "ability"),
        ("field_mapping", "字段映射 Skill", "ability"),
        ("ontology_context", "实体与规则 Skill", "ability"),
        ("difference_detect", "差异识别 Skill", "ability"),
        ("anomaly_explain", "异常解释 Skill", "knowledge"),
        ("query_tasks", "任务查询 Skill", "ability"),
        ("review_flow", "复核流转 Skill", "process"),
        ("re_verify", "再次验证 Skill", "ability"),
        ("report_gen", "报告生成 Skill", "ability"),
    ]
    skill_ids: list[str] = []
    for code, name, stype in skill_defs:
        sid = f"skill-{code}"
        skill_ids.append(sid)
        db.add(
            Skill(
                id=sid,
                name=name,
                code=code,
                type=stype,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                dependencies=[],
                status="published",
                version=1,
            )
        )

    db.add(
        Workflow(
            id=IDS["workflow"],
            name="收入核对 Workflow",
            code="revenue_reconciliation_flow",
            version=1,
            status="published",
            nodes=WORKFLOW_NODES,
            transitions=WORKFLOW_TRANSITIONS,
        )
    )

    page_modules = [
        "today_summary",
        "create_task",
        "task_batches",
        "difference_handling",
        "pending_review",
        "processing_progress",
        "re_verification",
        "reconciliation_report",
        "audit_trace",
        "audit_trace_skills",
        "audit_trace_workflow",
        "audit_trace_logs",
    ]

    db.add(
        BusinessCenter(
            id=IDS["business_center"],
            name="收入核对中心",
            code="revenue_reconciliation",
            status=BusinessCenterStatus.TESTING.value,
            workflow_id=IDS["workflow"],
            enabled_skill_ids=skill_ids,
            rule_version_id=IDS["rule_version_v1"],
            page_modules=page_modules,
            allowed_roles=["finance", "manager", "ops", "admin"],
            version=1,
        )
    )

    db.add(
        RuleVersion(
            id=IDS["rule_version_v1"],
            business_center_id=IDS["business_center"],
            version=1,
            status="published",
            description="收入核对初始规则版本 v1",
        )
    )

    with open(CONFIG_DIR / "field_mapping.yaml", encoding="utf-8") as f:
        fm = yaml.safe_load(f)
    for std_field, cfg in fm.get("standard_fields", {}).items():
        db.add(
            MappingConfig(
                id=str(uuid.uuid4()),
                business_center_id=IDS["business_center"],
                source_field=cfg.get("sap_field", std_field),
                target_field=std_field,
                transform_rule=f"dms:{cfg.get('dms_field')}, fanruan:{cfg.get('fanruan_field')}",
                version=1,
                enabled=True,
            )
        )

    try:
        from app.services.fangtai_rule_extract import load_preset
        from app.services.rule_import_service import _build_condition, _merge_params

        preset = load_preset()
        rule_defs = []
        for cr in preset.get("consolidated_rules", []):
            base_params = {
                "confidence": 0.95 if cr["rule_type"] == "amount_mismatch" else (1.0 if cr["rule_type"] == "duplicate_record" else 0.85),
                "responsible_party": "finance" if cr["rule_type"] != "mapping_anomaly" else "mdm_team",
            }
            merged = _merge_params(base_params, cr, source_file=preset.get("source_file", "fangtai_preset"))
            rule_defs.append((
                cr["rule_type"],
                cr.get("name", "排查规则"),
                _build_condition(cr),
                cr.get("severity", "high"),
                merged,
                cr.get("threshold") if cr["rule_type"] == "amount_mismatch" else 0.0,
            ))
    except Exception:
        rule_defs = []

    _ensure_rule_types = [
        ("amount_mismatch", "方太·金额差异排查规则", 0.0, "finance", 0.95),
        ("duplicate_record", "方太·重复数据排查规则", 0.0, "finance", 1.0),
        ("mapping_anomaly", "方太·主数据/映射异常排查规则", 0.0, "mdm_team", 0.85),
        ("status_mismatch", "方太·状态不一致排查规则", 0.0, "finance", 0.88),
        ("sync_failure", "方太·接口/同步异常排查规则", 0.0, "business", 0.9),
        ("payment_mismatch", "方太·回款差异排查规则", 0.0, "finance", 0.87),
        ("fanruan_summary", "方太·帆软汇总差异排查规则", 0.01, "finance", 0.92),
    ]
    existing_types = {r[0] for r in rule_defs}
    for rtype, name, threshold, party, conf in _ensure_rule_types:
        if rtype in existing_types:
            continue
        from app.services.rule_import_service import RULE_ENGINE_BASE
        rule_defs.append((
            rtype,
            name,
            RULE_ENGINE_BASE.get(rtype, ""),
            "high" if rtype not in ("duplicate_record",) else "medium",
            {"confidence": conf, "responsible_party": party, "source": "fangtai_registration"},
            threshold,
        ))
    for item in rule_defs:
        if len(item) == 6:
            rtype, name, cond, sev, params, threshold = item
        else:
            rtype, name, cond, sev, params = item
            threshold = 0.0
        db.add(
            RuleConfig(
                id=str(uuid.uuid4()),
                business_center_id=IDS["business_center"],
                rule_version_id=IDS["rule_version_v1"],
                rule_type=rtype,
                name=name,
                condition=cond,
                severity=sev,
                enabled=True,
                threshold=float(threshold or 0),
                params=params,
                version=1,
            )
        )

    db.add(
        AgentConfig(
            id=IDS["agent"],
            name="收入差异解释 Agent",
            code="revenue_diff_explain",
            description="方太财资收入核对分析助手：基于 SAP/DMS 双源数据解释差异、查询任务、对话内发起核对。",
            persona=(
                "你是方太收入核对分析助手（亿流 Work 收入核对中心），"
                "专注 SAP 发货开票与 DMS 收入台账之间的金额差异、重复数据、主数据/映射异常。"
                "用户发起对账时，必须在对话内弹出数据源确认卡片并引导一键执行，"
                "不要仅用一句话让用户自行去工作台。"
            ),
            allowed_skill_ids=["skill-anomaly_explain", "skill-query_tasks"],
            knowledge_scope="revenue_reconciliation",
            knowledge_base_ids=["kb-fangtai-cases", "revenue_reconciliation"],
            data_source_scope=["sap_billing", "dms_ledger"],
            linked_workflow_id=IDS["workflow"],
            output_format="natural",
            prompt_template="基于结构化差异事实、规则命中与证据链，解释异常原因并生成处理说明。",
            model_config_json={
                "model": "mock-ai",
                "temperature": 0.3,
                "fallback_strategy": "ask_user",
                "model_route": {"simple": "mock-ai", "complex": "deepseek-v4-pro"},
            },
            scope="team_published",
            owner_id=None,
            status="published",
            version=1,
        )
    )
    db.commit()


def get_published_business_center(db: Session) -> BusinessCenter | None:
    return (
        db.query(BusinessCenter)
        .filter(BusinessCenter.code == "revenue_reconciliation")
        .first()
    )
