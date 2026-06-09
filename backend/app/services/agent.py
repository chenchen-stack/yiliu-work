import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import AuditLog, CaseLibrary, Difference, ReviewDecision, Task, TaskStatus
from app.services.ai_analyzer import analyze_difference, build_evidence_chain
from app.services.data_loader import dataframe_to_records, load_dataframe, normalize_dataframe
from app.services.difference_detector import detect_differences
from app.services.report_generator import generate_pdf_report


def log_audit(db: Session, user_id: str | None, action: str, resource_type: str, resource_id: str, detail: dict | None = None):
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )
    )


class AnalysisAgent:
    """L2 Agent orchestrator — mirrors LangGraph POC workflow."""

    STEPS = [
        (TaskStatus.LOADING, 10),
        (TaskStatus.DETECTING, 40),
        (TaskStatus.ANALYZING, 70),
        (TaskStatus.REVIEWING, 85),
    ]

    def __init__(self, db: Session, task: Task):
        self.db = db
        self.task = task

    def _set_status(self, status: TaskStatus, progress: int):
        self.task.status = status.value
        self.task.progress = progress
        self.task.updated_at = datetime.utcnow()
        self.db.commit()

    async def run(self, file_paths: dict[str, str]):
        try:
            self._set_status(TaskStatus.LOADING, 10)
            sap_records = self._load_source(file_paths.get("sap"), "sap")
            dms_records = self._load_source(file_paths.get("dms"), "dms")
            fanruan_records = self._load_source(file_paths.get("fanruan"), "fanruan") if file_paths.get("fanruan") else []

            self._set_status(TaskStatus.DETECTING, 40)
            raw_diffs = detect_differences(sap_records, dms_records, fanruan_records)

            self._set_status(TaskStatus.ANALYZING, 70)
            for item in raw_diffs:
                recommendation = await analyze_difference(item, db=self.db, task=self.task)
                evidence = build_evidence_chain(item, recommendation)
                diff = Difference(
                    id=item["id"],
                    task_id=self.task.id,
                    type=item["type"],
                    amount_diff=item.get("amount_diff"),
                    confidence=item.get("confidence", 0),
                    responsible_party=item.get("responsible_party"),
                    sap_record=item.get("sap_record"),
                    dms_record=item.get("dms_record"),
                    statement_record=item.get("statement_record"),
                    ai_recommendation=recommendation,
                    evidence_chain=evidence,
                    status="analyzed",
                )
                self.db.add(diff)

            type_counts: dict[str, int] = {}
            for d in raw_diffs:
                type_counts[d["type"]] = type_counts.get(d["type"], 0) + 1

            self.task.summary = {
                "total": len(raw_diffs),
                "by_type": type_counts,
                "sap_rows": len(sap_records),
                "dms_rows": len(dms_records),
            }
            self._set_status(TaskStatus.REVIEWING, 85)
            log_audit(self.db, self.task.creator_id, "analyze_complete", "task", self.task.id, self.task.summary)
            self.db.commit()
        except Exception as e:
            self.task.status = TaskStatus.FAILED.value
            self.task.error_message = str(e)
            self.db.commit()
            raise

    def _load_source(self, path: str | None, source: str) -> list[dict]:
        if not path:
            return []
        df = load_dataframe(path)
        normalized = normalize_dataframe(df, source)
        return dataframe_to_records(normalized)

    def complete_after_review(self, user_id: str) -> str:
        self._set_status(TaskStatus.GENERATING, 95)
        diffs = self.db.query(Difference).filter(Difference.task_id == self.task.id).all()
        diff_dicts = [
            {
                "type": d.type,
                "amount_diff": d.amount_diff,
                "confidence": d.confidence,
                "review_decision": d.review_decision,
                "sap_record": d.sap_record,
                "ai_recommendation": d.ai_recommendation,
            }
            for d in diffs
        ]
        report_path = generate_pdf_report({"id": self.task.id, "name": self.task.name, "summary": self.task.summary}, diff_dicts)
        self.task.status = TaskStatus.COMPLETED.value
        self.task.progress = 100
        self.task.summary = {**(self.task.summary or {}), "report_path": report_path}
        self.task.updated_at = datetime.utcnow()

        for d in diffs:
            if d.review_decision == ReviewDecision.CONFIRMED.value:
                self.db.add(
                    CaseLibrary(
                        id=str(uuid.uuid4()),
                        task_id=self.task.id,
                        difference_id=d.id,
                        difference_type=d.type,
                        scenario=(d.ai_recommendation or {}).get("root_cause", d.type),
                        resolution=d.review_comment,
                        tags=[d.type, d.responsible_party or "unknown"],
                    )
                )

        log_audit(self.db, user_id, "task_completed", "task", self.task.id, {"report": report_path})
        self.db.commit()
        return report_path
