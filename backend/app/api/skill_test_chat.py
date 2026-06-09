"""Skill 对话测试 API — SSE 流式 + 预设场景。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agent_platform.core.registry import skill_registry
from app.database import get_db
from app.services.skill_test_agent import PRESET_MESSAGES, SkillTestAgent
from app.services.skill_test_chat_context import chat_store

router = APIRouter(prefix="/skill-test", tags=["skill-test"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    focus_skill: str | None = None


class PresetRequest(BaseModel):
    preset: str = Field(..., description="full_reconciliation | diff_only | ...")


def _sse_pack(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("/skills")
def list_testable_skills():
    """可测试 Skill 摘要（右侧监控 / 系统消息用）。"""
    if not skill_registry.list_all():
        skill_registry.reload()
    items = []
    for meta in skill_registry.list_all():
        items.append({
            "skill_id": meta.skill_id,
            "code": meta.package_code,
            "name": meta.name,
            "type": meta.skill_type,
            "category": meta.category,
        })
    return {"skills": items}


@router.get("/presets")
def list_presets():
    return {
        "presets": [
            {"id": k, "label": _preset_label(k), "message": v}
            for k, v in PRESET_MESSAGES.items()
        ],
    }


def _preset_label(preset_id: str) -> str:
    labels = {
        "full_reconciliation": "完整对账流程",
        "diff_only": "只看差异",
        "single_attribution": "单条归因",
        "review_simulation": "人工复核模拟",
        "generate_report": "生成报告",
    }
    return labels.get(preset_id, preset_id)


@router.get("/sessions/{session_id}/history")
def get_history(session_id: str):
    ctx = chat_store.get(session_id)
    if not ctx:
        raise HTTPException(404, "会话不存在")
    return {"session_id": session_id, "messages": ctx.messages}


@router.delete("/sessions/{session_id}")
def clear_session(session_id: str):
    ok = chat_store.delete(session_id)
    return {"status": "cleared" if ok else "not_found"}


@router.post("/sessions/{session_id}/chat")
async def chat_stream(
    session_id: str,
    body: ChatRequest,
    db: Session = Depends(get_db),
):
    """SSE：用户自然语言 → Agent 思考 / 调 Skill / 回复。"""

    async def event_gen():
        agent = SkillTestAgent(db)
        async for evt in agent.chat(
            session_id,
            body.message.strip(),
            focus_skill=body.focus_skill,
        ):
            yield _sse_pack(evt)
        yield _sse_pack({"type": "done"})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/preset")
async def run_preset(
    session_id: str,
    body: PresetRequest,
    db: Session = Depends(get_db),
):
    msg = PRESET_MESSAGES.get(body.preset)
    if not msg:
        raise HTTPException(400, f"未知预设: {body.preset}")
    return StreamingResponse(
        _preset_stream(session_id, msg, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _preset_stream(session_id: str, message: str, db: Session):
    agent = SkillTestAgent(db)
    async for evt in agent.chat(session_id, message):
        yield _sse_pack(evt)
    yield _sse_pack({"type": "done"})
