"""
已废弃：旧合成演示数据 (dataset_fangtai) 已移除。
请使用方太真实 POC 数据：

  python -m scripts.import_poc_data
  python -m scripts.seed_fangtai_poc_closure
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def seed():
    print("[deprecated] seed_demo_datasources 已废弃。")
    print("请运行: python -m scripts.import_poc_data && python -m scripts.seed_fangtai_poc_closure")


if __name__ == "__main__":
    seed()
