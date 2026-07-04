with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'is_fact_stg = missing_tbl.startswith' in line:
        print(f"Found at line {i+1}")
        # Replace lines i through i+4 with better detection
        new_lines = [
            '            # Detect if this staging table is used by a fact script\n',
            '            # Check if any fact SQL script references this staging table\n',
            '            is_fact_stg = any(\n',
            '                missing_tbl in script.get("sql", "").lower()\n',
            '                for script in sql_scripts\n',
            '                if script.get("name", "").startswith("fact_")\n',
            '            )\n',
        ]
        # Find end of old block (distinct_clause line)
        end = i
        for j in range(i, min(len(lines), i+10)):
            if 'distinct_clause' in lines[j]:
                end = j + 1
                break
        lines[i:end] = new_lines + [lines[end-1]]  # keep distinct_clause line
        print(f"Fixed - replaced lines {i+1} to {end}")
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