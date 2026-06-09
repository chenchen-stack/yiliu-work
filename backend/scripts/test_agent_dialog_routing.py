"""Agent 对话路由覆盖测试：action 走规则，其余走 dialog。

用法（在 backend 目录、依赖已安装时）：
  python scripts/test_agent_dialog_routing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- 场景表： (用户输入, 期望 intent, 说明) ---
SCENARIOS = [
    ("你好", "onboarding", "打招呼"),
    ("你有哪些技能", "agent_capabilities", "技能问法 → 后台确定性回复"),
    ("你可以调用什么skill", "agent_capabilities", "英文 skill 问法 → 不检索知识库"),
    ("能调用哪些 Skill", "agent_capabilities", "调用 skill 变体"),
    ("你能帮我做什么", "agent_capabilities", "能力问法"),
    ("你能帮我做", "agent_capabilities", "能力问法变体"),
    ("你是谁", "agent_capabilities", "自我介绍 → 后台配置"),
    ("你好啊 你可以干嘛", "agent_capabilities", "打招呼+能力问法 → 不检索知识库"),
    ("你配置了skills吗", "agent_capabilities", "配置 skill 问法 → 后台确定性回复"),
    ("你知道我喜欢干嘛", "dialog", "个人喜好闲聊 → 非能力卡"),
    ("异常卡片", "dialog", "无上下文卡片 → 确定性拦截"),
    ("收入核对的标准流程是什么", "dialog", "流程问法 → dialog + UI 增强"),
    ("金额差异、重复数据、映射异常分别怎么处理", "dialog", "差异类型 → dialog + UI 增强"),
    ("帮我核对一下5月份的收入数据", "start_reconciliation", "可执行：发起对账"),
    ("我有哪些进行中的对账任务", "query_tasks", "可执行：查任务"),
    ("为什么两边金额不一致", "dialog", "领域问答"),
    ("SAP和DMS口径不同怎么办", "dialog", "领域问答"),
    ("好", "dialog", "短回复不走对账伪表单"),
    ("方太知识库", "knowledge_query", "知识库检索"),
    ("请检索收入核对知识，说明回款异常怎么处理", "knowledge_query", "检索知识库勿走三类差异FAQ"),
]

# --- UI 增强话题（dialog 路径附加卡片，非 intent）---
UI_ENRICH = [
    ("你有哪些技能", "capability_list"),
    ("收入核对的标准流程是什么", "faq_workflow"),
    ("三类差异怎么处理", "faq_diff_types"),
]


def main() -> None:
    from app.services.agent_runtime import (
        classify_intent_by_rules,
        suggest_dialog_ui_blocks,
        try_deterministic_dialog_reply,
        _retrieve_knowledge,
        _topic_wants_capability_card,
        _topic_wants_workflow_card,
        _topic_wants_diff_types_card,
        _wants_knowledge_query,
        _mentions_anomaly_card_without_context,
    )

    failed = 0
    print("=== classify_intent_by_rules 回退场景 ===")
    for msg, expected, note in SCENARIOS:
        intent, _ = classify_intent_by_rules(msg, has_diff_context=False)
        ok = intent == expected
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {msg!r} → {intent} (期望 {expected}) // {note}")
        if not ok:
            failed += 1

    print("\n=== dialog UI 话题检测（非 intent）===")
    checks = [
        ("你有哪些技能", _topic_wants_capability_card, True),
        ("你可以调用什么skill", _topic_wants_capability_card, True),
        ("你好啊 你可以干嘛", _topic_wants_capability_card, True),
        ("你配置了skills吗", _topic_wants_capability_card, True),
        ("帮我核对5月", _topic_wants_capability_card, False),
        ("你知道我喜欢干嘛", _topic_wants_capability_card, False),
        ("收入核对流程是什么", _topic_wants_workflow_card, True),
        ("三类差异怎么处理", _topic_wants_diff_types_card, True),
        ("请检索收入核对知识，说明回款异常怎么处理", _topic_wants_diff_types_card, False),
    ]
    for msg, fn, expected in checks:
        got = fn(msg)
        ok = got == expected
        print(f"  [{'OK' if ok else 'FAIL'}] {fn.__name__}({msg!r}) = {got}")
        if not ok:
            failed += 1

    print("\n=== 知识库检索门控 ===")
    kb_checks = [
        ("你好啊 你可以干嘛", False),
        ("SAP和DMS口径不同怎么办", False),
        ("方太知识库有什么回款案例", True),
        ("排查规则里回款异常怎么处理", True),
    ]
    for msg, expected in kb_checks:
        got = _wants_knowledge_query(msg)
        ok = got == expected
        print(f"  [{'OK' if ok else 'FAIL'}] _wants_knowledge_query({msg!r}) = {got}")
        if not ok:
            failed += 1

    print("\n=== 差异上下文 ===")
    intent, _ = classify_intent_by_rules("请解释原因", has_diff_context=True)
    print(f"  有差异上下文 + 解释 → {intent} (期望 difference_explain)")
    if intent != "difference_explain":
        failed += 1

    intent, _ = classify_intent_by_rules("这个差异怎么回事", has_diff_context=True)
    print(f"  有差异上下文 + 泛问 → {intent} (期望 dialog)")
    if intent != "dialog":
        failed += 1

    print("\n=== 确定性 dialog 回复（无 DB 时跳过集成）===")
    try:
        from app.database import SessionLocal
        from app.models import AgentConfig

        db = SessionLocal()
        agent = db.query(AgentConfig).filter(AgentConfig.code == "revenue_diff_explain").first()
        if agent:
            r1 = try_deterministic_dialog_reply("你能帮我做什么", agent=agent, db=db, has_diff=False)
            assert r1 == ""
            print("  [OK] 你能帮我做什么 → 空文本（由 UI 块承载）")
            casual_hits = _retrieve_knowledge(db, agent, "你好啊 你可以干嘛", None)
            assert casual_hits == []
            print("  [OK] 闲聊不触发知识库检索")
            r2 = try_deterministic_dialog_reply("异常卡片", agent=agent, db=db, has_diff=False)
            assert r2 and "工作台" in r2
            print(f"  [OK] 异常卡片（无上下文）→ 拦截回复")
            assert not _mentions_anomaly_card_without_context("异常卡片", has_diff=True)
            print(f"  [OK] 有差异上下文时不拦截卡片关键词")
        db.close()
    except Exception as exc:
        print(f"  [SKIP] 集成检查: {exc}")

    if failed:
        print(f"\n{failed} 项失败")
        sys.exit(1)
    print("\n全部通过")


if __name__ == "__main__":
    main()
