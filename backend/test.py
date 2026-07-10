with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

changes = 0

# Fix 1: _patch_sql_column_names — lines 463-464 (0-indexed: 462-463)
# Find "if not _is_pg(target_config):" after line 461
for i, line in enumerate(lines):
    if i > 458 and i < 475 and 'if not _is_pg(target_config):' in line:
        next_line = lines[i+1] if i+1 < len(lines) else ''
        if 'return sql_scripts' in next_line:
            print(f"Found Fix 1 at line {i+1}")
            # Remove the if not _is_pg guard (2 lines)
            lines[i]   = '    # universal: runs for all target DB types\n'
            lines[i+1] = '    # (connection handled per-DB below)\n'
            changes += 1
            print("✓ Fix 1: removed _is_pg guard from _patch_sql_column_names")
            break

# Fix the _pg_connect call right after (now around line 466)
for i, line in enumerate(lines):
    if i > 460 and i < 480 and 'conn = _pg_connect(target_config)' in line:
        # Check it's in _patch_sql_column_names context
        print(f"Found _pg_connect in patch function at line {i+1}")
        lines[i] = '''        ct = target_config.get("connector_type", "postgres").lower()
        if ct in ("postgres", "postgresql", "redshift"):
            conn = _pg_connect(target_config)
        elif ct == "snowflake":
            from universal_connector import _snowflake_connect
            conn = _snowflake_connect(target_config)
        elif ct in ("mysql", "mariadb"):
            from universal_connector import _mysql_connect
            conn = _mysql_connect(target_config)
        elif ct in ("sqlserver", "mssql", "azuresql"):
            from universal_connector import _sqlserver_connect
            conn = _sqlserver_connect(target_config)
        else:
            conn = _pg_connect(target_config)
'''
        changes += 1
        print("✓ Fix 1b: _patch_sql_column_names uses universal connection")
        break

# Fix 2: _auto_create_intermediate_staging — around line 981-986
for i, line in enumerate(lines):
    if i > 978 and i < 990 and 'if not _is_pg(target_config):' in line:
        next_line = lines[i+1] if i+1 < len(lines) else ''
        if 'return' in next_line and 'sql_scripts' not in next_line:
            print(f"Found Fix 2 at line {i+1}")
            lines[i]   = '    # universal: runs for all target DB types\n'
            lines[i+1] = '    ct_stg = target_config.get("connector_type", "postgres").lower()\n'
            changes += 1
            print("✓ Fix 2: removed _is_pg guard from _auto_create_intermediate_staging")
            break

# Fix the _pg_connect in _auto_create_intermediate_staging
for i, line in enumerate(lines):
    if i > 983 and i < 996 and 'conn = _pg_connect(target_config)' in line:
        print(f"Found _pg_connect in staging function at line {i+1}")
        lines[i] = '''    if ct_stg in ("postgres", "postgresql", "redshift"):
        conn = _pg_connect(target_config)
    elif ct_stg == "snowflake":
        from universal_connector import _snowflake_connect
        conn = _snowflake_connect(target_config)
    elif ct_stg in ("mysql", "mariadb"):
        from universal_connector import _mysql_connect
        conn = _mysql_connect(target_config)
    elif ct_stg in ("sqlserver", "mssql", "azuresql"):
        from universal_connector import _sqlserver_connect
        conn = _sqlserver_connect(target_config)
    else:
        conn = _pg_connect(target_config)
'''
        changes += 1
        print("✓ Fix 2b: _auto_create_intermediate_staging uses universal connection")
        break

# Fix 4: _expand_composite_joins — around line 291
for i, line in enumerate(lines):
    if i > 287 and i < 298 and 'if not _is_pg(target_config):' in line:
        next_line = lines[i+1] if i+1 < len(lines) else ''
        if 'return sql_scripts' in next_line:
            print(f"Found Fix 4 at line {i+1}")
            lines[i]   = '    # universal: runs for all target DB types\n'
            lines[i+1] = '    # (expand composite joins for any target)\n'
            changes += 1
            print("✓ Fix 4: removed _is_pg guard from _expand_composite_joins")
            break

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"\n{changes} fixes applied")

import ast
with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print(f"Syntax OK — {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")