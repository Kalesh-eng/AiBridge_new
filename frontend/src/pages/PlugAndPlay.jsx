/**
 * PlugAndPlay.jsx v2 — Connect any existing warehouse, ask questions instantly
 * Connection-based BI (not pipeline-based) — works on any DB schema
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'

const DB_TYPES = [
  { value: 'postgres',  label: 'PostgreSQL', icon: '🐘', port: 5432 },
  { value: 'mysql',     label: 'MySQL',       icon: '🐬', port: 3306 },
  { value: 'sqlserver', label: 'SQL Server',  icon: '🪟', port: 1433 },
  { value: 'snowflake', label: 'Snowflake',   icon: '❄️', port: 443  },
  { value: 'bigquery',  label: 'BigQuery',    icon: '☁️', port: null },
  { value: 'redshift',  label: 'Redshift',    icon: '🔴', port: 5439 },
]

const TYPE_COLORS = {
  fact:      { bg: '#EFF6FF', border: '#BFDBFE', text: '#1D4ED8', label: 'FACT'    },
  dimension: { bg: '#F0FDF4', border: '#BBF7D0', text: '#15803D', label: 'DIM'     },
  lookup:    { bg: '#FFF7ED', border: '#FED7AA', text: '#C2410C', label: 'LOOKUP'  },
  staging:   { bg: '#F5F3FF', border: '#DDD6FE', text: '#6D28D9', label: 'STAGING' },
  unknown:   { bg: '#F9FAFB', border: '#E5E7EB', text: '#6B7280', label: 'TABLE'   },
}

const STEPS = [
  { id: 'connect',  label: 'Connect',  icon: '🔌' },
  { id: 'discover', label: 'Discover', icon: '🔍' },
  { id: 'explore',  label: 'Explore',  icon: '✨' },
]

export default function PlugAndPlay() {
  const navigate = useNavigate()

  // Step state
  const [step, setStep] = useState('connect')

  // Connect form
  const [dbType, setDbType] = useState('postgres')
  const [form, setForm] = useState({
    name: '', host: 'localhost', port: 5432,
    database_name: '', username: '', password: '', source_schema: ''
  })
  const [testing,     setTesting]     = useState(false)
  const [testResult,  setTestResult]  = useState(null)
  const [discovering, setDiscovering] = useState(false)

  // Discovery results
  const [introspection, setIntrospection] = useState(null)
  const [connectorId,   setConnectorId]   = useState(null)

  // Explore / BI
  const [allConnectors,   setAllConnectors]   = useState([])
  const [selectedConnId,  setSelectedConnId]  = useState('')
  const [question,        setQuestion]        = useState('')
  const [asking,          setAsking]          = useState(false)
  const [answer,          setAnswer]          = useState(null)
  const [selectedTable,   setSelectedTable]   = useState(null)
  const [error,           setError]           = useState(null)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  // Load all DB connectors (for explore step)
  useEffect(() => {
    api.get('/connector/list').then(r => {
      const list = (r.data.connectors || []).filter(c => c.connector_type !== 'duckdb')
      setAllConnectors(list)
    }).catch(() => {})
  }, [])

  // When connectorId is set (after discover), auto-select it
  useEffect(() => {
    if (connectorId) setSelectedConnId(connectorId)
    else if (allConnectors.length > 0) setSelectedConnId(allConnectors[0].id)
  }, [connectorId, allConnectors])

  // ── Test connection ──────────────────────────────────────────────────────
  const testConnection = async () => {
    setTesting(true); setTestResult(null); setError(null)
    try {
      const r = await api.post('/connector/test', {
        connector_type: dbType,
        host: form.host, port: Number(form.port),
        database_name: form.database_name,
        username: form.username, password: form.password,
      })
      setTestResult(r.data.success ? 'success' : 'error')
      if (!r.data.success) setError(r.data.error || 'Connection failed')
    } catch (e) {
      setTestResult('error')
      setError(e.response?.data?.detail || e.message)
    }
    setTesting(false)
  }

  // ── Save connector + introspect ──────────────────────────────────────────
  const discoverSchema = async () => {
    setDiscovering(true); setError(null)
    try {
      // Save connector
      const saveRes = await api.post('/connector/save', {
        name: form.name || `${dbType} — ${form.database_name}`,
        connector_type: dbType, role: 'both',
        host: form.host, port: Number(form.port),
        database_name: form.database_name,
        username: form.username, password: form.password,
        source_schema: form.source_schema || 'public',
      })
      const cId = saveRes.data.connector?.id
      setConnectorId(cId)

      // Introspect
      const r = await api.post('/dwh/introspect', {
        connector_id: cId,
        schemas: form.source_schema ? [form.source_schema] : null,
      })
      if (r.data.success) {
        setIntrospection(r.data)
        setStep('discover')
      } else {
        setError(r.data.error || 'Schema discovery failed')
      }
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    }
    setDiscovering(false)
  }

  // ── Discover from existing connector ────────────────────────────────────
  const discoverExisting = async (connector) => {
    setDiscovering(true); setError(null)
    setConnectorId(connector.id)
    try {
      const r = await api.post('/dwh/introspect', {
        connector_id: connector.id,
        schemas: connector.source_schema ? [connector.source_schema] : null,
      })
      if (r.data.success) {
        setIntrospection(r.data)
        setStep('discover')
      } else {
        setError(r.data.error || 'Discovery failed')
      }
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    }
    setDiscovering(false)
  }

  // ── Ask question using /chat endpoint ────────────────────────────────────
  const askQuestion = async () => {
    if (!question.trim() || !selectedConnId) return
    setAsking(true); setAnswer(null); setError(null)
    try {
      const r = await api.post('/chat', {
        message: question,
        connector_id: selectedConnId,
        history: [],
      })
      setAnswer(r.data)
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    }
    setAsking(false)
  }

  const summary = introspection?.summary || {}
  const tables  = Object.values(introspection?.tables || {})

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <>
      <PageHeader
        title="Plug & Play"
        subtitle="Connect any database — schema discovered automatically, ask questions instantly"
      />
      <PageBody>

        {/* Progress stepper */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24 }}>
          {STEPS.map((s, i) => {
            const active = step === s.id
            const done   = STEPS.findIndex(x => x.id === step) > i
            return (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center' }}>
                <div onClick={() => done && setStep(s.id)} style={{
                  display: 'flex', alignItems: 'center', gap: 7,
                  padding: '7px 16px', borderRadius: 20, cursor: done ? 'pointer' : 'default',
                  background: active ? '#185FA5' : done ? '#EAF3DE' : '#F9FAFB',
                  border: `1px solid ${active ? '#185FA5' : done ? '#3B6D11' : '#E5E7EB'}`,
                  transition: 'all 0.2s',
                }}>
                  <span style={{ fontSize: 14 }}>{done ? '✓' : s.icon}</span>
                  <span style={{ fontSize: 12, fontWeight: 600,
                    color: active ? '#fff' : done ? '#3B6D11' : '#9CA3AF' }}>{s.label}</span>
                </div>
                {i < STEPS.length - 1 && (
                  <div style={{ width: 28, height: 1, background: done ? '#3B6D11' : '#E5E7EB' }} />
                )}
              </div>
            )
          })}
        </div>

        {/* Error */}
        {error && (
          <div style={{ background: '#FEF2F2', border: '1px solid #FCA5A5', borderRadius: 8,
            padding: '10px 14px', marginBottom: 16, fontSize: 12, color: '#991B1B',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>{error}</span>
            <button onClick={() => setError(null)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#991B1B', fontSize: 16 }}>✕</button>
          </div>
        )}

        {/* ── STEP 1: CONNECT ────────────────────────────────────────────── */}
        {step === 'connect' && (
          <div style={{ maxWidth: 680 }}>

            {/* New connection */}
            <div style={card}>
              <div style={sectionTitle}>New connection — choose database type</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 20 }}>
                {DB_TYPES.map(db => (
                  <button key={db.value} onClick={() => { setDbType(db.value); set('port', db.port || '') }}
                    style={{
                      padding: '10px 12px', borderRadius: 8, cursor: 'pointer',
                      border: `2px solid ${dbType === db.value ? '#185FA5' : '#E5E7EB'}`,
                      background: dbType === db.value ? '#EBF4FF' : '#fff',
                      display: 'flex', alignItems: 'center', gap: 8, transition: 'all 0.15s',
                    }}>
                    <span style={{ fontSize: 18 }}>{db.icon}</span>
                    <span style={{ fontSize: 12, fontWeight: 600,
                      color: dbType === db.value ? '#185FA5' : '#374151' }}>{db.label}</span>
                  </button>
                ))}
              </div>

              <div style={sectionTitle}>Connection details</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
                <div style={{ gridColumn: '1/-1' }}>
                  <label style={lbl}>Connection name</label>
                  <input style={inp} placeholder="e.g. Production Warehouse"
                    value={form.name} onChange={e => set('name', e.target.value)} />
                </div>
                <div>
                  <label style={lbl}>Host</label>
                  <input style={inp} placeholder="localhost"
                    value={form.host} onChange={e => set('host', e.target.value)} />
                </div>
                <div>
                  <label style={lbl}>Port</label>
                  <input style={inp} type="number"
                    value={form.port} onChange={e => set('port', e.target.value)} />
                </div>
                <div>
                  <label style={lbl}>Database name</label>
                  <input style={inp} placeholder="mydb"
                    value={form.database_name} onChange={e => set('database_name', e.target.value)} />
                </div>
                <div>
                  <label style={lbl}>Schema (optional)</label>
                  <input style={inp} placeholder="public, warehouse, bank..."
                    value={form.source_schema} onChange={e => set('source_schema', e.target.value)} />
                </div>
                <div>
                  <label style={lbl}>Username</label>
                  <input style={inp} value={form.username} onChange={e => set('username', e.target.value)} />
                </div>
                <div>
                  <label style={lbl}>Password</label>
                  <input style={inp} type="password"
                    value={form.password} onChange={e => set('password', e.target.value)} />
                </div>
              </div>

              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <button style={btnSecondary} onClick={testConnection} disabled={testing}>
                  {testing ? '⏳ Testing...' : '🔗 Test Connection'}
                </button>
                {testResult === 'success' && (
                  <button style={btnPrimary} onClick={discoverSchema} disabled={discovering}>
                    {discovering ? '⏳ Discovering...' : '🔍 Discover Schema →'}
                  </button>
                )}
                {testResult === 'success' && (
                  <span style={{ fontSize: 11, color: '#3B6D11' }}>✓ Connected</span>
                )}
                {testResult === 'error' && (
                  <span style={{ fontSize: 11, color: '#991B1B' }}>✗ Failed — check credentials</span>
                )}
              </div>
            </div>

            {/* Existing connectors */}
            <div style={{ ...card, background: '#F9FAFB' }}>
              <div style={sectionTitle}>Use an existing connection</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {allConnectors.map(c => (
                  <button key={c.id} onClick={() => discoverExisting(c)} disabled={discovering}
                    style={{
                      padding: '7px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 12,
                      border: '1px solid #E5E7EB', background: '#fff', color: '#374151',
                      display: 'flex', alignItems: 'center', gap: 6,
                    }}>
                    🔌 <span style={{ fontWeight: 600 }}>{c.name}</span>
                    <span style={{ color: '#9CA3AF', fontSize: 10 }}>{c.database_name}</span>
                    {discovering && connectorId === c.id && <span>⏳</span>}
                  </button>
                ))}
                {allConnectors.length === 0 && (
                  <div style={{ fontSize: 12, color: '#9CA3AF' }}>No saved connections yet.</div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── STEP 2: DISCOVER ───────────────────────────────────────────── */}
        {step === 'discover' && introspection && (
          <div>
            {/* Summary */}
            <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
              {[
                { val: summary.total_tables,  label: 'Tables',        color: '#185FA5' },
                { val: summary.total_columns, label: 'Columns',       color: '#3B6D11' },
                { val: (summary.total_rows||0).toLocaleString(), label: 'Rows', color: '#854F0B' },
                { val: summary.relationships, label: 'Relationships', color: '#534AB7' },
              ].map((s, i) => (
                <div key={i} style={{ background: '#fff', border: '1px solid #E5E7EB',
                  borderRadius: 10, padding: '10px 18px', textAlign: 'center', minWidth: 100 }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color: s.color }}>{s.val}</div>
                  <div style={{ fontSize: 10, color: '#9CA3AF', textTransform: 'uppercase',
                    letterSpacing: '0.05em', marginTop: 2 }}>{s.label}</div>
                </div>
              ))}
              <div style={{ flex: 1 }} />
              <button style={btnPrimary} onClick={() => setStep('explore')}>
                Ask Questions ✨
              </button>
            </div>

            {/* AI context */}
            {introspection.business_context?.ai_context && (
              <div style={{ ...card, background: '#EBF4FF', borderColor: '#BFDBFE', marginBottom: 16 }}>
                <div style={sectionTitle}>🧠 AI Business Context</div>
                <p style={{ fontSize: 12, color: '#1E40AF', lineHeight: 1.7, margin: 0 }}>
                  {introspection.business_context.ai_context}
                </p>
              </div>
            )}

            {/* Table cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(290px,1fr))', gap: 12 }}>
              {tables.map((t, i) => {
                const ttype  = t.classification?.type || 'unknown'
                const colors = TYPE_COLORS[ttype] || TYPE_COLORS.unknown
                const isSel  = selectedTable?.full_name === t.full_name
                return (
                  <div key={i} onClick={() => setSelectedTable(isSel ? null : t)} style={{
                    background: isSel ? colors.bg : '#fff',
                    border: `1.5px solid ${isSel ? colors.border : '#E5E7EB'}`,
                    borderRadius: 10, padding: '12px 14px', cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: '#111827' }}>{t.table_name}</div>
                        <div style={{ fontSize: 10, color: '#9CA3AF' }}>{t.schema}</div>
                      </div>
                      <div style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
                        <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 10,
                          background: colors.bg, color: colors.text, border: `1px solid ${colors.border}`,
                          letterSpacing: '0.06em' }}>{colors.label}</span>
                        <span style={{ fontSize: 10, color: '#9CA3AF' }}>
                          {(t.row_count||0).toLocaleString()} rows
                        </span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {(t.columns||[]).slice(0, isSel ? 50 : 6).map((c, j) => (
                        <span key={j} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10,
                          background: '#F3F4F6', color: '#374151', border: '1px solid #E5E7EB' }}>
                          {c.name}
                        </span>
                      ))}
                      {!isSel && (t.columns||[]).length > 6 && (
                        <span style={{ fontSize: 10, color: '#9CA3AF', padding: '2px 4px' }}>
                          +{t.columns.length - 6} more
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Relationships */}
            {introspection.relationships?.length > 0 && (
              <div style={{ ...card, marginTop: 16 }}>
                <div style={sectionTitle}>🔗 Detected Relationships ({introspection.relationships.length})</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {introspection.relationships.slice(0, 15).map((r, i) => (
                    <div key={i} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 6,
                      background: '#F0FDF4', border: '1px solid #BBF7D0', color: '#15803D' }}>
                      {r.from_table.split('.').pop()}.{r.from_column} → {r.to_table.split('.').pop()}
                      {r.type === 'actual_fk' && <span style={{ marginLeft: 4, opacity: 0.5, fontSize: 9 }}>FK</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── STEP 3: EXPLORE ────────────────────────────────────────────── */}
        {step === 'explore' && (
          <div style={{ maxWidth: 780 }}>
            <div style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <div style={sectionTitle}>Ask your data anything</div>
                <button style={btnGhost} onClick={() => setStep('discover')}>← Back to schema</button>
              </div>

              {/* Connection selector — connection-based BI */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14,
                padding: '10px 14px', background: '#F0FDF4', borderRadius: 8, border: '1px solid #BBF7D0' }}>
                <span style={{ fontSize: 16 }}>🔌</span>
                <span style={{ fontSize: 11, color: '#15803D', fontWeight: 700, letterSpacing: '0.04em' }}>
                  CONNECTED TO:
                </span>
                <select value={selectedConnId} onChange={e => setSelectedConnId(e.target.value)}
                  style={{ fontSize: 12, padding: '5px 10px', border: '1px solid #BBF7D0',
                    borderRadius: 6, color: '#15803D', fontWeight: 600, background: '#F0FDF4',
                    flex: 1, maxWidth: 300 }}>
                  {allConnectors.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.name} — {c.database_name} ({c.connector_type})
                    </option>
                  ))}
                </select>
                <span style={{ fontSize: 10, color: '#9CA3AF' }}>
                  AI uses this DB's schema to answer
                </span>
              </div>

              {/* Quick suggestions */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
                {[
                  'Total transactions by channel',
                  'Top 5 customers by balance',
                  'Monthly revenue trend',
                  'Branch performance summary',
                  'Account type breakdown',
                ].map((s, i) => (
                  <button key={i} onClick={() => setQuestion(s)} style={{
                    fontSize: 10, padding: '4px 12px', borderRadius: 12,
                    background: '#EBF4FF', color: '#185FA5', border: '1px solid #BFDBFE',
                    cursor: 'pointer',
                  }}>{s}</button>
                ))}
              </div>

              {/* Question input */}
              <div style={{ display: 'flex', gap: 8 }}>
                <input style={{ ...inp, flex: 1 }}
                  placeholder="e.g. Total transactions by branch this month..."
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') askQuestion() }}
                />
                <button style={btnPrimary} onClick={askQuestion}
                  disabled={asking || !question.trim() || !selectedConnId}>
                  {asking ? '⏳' : '🚀 Ask'}
                </button>
              </div>
            </div>

            {/* Answer */}
            {answer && (
              <div style={card}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#185FA5',
                  textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                  ✦ Answer
                </div>
                <div style={{ fontSize: 13, color: '#111827', lineHeight: 1.7, marginBottom: 14,
                  whiteSpace: 'pre-wrap' }}>
                  {answer.response?.replace(/```[\s\S]*?```/g, '').trim()}
                </div>

                {/* Results table */}
                {answer.sql_result?.rows?.length > 0 && (
                  <div style={{ overflowX: 'auto', marginBottom: 12 }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                      <thead>
                        <tr>
                          {answer.sql_result.columns.map(c => (
                            <th key={c} style={{ background: '#F9FAFB', padding: '6px 12px',
                              textAlign: 'left', borderBottom: '1px solid #E5E7EB',
                              fontSize: 10, fontWeight: 700, color: '#6B7280',
                              textTransform: 'uppercase', letterSpacing: '0.05em' }}>{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {answer.sql_result.rows.slice(0, 20).map((row, i) => (
                          <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#F9FAFB' }}>
                            {row.map((cell, j) => (
                              <td key={j} style={{ padding: '6px 12px',
                                borderBottom: '1px solid #F3F4F6', color: '#374151' }}>
                                {cell === null
                                  ? <span style={{ color: '#D1D5DB' }}>—</span>
                                  : String(cell)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div style={{ fontSize: 10, color: '#9CA3AF', padding: '6px 12px' }}>
                      {answer.sql_result.rows.length} rows returned
                    </div>
                  </div>
                )}

                {/* SQL */}
                {answer.sql_result?.sql && (
                  <details style={{ marginTop: 8 }}>
                    <summary style={{ fontSize: 10, color: '#9CA3AF', cursor: 'pointer',
                      userSelect: 'none' }}>View SQL</summary>
                    <pre style={{ background: '#1E1E1E', color: '#D4D4D4', padding: '10px 14px',
                      borderRadius: 6, fontSize: 11, overflowX: 'auto', lineHeight: 1.6, marginTop: 8 }}>
                      {answer.sql_result.sql}
                    </pre>
                  </details>
                )}
              </div>
            )}

            {/* CTA */}
            <div style={{ ...card, background: '#EBF4FF', borderColor: '#BFDBFE', textAlign: 'center', marginTop: 8 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#185FA5', marginBottom: 6 }}>
                Want a full ETL pipeline with historical tracking?
              </div>
              <p style={{ fontSize: 12, color: '#1E40AF', marginBottom: 14, lineHeight: 1.6 }}>
                Plug & Play gives you instant BI on any existing database.
                Run the ETL Agent to build a clean star schema with SCD, data quality, and audit trails.
              </p>
              <button style={btnPrimary} onClick={() => navigate('/etl-agent')}>
                Go to ETL Agent →
              </button>
            </div>
          </div>
        )}

      </PageBody>
    </>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────────
const card         = { border: '1px solid #E5E7EB', borderRadius: 10, padding: '16px 18px', marginBottom: 14, background: '#fff' }
const sectionTitle = { fontSize: 10, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }
const inp          = { width: '100%', padding: '8px 10px', fontSize: 12, border: '1px solid #D1D5DB', borderRadius: 6, boxSizing: 'border-box' }
const lbl          = { display: 'block', fontSize: 10, fontWeight: 600, color: '#6B7280', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.04em' }
const btnPrimary   = { padding: '8px 18px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 12, cursor: 'pointer', fontWeight: 600 }
const btnSecondary = { padding: '8px 16px', background: '#fff', color: '#185FA5', border: '1px solid #185FA5', borderRadius: 6, fontSize: 12, cursor: 'pointer', fontWeight: 600 }
const btnGhost     = { padding: '7px 14px', background: '#fff', color: '#6B7280', border: '1px solid #E5E7EB', borderRadius: 6, fontSize: 12, cursor: 'pointer' }
