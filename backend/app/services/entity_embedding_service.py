"""Entity embedding — hash + keyword fallback (no pgvector required for MVP)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.ontology_models import OntologyEntity, OntologyEntityEmbedding


def _embed_text(text: str, dim: int = 64) -> list[float]:
    """Deterministic bag-of-chars vector for local similarity (no external API)."""
    vec = [0.0] * dim
    tokens = re.findall(r"[\u4e00-\u9fff\w]+", text.lower())
    for tok in tokens:
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]


def _entity_text(ent: OntologyEntity) -> str:
    aliases = json.loads(ent.aliases_json or "[]")
    queries = json.loads(ent.sample_queries_json or "[]")
    return " ".join(
        [ent.entity_key, ent.label, ent.description or "", *aliases, *[str(q) for q in queries]]
    )


def embed_entity(db: Session, entity: OntologyEntity) -> OntologyEntityEmbedding:
    text = _entity_text(entity)
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:32]
    vec = _embed_text(text)
    row = (
        db.query(OntologyEntityEmbedding)
        .filter(OntologyEntityEmbedding.entity_key == entity.entity_key)
        .first()
    )
    if row:
        row.embedding_json = json.dumps(vec)
        row.embedding_text_hash = text_hash
    else:
        row = OntologyEntityEmbedding(
            id=str(uuid.uuid4()),
            entity_key=entity.entity_key,
            embedding_json=json.dumps(vec),
            embedding_text_hash=text_hash,
        )
        db.add(row)
    db.commit()
    return row


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot


def find_similar_entities(db: Session, query_text: str, *, top_k: int = 5) -> list[dict[str, Any]]:
    qvec = _embed_text(query_text)
    hits: list[tuple[float, OntologyEntity]] = []
    entities = db.query(OntologyEntity).filter(OntologyEntity.status == 1).all()
    for ent in entities:
        aliases = json.loads(ent.aliases_json or "[]")
        kw_score = sum(1 for a in aliases if a and a in query_text)
        emb = (
            db.query(OntologyEntityEmbedding)
            .filter(OntologyEntityEmbedding.entity_key == ent.entity_key)
            .first()
        )
        score = float(kw_score)
        if emb and emb.embedding_json:
            ev = json.loads(emb.embedding_json)
            score += _cosine(qvec, ev) * 2
        if ent.label in query_text or ent.table_name in query_text:
            score += 1.5
        if score > 0:
            hits.append((score, ent))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "entity_key": e.entity_key,
            "label": e.label,
            "score": round(s, 3),
            "domain": e.domain,
        }
        for s, e in hits[:top_k]
    ]


def refresh_all_embeddings(db: Session) -> int:
    n = 0
    for ent in db.query(OntologyEntity).filter(OntologyEntity.status == 1).all():
        embed_entity(db, ent)
        n += 1
    return n
