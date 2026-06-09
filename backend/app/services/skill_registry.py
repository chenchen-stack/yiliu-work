"""SkillRegistry — 将 Workflow 节点的 skill_code 映射到真实可执行 handler。

设计原则（与审计报告 §9 对齐）：
- 复用现有 Python 服务函数作为 handler，不重写业务逻辑；
- Workflow.nodes 中的 skill_code 是唯一调度入口，引擎不得再硬编码 import 具体函数；
- 每个 handler 接收统一的 SkillContext，返回 output_summary（用于 SkillInvocation 审计）；
- 缺失 / 未启用的 Skill 必须显式抛错，由引擎记录失败并中止任务。
"""

from __future__ import annotations

from typing import Any, Callable

from app.services.ai_analyzer import analyze_difference, build_evidence_chain
from app.services.data_loader import dataframe_to_records, is_multi_sheet_excel, load_dataframe
from app.services.mapping_engine import (
    MappingRegistry,
    aggregate_records,
    detect_data_profile,
    enrich_records,
    get_poc_profile,
    load_and_translate_file,
    run_mapping_pipeline,
    split_combined_excel,
    translate_dataframe,
)
from app.services.difference_detector import detect_differences


class SkillExecutionError(Exception):
    """Skill 执行期可预期错误（缺失依赖、数据非法等）。"""


class SkillContext:
    """在一次 Workflow 运行内，跨节点共享的可变执行上下文。"""

    def __init__(self, *, db, task, file_paths: dict[str, str], rules: list[dict], ai_mode: str):
        self.db = db
        self.task = task
        self.file_paths = file_paths
        self.rules = rules
        self.ai_mode = ai_mode
        # 跨节点累积状态
        self.business_records: list[dict] = []
        self.finance_records: list[dict] = []
        self.statement_records: list[dict] = []
        self.payment_records: list[dict] = []
        self.sap_settlement_records: list[dict] = []
        self.raw_diffs: list[dict] = []
        # 供引擎在 detect / ai_explain 节点回调写库与审计
        self.on_rule_hit: Callable[[dict], None] | None = None
        self.on_difference_built: Callable[[dict, dict, list], None] | None = None
        self.business_profile: str = "sap"
        self.finance_profile: str = "dms"
        self.mapping_report: dict | None = None
        self.mapping_registry: MappingRegistry | None = None
        self.ontology_context: dict[str, Any] | None = None


def _load_records(path: str | None, side: str, registry: MappingRegistry) -> tuple[list[dict], str]:
    if not path:
        return [], "unknown"
    return load_and_translate_file(path, side, registry)


# ---- Handlers ----------------------------------------------------------------

def _try_combined_import(ctx: SkillContext) -> dict[str, Any] | None:
    """检测是否有多 Sheet Excel 文件，若有则自动拆分到各数据槽位。"""
    fp = ctx.file_paths
    combined_path = fp.get("combined")
    candidates = [
        fp.get("business"), fp.get("sap"),
        fp.get("finance"), fp.get("dms"),
    ]
    if not combined_path:
        for p in candidates:
            if p and is_multi_sheet_excel(p):
                combined_path = p
                break
    if not combined_path:
        return None

    bc_id = getattr(ctx.task, "business_center_id", None) or ""
    ctx.mapping_registry = MappingRegistry.load(ctx.db, bc_id)
    slot_data = split_combined_excel(combined_path, ctx.mapping_registry)

    if "business" not in slot_data or "finance" not in slot_data:
        return None

    ctx.business_records, ctx.business_profile = slot_data["business"]
    ctx.finance_records, ctx.finance_profile = slot_data["finance"]
    if "statement" in slot_data:
        ctx.statement_records = slot_data["statement"][0]
    if "payment" in slot_data:
        ctx.payment_records = slot_data["payment"][0]
    if "sap_settlement" in slot_data:
        ctx.sap_settlement_records = slot_data["sap_settlement"][0]

    return {
        "mode": "combined_multi_sheet",
        "source_file": str(combined_path),
        "business_rows": len(ctx.business_records),
        "finance_rows": len(ctx.finance_records),
        "statement_rows": len(ctx.statement_records),
        "payment_rows": len(ctx.payment_records),
        "sap_settlement_rows": len(ctx.sap_settlement_records),
        "business_profile": ctx.business_profile,
        "finance_profile": ctx.finance_profile,
        "slots_loaded": list(slot_data.keys()),
    }


