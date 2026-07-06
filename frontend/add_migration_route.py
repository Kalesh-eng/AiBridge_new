# Update App.jsx
with open('E:/AIBRIDGE_Claude/frontend/src/App.jsx', encoding='utf-8') as f:
    src = f.read()

# Add import
if 'MigrationAgent' not in src:
    src = src.replace(
        "import Help            from './pages/Help'",
        "import Help            from './pages/Help'\nimport MigrationAgent  from './pages/MigrationAgent'"
    )
    print("✓ Added MigrationAgent import")
else:
    print("  MigrationAgent import already exists")

# Add route
if '/migration' not in src:
    src = src.replace(
        "      <Route path=\"/help\"           element={<PrivateRoute><Help /></PrivateRoute>} />",
        "      <Route path=\"/help\"           element={<PrivateRoute><Help /></PrivateRoute>} />\n      <Route path=\"/migration\"      element={<PrivateRoute><MigrationAgent /></PrivateRoute>} />"
    )
    print("✓ Added /migration route")
else:
    print("  /migration route already exists")

with open('E:/AIBRIDGE_Claude/frontend/src/App.jsx', 'w', encoding='utf-8') as f:
    f.write(src)

# Update Layout.jsx - add nav item
with open('E:/AIBRIDGE_Claude/frontend/src/components/Layout.jsx', encoding='utf-8') as f:
    src = f.read()

if '/migration' not in src:
    src = src.replace(
        "{ path: '/source-target',  label: 'Source",
        "{ path: '/migration',      label: '🔄 Migration Agent',  color: '#534AB7',                        tip: 'Reverse engineer, extend or migrate an existing data warehouse' },\n  { path: '/source-target',  label: 'Source"
    )
    with open('E:/AIBRIDGE_Claude/frontend/src/components/Layout.jsx', 'w', encoding='utf-8') as f:
        f.write(src)
    print("✓ Added Migration Agent to nav")
else:
    print("  Migration Agent already in nav")
