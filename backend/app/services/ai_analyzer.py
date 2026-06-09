import json

import re

from datetime import datetime

from typing import Any



import httpx

from sqlalchemy.orm import Session



from app.models import RuleConfig, Task
from app.services.chat_service import llm_api_ready
from app.services.llm_config_service import EffectiveLlmConfig, get_effective_llm_config

DIFF_TYPE_TO_RULE_TYPE = {
    "金额差异": "amount_mismatch",
    "重复数据": "duplicate_record",
    "主数据/映射异常": "mapping_anomaly",
    "映射异常": "mapping_anomaly",
    "状态不一致": "status_mismatch",
    "接口/同步异常": "sync_failure",
    "回款差异": "payment_mismatch",
    "帆软汇总差异": "fanruan_summary",
}

RULE_TYPE_LABEL = {
    "amount_mismatch": "金额差异",
    "duplicate_record": "重复数据",
    "mapping_anomaly": "主数据/映射异常",
    "status_mismatch": "状态不一致",
    "sync_failure": "接口/同步异常",
    "payment_mismatch": "回款差异",
    "fanruan_summary": "帆软汇总差异",
}

PARTY_LABEL = {
    "finance": "财务侧",
    "sales": "业务侧",
    "mdm_team": "主数据团队",
    "logistics": "物流/供应链",
    "business": "业务 / 接口",
}

MOCK_REASONS = {

    "金额差异": "业务侧与财务侧确认金额不一致，需核对原始单据并修正录入。",

    "重复数据": "相同业务唯一键出现重复记录，需去重并核对同步逻辑。",

    "主数据/映射异常": "客户或产品主数据映射不一致，需 MDM/业务方确认编码关系。",

    "金额重复": "销售订单与发货单重复录入或系统同步异常。",

    "MDM异常": "客户主数据映射不一致，需 MDM 团队确认编码映射关系。",

    "编码不一致": "业务侧与财务侧产品编码体系不同，需确认 SKU 映射。",

}



SYSTEM_PROMPT = """你是方太财务部收入对账专家。根据 SAP/DMS/对账单数据，分析差异根因（仅作推测，不得替代规则引擎的判定）。

必须只返回 JSON，不要 markdown，字段：

- root_cause: string 中文原因说明；若无法从给定记录与规则说明中确定原因，必须写「信息不足，无法判断」，禁止编造未在输入中出现的原因

- confidence: number 0-1；当 root_cause 为「信息不足，无法判断」时 confidence 必须 ≤ 0.5

- responsible_party: string，取值 finance / sales / mdm_team / logistics 之一

- evidence: string[] 支持性证据列表，每条须引用输入中的具体字段或规则说明，禁止空泛表述如「根据分析」"""

# deepseek-v4-pro 等模型会把大量 token 用于 reasoning，过小 max_tokens 会导致 content 里 JSON 被截断
EXPLAIN_MIN_MAX_TOKENS = 2048
EXPLAIN_MAX_MAX_TOKENS = 4096


def _format_llm_fallback(exc: Exception) -> str:
    msg = str(exc).strip()
    if isinstance(exc, json.JSONDecodeError) or "Expecting value" in msg or "Unterminated" in msg:
        return (
            "大模型返回的 JSON 不完整（常见原因：最大输出 Token 过小，回复在 reasoning 阶段耗尽配额被截断）。"
            "请在管理后台「大模型配置」将 max_tokens 提高到 2048 以上后重试。"
        )
    if "返回空内容" in msg or "空响应" in msg:
        return "大模型未返回可用正文，请检查模型名称与 API Key 或稍后重试。"
    return msg or "大模型调用失败"


