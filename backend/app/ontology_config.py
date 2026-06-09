"""Ontology layer configuration."""

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import DATA_DIR

_SAMPLES = Path(r"c:\Users\10250\Desktop\数据样本")
_BACKEND_DATA = DATA_DIR / "samples"
# 用户提供的微信附件路径（若文件存在则优先）
_WECHAT_POC = Path(
    r"c:\Users\10250\Documents\xwechat_files\wxid_pxwz921zq21g12_6ab0\msg\attach"
    r"\508cb889fb0d2b71bd491b0166d9ae16\2026-06\Rec\837681d23baa49d1\F\0\收入对账-POC数据(1).xlsx"
)


class OntologySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1024
    extract_on_startup: bool = True
    sample_value_limit: int = 3
    sample_value_cache_ttl: int = 3600
    fangtai_poc_xlsx: Path | None = None
    fangtai_exception_xlsx: Path = _SAMPLES / "收入_回款异常问题登记表 .xlsx"
    sensitive_field_patterns: List[str] = [
        "phone", "mobile", "email", "id_card", "bank_card", "客户名称", "法人客户",
    ]
    sensitive_amount_fields: List[str] = [
        "amount", "balance", "金额", "含税", "不含税", "DRP订单金额",
    ]


ontology_settings = OntologySettings()


def resolve_poc_xlsx(explicit: Path | None = None) -> Path:
    """解析方太 POC Excel 路径（env > 显式参数 > 项目 samples > 微信附件 > 桌面样本）。"""
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    if ontology_settings.fangtai_poc_xlsx:
        candidates.append(ontology_settings.fangtai_poc_xlsx)
    candidates.extend(
        [
            _BACKEND_DATA / "收入对账-POC数据(1).xlsx",
            _BACKEND_DATA / "收入对账-POC数据.xlsx",
            _WECHAT_POC,
            _SAMPLES / "收入对账-POC数据(1).xlsx",
            _SAMPLES / "收入对账-POC数据.xlsx",
        ]
    )
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError(
        "未找到方太 POC Excel。请将「收入对账-POC数据(1).xlsx」复制到 "
        f"{_BACKEND_DATA} 或配置环境变量 FANGTAI_POC_XLSX"
    )
