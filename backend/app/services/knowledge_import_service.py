"""知识库资料导入：Excel 解析为可检索条目，供 Agent 知识库检索引用。"""
from __future__ import annotations

import uuid
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.models import CaseAsset
from app.services.audit_service import log_audit
from app.services.fangtai_rule_extract import extract_workbook_from_stream

VALID_KB_IDS = frozenset({
    "kb-fangtai-cases",
    "kb-compliance",
    "revenue_reconciliation",
})

RULE_TYPE_LABELS = {
    "amount_mismatch": "金额差异",
    "duplicate_record": "重复数据",
    "mapping_anomaly": "主数据/映射异常",
    "status_mismatch": "状态不一致",
    "sync_failure": "接口/同步异常",
    "payment_mismatch": "回款差异",
    "fanruan_summary": "帆软汇总差异",
}


def _pattern_to_case(
    pattern: dict,
    *,
    knowledge_base_id: str,
    source_file: str,
) -> CaseAsset:
    rule_type = pattern.get("rule_type") or "amount_mismatch"
    confirmed = RULE_TYPE_LABELS.get(rule_type, pattern.get("problem_group") or "未分类")
    category = pattern.get("category") or ""
    group = pattern.get("problem_group") or ""
    detail = pattern.get("problem_detail") or pattern.get("name") or ""
    cause = pattern.get("cause_category") or ""
    remedy = pattern.get("remedy") or ""
    steps = pattern.get("troubleshooting_steps") or ""

    root_parts = [p for p in [f"[{category}]" if category else "", group, detail] if p]
    root_cause = " · ".join(root_parts)
    if cause:
        root_cause = f"{root_cause}\n原因归类：{cause}" if root_cause else f"原因归类：{cause}"

    handling = remedy or "—"
    suggestion = steps or ""
    if pattern.get("count"):
        suggestion = f"登记频次：{pattern['count']} 条\n{suggestion}".strip()

    return CaseAsset(
        id=str(uuid.uuid4()),
        source_task_id=f"kb:{knowledge_base_id}",
        source_difference_id=f"kb-upload:{uuid.uuid4()}",
        confirmed_type=confirmed,
        root_cause=root_cause[:4000] if root_cause else None,
        handling_result=handling[:2000] if handling else None,
        reusable_rule_suggestion=suggestion[:4000] if suggestion else None,
        status="published",
        knowledge_base_id=knowledge_base_id,
        source_kind="kb_upload",
        source_file=source_file,
    )


def import_excel_to_knowledge(
    db: Session,
    *,
    stream: BinaryIO,
    filename: str,
    knowledge_base_id: str,
    user,
    replace_same_file: bool = True,
) -> dict:
    if knowledge_base_id not in VALID_KB_IDS:
        raise ValueError(f"不支持的知识库：{knowledge_base_id}")

    extracted = extract_workbook_from_stream(stream, filename)
    patterns = extracted.get("patterns") or []
    if not patterns:
        raise ValueError("未能从 Excel 中识别有效条目，请确认为《收入/回款异常问题登记表》或同类结构")

    if replace_same_file:
        db.query(CaseAsset).filter(
            CaseAsset.knowledge_base_id == knowledge_base_id,
            CaseAsset.source_kind == "kb_upload",
            CaseAsset.source_file == filename,
        ).delete(synchronize_session=False)

    created: list[CaseAsset] = []
    for pattern in patterns:
        asset = _pattern_to_case(
            pattern,
            knowledge_base_id=knowledge_base_id,
            source_file=filename,
        )
        db.add(asset)
        created.append(asset)

    log_audit(
        db,
        user=user,
        object_type="knowledge_base",
        object_id=knowledge_base_id,
        action="upload_excel",
        detail={
            "source_file": filename,
            "entries_created": len(created),
            "total_patterns": extracted.get("total_patterns", len(patterns)),
        },
    )
    db.commit()
    return {
        "knowledge_base_id": knowledge_base_id,
        "source_file": filename,
        "entries_created": len(created),
        "total_patterns": extracted.get("total_patterns", len(patterns)),
        "title": extracted.get("title"),
    }
