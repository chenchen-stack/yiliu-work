"""Skill Package Engine — 加载、解析、验证、执行 Skill 包。

一个 Skill 包 = 能让中台直接调用的最小能力单元。
给一段输入，产一段输出，中间逻辑可重复。

Skill 包的两个铁律：
  1. 输入输出必须结构化 — JSON 进 JSON 出
  2. Skill 不存数据，只处理数据

物理结构（方太标准 Skill 包）：
  skill_packages/<code>/
  ├── skill.md              ← 说明书 + 接口 + 执行逻辑（主文档）
  ├── skill.yaml            ← 机器可读元信息（供中台加载）
  ├── config.yaml           ← 可配置参数
  ├── execute.py            ← 可执行逻辑（如有）
  ├── references/           ← 参考数据
  └── scripts/              ← 自定义脚本
"""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

SKILL_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent / "skill_packages"


@dataclass
class SkillManifest:
    """skill.yaml 解析后的结构化元信息"""
    id: str
    code: str
    name: str
    description: str
    type: str  # ability / knowledge / flow
    version: int
    status: str
    category: str = ""
    creator: str = ""
    created_at: str = ""

    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    config_schema: dict = field(default_factory=dict)
    dependencies: dict = field(default_factory=dict)
    tests: list[dict] = field(default_factory=list)

    package_path: str = ""
    skill_md_path: str = ""


@dataclass
class SkillExecutionResult:
    """Skill 执行结果"""
    success: bool
    output: dict
    duration_ms: int
    error: str | None = None
    skill_code: str = ""
    skill_version: int = 0


@dataclass
class SkillTestResult:
    """单条测试用例执行结果"""
    name: str
    passed: bool
    expected: dict
    actual: dict
    duration_ms: int
    error: str | None = None


def _load_config_yaml(package_dir: Path) -> dict:
    config_path = package_dir / "config.yaml"
    if not config_path.is_file():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def load_manifest(package_dir: Path) -> SkillManifest:
    """从 skill.yaml 加载 Skill 元信息；config.yaml 合并为 config_schema。"""
    yaml_path = package_dir / "skill.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"skill.yaml 不存在: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    config_schema = raw.get("config") or {}
    file_config = _load_config_yaml(package_dir)
    if file_config:
        config_schema = {**config_schema, **file_config}

    skill_md = package_dir / "skill.md"
    return SkillManifest(
        id=raw.get("id", ""),
        code=raw.get("code", package_dir.name),
        name=raw.get("name", ""),
        description=raw.get("description", ""),
        type=raw.get("type", "ability"),
        version=raw.get("version", 1),
        status=raw.get("status", "draft"),
        category=str(raw.get("category") or ""),
        creator=raw.get("creator", ""),
        created_at=raw.get("created_at", ""),
        input_schema=raw.get("input", {}),
        output_schema=raw.get("output", {}),
        config_schema=config_schema,
        dependencies=raw.get("dependencies", {}),
        tests=raw.get("tests", []),
        package_path=str(package_dir),
        skill_md_path=str(skill_md) if skill_md.is_file() else "",
    )


def read_skill_markdown(skill_code: str) -> str | None:
    """读取 Skill 包 skill.md 全文（供管理后台详情展示）。"""
    md_path = SKILL_PACKAGES_DIR / skill_code / "skill.md"
    if not md_path.is_file():
        return None
    return md_path.read_text(encoding="utf-8")


def load_executor(package_dir: Path) -> Callable[[dict, dict | None], dict] | None:
    """动态加载 execute.py 中的 execute 函数"""
    exec_path = package_dir / "execute.py"
    if not exec_path.exists():
        return None

    spec = importlib.util.spec_from_file_location(
        f"skill_pkg_{package_dir.name}",
        str(exec_path),
    )
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fn = getattr(module, "execute", None)
    if not callable(fn):
        return None
    return fn


