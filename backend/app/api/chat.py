import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.auth import get_current_user
from app.database import get_db
from app.models import AgentConfig, CaseAsset, Conversation, Difference, Task, User
from app.schemas import CaseAssetOut, ChatExecuteRequest, ChatRequest, ChatResponse, ConversationListItem, ConversationOut
from app.services.audit_service import log_audit
from app.services.chat_actions import (
    assert_datasource_pair_allowed,
    connect_chat_demo_datasources,
    execute_reconciliation_from_chat,
    import_chat_datasources_from_excel,
    list_chat_datasources,
    parse_period_from_message,
    preview_datasource_for_agent,
    upload_chat_datasource_file,
    wants_execute_recommended,
)
from app.services.agent_config_service import resolve_agent
from app.services.agent_runtime import run_agent_turn

router = APIRouter(prefix="/chat", tags=["chat"])


def _conversation_title(task_name: str | None, business_key: str | None, messages: list | None) -> str:
    if business_key:
        base = f"{business_key}"
        if task_name:
            return f"{task_name} · {base}"
        return base
    if task_name:
        return task_name
    for m in messages or []:
        if m.get("role") == "user" and m.get("content"):
            return str(m["content"])[:32]
    return "收入差异解释"


def _conversation_preview(messages: list | None) -> str:
    if not messages:
        return "暂无消息"
    for m in reversed(messages):
        if m.get("content"):
            return str(m["content"])[:48]
        for b in m.get("ui_blocks") or []:
            if b.get("type") == "datasource_confirm":
                intro = (b.get("data") or {}).get("intro")
                if intro:
                    return str(intro)[:48]
    return "暂无消息"


@router.get("/conversations", response_model=list[ConversationListItem])
def list_conversations(
    limit: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(Conversation)
        .filter(
            or_(Conversation.user_id == user.id, Conversation.user_id.is_(None)),
        )
        .order_by(Conversation.updated_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    out: list[ConversationListItem] = []
    for conv in rows:
        msgs = conv.messages or []
        if len(msgs) < 1:
            continue
        task = db.query(Task).filter(Task.id == conv.task_id).first() if conv.task_id else None
        diff = (
            db.query(Difference).filter(Difference.id == conv.difference_item_id).first()
            if conv.difference_item_id
            else None
        )
        out.append(
            ConversationListItem(
                id=conv.id,
                task_id=conv.task_id,
                difference_item_id=conv.difference_item_id,
                title=_conversation_title(
                    task.name if task else None,
                    diff.business_key if diff else None,
                    msgs,
                ),
                preview=_conversation_preview(msgs),
                updated_at=conv.updated_at or conv.created_at,
                message_count=len(msgs),
            )
        )
    return out


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(404, "对话不存在")
    if conv.user_id and conv.user_id != user.id:
        raise HTTPException(403, "无权访问该对话")
    return conv


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


def _period_from_context(message: str, history: list) -> str:
    period = parse_period_from_message(message)
    if period:
        return period
    for h in reversed(history):
        if h.get("role") == "user":
            period = parse_period_from_message(h.get("content", ""))
            if period:
                return period
    return "2024-05"


def _ensure_conversation(
    db: Session,
    user: User,
    body: ChatRequest,
    task: Task | None,
    *,
    agent_id: str | None = None,
) -> Conversation:
    conv = None
    if body.conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == body.conversation_id).first()
        if conv and conv.user_id and conv.user_id != user.id:
            raise HTTPException(403, "无权访问该对话")
    if not conv:
        agent = resolve_agent(db, agent_id=agent_id or body.agent_id, user=user)
        now = datetime.utcnow()
        conv = Conversation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            agent_id=agent.id,
            task_id=body.task_id,
            difference_item_id=body.difference_item_id,
            messages=[],
            created_at=now,
            updated_at=now,
        )
        db.add(conv)
    elif not conv.user_id:
        conv.user_id = user.id
    return conv


