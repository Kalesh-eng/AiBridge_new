with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    content = f.read()

old = '''                        _col_defs = [c.strip() for c in _cols_block.split(',') if c.strip()]'''

new = '''                        # Split by comma but skip commas inside parentheses e.g. NUMERIC(10,2)
                        _col_defs = []
                        _buf = ""; _pdepth = 0
                        for _ch2 in _cols_block:
                            if _ch2 == '(': _pdepth += 1; _buf += _ch2
                            elif _ch2 == ')': _pdepth -= 1; _buf += _ch2
                            elif _ch2 == ',' and _pdepth == 0:
                                if _buf.strip(): _col_defs.append(_buf.strip())
                                _buf = ""
                            else: _buf += _ch2
                        if _buf.strip(): _col_defs.append(_buf.strip())'''

if old in content:
    content = content.replace(old, new, 1)
    print("✓ Fixed comma-split to skip commas inside parentheses")
else:
    print("Pattern not found")

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
