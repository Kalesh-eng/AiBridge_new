with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', encoding='utf-8') as f:
    content = f.read()

# Find the cols_sql line in the injection block
old = '            _cols_sql = ", ".join(f\'"{c}"\' for c in sorted(_cols_used))\n'
new = '            # Use ALL columns from raw staging — simpler and more reliable\n            _cols_sql = "*"\n'

if old in content:
    content = content.replace(old, new, 1)
    print("✓ Changed cols_sql to SELECT *")
else:
    print("Pattern not found")
    # Show context
    idx = content.find('_cols_sql')
    if idx >= 0:
        print(f"Found _cols_sql at char {idx}:")
        print(repr(content[idx:idx+100]))

with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")