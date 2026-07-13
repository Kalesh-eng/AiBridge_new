with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    content = f.read()

# Find and replace the current complex ON CONFLICT patch with a simple one
import re
old_pattern = r'            # Fix: strip ON CONFLICT from dim scripts.*?log\(f"\[SQLPatch\] ON CONFLICT.*?\)\n'
match = re.search(old_pattern, content, re.DOTALL)
if match:
    print(f"Found block at chars {match.start()}-{match.end()}")
    new_code = '''            # Fix: ON CONFLICT DO UPDATE → WHERE NOT EXISTS is too complex to inject generically.
            # Simply strip DO UPDATE (which requires UNIQUE constraint) — leave DO NOTHING as-is.
            # The WHERE NOT EXISTS patch below handles dim idempotency for existing WHERE NOT EXISTS blocks.
            if script.get("name", "").startswith("dim_") and "ON CONFLICT" in sql.upper() and "DO UPDATE" in sql.upper():
                sql = re.sub(
                    r'\\s*ON\\s+CONFLICT\\s*(?:\\([^)]*\\))?\\s*DO\\s+UPDATE[^;]*',
                    '', sql, flags=re.IGNORECASE | re.DOTALL
                )
                log(f"[SQLPatch] Stripped ON CONFLICT DO UPDATE from dim: {script.get('name')}")
'''
    content = content[:match.start()] + new_code + content[match.end():]
    print("✓ Replaced with simple DO UPDATE strip")
else:
    print("Pattern not found — trying line-based search")
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if '# Fix: strip ON CONFLICT from dim scripts' in line:
            print(f"Found at line {i+1}")
            break

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
