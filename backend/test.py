NEW_DEPLOY_ENDPOINT = '''@app.post("/migration/deploy")
def migration_deploy(
    req: dict,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Deploy an APPROVED migration SQL set — as ONE INDEPENDENT PIPELINE PER
    INFORMATICA MAPPING (typically one per target table), not a single
    monolithic pipeline for the whole repository. This gives each table
    its own Pipeline row, its own PipelineRun history, and failure
    isolation: if fact_car_listings' extraction fails, dim_car's pipeline
    (already run separately) is completely unaffected.

    Requires approval_id from /migration/generate-sql, and that approval
    must be "approved" or "edited" (via the existing /pipeline/approve-sql)
    before anything runs — this check happens ONCE, up front, covering the
    whole approved SQL set; only the actual creation/execution is split
    per-table afterward.

    Expects in `req`:
      approval_id (REQUIRED), source_connector_id (REQUIRED),
      target_connector_id (REQUIRED), project_name, source_schema.

    Returns:
      {"success": bool (true if ALL sub-pipelines succeeded),
       "pipelines": [{"pipeline_id", "table", "mapping_name", "success",
                       "stage", "error", "staging", "warehouse", "quality"}, ...]}
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
        all_scripts  = approved_data.get("sql_scripts", {}).get("scripts", [])
        domain       = approved_data.get("domain", "migrated")
        all_mappings = approved_data.get("mappings", [])
        all_tables   = approved_data.get("tables", [])

        if not all_scripts:
            raise HTTPException(400, "No SQL scripts found in this approval.")

        source_schema    = req.get("source_schema", "raw")
        staging_schema   = req.get("staging_schema") or approved_data.get("staging_schema", "staging")
        warehouse_schema = req.get("warehouse_schema") or approved_data.get("warehouse_schema", "warehouse")
        project_prefix   = req.get("project_name", f"Migration - {domain}")

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

        source_config = _cfg(src_connector)
        target_config = _cfg(tgt_connector)

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
                name              = f"{project_prefix} \u2014 {pipeline_label}",
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
                    log="\\n".join(result.get("pipeline_log", []) or result.get("log", []))
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
            "success":   all(r["success"] for r in results),
            "pipelines": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))'''

with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    src = f.read()

START_MARKER = '@app.post("/migration/deploy")'
END_MARKER = '# ── Recovery Agent ──'

start_idx = src.find(START_MARKER)
if start_idx == -1:
    print("Could not find /migration/deploy — nothing to replace.")
else:
    end_idx = src.find(END_MARKER, start_idx)
    if end_idx == -1:
        print("Could not find the Recovery Agent marker after /migration/deploy — aborting to avoid corrupting the file.")
    else:
        before = src[:start_idx]
        after  = src[end_idx:]
        new_src = before + NEW_DEPLOY_ENDPOINT + '\n\n\n' + after
        with open('E:/AIBRIDGE_Claude/backend/main.py', 'w', encoding='utf-8') as f:
            f.write(new_src)
        print("Replaced /migration/deploy with the per-mapping pipeline-splitting version.")
        print(f"  Old span: chars {start_idx} to {end_idx}")

print("Done")