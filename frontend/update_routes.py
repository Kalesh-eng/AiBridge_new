import re

# Update App.jsx - add import and route
with open('E:/AIBRIDGE_Claude/frontend/src/App.jsx', encoding='utf-8') as f:
    src = f.read()

# Add import
src = src.replace(
    "import Help            from './pages/Help'",
    "import Help            from './pages/Help'\nimport MigrationAgent  from './pages/MigrationAgent'"
)

# Add route
src = src.replace(
    "      <Route path=\"/help\"           element={<PrivateRoute><Help /></PrivateRoute>} />",
    "      <Route path=\"/help\"           element={<PrivateRoute><Help /></PrivateRoute>} />\n      <Route path=\"/migration\"      element={<PrivateRoute><MigrationAgent /></PrivateRoute>} />"
)

with open('E:/AIBRIDGE_Claude/frontend/src/App.jsx', 'w', encoding='utf-8') as f:
    f.write(src)
print("✓ App.jsx updated")

# Update Layout.jsx - add nav item
with open('E:/AIBRIDGE_Claude/frontend/src/components/Layout.jsx', encoding='utf-8') as f:
    src = f.read()

src = src.replace(
    "{ path: '/agent',          label: 'ETL Agent',          color: '#534AB7',",
    "{ path: '/agent',          label: 'ETL Agent',          color: '#534AB7',                        tip: 'AI-powered pipeline designer' },\n  { path: '/migration',      label: '🔄 Migration Agent',  color: '#534AB7',"
)

# Fix duplicate tip
src = src.replace(
    "{ path: '/agent',          label: 'ETL Agent',          color: '#534AB7',                        tip: 'AI-powered pipeline designer' },\n  { path: '/migration',      label: '🔄 Migration Agent',  color: '#534AB7',",
    "{ path: '/migration',      label: '🔄 Migration Agent',  color: '#534AB7',"
)

# Try simpler approach - just add after ETL Agent entry
with open('E:/AIBRIDGE_Claude/frontend/src/components/Layout.jsx', encoding='utf-8') as f:
    src = f.read()

# Find the ETL Agent line and add migration after it
old_line = "  { path: '/agent',          label: 'ETL Agent',          color: '#534AB7',"
new_lines = old_line + "\n  { path: '/migration',      label: '🔄 Migration Agent',  color: '#534AB7',                        tip: 'Reverse engineer, extend or migrate an existing data warehouse' },"

if old_line in src:
    # Find end of ETL Agent entry (next comma+newline after tip)
    idx = src.find(old_line)
    # Find the closing }, of this entry
    end = src.find('},', idx) + 2
    etl_entry = src[idx:end]
    src = src[:idx] + etl_entry + "\n  { path: '/migration',      label: '🔄 Migration Agent',  color: '#534AB7',                        tip: 'Reverse engineer, extend or migrate an existing data warehouse' }," + src[end:]
    with open('E:/AIBRIDGE_Claude/frontend/src/components/Layout.jsx', 'w', encoding='utf-8') as f:
        f.write(src)
    print("✓ Layout.jsx updated")
else:
    print("✗ ETL Agent entry not found in Layout.jsx")