async def analyze_difference(
    diff: dict[str, Any],
    *,
    db: Session | None = None,
    task: Task | None = None,
    prefer_llm: bool = False,
) -> dict[str, Any]:
    """默认按检测规则（含方太登记表排查要点）生成解释，不使用 Mock 话术。"""
    if db is not None:
        rule_rec = rule_based_recommendation(diff, db, task=task)
        if rule_rec:
            if prefer_llm:
                cfg = get_effective_llm_config(db)
                if llm_api_ready(cfg):
                    try:
                        return await _deepseek_recommendation(diff, cfg)
                    except Exception as exc:
                        rule_rec["fallback_reason"] = _format_llm_fallback(exc)
            return rule_rec
    return _fallback_recommendation(diff)





def _extract_message_content(message: dict[str, Any]) -> str:

    content = (message.get("content") or "").strip()

    if content:

        return content

    return (message.get("reasoning_content") or "").strip()





def _normalize_rule_type(diff: dict[str, Any]) -> str | None:
    raw = diff.get("rule_id") or diff.get("type") or ""
    if raw in RULE_TYPE_LABEL:
        return raw
    if raw in DIFF_TYPE_TO_RULE_TYPE:
        return DIFF_TYPE_TO_RULE_TYPE[raw]
    return DIFF_TYPE_TO_RULE_TYPE.get(str(raw))


def _load_rule_config(db: Session, diff: dict[str, Any], task: Task | None) -> RuleConfig | None:
    hits = diff.get("rule_hits") or []
    if hits and isinstance(hits[0], dict):
        hit_id = hits[0].get("rule_id")
        if hit_id and len(str(hit_id)) >= 32:
            row = db.query(RuleConfig).filter(RuleConfig.id == str(hit_id)).first()
            if row:
                return row
    rule_type = _normalize_rule_type(diff)
    if not rule_type:
        return None
    q = db.query(RuleConfig).filter(RuleConfig.rule_type == rule_type, RuleConfig.enabled.is_(True))
    if task and task.rule_version_id:
        q = q.filter(RuleConfig.rule_version_id == task.rule_version_id)
    elif task and task.business_center_id:
        q = q.filter(RuleConfig.business_center_id == task.business_center_id)
    return q.order_by(RuleConfig.version.desc()).first()


RULE_EXPLAIN_MAX_CHARS = 32_000


def _get_rule_troubleshooting_steps(rule: RuleConfig) -> str:
    return str((rule.params or {}).get("troubleshooting_steps") or "").strip()


def _pick_troubleshooting_hint(rule: RuleConfig, diff: dict[str, Any]) -> str:
    """返回与当前差异描述最相关的单条登记场景（完整块，不截断）。"""
    steps = _get_rule_troubleshooting_steps(rule)
    if not steps:
        return ""
    desc = str(diff.get("description") or "")
    for block in re.split(r"\n(?=\d+\.\s*(?:\[|【))", steps):
        block = block.strip()
        if not block:
            continue
        first_line = block.split("\n", 1)[0]
        if desc and any(tok in desc for tok in first_line.split() if len(tok) > 4):
            return block
        if desc and any(tok in desc for tok in block.split() if len(tok) > 4):
            return block
    return ""


def _build_rule_explain_root_cause(
    rule: RuleConfig,
    *,
    type_label: str,
    condition: str,
    steps: str,
    matched_block: str,
    fact_parts: list[str],
) -> str:
    """组装规则解释正文：检测逻辑 + 全部登记场景 + 差异事实（供前台 parseExplainText 结构化渲染）。"""
    sections: list[str] = [f"【{rule.name}】{type_label}。"]
    if condition:
        sections.append(condition.strip())
    if steps:
        if matched_block:
            headline = matched_block.split("\n", 1)[0].strip()
            sections.append(f"本条差异最相关登记场景：{headline}")
        sections.append(steps)
    if fact_parts:
        sections.append("差异事实：" + "；".join(fact_parts) + "。")
    text = "\n\n".join(sections)
    if len(text) > RULE_EXPLAIN_MAX_CHARS:
        return text[:RULE_EXPLAIN_MAX_CHARS] + "\n\n（内容过长已截断，完整条目请见管理后台规则引擎）"
    return text


