with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if '_cname = _words[0].strip' in line and i > 580:
        print(f"Found at line {i+1}: {repr(line)}")
        lines[i] = '                            _cname = _words[0].strip(\'"\'  ).lower() if _words else ""\n'
        print("✓ Fixed")
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
