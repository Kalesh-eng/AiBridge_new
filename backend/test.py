with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the SQL extraction block
for i, line in enumerate(lines):
    if '# Extract SQL from EXECUTE_SQL: prefix or markdown code block' in line and i > 3830:
        print(f"Found extraction block at line {i+1}")
        # Find end of this block - up to "# Clean up markdown"
        end = i
        for j in range(i+1, min(len(lines), i+25)):
            if '# Clean up markdown' in lines[j]:
                end = j
                break
        print(f"Block runs from {i+1} to {end+1}")
        
        new_block = [
            '            # Extract SQL — robust extraction from any response format\n',
            '            import re as _re_sql\n',
            '            sql_part = ""\n',
            '            if "EXECUTE_SQL:" in ai_response:\n',
            '                sql_part = ai_response.split("EXECUTE_SQL:")[1].strip()\n',
            '            else:\n',
            '                # Try ```sql blocks first\n',
            '                _blocks = _re_sql.findall(r\'```(?:sql)?[\\s\\S]*?\\n([\\s\\S]*?)```\', ai_response, _re_sql.IGNORECASE)\n',
            '                if _blocks:\n',
            '                    # Pick the block with SELECT\n',
            '                    for b in _blocks:\n',
            '                        if \'SELECT\' in b.upper():\n',
            '                            sql_part = b.strip()\n',
            '                            break\n',
            '                if not sql_part:\n',
            '                    # Extract SELECT...to end of SQL (LIMIT, semicolon or newline after last keyword)\n',
            '                    _sel = _re_sql.search(\n',
            '                        r\'(SELECT\\b[\\s\\S]*?(?:LIMIT\\s+\\d+|ORDER\\s+BY[\\s\\S]*?(?:LIMIT\\s+\\d+)?))(?:\\s*;|\\s*$|\\s*\\n\\s*\\n)\',\n',
            '                        ai_response, _re_sql.IGNORECASE\n',
            '                    )\n',
            '                    if _sel:\n',
            '                        sql_part = _sel.group(1).strip()\n',
            '            # Clean up markdown\n',
        ]
        lines[i:end] = new_block
        print(f"✓ Replaced extraction block with robust version")
        break

with open('E:/AIBRIDGE_Claude/backend/main.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

import ast
with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print(f"Syntax OK — {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
    src_lines = src.splitlines()
    for j in range(max(0,e.lineno-3), min(len(src_lines),e.lineno+2)):
        print(f"  {j+1}: {src_lines[j]}")