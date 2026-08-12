with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    content = f.read()

old = '''            # Fix 0b-pre2: Remove duplicate columns in INSERT column lists
            if "INSERT INTO" in sql.upper():
                import re as _re_ins
                def _dedup_insert_cols(m):
                    cols = [c.strip() for c in m.group(1).split(',')]
                    seen = set(); unique = []
                    for c in cols:
                        cl = c.lower()
                        if cl not in seen:
                            seen.add(cl); unique.append(c)
                    return '(' + ', '.join(unique) + ')'
                new_sql = _re_ins.sub(
                    r'INSERT\s+INTO\s+\w+\.\w+\s*(\([^)]+\))',
                    lambda m: m.group(0)[:m.group(0).index('(')] + _dedup_insert_cols(m),
                    sql, flags=_re_ins.IGNORECASE
                )
                if new_sql != sql:
                    sql = new_sql
                    log(f"[SQLPatch] Deduped INSERT columns for: {script.get('name')}")'''

new = '''            # Fix 0b-pre2: Remove duplicate columns in INSERT column lists
            if "INSERT INTO" in sql.upper():
                import re as _re_ins
                def _dedup_insert_cols(col_str):
                    cols = [c.strip() for c in col_str.split(',')]
                    seen = set(); unique = []
                    for c in cols:
                        cl = c.strip('"').lower()
                        if cl not in seen:
                            seen.add(cl); unique.append(c)
                    return ', '.join(unique)
                def _fix_insert(m):
                    return m.group(0).replace(m.group(1), _dedup_insert_cols(m.group(1)))
                new_sql = _re_ins.sub(
                    r'INSERT\s+INTO\s+\w+\.\w+\s*\(([^)]+)\)',
                    _fix_insert,
                    sql, flags=_re_ins.IGNORECASE
                )
                if new_sql != sql:
                    sql = new_sql
                    log(f"[SQLPatch] Deduped INSERT columns for: {script.get('name')}")'''

if old in content:
    content = content.replace(old, new, 1)
    print("✓ Fixed INSERT dedup — no double parens")
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
