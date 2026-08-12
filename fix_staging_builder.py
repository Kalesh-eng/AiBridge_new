with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    content = f.read()

old = '''        # Step 5: Pick best raw staging table (most columns = most complete)
        best_raw = max(raw_staging, key=lambda t: len(raw_staging[t]))'''

new = '''        # Step 5: Pick best raw staging table
        # Prefer: (1) table matching pipeline source table name, (2) most rows, (3) most columns
        def _raw_score(tbl):
            # Prefer stg_raw_* tables (direct source extracts)
            if tbl.startswith("stg_raw_"):
                return (2, len(raw_staging[tbl]))
            # Avoid stg_car, stg_location etc (intermediate tables)
            for missing in missing_tables:
                if tbl == missing:
                    return (0, len(raw_staging[tbl]))
            return (1, len(raw_staging[tbl]))
        best_raw = max(raw_staging, key=_raw_score)'''

if old in content:
    content = content.replace(old, new, 1)
    print("✓ Fixed StagingBuilder source table selection")
else:
    print("Pattern not found")

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR: {e}")
