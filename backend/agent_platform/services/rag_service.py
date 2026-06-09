"""Knowledge RAG retrieval (ChromaDB + existing case assets fallback)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from agent_platform.config import platform_settings
from agent_platform.logging_setup import get_logger

logger = get_logger("rag_service")


async def search(
    query: str,
    *,
    top_k: int | None = None,
    knowledge_base_ids: list[str] | None = None,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    """Retrieve relevant chunks; falls back to SQL case_assets when Chroma empty."""
    k = top_k or platform_settings.rag_top_k_default
    chroma_hits = _search_chroma(query, top_k=k)
    if chroma_hits:
        return chroma_hits
    if db is not None:
        return _search_case_assets(db, query, top_k=k, kb_ids=knowledge_base_ids)
    return []


def _search_chroma(query: str, *, top_k: int) -> list[dict[str, Any]]:
    persist = platform_settings.chroma_persist_dir
    if not persist.exists():
        return []
    try:
        import chromadb
    except ImportError:
        return []

    client = chromadb.PersistentClient(path=str(persist))
    try:
        collection = client.get_or_create_collection("fangtai_cases")
    except Exception:  # noqa: BLE001
        return []

    if collection.count() == 0:
        return []

    results = collection.query(query_texts=[query], n_results=min(top_k, collection.count()))
    docs = results.get("documents") or [[]]
    metas = results.get("metadatas") or [[]]
    dists = results.get("distances") or [[]]
    hits: list[dict[str, Any]] = []
    for doc, meta, dist in zip(docs[0], metas[0], dists[0]):
        hits.append(
            {
                "content": doc,
                "metadata": meta or {},
                "score": 1.0 - float(dist) if dist is not None else None,
                "source": "chroma",
            }
        )
    logger.info("chroma search", extra_fields={"query_len": len(query), "hits": len(hits)})
    return hits


def _search_case_assets(
    db: Session,
    query: str,
    *,
    top_k: int,
    kb_ids: list[str] | None,
) -> list[dict[str, Any]]:
    from app.models import CaseAsset

    q = db.query(CaseAsset).filter(CaseAsset.status == "published")
    if kb_ids:
        q = q.filter(CaseAsset.knowledge_base_id.in_(kb_ids))
    rows = q.order_by(CaseAsset.updated_at.desc()).limit(50).all()
    tokens = [t for t in query.replace("，", " ").split() if len(t) >= 2]
    scored: list[tuple[float, CaseAsset]] = []
    for row in rows:
        text = (
            f"{row.confirmed_type or ''} {row.root_cause or ''} "
            f"{row.handling_result or ''} {row.reusable_rule_suggestion or ''}"
        )
        score = sum(1 for t in tokens if t in text)
        if score > 0 or not tokens:
            scored.append((float(score), row))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits: list[dict[str, Any]] = []
    for score, row in scored[:top_k]:
        hits.append(
            {
                "case_id": row.id,
                "title": row.confirmed_type,
                "content": (row.root_cause or row.handling_result or "")[:500],
                "metadata": {"knowledge_base_id": row.knowledge_base_id},
                "score": score,
                "source": "case_assets",
            }
        )
    logger.info("case_assets search", extra_fields={"hits": len(hits)})
    return hits
