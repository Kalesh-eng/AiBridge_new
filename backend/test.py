with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'sql = sql_match.group(1).strip()' in line and i > 3850:
        print(f"Found at line {i+1}")
        insert_at = i + 1
        new_code = [
            '                # Add warehouse. prefix to bare fact_/dim_ table names\n',
            '                import re as _re_pfx\n',
            '                sql = _re_pfx.sub(r\'(?<![.\\w])(fact_\\w+|dim_\\w+)(?![\\w])\', r\'warehouse.\\1\', sql)\n',
            '                sql = sql.replace(\'warehouse.warehouse.\', \'warehouse.\')  # avoid double prefix\n',
            '                print(f"[ChatAgent] Executing SQL: {sql[:100]}")\n',
        ]
        lines[insert_at:insert_at] = new_code
        print(f"✓ Inserted schema prefix and debug log")
        break

with open('E:/AIBRIDGE_Claude/backend/main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

import ast
with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print(f"Syntax OK — {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")