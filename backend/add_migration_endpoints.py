MIGRATION_ENDPOINTS = '''
# ── Migration Agent ────────────────────────────────────────────────────────────
@app.post("/migration/scan")
async def migration_scan(
    connection:   str = Form(...),
    sub_mode:     str = Form("reverse"),
    upload_mode:  str = Form("repository"),
    files:        List[UploadFile] = File(default=[]),
    current_user=Depends(get_current_user)
):
    """
    Scan existing warehouse + optionally parse uploaded mapping files.
    Returns reverse data model, mappings, gaps, and data dictionary.
    """
    import json, tempfile, os, shutil
    from agents.migration_agent import scan_warehouse, parse_informatica_xml, parse_dbt_yml, detect_gaps

    try:
        conn_config = json.loads(connection)
    except Exception:
        raise HTTPException(400, "Invalid connection JSON")

    warehouse_schema = conn_config.get("warehouse_schema", "warehouse")

    # Step 1: Scan warehouse
    scan_result = scan_warehouse(conn_config, warehouse_schema, sub_mode)
    if not scan_result.get("success"):
        raise HTTPException(400, f"Warehouse scan failed: {scan_result.get('error')}")

    # Step 2: Parse uploaded mapping files
    all_mappings = []
    if files:
        tmp_dir = tempfile.mkdtemp()
        try:
            for f in files:
                content = await f.read()
                fname   = f.filename.lower()
                if fname.endswith(".xml"):
                    mappings = parse_informatica_xml(content.decode("utf-8", errors="ignore"))
                    all_mappings.extend(mappings)
                elif fname.endswith(".yml") or fname.endswith(".yaml"):
                    mappings = parse_dbt_yml(content.decode("utf-8", errors="ignore"))
                    all_mappings.extend(mappings)
                # SSIS, ODI, BRD parsers — future
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # Step 3: Detect gaps
    gaps = detect_gaps(scan_result["tables"], all_mappings) if all_mappings else []

    # Add coverage calculation
    total_cols   = sum(len(t.get("columns", [])) for t in scan_result["tables"])
    mapped_cols  = len(all_mappings)
    coverage     = round((mapped_cols / total_cols) * 100) if total_cols > 0 else 90

    return {
        **scan_result,
        "mappings":    all_mappings,
        "gaps":        gaps,
        "coverage":    coverage,
        "upload_mode": upload_mode,
        "files_count": len(files)
    }


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
'''

with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    src = f.read()

# Add Form and File imports if not present
if 'from fastapi import' in src and 'Form' not in src:
    src = src.replace(
        'from fastapi import FastAPI, HTTPException, Depends, UploadFile, File',
        'from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form'
    )
    print("✓ Added Form import")

# Add endpoint before Recovery Agent section
MARKER = '# ── Recovery Agent ──'
if MARKER in src:
    src = src.replace(MARKER, MIGRATION_ENDPOINTS + '\n' + MARKER)
    print("✓ Added migration endpoints")
else:
    print("✗ Marker not found")

with open('E:/AIBRIDGE_Claude/backend/main.py', 'w', encoding='utf-8') as f:
    f.write(src)

print("Done")
