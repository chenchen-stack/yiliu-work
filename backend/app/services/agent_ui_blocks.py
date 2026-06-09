"""Agent 对话可视化 UI 块构建（与 ChatActionCards 类型约定一致）。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import Difference, Task, Workflow
from app.services.ai_analyzer import PARTY_LABEL, RULE_TYPE_LABEL, diff_item_from_model
from app.services.chat_actions import build_faq_workflow_block
from app.services.platform_seed import IDS

# 与工作台 TaskExecutionPanel / 对话 faq_workflow 横向步骤标题一致
_PIPELINE_LABEL_BY_ID = {
    "import": "加载数据",
    "mapping": "字段映射",
    "detect": "差异识别",
    "ai_explain": "异常解释",
    "review": "复核流转",
    "verify": "再次验证",
    "report": "报告生成",
}


def build_workflow_block_from_db(db: Session, workflow_id: str | None) -> dict[str, Any]:
    wf_id = workflow_id or IDS.get("workflow")
    wf = db.query(Workflow).filter(Workflow.id == wf_id).first() if wf_id else None
    if not wf or not wf.nodes:
        return build_faq_workflow_block()
    steps = []
    for node in wf.nodes:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id") or "")
        steps.append({
            "title": _PIPELINE_LABEL_BY_ID.get(nid) or node.get("label") or nid or "步骤",
            "desc": node.get("description") or node.get("skill_code") or "",
        })
    return {
        "type": "faq_workflow",
        "data": {
            "title": wf.name or "标准核对流程",
            "steps": steps or build_faq_workflow_block()["data"]["steps"],
            "hint": "如需正式对账，请说明周期后发起，或点击下方进入工作台。",
            "workflow_id": wf.id,
            "workbench_path": "/workbench/reconciliation/tasks/new",
        },
    }

INTENT_META: dict[str, dict[str, str]] = {
    "onboarding": {"label": "欢迎引导", "color": "blue", "icon": "wave"},
    "operate": {"label": "发起对账", "color": "orange", "icon": "play"},
    "start_reconciliation": {"label": "数据源确认", "color": "orange", "icon": "database"},
    "query_tasks": {"label": "查询任务", "color": "cyan", "icon": "list"},
    "workflow_guide": {"label": "核对流程", "color": "purple", "icon": "flow"},
    "faq_diff_types": {"label": "差异类型", "color": "gold", "icon": "diff"},
    "difference_explain": {"label": "差异解释", "color": "green", "icon": "explain"},
    "list_differences": {"label": "差异清单", "color": "orange", "icon": "list"},
    "analyze": {"label": "分析问答", "color": "geekblue", "icon": "brain"},
    "upload": {"label": "数据接入", "color": "lime", "icon": "upload"},
    "progress": {"label": "进度查询", "color": "cyan", "icon": "clock"},
    "dialog": {"label": "自然语言对话", "color": "default", "icon": "chat"},
    "agent_capabilities": {"label": "技能清单", "color": "blue", "icon": "list"},
    "knowledge_query": {"label": "知识库检索", "color": "gold", "icon": "book"},
    "chitchat": {"label": "自然语言对话", "color": "default", "icon": "chat"},
    "suggest_workflow": {"label": "引导工作台", "color": "purple", "icon": "workbench"},
}


_SKILL_TYPE_LABEL = {
    "ability": "能力型",
    "knowledge": "知识型",
    "process": "流程型",
}


def _resolve_skill_item(db: Session, sid: str) -> dict[str, str]:
    """从 Skill 表 + skill_packages 读取名称与说明。"""
    from app.models import Skill
    from app.services.skill_package_engine import get_skill_manifest

    sk = db.query(Skill).filter((Skill.id == sid) | (Skill.code == sid)).first()
    code = (sk.code if sk else sid.replace("skill-", "")).strip()
    manifest = get_skill_manifest(code) if code else None
    name = (manifest.name if manifest else None) or (sk.name if sk else sid)
    stype = (manifest.type if manifest else None) or (sk.type if sk else "ability")
    desc = (manifest.description if manifest else "") or ""
    if not desc:
        if "query" in sid or "任务" in name:
            desc = "查看对账任务进度与待复核条数"
        elif "anomaly" in sid or "异常" in name:
            desc = "结合规则与证据链解释差异根因"
        else:
            desc = f"{_SKILL_TYPE_LABEL.get(stype, '已授权')} Skill"
    icon = "diff" if ("异常" in name or "anomaly" in sid) else "list"
    return {
        "id": sk.id if sk else sid,
        "code": code,
        "title": name,
        "desc": desc,
        "icon": icon,
        "type": stype,
    }


_SKILL_USAGE_HINTS: dict[str, str] = {
    "anomaly_explain": "在收入核对工作台打开某条「待复核」差异后追问，或在对话绑定差异上下文时使用。",
    "query_tasks": "在对话中说「我有哪些进行中的对账任务」或点击「查看任务」快捷按钮。",
    "query_tasks_skill": "在对话中说「我有哪些进行中的对账任务」或点击「查看任务」快捷按钮。",
}

# Workflow 七步中由引擎自动调度的节点（skill_registry）
_WORKFLOW_AUTOMATED = frozenset({
    "data_import", "ontology_context", "field_mapping", "difference_detect", "anomaly_explain",
})
# 仅对话 Agent 路由、不在 Workflow 链路中的 Skill
_CHAT_AGENT_SKILLS = frozenset({"query_tasks"})


def _normalize_schema_for_ui(schema: dict | None) -> dict[str, Any]:
    """将 skill.yaml 的扁平字段表转为带 properties 的结构，供前台展示。"""
    if not schema or not isinstance(schema, dict):
        return {}
    if "properties" in schema and isinstance(schema.get("properties"), dict):
        return schema
    field_keys = [
        k for k, v in schema.items()
        if isinstance(v, dict) and ("type" in v or "description" in v or "properties" in v)
    ]
    if field_keys:
        return {"properties": {k: schema[k] for k in field_keys}}
    return schema


def _resolve_skill_execution(code: str) -> tuple[str, str, bool]:
    """返回 (execution_mode, execution_label, registry_registered)。"""
    from app.services.skill_package_engine import has_executor
    from app.services.skill_registry import has_skill

    registered = bool(code and has_skill(code))
    if code and has_executor(code):
        return (
            "execute_py",
            "Skill 包 execute.py：Workflow 节点或管理后台在线测试可调用",
            registered,
        )
    if code in _CHAT_AGENT_SKILLS and registered:
        return (
            "chat_agent",
            "对话 Agent 经 SkillRegistry 直接调用，返回任务列表等 UI 卡片；不参与 Workflow 七步核对链路",
            True,
        )
    if code in _WORKFLOW_AUTOMATED and registered:
        return (
            "workflow_automated",
            "Workflow 自动流水线节点：任务执行时由 SkillRegistry 真实调用",
            True,
        )
    if registered:
        return (
            "workflow_manual",
            "Workflow 人工/复核网关节点或 API 触发（SkillRegistry 登记，非全自动流水线）",
            True,
        )
    return ("configured", "平台已登记；执行逻辑见 skill_packages 说明书", False)


def build_chat_skill_detail(db: Session, skill_id: str) -> dict[str, Any]:
    """对话内 Skill 详情（manifest + 库表 + 注册表，与 skill_packages 对齐）。"""
    from app.models import Skill
    from app.services.skill_package_engine import get_skill_manifest, has_executor

    base = _resolve_skill_item(db, skill_id)
    code = base.get("code") or ""
    sk = db.query(Skill).filter((Skill.id == skill_id) | (Skill.code == skill_id) | (Skill.code == code)).first()
    manifest = get_skill_manifest(code) if code else None
    hint = _SKILL_USAGE_HINTS.get(code) or _SKILL_USAGE_HINTS.get(skill_id.replace("skill-", ""), "")
    if not hint:
        hint = "在对话中描述与核对、差异、任务相关的需求，系统将按授权自动路由到本 Skill。"
    exec_mode, exec_label, registry_ok = _resolve_skill_execution(code)
    raw_in = manifest.input_schema if manifest else {}
    raw_out = manifest.output_schema if manifest else {}
    return {
        "id": base.get("id") or skill_id,
        "code": code,
        "name": base["title"],
        "type": base["type"],
        "type_label": _SKILL_TYPE_LABEL.get(base["type"], base["type"]),
        "description": (manifest.description if manifest else None) or base["desc"],
        "status": (sk.status if sk else None) or (manifest.status if manifest else "published"),
        "version": int((sk.version if sk else None) or (manifest.version if manifest else 1)),
        "category": (manifest.category if manifest else None) or None,
        "has_executor": bool(has_executor(code)) if code else False,
        "registry_registered": registry_ok,
        "execution_mode": exec_mode,
        "execution_label": exec_label,
        "input_schema": _normalize_schema_for_ui(raw_in),
        "output_schema": _normalize_schema_for_ui(raw_out),
        "dependencies": manifest.dependencies if manifest else {},
        "usage_hint": hint,
        "package_id": (manifest.id if manifest else None) or (f"skill-{code}" if code else skill_id),
    }


def agent_allows_skill(agent, skill_id: str, db: Session) -> bool:
    """当前 Agent 是否授权了该 Skill（id / code / skill-{code} 均可）。"""
    from app.models import Skill

    allowed = set(agent.allowed_skill_ids or [])
    if not allowed:
        return False
    if skill_id in allowed:
        return True
    sk = db.query(Skill).filter((Skill.id == skill_id) | (Skill.code == skill_id)).first()
    if sk:
        return sk.id in allowed or sk.code in allowed or f"skill-{sk.code}" in allowed
    code = skill_id.replace("skill-", "")
    return code in allowed or f"skill-{code}" in allowed


def build_workbench_grounding(db: Session) -> str:
    """前台工作台 / 业务中心事实，供 LLM 对齐方太收入核对场景。"""
    from app.services.platform_seed import get_published_business_center

    bc = get_published_business_center(db)
    if not bc:
        return (
            "【前台工作台】收入核对中心 /workbench/reconciliation\n"
            "业务域：方太 SAP 发货开票 × DMS 收入台账 收入核对\n"
            "核心差异类型：金额差异、重复数据、主数据/映射异常"
        )
    from app.services.chat_actions import load_published_rule_configs

    rules, rv_id = load_published_rule_configs(db)
    rule_line = "、".join(r.name for r in rules[:8]) if rules else "金额差异、重复数据、主数据/映射异常"
    rv_hint = f"规则版本 {rv_id[:8]}…（{len(rules)} 条启用）" if rv_id and rules else ""
    modules = "、".join(bc.page_modules or [])[:200]
    return (
        f"【前台工作台】{bc.name}（/workbench/reconciliation）\n"
        f"业务中心状态：{bc.status} · 版本 v{bc.version or 1}\n"
        "业务域：方太制造业收入核对 — SAP 结算行/发货开票 与 DMS 收入台账/结算单 比对\n"
        f"规则引擎（detect Skill 绑定）：{rule_line}\n"
        f"{rv_hint}\n"
        f"工作台模块：{modules or '任务、差异、待复核、报告等'}"
    )


def build_agent_grounding_context(agent, db: Session) -> str:
    """从后台装配 + 工作台生成 LLM 事实上下文，避免编造 Skill / 挂载 / 能力。"""
    from app.services.agent_governance_service import build_asset_mounts

    mounts = build_asset_mounts(agent, db)
    persona = (agent.persona or agent.prompt_template or "").strip()
    lines = [
        build_workbench_grounding(db),
        "",
        f"【Agent 配置 — 名称】{agent.name}",
        f"【Agent 配置 — 简介】{(agent.description or '').strip() or '—'}",
    ]
    if persona:
        lines.append(f"【Agent 配置 — 人设】{persona}")
    lines.extend([
        "",
        "【已装配 Skill — 仅可宣称以下能力，禁止编造未列出的 Skill】",
    ])
    skills = mounts.get("skills") or []
    if skills:
        for sk in skills:
            detail = _resolve_skill_item(db, str(sk.get("id") or ""))
            lines.append(f"- {detail['title']}（{_SKILL_TYPE_LABEL.get(detail['type'], detail['type'])}）：{detail['desc']}")
    else:
        lines.append("- （尚未装配 Skill）")

    kb = mounts.get("knowledge_bases") or []
    if kb:
        lines.append("")
        lines.append("【已挂载知识库】")
        for k in kb:
            lines.append(f"- {k.get('name') or k.get('id')}")

    ds = mounts.get("data_sources") or []
    if ds:
        lines.append("")
        lines.append("【已授权数据源范围】")
        for d in ds:
            lines.append(f"- {d.get('name') or d.get('id')}")

    if mounts.get("linked_workflow_name"):
        lines.append("")
        lines.append(f"【关联 Workflow】{mounts['linked_workflow_name']}")

    from app.services.chat_actions import load_published_rule_configs

    rules, rv_id = load_published_rule_configs(db)
    if rules:
        lines.append("")
        lines.append(f"【规则引擎 — 与 Workflow detect 节点同源 · 版本 {rv_id[:8] if rv_id else '—'}…】")
        for r in rules[:10]:
            cond = (r.condition or "").strip()[:80]
            lines.append(f"- {r.name}：{cond}{'…' if len(cond) >= 80 else ''}")

    allowed = set(agent.allowed_skill_ids or [])
    lines.extend([
        "",
        "【对话内可触发的真实操作】",
        "- 发起对账：对话内弹出数据源确认（SAP / DMS），执行收入核对 Workflow",
        f"- 查询任务：{'已授权，返回工作台任务库真实列表' if {'skill-query_tasks', 'query_tasks'} & allowed else '未授权，需引导联系管理员'}",
        f"- 差异解释：{'已授权，须从工作台绑定具体差异后生成解释卡片' if {'skill-anomaly_explain', 'anomaly_explain'} & allowed else '未授权'}",
        "",
        "【回答约束 — 必须遵守】",
        "- 所有回答必须基于上方工作台业务域、Agent 配置与已装配 Skill，不得脱离方太收入核对场景",
        "- 用户问技能/能力/能做什么/你是谁/你能帮我做什么时，仅列举「已装配 Skill」与挂载信息，禁止泛化自我介绍",
        "- 无差异上下文时：禁止解读「异常卡片」内容，禁止编造差异原因、金额、收单机构、结算单、支付通道等",
        "- 禁止出现与工作台无关的泛财资话术（如收单机构、银企直联、第三方支付对账等）",
        "- 无任务或差异上下文时，禁止编造差异编号、金额、单据号或任务条数",
        "- 仅当用户明确要对账/核对某月数据时，说明将在对话内弹出数据源确认卡片；勿对「好/嗯」等短回复主动编造对账表单",
        "- 禁止输出带方括号占位符的伪表单（如 [请选择…]、[执行核对]）；结构化操作必须使用系统 UI 卡片",
        "- 需要正式复核/报告时引导 /workbench/reconciliation",
        "- 禁止 Markdown；有结构化卡片时正文 1～2 句摘要，无卡片时 2～4 句",
    ])
    return "\n".join(lines)


def build_short_ack_followup_reply(agent, db: Session) -> str:
    """短回复（好/嗯）且未进入对账确认流程时，列举真实挂载能力，禁止 LLM 编造表单。"""
    from app.services.agent_governance_service import build_asset_mounts

    mounts = build_asset_mounts(agent, db)
    lines = ["好的。基于当前 Agent 后台配置，您可以直接说："]
    opts: list[str] = []
    for sk in mounts.get("skills") or []:
        detail = _resolve_skill_item(db, str(sk.get("id") or ""))
        opts.append(detail["title"])
    for kb in mounts.get("knowledge_bases") or []:
        opts.append(f"检索{kb.get('name') or kb.get('id')}")
    if opts:
        lines.append(" · ".join(opts[:5]) + "。")
    else:
        lines.append("请联系管理员在后台装配 Skill 与知识库。")
    lines.append("例如：「检索回款异常怎么处理」「我有哪些进行中的对账任务」「帮我核对 2024-05 收入」。")
    return "\n".join(lines)


def reply_looks_like_markdown_table(text: str) -> bool:
    """检测 LLM 输出的 Markdown 表格（前端不渲染，应由卡片替代）。"""
    t = (text or "").strip()
    if not re.search(r"^\|.+\|", t, re.M):
        return False
    return bool(re.search(
        r"能力|说明|字段|任务名称|当前状态|流水线|"
        r"数据导入|字段映射|差异检测|异常归因|复核流转|报告生成|任务查询",
        t,
    ))


def strip_markdown_tables(text: str) -> str:
    """移除 Markdown 表格行与分隔线，保留简短导语。"""
    kept: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if re.match(r"^\|.+\|$", s):
            continue
        if re.match(r"^\|[-:| ]+\|$", s):
            continue
        if s in ("---", "***", "___"):
            continue
        kept.append(line)
    result = "\n".join(kept).strip()
    return re.sub(r"\n{3,}", "\n\n", result)


def short_intro_from_reply(text: str, *, max_len: int = 200) -> str:
    """取表格前的第一段导语，过长则截断。"""
    clean = strip_markdown_tables(text)
    if not clean:
        return ""
    paras = [p.strip() for p in clean.split("\n\n") if p.strip()]
    intro = paras[0] if paras else clean
    if len(intro) > max_len:
        intro = intro[: max_len - 1].rstrip() + "…"
    return intro


def build_agent_capability_reply(agent, db: Session) -> str:
    """能力问询：正文由 agent_capability_overview UI 块承载，此处返回空避免重复。"""
    del agent, db
    return ""


def build_agent_skill_cards_block(agent, db: Session) -> dict[str, Any] | None:
    """仅 Skill 卡片（可点开详情）。"""
    from app.services.agent_governance_service import build_asset_mounts

    mounts = build_asset_mounts(agent, db)
    items: list[dict[str, str]] = []
    for sk in mounts.get("skills") or []:
        sid = str(sk.get("id") or "")
        detail = _resolve_skill_item(db, sid)
        items.append({
            "kind": "skill",
            "skill_id": sid,
            "icon": detail["icon"],
            "title": detail["title"],
            "desc": detail["desc"],
        })
    if not items:
        return None
    return {
        "type": "capability_list",
        "data": {
            "title": "已装配 Skill",
            "items": items,
        },
    }


def build_agent_capability_overview_block(agent, db: Session) -> dict[str, Any]:
    """能力问询 · 极简结构化概览（替代长段纯文本）。"""
    from app.services.agent_governance_service import build_asset_mounts
    from app.services.platform_seed import get_published_business_center

    bc = get_published_business_center(db)
    bc_name = bc.name if bc else "收入核对中心"
    mounts = build_asset_mounts(agent, db)
    tagline = (agent.description or "").strip()
    if not tagline:
        tagline = "基于 SAP / DMS 双源数据解释差异、查询任务，并可在对话内发起核对。"

    sections: list[dict[str, Any]] = []
    if not (mounts.get("skills") or []):
        sections.append({
            "key": "skills",
            "label": "Skill",
            "text": "尚未装配，请联系管理员授权",
        })

    ds = mounts.get("data_sources") or []
    if ds:
        sections.append({
            "key": "data",
            "label": "数据",
            "text": " · ".join(d.get("name") or d.get("id") for d in ds),
        })

    kb = mounts.get("knowledge_bases") or []
    if kb:
        sections.append({
            "key": "knowledge",
            "label": "知识库",
            "text": " · ".join(k.get("name") or k.get("id") for k in kb),
        })

    wf = mounts.get("linked_workflow_name")
    if wf:
        sections.append({
            "key": "workflow",
            "label": "流程",
            "text": f"{wf}（与工作台一致）",
        })

    return {
        "type": "agent_capability_overview",
        "data": {
            "agent_name": agent.name,
            "center_name": bc_name,
            "workbench_path": "/workbench/reconciliation",
            "tagline": tagline,
            "sections": sections,
            "cta": {
                "label": "发起对账示例",
                "prompt": "帮我核对 2024-05 的 SAP 与 DMS 收入",
            },
        },
    }


def build_agent_capability_turn_blocks(
    agent,
    db: Session,
    *,
    has_diff: bool = False,
) -> list[dict[str, Any]]:
    """能力问询完整 UI：概览 + Skill 卡片 + 快捷操作。"""
    blocks: list[dict[str, Any]] = [build_agent_capability_overview_block(agent, db)]
    skill_cards = build_agent_skill_cards_block(agent, db)
    if skill_cards:
        blocks.append(skill_cards)
    blocks.append(build_quick_actions_block(has_diff_context=has_diff))
    return blocks


def build_dialog_system_prompt(
    agent,
    db: Session,
    *,
    has_diff: bool = False,
) -> str:
    """自然语言对话系统提示：人设 + 后台 grounding。"""
    base = (agent.persona or agent.prompt_template or "").strip()
    grounding = build_agent_grounding_context(agent, db)
    ctx_hint = "当前对话已绑定具体差异，请基于界面卡片中的事实作答。" if has_diff else ""
    return f"{base}\n\n{grounding}\n{ctx_hint}".strip()


def build_onboarding_reply(agent, db: Session) -> str:
    """欢迎语：优先 Agent 后台描述，辅以真实挂载摘要。"""
    from app.services.agent_governance_service import build_asset_mounts

    desc = (agent.description or "").strip()
    mounts = build_asset_mounts(agent, db)
    skill_names = [
        _resolve_skill_item(db, str(s.get("id") or ""))["title"]
        for s in (mounts.get("skills") or [])
    ]
    if desc:
        intro = desc
    elif skill_names:
        intro = f"我是{agent.name}，已装配 {'、'.join(skill_names)}。"
    else:
        intro = f"我是{agent.name}。"
    return (
        f"您好！{intro}"
        "如需对账，请说明月份并比对 SAP 与 DMS，例如：帮我核对一下 2024-05 的收入数据。"
    )


def build_intent_card(intent: str, *, user_need: str = "") -> dict[str, Any]:
    meta = INTENT_META.get(intent, INTENT_META["chitchat"])
    return {
        "type": "intent_card",
        "data": {
            "intent": intent,
            "label": meta["label"],
            "color": meta["color"],
            "user_need": user_need,
        },
    }


def build_onboarding_block() -> dict[str, Any]:
    return {
        "type": "capability_list",
        "data": {
            "title": "我可以帮您完成",
            "items": [
                {"icon": "list", "title": "查询核对任务", "desc": "进度、待复核条数、最近批次"},
                {"icon": "diff", "title": "识别三类差异", "desc": "金额差异 · 重复数据 · 映射异常"},
                {"icon": "play", "title": "对话内发起对账", "desc": "选择 SAP / DMS 数据源并执行 Workflow"},
                {"icon": "flow", "title": "标准流程说明", "desc": "与业务中心流程编排一致"},
            ],
        },
    }


def build_onboarding_block_from_agent(agent, db: Session) -> dict[str, Any]:
    """按 Agent 真实挂载生成能力列表（与前台欢迎卡一致）。"""
    from app.services.agent_governance_service import build_asset_mounts

    mounts = build_asset_mounts(agent, db)
    items: list[dict[str, str]] = []
    for sk in mounts.get("skills") or []:
        sid = str(sk.get("id") or "")
        detail = _resolve_skill_item(db, sid)
        items.append({
            "kind": "skill",
            "skill_id": sid,
            "icon": detail["icon"],
            "title": detail["title"],
            "desc": detail["desc"],
        })
    for ds in mounts.get("data_sources") or []:
        items.append({
            "icon": "play",
            "title": ds.get("name") or ds.get("id"),
            "desc": "方太数据接入范围",
        })
    for kb in mounts.get("knowledge_bases") or []:
        items.append({
            "icon": "flow",
            "title": kb.get("name") or kb.get("id"),
            "desc": "知识库引用",
        })
    if mounts.get("linked_workflow_name"):
        items.append({
            "icon": "flow",
            "title": mounts.get("linked_workflow_name") or "收入核对 Workflow",
            "desc": "引导进入工作台正式任务",
        })
    if not items:
        return build_onboarding_block()
    return {
        "type": "capability_list",
        "data": {
            "title": f"{agent.name} · 已挂载能力",
            "items": items[:6],
        },
    }


def build_quick_actions_block(*, has_diff_context: bool = False) -> dict[str, Any]:
    if has_diff_context:
        actions = [
            {"label": "解释归因", "prompt": "请解释当前差异的归因结论与证据链", "variant": "primary"},
            {"label": "处理说明", "prompt": "请生成该差异的处理说明建议", "variant": "default"},
        ]
    else:
        actions = [
            {"label": "发起对账", "prompt": "帮我核对一下5月份的收入数据，比较SAP和DMS", "client_action": "start_reconciliation", "variant": "primary"},
            {
                "label": "查看任务",
                "prompt": "我有哪些进行中的对账任务？",
                "client_action": "query_tasks",
                "variant": "default",
            },
            {"label": "核对流程", "prompt": "收入核对中心的标准流程是什么？", "client_action": "faq_workflow", "variant": "default"},
            {"label": "差异类型", "prompt": "金额差异、重复数据、映射异常分别怎么处理？", "client_action": "faq_diff_types", "variant": "default"},
        ]
    return {"type": "quick_actions", "data": {"actions": actions}}


def build_task_list_block(tasks: list[Task], *, title: str = "近期对账任务") -> dict[str, Any]:
    from app.services.task_display import dedupe_tasks_for_display

    items = []
    status_label = {
        "draft": "草稿", "running": "执行中", "pending_review": "待复核",
        "processing": "处理中", "pending_verification": "待验证",
        "reporting": "报告输出", "closed": "已关闭", "failed": "失败",
    }
    seen_ids: set[str] = set()
    for t in dedupe_tasks_for_display(tasks):
        if t.id in seen_ids:
            continue
        seen_ids.add(t.id)
        pending = sum(1 for d in (t.differences or []) if d.status in ("pending_review", "identified"))
        items.append({
            "task_id": t.id,
            "name": t.name,
            "period": t.period or "—",
            "status": t.status,
            "status_label": status_label.get(t.status, t.status),
            "progress": t.progress or 0,
            "pending_review": pending,
            "diff_total": len(t.differences or []),
        })
    return {"type": "task_list", "data": {"title": title, "items": items, "empty": not items}}


CHAT_TASK_PIPELINE = [
    {"skill": "difference_detect", "label": "差异检测"},
    {"skill": "anomaly_explain", "label": "AI 归因解释"},
    {"skill": "review_flow", "label": "财务复核"},
    {"skill": "report_gen", "label": "生成报告"},
]

_TASK_STATUS_LABEL = {
    "draft": "草稿",
    "running": "执行中",
    "processing": "处理中",
    "pending_review": "待复核",
    "pending_verification": "待验证",
    "reporting": "报告输出",
    "closed": "已关闭",
    "failed": "失败",
}


def _pipeline_current_index(task: Task) -> int:
    status = task.status or "draft"
    progress = int(task.progress or 0)
    if status in ("closed", "reporting"):
        return 3
    if status == "pending_verification":
        return 3
    if status == "pending_review":
        return 2
    if status == "failed":
        return min(3, max(0, progress // 25))
    if status in ("running", "processing"):
        if progress >= 75:
            return 2
        if progress >= 50:
            return 1
        return 0
    return 0


def _pipeline_steps_for_task(task: Task) -> list[dict[str, Any]]:
    current = _pipeline_current_index(task)
    steps: list[dict[str, Any]] = []
    for i, node in enumerate(CHAT_TASK_PIPELINE):
        if i < current:
            state = "done"
        elif i == current:
            state = "done" if task.status == "closed" else "current"
        else:
            state = "pending"
        steps.append({**node, "state": state})
    return steps


def _next_skill_action_for_task(task: Task) -> dict[str, str] | None:
    status = task.status or ""
    if status == "pending_review":
        return {
            "skill": "review_flow",
            "label": "进入财务复核",
            "prompt": "请调用 review_flow 将差异清单推送到复核工作台",
            "workbench_path": f"/workbench/reconciliation/tasks/{task.id}?tab=review",
        }
    if status == "pending_verification":
        return {
            "skill": "re_verify",
            "label": "再次验证",
            "prompt": "请调用 re_verify 对复核结果做再次验证",
            "workbench_path": f"/workbench/reconciliation/tasks/{task.id}",
        }
    if status in ("reporting", "closed"):
        return {
            "skill": "report_gen",
            "label": "查看报告",
            "prompt": "请生成或打开对账报告",
            "workbench_path": f"/workbench/reconciliation/tasks/{task.id}?tab=report",
        }
    return None


def build_skill_invoke_block(
    items: list[dict[str, Any]],
    *,
    title: str = "Skill 调用结果",
) -> dict[str, Any]:
    return {"type": "skill_invoke", "data": {"title": title, "items": items}}


def build_task_detail_block(task: Task, *, agent=None, db: Session | None = None) -> dict[str, Any]:
    """单任务状态卡：进度条 + 流水线 + 下一步 Skill 引导（替代 Markdown 表格）。"""
    del agent, db
    pending = sum(
        1 for d in (task.differences or [])
        if d.status in ("pending_review", "identified")
    )
    return {
        "type": "task_detail",
        "data": {
            "task_id": task.id,
            "name": task.name,
            "period": task.period or "—",
            "status": task.status,
            "status_label": _TASK_STATUS_LABEL.get(task.status or "", task.status or ""),
            "progress": int(task.progress or 0),
            "pending_review": pending,
            "diff_total": len(task.differences or []),
            "pipeline": _pipeline_steps_for_task(task),
            "next_action": _next_skill_action_for_task(task),
            "workbench_path": f"/workbench/reconciliation/tasks/{task.id}",
        },
    }


# 与前端 buildReconciliationResultBlock 样例条数一致
RECONCILIATION_RESULT_SAMPLE_SIZE = 5


def _difference_row_item(d: Difference) -> dict[str, Any]:
    rec = d.ai_recommendation if isinstance(d.ai_recommendation, dict) else {}
    root = d.ai_explanation or rec.get("root_cause") or ""
    return {
        "id": d.id,
        "business_key": d.business_key or "",
        "type": d.type,
        "amount_diff": d.amount_diff,
        "status": d.status,
        "ai_explanation": (root or "")[:200],
        "responsible_party": d.responsible_party,
    }


def build_difference_list_block(
    task: Task,
    diffs: list[Difference],
    *,
    offset: int = 0,
    limit: int = 30,
    title: str = "差异清单",
) -> dict[str, Any]:
    """从任务库列出差异，禁止由 LLM 编造条数或「已全部展示」。"""
    total = len(diffs)
    page = diffs[offset : offset + limit]
    by_type: dict[str, int] = {}
    for d in diffs:
        by_type[d.type] = by_type.get(d.type, 0) + 1
    return {
        "type": "difference_list",
        "data": {
            "title": title,
            "task_id": task.id,
            "task_name": task.name,
            "period": task.period or "",
            "total": total,
            "offset": offset,
            "shown": len(page),
            "sample_size": RECONCILIATION_RESULT_SAMPLE_SIZE,
            "by_type": by_type,
            "items": [_difference_row_item(d) for d in page],
            "workbench_path": f"/workbench/reconciliation/tasks/{task.id}",
        },
    }


def _related_docs_from_diff(diff_dict: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    sap = diff_dict.get("sap_record") or {}
    dms = diff_dict.get("dms_record") or {}
    if sap.get("order_id"):
        lines.append(f"业务侧 order_id={sap.get('order_id')}")
    if dms.get("order_id"):
        lines.append(f"财务侧 order_id={dms.get('order_id')}")
    bk = diff_dict.get("business_key")
    if bk and not lines:
        lines.append(f"业务键 {bk}")
    return lines[:4]


def build_difference_explain_block(
    diff: Difference,
    recommendation: dict[str, Any],
    task: Task | None = None,
) -> dict[str, Any]:
    """与工作台差异详情同源：任务库中的 Difference + analyze_difference 结果。"""
    diff_dict = diff_item_from_model(diff)
    party = recommendation.get("responsible_party") or diff.responsible_party or ""
    party_label = PARTY_LABEL.get(str(party), str(party) or "待确认")
    evidence = list(recommendation.get("evidence") or [])
    if not evidence and isinstance(diff.evidence, dict):
        raw = diff.evidence.get("items") or diff.evidence.get("chain")
        if isinstance(raw, list):
            evidence = [str(x) for x in raw[:5]]
    suggested = recommendation.get("suggested_action") or diff.suggestion or ""
    root = recommendation.get("root_cause") or diff.ai_explanation or ""
    model = recommendation.get("model") or "rule-engine"
    task_id = task.id if task else diff.task_id
    return {
        "type": "difference_explain",
        "data": {
            "verified": True,
            "source": "task_difference",
            "difference_id": diff.id,
            "task_id": task_id,
            "task_name": task.name if task else "",
            "task_period": task.period if task else "",
            "diff_label": f"{diff.id[:8]}…",
            "type": diff.type,
            "business_key": diff.business_key or "",
            "business_amount": diff.business_amount,
            "finance_amount": diff.finance_amount,
            "amount_diff": diff.amount_diff,
            "status": diff.status,
            "responsible_party": party_label,
            "related_docs": _related_docs_from_diff(diff_dict),
            "root_cause": root,
            "evidence": evidence[:8],
            "suggestion": suggested,
            "model": model,
            "confidence": float(recommendation.get("confidence") or diff.confidence or 0),
            "rule_hits": diff.rule_hits if isinstance(diff.rule_hits, list) else [],
            "workbench_path": f"/workbench/reconciliation/tasks/{task_id}",
        },
    }


_REGISTRATION_REF_RE = re.compile(r"D\d{5,}[A-Z0-9]+", re.I)


def extract_registration_ref(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        hit = _REGISTRATION_REF_RE.search(text)
        if hit:
            return hit.group(0)
    return None


def source_kind_label(kind: str | None) -> str:
    return {
        "kb_upload": "登记表上传",
        "diff_archive": "差异沉淀",
    }.get(kind or "", "知识条目")


def build_knowledge_citation_prompt(hit_count: int) -> str:
    return (
        f"【知识库回答规范】本轮共注入 {hit_count} 条知识库条目。"
        f"首句须写明「共检索到 {hit_count} 条相关知识条目」。"
        "正文中引用案例时优先写「登记条目」单号（如 D10001FP…），不要单独写内部案例ID。"
        "可重点展开最相关的若干条；下方卡片会展示全部命中，正文无需重复罗列来源列表。"
        "若用户问「某人是谁/负责什么」，仅根据案例中出现的任务分工作答，并说明这只是案例内分工而非完整人事档案。"
        "仅引用上下文中出现的案例，禁止编造单号或责任人。"
    )


def _case_citation_line(c: dict, index: int, *, brief: bool = False) -> str:
    case_id = c.get("case_id") or ""
    short_id = case_id[:8] if case_id else "—"
    label = c.get("confirmed_type") or "条目"
    reg = c.get("registration_ref") or "—"
    summary = (c.get("root_cause") or "")
    limit = 80 if brief else 120
    clipped = summary[:limit]
    suffix = "…" if len(summary) > limit else ""
    sk = source_kind_label(c.get("source_kind"))
    return f"{index}. [{label}] 案例ID {short_id} · 登记条目 {reg} · {sk} · {clipped}{suffix}"


def build_knowledge_sources_footer(cases: list[dict]) -> str:
    if not cases:
        return ""
    lines = ["", "— 来源 —"]
    for i, c in enumerate(cases, 1):
        lines.append(_case_citation_line(c, i, brief=True))
    return "\n".join(lines)


def finalize_knowledge_reply(reply: str, cases: list[dict]) -> str:
    body = (reply or "").strip()
    if not body or not cases:
        return body
    n = len(cases)
    count_line = f"共检索到 {n} 条相关知识条目。"
    if count_line not in body and f"共检索到{n}" not in body.replace(" ", ""):
        body = f"{count_line}\n\n{body}"
    if "来源引用" in body or "\n— 来源 —" in body:
        return body
    return body + build_knowledge_sources_footer(cases)


def build_knowledge_query_reply(
    cases: list[dict],
    *,
    agent_name: str = "助手",
    fallback_reason: str | None = None,
) -> str:
    if not cases:
        return (
            f"当前 {agent_name} 已挂载知识库，但库内暂无条目。"
            "请在管理后台「知识库」上传《收入/回款异常问题登记表》，或完成差异复核后沉淀案例。"
        )
    lines: list[str] = []
    if fallback_reason:
        lines.append(
            f"大模型暂未能生成完整表述，已为您展示知识库摘要（共 {len(cases)} 条）。"
            f"原因：{fallback_reason}。可点击下方卡片查看登记表全文。"
        )
    else:
        lines.append(f"已从挂载的知识库检索到 {len(cases)} 条相关内容（见下方卡片）：")
    for i, c in enumerate(cases, 1):
        lines.append(_case_citation_line(c, i, brief=False))
    lines.append("可继续追问具体场景，例如「回款单与付款申请不一致怎么处理」。")
    return "\n".join(lines)


def _period_label_for_prompt(period: str) -> str:
    m = re.match(r"(20\d{2})-(\d{2})", period or "")
    if m:
        return f"{m.group(1)}年{int(m.group(2))}月"
    return period


def clarify_difference_intro(period: str | None) -> str:
    if period:
        return f"要分析 {period} 的差异原因，请先在下表确认任务与差异条目，我将为您生成归因解释。"
    return "要分析具体差异原因，请先确认对账任务与差异条目（见下方表单）。"


def build_clarify_difference_form_block(
    *,
    period: str | None,
    choices: list[dict[str, Any]],
    message_hint: str = "",
) -> dict[str, Any]:
    """反问表单：缺少 task_id / difference_id 时让用户点选。"""
    subtitle = f"已按「{period}」筛选" if period else "请选择要分析的任务与差异"
    return {
        "type": "clarify_form",
        "data": {
            "variant": "pick_difference",
            "title": "请确认要分析的差异",
            "subtitle": subtitle,
            "intro": message_hint or clarify_difference_intro(period),
            "period": period,
            "choices": choices,
            "empty": not choices,
            "submit_label": "解释这条差异",
            "submit_action": "explain_difference",
            "alt_actions": [
                {
                    "label": "先发起对账" if period else "发起对账",
                    "client_action": "start_reconciliation",
                    "prompt": (
                        f"帮我核对一下{_period_label_for_prompt(period)}的收入数据，比较SAP和DMS"
                        if period
                        else "帮我核对一下5月份的收入数据，比较SAP和DMS"
                    ),
                },
                {
                    "label": "查看我的任务",
                    "client_action": "query_tasks",
                    "prompt": "我有哪些进行中的对账任务？",
                },
            ],
        },
    }


def append_datasource_confirm_turn(
    ui_blocks: list,
    plan_steps: list,
    *,
    db: Session,
    agent,
    message: str,
    history: list[dict],
) -> str:
    """弹出真实 datasource_confirm 卡片（禁止 LLM 文本冒充表单）。"""
    from app.services.chat_actions import build_datasource_confirm_block, datasource_confirm_reply, parse_period_from_message

    period = parse_period_from_message(message) or "2024-05"
    for h in reversed(history or []):
        if h.get("role") == "user":
            p = parse_period_from_message(h.get("content", ""))
            if p:
                period = p
                break
    intro = datasource_confirm_reply(period)
    block = build_datasource_confirm_block(db, period, agent=agent)
    block["data"]["intro"] = intro
    ui_blocks.append(block)
    ui_blocks.append(build_quick_actions_block())
    plan_steps.append({
        "thought": "弹出数据源确认卡片（对话内可执行对账）",
        "action": "datasource_confirm",
        "observation": period,
    })
    return intro


def build_knowledge_refs_block(cases: list[dict], *, kb_ids: list[str] | None = None) -> dict[str, Any]:
    """对话中展示本次命中的知识库条目（供用户核对引用来源）。"""
    items = []
    for c in cases[:5]:
        items.append({
            "id": c.get("case_id"),
            "type_label": c.get("confirmed_type") or "条目",
            "registration_ref": c.get("registration_ref"),
            "source_label": source_kind_label(c.get("source_kind")),
            "summary": (c.get("root_cause") or "")[:160],
            "handling": (c.get("handling_result") or "")[:120],
            "rule_suggestion": (c.get("rule_suggestion") or "")[:80],
            "relevance_score": c.get("relevance_score"),
            "source_kind": c.get("source_kind"),
        })
    return {
        "type": "knowledge_refs",
        "data": {
            "title": "知识库检索命中",
            "kb_ids": kb_ids or [],
            "count": len(cases),
            "items": items,
            "hint": f"共 {len(cases)} 条，点击条目查看全文",
        },
    }


def build_agent_plan_block(plan_steps: list[dict], *, intent: str) -> dict[str, Any]:
    return {
        "type": "agent_plan",
        "data": {
            "intent": intent,
            "intent_label": INTENT_META.get(intent, {}).get("label", intent),
            "steps": plan_steps,
        },
    }


def build_outcomes_block() -> dict[str, Any]:
    return {
        "type": "outcome_preview",
        "data": {
            "title": "对账完成后您将获得",
            "items": [
                {"icon": "table", "text": "差异汇总与明细表"},
                {"icon": "ai", "text": "每条差异的 AI 解释与规则命中"},
                {"icon": "check", "text": "在线复核与再次验证"},
                {"icon": "pdf", "text": "可下载 PDF 对账报告"},
            ],
        },
    }