def rule_based_recommendation(
    diff: dict[str, Any],
    db: Session,
    *,
    task: Task | None = None,
) -> dict[str, Any] | None:
    if task is None and diff.get("task_id"):
        task = db.query(Task).filter(Task.id == diff["task_id"]).first()
    rule = _load_rule_config(db, diff, task)
    if not rule:
        return None

    rule_type = rule.rule_type
    type_label = RULE_TYPE_LABEL.get(rule_type, diff.get("type", rule_type))
    biz_amt = diff.get("business_amount")
    fin_amt = diff.get("finance_amount")
    amt_diff = diff.get("amount_diff")
    threshold = float(rule.threshold or 0)
    party = (rule.params or {}).get("responsible_party") or diff.get("responsible_party") or "finance"
    party_cn = PARTY_LABEL.get(party, party)

    fact_parts: list[str] = []
    if diff.get("business_key"):
        fact_parts.append(f"业务键 {diff['business_key']}")
    if biz_amt is not None and fin_amt is not None:
        fact_parts.append(f"业务侧 {biz_amt:,.2f} 元、财务侧 {fin_amt:,.2f} 元")
        if amt_diff is not None:
            fact_parts.append(f"差额 {amt_diff:,.2f} 元")
    if rule_type == "amount_mismatch" and threshold > 0:
        fact_parts.append(f"容差阈值 ¥{threshold:g}")

    condition = (rule.condition or "").strip()
    steps = _get_rule_troubleshooting_steps(rule)
    matched_block = _pick_troubleshooting_hint(rule, diff)
    root_cause = _build_rule_explain_root_cause(
        rule,
        type_label=type_label,
        condition=condition,
        steps=steps,
        matched_block=matched_block,
        fact_parts=fact_parts,
    )

    sap = diff.get("sap_record") or {}
    dms = diff.get("dms_record") or {}
    evidence = [
        f"命中规则：{rule.name}（{rule.id[:8]}…）",
        f"检测逻辑：{condition[:120]}{'…' if len(condition) > 120 else ''}" if condition else f"规则类型：{type_label}",
    ]
    if diff.get("description"):
        evidence.append(f"引擎判定：{diff['description'][:160]}")
    if steps:
        scenario_count = len(re.findall(r"(?m)^\d+\.\s*(?:\[|【)", steps))
        evidence.append(
            f"登记排查场景：共 {scenario_count or '多'} 条（与工作台规则引擎一致，已全部写入解释正文）"
        )
    if sap or dms:
        evidence.append(
            f"业务侧 order={sap.get('order_id')} 金额={sap.get('sales_amount')}；"
            f"财务侧 order={dms.get('order_id')} 金额={dms.get('sales_amount')}"
        )
    samples = (rule.params or {}).get("pattern_samples") or []
    if samples and isinstance(samples[0], dict):
        evidence.append(f"登记表样例：{samples[0].get('name', '')[:80]}")

    suggested = f"按「{rule.name}」处置：由{party_cn}核实原始单据与系统状态"
    if rule_type == "duplicate_record":
        suggested += "，去重或合并重复行后再次验证"
    elif rule_type == "mapping_anomaly":
        suggested += "，修正主数据/映射后重跑核对"
    else:
        suggested += "，修正源数据或说明差异原因"

    confidence = float((rule.params or {}).get("confidence") or diff.get("confidence") or 0.85)
    return {
        "root_cause": root_cause,
        "confidence": min(confidence, 0.99),
        "responsible_party": party,
        "suggested_action": suggested,
        "evidence": evidence,
        "model": "rule-engine",
        "prompt_version": "fangtai-rules-2",
        "provider": "rule-config",
        "rule_config_id": rule.id,
        "rule_name": rule.name,
    }