def discover_packages() -> list[SkillManifest]:
    """扫描 skill_packages 目录，返回所有 Skill 清单"""
    if not SKILL_PACKAGES_DIR.exists():
        return []

    results = []
    for item in sorted(SKILL_PACKAGES_DIR.iterdir()):
        if not item.is_dir():
            continue
        if not (item / "skill.yaml").is_file() and not (item / "skill.md").is_file():
            continue
        if not (item / "skill.yaml").is_file():
            logger.warning("Skill 包 %s 缺少 skill.yaml，跳过 API 加载", item.name)
            continue
        try:
            manifest = load_manifest(item)
            results.append(manifest)
        except Exception as e:
            logger.warning("Skill 包加载失败 %s: %s", item.name, e)
    return results


def install_skill_package_zip(data: bytes) -> SkillManifest:
    """解压 Skill 包 zip 并安装到 skill_packages/<code>/（需含 skill.yaml）。"""
    if not data:
        raise ValueError("上传文件为空")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "upload.zip"
        zip_path.write_bytes(data)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_path)
        except zipfile.BadZipFile as exc:
            raise ValueError("请上传有效的 .zip 压缩包") from exc

        yaml_files = list(tmp_path.rglob("skill.yaml"))
        if not yaml_files:
            raise ValueError("压缩包内未找到 skill.yaml")

        pkg_dir = yaml_files[0].parent
        if pkg_dir == tmp_path and len(yaml_files) > 1:
            subdirs = [p.parent for p in yaml_files if p.parent != tmp_path]
            if subdirs:
                pkg_dir = subdirs[0]

        preview = load_manifest(pkg_dir)
        code = (preview.code or pkg_dir.name).strip()
        if not code or not code.replace("_", "").replace("-", "").isalnum():
            raise ValueError("skill.yaml 中 code 无效")

        target = SKILL_PACKAGES_DIR / code
        SKILL_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(pkg_dir, target)
        _write_manifest_status(target, "draft")
        return load_manifest(target)


def _write_manifest_status(package_dir: Path, status: str) -> None:
    """更新 skill.yaml 中的 status 字段。"""
    yaml_path = package_dir / "skill.yaml"
    if not yaml_path.is_file():
        return
    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raw = {}
    raw["status"] = status
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)


def _sync_skill_db_row(db, manifest: SkillManifest, status: str) -> None:
    from app.models import Skill

    row = db.query(Skill).filter(Skill.code == manifest.code).first()
    if row:
        row.status = status
        row.name = manifest.name or row.name
        row.type = manifest.type or row.type
        row.version = manifest.version or row.version
    else:
        import uuid

        db.add(
            Skill(
                id=str(uuid.uuid4()),
                name=manifest.name or manifest.code,
                code=manifest.code,
                type=manifest.type or "ability",
                status=status,
                version=manifest.version or 1,
            )
        )


_SKILL_LIFECYCLE: dict[str, str] = {
    "submit_review": "pending_review",
    "publish": "published",
    "offline": "offline",
    "rollback": "draft",
}


def transition_skill_status(skill_code: str, action: str, db) -> SkillManifest:
    """Skill 包状态流转：草稿 → 待审核 → 已发布。"""
    target_status = _SKILL_LIFECYCLE.get(action)
    if not target_status:
        raise ValueError(f"不支持的操作: {action}")

    package_dir = SKILL_PACKAGES_DIR / skill_code
    if not package_dir.is_dir():
        raise ValueError(f"Skill 包不存在: {skill_code}")

    manifest = load_manifest(package_dir)
    current = (manifest.status or "draft").lower()
    allowed: dict[str, set[str]] = {
        "draft": {"submit_review"},
        "pending_review": {"publish", "rollback"},
        "published": {"offline"},
        "offline": {"publish"},
        "testing": {"publish", "rollback"},
    }
    if action not in allowed.get(current, set()):
        raise ValueError(f"当前状态「{current}」不可执行 {action}")

    _write_manifest_status(package_dir, target_status)
    manifest = load_manifest(package_dir)
    _sync_skill_db_row(db, manifest, target_status)
    db.commit()
    try:
        from agent_platform.core.registry import skill_registry

        skill_registry.reload()
    except Exception:  # noqa: BLE001
        pass
    return manifest


