"""Parse skill.md and config.yaml into SkillMeta."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from agent_platform.exceptions import SkillParseError
from agent_platform.models.skill import SkillMeta

_TYPE_MAP = {
    "流程型": "process",
    "能力型": "ability",
    "知识型": "knowledge",
    "process": "process",
    "ability": "ability",
    "knowledge": "knowledge",
}

_META_PATTERNS: dict[str, re.Pattern[str]] = {
    "skill_id": re.compile(r"skill_id\**\s*[:：]\s*(\S+)", re.I),
    "name": re.compile(r"(?:^|\n)\s*[-*]*\s*name\**\s*[:：]\s*(.+)", re.I | re.M),
    "type": re.compile(r"type\**\s*[:：]\s*(.+)", re.I),
    "category": re.compile(r"category\**\s*[:：]\s*(.+)", re.I),
    "description": re.compile(r"description\**\s*[:：]\s*(.+)", re.I),
    "version": re.compile(r"version\**\s*[:：]\s*(\S+)", re.I),
    "status": re.compile(r"status\**\s*[:：]\s*(.+)", re.I),
    "tags": re.compile(r"tags\**\s*[:：]\s*\[([^\]]*)\]", re.I),
}


def _extract_json_block(text: str, heading: str) -> dict[str, Any]:
    """Extract first ```json block after a ### heading."""
    pattern = re.compile(
        rf"###\s*{re.escape(heading)}.*?\n+```json\s*\n(.*?)```",
        re.DOTALL | re.I,
    )
    match = pattern.search(text)
    if not match:
        return {}
    raw = match.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _parse_execution_steps(text: str) -> list[str]:
    """Parse numbered steps under ## 执行逻辑."""
    section = re.search(r"##\s*执行逻辑\s*\n(.*?)(?=\n##\s|\Z)", text, re.DOTALL | re.I)
    if not section:
        return []
    steps: list[str] = []
    for line in section.group(1).splitlines():
        m = re.match(r"^\s*\d+\.\s*(.+)", line.strip())
        if m:
            steps.append(m.group(1).strip())
    return steps


def _parse_dependencies(text: str) -> list[str]:
    section = re.search(r"##\s*依赖\s*\n(.*?)(?=\n##\s|\Z)", text, re.DOTALL | re.I)
    if not section:
        return []
    deps: list[str] = []
    for line in section.group(1).splitlines():
        line = line.strip().lstrip("-").strip()
        if line and not line.startswith("#"):
            deps.append(line)
    return deps


def _first_match(pattern: re.Pattern[str], text: str, default: str = "") -> str:
    m = pattern.search(text)
    return m.group(1).strip() if m else default


def _parse_tags(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,，]\s*", raw)
    return [p.strip().strip("'\"") for p in parts if p.strip()]


def load_config_yaml(package_dir: Path) -> dict[str, Any]:
    """Load config.yaml if present."""
    path = package_dir / "config.yaml"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def parse_skill_md(package_dir: Path) -> SkillMeta:
    """Parse skill.md in a skill package directory."""
    md_path = package_dir / "skill.md"
    if not md_path.is_file():
        raise SkillParseError(str(package_dir), "缺少 skill.md")

    text = md_path.read_text(encoding="utf-8")
    package_code = package_dir.name

    skill_id = _first_match(_META_PATTERNS["skill_id"], text) or f"skill-{package_code}"
    name = _first_match(_META_PATTERNS["name"], text) or package_code
    type_raw = _first_match(_META_PATTERNS["type"], text)
    skill_type = _TYPE_MAP.get(type_raw.strip(), "ability")
    category = _first_match(_META_PATTERNS["category"], text) or "未分类"
    description = _first_match(_META_PATTERNS["description"], text)
    version = _first_match(_META_PATTERNS["version"], text) or "0.0.0"
    status = _first_match(_META_PATTERNS["status"], text) or "draft"
    tags_raw = _first_match(_META_PATTERNS["tags"], text)
    tags = _parse_tags(tags_raw)

    input_schema = _extract_json_block(text, "输入")
    output_schema = _extract_json_block(text, "输出")
    execution_steps = _parse_execution_steps(text)
    dependencies = _parse_dependencies(text)
    config = load_config_yaml(package_dir)

    return SkillMeta(
        skill_id=skill_id,
        name=name,
        skill_type=skill_type,
        category=category,
        description=description,
        tags=tags,
        version=version,
        status=status,
        input_schema=input_schema,
        output_schema=output_schema,
        execution_steps=execution_steps,
        dependencies=dependencies,
        config=config,
        package_code=package_code,
        skill_md_path=str(md_path),
    )
