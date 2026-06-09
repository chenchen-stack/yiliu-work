"""从方太《收入/回款异常问题登记表》提取排查规则，输出 JSON。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.fangtai_rule_extract import PRESET_JSON, extract_workbook_from_path

DEFAULT_XLSX = Path(
    r"c:\Users\10250\Documents\xwechat_files\wxid_pxwz921zq21g12_6ab0\msg\file\2026-06\收入_回款异常问题登记表 .xlsx"
)


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(1)
    data = extract_workbook_from_path(path)
    PRESET_JSON.parent.mkdir(parents=True, exist_ok=True)
    PRESET_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {PRESET_JSON} ({data['total_patterns']} patterns, {len(data['consolidated_rules'])} consolidated)")


if __name__ == "__main__":
    main()
