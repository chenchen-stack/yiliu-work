"""Skill Registry — scan skill_packages, index, query, hot reload."""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from agent_platform.config import platform_settings
from agent_platform.core.parser import parse_skill_md
from agent_platform.exceptions import SkillNotFoundError
from agent_platform.logging_setup import get_logger
from agent_platform.models.skill import SkillMeta, skill_meta_to_dict

logger = get_logger("registry")


class SkillRegistry:
    """In-memory skill index built from skill.md files."""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self.skills_dir = skills_dir or platform_settings.skills_dir
        self._by_id: dict[str, SkillMeta] = {}
        self._by_code: dict[str, SkillMeta] = {}
        self._by_category: dict[str, list[SkillMeta]] = {}
        self._by_type: dict[str, list[SkillMeta]] = {}
        self._lock = Lock()

    def reload(self) -> int:
        """Scan skills_dir and rebuild all indexes. Returns skill count."""
        with self._lock:
            self._by_id.clear()
            self._by_code.clear()
            self._by_category.clear()
            self._by_type.clear()

            if not self.skills_dir.is_dir():
                logger.warning("skills_dir missing", extra_fields={"path": str(self.skills_dir)})
                return 0

            count = 0
            for child in sorted(self.skills_dir.iterdir()):
                if not child.is_dir() or not (child / "skill.md").is_file():
                    continue
                try:
                    meta = parse_skill_md(child)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "parse failed",
                        extra_fields={"package": child.name, "error": str(exc)},
                    )
                    continue
                self._register(meta)
                count += 1

            logger.info("registry reloaded", extra_fields={"count": count})
            return count

    def _register(self, meta: SkillMeta) -> None:
        self._by_id[meta.skill_id] = meta
        self._by_code[meta.package_code] = meta
        self._by_category.setdefault(meta.category, []).append(meta)
        self._by_type.setdefault(meta.skill_type, []).append(meta)

    def get(self, skill_id: str) -> SkillMeta:
        """Resolve by skill_id or package_code."""
        key = skill_id.strip()
        meta = self._by_id.get(key) or self._by_code.get(key)
        if not meta and key.startswith("skill-"):
            meta = self._by_code.get(key.replace("skill-", "", 1))
        if not meta:
            raise SkillNotFoundError(key)
        return meta

    def list_all(self) -> list[SkillMeta]:
        return list(self._by_id.values())

    def query(
        self,
        *,
        category: str | None = None,
        skill_type: str | None = None,
        tags: list[str] | None = None,
    ) -> list[SkillMeta]:
        """Filter skills by category, type (process/ability/knowledge), and tags."""
        pool = self.list_all()
        if category:
            pool = [m for m in pool if m.category == category]
        if skill_type:
            norm = skill_type.strip()
            pool = [m for m in pool if m.skill_type == norm or m.type_label == norm]
        if tags:
            tag_set = {t.lower() for t in tags}
            pool = [m for m in pool if tag_set.intersection({t.lower() for t in m.tags})]
        return pool

    def to_api_list(self) -> list[dict]:
        return [skill_meta_to_dict(m, include_execution=False) for m in self.list_all()]

    def to_api_detail(self, skill_id: str) -> dict:
        meta = self.get(skill_id)
        detail = skill_meta_to_dict(meta, include_execution=True)
        if meta.skill_md_path:
            detail["skill_md"] = Path(meta.skill_md_path).read_text(encoding="utf-8")
        return detail


# Singleton used by FastAPI lifespan and executors
skill_registry = SkillRegistry()
