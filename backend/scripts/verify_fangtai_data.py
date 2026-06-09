"""验证方太真实 POC 数据三条路径可用。"""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def _get(path: str, token: str) -> dict | list:
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def main() -> None:
    login_req = urllib.request.Request(
        f"{BASE}/api/v1/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(login_req, timeout=10) as resp:
        token = json.load(resp)["access_token"]

    ds = _get("/api/v1/admin/datasources", token)
    print(f"1. 数据源: {len(ds)} 张")
    for row in sorted(ds, key=lambda x: x["name"]):
        print(f"   - {row['name']} ({row['row_count']} 行)")

    demo = _get("/api/v1/demo-datasets", token)
    print("2. 演示数据集:")
    for row in demo:
        print(f"   - {row['id']}: {row['name']}")

    chat = _get("/api/v1/chat/reconciliation-options", token)
    rec = chat["recommended"]
    print("3. 对话对账:")
    print(f"   mapping_ready={chat['mapping_ready']}")
    print(f"   推荐: {rec['business_name']} <-> {rec['finance_name']}")
    print(f"   demo_dataset_id={chat['demo_dataset_id']}")

    launch = _get("/api/v1/business-centers/revenue_reconciliation/launch-options", token)
    pair = (launch.get("datasource_pairs") or [{}])[0]
    print("4. 新建任务:")
    print(f"   mapping_ready={launch.get('mapping_ready')}")
    print(f"   {pair.get('business_name')} <-> {pair.get('finance_name')}")


if __name__ == "__main__":
    main()
