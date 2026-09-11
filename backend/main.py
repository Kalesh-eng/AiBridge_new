"""
main.py — AIBridge FastAPI backend (v2.0.0).

v2.0.0: ETL Mapping storage + Pipeline versioning.
        - PipelineMapping: save/list/update/activate mapping versions per user
        - PipelineVersion: full version history with rollback + diff compare
        - Auto-saves v1 on first pipeline save
        - New endpoints: /mapping/*, /version/*
v1.9.0: Generic FK-driven bridge joins.
v1.8.0: Universal DB support.
v1.7.0: Smart Table Selection.
v1.6.0: Schema caching.
v1.5.0: Multi-agent OrchestratorAgent system.
"""

import os
import json
import duckdb
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Body
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
                                PipelineRun, ApprovalQueue, Workspace,
                                PipelineMapping, PipelineVersion)
from pipeline_executor import (
    extract_to_staging, execute_warehouse_scripts,
    list_all_tables_by_schema, get_table_preview,
    get_full_schema_for_ai, list_schemas, list_columns_for_tables
)
from scheduler import (start_scheduler, stop_scheduler,
                        add_pipeline_job, remove_pipeline_job,
                        list_jobs, run_pipeline_now)
from sql_safety import check_pipeline_safety, check_sql_safety
from schema_cache import (
    compute_schema_hash, get_cached_design,
    save_cached_design, invalidate_cache, get_cache_status
)
from sql_dialect import convert_scripts, get_dialect_info, get_supported_targets
from agents import (
    OrchestratorAgent, AgentContext,
    SchemaAgent, MetadataAgent, BusinessAgent,
    PlannerAgent, RelationshipValidationAgent,
    DataModelAgent, ETLAgent, SQLAgent,
    SQLValidationAgent, GovernanceValidationAgent,
    ReviewAgent, ExecutionAgent, RecoveryAgent,
    QualityAgent, AnalyticsAgent
)

load_dotenv()

app = FastAPI(title="AIBridge API", version="1.8.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    setup_database()
    start_scheduler()
    print("[AIBridge] API started (v1.8.0 — Universal DB Support active)")


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
    scd_type:              str = "1"  # SCD Type 1, 2, or 3
    connector_id:          str = ""
    staging_schema:        str = "staging"
    warehouse_schema:      str = "warehouse"
    source_tables:         list = []     # ← ADDED
    source_schema:         str = "raw"   # ← ADDED

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

class RecommendTablesRequest(BaseModel):
    table_names: List[str]

class ScheduleRequest(BaseModel):
    pipeline_id:     str
    pipeline_name:   str
    sql_scripts:     list
    schedule:        str
    schedule_config: dict = {}   # NEW: custom schedule config from UI

class PostgresConnectRequest(BaseModel):
    host: str; port: int = 5433; database: str
    username: str; password: str

class SQLRunRequest(BaseModel):
    sql: str; connector_id: str = ""

class UpdateArtifactsRequest(BaseModel):
    artifacts: dict

class RegenerateRequest(BaseModel):
    pipeline_id:      str
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
    question:     str
    connector_id: str = ""
    pipeline_id:  str = ""

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

class SaveMappingRequest(BaseModel):
    pipeline_id:  str
    name:         str
    mappings:     dict
    notes:        str = ""

class UpdateMappingRequest(BaseModel):
    name:     Optional[str] = None
    mappings: Optional[dict] = None
    notes:    Optional[str] = None

class SaveVersionRequest(BaseModel):
    pipeline_id:    str
    version_label:  str = ""
    change_summary: str = ""

class RollbackVersionRequest(BaseModel):
    pipeline_id: str
    version_id:  str

class HILModeRequest(BaseModel):
    mode: str


# ── Config helpers ────────────────────────────────────────────────────────────

def _cfg(c: Connector) -> dict:
    """Build connector config dict — includes connector_type for universal DB support."""
    return {
        "connector_type": c.connector_type or "postgres",
        "host":           c.host,
        "port":           c.port,
        "database":       c.database_name,
        "database_name":  c.database_name,
        "username":       c.username,
        "password":       c.password,
    }


def _build_ctx(pipeline_id, workspace_id, connector_config, source_schema,
               source_tables, source_columns, source_description,
               business_requirements, target_config=None,
               staging_schema="staging", warehouse_schema="warehouse"):
    return OrchestratorAgent.build_context(
        pipeline_id=pipeline_id, workspace_id=workspace_id,
        connector_config=connector_config, source_schema=source_schema,
        source_tables=source_tables, source_columns=source_columns,
        source_description=source_description,
        business_requirements=business_requirements,
        target_config=target_config or connector_config,
        staging_schema=staging_schema, warehouse_schema=warehouse_schema,
    )


def _recount_warehouse_rows(target_config, warehouse_schema):
    """Recount warehouse rows — works for any target DB via universal_connector."""
    try:
        from universal_connector import recount_warehouse_rows
        return recount_warehouse_rows(target_config, warehouse_schema)
    except Exception as e:
        print(f"[Pipeline] Could not recount warehouse rows: {e}")
        return 0


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "message": "AIBridge API is running", "version": "1.8.0",
        "features": ["Multi-Agent", "HIL", "Recovery Agent", "Schema Cache",
                     "Smart Table Selection", "SQL Safety Guard", "Universal DB",
                     "SQL Dialect Converter", "MCP Ready"],
        "supported_databases": get_supported_targets()
    }

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.8.0", "agents": "active",
            "schema_cache": "active", "universal_db": "active",
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
def save_connector(req: ConnectorSaveRequest, current_user=Depends(get_current_user),
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
                          "connector_type": connector.connector_type,
                          "role": connector.role, "host": connector.host,
                          "port": connector.port, "database_name": connector.database_name,
                          "source_schema": connector.source_schema}}

@app.put("/connector/{connector_id}")
def update_connector(connector_id: str, req: ConnectorUpdateRequest,
                     current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")
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
            "connector": {"id": c.id, "name": c.name, "connector_type": c.connector_type,
                          "role": c.role, "host": c.host, "port": c.port,
                          "database_name": c.database_name, "username": c.username,
                          "source_schema": c.source_schema}}

