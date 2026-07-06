with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    src = f.read()

# Add should_stop_fn and source_connector_type params
OLD = '''def execute_warehouse_scripts(
    pipeline_id, pipeline_name, sql_scripts,
    target_config, workspace_id, db_session=None,
    warehouse_schema="warehouse", staging_schema="staging",
    data_model=None   # ← NEW: used for smart intermediate staging creation
) -> dict:'''

NEW = '''def execute_warehouse_scripts(
    pipeline_id, pipeline_name, sql_scripts,
    target_config, workspace_id, db_session=None,
    warehouse_schema="warehouse", staging_schema="staging",
    data_model=None,
    should_stop_fn=None,
    source_connector_type=None
) -> dict:'''

if OLD in src:
    src = src.replace(OLD, NEW)
    # Also fix allow_destructive to use source_connector_type
    src = src.replace(
        'sf = check_sql_safety(sql, allow_destructive=False, script_name=name)',
        'is_snapshot = (source_connector_type or "").lower() in ("duckdb", "csv", "excel")\n                sf = check_sql_safety(sql, allow_destructive=is_snapshot, script_name=name)'
    )
    with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print("✓ Fixed execute_warehouse_scripts parameters")
else:
    print("✗ Function signature not found")
