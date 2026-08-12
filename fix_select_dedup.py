@'
with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'Deduped INSERT columns for:' in line:
        print(f"Found at line {i+1}")
        insert_pos = i + 1
        new_lines = [
            '                import re as _re_sel\n',
            '                def _dedup_sel(m):\n',
            '                    cols = [c.strip() for c in m.group(1).split(",")]\n',
            '                    seen = set(); uniq = []\n',
            '                    for c in cols:\n',
            '                        b = c.strip().strip(chr(34)).lower().split("(")[0].strip()\n',
            '                        if b not in seen: seen.add(b); uniq.append(c)\n',
            '                    return "SELECT DISTINCT " + ", ".join(uniq)\n',
            '                import re as _re_s2\n',
            '                _ns = _re_s2.sub(r"SELECT\\s+DISTINCT\\s+((?:(?!FROM)[\\s\\S])+?)(?=\\s+FROM)", _dedup_sel, sql, flags=_re_s2.IGNORECASE)\n',
            '                if _ns != sql:\n',
            '                    sql = _ns\n',
            '                    log(f"[SQLPatch] Deduped SELECT cols for: {script.get(chr(110)+chr(97)+chr(109)+chr(101))}")\n',
        ]
        lines[insert_pos:insert_pos] = new_lines
        print("Inserted SELECT dedup")
        break

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

import ast
src = open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8').read()
try:
    ast.parse(src)
    print(f"Syntax OK - {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR {e.lineno}: {e.msg}")
'@ | Out-File -FilePath E:\AIBRIDGE_Claude\fix_select_dedup.py -Encoding utf8

& e:/AIBRIDGE_Claude/venv/Scripts/python.exe e:/AIBRIDGE_Claude/fix_select_dedup.py