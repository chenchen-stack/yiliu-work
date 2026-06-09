"""Quick E2E smoke test for POC API."""
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
SAMPLE = Path(__file__).resolve().parent.parent.parent / "sample-data"


def main():
    with httpx.Client(trust_env=False, timeout=60) as client:
        r = client.post(f"{BASE}/auth/login", json={"username": "lili", "password": "finance123"})
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        with open(SAMPLE / "sap_sample.csv", "rb") as sap, open(SAMPLE / "dms_sample.csv", "rb") as dms, open(
            SAMPLE / "fanruan_sample.csv", "rb"
        ) as fan:
            r = client.post(
                f"{BASE}/tasks",
                headers=h,
                data={"name": "smoke-test"},
                files={
                    "sap_file": ("sap.csv", sap, "text/csv"),
                    "dms_file": ("dms.csv", dms, "text/csv"),
                    "fanruan_file": ("fan.csv", fan, "text/csv"),
                },
            )
        assert r.status_code == 200, r.text
        task_id = r.json()["id"]
        print("task created:", task_id)

        for _ in range(30):
            time.sleep(1)
            t = client.get(f"{BASE}/tasks/{task_id}", headers=h).json()
            print("status:", t["status"], t["progress"])
            if t["status"] in ("reviewing", "completed", "failed"):
                break

        diffs = client.get(f"{BASE}/tasks/{task_id}/differences", headers=h).json()
        print("differences:", len(diffs), [d["type"] for d in diffs])
        assert len(diffs) > 0, "expected at least one difference"

        for d in diffs:
            client.post(
                f"{BASE}/differences/{d['id']}/review",
                headers=h,
                json={"decision": "confirm", "comment": "smoke test"},
            )

        r = client.post(f"{BASE}/tasks/{task_id}/complete", headers=h)
        print("complete:", r.status_code, r.json())
        assert r.status_code == 200
        print("E2E OK")


if __name__ == "__main__":
    main()
