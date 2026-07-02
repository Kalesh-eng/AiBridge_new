"""
main.py — AIBridge FastAPI backend (v1.4.2).

v1.4.2: Failed extract runs are now SAVED to the database so they appear on the Logs page.
v1.4.1: GET /connector/{id}/schemas — list schemas using saved connector
v1.4: TARGET connection + COLUMN picker + custom schemas + cross-DB pandas transfer.
v1.3: Edit connectors
v1.2: Dynamic source schema (per connector)
Plus: HIL gates, Recovery Agent, SQL Safety Guard.
"""

import os
import json
import duckdb
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from auth              import get_current_user, signup, login, get_user_workspace
from nlm_engine        import (run_full_pipeline, generate_schema_evolution,
                                run_phase_1_model_design, run_phase_2_sql_generation)
from connectors        import PostgresConnector, FileConnector
from database          import (get_db, setup_database, Connector, Pipeline,
                                PipelineRun, ApprovalQueue, Workspace)
from pipeline_executor import (
    extract_to_staging, execute_warehouse_scripts,
    list_all_tables_by_schema, get_table_preview,
    get_full_schema_for_ai, list_schemas, list_columns_for_tables
)
from scheduler import (start_scheduler, stop_scheduler,
                        add_pipeline_job, remove_pipeline_job,
                        list_jobs, run_pipeline_now)
from sql_safety import check_pipeline_safety, check_sql_safety

load_dotenv()

app = FastAPI(title="AIBridge API", version="1.4.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    setup_database()
    start_scheduler()
    print("[AIBridge] API started (v1.4.2 — failed runs are saved to logs)")


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()


# ── Request models ────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: str; password: str; full_name: str

class LoginRequest(BaseModel):
    email: str; password: str

class PipelineRequest(BaseModel):
    source_description:    str
    raw_schema:            str
    business_requirements: str
    connector_id:          str = ""
    staging_schema:        str = "staging"
    warehouse_schema:      str = "warehouse"

class SavePipelineRequest(BaseModel):
    name: str
    artifacts: dict
    schedule: str = "manual"
    source_description: str = ""
    raw_schema: str = ""
    business_requirements: str = ""
    connector_id: str = ""
    source_tables: list = []
    source_schema: str = "raw"
    source_columns: dict = {}
    target_connector_id: str = ""
    staging_schema: str = "staging"
    warehouse_schema: str = "warehouse"

class ConnectorSaveRequest(BaseModel):
    name: str; connector_type: str = "postgres"; role: str = "both"
    host: str; port: int = 5433; database_name: str
    username: str; password: str
    source_schema: str = "raw"

class ConnectorUpdateRequest(BaseModel):
    name:          Optional[str] = None
    role:          Optional[str] = None
    host:          Optional[str] = None
    port:          Optional[int] = None
    database_name: Optional[str] = None
    username:      Optional[str] = None
    password:      Optional[str] = None
    source_schema: Optional[str] = None

class ColumnListRequest(BaseModel):
    table_names: List[str]

class ScheduleRequest(BaseModel):
    pipeline_id: str; pipeline_name: str
    sql_scripts: list; schedule: str

class PostgresConnectRequest(BaseModel):
    host: str; port: int = 5433; database: str
    username: str; password: str

class SQLRunRequest(BaseModel):
    sql: str; connector_id: str = ""


class UpdateArtifactsRequest(BaseModel):
    artifacts: dict


class RegenerateRequest(BaseModel):
    pipeline_id: str
    new_requirements: str


class ExecuteOverrideRequest(BaseModel):
    tables_override: list = []

class SchemaEvolutionRequest(BaseModel):
    table_name: str; existing_columns: list
    new_column: str; column_type: str
    user_instruction: str

class ProviderRequest(BaseModel):
    provider: str; api_key: str = ""

class NLToSQLRequest(BaseModel):
    question: str; connector_id: str = ""

class ApproveModelRequest(BaseModel):
    approval_id:  str
    edited_model: dict = None
    comments:     str = ""

class ApproveSQLRequest(BaseModel):
    approval_id:              str
    edited_scripts:           list = None
    comments:                 str  = ""
    i_understand_destructive: bool = False

class RejectRequest(BaseModel):
    approval_id: str
    comments:    str
    regenerate:  bool = True

class HILModeRequest(BaseModel):
    mode: str


def _cfg(c: Connector) -> dict:
    return {"host": c.host, "port": c.port, "database": c.database_name,
            "username": c.username, "password": c.password}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "AIBridge API is running", "version": "1.4.2",
            "features": ["HIL", "Recovery Agent", "SQL Safety Guard",
                         "Dynamic Schema", "Edit Connectors",
                         "Target Connection", "Column Picker", "Schema Dropdown",
                         "Failed Runs in Logs"]}

@app.get("/health")
def health():
    return {"status": "ok", "scheduler": "running",
            "timestamp": datetime.utcnow().isoformat()}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/auth/signup")
def auth_signup(req: SignupRequest, db: Session = Depends(get_db)):
    return signup(req.email, req.password, req.full_name, db)

@app.post("/auth/login")
def auth_login(req: LoginRequest, db: Session = Depends(get_db)):
    return login(req.email, req.password, db)

@app.post("/auth/logout")
def auth_logout(current_user=Depends(get_current_user)):
    return {"success": True, "message": "Logged out"}

