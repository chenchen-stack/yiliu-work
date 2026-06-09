"""MVP Workflow execution engine.

本引擎不再硬编码调用具体 Python 函数，而是读取任务绑定的 Workflow.nodes，
按节点 skill_code 经 SkillRegistry 调度真实 handler，并为每个节点写入 SkillInvocation
审计记录（审计报告 §9 的核心补齐项）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    BusinessCenter,
    Difference,
    DifferenceStatus,
    RuleConfig,
    Skill,
    SkillInvocation,
    Task,
    TaskStatus,
    Workflow,
    WorkflowRun,
)
from app.services.audit_service import log_audit
from app.services.data_loader import dataframe_to_records, load_dataframe, normalize_dataframe
from app.services.difference_detector import detect_for_verification
from app.services.skill_registry import (
    AUTOMATED_SKILLS,
    AUTOMATED_SKILLS,
    SkillContext,
    SkillExecutionError,
    get_handler,
    has_skill,
    is_async,
)


# 默认 Workflow 定义（用于全新 DB 的 seed；每个节点均带 skill_code）
WORKFLOW_NODES = [
    {"id": "import", "skill": "data_import", "skill_code": "data_import", "label": "数据导入", "enabled": True},
    {
        "id": "ontology",
        "skill": "ontology_context",
        "skill_code": "ontology_context",
        "label": "实体与规则",
        "enabled": True,
    },
    {"id": "mapping", "skill": "field_mapping", "skill_code": "field_mapping", "label": "字段映射", "enabled": True},
    {"id": "detect", "skill": "difference_detect", "skill_code": "difference_detect", "label": "差异识别", "enabled": True},
    {"id": "ai_explain", "skill": "anomaly_explain", "skill_code": "anomaly_explain", "label": "异常解释", "enabled": True},
    {"id": "review", "skill": "review_flow", "skill_code": "review_flow", "label": "复核流转", "enabled": True},
    {"id": "verify", "skill": "re_verify", "skill_code": "re_verify", "label": "再次验证", "enabled": True},
    {"id": "report", "skill": "report_gen", "skill_code": "report_gen", "label": "报告生成", "enabled": True},
]

WORKFLOW_TRANSITIONS = [
    {"from": "import", "to": "ontology"},
    {"from": "ontology", "to": "mapping"},
    {"from": "mapping", "to": "detect"},
    {"from": "detect", "to": "ai_explain"},
    {"from": "ai_explain", "to": "review"},
    {"from": "review", "to": "verify"},
    {"from": "verify", "to": "report"},
]


def reorder_workflow_nodes(nodes: list[dict]) -> list[dict]:
    """按平台标准顺序排列：接入 → 实体与规则 → 映射 → 识别 → …"""
    canonical = [n["id"] for n in WORKFLOW_NODES]
    by_id = {n.get("id"): dict(n) for n in nodes if n.get("id")}
    ordered: list[dict] = []
    seen: set[str] = set()
    for nid in canonical:
        if nid in by_id:
            ordered.append(by_id[nid])
            seen.add(nid)
    for node in nodes:
        nid = node.get("id")
        if nid and nid not in seen:
            ordered.append(by_id.get(nid, dict(node)))
            seen.add(nid)
    return ordered


def ensure_workflow_nodes(nodes: list[dict]) -> list[dict]:
    """补全缺失的「实体与规则」节点，并规范为接入 → 实体 → 映射 → 识别顺序。"""
    if not nodes:
        return list(WORKFLOW_NODES)
    default = {n["id"]: dict(n) for n in WORKFLOW_NODES}
    by_id = {n.get("id"): dict(n) for n in nodes if n.get("id")}
    if "ontology" not in by_id and default.get("ontology"):
        by_id["ontology"] = dict(default["ontology"])
    merged = [by_id[nid] for nid in by_id]
    return reorder_workflow_nodes(merged)


def current_ai_mode(db=None) -> str:
    from sqlalchemy.orm import Session

    from app.services.llm_config_service import get_effective_llm_config

    if isinstance(db, Session):
        cfg = get_effective_llm_config(db)
        if cfg.use_mock or not cfg.api_key:
            return "rule-engine"
        return cfg.model
    if settings.use_mock_ai or not settings.deepseek_api_key:
        return "rule-engine"
    return settings.deepseek_model


class WorkflowEngine:
    def __init__(self, db: Session, task: Task):
        self.db = db
        self.task = task
        self._wf: Workflow | None = None
        self._skill_versions: dict[str, int] | None = None
        self._enabled_codes: set[str] | None = None

    # ---- 配置解析 -----------------------------------------------------------

    def _workflow(self) -> Workflow | None:
        if self._wf is not None:
            return self._wf
        wf_id = (self.task.summary or {}).get("workflow_id")
        if not wf_id and self.task.business_center_id:
            bc = self.db.query(BusinessCenter).filter(BusinessCenter.id == self.task.business_center_id).first()
            wf_id = bc.workflow_id if bc else None
        if wf_id:
            self._wf = self.db.query(Workflow).filter(Workflow.id == wf_id).first()
        return self._wf

    def _ordered_nodes(self) -> list[dict]:
        wf = self._workflow()
        if wf and wf.nodes:
            return ensure_workflow_nodes(wf.nodes)
        return WORKFLOW_NODES

    def _skill_version_map(self) -> dict[str, int]:
        if self._skill_versions is None:
            self._skill_versions = {s.code: s.version for s in self.db.query(Skill).all()}
        return self._skill_versions

    def _enabled_skill_codes(self) -> set[str]:
        """业务中心 enabled_skill_ids 对应、且状态为 published 的 Skill code 集合。"""
        if self._enabled_codes is not None:
            return self._enabled_codes
        codes: set[str] = set()
        bc = None
        if self.task.business_center_id:
            bc = self.db.query(BusinessCenter).filter(BusinessCenter.id == self.task.business_center_id).first()
        skill_ids = (bc.enabled_skill_ids if bc else None) or []
        if skill_ids:
            rows = self.db.query(Skill).filter(Skill.id.in_(skill_ids), Skill.status == "published").all()
            codes = {s.code for s in rows}
        else:
            # 未显式配置时，回退为全部已发布 Skill（兼容旧数据）
            codes = {s.code for s in self.db.query(Skill).filter(Skill.status == "published").all()}
        codes |= AUTOMATED_SKILLS
        self._enabled_codes = codes
        return codes

    def _get_rules(self) -> list[dict]:
        if not self.task.rule_version_id:
            return []
        # 返回该版本下全部规则（含 enabled=False），由检测器按 enabled 标志诚实判定，
        # 避免“缺失即默认启用”导致禁用规则反而生效。
        rows = (
            self.db.query(RuleConfig)
            .filter(RuleConfig.rule_version_id == self.task.rule_version_id)
            .all()
        )
        return [
            {
                "rule_type": r.rule_type,
                "name": r.name,
                "condition": r.condition,
                "severity": r.severity,
                "enabled": r.enabled,
                "threshold": getattr(r, "threshold", 0) or 0,
                "params": getattr(r, "params", None),
            }
            for r in rows
        ]

    # ---- 运行日志 / 调用审计 -------------------------------------------------

    def _run_log(self, node_id: str, label: str, status: str, detail: dict | None = None):
        self.db.add(
            WorkflowRun(
                id=str(uuid.uuid4()),
                task_id=self.task.id,
                workflow_id=(self.task.summary or {}).get("workflow_id", "") if self.task.summary else "",
                node_id=node_id,
                node_label=label,
                status=status,
                detail=detail,
            )
        )
        log_audit(
            self.db,
            trace_id=self.task.trace_id,
            object_type="task",
            object_id=self.task.id,
            action="workflow_step",
            detail={"node_id": node_id, "label": label, "status": status, **(detail or {})},
        )

    def _record_invocation(
        self,
        *,
        node_code: str,
        node_label: str,
        skill_code: str,
        input_summary: dict | None,
        output_summary: dict | None,
        status: str,
        started_at: datetime,
        error_message: str | None = None,
    ) -> SkillInvocation:
        wf = self._workflow()
        inv = SkillInvocation(
            id=str(uuid.uuid4()),
            trace_id=self.task.trace_id,
            task_id=self.task.id,
            workflow_id=wf.id if wf else None,
            workflow_version=wf.version if wf else self.task.workflow_version,
            node_code=node_code,
            node_label=node_label,
            skill_code=skill_code,
            skill_version=self._skill_version_map().get(skill_code),
            input_summary=input_summary,
            output_summary=output_summary,
            status=status,
            error_message=error_message,
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )
        self.db.add(inv)
        log_audit(
            self.db,
            trace_id=self.task.trace_id,
            object_type="skill_invocation",
            object_id=inv.id,
            action="skill_invoke",
            detail={
                "node_code": node_code,
                "skill_code": skill_code,
                "skill_version": inv.skill_version,
                "status": status,
                "output_summary": output_summary,
            },
        )
        return inv

    def _validate_skill(self, skill_code: str):
        if not has_skill(skill_code):
            raise SkillExecutionError(f"节点 skill_code 未注册到 SkillRegistry: {skill_code}")
        if skill_code not in self._enabled_skill_codes():
            raise SkillExecutionError(f"Skill 未在业务中心启用或已停用: {skill_code}")

    # ---- 回调：写库与细粒度审计 ---------------------------------------------

    def _audit_rule_hit(self, item: dict):
        log_audit(
            self.db,
            trace_id=self.task.trace_id,
            object_type="difference",
            object_id=item["id"],
            action="rule_hit",
            detail={"rule_id": item.get("rule_id"), "type": item.get("type")},
        )

    def _persist_difference(self, item: dict, recommendation: dict, evidence: list):
        ai_expl = recommendation.get("root_cause", "")
        suggestion = recommendation.get("suggested_action") or recommendation.get("root_cause", "")
        diff = Difference(
            id=item["id"],
            task_id=self.task.id,
            business_key=item.get("business_key"),
            type=item["type"],
            difference_type=item.get("difference_type"),
            business_amount=item.get("business_amount"),
            finance_amount=item.get("finance_amount"),
            amount_diff=item.get("amount_diff"),
            confidence=item.get("confidence", 0),
            status=DifferenceStatus.PENDING_REVIEW.value,
            responsible_party=item.get("responsible_party"),
            sap_record=item.get("sap_record"),
            dms_record=item.get("dms_record"),
            statement_record=item.get("statement_record"),
            rule_hits=item.get("rule_hits"),
            evidence=item.get("evidence"),
            ai_recommendation=recommendation,
            ai_explanation=ai_expl,
            suggestion=suggestion,
            risk_level=item.get("risk_level"),
            evidence_chain=evidence,
        )
        self.db.add(diff)
        actual_model = recommendation.get("model") or "rule-engine"
        is_rule = str(actual_model).startswith("rule")
        is_mock = str(actual_model).startswith("mock")
        log_audit(
            self.db,
            trace_id=self.task.trace_id,
            object_type="difference",
            object_id=item["id"],
            action="ai_explain",
            detail={
                "model_mode": "rule" if is_rule else "llm",
                "model_name": actual_model,
                "configured_ai_mode": current_ai_mode(self.db),
                "prompt_version": recommendation.get("prompt_version"),
                "provider": recommendation.get(
                    "provider",
                    "mock" if is_mock else ("rule-config" if is_rule else "deepseek"),
                ),
                "fallback_reason": recommendation.get("fallback_reason"),
                "input_fact_summary": {
                    "type": item.get("type"),
                    "business_key": item.get("business_key"),
                    "business_amount": item.get("business_amount"),
                    "finance_amount": item.get("finance_amount"),
                    "amount_diff": item.get("amount_diff"),
                    "rule_id": item.get("rule_id"),
                },
                "referenced_evidence": len(recommendation.get("evidence", []) or []),
                "output_summary": ai_expl[:200],
            },
        )

    # ---- 主流程 -------------------------------------------------------------

    async def execute_through_review(self, file_paths: dict[str, str]):
        progress_map = {
            "data_import": 18,
            "ontology_context": 30,
            "field_mapping": 42,
            "difference_detect": 55,
            "anomaly_explain": 80,
        }
        started_pipeline = datetime.utcnow()
        try:
            self.task.status = TaskStatus.RUNNING.value
            self.task.progress = 5
            self.task.updated_at = datetime.utcnow()
            self.db.commit()

            rules = self._get_rules()
            ctx = SkillContext(
                db=self.db,
                task=self.task,
                file_paths=file_paths,
                rules=rules,
                ai_mode=current_ai_mode(self.db),
            )
            ctx.on_rule_hit = self._audit_rule_hit
            ctx.on_difference_built = self._persist_difference

            for node in self._ordered_nodes():
                if node.get("enabled") is False:
                    continue
                skill_code = node.get("skill_code") or node.get("skill")
                label = node.get("label", skill_code)
                node_id = node.get("id", skill_code)
                if skill_code not in AUTOMATED_SKILLS:
                    # 到达人工/后续节点（如 review），自动流水线在此暂停
                    break

                self._validate_skill(skill_code)
                self._run_log(node_id, label, "running")
                started = datetime.utcnow()
                try:
                    handler = get_handler(skill_code)
                    output = await handler(ctx) if is_async(skill_code) else handler(ctx)
                except SkillExecutionError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._record_invocation(
                        node_code=node_id,
                        node_label=label,
                        skill_code=skill_code,
                        input_summary={"files": list(file_paths.keys())},
                        output_summary=None,
                        status="failed",
                        started_at=started,
                        error_message=str(exc),
                    )
                    raise

                self._record_invocation(
                    node_code=node_id,
                    node_label=label,
                    skill_code=skill_code,
                    input_summary={"rule_count": len(rules)} if skill_code == "difference_detect" else None,
                    output_summary=output,
                    status="completed",
                    started_at=started,
                )
                self._run_log(node_id, label, "completed", output)
                self.task.progress = progress_map.get(skill_code, self.task.progress)
                self.db.commit()

            # 汇总
            type_counts: dict[str, int] = {}
            total_amount = 0.0
            for d in ctx.raw_diffs:
                type_counts[d["type"]] = type_counts.get(d["type"], 0) + 1
                total_amount += float(d.get("amount_diff") or 0)

            self.task.summary = {
                **(self.task.summary or {}),
                "total": len(ctx.raw_diffs),
                "by_type": type_counts,
                "total_difference_amount": total_amount,
                "business_rows": len(ctx.business_records),
                "finance_rows": len(ctx.finance_records),
                "ai_mode": current_ai_mode(self.db),
            }
            if len(ctx.raw_diffs) == 0:
                self._advance_zero_diff_to_reporting(trigger="auto_pipeline")
            else:
                self.task.status = TaskStatus.PENDING_REVIEW.value
                self.task.progress = 85
                self._run_log("review", "复核流转", "waiting", {"message": "等待人工复核"})
                from app.services.review_flow_service import notify_review_pending, review_progress

                stats = review_progress(self.db, self.task.id)
                self.task.summary = {
                    **(self.task.summary or {}),
                    "review_progress": stats,
                }
                notify_review_pending(self.db, self.task, kind="review_pending")
                self._record_invocation(
                    node_code="review",
                    node_label="复核流转",
                    skill_code="review_flow",
                    input_summary={"diff_count": len(ctx.raw_diffs)},
                    output_summary={"status": "waiting", "pending_review": stats.get("pending_review", 0)},
                    status="waiting",
                    started_at=datetime.utcnow(),
                )
            self.task.updated_at = datetime.utcnow()
            log_audit(
                self.db,
                user_id=self.task.creator_id,
                trace_id=self.task.trace_id,
                object_type="task",
                object_id=self.task.id,
                action="execute_complete",
                after_data={"status": self.task.status, "summary": self.task.summary},
            )
            self.db.commit()
        except Exception as e:
            self.task.status = TaskStatus.FAILED.value
            self.task.error_message = str(e)
            log_audit(
                self.db,
                trace_id=self.task.trace_id,
                object_type="task",
                object_id=self.task.id,
                action="execute_failed",
                detail={"error": str(e)},
            )
            self.db.commit()
            raise

    def _advance_zero_diff_to_reporting(self, *, trigger: str = "manual", user_id: str | None = None):
        """无差异：自动跳过人工复核与再次验证，进入报告输出。"""
        self._run_log(
            "review",
            "复核流转",
            "completed",
            {"message": "无差异，自动跳过人工复核", "trigger": trigger},
        )
        self._run_log(
            "verify",
            "再次验证",
            "completed",
            {"resolved": 0, "total": 0, "message": "无差异，自动验证通过", "trigger": trigger},
        )
        self.task.status = TaskStatus.REPORTING.value
        self.task.progress = 90
        self.task.summary = {
            **(self.task.summary or {}),
            "auto_skipped_review": True,
            "zero_diff_auto_pass": True,
        }
        log_audit(
            self.db,
            user_id=user_id or self.task.creator_id,
            trace_id=self.task.trace_id,
            object_type="task",
            object_id=self.task.id,
            action="auto_skip_review",
            after_data={"status": TaskStatus.REPORTING.value, "trigger": trigger},
        )
        self._try_auto_generate_report()

    def _try_auto_generate_report(self) -> None:
        """无差异进入 reporting 后自动生成 PDF，避免流程卡在 90%。"""
        if (self.task.summary or {}).get("report_path"):
            return
        try:
            from app.services.task_report_service import create_task_pdf_report

            create_task_pdf_report(self.db, self.task, user=None, write_workflow_run=True)
            self.task.progress = 95
        except Exception as exc:
            self.task.summary = {
                **(self.task.summary or {}),
                "report_error": str(exc),
            }
            log_audit(
                self.db,
                user_id=self.task.creator_id,
                trace_id=self.task.trace_id,
                object_type="task",
                object_id=self.task.id,
                action="auto_generate_report_failed",
                detail={"error": str(exc)},
            )

    async def run_verification(self, file_paths: dict[str, str], user_id: str) -> dict[str, Any]:
        from app.models import VerificationRecord

        started = datetime.utcnow()
        self._validate_skill("re_verify")

        def _load(path, source):
            if not path:
                return []
            return dataframe_to_records(normalize_dataframe(load_dataframe(path), source))

        business_records = _load(file_paths.get("business") or file_paths.get("sap"), "sap")
        finance_records = _load(file_paths.get("finance") or file_paths.get("dms"), "dms")
        diffs = (
            self.db.query(Difference)
            .filter(
                Difference.task_id == self.task.id,
                Difference.status.in_([
                    DifferenceStatus.CONFIRMED.value,
                    DifferenceStatus.PENDING_VERIFICATION.value,
                    DifferenceStatus.ASSIGNED.value,
                    DifferenceStatus.PROCESSING.value,
                    DifferenceStatus.RETURNED.value,
                ]),
            )
            .all()
        )
        keys = [d.business_key for d in diffs if d.business_key]
        results_map = detect_for_verification(business_records, finance_records, keys, self._get_rules())

        resolved_count = 0
        for d in diffs:
            if not d.business_key:
                continue
            resolved = results_map.get(d.business_key, False)
            remaining = 0.0 if resolved else float(d.amount_diff or 0)
            vr = VerificationRecord(
                id=str(uuid.uuid4()),
                difference_item_id=d.id,
                task_id=self.task.id,
                verification_result="resolved" if resolved else "returned",
                remaining_difference=remaining,
                verified_by=user_id,
            )
            self.db.add(vr)
            before = d.status
            d.status = DifferenceStatus.RESOLVED.value if resolved else DifferenceStatus.RETURNED.value
            if resolved:
                resolved_count += 1
            log_audit(
                self.db,
                user_id=user_id,
                trace_id=self.task.trace_id,
                object_type="difference",
                object_id=d.id,
                action="verify",
                before_data={"status": before},
                after_data={"status": d.status, "remaining_difference": remaining},
            )

        # autoflush=False：先 flush 让本次状态变更对下面的统计查询可见
        self.db.flush()
        open_diffs = (
            self.db.query(Difference)
            .filter(
                Difference.task_id == self.task.id,
                Difference.status.in_([
                    DifferenceStatus.ASSIGNED.value,
                    DifferenceStatus.PROCESSING.value,
                    DifferenceStatus.PENDING_VERIFICATION.value,
                    DifferenceStatus.PENDING_REVIEW.value,
                    DifferenceStatus.RETURNED.value,
                ]),
            )
            .count()
        )
        if open_diffs == 0:
            self.task.status = TaskStatus.REPORTING.value
            self.task.progress = 90
        self._record_invocation(
            node_code="verify",
            node_label="再次验证",
            skill_code="re_verify",
            input_summary={"verified": len(diffs)},
            output_summary={"resolved": resolved_count, "total": len(diffs)},
            status="completed",
            started_at=started,
        )
        self._run_log("verify", "再次验证", "completed", {"resolved": resolved_count, "total": len(diffs)})
        self.task.updated_at = datetime.utcnow()
        self.db.commit()
        return {"resolved": resolved_count, "total": len(diffs), "task_status": self.task.status}
