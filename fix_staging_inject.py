with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with "Any other staging table MUST be created"
for i, line in enumerate(lines):
    if "Any other staging table MUST be created in the SQL script itself" in line:
        print(f"Found at line {i+1}: {repr(line[:80])}")
        # Insert staging_hint injection after the closing paren of the string concat
        # Find the next line which should be ")" closing the staging_available assignment
        for j in range(i+1, i+5):
            if lines[j].strip() == ')':
                print(f"Closing paren at line {j+1}: {repr(lines[j])}")
                # Insert after the closing paren
                lines.insert(j+1, '        # Append staging hint about narrow vs wide tables\n')
                lines.insert(j+2, '        if staging_hint:\n')
                lines.insert(j+3, '            staging_available += "\\n\\n" + staging_hint.strip()\n')
                print("✓ Inserted staging_hint injection")
                break
        break

with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

import ast
with open('E:/AIBRIDGE_Claude/backend/nlm_engine.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print(f"Syntax OK — {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
