"""检测规则：方太登记表导入与应用。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy.orm import Session

from app.models import BusinessCenter, RuleConfig, Workflow
from app.services.audit_service import log_audit
from app.services.fangtai_rule_extract import extract_workbook_from_path, extract_workbook_from_stream, load_preset
from app.services.llm_config_service import get_effective_llm_config
from app.services.ontology_rule_bind_service import bind_rule_configs_to_ontology

RULE_ENGINE_BASE = {
    "amount_mismatch": "同 business_key（发票号/结算单）两侧金额汇总不等，且差值 > 容差阈值",
    "duplicate_record": "同侧 (order_id, invoice_num, customer_id) 组合键重复出现 ≥2 次",
    "mapping_anomaly": "MDM 主数据、发票抬头/类型或 product_code 映射与 SAP/DMS 不一致",
    "status_mismatch": "过账/开票/结算状态字段组合不符合方太正常态（如过账成功但开票中）",
    "sync_failure": "SAP 与 DMS 回传/同步异常（回传成功但对方未更新、接口报错等）",
    "payment_mismatch": "回款/台账侧金额或与 DRP/付款申请不一致、同单多状态",
    "fanruan_summary": "帆软对账平台四列（SAP/DRP/LTC/DMS）勾稽不等或差异标识为有差异",
}


def _build_condition(consolidated: dict) -> str:
    base = RULE_ENGINE_BASE.get(consolidated["rule_type"], "")
    return f"{base}。{consolidated.get('condition', '')}"


def _merge_params(existing: dict | None, consolidated: dict, *, source_file: str) -> dict:
    params = dict(existing or {})
    params.update({
        "source": "fangtai_registration",
        "source_file": source_file,
        "troubleshooting_steps": consolidated.get("troubleshooting_steps", ""),
        "sample_count": consolidated.get("sample_count", 0),
        "pattern_samples": consolidated.get("samples", [])[:3],
    })
    return params


async def ai_enhance_consolidated(extracted: dict, db: Session | None) -> dict:
    """可选：用大模型精炼三类规则的检测逻辑说明（无 Key 时原样返回）。"""
    cfg = get_effective_llm_config(db)
    if cfg.use_mock or not cfg.api_key:
        return extracted
    try:
        from app.services.chat_service import call_deepseek_chat

        prompt = (
            "你是方太财务收入核对专家。根据下列从《收入/回款异常问题登记表》提取的 JSON，"
            "为三类检测规则各写一段 80 字以内的「检测逻辑说明」（面向财务，不要 Markdown）。"
            "只返回 JSON 数组，每项含 rule_type、condition 字段。\n\n"
            + json.dumps(extracted.get("consolidated_rules", [])[:3], ensure_ascii=False)[:6000]
        )
        raw = await call_deepseek_chat(
            cfg,
            [
                {"role": "system", "content": "只输出合法 JSON 数组，不要其它文字。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
        )
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            patches = json.loads(raw[start:end])
            by_type = {p["rule_type"]: p.get("condition", "") for p in patches if p.get("rule_type")}
            for cr in extracted.get("consolidated_rules", []):
                if cr["rule_type"] in by_type and by_type[cr["rule_type"]]:
                    cr["condition"] = by_type[cr["rule_type"]]
            extracted["ai_enhanced"] = True
    except Exception:
        extracted["ai_enhanced"] = False
    return extracted


def apply_consolidated_to_rules(
    db: Session,
    *,
    rule_version_id: str,
    business_center_id: str,
    consolidated_rules: list[dict],
    source_file: str,
    user,
) -> list[dict]:
    """将 consolidated_rules 写入当前版本的 RuleConfig。"""
    applied: list[dict] = []
    rows = (
        db.query(RuleConfig)
        .filter(
            RuleConfig.rule_version_id == rule_version_id,
            RuleConfig.business_center_id == business_center_id,
        )
        .all()
    )
    by_type = {r.rule_type: r for r in rows}
    for cr in consolidated_rules:
        rule = by_type.get(cr["rule_type"])
        if not rule:
            rule = RuleConfig(
                id=str(uuid.uuid4()),
                business_center_id=business_center_id,
                rule_version_id=rule_version_id,
                rule_type=cr["rule_type"],
                name=cr.get("name") or cr["rule_type"],
                condition=_build_condition(cr),
                severity=cr.get("severity") or "high",
                enabled=True,
                threshold=float(cr.get("threshold") or 0),
                params=_merge_params({}, cr, source_file=source_file),
                version=1,
            )
            db.add(rule)
            by_type[cr["rule_type"]] = rule
        before = {
            "name": rule.name,
            "condition": rule.condition,
            "severity": rule.severity,
            "threshold": rule.threshold,
            "params": rule.params,
        }
        rule.name = cr.get("name") or rule.name
        rule.condition = _build_condition(cr)
        rule.severity = cr.get("severity") or rule.severity
        if cr.get("threshold") is not None and cr["rule_type"] == "amount_mismatch":
            rule.threshold = float(cr["threshold"])
        rule.params = _merge_params(rule.params, cr, source_file=source_file)
        rule.enabled = True
        log_audit(
            db,
            user=user,
            object_type="rule_config",
            object_id=rule.id,
            action="import_troubleshooting_rules",
            before_data=before,
            after_data={
                "name": rule.name,
                "condition": rule.condition,
                "params_keys": list((rule.params or {}).keys()),
            },
        )
        applied.append({
            "rule_id": rule.id,
            "rule_type": rule.rule_type,
            "name": rule.name,
        })
    db.commit()
    return applied


def bind_rules_to_ontology(
    db: Session,
    *,
    rule_version_id: str,
    business_center_id: str,
    source_file: str = "",
    user=None,
) -> dict[str, Any]:
    """规则引擎 → 数据语义领域规则（DETECT 类型，按 rule_config_id 关联）。"""
    operator = getattr(user, "username", None) or "system"
    return bind_rule_configs_to_ontology(
        db,
        rule_version_id=rule_version_id,
        business_center_id=business_center_id,
        source_file=source_file,
        operator=operator,
    )


def bind_rules_to_workflow_detect(
    db: Session,
    *,
    business_center_id: str,
    rule_version_id: str,
) -> dict[str, Any] | None:
    """将当前规则版本写入 Workflow「差异识别」节点，供编排页与任务执行展示。"""
    bc = db.query(BusinessCenter).filter(BusinessCenter.id == business_center_id).first()
    if not bc or not bc.workflow_id:
        return None
    rows = (
        db.query(RuleConfig)
        .filter(
            RuleConfig.rule_version_id == rule_version_id,
            RuleConfig.business_center_id == business_center_id,
            RuleConfig.enabled.is_(True),
        )
        .order_by(RuleConfig.rule_type)
        .all()
    )
    bindings = [
        {
            "id": r.id,
            "name": r.name,
            "rule_type": r.rule_type,
            "severity": r.severity,
        }
        for r in rows
    ]
    wf = db.query(Workflow).filter(Workflow.id == bc.workflow_id).first()
    if not wf:
        return None
    nodes = [dict(n) for n in (wf.nodes or [])]
    synced = False
    for i, node in enumerate(nodes):
        if node.get("id") != "detect":
            continue
        nodes[i] = {
            **node,
            "rule_version_id": rule_version_id,
            "rule_bindings": bindings,
            "rule_synced_at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        synced = True
        break
    if not synced:
        return None
    wf.nodes = nodes
    db.commit()
    return {
        "workflow_id": wf.id,
        "node_id": "detect",
        "bound_count": len(bindings),
        "rule_bindings": bindings,
    }


def apply_preset(
    db: Session,
    *,
    rule_version_id: str,
    business_center_id: str,
    user,
) -> dict:
    preset = load_preset()
    applied = apply_consolidated_to_rules(
        db,
        rule_version_id=rule_version_id,
        business_center_id=business_center_id,
        consolidated_rules=preset["consolidated_rules"],
        source_file=preset.get("source_file", "fangtai_preset.json"),
        user=user,
    )
    workflow_bind = bind_rules_to_workflow_detect(
        db,
        business_center_id=business_center_id,
        rule_version_id=rule_version_id,
    )
    ontology_bind = bind_rules_to_ontology(
        db,
        rule_version_id=rule_version_id,
        business_center_id=business_center_id,
        source_file=preset.get("source_file", "fangtai_preset.json"),
        user=user,
    )
    return {
        "total_patterns": preset.get("total_patterns", 0),
        "consolidated_rules": preset.get("consolidated_rules", []),
        "applied": applied,
        "ai_enhanced": False,
        "source_file": preset.get("source_file"),
        "workflow_bind": workflow_bind,
        "ontology_bind": ontology_bind,
    }


async def import_excel_and_apply(
    db: Session,
    *,
    stream: BinaryIO,
    filename: str,
    rule_version_id: str,
    business_center_id: str,
    user,
    use_ai: bool = False,
) -> dict:
    extracted = extract_workbook_from_stream(stream, filename)
    if use_ai:
        extracted = await ai_enhance_consolidated(extracted, db)
    else:
        extracted["ai_enhanced"] = False
    applied = apply_consolidated_to_rules(
        db,
        rule_version_id=rule_version_id,
        business_center_id=business_center_id,
        consolidated_rules=extracted["consolidated_rules"],
        source_file=filename,
        user=user,
    )
    workflow_bind = bind_rules_to_workflow_detect(
        db,
        business_center_id=business_center_id,
        rule_version_id=rule_version_id,
    )
    ontology_bind = bind_rules_to_ontology(
        db,
        rule_version_id=rule_version_id,
        business_center_id=business_center_id,
        source_file=filename,
        user=user,
    )
    return {
        "total_patterns": extracted.get("total_patterns", 0),
        "consolidated_rules": extracted.get("consolidated_rules", []),
        "applied": applied,
        "ai_enhanced": extracted.get("ai_enhanced", False),
        "source_file": filename,
        "workflow_bind": workflow_bind,
        "ontology_bind": ontology_bind,
    }


def import_excel_preview(stream: BinaryIO, filename: str, *, use_ai: bool = False) -> dict:
    """仅解析预览，不写库。"""
    return extract_workbook_from_stream(stream, filename)
