"""SQLAlchemy models for enterprise ontology semantic layer."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OntologyEntity(Base):
    __tablename__ = "ontology_entity"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    datasource_code: Mapped[str] = mapped_column(String(80), index=True)
    source_type: Mapped[str] = mapped_column(String(30), default="EXCEL")
    schema_name: Mapped[str | None] = mapped_column(String(80))
    table_name: Mapped[str] = mapped_column(String(200))
    entity_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    columns_json: Mapped[str] = mapped_column(Text, default="[]")
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    sample_queries_json: Mapped[str] = mapped_column(Text, default="[]")
    domain: Mapped[str | None] = mapped_column(String(80), index=True)
    data_sensitivity: Mapped[str] = mapped_column(String(30), default="internal")
    prompt_visible: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[int] = mapped_column(Integer, default=1)
    remark: Mapped[str | None] = mapped_column(Text)
    create_by: Mapped[str | None] = mapped_column(String(50))
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    update_by: Mapped[str | None] = mapped_column(String(50))
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OntologyRelation(Base):
    __tablename__ = "ontology_relation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    from_entity: Mapped[str] = mapped_column(String(300), index=True)
    to_entity: Mapped[str] = mapped_column(String(300), index=True)
    from_column: Mapped[str] = mapped_column(String(120))
    to_column: Mapped[str] = mapped_column(String(120))
    relation_type: Mapped[str] = mapped_column(String(20), default="MANUAL")
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[int] = mapped_column(Integer, default=1)
    remark: Mapped[str | None] = mapped_column(Text)
    create_by: Mapped[str | None] = mapped_column(String(50))
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    update_by: Mapped[str | None] = mapped_column(String(50))
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OntologyDomainRule(Base):
    __tablename__ = "ontology_domain_rule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    domain: Mapped[str] = mapped_column(String(80), index=True)
    entity_key: Mapped[str | None] = mapped_column(String(300))
    rule_type: Mapped[str] = mapped_column(String(30))
    rule_content: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")
    effective_status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_by: Mapped[str | None] = mapped_column(String(50))
    approved_time: Mapped[datetime | None] = mapped_column(DateTime)
    examples_json: Mapped[str | None] = mapped_column(Text)
    rule_config_id: Mapped[str | None] = mapped_column(String(36), index=True)
    bind_source: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[int] = mapped_column(Integer, default=1)
    remark: Mapped[str | None] = mapped_column(Text)
    create_by: Mapped[str | None] = mapped_column(String(50))
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    update_by: Mapped[str | None] = mapped_column(String(50))
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OntologyEntityEmbedding(Base):
    __tablename__ = "ontology_entity_embedding"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_key: Mapped[str] = mapped_column(String(300), index=True)
    embedding_json: Mapped[str | None] = mapped_column(Text)
    embedding_text_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[int] = mapped_column(Integer, default=1)
    create_by: Mapped[str | None] = mapped_column(String(50))
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    update_by: Mapped[str | None] = mapped_column(String(50))
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
