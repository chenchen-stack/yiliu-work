"""仅将数据库中历史 POC 数据源名称纠正为 Excel Sheet 原名（不重新导入文件）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, engine, Base
from app.models import DataSource
from scripts.import_poc_data import LEGACY_NAME_MAP, rename_legacy_datasources


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        n = rename_legacy_datasources(db)
        db.commit()
        print(f"done: renamed {n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
