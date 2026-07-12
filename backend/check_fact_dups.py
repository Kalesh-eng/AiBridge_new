with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if i > 810 and 'elif year_col:' in line:
        print(f"Found elif year_col at line {i+1}")
        # Find the return statement for year join
        for j in range(i, min(len(lines), i+12)):
            if 'AND dd.month = 1 AND dd.day = 1' in lines[j]:
                print(f"Found year join return at line {j+1}")
                # Replace year join with NULL date_key
                # Find the full return statement (may span multiple lines)
                start = j
                while start > i and 'return' not in lines[start]:
                    start -= 1
                # Replace from return to end of this statement
                end = j
                old_lines = lines[start:end+1]
                print(f"Replacing lines {start+1} to {end+1}")
                
                new_lines = [
                    '                    # No real date in source — skip dim_date join, set date_key = NULL\n',
                    '                    log(f"[SQLPatch] dim_date join: no real date in source — removing join, date_key will be NULL")\n',
                    '                    return \'\'\n',
                ]
                lines[start:end+1] = new_lines
                print("✓ Year join replaced with NULL")
                break
        break

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

import ast
with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print(f"Syntax OK — {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")