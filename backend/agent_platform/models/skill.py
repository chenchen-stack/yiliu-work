"""Skill metadata models (parsed from skill.md + config.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillMeta:
    """Parsed skill.md metadata and interface definition."""

    skill_id: str
    name: str
    skill_type: str  # process | ability | knowledge (流程型/能力型/知识型)
    category: str
    description: str
    tags: list[str]
    version: str
    status: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    execution_steps: list[str]
    dependencies: list[str]
    config: dict[str, Any]
    package_code: str  # folder name under skills_dir
    skill_md_path: str = ""

    @property
    def type_label(self) -> str:
        """Chinese label for skill type."""
        return {
            "process": "流程型",
            "ability": "能力型",
            "knowledge": "知识型",
        }.get(self.skill_type, self.skill_type)


def skill_meta_to_dict(meta: SkillMeta, *, include_execution: bool = True) -> dict[str, Any]:
    """Serialize SkillMeta for API responses."""
    body: dict[str, Any] = {
        "skill_id": meta.skill_id,
        "package_code": meta.package_code,
        "name": meta.name,
        "type": meta.type_label,
        "skill_type": meta.skill_type,
        "category": meta.category,
        "description": meta.description,
        "tags": meta.tags,
        "version": meta.version,
        "status": meta.status,
        "input_schema": meta.input_schema,
        "output_schema": meta.output_schema,
        "dependencies": meta.dependencies,
        "config": meta.config,
    }
    if include_execution:
        body["execution_steps"] = meta.execution_steps
    return body