def skill_data_import(ctx: SkillContext) -> dict[str, Any]:
    combined_result = _try_combined_import(ctx)
    if combined_result:
        return combined_result

    fp = ctx.file_paths
    business_path = fp.get("business") or fp.get("sap")
    finance_path = fp.get("finance") or fp.get("dms")
    statement_path = fp.get("statement") or fp.get("fanruan")
    if not business_path or not finance_path:
        raise SkillExecutionError("缺少业务侧或财务侧数据文件，无法执行数据导入")
    bc_id = getattr(ctx.task, "business_center_id", None) or ""
    ctx.mapping_registry = MappingRegistry.load(ctx.db, bc_id)
    biz, biz_prof = _load_records(business_path, "business", ctx.mapping_registry)
    fin, fin_prof = _load_records(finance_path, "finance", ctx.mapping_registry)
    ctx.business_records = biz
    ctx.finance_records = fin
    ctx.business_profile = biz_prof
    ctx.finance_profile = fin_prof
    stmt_prof = "fanruan"
    if statement_path:
        df = load_dataframe(statement_path)
        stmt_prof = detect_data_profile(df)
        prof = stmt_prof if stmt_prof not in ("unknown", "fanruan") else "fanruan_platform"
        stmt_df = translate_dataframe(df, prof, ctx.mapping_registry)
        ctx.statement_records = dataframe_to_records(stmt_df)
    else:
        ctx.statement_records = []

    payment_path = fp.get("payment") or fp.get("dms_payment")
    if payment_path:
        pdf = load_dataframe(payment_path)
        pprof = detect_data_profile(pdf)
        ctx.payment_records = dataframe_to_records(
            translate_dataframe(pdf, pprof if pprof != "unknown" else "dms_revenue_ledger", ctx.mapping_registry)
        )
    settlement_path = fp.get("sap_settlement")
    if settlement_path:
        sdf = load_dataframe(settlement_path)
        ctx.sap_settlement_records = dataframe_to_records(translate_dataframe(sdf, "sap_billing_detail", ctx.mapping_registry))

    return {
        "business_rows": len(ctx.business_records),
        "finance_rows": len(ctx.finance_records),
        "statement_rows": len(ctx.statement_records),
        "payment_rows": len(ctx.payment_records),
        "sap_settlement_rows": len(ctx.sap_settlement_records),
        "business_profile": ctx.business_profile,
        "finance_profile": ctx.finance_profile,
    }


def skill_field_mapping(ctx: SkillContext) -> dict[str, Any]:
    registry = ctx.mapping_registry or MappingRegistry.load(
        ctx.db, getattr(ctx.task, "business_center_id", None) or ""
    )
    ctx.business_records = enrich_records(ctx.business_records, ctx.business_profile, registry)
    ctx.finance_records = enrich_records(ctx.finance_records, ctx.finance_profile, registry)
    report = run_mapping_pipeline(
        ctx.business_records,
        ctx.finance_records,
        business_profile=ctx.business_profile,
        finance_profile=ctx.finance_profile,
        registry=registry,
    )
    ctx.mapping_report = report
    # 差异识别使用与映射一致的聚合后记录
    for side, profile in (("business", ctx.business_profile), ("finance", ctx.finance_profile)):
        cfg = get_poc_profile(profile) or {}
        if not cfg.get("aggregate_by"):
            continue
        records = aggregate_records(
            ctx.business_records if side == "business" else ctx.finance_records,
            cfg["aggregate_by"],
            amount_field=cfg.get("amount_field", "sales_amount"),
        )
        records = enrich_records(records, profile, registry)
        if side == "business":
            ctx.business_records = records
        else:
            ctx.finance_records = records
    return report


def skill_ontology_context(ctx: SkillContext) -> dict[str, Any]:
    """加载已发布本体与领域规则摘要，供差异识别与异常解释引用（不搬数据、不产出差异）。"""
    from app.ontology_models import OntologyDomainRule, OntologyEntity, OntologyRelation

    db = ctx.db
    entity_count = db.query(OntologyEntity).filter(OntologyEntity.status == 1).count()
    relation_count = db.query(OntologyRelation).filter(OntologyRelation.status == 1).count()
    rule_count = db.query(OntologyDomainRule).filter(OntologyDomainRule.status == 1).count()
    published_rule_count = (
        db.query(OntologyDomainRule)
        .filter(OntologyDomainRule.status == 1, OntologyDomainRule.effective_status == "PUBLISHED")
        .count()
    )
    if entity_count <= 0:
        raise SkillExecutionError(
            "语义层未配置实体，请先在管理后台「数据语义 → 实体与规则」维护或从样本抽取"
        )

    payload = {
        "ready": True,
        "entity_count": entity_count,
        "relation_count": relation_count,
        "rule_count": rule_count,
        "published_rule_count": published_rule_count,
        "mode": "semantic_context_load",
    }
    ctx.ontology_context = payload
    summary = dict(ctx.task.summary or {})
    summary["ontology_context"] = payload
    ctx.task.summary = summary
    return payload


