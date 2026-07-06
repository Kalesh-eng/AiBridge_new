with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    src = f.read()

# Find the widen_numeric_decl function and make it widen ALL NUMERIC(10,2) to NUMERIC(20,6)
OLD = '''                def widen_numeric_decl(m):
                    col_name = m.group(1)
                    old_prec, old_scale = m.group(2), m.group(3)
                    key = col_name.lower().replace("_", "")'''

NEW = '''                def widen_numeric_decl(m):
                    col_name = m.group(1)
                    old_prec, old_scale = m.group(2), m.group(3)
                    # Always widen NUMERIC(10,2) to NUMERIC(20,6) for dim tables
                    # This handles cases where dim col name differs from source col name
                    if old_prec == "10" and old_scale == "2":
                        log(f"[SQLPatch] Widening {col_name} precision: NUMERIC(10,2) → NUMERIC(20,6) to match source")
                        return f"{col_name} NUMERIC(20,6)"
                    key = col_name.lower().replace("_", "")'''

if OLD in src:
    src = src.replace(OLD, NEW)
    with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print("Fixed — all NUMERIC(10,2) widened to NUMERIC(20,6)")
else:
    print("Pattern not found")

import ast
try:
    ast.parse(src)
    print(f"Syntax OK - {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR: {e}")
