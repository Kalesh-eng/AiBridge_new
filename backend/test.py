import ast

path = r"E:\AIBRIDGE_Claude\backend\main.py"

with open(path, encoding='utf-8') as f:
    lines = f.readlines()

# Replace lines 1930-1932 (0-indexed 1929-1931) with correct else block
lines[1929] = '        else:\n'
lines[1930] = '            con    = duckdb.connect(os.getenv("DUCKDB_PATH", "./aibridge.duckdb"))\n'
lines[1931] = '            result = con.execute(req.sql).fetchdf(); con.close()\n'
# Insert the missing return line after 1931
lines.insert(1932, '            return {"success": True, "columns": list(result.columns),\n')
lines.insert(1933, '                    "rows": result.values.tolist(), "row_count": len(result)}\n')

content = ''.join(lines)
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
try:
    ast.parse(content)
    print("Patch OK + Syntax OK")
except SyntaxError as e:
    print(f"Syntax ERROR: {e}")
    for i, l in enumerate(content.split('\n')[max(0,e.lineno-3):e.lineno+3], max(1,e.lineno-2)):
        print(f"  {i}: {l}")