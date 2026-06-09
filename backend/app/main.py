import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import demo_router, public_router, router as admin_router
from app.api.auth import dashboard_router, router as auth_router
from app.api.agents import admin_router as agents_admin_router
from app.api.agents import router as agents_router
from app.api.skill_packages import router as skill_packages_router
from app.api.skill_test_chat import router as skill_test_chat_router
from agent_platform.main import router as agent_platform_router
from app.api.ontology_api import router as ontology_router
from app.ontology_config import ontology_settings
from app.api.chat import router as chat_router
from app.api.differences import processing_router, router as differences_router
from app.api.reports import router as reports_router
from app.api.tasks import router as tasks_router
from app.config import settings
from app.database import SessionLocal, init_db
from app.services.platform_seed import seed_platform, seed_users


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_users(db)
        seed_platform(db)
        from app.services.llm_config_service import ensure_llm_config

        ensure_llm_config(db)
        from app.services.agent_seed_upgrade import ensure_chat_agent_available, upgrade_default_agent

        upgrade_default_agent(db)
        ensure_chat_agent_available(db)
    finally:
        db.close()
    from app.api.tasks import resume_stuck_tasks_on_startup

    asyncio.create_task(resume_stuck_tasks_on_startup())
    from agent_platform.core.registry import skill_registry
    from agent_platform.db_init import init_platform_tables

    init_platform_tables()
    skill_registry.reload()
    from agent_platform.workflow.checkpoint import init_workflow_checkpointer

    await init_workflow_checkpointer()
    if ontology_settings.extract_on_startup:
        from app.ontology_models import OntologyEntity
        from app.services.ontology_extractor import extract_all_fangtai_sources
        from app.services.entity_embedding_service import refresh_all_embeddings

        db2 = SessionLocal()
        try:
            if db2.query(OntologyEntity).count() == 0:
                extract_all_fangtai_sources(db2)
                refresh_all_embeddings(db2)
        except Exception:  # noqa: BLE001
            pass
        finally:
            db2.close()
    yield


app = FastAPI(title=settings.app_name, version="0.2.0-mvp", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(public_router, prefix="/api/v1")
app.include_router(demo_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(differences_router, prefix="/api/v1")
app.include_router(processing_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")
app.include_router(agents_admin_router, prefix="/api/v1")
app.include_router(skill_packages_router, prefix="/api/v1")
app.include_router(skill_test_chat_router, prefix="/api/v1")
app.include_router(agent_platform_router, prefix="/api/v1")
app.include_router(ontology_router, prefix="/api/v1")


@app.get("/")
def root():
    return {"name": settings.app_name, "version": "0.2.0-mvp", "docs": "/docs"}


@app.get("/health")
def health():
    from app.services.mapping_engine import _load_poc_profiles

    agent_routes = [
        getattr(r, "path", "")
        for r in app.routes
        if getattr(r, "path", "").startswith("/api/v1/admin/agents")
    ]
    from agent_platform.core.registry import skill_registry

    platform_routes = [getattr(r, "path", "") for r in app.routes if "/skills" in getattr(r, "path", "")]
    skill_test_routes = [
        getattr(r, "path", "")
        for r in app.routes
        if getattr(r, "path", "").startswith("/api/v1/skill-test")
    ]
    return {
        "status": "ok",
        "mapping_engine": "poc-cn-v2" if _load_poc_profiles() else "legacy",
        "agents_api": "v2" if agent_routes else "legacy",
        "skill_test_chat": bool(skill_test_routes),
        "agent_platform": {
            "skills_registered": len(skill_registry.list_all()),
            "routes": bool(platform_routes),
        },
        "ontology": _ontology_health(),
    }


def _ontology_health() -> dict:
    try:
        from app.ontology_models import OntologyEntity
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            n = db.query(OntologyEntity).filter(OntologyEntity.status == 1).count()
        finally:
            db.close()
        return {"status": "ok", "entities": n}
    except Exception:  # noqa: BLE001
        return {"status": "unavailable", "entities": 0}

