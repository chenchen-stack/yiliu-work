"""验收 ontology 节点：Workflow 配置 + 对账任务执行记录。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
WF_ID = "wf-revenue-reconciliation-v1"
BC_ID = "bc-revenue-reconciliation"
DEMO_ID = "dataset_fangtai_real"


def _req(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    form: dict | None = None,
) -> dict | list:
    headers: dict[str, str] = {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"{method} {path} -> {e.code}: {err}") from e


def login() -> str:
    out = _req("POST", "/api/v1/auth/login", body={"username": "admin", "password": "admin123"})
    return out["access_token"]


def ensure_workflow_nodes(nodes: list[dict]) -> list[dict]:
    """与 workflow_engine.ensure_workflow_nodes 一致（避免脚本未在 app 包内运行）。"""
    from app.services.workflow_engine import ensure_workflow_nodes as _ensure

    return _ensure(nodes)


def main() -> None:
    print("== 健康检查 ==")
    with urllib.request.urlopen(f"{BASE}/health", timeout=10) as resp:
        health = json.load(resp)
    print(json.dumps(health, ensure_ascii=False, indent=2))

    token = login()
    print("\n== Workflow 节点（API 原始） ==")
    wf = _req("GET", f"/api/v1/admin/workflows/{WF_ID}", token=token)
    raw_ids = [n.get("id") for n in (wf.get("nodes") or [])]
    print("DB nodes:", " -> ".join(raw_ids))
    has_ontology_db = "ontology" in raw_ids

    merged = ensure_workflow_nodes(wf.get("nodes") or [])
    merged_ids = [n["id"] for n in merged]
    print("合并后（与前端 ensureWorkflowNodes 一致）:", " -> ".join(merged_ids))

    if not has_ontology_db:
        print("\n== DB 缺 ontology，模拟「保存」写入 ==")
        wf = _req(
            "PATCH",
            f"/api/v1/admin/workflows/{WF_ID}",
            token=token,
            body={
                "node_order": merged_ids,
                "nodes": [{"id": n["id"], "enabled": n.get("enabled", True)} for n in merged],
            },
        )
        raw_ids = [n.get("id") for n in (wf.get("nodes") or [])]
        print("保存后 DB nodes:", " -> ".join(raw_ids))
    else:
        print("\nDB 已含 ontology，无需保存")

    print("\n== 业务中心发布状态 ==")
    bc = _req("GET", f"/api/v1/admin/business-centers/{BC_ID}", token=token)
    print(f"status={bc.get('status')}")
    if bc.get("status") != "published":
        bc = _req("POST", f"/api/v1/admin/business-centers/{BC_ID}/publish", token=token)
        print(f"已发布 -> status={bc.get('status')}")

    print("\n== 语义层实体（任务 ontology 步骤依赖） ==")
    stats = _req("GET", "/api/v1/admin/ontology/stats", token=token)
    print(json.dumps(stats, ensure_ascii=False))
    if (stats.get("entity_count") or 0) <= 0:
        print("抽取语义层...")
        reload = _req("POST", "/api/v1/admin/ontology/reload", token=token)
        print(json.dumps(reload, ensure_ascii=False, indent=2))
        stats = _req("GET", "/api/v1/admin/ontology/stats", token=token)
        print("抽取后:", json.dumps(stats, ensure_ascii=False))

    print("\n== 创建并执行对账任务（演示数据集） ==")
    task = _req(
        "POST",
        "/api/v1/tasks",
        token=token,
        form={
            "name": f"ontology验收-{int(time.time())}",
            "period": "2024-05",
            "demo_dataset_id": DEMO_ID,
            "auto_execute": "true",
        },
    )
    task_id = task["id"]
    print(f"task_id={task_id} status={task.get('status')}")

    ontology_run = None
    ontology_inv = None
    for i in range(90):
        time.sleep(2)
        task = _req("GET", f"/api/v1/tasks/{task_id}", token=token)
        runs = _req("GET", f"/api/v1/tasks/{task_id}/workflow-runs", token=token)
        invs = _req("GET", f"/api/v1/tasks/{task_id}/skill-invocations", token=token)
        ontology_run = next((r for r in runs if r.get("node_id") == "ontology"), None)
        ontology_inv = next((r for r in invs if r.get("skill_code") == "ontology_context"), None)
        node_ids = [r.get("node_id") for r in runs]
        print(
            f"  [{i+1}] task={task.get('status')} progress={task.get('progress')}% "
            f"runs={len(runs)} nodes={' -> '.join(node_ids) if node_ids else '(none)'}"
        )
        if ontology_run and ontology_inv:
            break
        if task.get("status") in ("failed", "review_pending", "completed", "verified"):
            break

    print("\n== ontology WorkflowRun ==")
    if ontology_run:
        print(json.dumps(ontology_run, ensure_ascii=False, indent=2))
    else:
        print("未找到 node_id=ontology 的执行记录")

    print("\n== ontology_context SkillInvocation ==")
    if ontology_inv:
        print(json.dumps(ontology_inv, ensure_ascii=False, indent=2))
    else:
        print("未找到 skill_code=ontology_context 的调用记录")

    summary = (task.get("summary") or {}) if isinstance(task, dict) else {}
    oc = summary.get("ontology_context")
    print("\n== task.summary.ontology_context ==")
    print(json.dumps(oc, ensure_ascii=False, indent=2) if oc else "(missing)")

    ok = bool(ontology_run and ontology_inv and oc)
    print("\n" + ("验收通过" if ok else "验收未完全通过 — 请查看上方日志"))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
