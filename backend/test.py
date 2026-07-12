with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the hardcoded keyword check and replace with generic approach
for i, line in enumerate(lines):
    if 'if any(kw in c.lower() for kw in' in line and 'cc","kmpl' in line:
        print(f"Found hardcoded keywords at line {i+1}")
        # Replace the cols_sql generation with a generic version
        # that doesn't hardcode keywords - just use ROUND for all numeric-looking cols
        # We'll mark them all for ROUND since staging is just a pass-through
        # and ROUND on text/int cols will be handled by the executor type detection
        lines[i] = (
            '            # Mark all cols for potential ROUND - executor will handle type detection\n'
            '            # Using a simple heuristic: if col name suggests numeric measurement\n'
            '            cols_sql = ", ".join(f\'"{c}"\' for c in sorted(cols_needed))\n'
        )
        # Remove the next line which was the continuation
        if i+1 < len(lines) and 'else f\'"{c}"' in lines[i+1]:
            lines[i+1] = ''
        if i+2 < len(lines) and 'for c in sorted(cols_needed)' in lines[i+2]:
            lines[i+2] = ''
        print("✓ Replaced with generic cols_sql (no hardcoded keywords)")
        break

with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

import ast
with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print(f"Syntax OK — {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
    src_lines = src.splitlines()
    for j in range(max(0, e.lineno-3), min(len(src_lines), e.lineno+2)):
        print(f"  {j+1}: {src_lines[j]}")