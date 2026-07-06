with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the end of _patch_sql_column_names — just before "patched.append(script)"
# and add a WHERE NOT EXISTS → IS NOT DISTINCT FROM fix for dim tables

for i, line in enumerate(lines):
    if 'if sql != original:' in line and i > 900:
        print(f"Found insertion point at line {i+1}")
        new_fix = [
            '            # Fix: WHERE NOT EXISTS on dim tables — replace = with IS NOT DISTINCT FROM\n',
            '            # so nullable columns dont cause duplicate rows on re-runs\n',
            '            if script.get("name", "").startswith("dim_") and "WHERE NOT EXISTS" in sql:\n',
            '                import re as _re3\n',
            '                def _fix_not_exists(m):\n',
            '                    cond = m.group(1)\n',
            '                    # Replace = with IS NOT DISTINCT FROM in NOT EXISTS conditions\n',
            '                    cond = _re3.sub(\n',
            '                        r\'(\\w+\\.\\w+)\\s*=\\s*(s|src)\\."(\\w+)"\',\n',
            '                        lambda mc: mc.group(1) + " IS NOT DISTINCT FROM " + mc.group(2) + \'."\' + mc.group(3) + \'"\',\n',
            '                        cond\n',
            '                    )\n',
            '                    return "WHERE NOT EXISTS (SELECT 1 FROM " + m.group(2) + " WHERE " + cond + ")"\n',
            '                sql = _re3.sub(\n',
            '                    r\'WHERE NOT EXISTS \\(SELECT 1 FROM (\\w+\\.\\w+) \\w+ WHERE (.+?)\\)\',\n',
            '                    lambda m: "WHERE NOT EXISTS (SELECT 1 FROM " + m.group(1) + " x WHERE " +\n',
            '                        _re3.sub(r\'(\\w+\\.\\w+)\\s*=\\s*(s|src)\\."(\\w+)"\',\n',
            '                        lambda mc: mc.group(1) + " IS NOT DISTINCT FROM " + mc.group(2) + \'."\' + mc.group(3) + \'"\',\n',
            '                        m.group(2)) + ")",\n',
            '                    sql, flags=_re3.IGNORECASE | _re3.DOTALL\n',
            '                )\n',
            '                if sql != original:\n',
            '                    log(f"[SQLPatch] WHERE NOT EXISTS: IS NOT DISTINCT FROM applied for {script.get(\'name\')}")\n',
        ]
        lines[i:i] = new_fix
        print("Inserted WHERE NOT EXISTS fix")
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
