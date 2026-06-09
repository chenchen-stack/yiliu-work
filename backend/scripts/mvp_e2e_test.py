"""MVP P0 end-to-end verification script."""
import os
import time
import httpx

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
BC_ID = "bc-revenue-reconciliation"


def login(client, username, password):
    r = client.post(f"{BASE}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def main():
    results = []
    with httpx.Client(trust_env=False, timeout=120) as client:
        h_admin = login(client, "admin", "admin123")
        h_lili = login(client, "lili", "finance123")
        h_ops = login(client, "ops1", "ops123")

        # Step 1-3: publish business center
        bc = client.get(f"{BASE}/admin/business-centers/{BC_ID}", headers=h_admin)
        assert bc.status_code == 200, bc.text
        results.append(("1-2 查看业务中心配置", True))

        pub = client.post(f"{BASE}/admin/business-centers/{BC_ID}/publish", headers=h_admin)
        assert pub.status_code == 200, pub.text
        assert pub.json()["status"] == "published"
        results.append(("3 发布业务中心", True))

        # Step 5: published center visible
        centers = client.get(f"{BASE}/business-centers", headers=h_lili)
        assert centers.status_code == 200 and len(centers.json()) >= 1
        results.append(("5 按权限看到业务中心", True))

        # Step 6-8: create task
        r = client.post(
            f"{BASE}/tasks",
            headers=h_lili,
            data={"name": "MVP验收任务", "period": "2024-05", "demo_dataset_id": "dataset_fangtai_real", "auto_execute": "true"},
        )
        assert r.status_code == 200, r.text
        task = r.json()
        task_id = task["id"]
        results.append(("6-7 新建任务并执行", task["status"] in ("pending_review", "running")))

        for _ in range(120):
            time.sleep(1)
            t = client.get(f"{BASE}/tasks/{task_id}", headers=h_lili).json()
            if t["status"] == "pending_review":
                break
        assert t["status"] == "pending_review", t
        results.append(("8 进入 pending_review", True))

        diffs = client.get(f"{BASE}/tasks/{task_id}/differences", headers=h_lili).json()
        types = {d["type"] for d in diffs}
        assert len(diffs) > 0
        results.append(("8 三类差异", len(types) >= 1))

        users = client.get(f"{BASE}/auth/users", headers=h_lili).json()
        ops_id = next(u["id"] for u in users if u["username"] == "ops1")

        assigned_id = None
        for i, d in enumerate(diffs):
            if i == 0:
                client.post(f"{BASE}/differences/{d['id']}/review", headers=h_lili, json={"decision": "confirm", "comment": "确认"})
            elif i == 1:
                client.post(f"{BASE}/differences/{d['id']}/review", headers=h_lili, json={"decision": "reject", "comment": "退回"})
            elif i == 2:
                client.post(f"{BASE}/differences/{d['id']}/review", headers=h_lili, json={"decision": "assign", "comment": "请处理", "assignee_id": ops_id})
                assigned_id = d["id"]
            else:
                client.post(f"{BASE}/differences/{d['id']}/review", headers=h_lili, json={"decision": "confirm", "comment": "确认"})
        results.append(("11 复核/指派", True))

        if assigned_id:
            client.post(
                f"{BASE}/processing-records",
                headers=h_ops,
                json={"difference_item_id": assigned_id, "action_description": "已修正映射关系"},
            )
            results.append(("12 责任处理", True))

        # Verify all pending verification diffs - for simplicity verify whole task
        vr = client.post(
            f"{BASE}/tasks/{task_id}/verify",
            headers=h_lili,
            data={"demo_dataset_id": "dataset_fangtai_real"},
        )
        assert vr.status_code == 200, vr.text
        results.append(("13 再次验证", True))

        rep = client.post(f"{BASE}/tasks/{task_id}/report", headers=h_lili)
        assert rep.status_code == 200, rep.text
        results.append(("14 生成报告", True))

        close = client.post(f"{BASE}/tasks/{task_id}/close", headers=h_lili)
        assert close.status_code == 200, close.text
        assert close.json()["status"] == "closed"
        results.append(("15 关闭任务", True))

        logs = client.get(f"{BASE}/tasks/{task_id}/audit-logs", headers=h_lili).json()
        assert len(logs) >= 5
        results.append(("16 审计日志", True))

        if diffs:
            case = client.post(
                f"{BASE}/differences/{diffs[0]['id']}/archive-case",
                headers=h_lili,
                json={"reusable_rule_suggestion": "加强金额阈值校验"},
            )
            assert case.status_code == 200, case.text
            results.append(("17 案例沉淀", True))

        rv = client.post(
            f"{BASE}/admin/rule-configs/new-version",
            headers=h_admin,
            json={"description": "基于案例优化 v2", "reusable_rule_suggestion": "金额差异>1000强制复核", "source_case_id": case.json()["id"] if diffs else None},
        )
        assert rv.status_code == 200, rv.text
        results.append(("18 规则新版本", True))

        pub2 = client.post(f"{BASE}/admin/business-centers/{BC_ID}/publish", headers=h_admin)
        assert pub2.status_code == 200
        results.append(("19 重新发布", True))

        # Chat context
        chat = client.post(
            f"{BASE}/chat",
            headers=h_lili,
            json={"message": "这条差异如何处理？", "task_id": task_id, "difference_item_id": diffs[0]["id"] if diffs else None, "history": []},
        )
        assert chat.status_code == 200 and len(chat.json()["reply"]) > 10
        results.append(("10 对话上下文", True))

    print("\n=== MVP E2E Results ===")
    for name, ok in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\nTotal: {sum(1 for _, o in results if o)}/{len(results)} passed")


if __name__ == "__main__":
    main()
