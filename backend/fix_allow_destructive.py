with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    src = f.read()

OLD = 'sf = check_sql_safety(sql, allow_destructive=False, script_name=name)'
NEW = 'is_snapshot = (source_connector_type or "").lower() in ("duckdb", "csv", "excel")\n                sf = check_sql_safety(sql, allow_destructive=is_snapshot, script_name=name)'

if OLD in src:
    src = src.replace(OLD, NEW)
    with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print("Fixed allow_destructive for snapshot")
else:
    print("Not found")

import ast
try:
    ast.parse(src)
    print(f"Syntax OK - {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR: {e}")
