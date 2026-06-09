"""Agent 对话运行时：主动识别意图 → 可视化 UI 块 → 真实调用能力资产。"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AgentConfig, AgentRun, CaseAsset, Conversation, Difference, Task, User
from app.services.agent_ui_blocks import (
    RECONCILIATION_RESULT_SAMPLE_SIZE,
    build_agent_capability_reply,
    build_agent_capability_turn_blocks,
    build_agent_plan_block,
    build_dialog_system_prompt,
    build_difference_explain_block,
    build_difference_list_block,
    append_datasource_confirm_turn,
    build_clarify_difference_form_block,
    build_knowledge_citation_prompt,
    build_knowledge_query_reply,
    build_knowledge_refs_block,
    clarify_difference_intro,
    extract_registration_ref,
    finalize_knowledge_reply,
    build_onboarding_block_from_agent,
    build_short_ack_followup_reply,
    build_onboarding_reply,
    build_quick_actions_block,
    build_skill_invoke_block,
    build_task_detail_block,
    build_task_list_block,
    build_workflow_block_from_db,
    reply_looks_like_markdown_table,
    short_intro_from_reply,
    strip_markdown_tables,
)
from app.services.ai_analyzer import RULE_EXPLAIN_MAX_CHARS, analyze_difference, diff_item_from_model
from app.services.chat_actions import (
    build_datasource_confirm_block,
    build_faq_diff_types_block,
    parse_period_from_message,
    should_show_datasource_panel,
    wants_start_reconciliation,
)
from app.services.task_display import dedupe_tasks_for_display
from app.services.chat_service import (
    LLM_FAILURE_PREFIX,
    LLM_UNAVAILABLE_MSG,
    _deepseek_chat,
    llm_api_ready,
    llm_failure_reply,
)
from app.services.context_chat import chat_with_context
from app.services.llm_config_service import (
    EffectiveLlmConfig,
    agent_llm_invocation_ready,
    get_effective_llm_config,
    is_mock_model_route,
    llm_runtime_ready,
)

log = logging.getLogger(__name__)

CHAT_SAFE_SKILLS = frozenset({"skill-anomaly_explain", "skill-query_tasks"})


def classify_intent_by_rules(
    message: str,
    *,
    has_diff_context: bool,
    client_action: str | None = None,
    history: list[dict] | None = None,
) -> tuple[str, str]:
    """规则回退意图识别（LLM 不可用或解析失败时使用）。"""
    msg = (message or "").strip()
    hist = history or []

    if client_action == "faq_workflow":
        return "workflow_guide", "了解标准核对流程"
    if client_action == "faq_diff_types":
        return "faq_diff_types", "了解三类差异处理方式"
    if client_action == "start_reconciliation":
        return "start_reconciliation", "发起对账并确认数据源"
    if client_action == "query_tasks":
        return "query_tasks", "查询任务进度与状态"
    if client_action == "query_knowledge":
        return "knowledge_query", "检索挂载的知识库"
    if client_action == "explain_difference":
        return "difference_explain", "解释当前差异归因"

    # --- 差异上下文：优先走真实 Skill ---
    if has_diff_context:
        if _wants_difference_list(msg):
            return "list_differences", "查看任务其余差异"
        if re.search(r"处理|说明|步骤|怎么办", msg):
            return "difference_explain", "生成差异处理说明"
        if _wants_difference_explain(msg):
            return "difference_explain", "解释当前差异归因"
        return "dialog", "围绕当前差异问答"

    # --- 可执行操作（需真实数据 / 卡片）---
    if re.search(r"^(你好|您好|hi|hello|在吗)$", msg, re.I):
        return "onboarding", "初次进入或打招呼"

    if re.search(r"(上传|导入|文件|excel|csv|批次)", msg, re.I):
        return "upload", "接入或上传对账数据"

    if not _is_informational_query(msg):
        if should_show_datasource_panel(msg, hist, has_diff_context=False, client_action=client_action):
            return "start_reconciliation", "发起对账（需确认数据源）"

        if wants_start_reconciliation(msg, hist):
            return "start_reconciliation", "发起对账并确认数据源"

    if re.search(
        r"(查看任务|看看任务|我的任务|有哪些.{0,12}任务|查询任务|任务列表|"
        r"多少.{0,8}任务|几条.{0,8}任务|对账任务|进行中.{0,8}任务|"
        r"待复核|任务状态|完成了吗|最近.{0,6}任务)",
        msg,
    ):
        return "query_tasks", "查询任务进度与状态"

    if re.search(r"(进度|状态|完成了)", msg) and re.search(r"任务|对账|核对", msg):
        return "query_tasks", "查询任务进度与状态"

    if _mentions_anomaly_card_without_context(msg, has_diff=has_diff_context):
        return "dialog", "询问异常卡片（无差异上下文）"

    if _wants_knowledge_query(msg):
        return "knowledge_query", "检索挂载知识库并回答（非 FAQ 固定卡）"

    if _topic_wants_capability_card(msg):
        return "agent_capabilities", "列举后台已装配 Skill"

    if _wants_difference_list(msg):
        return "list_differences", "查看任务差异清单"

    # --- 其余全部走自然语言对话（技能/流程/领域问答等不再单独加 intent）---
    return "dialog", "自然语言问答"


_SHORT_ACK_RE = re.compile(
    r"^(好|好的|好啊|可以|行|嗯|嗯嗯|ok|okay|是的|对|要|需要|继续|来吧)[。.!？?~～\s]*$",
    re.I,
)


def _is_short_ack(message: str) -> bool:
    return bool(_SHORT_ACK_RE.match((message or "").strip()))


def _history_offered_reconciliation(history: list[dict] | None) -> bool:
    """仅当上轮已明确进入「数据源确认/执行核对」流程时，短回复「好」才弹出对账卡片。"""
    for h in reversed((history or [])[-6:]):
        if h.get("role") != "assistant":
            continue
        c = (h.get("content") or "").strip()
        if re.search(r"数据源确认|确认.{0,8}SAP|使用推荐方案|核对周期|点击下方", c):
            return True
        if re.search(r"发起对账|执行核对|一键执行", c) and "需要吗" in c:
            return True
    return False


_PERSON_KB_QUERY_STOP = frozenset({
    "你", "他", "她", "它", "这", "那", "谁", "什么", "哪个", "哪位", "如何", "怎么",
})


def _extract_kb_search_terms(message: str) -> set[str]:
    """从「林燕华是谁」等话术提取检索词（姓名 / 业务键）。"""
    msg = (message or "").strip()
    terms: set[str] = set()
    patterns = (
        r"([\u4e00-\u9fff]{2,4})是谁",
        r"谁是([\u4e00-\u9fff]{2,4})",
        r"([\u4e00-\u9fff]{2,4})(?:是做什么的|负责什么|什么角色|什么职务)",
        r"查(?:一下|询)?(?:知识库)?(?:里)?(?:的)?([\u4e00-\u9fff@]{2,8})",
    )
    for pat in patterns:
        for m in re.finditer(pat, msg):
            t = (m.group(1) or "").strip().lstrip("@")
            if t and t not in _PERSON_KB_QUERY_STOP and len(t) >= 2:
                terms.add(t)
    for m in re.finditer(r"@[\u4e00-\u9fff]{2,4}", msg):
        terms.add(m.group(0).lstrip("@"))
    return terms


def _person_kb_lookup(message: str) -> bool:
    return bool(_extract_kb_search_terms(message))


def _wants_knowledge_query(message: str) -> bool:
    """用户明确要查规则/知识/案例，或按姓名/责任人查登记表（才触发知识库检索）。"""
    if _person_kb_lookup(message):
        return True
    return bool(re.search(
        r"(知识库|案例库|案例经验|历史案例|登记表|对账经验|"
        r"检索.{0,8}知识|查阅.{0,8}知识|知识条目|相关知识|查.{0,4}知识|"
        r"方太.{0,4}知识|知识域|"
        r"排查规则|排查要点|处理规则|对账规则|规则引擎|"
        r"有什么规则|哪些规则|规则是什么|规则.{0,6}怎么|"
        r"回款异常.{0,8}怎么|异常.{0,6}登记|案例.{0,6}怎么|经验.{0,6}怎么|"
        r"对照.{0,6}规则|按.{0,4}规则)",
        message,
    ))


def _wants_invoke_skills(message: str) -> bool:
    """用户明确要求真实调用 Skill（非仅列举能力）。"""
    msg = (message or "").strip()
    if not msg:
        return False
    if re.search(r"调用.{0,10}skills?", msg, re.I):
        return True
    if re.search(r"真实.{0,6}调用|执行.{0,6}skill", msg, re.I):
        return True
    return bool(re.search(r"帮我调用", msg) and re.search(r"skill", msg, re.I))


def _is_personal_chitchat(message: str) -> bool:
    """用户聊个人喜好/生活，勿误判为「Agent 能做什么」。"""
    return bool(re.search(
        r"我喜欢|我爱|我的喜好|我的爱好|我的兴趣|知道我喜欢|知道我爱|"
        r"猜猜我喜欢|你喜欢什么|你猜我喜欢|平时喜欢|爱好是什么|"
        r"喜欢干嘛|喜欢做什么|喜欢干什么|爱干嘛|爱做什么",
        message,
    ))


def _topic_wants_capability_card(message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    if _is_personal_chitchat(msg):
        return False
    if re.search(r"\bskills?\b", msg, re.I) and re.search(
        r"调用|哪些|什么|有啥|列出|清单|会|能|可以|授权|装配|挂载|配置",
        msg,
    ):
        return True
    if re.search(r"配置.{0,8}(了|过)?.*skills?", msg, re.I):
        return True
    return bool(re.search(
        r"(有哪些|有什么|会哪些|具备哪些|挂载了哪些|装配了哪些|授权了哪些).{0,12}(技能|能力|skill)|"
        r"(调用|使用).{0,12}(什么|哪些|啥).{0,8}(技能|能力|skill)|"
        r"(你|您).{0,8}(有哪些|有什么|会什么|能做什么|能做哪些|能帮我做|可以帮我|可以调用|能调用|帮我做)"
        r".{0,12}(什么|哪些|事|技能|能力|skill)?|"
        r"^(技能|能力)(列表|清单|一览)|"
        r"列出.{0,6}(技能|能力)|"
        r"介绍.{0,4}自己|你是谁|什么助手|"
        r"(你|您|agent|助手).{0,12}(能|会|可以).{0,8}(干嘛|做什么|干什么|干啥|啥)|"
        r"^(能|会|可以).{0,6}(干嘛|做什么|干什么|干啥|啥)|"
        r"(你好|您好).{0,8}(可以|能).{0,8}(干嘛|做什么|干什么|啥)",
        msg,
        re.I,
    ))


def _mentions_anomaly_card_without_context(message: str, *, has_diff: bool) -> bool:
    if has_diff:
        return False
    return bool(re.search(
        r"异常卡片|差异卡片|这张卡片|看到卡片|卡片了|解释.{0,4}卡片|卡片.{0,4}原因",
        message,
    ))


def try_deterministic_dialog_reply(
    message: str,
    *,
    agent: AgentConfig,
    db: Session,
    has_diff: bool,
) -> str | None:
    """能力说明 / 无上下文卡片解读 — 后台确定性回复，禁止 LLM 编造。"""
    msg = (message or "").strip()
    if _topic_wants_capability_card(msg) or _wants_invoke_skills(msg):
        return None
    if _mentions_anomaly_card_without_context(msg, has_diff=has_diff):
        return (
            "当前对话未绑定工作台中的具体差异，我无法解读异常卡片内容。"
            "请从收入核对工作台（/workbench/reconciliation）任务详情「待复核」或「差异清单」"
            "进入某条差异后再追问；或在对话中发起对账，待结果卡片出现后再分析。"
        )
    return None


def _topic_wants_workflow_card(message: str) -> bool:
    return bool(re.search(
        r"(标准流程|流程是什么|怎么操作|有哪些步骤|工作流程|核对流程|对账流程)",
        message,
    ) and re.search(r"核对|对账|收入", message))


def _topic_wants_diff_types_card(message: str) -> bool:
    """规则引擎三类差异说明卡；勿与「检索知识库」类诉求混淆。"""
    if _wants_knowledge_query(message):
        return False
    if re.search(r"检索|知识库|案例库|登记表|对账经验", message):
        return False
    has_diff_topic = bool(re.search(
        r"差异类型|三类差异|三类|金额差异|重复数据|映射异常|差异.{0,6}怎么",
        message,
    ))
    has_generic_how = bool(re.search(r"分别怎么处理|如何处理|怎么处理", message))
    return has_diff_topic or (has_generic_how and re.search(r"差异|三类|金额|重复|映射", message))


def _topic_wants_task_card(message: str) -> bool:
    return bool(re.search(r"(任务|进度|状态|待复核|完成了)", message))


def _is_informational_query(message: str) -> bool:
    """流程/技能/差异类型等说明类问题，不应触发可执行 action。"""
    return (
        _topic_wants_workflow_card(message)
        or _topic_wants_diff_types_card(message)
        or _topic_wants_capability_card(message)
        or _wants_knowledge_query(message)
    )


def suggest_dialog_ui_blocks(
    message: str,
    *,
    agent: AgentConfig,
    db: Session,
    user: User,
    has_diff: bool,
) -> list[dict]:
    """自然语言路径的 UI 增强：按话题附加卡片，不单独新增 intent。"""
    if has_diff:
        return []

    blocks: list[dict] = []
    msg = (message or "").strip()
    allowed = set(agent.allowed_skill_ids or [])

    if _topic_wants_capability_card(msg):
        blocks.extend(build_agent_capability_turn_blocks(agent, db, has_diff=has_diff)[:-1])

    if _topic_wants_workflow_card(msg):
        blocks.append(build_workflow_block_from_db(db, agent.linked_workflow_id))

    if _topic_wants_diff_types_card(msg):
        blocks.append(build_faq_diff_types_block(db))

    if _topic_wants_task_card(msg) and ({"skill-query_tasks", "query_tasks"} & allowed):
        tasks = _fetch_tasks(db, user)
        if tasks:
            blocks.append(build_task_list_block(tasks))

    return blocks


def _wants_difference_list(message: str) -> bool:
    msg = (message or "").strip()
    if re.search(r"^(异常卡片|差异卡片|看到卡片|这张卡片)$", msg):
        return False
    return bool(re.search(
        r"(还有|其他|更多|其余|剩下|继续看|再看).{0,10}(异常|差异|卡片)|"
        r"(异常|差异).{0,10}(清单|列表|有哪些|几条|多少|卡片)|"
        r"(列出|展示|显示).{0,8}(全部|所有|完整).{0,8}(差异|异常)|"
        r"全部.{0,8}(异常|差异|卡片)",
        message,
    ))


def _difference_list_offset(message: str) -> int:
    if re.search(r"还有|其他|更多|其余|剩下|继续|再看", message):
        return RECONCILIATION_RESULT_SAMPLE_SIZE
    return 0


def _wants_difference_explain(message: str) -> bool:
    return bool(re.search(
        r"解释|归因|原因|证据|处理说明|异常说明|差异说明|怎么处理|什么原因|为何|为什么",
        message,
    ))


def _mentions_largest_difference(message: str) -> bool:
    return bool(
        re.search(r"最大|最高|最严重|金额最大|差额最大", message)
        and re.search(r"差异|异常|不一致", message)
    )


def _needs_open_qa_runtime(message: str) -> bool:
    """开放问答须走 agent_runtime（知识库 / 差异反问表单 / 技能清单等）。"""
    return (
        _wants_knowledge_query(message)
        or _wants_difference_explain(message)
        or _wants_difference_list(message)
        or _mentions_largest_difference(message)
        or _topic_wants_capability_card(message)
    )


def _tasks_matching_period(tasks: list[Task], period: str | None, message: str) -> list[Task]:
    if period:
        matched = [
            t for t in tasks
            if (t.period or "") == period
            or period in (t.name or "")
            or period.replace("-", "") in (t.name or "")
        ]
        if matched:
            return matched
    filtered, _ = _filter_tasks_by_message(tasks, message)
    return filtered[:8]


def _build_difference_clarify_choices(
    db: Session,
    user: User,
    message: str,
) -> tuple[str | None, list[dict]]:
    from app.services.ai_analyzer import RULE_TYPE_LABEL

    period = parse_period_from_message(message)
    tasks = _tasks_matching_period(_fetch_tasks(db, user, limit=40), period, message)
    pick_largest = _mentions_largest_difference(message) or bool(
        re.search(r"哪笔|哪条|哪一个|哪一项", message)
    )
    choices: list[dict] = []
    for task in tasks:
        _, diffs = _fetch_task_differences(db, task.id)
        if not diffs:
            continue
        top = max(diffs, key=lambda d: abs(float(d.amount_diff or 0)))
        if pick_largest:
            candidates = [top]
        else:
            candidates = sorted(
                diffs,
                key=lambda d: abs(float(d.amount_diff or 0)),
                reverse=True,
            )[:3]
        for i, d in enumerate(candidates):
            choices.append({
                "task_id": task.id,
                "task_name": task.name,
                "task_period": task.period or "",
                "task_status": task.status,
                "difference_id": d.id,
                "business_key": d.business_key or "",
                "type": d.type,
                "type_label": RULE_TYPE_LABEL.get(d.type or "", d.type or "差异"),
                "amount_diff": d.amount_diff,
                "badge": "金额最大" if pick_largest and i == 0 else None,
            })
        if pick_largest and choices:
            break
    return period, choices[:6]


def append_clarify_difference_turn(
    ui_blocks: list,
    plan_steps: list,
    *,
    db: Session,
    user: User,
    message: str,
) -> str:
    period, choices = _build_difference_clarify_choices(db, user, message)
    intro = clarify_difference_intro(period)
    ui_blocks.append(build_clarify_difference_form_block(
        period=period,
        choices=choices,
        message_hint=intro,
    ))
    ui_blocks.append(build_quick_actions_block())
    plan_steps.append(_plan_step(
        "弹出差异确认表单（反问用户）",
        "clarify_form:pick_difference",
        f"period={period or '—'} choices={len(choices)}",
    ))
    if not choices:
        return (
            f"{intro}\n"
            f"未找到{(' ' + period + ' ' if period else ' ')}已落库的对账任务或差异记录。"
            "可先发起对账，或从下方选择其他操作。"
        )
    return intro


def _plan_step(thought: str, action: str, observation: str = "") -> dict:
    return {"thought": thought, "action": action, "observation": (observation or "")[:500]}


def _dedupe_reply_text(text: str) -> str:
    """去掉回复中重复段落/半段重复。"""
    raw = (text or "").strip()
    if not raw or len(raw) < 80:
        return text
    mid = len(raw) // 2
    first, second = raw[:mid].strip(), raw[mid:].strip()
    n1 = " ".join(first.split())
    n2 = " ".join(second.split())
    probe = n1[:72]
    if len(probe) >= 24 and n2.startswith(probe):
        return first
    paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
    if len(paras) <= 1:
        return text
    seen: set[str] = set()
    out: list[str] = []
    for p in paras:
        key = " ".join(p.split())[:160]
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return "\n\n".join(out) if out else text


_ACTIVE_TASK_STATUSES = frozenset({
    "draft", "running", "processing", "pending_review", "pending_verification",
})


def _resolve_task_id(
    db: Session,
    context: dict | None,
    conversation_id: str | None,
) -> str | None:
    if context and context.get("task_id"):
        return str(context["task_id"])
    if not conversation_id:
        return None
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        return None
    if conv.task_id:
        return conv.task_id
    for m in reversed(conv.messages or []):
        for b in m.get("ui_blocks") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") in ("reconciliation_result", "difference_list", "review_prompt"):
                tid = (b.get("data") or {}).get("task_id")
                if tid:
                    return str(tid)
    return None


def _fetch_task_differences(db: Session, task_id: str) -> tuple[Task | None, list[Difference]]:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return None, []
    diffs = (
        db.query(Difference)
        .filter(Difference.task_id == task_id)
        .order_by(Difference.id)
        .all()
    )
    return task, diffs


def _fetch_tasks(db: Session, user: User, limit: int = 10) -> list[Task]:
    q = db.query(Task)
    if user.role not in ("admin", "manager"):
        q = q.filter(Task.creator_id == user.id)
    return dedupe_tasks_for_display(
        q.order_by(Task.updated_at.desc()).limit(max(limit * 3, 20)).all(),
    )[:limit]


def _filter_tasks_by_message(tasks: list[Task], message: str) -> tuple[list[Task], str | None]:
    """按用户措辞过滤任务子集，返回 (tasks, 列表标题后缀)。"""
    msg = (message or "").strip()
    if re.search(r"进行中|在执行|未完成|正在跑|还在跑", msg):
        filtered = [t for t in tasks if t.status in _ACTIVE_TASK_STATUSES]
        return dedupe_tasks_for_display(filtered), "进行中"
    if re.search(r"待复核", msg):
        filtered = [t for t in tasks if t.status == "pending_review"]
        return dedupe_tasks_for_display(filtered), "待复核"
    if re.search(r"已完成|已关闭|做完|结束了", msg):
        filtered = [t for t in tasks if t.status in ("reporting", "closed")]
        return dedupe_tasks_for_display(filtered), "已完成"
    return dedupe_tasks_for_display(tasks), None


# ---------------------------------------------------------------------------
# 知识库检索：从 CaseAsset 中检索与问题相关的历史案例
# ---------------------------------------------------------------------------
def _case_matches_kb(c: CaseAsset, kb_id: str) -> bool:
    if kb_id == "kb-fangtai-cases":
        if c.knowledge_base_id in (None, "kb-fangtai-cases"):
            return c.source_kind != "kb_upload" or c.knowledge_base_id == "kb-fangtai-cases"
        return False
    return c.knowledge_base_id == kb_id


def _retrieve_knowledge(
    db: Session,
    agent: AgentConfig,
    message: str,
    diff_context: dict | None = None,
    *,
    implicit: bool = False,
) -> list[dict]:
    """按 Agent 的 knowledge_base_ids 检索案例与上传知识条目。

    implicit=True：仅差异解释 Skill 内部注入上下文，不展示命中卡片；
    仍要求用户话术命中 _wants_knowledge_query，或存在 diff_context 关键词。
    """
    if _topic_wants_capability_card(message):
        return []
    explicit_kb = _wants_knowledge_query(message)
    if not explicit_kb and not implicit:
        return []
    if implicit and not explicit_kb and not diff_context:
        return []

    kb_ids = agent.knowledge_base_ids or []
    if not kb_ids:
        return []

    pool = db.query(CaseAsset).order_by(CaseAsset.created_at.desc()).limit(200).all()
    cases = [c for c in pool if any(_case_matches_kb(c, kb) for kb in kb_ids)]
    if not cases:
        return []

    keywords = set()
    if diff_context:
        dt = diff_context.get("difference_type", "")
        bk = diff_context.get("business_key", "")
        if dt:
            keywords.add(dt)
        if bk:
            keywords.update(bk.split("/")[:2])
    person_terms = _extract_kb_search_terms(message)
    if explicit_kb:
        if person_terms:
            keywords.update(person_terms)
        else:
            for w in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", message):
                keywords.add(w)
            keywords.discard("知识库")
            keywords.discard("案例库")
            keywords.discard("是谁")
            keywords.discard("什么是")
            keywords.update({"回款", "收入", "差异", "映射", "同步", "重复", "过账", "开票", "台账"})
    if not keywords:
        return []

    scored: list[tuple[float, CaseAsset]] = []
    for c in cases:
        score = 0.0
        text = f"{c.confirmed_type or ''} {c.root_cause or ''} {c.handling_result or ''} {c.reusable_rule_suggestion or ''}"
        for kw in keywords:
            if kw in text:
                score += 1.0
        if c.source_kind == "kb_upload" and keywords:
            score += 0.2
        if score > 0:
            scored.append((score, c))
        elif explicit_kb:
            scored.append((0.05, c))

    scored.sort(key=lambda x: -x[0])
    results = []
    for score, c in scored[:5]:
        results.append({
            "case_id": c.id,
            "confirmed_type": c.confirmed_type,
            "root_cause": (c.root_cause or "")[:280],
            "handling_result": (c.handling_result or "")[:280],
            "rule_suggestion": (c.reusable_rule_suggestion or "")[:200],
            "relevance_score": round(score, 2),
            "source_kind": c.source_kind,
            "knowledge_base_id": c.knowledge_base_id,
            "source_file": c.source_file,
            "registration_ref": extract_registration_ref(c.root_cause, c.handling_result),
        })
    return results


def _record_knowledge_hits(
    ui_blocks: list[dict],
    skills_called: list[str],
    plan_steps: list[dict],
    agent: AgentConfig,
    kb_cases: list[dict],
    *,
    message: str = "",
) -> None:
    if not kb_cases or not _wants_knowledge_query(message):
        return
    skills_called.append("knowledge_retrieval")
    plan_steps.append(_plan_step(
        "知识库检索",
        f"retrieve_kb:{','.join(agent.knowledge_base_ids or [])}",
        f"命中 {len(kb_cases)} 条",
    ))
    ui_blocks.append(build_knowledge_refs_block(kb_cases, kb_ids=agent.knowledge_base_ids or []))


def _build_knowledge_context(cases: list[dict]) -> str:
    """将检索到的案例/知识库条目格式化为 LLM 上下文。"""
    if not cases:
        return ""
    lines = ["【知识库参考（案例沉淀与上传资料）】"]
    for i, c in enumerate(cases, 1):
        label = c.get("confirmed_type") or "条目"
        case_id = c.get("case_id") or ""
        reg = c.get("registration_ref") or "—"
        lines.append(f"{i}. [案例ID {case_id[:8]}] [{label}] 登记条目 {reg}")
        lines.append(f"   {c['root_cause']}")
        if c.get("handling_result"):
            lines.append(f"   处理/对策：{c['handling_result']}")
        if c.get("rule_suggestion"):
            lines.append(f"   排查要点：{c['rule_suggestion']}")
    return "\n".join(lines)


async def _generate_knowledge_reply(
    agent: AgentConfig,
    message: str,
    history: list[dict],
    context: dict | None,
    db: Session,
    kb_cases: list[dict],
) -> tuple[str, list[dict]]:
    """知识库问答：LLM 生成 + 来源引用收尾；失败则回退摘要并说明原因。"""
    extra_steps: list[dict] = []
    agent_name = agent.name or "助手"
    if not kb_cases:
        return build_knowledge_query_reply([], agent_name=agent_name), extra_steps

    kb_ctx = _build_knowledge_context(kb_cases)
    system_prompt = build_dialog_system_prompt(agent, db, has_diff=False)
    system_prompt = f"{system_prompt}\n\n{build_knowledge_citation_prompt(len(kb_cases))}"
    llm_reply, _sub = await _chat_with_model_route(
        agent, message, history, context, db,
        system_prompt, "dialog", False, knowledge_ctx=kb_ctx,
    )
    if (
        llm_reply
        and not _llm_reply_is_failure(llm_reply)
        and not _llm_reply_looks_hallucinated(message, llm_reply, agent, db)
    ):
        return finalize_knowledge_reply(llm_reply, kb_cases), extra_steps

    fallback_reason: str | None = None
    if _llm_reply_is_failure(llm_reply):
        raw = (llm_reply or "").replace(f"{LLM_FAILURE_PREFIX}：", "").strip()
        fallback_reason = raw or "大模型调用失败"
        extra_steps.append(_plan_step(
            "大模型未生成，已回退知识库摘要",
            "knowledge_query_fallback",
            (llm_reply or "")[:120],
        ))
    else:
        fallback_reason = "回复内容与知识库事实不一致，已改用知识库摘要"
        extra_steps.append(_plan_step(
            "知识库事实校验未通过，已回退摘要",
            "knowledge_query_fallback",
            (llm_reply or "")[:120],
        ))
    return (
        build_knowledge_query_reply(
            kb_cases,
            agent_name=agent_name,
            fallback_reason=fallback_reason,
        ),
        extra_steps,
    )


# ---------------------------------------------------------------------------
# 模型路由：Agent model_route + 平台大模型中心
# ---------------------------------------------------------------------------
def _resolve_model_route(
    agent: AgentConfig,
    intent: str,
    has_diff: bool,
) -> str | None:
    from app.services.llm_config_service import resolve_agent_model_route

    return resolve_agent_model_route(agent, intent=intent, has_diff=has_diff)


async def _chat_with_model_route(
    agent: AgentConfig,
    message: str,
    history: list[dict],
    context: dict | None,
    db: Session,
    system_prompt: str,
    intent: str,
    has_diff: bool,
    knowledge_ctx: str = "",
) -> tuple[str, str | None]:
    """带 Agent 路由 + 平台大模型配置的 LLM 对话。"""
    enriched_prompt = system_prompt
    if knowledge_ctx:
        enriched_prompt = f"{system_prompt}\n\n{knowledge_ctx}"

    chat_cfg, route_id = agent_llm_invocation_ready(agent, db, intent=intent, has_diff=has_diff)
    if not chat_cfg:
        if is_mock_model_route(route_id):
            return (
                "当前 Agent 推理模型为 Mock/规则模式，未调用大模型。"
                "请在 Agent 配置中选择 DeepSeek，并在大模型中心关闭模拟模式。",
                None,
            )
        return LLM_UNAVAILABLE_MSG, None

    try:
        if context and context.get("difference_id"):
            return await chat_with_context(
                message, history, context, db=db, system_prompt=enriched_prompt,
            )
        reply = await _deepseek_chat(message, history, chat_cfg, system_prompt=enriched_prompt)
        return reply, None
    except Exception as exc:
        log.warning("LLM call failed: %r", exc, exc_info=True)
        return llm_failure_reply(exc), None


def _llm_reply_is_failure(reply: str | None) -> bool:
    return bool(reply and reply.strip().startswith(LLM_FAILURE_PREFIX))


# ---------------------------------------------------------------------------
# 真实调用 anomaly_explain：使用 ai_analyzer.analyze_difference
# ---------------------------------------------------------------------------
async def _real_anomaly_explain(
    db: Session,
    context: dict,
    agent: AgentConfig,
    message: str,
    knowledge_ctx: str = "",
) -> tuple[str, list[str], list[dict]]:
    """真实调用规则引擎 + LLM，返回与工作台同源的差异解释卡片。"""
    diff_id = context.get("difference_id")
    if not diff_id:
        return "未找到差异上下文，无法执行差异解释。", [], []

    diff_row = db.query(Difference).filter(Difference.id == str(diff_id)).first()
    if not diff_row:
        return f"差异 {str(diff_id)[:8]} 不存在或已被删除。", [], []

    task = db.query(Task).filter(Task.id == diff_row.task_id).first()
    diff_dict = diff_item_from_model(diff_row)

    cfg = get_effective_llm_config(db)
    _, route_id = agent_llm_invocation_ready(agent, db, intent="difference_explain", has_diff=True)
    prefer_llm = not is_mock_model_route(route_id) and llm_runtime_ready(cfg)

    recommendation = await analyze_difference(
        diff_dict, db=db, task=task, prefer_llm=prefer_llm,
    )

    model_used = recommendation.get("model", "rule-engine")
    root_cause = recommendation.get("root_cause", "")
    party = recommendation.get("responsible_party", "")
    confidence = recommendation.get("confidence", 0)

    if diff_row.ai_explanation != root_cause:
        diff_row.ai_explanation = root_cause[:RULE_EXPLAIN_MAX_CHARS]
        diff_row.confidence = confidence
        diff_row.responsible_party = party or diff_row.responsible_party
        if suggested := recommendation.get("suggested_action"):
            diff_row.suggestion = str(suggested)[:2000]
        diff_row.evidence = {
            **(diff_row.evidence or {}),
            "chat_analysis": {
                "model": model_used,
                "root_cause": root_cause[:800],
                "timestamp": datetime.utcnow().isoformat(),
            },
        }
        db.commit()

    brief = (root_cause or "已基于当前任务差异生成解释。").strip()
    if len(brief) > 96:
        brief = brief[:96] + "…"
    if knowledge_ctx:
        brief = f"{brief}（已参考历史案例）"

    try:
        block = build_difference_explain_block(diff_row, recommendation, task)
    except Exception:
        log.exception("build_difference_explain_block failed diff=%s", diff_id)
        block = {
            "type": "difference_explain",
            "data": {
                "verified": True,
                "difference_id": diff_row.id,
                "task_id": task.id if task else diff_row.task_id,
                "task_name": task.name if task else "",
                "task_period": task.period if task else "",
                "type": diff_row.type,
                "business_key": diff_row.business_key or "",
                "business_amount": diff_row.business_amount,
                "finance_amount": diff_row.finance_amount,
                "amount_diff": diff_row.amount_diff,
                "status": diff_row.status,
                "root_cause": root_cause or brief,
                "suggestion": str(recommendation.get("suggested_action") or diff_row.suggestion or ""),
                "model": model_used,
                "confidence": float(confidence or 0),
                "workbench_path": f"/workbench/reconciliation/tasks/{diff_row.task_id}",
            },
        }
    return brief, [f"skill-anomaly_explain ({model_used})"], [block]


def _llm_reply_looks_hallucinated(message: str, reply: str, agent: AgentConfig, db: Session) -> bool:
    """检测 LLM 是否脱离方太/后台配置胡编。"""
    text = (reply or "").strip()
    if not text:
        return True
    if reply_looks_like_markdown_table(text):
        return True
    if re.search(r"\[[^\]]{0,40}(请|选|填|输入|执行)", text):
        return True
    if re.search(r"核对范围|时间跨度.*\[|请点击下方按钮", text) and "datasource_confirm" not in text:
        return True
    forbidden = ("支付平台", "收单机构", "银企直联", "业务系统、支付", "订单金额在业务")
    if any(x in text for x in forbidden):
        return True
    if _topic_wants_capability_card(message):
        from app.services.agent_ui_blocks import _resolve_skill_item
        skill_titles = [
            _resolve_skill_item(db, sid)["title"]
            for sid in (agent.allowed_skill_ids or [])
        ]
        if skill_titles and not any(t.split(" Skill")[0] in text for t in skill_titles):
            return True
    return False


def _finalize_capability_turn(
    agent: AgentConfig,
    db: Session,
    *,
    has_diff: bool,
) -> tuple[str, list[dict], list[dict]]:
    """技能/能力类回复：后台配置 + 能力卡片，绝不走 LLM。"""
    ui_blocks = build_agent_capability_turn_blocks(agent, db, has_diff=has_diff)
    reply = build_agent_capability_reply(agent, db)
    plan = [_plan_step(
        "读取后台 Skill 配置生成回复",
        "agent_capabilities",
        f"skills={len(agent.allowed_skill_ids or [])}",
    )]
    return reply, ui_blocks, plan


async def _finalize_invoke_skills_turn(
    agent: AgentConfig,
    db: Session,
    user: User,
    *,
    context: dict | None,
    conversation_id: str | None,
    has_diff: bool,
) -> tuple[str, list[dict], list[dict]]:
    """真实调用 query_tasks 等 Skill，并以结构化卡片展示结果。"""
    ui_blocks: list[dict] = []
    plan: list[dict] = []
    allowed = set(agent.allowed_skill_ids or [])
    task_id = _resolve_task_id(db, context, conversation_id)

    overview_blocks = build_agent_capability_turn_blocks(agent, db, has_diff=has_diff)
    if overview_blocks:
        ui_blocks.extend(overview_blocks[:-1])

    invoked: list[dict[str, Any]] = []
    tasks: list[Task] = []

    if "skill-query_tasks" in allowed or "query_tasks" in allowed:
        from app.services.skill_platform_runner import build_chat_skill_context, execute_skill_unified

        result = await execute_skill_unified(
            db,
            "query_tasks",
            {"task_id": task_id, "user_id": user.id} if task_id else {"user_id": user.id},
            task_id=task_id,
        )
        summary = ""
        if result.success and isinstance(result.output, dict):
            payload = result.output.get("result") if isinstance(result.output.get("result"), dict) else result.output
            total = payload.get("total", 0)
            summary = f"返回 {total} 条任务"
            raw_tasks = payload.get("tasks") or []
            if task_id:
                row = db.query(Task).filter(Task.id == task_id).first()
                if row:
                    tasks = [row]
            elif raw_tasks:
                ids = [str(t.get("id")) for t in raw_tasks if t.get("id")]
                if ids:
                    tasks = (
                        db.query(Task)
                        .filter(Task.id.in_(ids))
                        .order_by(Task.updated_at.desc())
                        .all()
                    )
        else:
            summary = (result.error or "调用失败")[:120]
        invoked.append({
            "skill_code": "query_tasks",
            "skill_id": "skill-query_tasks",
            "success": result.success,
            "summary": summary,
            "duration_ms": result.duration_ms,
        })
        plan.append(_plan_step(
            "真实调用 Skill: query_tasks",
            "call_skill:skill-query_tasks",
            summary or "failed",
        ))
        if not tasks:
            tasks = _fetch_tasks(db, user)
        tasks = dedupe_tasks_for_display(tasks)
        if result.success and invoked:
            invoked[-1]["summary"] = f"返回 {len(tasks)} 条任务（已去重）"
    else:
        plan.append(_plan_step("Skill 授权校验", "permission_denied", "query_tasks"))

    if invoked:
        ui_blocks.append(build_skill_invoke_block(invoked))
    if task_id and tasks:
        ui_blocks.append(build_task_detail_block(tasks[0]))
    elif tasks:
        ui_blocks.append(build_task_list_block(tasks))
    ui_blocks.append(build_quick_actions_block(has_diff_context=has_diff))

    if invoked and any(i.get("success") for i in invoked):
        if task_id and tasks:
            reply = f"已调用 query_tasks，当前任务状态见下方卡片。"
        elif tasks:
            reply = f"已调用 query_tasks，共 {len(tasks)} 条任务，见下方列表。"
        else:
            reply = "已调用 query_tasks，暂无任务记录。"
    elif invoked:
        reply = "query_tasks 调用失败，请检查 Skill 授权或稍后重试。"
    else:
        reply = "当前 Agent 未授权 query_tasks，请联系管理员添加授权。"
    return reply, ui_blocks, plan


async def _llm_brief_reply(
    agent: AgentConfig,
    message: str,
    history: list[dict],
    context: dict | None,
    db: Session,
    intent: str,
    has_diff: bool,
    *,
    knowledge_ctx: str = "",
) -> str:
    """通用 LLM 短回复，用于 onboarding / dialog 等。"""
    system_prompt = build_dialog_system_prompt(agent, db, has_diff=has_diff)
    reply, _ = await _chat_with_model_route(
        agent, message, history, context, db,
        system_prompt, intent, has_diff, knowledge_ctx=knowledge_ctx,
    )
    return reply


async def run_agent_turn(
    db: Session,
    *,
    agent: AgentConfig,
    user: User,
    message: str,
    history: list[dict],
    context: dict | None,
    conversation_id: str | None,
    client_action: str | None = None,
) -> tuple[str, str | None, list[dict], list[dict]]:
    has_diff = bool(context and context.get("difference_id"))
    from app.services.agent_intent_classifier import resolve_intent

    intent, user_need, intent_source = await resolve_intent(
        message,
        agent=agent,
        db=db,
        has_diff_context=has_diff,
        client_action=client_action,
        history=history,
    )

    plan_steps: list[dict] = [
        _plan_step(
            f"识别用户诉求：{user_need}",
            f"classify_intent_{intent_source}",
            f"intent={intent}",
        ),
    ]
    ui_blocks: list[dict] = []
    skills_called: list[str] = []
    reply = ""
    msg_norm = (message or "").strip()

    # --- 最高优先级：真实调用 Skill / 能力问询，禁止 LLM 表格输出 ---
    if not has_diff and (_wants_invoke_skills(msg_norm) or intent == "agent_capabilities"):
        if _wants_invoke_skills(msg_norm):
            reply, cap_blocks, cap_steps = await _finalize_invoke_skills_turn(
                agent, db, user, context=context, conversation_id=conversation_id, has_diff=has_diff,
            )
            intent = "invoke_skills"
        else:
            reply, cap_blocks, cap_steps = _finalize_capability_turn(agent, db, has_diff=has_diff)
            intent = "agent_capabilities"
        ui_blocks.extend(cap_blocks)
        plan_steps.extend(cap_steps)

    elif not has_diff and _mentions_anomaly_card_without_context(msg_norm, has_diff=has_diff):
        reply = (
            "当前对话未绑定工作台中的具体差异，我无法解读异常卡片内容。"
            "请从收入核对工作台（/workbench/reconciliation）任务详情「待复核」或「差异清单」"
            "进入某条差异后再追问；或在对话中发起对账，待结果卡片出现后再分析。"
        )
        ui_blocks.append(build_quick_actions_block())
        plan_steps.append(_plan_step("无差异上下文，拦截卡片臆测", "block_anomaly_card", ""))
        intent = "dialog"

    elif not has_diff and intent == "knowledge_query":
        kb_cases = _retrieve_knowledge(db, agent, message, context)
        _record_knowledge_hits(ui_blocks, skills_called, plan_steps, agent, kb_cases, message=msg_norm)
        reply, kb_extra_steps = await _generate_knowledge_reply(
            agent, message, history, context, db, kb_cases,
        )
        plan_steps.extend(kb_extra_steps)
        ui_blocks.append(build_quick_actions_block())
        plan_steps.append(_plan_step(
            "知识库检索并生成回复",
            "knowledge_query",
            f"hits={len(kb_cases)}",
        ))
        intent = "knowledge_query"

    # --- 可视化优先分支（少用文字墙）---
    elif intent == "onboarding":
        ui_blocks.extend([
            build_onboarding_block_from_agent(agent, db),
            build_quick_actions_block(has_diff_context=has_diff),
        ])
        reply = build_onboarding_reply(agent, db)
        plan_steps.append(_plan_step("展示能力卡片与引导说明", "render_ui", "onboarding"))

    elif intent in ("start_reconciliation", "operate"):
        reply = append_datasource_confirm_turn(
            ui_blocks, plan_steps, db=db, agent=agent, message=message, history=history,
        )
        intent = "start_reconciliation"

    elif intent == "query_tasks":
        allowed_skills = set(agent.allowed_skill_ids or [])
        if "skill-query_tasks" not in allowed_skills and "query_tasks" not in allowed_skills:
            reply = "当前 Agent 未授权「任务查询」Skill，请联系管理员添加授权。"
            plan_steps.append(_plan_step("Skill 授权校验", "permission_denied", "query_tasks"))
        else:
            from app.services.skill_platform_runner import execute_skill_unified

            ctx_tid = _resolve_task_id(db, context, conversation_id)
            skill_result = await execute_skill_unified(
                db,
                "query_tasks",
                {"task_id": ctx_tid, "user_id": user.id} if ctx_tid else {"user_id": user.id},
                task_id=ctx_tid,
            )
            summary = ""
            if skill_result.success and isinstance(skill_result.output, dict):
                payload = (
                    skill_result.output.get("result")
                    if isinstance(skill_result.output.get("result"), dict)
                    else skill_result.output
                )
            else:
                summary = (skill_result.error or "调用失败")[:80]
            all_tasks = _fetch_tasks(db, user)
            tasks, scope = _filter_tasks_by_message(all_tasks, message)
            if skill_result.success:
                scope_hint = f"{scope} " if scope else ""
                summary = f"返回 {len(tasks)} 条{scope_hint}任务（已去重）"
            ui_blocks.append(build_skill_invoke_block([{
                "skill_code": "query_tasks",
                "skill_id": "skill-query_tasks",
                "success": skill_result.success,
                "summary": summary,
                "duration_ms": skill_result.duration_ms,
            }]))
            list_title = f"{'近期' if not scope else scope}对账任务"
            if ctx_tid:
                focus = db.query(Task).filter(Task.id == ctx_tid).first()
                if focus:
                    ui_blocks.append(build_task_detail_block(focus))
                elif tasks:
                    ui_blocks.append(build_task_list_block(tasks, title=list_title))
            else:
                ui_blocks.append(build_task_list_block(tasks, title=list_title))
            ui_blocks.append(build_quick_actions_block())
            if not tasks:
                if scope:
                    reply = f"暂无{scope}的对账任务，可通过「发起对账」创建新任务，或换个条件再查。"
                else:
                    reply = "暂无任务记录，可通过「发起对账」创建第一条。"
            else:
                running = sum(1 for t in tasks if t.status in _ACTIVE_TASK_STATUSES)
                done = sum(1 for t in tasks if t.status in ("reporting", "closed"))
                scope_hint = f"{scope} " if scope else ""
                reply = (
                    f"共找到 {len(tasks)} 个{scope_hint}任务"
                    f"（进行中 {running}，已完成 {done}），详情见下方卡片。"
                )
            skills_called.append("skill-query_tasks")
            plan_steps.append(_plan_step(
                "真实调用 Skill: query_tasks",
                "call_skill:skill-query_tasks",
                f"shown={len(tasks)} deduped",
            ))

    elif intent == "workflow_guide":
        ui_blocks.append(build_workflow_block_from_db(db, agent.linked_workflow_id))
        ui_blocks.append(build_quick_actions_block())
        reply = ""
        plan_steps.append(_plan_step("加载 Workflow 流程图", "workflow_guide", "faq_workflow block"))

    elif intent == "faq_diff_types":
        if _wants_knowledge_query(msg_norm):
            kb_cases = _retrieve_knowledge(db, agent, message, context)
            _record_knowledge_hits(ui_blocks, skills_called, plan_steps, agent, kb_cases, message=msg_norm)
            reply, kb_extra_steps = await _generate_knowledge_reply(
                agent, message, history, context, db, kb_cases,
            )
            plan_steps.extend(kb_extra_steps)
            ui_blocks.append(build_quick_actions_block())
            intent = "knowledge_query"
            plan_steps.append(_plan_step("纠偏：知识库检索（原误路由 faq_diff_types）", "knowledge_query", f"hits={len(kb_cases)}"))
        else:
            ui_blocks.append(build_faq_diff_types_block(db))
            reply = ""
            plan_steps.append(_plan_step("展示规则引擎差异说明卡", "faq_diff_types", ""))

    elif intent == "upload":
        ui_blocks.extend([
            build_onboarding_block_from_agent(agent, db),
            build_quick_actions_block(),
        ])
        period = parse_period_from_message(message) or "2024-05"
        ui_blocks.append(build_datasource_confirm_block(db, period, agent=agent))
        reply = ""
        plan_steps.append(_plan_step("引导数据接入", "upload_guide", period))

    elif has_diff and (
        intent == "difference_explain"
        or client_action == "explain_difference"
        or _wants_difference_explain(message)
    ):
        allowed = set(agent.allowed_skill_ids or [])
        if "skill-anomaly_explain" not in allowed and "anomaly_explain" not in allowed:
            reply = "当前 Agent 未授权「异常解释」Skill，无法分析差异。请联系管理员添加授权。"
            plan_steps.append(_plan_step("Skill 授权校验", "permission_denied", "anomaly_explain"))
        else:
            kb_cases = _retrieve_knowledge(db, agent, message, context, implicit=True)
            kb_ctx = _build_knowledge_context(kb_cases)

            explain_reply, explain_skills, explain_blocks = await _real_anomaly_explain(
                db, context, agent, message, knowledge_ctx=kb_ctx,
            )
            reply = explain_reply
            ui_blocks.extend(explain_blocks)
            skills_called.extend(explain_skills)
            intent = "difference_explain"

            _record_knowledge_hits(ui_blocks, skills_called, plan_steps, agent, kb_cases, message=msg_norm)
            plan_steps.append(_plan_step(
                "真实调用 Skill: anomaly_explain",
                "call_skill:skill-anomaly_explain",
                "已生成差异解释卡片" if explain_blocks else "未返回解释卡片",
            ))

    elif not has_diff and (
        _wants_difference_explain(message) or _mentions_largest_difference(message)
    ):
        reply = append_clarify_difference_turn(
            ui_blocks, plan_steps, db=db, user=user, message=message,
        )
        intent = "clarify_difference"

    elif intent == "list_differences" or _wants_difference_list(message):
        task_id = _resolve_task_id(db, context, conversation_id)
        task, diffs = _fetch_task_differences(db, task_id) if task_id else (None, [])
        if not task_id or not task:
            reply = append_clarify_difference_turn(
                ui_blocks, plan_steps, db=db, user=user, message=message,
            )
            intent = "clarify_difference"
        elif not diffs:
            reply = f"任务「{task.name}」暂无差异记录。"
            ui_blocks.append(build_quick_actions_block())
            plan_steps.append(_plan_step("任务无差异", "empty_difference_list", task_id))
            intent = "list_differences"
        else:
            offset = _difference_list_offset(message)
            remaining = max(0, len(diffs) - offset)
            title = "其余差异" if offset > 0 else "差异清单"
            ui_blocks.append(
                build_difference_list_block(task, diffs, offset=offset, title=title),
            )
            ui_blocks.append(build_quick_actions_block())
            sample_n = RECONCILIATION_RESULT_SAMPLE_SIZE
            if offset > 0 and remaining > 0:
                reply = (
                    f"本任务共 {len(diffs)} 条差异；对账结果卡片仅展示前 {sample_n} 条样例。"
                    f"下方为第 {offset + 1}–{min(offset + remaining, len(diffs))} 条（共 {remaining} 条）。"
                )
            elif offset > 0 and remaining == 0:
                reply = (
                    f"本任务共 {len(diffs)} 条差异，对账结果已展示前 {sample_n} 条样例，没有更多条目。"
                )
            else:
                reply = f"本任务共 {len(diffs)} 条差异，清单见下方卡片（数据来自任务库）。"
            skills_called.append("skill-query_tasks")
            plan_steps.append(_plan_step(
                "查询任务差异清单",
                "list_differences",
                f"total={len(diffs)} offset={offset}",
            ))
            intent = "list_differences"

    elif intent == "dialog" or intent in ("analyze", "chitchat", "progress"):
        if not has_diff and _is_short_ack(msg_norm):
            if _history_offered_reconciliation(history):
                reply = append_datasource_confirm_turn(
                    ui_blocks, plan_steps, db=db, agent=agent, message=message, history=history,
                )
                intent = "start_reconciliation"
            else:
                reply = build_short_ack_followup_reply(agent, db)
                ui_blocks.append(build_onboarding_block_from_agent(agent, db))
                ui_blocks.append(build_quick_actions_block())
                plan_steps.append(_plan_step(
                    "短回复：列举后台挂载能力（不走 LLM）", "short_ack_capabilities", "",
                ))
                intent = "dialog"
        elif not has_diff and wants_start_reconciliation(message):
            reply = append_datasource_confirm_turn(
                ui_blocks, plan_steps, db=db, agent=agent, message=message, history=history,
            )
            intent = "start_reconciliation"
            plan_steps.append(_plan_step("识别对账诉求并弹出数据源确认", "datasource_confirm", ""))
        elif not has_diff and _wants_difference_list(message):
            reply = "差异条数与清单需从任务库读取，请勿臆测。请说明对账任务或先完成一次对账。"
            ui_blocks.append(build_quick_actions_block())
            plan_steps.append(_plan_step("拦截差异清单臆测", "block_hallucinated_list", ""))
        else:
            det_reply = try_deterministic_dialog_reply(
                message, agent=agent, db=db, has_diff=has_diff,
            )
            if det_reply is not None:
                reply = det_reply
                ui_blocks.extend(suggest_dialog_ui_blocks(
                    message, agent=agent, db=db, user=user, has_diff=has_diff,
                ))
                ui_blocks.append(build_quick_actions_block(has_diff_context=has_diff))
                plan_steps.append(_plan_step(
                    "后台配置生成确定性回复", "dialog_deterministic", "",
                ))
                intent = "dialog"
            elif _topic_wants_capability_card(msg_norm):
                reply, cap_blocks, cap_steps = _finalize_capability_turn(agent, db, has_diff=has_diff)
                ui_blocks.extend(cap_blocks)
                plan_steps.extend(cap_steps)
                intent = "agent_capabilities"
            else:
                kb_cases: list[dict] = []
                kb_ctx = ""
                if _wants_knowledge_query(msg_norm):
                    kb_cases = _retrieve_knowledge(db, agent, message, context)
                    kb_ctx = _build_knowledge_context(kb_cases)
                system_prompt = build_dialog_system_prompt(agent, db, has_diff=has_diff)

                llm_reply, sub = await _chat_with_model_route(
                    agent, message, history, context, db,
                    system_prompt, intent, has_diff, knowledge_ctx=kb_ctx,
                )

                model_target = _resolve_model_route(agent, intent, has_diff) or get_effective_llm_config(db).model
                reply = llm_reply
                if _llm_reply_looks_hallucinated(message, reply, agent, db):
                    plan_steps.append(_plan_step(
                        "拦截 LLM 伪表单/泛化回复", "block_hallucination", (reply or "")[:120],
                    ))
                    if _history_offered_reconciliation(history) and _is_short_ack(msg_norm):
                        reply = append_datasource_confirm_turn(
                            ui_blocks, plan_steps, db=db, agent=agent, message=message, history=history,
                        )
                        intent = "start_reconciliation"
                    elif (
                        _topic_wants_capability_card(msg_norm)
                        or re.search(r"\[", reply or "")
                        or reply_looks_like_markdown_table(reply or "")
                    ):
                        reply, cap_blocks, cap_steps = _finalize_capability_turn(agent, db, has_diff=has_diff)
                        ui_blocks.extend(cap_blocks)
                        plan_steps.extend(cap_steps)
                        intent = "agent_capabilities"
                    else:
                        reply = build_short_ack_followup_reply(agent, db)
                        ui_blocks.extend(build_agent_capability_turn_blocks(agent, db, has_diff=has_diff)[:-1])
                elif sub:
                    intent = sub

                _record_knowledge_hits(ui_blocks, skills_called, plan_steps, agent, kb_cases, message=msg_norm)

                ui_blocks.extend(suggest_dialog_ui_blocks(
                    message, agent=agent, db=db, user=user, has_diff=has_diff,
                ))
                ui_blocks.append(build_quick_actions_block(has_diff_context=has_diff))
                plan_steps.append(_plan_step(
                    f"自然语言回复 ({model_target})", "dialog_llm", "",
                ))
                intent = "dialog"

    if not reply and not any(
        b["type"] in (
            "datasource_confirm", "faq_workflow", "faq_diff_types", "task_progress",
            "difference_explain", "difference_list", "capability_list", "task_list",
            "task_detail", "skill_invoke", "knowledge_refs",
        )
        for b in ui_blocks
    ):
        reply = reply or ""

    if reply and reply_looks_like_markdown_table(reply):
        intro = short_intro_from_reply(reply)
        reply = intro or ""
        if not any(
            b["type"] in ("agent_capability_overview", "capability_list")
            for b in ui_blocks
        ):
            ui_blocks = build_agent_capability_turn_blocks(agent, db, has_diff=has_diff) + ui_blocks
    else:
        reply = strip_markdown_tables(reply) if reply else reply
    reply = _dedupe_reply_text(reply)

    ui_blocks.append(build_agent_plan_block(plan_steps, intent=intent))

    db.add(
        AgentRun(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            agent_id=agent.id,
            user_id=user.id,
            user_input=message[:2000],
            intent=intent,
            plan_steps=plan_steps,
            final_output=(reply or "")[:4000] or None,
            skills_called=skills_called,
            created_at=datetime.utcnow(),
        )
    )

    return reply, intent, ui_blocks, plan_steps
