import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def log_audit(
    db: Session,
    *,
    user: User | None = None,
    user_id: str | None = None,
    trace_id: str | None = None,
    object_type: str,
    object_id: str,
    action: str,
    before_data: dict | None = None,
    after_data: dict | None = None,
    detail: dict | None = None,
):
    uid = user_id or (user.id if user else None)
    operator = user.display_name if user else None
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            trace_id=trace_id,
            user_id=uid,
            object_type=object_type,
            object_id=object_id,
            action=action,
            operator=operator,
            before_data=before_data,
            after_data=after_data,
            detail=detail,
            resource_type=object_type,
            resource_id=object_id,
        )
    )
