with open('E:/AIBRIDGE_Claude/frontend/src/pages/EtlAgent.jsx', encoding='utf-8') as f:
    src = f.read()

replacements = [
    ("background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6,",
     "background: '#f8fafc', color: '#1e293b', padding: 12, borderRadius: 6,"),
    ("line.includes('✗') || line.includes('ERROR') ? '#f87171'",
     "line.includes('✗') || line.includes('ERROR') ? '#dc2626'"),
    (": line.includes('✓')   ? '#86efac'",
     ": line.includes('✓')   ? '#16a34a'"),
    (": line.includes('⚠')   ? '#fbbf24'",
     ": line.includes('⚠')   ? '#d97706'"),
    (": line.includes('🛑')  ? '#fb923c'",
     ": line.includes('🛑')  ? '#ea580c'"),
    (": '#d4d4d4'",
     ": '#374151'"),
]

for old, new in replacements:
    if old in src:
        src = src.replace(old, new)
        print(f"✓ {old[:40]}...")
    else:
        print(f"✗ Not found: {old[:40]}...")

with open('E:/AIBRIDGE_Claude/frontend/src/pages/EtlAgent.jsx', 'w', encoding='utf-8') as f:
    f.write(src)
print("Done")