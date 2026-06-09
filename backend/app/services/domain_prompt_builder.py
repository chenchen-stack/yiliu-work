"""Build Agent system prompt sections from ontology."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.ontology_models import OntologyDomainRule, OntologyEntity, OntologyRelation


class DomainPromptBuilder:
    """Assemble markdown ontology context for agents."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def build(
        self,
        agent_entity_keys: list[str] | None,
        agent_domain: str | None,
        *,
        user_permissions: set[str] | None = None,
    ) -> str:
        perms = user_permissions or {"internal", "internal_finance", "public"}
        q = self.db.query(OntologyEntity).filter(
            OntologyEntity.status == 1,
            OntologyEntity.prompt_visible == 1,
        )
        if agent_domain:
            q = q.filter(OntologyEntity.domain == agent_domain)
        entities = q.all()
        if agent_entity_keys:
            key_set = set(agent_entity_keys)
            entities = [e for e in entities if e.entity_key in key_set]
        entities = [e for e in entities if e.data_sensitivity in perms]

        lines = ["## 你可用的企业数据", ""]
        keys = {e.entity_key for e in entities}
        for ent in entities:
            lines.append(f"### {ent.label} ({ent.entity_key})")
            if ent.description:
                lines.append(f"业务口径: {ent.description}")
            lines.append("字段:")
            for col in json.loads(ent.columns_json or "[]"):
                if col.get("sensitivity") == "restricted":
                    continue
                samples = col.get("sample_values") or []
                samp = f"，示例: {', '.join(samples[:3])}" if samples else ""
                lines.append(f" - {col.get('name')}: {col.get('data_type', '')}{samp}")
            lines.append("")

        rels = (
            self.db.query(OntologyRelation)
            .filter(OntologyRelation.status == 1)
            .all()
        )
        rel_lines = [
            f"{r.from_entity}.{r.from_column} → {r.to_entity}.{r.to_column}"
            for r in rels
            if r.from_entity in keys and r.to_entity in keys
        ]
        if rel_lines:
            lines.extend(["## 实体关系", *rel_lines, ""])

        rules_q = self.db.query(OntologyDomainRule).filter(
            OntologyDomainRule.effective_status == "PUBLISHED",
            OntologyDomainRule.status == 1,
        )
        if agent_domain:
            rules_q = rules_q.filter(OntologyDomainRule.domain == agent_domain)
        rules = rules_q.order_by(OntologyDomainRule.priority).all()
        if rules:
            lines.append("## 领域规则（请严格遵守）")
            by_type: dict[str, list[str]] = {}
            type_title = {
                "DEFINITION": "数据约定",
                "INVARIANT": "不变量",
                "HEURISTIC": "经验模式",
                "ANOMALY": "异常判断",
            }
            for rule in rules:
                title = type_title.get(rule.rule_type, rule.rule_type)
                by_type.setdefault(title, []).append(f"- {rule.rule_content}")
            for title, items in by_type.items():
                lines.append(f"### {title}")
                lines.extend(items)
                lines.append("")
        return "\n".join(lines).strip()
