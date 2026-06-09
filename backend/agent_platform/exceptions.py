"""Platform-specific exceptions and HTTP error helpers."""

from __future__ import annotations

from typing import Any


class PlatformError(Exception):
    """Base platform error."""

    def __init__(self, message: str, *, code: str = "platform_error", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class SkillNotFoundError(PlatformError):
    def __init__(self, skill_id: str):
        super().__init__(f"Skill 不存在: {skill_id}", code="skill_not_found", details={"skill_id": skill_id})


class SkillParseError(PlatformError):
    def __init__(self, path: str, reason: str):
        super().__init__(
            f"解析 skill.md 失败: {path} — {reason}",
            code="skill_parse_error",
            details={"path": path, "reason": reason},
        )


class SkillExecutionFailed(PlatformError):
    def __init__(self, skill_id: str, reason: str):
        super().__init__(
            f"Skill 执行失败: {skill_id} — {reason}",
            code="skill_execution_failed",
            details={"skill_id": skill_id, "reason": reason},
        )


class WorkflowNotFoundError(PlatformError):
    def __init__(self, workflow_id: str):
        super().__init__(
            f"Workflow 不存在: {workflow_id}",
            code="workflow_not_found",
            details={"workflow_id": workflow_id},
        )


class WorkflowStateError(PlatformError):
    def __init__(self, workflow_id: str, reason: str):
        super().__init__(
            reason,
            code="workflow_state_error",
            details={"workflow_id": workflow_id},
        )


def error_response(exc: PlatformError) -> dict[str, Any]:
    """Unified JSON error body for FastAPI handlers."""
    return {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
