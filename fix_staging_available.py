with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', encoding='utf-8') as f:
    content = f.read()

old = '''            "\n\nAny other staging table MUST be created in the SQL script itself (Step 1)."
        )
    else:
        staging_available = "EXTRACTED STAGING TABLES: unknown — derive from source tables in data model"'''

new = '''            "\\n\\nAny other staging table MUST be created in the SQL script itself (Step 1)."
        )
        # Append the staging hint (warns about narrow entity tables)
        if staging_hint:
            staging_available += "\\n\\n" + staging_hint.strip()
    else:
        staging_available = "EXTRACTED STAGING TABLES: unknown — derive from source tables in data model"'''

if old in content:
    content = content.replace(old, new, 1)
    print("✓ Injected staging_hint into staging_available")
else:
    print("Pattern not found — trying alternate")
    # Try with different escaping
    old2 = '            "\\n\\nAny other staging table MUST be created in the SQL script itself (Step 1)."\n        )\n    else:\n        staging_available = "EXTRACTED STAGING TABLES: unknown — derive from source tables in data model"'
    if old2 in content:
        print("Found alternate pattern")
    else:
        # Just show what's around line 898
        lines = content.splitlines()
        for i in range(895, 905):
            print(f"{i+1}: {repr(lines[i])}")

with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
