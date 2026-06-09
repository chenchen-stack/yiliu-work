"""将《收入/回款异常问题登记表》导入「收入核对知识」库。用法:
  python scripts/import_knowledge_excel.py [xlsx路径]
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.database import SessionLocal, init_db
from app.models import User
from app.services.knowledge_import_service import import_excel_to_knowledge

DEFAULT_XLSX = Path(r"c:\Users\10250\Desktop\数据样本\收入_回款异常问题登记表 .xlsx")
KB_ID = "revenue_reconciliation"


def main() -> None:
    init_db()
    xlsx = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    if not xlsx.exists():
        print(f"文件不存在: {xlsx}")
        sys.exit(1)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.role == "admin").first()
        if not user:
            user = db.query(User).first()
        content = xlsx.read_bytes()
        import io

        result = import_excel_to_knowledge(
            db,
            stream=io.BytesIO(content),
            filename=xlsx.name,
            knowledge_base_id=KB_ID,
            user=user,
        )
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
