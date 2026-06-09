"""Ontology semantic layer API."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.database import get_db
from app.models import User, UserRole
from app.ontology_models import OntologyDomainRule, OntologyEntity, OntologyRelation
from app.services.domain_prompt_builder import DomainPromptBuilder
from app.services.entity_embedding_service import find_similar_entities, refresh_all_embeddings
from app.ontology_config import resolve_poc_xlsx
from app.services.ontology_extractor import extract_all_fangtai_sources
from app.services.rule_governance import RuleGovernanceService

router = APIRouter(tags=["ontology"])


def ok(data: Any = None, message: str = "") -> dict:
    return {"code": 0, "data": data, "message": message}


def _entity_out(row: OntologyEntity) -> dict:
    return {
        "id": row.id,
        "entity_key": row.entity_key,
        "datasource_code": row.datasource_code,
        "source_type": row.source_type,
        "schema_name": row.schema_name,
        "table_name": row.table_name,
        "label": row.label,
        "description": row.description,
        "columns": json.loads(row.columns_json or "[]"),
        "aliases": json.loads(row.aliases_json or "[]"),
        "sample_queries": json.loads(row.sample_queries_json or "[]"),
        "domain": row.domain,
        "data_sensitivity": row.data_sensitivity,
        "prompt_visible": row.prompt_visible,
    }


class EntityUpdateBody(BaseModel):
    label: str | None = None
    description: str | None = None
    aliases: list[str] | None = None
    sample_queries: list[str] | None = None


class RelationCreateBody(BaseModel):
    from_entity: str
    to_entity: str
    from_column: str
    to_column: str
    relation_type: str = "MANUAL"
    description: str | None = None


class RuleCreateBody(BaseModel):
    domain: str
    rule_type: str
    rule_content: str
    entity_key: str | None = None
    priority: int = 5
    risk_level: str = "LOW"


class RuleUpdateBody(BaseModel):
    rule_content: str | None = None
    priority: int | None = None
    risk_level: str | None = None


class SimilarQueryBody(BaseModel):
    query: str
    top_k: int = 5


@router.get("/ontology/entities")
def list_entities(
    domain: str | None = None,
    datasource_code: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(OntologyEntity).filter(OntologyEntity.status == 1)
    if domain:
        q = q.filter(OntologyEntity.domain == domain)
    if datasource_code:
        q = q.filter(OntologyEntity.datasource_code == datasource_code)
    rows = q.order_by(OntologyEntity.datasource_code, OntologyEntity.table_name).all()
    return ok([_entity_out(r) for r in rows])


@router.get("/ontology/entities/{entity_key:path}")
def get_entity(
    entity_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.query(OntologyEntity).filter(OntologyEntity.entity_key == entity_key).first()
    if not row:
        raise HTTPException(404, f"实体不存在: {entity_key}")
    return ok(_entity_out(row))


@router.put("/ontology/entities/{entity_key:path}")
def update_entity(
    entity_key: str,
    body: EntityUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    row = db.query(OntologyEntity).filter(OntologyEntity.entity_key == entity_key).first()
    if not row:
        raise HTTPException(404, f"实体不存在: {entity_key}")
    if body.label is not None:
        row.label = body.label
    if body.description is not None:
        row.description = body.description
    if body.aliases is not None:
        row.aliases_json = json.dumps(body.aliases, ensure_ascii=False)
    if body.sample_queries is not None:
        row.sample_queries_json = json.dumps(body.sample_queries, ensure_ascii=False)
    row.update_by = user.username
    row.update_time = datetime.utcnow()
    db.commit()
    return ok(_entity_out(row))


def _relation_edge_label(from_column: str, to_column: str) -> str:
    """单边展示文案，避免 from 已含箭头时再拼 to 导致重复。"""
    f = (from_column or "").strip()
    t = (to_column or "").strip()
    if not f and t:
        return t
    if not t or f == t:
        return f
    if any(ch in f for ch in ("→", "->", "—")) and (not t or t in f):
        return f
    if f"→ {t}" in f or f"-> {t}" in f:
        return f
    return f"{f} → {t}"


@router.get("/ontology/graph")
def get_ontology_graph(
    domain: str | None = Query("revenue_reconciliation"),
    view: str = Query("full"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回实体-关系图谱数据（节点 + 边），供前端可视化。"""
    q = db.query(OntologyEntity).filter(OntologyEntity.status == 1)
    if domain:
        q = q.filter(OntologyEntity.domain == domain)
    entities = q.all()

    core_keys = {
        "sap_pg.public.sap_settlement_line",
        "dms_pg.public.dms_revenue_ledger",
        "fanruan_pg.public.fanruan_reconciliation",
        "dms_pg.public.dms_settlement_order",
        "sap_pg.public.sap_settlement",
    }
    if view == "core":
        entities = [e for e in entities if e.entity_key in core_keys]

    node_ids = {e.entity_key for e in entities}
    nodes = [
        {
            "id": e.entity_key,
            "label": e.label,
            "table_name": e.table_name,
            "datasource_code": e.datasource_code,
            "description": (e.description or "")[:120],
            "column_count": len(json.loads(e.columns_json or "[]")),
        }
        for e in entities
    ]

    rel_q = db.query(OntologyRelation).filter(OntologyRelation.status == 1)
    edges = []
    for r in rel_q.all():
        if r.from_entity in node_ids and r.to_entity in node_ids:
            edges.append(
                {
                    "id": r.id,
                    "source": r.from_entity,
                    "target": r.to_entity,
                    "from_column": r.from_column,
                    "to_column": r.to_column,
                    "relation_type": r.relation_type,
                    "label": _relation_edge_label(r.from_column, r.to_column),
                    "description": r.description,
                }
            )

    layers = [
        {"key": "fanruan_pg", "title": "帆软 BI", "color": "#f59e0b"},
        {"key": "sap_pg", "title": "SAP", "color": "#3b82f6"},
        {"key": "dms_pg", "title": "DMS", "color": "#10b981"},
        {"key": "knowledge", "title": "知识/异常", "color": "#8b5cf6"},
    ]
    return ok({"nodes": nodes, "edges": edges, "layers": layers, "view": view})


