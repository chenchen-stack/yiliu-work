from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Report, Task, User

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{task_id}")
def download_report(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    report = db.query(Report).filter(Report.task_id == task_id).order_by(Report.generated_at.desc()).first()
    report_path = report.file_url if report else (task.summary or {}).get("report_path")
    if not report_path:
        raise HTTPException(404, "报告尚未生成")
    return FileResponse(report_path, filename=f"对账报告_{task.name}.pdf", media_type="application/pdf")
