with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', encoding='utf-8') as f:
    content = f.read()

old = '''        src_table = _ensure_stg_prefix(dim.get("source_table", ""))'''

new = '''        src_table = _ensure_stg_prefix(dim.get("source_table", ""))
        # For flat file sources: if src_table is a narrow entity table (stg_car, stg_location etc)
        # that was derived from a single CSV, override to use the raw staging table
        # The raw staging table has ALL columns needed for dim population
        if src_table and not src_table.startswith("stg_raw_"):
            # Check if actual_staging_tables hint is available in the data model
            raw_hint = data_model.get("_raw_staging_table", "")
            if not raw_hint:
                # Derive from source tables in schema_analysis embedded in data model
                pass  # will be overridden at prompt level via actual_staging_tables hint'''

if old in content:
    content = content.replace(old, new, 1)
    print("✓ Added src_table override comment")
else:
    print("Pattern not found")

# The better fix: add actual_staging_tables to the prompt as a MUST USE hint
# Find where actual_staging_tables is added to the prompt
old2 = '''    actual_cols_hint = ""
    if raw_schema:'''

new2 = '''    # Build staging table hint — tells AI which staging tables ACTUALLY exist
    staging_hint = ""
    if actual_staging_tables:
        raw_tables = [t for t in actual_staging_tables if "raw" in t.lower()]
        all_tables = actual_staging_tables
        staging_hint = f"""
AVAILABLE STAGING TABLES (ONLY these exist — do NOT reference others):
{chr(10).join(f"  - staging.{t}" for t in all_tables)}

CRITICAL FOR FLAT FILE / CSV SOURCES:
- The RAW table(s) have ALL columns: {", ".join(raw_tables) if raw_tables else all_tables[0] if all_tables else ""}
- Narrow entity tables (stg_car, stg_location etc) have ONLY 1-2 columns
- For dim population, READ FROM THE RAW TABLE, not the narrow entity table
- Use: FROM staging.{raw_tables[0] if raw_tables else (all_tables[0] if all_tables else "stg_raw_source")} s
- NEVER read all 20 columns from stg_car which only has Brand column!
"""

    actual_cols_hint = ""
    if raw_schema:'''

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("✓ Added staging table hint to prompt")
else:
    print("Pattern 2 not found")

with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
    lines = content.splitlines()
    for j in range(max(0,e.lineno-3), min(len(lines),e.lineno+2)):
        print(f"  {j+1}: {lines[j]}")
