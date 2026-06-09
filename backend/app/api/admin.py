import json
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.config import CONFIG_DIR, UPLOAD_DIR
from app.database import get_db
from app.models import (
    AgentConfig,
    AuditLog,
    BusinessCenter,
    BusinessCenterStatus,
    CaseAsset,
    DataSource,
    MappingConfig,
    RuleConfig,
    RuleVersion,
    Skill,
    User,
    UserRole,
    Workflow,
)
from app.schemas import (
    AuditLogOut,
    BusinessCenterDetail,
    BusinessCenterOut,
    CaseAssetOut,
    KnowledgeUploadResultOut,
    DataSourceItemOut,
    DataSourceOut,
    DemoDatasetOut,
    LlmConfigOut,
    LlmConfigTestResult,
    LlmConfigUpdate,
    MappingConfigOut,
    FieldMappingRowIn,
    FieldMappingsSave,
    MappingDryRunOut,
    MatchRuleOut,
    ObjectTypeOut,
    OntologyMappingOut,
    PipelineStepOut,
    RawExampleOut,
    RelationshipOut,
    RevenueFieldMappingOut,
    RuleConfigOut,
    RuleConfigUpdate,
    ApplyTroubleshootingPresetIn,
    RuleImportResultOut,
    ReconciliationLaunchOptionsOut,
    DatasourcePairOut,
    RuleVersionCreate,
    TroubleshootingPresetOut,
    SkillInvocationOut,
    SkillOut,
    WorkflowOut,
    WorkflowUpdate,
)
from app.services.audit_service import log_audit
from app.services.mapping_engine import MappingRegistry, invalidate_mapping_cache, run_mapping_pipeline
from app.services.mapping_engine import load_and_translate_file
from app.services.platform_seed import IDS
from app.services.mapping_binding import (
    list_launch_datasource_pairs,
    set_mapping_binding,
    validate_datasource_pair,
)
from app.services.rule_import_service import (
    apply_preset,
    bind_rules_to_ontology,
    bind_rules_to_workflow_detect,
    import_excel_and_apply,
    import_excel_preview,
)
from app.services.fangtai_rule_extract import load_preset
from app.services.semantics_demo_seed import run_semantics_demo_seed
from app.services.datasource_excel_import import import_excel_workbook

router = APIRouter(prefix="/admin", tags=["admin"])
public_router = APIRouter(prefix="/business-centers", tags=["business-centers"])
demo_router = APIRouter(prefix="/demo-datasets", tags=["demo"])

SAMPLE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "sample-data"


def _bc_detail(db: Session, bc: BusinessCenter) -> BusinessCenterDetail:
    from app.services.workflow_engine import ensure_workflow_nodes

    wf = db.query(Workflow).filter(Workflow.id == bc.workflow_id).first() if bc.workflow_id else None
    wf_payload = None
    if wf:
        wf_payload = WorkflowOut.model_validate(wf).model_dump()
        wf_payload["nodes"] = ensure_workflow_nodes(wf_payload.get("nodes") or [])
        ids = [n["id"] for n in wf_payload["nodes"] if n.get("id")]
        wf_payload["transitions"] = [{"from": ids[i], "to": ids[i + 1]} for i in range(len(ids) - 1)]
    skills = []
    if bc.enabled_skill_ids:
        skills = db.query(Skill).filter(Skill.id.in_(bc.enabled_skill_ids)).all()
    rv = db.query(RuleVersion).filter(RuleVersion.id == bc.rule_version_id).first() if bc.rule_version_id else None
    return BusinessCenterDetail(
        id=bc.id,
        name=bc.name,
        code=bc.code,
        status=bc.status,
        workflow_id=bc.workflow_id,
        enabled_skill_ids=bc.enabled_skill_ids,
        rule_version_id=bc.rule_version_id,
        page_modules=bc.page_modules,
        allowed_roles=bc.allowed_roles,
        version=bc.version,
        workflow=wf_payload,
        skills=[SkillOut.model_validate(s).model_dump() for s in skills],
        rule_version={"id": rv.id, "version": rv.version, "status": rv.status, "description": rv.description} if rv else None,
    )


@public_router.get("", response_model=list[BusinessCenterOut])
def list_published_centers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(BusinessCenter).filter(BusinessCenter.status == BusinessCenterStatus.PUBLISHED.value)
    centers = q.all()
    return [c for c in centers if user.role in (c.allowed_roles or []) or user.role == UserRole.ADMIN.value]


