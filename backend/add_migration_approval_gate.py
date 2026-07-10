NEW_BLOCK = '''@app.post("/migration/generate-sql")
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

    Expected payload:
      {
        "tables": [...], "mappings": [...], "gaps": [...],
        "resolutions": { "<gap column or index>": "<user's resolution text>" },
        "domain": "retail",
        "staging_schema": "staging" (optional), "warehouse_schema": "warehouse" (optional)
      }

    Response:
      { "success": true, "approval_id": "...", "sql_scripts": {"scripts": [...]},
        "risk_level": "low"|"medium"|"high", "generated_at": "..." }
    """
    from agents.migration_agent import generate_sql_scripts

    tables           = payload.get("tables", [])
    mappings         = payload.get("mappings", [])
    gaps             = payload.get("gaps", [])
    resolutions      = payload.get("resolutions", {})
    domain           = payload.get("domain", "")
    staging_schema   = payload.get("staging_schema", "staging")
    warehouse_schema = payload.get("warehouse_schema", "warehouse")

    if not tables:
        raise HTTPException(400, "No tables provided — run a scan first")

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

    workspace = get_user_workspace(current_user.id, db)
    approval = ApprovalQueue(
        workspace_id=workspace.get("id"),
        approval_type="migration_sql_scripts",
        title=f"Migration SQL — {len(scripts)} scripts ({domain or 'unknown domain'})",
        description=(
            f"{unmapped_count} unmapped column(s), {unresolved_count} needing manual review. "
            f"Review each script before deploying to the warehouse."
        ),
        proposed_data={
            "sql_scripts":      result["sql_scripts"],
            "tables":           tables,
            "mappings":         mappings,
            "gaps":             gaps,
            "resolutions":      resolutions,
            "domain":           domain,
            "staging_schema":   staging_schema,
            "warehouse_schema": warehouse_schema,
        },
        context={
            "domain": domain, "staging_schema": staging_schema,
            "warehouse_schema": warehouse_schema
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
    Deploy an APPROVED migration SQL set: requires approval_id from
    /migration/generate-sql, and that approval must be "approved" or
    "edited" (via the existing /pipeline/approve-sql) before anything runs.
    Creates a Pipeline + PipelineVersion row, then RUNS it immediately via
    the dedicated migration execution flow in agents/migration_agent.py
    (ETLAgent -> QualityAgent -> ExecutionAgent -> RecoveryAgent ->
    AnalyticsAgent) — a separate path from /pipeline/execute-async.

    Expects in `req`:
      approval_id (REQUIRED), source_connector_id (REQUIRED),
      target_connector_id, project_name, source_schema, source_tables
      (optional — derived from mappings if omitted).
    """
    from agents.migration_agent import run_migration_deployment

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
        sql_scripts   = approved_data.get("sql_scripts", {})
        domain        = approved_data.get("domain", "migrated")
        mappings      = approved_data.get("mappings", [])
        tables        = approved_data.get("tables", [])

        source_schema    = req.get("source_schema", "raw")
        staging_schema   = req.get("staging_schema") or approved_data.get("staging_schema", "staging")
        warehouse_schema = req.get("warehouse_schema") or approved_data.get("warehouse_schema", "warehouse")
        project_name     = req.get("project_name", f"Migration - {domain}")

        artifacts = {
            "sql_scripts": sql_scripts,
            "data_model":  req.get("data_model", {}),
            "etl_mappings": {"mappings": mappings},
            "migration": {
                "domain": domain, "approval_id": approval_id,
            }
        }

        source_connector_id = req.get("source_connector_id")
        if not source_connector_id:
            raise HTTPException(400, "source_connector_id is required — the legacy system "
                                      "ETLAgent extracts source tables from.")
        src_connector = db.query(Connector).filter(Connector.id == source_connector_id).first()
        if not src_connector:
            raise HTTPException(404, "Source connector not found")

        target_connector_id = req.get("target_connector_id")
        if not target_connector_id:
            raise HTTPException(400, "target_connector_id is required — the warehouse being migrated into.")
        tgt_connector = db.query(Connector).filter(Connector.id == target_connector_id).first()
        if not tgt_connector:
            raise HTTPException(404, "Target connector not found")

        source_tables = req.get("source_tables") or list(dict.fromkeys(
            m.get("source_table") for m in mappings
            if m.get("source_table") and not m.get("needs_review")
        ))

        pipeline = Pipeline(
            workspace_id      = workspace.get("id"),
            name              = project_name,
            source_desc       = f"Migration project - {domain} domain",
            biz_requirements  = f"Migrated from existing warehouse. Domain: {domain}",
            schedule          = "manual",
            artifacts         = artifacts,
            connector_id      = src_connector.id,
            source_schema     = "migration",
            source_columns    = {},
            source_tables     = [t.get("name") for t in tables],
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
                sql_scripts    = sql_scripts,
                etl_mappings   = artifacts.get("etl_mappings", {}),
                schema_hash    = "",
                change_summary = f"Migration deployment (approval {approval_id})"
            )
            db.add(version); db.commit()
        except Exception as e:
            print(f"[Migration] Could not save version: {e}")

        source_config = _cfg(src_connector)
        target_config = _cfg(tgt_connector)

        result = run_migration_deployment(
            source_connector_config=source_config,
            target_connector_config=target_config,
            source_schema=source_schema,
            staging_schema=staging_schema,
            warehouse_schema=warehouse_schema,
            source_tables=source_tables,
            sql_scripts=sql_scripts,
            data_model=req.get("data_model", {}),
            pipeline_id=pipeline.id,
            workspace_id=workspace.get("id"),
        )

        # Link this run back to the approval that authorized it
        try:
            approval.pipeline_id = pipeline.id
            db.commit()
        except Exception as e:
            print(f"[Migration] Could not link approval to pipeline: {e}")

        try:
            run = PipelineRun(
                run_id=f"{pipeline.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                pipeline_id=pipeline.id, workspace_id=workspace.get("id"),
                status="success" if result.get("success") else "failed",
                started_at=datetime.utcnow(), ended_at=datetime.utcnow(),
                rows_loaded=result.get("warehouse", {}).get("total_rows", 0),
                log="\\n".join(result.get("pipeline_log", []) or result.get("log", []))
            )
            db.add(run); db.commit()
        except Exception as e:
            print(f"[Migration] Could not save run record: {e}")

        return {
            "success":       result.get("success", False),
            "pipeline_id":   pipeline.id,
            "pipeline_name": pipeline.name,
            "stage":         result.get("stage"),
            "error":         result.get("error"),
            "staging":       result.get("staging"),
            "warehouse":     result.get("warehouse"),
            "quality":       result.get("quality"),
            "log":           result.get("log", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))'''

with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    src = f.read()

START_MARKER = '@app.post("/migration/generate-sql")'
END_MARKER = '# ── Recovery Agent ──'

start_idx = src.find(START_MARKER)
if start_idx == -1:
    print("Could not find /migration/generate-sql — nothing to replace.")
else:
    end_idx = src.find(END_MARKER, start_idx)
    if end_idx == -1:
        print("Could not find the Recovery Agent marker after /migration/generate-sql — aborting to avoid corrupting the file.")
    else:
        before = src[:start_idx]
        after  = src[end_idx:]
        new_src = before + NEW_BLOCK + '\n\n\n' + after
        with open('E:/AIBRIDGE_Claude/backend/main.py', 'w', encoding='utf-8') as f:
            f.write(new_src)
        print("Replaced /migration/generate-sql and /migration/deploy with the approval-gated versions.")
        print(f"  Old span: chars {start_idx} to {end_idx}")

print("Done")