@app.get("/connector/list")
def list_connectors(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    workspace = get_user_workspace(current_user.id, db)
    connectors = db.query(Connector).filter(
        Connector.workspace_id == workspace.get("id"), Connector.is_active == True
    ).order_by(Connector.created_at.desc()).all()
    return {"success": True, "connectors": [
        {"id": c.id, "name": c.name, "connector_type": c.connector_type,
         "role": c.role, "host": c.host, "port": c.port,
         "database_name": c.database_name, "username": c.username,
         "source_schema": c.source_schema or "raw", "created_at": str(c.created_at)}
        for c in connectors]}

@app.delete("/connector/{connector_id}")
def delete_connector(connector_id: str, current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")
    c.is_active = False; db.commit()
    return {"success": True, "message": "Connector deleted"}

@app.post("/connector/test")
def test_connector_universal(req: dict, current_user=Depends(get_current_user)):
    """Test any database connection via universal_connector."""
    from universal_connector import test_connection
    return test_connection(req)

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
def get_connector_schemas(connector_id: str, current_user=Depends(get_current_user),
                          db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")
    return list_schemas(_cfg(c))

@app.get("/connector/{connector_id}/tables")
def get_connector_tables(connector_id: str, current_user=Depends(get_current_user),
                         db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")
    return list_all_tables_by_schema(_cfg(c), source_schema=c.source_schema or "raw")

@app.post("/connector/{connector_id}/columns")
def get_columns_for_tables(connector_id: str, req: ColumnListRequest,
                           current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")

    # ── DuckDB (CSV/Excel file) — read columns directly ───────────────────────
    if c.connector_type == "duckdb":
        try:
            import duckdb as _duckdb
            duckdb_path = c.username  # username stores the DuckDB file path
            table_name  = c.database_name
            con         = _duckdb.connect(duckdb_path, read_only=True)
            cols        = con.execute(f'DESCRIBE "{table_name}"').fetchall()
            con.close()
            return {
                "success": True,
                "source_schema": "main",
                "tables": {
                    table_name: [
                        {"name": col[0], "type": col[1], "nullable": True}
                        for col in cols
                    ]
                }
            }
        except Exception as e:
            raise HTTPException(500, f"Could not read DuckDB columns: {e}")

    return list_columns_for_tables(_cfg(c), source_schema=c.source_schema or "raw",
                                   table_names=req.table_names)

@app.post("/connector/{connector_id}/recommend-tables")
def recommend_tables(connector_id: str, req: RecommendTablesRequest,
                     current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Smart Table Selection — AI recommends tables from large schemas."""
    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")

    cfg         = _cfg(c)
    table_names = req.table_names

    if not table_names:
        return {"recommended": [], "optional": [], "excluded": [], "reasons": {}}

    table_context = ""
    try:
        from universal_connector import get_row_count, discover_foreign_keys
        row_counts = {}
        for t in table_names[:50]:
            try:
                row_counts[t] = get_row_count(cfg, c.source_schema or "raw", t)
            except Exception:
                row_counts[t] = 0

        fks    = discover_foreign_keys(cfg, c.source_schema or "raw")
        fk_map = {}
        for fk in fks:
            src = fk.get("from_table", "")
            tgt = fk.get("to_table", "")
            if src: fk_map.setdefault(src, []).append(tgt)

        lines = []
        for t in table_names:
            rc     = row_counts.get(t, 0)
            fk_list = fk_map.get(t, [])
            rc_str = f"{rc:,}" if rc > 0 else "unknown"
            fk_str = f", FKs → {', '.join(fk_list)}" if fk_list else ""
            lines.append(f"  {t}: {rc_str} rows{fk_str}")
        table_context = "\n".join(lines)

    except Exception as e:
        print(f"[RecommendTables] Could not get row counts/FKs: {e}")
        table_context = "\n".join(f"  {t}" for t in table_names)

    from ai_provider import ask_ai
    prompt = f"""You are a data warehouse architect. Analyse these database tables and recommend which ones to include in a star schema warehouse design.

SOURCE SCHEMA: {c.source_schema}
TABLES ({len(table_names)} total):
{table_context}

CLASSIFICATION RULES:
1. RECOMMENDED — core business tables:
   - Transaction/fact tables (orders, sales, enrollments, transactions, visits)
   - Master entity tables (customers, products, students, patients, accounts)
   - Dimension tables (branches, departments, categories, locations)

2. OPTIONAL — may add value:
   - Reference/lookup tables (statuses, types, codes)
   - History tables with business value

3. EXCLUDED — system/operational tables:
   - Names containing: audit, log, temp, tmp, backup, migration, schema, session, token, queue, cache, lock, _bak, _old, _test
   - AIBridge system tables: pipelines, connectors, pipeline_runs, recovery_logs, approval_queue, workspaces, users
   - Config tables with very low row counts (< 10 rows)

Return ONLY valid JSON:
{{
  "recommended": ["table1", "table2"],
  "optional":    ["table3"],
  "excluded":    ["table4", "table5"],
  "reasons": {{
    "table1": "Core transaction table with 2.3M rows and FKs to customers",
    "table4": "System audit table — no business value"
  }}
}}

Only include tables from the list above."""

    try:
        result      = ask_ai(prompt)
        table_set   = set(table_names)
        recommended = [t for t in (result.get("recommended") or []) if t in table_set]
        optional    = [t for t in (result.get("optional")    or []) if t in table_set]
        excluded    = [t for t in (result.get("excluded")    or []) if t in table_set]
        classified  = set(recommended + optional + excluded)
        optional.extend([t for t in table_names if t not in classified])
        return {"recommended": recommended, "optional": optional, "excluded": excluded,
                "reasons": result.get("reasons") or {}, "total": len(table_names)}
    except Exception as e:
        print(f"[RecommendTables] AI error: {e} — using heuristic fallback")
        excluded_kw = ['audit', 'log', 'temp', 'tmp', 'backup', 'migration', 'schema',
                       'session', 'token', 'queue', 'cache', 'lock', 'pipelines', 'connectors',
                       'pipeline_runs', 'recovery_logs', 'approval_queue', 'workspaces',
                       'users', '_bak', '_old']
        recommended = [t for t in table_names if not any(kw in t.lower() for kw in excluded_kw)]
        excluded    = [t for t in table_names if any(kw in t.lower() for kw in excluded_kw)]
        return {"recommended": recommended, "optional": [], "excluded": excluded,
                "reasons": {}, "total": len(table_names), "fallback": True}

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
    if not c: raise HTTPException(404, "Connector not found")
    return {"success": True, "connector": {
        "id": c.id, "name": c.name, "connector_type": c.connector_type,
        "role": c.role, "host": c.host, "port": c.port,
        "database_name": c.database_name, "username": c.username,
        "source_schema": c.source_schema or "raw"}}

@app.get("/connector/types")
def get_connector_types_endpoint(current_user=Depends(get_current_user)):
    """Return all supported connector types."""
    from connectors import get_connector_types
    return {"success": True, "connector_types": get_connector_types(),
            "supported_targets": get_supported_targets()}

@app.post("/connector/file/upload")
async def upload_file(file: UploadFile = File(...),
                      current_user=Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """
    Upload CSV/Excel → load into DuckDB → auto-create a connector record.
    Returns connector_id so ETL Agent can use it immediately.
    """
    import tempfile, shutil
    try:
        suffix     = ".csv" if file.filename.lower().endswith(".csv") else ".xlsx"
        table_name = (file.filename
                      .lower()
                      .replace(".csv","").replace(".xlsx","").replace(".xls","")
                      .replace(" ","_").replace("-","_"))

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        # Load into DuckDB
        duckdb_path = os.getenv("DUCKDB_PATH", "./aibridge.duckdb")
        fc          = FileConnector(duckdb_path)
        result      = fc.load_csv(tmp_path, table_name) if suffix == ".csv" \
                      else fc.load_excel(tmp_path, table_name)
        os.unlink(tmp_path)

        # Use actual table name stored in DuckDB (FileConnector may add raw_ prefix)
        actual_table = result.get("table", table_name)
        if not actual_table:
            actual_table = table_name

        if not result.get("success", True) is False:
            # Get column info from DuckDB using actual table name
            import duckdb as _duckdb
            con  = _duckdb.connect(duckdb_path)
            cols = con.execute(f'DESCRIBE "{actual_table}"').fetchall()
            rows = con.execute(f'SELECT COUNT(*) FROM "{actual_table}"').fetchone()[0]
            con.close()

            schema_text = f"Table: {actual_table}\nColumns:\n"
            schema_text += "\n".join([f"  {c[0]} ({c[1]})" for c in cols])

            # Auto-create connector using actual DuckDB table name
            workspace   = get_user_workspace(current_user.id, db)
            conn_name   = f"📄 {file.filename}"

            existing = db.query(Connector).filter(
                Connector.workspace_id == workspace.get("id"),
                Connector.database_name == actual_table,
                Connector.connector_type == "duckdb"
            ).first()

            if existing:
                connector_id = existing.id
            else:
                new_conn = Connector(
                    workspace_id   = workspace.get("id"),
                    name           = conn_name,
                    connector_type = "duckdb",
                    role           = "source",
                    host           = "localhost",
                    port           = 0,
                    database_name  = actual_table,   # ← actual DuckDB table name
                    username       = duckdb_path,
                    password       = "",
                    source_schema  = "main",
                    is_active      = True
                )
                db.add(new_conn); db.commit(); db.refresh(new_conn)
                connector_id = new_conn.id

            print(f"[FileUpload] ✓ {file.filename} → DuckDB table '{actual_table}' ({rows} rows)")
            print(f"[FileUpload] ✓ Connector saved: {connector_id}")

            return {
                "success":        True,
                "table":          actual_table,
                "rows":           rows,
                "columns":        [{"name": c[0], "type": c[1]} for c in cols],
                "schema_text":    schema_text,
                "connector_id":   connector_id,
                "connector_name": conn_name,
                "message":        f"✓ {file.filename} loaded — {rows:,} rows, {len(cols)} columns"
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── ETL Agent — Legacy ────────────────────────────────────────────────────────

@app.post("/pipeline/run")
def run_pipeline(req: PipelineRequest, current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    try:
        connector_config = None; source_schema = "raw"
        if req.connector_id:
            c = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if c: connector_config = _cfg(c); source_schema = c.source_schema or "raw"
        result = run_full_pipeline(req.source_description, req.raw_schema,
                                    req.business_requirements, connector_config, source_schema)
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── HIL Endpoints with Schema Cache ──────────────────────────────────────────

@app.post("/pipeline/run-phase-1")
def run_phase_1(req: PipelineRequest, current_user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    try:
        workspace = get_user_workspace(current_user.id, db)
        wid       = workspace.get("id")

        connector_config = None; source_schema = "raw"
        if req.connector_id:
            c = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if c: connector_config = _cfg(c); source_schema = c.source_schema or "raw"

        print("[Phase 1] Starting OrchestratorAgent Phase 1...")

        ctx = _build_ctx("", wid, connector_config or {}, source_schema, [], {},
                         req.source_description, req.business_requirements + (f". Use SCD Type {req.scd_type} for all dimensions." if req.scd_type else ""),
                         staging_schema=req.staging_schema, warehouse_schema=req.warehouse_schema)

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(SchemaAgent().run,   ctx): "SchemaAgent",
                executor.submit(MetadataAgent().run, ctx): "MetadataAgent",
                executor.submit(BusinessAgent().run, ctx): "BusinessAgent",
            }
            for future in concurrent.futures.as_completed(futures):
                agent_name = futures[future]
                try:
                    r = future.result()
                    print(f"[Phase 1] {'✓' if r.success else '✗'} {agent_name} ({r.duration_s:.1f}s)")
                except Exception as e:
                    print(f"[Phase 1] ✗ {agent_name} error: {e}")

        schema_text = ctx.schema_result.get("schema_text", "") if ctx.schema_result else ""
        src_tables  = ctx.schema_result.get("source_tables", []) if ctx.schema_result else []

        # ── DuckDB fallback: derive source_tables from connector ──────────────
        if not src_tables and connector_config and connector_config.get("connector_type") == "duckdb":
            table_name = connector_config.get("database_name", "")
            if table_name:
                src_tables = [table_name]
                print(f"[Phase 1] DuckDB source table: {src_tables}")
        # ── Also use req.source_tables if still empty ─────────────────────────
        if not src_tables and req.source_tables:
            src_tables = req.source_tables

        # ── Enrich schema_text with actual columns from DuckDB or staging ──────
        # DuckDB raw_schema only has table name — fetch real columns
        if connector_config and connector_config.get("connector_type") == "duckdb" and src_tables:
            try:
                duckdb_path = connector_config.get("username", "")  # DuckDB path stored in username
                if duckdb_path:
                    import duckdb as _ddb
                    _dcon = _ddb.connect(duckdb_path)
                    for t in src_tables:
                        try:
                            cols = _dcon.execute(f'DESCRIBE "{t}"').fetchall()
                            if cols:
                                schema_text = f"Table: {t}\nColumns:\n"
                                schema_text += "\n".join([f"  {c[0]} ({c[1]})" for c in cols])
                                print(f"[Phase 1] Enriched schema from DuckDB: {len(cols)} columns from {t}")
                                break
                        except Exception:
                            pass
                    _dcon.close()
            except Exception as e:
                print(f"[Phase 1] DuckDB schema enrichment warning: {e}")
                # Fallback: try PostgreSQL staging table
                try:
                    pg_connector = db.query(Connector).filter(
                        Connector.workspace_id == wid,
                        Connector.connector_type == "postgres",
                        Connector.is_active == True
                    ).first()
                    if pg_connector:
                        import psycopg2 as _pg2
                        _con2 = _pg2.connect(
                            host=pg_connector.host, port=int(pg_connector.port or 5432),
                            dbname=pg_connector.database_name,
                            user=pg_connector.username, password=pg_connector.password
                        )
                        _cur2 = _con2.cursor()
                        for t in src_tables:
                            stg_name = f"stg_{t}" if not t.startswith("stg_") else t
                            _cur2.execute("""
                                SELECT column_name, data_type
                                FROM information_schema.columns
                                WHERE table_schema = 'staging' AND table_name = %s
                                ORDER BY ordinal_position
                            """, (stg_name,))
                            pg_cols = _cur2.fetchall()
                            if pg_cols:
                                schema_text = f"Table: {stg_name}\nColumns:\n"
                                schema_text += "\n".join([f"  {c[0]} ({c[1]})" for c in pg_cols])
                                print(f"[Phase 1] Enriched schema from staging: {len(pg_cols)} columns")
                                break
                        _cur2.close(); _con2.close()
                except Exception as e2:
                    print(f"[Phase 1] Staging schema enrichment warning: {e2}")
        # Pass enriched schema_text back to ctx so DataModelAgent gets real columns
        # Without this, DataModelAgent only sees 23-char table name, not 20 columns
        if schema_text and len(schema_text) > 30:
            ctx.raw_schema = schema_text
            if ctx.schema_result:
                ctx.schema_result["schema_text"] = schema_text
            print(f"[Phase 1] Schema propagated to ctx: {len(schema_text)} chars")

        schema_hash = compute_schema_hash(schema_text, src_tables, req.business_requirements)
        print(f"[SchemaCache] Schema hash: {schema_hash}")

        cached_pipeline = None
        if req.connector_id:
            existing = db.query(Pipeline).filter(
                Pipeline.workspace_id == wid,
                Pipeline.connector_id == req.connector_id
            ).order_by(Pipeline.created_at.desc()).all()
            for p in existing:
                cached = get_cached_design(p.id, schema_hash, db)
                if cached:
                    cached_pipeline = cached
                    print(f"[SchemaCache] ✓ Cache HIT — using design from: {p.name}")
                    break

        if cached_pipeline:
            data_model      = cached_pipeline.get("data_model", {})
            schema_analysis = cached_pipeline.get("schema_analysis", {})
            dim_count       = len(data_model.get("dimension_tables", []))
            fact_count      = len(data_model.get("fact_tables", []))

            agent_metadata = {
                "plan": {"plan": "star_schema", "reason": "From cache"},
                "business_analysis": ctx.business_result,
                "relationship_validation": {"passed": True},
                "pii_detected": [], "cache_hit": True, "schema_hash": schema_hash
            }

            approval = ApprovalQueue(
                workspace_id=wid, approval_type="data_model",
                title=f"Cached data model — {fact_count} facts, {dim_count} dims (schema unchanged)",
                description=f"Schema unchanged — reusing cached design. $0 AI cost. Hash: {schema_hash}",
                proposed_data={"schema_analysis": schema_analysis, "data_model": data_model,
                               "agent_metadata": agent_metadata},
                context={
                    "source_description": req.source_description, "raw_schema": req.raw_schema,
                    "business_requirements": req.business_requirements,
                    "connector_id": req.connector_id, "source_schema": source_schema,
                    "staging_schema": req.staging_schema, "warehouse_schema": req.warehouse_schema,
                    "schema_hash": schema_hash, "from_cache": True,
                    "sql_scripts": cached_pipeline.get("sql_scripts", {}),
                    "etl_mappings": cached_pipeline.get("etl_mappings", {}),
                    "plan": {"plan": "star_schema"}
                },
                status="pending", requested_by=current_user.id, risk_level="low"
            )
            db.add(approval); db.commit(); db.refresh(approval)

            print(f"[Phase 1] ✓ CACHE HIT — {fact_count} facts, {dim_count} dims — $0 AI cost")
            return {
                "success": True, "approval_id": approval.id,
                "phase": "awaiting_model_approval",
                "cache_hit": True, "schema_hash": schema_hash,
                "data": {"schema_analysis": schema_analysis, "data_model": data_model,
                         "agent_metadata": agent_metadata},
                "message": "✓ Schema unchanged — using cached design. $0 AI cost this run."
            }

        print("[SchemaCache] Cache MISS — running full AI pipeline")

        PlannerAgent().run(ctx)
        print(f"[Phase 1] ✓ PlannerAgent — plan: {ctx.plan.get('plan') if ctx.plan else 'unknown'}")

        RelationshipValidationAgent().run(ctx)
        rv_passed = ctx.relationship_validation.get("passed", True) if ctx.relationship_validation else True
        print(f"[Phase 1] {'✓' if rv_passed else '⚠'} RelationshipValidationAgent")

        # FK relationships now set directly on ctx by RelationshipValidationAgent
        # Also try fallback from schema_analysis if agent couldn't connect
        fk_relationships = ctx.fk_relationships or []
        if not fk_relationships and ctx.schema_result:
            rels = ctx.schema_result.get("relationships", [])
            fk_relationships = [
                {"from_table": r.get("from_table"), "from_column": r.get("join_key"),
                 "to_table":   r.get("to_table"),   "to_column":   r.get("join_key")}
                for r in rels if r.get("from_table") and r.get("to_table")
            ]
            ctx.fk_relationships = fk_relationships
        print(f"[Phase 1] ✓ FK relationships for AI: {len(fk_relationships)}")

        if connector_config:
            # ── Domain mismatch check (runs before DataModelAgent) ────────────
            try:
                from nlm_engine import _validate_domain_match
                schema_text = ctx.schema_result.get("schema_text", "") if ctx.schema_result else ""
                schema_anal = ctx.schema_result or {}
                mismatch = _validate_domain_match(
                    req.raw_schema or schema_text,
                    req.business_requirements,
                    schema_anal
                )
                if mismatch:
                    print(f"[Phase 1] ✗ Domain mismatch: {mismatch}")
                    raise HTTPException(status_code=400, detail=mismatch)
            except HTTPException:
                raise
            except Exception as e:
                print(f"[Phase 1] Domain validation skipped: {e}")

            dm_result = DataModelAgent().run(ctx)
            if dm_result.success and ctx.data_model:
                data_model      = ctx.data_model.get("data_model", {})
                schema_analysis = ctx.data_model.get("schema_analysis", {})
                # Fix source column names using enriched schema_text
                # DataModelAgent may invent column names (e.g. Accident_History vs Accidents)
                if schema_text:
                    from nlm_engine import _fix_source_column_names
                    data_model = _fix_source_column_names(data_model, schema_text)
            else:
                print("[Phase 1] DataModelAgent failed — falling back to nlm_engine")
                try:
                    fallback        = run_phase_1_model_design(
                        req.source_description, schema_text or req.raw_schema,
                        req.business_requirements, connector_config, source_schema,
                        fk_relationships=fk_relationships)
                    data_model      = fallback["data_model"]
                    schema_analysis = fallback["schema_analysis"]
                except ValueError as e:
                    if "Domain mismatch" in str(e):
                        raise HTTPException(status_code=400, detail=str(e))
                    raise
        else:
            try:
                fallback        = run_phase_1_model_design(
                    req.source_description, schema_text or req.raw_schema,
                    req.business_requirements, connector_config, source_schema,
                    fk_relationships=fk_relationships)
                data_model      = fallback["data_model"]
                schema_analysis = fallback["schema_analysis"]
            except ValueError as e:
                if "Domain mismatch" in str(e):
                    raise HTTPException(status_code=400, detail=str(e))
                raise

        dim_count  = len(data_model.get("dimension_tables", []))
        fact_count = len(data_model.get("fact_tables", []))

        agent_metadata = {
            "plan": ctx.plan, "business_analysis": ctx.business_result,
            "relationship_validation": ctx.relationship_validation,
            "pii_detected": ctx.metadata_result.get("pii_columns", []) if ctx.metadata_result else [],
            "cache_hit": False, "schema_hash": schema_hash
        }

        approval = ApprovalQueue(
            workspace_id=wid, approval_type="data_model",
            title=f"Review proposed data model — {fact_count} facts, {dim_count} dims",
            description=f"AI analyzed schema, designed {fact_count + dim_count} warehouse tables. Hash: {schema_hash}",
            proposed_data={"schema_analysis": schema_analysis, "data_model": data_model,
                           "agent_metadata": agent_metadata},
            context={
                "source_description": req.source_description,
                "raw_schema": schema_text or req.raw_schema,   # ← enriched schema with columns
                "business_requirements": req.business_requirements,
                "connector_id": req.connector_id, "source_schema": source_schema,
                "staging_schema": req.staging_schema, "warehouse_schema": req.warehouse_schema,
                "schema_hash": schema_hash, "from_cache": False, "plan": ctx.plan,
                "fk_relationships": fk_relationships,
                "source_tables": src_tables or req.source_tables or []
            },
            status="pending", requested_by=current_user.id, risk_level="medium"
        )
        db.add(approval); db.commit(); db.refresh(approval)

        print(f"[Phase 1] ✓ Complete — {fact_count} facts, {dim_count} dims — awaiting HIL Gate 1")
        return {
            "success": True, "approval_id": approval.id,
            "phase": "awaiting_model_approval",
            "cache_hit": False, "schema_hash": schema_hash,
            "data": {"schema_analysis": schema_analysis, "data_model": data_model,
                     "agent_metadata": agent_metadata},
            "message": "✓ Model designed by agents. Please review and approve."
        }

    except Exception as e:
        import traceback
        print(f"[Phase 1] ERROR: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/approve-model")
def approve_model(req: ApproveModelRequest, current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    try:
        approval = db.query(ApprovalQueue).filter(ApprovalQueue.id == req.approval_id).first()
        if not approval: raise HTTPException(404, "Approval not found")
        if approval.status != "pending": raise HTTPException(400, f"Approval already {approval.status}")

        if req.edited_model:
            approval.edited_data = {"data_model": req.edited_model}
            approval.status      = "edited"
            data_model           = req.edited_model
        else:
            approval.status = "approved"
            data_model      = approval.proposed_data["data_model"]

        approval.approved_by = current_user.id
        approval.comments    = req.comments
        approval.decided_at  = datetime.utcnow()
        db.commit()

        schema_analysis = approval.proposed_data["schema_analysis"]
        ctx_data        = approval.context or {}
        wid             = approval.workspace_id
        schema_hash     = ctx_data.get("schema_hash")
        from_cache      = ctx_data.get("from_cache", False)

        if from_cache and not req.edited_model:
            cached_scripts  = ctx_data.get("sql_scripts", {})
            cached_mappings = ctx_data.get("etl_mappings", {})

            if cached_scripts and cached_scripts.get("scripts"):
                scripts      = cached_scripts.get("scripts", [])
                script_count = len(scripts)
                print(f"[Phase 2] ✓ CACHE HIT — reusing {script_count} SQL scripts ($0 AI cost)")

                sql_approval = ApprovalQueue(
                    workspace_id=wid, approval_type="sql_scripts",
                    title=f"Cached SQL — {script_count} scripts (schema unchanged)",
                    description="Schema unchanged — reusing cached SQL. $0 AI cost.",
                    proposed_data={
                        "schema_analysis": schema_analysis, "data_model": data_model,
                        "etl_mappings": cached_mappings, "sql_scripts": cached_scripts,
                        "validation": {"sql_issues": [], "auto_fixes": [], "gov_warnings": []}
                    },
                    context=ctx_data, status="pending",
                    requested_by=current_user.id, risk_level="low"
                )
                db.add(sql_approval); db.commit(); db.refresh(sql_approval)

                return {
                    "success": True, "approval_id": sql_approval.id,
                    "phase": "awaiting_sql_approval", "cache_hit": True,
                    "data": {"schema_analysis": schema_analysis, "data_model": data_model,
                             "etl_mappings": cached_mappings, "sql_scripts": cached_scripts,
                             "validation": {"sql_issues": [], "auto_fixes": [], "gov_warnings": []}},
                    "message": "✓ Schema unchanged — using cached SQL. $0 AI cost."
                }

        print("[Phase 2] Starting agent SQL pipeline...")

        connector_config = None
        if ctx_data.get("connector_id"):
            c = db.query(Connector).filter(Connector.id == ctx_data["connector_id"]).first()
            if c: connector_config = _cfg(c)

        ctx = _build_ctx("", wid, connector_config or {},
                         ctx_data.get("source_schema", "raw"), [], {},
                         ctx_data.get("source_description", ""),
                         ctx_data.get("business_requirements", ""),
                         staging_schema=ctx_data.get("staging_schema", "staging"),
                         warehouse_schema=ctx_data.get("warehouse_schema", "warehouse"))

        ctx.data_model = {"data_model": data_model, "schema_analysis": schema_analysis}
        if ctx_data.get("plan"): ctx.plan = ctx_data["plan"]
        # Restore FK relationships into context for SQLAgent
        ctx.fk_relationships = ctx_data.get("fk_relationships", [])
        # Pass actual staging tables so SQLAgent knows what exists
        src_tables = ctx_data.get("source_tables", [])
        # DuckDB fallback — derive from connector if source_tables not saved
        if not src_tables and connector_config and connector_config.get("connector_type") == "duckdb":
            table_name = connector_config.get("database_name", "")
            if table_name:
                src_tables = [table_name]
                print(f"[Phase 2] DuckDB source table (fallback): {src_tables}")
        ctx.actual_staging_tables = [
            f"stg_{t}" if not t.startswith("stg_") else t
            for t in src_tables
        ]
        print(f"[Phase 2] Actual staging tables: {ctx.actual_staging_tables}")

        # Single flat-file source (CSV/Excel via DuckDB) needs staging table hints
        # Multi-table DB sources (PostgreSQL/MySQL etc) use SQLAgent as normal
        is_duckdb_source   = connector_config and connector_config.get("connector_type") == "duckdb"
        is_single_table    = len(ctx.actual_staging_tables) == 1
        use_staging_hints  = is_duckdb_source and is_single_table

        if use_staging_hints:
            print(f"[Phase 2] Single file source — skipping SQLAgent, using nlm_engine with staging hints")
            print(f"[Phase 2] Staging table: {ctx.actual_staging_tables}")
            phase2           = run_phase_2_sql_generation(
                schema_analysis, data_model,
                staging_schema=ctx_data.get("staging_schema", "staging"),
                warehouse_schema=ctx_data.get("warehouse_schema", "warehouse"),
                fk_relationships=ctx.fk_relationships,
                actual_staging_tables=ctx.actual_staging_tables,
                raw_schema=ctx_data.get("raw_schema", ""))   # ← pass enriched schema
            ctx.sql_scripts  = phase2["sql_scripts"]
            ctx.etl_mappings = phase2["etl_mappings"]
        else:
            # Multi-table DB source — use SQLAgent as normal
            sql_result = SQLAgent().run(ctx)
            if not sql_result.success or not ctx.sql_scripts:
                print("[Phase 2] SQLAgent failed — falling back to nlm_engine")
                phase2           = run_phase_2_sql_generation(
                    schema_analysis, data_model,
                    staging_schema=ctx_data.get("staging_schema", "staging"),
                    warehouse_schema=ctx_data.get("warehouse_schema", "warehouse"),
                    fk_relationships=ctx.fk_relationships,
                    actual_staging_tables=ctx.actual_staging_tables,
                    raw_schema=ctx_data.get("raw_schema", ""))
                ctx.sql_scripts  = phase2["sql_scripts"]
                ctx.etl_mappings = phase2["etl_mappings"]

        SQLValidationAgent().run(ctx)
        sv_issues = ctx.sql_validation.get("issues", []) if ctx.sql_validation else []
        sv_fixes  = ctx.sql_validation.get("auto_fixes", []) if ctx.sql_validation else []

        GovernanceValidationAgent().run(ctx)
        if ctx.blocked: raise HTTPException(400, f"Pipeline blocked: {ctx.blocked_reason}")

        gov_warnings = ctx.governance_validation.get("warnings", []) if ctx.governance_validation else []
        scripts      = ctx.sql_scripts.get("scripts", []) if ctx.sql_scripts else []
        script_count = len(scripts)
        ctx_data["schema_hash"] = schema_hash

        sql_approval = ApprovalQueue(
            workspace_id=wid, approval_type="sql_scripts",
            title=f"Review generated SQL — {script_count} scripts",
            description=f"Generated {script_count} scripts. {len(sv_fixes)} auto-fixes. {len(gov_warnings)} governance warnings.",
            proposed_data={
                "schema_analysis": schema_analysis, "data_model": data_model,
                "etl_mappings": ctx.etl_mappings or {}, "sql_scripts": ctx.sql_scripts or {},
                "validation": {"sql_issues": sv_issues, "auto_fixes": sv_fixes, "gov_warnings": gov_warnings}
            },
            context=ctx_data, status="pending",
            requested_by=current_user.id, risk_level="high"
        )
        db.add(sql_approval); db.commit(); db.refresh(sql_approval)

        print(f"[Phase 2] ✓ Complete — {script_count} scripts ready for HIL Gate 2")
        return {
            "success": True, "approval_id": sql_approval.id,
            "phase": "awaiting_sql_approval", "cache_hit": False,
            "data": {"schema_analysis": schema_analysis, "data_model": data_model,
                     "etl_mappings": ctx.etl_mappings or {}, "sql_scripts": ctx.sql_scripts or {},
                     "validation": {"sql_issues": sv_issues, "auto_fixes": sv_fixes, "gov_warnings": gov_warnings}},
            "message": f"✓ SQL generated. {len(sv_fixes)} auto-fixes applied."
        }

    except HTTPException: raise
    except Exception as e:
        import traceback
        print(f"[Phase 2] ERROR: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/approve-sql")
def approve_sql(req: ApproveSQLRequest, current_user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    try:
        approval = db.query(ApprovalQueue).filter(ApprovalQueue.id == req.approval_id).first()
        if not approval: raise HTTPException(404, "Approval not found")
        if approval.status != "pending": raise HTTPException(400, f"Approval already {approval.status}")

        data = dict(approval.proposed_data)
        if req.edited_scripts: data["sql_scripts"] = {"scripts": req.edited_scripts}

        scripts = data["sql_scripts"].get("scripts", [])
        safety  = check_pipeline_safety(scripts, allow_destructive=req.i_understand_destructive)

        if safety["blocked"]:
            return {"success": False, "blocked": True, "data": data,
                    "violations": safety["violations"], "warnings": safety["warnings"],
                    "per_script": safety["per_script"], "message": safety["message"],
                    "hint": "To override, re-submit with i_understand_destructive=true"}

        if req.edited_scripts:
            approval.edited_data = {"sql_scripts": req.edited_scripts}
            approval.status      = "edited"
        else:
            approval.status = "approved"

        approval.approved_by = current_user.id
        approval.comments    = req.comments
        approval.decided_at  = datetime.utcnow()
        db.commit()

        return {"success": True, "blocked": False, "data": data,
                "warnings": safety["warnings"], "override_used": req.i_understand_destructive,
                "message": ("✓ SQL approved (override active)" if req.i_understand_destructive
                            else "✓ SQL approved. Save and execute the pipeline.")}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/reject")
def reject_approval(req: RejectRequest, current_user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    try:
        approval = db.query(ApprovalQueue).filter(ApprovalQueue.id == req.approval_id).first()
        if not approval: raise HTTPException(404, "Approval not found")
        approval.status      = "rejected"
        approval.approved_by = current_user.id
        approval.comments    = req.comments
        approval.decided_at  = datetime.utcnow()
        db.commit()
        return {"success": True, "message": "Approval rejected.", "should_regenerate": req.regenerate}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


@app.get("/approvals/pending")
def list_pending_approvals(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    workspace = get_user_workspace(current_user.id, db)
    approvals = db.query(ApprovalQueue).filter(
        ApprovalQueue.workspace_id == workspace.get("id"),
        ApprovalQueue.status == "pending"
    ).order_by(ApprovalQueue.created_at.desc()).all()
    return {"success": True, "approvals": [
        {"id": a.id, "approval_type": a.approval_type, "title": a.title,
         "description": a.description, "risk_level": a.risk_level,
         "created_at": str(a.created_at)} for a in approvals]}


@app.get("/approvals/history")
def list_all_approvals(current_user=Depends(get_current_user),
                       db: Session = Depends(get_db), limit: int = 50):
    workspace = get_user_workspace(current_user.id, db)
    approvals = db.query(ApprovalQueue).filter(
        ApprovalQueue.workspace_id == workspace.get("id")
    ).order_by(ApprovalQueue.created_at.desc()).limit(limit).all()
    return {"success": True, "approvals": [
        {"id": a.id, "approval_type": a.approval_type, "title": a.title,
         "description": a.description, "status": a.status, "risk_level": a.risk_level,
         "comments": a.comments, "created_at": str(a.created_at),
         "decided_at": str(a.decided_at) if a.decided_at else None} for a in approvals]}


@app.get("/approvals/{approval_id}")
def get_approval(approval_id: str, current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    approval = db.query(ApprovalQueue).filter(ApprovalQueue.id == approval_id).first()
    if not approval: raise HTTPException(404, "Approval not found")
    return {"success": True, "id": approval.id, "approval_type": approval.approval_type,
            "title": approval.title, "description": approval.description,
            "proposed_data": approval.proposed_data, "edited_data": approval.edited_data,
            "context": approval.context, "status": approval.status,
            "risk_level": approval.risk_level, "comments": approval.comments,
            "created_at": str(approval.created_at),
            "decided_at": str(approval.decided_at) if approval.decided_at else None}


@app.post("/workspace/hil-mode")
def set_hil_mode(req: HILModeRequest, current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    if req.mode not in ["full_auto", "balanced", "strict"]: raise HTTPException(400, "Invalid mode")
    workspace = get_user_workspace(current_user.id, db)
    ws = db.query(Workspace).filter(Workspace.id == workspace.get("id")).first()
    if ws: ws.hil_mode = req.mode; db.commit()
    return {"success": True, "hil_mode": req.mode}


@app.get("/workspace/hil-mode")
def get_hil_mode(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    workspace = get_user_workspace(current_user.id, db)
    ws = db.query(Workspace).filter(Workspace.id == workspace.get("id")).first()
    return {"success": True, "hil_mode": ws.hil_mode if ws else "balanced"}


# ── Pipeline Save / List / Execute ────────────────────────────────────────────

@app.post("/pipeline/update-artifacts/{pipeline_id}")
def update_pipeline_artifacts(pipeline_id: str, req: UpdateArtifactsRequest,
                              current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")
    pipeline.artifacts = req.artifacts
    db.commit()
    return {"success": True, "message": "Pipeline SQL updated successfully"}


@app.post("/pipeline/save")
def save_pipeline(req: SavePipelineRequest, current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    try:
        workspace = get_user_workspace(current_user.id, db)
        pipeline  = Pipeline(
            workspace_id=workspace.get("id"), name=req.name,
            source_desc=req.source_description, raw_schema=req.raw_schema,
            biz_requirements=req.business_requirements, schedule=req.schedule,
            artifacts=req.artifacts, connector_id=req.connector_id or None,
            source_tables=req.source_tables, source_schema=req.source_schema or "raw",
            source_columns=req.source_columns or {},
            target_connector_id=req.target_connector_id or None,
            staging_schema=req.staging_schema or "staging",
            warehouse_schema=req.warehouse_schema or "warehouse"
        )
        db.add(pipeline); db.commit(); db.refresh(pipeline)

        try:
            artifacts   = req.artifacts or {}
            schema_hash = (artifacts.get("schema_hash") or
                           artifacts.get("agent_metadata", {}).get("schema_hash"))
            if schema_hash and artifacts.get("data_model"):
                save_cached_design(
                    pipeline_id=pipeline.id, schema_hash=schema_hash,
                    schema_analysis=artifacts.get("schema_analysis", {}),
                    data_model=artifacts.get("data_model", {}),
                    etl_mappings=artifacts.get("etl_mappings", {}),
                    sql_scripts=artifacts.get("sql_scripts", {}), db=db
                )
                print(f"[SchemaCache] ✓ Design cached — next run with same schema = $0 AI cost")
        except Exception as e:
            print(f"[SchemaCache] Could not save cache: {e}")

        # ── Auto-save version 1 on first pipeline save ────────────────────────
        try:
            artifacts = req.artifacts or {}
            if artifacts.get("data_model") or artifacts.get("sql_scripts"):
                version = PipelineVersion(
                    pipeline_id    = pipeline.id,
                    workspace_id   = workspace.get("id"),
                    created_by     = current_user.id,
                    version        = 1,
                    version_label  = "v1",
                    is_active      = True,
                    data_model     = artifacts.get("data_model", {}),
                    sql_scripts    = artifacts.get("sql_scripts", {}),
                    etl_mappings   = artifacts.get("etl_mappings", {}),
                    schema_hash    = artifacts.get("schema_hash", ""),
                    change_summary = "Initial pipeline design"
                )
                db.add(version); db.commit()
                print(f"[Version] ✓ v1 saved for pipeline {pipeline.id}")
        except Exception as e:
            print(f"[Version] Could not auto-save v1: {e}")

        return {"success": True, "pipeline": {"id": pipeline.id, "name": pipeline.name}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/pipeline/{pipeline_id}")
def delete_pipeline(pipeline_id: str, current_user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Delete a pipeline and its cache. Runs/logs are kept for audit trail."""
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")
    # Invalidate cache first
    try:
        invalidate_cache(pipeline_id, db)
    except Exception:
        pass
    db.delete(pipeline)
    db.commit()
    return {"success": True, "message": f"Pipeline '{pipeline.name}' deleted"}


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
             "source_tables": p.source_tables, "artifacts": p.artifacts,
             "created_at": str(p.created_at)} for p in pipelines]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pipeline/regenerate")
def regenerate_pipeline(req: RegenerateRequest, current_user=Depends(get_current_user),
                        db: Session = Depends(get_db)):
    pipeline = db.query(Pipeline).filter(Pipeline.id == req.pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")

    connector_config = None; source_schema = "raw"
    if pipeline.connector_id:
        c = db.query(Connector).filter(Connector.id == pipeline.connector_id).first()
        if c: connector_config = _cfg(c); source_schema = c.source_schema or "raw"

    combined = f"{pipeline.biz_requirements or ''}\n\nUPDATE: {req.new_requirements}".strip()

    try:
        ctx = _build_ctx(pipeline.id, "", connector_config or {}, source_schema,
                         pipeline.source_tables or [], pipeline.source_columns or {},
                         pipeline.source_desc or "", combined,
                         staging_schema=pipeline.staging_schema or "staging",
                         warehouse_schema=pipeline.warehouse_schema or "warehouse")

        DataModelAgent().run(ctx)
        SQLAgent().run(ctx)
        SQLValidationAgent().run(ctx)
        GovernanceValidationAgent().run(ctx)

        if ctx.blocked: raise HTTPException(400, f"Blocked: {ctx.blocked_reason}")

        new_artifacts = {
            "schema_analysis": ctx.data_model.get("schema_analysis", {}) if ctx.data_model else {},
            "data_model":      ctx.data_model.get("data_model", {}) if ctx.data_model else {},
            "etl_mappings":    ctx.etl_mappings or {},
            "sql_scripts":     ctx.sql_scripts or {}
        }
        pipeline.artifacts        = new_artifacts
        pipeline.biz_requirements = combined
        db.commit()
        invalidate_cache(pipeline.id, db)

        scripts = (ctx.sql_scripts or {}).get("scripts", [])
        return {"success": True, "message": f"✓ Regenerated {len(scripts)} scripts", "scripts": scripts}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))


def _run_pipeline_execution(pipeline_id: str, tables_override: list,
                             current_user, db: Session,
                             run_id: str = None) -> dict:
    """
    Core pipeline execution logic — extracted from the original synchronous
    /pipeline/execute/{id} endpoint so the exact same logic can run either:
      (a) inline within an HTTP request (the original, still-supported
          synchronous behavior — see execute_pipeline_endpoint below), or
      (b) inside a background thread for the new async execute-with-streaming
          flow (see /pipeline/execute-async/{id}), tracked via run_id in
          run_registry so the frontend can poll live logs and request a stop.

    When run_id is provided, every "Stopped at next checkpoint" opportunity
    pipeline_executor.py now supports (should_stop_fn) is wired to check
    run_registry.should_stop(run_id), and a final partial/stopped result is
    returned instead of raising, so a Stop request ends the run cleanly.
    """
    import run_registry

    def _should_stop():
        return bool(run_id) and run_registry.should_stop(run_id)

    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")
    if not pipeline.connector_id: raise HTTPException(400, "No source connector linked.")

    src = db.query(Connector).filter(Connector.id == pipeline.connector_id).first()
    if not src: raise HTTPException(404, "Source connector not found")

    tgt = src
    if pipeline.target_connector_id:
        t = db.query(Connector).filter(Connector.id == pipeline.target_connector_id).first()
        if t: tgt = t
    elif src.connector_type == "duckdb":
        # DuckDB is file source only — auto-find PostgreSQL target
        pg_conn = db.query(Connector).filter(
            Connector.workspace_id == src.workspace_id,
            Connector.connector_type == "postgres",
            Connector.is_active == True
        ).first()
        if pg_conn:
            tgt = pg_conn
            print(f"[Pipeline] DuckDB source → auto-selected PostgreSQL target: {pg_conn.name}")
        else:
            raise HTTPException(400,
                "DuckDB source requires a PostgreSQL target connector. Please add one in Connectors.")

    source_config    = _cfg(src)
    target_config    = _cfg(tgt)
    source_schema    = src.source_schema or pipeline.source_schema or "raw"
    staging_schema   = pipeline.staging_schema or "staging"
    warehouse_schema = pipeline.warehouse_schema or "warehouse"
    workspace        = get_user_workspace(current_user.id, db)
    workspace_id     = workspace.get("id", "")

    # Log the DB types being used
    src_type = source_config.get("connector_type", "postgres").upper()
    tgt_type = target_config.get("connector_type", "postgres").upper()
    print(f"[Pipeline] Source: {src_type} → Target: {tgt_type}")

    source_tables = tables_override if tables_override else (pipeline.source_tables or [])

    if not source_tables:
        try:
            tr            = list_all_tables_by_schema(source_config, source_schema=source_schema)
            raw_tables    = tr.get("schemas", {}).get("raw", [])
            source_tables = [t["name"] for t in raw_tables]
        except Exception as e:
            raise HTTPException(400, f"Could not auto-discover source tables: {e}")

    if not source_tables: raise HTTPException(400, "No source tables found.")

    all_scripts = pipeline.artifacts.get("sql_scripts", {}).get("scripts", [])
    wh_scripts  = [s for s in all_scripts
                   if not ("staging" in s.get("label","").lower()
                           and s.get("name","").lower().startswith("stg_"))]

    # Safety check (PostgreSQL targets only)
    if tgt_type in ("POSTGRES", "POSTGRESQL", "REDSHIFT"):
        safety = check_pipeline_safety(wh_scripts, allow_destructive=False)
        if safety["blocked"]:
            raise HTTPException(400, {"error": "Dangerous SQL blocked",
                                      "violations": safety["violations"], "message": safety["message"]})

    if _should_stop():
        print("[Pipeline] 🛑 Stop requested before execution began — nothing was run.")
        return {"success": False, "stopped": True, "staging": None, "warehouse": None,
                "message": "Stopped before execution began."}

    ctx = _build_ctx(pipeline_id, workspace_id, source_config, source_schema,
                     source_tables, pipeline.source_columns or {},
                     pipeline.source_desc or "", pipeline.biz_requirements or "",
                     target_config=target_config, staging_schema=staging_schema,
                     warehouse_schema=warehouse_schema)
    ctx.sql_scripts = pipeline.artifacts.get("sql_scripts", {})

    print(f"[Pipeline] Starting extract: {len(source_tables)} tables → {staging_schema}")
    etl_result = ETLAgent().run(ctx)

    if not etl_result.success:
        failed_run_id = f"{pipeline_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        error_msg     = etl_result.error or "extract failed"
        try:
            run = PipelineRun(run_id=failed_run_id, pipeline_id=pipeline_id,
                              workspace_id=workspace_id, status="failed",
                              started_at=datetime.utcnow(), ended_at=datetime.utcnow(),
                              rows_loaded=0, log="\n".join(etl_result.logs + [f"Error: {error_msg}"]))
            db.add(run); db.commit()
        except Exception as e:
            print(f"[Pipeline] Could not save failed run: {e}")
        return {"success": False, "staging": {"success": False, "error": error_msg},
                "warehouse": None, "message": f"✗ Pipeline aborted: {error_msg}"}

    staging_result = ctx.staging_result or {}

    if _should_stop():
        print("[Pipeline] 🛑 Stop requested after extract — skipping warehouse load.")
        return {"success": False, "stopped": True, "staging": staging_result,
                "warehouse": None, "message": "Stopped after extract — staging data is loaded "
                                               "but warehouse tables were not built this run."}

    # ── QualityAgent — PRE-LOAD (scan staging, quarantine bad rows) ───────────
    print(f"[Pipeline] Running QualityAgent (pre-load)...")
    QualityAgent().run(ctx)
    quality_data   = ctx.quality_result or {}
    quality_score  = quality_data.get("score", 100)
    quality_status = quality_data.get("status", "passed")
    quality_emoji  = quality_data.get("emoji", "✅")
    removed        = quality_data.get("total_removed", 0)
    print(f"[Pipeline] {quality_emoji} Pre-load quality: {quality_score}% "
          f"({quality_status}){f' — {removed} bad rows quarantined' if removed else ''}")

    # ── Auto-create intermediate staging tables BEFORE ExecutionAgent ────────
    # Generic: detects missing staging tables from SQL scripts, creates them
    # from raw staging via SELECT DISTINCT using data model column hints
    try:
        from pipeline_executor import _auto_create_intermediate_staging
        data_model_obj = pipeline.artifacts.get("data_model", {})
        _auto_create_intermediate_staging(
            target_config  = target_config,
            staging_schema = staging_schema,
            sql_scripts    = wh_scripts,
            data_model     = data_model_obj,
            log            = lambda msg: print(f"[StagingBuilder] {msg}")
        )
    except Exception as e:
        print(f"[StagingBuilder] Warning: {e}")

    if _should_stop():
        print("[Pipeline] 🛑 Stop requested before warehouse load — staging built, "
              "warehouse not loaded.")
        return {"success": False, "stopped": True, "staging": staging_result,
                "warehouse": None, "message": "Stopped before warehouse load."}

    # ── ExecutionAgent — loads ONLY clean rows ────────────────────────────────
    ctx.sql_scripts = {"scripts": wh_scripts}
    # Pass data model so StagingBuilder can create precise intermediate tables
    if not ctx.data_model:
        ctx.data_model = {"data_model": pipeline.artifacts.get("data_model", {})}
    ExecutionAgent().run(ctx)
    exec_result = ctx.execution_result or {}

    failed_scripts = [s for s in exec_result.get("scripts", []) if not s.get("success", True)]
    if failed_scripts and not _should_stop():
        print(f"[Pipeline] {len(failed_scripts)} scripts failed — activating RecoveryAgent")
        RecoveryAgent().run(ctx)
        if ctx.recovery_result and ctx.recovery_result.get("recovered", 0) > 0:
            print("[Pipeline] Recovery fixed scripts — retrying execution")
            ExecutionAgent().run(ctx)
            exec_result = ctx.execution_result or {}

    actual_rows = _recount_warehouse_rows(target_config, warehouse_schema)
    print(f"[Pipeline] ✓ Total warehouse rows (cumulative): {actual_rows}")

    # Per-table breakdown — a single combined total hides which specific
    # table has an unexpected count (e.g. a fact table too high/low vs its
    # dimensions). Print each warehouse table's row count individually.
    try:
        table_names = [s.get("name") for s in wh_scripts if s.get("name")]
        if table_names:
            from pipeline_executor import _pg_connect, _is_pg
            if _is_pg(target_config):
                conn = _pg_connect(target_config)
                cur  = conn.cursor()
                counts = []
                for tbl in table_names:
                    try:
                        cur.execute(f'SELECT COUNT(*) FROM "{warehouse_schema}"."{tbl}"')
                        counts.append((tbl, cur.fetchone()[0]))
                    except Exception:
                        pass
                cur.close(); conn.close()
                if counts:
                    breakdown = ", ".join(f"{t}={c:,}" for t, c in counts)
                    print(f"[Pipeline] 📊 Per-table counts — {breakdown}")
    except Exception as e:
        print(f"[Pipeline] Could not compute per-table breakdown: {e}")

    # Use rows inserted THIS run from execution result
    this_run_rows = exec_result.get("rows", exec_result.get("total_rows", 0))
    if not this_run_rows:
        this_run_rows = actual_rows
    print(f"[Pipeline] ✓ Rows loaded this run: {this_run_rows}")
    if ctx.execution_result:
        ctx.execution_result["total_rows"] = this_run_rows
    exec_result["total_rows"] = this_run_rows

    AnalyticsAgent().run(ctx)

    if run_id and run_registry.should_stop(run_id):
        print("[Pipeline] 🛑 Stop was requested during this run — warehouse load completed "
              "before the stop took effect (no checkpoint hit it in time).")

    return {"success": exec_result.get("success", False), "staging": staging_result,
            "warehouse": exec_result, "analytics": ctx.analytics_result,
            "quality": quality_data,
            "message": (f"Pipeline executed. {src.name} [{src_type}]/{source_schema} → "
                        f"{tgt.name} [{tgt_type}]/{warehouse_schema}. "
                        f"Rows: {actual_rows}. Quality: {quality_emoji} {quality_score}%"
                        + (f" ({removed} bad rows quarantined)" if removed else ""))}


@app.post("/pipeline/execute/{pipeline_id}")
def execute_pipeline_endpoint(pipeline_id: str, req: ExecuteOverrideRequest = None,
                              current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Synchronous execution — blocks until the pipeline finishes (original
    behavior, unchanged). For long-running pipelines, prefer
    /pipeline/execute-async/{id} which returns immediately with a run_id
    and supports live log streaming + a Stop control.
    """
    tables_override = req.tables_override if req else []
    return _run_pipeline_execution(pipeline_id, tables_override, current_user, db)


_stdout_dispatcher_lock = None
_thread_run_map = {}  # threading.get_ident() -> run_id, for routing print() output

def _ensure_global_stdout_dispatcher():
    """
    Install a single process-wide stdout wrapper, once. It looks up which
    run_id (if any) is associated with the CURRENT thread for every write,
    so concurrent background pipeline runs each get only their own log
    lines, not each other's — sys.stdout itself is only ever swapped this
    one time, regardless of how many runs start afterward.
    """
    import sys, io, threading
    global _stdout_dispatcher_lock
    if _stdout_dispatcher_lock is not None:
        return  # already installed
    _stdout_dispatcher_lock = threading.Lock()

    import run_registry
    real_stdout = sys.stdout

    class _DispatchWriter(io.TextIOBase):
        def __init__(self):
            self._buffers = {}  # thread_ident -> partial-line buffer

        def write(self, s):
            real_stdout.write(s)
            ident = threading.get_ident()
            run_id = _thread_run_map.get(ident)
            if run_id:
                buf = self._buffers.get(ident, "") + s
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if line.strip():
                        run_registry.append_log(run_id, line)
                self._buffers[ident] = buf
            return len(s)

        def flush(self):
            real_stdout.flush()

    sys.stdout = _DispatchWriter()


def _register_thread_run(thread_ident: int, run_id: str) -> None:
    _thread_run_map[thread_ident] = run_id


def _unregister_thread_run(thread_ident: int) -> None:
    _thread_run_map.pop(thread_ident, None)


@app.post("/pipeline/execute-async/{pipeline_id}")
def execute_pipeline_async(pipeline_id: str, req: ExecuteOverrideRequest = None,
                           current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Starts pipeline execution in a background thread and returns
    immediately with a run_id. The frontend should:
      1. Connect to GET /pipeline/execute-async/{run_id}/stream for live logs
      2. Optionally POST /pipeline/execute-async/{run_id}/stop to cancel
      3. Poll GET /pipeline/execute-async/{run_id}/status for the final result

    A plain Python thread (not asyncio) is used because the execution path
    uses blocking DB drivers (psycopg2, duckdb) throughout — a real asyncio
    background task wouldn't actually free up the event loop here.
    """
    import threading, sys, io, contextlib
    import run_registry

    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")

    run_registry.cleanup_old_runs()
    run_id = run_registry.create_run(pipeline_id, pipeline.name)
    tables_override = req.tables_override if req else []

    # Each background thread needs its own DB session — the request-scoped
    # `db` from Depends(get_db) is closed once this endpoint returns, which
    # happens immediately (before the thread's work is done).
    from database import SessionLocal

    # IMPORTANT: sys.stdout is process-global, not thread-local. If two
    # pipelines run concurrently and each background thread independently
    # calls contextlib.redirect_stdout, their writes interleave into
    # whichever writer object happens to be assigned to sys.stdout at that
    # instant — log lines from run A leak into run B's buffer and vice
    # versa. To avoid this, stdout is swapped exactly ONCE for the whole
    # process (installed lazily, the first time any async run starts) by a
    # single dispatcher writer that looks up the CURRENT thread's run_id
    # via threading.local() and routes each line to the correct run only.
    _ensure_global_stdout_dispatcher()

    def _worker():
        # Register THIS thread's ident so the stdout dispatcher routes our
        # print() calls into the correct run's log buffer — must happen here
        # inside the worker, not in the request handler, because each thread
        # has a different ident and the dispatcher keys on threading.get_ident().
        _register_thread_run(threading.get_ident(), run_id)
        thread_db = SessionLocal()
        try:
            result = _run_pipeline_execution(
                pipeline_id, tables_override, current_user, thread_db, run_id=run_id
            )
            run = run_registry.get_run(run_id)
            final_status = "stopped" if (run and run.get("cancel_requested")) or result.get("stopped") \
                           else ("success" if result.get("success") else "failed")
            run_registry.finish_run(run_id, final_status, result=result)
            # Refresh warehouse knowledge graph after successful pipeline run
            if final_status == "success":
                try:
                    from warehouse_knowledge import refresh_warehouse_knowledge
                    refresh_warehouse_knowledge(thread_db)
                except Exception as _ke:
                    print(f"[Knowledge] Refresh warning: {_ke}")
        except Exception as e:
            import traceback
            err_text = f"{e}\n{traceback.format_exc()}"
            run_registry.append_log(run_id, f"✗ ERROR: {err_text}")
            run_registry.finish_run(run_id, "failed", error=str(e))
        finally:
            thread_db.close()
            _unregister_thread_run(threading.get_ident())

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    return {"success": True, "run_id": run_id, "pipeline_id": pipeline_id,
            "message": "Pipeline execution started in the background. "
                       "Connect to the stream endpoint for live logs."}


@app.get("/pipeline/execute-async/{run_id}/stream")
def stream_pipeline_logs(run_id: str):
    """
    Server-Sent Events stream of live execution logs for a background run.
    Emits one `data: <line>` event per new log line as it's produced, and
    a final `event: done` with the run's terminal status when finished.
    """
    import run_registry
    import time
    from fastapi.responses import StreamingResponse

    def event_generator():
        offset = 0
        idle_polls = 0
        while True:
            run = run_registry.get_run(run_id)
            if run is None:
                yield "event: error\ndata: run not found\n\n"
                return

            new_lines, offset = run_registry.get_logs_since(run_id, offset)
            for line in new_lines:
                # SSE data fields can't contain raw newlines — escape any
                # embedded newlines within a single log line.
                safe_line = line.replace("\n", "\\n")
                yield f"data: {safe_line}\n\n"
                idle_polls = 0

            if run["status"] in ("success", "failed", "stopped"):
                import json
                payload = {
                    "status":  run["status"],
                    "error":   run.get("error"),
                    "message": (run.get("result") or {}).get("message", "")
                }
                yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                return

            idle_polls += 1
            time.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/pipeline/execute-async/{run_id}/stop")
def stop_pipeline_run(run_id: str, current_user=Depends(get_current_user)):
    """
    Request cancellation of a running background execution. This is
    best-effort: the running code checks for the stop signal between
    discrete steps (per warehouse script, per extract chunk, between
    major pipeline phases) — it can't interrupt a single SQL statement
    that's already executing against the database, so a Stop request
    during e.g. a long-running fact table JOIN will take effect once
    that statement completes, not instantly.
    """
    import run_registry
    ok = run_registry.request_stop(run_id)
    if not ok:
        run = run_registry.get_run(run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        raise HTTPException(400, f"Run is already {run['status']} — cannot stop.")
    return {"success": True, "message": "Stop requested — execution will halt at its next checkpoint."}


@app.get("/pipeline/execute-async/{run_id}/status")
def get_pipeline_run_status(run_id: str, current_user=Depends(get_current_user)):
    """Poll the current status/result of a background run (non-streaming)."""
    import run_registry
    run = run_registry.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return {"success": True, "run_id": run_id, "pipeline_id": run["pipeline_id"],
            "status": run["status"], "started_at": run["started_at"],
            "ended_at": run["ended_at"], "result": run["result"], "error": run["error"],
            "log_count": len(run["logs"])}


@app.get("/pipeline/runs/{pipeline_id}")
def get_pipeline_runs(pipeline_id: str, current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    try:
        runs = db.query(PipelineRun).filter(PipelineRun.pipeline_id == pipeline_id
            ).order_by(PipelineRun.started_at.desc()).limit(20).all()
        return {"success": True, "runs": [
            {"id": r.id, "run_id": r.run_id, "status": r.status,
             "started_at": str(r.started_at), "ended_at": str(r.ended_at),
             "rows_loaded": r.rows_loaded, "log": r.log} for r in runs]}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


@app.get("/pipeline/runs")
def list_all_pipeline_runs(current_user=Depends(get_current_user),
                           db: Session = Depends(get_db), limit: int = 100):
    try:
        workspace = get_user_workspace(current_user.id, db)
        runs = db.query(PipelineRun, Pipeline).outerjoin(
            Pipeline, Pipeline.id == PipelineRun.pipeline_id
        ).filter(PipelineRun.workspace_id == workspace.get("id")
        ).order_by(PipelineRun.started_at.desc()).limit(limit).all()
        return {"success": True, "runs": [
            {"id": r.PipelineRun.id, "run_id": r.PipelineRun.run_id,
             "pipeline_id": r.PipelineRun.pipeline_id,
             "pipeline_name": r.Pipeline.name if r.Pipeline else "(deleted)",
             "status": r.PipelineRun.status,
             "started_at": str(r.PipelineRun.started_at) if r.PipelineRun.started_at else None,
             "ended_at":   str(r.PipelineRun.ended_at)   if r.PipelineRun.ended_at   else None,
             "rows_loaded": r.PipelineRun.rows_loaded or 0,
             "log_preview": ((r.PipelineRun.log[:200] + '...')
                             if r.PipelineRun.log and len(r.PipelineRun.log) > 200
                             else (r.PipelineRun.log or ""))} for r in runs]}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


@app.get("/pipeline/run/{run_id}")
def get_pipeline_run_detail(run_id: str, current_user=Depends(get_current_user),
                            db: Session = Depends(get_db)):
    try:
        run = db.query(PipelineRun).filter(PipelineRun.run_id == run_id).first()
        if not run: raise HTTPException(404, "Run not found")
        pipeline      = db.query(Pipeline).filter(Pipeline.id == run.pipeline_id).first()
        pipeline_name = pipeline.name if pipeline else "(deleted)"
        from database import RecoveryLog
        recoveries = db.query(RecoveryLog).filter(RecoveryLog.pipeline_run_id == run_id
            ).order_by(RecoveryLog.created_at.asc()).all()
        return {"success": True,
                "run": {"id": run.id, "run_id": run.run_id, "pipeline_id": run.pipeline_id,
                        "pipeline_name": pipeline_name, "status": run.status,
                        "started_at": str(run.started_at) if run.started_at else None,
                        "ended_at":   str(run.ended_at)   if run.ended_at   else None,
                        "rows_loaded": run.rows_loaded or 0, "log": run.log or "",
                        "log_lines": (run.log or "").split("\n") if run.log else []},
                "recoveries": [{"id": r.id, "failed_script": r.failed_script,
                                "error_message": r.error_message, "action_taken": r.action_taken,
                                "fix_method": r.fix_method, "recovered": r.recovered,
                                "summary": r.summary,
                                "started_at": str(r.started_at) if r.started_at else None,
                                "ended_at":   str(r.ended_at)   if r.ended_at   else None}
                               for r in recoveries]}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


# ── Schema Cache endpoints ────────────────────────────────────────────────────

@app.post("/pipeline/cache/invalidate/{pipeline_id}")
def invalidate_pipeline_cache(pipeline_id: str, current_user=Depends(get_current_user),
                               db: Session = Depends(get_db)):
    success = invalidate_cache(pipeline_id, db)
    return {"success": success, "message": "Cache invalidated — next ETL Agent run will regenerate design"}


@app.get("/pipeline/cache/status/{pipeline_id}")
def get_pipeline_cache_status(pipeline_id: str, current_user=Depends(get_current_user),
                               db: Session = Depends(get_db)):
    status = get_cache_status(pipeline_id, db)
    return {"success": True, **status}


# ── SQL execution ─────────────────────────────────────────────────────────────

@app.post("/sql/run")
def run_sql(req: SQLRunRequest, current_user=Depends(get_current_user),
            db: Session = Depends(get_db)):
    try:
        safety = check_sql_safety(req.sql, allow_destructive=False, script_name="ad-hoc")
        if safety["blocked"]:
            raise HTTPException(400, {"error": "Dangerous SQL blocked",
                                      "violations": safety["violations"], "message": safety["message"]})
        if req.connector_id:
            import psycopg2, psycopg2.extras
            c = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if not c: raise HTTPException(404, "Connector not found")
            conn = psycopg2.connect(host=c.host, port=c.port, dbname=c.database_name,
                                     user=c.username, password=c.password)
            cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(req.sql)
            rows    = cur.fetchall() if cur.description else []
            columns = [d[0] for d in cur.description] if cur.description else []
            conn.close()
            import math
            def _safe(v):
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    return None
                return v
            return {"success": True, "columns": columns,
                    "rows": [[_safe(v) for v in r.values()] for r in rows], "row_count": len(rows)}
        else:
            con    = duckdb.connect(os.getenv("DUCKDB_PATH", "./aibridge.duckdb"))
            result = con.execute(req.sql).fetchdf(); con.close()
            return {"success": True, "columns": list(result.columns),
                    "rows": result.values.tolist(), "row_count": len(result)}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))


@app.post("/sql/check-safety")
def check_sql_safety_endpoint(req: SQLRunRequest, current_user=Depends(get_current_user)):
    return check_sql_safety(req.sql, allow_destructive=False, script_name="ad-hoc")


# ── NL to SQL ─────────────────────────────────────────────────────────────────

@app.post("/nl/to-sql")
def nl_to_sql(req: NLToSQLRequest, current_user=Depends(get_current_user),
              db: Session = Depends(get_db)):
    try:
        schema_text = ""
        warehouse_schema = "warehouse"  # default

        if req.pipeline_id:
            # Use pipeline's actual target warehouse schema
            pipeline = db.query(Pipeline).filter(Pipeline.id == req.pipeline_id).first()
            if pipeline:
                warehouse_schema = getattr(pipeline, 'warehouse_schema', None) or                                    (pipeline.artifacts or {}).get('warehouse_schema', 'warehouse')
                tgt_conn_id = pipeline.target_connector_id or pipeline.connector_id
                tgt_conn = db.query(Connector).filter(Connector.id == tgt_conn_id).first()
                if tgt_conn:
                    schema_text = get_full_schema_for_ai(_cfg(tgt_conn), source_schema=warehouse_schema)
                    print(f"[NL2SQL] Pipeline mode — schema: {warehouse_schema}")

        if not schema_text and req.connector_id:
            c = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if c:
                schema_text = get_full_schema_for_ai(_cfg(c), source_schema=warehouse_schema)
                print(f"[NL2SQL] Connector mode — schema: {warehouse_schema}")

        from ai_provider import ask_ai
        prompt = f"""You are a PostgreSQL expert. Your ONLY job is to return a JSON object containing a SQL query.

WAREHOUSE SCHEMA:
{schema_text if schema_text else f"(use {warehouse_schema}.fact_* and {warehouse_schema}.dim_* tables)"}

STRICT RULES:
1. Your ENTIRE response must be a single JSON object, nothing else, no explanation, no markdown
2. Format: {{"sql": "SELECT ..."}}
3. Use ONLY exact table and column names from the schema above
4. Always prefix tables with schema name: use exact schema.table_name as shown in schema above
5. JOIN dimension tables to the fact table using _key columns
6. Only SELECT statements
7. Always add LIMIT 100 at the end

EXAMPLE OUTPUT for "total sales by city":
{{"sql": "SELECT d.city, SUM(f.amount) AS total FROM {warehouse_schema}.fact_sales f JOIN {warehouse_schema}.dim_location d ON f.location_key = d.location_key GROUP BY d.city ORDER BY total DESC LIMIT 100"}}

USER QUESTION: {req.question}

Respond with ONLY the JSON object, nothing else:"""

        result = ask_ai(prompt, agent_name="AnalyticsAgent")
        sql    = result.get("sql", "").strip().replace("```sql","").replace("```","").strip()

        if not sql:
            return {"success": False, "error": "AI did not return SQL. Try rephrasing more specifically, e.g. \"average price grouped by transmission type\".", "sql": ""}

        safety_check = check_sql_safety(sql, allow_destructive=False)
        return {"success": True, "sql": sql, "question": req.question,
                "safety": {"blocked": safety_check["blocked"], "warnings": safety_check["warnings"],
                           "violations": safety_check["violations"]}}
    except Exception as e:
        return {"success": False, "error": str(e), "sql": ""}


class RefineSQLRequest(BaseModel):
    current_sql:    str
    refinement:     str
    connector_id:   str = ""
    history:        list = []   # list of {"instruction": str, "sql": str} for context


@app.post("/nl/refine-sql")
def refine_sql(req: RefineSQLRequest, current_user=Depends(get_current_user),
               db: Session = Depends(get_db)):
    """
    Refine an existing SQL query with a natural language instruction.
    Sends the current SQL + the refinement instruction to the AI, which
    returns an updated SQL with the condition appended or modified.
    The history chain is included so the AI understands the full context
    of what the user has been building up iteratively.
    """
    try:
        schema_text = ""
        warehouse_schema = "warehouse"  # default

        if req.pipeline_id:
            # Use pipeline's actual target warehouse schema
            pipeline = db.query(Pipeline).filter(Pipeline.id == req.pipeline_id).first()
            if pipeline:
                warehouse_schema = getattr(pipeline, 'warehouse_schema', None) or                                    (pipeline.artifacts or {}).get('warehouse_schema', 'warehouse')
                tgt_conn_id = pipeline.target_connector_id or pipeline.connector_id
                tgt_conn = db.query(Connector).filter(Connector.id == tgt_conn_id).first()
                if tgt_conn:
                    schema_text = get_full_schema_for_ai(_cfg(tgt_conn), source_schema=warehouse_schema)
                    print(f"[NL2SQL] Pipeline mode — schema: {warehouse_schema}")

        if not schema_text and req.connector_id:
            c = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if c:
                schema_text = get_full_schema_for_ai(_cfg(c), source_schema=warehouse_schema)
                print(f"[NL2SQL] Connector mode — schema: {warehouse_schema}")

        history_text = ""
        if req.history:
            history_text = "\n\nREFINEMENT HISTORY (what the user has already asked for):\n"
            for i, h in enumerate(req.history, 1):
                history_text += f"  Step {i}: {h.get('instruction', '')}\n"

        from ai_provider import ask_ai
        prompt = f"""You are a SQL expert. The user has an existing PostgreSQL query and wants to refine it.

WAREHOUSE SCHEMA:
{schema_text if schema_text else f"(use {warehouse_schema}.fact_* and {warehouse_schema}.dim_* tables)"}

CURRENT SQL:
{req.current_sql}
{history_text}
NEW REFINEMENT INSTRUCTION: {req.refinement}

RULES:
1. Return ONLY JSON: {{"sql": "SELECT ...", "explanation": "what changed"}}
2. Modify the CURRENT SQL to incorporate the new refinement — do NOT start from scratch
3. Keep all existing JOINs, columns, and conditions unless the refinement explicitly changes them
4. Use ONLY exact column names from the schema above
5. ONLY SELECT statements — no INSERT, UPDATE, DELETE, DROP
6. Common refinement patterns:
   - "only X" / "filter by X" → add WHERE or AND clause
   - "top N" / "limit to N" → change or add LIMIT N
   - "sort by X" / "order by X" → add or change ORDER BY
   - "group by X" → add or change GROUP BY
   - "exclude X" / "remove X" → add WHERE NOT or AND ... != condition
   - "add X column" → add column to SELECT
   - "between X and Y" / "from X to Y" → add BETWEEN or >= <= condition
7. The explanation should be a short human-readable description of what changed (1 sentence)

Refined SQL must be a complete, valid, runnable PostgreSQL SELECT statement."""

        result = ask_ai(prompt)
        sql         = result.get("sql", "").strip().replace("```sql","").replace("```","").strip()
        explanation = result.get("explanation", req.refinement)

        if not sql:
            return {"success": False, "error": "AI could not refine the SQL. Try rephrasing.", "sql": ""}

        safety_check = check_sql_safety(sql, allow_destructive=False)
        if safety_check["blocked"]:
            return {"success": False,
                    "error": f"Refined SQL blocked by safety guard: {safety_check['message']}",
                    "sql": ""}

        return {"success": True, "sql": sql, "explanation": explanation,
                "refinement": req.refinement}
    except Exception as e:
        return {"success": False, "error": str(e), "sql": ""}


# ── Report Export (CSV / Excel / PDF) ────────────────────────────────────────

class ReportExportRequest(BaseModel):
    sql:         str
    connector_id: str = ""
    format:      str = "csv"   # csv | excel | pdf
    report_name: str = "report"
    question:    str = ""


@app.post("/report/export")
def export_report(req: ReportExportRequest, current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """
    Execute SQL against the warehouse and return the results as a
    downloadable file in the requested format (CSV, Excel, or PDF).
    """
    from fastapi.responses import Response
    import psycopg2, psycopg2.extras

    if not req.connector_id:
        raise HTTPException(400, "connector_id is required for report export")

    c = db.query(Connector).filter(Connector.id == req.connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")

    try:
        conn = psycopg2.connect(host=c.host, port=c.port, dbname=c.database_name,
                                 user=c.username, password=c.password)
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(req.sql)
        rows_raw = cur.fetchall() if cur.description else []
        columns  = [d[0] for d in cur.description] if cur.description else []
        conn.close()
        rows = [list(r.values()) for r in rows_raw]
    except Exception as e:
        raise HTTPException(400, f"SQL execution failed: {e}")

    from report_export import export_to_csv, export_to_excel, export_to_pdf

    fmt  = req.format.lower()
    name = req.report_name or "report"

    if fmt == "excel":
        data         = export_to_excel(columns, rows, name, req.sql, req.question)
        media_type   = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename     = f"{name.replace(' ', '_')}.xlsx"
    elif fmt == "pdf":
        data         = export_to_pdf(columns, rows, name, req.sql, req.question)
        media_type   = "application/pdf"
        filename     = f"{name.replace(' ', '_')}.pdf"
    else:
        data         = export_to_csv(columns, rows, name)
        media_type   = "text/csv"
        filename     = f"{name.replace(' ', '_')}.csv"

    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ── Report Scheduling ─────────────────────────────────────────────────────────

class ReportScheduleRequest(BaseModel):
    report_id:    str            # client-side report id (from localStorage)
    report_name:  str
    sql:          str
    question:     str = ""
    connector_id: str
    schedule:     str            # same format as pipeline schedules
    schedule_config: dict = {}
    export_format: str = "csv"   # csv | excel | pdf
    export_path:  str = ""       # optional server-side save path


# In-memory report schedule store (same pattern as run_registry)
# Persisted to a small SQLite file so schedules survive restarts.
_REPORT_SCHEDULE_DB = os.path.join(
    os.path.dirname(os.getenv("COST_DB_PATH", "./aibridge_costs.db")),
    "aibridge_report_schedules.db"
)

def _ensure_report_schedule_db():
    import sqlite3
    con = sqlite3.connect(_REPORT_SCHEDULE_DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS report_schedules (
            id            TEXT PRIMARY KEY,
            report_name   TEXT,
            sql           TEXT,
            question      TEXT,
            connector_id  TEXT,
            schedule      TEXT,
            schedule_config TEXT,
            export_format TEXT DEFAULT 'csv',
            export_path   TEXT DEFAULT '',
            workspace_id  TEXT,
            created_by    TEXT,
            created_at    TEXT,
            last_run_at   TEXT,
            last_run_rows INTEGER DEFAULT 0,
            last_run_status TEXT DEFAULT 'pending',
            is_active     INTEGER DEFAULT 1
        )
    """)
    con.commit(); con.close()


@app.post("/report/schedule")
def schedule_report(req: ReportScheduleRequest, current_user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Save a report schedule — the scheduler will execute the SQL on the given cadence."""
    import sqlite3, uuid
    workspace    = get_user_workspace(current_user.id, db)
    workspace_id = workspace.get("id", "")
    _ensure_report_schedule_db()

    schedule_id = req.report_id or str(uuid.uuid4())
    con = sqlite3.connect(_REPORT_SCHEDULE_DB)
    con.execute("""
        INSERT OR REPLACE INTO report_schedules
          (id, report_name, sql, question, connector_id, schedule, schedule_config,
           export_format, export_path, workspace_id, created_by, created_at, is_active)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)
    """, (schedule_id, req.report_name, req.sql, req.question, req.connector_id,
          req.schedule, json.dumps(req.schedule_config), req.export_format,
          req.export_path, workspace_id, current_user.id,
          datetime.utcnow().isoformat()))
    con.commit(); con.close()

    return {"success": True, "schedule_id": schedule_id,
            "message": f"✓ Report '{req.report_name}' scheduled ({req.schedule})"}


@app.get("/report/schedules")
def list_report_schedules(current_user=Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """List all active report schedules for this workspace."""
    import sqlite3
    workspace    = get_user_workspace(current_user.id, db)
    workspace_id = workspace.get("id", "")
    _ensure_report_schedule_db()
    con = sqlite3.connect(_REPORT_SCHEDULE_DB)
    cur = con.cursor()
    cur.execute("""
        SELECT id, report_name, question, schedule, export_format,
               last_run_at, last_run_rows, last_run_status, is_active, created_at
        FROM report_schedules WHERE workspace_id = ? AND is_active = 1
        ORDER BY created_at DESC
    """, (workspace_id,))
    rows = cur.fetchall(); con.close()
    return {"success": True, "schedules": [
        {"id": r[0], "report_name": r[1], "question": r[2], "schedule": r[3],
         "export_format": r[4], "last_run_at": r[5], "last_run_rows": r[6],
         "last_run_status": r[7], "is_active": bool(r[8]), "created_at": r[9]}
        for r in rows
    ]}


@app.delete("/report/schedule/{schedule_id}")
def delete_report_schedule(schedule_id: str, current_user=Depends(get_current_user)):
    """Remove a report schedule."""
    import sqlite3
    _ensure_report_schedule_db()
    con = sqlite3.connect(_REPORT_SCHEDULE_DB)
    con.execute("UPDATE report_schedules SET is_active=0 WHERE id=?", (schedule_id,))
    con.commit(); con.close()
    return {"success": True, "message": "Report schedule removed"}


@app.post("/report/run-now/{schedule_id}")
def run_report_now(schedule_id: str, current_user=Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Manually trigger a scheduled report — executes SQL and returns results."""
    import sqlite3, psycopg2, psycopg2.extras
    _ensure_report_schedule_db()
    con = sqlite3.connect(_REPORT_SCHEDULE_DB)
    cur = con.cursor()
    cur.execute("SELECT sql, connector_id, report_name, question, export_format FROM report_schedules WHERE id=?",
                (schedule_id,))
    row = cur.fetchone(); con.close()
    if not row: raise HTTPException(404, "Report schedule not found")
    sql, connector_id, report_name, question, export_format = row

    c = db.query(Connector).filter(Connector.id == connector_id).first()
    if not c: raise HTTPException(404, "Connector not found")

    try:
        pg_conn = psycopg2.connect(host=c.host, port=c.port, dbname=c.database_name,
                                    user=c.username, password=c.password)
        pg_cur  = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        pg_cur.execute(sql)
        rows_raw = pg_cur.fetchall() if pg_cur.description else []
        columns  = [d[0] for d in pg_cur.description] if pg_cur.description else []
        pg_conn.close()
        rows = [list(r.values()) for r in rows_raw]
    except Exception as e:
        raise HTTPException(400, f"Report SQL failed: {e}")

    # Update last run metadata
    import sqlite3 as _sqlite3
    con2 = _sqlite3.connect(_REPORT_SCHEDULE_DB)
    con2.execute("""
        UPDATE report_schedules SET last_run_at=?, last_run_rows=?, last_run_status='success'
        WHERE id=?
    """, (datetime.utcnow().isoformat(), len(rows), schedule_id))
    con2.commit(); con2.close()

    return {"success": True, "columns": columns,
            "rows": rows, "row_count": len(rows),
            "report_name": report_name, "ran_at": datetime.utcnow().isoformat()}


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
        pipeline  = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
        if not pipeline: raise HTTPException(404, "Pipeline not found")
        scripts   = pipeline.artifacts.get("sql_scripts", {}).get("scripts", [])
        workspace = get_user_workspace(current_user.id, db)
        return run_pipeline_now(pipeline_id, pipeline.name, scripts, workspace.get("id",""))
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


# ── Schema Evolution ──────────────────────────────────────────────────────────

@app.post("/schema/evolve")
def evolve_schema(req: SchemaEvolutionRequest, current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    try:
        result = generate_schema_evolution(req.table_name, req.existing_columns,
                                            req.new_column, req.column_type, req.user_instruction)
        try:
            from database import SchemaChange
            workspace = get_user_workspace(current_user.id, db)
            db.add(SchemaChange(workspace_id=workspace.get("id"), table_name=req.table_name,
                                 change_type="ADD_COLUMN", column_name=req.new_column, details=result))
            db.commit()
        except Exception: pass
        return {"success": True, "data": result}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


# ── AI Provider ───────────────────────────────────────────────────────────────

@app.get("/provider")
def get_provider(current_user=Depends(get_current_user)):
    import ai_provider
    return {"active": ai_provider.PROVIDER,
            "available": ["ollama", "claude", "openai", "gemini", "deepseek"]}

@app.post("/provider/set")
def set_provider(req: ProviderRequest, current_user=Depends(get_current_user)):
    import ai_provider
    if req.provider not in ["ollama", "claude", "openai", "gemini", "deepseek"]:
        raise HTTPException(400, "Invalid provider. Supported: ollama, claude, openai, gemini, deepseek")
    ai_provider.PROVIDER = req.provider
    if req.api_key:
        env_map = {
            "claude":    "ANTHROPIC_API_KEY",
            "openai":    "OPENAI_API_KEY",
            "gemini":    "GEMINI_API_KEY",
            "deepseek":  "DEEPSEEK_API_KEY",
        }
        if req.provider in env_map:
            os.environ[env_map[req.provider]] = req.api_key
    return {"success": True, "active_provider": ai_provider.PROVIDER}


# ── Agent status ──────────────────────────────────────────────────────────────

@app.get("/agents/status")
def get_agents_status(current_user=Depends(get_current_user)):
    return {"success": True, "version": "1.8.0", "schema_cache": "active",
            "universal_db": "active", "sql_dialect": "active",
            "agents": [
                {"name": "OrchestratorAgent",           "status": "active", "role": "Coordinates all agents"},
                {"name": "SchemaAgent",                 "status": "active", "role": "Discovers tables, columns, PKs, FKs"},
                {"name": "MetadataAgent",               "status": "active", "role": "Data profiling, quality, PII detection"},
                {"name": "BusinessAgent",               "status": "active", "role": "Analyzes requirements and KPIs"},
                {"name": "PlannerAgent",                "status": "active", "role": "Decides Star/Snowflake/ETL/KPI plan"},
                {"name": "RelationshipValidationAgent", "status": "active", "role": "Validates FKs, circular joins"},
                {"name": "DataModelAgent",              "status": "active", "role": "Designs star schema"},
                {"name": "ETLAgent",                    "status": "active", "role": "Source → staging extraction"},
                {"name": "SQLAgent",                    "status": "active", "role": "Generates warehouse SQL"},
                {"name": "SQLValidationAgent",          "status": "active", "role": "Validates and auto-fixes SQL"},
                {"name": "GovernanceValidationAgent",   "status": "active", "role": "PII, safety, governance checks"},
                {"name": "ReviewAgent",                 "status": "active", "role": "HIL gateway (Gate 1 + Gate 2)"},
                {"name": "ExecutionAgent",              "status": "active", "role": "Runs SQL scripts on warehouse"},
                {"name": "RecoveryAgent",               "status": "active", "role": "Auto-fixes failed scripts"},
                {"name": "QualityAgent",                "status": "active", "role": "Null checks, duplicate detection, business rules"},
                {"name": "AnalyticsAgent",              "status": "active", "role": "Pipeline metrics and BI queries"},
            ]}


# ── ETL Mapping endpoints ─────────────────────────────────────────────────────

@app.post("/mapping/save")
def save_mapping(req: SaveMappingRequest, current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Save ETL mapping for a pipeline. Auto-increments version."""
    workspace = get_user_workspace(current_user.id, db)
    wid       = workspace.get("id")

    # Get current max version for this pipeline
    existing = db.query(PipelineMapping).filter(
        PipelineMapping.pipeline_id == req.pipeline_id,
        PipelineMapping.workspace_id == wid
    ).order_by(PipelineMapping.version.desc()).first()

    next_version = (existing.version + 1) if existing else 1

    # Deactivate all previous versions
    db.query(PipelineMapping).filter(
        PipelineMapping.pipeline_id == req.pipeline_id,
        PipelineMapping.workspace_id == wid
    ).update({"is_active": False})

    # Save new version
    mapping = PipelineMapping(
        pipeline_id  = req.pipeline_id,
        workspace_id = wid,
        created_by   = current_user.id,
        name         = req.name,
        version      = next_version,
        is_active    = True,
        mappings     = req.mappings,
        notes        = req.notes
    )
    db.add(mapping); db.commit(); db.refresh(mapping)
    return {"success": True, "mapping_id": mapping.id,
            "version": next_version, "message": f"Mapping saved as v{next_version}"}


@app.get("/mapping/list/{pipeline_id}")
def list_mappings(pipeline_id: str, current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """List all mapping versions for a pipeline."""
    workspace = get_user_workspace(current_user.id, db)
    mappings  = db.query(PipelineMapping).filter(
        PipelineMapping.pipeline_id == pipeline_id,
        PipelineMapping.workspace_id == workspace.get("id")
    ).order_by(PipelineMapping.version.desc()).all()
    return {"success": True, "mappings": [
        {"id": m.id, "name": m.name, "version": m.version,
         "is_active": m.is_active, "notes": m.notes,
         "created_by": m.created_by,
         "created_at": str(m.created_at)} for m in mappings
    ]}


@app.get("/mapping/{mapping_id}")
def get_mapping(mapping_id: str, current_user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Get full mapping detail including column mappings."""
    m = db.query(PipelineMapping).filter(PipelineMapping.id == mapping_id).first()
    if not m: raise HTTPException(404, "Mapping not found")
    return {"success": True, "id": m.id, "name": m.name,
            "version": m.version, "is_active": m.is_active,
            "mappings": m.mappings, "notes": m.notes,
            "created_at": str(m.created_at)}


@app.put("/mapping/{mapping_id}")
def update_mapping(mapping_id: str, req: UpdateMappingRequest,
                   current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Update an existing mapping (creates new version)."""
    m = db.query(PipelineMapping).filter(PipelineMapping.id == mapping_id).first()
    if not m: raise HTTPException(404, "Mapping not found")
    if req.name     is not None: m.name     = req.name
    if req.mappings is not None: m.mappings = req.mappings
    if req.notes    is not None: m.notes    = req.notes
    m.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Mapping updated"}


@app.delete("/mapping/{mapping_id}")
def delete_mapping(mapping_id: str, current_user=Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Delete a mapping version."""
    m = db.query(PipelineMapping).filter(PipelineMapping.id == mapping_id).first()
    if not m: raise HTTPException(404, "Mapping not found")
    db.delete(m); db.commit()
    return {"success": True, "message": "Mapping deleted"}


@app.post("/mapping/activate/{mapping_id}")
def activate_mapping(mapping_id: str, current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Set a specific mapping version as active."""
    workspace = get_user_workspace(current_user.id, db)
    m = db.query(PipelineMapping).filter(PipelineMapping.id == mapping_id).first()
    if not m: raise HTTPException(404, "Mapping not found")
    # Deactivate all others for this pipeline
    db.query(PipelineMapping).filter(
        PipelineMapping.pipeline_id == m.pipeline_id,
        PipelineMapping.workspace_id == workspace.get("id")
    ).update({"is_active": False})
    m.is_active = True
    db.commit()
    return {"success": True, "message": f"Mapping v{m.version} activated"}


# ── Pipeline version endpoints ────────────────────────────────────────────────

@app.post("/version/save")
def save_version(req: SaveVersionRequest, current_user=Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Save current pipeline design as a named version."""
    workspace = get_user_workspace(current_user.id, db)
    wid       = workspace.get("id")

    pipeline = db.query(Pipeline).filter(Pipeline.id == req.pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")

    # Get next version number
    existing = db.query(PipelineVersion).filter(
        PipelineVersion.pipeline_id == req.pipeline_id,
        PipelineVersion.workspace_id == wid
    ).order_by(PipelineVersion.version.desc()).first()

    next_version = (existing.version + 1) if existing else 1
    label        = req.version_label or f"v{next_version}"

    # Deactivate previous active version
    db.query(PipelineVersion).filter(
        PipelineVersion.pipeline_id == req.pipeline_id,
        PipelineVersion.workspace_id == wid,
        PipelineVersion.is_active == True
    ).update({"is_active": False})

    # Save snapshot
    artifacts = pipeline.artifacts or {}
    version = PipelineVersion(
        pipeline_id    = req.pipeline_id,
        workspace_id   = wid,
        created_by     = current_user.id,
        version        = next_version,
        version_label  = label,
        is_active      = True,
        data_model     = artifacts.get("data_model", {}),
        sql_scripts    = artifacts.get("sql_scripts", {}),
        etl_mappings   = artifacts.get("etl_mappings", {}),
        schema_hash    = artifacts.get("schema_hash", ""),
        change_summary = req.change_summary or f"Saved as {label}"
    )
    db.add(version)

    # Update pipeline current version
    pipeline.current_version = next_version
    pipeline.updated_at      = datetime.utcnow()
    db.commit(); db.refresh(version)

    return {"success": True, "version_id": version.id,
            "version": next_version, "label": label,
            "message": f"Pipeline saved as {label}"}


@app.get("/version/list/{pipeline_id}")
def list_versions(pipeline_id: str, current_user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """List all versions for a pipeline."""
    workspace = get_user_workspace(current_user.id, db)
    versions  = db.query(PipelineVersion).filter(
        PipelineVersion.pipeline_id  == pipeline_id,
        PipelineVersion.workspace_id == workspace.get("id")
    ).order_by(PipelineVersion.version.desc()).all()
    return {"success": True, "versions": [
        {"id":             v.id,
         "version":        v.version,
         "version_label":  v.version_label,
         "is_active":      v.is_active,
         "change_summary": v.change_summary,
         "created_by":     v.created_by,
         "schema_hash":    v.schema_hash,
         "script_count":   len((v.sql_scripts or {}).get("scripts", [])),
         "dim_count":      len((v.data_model or {}).get("dimension_tables", [])),
         "fact_count":     len((v.data_model or {}).get("fact_tables", [])),
         "created_at":     str(v.created_at)} for v in versions
    ]}


@app.get("/version/{version_id}")
def get_version(version_id: str, current_user=Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Get full version detail."""
    v = db.query(PipelineVersion).filter(PipelineVersion.id == version_id).first()
    if not v: raise HTTPException(404, "Version not found")
    return {"success": True, "id": v.id, "version": v.version,
            "version_label": v.version_label, "is_active": v.is_active,
            "data_model":    v.data_model,    "sql_scripts":   v.sql_scripts,
            "etl_mappings":  v.etl_mappings,  "schema_hash":   v.schema_hash,
            "change_summary": v.change_summary, "created_at": str(v.created_at)}


@app.post("/version/rollback")
def rollback_version(req: RollbackVersionRequest, current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Rollback pipeline to a previous version."""
    workspace = get_user_workspace(current_user.id, db)
    wid       = workspace.get("id")

    v = db.query(PipelineVersion).filter(PipelineVersion.id == req.version_id).first()
    if not v: raise HTTPException(404, "Version not found")

    pipeline = db.query(Pipeline).filter(Pipeline.id == req.pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")

    # Restore artifacts from this version
    pipeline.artifacts = {
        "data_model":   v.data_model,
        "sql_scripts":  v.sql_scripts,
        "etl_mappings": v.etl_mappings,
        "schema_hash":  v.schema_hash,
    }
    pipeline.current_version = v.version
    pipeline.updated_at      = datetime.utcnow()

    # Set this as active version
    db.query(PipelineVersion).filter(
        PipelineVersion.pipeline_id == req.pipeline_id,
        PipelineVersion.workspace_id == wid
    ).update({"is_active": False})
    v.is_active = True
    db.commit()

    return {"success": True,
            "message": f"Pipeline rolled back to {v.version_label} (v{v.version})",
            "version": v.version, "label": v.version_label}


@app.get("/version/compare/{version_id_a}/{version_id_b}")
def compare_versions(version_id_a: str, version_id_b: str,
                     current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Compare two versions — returns diff summary."""
    va = db.query(PipelineVersion).filter(PipelineVersion.id == version_id_a).first()
    vb = db.query(PipelineVersion).filter(PipelineVersion.id == version_id_b).first()
    if not va or not vb: raise HTTPException(404, "Version not found")

    # Compare dim/fact tables
    dims_a  = {d.get("name") for d in (va.data_model or {}).get("dimension_tables", [])}
    dims_b  = {d.get("name") for d in (vb.data_model or {}).get("dimension_tables", [])}
    facts_a = {f.get("name") for f in (va.data_model or {}).get("fact_tables", [])}
    facts_b = {f.get("name") for f in (vb.data_model or {}).get("fact_tables", [])}

    scripts_a = {s.get("name") for s in (va.sql_scripts or {}).get("scripts", [])}
    scripts_b = {s.get("name") for s in (vb.sql_scripts or {}).get("scripts", [])}

    return {"success": True,
            "version_a": {"version": va.version, "label": va.version_label},
            "version_b": {"version": vb.version, "label": vb.version_label},
            "diff": {
                "dims_added":    list(dims_b  - dims_a),
                "dims_removed":  list(dims_a  - dims_b),
                "facts_added":   list(facts_b - facts_a),
                "facts_removed": list(facts_a - facts_b),
                "scripts_added":   list(scripts_b - scripts_a),
                "scripts_removed": list(scripts_a - scripts_b),
                "schema_changed":  va.schema_hash != vb.schema_hash,
            }}


# ── Data Quality endpoints ────────────────────────────────────────────────────

@app.get("/quality/report/{pipeline_id}")
def get_quality_report(pipeline_id: str, current_user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Get latest quality report for a pipeline."""
    from database import RecoveryLog
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")
    quality = pipeline.artifacts.get("quality_report") if pipeline.artifacts else None
    if not quality:
        return {"success": True, "pipeline_id": pipeline_id,
                "report": None, "message": "No quality report yet — execute pipeline first"}
    return {"success": True, "pipeline_id": pipeline_id,
            "pipeline_name": pipeline.name, "report": quality}

@app.post("/quality/run/{pipeline_id}")
def run_quality_check(pipeline_id: str, current_user=Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Run quality checks on demand for an already-executed pipeline."""
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")
    if not pipeline.connector_id: raise HTTPException(400, "No connector linked")

    src = db.query(Connector).filter(Connector.id == pipeline.connector_id).first()
    if not src: raise HTTPException(404, "Source connector not found")

    tgt = src
    if pipeline.target_connector_id:
        t = db.query(Connector).filter(Connector.id == pipeline.target_connector_id).first()
        if t: tgt = t

    ctx = _build_ctx(
        pipeline_id, "", _cfg(src), src.source_schema or "raw",
        pipeline.source_tables or [], {},
        pipeline.source_desc or "", pipeline.biz_requirements or "",
        target_config=_cfg(tgt),
        staging_schema=pipeline.staging_schema or "staging",
        warehouse_schema=pipeline.warehouse_schema or "warehouse"
    )
    # Pass data model for business rule generation
    if pipeline.artifacts:
        ctx.data_model      = {"data_model": pipeline.artifacts.get("data_model", {})}
        ctx.business_result = pipeline.artifacts.get("agent_metadata", {}).get("business_analysis", {})

    QualityAgent().run(ctx)
    quality = ctx.quality_result or {}

    # Save report to pipeline artifacts
    try:
        artifacts = dict(pipeline.artifacts or {})
        artifacts["quality_report"] = quality
        pipeline.artifacts = artifacts
        db.commit()
    except Exception as e:
        print(f"[Quality] Could not save report: {e}")

    return {"success": True, "pipeline_id": pipeline_id,
            "pipeline_name": pipeline.name, "report": quality}



@app.get("/quality/audit/{pipeline_id}")
def get_quality_audit(pipeline_id: str, limit: int = 500,
                      current_user=Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Fetch audit records directly from warehouse.dq_audit_log for a pipeline."""
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")
    try:
        tgt = None
        if pipeline.target_connector_id:
            tgt = db.query(Connector).filter(Connector.id == pipeline.target_connector_id).first()
        if not tgt and pipeline.connector_id:
            tgt = db.query(Connector).filter(Connector.id == pipeline.connector_id).first()
        if not tgt:
            return {"success": True, "records": [], "total": 0}
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(
            host=tgt.host, port=tgt.port, dbname=tgt.database_name,
            user=tgt.username, password=tgt.password
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT audit_id as id, pipeline_id, table_name, column_name, issue_type,
                   check_type as check_name, reason as message, row_data, check_date
            FROM warehouse.dq_audit_log
            WHERE pipeline_id = %s
            ORDER BY check_date DESC
            LIMIT %s
        """, (pipeline_id, limit))
        records = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM warehouse.dq_audit_log WHERE pipeline_id = %s", (pipeline_id,))
        total = cur.fetchone()["count"]
        cur.close(); conn.close()
        return {"success": True, "records": [dict(r) for r in records], "total": total}
    except Exception as e:
        return {"success": True, "records": [], "total": 0, "error": str(e)}


# ── Migration Agent ────────────────────────────────────────────────────────────
@app.post("/migration/scan")
async def migration_scan(
    connection:   str = Form(...),
    sub_mode:     str = Form("reverse"),
    upload_mode:  str = Form("repository"),
    technology:   str = Form("informatica"),
    files:        List[UploadFile] = File(default=[]),
    current_user=Depends(get_current_user)
):
    """
    Scan existing warehouse + optionally parse uploaded mapping files.
    Returns reverse data model, mappings, gaps, and data dictionary.

    `technology` selects which parser interprets the uploaded files:
      "informatica" (default) — repository/mapping XML, column-level
                                 mappings, column-level gaps (a column with
                                 no source mapping is a gap).
      "dbt"                    — a dbt project's .sql model files + .yml
                                 (sources.yml/schema.yml). dbt models are
                                 complete, self-contained SQL — there's no
                                 column-level "gap" concept the way
                                 Informatica has. Instead, a gap here means
                                 a scanned warehouse table has NO matching
                                 dbt model at all, plus any source()
                                 reference that couldn't be resolved via
                                 sources.yml.
    """
    import json, tempfile, os, shutil
    from agents.migration_agent import (
        scan_warehouse, parse_informatica_xml, parse_dbt_yml, detect_gaps,
        parse_dbt_project
    )

    try:
        conn_config = json.loads(connection)
    except Exception:
        raise HTTPException(400, "Invalid connection JSON")

    warehouse_schema = conn_config.get("warehouse_schema", "warehouse")

    # Step 1: Scan warehouse (unchanged regardless of technology)
    scan_result = scan_warehouse(conn_config, warehouse_schema, sub_mode)
    if not scan_result.get("success"):
        raise HTTPException(400, f"Warehouse scan failed: {scan_result.get('error')}")

    all_mappings = []
    gaps = []
    dbt_deployment_order = None

    if technology == "dbt":
        # Step 2 (dbt): separate uploaded files by type, parse as a dbt project
        sql_files_map, yml_files_map = {}, {}
        for f in files:
            content = await f.read()
            text = content.decode("utf-8", errors="ignore")
            fname_lower = f.filename.lower()
            if fname_lower.endswith(".sql"):
                sql_files_map[f.filename] = text
            elif fname_lower.endswith(".yml") or fname_lower.endswith(".yaml"):
                yml_files_map[f.filename] = text

        if not sql_files_map:
            raise HTTPException(400, "No .sql model files found in upload — a dbt migration needs at least one model file.")

        dbt_parsed = parse_dbt_project(sql_files_map, yml_files_map)
        if not dbt_parsed.get("success"):
            raise HTTPException(400, f"dbt project parsing failed: {dbt_parsed.get('error')}")

        all_mappings = dbt_parsed["mappings"]
        dbt_deployment_order = dbt_parsed["deployment_order"]

        # Table-level gaps: warehouse tables with no matching dbt model,
        # PLUS any unresolved source() reference the parser already found.
        dbt_model_names = set(dbt_deployment_order)
        for t in scan_result["tables"]:
            if t.get("type") in ("dim", "fact") and t["name"] not in dbt_model_names:
                gaps.append({
                    "column": t["name"], "table": t["name"],
                    "reason": f"No dbt model found for warehouse table '{t['name']}'."
                })
        gaps.extend(dbt_parsed.get("gaps", []))

        relevant_tables = [t for t in scan_result["tables"] if t.get("type") in ("dim", "fact")]
        mapped_count = len(dbt_model_names & {t["name"] for t in relevant_tables})
        coverage = round((mapped_count / len(relevant_tables)) * 100) if relevant_tables else 0

    else:
        # Step 2 (Informatica, default): unchanged from before
        if files:
            tmp_dir = tempfile.mkdtemp()
            try:
                for f in files:
                    content = await f.read()
                    fname   = f.filename.lower()
                    if fname.endswith(".xml"):
                        mappings = parse_informatica_xml(content.decode("utf-8", errors="ignore"), source_file=f.filename)
                        all_mappings.extend(mappings)
                    elif fname.endswith(".yml") or fname.endswith(".yaml"):
                        mappings = parse_dbt_yml(content.decode("utf-8", errors="ignore"))
                        all_mappings.extend(mappings)
                    # SSIS, ODI, BRD parsers — future
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        gaps = detect_gaps(scan_result["tables"], all_mappings) if all_mappings else []
        total_cols   = sum(len(t.get("columns", [])) for t in scan_result["tables"])
        mapped_cols  = len(all_mappings)
        coverage     = round((mapped_cols / total_cols) * 100) if total_cols > 0 else 90

    response = {
        **scan_result,
        "mappings":    all_mappings,
        "gaps":        gaps,
        "coverage":    coverage,
        "upload_mode": upload_mode,
        "technology":  technology,
        "files_count": len(files)
    }
    if dbt_deployment_order is not None:
        response["dbt_deployment_order"] = dbt_deployment_order
        response["dbt_source_lookup"] = dbt_parsed.get("source_lookup_display", {})
    return response


@app.get("/migration/list")
def migration_list(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """List all migration projects for this workspace."""
    workspace = get_user_workspace(current_user.id, db)
    pipelines = db.query(Pipeline).filter(
        Pipeline.workspace_id == workspace.get("id"),
        Pipeline.source_schema == "migration"
    ).order_by(Pipeline.created_at.desc()).all()
    return {"success": True, "projects": [
        {"id": p.id, "name": p.name, "created_at": str(p.created_at)}
        for p in pipelines
    ]}

@app.post("/migration/generate-sql")
async def migration_generate_sql(
    payload: dict = Body(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Given a scanned data model (tables + mappings) plus any user-resolved
    gaps, generate the SQL needed to populate each table from its
    identified sources — then create an ApprovalQueue row (same mechanism
    native pipelines use for Gate 2 / SQL review) instead of handing scripts
    straight to deploy. Nothing runs against the warehouse until a human
    approves via the existing /pipeline/approve-sql endpoint.

    `technology` selects which SQL generation path runs:
      "informatica" (default) — generate_sql_scripts(): the AI reconstructs
                                 SQL column-by-column from traced Informatica
                                 mappings, since Informatica's XML never
                                 contains real target SQL itself.
      "dbt"                    — generate_sql_from_dbt_models(): dbt models
                                 ALREADY are real, tested SQL — no AI
                                 reconstruction needed. Each script
                                 replicates dbt's own materialization
                                 (DROP + CREATE TABLE AS SELECT), with
                                 ref()/source() resolved to real tables.
                                 CRITICAL: dbt scripts must stay in the
                                 topologically-sorted deployment_order the
                                 parser already computed — see
                                 generate_sql_from_dbt_models()'s docstring
                                 for why (dbt models form a real dependency
                                 graph, unlike Informatica's mostly-
                                 independent target tables).

    Expected payload:
      {
        "technology": "informatica" | "dbt",
        "tables": [...], "mappings": [...], "gaps": [...],
        "resolutions": { "<gap column or index>": "<user's resolution text>" },
        "domain": "retail",
        "staging_schema": "staging" (optional), "warehouse_schema": "warehouse" (optional),
        "dbt_deployment_order": [...],  (REQUIRED if technology == "dbt" — from /migration/scan)
        "dbt_source_lookup": {...}      (REQUIRED if technology == "dbt" — from /migration/scan)
      }

    Response:
      { "success": true, "approval_id": "...", "sql_scripts": {"scripts": [...]},
        "risk_level": "low"|"medium"|"high", "generated_at": "..." }
    """
    from agents.migration_agent import generate_sql_scripts, generate_sql_from_dbt_models

    technology       = payload.get("technology", "informatica")
    tables           = payload.get("tables", [])
    mappings         = payload.get("mappings", [])
    gaps             = payload.get("gaps", [])
    resolutions      = payload.get("resolutions", {})
    domain           = payload.get("domain", "")
    source_schema    = payload.get("source_schema", "raw")
    staging_schema   = payload.get("staging_schema", "staging")
    warehouse_schema = payload.get("warehouse_schema", "warehouse")

    if not tables:
        raise HTTPException(400, "No tables provided — run a scan first")

    if technology == "dbt":
        deployment_order = payload.get("dbt_deployment_order")
        if not deployment_order:
            raise HTTPException(400, "dbt_deployment_order is required for dbt migrations — re-run /migration/scan first.")

        # Reconstruct the parsed-project shape generate_sql_from_dbt_models()
        # expects from what /migration/scan already returned in `mappings`
        # (raw_sql, ref_dependencies, source_dependencies were carried
        # through specifically so this round-trip works without re-parsing
        # the original .sql files).
        models_by_name = {}
        for m in mappings:
            models_by_name[m["target"]] = {
                "name": m["target"],
                "ref_dependencies": m.get("ref_dependencies", []),
                "source_dependencies": [tuple(sd) for sd in m.get("source_dependencies", [])],
                "materialized": m.get("materialized", "table"),
                "raw_sql": m.get("raw_sql", ""),
            }

        # source_lookup crossed the HTTP boundary as a JSON-safe
        # {"source.table": "schema.table"} dict — reconstruct the
        # tuple-keyed form resolve_dbt_model_sql() actually expects.
        source_lookup_display = payload.get("dbt_source_lookup", {})
        source_lookup = {}
        for key, val in source_lookup_display.items():
            if "." in key:
                src_name, tbl_name = key.split(".", 1)
                source_lookup[(src_name, tbl_name)] = val

        parsed_project = {
            "success": True,
            "models": [models_by_name[name] for name in deployment_order if name in models_by_name],
            "deployment_order": [name for name in deployment_order if name in models_by_name],
            "source_lookup": source_lookup,
        }
        result = generate_sql_from_dbt_models(parsed_project, warehouse_schema=warehouse_schema, source_schema=source_schema)
        if not result.get("success"):
            raise HTTPException(400, f"dbt SQL generation failed: {result.get('error')}")

        scripts = result["sql_scripts"].get("scripts", [])
        incremental_count = sum(1 for s in scripts if s.get("materialized") == "incremental")
        risk_level = "high" if incremental_count > 0 else ("medium" if gaps else "low")
        description = (
            f"{len(scripts)} dbt model(s) in dependency order. "
            f"{incremental_count} incremental model(s) need manual review of their filter logic. "
            f"{len(gaps)} warehouse table(s) or source() reference(s) have no matching dbt model."
        )
    else:
        result = generate_sql_scripts(
            tables, mappings, gaps, resolutions, domain,
            staging_schema=staging_schema, warehouse_schema=warehouse_schema
        )
        if not result.get("success"):
            raise HTTPException(400, f"SQL generation failed: {result.get('error')}")

        scripts = result["sql_scripts"].get("scripts", [])
        unresolved_count = sum(1 for m in mappings if m.get("needs_review"))
        unmapped_count = sum(
            s.get("columns_total", 0) - s.get("columns_mapped", 0) for s in scripts
        )
        risk_level = "high" if unresolved_count > 0 else ("medium" if unmapped_count > 0 else "low")
        description = (
            f"{unmapped_count} unmapped column(s), {unresolved_count} needing manual review. "
            f"Review each script before deploying to the warehouse."
        )

    workspace = get_user_workspace(current_user.id, db)
    approval = ApprovalQueue(
        workspace_id=workspace.get("id"),
        approval_type="migration_sql_scripts",
        title=f"Migration SQL ({technology}) — {len(scripts)} scripts ({domain or 'unknown domain'})",
        description=description,
        proposed_data={
            "sql_scripts":      result["sql_scripts"],
            "technology":       technology,
            "tables":           tables,
            "mappings":         mappings,
            "gaps":             gaps,
            "resolutions":      resolutions,
            "domain":           domain,
            "staging_schema":   staging_schema,
            "warehouse_schema": warehouse_schema,
            "dbt_deployment_order": payload.get("dbt_deployment_order"),
        },
        context={
            "domain": domain, "staging_schema": staging_schema,
            "warehouse_schema": warehouse_schema, "technology": technology
        },
        status="pending",
        requested_by=current_user.id,
        risk_level=risk_level,
    )
    db.add(approval); db.commit(); db.refresh(approval)

    return {
        "success":      True,
        "approval_id":  approval.id,
        "sql_scripts":  result["sql_scripts"],
        "risk_level":   risk_level,
        "generated_at": result.get("generated_at"),
    }


@app.post("/migration/deploy")
def migration_deploy(
    req: dict,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Deploy an APPROVED migration SQL set.

    Deploy strategy depends on `technology` (stored on the approval from
    /migration/generate-sql):

      "informatica" (default) — ONE INDEPENDENT PIPELINE PER MAPPING
                                 (typically one per target table). Informatica
                                 mappings are mostly independent target
                                 tables, so each gets its own Pipeline row,
                                 its own PipelineRun history, and failure
                                 isolation.

      "dbt"                    — ONE SEQUENTIAL PIPELINE containing ALL dbt
                                 models as scripts, in the topologically-
                                 sorted dependency order already computed at
                                 generate-sql time. dbt models form a real
                                 dependency graph (via ref()) — splitting them
                                 into independent pipelines would risk a
                                 downstream model running before its
                                 dependency exists. execute_warehouse_scripts()
                                 already runs scripts sequentially in the
                                 order given, so one pipeline with correctly
                                 ordered scripts is sufficient — no new
                                 orchestration needed. Uses run_dbt_deployment()
                                 (skips extraction — dbt sources are assumed
                                 already loaded in the target warehouse),
                                 not run_migration_deployment().

    Requires approval_id from /migration/generate-sql, and that approval
    must be "approved" or "edited" (via the existing /pipeline/approve-sql)
    before anything runs.

    Expects in `req`:
      approval_id (REQUIRED), target_connector_id (REQUIRED),
      source_connector_id (REQUIRED for informatica; NOT required for dbt,
      since dbt deployment skips extraction), project_name, source_schema.

    Returns:
      Informatica: {"success": bool, "technology": "informatica",
                    "pipelines": [{"pipeline_id", "table", "mapping_name",
                                    "success", "stage", "error", ...}, ...]}
      dbt:         {"success": bool, "technology": "dbt", "pipeline_id": str,
                    "pipeline_name": str, "models": [{"name", "success"}, ...],
                    "quality": ..., "log": [...]}
    """
    from agents.migration_agent import run_migration_deployment, run_dbt_deployment

    try:
        workspace = get_user_workspace(current_user.id, db)

        approval_id = req.get("approval_id")
        if not approval_id:
            raise HTTPException(400, "approval_id is required — call /migration/generate-sql first, "
                                      "then approve it via /pipeline/approve-sql.")
        approval = db.query(ApprovalQueue).filter(ApprovalQueue.id == approval_id).first()
        if not approval:
            raise HTTPException(404, "Approval not found")
        if approval.status not in ("approved", "edited"):
            raise HTTPException(400, f"This SQL has not been approved yet (status: {approval.status}). "
                                      f"Approve it via /pipeline/approve-sql before deploying.")

        approved_data = approval.edited_data if approval.status == "edited" and approval.edited_data else approval.proposed_data
        all_scripts  = approved_data.get("sql_scripts", {}).get("scripts", [])
        domain       = approved_data.get("domain", "migrated")
        all_mappings = approved_data.get("mappings", [])
        all_tables   = approved_data.get("tables", [])
        technology   = approved_data.get("technology", "informatica")

        if not all_scripts:
            raise HTTPException(400, "No SQL scripts found in this approval.")

        source_schema    = req.get("source_schema", "raw")
        staging_schema   = req.get("staging_schema") or approved_data.get("staging_schema", "staging")
        warehouse_schema = req.get("warehouse_schema") or approved_data.get("warehouse_schema", "warehouse")
        project_prefix   = req.get("project_name", f"Migration - {domain}")

        target_connector_id = req.get("target_connector_id")
        if not target_connector_id:
            raise HTTPException(400, "target_connector_id is required — the warehouse being migrated into.")
        tgt_connector = db.query(Connector).filter(Connector.id == target_connector_id).first()
        if not tgt_connector:
            raise HTTPException(404, "Target connector not found")
        target_config = _cfg(tgt_connector)

        # ══════════════════════════════════════════════════════════════════
        # dbt: ONE sequential pipeline, dependency order preserved, no extraction
        # ══════════════════════════════════════════════════════════════════
        if technology == "dbt":
            pipeline_label = f"dbt project ({len(all_scripts)} models)"
            artifacts = {
                "sql_scripts":  {"scripts": all_scripts},
                "data_model":   {"domain": domain, "tables": all_tables},
                "etl_mappings": {"mappings": all_mappings},
                "migration":    {"domain": domain, "approval_id": approval_id, "technology": "dbt"},
            }

            pipeline = Pipeline(
                workspace_id      = workspace.get("id"),
                name              = f"{project_prefix} — {pipeline_label}",
                source_desc       = f"dbt migration - {domain} domain, {len(all_scripts)} models",
                biz_requirements  = f"Migrated dbt project. Domain: {domain}.",
                schedule          = "manual",
                artifacts         = artifacts,
                connector_id      = None,
                source_schema     = "migration",
                source_columns    = {},
                source_tables     = [s.get("name") for s in all_scripts],
                target_connector_id = target_connector_id,
                staging_schema    = staging_schema,
                warehouse_schema  = warehouse_schema
            )
            db.add(pipeline); db.commit(); db.refresh(pipeline)

            try:
                version = PipelineVersion(
                    pipeline_id    = pipeline.id,
                    workspace_id   = workspace.get("id"),
                    created_by     = current_user.id,
                    version        = 1,
                    version_label  = "v1",
                    is_active      = True,
                    data_model     = artifacts.get("data_model", {}),
                    sql_scripts    = {"scripts": all_scripts},
                    etl_mappings   = artifacts.get("etl_mappings", {}),
                    schema_hash    = "",
                    change_summary = f"dbt migration deployment (approval {approval_id})"
                )
                db.add(version); db.commit()
            except Exception as e:
                print(f"[Migration] Could not save version: {e}")

            # One PipelineMapping row per dbt model, all under the same pipeline
            try:
                for m in all_mappings:
                    pipeline_mapping = PipelineMapping(
                        pipeline_id  = pipeline.id,
                        workspace_id = workspace.get("id"),
                        created_by   = current_user.id,
                        name         = f"{m.get('target', '')} v1",
                        version      = 1,
                        is_active    = True,
                        mappings     = {"mappings": [{
                            "target_table":  f"{warehouse_schema}.{m.get('target', '')}",
                            "source_schema": staging_schema,
                            "columns":       [],  # dbt lineage is table-level, not column-level — see parse_dbt_model_sql
                        }]},
                        notes = f"dbt model — depends on: {m.get('source', 'none')}"
                    )
                    db.add(pipeline_mapping)
                db.commit()
            except Exception as e:
                print(f"[Migration] Could not save dbt PipelineMappings: {e}")

            result = run_dbt_deployment(
                target_connector_config=target_config,
                staging_schema=staging_schema,
                warehouse_schema=warehouse_schema,
                sql_scripts={"scripts": all_scripts},
                pipeline_id=pipeline.id,
                workspace_id=workspace.get("id"),
            )

            try:
                run = PipelineRun(
                    run_id=f"{pipeline.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                    pipeline_id=pipeline.id, workspace_id=workspace.get("id"),
                    status="success" if result.get("success") else "failed",
                    started_at=datetime.utcnow(), ended_at=datetime.utcnow(),
                    rows_loaded=result.get("warehouse", {}).get("total_rows", 0),
                    log="\n".join(result.get("pipeline_log", []) or result.get("log", []))
                )
                db.add(run); db.commit()
            except Exception as e:
                print(f"[Migration] Could not save run record: {e}")

            model_results = result.get("warehouse", {}).get("scripts", [])
            return {
                "success":       result.get("success", False),
                "technology":    "dbt",
                "pipeline_id":   pipeline.id,
                "pipeline_name": pipeline.name,
                "models":        model_results,
                "stage":         result.get("stage"),
                "error":         result.get("error"),
                "quality":       result.get("quality"),
                "log":           result.get("log", []),
            }

        # ══════════════════════════════════════════════════════════════════
        # Informatica (default): one independent pipeline per mapping
        # ══════════════════════════════════════════════════════════════════
        source_connector_id = req.get("source_connector_id")
        if not source_connector_id:
            raise HTTPException(400, "source_connector_id is required — the legacy system "
                                      "ETLAgent extracts source tables from.")
        src_connector = db.query(Connector).filter(Connector.id == source_connector_id).first()
        if not src_connector:
            raise HTTPException(404, "Source connector not found")
        source_config = _cfg(src_connector)

        results = []
        for script in all_scripts:
            tname = script.get("name", "")
            table_mappings = [m for m in all_mappings if m.get("target", "").split(".")[0] == tname]
            mapping_names = sorted(set(m.get("mapping_name") for m in table_mappings if m.get("mapping_name")))
            pipeline_label = mapping_names[0] if len(mapping_names) == 1 else (
                f"{tname} (multiple mappings)" if mapping_names else tname
            )
            source_tables = list(dict.fromkeys(
                m.get("source_table") for m in table_mappings
                if m.get("source_table") and not m.get("needs_review")
            ))
            table_def = next((t for t in all_tables if t.get("name") == tname), {})

            artifacts = {
                "sql_scripts":  {"scripts": [script]},
                "data_model":   {"domain": domain, "tables": [table_def] if table_def else []},
                "etl_mappings": {"mappings": table_mappings},
                "migration":    {"domain": domain, "approval_id": approval_id, "mapping_name": pipeline_label},
            }

            pipeline = Pipeline(
                workspace_id      = workspace.get("id"),
                name              = f"{project_prefix} — {pipeline_label}",
                source_desc       = f"Migration project - {domain} domain ({pipeline_label})",
                biz_requirements  = f"Migrated from existing warehouse. Domain: {domain}. Mapping: {pipeline_label}.",
                schedule          = "manual",
                artifacts         = artifacts,
                connector_id      = src_connector.id,
                source_schema     = "migration",
                source_columns    = {},
                source_tables     = [tname],
                target_connector_id = target_connector_id,
                staging_schema    = staging_schema,
                warehouse_schema  = warehouse_schema
            )
            db.add(pipeline); db.commit(); db.refresh(pipeline)

            try:
                version = PipelineVersion(
                    pipeline_id    = pipeline.id,
                    workspace_id   = workspace.get("id"),
                    created_by     = current_user.id,
                    version        = 1,
                    version_label  = "v1",
                    is_active      = True,
                    data_model     = artifacts.get("data_model", {}),
                    sql_scripts    = {"scripts": [script]},
                    etl_mappings   = artifacts.get("etl_mappings", {}),
                    schema_hash    = "",
                    change_summary = f"Migration deployment (approval {approval_id}, mapping {pipeline_label})"
                )
                db.add(version); db.commit()
            except Exception as e:
                print(f"[Migration] Could not save version for {tname}: {e}")

            try:
                pm_columns = []
                for m in table_mappings:
                    src_stg = None
                    if m.get("source_table") and not m.get("needs_review"):
                        src_stg = f"{staging_schema}.stg_{m['source_table']}"
                    pm_columns.append({
                        "source_table":  src_stg,
                        "source_column": m.get("source", ""),
                        "target_column": m.get("target", "").split(".")[-1],
                        "transform_rule": m.get("transformation", "direct"),
                    })
                pipeline_mapping = PipelineMapping(
                    pipeline_id  = pipeline.id,
                    workspace_id = workspace.get("id"),
                    created_by   = current_user.id,
                    name         = f"{pipeline_label} v1",
                    version      = 1,
                    is_active    = True,
                    mappings     = {"mappings": [{
                        "target_table":  f"{warehouse_schema}.{tname}",
                        "source_schema": staging_schema,
                        "columns":       pm_columns,
                    }]},
                    notes        = f"Auto-saved from Migration Agent deployment (approval {approval_id})"
                )
                db.add(pipeline_mapping); db.commit()
            except Exception as e:
                print(f"[Migration] Could not save PipelineMapping for {tname}: {e}")

            result = run_migration_deployment(
                source_connector_config=source_config,
                target_connector_config=target_config,
                source_schema=source_schema,
                staging_schema=staging_schema,
                warehouse_schema=warehouse_schema,
                source_tables=source_tables,
                sql_scripts={"scripts": [script]},
                data_model=artifacts["data_model"],
                pipeline_id=pipeline.id,
                workspace_id=workspace.get("id"),
            )

            try:
                run = PipelineRun(
                    run_id=f"{pipeline.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                    pipeline_id=pipeline.id, workspace_id=workspace.get("id"),
                    status="success" if result.get("success") else "failed",
                    started_at=datetime.utcnow(), ended_at=datetime.utcnow(),
                    rows_loaded=result.get("warehouse", {}).get("total_rows", 0),
                    log="\n".join(result.get("pipeline_log", []) or result.get("log", []))
                )
                db.add(run); db.commit()
            except Exception as e:
                print(f"[Migration] Could not save run record for {tname}: {e}")

            results.append({
                "pipeline_id":   pipeline.id,
                "pipeline_name": pipeline.name,
                "table":         tname,
                "mapping_name":  pipeline_label,
                "success":       result.get("success", False),
                "stage":         result.get("stage"),
                "error":         result.get("error"),
                "staging":       result.get("staging"),
                "warehouse":     result.get("warehouse"),
                "quality":       result.get("quality"),
            })

        return {
            "success":    all(r["success"] for r in results),
            "technology": "informatica",
            "pipelines":  results,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Recovery Agent ────────────────────────────────────────────────────────────

@app.get("/recovery/logs")
def list_recovery_logs(current_user=Depends(get_current_user),
                       db: Session = Depends(get_db), limit: int = 50):
    from database import RecoveryLog
    workspace = get_user_workspace(current_user.id, db)
    logs = db.query(RecoveryLog).filter(RecoveryLog.workspace_id == workspace.get("id")
        ).order_by(RecoveryLog.created_at.desc()).limit(limit).all()
    return {"success": True, "logs": [
        {"id": r.id, "pipeline_id": r.pipeline_id, "pipeline_run_id": r.pipeline_run_id,
         "failed_script": r.failed_script,
         "error_message": r.error_message[:200] if r.error_message else "",
         "action_taken": r.action_taken, "fix_method": r.fix_method,
         "recovered": r.recovered, "summary": r.summary,
         "started_at": str(r.started_at) if r.started_at else None,
         "ended_at":   str(r.ended_at)   if r.ended_at   else None} for r in logs]}

@app.get("/recovery/logs/{log_id}")
def get_recovery_log(log_id: str, current_user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    from database import RecoveryLog
    log = db.query(RecoveryLog).filter(RecoveryLog.id == log_id).first()
    if not log: raise HTTPException(404, "Recovery log not found")
    return {"success": True, "id": log.id, "pipeline_id": log.pipeline_id,
            "pipeline_run_id": log.pipeline_run_id, "failed_script": log.failed_script,
            "error_message": log.error_message, "error_pattern": log.error_pattern,
            "action_taken": log.action_taken, "fix_method": log.fix_method,
            "fix_sql": log.fix_sql, "recovered": log.recovered,
            "attempts": log.attempts, "summary": log.summary,
            "started_at": str(log.started_at), "ended_at": str(log.ended_at)}

@app.get("/recovery/stats")
def get_recovery_stats(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    from database import RecoveryLog
    workspace = get_user_workspace(current_user.id, db)
    all_logs  = db.query(RecoveryLog).filter(RecoveryLog.workspace_id == workspace.get("id")).all()
    total     = len(all_logs)
    recovered = sum(1 for l in all_logs if l.recovered)
    actions   = {}
    for l in all_logs: actions[l.action_taken] = actions.get(l.action_taken, 0) + 1
    return {"success": True, "total": total, "recovered": recovered, "failed": total - recovered,
            "success_rate": round((recovered/total)*100,1) if total > 0 else 0,
            "top_actions": sorted(actions.items(), key=lambda x: -x[1])[:5]}


# ── AI Cost Tracking endpoints ────────────────────────────────────────────────

@app.get("/cost/summary")
def get_cost_summary_endpoint(days: int = 30, pipeline_id: str = None,
                               current_user=Depends(get_current_user)):
    """Return cost summary — total spend, token usage, peak vs off-peak, per-agent breakdown."""
    from ai_provider import get_cost_summary
    return {"success": True, **get_cost_summary(pipeline_id=pipeline_id, days=days)}


@app.get("/cost/calls")
def get_cost_calls(limit: int = 100, pipeline_id: str = None,
                   current_user=Depends(get_current_user)):
    """Return the most recent individual AI calls for the cost log."""
    from ai_provider import get_recent_calls
    return {"success": True, "calls": get_recent_calls(limit=limit, pipeline_id=pipeline_id)}


@app.get("/cost/pricing")
def get_pricing(current_user=Depends(get_current_user)):
    """Return current pricing config and whether we're in peak hours right now."""
    from ai_provider import _PRICING, _is_peak_hour, PROVIDER
    from datetime import datetime, timezone
    pricing = _PRICING.get(PROVIDER, {})
    return {
        "success":          True,
        "provider":         PROVIDER,
        "pricing":          pricing,
        "is_peak_now":      _is_peak_hour(PROVIDER),
        "utc_hour":         datetime.now(timezone.utc).hour,
        "peak_windows_utc": pricing.get("peak_windows", []),
        "peak_multiplier":  pricing.get("peak_multiplier", 1.0),
    }


# ── Pipeline Export / Import ──────────────────────────────────────────────────

@app.get("/pipeline/export/{pipeline_id}")
def export_pipeline(pipeline_id: str, current_user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """
    Export a pipeline as a self-contained JSON bundle that can be imported
    into any AIBridge instance (DEV → PROD promotion).
    Credentials are NOT included — the import step re-maps connectors by
    name/type so the destination environment can use its own credentials.
    """
    from fastapi.responses import JSONResponse
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline: raise HTTPException(404, "Pipeline not found")

    # Connector metadata (no passwords)
    src_connector = None
    tgt_connector = None
    if pipeline.connector_id:
        c = db.query(Connector).filter(Connector.id == pipeline.connector_id).first()
        if c:
            src_connector = {
                "name":           c.name,
                "connector_type": c.connector_type,
                "role":           c.role,
                "source_schema":  c.source_schema or "raw",
                "host_hint":      c.host,   # hint only — not used on import
                "port_hint":      c.port,
            }
    if pipeline.target_connector_id:
        c = db.query(Connector).filter(Connector.id == pipeline.target_connector_id).first()
        if c:
            tgt_connector = {
                "name":           c.name,
                "connector_type": c.connector_type,
                "role":           c.role,
                "source_schema":  c.source_schema or "raw",
                "host_hint":      c.host,
                "port_hint":      c.port,
            }

    # Latest version snapshot
    latest_version = db.query(PipelineVersion).filter(
        PipelineVersion.pipeline_id == pipeline_id,
        PipelineVersion.is_active    == True
    ).first()

    bundle = {
        "aibridge_export_version": "1.0",
        "exported_at":   datetime.utcnow().isoformat(),
        "exported_by":   current_user.email,
        "pipeline": {
            "name":                  pipeline.name,
            "source_description":    pipeline.source_desc or "",
            "business_requirements": pipeline.biz_requirements or "",
            "schedule":              pipeline.schedule or "manual",
            "source_schema":         pipeline.source_schema or "raw",
            "staging_schema":        pipeline.staging_schema or "staging",
            "warehouse_schema":      pipeline.warehouse_schema or "warehouse",
            "source_tables":         pipeline.source_tables or [],
            "artifacts":             pipeline.artifacts or {},
            "current_version":       pipeline.current_version or 1,
        },
        "connectors": {
            "source": src_connector,
            "target": tgt_connector,
        },
        "version_snapshot": {
            "version":        latest_version.version      if latest_version else 1,
            "version_label":  latest_version.version_label if latest_version else "v1",
            "change_summary": latest_version.change_summary if latest_version else "",
            "data_model":     latest_version.data_model   if latest_version else {},
            "sql_scripts":    latest_version.sql_scripts  if latest_version else {},
            "etl_mappings":   latest_version.etl_mappings if latest_version else {},
        } if latest_version else None,
    }

    return JSONResponse(
        content=bundle,
        headers={
            "Content-Disposition": f'attachment; filename="{pipeline.name.replace(" ", "_")}_aibridge_export.json"'
        }
    )


class ImportPipelineRequest(BaseModel):
    bundle:             dict            # the exported JSON bundle
    connector_map:      dict  = {}      # {"source": connector_id, "target": connector_id}
    name_override:      str   = ""      # rename the pipeline on import
    staging_schema:     str   = ""      # override staging schema
    warehouse_schema:   str   = ""      # override warehouse schema


@app.post("/pipeline/import")
def import_pipeline(req: ImportPipelineRequest, current_user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """
    Import a pipeline bundle (from /pipeline/export/{id}).
    connector_map remaps the exported connector names/types to actual connector
    IDs in this environment — required since credentials aren't exported.
    """
    workspace = get_user_workspace(current_user.id, db)
    wid       = workspace.get("id")

    bundle = req.bundle
    if bundle.get("aibridge_export_version") != "1.0":
        raise HTTPException(400, "Unrecognised export format. Expected aibridge_export_version 1.0.")

    p = bundle.get("pipeline", {})
    if not p:
        raise HTTPException(400, "Bundle missing pipeline data.")

    name             = req.name_override or p.get("name", "Imported Pipeline")
    staging_schema   = req.staging_schema   or p.get("staging_schema",   "staging")
    warehouse_schema = req.warehouse_schema or p.get("warehouse_schema", "warehouse")

    # Resolve connector IDs from the map — caller provides {"source": id, "target": id}
    src_connector_id = req.connector_map.get("source")
    tgt_connector_id = req.connector_map.get("target")

    # Validate connectors exist if provided
    if src_connector_id:
        if not db.query(Connector).filter(Connector.id == src_connector_id).first():
            raise HTTPException(404, f"Source connector '{src_connector_id}' not found.")
    if tgt_connector_id:
        if not db.query(Connector).filter(Connector.id == tgt_connector_id).first():
            raise HTTPException(404, f"Target connector '{tgt_connector_id}' not found.")

    artifacts = p.get("artifacts", {})

    # If a version snapshot is present, use it as the authoritative artifacts
    vs = bundle.get("version_snapshot")
    if vs and (vs.get("data_model") or vs.get("sql_scripts")):
        artifacts = {
            **artifacts,
            "data_model":   vs.get("data_model", artifacts.get("data_model", {})),
            "sql_scripts":  vs.get("sql_scripts", artifacts.get("sql_scripts", {})),
            "etl_mappings": vs.get("etl_mappings", artifacts.get("etl_mappings", {})),
        }

    pipeline = Pipeline(
        workspace_id        = wid,
        name                = name,
        source_desc         = p.get("source_description", ""),
        biz_requirements    = p.get("business_requirements", ""),
        schedule            = p.get("schedule", "manual"),
        source_schema       = p.get("source_schema", "raw"),
        staging_schema      = staging_schema,
        warehouse_schema    = warehouse_schema,
        source_tables       = p.get("source_tables", []),
        artifacts           = artifacts,
        connector_id        = src_connector_id or None,
        target_connector_id = tgt_connector_id or None,
    )
    db.add(pipeline); db.commit(); db.refresh(pipeline)

    # Auto-save v1 for the imported pipeline
    if artifacts.get("data_model") or artifacts.get("sql_scripts"):
        try:
            version = PipelineVersion(
                pipeline_id    = pipeline.id,
                workspace_id   = wid,
                created_by     = current_user.id,
                version        = 1,
                version_label  = vs.get("version_label", "v1") if vs else "v1",
                is_active      = True,
                data_model     = artifacts.get("data_model", {}),
                sql_scripts    = artifacts.get("sql_scripts", {}),
                etl_mappings   = artifacts.get("etl_mappings", {}),
                schema_hash    = artifacts.get("schema_hash", ""),
                change_summary = f"Imported from export (original: {bundle.get('exported_at', '')})"
            )
            db.add(version); db.commit()
        except Exception as e:
            print(f"[Import] Could not save v1: {e}")

    return {
        "success":     True,
        "pipeline_id": pipeline.id,
        "name":        pipeline.name,
        "message":     f"✓ Pipeline '{name}' imported successfully. "
                       f"{len((artifacts.get('sql_scripts') or {}).get('scripts', []))} SQL scripts ready."
    }


@app.get("/pipeline/export-list")
def list_exportable_pipelines(current_user=Depends(get_current_user),
                               db: Session = Depends(get_db)):
    """List pipelines available for export with their connector hints."""
    workspace = get_user_workspace(current_user.id, db)
    pipelines = db.query(Pipeline).filter(
        Pipeline.workspace_id == workspace.get("id")
    ).order_by(Pipeline.created_at.desc()).all()

    result = []
    for p in pipelines:
        src_name = tgt_name = None
        if p.connector_id:
            c = db.query(Connector).filter(Connector.id == p.connector_id).first()
            if c: src_name = f"{c.name} ({c.connector_type})"
        if p.target_connector_id:
            c = db.query(Connector).filter(Connector.id == p.target_connector_id).first()
            if c: tgt_name = f"{c.name} ({c.connector_type})"
        result.append({
            "id":               p.id,
            "name":             p.name,
            "source_connector": src_name,
            "target_connector": tgt_name,
            "script_count":     len((p.artifacts or {}).get("sql_scripts", {}).get("scripts", [])),
            "created_at":       str(p.created_at),
            "current_version":  p.current_version or 1,
        })
    return {"success": True, "pipelines": result}


@app.post("/migration/export-docs")
def migration_export_docs(
    payload: dict = Body(...),
    current_user=Depends(get_current_user)
):
    """
    Generate and download the Migration Requirements & Data Lineage
    document — available as soon as a scan completes (doesn't require SQL
    to have been generated yet).

    Expected payload:
      {
        "tables": [...scanResult.tables...],
        "mappings": [...scanResult.mappings...],
        "gaps": [...scanResult.gaps...],
        "domain": "retail", "ai_summary": "...",
        "resolutions": { "<gap column or index>": "<user's resolution text>" },
        "format": "docx" | "pdf"   (default "docx")
      }

    Returns the file directly as a download (not JSON).

    NOTE: this endpoint is intentionally placed at the very END of main.py
    (appended, not inserted between other endpoints) after it was
    accidentally deleted TWICE by patches to neighboring /migration/*
    endpoints whose text-boundary markers swept over wherever this was
    sitting. Appending to EOF avoids that fragility entirely — no future
    patch to another endpoint should ever need to touch the end of the file.
    """
    from agents.migration_agent import generate_migration_document, convert_docx_to_pdf
    from fastapi.responses import Response

    scan_result = {
        "tables":     payload.get("tables", []),
        "mappings":   payload.get("mappings", []),
        "gaps":       payload.get("gaps", []),
        "domain":     payload.get("domain", ""),
        "ai_summary": payload.get("ai_summary", ""),
    }
    resolutions = payload.get("resolutions", {})
    fmt = payload.get("format", "docx").lower()

    if not scan_result["tables"]:
        raise HTTPException(400, "No tables provided — run a scan first")

    try:
        docx_bytes = generate_migration_document(scan_result, resolutions)
    except Exception as e:
        raise HTTPException(500, f"Document generation failed: {e}")

    if fmt == "pdf":
        try:
            pdf_bytes = convert_docx_to_pdf(docx_bytes)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return Response(
            content=pdf_bytes, media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="migration_requirements.pdf"'}
        )

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="migration_requirements.docx"'}
    )




# ── Plug & Play: DWH Introspection ──────────────────────────────────────────
class DWHIntrospectRequest(BaseModel):
    connector_id: str
    schemas: list = None

@app.post("/dwh/introspect")
def dwh_introspect(req: DWHIntrospectRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Plug & Play: Connect to any existing DWH and auto-discover schema.
    Returns table classifications, relationships, and business context.
    """
    from dwh_introspector import introspect_connector

    # Get connector config
    connector = db.query(Connector).filter(
        Connector.id == req.connector_id,
        Connector.workspace_id == get_user_workspace(current_user.id, db).get("id")
    ).first()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    config = {
        "connector_type": connector.connector_type or "postgres",
        "host":           connector.host or "localhost",
        "port":           connector.port or 5432,
        "database_name":  connector.database_name or "postgres",
        "username":       connector.username or "postgres",
        "password":       connector.password or "",
        "schemas":        req.schemas or ([connector.source_schema] if connector.source_schema else None),
    }

    result = introspect_connector(config)
    return result

@app.get("/dwh/knowledge/{connector_id}")
def dwh_knowledge(connector_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Get cached knowledge graph for a connector."""
    from dwh_introspector import introspect_connector

    connector = db.query(Connector).filter(
        Connector.id == connector_id,
        Connector.workspace_id == get_user_workspace(current_user.id, db).get("id")
    ).first()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    config = {
        "connector_type": connector.connector_type or "postgres",
        "host":           connector.host or "localhost",
        "port":           connector.port or 5432,
        "database_name":  connector.database_name or "postgres",
        "username":       connector.username or "postgres",
        "password":       connector.password or "",
    }
    return introspect_connector(config)




# ── Multi-Language Voice Endpoints ──────────────────────────────────────────

class TranslateRequest(BaseModel):
    text:        str
    source_lang: str = "auto"
    target_lang: str = "en"

class VoiceQueryRequest(BaseModel):
    text:         str
    connector_id: str = ""
    pipeline_id:  str = ""
    source_lang:  str = "auto"
    respond_in_lang: str = ""  # if empty, respond in detected language

@app.get("/voice/languages")
def get_languages(current_user=Depends(get_current_user)):
    """Return all supported languages for voice mode."""
    from translation_agent import get_supported_languages
    return {"success": True, "languages": get_supported_languages()}

@app.post("/voice/detect-language")
def detect_language_endpoint(req: TranslateRequest, current_user=Depends(get_current_user)):
    """Detect language of given text."""
    from translation_agent import detect_language
    result = detect_language(req.text)
    return {"success": True, **result}

@app.post("/voice/translate")
def translate_endpoint(req: TranslateRequest, current_user=Depends(get_current_user)):
    """Translate text between languages."""
    from translation_agent import translate_to_english, translate_from_english
    if req.target_lang == "en":
        result = translate_to_english(req.text, req.source_lang)
        return {"success": True, "translated": result["english"], "detected_lang": result["original_lang"]}
    else:
        translated = translate_from_english(req.text, req.target_lang)
        return {"success": True, "translated": translated, "target_lang": req.target_lang}

@app.post("/voice/query")
def voice_query(req: VoiceQueryRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Multi-language voice query endpoint.
    1. Detect language of input
    2. Translate to English
    3. Run through /chat endpoint
    4. Translate answer back to original language
    """
    from translation_agent import process_multilang_query, translate_from_english
    from ai_provider import ask_ai_text

    # Step 1: Process language
    lang_info = process_multilang_query(req.text, req.connector_id, req.pipeline_id)
    english_query = lang_info["english_query"]
    detected_lang = lang_info["detected_lang"]
    respond_lang  = req.respond_in_lang or detected_lang

    print(f"[VoiceQuery] Lang: {lang_info['detected_lang_name']} | Query: {english_query}")

    # Step 2: Get schema context (same as /chat)
    schema_context = ""
    try:
        from dwh_introspector import introspect_connector
        if req.connector_id:
            _conn = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if _conn:
                _cfg = {
                    "connector_type": _conn.connector_type or "postgres",
                    "host": _conn.host, "port": _conn.port or 5432,
                    "database_name": _conn.database_name,
                    "username": _conn.username, "password": _conn.password,
                    "schemas": [_conn.source_schema] if _conn.source_schema else None,
                }
                _intro = introspect_connector(_cfg)
                schema_context = _intro.get("schema_context", "")
    except Exception as e:
        print(f"[VoiceQuery] Schema error: {e}")

    # Step 3: Generate SQL + answer (English)
    import re as _re
    sql_result = None
    english_answer = ""

    try:
        import re as _re_tbl
        _table_matches = _re_tbl.findall(r'(\S+\.\S+) \[', schema_context)
        available_tables = "\n".join(f"  - {t}" for t in _table_matches) if _table_matches else ""

        prompt = f"""{schema_context}

AVAILABLE TABLES:
{available_tables}

User question: {english_query}

RULES:
- Use ONLY tables from AVAILABLE TABLES
- Generate aggregated SQL (COUNT, SUM, AVG, GROUP BY)
- Use EXECUTE_SQL: prefix before SQL
- Be concise"""

        system = "You are AIBridge BI Assistant. Answer data questions by executing SQL. Always use EXECUTE_SQL: prefix. Use only tables from schema context."
        ai_response = ask_ai_text(prompt, system_prompt=system, agent_name="VoiceQueryAgent")

        # Extract and execute SQL
        if "EXECUTE_SQL:" in ai_response:
            sql_part = ai_response.split("EXECUTE_SQL:")[1].strip()
        else:
            blocks = _re.findall(r'```(?:sql)?\s*([\s\S]*?)```', ai_response, _re.IGNORECASE)
            sql_part = max(blocks, key=len).strip() if blocks else ""

        if sql_part:
            # Clean SQL
            sql = sql_part.split("```")[0].strip()
            # Execute
            import psycopg2
            if req.connector_id:
                _conn = db.query(Connector).filter(Connector.id == req.connector_id).first()
                if _conn:
                    pg_conn = psycopg2.connect(
                        host=_conn.host, port=_conn.port or 5432,
                        dbname=_conn.database_name,
                        user=_conn.username, password=_conn.password
                    )
                    cur = pg_conn.cursor()
                    cur.execute(sql)
                    rows = cur.fetchall()
                    cols = [d[0] for d in cur.description]
                    pg_conn.close()
                    sql_result = {"sql": sql, "columns": cols, "rows": [list(r) for r in rows]}

        english_answer = ai_response.replace(f"EXECUTE_SQL:{sql_part}" if "EXECUTE_SQL:" in ai_response else "", "").strip()
        english_answer = _re.sub(r'```[\s\S]*?```', '', english_answer).strip()

    except Exception as e:
        english_answer = f"I encountered an error: {str(e)}"
        print(f"[VoiceQuery] Query error: {e}")

    # Step 4: Translate answer back if needed
    final_answer = english_answer
    if respond_lang != "en" and english_answer:
        final_answer = translate_from_english(english_answer, respond_lang)
        print(f"[VoiceQuery] Answer translated to {respond_lang}")

    return {
        "success":         True,
        "original_text":   req.text,
        "english_query":   english_query,
        "detected_lang":   detected_lang,
        "detected_lang_name": lang_info["detected_lang_name"],
        "response":        final_answer,
        "english_response": english_answer,
        "sql_result":      sql_result,
        "web_speech_code": lang_info["web_speech_code"],
    }

# ── Chat Endpoint ──────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role:    str  # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    message:     str
    history:     list = []
    pipeline_id: str  = ""
    connector_id: str = ""

@app.post("/chat")
def chat(req: ChatRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Conversational AI endpoint for AIBridge.
    Privacy-safe: AI only sees schema, never raw warehouse data.
    AI generates SQL → AIBridge executes → results returned as natural language.
    """
    from ai_provider import ask_ai_text
    import psycopg2

    # 1. Get schema context — scoped to selected connector or pipeline
    schema_context = ""
    pipeline_summary = ""
    try:
        from dwh_introspector import introspect_connector

        if req.connector_id:
            # CONNECTION MODE — introspect selected connector only
            _conn = db.query(Connector).filter(Connector.id == req.connector_id).first()
            if _conn:
                _cfg = {
                    "connector_type": _conn.connector_type or "postgres",
                    "host":           _conn.host,
                    "port":           _conn.port or 5432,
                    "database_name":  _conn.database_name,
                    "username":       _conn.username,
                    "password":       _conn.password,
                    "schemas":        [_conn.source_schema] if _conn.source_schema else None,
                }
                _intro = introspect_connector(_cfg)
                if _intro.get("schema_context"):
                    schema_context = _intro["schema_context"]
                    print(f"[Chat] Connection mode — schema: {_conn.name} ({_conn.source_schema})")

        elif req.pipeline_id:
            # PIPELINE MODE — use pipeline's target warehouse schema
            pipeline = db.query(Pipeline).filter(Pipeline.id == req.pipeline_id).first()
            if pipeline:
                pipeline_summary = f"\nActive pipeline: {pipeline.name}"
                # Get target connector
                tgt_conn_id = pipeline.target_connector_id or pipeline.connector_id
                tgt_conn = db.query(Connector).filter(Connector.id == tgt_conn_id).first()
                if tgt_conn:
                    warehouse_schema = getattr(pipeline, 'warehouse_schema', None) or                                        (pipeline.artifacts or {}).get('warehouse_schema', 'warehouse')
                    _cfg = {
                        "connector_type": tgt_conn.connector_type or "postgres",
                        "host":           tgt_conn.host,
                        "port":           tgt_conn.port or 5432,
                        "database_name":  tgt_conn.database_name,
                        "username":       tgt_conn.username,
                        "password":       tgt_conn.password,
                        "schemas":        [warehouse_schema],
                    }
                    _intro = introspect_connector(_cfg)
                    if _intro.get("schema_context"):
                        schema_context = _intro["schema_context"]
                        print(f"[Chat] Pipeline mode — warehouse: {warehouse_schema}")

        # Fallback — global knowledge graph if nothing else worked
        if not schema_context:
            from warehouse_knowledge import get_warehouse_knowledge
            knowledge = get_warehouse_knowledge(db)
            if knowledge.get("schema_context"):
                schema_context = knowledge["schema_context"]
                print("[Chat] Fallback — using global knowledge graph")

    except Exception as e:
        schema_context = f"(Schema not available: {e})"
        print(f"[Chat] Schema error: {e}")

    # 2. Build conversation history
    history_text = ""
    for msg in req.history[-6:]:  # last 6 messages for context
        role = msg.get("role", "user")
        content = msg.get("content", "")
        history_text += f"\n{role.capitalize()}: {content}"

    # 3. Build system prompt — privacy-safe
    system_prompt = """You are AIBridge Assistant, an expert data engineering AI embedded in the AIBridge ETL platform.

PRIVACY RULES (CRITICAL):
- You NEVER see or request raw row-level data
- You only have access to schema (table/column names and types)
- When querying data, generate aggregated SQL only (COUNT, AVG, SUM, MIN, MAX, GROUP BY)
- Never generate SELECT * or queries that return individual rows

YOUR CAPABILITIES:
- Answer questions about pipeline health and status
- Generate safe aggregated SQL queries against the warehouse
- Explain data models, ETL flows, and transformations
- Help troubleshoot pipeline failures
- Suggest analytics and KPIs based on the schema

RESPONSE FORMAT:
- Be concise and helpful
- If generating SQL, wrap it in ```sql blocks
- If you need to query data to answer, say "Let me check..." and provide the SQL
- Always explain what the SQL does before showing it"""

    # 4. Build user prompt
    # Build explicit available tables list
    import re as _re_tbl
    _table_matches = _re_tbl.findall(r'(\S+\.\S+) \[', schema_context)
    _available_tables = "\n".join(f"  - {t}" for t in _table_matches) if _table_matches else "  (check schema context above)"

    user_prompt = f"""{schema_context}{pipeline_summary}

AVAILABLE TABLES (use ONLY these exact names):
{_available_tables}

Conversation history:{history_text}

User: {req.message}

RULES:
- Use ONLY the tables listed in AVAILABLE TABLES above
- Use exact schema.table format as shown (e.g. insdwh.fact_claims)
- Generate aggregated SQL only (COUNT, SUM, AVG, GROUP BY, no SELECT *)
- Prefix SQL with: EXECUTE_SQL:"""

    # 5. Get AI response
    ai_response = ask_ai_text(user_prompt, system_prompt=system_prompt, agent_name="ChatAgent")

    # 6. Check if AI wants to execute SQL
    sql_result = None
    final_response = ai_response

    if "EXECUTE_SQL:" in ai_response or ("SELECT" in ai_response.upper() and "FROM" in ai_response.upper() and ("warehouse." in ai_response.lower() or "fact_" in ai_response.lower() or "dim_" in ai_response.lower() or "insdwh." in ai_response.lower() or "bank." in ai_response.lower() or "stg_" in ai_response.lower())):
        try:
            # Extract SQL
            # Extract SQL — robust extraction from any response format
            import re as _re_sql
            sql_part = ""
            if "EXECUTE_SQL:" in ai_response:
                sql_part = ai_response.split("EXECUTE_SQL:")[1].strip()
            else:
                # Try ```sql blocks first
                _blocks = _re_sql.findall(r'```(?:sql)?[\s\S]*?\n([\s\S]*?)```', ai_response, _re_sql.IGNORECASE)
                if _blocks:
                    # Pick the block with SELECT
                    for b in _blocks:
                        if 'SELECT' in b.upper():
                            sql_part = b.strip()
                            break
                if not sql_part:
                    # Extract SELECT...to end of SQL (LIMIT, semicolon or newline after last keyword)
                    _sel = _re_sql.search(
                        r'(SELECT\b[\s\S]*?(?:LIMIT\s+\d+|ORDER\s+BY[\s\S]*?(?:LIMIT\s+\d+)?))(?:\s*;|\s*$|\s*\n\s*\n)',
                        ai_response, _re_sql.IGNORECASE
                    )
                    if _sel:
                        sql_part = _sel.group(1).strip()
            # Clean up markdown
            # Clean up markdown
            sql = sql_part.replace("```sql", "").replace("```", "").strip()
            # Extract just the SELECT statement
            import re
            sql_match = re.search(r'(SELECT\s+.+?)(?:;|$)', sql, re.IGNORECASE | re.DOTALL)
            if sql_match:
                sql = sql_match.group(1).strip()
                # Add warehouse. prefix to bare fact_/dim_ table names
                import re as _re_pfx
                sql = _re_pfx.sub(r'(?<![.\w])(fact_\w+|dim_\w+)(?![\w])', r'warehouse.\1', sql)
                sql = sql.replace('warehouse.warehouse.', 'warehouse.')  # avoid double prefix
                print(f"[ChatAgent] Executing SQL: {sql[:100]}")

                # Safety check — only allow aggregated queries
                sql_upper = sql.upper()
                has_aggregate = any(fn in sql_upper for fn in ['COUNT(', 'AVG(', 'SUM(', 'MIN(', 'MAX(', 'GROUP BY'])
                has_select_star = 'SELECT *' in sql_upper or 'SELECT\n*' in sql_upper

                if has_aggregate and not has_select_star:
                    with _chat_engine.connect() as _exec_conn:
                        _exec_r = _exec_conn.execute(_sa_chat.text(sql))
                        columns = list(_exec_r.keys())
                        results = _exec_r.fetchmany(50)

                    # Format results
                    result_text = " | ".join(columns) + "\n"
                    result_text += "-" * 40 + "\n"
                    for row in results:
                        result_text += " | ".join(str(v) for v in row) + "\n"

                    sql_result = {"sql": sql, "columns": columns, "rows": [[str(v) for v in r] for r in results]}

                    # Ask AI to interpret results
                    interpret_prompt = f"""The user asked: {req.message}

I ran this SQL: {sql}

Results:
{result_text}

Please provide a clear, concise natural language summary of these results. Be specific with numbers."""
                    final_response = ask_ai_text(interpret_prompt, system_prompt=system_prompt, agent_name="ChatAgent")
                else:
                    final_response = ai_response.replace("EXECUTE_SQL:", "\n```sql\n") + "\n```"
        except Exception as e:
            final_response = ai_response.replace("EXECUTE_SQL:", "").strip()
            sql_result = {"error": str(e)}

    return {
        "response": final_response,
        "sql_result": sql_result,
        "schema_available": bool(schema_context and "not available" not in schema_context)
    }










