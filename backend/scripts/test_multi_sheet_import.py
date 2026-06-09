"""验证多 Sheet Excel 自动分类和差异检测的端到端测试。

使用方式:
  cd yiliu-work/backend
  python scripts/test_multi_sheet_import.py [path_to_poc_excel]
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path

POC_FILE = "c:/Users/10250/Desktop/数据样本/收入对账-POC数据.xlsx"


def test_load_all_sheets(file_path: str):
    from app.services.data_loader import load_all_sheets, is_multi_sheet_excel

    print("=" * 60)
    print("TEST 1: load_all_sheets")
    print("=" * 60)

    assert is_multi_sheet_excel(file_path), "应识别为多 Sheet Excel"
    sheets = load_all_sheets(file_path)
    print(f"  共读取 {len(sheets)} 个 Sheet:")
    for name, df in sheets.items():
        print(f"    {name}: {df.shape[0]} 行 x {df.shape[1]} 列")
    assert len(sheets) >= 7, f"POC 数据应有至少 7 个 Sheet，实际 {len(sheets)}"
    print("  PASS\n")
    return sheets


def test_detect_profiles(sheets: dict):
    from app.services.mapping_engine import detect_data_profile

    print("=" * 60)
    print("TEST 2: detect_data_profile (每个 Sheet)")
    print("=" * 60)

    profiles = {}
    for name, df in sheets.items():
        profile = detect_data_profile(df)
        profiles[name] = profile
        print(f"  {name} → {profile}")

    expected_matches = {
        "sap_revenue_total": False,
        "dms_revenue_ledger": False,
        "fanruan_platform": False,
        "sap_billing_detail": False,
    }
    for profile in profiles.values():
        if profile in expected_matches:
            expected_matches[profile] = True
    for p, found in expected_matches.items():
        status = "PASS" if found else "WARN"
        print(f"  [{status}] 画像 {p} {'已匹配' if found else '未匹配到任何 Sheet'}")

    print()
    return profiles


def test_classify_sheets(file_path: str):
    from app.services.mapping_engine import classify_excel_sheets

    print("=" * 60)
    print("TEST 3: classify_excel_sheets (自动分类到槽位)")
    print("=" * 60)

    result = classify_excel_sheets(file_path)
    for slot, entries in result.items():
        print(f"  [{slot}]:")
        for sheet_name, df, profile, priority in entries:
            print(f"    {sheet_name} → {profile} (priority={priority}, rows={len(df)})")

    required_slots = {"business", "finance"}
    for s in required_slots:
        assert s in result, f"缺少必需槽位: {s}"
    print(f"  已分类槽位: {list(result.keys())}")
    print("  PASS\n")
    return result


def test_split_combined(file_path: str):
    from app.services.mapping_engine import MappingRegistry, split_combined_excel

    print("=" * 60)
    print("TEST 4: split_combined_excel (翻译 + 标准化)")
    print("=" * 60)

    registry = MappingRegistry.load(None, "")
    slot_data = split_combined_excel(file_path, registry)

    for slot, (records, profile) in slot_data.items():
        print(f"  [{slot}] {len(records)} 条记录, 画像={profile}")
        if records:
            sample = records[0]
            std_fields = [k for k in ("customer_id", "order_id", "sales_amount", "mdm_code", "invoice_num", "_match_key") if k in sample]
            print(f"    标准字段: {std_fields}")
            if "sales_amount" in sample:
                print(f"    首条 sales_amount={sample['sales_amount']}")
            if "_match_key" in sample:
                print(f"    首条 _match_key={sample['_match_key']}")

    assert "business" in slot_data, "缺少 business 槽位"
    assert "finance" in slot_data, "缺少 finance 槽位"
    biz_count = len(slot_data["business"][0])
    fin_count = len(slot_data["finance"][0])
    print(f"\n  业务侧: {biz_count} 条")
    print(f"  财务侧: {fin_count} 条")
    assert biz_count > 0, "业务侧记录为空"
    assert fin_count > 0, "财务侧记录为空"
    print("  PASS\n")
    return slot_data


def test_difference_detect(slot_data: dict):
    from app.services.difference_detector import detect_differences

    print("=" * 60)
    print("TEST 5: detect_differences (差异检测)")
    print("=" * 60)

    biz_records = slot_data.get("business", ([], ""))[0]
    fin_records = slot_data.get("finance", ([], ""))[0]
    stmt_records = slot_data.get("statement", ([], ""))[0]
    pay_records = slot_data.get("payment", ([], ""))[0]
    sap_sett_records = slot_data.get("sap_settlement", ([], ""))[0]

    diffs = detect_differences(
        biz_records,
        fin_records,
        stmt_records,
        payment_records=pay_records,
        sap_settlement_records=sap_sett_records,
    )

    print(f"  检测到 {len(diffs)} 条差异:")
    by_type: dict[str, int] = {}
    total_amount = 0.0
    for d in diffs:
        t = d.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        total_amount += abs(float(d.get("amount_diff") or 0))

    for t, count in sorted(by_type.items()):
        print(f"    {t}: {count} 条")
    print(f"  差异总金额: ¥{total_amount:,.2f}")

    if diffs:
        print("\n  前 3 条差异样本:")
        for d in diffs[:3]:
            print(f"    [{d.get('type')}] key={d.get('business_key')} "
                  f"biz={d.get('business_amount')} fin={d.get('finance_amount')} "
                  f"diff={d.get('amount_diff')}")
            print(f"      规则: {d.get('rule_id')} | {d.get('description', '')[:80]}")

    assert len(diffs) > 0, "应检测到至少 1 条差异"
    print("  PASS\n")
    return diffs


def main():
    file_path = sys.argv[1] if len(sys.argv) > 1 else POC_FILE
    if not Path(file_path).exists():
        print(f"ERROR: 文件不存在: {file_path}")
        sys.exit(1)

    print(f"\n使用 POC 数据文件: {file_path}\n")

    sheets = test_load_all_sheets(file_path)
    test_detect_profiles(sheets)
    classified = test_classify_sheets(file_path)
    slot_data = test_split_combined(file_path)
    diffs = test_difference_detect(slot_data)

    print("=" * 60)
    print("ALL TESTS PASSED")
    print(f"  {len(sheets)} 个 Sheet 自动分类")
    print(f"  {sum(len(v[0]) for v in slot_data.values())} 条记录标准化")
    print(f"  {len(diffs)} 条差异检测到")
    print("=" * 60)


if __name__ == "__main__":
    main()
