with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', encoding='utf-8') as f:
    content = f.read()

old = '    {nat_key} INTEGER UNIQUE NOT NULL,'
new = '    {nat_key} VARCHAR(255) UNIQUE NOT NULL,'

count = content.count(old)
print(f"Found {count} occurrences")

if count > 0:
    content = content.replace(old, new)
    print("✓ Changed nat_key type from INTEGER to VARCHAR(255)")
else:
    print("Pattern not found")

with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
