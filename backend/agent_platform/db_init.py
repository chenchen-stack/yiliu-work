"""Ensure platform ORM tables exist."""

from app.database import Base, engine


def init_platform_tables() -> None:
    from agent_platform.models.trace import PlatformTraceORM, PlatformWorkflowORM  # noqa: F401

    Base.metadata.create_all(
        bind=engine,
        tables=[PlatformTraceORM.__table__, PlatformWorkflowORM.__table__],
    )
