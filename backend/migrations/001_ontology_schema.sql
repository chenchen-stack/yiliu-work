-- 企业数据语义层（SQLite / PostgreSQL 通用 DDL）
-- PostgreSQL 启用 pgvector 时可执行: CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ontology_entity (
    id TEXT PRIMARY KEY,
    datasource_code TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'EXCEL',
    schema_name TEXT,
    table_name TEXT NOT NULL,
    entity_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    description TEXT,
    columns_json TEXT NOT NULL DEFAULT '[]',
    aliases_json TEXT DEFAULT '[]',
    sample_queries_json TEXT DEFAULT '[]',
    domain TEXT,
    data_sensitivity TEXT NOT NULL DEFAULT 'internal',
    prompt_visible INTEGER NOT NULL DEFAULT 1,
    status INTEGER NOT NULL DEFAULT 1,
    remark TEXT,
    create_by TEXT,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_by TEXT,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ontology_relation (
    id TEXT PRIMARY KEY,
    from_entity TEXT NOT NULL,
    to_entity TEXT NOT NULL,
    from_column TEXT NOT NULL,
    to_column TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'MANUAL',
    description TEXT,
    status INTEGER NOT NULL DEFAULT 1,
    remark TEXT,
    create_by TEXT,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_by TEXT,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_entity, to_entity, from_column)
);

CREATE TABLE IF NOT EXISTS ontology_domain_rule (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    entity_key TEXT,
    rule_type TEXT NOT NULL,
    rule_content TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 5,
    risk_level TEXT NOT NULL DEFAULT 'LOW',
    effective_status TEXT NOT NULL DEFAULT 'DRAFT',
    version INTEGER NOT NULL DEFAULT 1,
    approved_by TEXT,
    approved_time TIMESTAMP,
    examples_json TEXT,
    status INTEGER NOT NULL DEFAULT 1,
    remark TEXT,
    create_by TEXT,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_by TEXT,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ontology_entity_embedding (
    id TEXT PRIMARY KEY,
    entity_key TEXT NOT NULL,
    embedding_json TEXT,
    embedding_text_hash TEXT,
    status INTEGER NOT NULL DEFAULT 1,
    create_by TEXT,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_by TEXT,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ontology_entity_domain ON ontology_entity(domain);
CREATE INDEX IF NOT EXISTS idx_ontology_entity_datasource ON ontology_entity(datasource_code);
CREATE INDEX IF NOT EXISTS idx_ontology_rule_domain ON ontology_domain_rule(domain, effective_status);
CREATE INDEX IF NOT EXISTS idx_ontology_relation_from ON ontology_relation(from_entity);
