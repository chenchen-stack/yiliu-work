"""Phase 4 验证：规则版本真实生效 + 老任务隔离。"""
import os
import time
import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
BC_ID = "bc-revenue-reconciliation"


def login(client, u, p):
    r = client.post(f"{BASE}/auth/login", json={"username": u, "password": p})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def create_and_wait(client, h, name):
    r = client.post(f"{BASE}/tasks", headers=h, data={"name": name, "period": "2024-05", "demo_dataset_id": "dataset_fangtai_real", "auto_execute": "true"})
    r.raise_for_status()
    tid = r.json()["id"]
    for _ in range(180):
        time.sleep(1)
        t = client.get(f"{BASE}/tasks/{tid}", headers=h).json()
        if t["status"] in ("pending_review", "failed"):
            break
    return tid, t


def count_by_type(client, h, tid):
    diffs = client.get(f"{BASE}/tasks/{tid}/differences", headers=h).json()
    by = {}
    for d in diffs:
        by[d["type"]] = by.get(d["type"], 0) + 1
    return len(diffs), by


def main():
    with httpx.Client(trust_env=False, timeout=300) as c:
        ha = login(c, "admin", "admin123")
        hl = login(c, "lili", "finance123")

        # 建立确定性基线：所有三类规则启用、阈值归零（不依赖历史状态）
        base = c.post(f"{BASE}/admin/rule-configs/new-version", headers=ha, json={
            "description": "Phase4 基线：全部规则启用",
            "reusable_rule_suggestion": "baseline",
            "rule_overrides": [
                {"rule_type": "amount_mismatch", "enabled": True, "threshold": 0},
                {"rule_type": "duplicate_record", "enabled": True},
                {"rule_type": "mapping_anomaly", "enabled": True},
            ],
        })
        base.raise_for_status()
        c.post(f"{BASE}/admin/business-centers/{BC_ID}/publish", headers=ha)

        bc = c.get(f"{BASE}/admin/business-centers/{BC_ID}", headers=ha).json()
        rv1 = bc["rule_version_id"]
        tA, tAobj = create_and_wait(c, hl, "Phase4-任务A-v1")
        nA, byA = count_by_type(c, hl, tA)
        print(f"[A] rule_version={tAobj['rule_version_id']} total={nA} by_type={byA}")

        # 创建 v2：禁用 amount_mismatch 规则
        rv = c.post(f"{BASE}/admin/rule-configs/new-version", headers=ha, json={
            "description": "Phase4 验证：禁用金额差异规则",
            "reusable_rule_suggestion": "暂停金额差异检测",
            "rule_overrides": [{"rule_type": "amount_mismatch", "enabled": False}],
        })
        rv.raise_for_status()
        rv2 = rv.json()["rule_version_id"]
        print(f"[v2] created rule_version={rv2} overrides={rv.json().get('rule_overrides')}")
        c.post(f"{BASE}/admin/business-centers/{BC_ID}/publish", headers=ha)

        tB, tBobj = create_and_wait(c, hl, "Phase4-任务B-v2")
        nB, byB = count_by_type(c, hl, tB)
        print(f"[B] rule_version={tBobj['rule_version_id']} total={nB} by_type={byB}")

        # 重新读取 A，确认未被污染
        nA2, byA2 = count_by_type(c, hl, tA)
        print(f"[A-recheck] total={nA2} by_type={byA2}")

        checks = {
            "A 绑定 v1": tAobj["rule_version_id"] == rv1,
            "B 绑定 v2": tBobj["rule_version_id"] == rv2,
            "A 含金额差异": byA.get("金额差异", 0) > 0,
            "B 无金额差异(v2禁用生效)": byB.get("金额差异", 0) == 0,
            "B 结果数量变化": nB != nA,
            "A 结果未被污染": (nA2, byA2) == (nA, byA),
        }
        print("\n=== Phase 4 Checks ===")
        for k, v in checks.items():
            print(f"[{'PASS' if v else 'FAIL'}] {k}")
        print(f"\nTotal: {sum(checks.values())}/{len(checks)} passed")


if __name__ == "__main__":
    main()
