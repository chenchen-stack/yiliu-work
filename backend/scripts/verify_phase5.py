"""Phase 5 验证：非法状态流转拦截 + closed 只读。"""
import os
import time
import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8014/api/v1")
BC_ID = "bc-revenue-reconciliation"


def login(c, u, p):
    r = c.post(f"{BASE}/auth/login", json={"username": u, "password": p})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main():
    checks = {}
    with httpx.Client(trust_env=False, timeout=120) as c:
        ha = login(c, "admin", "admin123")
        hl = login(c, "lili", "finance123")
        ho = login(c, "ops1", "ops123")
        c.post(f"{BASE}/admin/business-centers/{BC_ID}/publish", headers=ha)

        r = c.post(f"{BASE}/tasks", headers=hl, data={"name": "Phase5-状态机", "period": "2024-05", "demo_dataset_id": "dataset_fangtai_real", "auto_execute": "true"})
        tid = r.json()["id"]
        for _ in range(120):
            time.sleep(1)
            t = c.get(f"{BASE}/tasks/{tid}", headers=hl).json()
            if t["status"] in ("pending_review", "failed"):
                break
        checks["任务进入 pending_review"] = t["status"] == "pending_review"

        # 非法：pending_review 直接 verify
        v = c.post(f"{BASE}/tasks/{tid}/verify", headers=hl, data={"demo_dataset_id": "dataset_fangtai_real"})
        checks["pending_review 直接 verify 被拒(400)"] = v.status_code == 400

        # 非法：pending_review 直接 report
        rp = c.post(f"{BASE}/tasks/{tid}/report", headers=hl)
        checks["pending_review 直接 report 被拒(400)"] = rp.status_code == 400

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

        # 非法：重复复核已确认差异
        if len(diffs) > 1:
            re_review = c.post(f"{BASE}/differences/{diffs[1]['id']}/review", headers=hl, json={"decision": "confirm", "comment": "再次"})
            checks["重复复核已确认差异被拒(400)"] = re_review.status_code == 400

        # ops 处理 → 任务 pending_verification
        c.post(f"{BASE}/processing-records", headers=ho, json={"difference_item_id": assigned, "action_description": "已修正"})
        t = c.get(f"{BASE}/tasks/{tid}", headers=hl).json()
        checks["处理后进入 pending_verification"] = t["status"] == "pending_verification"

        # 合法：verify
        v2 = c.post(f"{BASE}/tasks/{tid}/verify", headers=hl, data={"demo_dataset_id": "dataset_fangtai_real"})
        checks["pending_verification 可 verify(200)"] = v2.status_code == 200
        print(f"DEBUG verify resp={v2.status_code} body={v2.text}")

        t = c.get(f"{BASE}/tasks/{tid}", headers=hl).json()
        print(f"DEBUG task status after verify={t['status']}")
        odiffs = c.get(f"{BASE}/tasks/{tid}/differences", headers=hl).json()
        print(f"DEBUG diff statuses={[ (d['type'], d['status']) for d in odiffs]}")
        # 合法：report（reporting 状态）
        rp2 = c.post(f"{BASE}/tasks/{tid}/report", headers=hl)
        checks["reporting 可生成报告(200)"] = rp2.status_code == 200

        # 合法：close
        cl = c.post(f"{BASE}/tasks/{tid}/close", headers=hl)
        checks["reporting 可关闭(200)"] = cl.status_code == 200 and cl.json()["status"] == "closed"

        # closed 只读：review / verify / processing 全部被拒
        rv_closed = c.post(f"{BASE}/differences/{diffs[0]['id']}/review", headers=hl, json={"decision": "confirm", "comment": "x"})
        checks["closed 后复核被拒(400)"] = rv_closed.status_code == 400
        v_closed = c.post(f"{BASE}/tasks/{tid}/verify", headers=hl, data={"demo_dataset_id": "dataset_fangtai_real"})
        checks["closed 后 verify 被拒(400)"] = v_closed.status_code == 400

    print("\n=== Phase 5 Checks ===")
    for k, v in checks.items():
        print(f"[{'PASS' if v else 'FAIL'}] {k}")
    print(f"\nTotal: {sum(checks.values())}/{len(checks)} passed")


if __name__ == "__main__":
    main()
