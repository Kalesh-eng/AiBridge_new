DEPLOY_ENDPOINT = '''
@app.post("/migration/deploy")
def migration_deploy(
    req: dict,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Save a migration project as a runnable pipeline.
    Takes sql_scripts from /migration/generate-sql output,
    creates a Pipeline row, returns pipeline_id for execution
    via existing /pipeline/execute-async/{pipeline_id}.
    """
    from pydantic import BaseModel
    try:
        workspace = get_user_workspace(current_user.id, db)
        sql_scripts = req.get("sql_scripts", {})
        connection  = req.get("connection", {})
        domain      = req.get("domain", "migrated")
        project_name = req.get("project_name", f"Migration - {domain}")

        # Build artifacts in same format as native pipeline
        artifacts = {
            "sql_scripts": sql_scripts,
            "data_model":  req.get("data_model", {}),
            "etl_mappings": {"mappings": req.get("mappings", [])},
            "migration": {
                "source_mode": req.get("sub_mode", "reverse"),
                "upload_mode": req.get("upload_mode", "repository"),
                "domain":      domain,
                "scanned_at":  req.get("scanned_at", ""),
                "gaps_resolved": req.get("resolutions", {})
            }
        }

        # Find or use target connector
        target_connector_id = req.get("target_connector_id")
        if not target_connector_id and connection:
            # Try to find matching connector by host/database
            connectors = db.query(Connector).filter(
                Connector.workspace_id == workspace.get("id")
            ).all()
            for c in connectors:
                if (c.host == connection.get("host") and
                    c.database_name == connection.get("database")):
                    target_connector_id = c.id
                    break

        # Create pipeline row
        pipeline = Pipeline(
            workspace_id      = workspace.get("id"),
            name              = project_name,
            source_desc       = f"Migration project — {domain} domain",
            biz_requirements  = f"Migrated from existing warehouse. Domain: {domain}",
            schedule          = "manual",
            artifacts         = artifacts,
            source_schema     = "migration",
            source_columns    = {},
            source_tables     = [t.get("name") for t in req.get("tables", [])],
            target_connector_id = target_connector_id,
            staging_schema    = connection.get("warehouse_schema", "warehouse"),
            warehouse_schema  = connection.get("warehouse_schema", "warehouse")
        )
        db.add(pipeline)
        db.commit()
        db.refresh(pipeline)

        # Auto-save version 1
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
                change_summary = "Migration project initial version"
            )
            db.add(version)
            db.commit()
        except Exception as e:
            print(f"[Migration] Could not save version: {e}")

        return {
            "success":     True,
            "pipeline_id": pipeline.id,
            "pipeline_name": pipeline.name,
            "message":     "Migration pipeline created — ready to execute",
            "execute_url": f"/pipeline/execute-async/{pipeline.id}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
'''

with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    src = f.read()

MARKER = '# ── Recovery Agent ──'
if MARKER in src:
    src = src.replace(MARKER, DEPLOY_ENDPOINT + '\n' + MARKER)
    with open('E:/AIBRIDGE_Claude/backend/main.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print("✓ Added /migration/deploy endpoint")
else:
    print("✗ Marker not found")