@public_router.get("/{code}/launch-options", response_model=ReconciliationLaunchOptionsOut)
def get_reconciliation_launch_options(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """前台新建任务可选的数据源对：仅返回管理后台已绑定且校验通过的表对。"""
    bc = db.query(BusinessCenter).filter(BusinessCenter.code == code).first()
    if not bc:
        raise HTTPException(404, "业务中心不存在")
    if bc.status != BusinessCenterStatus.PUBLISHED.value:
        raise HTTPException(403, "业务中心未发布")
    if user.role not in (bc.allowed_roles or []) and user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "无权限访问该业务中心")
    pairs, meta = list_launch_datasource_pairs(db, bc.id)
    return ReconciliationLaunchOptionsOut(
        mapping_configured=bool(meta.get("mapping_configured")),
        mapping_ready=bool(meta.get("mapping_ready")),
        hint=meta.get("hint") or "",
        datasource_pairs=[DatasourcePairOut(**p) for p in pairs],
        binding=meta.get("binding"),
    )


@public_router.get("/{code}", response_model=BusinessCenterDetail)
def get_center_by_code(code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bc = db.query(BusinessCenter).filter(BusinessCenter.code == code).first()
    if not bc:
        raise HTTPException(404, "业务中心不存在")
    if bc.status != BusinessCenterStatus.PUBLISHED.value:
        raise HTTPException(403, "业务中心未发布")
    if user.role not in (bc.allowed_roles or []) and user.role != UserRole.ADMIN.value:
        raise HTTPException(403, "无权限访问该业务中心")
    return _bc_detail(db, bc)


@router.get("/business-centers", response_model=list[BusinessCenterOut])
def admin_list_centers(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    return db.query(BusinessCenter).all()


@router.get("/business-centers/{center_id}", response_model=BusinessCenterDetail)
def admin_get_center(
    center_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    bc = db.query(BusinessCenter).filter(BusinessCenter.id == center_id).first()
    if not bc:
        raise HTTPException(404, "业务中心不存在")
    return _bc_detail(db, bc)


@router.post("/business-centers/{center_id}/publish", response_model=BusinessCenterOut)
def publish_center(
    center_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    bc = db.query(BusinessCenter).filter(BusinessCenter.id == center_id).first()
    if not bc:
        raise HTTPException(404, "业务中心不存在")
    before = bc.status
    bc.status = BusinessCenterStatus.PUBLISHED.value
    bc.version += 1
    log_audit(
        db,
        user=user,
        object_type="business_center",
        object_id=bc.id,
        action="publish",
        before_data={"status": before, "version": bc.version - 1},
        after_data={"status": bc.status, "version": bc.version},
    )
    db.commit()
    db.refresh(bc)
    return bc


@router.post("/business-centers/{center_id}/offline", response_model=BusinessCenterOut)
def offline_center(
    center_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    bc = db.query(BusinessCenter).filter(BusinessCenter.id == center_id).first()
    if not bc:
        raise HTTPException(404, "业务中心不存在")
    before = bc.status
    bc.status = BusinessCenterStatus.OFFLINE.value
    log_audit(
        db,
        user=user,
        object_type="business_center",
        object_id=bc.id,
        action="offline",
        before_data={"status": before},
        after_data={"status": bc.status},
    )
    db.commit()
    db.refresh(bc)
    return bc


@router.post("/business-centers/{center_id}/page-modules", response_model=BusinessCenterDetail)
def update_page_modules(
    center_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """更新业务中心页面模块（草稿态保存；发布后才影响前台）。body: {"page_modules": [...]}"""
    bc = db.query(BusinessCenter).filter(BusinessCenter.id == center_id).first()
    if not bc:
        raise HTTPException(404, "业务中心不存在")
    modules = body.get("page_modules")
    if not isinstance(modules, list):
        raise HTTPException(400, "page_modules 必须为字符串数组")
    before = bc.page_modules
    bc.page_modules = modules
    # 修改后回到 testing，需重新发布才对前台生效
    bc.status = BusinessCenterStatus.TESTING.value
    log_audit(
        db,
        user=user,
        object_type="business_center",
        object_id=bc.id,
        action="update_page_modules",
        before_data={"page_modules": before},
        after_data={"page_modules": modules},
    )
    db.commit()
    db.refresh(bc)
    return _bc_detail(db, bc)


@router.post("/business-centers/{center_id}/rollback", response_model=BusinessCenterOut)
def rollback_center(
    center_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    bc = db.query(BusinessCenter).filter(BusinessCenter.id == center_id).first()
    if not bc:
        raise HTTPException(404, "业务中心不存在")
    before = {"status": bc.status, "rule_version_id": bc.rule_version_id}
    prev = (
        db.query(RuleVersion)
        .filter(RuleVersion.business_center_id == center_id, RuleVersion.version < bc.version)
        .order_by(RuleVersion.version.desc())
        .first()
    )
    if prev:
        bc.rule_version_id = prev.id
    bc.status = BusinessCenterStatus.TESTING.value
    log_audit(
        db,
        user=user,
        object_type="business_center",
        object_id=bc.id,
        action="rollback",
        before_data=before,
        after_data={"status": bc.status, "rule_version_id": bc.rule_version_id},
    )
    db.commit()
    db.refresh(bc)
    return bc


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, "Workflow 不存在")
    return wf


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut)
def update_workflow(
    workflow_id: str,
    body: WorkflowUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(404, "Workflow 不存在")

    locked = {"import", "mapping", "ontology", "detect"}
    before_nodes = list(wf.nodes or [])

    def _rebuild_transitions(nodes: list[dict]) -> list[dict]:
        ids = [n["id"] for n in nodes if n.get("id") and n.get("enabled", True)]
        return [{"from": ids[i], "to": ids[i + 1]} for i in range(len(ids) - 1)]

    if body.name:
        wf.name = body.name.strip()

    from app.services.workflow_engine import WORKFLOW_NODES, ensure_workflow_nodes

    base_nodes = ensure_workflow_nodes(list(wf.nodes or []))
    default_by_id = {n["id"]: dict(n) for n in WORKFLOW_NODES}
    if body.node_order:
        by_id = {n.get("id"): dict(n) for n in base_nodes if n.get("id")}
        ordered: list[dict] = []
        for nid in body.node_order:
            if nid in by_id:
                ordered.append(by_id.pop(nid))
            elif nid in default_by_id:
                ordered.append(dict(default_by_id[nid]))
        base_nodes = ordered

    if body.nodes is not None:
        patch_map = {n.id: n for n in body.nodes}
        merged: list[dict] = []
        for node in base_nodes:
            nid = node.get("id")
            if not nid:
                continue
            updated = dict(node)
            patch = patch_map.get(nid)
            if patch:
                if patch.label is not None:
                    updated["label"] = patch.label.strip()
                if patch.position is not None:
                    updated["position"] = {
                        "x": round(patch.position.x, 1),
                        "y": round(patch.position.y, 1),
                    }
                if patch.enabled is not None:
                    if nid in locked and not patch.enabled:
                        raise HTTPException(400, f"节点「{nid}」为核心步骤，不可停用")
                    updated["enabled"] = patch.enabled
            if "enabled" not in updated:
                updated["enabled"] = True
            merged.append(updated)
        wf.nodes = merged
        wf.transitions = _rebuild_transitions(merged)
    elif body.node_order:
        wf.nodes = base_nodes
        wf.transitions = _rebuild_transitions(base_nodes)

    log_audit(
        db,
        user=user,
        object_type="workflow",
        object_id=workflow_id,
        action="update",
        before_data={"nodes": before_nodes},
        after_data={"nodes": wf.nodes, "name": wf.name},
    )
    db.commit()
    db.refresh(wf)
    return wf


@router.get("/skills", response_model=list[SkillOut])
def list_skills(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    return db.query(Skill).all()


@router.get("/rule-configs", response_model=list[RuleConfigOut])
def list_rules(
    business_center_id: str | None = None,
    rule_version_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    q = db.query(RuleConfig)
    if business_center_id:
        q = q.filter(RuleConfig.business_center_id == business_center_id)
    if rule_version_id:
        q = q.filter(RuleConfig.rule_version_id == rule_version_id)
    return q.all()


def _troubleshooting_preset_out() -> TroubleshootingPresetOut:
    try:
        data = load_preset()
    except FileNotFoundError:
        raise HTTPException(404, "方太排查规则预设文件缺失，请确认 backend/data/fangtai_troubleshooting_rules.json 存在")
    return TroubleshootingPresetOut(
        title=data.get("title", ""),
        source_file=data.get("source_file", ""),
        extracted_at=data.get("extracted_at"),
        total_patterns=data.get("total_patterns", 0),
        consolidated_rules=data.get("consolidated_rules", []),
    )


@router.post("/semantics/demo-seed")
def semantics_demo_seed(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """
    一键方太 POC 闭环：sample-data CSV → 数据源 → 中文映射 → 排查规则 → 本体抽取。
    供管理后台「数据语义」引导使用。
    """
    result = run_semantics_demo_seed(db, user)
    log_audit(
        db,
        user=user,
        object_type="semantics",
        object_id=IDS["business_center"],
        action="demo_seed",
        after_data=result,
    )
    db.commit()
    return result


@router.get("/rule-import/preset", response_model=TroubleshootingPresetOut)
def get_troubleshooting_preset(
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    return _troubleshooting_preset_out()


@router.get("/rule-configs/troubleshooting-preset", response_model=TroubleshootingPresetOut, include_in_schema=False)
def get_troubleshooting_preset_legacy(
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """兼容旧前端路径（须在 /rule-configs/{rule_id} 之前注册）。"""
    return _troubleshooting_preset_out()


@router.post("/rule-import/apply", response_model=RuleImportResultOut)
def apply_troubleshooting_preset(
    body: ApplyTroubleshootingPresetIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    bc_id = body.business_center_id or IDS["business_center"]
    result = apply_preset(
        db,
        rule_version_id=body.rule_version_id,
        business_center_id=bc_id,
        user=user,
    )
    return RuleImportResultOut(**result)


@router.post("/rule-import/bind-ontology", response_model=RuleImportResultOut)
def bind_troubleshooting_rules_to_ontology(
    body: ApplyTroubleshootingPresetIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """将当前规则版本同步绑定到「数据语义 → 领域规则」（与规则引擎 RuleConfig 一一对应）。"""
    bc_id = body.business_center_id or IDS["business_center"]
    ontology_bind = bind_rules_to_ontology(
        db,
        rule_version_id=body.rule_version_id,
        business_center_id=bc_id,
        user=user,
    )
    log_audit(
        db,
        user=user,
        object_type="ontology",
        object_id="domain_rule",
        action="bind_rule_engine",
        after_data=ontology_bind,
    )
    return RuleImportResultOut(
        total_patterns=0,
        applied=ontology_bind.get("bindings", []),
        ontology_bind=ontology_bind,
    )


@router.post("/rule-import/bind-workflow", response_model=RuleImportResultOut)
def bind_troubleshooting_rules_to_workflow(
    body: ApplyTroubleshootingPresetIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """将当前规则版本同步到 Workflow「差异识别」节点（已应用规则后可单独执行）。"""
    bc_id = body.business_center_id or IDS["business_center"]
    workflow_bind = bind_rules_to_workflow_detect(
        db,
        business_center_id=bc_id,
        rule_version_id=body.rule_version_id,
    )
    if not workflow_bind:
        raise HTTPException(400, "未找到 Workflow 或「差异识别」节点，请确认业务中心已关联流程")
    log_audit(
        db,
        user=user,
        object_type="workflow",
        object_id=workflow_bind["workflow_id"],
        action="bind_detect_rules",
        after_data=workflow_bind,
    )
    return RuleImportResultOut(
        total_patterns=0,
        applied=workflow_bind.get("rule_bindings", []),
        workflow_bind=workflow_bind,
    )


@router.post("/rule-import/excel", response_model=RuleImportResultOut)
async def import_troubleshooting_excel(
    file: UploadFile = File(...),
    rule_version_id: str = Form(...),
    business_center_id: str = Form(IDS["business_center"]),
    apply: bool = Form(True),
    use_ai: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "请上传 Excel 文件（.xlsx）")
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过 15MB")
    import io

    stream = io.BytesIO(content)
    if apply:
        result = await import_excel_and_apply(
            db,
            stream=stream,
            filename=file.filename,
            rule_version_id=rule_version_id,
            business_center_id=business_center_id,
            user=user,
            use_ai=use_ai,
        )
        return RuleImportResultOut(**result)
    preview = import_excel_preview(stream, file.filename)
    return RuleImportResultOut(
        total_patterns=preview.get("total_patterns", 0),
        source_file=preview.get("source_file"),
        ai_enhanced=False,
        applied=[],
        consolidated_rules=preview.get("consolidated_rules", []),
    )


@router.get("/rule-configs/{rule_id}", response_model=RuleConfigOut)
def get_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    rule = db.query(RuleConfig).filter(RuleConfig.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "规则不存在")
    return rule


@router.patch("/rule-configs/{rule_id}", response_model=RuleConfigOut)
def update_rule(
    rule_id: str,
    body: RuleConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    rule = db.query(RuleConfig).filter(RuleConfig.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "规则不存在")
    before = {
        "name": rule.name,
        "condition": rule.condition,
        "severity": rule.severity,
        "enabled": rule.enabled,
        "threshold": rule.threshold,
        "params": rule.params,
    }
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(rule, key, value)
    log_audit(
        db,
        user=user,
        object_type="rule_config",
        object_id=rule.id,
        action="update_rule_config",
        before_data=before,
        after_data=updates,
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/mapping-configs", response_model=list[MappingConfigOut])
def list_mappings(
    business_center_id: str = IDS["business_center"],
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    return db.query(MappingConfig).filter(MappingConfig.business_center_id == business_center_id).all()


# ── 数据源管理 ──────────────────────────────────────────────

@router.get("/datasources", response_model=list[DataSourceOut])
def list_datasources(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    return db.query(DataSource).order_by(DataSource.created_at.desc()).all()


@router.post("/datasources/upload", response_model=DataSourceOut)
async def upload_datasource(
    name: str = Form(...),
    system_type: str = Form("sap"),
    side: str = Form("business"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    from app.services.mapping_engine import detect_data_profile
    from app.services.data_loader import load_dataframe

    ds_id = str(uuid.uuid4())
    suffix = Path(file.filename or "data.csv").suffix or ".csv"
    dest = UPLOAD_DIR / f"ds_{ds_id}{suffix}"
    content = await file.read()
    dest.write_bytes(content)

    df = load_dataframe(dest)
    profile = detect_data_profile(df)
    columns = list(df.columns.astype(str))

    ds = DataSource(
        id=ds_id,
        name=name,
        system_type=system_type,
        side=side,
        file_path=str(dest),
        detected_columns=columns,
        detected_profile=profile if profile != "unknown" else system_type,
        row_count=len(df),
    )
    db.add(ds)
    log_audit(db, user=user, object_type="datasource", object_id=ds_id, action="upload",
              detail={"name": name, "columns": len(columns), "rows": len(df), "profile": ds.detected_profile})
    db.commit()
    db.refresh(ds)
    return ds


@router.post("/datasources/import-excel")
async def import_datasources_from_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """
    上传方太 POC 类 Excel（如「收入对账-POC数据(1).xlsx」）：
    按 Sheet 拆成多张数据源，Sheet 名即表名（SAP结算行明细、DMS收入台账明细等）。
    """
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过 25MB")
    try:
        result = import_excel_workbook(db, content, file.filename or "workbook.xlsx")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Excel 解析失败: {exc}") from exc

    log_audit(
        db,
        user=user,
        object_type="datasource",
        object_id="batch",
        action="import_excel",
        detail={
            "filename": result.get("filename"),
            "sheet_count": result.get("sheet_count"),
            "imported_count": len(result.get("imported") or []),
            "skipped_count": len(result.get("skipped") or []),
            "message": result.get("message"),
        },
    )
    db.commit()
    return result


@router.get("/datasources/preview/{ds_id}")
def preview_datasource(
    ds_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
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
    try:
        head = df.head(min(max(limit, 1), 200))
        rows: list[dict] = []
        for record in head.to_dict(orient="records"):
            rows.append({str(k): json_safe_cell(v) for k, v in record.items()})
        columns = [str(c) for c in df.columns]
    except Exception as exc:
        raise HTTPException(500, f"数据预览失败: {exc}") from exc
    return {
        "id": ds.id,
        "name": ds.name,
        "columns": columns,
        "total_rows": int(len(df)),
        "rows": rows,
    }


@router.delete("/datasources/{ds_id}")
def delete_datasource(
    ds_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    ds = db.query(DataSource).filter(DataSource.id == ds_id).first()
    if not ds:
        raise HTTPException(404, "数据源不存在")
    fpath = Path(ds.file_path)
    if fpath.exists():
        fpath.unlink()
    db.delete(ds)
    log_audit(db, user=user, object_type="datasource", object_id=ds_id, action="delete",
              detail={"name": ds.name})
    db.commit()
    return {"ok": True}


@router.get("/ontology-mapping", response_model=OntologyMappingOut)
def get_ontology_mapping(
    business_center_id: str = IDS["business_center"],
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """数据源、四步映射场景与字段对照（配置驱动，MVP 只读展示）。"""
    path = CONFIG_DIR / "revenue_ontology_mapping.yaml"
    if not path.exists():
        raise HTTPException(404, "未找到本体映射配置 revenue_ontology_mapping.yaml")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    db_maps = db.query(MappingConfig).filter(MappingConfig.business_center_id == business_center_id).all()
    return OntologyMappingOut(
        scenario_title=cfg.get("scenario_title", ""),
        scenario_summary=cfg.get("scenario_summary", ""),
        mvp_note=cfg.get("mvp_note", ""),
        data_sources=[DataSourceItemOut(**ds) for ds in cfg.get("data_sources", [])],
        raw_examples=[RawExampleOut(**ex) for ex in cfg.get("raw_examples", [])],
        pipeline_steps=[PipelineStepOut(**s) for s in cfg.get("pipeline_steps", [])],
        field_mappings=[RevenueFieldMappingOut(**m) for m in cfg.get("field_mappings", [])],
        object_types=[ObjectTypeOut(**o) for o in cfg.get("object_types", [])],
        relationships=[RelationshipOut(**r) for r in cfg.get("relationships", [])],
        match_rules=[MatchRuleOut(**r) for r in cfg.get("match_rules", [])],
        demo_field_mappings=cfg.get("demo_field_mappings", []),
        db_mapping_configs=[MappingConfigOut.model_validate(m) for m in db_maps],
    )


@router.put("/field-mappings", response_model=list[MappingConfigOut])
def save_field_mappings(
    body: FieldMappingsSave,
    business_center_id: str = IDS["business_center"],
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """保存字段对照表到 mapping_configs，任务执行时由映射引擎读取。"""
    import json

    biz = fin = None
    if body.business_datasource_id and body.finance_datasource_id:
        biz = db.query(DataSource).filter(DataSource.id == body.business_datasource_id).first()
        fin = db.query(DataSource).filter(DataSource.id == body.finance_datasource_id).first()
        if not biz or not fin:
            raise HTTPException(400, "所选业务侧或财务侧数据源不存在")

    try:
        db.query(MappingConfig).filter(MappingConfig.business_center_id == business_center_id).delete()
        out: list[MappingConfig] = []
        for row in body.rows:
            spec = json.dumps(
                {
                    "label": row.unified_label or row.unified_field,
                    "finance_column": row.finance_column,
                    "bank_column": row.bank_column,
                    "transform": row.transform or "rename",
                },
                ensure_ascii=False,
            )
            mc = MappingConfig(
                id=str(uuid.uuid4()),
                business_center_id=business_center_id,
                source_field=(row.business_column or "").strip(),
                target_field=row.unified_field,
                transform_rule=spec,
                version=1,
                enabled=row.enabled,
            )
            db.add(mc)
            out.append(mc)
        db.flush()
        if biz and fin:
            validation = validate_datasource_pair(db, business_center_id, biz, fin)
            if not validation.ready:
                db.rollback()
                raise HTTPException(
                    400,
                    f"表对未通过列校验，未保存：{validation.message}。"
                    "请点「AI 映射」按当前表实际列名生成对照后再保存。",
                )
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"保存字段映射失败: {exc}")
    invalidate_mapping_cache()

    binding_detail: dict = {}
    if biz and fin:
        entry = set_mapping_binding(
            business_center_id,
            business_datasource_id=body.business_datasource_id,
            finance_datasource_id=body.finance_datasource_id,
            mapping_row_count=len(out),
            validated=True,
            message="映射校验通过",
        )
        binding_detail = {"binding": entry, "mapping_ready": True}

    log_audit(
        db,
        user=user,
        object_type="mapping_config",
        object_id=business_center_id,
        action="save_field_mappings",
        detail={"count": len(out), **binding_detail},
    )
    return out


@router.post("/auto-map-fields")
async def auto_map_fields(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """AI 自动推荐字段映射：根据业务侧/财务侧列名，生成统一字段、中文标签和翻译规则。"""
    biz_cols = body.get("business_columns", [])
    fin_cols = body.get("finance_columns", [])
    if not biz_cols and not fin_cols:
        raise HTTPException(400, "至少提供一侧列名")

    from app.services.auto_mapper import auto_map, _heuristic_map
    try:
        rows = await auto_map(biz_cols, fin_cols)
    except Exception:
        rows = _heuristic_map(biz_cols, fin_cols)
    return {"rows": rows}


@router.post("/mapping-engine/dry-run", response_model=MappingDryRunOut)
def mapping_engine_dry_run(
    dataset_id: str | None = "dataset_fangtai_real",
    business_datasource_id: str | None = None,
    finance_datasource_id: str | None = None,
    business_center_id: str = IDS["business_center"],
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """试运行映射：可指定已上传数据源 ID 或演示集 ID。"""
    biz_path: Path | None = None
    fin_path: Path | None = None

    if business_datasource_id and finance_datasource_id:
        biz_ds = db.query(DataSource).filter(DataSource.id == business_datasource_id).first()
        fin_ds = db.query(DataSource).filter(DataSource.id == finance_datasource_id).first()
        if not biz_ds or not fin_ds:
            raise HTTPException(404, "数据源不存在")
        biz_path = Path(biz_ds.file_path)
        fin_path = Path(fin_ds.file_path)
    else:
        manifest_path = SAMPLE_ROOT / "manifest.json"
        if not manifest_path.exists():
            raise HTTPException(404, "未找到 sample-data/manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        ds = next((d for d in manifest.get("datasets", []) if d["id"] == (dataset_id or "dataset_fangtai_real")), None)
        if not ds:
            raise HTTPException(404, f"演示集 {dataset_id} 不存在")
        files = ds.get("files", {})
        biz_path = SAMPLE_ROOT / files["business"]
        fin_path = SAMPLE_ROOT / files["finance"]

    if not biz_path or not fin_path or not biz_path.exists() or not fin_path.exists():
        raise HTTPException(404, "数据文件缺失")

    registry = MappingRegistry.load(db, business_center_id)
    biz, biz_prof = load_and_translate_file(biz_path, "business", registry)
    fin, fin_prof = load_and_translate_file(fin_path, "finance", registry)
    report = run_mapping_pipeline(biz, fin, business_profile=biz_prof, finance_profile=fin_prof, registry=registry)
    return MappingDryRunOut(
        **report,
        sample_business=biz[:5],
        sample_finance=fin[:5],
    )


@router.post("/rule-configs/new-version")
def create_rule_version(
    body: RuleVersionCreate,
    business_center_id: str = IDS["business_center"],
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    bc = db.query(BusinessCenter).filter(BusinessCenter.id == business_center_id).first()
    if not bc:
        raise HTTPException(404, "业务中心不存在")
    max_v = db.query(RuleVersion).filter(RuleVersion.business_center_id == business_center_id).count()
    new_rv_id = str(uuid.uuid4())
    rv = RuleVersion(
        id=new_rv_id,
        business_center_id=business_center_id,
        version=max_v + 1,
        status="draft",
        description=body.description,
        source_case_id=body.source_case_id,
    )
    db.add(rv)
    overrides = {o.rule_type: o for o in (body.rule_overrides or [])}
    applied_changes: list[dict] = []
    old_rules = db.query(RuleConfig).filter(RuleConfig.rule_version_id == bc.rule_version_id).all()
    for r in old_rules:
        ov = overrides.get(r.rule_type)
        new_enabled = r.enabled if (ov is None or ov.enabled is None) else ov.enabled
        new_threshold = (getattr(r, "threshold", 0) or 0) if (ov is None or ov.threshold is None) else ov.threshold
        new_severity = r.severity if (ov is None or ov.severity is None) else ov.severity
        if ov is not None:
            applied_changes.append({
                "rule_type": r.rule_type,
                "enabled": new_enabled,
                "threshold": new_threshold,
                "severity": new_severity,
            })
        db.add(
            RuleConfig(
                id=str(uuid.uuid4()),
                business_center_id=business_center_id,
                rule_version_id=new_rv_id,
                rule_type=r.rule_type,
                name=r.name,
                condition=body.reusable_rule_suggestion or r.condition,
                severity=new_severity,
                enabled=new_enabled,
                threshold=new_threshold,
                params=r.params,
                version=max_v + 1,
            )
        )
    bc.rule_version_id = new_rv_id
    bc.status = BusinessCenterStatus.TESTING.value
    log_audit(
        db,
        user=user,
        object_type="rule_version",
        object_id=new_rv_id,
        action="create_rule_version",
        after_data={
            "version": rv.version,
            "suggestion": body.reusable_rule_suggestion,
            "rule_overrides": applied_changes,
        },
    )
    db.commit()
    return {"rule_version_id": new_rv_id, "version": rv.version, "rule_overrides": applied_changes}


@router.get("/cases", response_model=list[CaseAssetOut])
def list_cases(
    knowledge_base_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    q = db.query(CaseAsset)
    if knowledge_base_id:
        if knowledge_base_id == "kb-fangtai-cases":
            q = q.filter(
                (CaseAsset.knowledge_base_id == knowledge_base_id)
                | (CaseAsset.knowledge_base_id.is_(None))
                | (CaseAsset.source_kind == "diff_archive")
            )
        else:
            q = q.filter(CaseAsset.knowledge_base_id == knowledge_base_id)
    return q.order_by(CaseAsset.created_at.desc()).all()


@router.post("/knowledge/upload", response_model=KnowledgeUploadResultOut)
async def upload_knowledge_excel(
    file: UploadFile = File(...),
    knowledge_base_id: str = Form("revenue_reconciliation"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    """上传 Excel 到指定知识库，自动解析为可检索条目（供 Agent 知识库检索）。"""
    from app.services.knowledge_import_service import import_excel_to_knowledge

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "请上传 Excel 文件（.xlsx）")
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(400, "文件不能超过 15MB")

    dest = UPLOAD_DIR / f"kb_{knowledge_base_id}_{uuid.uuid4().hex[:8]}_{Path(file.filename).name}"
    dest.write_bytes(content)

    import io

    try:
        result = import_excel_to_knowledge(
            db,
            stream=io.BytesIO(content),
            filename=file.filename,
            knowledge_base_id=knowledge_base_id,
            user=user,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return KnowledgeUploadResultOut(**result)


@router.get("/audit-logs", response_model=list[AuditLogOut])
def list_audit_logs(
    object_type: str | None = None,
    object_id: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    q = db.query(AuditLog)
    if object_type:
        q = q.filter(AuditLog.object_type == object_type)
    if object_id:
        q = q.filter(AuditLog.object_id == object_id)
    return q.order_by(AuditLog.created_at.desc()).limit(limit).all()


@router.get("/skill-invocations", response_model=list[SkillInvocationOut])
def admin_list_skill_invocations(
    task_id: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    from app.models import SkillInvocation

    q = db.query(SkillInvocation)
    if task_id:
        q = q.filter(SkillInvocation.task_id == task_id)
    return q.order_by(SkillInvocation.started_at.desc()).limit(limit).all()


@router.get("/skill-registry")
def skill_registry_status(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    from app.services.skill_registry import AUTOMATED_SKILLS, registered_codes

    skills = db.query(Skill).all()
    return {
        "registered_codes": registered_codes(),
        "automated_skills": sorted(AUTOMATED_SKILLS),
        "skills": [
            {"code": s.code, "name": s.name, "type": s.type, "version": s.version, "status": s.status}
            for s in skills
        ],
    }


@router.get("/agent-configs")
def list_agents(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    return db.query(AgentConfig).all()


@router.get("/llm-config", response_model=LlmConfigOut)
def get_llm_config(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    from app.services.llm_config_service import ensure_llm_config, get_effective_llm_config, llm_config_to_out

    row = ensure_llm_config(db)
    effective = get_effective_llm_config(db)
    return llm_config_to_out(row, effective)


@router.put("/llm-config", response_model=LlmConfigOut)
def update_llm_config(
    body: LlmConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    from app.services.llm_config_service import get_effective_llm_config, llm_config_to_out, update_llm_config as save_llm

    payload = body.model_dump(exclude_unset=True)
    row, effective = save_llm(db, payload, user.id)
    log_audit(
        db,
        user=user,
        object_type="llm_config",
        object_id=row.id,
        action="update",
        detail={
            "model": row.model,
            "use_mock": row.use_mock,
            "api_key_set": bool(effective.api_key),
            "effective_mode": effective.model if not effective.use_mock else "mock-ai",
        },
    )
    db.commit()
    return llm_config_to_out(row, effective)


@router.post("/llm-config/test", response_model=LlmConfigTestResult)
async def test_llm_config(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER)),
):
    from app.services.llm_config_service import get_effective_llm_config, test_llm_connection

    cfg = get_effective_llm_config(db)
    result = await test_llm_connection(cfg)
    log_audit(
        db,
        user=user,
        object_type="llm_config",
        object_id="platform-default",
        action="test_connection",
        detail={"ok": result.get("ok"), "mode": result.get("mode"), "model": result.get("model")},
    )
    db.commit()
    return result


@demo_router.get("", response_model=list[DemoDatasetOut])
def list_demo_datasets(user: User = Depends(get_current_user)):
    manifest_path = SAMPLE_ROOT / "manifest.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        DemoDatasetOut(
            id=d["id"],
            name=d["name"],
            description=d["description"],
            expected=d.get("expected"),
        )
        for d in manifest.get("datasets", [])
    ]
