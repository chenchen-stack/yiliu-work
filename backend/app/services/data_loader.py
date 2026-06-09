from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from app.config import CONFIG_DIR


class ConfigLoader:
    _field_mapping: dict | None = None
    _rules: dict | None = None

    @classmethod
    def field_mapping(cls) -> dict:
        if cls._field_mapping is None:
            with open(CONFIG_DIR / "field_mapping.yaml", encoding="utf-8") as f:
                cls._field_mapping = yaml.safe_load(f)
        return cls._field_mapping

    @classmethod
    def rules(cls) -> dict:
        if cls._rules is None:
            with open(CONFIG_DIR / "rules.yaml", encoding="utf-8") as f:
                cls._rules = yaml.safe_load(f)
        return cls._rules

    @classmethod
    def mdm_table(cls) -> list[dict]:
        return cls.field_mapping().get("mdm", [])


def load_dataframe(file_path: str | Path, sheet_name: str | int = 0) -> pd.DataFrame:
    path = Path(file_path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet_name)
    return pd.read_csv(path)


def load_all_sheets(file_path: str | Path) -> dict[str, pd.DataFrame]:
    """读取 Excel 文件的所有 Sheet，返回 {sheet_name: DataFrame}。"""
    path = Path(file_path)
    if path.suffix.lower() not in {".xlsx", ".xls"}:
        return {"Sheet1": pd.read_csv(path)}
    xls = pd.ExcelFile(path)
    result: dict[str, pd.DataFrame] = {}
    for name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=name)
        if df.empty or df.shape[0] < 1:
            continue
        result[name] = df
    return result


def is_multi_sheet_excel(file_path: str | Path) -> bool:
    path = Path(file_path)
    if path.suffix.lower() not in {".xlsx", ".xls"}:
        return False
    try:
        xls = pd.ExcelFile(path)
        return len(xls.sheet_names) > 1
    except Exception:
        return False


def json_safe_cell(val: Any) -> Any:
    """将 DataFrame 单元格转为 JSON 可序列化值。"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, (str, int, bool)):
        return val
    if isinstance(val, float):
        if val != val or val in (float("inf"), float("-inf")):
            return None
        return val
    if hasattr(val, "item"):
        try:
            return json_safe_cell(val.item())
        except (ValueError, AttributeError):
            pass
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def normalize_dataframe(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Map source-specific columns to standard field names."""
    mapping_cfg = ConfigLoader.field_mapping()["standard_fields"]
    rename_map: dict[str, str] = {}
    for std_field, cfg in mapping_cfg.items():
        src_col = cfg.get(f"{source}_field")
        if src_col and src_col in df.columns:
            rename_map[src_col] = std_field
    normalized = df.rename(columns=rename_map)
    for col in ["customer_id", "order_id", "product_code", "invoice_num"]:
        if col not in normalized.columns:
            normalized[col] = None
    if "sales_amount" in normalized.columns:
        normalized["sales_amount"] = pd.to_numeric(normalized["sales_amount"], errors="coerce")
    return normalized


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    records = df.where(pd.notnull(df), None).to_dict(orient="records")
    return records
