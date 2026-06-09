"""Ontology / field mapping translation service."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from agent_platform.logging_setup import get_logger

logger = get_logger("ontology_translate")


def translate_records(
    db: Session,
    *,
    business_center_id: str | None,
    records: list[dict[str, Any]],
    side: str = "business",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply mapping registry translation to raw records."""
    from app.services.mapping_engine import MappingRegistry, enrich_records

    registry = MappingRegistry.load(db, business_center_id or "")
    enriched = enrich_records(records, side, registry)
    report = {
        "side": side,
        "count_in": len(records),
        "count_out": len(enriched),
        "profile": registry.profile_for(side) if hasattr(registry, "profile_for") else side,
    }
    logger.info("ontology translate", extra_fields=report)
    return enriched, report