def skill_difference_detect(ctx: SkillContext) -> dict[str, Any]:
    ctx.raw_diffs = detect_differences(
        ctx.business_records,
        ctx.finance_records,
        ctx.statement_records,
        ctx.rules,
        mapping_report=ctx.mapping_report,
        payment_records=ctx.payment_records,
        sap_settlement_records=ctx.sap_settlement_records,
    )
    if ctx.on_rule_hit:
        for item in ctx.raw_diffs:
            ctx.on_rule_hit(item)
    by_type: dict[str, int] = {}
    for d in ctx.raw_diffs:
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1
    enabled = [r for r in (ctx.rules or []) if r.get("enabled", True)]
    rule_names = [r.get("name") or r.get("rule_type") for r in enabled]
    return {
        "count": len(ctx.raw_diffs),
        "by_type": by_type,
        "rules_applied": len(enabled),
        "rule_names": rule_names,
    }


async def skill_anomaly_explain(ctx: SkillContext) -> dict[str, Any]:
    explained = 0
    total = max(len(ctx.raw_diffs), 1)
    for item in ctx.raw_diffs:
        recommendation = await analyze_difference(item, db=ctx.db, task=ctx.task)
        evidence = build_evidence_chain(item, recommendation)
        if ctx.on_difference_built:
            ctx.on_difference_built(item, recommendation, evidence)
        explained += 1
        if ctx.task and ctx.db:
            ctx.task.progress = 55 + int(25 * explained / total)
            ctx.db.commit()
    return {"explained": explained, "ai_mode": ctx.ai_mode}


# 复核 / 验证 / 报告 / 案例 等节点为人工或 API 触发，仍登记到注册表用于
# 资产清单展示与（在对应 API 中）SkillInvocation 记录。
def _manual_gate(ctx: SkillContext) -> dict[str, Any]:  # noqa: ARG001
    return {"mode": "manual_or_api_triggered"}


def skill_query_tasks(ctx: SkillContext) -> dict[str, Any]:
    """对话侧可调用的任务查询 Skill — 查询当前用户的任务列表。"""
    from app.models import Task as TaskModel

    user_id = getattr(ctx.task, "creator_id", None) or ""
    if user_id:
        tasks = ctx.db.query(TaskModel).filter(
            TaskModel.creator_id == user_id,
        ).order_by(TaskModel.updated_at.desc()).limit(10).all()
    else:
        tasks = ctx.db.query(TaskModel).order_by(
            TaskModel.updated_at.desc(),
        ).limit(10).all()

    from app.services.task_display import dedupe_tasks_for_display

    deduped = dedupe_tasks_for_display(tasks)
    return {
        "total": len(deduped),
        "tasks": [
            {
                "id": t.id,
                "name": t.name,
                "status": t.status,
                "progress": t.progress,
                "period": t.period,
            }
            for t in deduped
        ],
    }


# skill_code -> (handler, is_async)
_REGISTRY: dict[str, tuple[Callable, bool]] = {
    "data_import": (skill_data_import, False),
    "field_mapping": (skill_field_mapping, False),
    "ontology_context": (skill_ontology_context, False),
    "difference_detect": (skill_difference_detect, False),
    "anomaly_explain": (skill_anomaly_explain, True),
    "query_tasks": (skill_query_tasks, False),
    "review_flow": (_manual_gate, False),
    "re_verify": (_manual_gate, False),
    "report_gen": (_manual_gate, False),
    "report_generate": (_manual_gate, False),
    "processing_feedback": (_manual_gate, False),
    "case_archive": (_manual_gate, False),
}

# 引擎自动流水线必须真实执行的节点（缺失即任务失败）
AUTOMATED_SKILLS = {"data_import", "field_mapping", "ontology_context", "difference_detect", "anomaly_explain"}


def has_skill(skill_code: str) -> bool:
    return skill_code in _REGISTRY


def is_async(skill_code: str) -> bool:
    entry = _REGISTRY.get(skill_code)
    return bool(entry and entry[1])


def get_handler(skill_code: str) -> Callable:
    entry = _REGISTRY.get(skill_code)
    if not entry:
        raise SkillExecutionError(f"Skill 未在 SkillRegistry 注册: {skill_code}")
    return entry[0]


def registered_codes() -> list[str]:
    return list(_REGISTRY.keys())
