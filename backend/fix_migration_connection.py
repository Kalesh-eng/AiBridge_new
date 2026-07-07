with open('E:/AIBRIDGE_Claude/frontend/src/pages/MigrationAgent.jsx', encoding='utf-8') as f:
    src = f.read()

# Add useEffect and api import at top, add connectors state
OLD = "  const [conn, setConn] = useState({"
NEW = """  const [connectors, setConnectors]       = useState([])
  const [selectedConnector, setSelectedConnector] = useState('')
  const [useExisting, setUseExisting]     = useState(true)

  // Load saved connectors on mount
  useState(() => {
    api.get('/connector/list').then(r => {
      setConnectors(r.data.connectors || [])
    }).catch(() => {})
  })

  const [conn, setConn] = useState({"""

if OLD in src:
    src = src.replace(OLD, NEW)
    print("✓ Added connectors state")
else:
    print("✗ conn state not found")

# Replace the connection form section
OLD_FORM = '''            {/* Connection form */}
            <div style={card}>
              <div style={sectionLabel}>Warehouse connection</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                {[
                  { key: 'host',     label: 'Host',     placeholder: 'localhost' },
                  { key: 'port',     label: 'Port',     placeholder: '5432' },
                  { key: 'database', label: 'Database', placeholder: 'my_warehouse' },
                  { key: 'username', label: 'Username', placeholder: 'readonly_user' },
                ].map(f => (
                  <div key={f.key}>
                    <label style={labelStyle}>{f.label}</label>
                    <input style={inp} value={conn[f.key]} placeholder={f.placeholder}
                      onChange={e => setConn(c => ({ ...c, [f.key]: e.target.value }))} />
                  </div>
                ))}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <div>
                  <label style={labelStyle}>Password</label>
                  <input style={inp} type="password" value={conn.password}
                    onChange={e => setConn(c => ({ ...c, password: e.target.value }))} />
                </div>
                <div>
                  <label style={labelStyle}>Warehouse schema</label>
                  <input style={inp} value={conn.warehouse_schema}
                    onChange={e => setConn(c => ({ ...c, warehouse_schema: e.target.value }))} />
                </div>
              </div>
            </div>'''

NEW_FORM = '''            {/* Connection form */}
            <div style={card}>
              <div style={sectionLabel}>Warehouse connection</div>

              {/* Toggle: use existing connector or new */}
              <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
                <button onClick={() => setUseExisting(true)} style={{
                  padding: '5px 14px', fontSize: 11, borderRadius: 6, cursor: 'pointer',
                  background: useExisting ? '#534AB7' : '#fff',
                  color: useExisting ? '#fff' : '#555',
                  border: `1px solid ${useExisting ? '#534AB7' : '#d1d5db'}`
                }}>Use saved connector</button>
                <button onClick={() => setUseExisting(false)} style={{
                  padding: '5px 14px', fontSize: 11, borderRadius: 6, cursor: 'pointer',
                  background: !useExisting ? '#534AB7' : '#fff',
                  color: !useExisting ? '#fff' : '#555',
                  border: `1px solid ${!useExisting ? '#534AB7' : '#d1d5db'}`
                }}>New connection</button>
              </div>

              {useExisting ? (
                /* Existing connector selector */
                connectors.length > 0 ? (
                  <div>
                    <label style={labelStyle}>Select warehouse connector</label>
                    <select style={inp} value={selectedConnector}
                      onChange={e => {
                        setSelectedConnector(e.target.value)
                        const c = connectors.find(c => c.id === e.target.value)
                        if (c) setConn({
                          host: c.host, port: String(c.port),
                          database: c.database_name, username: c.username,
                          password: '', warehouse_schema: 'warehouse',
                          connector_type: c.connector_type
                        })
                      }}>
                      <option value="">— Select connector —</option>
                      {connectors.map(c => (
                        <option key={c.id} value={c.id}>
                          {c.name} — {c.connector_type} / {c.host}/{c.database_name}
                        </option>
                      ))}
                    </select>
                    {selectedConnector && (
                      <div>
                        <label style={{ ...labelStyle, marginTop: 10 }}>Warehouse schema</label>
                        <input style={inp} value={conn.warehouse_schema}
                          onChange={e => setConn(c => ({ ...c, warehouse_schema: e.target.value }))} />
                        <label style={{ ...labelStyle, marginTop: 8 }}>Password (re-enter for security)</label>
                        <input style={inp} type="password" value={conn.password}
                          onChange={e => setConn(c => ({ ...c, password: e.target.value }))} />
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: '#888', padding: '10px 0' }}>
                    No connectors saved yet. Use "New connection" or add one in Connectors.
                  </div>
                )
              ) : (
                /* New connection form */
                <div>
                  <div style={{ marginBottom: 10 }}>
                    <label style={labelStyle}>Database type</label>
                    <select style={inp} value={conn.connector_type}
                      onChange={e => setConn(c => ({ ...c, connector_type: e.target.value }))}>
                      <option value="postgres">PostgreSQL</option>
                      <option value="mysql">MySQL / MariaDB</option>
                      <option value="sqlserver">SQL Server / Azure SQL</option>
                      <option value="snowflake">Snowflake</option>
                      <option value="bigquery">BigQuery</option>
                      <option value="redshift">Amazon Redshift</option>
                      <option value="oracle">Oracle</option>
                    </select>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                    {[
                      { key: 'host',     label: 'Host',     placeholder: 'localhost' },
                      { key: 'port',     label: 'Port',     placeholder: '5432' },
                      { key: 'database', label: 'Database', placeholder: 'my_warehouse' },
                      { key: 'username', label: 'Username', placeholder: 'readonly_user' },
                    ].map(f => (
                      <div key={f.key}>
                        <label style={labelStyle}>{f.label}</label>
                        <input style={inp} value={conn[f.key]} placeholder={f.placeholder}
                          onChange={e => setConn(c => ({ ...c, [f.key]: e.target.value }))} />
                      </div>
                    ))}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    <div>
                      <label style={labelStyle}>Password</label>
                      <input style={inp} type="password" value={conn.password}
                        onChange={e => setConn(c => ({ ...c, password: e.target.value }))} />
                    </div>
                    <div>
                      <label style={labelStyle}>Warehouse schema</label>
                      <input style={inp} value={conn.warehouse_schema}
                        onChange={e => setConn(c => ({ ...c, warehouse_schema: e.target.value }))} />
                    </div>
                  </div>
                </div>
              )}
            </div>'''

if OLD_FORM in src:
    src = src.replace(OLD_FORM, NEW_FORM)
    print("✓ Updated connection form")
else:
    print("✗ Connection form not found")

# Fix the scan button disabled condition
src = src.replace(
    'disabled={loading || !conn.host}',
    'disabled={loading || (!conn.host && !selectedConnector)}'
)

with open('E:/AIBRIDGE_Claude/frontend/src/pages/MigrationAgent.jsx', 'w', encoding='utf-8') as f:
    f.write(src)

print("Done")