def _fallback_recommendation(diff: dict[str, Any]) -> dict[str, Any]:
    """无规则库命中时，仍基于差异事实与引擎说明生成，不使用 Mock 话术表。"""
    diff_type = diff.get("type", "")
    desc = diff.get("description") or MOCK_REASONS.get(diff_type, "需进一步人工核实")
    rec = _mock_recommendation(diff)
    rec["root_cause"] = f"【{diff_type}】{desc}"
    rec["model"] = "rule-engine"
    rec["provider"] = "detector-fallback"
    rec["prompt_version"] = "detector-fallback-1"
    return rec


def _mock_recommendation(diff: dict[str, Any]) -> dict[str, Any]:

    diff_type = diff.get("type", "")

    sap = diff.get("sap_record") or {}

    dms = diff.get("dms_record") or {}

    root = MOCK_REASONS.get(diff_type, "需进一步人工核实")

    return {

        "root_cause": root,

        "confidence": diff.get("confidence", 0.75),

        "responsible_party": diff.get("responsible_party", "finance"),

        "suggested_action": "verify_with_responsible_party",

        "evidence": [

            f"SAP 订单: {sap.get('order_id')} 金额 {sap.get('sales_amount')}",

            f"DMS 订单: {dms.get('order_id')} 金额 {dms.get('sales_amount')}",

            f"规则命中: {diff.get('rule_id')}",

            f"检测说明: {diff.get('description')}",

        ],

        "model": "mock-ai",

        "prompt_version": "2.0",

    }





async def _deepseek_recommendation(diff: dict[str, Any], cfg: EffectiveLlmConfig) -> dict[str, Any]:
    user_prompt = f"""分析以下对账差异：

差异类型: {diff.get('type')}
规则说明: {diff.get('description')}
SAP 记录: {json.dumps(diff.get('sap_record') or {}, ensure_ascii=False)}
DMS 记录: {json.dumps(diff.get('dms_record') or {}, ensure_ascii=False)}
对账单记录: {json.dumps(diff.get('statement_record') or {}, ensure_ascii=False)}
规则置信度: {diff.get('confidence')}"""

    data = await _request_explain_json(cfg, user_prompt)

    data["model"] = cfg.model

    data["prompt_version"] = "2.0-deepseek"

    data["provider"] = cfg.provider or "deepseek"

    if "suggested_action" not in data:

        party = data.get("responsible_party") or diff.get("responsible_party") or "finance"

        data["suggested_action"] = f"联系责任方 {party} 核实原始单据并修正"

    if "evidence" not in data or not data["evidence"]:

        sap = diff.get("sap_record") or {}

        dms = diff.get("dms_record") or {}

        data["evidence"] = [

            f"业务键: {diff.get('business_key')}",

            f"业务侧金额: {sap.get('sales_amount') or diff.get('business_amount')}",

            f"财务侧金额: {dms.get('sales_amount') or diff.get('finance_amount')}",

            f"规则: {diff.get('rule_id')}",

            f"说明: {diff.get('description')}",

        ]

    if "confidence" in data:

        c = data["confidence"]

        data["confidence"] = float(c) if float(c) <= 1 else float(c) / 100

    root = str(data.get("root_cause") or "").strip()
    if re.search(r"信息不足|无法判断|不确定", root):
        data["root_cause"] = "信息不足，无法判断"
        data["confidence"] = min(float(data.get("confidence") or 0.48), 0.5)
        data["insufficient_info"] = True

    return data


