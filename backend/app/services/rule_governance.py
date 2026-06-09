"""Domain rule lifecycle: publish / archive / rollback."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.ontology_models import OntologyDomainRule


class RuleGovernanceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def publish_rule(self, rule_id: str, *, approved_by: str) -> OntologyDomainRule:
        rule = self.db.get(OntologyDomainRule, rule_id)
        if not rule:
            raise ValueError(f"规则不存在: {rule_id}")
        if rule.risk_level in ("HIGH", "CRITICAL") and not approved_by:
            raise ValueError("高风险规则需指定审批人")
        rule.effective_status = "PUBLISHED"
        rule.approved_by = approved_by
        rule.approved_time = datetime.utcnow()
        rule.update_time = datetime.utcnow()
        self.db.commit()
        return rule

    def archive_rule(self, rule_id: str) -> OntologyDomainRule:
        rule = self.db.get(OntologyDomainRule, rule_id)
        if not rule:
            raise ValueError(f"规则不存在: {rule_id}")
        rule.effective_status = "ARCHIVED"
        rule.update_time = datetime.utcnow()
        self.db.commit()
        return rule

    def rollback_rule(self, rule_id: str) -> OntologyDomainRule:
        rule = self.db.get(OntologyDomainRule, rule_id)
        if not rule:
            raise ValueError(f"规则不存在: {rule_id}")
        if rule.version <= 1:
            rule.effective_status = "DRAFT"
        else:
            rule.version -= 1
            rule.effective_status = "PUBLISHED"
        rule.update_time = datetime.utcnow()
        self.db.commit()
        return rule

    def get_impact_analysis(self, rule_id: str) -> dict:
        rule = self.db.get(OntologyDomainRule, rule_id)
        if not rule:
            raise ValueError(f"规则不存在: {rule_id}")
        return {
            "rule_id": rule_id,
            "domain": rule.domain,
            "entity_key": rule.entity_key,
            "affected_agents": ["revenue_reconciliation_agent", "chat_agent"],
            "prompt_snippet": rule.rule_content[:200],
        }

    def get_pending_approvals(self) -> list[OntologyDomainRule]:
        return (
            self.db.query(OntologyDomainRule)
            .filter(
                OntologyDomainRule.effective_status == "DRAFT",
                OntologyDomainRule.risk_level.in_(["HIGH", "CRITICAL"]),
            )
            .all()
        )