def _append_messages(
    conv: Conversation,
    user_message: str,
    reply: str,
    *,
    ui_blocks: list | None = None,
    task_id: str | None = None,
    plan_steps: list | None = None,
):
    msgs = list(conv.messages or [])
    msgs.append({"role": "user", "content": user_message, "at": datetime.utcnow().isoformat()})
    assistant: dict = {"role": "assistant", "content": reply, "at": datetime.utcnow().isoformat()}
    if ui_blocks:
        assistant["ui_blocks"] = ui_blocks
    if task_id:
        assistant["task_id"] = task_id
    if plan_steps:
        assistant["plan_steps"] = plan_steps
    msgs.append(assistant)
    conv.messages = msgs
    flag_modified(conv, "messages")
    conv.updated_at = datetime.utcnow()


@router.get("/reconciliation-options")
def reconciliation_options(
    agent_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = resolve_agent(db, agent_id=agent_id, user=user)
    return list_chat_datasources(db, agent=agent)


@router.post("/datasources/import-excel")
async def chat_import_datasources_excel(
    file: UploadFile = File(...),
    agent_id: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对话内上传 Excel（多 Sheet），无需跳转工作台。"""
    agent = resolve_agent(db, agent_id=agent_id, user=user)
    content = await file.read()
    return import_chat_datasources_from_excel(
        db, user, content, file.filename or "workbook.xlsx", agent=agent,
    )


@router.post("/datasources/upload")
async def chat_upload_datasource(
    file: UploadFile = File(...),
    name: str = Form(""),
    system_type: str = Form("sap"),
    side: str = Form("business"),
    agent_id: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对话内上传单表 csv/xlsx。"""
    from pathlib import Path

    from app.services.mapping_engine import detect_data_profile
    from app.services.data_loader import load_dataframe
    from io import BytesIO

    agent = resolve_agent(db, agent_id=agent_id, user=user)
    content = await file.read()
    fname = file.filename or "data.csv"
    suffix = Path(fname).suffix.lower()
    if suffix in (".xlsx", ".xls", ".xlsm") and not name.strip():
        try:
            import pandas as pd
            df = pd.read_excel(BytesIO(content))
            inferred = detect_data_profile(df)
            st = inferred if inferred in ("sap", "dms", "fanruan") else system_type
            sd = "finance" if st == "dms" else "business"
            return upload_chat_datasource_file(
                db, user,
                name=Path(fname).stem,
                system_type=st,
                side=sd,
                content=content,
                filename=fname,
                agent=agent,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"Excel 解析失败: {exc}") from exc
    return upload_chat_datasource_file(
        db, user,
        name=name.strip() or Path(fname).stem,
        system_type=system_type,
        side=side,
        content=content,
        filename=fname,
        agent=agent,
    )


@router.post("/datasources/connect-demo")
def chat_connect_demo_datasources(
    agent_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对话内连接 SAP / DMS 演示库（无需跳转管理后台）。"""
    agent = resolve_agent(db, agent_id=agent_id, user=user)
    result = connect_chat_demo_datasources(db, user)
    result["options"] = list_chat_datasources(db, agent=agent)
    return result


@router.get("/datasources/{ds_id}/preview")
def chat_datasource_preview(
    ds_id: str,
    agent_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = resolve_agent(db, agent_id=agent_id, user=user)
    return preview_datasource_for_agent(db, ds_id, agent=agent, limit=limit)


@router.get("/skills/{skill_id}")
def chat_skill_detail(
    skill_id: str,
    agent_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对话内查看已授权 Skill 的完整说明（含 input/output Schema）。"""
    from app.services.agent_ui_blocks import agent_allows_skill, build_chat_skill_detail

    agent = resolve_agent(db, agent_id=agent_id, user=user)
    if not agent_allows_skill(agent, skill_id, db):
        raise HTTPException(403, "该 Skill 不在当前 Agent 授权范围内")
    return build_chat_skill_detail(db, skill_id)


@router.get("/knowledge-entries/{case_id}", response_model=CaseAssetOut)
def chat_knowledge_entry_detail(
    case_id: str,
    agent_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对话内查看知识库命中条目的完整内容（仅限当前 Agent 挂载的知识库）。"""
    from app.services.agent_runtime import _case_matches_kb

    agent = resolve_agent(db, agent_id=agent_id, user=user)
    case = db.query(CaseAsset).filter(CaseAsset.id == case_id).first()
    if not case:
        raise HTTPException(404, "知识库条目不存在")
    kb_ids = agent.knowledge_base_ids or []
    if not kb_ids or not any(_case_matches_kb(case, kb) for kb in kb_ids):
        raise HTTPException(403, "该条目不在当前 Agent 知识库范围内")
    return case


@router.post("/execute", response_model=ChatResponse)
async def chat_execute(
    body: ChatExecuteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.action != "start_reconciliation":
        raise HTTPException(400, "不支持的操作")

    conv = None
    if body.conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == body.conversation_id).first()
        if conv and conv.user_id and conv.user_id != user.id:
            raise HTTPException(403, "无权访问该对话")

    agent = resolve_agent(
        db,
        agent_id=body.agent_id or (conv.agent_id if conv else None),
        user=user,
    )

    biz_id = body.business_datasource_id
    fin_id = body.finance_datasource_id
    demo_id = body.demo_dataset_id
    if body.use_recommended and not biz_id and not fin_id and not demo_id:
        opts = list_chat_datasources(db, agent=agent)
        rec = opts["recommended"]
        if opts["has_datasource_pair"]:
            biz_id = rec["business_datasource_id"]
            fin_id = rec["finance_datasource_id"]
        else:
            demo_id = opts["demo_dataset_id"]
    else:
        assert_datasource_pair_allowed(
            db,
            agent=agent,
            business_datasource_id=biz_id,
            finance_datasource_id=fin_id,
        )

    task, reply, ui_blocks = execute_reconciliation_from_chat(
        db,
        user,
        business_datasource_id=biz_id,
        finance_datasource_id=fin_id,
        demo_dataset_id=demo_id,
        period=body.period,
        name=body.name,
        background_tasks=background_tasks,
        agent=agent,
    )

    if conv:
        _append_messages(
            conv,
            "使用推荐方案进行对账分析",
            reply,
            ui_blocks=ui_blocks,
            task_id=task.id,
        )
        conv.task_id = task.id
        log_audit(
            db,
            user=user,
            trace_id=task.trace_id,
            object_type="conversation",
            object_id=conv.id,
            action="chat_execute_reconciliation",
            detail={"task_id": task.id},
        )
        db.commit()

    return ChatResponse(
        reply=reply,
        intent="execute_reconciliation",
        conversation_id=conv.id if conv else None,
        ui_blocks=ui_blocks,
        task_id=task.id,
    )


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    context = None
    task = None
    diff = None
    effective_task_id = body.task_id
    if not effective_task_id and body.conversation_id:
        conv_probe = db.query(Conversation).filter(Conversation.id == body.conversation_id).first()
        if conv_probe:
            effective_task_id = conv_probe.task_id
            if not effective_task_id:
                for m in reversed(conv_probe.messages or []):
                    for b in m.get("ui_blocks") or []:
                        if isinstance(b, dict) and b.get("type") in (
                            "reconciliation_result", "difference_list", "review_prompt",
                        ):
                            effective_task_id = (b.get("data") or {}).get("task_id")
                            break
                    if effective_task_id:
                        break

    if effective_task_id:
        task = db.query(Task).filter(Task.id == effective_task_id).first()
    if body.difference_item_id:
        diff = db.query(Difference).filter(Difference.id == body.difference_item_id).first()

    if task or diff:
        context = {
            "task_id": task.id if task else None,
            "task_name": task.name if task else None,
            "task_period": task.period if task else None,
            "difference_id": diff.id if diff else None,
            "difference_type": diff.type if diff else None,
            "business_key": diff.business_key if diff else None,
            "rule_hits": diff.rule_hits if diff else None,
            "evidence": diff.evidence if diff else None,
            "ai_explanation": diff.ai_explanation if diff else None,
        }

    reply: str = ""
    intent: str | None = None
    ui_blocks: list = []
    task_id: str | None = None
    plan_steps: list = []
    active_agent_id: str | None = body.agent_id

    history = [m.model_dump() for m in body.history]
    has_diff_context = bool(diff)

    if not has_diff_context and wants_execute_recommended(body.message):
        period = _period_from_context(body.message, history)
        task, reply, ui_blocks = execute_reconciliation_from_chat(
            db,
            user,
            business_datasource_id=None,
            finance_datasource_id=None,
            demo_dataset_id=None,
            period=period,
            name=None,
            background_tasks=background_tasks,
        )
        intent = "execute_reconciliation"
        task_id = task.id
    else:
        from app.services.agent_config_service import resolve_agent

        agent = resolve_agent(db, agent_id=body.agent_id, user=user)
        active_agent_id = agent.id
        reply, intent, ui_blocks, plan_steps = await run_agent_turn(
            db,
            agent=agent,
            user=user,
            message=body.message,
            history=history,
            context=context,
            conversation_id=body.conversation_id,
            client_action=body.client_action,
        )

    conv = _ensure_conversation(db, user, body, task, agent_id=body.agent_id)
    _append_messages(
        conv,
        body.message,
        reply,
        ui_blocks=ui_blocks or None,
        task_id=task_id,
        plan_steps=plan_steps or None,
    )
    if task_id:
        conv.task_id = task_id
    elif task and not conv.task_id:
        conv.task_id = task.id
    log_audit(
        db,
        user=user,
        trace_id=task.trace_id if task else None,
        object_type="conversation",
        object_id=conv.id,
        action="ai_chat",
        detail={"message": body.message[:100], "intent": intent, "task_id": task_id},
    )
    db.commit()

    return ChatResponse(
        reply=reply,
        intent=intent,
        conversation_id=conv.id,
        ui_blocks=ui_blocks,
        task_id=task_id,
        agent_id=conv.agent_id or active_agent_id,
        plan_steps=plan_steps,
    )


def _build_chat_context(body: ChatRequest, db: Session):
    """与 POST /chat 相同的任务/差异上下文解析。"""
    context = None
    task = None
    diff = None
    effective_task_id = body.task_id
    if not effective_task_id and body.conversation_id:
        conv_probe = db.query(Conversation).filter(Conversation.id == body.conversation_id).first()
        if conv_probe:
            effective_task_id = conv_probe.task_id
            if not effective_task_id:
                for m in reversed(conv_probe.messages or []):
                    for b in m.get("ui_blocks") or []:
                        if isinstance(b, dict) and b.get("type") in (
                            "reconciliation_result", "difference_list", "review_prompt",
                        ):
                            effective_task_id = (b.get("data") or {}).get("task_id")
                            break
                    if effective_task_id:
                        break
    if effective_task_id:
        task = db.query(Task).filter(Task.id == effective_task_id).first()
    if body.difference_item_id:
        diff = db.query(Difference).filter(Difference.id == body.difference_item_id).first()
    if task or diff:
        context = {
            "task_id": task.id if task else None,
            "task_name": task.name if task else None,
            "task_period": task.period if task else None,
            "difference_id": diff.id if diff else None,
            "difference_type": diff.type if diff else None,
            "business_key": diff.business_key if diff else None,
            "rule_hits": diff.rule_hits if diff else None,
            "evidence": diff.evidence if diff else None,
            "ai_explanation": diff.ai_explanation if diff else None,
        }
    return context, task, diff, effective_task_id


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    对话 SSE（thinking / tool_call / reply / ui_blocks / done）。
    默认仍由 agent_runtime 产出 UI；开放问答在 USE_PLATFORM_CHAT_SSE=true 时走 PlatformAgentEngine。
    """
    from app.services.chat_agent_bridge import stream_chat_turn

    async def _gen():
        async for line in stream_chat_turn(
            db,
            user,
            body,
            background_tasks=background_tasks,
            build_context=lambda b: _build_chat_context(b, db),
            ensure_conversation=lambda b, task: _ensure_conversation(
                db, user, b, task, agent_id=b.agent_id,
            ),
            append_messages=_append_messages,
            period_from_context=_period_from_context,
            log_and_commit=lambda conv, b, intent, task_id, task: (
                log_audit(
                    db,
                    user=user,
                    trace_id=task.trace_id if task else None,
                    object_type="conversation",
                    object_id=conv.id,
                    action="ai_chat_stream",
                    detail={"message": b.message[:100], "intent": intent, "task_id": task_id},
                ),
                db.commit(),
            ),
        ):
            yield line

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