@router.get("/ontology/relations")
def list_relations(
    from_entity: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(OntologyRelation).filter(OntologyRelation.status == 1)
    if from_entity:
        q = q.filter(OntologyRelation.from_entity == from_entity)
    rows = q.all()
    return ok(
        [
            {
                "id": r.id,
                "from_entity": r.from_entity,
                "to_entity": r.to_entity,
                "from_column": r.from_column,
                "to_column": r.to_column,
                "relation_type": r.relation_type,
                "description": r.description,
            }
            for r in rows
        ]
    )


@router.post("/ontology/relations")
def create_relation(
    body: RelationCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    rid = str(uuid.uuid4())
    row = OntologyRelation(
        id=rid,
        from_entity=body.from_entity,
        to_entity=body.to_entity,
        from_column=body.from_column,
        to_column=body.to_column,
        relation_type=body.relation_type,
        description=body.description,
        create_by=user.username,
    )
    db.add(row)
    db.commit()
    return ok({"id": rid})


@router.delete("/ontology/relations/{relation_id}")
def delete_relation(
    relation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    row = db.get(OntologyRelation, relation_id)
    if not row:
        raise HTTPException(404, "关系不存在")
    row.status = 0
    db.commit()
    return ok({"deleted": relation_id})


@router.get("/ontology/rules")
def list_rules(
    domain: str | None = None,
    rule_type: str | None = None,
    effective_status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(OntologyDomainRule).filter(OntologyDomainRule.status == 1)
    if domain:
        q = q.filter(OntologyDomainRule.domain == domain)
    if rule_type:
        q = q.filter(OntologyDomainRule.rule_type == rule_type)
    if effective_status:
        q = q.filter(OntologyDomainRule.effective_status == effective_status)
    rows = q.order_by(OntologyDomainRule.priority).all()
    from app.models import RuleConfig

    rule_ids = [r.rule_config_id for r in rows if r.rule_config_id]
    rule_by_id: dict[str, RuleConfig] = {}
    if rule_ids:
        for rc in db.query(RuleConfig).filter(RuleConfig.id.in_(rule_ids)).all():
            rule_by_id[rc.id] = rc

    payload = []
    for r in rows:
        rc = rule_by_id.get(r.rule_config_id) if r.rule_config_id else None
        payload.append(
            {
                "id": r.id,
                "domain": r.domain,
                "entity_key": r.entity_key,
                "rule_type": r.rule_type,
                "rule_content": r.rule_content,
                "priority": r.priority,
                "risk_level": r.risk_level,
                "effective_status": r.effective_status,
                "version": r.version,
                "rule_config_id": r.rule_config_id,
                "bind_source": r.bind_source,
                "rule_engine_type": r.remark if r.bind_source == "rule_engine" else None,
                "rule_engine_name": rc.name if rc else None,
            }
        )
    return ok(payload)


@router.post("/ontology/rules")
def create_rule(
    body: RuleCreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    rid = str(uuid.uuid4())
    row = OntologyDomainRule(
        id=rid,
        domain=body.domain,
        entity_key=body.entity_key,
        rule_type=body.rule_type,
        rule_content=body.rule_content,
        priority=body.priority,
        risk_level=body.risk_level,
        effective_status="DRAFT",
        create_by=user.username,
    )
    db.add(row)
    db.commit()
    return ok({"id": rid})


@router.put("/ontology/rules/{rule_id}")
def update_rule(
    rule_id: str,
    body: RuleUpdateBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    row = db.get(OntologyDomainRule, rule_id)
    if not row:
        raise HTTPException(404, "规则不存在")
    if body.rule_content is not None:
        row.rule_content = body.rule_content
        row.version += 1
    if body.priority is not None:
        row.priority = body.priority
    if body.risk_level is not None:
        row.risk_level = body.risk_level
    row.update_by = user.username
    row.update_time = datetime.utcnow()
    db.commit()
    return ok({"id": rule_id, "version": row.version})


@router.post("/ontology/rules/{rule_id}/publish")
def publish_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    svc = RuleGovernanceService(db)
    try:
        row = svc.publish_rule(rule_id, approved_by=user.username)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ok({"id": row.id, "effective_status": row.effective_status})


@router.post("/ontology/rules/{rule_id}/archive")
def archive_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    row = RuleGovernanceService(db).archive_rule(rule_id)
    return ok({"id": row.id, "effective_status": row.effective_status})


@router.post("/ontology/rules/{rule_id}/rollback")
def rollback_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    row = RuleGovernanceService(db).rollback_rule(rule_id)
    return ok({"id": row.id, "version": row.version})


@router.post("/admin/ontology/reload")
def reload_ontology(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    stats = extract_all_fangtai_sources(db)
    emb = refresh_all_embeddings(db)
    poc_path = ""
    try:
        poc_path = str(resolve_poc_xlsx())
    except FileNotFoundError as exc:
        stats.errors.append(str(exc))
    return ok(
        {
            "entities_upserted": stats.entities_upserted,
            "relations_upserted": stats.relations_upserted,
            "rules_upserted": stats.rules_upserted,
            "embeddings_refreshed": emb,
            "poc_xlsx": poc_path,
            "errors": stats.errors,
        },
        message="A客户语义层抽取完成（种子 + Excel）",
    )


@router.get("/admin/ontology/stats")
def ontology_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ec = db.query(OntologyEntity).filter(OntologyEntity.status == 1).count()
    rc = db.query(OntologyRelation).filter(OntologyRelation.status == 1).count()
    rule_c = db.query(OntologyDomainRule).filter(OntologyDomainRule.status == 1).count()
    pub = (
        db.query(OntologyDomainRule)
        .filter(OntologyDomainRule.effective_status == "PUBLISHED")
        .count()
    )
    col_count = 0
    for ent in db.query(OntologyEntity).filter(OntologyEntity.status == 1).all():
        col_count += len(json.loads(ent.columns_json or "[]"))
    return ok(
        {
            "entity_count": ec,
            "column_count": col_count,
            "relation_count": rc,
            "rule_count": rule_c,
            "published_rule_count": pub,
        }
    )


@router.post("/ontology/similar")
def similar_entities(
    body: SimilarQueryBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    hits = find_similar_entities(db, body.query, top_k=body.top_k)
    return ok(hits)


@router.get("/ontology/prompt-preview")
def prompt_preview(
    domain: str = Query("revenue_reconciliation"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    text = DomainPromptBuilder(db).build(None, domain)
    return ok({"markdown": text})
