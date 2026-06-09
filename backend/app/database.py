from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATA_DIR, settings

SCHEMA_VERSION = "mvp-p0-v1"
VERSION_FILE = DATA_DIR / ".schema_version"

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 轻量迁移：对已存在的表补齐新增列，避免 drop 破坏演示数据
# 格式: { 表名: { 列名: "SQLite 列定义" } }
_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "rule_configs": {
        "threshold": "FLOAT DEFAULT 0",
        "params": "JSON",
    },
    "conversations": {
        "user_id": "VARCHAR(36)",
    },
    "agent_configs": {
        "description": "TEXT",
        "persona": "TEXT",
        "knowledge_base_ids": "JSON",
        "data_source_scope": "JSON",
        "linked_workflow_id": "VARCHAR(36)",
        "output_format": "VARCHAR(30) DEFAULT 'natural'",
        "scope": "VARCHAR(30) DEFAULT 'team_published'",
        "owner_id": "VARCHAR(36)",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    },
    "case_assets": {
        "knowledge_base_id": "VARCHAR(50)",
        "source_kind": "VARCHAR(20) DEFAULT 'diff_archive'",
        "source_file": "VARCHAR(255)",
    },
    "ontology_domain_rule": {
        "rule_config_id": "VARCHAR(36)",
        "bind_source": "VARCHAR(30)",
    },
    "llm_configs": {
        "agent_chat_json": "JSON",
    },
}


def _apply_additive_migrations():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for col, ddl in columns.items():
                if col not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def init_db():
    from app import models  # noqa: F401
    from app import ontology_models  # noqa: F401

    current = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else None
    if current != SCHEMA_VERSION:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        VERSION_FILE.write_text(SCHEMA_VERSION, encoding="utf-8")
    else:
        # 新增表（如 skill_invocations）自动创建；新增列通过轻量迁移补齐，保留既有数据
        Base.metadata.create_all(bind=engine)
        _apply_additive_migrations()

