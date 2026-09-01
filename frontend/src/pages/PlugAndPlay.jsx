/**
 * PlugAndPlay.jsx v3 — Connect any DB, discover schema, ask questions
 * - Connection-based BI (no pipeline needed)
 * - Voice input (Web Speech API)
 * - Bar/Line/Pie charts on results
 * - String-to-number conversion for chart rendering
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, PageBody } from '../components/Layout'
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import api from '../api/api'

const COLORS = ['#185FA5','#3B6D11','#854F0B','#534AB7','#A32D2D','#0F6E56','#1D8A99','#6B4F9E']

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

// ── Voice hook (same as Analytics) ──────────────────────────────────────────
function useVoice(onResult) {
  const [listening, setListening] = useState(false)
  const [supported, setSupported] = useState(false)
  const [voiceOn,   setVoiceOn]   = useState(true)
  const recogRef = useRef(null)

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return
    setSupported(true)
    const r = new SR()
    r.continuous = false; r.interimResults = false; r.lang = 'en-IN'
    r.onresult = (e) => { onResult(e.results[0][0].transcript); setListening(false) }
    r.onend = () => setListening(false)
    r.onerror = () => setListening(false)
    recogRef.current = r
  }, [onResult])

  const toggleListen = useCallback(() => {
    if (!recogRef.current) return
    if (listening) { recogRef.current.stop(); setListening(false) }
    else { try { recogRef.current.start(); setListening(true) } catch {} }
  }, [listening])

  const speak = useCallback((text) => {
    if (!voiceOn || !window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const utt = new SpeechSynthesisUtterance(
      text.replace(/```[\s\S]*?```/g,'').replace(/[#*_`>]/g,'').replace(/\n+/g,' ').trim().slice(0,400)
    )
    utt.lang = 'en-IN'; utt.rate = 0.93
    window.speechSynthesis.speak(utt)
  }, [voiceOn])

  const stopSpeaking = useCallback(() => { window.speechSynthesis?.cancel() }, [])

  return { listening, supported, voiceOn, setVoiceOn, toggleListen, speak, stopSpeaking }
}

// ── Chart renderer ───────────────────────────────────────────────────────────
function SmartChart({ columns, rows, question }) {
  const [chartType, setChartType] = useState('bar')
  const [xAxis, setXAxis] = useState('')
  const [yAxis, setYAxis] = useState('')

  // Convert rows — strings to numbers where possible
  const cleanRows = rows.map(row =>
    row.map(cell => {
      if (cell === null) return null
      const n = parseFloat(cell)
      return !isNaN(n) && cell !== '' ? n : cell
    })
  )

  useEffect(() => {
    if (!columns.length) return
    const numericCols = columns.filter((_, i) =>
      cleanRows.length > 0 && typeof cleanRows[0][i] === 'number'
    )
    const textCols = columns.filter((_, i) =>
      cleanRows.length > 0 && typeof cleanRows[0][i] !== 'number'
    )
    setXAxis(textCols[0] || columns[0] || '')
    setYAxis(numericCols[0] || columns[1] || '')
    // Auto-detect chart type from question
    const q = (question || '').toLowerCase()
    if (q.includes('trend') || q.includes('over time') || q.includes('monthly') || q.includes('yearly')) setChartType('line')
    else if (q.includes('breakdown') || q.includes('distribution') || q.includes('proportion')) setChartType('pie')
    else setChartType('bar')
  }, [columns, rows])

  const data = cleanRows.map(row => {
    const obj = {}
    columns.forEach((c, i) => { obj[c] = row[i] })
    return obj
  })

  const renderChart = () => {
    if (!data.length || !xAxis || !yAxis) return null
    if (chartType === 'bar') return (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xAxis} tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend />
          <Bar dataKey={yAxis}>{data.map((_,i) => <Cell key={i} fill={COLORS[i%COLORS.length]} />)}</Bar>
        </BarChart>
      </ResponsiveContainer>
    )
    if (chartType === 'line') return (
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xAxis} tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
          <Tooltip /><Legend />
          <Line type="monotone" dataKey={yAxis} stroke="#185FA5" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    )
    if (chartType === 'pie') return (
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie data={data} dataKey={yAxis} nameKey={xAxis} cx="50%" cy="50%" outerRadius={90} label={e => e[xAxis]}>
            {data.map((_,i) => <Cell key={i} fill={COLORS[i%COLORS.length]} />)}
          </Pie><Tooltip /><Legend />
        </PieChart>
      </ResponsiveContainer>
    )
    return null
  }

  return (
    <div style={{ marginBottom: 14 }}>
      {/* Chart type + axis controls */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          {['bar','line','pie','table'].map(t => (
            <button key={t} onClick={() => setChartType(t)} style={{
              padding: '3px 10px', fontSize: 10, borderRadius: 6, cursor: 'pointer',
              background: chartType===t ? '#185FA5' : '#fff',
              color: chartType===t ? '#fff' : '#555',
              border: `1px solid ${chartType===t ? '#185FA5' : '#d1d5db'}`,
            }}>{t==='bar'?'▥':t==='line'?'📈':t==='pie'?'🥧':'⊞'}</button>
          ))}
        </div>
        {chartType !== 'table' && (
          <>
            <select value={xAxis} onChange={e => setXAxis(e.target.value)}
              style={{ fontSize: 11, padding: '3px 8px', border: '1px solid #E5E7EB', borderRadius: 6 }}>
              {columns.map(c => <option key={c} value={c}>X: {c}</option>)}
            </select>
            <select value={yAxis} onChange={e => setYAxis(e.target.value)}
              style={{ fontSize: 11, padding: '3px 8px', border: '1px solid #E5E7EB', borderRadius: 6 }}>
              {columns.map(c => <option key={c} value={c}>Y: {c}</option>)}
            </select>
          </>
        )}
      </div>

      {/* Chart */}
      {chartType !== 'table' && renderChart()}

      {/* Table */}
      <div style={{ overflowX: 'auto', marginTop: chartType !== 'table' ? 12 : 0 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr>
            {columns.map(c => (
              <th key={c} style={{ background: '#F9FAFB', padding: '6px 12px', textAlign: 'left',
                borderBottom: '1px solid #E5E7EB', fontSize: 10, fontWeight: 700, color: '#6B7280',
                textTransform: 'uppercase', letterSpacing: '0.05em' }}>{c}</th>
            ))}
          </tr></thead>
          <tbody>
            {rows.slice(0,20).map((row,i) => (
              <tr key={i} style={{ background: i%2===0?'#fff':'#F9FAFB' }}>
                {row.map((cell,j) => (
                  <td key={j} style={{ padding: '6px 12px', borderBottom: '1px solid #F3F4F6', color: '#374151' }}>
                    {cell===null ? <span style={{ color: '#D1D5DB' }}>—</span> : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ fontSize: 10, color: '#9CA3AF', padding: '6px 12px' }}>
          {rows.length} rows returned
        </div>
      </div>
    </div>
  )
}

export default function PlugAndPlay() {
  const navigate = useNavigate()
  const [step, setStep] = useState('connect')
  const [dbType, setDbType] = useState('postgres')
  const [form, setForm] = useState({
    name: '', host: 'localhost', port: 5432,
    database_name: '', username: '', password: '', source_schema: ''
  })
  const [testing,     setTesting]     = useState(false)
  const [testResult,  setTestResult]  = useState(null)
  const [discovering, setDiscovering] = useState(false)
  const [introspection, setIntrospection] = useState(null)
  const [connectorId,   setConnectorId]   = useState(null)
  const [allConnectors,   setAllConnectors]   = useState([])
  const [selectedConnId,  setSelectedConnId]  = useState('')
  const [question,  setQuestion]  = useState('')
  const [asking,    setAsking]    = useState(false)
  const [answer,    setAnswer]    = useState(null)
  const [selectedTable, setSelectedTable] = useState(null)
  const [error,     setError]     = useState(null)
  const [voiceStatus, setVoiceStatus] = useState('')
  const voiceSubmitRef = useRef(null)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  // Voice
  const handleVoiceResult = useCallback((text) => {
    setQuestion(text)
    setVoiceStatus(`Heard: "${text}"`)
    setTimeout(() => setVoiceStatus(''), 3000)
    setTimeout(() => voiceSubmitRef.current?.(text), 600)
  }, [])

  const { listening, supported, voiceOn, setVoiceOn, toggleListen, speak, stopSpeaking } = useVoice(handleVoiceResult)

  useEffect(() => {
    api.get('/connector/list').then(r => {
      const list = (r.data.connectors || []).filter(c => c.connector_type !== 'duckdb')
      setAllConnectors(list)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (connectorId) setSelectedConnId(connectorId)
    else if (allConnectors.length > 0) setSelectedConnId(allConnectors[0].id)
  }, [connectorId, allConnectors])

  // Wire voice submit
  useEffect(() => { voiceSubmitRef.current = askQuestion }, [selectedConnId])

  const testConnection = async () => {
    setTesting(true); setTestResult(null); setError(null)
    try {
      const r = await api.post('/connector/test', {
        connector_type: dbType, host: form.host, port: Number(form.port),
        database_name: form.database_name, username: form.username, password: form.password,
      })
      setTestResult(r.data.success ? 'success' : 'error')
      if (!r.data.success) setError(r.data.error || 'Connection failed')
    } catch (e) { setTestResult('error'); setError(e.response?.data?.detail || e.message) }
    setTesting(false)
  }

  const discoverSchema = async () => {
    setDiscovering(true); setError(null)
    try {
      const saveRes = await api.post('/connector/save', {
        name: form.name || `${dbType} — ${form.database_name}`,
        connector_type: dbType, role: 'both',
        host: form.host, port: Number(form.port),
        database_name: form.database_name, username: form.username, password: form.password,
        source_schema: form.source_schema || 'public',
      })
      const cId = saveRes.data.connector?.id
      setConnectorId(cId)
      const r = await api.post('/dwh/introspect', {
        connector_id: cId,
        schemas: form.source_schema ? [form.source_schema] : null,
      })
      if (r.data.success) { setIntrospection(r.data); setStep('discover') }
      else setError(r.data.error || 'Schema discovery failed')
    } catch (e) { setError(e.response?.data?.detail || e.message) }
    setDiscovering(false)
  }

  const discoverExisting = async (connector) => {
    setDiscovering(true); setError(null); setConnectorId(connector.id)
    try {
      const r = await api.post('/dwh/introspect', {
        connector_id: connector.id,
        schemas: connector.source_schema ? [connector.source_schema] : null,
      })
      if (r.data.success) { setIntrospection(r.data); setStep('discover') }
      else setError(r.data.error || 'Discovery failed')
    } catch (e) { setError(e.response?.data?.detail || e.message) }
    setDiscovering(false)
  }

  const askQuestion = async (q) => {
    const question_text = q || question
    if (!question_text.trim() || !selectedConnId) return
    setAsking(true); setAnswer(null); setError(null)
    try {
      const r = await api.post('/chat', {
        message: question_text, connector_id: selectedConnId, history: [],
      })
      setAnswer(r.data)
      // Speak summary
      if (r.data.sql_result?.rows?.length > 0) {
        const rows = r.data.sql_result.rows
        const cols = r.data.sql_result.columns
        const top = rows.slice(0,3).map(row => cols.map((c,i) => `${c}: ${row[i]}`).join(', ')).join('; ')
        speak(`Found ${rows.length} results. ${top}`)
      }
    } catch (e) { setError(e.response?.data?.detail || e.message) }
    setAsking(false)
  }

  const summary = introspection?.summary || {}
  const tables  = Object.values(introspection?.tables || {})

  return (
    <>
      <PageHeader
        title="Plug & Play"
        subtitle="Connect any database — schema discovered automatically, ask questions instantly"
      />
      <PageBody>
        {/* Stepper */}
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

        {error && (
          <div style={{ background: '#FEF2F2', border: '1px solid #FCA5A5', borderRadius: 8,
            padding: '10px 14px', marginBottom: 16, fontSize: 12, color: '#991B1B',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>{error}</span>
            <button onClick={() => setError(null)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#991B1B', fontSize: 16 }}>✕</button>
          </div>
        )}

        {/* ── STEP 1: CONNECT ── */}
        {step === 'connect' && (
          <div style={{ maxWidth: 680 }}>
            <div style={card}>
              <div style={sectionTitle}>New connection — choose database type</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 20 }}>
                {DB_TYPES.map(db => (
                  <button key={db.value} onClick={() => { setDbType(db.value); set('port', db.port || '') }}
                    style={{
                      padding: '10px 12px', borderRadius: 8, cursor: 'pointer',
                      border: `2px solid ${dbType === db.value ? '#185FA5' : '#E5E7EB'}`,
                      background: dbType === db.value ? '#EBF4FF' : '#fff',
                      display: 'flex', alignItems: 'center', gap: 8,
                    }}>
                    <span style={{ fontSize: 18 }}>{db.icon}</span>
                    <span style={{ fontSize: 12, fontWeight: 600,
                      color: dbType === db.value ? '#185FA5' : '#374151' }}>{db.label}</span>
                  </button>
                ))}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
                <div style={{ gridColumn: '1/-1' }}>
                  <label style={lbl}>Connection name</label>
                  <input style={inp} placeholder="e.g. Production Warehouse"
                    value={form.name} onChange={e => set('name', e.target.value)} />
                </div>
                <div><label style={lbl}>Host</label>
                  <input style={inp} placeholder="localhost" value={form.host} onChange={e => set('host', e.target.value)} /></div>
                <div><label style={lbl}>Port</label>
                  <input style={inp} type="number" value={form.port} onChange={e => set('port', e.target.value)} /></div>
                <div><label style={lbl}>Database name</label>
                  <input style={inp} placeholder="mydb" value={form.database_name} onChange={e => set('database_name', e.target.value)} /></div>
                <div><label style={lbl}>Schema (optional)</label>
                  <input style={inp} placeholder="public, warehouse, bank..." value={form.source_schema} onChange={e => set('source_schema', e.target.value)} /></div>
                <div><label style={lbl}>Username</label>
                  <input style={inp} value={form.username} onChange={e => set('username', e.target.value)} /></div>
                <div><label style={lbl}>Password</label>
                  <input style={inp} type="password" value={form.password} onChange={e => set('password', e.target.value)} /></div>
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
                {testResult === 'success' && <span style={{ fontSize: 11, color: '#3B6D11' }}>✓ Connected</span>}
                {testResult === 'error'   && <span style={{ fontSize: 11, color: '#991B1B' }}>✗ Failed</span>}
              </div>
            </div>

            <div style={{ ...card, background: '#F9FAFB' }}>
              <div style={sectionTitle}>Use an existing connection</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {allConnectors.map(c => (
                  <button key={c.id} onClick={() => discoverExisting(c)} disabled={discovering}
                    style={{ padding: '7px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 12,
                      border: '1px solid #E5E7EB', background: '#fff', color: '#374151',
                      display: 'flex', alignItems: 'center', gap: 6 }}>
                    🔌 <span style={{ fontWeight: 600 }}>{c.name}</span>
                    <span style={{ color: '#9CA3AF', fontSize: 10 }}>{c.database_name}</span>
                    {discovering && connectorId === c.id && <span>⏳</span>}
                  </button>
                ))}
                {allConnectors.length === 0 && <div style={{ fontSize: 12, color: '#9CA3AF' }}>No saved connections yet.</div>}
              </div>
            </div>
          </div>
        )}

        {/* ── STEP 2: DISCOVER ── */}
        {step === 'discover' && introspection && (
          <div>
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
                  <div style={{ fontSize: 10, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.05em', marginTop: 2 }}>{s.label}</div>
                </div>
              ))}
              <div style={{ flex: 1 }} />
              <button style={btnPrimary} onClick={() => setStep('explore')}>Ask Questions ✨</button>
            </div>

            {introspection.business_context?.ai_context && (
              <div style={{ ...card, background: '#EBF4FF', borderColor: '#BFDBFE', marginBottom: 16 }}>
                <div style={sectionTitle}>🧠 AI Business Context</div>
                <p style={{ fontSize: 12, color: '#1E40AF', lineHeight: 1.7, margin: 0 }}>
                  {introspection.business_context.ai_context}
                </p>
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(290px,1fr))', gap: 12 }}>
              {tables.map((t, i) => {
                const ttype  = t.classification?.type || 'unknown'
                const colors = TYPE_COLORS[ttype] || TYPE_COLORS.unknown
                const isSel  = selectedTable?.full_name === t.full_name
                return (
                  <div key={i} onClick={() => setSelectedTable(isSel ? null : t)} style={{
                    background: isSel ? colors.bg : '#fff',
                    border: `1.5px solid ${isSel ? colors.border : '#E5E7EB'}`,
                    borderRadius: 10, padding: '12px 14px', cursor: 'pointer', transition: 'all 0.15s',
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
                        <span style={{ fontSize: 10, color: '#9CA3AF' }}>{(t.row_count||0).toLocaleString()} rows</span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {(t.columns||[]).slice(0, isSel ? 50 : 6).map((c, j) => (
                        <span key={j} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10,
                          background: '#F3F4F6', color: '#374151', border: '1px solid #E5E7EB' }}>{c.name}</span>
                      ))}
                      {!isSel && (t.columns||[]).length > 6 && (
                        <span style={{ fontSize: 10, color: '#9CA3AF', padding: '2px 4px' }}>+{t.columns.length - 6} more</span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {introspection.relationships?.length > 0 && (
              <div style={{ ...card, marginTop: 16 }}>
                <div style={sectionTitle}>🔗 Detected Relationships ({introspection.relationships.length})</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {introspection.relationships.slice(0,15).map((r, i) => (
                    <div key={i} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 6,
                      background: '#F0FDF4', border: '1px solid #BBF7D0', color: '#15803D' }}>
                      {r.from_table.split('.').pop()}.{r.from_column} → {r.to_table.split('.').pop()}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── STEP 3: EXPLORE ── */}
        {step === 'explore' && (
          <div style={{ maxWidth: 820 }}>
            <div style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <div style={sectionTitle}>Ask your data anything</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {supported && (
                    <button title={voiceOn ? 'Mute' : 'Unmute'}
                      onClick={() => { setVoiceOn(!voiceOn); stopSpeaking() }}
                      style={{ fontSize: 14, background: 'none', border: 'none', cursor: 'pointer', opacity: voiceOn?1:0.4 }}>
                      {voiceOn ? '🔊' : '🔇'}
                    </button>
                  )}
                  <button style={btnGhost} onClick={() => setStep('discover')}>← Back to schema</button>
                </div>
              </div>

              {/* Connection selector */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14,
                padding: '10px 14px', background: '#F0FDF4', borderRadius: 8, border: '1px solid #BBF7D0' }}>
                <span style={{ fontSize: 16 }}>🔌</span>
                <span style={{ fontSize: 11, color: '#15803D', fontWeight: 700 }}>CONNECTED TO:</span>
                <select value={selectedConnId} onChange={e => setSelectedConnId(e.target.value)}
                  style={{ fontSize: 12, padding: '5px 10px', border: '1px solid #BBF7D0',
                    borderRadius: 6, color: '#15803D', fontWeight: 600, background: '#F0FDF4', flex: 1, maxWidth: 300 }}>
                  {allConnectors.map(c => (
                    <option key={c.id} value={c.id}>{c.name} — {c.database_name}</option>
                  ))}
                </select>
                <span style={{ fontSize: 10, color: '#9CA3AF' }}>AI queries this DB directly</span>
              </div>

              {/* Suggestions */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
                {[
                  'Total transactions by channel',
                  'Top 5 by amount',
                  'Count records by category',
                  'Show summary statistics',
                  'Latest 10 records',
                ].map((s, i) => (
                  <button key={i} onClick={() => setQuestion(s)} style={{
                    fontSize: 10, padding: '4px 12px', borderRadius: 12,
                    background: '#EBF4FF', color: '#185FA5', border: '1px solid #BFDBFE', cursor: 'pointer',
                  }}>{s}</button>
                ))}
              </div>

              {/* Input + mic */}
              <div style={{ position: 'relative' }}>
                <input style={{ ...inp, paddingRight: supported ? 48 : 12 }}
                  placeholder="Ask anything about your data in plain English..."
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') askQuestion() }}
                />
                {supported && (
                  <button onClick={toggleListen}
                    title={listening ? 'Stop' : 'Speak'}
                    style={{
                      position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                      width: 32, height: 32, borderRadius: '50%',
                      border: listening ? '2px solid #dc2626' : '2px solid #185FA5',
                      background: listening ? '#fef2f2' : '#EBF4FF',
                      cursor: 'pointer', fontSize: 16,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      animation: listening ? 'pulse-mic 1.2s infinite' : 'none',
                    }}>
                    {listening ? '⏹' : '🎤'}
                  </button>
                )}
              </div>

              {voiceStatus && (
                <div style={{ fontSize: 11, color: '#185FA5', marginTop: 6, fontStyle: 'italic' }}>{voiceStatus}</div>
              )}

              <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
                <button style={btnPrimary} onClick={() => askQuestion()}
                  disabled={asking || !question.trim() || !selectedConnId}>
                  {asking ? '⏳ Thinking...' : '🚀 Ask'}
                </button>
                {supported && <span style={{ fontSize: 10, color: '#aaa' }}>or press 🎤 and speak</span>}
              </div>

              <style>{`
                @keyframes pulse-mic {
                  0%,100% { box-shadow: 0 0 0 0 rgba(220,38,38,0.4); }
                  50% { box-shadow: 0 0 0 8px rgba(220,38,38,0); }
                }
              `}</style>
            </div>

            {/* Answer */}
            {answer && (
              <div style={card}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#185FA5',
                  textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                  ✦ Answer
                  {supported && voiceOn && (
                    <button onClick={() => speak(answer.response || '')}
                      style={{ marginLeft: 10, fontSize: 14, background: 'none', border: 'none', cursor: 'pointer' }}>🔊</button>
                  )}
                </div>

                <div style={{ fontSize: 13, color: '#111827', lineHeight: 1.7, marginBottom: 14 }}>
                  {answer.response?.replace(/```[\s\S]*?```/g, '').trim()}
                </div>

                {/* Chart + Table */}
                {answer.sql_result?.rows?.length > 0 && (
                  <SmartChart
                    columns={answer.sql_result.columns}
                    rows={answer.sql_result.rows}
                    question={question}
                  />
                )}

                {/* SQL */}
                {answer.sql_result?.sql && (
                  <details style={{ marginTop: 8 }}>
                    <summary style={{ fontSize: 10, color: '#9CA3AF', cursor: 'pointer', userSelect: 'none' }}>
                      View SQL
                    </summary>
                    <pre style={{ background: '#1E1E1E', color: '#D4D4D4', padding: '10px 14px',
                      borderRadius: 6, fontSize: 11, overflowX: 'auto', lineHeight: 1.6, marginTop: 8 }}>
                      {answer.sql_result.sql}
                    </pre>
                  </details>
                )}
              </div>
            )}

            {/* CTA */}
            <div style={{ ...card, background: '#EBF4FF', borderColor: '#BFDBFE', textAlign: 'center' }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#185FA5', marginBottom: 6 }}>
                Want a full ETL pipeline with historical tracking?
              </div>
              <p style={{ fontSize: 12, color: '#1E40AF', marginBottom: 14, lineHeight: 1.6 }}>
                Plug & Play gives you instant BI on any existing database.
                Run the ETL Agent to build a clean star schema with SCD, data quality, and audit trails.
              </p>
              <button style={btnPrimary} onClick={() => navigate('/etl-agent')}>Go to ETL Agent →</button>
            </div>
          </div>
        )}

      </PageBody>
    </>
  )
}

const card         = { border: '1px solid #E5E7EB', borderRadius: 10, padding: '16px 18px', marginBottom: 14, background: '#fff' }
const sectionTitle = { fontSize: 10, fontWeight: 700, color: '#6B7280', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }
const inp          = { width: '100%', padding: '8px 10px', fontSize: 12, border: '1px solid #D1D5DB', borderRadius: 6, boxSizing: 'border-box' }
const lbl          = { display: 'block', fontSize: 10, fontWeight: 600, color: '#6B7280', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.04em' }
const btnPrimary   = { padding: '8px 18px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 12, cursor: 'pointer', fontWeight: 600 }
const btnSecondary = { padding: '8px 16px', background: '#fff', color: '#185FA5', border: '1px solid #185FA5', borderRadius: 6, fontSize: 12, cursor: 'pointer', fontWeight: 600 }
const btnGhost     = { padding: '7px 14px', background: '#fff', color: '#6B7280', border: '1px solid #E5E7EB', borderRadius: 6, fontSize: 12, cursor: 'pointer' }
