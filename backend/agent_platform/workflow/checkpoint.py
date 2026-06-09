# File: agent_platform/workflow/checkpoint.py
"""LangGraph checkpointer — AsyncSqliteSaver (async) with MemorySaver fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_platform.logging_setup import get_logger

logger = get_logger("workflow.checkpoint")

_CHECKPOINTER: Any = None
_SQLITE_CONN: Any = None


def _sqlite_path() -> Path:
    backend_dir = Path(__file__).resolve().parent.parent.parent
    return backend_dir / "data" / "langgraph_checkpoints.db"


async def init_workflow_checkpointer() -> Any:
    """Initialize durable async SQLite checkpointer (call from FastAPI lifespan)."""
    global _CHECKPOINTER, _SQLITE_CONN
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    sqlite_path = _sqlite_path()
    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        _SQLITE_CONN = await aiosqlite.connect(str(sqlite_path))
        saver = AsyncSqliteSaver(_SQLITE_CONN)
        await saver.setup()
        _CHECKPOINTER = saver
        logger.info(
            "LangGraph checkpointer: AsyncSqliteSaver",
            extra_fields={"path": str(sqlite_path)},
        )
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver

        _CHECKPOINTER = MemorySaver()
        logger.info(
            "LangGraph checkpointer: MemorySaver "
            "(install aiosqlite + langgraph-checkpoint-sqlite for durable checkpoints)"
        )
    return _CHECKPOINTER


def get_workflow_checkpointer():
    """
    Return shared checkpointer for graph.compile().
    Prefer init_workflow_checkpointer() at app startup; otherwise MemorySaver.
    """
    if _CHECKPOINTER is not None:
        return _CHECKPOINTER

    from langgraph.checkpoint.memory import MemorySaver

    logger.warning(
        "LangGraph checkpointer not initialized; using in-memory MemorySaver "
        "(call init_workflow_checkpointer during app startup)"
    )
    return MemorySaver()
