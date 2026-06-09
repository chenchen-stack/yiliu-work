"""Skill 包 API — 查看清单、查看Schema、结构化执行、运行测试。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import User, UserRole
from app.services.skill_package_engine import (
    discover_packages,
    get_skill_manifest,
    has_executor,
    install_skill_package_zip,
    read_skill_markdown,
    transition_skill_status,
)
from app.services.skill_platform_runner import (
    execute_skill_unified,
    get_sample_input,
    platform_executable,
    run_skill_tests_unified,
)

router = APIRouter(prefix="/skill-packages", tags=["skill-packages"])


class SkillPackageListItem(BaseModel):
    id: str
    code: str
    name: str
    description: str
    type: str
    version: int
    status: str
    creator: str
    has_executor: bool
    platform_executable: bool
    test_count: int
    input_schema: dict
    output_schema: dict
    config_schema: dict
    dependencies: dict


class SkillExecuteRequest(BaseModel):
    input_data: dict
    config: dict | None = None
    task_id: str | None = None


class SkillExecuteResponse(BaseModel):
    success: bool
    output: dict
    duration_ms: int
    error: str | None = None
    skill_code: str
    skill_version: int


class SkillTestResultItem(BaseModel):
    name: str
    passed: bool
    expected: dict
    actual: dict
    duration_ms: int
    error: str | None = None


@router.get("", response_model=list[SkillPackageListItem])
def list_skill_packages():
    """扫描 skill_packages/ 目录，返回所有已注册 Skill 包清单"""
    packages = discover_packages()
    return [
        SkillPackageListItem(
            id=p.id,
            code=p.code,
            name=p.name,
            description=p.description,
            type=p.type,
            version=p.version,
            status=p.status,
            creator=p.creator,
            has_executor=has_executor(p.code),
            platform_executable=platform_executable(p.code),
            test_count=len(p.tests) or 1,
            input_schema=p.input_schema,
            output_schema=p.output_schema,
            config_schema=p.config_schema,
            dependencies=p.dependencies,
        )
        for p in packages
    ]


class SkillUploadResponse(BaseModel):
    code: str
    name: str
    version: int
    message: str


class SkillLifecycleBody(BaseModel):
    action: str = Field(..., description="submit_review | publish | offline | rollback")


@router.post("/upload", response_model=SkillUploadResponse)
async def upload_skill_package(
    file: UploadFile = File(...),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """上传 Skill 包 zip（根目录或子目录含 skill.yaml、可选 execute.py / skill.md）。"""
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过 20MB")
    try:
        manifest = install_skill_package_zip(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"安装失败: {exc}") from exc

    try:
        from agent_platform.core.registry import skill_registry

        skill_registry.reload()
    except Exception:  # noqa: BLE001
        pass

    return SkillUploadResponse(
        code=manifest.code,
        name=manifest.name,
        version=manifest.version,
        message=f"Skill「{manifest.name}」已安装，可在技能库中测试与挂载",
    )


@router.post("/{skill_code}/lifecycle")
def skill_package_lifecycle(
    skill_code: str,
    body: SkillLifecycleBody,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """Skill 状态：草稿 → 提交审核 → 发布 → 下架。"""
    try:
        manifest = transition_skill_status(skill_code, body.action, db)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    labels = {
        "submit_review": "已提交审核",
        "publish": "已发布，可供前台与 Workflow 调用",
        "offline": "已下架",
        "rollback": "已回退为草稿",
    }
    return {
        "code": manifest.code,
        "status": manifest.status,
        "message": labels.get(body.action, "操作成功"),
    }


@router.get("/{skill_code}")
def get_skill_package(skill_code: str):
    """获取单个 Skill 包完整元信息（含 input/output Schema、依赖、测试用例）"""
    manifest = get_skill_manifest(skill_code)
    if not manifest:
        raise HTTPException(404, f"Skill 包不存在: {skill_code}")
    return {
        "id": manifest.id,
        "code": manifest.code,
        "name": manifest.name,
        "description": manifest.description,
        "type": manifest.type,
        "version": manifest.version,
        "status": manifest.status,
        "creator": manifest.creator,
        "created_at": manifest.created_at,
        "has_executor": has_executor(manifest.code),
        "platform_executable": platform_executable(manifest.code),
        "sample_input": get_sample_input(manifest.code),
        "input_schema": manifest.input_schema,
        "output_schema": manifest.output_schema,
        "config_schema": manifest.config_schema,
        "dependencies": manifest.dependencies,
        "tests": manifest.tests,
        "skill_md": read_skill_markdown(skill_code),
        "has_skill_md": bool(manifest.skill_md_path),
    }


@router.post("/{skill_code}/execute", response_model=SkillExecuteResponse)
async def execute_skill_package(
    skill_code: str,
    body: SkillExecuteRequest,
    db: Session = Depends(get_db),
):
    """结构化执行 Skill — JSON 进、JSON 出（支持 execute.py 与 Workflow Registry）"""
    manifest = get_skill_manifest(skill_code)
    if not manifest:
        raise HTTPException(404, f"Skill 包不存在: {skill_code}")
    if not platform_executable(skill_code):
        raise HTTPException(400, f"Skill 包 {skill_code} 未注册可执行逻辑")

    result = await execute_skill_unified(
        db,
        skill_code,
        body.input_data,
        body.config,
        task_id=body.task_id,
    )
    return SkillExecuteResponse(
        success=result.success,
        output=result.output,
        duration_ms=result.duration_ms,
        error=result.error,
        skill_code=result.skill_code,
        skill_version=result.skill_version,
    )


@router.post("/{skill_code}/test", response_model=list[SkillTestResultItem])
async def test_skill_package(skill_code: str, db: Session = Depends(get_db)):
    """执行内置测试或 skill.md 示例输入冒烟测试（含 Workflow Skill）"""
    manifest = get_skill_manifest(skill_code)
    if not manifest:
        raise HTTPException(404, f"Skill 包不存在: {skill_code}")
    if not platform_executable(skill_code):
        raise HTTPException(400, f"Skill 包 {skill_code} 不可测试")

    results = await run_skill_tests_unified(db, skill_code)
    return [
        SkillTestResultItem(
            name=r.name,
            passed=r.passed,
            expected=r.expected,
            actual=r.actual,
            duration_ms=r.duration_ms,
            error=r.error,
        )
        for r in results
    ]
