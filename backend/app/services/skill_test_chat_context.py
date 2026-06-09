"""Skill 对话测试 — 会话上下文与内存存储。"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models import Task

DEFAULT_IMPORT_ID = "imp-20260604-001"


def resolve_skill_test_task_id(db: Session | None) -> str | None:
    """对话测试绑定库内最新任务，避免干跑。"""
    if db is None:
        return None
    row = (
        db.query(Task)
        .order_by(Task.updated_at.desc(), Task.created_at.desc())
        .first()
    )
    return row.id if row else None


@dataclass
class ChatContext:
    """跨轮对话记住 import_id、差异列表等隐式参数。"""

    session_id: str
    focus_skill: str | None = None
    task_id: str | None = None
    import_id: str | None = None
    diff_ids: list[str] = field(default_factory=list)
    last_skill_results: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def append_message(self, role: str, content: str, **extra: Any) -> None:
        row: dict[str, Any] = {"role": role, "content": content, **extra}
        self.messages.append(row)

    def ingest_skill_output(self, skill_code: str, output: dict[str, Any]) -> None:
        self.last_skill_results[skill_code] = output
        payload = output
        if isinstance(output, dict) and "result" in output:
            inner = output.get("result")
            if isinstance(inner, dict):
                payload = {**output, **inner}
        if skill_code == "data_import":
            iid = payload.get("import_id")
            if isinstance(iid, str) and iid:
                self.import_id = iid
        if skill_code in ("field_mapping", "difference_detect", "report_gen"):
            iid = payload.get("import_id")
            if isinstance(iid, str) and iid:
                self.import_id = iid
        diffs = payload.get("diff_list") or payload.get("differences")
        if isinstance(diffs, list):
            ids = []
            for d in diffs:
                if isinstance(d, dict) and d.get("diff_id"):
                    ids.append(str(d["diff_id"]))
                elif isinstance(d, str):
                    ids.append(d)
            if ids:
                self.diff_ids = ids

    def merge_params(self, skill_code: str, params: dict[str, Any]) -> dict[str, Any]:
        """将上下文默认值注入 Skill 入参。"""
        merged = dict(params)
        if self.task_id and not merged.get("task_id"):
            merged["task_id"] = self.task_id
        if self.import_id and skill_code in (
            "field_mapping",
            "difference_detect",
            "review_flow",
            "report_gen",
        ):
            merged.setdefault("import_id", self.import_id)
        if skill_code == "anomaly_explain" and not merged.get("diff_id") and self.diff_ids:
            merged.setdefault("diff_id", self.diff_ids[0])
        if skill_code == "re_verify" and not merged.get("diff_id") and self.diff_ids:
            merged.setdefault("diff_id", self.diff_ids[0])
        return merged

    def context_hint(self) -> str:
        parts = [f"task_id={self.task_id or '未绑定'}"]
        if self.import_id:
            parts.append(f"import_id={self.import_id}")
        if self.diff_ids:
            parts.append(f"差异条数={len(self.diff_ids)}")
        return "；".join(parts)

    def extract_from_user_message(self, text: str) -> None:
        tid = re.search(r"(FT-\d{4}-\d{2}-\d{3})", text, re.I)
        if tid:
            self.task_id = tid.group(1).upper()
        iid = re.search(r"(imp-[a-z0-9-]+)", text, re.I)
        if iid:
            self.import_id = iid.group(1)
        did = re.findall(r"(D-\d{8}-\d{3}|diff-[a-z0-9-]+)", text, re.I)
        if did:
            self.diff_ids = list(did)


class SkillTestChatStore:
    """进程内会话存储（管理后台测试用）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, ChatContext] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        session_id: str | None,
        *,
        focus_skill: str | None = None,
    ) -> ChatContext:
        with self._lock:
            if session_id and session_id in self._sessions:
                ctx = self._sessions[session_id]
                if focus_skill:
                    ctx.focus_skill = focus_skill
                return ctx
            sid = session_id or str(uuid.uuid4())
            ctx = ChatContext(session_id=sid, focus_skill=focus_skill)
            ctx.append_message(
                "system",
                "已加载方太对账 Skill 能力。请用自然语言描述你想完成的操作，我会自动选择并调用合适的 Skill。",
            )
            self._sessions[sid] = ctx
            return ctx

    def get(self, session_id: str) -> ChatContext | None:
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None


chat_store = SkillTestChatStore()
