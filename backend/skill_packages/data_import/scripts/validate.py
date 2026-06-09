"""数据导入前置校验（可选脚本）。"""
from __future__ import annotations

from pathlib import Path


def validate_file(path: str, *, max_mb: float = 50.0) -> list[str]:
    errors: list[str] = []
    p = Path(path)
    if not p.is_file():
        errors.append(f"文件不存在: {path}")
        return errors
    size_mb = p.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        errors.append(f"文件超过 {max_mb}MB: {size_mb:.1f}MB")
    if p.suffix.lower() not in {".xlsx", ".xls", ".csv"}:
        errors.append(f"不支持的格式: {p.suffix}")
    return errors