async def _request_explain_json(cfg: EffectiveLlmConfig, user_prompt: str) -> dict[str, Any]:
    """调用 DeepSeek 并解析 JSON；输出 token 不足时自动加大 max_tokens 重试。"""
    url = f"{cfg.base_url.rstrip('/')}/chat/completions"
    limit = max(int(cfg.max_tokens or 800), EXPLAIN_MIN_MAX_TOKENS)
    last_err: Exception | None = None

    while limit <= EXPLAIN_MAX_MAX_TOKENS:
        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": cfg.system_prompt or SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
            "max_tokens": limit,
            "temperature": cfg.temperature,
        }
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            raw = (resp.text or "").strip()
            if not raw:
                raise ValueError("DeepSeek 返回空响应体")
            body = json.loads(raw)

        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = _extract_message_content(message)
        finish_reason = choice.get("finish_reason")

        if not content:
            raise ValueError("DeepSeek 返回空内容")

        try:
            return _parse_json_content(content)
        except json.JSONDecodeError as exc:
            last_err = exc
            if finish_reason == "length" and limit < EXPLAIN_MAX_MAX_TOKENS:
                limit = min(limit * 2, EXPLAIN_MAX_MAX_TOKENS)
                continue
            raise ValueError(
                f"大模型 JSON 解析失败（finish_reason={finish_reason}，max_tokens={limit}）: {exc}"
            ) from exc

    if last_err:
        raise last_err
    raise ValueError("大模型解释失败：已超过最大重试配额")


def _parse_json_content(text: str) -> dict[str, Any]:

    text = text.strip()

    try:

        return json.loads(text)

    except json.JSONDecodeError:

        match = re.search(r"\{[\s\S]*\}", text)

        if match:

            return json.loads(match.group())

        raise





def diff_item_from_model(diff: Any) -> dict[str, Any]:

    """将已持久化的差异行还原为 analyze_difference 所需结构。"""

    rule_hit = (diff.rule_hits or [{}])[0] if diff.rule_hits else {}

    description = rule_hit.get("message") if isinstance(rule_hit, dict) else None

    if not description and diff.evidence:

        description = str(diff.evidence.get("difference_amount") or diff.type)

    return {

        "id": diff.id,

        "task_id": diff.task_id,

        "type": diff.type,

        "rule_id": rule_hit.get("rule_id") if isinstance(rule_hit, dict) else diff.type,

        "description": description or diff.ai_explanation or diff.type,

        "business_key": diff.business_key,

        "business_amount": diff.business_amount,

        "finance_amount": diff.finance_amount,

        "amount_diff": diff.amount_diff,

        "confidence": diff.confidence,

        "responsible_party": diff.responsible_party,

        "sap_record": diff.sap_record,

        "dms_record": diff.dms_record,

        "statement_record": diff.statement_record,

        "rule_hits": diff.rule_hits,

    }





def build_evidence_chain(diff: dict, recommendation: dict, user_review: dict | None = None) -> list[dict]:

    now = datetime.utcnow().isoformat() + "Z"

    chain = [

        {

            "step": 1,

            "stage": "detection",

            "action": "rules_applied",

            "rule_id": diff.get("rule_id"),

            "result": "matched",

            "confidence": diff.get("confidence"),

            "timestamp": now,

            "executed_by": "system",

        },

        {

            "step": 2,

            "stage": "rule_analysis"
            if str(recommendation.get("model", "")).startswith("rule")
            else "ai_analysis",

            "action": "rule_based_explain"
            if str(recommendation.get("model", "")).startswith("rule")
            else "llm_invoked",

            "model": recommendation.get("model", "rule-engine"),

            "prompt_version": recommendation.get("prompt_version", "fangtai-rules-1"),

            "provider": recommendation.get("provider", "rule-config"),

            "rule_name": recommendation.get("rule_name"),

            "result": recommendation.get("root_cause"),

            "confidence": recommendation.get("confidence"),

            "timestamp": now,

            "executed_by": "system",

        },

    ]

    if user_review:

        chain.append(

            {

                "step": 3,

                "stage": "human_review",

                "action": "user_reviewed",

                "result": user_review.get("decision"),

                "user_name": user_review.get("user_name"),

                "comment": user_review.get("comment"),

                "timestamp": now,

                "executed_by": user_review.get("user_id", "user"),

            }

        )

    return chain


