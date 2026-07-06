with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the widen_numeric_decl function and add fuzzy matching
for i, line in enumerate(lines):
    if 'def widen_numeric_decl(m):' in line:
        print(f"Found widen_numeric_decl at line {i+1}")
        # Find the key = col_name.lower().replace("_", "") line
        for j in range(i, min(len(lines), i+10)):
            if 'key = col_name.lower().replace' in lines[j]:
                # Add fuzzy lookup after the key line
                insert_at = j + 1
                new_lines = [
                    '                    # Also check fuzzy match — dim col name may differ from source\n',
                    '                    # e.g. max_power in dim maps to Horsepower in source\n',
                    '                    if key not in src_prec_lookup:\n',
                    '                        for src_col_key in src_prec_lookup:\n',
                    '                            if (key in src_col_key or src_col_key in key) and len(key) > 4:\n',
                    '                                key = src_col_key\n',
                    '                                break\n',
                ]
                lines[insert_at:insert_at] = new_lines
                print(f"Inserted fuzzy lookup at line {insert_at+1}")
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
    print(f"ERROR at line {e.lineno}: {e.msg}")