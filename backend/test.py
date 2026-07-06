with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'For small dims' in line and 'text/categorical' in line:
        print(f"Found fallback comment at line {i+1}")
        # Find "select_cols = text_cols" line
        for j in range(i, min(len(lines), i+15)):
            if 'select_cols = text_cols' in lines[j]:
                lines[j] = '                    select_cols = [c for c, dt in all_col_info]  # Use ALL columns\n'
                print(f"Fixed line {j+1} — now uses ALL columns instead of text-only")
                break
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
    print(f"ERROR: {e}")