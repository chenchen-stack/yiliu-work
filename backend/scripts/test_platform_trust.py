"""中台可信度反证测试套件（§17.2）。

针对运行中的后端执行黑盒反证，证明中台配置真正驱动运行、版本真实生效、
状态机拒绝非法跳转、Skill 真实调度、AI 模式可识别可审计、角色权限正确。

用法：
    set API_BASE=http://127.0.0.1:8014/api/v1   (建议指向 USE_MOCK_AI=true 的实例以加速)
    python scripts/test_platform_trust.py
"""
import os
import time
import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8014/api/v1")
BC_ID = "bc-revenue-reconciliation"
BC_CODE = "revenue_reconciliation"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, ok, detail))


def login(c, u, p):
    r = c.post(f"{BASE}/auth/login", json={"username": u, "password": p})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def publish(c, h):
    c.post(f"{BASE}/admin/business-centers/{BC_ID}/publish", headers=h)


def baseline_rules(c, h):
    """重置为确定性基线：三类规则启用、金额阈值 0。"""
    c.post(f"{BASE}/admin/rule-configs/new-version", headers=h, json={
        "description": "trust-test baseline", "reusable_rule_suggestion": "baseline",
        "rule_overrides": [
            {"rule_type": "amount_mismatch", "enabled": True, "threshold": 0},
            {"rule_type": "duplicate_record", "enabled": True},
            {"rule_type": "mapping_anomaly", "enabled": True},
        ],
    })
    publish(c, h)


def create_wait(c, h, name):
    r = c.post(f"{BASE}/tasks", headers=h, data={"name": name, "period": "2024-05", "demo_dataset_id": "dataset_fangtai_real", "auto_execute": "true"})
    r.raise_for_status()
    tid = r.json()["id"]
    for _ in range(180):
        time.sleep(1)
        t = c.get(f"{BASE}/tasks/{tid}", headers=h).json()
        if t["status"] in ("pending_review", "failed"):
            return tid, t
    return tid, t


def diff_types(c, h, tid):
    diffs = c.get(f"{BASE}/tasks/{tid}/differences", headers=h).json()
    by = {}
    for d in diffs:
        by[d["type"]] = by.get(d["type"], 0) + 1
    return len(diffs), by


def run_review_to_close(c, hl, ho, tid):
    diffs = c.get(f"{BASE}/tasks/{tid}/differences", headers=hl).json()
    users = c.get(f"{BASE}/auth/users", headers=hl).json()
    ops_id = next(u["id"] for u in users if u["username"] == "ops1")
    assigned = None
    for i, d in enumerate(diffs):
        if i == 0:
            c.post(f"{BASE}/differences/{d['id']}/review", headers=hl, json={"decision": "assign", "comment": "处理", "assignee_id": ops_id})
            assigned = d["id"]
        else:
            c.post(f"{BASE}/differences/{d['id']}/review", headers=hl, json={"decision": "confirm", "comment": "确认"})
    c.post(f"{BASE}/processing-records", headers=ho, json={"difference_item_id": assigned, "action_description": "已修正"})
    c.post(f"{BASE}/tasks/{tid}/verify", headers=hl, data={"demo_dataset_id": "dataset_fangtai_real"})
    c.post(f"{BASE}/tasks/{tid}/report", headers=hl)
    c.post(f"{BASE}/tasks/{tid}/close", headers=hl)
    return diffs


