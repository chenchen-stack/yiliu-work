"""对话内可执行动作：数据源确认、发起核对。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.models import DataSource, RuleConfig, Task
from app.services.ai_analyzer import PARTY_LABEL, RULE_TYPE_LABEL
from app.services.mapping_binding import list_launch_datasource_pairs
from app.services.platform_seed import get_published_business_center

# 仅用于显式发起核对，勿用「核对/差异/收入」等单关键词（会误判流程说明类问题）
START_RECON_PATTERNS = (
    "帮我核对", "帮我查", "帮我比对", "帮我核", "发起对账", "开始对账", "执行核对",
    "跑一遍", "跑一", "对账分析", "比较SAP", "比对SAP", "核对一下",
    "我要对账", "想要对账", "需要对账", "打算对账", "做个对账", "做一下对账",
    "进行对账", "做对账", "跑对账", "收入核对", "收入对账",
)
EXECUTE_PATTERNS = (
    "使用推荐方案", "确认对账", "开始对账", "执行对账", "开始分析", "确认执行",
    "使用推荐", "按推荐方案",
)

PREFERRED_PAIRS: list[tuple[re.Pattern[str], re.Pattern[str]]] = [
    (re.compile(r"SAP结算行明细|SAP发货开票明细"), re.compile(r"DMS收入台账明细")),
]


def _system_label(ds: DataSource) -> str:
    profile = (ds.detected_profile or ds.system_type or "").lower()
    if profile in ("sap",):
        return "SAP 财务系统"
    if profile in ("dms",):
        return "DMS 经销商系统"
    if profile in ("fanruan", "statement"):
        return "帆软报表系统"
    side = "业务侧" if ds.side == "business" else "财务侧"
    return f"{ds.name}（{side}）"


def _format_sync_time(ds: DataSource) -> str:
    ts = ds.created_at or datetime.utcnow()
    return ts.strftime("%Y-%m-%d %H:%M")


def resolve_default_pair(sources: list[DataSource]) -> tuple[DataSource | None, DataSource | None]:
    biz_list = [s for s in sources if s.side == "business"]
    fin_list = [s for s in sources if s.side == "finance"]
    if not biz_list or not fin_list:
        return None, None

    for biz_re, fin_re in PREFERRED_PAIRS:
        biz = next((s for s in biz_list if biz_re.search(s.name)), None)
        fin = next((s for s in fin_list if fin_re.search(s.name)), None)
        if biz and fin:
            return biz, fin

    def score(ds: DataSource, side: str) -> float:
        cols = ds.detected_columns or []
        english = sum(1 for c in cols if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(c)))
        profile_bonus = 20 if ds.detected_profile == ("sap" if side == "business" else "dms") else 0
        poc_bonus = 25 if re.search(r"结算行|收入台账", ds.name) else 0
        return english * 2 + profile_bonus + poc_bonus + len(cols) * 0.01

    biz = max(biz_list, key=lambda s: score(s, "business"))
    fin = max(fin_list, key=lambda s: score(s, "finance"))
    return biz, fin


def _system_kind(ds: DataSource) -> str:
    profile = (ds.detected_profile or ds.system_type or ds.name or "").lower()
    if "sap" in profile:
        return "sap"
    if "dms" in profile:
        return "dms"
    if re.search(r"帆软|fanruan|报表|statement", profile):
        return "fanruan"
    return "generic"


def _recommended_display_ids(rows: list[DataSource], biz: DataSource | None, fin: DataSource | None) -> list[str]:
    ids: list[str] = []
    if biz:
        ids.append(biz.id)
    if fin and fin.id not in ids:
        ids.append(fin.id)
    extra = next(
        (s for s in rows if re.search(r"帆软|fanruan|报表", s.name, re.I) and s.id not in ids),
        None,
    )
    if extra:
        ids.append(extra.id)
    return ids


def list_chat_datasources(db: Session, agent=None) -> dict[str, Any]:
    bc = get_published_business_center(db)
    mapping_hint = ""
    mapping_ready = False
    biz = fin = None

    if bc:
        pairs, meta = list_launch_datasource_pairs(db, bc.id)
        mapping_hint = meta.get("hint") or ""
        mapping_ready = bool(meta.get("mapping_ready"))
        if mapping_ready and pairs:
            biz = db.query(DataSource).filter(DataSource.id == pairs[0]["business_datasource_id"]).first()
            fin = db.query(DataSource).filter(DataSource.id == pairs[0]["finance_datasource_id"]).first()

    if not mapping_ready:
        if not mapping_hint:
            mapping_hint = "可直接上传 Excel / 连接演示库后在本页发起核对；也可使用内置演示数据集快速体验"
        rows = db.query(DataSource).filter(DataSource.status == "active").order_by(DataSource.created_at.desc()).all()
        scope_rows = rows
        if not biz and not fin and rows:
            biz, fin = resolve_default_pair(rows)
    else:
        scope_rows = [d for d in (biz, fin) if d]

    agent_scope = getattr(agent, "data_source_scope", None) if agent else None
    if agent_scope:
        _SCOPE_PROFILE_MAP = {
            "sap_billing": "sap",
            "dms_ledger": "dms",
            "fanruan_platform": "fanruan",
        }
        allowed_profiles = {_SCOPE_PROFILE_MAP.get(s, s) for s in agent_scope}
        scope_rows = [
            ds for ds in scope_rows
            if _system_kind(ds) in allowed_profiles
            or ds.id in (biz.id if biz else "", fin.id if fin else "")
        ]

    systems = [
        {
            "id": ds.id,
            "name": ds.name,
            "side": ds.side,
            "system_type": ds.system_type,
            "kind": _system_kind(ds),
            "system_label": _system_label(ds),
            "row_count": ds.row_count,
            "last_sync": _format_sync_time(ds),
            "status": "ok" if ds.status == "active" else "offline",
            "status_label": "连接正常" if ds.status == "active" else "离线",
        }
        for ds in scope_rows
    ]
    uploaded_pair = bool(biz and fin)
    return {
        "systems": systems,
        "recommended": {
            "business_datasource_id": biz.id if biz else None,
            "finance_datasource_id": fin.id if fin else None,
            "business_name": biz.name if biz else None,
            "finance_name": fin.name if fin else None,
            "display_ids": _recommended_display_ids(scope_rows, biz, fin),
        },
        "has_datasource_pair": mapping_ready and uploaded_pair,
        "has_uploaded_pair": uploaded_pair,
        "mapping_ready": mapping_ready,
        "mapping_hint": mapping_hint,
        "demo_dataset_id": "dataset_fangtai_real",
    }


def import_chat_datasources_from_excel(
    db: Session,
    user,
    content: bytes,
    filename: str,
    *,
    agent=None,
) -> dict[str, Any]:
    """对话内上传方太类 Excel，注册数据源并尝试绑定 SAP↔DMS 映射。"""
    from app.services.audit_service import log_audit
    from app.services.datasource_excel_import import import_excel_workbook
    from app.services.semantics_demo_seed import _bind_billing_ledger, _seed_billing_mapping

    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过 25MB")
    try:
        result = import_excel_workbook(db, content, filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Excel 解析失败: {exc}") from exc

    _seed_billing_mapping(db)
    bind_msg = _bind_billing_ledger(db)
    log_audit(
        db,
        user=user,
        object_type="datasource",
        object_id="chat_import",
        action="chat_import_excel",
        detail={
            "filename": result.get("filename"),
            "imported": len(result.get("imported") or []),
            "bind": bind_msg,
        },
    )
    db.commit()
    opts = list_chat_datasources(db, agent=agent)
    return {
        "import": result,
        "bind_message": bind_msg,
        "options": opts,
        "message": result.get("message") or "导入完成",
    }


def upload_chat_datasource_file(
    db: Session,
    user,
    *,
    name: str,
    system_type: str,
    side: str,
    content: bytes,
    filename: str,
    agent=None,
) -> dict[str, Any]:
    """对话内单文件上传（csv / xlsx 单表）。"""
    from pathlib import Path

    from app.services.audit_service import log_audit
    from app.config import UPLOAD_DIR
    from app.models import DataSource
    from app.services.data_loader import load_dataframe
    from app.services.mapping_engine import detect_data_profile

    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过 25MB")

    ds_id = str(uuid.uuid4())
    suffix = Path(filename or "data.csv").suffix or ".csv"
    dest = UPLOAD_DIR / f"ds_{ds_id}{suffix}"
    dest.write_bytes(content)

    try:
        df = load_dataframe(dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"文件解析失败: {exc}") from exc

    profile = detect_data_profile(df)
    columns = list(df.columns.astype(str))
    ds = DataSource(
        id=ds_id,
        name=name.strip() or Path(filename).stem,
        system_type=system_type,
        side=side,
        file_path=str(dest),
        detected_columns=columns,
        detected_profile=profile if profile != "unknown" else system_type,
        row_count=len(df),
    )
    db.add(ds)
    log_audit(
        db,
        user=user,
        object_type="datasource",
        object_id=ds_id,
        action="chat_upload",
        detail={"name": ds.name, "rows": len(df), "side": side},
    )
    db.commit()
    opts = list_chat_datasources(db, agent=agent)
    return {"datasource_id": ds_id, "name": ds.name, "row_count": len(df), "options": opts}


def connect_chat_demo_datasources(db: Session, user) -> dict[str, Any]:
    """对话内一键连接 SAP / DMS 演示库（sample-data → 数据源 + 映射绑定）。"""
    from app.services.semantics_demo_seed import run_semantics_demo_seed

    seed = run_semantics_demo_seed(db, user)
    return {
        "message": "已连接 SAP / DMS 演示数据源，可直接发起核对"
        if seed.get("mapping_ready")
        else "演示数据已加载，请上传完整 POC 文件或联系管理员完善映射",
        "seed": seed,
    }


def build_datasource_confirm_block(db: Session, period: str | None = None, agent=None) -> dict[str, Any]:
    opts = list_chat_datasources(db, agent=agent)
    rec = opts["recommended"]
    agent_id = getattr(agent, "id", None) if agent else None
    return {
        "type": "datasource_confirm",
        "data": {
            "period": period or "2024-05",
            "intro": datasource_confirm_reply(period or "2024-05"),
            "systems": opts["systems"],
            "recommended_business_id": rec["business_datasource_id"],
            "recommended_finance_id": rec["finance_datasource_id"],
            "recommended_display_ids": rec.get("display_ids") or [],
            "has_datasource_pair": opts["has_datasource_pair"],
            "mapping_ready": opts.get("mapping_ready", False),
            "mapping_hint": opts.get("mapping_hint") or "",
            "demo_dataset_id": opts["demo_dataset_id"],
            "agent_id": agent_id,
        },
    }


def load_datasource_preview(db: Session, ds_id: str, *, limit: int = 50) -> dict[str, Any]:
    """读取后台 DataSource 文件预览（与 admin 预览一致）。"""
    from pathlib import Path

    from app.services.data_loader import json_safe_cell, load_dataframe

    ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
    if not ds:
        raise HTTPException(404, "数据源不存在")
    fpath = Path(ds.file_path)
    if not fpath.is_file():
        raise HTTPException(404, "数据文件已丢失，请重新上传该数据源")
    try:
        df = load_dataframe(fpath)
    except Exception as exc:
        raise HTTPException(422, f"数据文件解析失败: {exc}") from exc
    head = df.head(min(max(limit, 1), 200))
    rows: list[dict] = []
    for record in head.to_dict(orient="records"):
        rows.append({str(k): json_safe_cell(v) for k, v in record.items()})
    return {
        "id": ds.id,
        "name": ds.name,
        "system_type": ds.system_type,
        "side": ds.side,
        "row_count": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "total_rows": int(len(df)),
        "rows": rows,
    }


def preview_datasource_for_agent(
    db: Session,
    ds_id: str,
    *,
    agent,
    limit: int = 50,
) -> dict[str, Any]:
    """仅允许预览当前 Agent / 业务中心授权范围内的数据源。"""
    opts = list_chat_datasources(db, agent=agent)
    allowed = {s["id"] for s in opts.get("systems") or []}
    if ds_id not in allowed:
        raise HTTPException(403, "该数据源不在当前 Agent 授权范围内")
    return load_datasource_preview(db, ds_id, limit=limit)


def assert_datasource_pair_allowed(
    db: Session,
    *,
    agent,
    business_datasource_id: str | None,
    finance_datasource_id: str | None,
) -> None:
    opts = list_chat_datasources(db, agent=agent)
    allowed = {s["id"] for s in opts.get("systems") or []}
    for sid in (business_datasource_id, finance_datasource_id):
        if sid and sid not in allowed:
            raise HTTPException(403, f"数据源 {sid} 不在当前 Agent 授权范围内")


def build_task_progress_block(task: Task) -> dict[str, Any]:
    return {
        "type": "task_progress",
        "data": {
            "task_id": task.id,
            "task_name": task.name,
            "period": task.period,
            "status": task.status,
            "progress": task.progress,
        },
    }


def parse_period_from_message(message: str) -> str | None:
    m = re.search(r"(20\d{2})[-年/](\d{1,2})", message)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m2 = re.search(r"(\d{1,2})\s*月", message)
    if m2:
        return f"2024-{int(m2.group(1)):02d}"
    if "上月" in message or "上个月" in message:
        return "2024-04"
    if "本月" in message or "这个月" in message:
        return "2024-05"
    return None


def is_faq_question(message: str, client_action: str | None = None) -> str | None:
    """知识类问题返回预设 intent，不走数据源确认卡片。"""
    if re.search(r"检索|知识库|案例库|登记表|对账经验", message or ""):
        return None
    if client_action == "faq_workflow":
        return "faq_workflow"
    if client_action == "faq_diff_types":
        return "faq_diff_types"
    if re.search(r"(标准流程|流程是什么|怎么操作|有哪些步骤|工作流程)", message) and re.search(
        r"核对|对账|收入核对", message
    ):
        return "faq_workflow"
    if re.search(r"(分别怎么处理|如何处理|怎么处理|处理建议|处置)", message) and re.search(
        r"金额差异|重复数据|映射异常|三类差异|三类", message
    ):
        return "faq_diff_types"
    if re.search(r"^(你好|您好|hi|hello)\b", message, re.I):
        return "faq_intro"
    return None


def build_faq_workflow_block() -> dict[str, Any]:
    """步骤顺序与文案与工作台 EXECUTION_PIPELINE 一致（7 步横向展示）。"""
    return {
        "type": "faq_workflow",
        "data": {
            "title": "收入核对 Workflow",
            "steps": [
                {
                    "title": "加载数据",
                    "desc": "读取已接入的业务侧、财务侧数据源（SAP / DMS 等）。",
                },
                {
                    "title": "实体与规则",
                    "desc": "加载已发布本体实体与领域规则，建立对账语义上下文。",
                },
                {
                    "title": "字段映射",
                    "desc": "将物理列挂接到语义实体与匹配键，生成可比对记录。",
                },
                {
                    "title": "差异识别",
                    "desc": "按规则引擎识别金额差异、重复数据、主数据/映射异常。",
                },
                {
                    "title": "异常解释",
                    "desc": "大模型结合规则与证据链生成差异解释。",
                },
                {
                    "title": "复核流转",
                    "desc": "在「待复核」中确认、退回或指派处理。",
                },
                {
                    "title": "再次验证",
                    "desc": "处理完成后重新跑批，验证是否闭环。",
                },
                {
                    "title": "报告生成",
                    "desc": "生成 PDF 对账报告并归档。",
                },
            ],
            "hint": "如需直接开始对账，请说明周期，例如：帮我核对一下 5 月份的收入数据。",
            "workbench_path": "/workbench/reconciliation/tasks/new",
        },
    }


RULE_TYPE_KIND: dict[str, str] = {
    "amount_mismatch": "amount",
    "duplicate_record": "duplicate",
    "mapping_anomaly": "mapping",
    "payment_mismatch": "payment",
    "sync_failure": "sync",
    "status_mismatch": "status",
    "fanruan_summary": "fanruan",
}

SEVERITY_CN = {"high": "高", "medium": "中", "low": "低"}

_FALLBACK_FAQ_DIFF_ITEMS = [
    {
        "kind": "amount",
        "label": "金额差异",
        "severity": "高",
        "definition": "同业务键（发票号/结算单等）两侧金额不一致。",
        "action": "财务在待复核中确认事实后，修正源数据或说明原因；差值在容差阈值内可不计差异。",
        "owner": "财务侧",
    },
    {
        "kind": "duplicate",
        "label": "重复数据",
        "severity": "中",
        "definition": "同侧组合键（订单+发票+客户等）出现重复行。",
        "action": "定位重复来源（接口重传、手工补录等），去重或合并后再验证。",
        "owner": "业务 / 接口",
    },
    {
        "kind": "mapping",
        "label": "主数据 / 映射异常",
        "severity": "高",
        "definition": "MDM 抬头、发票类型、产品编码或 MDMID/办事处映射不一致。",
        "action": "由主数据或 IT 修正映射后重跑。",
        "owner": "主数据 / IT",
    },
]


def load_published_rule_configs(db: Session) -> tuple[list[RuleConfig], str | None]:
    """读取已发布业务中心当前绑定的规则版本（与 Workflow detect 节点同源）。"""
    bc = get_published_business_center(db)
    if not bc or not bc.rule_version_id:
        return [], None
    rows = (
        db.query(RuleConfig)
        .filter(
            RuleConfig.rule_version_id == bc.rule_version_id,
            RuleConfig.enabled.is_(True),
        )
        .order_by(RuleConfig.name)
        .all()
    )
    return rows, bc.rule_version_id


def _rule_to_faq_item(rule: RuleConfig) -> dict[str, Any]:
    params = rule.params or {}
    rt = rule.rule_type or ""
    hint = str(params.get("troubleshooting_steps") or "").strip()
    action_line = ""
    if hint:
        action_line = hint.split("\n", 1)[0].strip()[:240]
    if not action_line:
        action_line = (rule.condition or "").strip()[:240]
    party = params.get("responsible_party") or "finance"
    owner = PARTY_LABEL.get(str(party), str(party))
    definition = (rule.condition or RULE_TYPE_LABEL.get(rt, rule.name or rt)).strip()
    if rule.threshold and float(rule.threshold) > 0 and rt == "amount_mismatch":
        definition = f"{definition}（容差阈值 ¥{float(rule.threshold):g}）"
    return {
        "kind": RULE_TYPE_KIND.get(rt, "generic"),
        "label": rule.name or RULE_TYPE_LABEL.get(rt, rt),
        "severity": SEVERITY_CN.get(str(rule.severity or "medium"), rule.severity),
        "definition": definition[:320],
        "action": action_line or "按方太登记表排查要点处理",
        "owner": owner,
        "rule_id": rule.id,
        "rule_type": rt,
        "troubleshooting": hint[:600] if hint else "",
    }


def build_faq_diff_types_block(db: Session | None = None) -> dict[str, Any]:
    """差异类型说明卡：优先读取后台 RuleConfig（与规则引擎 / detect Skill 同源）。"""
    items: list[dict[str, Any]] = []
    rule_version_id: str | None = None
    if db is not None:
        rules, rule_version_id = load_published_rule_configs(db)
        items = [_rule_to_faq_item(r) for r in rules]
    if not items:
        items = [dict(x) for x in _FALLBACK_FAQ_DIFF_ITEMS]
    title = (
        f"方太排查规则（{len(items)} 类）"
        if rule_version_id
        else "三类核心差异处理"
    )
    hint = (
        "以上规则与后台「规则引擎」及 Workflow「差异识别」节点绑定一致；"
        "发起对账后由规则引擎自动判定，异常解释 Skill 会引用命中规则的排查要点。"
        if rule_version_id
        else "需要发起自动核对时，请描述月份与数据源，例如：帮我核对 2024-05 的 SAP 与 DMS 收入。"
    )
    return {
        "type": "faq_diff_types",
        "data": {
            "title": title,
            "items": items,
            "rule_version_id": rule_version_id,
            "source": "rule_engine" if rule_version_id else "fallback",
            "hint": hint,
        },
    }


def wants_start_reconciliation(message: str, history: list | None = None) -> bool:
    del history  # 不再用历史关键词累加误判
    msg = (message or "").strip()
    if not msg:
        return False
    if any(p in msg for p in START_RECON_PATTERNS):
        return True
    if re.search(r"(我要|想要|需要|打算|帮我).{0,6}(对账|核对)", msg):
        return True
    if re.search(r"^(对账|核对)(一下|吧|呢)?$", msg):
        return True
    if re.search(r"(发起|开始|执行).{0,8}(对账|核对)", msg):
        return True
    if re.search(r"(核对|对账).{0,12}\d{1,2}\s*月", message):
        return True
    if re.search(r"\d{1,2}\s*月.{0,20}(收入|数据).{0,12}(核对|对账|SAP|DMS)", message):
        return True
    if ("比较" in message or "比对" in message) and ("SAP" in message or "DMS" in message):
        return True
    return False


def should_show_datasource_panel(
    message: str,
    history: list,
    *,
    has_diff_context: bool,
    client_action: str | None = None,
) -> bool:
    if has_diff_context:
        return False
    if client_action == "start_reconciliation":
        return True
    if wants_execute_recommended(message):
        return False
    return wants_start_reconciliation(message, history)


def wants_execute_recommended(message: str) -> bool:
    return any(p in message for p in EXECUTE_PATTERNS)


def intro_reply() -> str:
    return (
        "您好，我是亿流 Work 收入核对助手，可协助您完成以下工作：\n"
        "1. 查询当前收入核对任务的完成状态与最新处理时间\n"
        "2. 解释金额差异、重复数据、主数据或映射异常三类差异\n"
        "3. 在对话中直接选择数据源并发起核对分析\n"
        "4. 说明差异工单的复核规则与闭环处置方式\n\n"
        "如需对账，请直接描述需求，例如：帮我核对一下 5 月份的收入数据。"
    )


def datasource_confirm_reply(period: str) -> str:
    return (
        f"好的，已为您准备「{period}」收入核对。"
        "请在下方案块确认 SAP / DMS 数据来源与核对周期；"
        "确认后点击「使用推荐方案进行对账分析」，系统将自动执行字段映射、差异识别与 AI 解释，"
        "约 1–3 分钟可在对话中查看结果摘要与待复核清单。"
    )


def task_started_reply(task: Task) -> str:
    return (
        f"已收到，正在对「{task.name}」进行数据分析，Workflow 将自动完成字段映射、差异识别与 AI 解释。"
        f"预计 1–3 分钟，您可点击下方链接查看实时进度。"
    )


def detect_chat_ui(
    message: str,
    db: Session,
    *,
    has_diff_context: bool,
    history: list | None = None,
    client_action: str | None = None,
) -> tuple[str | None, list[dict[str, Any]], str | None]:
    """返回 (preset_reply, ui_blocks, intent)。有 intent 时跳过 LLM。"""
    hist = history or []
    faq = is_faq_question(message, client_action)
    if faq == "faq_workflow":
        return "", [build_faq_workflow_block()], "faq_workflow"
    if faq == "faq_diff_types":
        return "", [build_faq_diff_types_block(db)], "faq_diff_types"
    if faq == "faq_intro":
        from app.services.agent_ui_blocks import (
            build_onboarding_block,
            build_quick_actions_block,
        )
        return "", [
            build_onboarding_block(),
            build_quick_actions_block(),
        ], "onboarding"

    if not should_show_datasource_panel(
        message, hist, has_diff_context=has_diff_context, client_action=client_action
    ):
        return None, [], None

    period = parse_period_from_message(message) or "2024-05"
    for h in reversed(hist):
        if h.get("role") == "user":
            p = parse_period_from_message(h.get("content", ""))
            if p:
                period = p
                break

    block = build_datasource_confirm_block(db, period)
    # 引导文案仅放在 ui_blocks.data.intro，避免与 assistant.content 重复渲染
    return "", [block], "start_reconciliation"


def execute_reconciliation_from_chat(
    db: Session,
    user,
    *,
    business_datasource_id: str | None,
    finance_datasource_id: str | None,
    demo_dataset_id: str | None,
    period: str,
    name: str | None,
    background_tasks: BackgroundTasks,
    agent=None,
) -> tuple[Task, str, list[dict[str, Any]]]:
    from app.services.task_launch_service import launch_reconciliation_task

    task_name = name or f"{period.replace('-', '年')}月收入核对"
    if not business_datasource_id and not finance_datasource_id and not demo_dataset_id:
        opts = list_chat_datasources(db, agent=agent)
        rec = opts["recommended"]
        if opts["has_datasource_pair"]:
            business_datasource_id = rec["business_datasource_id"]
            finance_datasource_id = rec["finance_datasource_id"]
        else:
            demo_dataset_id = opts["demo_dataset_id"]

    launch_kwargs: dict = dict(
        name=task_name,
        period=period,
        business_datasource_id=business_datasource_id,
        finance_datasource_id=finance_datasource_id,
        demo_dataset_id=demo_dataset_id if not business_datasource_id else None,
        background_tasks=background_tasks,
        auto_execute=True,
    )
    if agent and getattr(agent, "linked_workflow_id", None):
        launch_kwargs["workflow_id"] = agent.linked_workflow_id

    task = launch_reconciliation_task(db, user, **launch_kwargs)
    reply = task_started_reply(task)
    blocks = [build_task_progress_block(task)]
    return task, reply, blocks