def execute_skill(
    skill_code: str,
    input_data: dict,
    config: dict | None = None,
) -> SkillExecutionResult:
    """结构化调用 Skill 包 — JSON 进、JSON 出。"""

    package_dir = SKILL_PACKAGES_DIR / skill_code
    if not package_dir.exists():
        return SkillExecutionResult(
            success=False,
            output={},
            duration_ms=0,
            error=f"Skill 包不存在: {skill_code}",
            skill_code=skill_code,
        )

    manifest = load_manifest(package_dir)
    executor = load_executor(package_dir)

    if not executor:
        return SkillExecutionResult(
            success=False,
            output={},
            duration_ms=0,
            error=f"Skill 包无 execute.py 或无 execute() 函数: {skill_code}",
            skill_code=skill_code,
            skill_version=manifest.version,
        )

    start = time.perf_counter()
    try:
        output = executor(input_data, config)
        elapsed = int((time.perf_counter() - start) * 1000)

        if not isinstance(output, dict):
            return SkillExecutionResult(
                success=False,
                output={"raw": str(output)},
                duration_ms=elapsed,
                error="execute() 必须返回 dict (JSON 进 JSON 出)",
                skill_code=skill_code,
                skill_version=manifest.version,
            )

        return SkillExecutionResult(
            success=True,
            output=output,
            duration_ms=elapsed,
            skill_code=skill_code,
            skill_version=manifest.version,
        )
    except Exception as e:
        elapsed = int((time.perf_counter() - start) * 1000)
        logger.exception("Skill 执行失败 %s", skill_code)
        return SkillExecutionResult(
            success=False,
            output={},
            duration_ms=elapsed,
            error=str(e),
            skill_code=skill_code,
            skill_version=manifest.version,
        )


def run_skill_tests(skill_code: str) -> list[SkillTestResult]:
    """执行 Skill 包内置测试用例"""
    package_dir = SKILL_PACKAGES_DIR / skill_code
    manifest = load_manifest(package_dir)
    executor = load_executor(package_dir)

    if not executor:
        return [SkillTestResult(
            name="加载检查",
            passed=False,
            expected={},
            actual={},
            duration_ms=0,
            error="无 execute.py 或无 execute() 函数",
        )]

    results = []
    for test_case in manifest.tests:
        name = test_case.get("name", "unnamed")
        input_data = test_case.get("input", {})
        expected = test_case.get("expected", {})
        config = test_case.get("config")

        start = time.perf_counter()
        try:
            actual = executor(input_data, config)
            elapsed = int((time.perf_counter() - start) * 1000)

            passed = _check_expected(expected, actual)
            results.append(SkillTestResult(
                name=name,
                passed=passed,
                expected=expected,
                actual=actual,
                duration_ms=elapsed,
            ))
        except Exception as e:
            elapsed = int((time.perf_counter() - start) * 1000)
            results.append(SkillTestResult(
                name=name,
                passed=False,
                expected=expected,
                actual={},
                duration_ms=elapsed,
                error=str(e),
            ))

    return results


def _check_expected(expected: dict, actual: dict) -> bool:
    """递归检查 expected 中的字段是否在 actual 中存在并匹配"""
    for key, exp_val in expected.items():
        act_val = actual.get(key)
        if act_val is None:
            return False
        if isinstance(exp_val, dict):
            if not isinstance(act_val, dict):
                return False
            if not _check_expected(exp_val, act_val):
                return False
        elif isinstance(exp_val, list):
            if not isinstance(act_val, list):
                return False
            if len(exp_val) > len(act_val):
                return False
            for i, ev in enumerate(exp_val):
                if isinstance(ev, dict):
                    if not _check_expected(ev, act_val[i]):
                        return False
                elif str(ev) != str(act_val[i]):
                    return False
        else:
            if str(exp_val) != str(act_val):
                return False
    return True


def get_skill_manifest(skill_code: str) -> SkillManifest | None:
    """获取单个 Skill 包元信息"""
    package_dir = SKILL_PACKAGES_DIR / skill_code
    if not package_dir.exists():
        return None
    try:
        return load_manifest(package_dir)
    except Exception:
        return None


def has_executor(skill_code: str) -> bool:
    """检查 Skill 包是否有可执行逻辑"""
    package_dir = SKILL_PACKAGES_DIR / skill_code
    return (package_dir / "execute.py").exists()