def main():
    with httpx.Client(trust_env=False, timeout=300) as c:
        ha = login(c, "admin", "admin123")
        hl = login(c, "lili", "finance123")
        ho = login(c, "ops1", "ops123")

        baseline_rules(c, ha)

        # --- test_unpublished_center_hidden_or_blocked_in_frontend ---
        c.post(f"{BASE}/admin/business-centers/{BC_ID}/offline", headers=ha)
        centers = c.get(f"{BASE}/business-centers", headers=hl).json()
        hidden = all(x["id"] != BC_ID for x in centers)
        blocked = c.post(f"{BASE}/tasks", headers=hl, data={"name": "x", "demo_dataset_id": "dataset_fangtai_real"}).status_code == 403
        check("test_unpublished_center_hidden_or_blocked_in_frontend", hidden and blocked, f"hidden={hidden} blocked={blocked}")
        publish(c, ha)

        # --- test_page_modules_drive_task_detail_tabs ---
        full = ["today_summary", "create_task", "task_batches", "difference_handling", "pending_review", "processing_progress", "re_verification", "reconciliation_report", "audit_trace"]
        c.post(f"{BASE}/admin/business-centers/{BC_ID}/page-modules", headers=ha, json={"page_modules": [m for m in full if m != "audit_trace"]})
        publish(c, ha)
        d1 = c.get(f"{BASE}/business-centers/{BC_CODE}", headers=hl).json()
        off = "audit_trace" not in (d1.get("page_modules") or [])
        c.post(f"{BASE}/admin/business-centers/{BC_ID}/page-modules", headers=ha, json={"page_modules": full})
        publish(c, ha)
        d2 = c.get(f"{BASE}/business-centers/{BC_CODE}", headers=hl).json()
        on = "audit_trace" in (d2.get("page_modules") or [])
        check("test_page_modules_drive_task_detail_tabs", off and on, f"off_hidden={off} on_restored={on}")

        # 基线任务（v1）
        baseline_rules(c, ha)
        bc = c.get(f"{BASE}/admin/business-centers/{BC_ID}", headers=ha).json()
        rv1 = bc["rule_version_id"]
        tA, tAobj = create_wait(c, hl, "trust-任务A-v1")
        nA, byA = diff_types(c, hl, tA)

        # --- test_workflow_runtime_uses_skill_registry ---
        inv = c.get(f"{BASE}/tasks/{tA}/skill-invocations", headers=ha).json()
        codes = {i["skill_code"] for i in inv}
        check("test_workflow_runtime_uses_skill_registry",
              {"data_import", "field_mapping", "difference_detect", "anomaly_explain"}.issubset(codes),
              f"codes={sorted(codes)}")

        # --- test_skill_invocation_audit_created ---
        logs = c.get(f"{BASE}/tasks/{tA}/audit-logs", headers=hl).json()
        has_skill_audit = any(l["action"] == "skill_invoke" for l in logs)
        check("test_skill_invocation_audit_created", len(inv) >= 4 and has_skill_audit, f"invocations={len(inv)} skill_audit={has_skill_audit}")

        # --- test_mock_ai_is_visible_and_audited ---
        ai_mode = (tAobj.get("summary") or {}).get("ai_mode")
        ai_logs = [l for l in logs if l["action"] == "ai_explain"]
        mode_field = ai_logs[0]["detail"].get("model_mode") if ai_logs else None
        is_mock = str(ai_mode).startswith("mock")
        check("test_mock_ai_is_visible_and_audited",
              ai_mode is not None and mode_field in ("mock", "real"),
              f"summary_ai_mode={ai_mode} audit_model_mode={mode_field} (mock={is_mock})")

        # --- test_rule_version_changes_new_task_result ---
        rv = c.post(f"{BASE}/admin/rule-configs/new-version", headers=ha, json={
            "description": "禁用金额差异", "reusable_rule_suggestion": "停用",
            "rule_overrides": [{"rule_type": "amount_mismatch", "enabled": False}],
        }).json()
        rv2 = rv["rule_version_id"]
        publish(c, ha)
        tB, tBobj = create_wait(c, hl, "trust-任务B-v2")
        nB, byB = diff_types(c, hl, tB)
        check("test_rule_version_changes_new_task_result",
              tBobj["rule_version_id"] == rv2 and byB.get("金额差异", 0) == 0 and nB != nA,
              f"A={nA}{byA} B={nB}{byB}")

        # --- test_old_task_keeps_original_version ---
        nA2, byA2 = diff_types(c, hl, tA)
        check("test_old_task_keeps_original_version",
              tAobj["rule_version_id"] == rv1 and (nA2, byA2) == (nA, byA),
              f"A_rv={tAobj['rule_version_id'][:8]} unchanged={(nA2, byA2) == (nA, byA)}")

        # --- test_invalid_state_transitions_rejected ---
        baseline_rules(c, ha)
        tC, _ = create_wait(c, hl, "trust-任务C-状态机")
        v_pr = c.post(f"{BASE}/tasks/{tC}/verify", headers=hl, data={"demo_dataset_id": "dataset_fangtai_real"}).status_code
        r_pr = c.post(f"{BASE}/tasks/{tC}/report", headers=hl).status_code
        diffs = run_review_to_close(c, hl, ho, tC)
        # closed 只读
        rv_closed = c.post(f"{BASE}/differences/{diffs[0]['id']}/review", headers=hl, json={"decision": "confirm"}).status_code
        check("test_invalid_state_transitions_rejected",
              v_pr == 400 and r_pr == 400 and rv_closed == 400,
              f"verify_pr={v_pr} report_pr={r_pr} closed_review={rv_closed}")

        # --- test_role_based_navigation ---
        ops_admin = c.get(f"{BASE}/admin/business-centers", headers=ho).status_code
        fin_rule = c.post(f"{BASE}/admin/rule-configs/new-version", headers=hl, json={"description": "x", "reusable_rule_suggestion": "x"}).status_code
        adm_admin = c.get(f"{BASE}/admin/business-centers", headers=ha).status_code
        check("test_role_based_navigation",
              ops_admin == 403 and fin_rule == 403 and adm_admin == 200,
              f"ops_admin={ops_admin} finance_rule={fin_rule} admin_admin={adm_admin}")

        # --- test_case_to_rule_version_to_republish ---
        case = c.post(f"{BASE}/differences/{diffs[0]['id']}/archive-case", headers=hl,
                      json={"reusable_rule_suggestion": "加强阈值"}).json()
        rv3 = c.post(f"{BASE}/admin/rule-configs/new-version", headers=ha, json={
            "description": "基于案例升级", "reusable_rule_suggestion": "案例规则", "source_case_id": case["id"],
        }).json()
        publish(c, ha)
        tD, tDobj = create_wait(c, hl, "trust-任务D-案例版本")
        check("test_case_to_rule_version_to_republish",
              "id" in case and tDobj["rule_version_id"] == rv3["rule_version_id"],
              f"case={case.get('id','')[:8]} D_rv_matches={tDobj['rule_version_id'] == rv3['rule_version_id']}")

    print("\n=== 中台可信度反证测试 ===")
    for name, ok, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  // {detail}" if not ok else ""))
    print(f"\nTotal: {sum(1 for _, o, _ in RESULTS if o)}/{len(RESULTS)} passed")


if __name__ == "__main__":
    main()
