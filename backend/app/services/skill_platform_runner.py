"""统一 Skill 在线测试：execute.py 包 + Workflow Registry + 干跑校验。"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from agent_platform.core.registry import skill_registry
from agent_platform.core.executor import SkillExecutor
from app.models import Task
from app.services.skill_package_engine import (
    SkillExecutionResult,
    SkillTestResult,
    execute_skill,
    get_skill_manifest,
    has_executor,
    run_skill_tests,
)
from app.services.skill_registry import SkillContext, has_skill
from app.services.workflow_engine import WorkflowEngine, current_ai_mode


def platform_executable(skill_code: str) -> bool:
    """是否可在管理后台在线测试（独立 execute.py 或 Workflow 注册表）。"""
    return has_executor(skill_code) or has_skill(skill_code)


def _ensure_registry_loaded() -> None:
    if not skill_registry.list_all():
        skill_registry.reload()


def _is_placeholder_value(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    s = val.strip()
    if (s.startswith("<") and s.endswith(">")) or s in ("", "task_id", "<task_id>"):
        return True
    # skill.md 文档示例编号，非数据库 task.id（UUID）
    if s.upper().startswith("FT-") and len(s) < 24:
        return True
    return False


def _resolve_task_id(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    tid = raw.strip()
    if not tid or _is_placeholder_value(tid):
        return None
    return tid


def get_sample_input(skill_code: str) -> dict[str, Any]:
    """从 skill.md / skill.yaml 提取示例输入 JSON。"""
    _ensure_registry_loaded()
    try:
        meta = skill_registry.get(skill_code)
        if meta.input_schema and not _is_placeholder_value(meta.input_schema.get("task_id")):
            return dict(meta.input_schema)
        if meta.input_schema:
            sample = dict(meta.input_schema)
            if _is_placeholder_value(sample.get("task_id")):
                sample.pop("task_id", None)
            return sample
    except Exception:  # noqa: BLE001
        pass
    manifest = get_skill_manifest(skill_code)
    if not manifest:
        return {}
    if manifest.tests:
        first = manifest.tests[0].get("input")
        if isinstance(first, dict):
            return first
    if isinstance(manifest.input_schema, dict) and manifest.input_schema:
        return _schema_to_sample(manifest.input_schema)
    return {}


def _schema_to_sample(schema: dict[str, Any]) -> dict[str, Any]:
    """将 yaml input schema 转为可编辑示例对象。"""
    sample: dict[str, Any] = {}
    for key, spec in schema.items():
        if isinstance(spec, dict):
            t = spec.get("type", "string")
            if t == "integer":
                sample[key] = 0
            elif t == "number":
                sample[key] = 0.0
            elif t == "boolean":
                sample[key] = False
            elif t == "array":
                sample[key] = []
            elif t == "object":
                sample[key] = {}
            else:
                sample[key] = spec.get("example") or f"<{key}>"
        else:
            sample[key] = spec
    return sample


def _build_skill_context(db: Session, task: Task) -> SkillContext:
    engine = WorkflowEngine(db, task)
    ctx = SkillContext(
        db=db,
        task=task,
        file_paths=task.data_sources or {},
        rules=engine._get_rules(),
        ai_mode=current_ai_mode(db),
    )
    ctx.on_rule_hit = engine._audit_rule_hit
    ctx.on_difference_built = engine._persist_difference
    return ctx


def build_skill_context_for_task(db: Session | None, task_id: str | None) -> SkillContext | None:
    """为 Agent / 在线测试按 task_id 构建 Workflow 级 SkillContext。"""
    if not db or not task_id or not str(task_id).strip():
        return None
    task = db.query(Task).filter(Task.id == str(task_id).strip()).first()
    if not task:
        return None
    return _build_skill_context(db, task)


def build_chat_skill_context(
    db: Session | None,
    *,
    user_id: str | None = None,
    task_id: str | None = None,
) -> SkillContext | None:
    """对话 Agent 调用能力型 Skill（如 query_tasks）时的轻量 SkillContext。"""
    if db is None:
        return None

    tid = str(task_id).strip() if task_id else ""
    if tid:
        found = build_skill_context_for_task(db, tid)
        if found:
            return found
        task_row = db.query(Task).filter(Task.id == tid).first()
        if task_row:
            return _build_skill_context(db, task_row)

    q = db.query(Task).order_by(Task.updated_at.desc())
    if user_id:
        scoped = q.filter(Task.creator_id == user_id).first()
        if scoped:
            return _build_skill_context(db, scoped)
    latest = q.first()
    if latest:
        return _build_skill_context(db, latest)

    from types import SimpleNamespace

    proxy = SimpleNamespace(creator_id=user_id or "")
    return SkillContext(
        db=db,
        task=proxy,
        file_paths={},
        rules=[],
        ai_mode=current_ai_mode(db),
    )


async def execute_skill_unified(
    db: Session | None,
    skill_code: str,
    input_data: dict[str, Any],
    config: dict[str, Any] | None = None,
    *,
    task_id: str | None = None,
) -> SkillExecutionResult:
    """JSON 进 JSON 出：优先 execute.py，否则 Registry + 可选 task 上下文。"""
    manifest = get_skill_manifest(skill_code)
    version = manifest.version if manifest else 1

    if has_executor(skill_code):
        return execute_skill(skill_code, input_data, config)

    if not has_skill(skill_code):
        return SkillExecutionResult(
            success=False,
            output={},
            duration_ms=0,
            error=f"Skill 未注册可执行逻辑: {skill_code}",
            skill_code=skill_code,
            skill_version=version,
        )

    start = time.perf_counter()
    tid_raw = _resolve_task_id(task_id) or _resolve_task_id(input_data.get("task_id"))
    tid: str | None = None
    if db and tid_raw:
        if db.query(Task).filter(Task.id == tid_raw).first():
            tid = tid_raw

    if db and not tid and skill_code == "query_tasks":
        from app.services.skill_registry import skill_query_tasks

        uid = str(input_data.get("user_id") or "").strip() or None
        chat_ctx = build_chat_skill_context(db, user_id=uid, task_id=None)
        if chat_ctx:
            out = skill_query_tasks(chat_ctx)
            elapsed = int((time.perf_counter() - start) * 1000)
            return SkillExecutionResult(
                success=True,
                output=out,
                duration_ms=elapsed,
                skill_code=skill_code,
                skill_version=version,
            )

    if not db or not tid:
        try:
            meta = skill_registry.get(skill_code)
        except Exception:  # noqa: BLE001
            elapsed = int((time.perf_counter() - start) * 1000)
            return SkillExecutionResult(
                success=False,
                output={},
                duration_ms=elapsed,
                error=f"Skill 未注册: {skill_code}",
                skill_code=skill_code,
                skill_version=version,
            )
        elapsed = int((time.perf_counter() - start) * 1000)
        return SkillExecutionResult(
            success=True,
            output={
                "mode": "dry_run",
                "skill_id": meta.skill_id,
                "skill_type": meta.skill_type,
                "execution_steps": meta.execution_steps,
                "input_received": input_data,
                "hint": "填写有效 task_id 后可在任务上下文中真实调用该 Skill",
            },
            duration_ms=elapsed,
            skill_code=skill_code,
            skill_version=version,
        )

    task = db.query(Task).filter(Task.id == tid).first()
    if not task:
        elapsed = int((time.perf_counter() - start) * 1000)
        return SkillExecutionResult(
            success=False,
            output={},
            duration_ms=elapsed,
            error=f"任务不存在: {tid}",
            skill_code=skill_code,
            skill_version=version,
        )

    try:
        ctx = _build_skill_context(db, task)
        executor = SkillExecutor(db)
        raw = await executor.run(
            skill_code,
            input_data,
            skill_context=ctx,
        )
        elapsed = int((time.perf_counter() - start) * 1000)
        out = raw.get("output") if isinstance(raw, dict) else raw
        if isinstance(out, dict) and "result" in out:
            payload = out
        else:
            payload = {"result": out, "trace_id": raw.get("trace_id") if isinstance(raw, dict) else None}
        return SkillExecutionResult(
            success=True,
            output=payload,
            duration_ms=elapsed,
            skill_code=skill_code,
            skill_version=version,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.perf_counter() - start) * 1000)
        return SkillExecutionResult(
            success=False,
            output={},
            duration_ms=elapsed,
            error=str(exc),
            skill_code=skill_code,
            skill_version=version,
        )


async def run_skill_tests_unified(db: Session | None, skill_code: str) -> list[SkillTestResult]:
    """运行 skill.yaml 内置用例；若无则用示例输入做冒烟测试。"""
    manifest = get_skill_manifest(skill_code)
    if manifest and manifest.tests and has_executor(skill_code):
        return run_skill_tests(skill_code)

    sample = get_sample_input(skill_code)
    if not sample:
        return [
            SkillTestResult(
                name="加载检查",
                passed=False,
                expected={},
                actual={},
                duration_ms=0,
                error="无示例输入，请在 skill.md 接口定义或 skill.yaml tests 中补充",
            )
        ]

    tid = _resolve_task_id(sample.get("task_id"))
    result = await execute_skill_unified(db, skill_code, sample, task_id=tid)
    passed = result.success and not result.error
    if result.output.get("mode") == "dry_run":
        passed = True

    return [
        SkillTestResult(
            name="接口冒烟（示例输入）",
            passed=passed,
            expected={"success": True},
            actual={
                "success": result.success,
                "output": result.output,
                "error": result.error,
            },
            duration_ms=result.duration_ms,
            error=result.error,
        )
    ]
