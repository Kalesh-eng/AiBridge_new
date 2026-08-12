import ast

path = r"E:\AIBRIDGE_Claude\backend\main.py"

with open(path, encoding='utf-8') as f:
    lines = f.readlines()

# Find line 758 "schema_hash = compute_schema_hash" and insert ctx.raw_schema before it
target = None
for i, line in enumerate(lines):
    if 'schema_hash = compute_schema_hash(schema_text' in line:
        target = i
        print(f"Found at line {i+1}")
        break

if target is None:
    print("FAILED")
else:
    new_code = '''        # Pass enriched schema_text back to ctx so DataModelAgent gets real columns
        # Without this, DataModelAgent only sees 23-char table name, not 20 columns
        if schema_text and len(schema_text) > 30:
            ctx.raw_schema = schema_text
            if ctx.schema_result:
                ctx.schema_result["schema_text"] = schema_text
            print(f"[Phase 1] Schema propagated to ctx: {len(schema_text)} chars")

'''
    lines.insert(target, new_code)
    content = ''.join(lines)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    try:
        ast.parse(content)
        print("Patch OK + Syntax OK")
    except SyntaxError as e:
        print(f"Syntax ERROR: {e}")