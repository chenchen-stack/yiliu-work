"""
方太 POC 闭环一键初始化：
1. 从《收入对账-POC数据.xlsx》导入全部 Sheet（含 SAP结算单明细）
2. 从《收入_回款异常问题登记表》提取规则并写入 RuleConfig
3. 写入「发货开票↔收入台账」中文字段映射
4. 绑定默认表对（主演示线）

用法:
  cd backend
  .venv/Scripts/python.exe -m scripts.seed_fangtai_poc_closure
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, engine, Base
from app.models import MappingConfig, RuleConfig, RuleVersion
from app.services.mapping_binding import set_mapping_binding, validate_datasource_pair
from app.services.platform_seed import IDS, seed_platform
BILLING_LEDGER_MAPPING = [
    # POC 发货开票 CSV 无客户列，仅按订单键核对，不写 customer_id 映射
    ("order_id", "单据编号", "DMS结算订单", "结算单编码", "rename"),
    ("sales_amount", "金额", "DRP订单金额", "收入含税金额", "amount"),
    ("invoice_num", "发票号", "开票凭证", "结算单编码", "rename"),
    ("business_date", "业务日期", "处理日期", None, "date"),
    ("mdm_code", "MDM编码", "DMS行唯一ID", "MDMID", "mdm"),
]


def _seed_billing_mapping(db) -> int:
    bc = IDS["business_center"]
    db.query(MappingConfig).filter(MappingConfig.business_center_id == bc).delete()
    for uf, label, biz_col, fin_col, transform in BILLING_LEDGER_MAPPING:
        if not biz_col and not fin_col:
            continue
        spec = json.dumps(
            {"label": label, "finance_column": fin_col, "transform": transform},
            ensure_ascii=False,
        )
        db.add(
            MappingConfig(
                id=str(uuid.uuid4()),
                business_center_id=bc,
                source_field=(biz_col or "").strip(),
                target_field=uf,
                transform_rule=spec,
                version=1,
                enabled=True,
            )
        )
    return len(BILLING_LEDGER_MAPPING)


def _bind_billing_ledger(db) -> None:
    from app.models import DataSource

    biz = db.query(DataSource).filter(DataSource.name == "SAP结算行明细").first()
    fin = db.query(DataSource).filter(DataSource.name == "DMS收入台账明细").first()
    if not biz or not fin:
        print("[warn] 未找到 SAP结算行明细 / DMS收入台账明细，请先运行 import_poc_data")
        return
    v = validate_datasource_pair(db, IDS["business_center"], biz, fin)
    set_mapping_binding(
        IDS["business_center"],
        business_datasource_id=biz.id,
        finance_datasource_id=fin.id,
        mapping_row_count=db.query(MappingConfig).filter(MappingConfig.business_center_id == IDS["business_center"]).count(),
        validated=v.ready,
        message=v.message,
    )
    print(f"[ok] 默认绑定: {biz.name} <-> {fin.name} (校验{'通过' if v.ready else v.message})")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_platform(db)
        db.commit()
        print("[ok] platform_seed 完成")

        from scripts.import_poc_data import run as import_poc

        import_poc()

        reg_xlsx = Path(
            r"c:\Users\10250\Documents\xwechat_files\wxid_pxwz921zq21g12_6ab0\msg\file\2026-06\收入_回款异常问题登记表 .xlsx"
        )
        if reg_xlsx.exists():
            import subprocess

            subprocess.run([sys.executable, "-m", "scripts.extract_fangtai_rules"], check=False)
            from app.models import User
            from app.services.rule_import_service import apply_preset

            admin = db.query(User).filter(User.username == "admin").first()
            if admin:
                res = apply_preset(
                    db,
                    rule_version_id=IDS["rule_version_v1"],
                    business_center_id=IDS["business_center"],
                    user=admin,
                )
                print(f"[ok] 登记表规则已应用（{len(res.get('applied', []))} 条）")
        else:
            print(f"[warn] 登记表不存在: {reg_xlsx}")

        nmap = _seed_billing_mapping(db)
        print(f"[ok] billing-ledger mapping rows: {nmap}")
        _bind_billing_ledger(db)
        db.commit()
        print("\n[done] 方太 POC 闭环初始化完成。请重启后端后：管理后台确认表对 → 新建任务。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
