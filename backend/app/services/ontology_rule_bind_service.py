"""将规则引擎 RuleConfig 绑定到本体 OntologyDomainRule（数据语义 · 领域规则）。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import RuleConfig
from app.ontology_models import OntologyDomainRule
from app.services.ontology_a_customer_seed import DOMAIN as ONTOLOGY_DOMAIN
from app.services.ontology_a_customer_seed import entity_key

REGISTER_ENTITY_KEY = entity_key("knowledge", "register", "exception_register")
BIND_SOURCE = "rule_engine"
DETECT_RULE_TYPE = "DETECT"


def _build_rule_content(rule: RuleConfig, *, source_file: str = "") -> str:
    lines = [f"【规则引擎·检测】{rule.name}"]
    if rule.condition:
        lines.append(f"检测逻辑：{rule.condition}")
    params = rule.params or {}
    steps = params.get("troubleshooting_steps") or ""
    if steps:
        lines.append(f"排查要点：{str(steps)[:800]}")
    sample_count = params.get("sample_count")
    if sample_count:
        lines.append(f"登记表提炼场景：{sample_count} 条")
    if source_file:
        lines.append(f"来源文件：{source_file}")
    return "\n".join(lines)


def bind_rule_configs_to_ontology(
    db: Session,
    *,
    rule_version_id: str,
    business_center_id: str,
    source_file: str = "",
    operator: str = "system",
) -> dict[str, Any]:
    """
    把当前规则版本下的 RuleConfig 同步为本体「领域规则」中 rule_type=DETECT 的条目，
    通过 rule_config_id 与规则引擎一一对应。
    """
    rows = (
        db.query(RuleConfig)
        .filter(
            RuleConfig.rule_version_id == rule_version_id,
            RuleConfig.business_center_id == business_center_id,
        )
        .order_by(RuleConfig.rule_type)
        .all()
    )
    bound: list[dict[str, Any]] = []
    for rule in rows:
        content = _build_rule_content(rule, source_file=source_file)
        existing = (
            db.query(OntologyDomainRule)
            .filter(OntologyDomainRule.rule_config_id == rule.id)
            .first()
        )
        if not existing:
            existing = (
                db.query(OntologyDomainRule)
                .filter(
                    OntologyDomainRule.domain == ONTOLOGY_DOMAIN,
                    OntologyDomainRule.bind_source == BIND_SOURCE,
                    OntologyDomainRule.remark == rule.rule_type,
                    OntologyDomainRule.status == 1,
                )
                .first()
            )
        status = "PUBLISHED" if rule.enabled else "DRAFT"
        risk = "HIGH" if rule.severity == "high" else "MEDIUM" if rule.severity == "medium" else "LOW"

        if existing:
            existing.rule_content = content
            existing.effective_status = status
            existing.risk_level = risk
            existing.rule_config_id = rule.id
            existing.bind_source = BIND_SOURCE
            existing.entity_key = REGISTER_ENTITY_KEY
            existing.update_by = operator
            action = "updated"
        else:
            existing = OntologyDomainRule(
                id=str(uuid.uuid4()),
                domain=ONTOLOGY_DOMAIN,
                entity_key=REGISTER_ENTITY_KEY,
                rule_type=DETECT_RULE_TYPE,
                rule_content=content,
                priority=3,
                risk_level=risk,
                effective_status=status,
                rule_config_id=rule.id,
                bind_source=BIND_SOURCE,
                remark=rule.rule_type,
                examples_json=json.dumps(
                    [{"rule_engine_name": rule.name, "rule_type": rule.rule_type}],
                    ensure_ascii=False,
                ),
                create_by=operator,
            )
            db.add(existing)
            action = "created"

        bound.append({
            "ontology_rule_id": existing.id,
            "rule_config_id": rule.id,
            "rule_type": rule.rule_type,
            "name": rule.name,
            "action": action,
            "effective_status": status,
        })

    db.commit()
    return {
        "bound_count": len(bound),
        "bindings": bound,
        "register_entity_key": REGISTER_ENTITY_KEY,
        "message": f"已绑定 {len(bound)} 条规则引擎规则到本体领域规则",
    }
