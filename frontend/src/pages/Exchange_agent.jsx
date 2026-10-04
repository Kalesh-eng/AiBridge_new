/**
 * Exchange.jsx — Universal Data Exchange
 * Move data between ANY source and ANY target
 * Files ↔ Databases ↔ Files
 * Multi-file upload with custom table names + natural language requirements
 */
import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'

const SOURCE_TYPES = [
  { value: 'file',       label: 'Files (CSV/Excel/JSON)', icon: '📄' },
  { value: 'postgres',   label: 'PostgreSQL',             icon: '🐘' },
  { value: 'mysql',      label: 'MySQL',                  icon: '🐬' },
  { value: 'sqlserver',  label: 'SQL Server',             icon: '🪟' },
  { value: 'snowflake',  label: 'Snowflake',              icon: '❄️' },
  { value: 'bigquery',   label: 'BigQuery',               icon: '☁️' },
  { value: 'oracle',     label: 'Oracle',                 icon: '🔴' },
]

const TARGET_TYPES = [
  { value: 'postgres',   label: 'PostgreSQL',             icon: '🐘' },
  { value: 'mysql',      label: 'MySQL',                  icon: '🐬' },
  { value: 'snowflake',  label: 'Snowflake',              icon: '❄️' },
  { value: 'bigquery',   label: 'BigQuery',               icon: '☁️' },
  { value: 'sqlserver',  label: 'SQL Server',             icon: '🪟' },
  { value: 'file',       label: 'Export to File',         icon: '📤' },
  { value: 'duckdb',     label: 'DuckDB (local)',         icon: '🦆' },
]

const LOAD_MODES = [
  { value: 'full',        label: 'Full Load',       desc: 'Replace all data' },
  { value: 'incremental', label: 'Incremental',     desc: 'Append new rows' },
  { value: 'upsert',      label: 'Upsert',          desc: 'Insert or update' },
  { value: 'warehouse',   label: 'Build Warehouse', desc: 'Auto star schema' },
]

