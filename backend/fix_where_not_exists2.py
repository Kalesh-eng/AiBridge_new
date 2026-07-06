with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find and remove the broken WHERE NOT EXISTS fix
start = None
end = None
for i, line in enumerate(lines):
    if '# Fix: WHERE NOT EXISTS on dim tables' in line:
        start = i
    if start and 'log(f"[SQLPatch] WHERE NOT EXISTS: IS NOT DISTINCT FROM' in line:
        end = i + 1
        break

if start and end:
    print(f"Removing broken fix at lines {start+1} to {end}")
    # Replace with corrected version
    new_fix = [
        '            # Fix: WHERE NOT EXISTS on dim tables — replace = with IS NOT DISTINCT FROM\n',
        '            # Preserves original aliases — does NOT rename them\n',
        '            if script.get("name", "").startswith("dim_") and "WHERE NOT EXISTS" in sql:\n',
        '                import re as _re3\n',
        '                # Find the NOT EXISTS subquery and replace = with IS NOT DISTINCT FROM\n',
        '                # Pattern: d.col = s."Col" OR d.col = src."Col"\n',
        '                new_sql = _re3.sub(\n',
        '                    r\'(\\w+\\.\\w+)\\s*=\\s*(s|src)\\."(\\w+)"\',\n',
        '                    lambda m: m.group(1) + " IS NOT DISTINCT FROM " + m.group(2) + \'."\' + m.group(3) + \'"\',\n',
        '                    sql\n',
        '                )\n',
        '                if new_sql != sql:\n',
        '                    sql = new_sql\n',
        '                    log(f"[SQLPatch] WHERE NOT EXISTS: IS NOT DISTINCT FROM applied for {script.get(\'name\')}")\n',
    ]
    lines[start:end] = new_fix
    print("Fixed")

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
