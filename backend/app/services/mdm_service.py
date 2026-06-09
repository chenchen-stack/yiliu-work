from typing import Any

from app.services.data_loader import ConfigLoader


def build_mdm_lookup() -> dict[str, dict]:
    lookup: dict[str, dict] = {"sap": {}, "dms": {}, "fanruan": {}}
    for row in ConfigLoader.mdm_table():
        lookup["sap"][str(row["sap_code"])] = row
        lookup["dms"][str(row["dms_code"])] = row
        lookup["fanruan"][str(row["fanruan_code"])] = row
    return lookup


def resolve_mdm(customer_id: str | None, source: str, mdm_lookup: dict) -> dict | None:
    if not customer_id:
        return None
    return mdm_lookup.get(source, {}).get(str(customer_id))


def check_mdm_consistency(sap_record: dict, dms_record: dict, mdm_lookup: dict) -> tuple[bool, str | None]:
    sap_code = sap_record.get("customer_id")
    dms_code = dms_record.get("customer_id")
    sap_mdm = resolve_mdm(sap_code, "sap", mdm_lookup)
    dms_mdm = resolve_mdm(dms_code, "dms", mdm_lookup)

    if sap_mdm is None and sap_code:
        return False, f"SAP 客户编码 {sap_code} 在 MDM 中无映射"
    if dms_mdm is None and dms_code:
        return False, f"DMS 客户编码 {dms_code} 在 MDM 中无映射"
    if sap_mdm and dms_mdm and sap_mdm["mdm_id"] != dms_mdm["mdm_id"]:
        return False, f"SAP({sap_code}) 与 DMS({dms_code}) 对应不同 MDM 客户"
    return True, None
