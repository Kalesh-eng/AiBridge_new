with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    content = f.read()

old = '''                log(f"[SQLPatch] Stripped ON CONFLICT DO UPDATE from dim: {script.get('name')}")
            # Fix 0b: SERIAL PRIMARY KEY INTEGER'''

new = '''                log(f"[SQLPatch] Stripped ON CONFLICT DO UPDATE from dim: {script.get('name')}")
            # Fix 0b-pre: Remove duplicate column definitions in CREATE TABLE
            if "CREATE TABLE" in sql.upper():
                import re as _re_dup
                def _dedup_create_table(m):
                    cols_block = m.group(1)
                    lines = [l.strip() for l in cols_block.split(',')]
                    seen_cols = set()
                    unique_lines = []
                    for line in lines:
                        # Extract column name (first word)
                        col_name = line.split()[0].strip('"').lower() if line.split() else ""
                        if col_name and col_name not in seen_cols:
                            seen_cols.add(col_name)
                            unique_lines.append(line)
                        elif col_name and col_name in seen_cols:
                            pass  # skip duplicate
                        else:
                            unique_lines.append(line)
                    return "(" + ",\\n    ".join(unique_lines) + ")"
                new_sql = _re_dup.sub(
                    r\'\\(([^)]+)\\)\',
                    lambda m: _dedup_create_table(m) if "SERIAL" in m.group(0).upper() or len(m.group(1)) > 50 else m.group(0),
                    sql, count=1
                )
                if new_sql != sql:
                    sql = new_sql
                    log(f"[SQLPatch] Deduped CREATE TABLE columns for: {script.get(\'name\')}")
            # Fix 0b: SERIAL PRIMARY KEY INTEGER'''

if old in content:
    content = content.replace(old, new, 1)
    print("✓ Added duplicate column fix")
else:
    print("Pattern not found")

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