@app.get("/auth/me")
def auth_me(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    workspace = get_user_workspace(current_user.id, db)
    return {"id": current_user.id, "email": current_user.email,
            "full_name": current_user.full_name, "workspace": workspace}


# ── Connector Registry ────────────────────────────────────────────────────────

@app.post("/connector/save")
def save_connector(req: ConnectorSaveRequest,
                   current_user=Depends(get_current_user),
                   db: Session = Depends(get_db)):
    workspace = get_user_workspace(current_user.id, db)
    connector = Connector(
        workspace_id=workspace.get("id"), name=req.name,
        connector_type=req.connector_type, role=req.role,
        host=req.host, port=req.port, database_name=req.database_name,
        username=req.username, password=req.password,
        source_schema=req.source_schema or "raw"
    )
    db.add(connector); db.commit(); db.refresh(connector)
    return {"success": True, "message": f"Connection '{req.name}' saved",
            "connector": {"id": connector.id, "name": connector.name,
                          "role": connector.role, "host": connector.host,
                          "port": connector.port, "database_name": connector.database_name,
                          "source_schema": connector.source_schema}}

@app.put("/connector/{connector_id}")
def update_connector(connector_id: str, req: ConnectorUpdateRequest,
                     current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c:
        raise HTTPException(404, "Connector not found")

    if req.name          is not None: c.name          = req.name
    if req.role          is not None: c.role          = req.role
    if req.host          is not None: c.host          = req.host
    if req.port          is not None: c.port          = req.port
    if req.database_name is not None: c.database_name = req.database_name
    if req.username      is not None: c.username      = req.username
    if req.password:                  c.password      = req.password
    if req.source_schema is not None: c.source_schema = req.source_schema

    db.commit(); db.refresh(c)
    return {"success": True, "message": f"Connection '{c.name}' updated",
            "connector": {"id": c.id, "name": c.name, "role": c.role,
                          "host": c.host, "port": c.port,
                          "database_name": c.database_name,
                          "username": c.username,
                          "source_schema": c.source_schema}}

@app.get("/connector/list")
def list_connectors(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    workspace = get_user_workspace(current_user.id, db)
    connectors = db.query(Connector).filter(
        Connector.workspace_id == workspace.get("id"),
        Connector.is_active == True
    ).order_by(Connector.created_at.desc()).all()
    return {"success": True, "connectors": [
        {"id": c.id, "name": c.name, "connector_type": c.connector_type,
         "role": c.role, "host": c.host, "port": c.port,
         "database_name": c.database_name, "username": c.username,
         "source_schema": c.source_schema or "raw",
         "created_at": str(c.created_at)} for c in connectors
    ]}

@app.delete("/connector/{connector_id}")
def delete_connector(connector_id: str, current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")
    c.is_active = False; db.commit()
    return {"success": True, "message": "Connector deleted"}

@app.post("/connector/postgres/test")
def test_postgres(req: PostgresConnectRequest, current_user=Depends(get_current_user)):
    conn = PostgresConnector(req.host, req.port, req.database, req.username, req.password)
    return conn.connect()

@app.post("/connector/postgres/schemas")
def get_postgres_schemas(req: PostgresConnectRequest, current_user=Depends(get_current_user)):
    return list_schemas({"host": req.host, "port": req.port, "database": req.database,
                         "username": req.username, "password": req.password})

@app.post("/connector/postgres/schema")
def get_postgres_schema(req: PostgresConnectRequest, current_user=Depends(get_current_user)):
    conn = PostgresConnector(req.host, req.port, req.database, req.username, req.password)
    result = conn.get_schema()
    if result["success"]: result["nlm_schema"] = conn.format_schema_for_nlm()
    return result

@app.get("/connector/{connector_id}/schemas")
def get_connector_schemas(connector_id: str,
                          current_user=Depends(get_current_user),
                          db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c:
        raise HTTPException(404, "Connector not found")
    return list_schemas(_cfg(c))

@app.get("/connector/{connector_id}/tables")
def get_connector_tables(connector_id: str, current_user=Depends(get_current_user),
                         db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")
    return list_all_tables_by_schema(_cfg(c), source_schema=c.source_schema or "raw")

@app.post("/connector/{connector_id}/columns")
def get_columns_for_tables(connector_id: str, req: ColumnListRequest,
                           current_user=Depends(get_current_user),
                           db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")
    return list_columns_for_tables(_cfg(c),
                                   source_schema=c.source_schema or "raw",
                                   table_names=req.table_names)

@app.get("/connector/{connector_id}/preview/{schema_name}/{table_name}")
def preview_table(connector_id: str, schema_name: str, table_name: str,
                  current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")
    real_schema = schema_name
    if schema_name == "raw" and (c.source_schema or "raw") != "raw":
        real_schema = c.source_schema
    return get_table_preview(f'"{real_schema}"."{table_name}"', _cfg(c))

@app.get("/connector/{connector_id}")
def get_connector(connector_id: str, current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c:
        raise HTTPException(404, "Connector not found")
    return {"success": True, "connector": {
        "id": c.id, "name": c.name, "connector_type": c.connector_type,
        "role": c.role, "host": c.host, "port": c.port,
        "database_name": c.database_name, "username": c.username,
        "source_schema": c.source_schema or "raw"
    }}

@app.post("/connector/file/upload")
async def upload_file(file: UploadFile = File(...), current_user=Depends(get_current_user)):
    import tempfile, shutil
    try:
        suffix = ".csv" if file.filename.endswith(".csv") else ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
        duckdb_path = os.getenv("DUCKDB_PATH", "./aibridge.duckdb")
        fc = FileConnector(duckdb_path)
        table_name = file.filename.replace(".csv","").replace(".xlsx","")\
                                   .replace(" ","_").lower()
        result = fc.load_csv(tmp_path, table_name) if suffix == ".csv" \
                 else fc.load_excel(tmp_path, table_name)
        os.unlink(tmp_path)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── ETL Agent — Legacy ────────────────────────────────────────────────────────

@app.post("/pipeline/run")
def run_pipeline(req: PipelineRequest, current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    try:
        connector_config = None
        source_schema = "raw"
        if req.connector_id:
            c = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if c:
                connector_config = _cfg(c)
                source_schema = c.source_schema or "raw"
        result = run_full_pipeline(req.source_description, req.raw_schema,
                                    req.business_requirements, connector_config,
                                    source_schema)
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── HIL Endpoints ─────────────────────────────────────────────────────────────

@app.post("/pipeline/run-phase-1")
def run_phase_1(req: PipelineRequest,
                current_user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    try:
        workspace = get_user_workspace(current_user.id, db)
        wid       = workspace.get("id")

        connector_config = None
        source_schema = "raw"
        if req.connector_id:
            c = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if c:
                connector_config = _cfg(c)
                source_schema = c.source_schema or "raw"

        result = run_phase_1_model_design(
            req.source_description, req.raw_schema,
            req.business_requirements, connector_config, source_schema
        )

        dim_count  = len(result["data_model"].get("dimension_tables", []))
        fact_count = len(result["data_model"].get("fact_tables", []))
        rel_count  = len(result["schema_analysis"].get("relationships", []))

        approval = ApprovalQueue(
            workspace_id   = wid,
            approval_type  = "data_model",
            title          = f"Review proposed data model — {fact_count} facts, {dim_count} dims",
            description    = f"AI analyzed {len(result['schema_analysis'].get('entities', []))} tables, "
                              f"found {rel_count} relationships, designed {fact_count + dim_count} warehouse tables.",
            proposed_data  = {
                "schema_analysis": result["schema_analysis"],
                "data_model":      result["data_model"]
            },
            context = {
                "source_description":    req.source_description,
                "raw_schema":            req.raw_schema,
                "business_requirements": req.business_requirements,
                "connector_id":          req.connector_id,
                "source_schema":         source_schema,
                "staging_schema":        req.staging_schema,
                "warehouse_schema":      req.warehouse_schema,
                "used_profile":          result.get("used_profile", False)
            },
            status       = "pending",
            requested_by = current_user.id,
            risk_level   = "medium"
        )
        db.add(approval); db.commit(); db.refresh(approval)

        return {
            "success":      True,
            "approval_id":  approval.id,
            "phase":        "awaiting_model_approval",
            "data":         result,
            "message":      "✓ Model designed. Please review and approve to continue."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/approve-model")
def approve_model(req: ApproveModelRequest,
                  current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    try:
        approval = db.query(ApprovalQueue).filter(
            ApprovalQueue.id == req.approval_id
        ).first()
        if not approval:
            raise HTTPException(404, "Approval not found")
        if approval.status != "pending":
            raise HTTPException(400, f"Approval already {approval.status}")

        if req.edited_model:
            approval.edited_data = {"data_model": req.edited_model}
            approval.status      = "edited"
            data_model           = req.edited_model
        else:
            approval.status      = "approved"
            data_model           = approval.proposed_data["data_model"]

        approval.approved_by = current_user.id
        approval.comments    = req.comments
        approval.decided_at  = datetime.utcnow()
        db.commit()

        schema_analysis = approval.proposed_data["schema_analysis"]
        ctx             = approval.context or {}
        phase2          = run_phase_2_sql_generation(
            schema_analysis, data_model,
            staging_schema   = ctx.get("staging_schema", "staging"),
            warehouse_schema = ctx.get("warehouse_schema", "warehouse")
        )

        wid           = approval.workspace_id
        script_count  = len(phase2["sql_scripts"].get("scripts", []))

        sql_approval = ApprovalQueue(
            workspace_id   = wid,
            approval_type  = "sql_scripts",
            title          = f"Review generated SQL — {script_count} scripts to execute",
            description    = f"AI generated {script_count} SQL scripts. Review each before execution.",
            proposed_data  = {
                "schema_analysis": schema_analysis,
                "data_model":      data_model,
                "etl_mappings":    phase2["etl_mappings"],
                "sql_scripts":     phase2["sql_scripts"]
            },
            context        = approval.context,
            status         = "pending",
            requested_by   = current_user.id,
            risk_level     = "high"
        )
        db.add(sql_approval); db.commit(); db.refresh(sql_approval)

        return {
            "success":     True,
            "approval_id": sql_approval.id,
            "phase":       "awaiting_sql_approval",
            "data": {
                "schema_analysis": schema_analysis,
                "data_model":      data_model,
                "etl_mappings":    phase2["etl_mappings"],
                "sql_scripts":     phase2["sql_scripts"]
            },
            "message":     "✓ Model approved. SQL generated. Please review before execution."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/approve-sql")
def approve_sql(req: ApproveSQLRequest,
                current_user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    try:
        approval = db.query(ApprovalQueue).filter(
            ApprovalQueue.id == req.approval_id
        ).first()
        if not approval:
            raise HTTPException(404, "Approval not found")
        if approval.status != "pending":
            raise HTTPException(400, f"Approval already {approval.status}")

        data = dict(approval.proposed_data)
        if req.edited_scripts:
            data["sql_scripts"] = {"scripts": req.edited_scripts}

        scripts = data["sql_scripts"].get("scripts", [])

        safety = check_pipeline_safety(
            scripts, allow_destructive=req.i_understand_destructive
        )

        if safety["blocked"]:
            return {
                "success":     False,
                "blocked":     True,
                "data":        data,
                "violations":  safety["violations"],
                "warnings":    safety["warnings"],
                "per_script":  safety["per_script"],
                "message":     safety["message"],
                "hint":        "To override and proceed anyway, re-submit with i_understand_destructive=true"
            }

        if req.edited_scripts:
            approval.edited_data = {"sql_scripts": req.edited_scripts}
            approval.status      = "edited"
        else:
            approval.status      = "approved"

        approval.approved_by = current_user.id
        approval.comments    = req.comments
        approval.decided_at  = datetime.utcnow()
        db.commit()

        return {
            "success":  True,
            "blocked":  False,
            "data":     data,
            "warnings": safety["warnings"],
            "override_used": req.i_understand_destructive,
            "message":  ("✓ SQL approved (override active)" if req.i_understand_destructive
                         else "✓ SQL approved. You can now save and execute the pipeline.")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/reject")
def reject_approval(req: RejectRequest,
                    current_user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    try:
        approval = db.query(ApprovalQueue).filter(
            ApprovalQueue.id == req.approval_id
        ).first()
        if not approval:
            raise HTTPException(404, "Approval not found")
        approval.status      = "rejected"
        approval.approved_by = current_user.id
        approval.comments    = req.comments
        approval.decided_at  = datetime.utcnow()
        db.commit()
        return {"success": True, "message": "Approval rejected.",
                "should_regenerate": req.regenerate}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/approvals/pending")
def list_pending_approvals(current_user=Depends(get_current_user),
                           db: Session = Depends(get_db)):
    workspace = get_user_workspace(current_user.id, db)
    approvals = db.query(ApprovalQueue).filter(
        ApprovalQueue.workspace_id == workspace.get("id"),
        ApprovalQueue.status       == "pending"
    ).order_by(ApprovalQueue.created_at.desc()).all()
    return {"success": True, "approvals": [
        {"id": a.id, "approval_type": a.approval_type, "title": a.title,
         "description": a.description, "risk_level": a.risk_level,
         "created_at": str(a.created_at)} for a in approvals
    ]}


@app.get("/approvals/history")
def list_all_approvals(current_user=Depends(get_current_user),
                       db: Session = Depends(get_db), limit: int = 50):
    workspace = get_user_workspace(current_user.id, db)
    approvals = db.query(ApprovalQueue).filter(
        ApprovalQueue.workspace_id == workspace.get("id")
    ).order_by(ApprovalQueue.created_at.desc()).limit(limit).all()
    return {"success": True, "approvals": [
        {"id": a.id, "approval_type": a.approval_type, "title": a.title,
         "description": a.description, "status": a.status,
         "risk_level": a.risk_level, "comments": a.comments,
         "created_at": str(a.created_at),
         "decided_at": str(a.decided_at) if a.decided_at else None}
        for a in approvals
    ]}


@app.get("/approvals/{approval_id}")
def get_approval(approval_id: str,
                 current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    approval = db.query(ApprovalQueue).filter(
        ApprovalQueue.id == approval_id
    ).first()
    if not approval:
        raise HTTPException(404, "Approval not found")
    return {
        "success": True, "id": approval.id,
        "approval_type": approval.approval_type, "title": approval.title,
        "description": approval.description,
        "proposed_data": approval.proposed_data,
        "edited_data": approval.edited_data,
        "context": approval.context, "status": approval.status,
        "risk_level": approval.risk_level, "comments": approval.comments,
        "created_at": str(approval.created_at),
        "decided_at": str(approval.decided_at) if approval.decided_at else None
    }


@app.post("/workspace/hil-mode")
def set_hil_mode(req: HILModeRequest,
                 current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    if req.mode not in ["full_auto", "balanced", "strict"]:
        raise HTTPException(400, "Invalid mode")
    workspace = get_user_workspace(current_user.id, db)
    ws = db.query(Workspace).filter(Workspace.id == workspace.get("id")).first()
    if ws:
        ws.hil_mode = req.mode
        db.commit()
    return {"success": True, "hil_mode": req.mode}


@app.get("/workspace/hil-mode")
def get_hil_mode(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    workspace = get_user_workspace(current_user.id, db)
    ws = db.query(Workspace).filter(Workspace.id == workspace.get("id")).first()
    return {"success": True, "hil_mode": ws.hil_mode if ws else "balanced"}


# ── Pipeline Save / List / Execute ────────────────────────────────────────────

@app.post("/pipeline/update-artifacts/{pipeline_id}")
def update_pipeline_artifacts(
    pipeline_id: str,
    req: UpdateArtifactsRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Save edited SQL scripts back to the pipeline."""

    pipeline = db.query(Pipeline).filter(
        Pipeline.id == pipeline_id
    ).first()

    if not pipeline:
        raise HTTPException(404, "Pipeline not found")

    pipeline.artifacts = req.artifacts
    db.commit()

    return {
        "success": True,
        "message": "Pipeline SQL updated successfully"
    }
@app.post("/pipeline/save")
def save_pipeline(req: SavePipelineRequest,
                  current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    try:
        workspace = get_user_workspace(current_user.id, db)
        pipeline = Pipeline(
            workspace_id=workspace.get("id"), name=req.name,
            source_desc=req.source_description, raw_schema=req.raw_schema,
            biz_requirements=req.business_requirements, schedule=req.schedule,
            artifacts=req.artifacts, connector_id=req.connector_id or None,
            source_tables=req.source_tables,
            source_schema=req.source_schema or "raw",
            source_columns=req.source_columns or {},
            target_connector_id=req.target_connector_id or None,
            staging_schema=req.staging_schema or "staging",
            warehouse_schema=req.warehouse_schema or "warehouse"
        )
        db.add(pipeline); db.commit(); db.refresh(pipeline)
        return {"success": True, "pipeline": {"id": pipeline.id, "name": pipeline.name}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/pipeline/list")
def list_pipelines(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        workspace = get_user_workspace(current_user.id, db)
        pipelines = db.query(Pipeline).filter(
            Pipeline.workspace_id == workspace.get("id")
        ).order_by(Pipeline.created_at.desc()).all()
        return {"success": True, "pipelines": [
            {"id": p.id, "name": p.name, "schedule": p.schedule,
             "is_active": p.is_active, "connector_id": p.connector_id,
             "artifacts": p.artifacts, "created_at": str(p.created_at)}
            for p in pipelines
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/pipeline/regenerate")
def regenerate_pipeline(
    req: RegenerateRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Re-run AI with new requirements for an existing pipeline."""

    pipeline = db.query(Pipeline).filter(
        Pipeline.id == req.pipeline_id
    ).first()

    if not pipeline:
        raise HTTPException(404, "Pipeline not found")

    connector_config = None
    source_schema = "raw"

    if pipeline.connector_id:
        c = db.query(Connector).filter(
            Connector.id == pipeline.connector_id
        ).first()

        if c:
            connector_config = _cfg(c)
            source_schema = c.source_schema or "raw"

    combined_requirements = (
        f"{pipeline.biz_requirements or ''}\n\nUPDATE: {req.new_requirements}"
    ).strip()

    try:
        p1 = run_phase_1_model_design(
            pipeline.source_desc or "",
            pipeline.raw_schema or "",
            combined_requirements,
            connector_config,
            source_schema
        )

        p2 = run_phase_2_sql_generation(
            p1["schema_analysis"],
            p1["data_model"],
            staging_schema=pipeline.staging_schema or "staging",
            warehouse_schema=pipeline.warehouse_schema or "warehouse"
        )

        new_artifacts = {
            "schema_analysis": p1["schema_analysis"],
            "data_model": p1["data_model"],
            "etl_mappings": p2["etl_mappings"],
            "sql_scripts": p2["sql_scripts"]
        }

        pipeline.artifacts = new_artifacts
        pipeline.biz_requirements = combined_requirements

        db.commit()

        scripts = p2["sql_scripts"].get("scripts", [])

        return {
            "success": True,
            "message": f"✓ AI regenerated {len(scripts)} scripts",
            "scripts": scripts
        }

    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/pipeline/execute/{pipeline_id}")
def execute_pipeline_endpoint(pipeline_id: str,
                              req: ExecuteOverrideRequest = None,
                              current_user=Depends(get_current_user),
                              db: Session = Depends(get_db)):
    """Execute a pipeline. Reads from SOURCE connector, writes to TARGET connector."""
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")
    if not pipeline.connector_id:
        raise HTTPException(400, "No source connector linked to this pipeline.")

    src = db.query(Connector).filter(Connector.id == pipeline.connector_id).first()
    if not src: raise HTTPException(404, "Source connector not found")

    tgt = src
    if pipeline.target_connector_id:
        t = db.query(Connector).filter(Connector.id == pipeline.target_connector_id).first()
        if t: tgt = t

    source_config    = _cfg(src)
    target_config    = _cfg(tgt)

    # CRITICAL FIX: prefer the connector's CURRENT source_schema over the pipeline's saved one.
    # This way, if the user fixes the connector schema after saving the pipeline,
    # the next execution uses the corrected value.
    source_schema    = src.source_schema or pipeline.source_schema or "raw"

    staging_schema   = pipeline.staging_schema or "staging"
    warehouse_schema = pipeline.warehouse_schema or "warehouse"
    source_columns   = pipeline.source_columns or {}

    workspace    = get_user_workspace(current_user.id, db)
    workspace_id = workspace.get("id", "")

    tables_override = req.tables_override if req else []

    source_tables = (
        tables_override
        if tables_override
        else (pipeline.source_tables or [])
    )

    if tables_override:
        print(
            f"[Pipeline] Selective refresh: only extracting {tables_override}"
        )
    if not source_tables:
        try:
            tr = list_all_tables_by_schema(source_config, source_schema=source_schema)
            raw_tables = tr.get("schemas", {}).get("raw", [])
            source_tables = [t["name"] for t in raw_tables]
            print(f"[Pipeline] Auto-discovered {len(source_tables)} tables from {source_schema}")
        except Exception as e:
            raise HTTPException(400, f"Could not auto-discover source tables: {e}")

    if not source_tables:
        raise HTTPException(400, "No source tables found.")

    all_scripts = pipeline.artifacts.get("sql_scripts", {}).get("scripts", [])
    wh_scripts  = []
    for s in all_scripts:
        label = s.get("label", "").lower()
        name  = s.get("name",  "").lower()
        if "staging" in label and name.startswith("stg_"):
            continue
        wh_scripts.append(s)

    safety = check_pipeline_safety(wh_scripts, allow_destructive=False)
    if safety["blocked"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error":      "Pipeline contains dangerous SQL — execution blocked",
                "violations": safety["violations"],
                "message":    safety["message"],
                "hint":       "Either edit the pipeline SQL or re-approve with i_understand_destructive=true"
            }
        )

    # Extract source → target staging
    print(f"[Pipeline] Starting extract: {len(source_tables)} tables → {staging_schema}")
    print(f"[Pipeline] Effective source schema: '{source_schema}' (from connector)")
    staging_result = extract_to_staging(
        source_tables, source_config, target_config,
        source_schema=source_schema, staging_schema=staging_schema,
        source_columns=source_columns
    )

    # ABORT if extract failed AND save failed run to DB so it shows up on Logs page
    if not staging_result.get("success"):
        failed_run_id = f"{pipeline_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        try:
            failed_log_lines = list(staging_result.get("logs", []))
            failed_log_lines.append("━━━ Pipeline ABORTED — extract phase failed ━━━")
            failed_log_lines.append(f"Error: {staging_result.get('error', 'unknown')}")
            failed_log_lines.append("ℹ Hint: check connector's source_schema matches where your data lives")
            run = PipelineRun(
                run_id       = failed_run_id,
                pipeline_id  = pipeline_id,
                workspace_id = workspace_id,
                status       = "failed",
                started_at   = datetime.utcnow(),
                ended_at     = datetime.utcnow(),
                rows_loaded  = 0,
                log          = "\n".join(failed_log_lines)
            )
            db.add(run); db.commit()
            print(f"[Pipeline] ✓ Failed run saved to DB: {failed_run_id}")
        except Exception as e:
            print(f"[Pipeline] ⚠ Could not save failed run: {e}")

        return {
            "success":   False,
            "staging":   staging_result,
            "warehouse": None,
            "run_id":    failed_run_id,
            "message":   f"✗ Pipeline aborted: extract phase failed — "
                         f"{staging_result.get('error', 'unknown error')}. "
                         f"Warehouse SQL was NOT executed."
        }

    print(f"[Pipeline] ✓ Extract complete — {staging_result.get('rows', 0)} rows "
          f"across {staging_result.get('tables_extracted', 0)} tables")

    exec_result = execute_warehouse_scripts(
        pipeline_id=pipeline_id, pipeline_name=pipeline.name,
        sql_scripts=wh_scripts, target_config=target_config,
        workspace_id=workspace_id, db_session=db,
        warehouse_schema=warehouse_schema, staging_schema=staging_schema
    )
    return {
        "success": exec_result["success"], "staging": staging_result,
        "warehouse": exec_result,
        "message": (f"Pipeline executed. Source: {src.name}/{source_schema} → "
                    f"Target: {tgt.name}/{warehouse_schema}.")
    }

@app.get("/pipeline/runs/{pipeline_id}")
def get_pipeline_runs(pipeline_id: str,
                     current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    try:
        runs = db.query(PipelineRun).filter(
            PipelineRun.pipeline_id == pipeline_id
        ).order_by(PipelineRun.started_at.desc()).limit(20).all()
        return {"success": True, "runs": [
            {"id": r.id, "run_id": r.run_id, "status": r.status,
             "started_at": str(r.started_at), "ended_at": str(r.ended_at),
             "rows_loaded": r.rows_loaded, "log": r.log}
            for r in runs
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pipeline/runs")
def list_all_pipeline_runs(current_user=Depends(get_current_user),
                           db: Session = Depends(get_db),
                           limit: int = 100):
    """List ALL pipeline runs across the workspace (for the Logs page)."""
    try:
        workspace = get_user_workspace(current_user.id, db)
        runs = db.query(PipelineRun, Pipeline).outerjoin(
            Pipeline, Pipeline.id == PipelineRun.pipeline_id
        ).filter(
            PipelineRun.workspace_id == workspace.get("id")
        ).order_by(PipelineRun.started_at.desc()).limit(limit).all()

        return {"success": True, "runs": [
            {
                "id":             r.PipelineRun.id,
                "run_id":         r.PipelineRun.run_id,
                "pipeline_id":    r.PipelineRun.pipeline_id,
                "pipeline_name":  r.Pipeline.name if r.Pipeline else "(deleted pipeline)",
                "status":         r.PipelineRun.status,
                "started_at":     str(r.PipelineRun.started_at) if r.PipelineRun.started_at else None,
                "ended_at":       str(r.PipelineRun.ended_at) if r.PipelineRun.ended_at else None,
                "rows_loaded":    r.PipelineRun.rows_loaded or 0,
                "log_preview":    (r.PipelineRun.log[:200] + '...') if r.PipelineRun.log and len(r.PipelineRun.log) > 200 else (r.PipelineRun.log or "")
            }
            for r in runs
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pipeline/run/{run_id}")
def get_pipeline_run_detail(run_id: str,
                            current_user=Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """Get full details of a single pipeline run including the complete log."""
    try:
        run = db.query(PipelineRun).filter(
            PipelineRun.run_id == run_id
        ).first()
        if not run:
            raise HTTPException(404, "Run not found")

        pipeline = db.query(Pipeline).filter(Pipeline.id == run.pipeline_id).first()
        pipeline_name = pipeline.name if pipeline else "(deleted pipeline)"

        from database import RecoveryLog
        recoveries = db.query(RecoveryLog).filter(
            RecoveryLog.pipeline_run_id == run_id
        ).order_by(RecoveryLog.created_at.asc()).all()

        return {
            "success": True,
            "run": {
                "id":             run.id,
                "run_id":         run.run_id,
                "pipeline_id":    run.pipeline_id,
                "pipeline_name":  pipeline_name,
                "status":         run.status,
                "started_at":     str(run.started_at) if run.started_at else None,
                "ended_at":       str(run.ended_at) if run.ended_at else None,
                "rows_loaded":    run.rows_loaded or 0,
                "log":            run.log or "",
                "log_lines":      (run.log or "").split("\n") if run.log else []
            },
            "recoveries": [
                {
                    "id":             r.id,
                    "failed_script":  r.failed_script,
                    "error_message":  r.error_message,
                    "action_taken":   r.action_taken,
                    "fix_method":     r.fix_method,
                    "recovered":      r.recovered,
                    "summary":        r.summary,
                    "started_at":     str(r.started_at) if r.started_at else None,
                    "ended_at":       str(r.ended_at) if r.ended_at else None,
                }
                for r in recoveries
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── SQL execution ─────────────────────────────────────────────────────────────

@app.post("/sql/run")
def run_sql(req: SQLRunRequest, current_user=Depends(get_current_user),
            db: Session = Depends(get_db)):
    try:
        safety = check_sql_safety(req.sql, allow_destructive=False, script_name="ad-hoc")
        if safety["blocked"]:
            raise HTTPException(
                status_code=400,
                detail={"error": "Dangerous SQL blocked",
                        "violations": safety["violations"],
                        "message": safety["message"]}
            )

        if req.connector_id:
            import psycopg2, psycopg2.extras
            c = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if not c: raise HTTPException(404, "Connector not found")
            conn = psycopg2.connect(host=c.host, port=c.port, dbname=c.database_name,
                                     user=c.username, password=c.password)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(req.sql)
            rows = cur.fetchall() if cur.description else []
            columns = [d[0] for d in cur.description] if cur.description else []
            conn.close()
            return {"success": True, "columns": columns,
                    "rows": [list(r.values()) for r in rows],
                    "row_count": len(rows)}
        else:
            duckdb_path = os.getenv("DUCKDB_PATH", "./aibridge.duckdb")
            con = duckdb.connect(duckdb_path)
            result = con.execute(req.sql).fetchdf()
            con.close()
            return {"success": True, "columns": list(result.columns),
                    "rows": result.values.tolist(), "row_count": len(result)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sql/check-safety")
def check_sql_safety_endpoint(req: SQLRunRequest,
                              current_user=Depends(get_current_user)):
    return check_sql_safety(req.sql, allow_destructive=False, script_name="ad-hoc")


# ── NL to SQL ─────────────────────────────────────────────────────────────────

@app.post("/nl/to-sql")
def nl_to_sql(req: NLToSQLRequest, current_user=Depends(get_current_user),
              db: Session = Depends(get_db)):
    try:
        schema_text = ""
        if req.connector_id:
            c = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if c:
                schema_text = get_full_schema_for_ai(
                    _cfg(c), source_schema=c.source_schema or "raw"
                )

        from ai_provider import ask_ai

        prompt = f"""You are a SQL expert. Generate a valid PostgreSQL SELECT query.

DATABASE SCHEMA — USE ONLY THESE EXACT COLUMN NAMES:
{schema_text if schema_text else "(no schema available — be conservative)"}

CRITICAL RULES:
1. Return ONLY valid JSON: {{"sql": "SELECT ..."}}
2. NO explanations, NO markdown, NO extra text
3. Use ONLY the EXACT column names listed in the schema above
4. Use PostgreSQL syntax (LIMIT not TOP)
5. Always prefix tables with schema (warehouse.fact_*, not fact_*)
6. ONLY SELECT statements — no DROP, DELETE, UPDATE, TRUNCATE
7. JOIN dim tables to fact tables using surrogate keys
8. Add LIMIT 100 for safety

USER QUESTION: {req.question}

Respond with ONLY {{"sql": "..."}}"""

        result = ask_ai(prompt)
        sql = result.get("sql", "").strip()
        sql = sql.replace("```sql", "").replace("```", "").strip()

        if not sql:
            return {"success": False, "error": "AI did not return SQL. Try rephrasing.", "sql": ""}

        safety_check = check_sql_safety(sql, allow_destructive=False)
        return {
            "success": True, "sql": sql, "question": req.question,
            "safety": {"blocked": safety_check["blocked"],
                       "warnings": safety_check["warnings"],
                       "violations": safety_check["violations"]}
        }
    except Exception as e:
        return {"success": False, "error": str(e), "sql": ""}


# ── Scheduler ─────────────────────────────────────────────────────────────────

@app.post("/scheduler/add")
def schedule_pipeline(req: ScheduleRequest, current_user=Depends(get_current_user),
                      db: Session = Depends(get_db)):
    workspace = get_user_workspace(current_user.id, db)
    return add_pipeline_job(req.pipeline_id, req.pipeline_name,
                             req.sql_scripts, req.schedule, workspace.get("id",""))

@app.delete("/scheduler/{pipeline_id}")
def unschedule_pipeline(pipeline_id: str, current_user=Depends(get_current_user)):
    return remove_pipeline_job(pipeline_id)

@app.get("/scheduler/jobs")
def get_scheduled_jobs(current_user=Depends(get_current_user)):
    return {"jobs": list_jobs()}

@app.post("/scheduler/run-now/{pipeline_id}")
def trigger_pipeline_now(pipeline_id: str, current_user=Depends(get_current_user),
                         db: Session = Depends(get_db)):
    try:
        pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
        if not pipeline: raise HTTPException(404, "Pipeline not found")
        scripts = pipeline.artifacts.get("sql_scripts", {}).get("scripts", [])
        workspace = get_user_workspace(current_user.id, db)
        return run_pipeline_now(pipeline_id, pipeline.name, scripts, workspace.get("id",""))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Schema Evolution ──────────────────────────────────────────────────────────

@app.post("/schema/evolve")
def evolve_schema(req: SchemaEvolutionRequest, current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    try:
        result = generate_schema_evolution(req.table_name, req.existing_columns,
                                             req.new_column, req.column_type,
                                             req.user_instruction)
        try:
            from database import SchemaChange
            workspace = get_user_workspace(current_user.id, db)
            db.add(SchemaChange(workspace_id=workspace.get("id"),
                                 table_name=req.table_name, change_type="ADD_COLUMN",
                                 column_name=req.new_column, details=result))
            db.commit()
        except Exception: pass
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── AI Provider ───────────────────────────────────────────────────────────────

@app.get("/provider")
def get_provider(current_user=Depends(get_current_user)):
    import ai_provider
    return {"active": ai_provider.PROVIDER,
            "available": ["ollama","claude","openai","gemini"]}

@app.post("/provider/set")
def set_provider(req: ProviderRequest, current_user=Depends(get_current_user)):
    import ai_provider
    if req.provider not in ["ollama","claude","openai","gemini"]:
        raise HTTPException(400, "Invalid provider")
    ai_provider.PROVIDER = req.provider
    if req.api_key:
        env_map = {"claude":"ANTHROPIC_API_KEY","openai":"OPENAI_API_KEY","gemini":"GEMINI_API_KEY"}
        if req.provider in env_map:
            os.environ[env_map[req.provider]] = req.api_key
    return {"success": True, "active_provider": ai_provider.PROVIDER}


# ── Recovery Agent ────────────────────────────────────────────────────────────

@app.get("/recovery/logs")
def list_recovery_logs(current_user=Depends(get_current_user),
                       db: Session = Depends(get_db), limit: int = 50):
    from database import RecoveryLog
    workspace = get_user_workspace(current_user.id, db)
    logs = db.query(RecoveryLog).filter(
        RecoveryLog.workspace_id == workspace.get("id")
    ).order_by(RecoveryLog.created_at.desc()).limit(limit).all()
    return {"success": True, "logs": [
        {"id": r.id, "pipeline_id": r.pipeline_id,
         "pipeline_run_id": r.pipeline_run_id,
         "failed_script": r.failed_script,
         "error_message": r.error_message[:200] if r.error_message else "",
         "action_taken": r.action_taken, "fix_method": r.fix_method,
         "recovered": r.recovered, "summary": r.summary,
         "started_at": str(r.started_at) if r.started_at else None,
         "ended_at": str(r.ended_at) if r.ended_at else None}
        for r in logs
    ]}

@app.get("/recovery/logs/{log_id}")
def get_recovery_log(log_id: str, current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    from database import RecoveryLog
    log = db.query(RecoveryLog).filter(RecoveryLog.id == log_id).first()
    if not log: raise HTTPException(404, "Recovery log not found")
    return {
        "success": True, "id": log.id, "pipeline_id": log.pipeline_id,
        "pipeline_run_id": log.pipeline_run_id,
        "failed_script": log.failed_script,
        "error_message": log.error_message, "error_pattern": log.error_pattern,
        "action_taken": log.action_taken, "fix_method": log.fix_method,
        "fix_sql": log.fix_sql, "recovered": log.recovered,
        "attempts": log.attempts, "summary": log.summary,
        "started_at": str(log.started_at), "ended_at": str(log.ended_at)
    }

@app.get("/recovery/stats")
def get_recovery_stats(current_user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    from database import RecoveryLog
    workspace = get_user_workspace(current_user.id, db)
    all_logs = db.query(RecoveryLog).filter(
        RecoveryLog.workspace_id == workspace.get("id")
    ).all()
    total = len(all_logs)
    recovered = sum(1 for l in all_logs if l.recovered)
    actions = {}
    for l in all_logs:
        actions[l.action_taken] = actions.get(l.action_taken, 0) + 1
    return {
        "success": True, "total": total, "recovered": recovered,
        "failed": total - recovered,
        "success_rate": round((recovered / total) * 100, 1) if total > 0 else 0,
        "top_actions": sorted(actions.items(), key=lambda x: -x[1])[:5]
    }