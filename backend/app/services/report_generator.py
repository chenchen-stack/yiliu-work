import uuid
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import REPORT_DIR


def generate_pdf_report(task: dict, differences: list[dict]) -> str:
    report_id = str(uuid.uuid4())[:8]
    path = REPORT_DIR / f"report_{task['id']}_{report_id}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>亿流 Work 对账报告</b>", styles["Title"]))
    story.append(Paragraph(f"任务: {task.get('name', '')}", styles["Normal"]))
    story.append(Paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
    story.append(Spacer(1, 16))

    summary = task.get("summary") or {}
    story.append(Paragraph(f"差异总数: {summary.get('total', len(differences))}", styles["Normal"]))
    story.append(Spacer(1, 12))

    table_data = [["类型", "订单号", "金额", "置信度", "复核状态", "AI 推荐原因"]]
    for d in differences:
        ai = d.get("ai_recommendation") or {}
        sap = d.get("sap_record") or {}
        table_data.append(
            [
                d.get("type", ""),
                str(sap.get("order_id", "")),
                str(d.get("amount_diff", "")),
                f"{float(d.get('confidence') or 0):.0%}",
                d.get("review_decision", "pending"),
                (ai.get("root_cause") or "")[:40],
            ]
        )

    table = Table(table_data, colWidths=[70, 60, 50, 50, 60, 180])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#06b6d4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return str(path)
