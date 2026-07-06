with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find "if sql != original:" after line 940
for i, line in enumerate(lines):
    if i > 940 and 'if sql != original:' in line:
        print(f"Found insertion point at line {i+1}")
        new_fix = [
            '            # Fix: WHERE NOT EXISTS — use IS NOT DISTINCT FROM for nullable columns\n',
            '            if script.get("name", "").startswith("dim_") and "WHERE NOT EXISTS" in sql:\n',
            '                import re as _re3\n',
            '                new_sql = _re3.sub(\n',
            '                    r\'(\\w+\\.\\w+)\\s*=\\s*(s|src)\\."(\\w+)"\',\n',
            '                    lambda m: m.group(1) + " IS NOT DISTINCT FROM " + m.group(2) + \'."\'+ m.group(3) + \'"\',\n',
            '                    sql\n',
            '                )\n',
            '                if new_sql != sql:\n',
            '                    sql = new_sql\n',
            '                    log(f"[SQLPatch] WHERE NOT EXISTS: IS NOT DISTINCT FROM applied for {script.get(\'name\')}")\n',
        ]
        lines[i:i] = new_fix
        print("Inserted fix")
        break

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

import ast
with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print(f"Syntax OK - {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
