path = r"E:\AIBRIDGE_Claude\frontend\src\pages\Analytics.jsx"

with open(path, encoding='utf-8') as f:
    content = f.read()

old = """        if (!r.data.sql_result) {
          setError(r.data.response?.slice(0, 200) || 'Could not generate SQL')
          setLoading(false); return
        }"""

new = """        if (!r.data.sql_result && bestSql) {
          // SQL found in response but auto-exec failed — still use it
          r.data.sql_result = { sql: bestSql, columns: [], rows: [] }
          r.data.sql = bestSql
        }
        if (!r.data.sql_result) {
          setError(r.data.response?.slice(0, 200) || 'Could not generate SQL')
          setLoading(false); return
        }"""

if old in content:
    content = content.replace(old, new)
    print("✓ AutoExec fix applied")
else:
    print("✗ Pattern not found")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Done")