export default function Exchange() {
  const navigate = useNavigate()
  const fileInputRef = useRef(null)

  // Source
  const [sourceType,    setSourceType]    = useState('file')
  const [sourceConnId,  setSourceConnId]  = useState('')
  const [files,         setFiles]         = useState([])  // {file, name, tableName, preview}
  const [connectors,    setConnectors]    = useState([])
  const [dbTables,      setDbTables]      = useState([])  // for DB source
  const [selectedTables, setSelectedTables] = useState([]) // {tableName, targetName}

  // Target
  const [targetType,    setTargetType]    = useState('postgres')
  const [targetConnId,  setTargetConnId]  = useState('')
  const [targetSchema,  setTargetSchema]  = useState('exchange')

  // Requirements
  const [requirements,  setRequirements]  = useState('')
  const [loadMode,      setLoadMode]      = useState('warehouse')

  // Status
  const [loading,       setLoading]       = useState(false)
  const [status,        setStatus]        = useState(null)
  const [error,         setError]         = useState(null)
  const [result,        setResult]        = useState(null)
  const [previewing,    setPreviewing]    = useState(null)

  // Load connectors
  useEffect(() => {
    api.get('/connector/list').then(r => {
      setConnectors(r.data.connectors || [])
      const dbConns = (r.data.connectors || []).filter(c => c.connector_type !== 'duckdb' && c.connector_type !== 'csv' && c.connector_type !== 'excel')
      if (dbConns.length > 0) {
        setTargetConnId(dbConns[0].id)
        setSourceConnId(dbConns[0].id)
      }
    }).catch(() => {})
  }, [])

  // Handle file drop
  const handleDrop = (e) => {
    e.preventDefault()
    const dropped = Array.from(e.dataTransfer.files)
    addFiles(dropped)
  }

  const handleFileSelect = (e) => {
    addFiles(Array.from(e.target.files))
  }

  const addFiles = (newFiles) => {
    const mapped = newFiles.map(f => ({
      file: f,
      name: f.name,
      tableName: f.name.replace(/\.(csv|xlsx|xls|json|txt)$/i, '').toLowerCase().replace(/[^a-z0-9]/g, '_'),
      size: f.size,
      type: f.name.split('.').pop().toLowerCase(),
      preview: null,
    }))
    setFiles(prev => [...prev, ...mapped])
  }

  const updateTableName = (idx, name) => {
    setFiles(prev => prev.map((f, i) => i === idx ? { ...f, tableName: name } : f))
  }

  const removeFile = (idx) => {
    setFiles(prev => prev.filter((_, i) => i !== idx))
  }

  // Load DB tables when source connector changes
  const loadDbTables = async (connId) => {
    if (!connId) return
    try {
      const r = await api.post('/dwh/introspect', { connector_id: connId })
      if (r.data.tables) {
        const tables = Object.values(r.data.tables).map(t => ({
          tableName: t.full_name,
          targetName: t.table_name,
          selected: false,
          rowCount: t.row_count || 0,
        }))
        setDbTables(tables)
      }
    } catch (e) { console.log(e) }
  }

  // Run the exchange
  const runExchange = async () => {
    if (sourceType === 'file' && files.length === 0) {
      setError('Please add at least one file')
      return
    }
    if (sourceType !== 'file' && !sourceConnId) {
      setError('Please select a source connection')
      return
    }
    if (!targetConnId && targetType !== 'file') {
      setError('Please select a target connection')
      return
    }

    setLoading(true); setError(null); setStatus('Preparing exchange...')

    try {
      if (sourceType === 'file') {
        // Upload all files first
        setStatus('Uploading files...')
        const uploadedFiles = []

        for (const f of files) {
          const formData = new FormData()
          formData.append('file', f.file)
          formData.append('table_name', f.tableName)
          const r = await api.post('/connector/file/upload', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          })
          if (r.data.connector_id) {
            uploadedFiles.push({
              connector_id: r.data.connector_id,
              table_name: f.tableName,
              file_name: f.name,
            })
          }
        }

        setStatus(`Uploaded ${uploadedFiles.length} files. Building exchange pipeline...`)

        // Create exchange pipeline
        const r = await api.post('/exchange/run', {
          source_files: uploadedFiles,
          target_connector_id: targetConnId,
          target_schema: targetSchema,
          load_mode: loadMode,
          requirements: requirements,
        })

        if (r.data.success) {
          setResult(r.data)
          setStatus('✓ Exchange complete!')
        } else {
          setError(r.data.error || 'Exchange failed')
        }
      } else {
        // DB to DB exchange
        setStatus('Starting DB exchange...')
        const tables = selectedTables.length > 0 ? selectedTables : dbTables.filter(t => t.selected)
        const r = await api.post('/exchange/run', {
          source_connector_id: sourceConnId,
          source_tables: tables,
          target_connector_id: targetConnId,
          target_schema: targetSchema,
          load_mode: loadMode,
          requirements: requirements,
        })
        if (r.data.success) {
          setResult(r.data)
          setStatus('✓ Exchange complete!')
        } else {
          setError(r.data.error || 'Exchange failed')
        }
      }
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    }
    setLoading(false)
  }

  const dbConnectors = connectors.filter(c => !['csv','excel','duckdb'].includes(c.connector_type))

  return (
    <>
      <PageHeader
        title="🔄 Exchange"
        subtitle="Move data between any source and target — files, databases, warehouses"
      />
      <PageBody>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>

          {/* ── SOURCE ── */}
          <div style={card}>
            <div style={sectionTitle}>📥 Source</div>

            {/* Source type selector */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
              {SOURCE_TYPES.map(t => (
                <button key={t.value} onClick={() => setSourceType(t.value)} style={{
                  padding: '5px 10px', borderRadius: 8, cursor: 'pointer', fontSize: 11,
                  border: `1.5px solid ${sourceType === t.value ? '#185FA5' : '#E5E7EB'}`,
                  background: sourceType === t.value ? '#EBF4FF' : '#fff',
                  color: sourceType === t.value ? '#185FA5' : '#374151',
                  fontWeight: sourceType === t.value ? 600 : 400,
                  display: 'flex', alignItems: 'center', gap: 4,
                }}>
                  <span>{t.icon}</span> {t.label}
                </button>
              ))}
            </div>

            {/* File source */}
            {sourceType === 'file' && (
              <div>
                {/* Drop zone */}
                <div
                  onDrop={handleDrop}
                  onDragOver={e => e.preventDefault()}
                  onClick={() => fileInputRef.current?.click()}
                  style={{
                    border: '2px dashed #BFDBFE', borderRadius: 10, padding: '20px',
                    textAlign: 'center', cursor: 'pointer', background: '#F0F9FF',
                    marginBottom: 12, transition: 'all 0.2s',
                  }}>
                  <div style={{ fontSize: 28, marginBottom: 6 }}>📁</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#185FA5' }}>
                    Drop files here or click to browse
                  </div>
                  <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 4 }}>
                    CSV, Excel (.xlsx), JSON, TXT — multiple files supported
                  </div>
                  <input ref={fileInputRef} type="file" multiple
                    accept=".csv,.xlsx,.xls,.json,.txt"
                    style={{ display: 'none' }} onChange={handleFileSelect} />
                </div>

                {/* File list */}
                {files.length > 0 && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: '#6B7280',
                      textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                      {files.length} file{files.length > 1 ? 's' : ''} — set target table names
                    </div>
                    {files.map((f, i) => (
                      <div key={i} style={{
                        display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
                        padding: '8px 10px', background: '#F9FAFB', borderRadius: 8,
                        border: '1px solid #E5E7EB',
                      }}>
                        <span style={{ fontSize: 18 }}>
                          {f.type === 'xlsx' || f.type === 'xls' ? '📊' : f.type === 'json' ? '{}' : '📄'}
                        </span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 3,
                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {f.name}
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ fontSize: 10, color: '#9CA3AF' }}>→ table:</span>
                            <input
                              value={f.tableName}
                              onChange={e => updateTableName(i, e.target.value)}
                              style={{ fontSize: 11, padding: '2px 6px', border: '1px solid #D1D5DB',
                                borderRadius: 4, flex: 1, fontFamily: 'monospace' }}
                            />
                          </div>
                        </div>
                        <div style={{ fontSize: 10, color: '#9CA3AF', whiteSpace: 'nowrap' }}>
                          {(f.size / 1024).toFixed(0)} KB
                        </div>
                        <button onClick={() => removeFile(i)}
                          style={{ background: 'none', border: 'none', cursor: 'pointer',
                            color: '#EF4444', fontSize: 16, padding: 0 }}>✕</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* DB source */}
            {sourceType !== 'file' && (
              <div>
                <label style={lbl}>Source Connection</label>
                <select style={inp} value={sourceConnId} onChange={e => {
                  setSourceConnId(e.target.value)
                  loadDbTables(e.target.value)
                }}>
                  <option value="">Select connection...</option>
                  {dbConnectors.filter(c => c.connector_type === sourceType).map(c => (
                    <option key={c.id} value={c.id}>{c.name} — {c.database_name}</option>
                  ))}
                </select>

                {dbTables.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: '#6B7280',
                      textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                      Select tables to exchange
                    </div>
                    <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                      {dbTables.map((t, i) => (
                        <div key={i} style={{
                          display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
                          padding: '6px 8px', background: '#F9FAFB', borderRadius: 6,
                        }}>
                          <input type="checkbox" checked={t.selected}
                            onChange={() => setDbTables(prev => prev.map((x, j) =>
                              j === i ? { ...x, selected: !x.selected } : x))} />
                          <span style={{ fontSize: 11, flex: 1, fontFamily: 'monospace' }}>{t.tableName}</span>
                          <span style={{ fontSize: 10, color: '#9CA3AF' }}>{t.rowCount} rows</span>
                          <span style={{ fontSize: 10, color: '#9CA3AF' }}>→</span>
                          <input value={t.targetName}
                            onChange={e => setDbTables(prev => prev.map((x, j) =>
                              j === i ? { ...x, targetName: e.target.value } : x))}
                            style={{ fontSize: 11, padding: '2px 6px', border: '1px solid #D1D5DB',
                              borderRadius: 4, width: 120, fontFamily: 'monospace' }} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── TARGET ── */}
          <div style={card}>
            <div style={sectionTitle}>📤 Target</div>

            {/* Target type selector */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
              {TARGET_TYPES.map(t => (
                <button key={t.value} onClick={() => setTargetType(t.value)} style={{
                  padding: '5px 10px', borderRadius: 8, cursor: 'pointer', fontSize: 11,
                  border: `1.5px solid ${targetType === t.value ? '#3B6D11' : '#E5E7EB'}`,
                  background: targetType === t.value ? '#F0FDF4' : '#fff',
                  color: targetType === t.value ? '#3B6D11' : '#374151',
                  fontWeight: targetType === t.value ? 600 : 400,
                  display: 'flex', alignItems: 'center', gap: 4,
                }}>
                  <span>{t.icon}</span> {t.label}
                </button>
              ))}
            </div>

            {targetType !== 'file' && (
              <div>
                <label style={lbl}>Target Connection</label>
                <select style={inp} value={targetConnId} onChange={e => setTargetConnId(e.target.value)}>
                  <option value="">Select connection...</option>
                  {dbConnectors.map(c => (
                    <option key={c.id} value={c.id}>{c.name} — {c.database_name}</option>
                  ))}
                </select>

                <label style={{ ...lbl, marginTop: 10 }}>Target Schema</label>
                <input style={inp} value={targetSchema}
                  onChange={e => setTargetSchema(e.target.value)}
                  placeholder="e.g. suitecrm_dwh, exchange, analytics" />

                <div style={{ fontSize: 10, color: '#3B6D11', marginTop: 6 }}>
                  ✓ Tables will be created in this schema automatically
                </div>
              </div>
            )}

            {targetType === 'file' && (
              <div style={{ padding: '20px', textAlign: 'center', background: '#F9FAFB',
                borderRadius: 8, border: '1px dashed #D1D5DB' }}>
                <div style={{ fontSize: 24, marginBottom: 8 }}>📤</div>
                <div style={{ fontSize: 12, color: '#6B7280' }}>
                  Data will be exported as Excel files after exchange
                </div>
              </div>
            )}

            {/* Load mode */}
            <div style={{ marginTop: 14 }}>
              <label style={lbl}>Load Mode</label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                {LOAD_MODES.map(m => (
                  <button key={m.value} onClick={() => setLoadMode(m.value)} style={{
                    padding: '8px 10px', borderRadius: 8, cursor: 'pointer', textAlign: 'left',
                    border: `1.5px solid ${loadMode === m.value ? '#185FA5' : '#E5E7EB'}`,
                    background: loadMode === m.value ? '#EBF4FF' : '#fff',
                  }}>
                    <div style={{ fontSize: 11, fontWeight: 600,
                      color: loadMode === m.value ? '#185FA5' : '#374151' }}>{m.label}</div>
                    <div style={{ fontSize: 10, color: '#9CA3AF', marginTop: 2 }}>{m.desc}</div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* ── REQUIREMENTS ── */}
        <div style={card}>
          <div style={sectionTitle}>🧠 Business Requirements (natural language — optional)</div>
          <textarea
            style={{ width: '100%', padding: '10px 12px', fontSize: 12, border: '1px solid #D1D5DB',
              borderRadius: 8, minHeight: 80, resize: 'vertical', boxSizing: 'border-box',
              fontFamily: 'system-ui' }}
            placeholder='e.g. "This is CRM data from SuiteCRM. accounts links to leads via company name. Build a sales analytics warehouse. Key metrics: lead conversion rate, pipeline by stage, inactive accounts (no activity 90+ days), sales rep performance."'
            value={requirements}
            onChange={e => setRequirements(e.target.value)}
          />
          {/* Preset templates */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {[
              { label: '1:1 Load',        text: 'Load each file as-is into its own table. No transformation. Direct one-to-one mapping from source to target.' },
              { label: 'Sample (100 rows)',text: 'Load only the first 100 rows from each file for testing and preview purposes.' },
              { label: 'Build Warehouse', text: 'Analyze all files, detect relationships between tables, build a star schema warehouse with fact and dimension tables.' },
              { label: 'CRM Analytics',   text: 'This is CRM data. Build analytics for: lead conversion rates, pipeline by stage, inactive accounts (no activity 90+ days), sales rep performance, revenue forecast.' },
              { label: 'Clean & Load',    text: 'Clean the data before loading: remove duplicates, fix null values, standardize date formats, trim whitespace. Then load to target tables.' },
            ].map((t, i) => (
              <button key={i} onClick={() => setRequirements(t.text)}
                style={{ fontSize: 10, padding: '3px 10px', borderRadius: 10, cursor: 'pointer',
                  border: '1px solid #D1D5DB', background: requirements === t.text ? '#EBF4FF' : '#F9FAFB',
                  color: requirements === t.text ? '#185FA5' : '#6B7280',
                  fontWeight: requirements === t.text ? 600 : 400 }}>
                {t.label}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 10, color: '#9CA3AF', marginTop: 6 }}>
            AIBridge AI reads this and optimizes the data model accordingly
          </div>
        </div>

        {/* ── SUMMARY + RUN ── */}
        <div style={{ ...card, background: '#F0FDF4', borderColor: '#BBF7D0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#15803D', marginBottom: 4 }}>
                Exchange Summary
              </div>
              <div style={{ fontSize: 12, color: '#374151' }}>
                <span style={{ fontWeight: 600 }}>
                  {sourceType === 'file'
                    ? `${files.length} file${files.length !== 1 ? 's' : ''}`
                    : `DB: ${dbConnectors.find(c => c.id === sourceConnId)?.name || 'none'}`}
                </span>
                {' '}→ AIBridge →{' '}
                <span style={{ fontWeight: 600 }}>
                  {targetType === 'file'
                    ? 'Excel export'
                    : `${dbConnectors.find(c => c.id === targetConnId)?.name || 'none'}.${targetSchema}`}
                </span>
                {' '}({LOAD_MODES.find(m => m.value === loadMode)?.label})
              </div>
              {files.length > 0 && sourceType === 'file' && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                  {files.map((f, i) => (
                    <span key={i} style={{ fontSize: 10, padding: '2px 8px', borderRadius: 10,
                      background: '#DCFCE7', color: '#15803D', border: '1px solid #BBF7D0' }}>
                      {f.tableName}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <button style={{
              padding: '12px 24px', background: loading ? '#9CA3AF' : '#15803D',
              color: '#fff', border: 'none', borderRadius: 8, fontSize: 14,
              cursor: loading ? 'not-allowed' : 'pointer', fontWeight: 700,
              whiteSpace: 'nowrap',
            }} onClick={runExchange} disabled={loading}>
              {loading ? '⏳ Exchanging...' : '🚀 Run Exchange'}
            </button>
          </div>
        </div>

        {/* ── STATUS ── */}
        {status && !error && (
          <div style={{ ...card, background: '#EBF4FF', borderColor: '#BFDBFE' }}>
            <div style={{ fontSize: 13, color: '#185FA5', fontWeight: 500 }}>
              {loading ? '⏳ ' : '✅ '}{status}
            </div>
          </div>
        )}

        {error && (
          <div style={{ ...card, background: '#FEF2F2', borderColor: '#FCA5A5' }}>
            <div style={{ fontSize: 13, color: '#991B1B' }}>❌ {error}</div>
          </div>
        )}

        {/* ── RESULT ── */}
        {result && (
          <div style={card}>
            <div style={sectionTitle}>✅ Exchange Complete</div>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
              {[
                { val: result.tables_loaded || files.length, label: 'Tables loaded', color: '#185FA5' },
                { val: result.total_rows || '?', label: 'Total rows', color: '#3B6D11' },
                { val: result.duration || '?', label: 'Duration', color: '#854F0B' },
              ].map((s, i) => (
                <div key={i} style={{ background: '#F9FAFB', border: '1px solid #E5E7EB',
                  borderRadius: 8, padding: '10px 16px', textAlign: 'center' }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color: s.color }}>{s.val}</div>
                  <div style={{ fontSize: 10, color: '#9CA3AF', textTransform: 'uppercase' }}>{s.label}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button style={btnPrimary} onClick={() => navigate('/analytics')}>
                📊 Go to Analytics →
              </button>
              <button style={btnSecondary} onClick={() => navigate('/plug-and-play')}>
                🔌 Explore in Plug & Play →
              </button>
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
