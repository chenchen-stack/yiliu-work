from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import authenticate_user, create_access_token, get_current_user
from app.database import get_db
from app.models import Difference, DifferenceStatus, Task, TaskStatus, User, WorkflowNotification
from app.schemas import DashboardStats, LlmStatusOut, LoginRequest, TokenResponse, UserOut, WorkflowNotificationOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, body.username, body.password)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(User).all()


@router.get("/notifications", response_model=list[WorkflowNotificationOut])
def my_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(WorkflowNotification).filter(WorkflowNotification.user_id == user.id)
    if unread_only:
        q = q.filter(WorkflowNotification.read.is_(False))
    return q.order_by(WorkflowNotification.created_at.desc()).limit(50).all()


@router.post("/notifications/{notification_id}/read", response_model=WorkflowNotificationOut)
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.query(WorkflowNotification).filter(
        WorkflowNotification.id == notification_id,
        WorkflowNotification.user_id == user.id,
    ).first()
    if not row:
        raise HTTPException(404, "通知不存在")
    row.read = True
    db.commit()
    db.refresh(row)
    return row


dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@dashboard_router.get("/stats", response_model=DashboardStats)
def stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tasks_q = db.query(Task)
    if user.role not in ("admin", "manager"):
        tasks_q = tasks_q.filter(Task.creator_id == user.id)

    tasks = tasks_q.all()
    task_ids = [t.id for t in tasks]

    period_tasks = len(tasks)
    pending = sum(1 for t in tasks if t.status in (TaskStatus.DRAFT.value, TaskStatus.RUNNING.value))
    reviewing = sum(1 for t in tasks if t.status == TaskStatus.PENDING_REVIEW.value)
    closed = sum(1 for t in tasks if t.status == TaskStatus.CLOSED.value)

    all_diffs = db.query(Difference).filter(Difference.task_id.in_(task_ids)).all() if task_ids else []
    pending_reviews = sum(1 for d in all_diffs if d.status == DifferenceStatus.PENDING_REVIEW.value)
    diff_amount = sum(float(d.amount_diff or 0) for d in all_diffs)

    return DashboardStats(
        period_tasks=period_tasks,
        difference_count=len(all_diffs),
        difference_amount=round(diff_amount, 2),
        pending_review_count=pending_reviews,
        closed_count=closed,
        pending_tasks=pending,
        reviewing_tasks=reviewing,
        completed_tasks=closed,
        pending_reviews=pending_reviews,
        total_differences=len(all_diffs),
    )


@dashboard_router.get("/llm-status", response_model=LlmStatusOut)
def llm_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """任意登录用户可查询大模型是否可用于「用大模型补充」差异解释。"""
    from app.services.llm_config_service import ensure_llm_config, get_effective_llm_config, llm_config_to_out

    _ = user
    llm_row = ensure_llm_config(db)
    effective = get_effective_llm_config(db)
    cfg = llm_config_to_out(llm_row, effective)
    ready = bool(cfg.get("runtime_ready"))
    hint = ""
    if not ready:
        if cfg.get("use_mock"):
            hint = "当前为模拟模式。请在管理后台「系统配置 → 大模型」关闭模拟模式并配置 API Key。"
        elif not cfg.get("api_key_set"):
            hint = "未配置 API Key。请在管理后台「系统配置 → 大模型」填写密钥。"
        else:
            hint = "大模型未就绪，请检查管理后台配置。"
    return LlmStatusOut(
        runtime_ready=ready,
        use_mock=bool(cfg.get("use_mock")),
        model=str(cfg.get("model") or effective.model),
        effective_mode=str(cfg.get("effective_mode") or "mock-ai"),
        api_key_set=bool(cfg.get("api_key_set")),
        hint=hint,
    )

