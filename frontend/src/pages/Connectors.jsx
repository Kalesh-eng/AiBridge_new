/**
 * Connectors.jsx — Edit + reliable schema loading
 * v2.0: CSV/Excel upload now auto-creates connector + shows success panel
 *       with row count, columns, and "Go to ETL Agent" button
 */

import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, PageBody } from '../components/Layout'
import { Spinner, EmptyState, getErrorMessage } from '../components/ErrorBoundary'
import api from '../api/api'

const DB_TYPES = [
  { value: 'postgres',  label: 'PostgreSQL',  icon: '🐘', category: 'On-Prem', port: 5432  },
  { value: 'mysql',     label: 'MySQL',        icon: '🐬', category: 'On-Prem', port: 3306  },
  { value: 'sqlserver', label: 'SQL Server',   icon: '🪟', category: 'On-Prem', port: 1433  },
  { value: 'oracle',    label: 'Oracle',       icon: '🔴', category: 'On-Prem', port: 1521  },
  { value: 'sqlite',    label: 'SQLite',       icon: '📁', category: 'On-Prem', port: null  },
  { value: 'snowflake', label: 'Snowflake',    icon: '❄️', category: 'Cloud',   port: 443   },
  { value: 'bigquery',  label: 'BigQuery',     icon: '☁️', category: 'Cloud',   port: null  },
  { value: 'redshift',  label: 'Redshift',     icon: '🔴', category: 'Cloud',   port: 5439  },
  { value: 'azuresql',  label: 'Azure SQL',    icon: '🔷', category: 'Cloud',   port: 1433  },
  { value: 'csv',       label: 'CSV File',     icon: '📄', category: 'File',    port: null  },
  { value: 'excel',     label: 'Excel File',   icon: '📊', category: 'File',    port: null  },
]

const CATEGORIES = ['On-Prem', 'Cloud', 'File']

const EMPTY_CONFIG = {
  name: '', connector_type: 'postgres', role: 'both',
  host: 'localhost', port: 5432, database_name: '',
  username: '', password: '',
  source_schema: 'raw',
  account: '', project_id: '', dataset_id: '', credentials_json: '',
  file_path: '', warehouse: 'COMPUTE_WH'
}

export default function Connectors() {
  const navigate     = useNavigate()
  const [tab,        setTab]        = useState('saved')
  const [saved,      setSaved]      = useState([])
  const [loading,    setLoading]    = useState(true)
  const [config,     setConfig]     = useState({ ...EMPTY_CONFIG })
  const [editingId,  setEditingId]  = useState(null)
  const [availableSchemas, setAvailableSchemas] = useState([])
  const [loadingSchemas, setLoadingSchemas]     = useState(false)
  const [status,     setStatus]     = useState(null)
  const [testing,    setTesting]    = useState(false)
  const [saving,     setSaving]     = useState(false)
  const [schema,     setSchema]     = useState(null)
  const [tables,     setTables]     = useState(null)
  const [activeConn, setActiveConn] = useState(null)
  const [preview,    setPreview]    = useState(null)
  const [successMsg, setSuccessMsg] = useState(null)
  const [uploadResult,  setUploadResult]  = useState(null)
  const [uploading,     setUploading]     = useState(false)
  const [reuploading,   setReuploading]   = useState(null)   // connector id being re-uploaded
  const [reuploadMsg,   setReuploadMsg]   = useState({})     // connectorId -> message
  const fileRef    = useRef()
  const reuploadRef = useRef()

  useEffect(() => { loadSaved() }, [])

  const loadSaved = async () => {
    try {
      const r = await api.get('/connector/list')
      setSaved(r.data.connectors || [])
    } catch { setSaved([]) }
    finally { setLoading(false) }
  }

  const selectedType = DB_TYPES.find(d => d.value === config.connector_type)

  const loadSchemas = async () => {
    if (!config.host || !config.database_name || !config.username) {
      setStatus({ ok: false, msg: 'Fill in host, database, and username first' })
      return
    }
    setLoadingSchemas(true)
    try {
      const s = await api.post('/connector/postgres/schemas', {
        host: config.host, port: config.port,
        database: config.database_name,
        username: config.username, password: config.password
      })
      const schemas = s.data.schemas || []
      if (schemas.length > 0) {
        setAvailableSchemas(schemas)
        setStatus({ ok: true, msg: `Found ${schemas.length} schemas` })
      } else {
        setStatus({ ok: false, msg: 'No schemas found (check password)' })
      }
    } catch (e) {
      setStatus({ ok: false, msg: 'Could not load schemas: ' + getErrorMessage(e) })
    }
    setLoadingSchemas(false)
  }

  const testConnection = async () => {
    setTesting(true); setStatus(null)
    try {
      const r = await api.post('/connector/postgres/test', {
        host: config.host, port: config.port,
        database: config.database_name,
        username: config.username, password: config.password
      })
      setStatus({ ok: r.data.success, msg: r.data.message })
      if (r.data.success) {
        try {
          const s = await api.post('/connector/postgres/schemas', {
            host: config.host, port: config.port,
            database: config.database_name,
            username: config.username, password: config.password
          })
          const schemas = s.data.schemas || []
          setAvailableSchemas(schemas)
          if (!schemas.includes(config.source_schema)) {
            if (schemas.includes('raw'))         setConfig(c => ({ ...c, source_schema: 'raw' }))
            else if (schemas.includes('public')) setConfig(c => ({ ...c, source_schema: 'public' }))
            else if (schemas.length > 0)         setConfig(c => ({ ...c, source_schema: schemas[0] }))
          }
        } catch { /* optional */ }
      }
    } catch (e) {
      setStatus({ ok: false, msg: getErrorMessage(e) })
    }
    setTesting(false)
  }

  const extractSchema = async () => {
    setTesting(true)
    try {
      const r = await api.post('/connector/postgres/schema', {
        host: config.host, port: config.port,
        database: config.database_name,
        username: config.username, password: config.password
      })
      setSchema(r.data)
    } catch (e) {
      setStatus({ ok: false, msg: getErrorMessage(e) })
    }
    setTesting(false)
  }

  const startEdit = async (connector) => {
    try {
      const r = await api.get(`/connector/${connector.id}`)
      const c = r.data.connector
      setConfig({
        ...EMPTY_CONFIG,
        name: c.name, connector_type: c.connector_type, role: c.role,
        host: c.host, port: c.port, database_name: c.database_name,
        username: c.username, password: '',
        source_schema: c.source_schema || 'raw'
      })
      setEditingId(connector.id)
      setAvailableSchemas(c.source_schema ? [c.source_schema] : [])
      setStatus(null); setSchema(null)
      setTab('add')
    } catch (e) { alert(getErrorMessage(e)) }
  }

  const cancelEdit = () => {
    setConfig({ ...EMPTY_CONFIG }); setEditingId(null)
    setAvailableSchemas([]); setStatus(null); setTab('saved')
  }

  const saveConnector = async () => {
    if (!config.name) { setStatus({ ok: false, msg: 'Enter a connection name' }); return }
    setSaving(true)
    try {
      if (editingId) {
        const payload = {
          name: config.name, role: config.role,
          host: config.host, port: config.port,
          database_name: config.database_name,
          username: config.username,
          source_schema: config.source_schema
        }
        if (config.password) payload.password = config.password
        await api.put(`/connector/${editingId}`, payload)
        setSuccessMsg(`✓ "${config.name}" updated successfully`)
      } else {
        await api.post('/connector/save', config)
        setSuccessMsg(`✓ "${config.name}" saved successfully`)
      }
      setConfig({ ...EMPTY_CONFIG }); setEditingId(null)
      setAvailableSchemas([]); loadSaved(); setTab('saved')
      setTimeout(() => setSuccessMsg(null), 3000)
    } catch (e) {
      setStatus({ ok: false, msg: getErrorMessage(e) })
    }
    setSaving(false)
  }

  const deleteConnector = async (id, name) => {
    if (!window.confirm(`Delete "${name}"?`)) return
    await api.delete(`/connector/${id}`)
    loadSaved()
  }

  const viewTables = async (connector) => {
    setActiveConn(connector); setTables(null); setPreview(null); setTab('tables')
    try {
      const r = await api.get(`/connector/${connector.id}/tables`)
      setTables(r.data)
    } catch (e) { alert(getErrorMessage(e)) }
  }

  const previewTable = async (schemaName, tableName) => {
    setPreview(null)
    try {
      const r = await api.get(`/connector/${activeConn.id}/preview/${schemaName}/${tableName}`)
      setPreview(r.data)
    } catch (e) { alert(getErrorMessage(e)) }
  }

  // ── NEW: Fixed upload handler ─────────────────────────────────────────────
  const uploadFile = async (e) => {
    const file = e.target.files[0]; if (!file) return
    setUploading(true); setSuccessMsg(null); setUploadResult(null)
    const form = new FormData(); form.append('file', file)
    try {
      const r = await api.post('/connector/file/upload', form,
        { headers: { 'Content-Type': 'multipart/form-data' } })
      setUploadResult(r.data)
      setSuccessMsg(r.data.message || `✓ File loaded: ${r.data.table}`)
      await loadSaved()  // refresh connector list — new connector appears
    } catch (e) {
      alert('Upload failed: ' + getErrorMessage(e))
    }
    setUploading(false)
  }

  // Re-upload a new file to an existing DuckDB connector
  // Replaces the DuckDB table with fresh data, keeps the same connector ID
  // so all existing pipelines continue to work without any changes.
  const reuploadFile = async (e, connectorId, connectorName) => {
    const file = e.target.files[0]; if (!file) return
    setReuploading(connectorId)
    setReuploadMsg(prev => ({ ...prev, [connectorId]: '' }))
    const form = new FormData()
    form.append('file', file)
    form.append('connector_id', connectorId)
    try {
      const r = await api.post('/connector/file/upload', form,
        { headers: { 'Content-Type': 'multipart/form-data' } })
      setReuploadMsg(prev => ({
        ...prev,
        [connectorId]: r.data.message || `✓ ${file.name} loaded — ${r.data.rows?.toLocaleString()} rows`
      }))
      await loadSaved()
      setTimeout(() => setReuploadMsg(prev => ({ ...prev, [connectorId]: '' })), 5000)
    } catch (e2) {
      setReuploadMsg(prev => ({
        ...prev,
        [connectorId]: '✗ Upload failed: ' + (e2.response?.data?.detail || e2.message)
      }))
    }
    setReuploading(null)
    e.target.value = ''
  }

  const needsFileInput  = ['csv','excel'].includes(config.connector_type)
  const needsCloudInput = ['bigquery'].includes(config.connector_type)
  const needsSnowflake  = config.connector_type === 'snowflake'

  return (
    <>
      <PageHeader
        title="Connectors"
        subtitle="Connect your databases — on-prem, cloud, or upload CSV/Excel files directly."
      />
      <PageBody>

        {successMsg && (
          <div style={{ background: '#EAF3DE', border: '1px solid #a7d9a0',
            borderRadius: 6, padding: '8px 14px', fontSize: 12,
            color: '#27500A', marginBottom: 12 }}>
            {successMsg}
          </div>
        )}

        <div style={{ display: 'flex', gap: 5, marginBottom: 16, flexWrap: 'wrap' }}>
          {[
            { key: 'saved',  label: `My connections (${saved.length})` },
            { key: 'add',    label: editingId ? '✎ Editing connection' : '+ Add connection' },
            { key: 'tables', label: '📋 View tables by schema' },
          ].map(t => (
            <button key={t.key}
              style={tab === t.key ? btnActive : btnGhost}
              onClick={() => { if (t.key !== 'add' && editingId) cancelEdit(); setTab(t.key) }}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Saved connectors ── */}
        {tab === 'saved' && (
          <div>
            {loading && <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spinner /></div>}
            {!loading && saved.length === 0 && (
              <EmptyState
                icon="🔌"
                title="No connections yet"
                message="Connect your database or upload a CSV file to get started."
                action={() => setTab('add')}
                actionLabel="Add your first connection"
              />
            )}
            {saved.map(c => {
              const dbType  = DB_TYPES.find(d => d.value === c.connector_type)
              const isFile  = c.connector_type === 'duckdb'
              return (
                <div key={c.id} style={card}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                    <span style={{ fontSize: 22 }}>
                      {isFile ? '📄' : (dbType?.icon || '🗄️')}
                    </span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{c.name}</div>
                      <div style={{ fontSize: 10, color: '#888', fontFamily: 'monospace' }}>
                        {isFile
                          ? `DuckDB table: ${c.database_name}`
                          : `${c.username}@${c.host}${c.port ? `:${c.port}` : ''}/${c.database_name}`}
                        {c.source_schema ? ` · schema: ${c.source_schema}` : ''}
                      </div>
                    </div>
                    <div style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
                      <span style={tagGreen}>{c.role}</span>
                      <span style={tagBlue}>
                        {isFile ? 'CSV/File' : (dbType?.label || c.connector_type)}
                      </span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {!isFile && (
                      <button style={btnPrimary} onClick={() => viewTables(c)}>View tables</button>
                    )}
                    {isFile && (
                      <button style={btnPrimary} onClick={() => navigate('/agent')}>
                        🚀 Use in ETL Agent
                      </button>
                    )}
                    {isFile && (
                      <>
                        <input
                          type="file" accept=".csv,.xlsx,.xls"
                          ref={reuploadRef}
                          style={{ display: 'none' }}
                          onChange={e => reuploadFile(e, c.id, c.name)}
                        />
                        <button
                          style={{ ...btnGhost, color: '#185FA5', borderColor: '#185FA5',
                            opacity: reuploading === c.id ? 0.6 : 1 }}
                          onClick={() => {
                            reuploadRef.current.dataset.connectorId = c.id
                            reuploadRef.current.click()
                          }}
                          disabled={reuploading === c.id}>
                          {reuploading === c.id ? '⏳ Uploading...' : '🔄 Re-upload file'}
                        </button>
                      </>
                    )}
                    {!isFile && (
                      <button style={btnGhost} onClick={() => startEdit(c)}>✎ Edit</button>
                    )}
                    <button style={btnGhost} onClick={() => deleteConnector(c.id, c.name)}>Delete</button>
                  </div>
                  {reuploadMsg[c.id] && (
                    <div style={{ marginTop: 8, fontSize: 11, padding: '5px 10px', borderRadius: 6,
                      background: reuploadMsg[c.id].startsWith('✓') ? '#EAF3DE' : '#fef2f2',
                      color: reuploadMsg[c.id].startsWith('✓') ? '#27500A' : '#991b1b' }}>
                      {reuploadMsg[c.id]}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* ── Add connection ── */}
        {tab === 'add' && (
          <div>
            {editingId && (
              <div style={{ background: '#E6F1FB', border: '1px solid #185FA5',
                borderRadius: 6, padding: '8px 14px', fontSize: 12, color: '#0C447C',
                marginBottom: 12, display: 'flex', justifyContent: 'space-between',
                alignItems: 'center' }}>
                <span>✎ Editing "<strong>{config.name}</strong>" — click "🔄 Load schemas" to refresh schema list.</span>
                <button style={{ ...btnGhost, fontSize: 10, padding: '4px 10px' }} onClick={cancelEdit}>
                  Cancel edit
                </button>
              </div>
            )}

            {!editingId && CATEGORIES.map(cat => (
              <div key={cat} style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                  textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 6 }}>
                  {cat}
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {DB_TYPES.filter(d => d.category === cat).map(db => (
                    <button key={db.value}
                      style={{ border: `1.5px solid ${config.connector_type === db.value ? '#185FA5' : '#e5e7eb'}`,
                        borderRadius: 8, padding: '8px 12px',
                        background: config.connector_type === db.value ? '#E6F1FB' : '#fff',
                        cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
                      onClick={() => {
                        setUploadResult(null)
                        setConfig({ ...config, connector_type: db.value, port: db.port || config.port })
                      }}>
                      <span style={{ fontSize: 16 }}>{db.icon}</span>
                      <span style={{ fontSize: 11, fontWeight: 500,
                        color: config.connector_type === db.value ? '#185FA5' : '#555' }}>
                        {db.label}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}

            {/* ── File upload panel ── */}
            {needsFileInput && !editingId && (
              <div style={card}>
                <div style={sectionTitle}>Upload file — loads into DuckDB → builds warehouse</div>

                {/* Drop zone */}
                <div
                  onDragOver={e => { e.preventDefault(); e.currentTarget.style.borderColor = '#185FA5'; e.currentTarget.style.background = '#EBF4FF' }}
                  onDragLeave={e => { e.currentTarget.style.borderColor = '#d1d5db'; e.currentTarget.style.background = uploading ? '#EBF4FF' : '#fff' }}
                  onDrop={e => {
                    e.preventDefault()
                    e.currentTarget.style.borderColor = '#d1d5db'
                    e.currentTarget.style.background = '#fff'
                    const file = e.dataTransfer.files[0]
                    if (file) uploadFile({ target: { files: [file] } })
                  }}
                  style={{ border: `2px dashed ${uploading ? '#185FA5' : '#d1d5db'}`,
                    borderRadius: 8, padding: 32, textAlign: 'center', cursor: 'pointer',
                    background: uploading ? '#EBF4FF' : '#fff',
                    transition: 'all 0.2s' }}
                  onClick={() => !uploading && fileRef.current?.click()}>
                  <div style={{ fontSize: 40, marginBottom: 8 }}>
                    {uploading ? '⏳' : config.connector_type === 'csv' ? '📄' : '📊'}
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 4 }}>
                    {uploading
                      ? 'Uploading and processing...'
                      : `Click or drag & drop ${config.connector_type.toUpperCase()} file here`}
                  </div>
                  <div style={{ fontSize: 11, color: '#888' }}>
                    {uploading
                      ? 'Loading into DuckDB, please wait'
                      : 'File will be loaded into DuckDB and a connector created automatically'}
                  </div>
                  <input ref={fileRef} type="file"
                    accept=".csv,.xlsx,.xls" style={{ display: 'none' }}
                    onChange={uploadFile} />
                </div>

                {/* ── Upload success panel ── */}
                {uploadResult && (
                  <div style={{ background: '#EAF3DE', border: '1px solid #a7d9a0',
                    borderRadius: 8, padding: '16px', marginTop: 12 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#27500A', marginBottom: 10 }}>
                      ✅ File loaded successfully!
                    </div>

                    {/* Stats row */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)',
                      gap: 8, marginBottom: 12 }}>
                      {[
                        { label: 'Table', value: uploadResult.table, mono: true },
                        { label: 'Rows',  value: uploadResult.rows?.toLocaleString() },
                        { label: 'Columns', value: uploadResult.columns?.length },
                      ].map(s => (
                        <div key={s.label} style={{ background: '#fff', borderRadius: 6,
                          padding: '8px 12px' }}>
                          <div style={{ fontSize: 10, color: '#888', marginBottom: 2 }}>{s.label}</div>
                          <div style={{ fontSize: 13, fontWeight: 700,
                            color: '#27500A',
                            fontFamily: s.mono ? 'monospace' : 'inherit' }}>
                            {s.value}
                          </div>
                        </div>
                      ))}
                    </div>

                    {/* Column list */}
                    {uploadResult.columns && (
                      <div style={{ marginBottom: 12 }}>
                        <div style={{ fontSize: 10, color: '#555', fontWeight: 600,
                          marginBottom: 6 }}>
                          COLUMNS DETECTED
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {uploadResult.columns.map(col => (
                            <span key={col.name} style={{ fontSize: 10, padding: '2px 8px',
                              borderRadius: 10, background: '#fff', color: '#185FA5',
                              border: '1px solid #93C5FD', fontFamily: 'monospace' }}>
                              {col.name}
                              <span style={{ color: '#888', marginLeft: 4 }}>
                                {col.type?.toLowerCase().includes('varchar') || col.type?.toLowerCase().includes('text')
                                  ? 'text' : col.type?.toLowerCase().includes('int') ? 'int'
                                  : col.type?.toLowerCase().includes('double') || col.type?.toLowerCase().includes('float')
                                  ? 'decimal' : col.type?.toLowerCase()}
                              </span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div style={{ fontSize: 11, color: '#27500A', marginBottom: 12 }}>
                      ✓ Connector saved automatically as "<strong>{uploadResult.connector_name}</strong>"
                      <br />
                      Go to ETL Agent → select this connector → build your warehouse!
                    </div>

                    <div style={{ display: 'flex', gap: 8 }}>
                      <button
                        style={{ padding: '8px 18px', background: '#185FA5', color: '#fff',
                          border: 'none', borderRadius: 6, fontSize: 12,
                          cursor: 'pointer', fontWeight: 600 }}
                        onClick={() => navigate('/agent')}>
                        🚀 Go to ETL Agent →
                      </button>
                      <button
                        style={{ ...btnGhost, fontSize: 11 }}
                        onClick={() => { setUploadResult(null); setTab('saved') }}>
                        View My Connections
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── DB connection form ── */}
            {!needsFileInput && (
              <div style={card}>
                <div style={sectionTitle}>Connection details — {selectedType?.label}</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr',
                  gap: 10, marginBottom: 12 }}>
                  <Field label="Connection name">
                    <input style={inp} value={config.name}
                      onChange={e => setConfig({...config, name: e.target.value})}
                      placeholder={`My ${selectedType?.label}`} />
                  </Field>
                  <Field label="Role">
                    <select style={inp} value={config.role}
                      onChange={e => setConfig({...config, role: e.target.value})}>
                      <option value="both">Source + Target (same DB)</option>
                      <option value="source">Source only</option>
                      <option value="target">Target only</option>
                    </select>
                  </Field>

                  {needsSnowflake ? (
                    <>
                      <Field label="Account (e.g. xyz.us-east-1)">
                        <input style={inp} value={config.account}
                          onChange={e => setConfig({...config, account: e.target.value})} />
                      </Field>
                      <Field label="Warehouse">
                        <input style={inp} value={config.warehouse}
                          onChange={e => setConfig({...config, warehouse: e.target.value})} />
                      </Field>
                    </>
                  ) : needsCloudInput ? (
                    <>
                      <Field label="Project ID">
                        <input style={inp} value={config.project_id}
                          onChange={e => setConfig({...config, project_id: e.target.value})} />
                      </Field>
                      <Field label="Dataset ID">
                        <input style={inp} value={config.dataset_id}
                          onChange={e => setConfig({...config, dataset_id: e.target.value})} />
                      </Field>
                    </>
                  ) : (
                    <>
                      <Field label="Host">
                        <input style={inp} value={config.host}
                          onChange={e => setConfig({...config, host: e.target.value})} />
                      </Field>
                      <Field label="Port">
                        <input style={inp} type="number" value={config.port}
                          onChange={e => setConfig({...config, port: +e.target.value})} />
                      </Field>
                    </>
                  )}

                  <Field label="Database name">
                    <input style={inp} value={config.database_name}
                      onChange={e => setConfig({...config, database_name: e.target.value})} />
                  </Field>
                  <Field label="Username">
                    <input style={inp} value={config.username}
                      onChange={e => setConfig({...config, username: e.target.value})} />
                  </Field>
                  <Field label={editingId ? "Password (blank = keep current)" : "Password"}>
                    <input style={inp} type="password" value={config.password}
                      placeholder={editingId ? "•••••• (unchanged)" : ""}
                      onChange={e => setConfig({...config, password: e.target.value})} />
                  </Field>
                  <Field label="Source schema (where your data lives)">
                    <div style={{ display: 'flex', gap: 6 }}>
                      {availableSchemas.length > 0 ? (
                        <select style={{ ...inp, flex: 1 }} value={config.source_schema}
                          onChange={e => setConfig({...config, source_schema: e.target.value})}>
                          {availableSchemas.map(s => <option key={s} value={s}>{s}</option>)}
                        </select>
                      ) : (
                        <input style={{ ...inp, flex: 1 }} value={config.source_schema}
                          placeholder="raw"
                          onChange={e => setConfig({...config, source_schema: e.target.value})} />
                      )}
                      <button style={{ ...btnGhost, whiteSpace: 'nowrap' }}
                        onClick={loadSchemas} disabled={loadingSchemas}>
                        {loadingSchemas ? '⏳' : '🔄 Load schemas'}
                      </button>
                    </div>
                  </Field>

                  {needsCloudInput && (
                    <div style={{ gridColumn: '1/-1' }}>
                      <Field label="Service account JSON (paste entire JSON key)">
                        <textarea style={{ ...inp, resize: 'vertical',
                          fontFamily: 'monospace', fontSize: 10 }} rows={4}
                          value={config.credentials_json}
                          onChange={e => setConfig({...config, credentials_json: e.target.value})}
                          placeholder='{"type":"service_account","project_id":"..."}' />
                      </Field>
                    </div>
                  )}
                </div>

                {status && (
                  <div style={{ background: status.ok ? '#EAF3DE' : '#fef2f2',
                    border: `1px solid ${status.ok ? '#a7d9a0' : '#fca5a5'}`,
                    borderRadius: 6, padding: '7px 12px', fontSize: 11,
                    color: status.ok ? '#27500A' : '#991b1b', marginBottom: 10 }}>
                    {status.ok ? '✓ ' : '✗ '}{status.msg}
                  </div>
                )}

                <div style={{ display: 'flex', gap: 8 }}>
                  <button style={btnPrimary} onClick={testConnection} disabled={testing}>
                    {testing ? <><Spinner size={12} color="#fff" />&nbsp;Testing...</> : 'Test connection'}
                  </button>
                  {(status?.ok || editingId) && (
                    <>
                      <button style={btnGhost} onClick={extractSchema} disabled={testing}>
                        Extract schema
                      </button>
                      <button style={{ ...btnPrimary, background: '#3B6D11' }}
                        onClick={saveConnector} disabled={saving}>
                        {saving ? 'Saving...' : (editingId ? 'Update connection' : 'Save connection')}
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}

            {schema?.success && (
              <div style={card}>
                <div style={sectionTitle}>{schema.table_count} tables found</div>
                <pre style={{ background: '#1e1e1e', color: '#d4d4d4', borderRadius: 6,
                  padding: '10px 14px', fontSize: 10, fontFamily: 'monospace',
                  overflowX: 'auto', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                  {schema.nlm_schema}
                </pre>
                <div style={{ fontSize: 11, color: '#888', marginTop: 8 }}>
                  Copy this text into ETL Agent → Schema field
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── View tables ── */}
        {tab === 'tables' && (
          <div>
            {!activeConn && (
              <EmptyState icon="📋" title="Select a connection"
                message='Go to "My connections" and click "View tables" on any connection.' />
            )}
            {activeConn && !tables && (
              <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
                <Spinner />
              </div>
            )}
            {tables && (
              <>
                <div style={{ fontSize: 12, color: '#888', marginBottom: 14 }}>
                  <strong>{activeConn?.name}</strong> · Click any table to preview its data
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)',
                  gap: 8, marginBottom: 16 }}>
                  <SchemaMetric label="raw"       tables={tables.schemas?.raw}       color="#185FA5" desc="Source data" />
                  <SchemaMetric label="staging"   tables={tables.schemas?.staging}   color="#854F0B" desc="Cleaned copies" />
                  <SchemaMetric label="warehouse" tables={tables.schemas?.warehouse}  color="#534AB7" desc="Dim + Fact" />
                  <SchemaMetric label="public"    tables={tables.schemas?.public}    color="#888"    desc="Other" />
                </div>
                <SchemaSection title="raw — source tables"      color="#185FA5" bg="#E6F1FB" tables={tables.schemas?.raw       || []} onPreview={(s,t) => previewTable(s,t)} emptyMsg="No tables in raw schema yet." />
                <SchemaSection title="staging — cleaned copies" color="#854F0B" bg="#FAEEDA" tables={tables.schemas?.staging   || []} onPreview={(s,t) => previewTable(s,t)} emptyMsg="No staging tables yet. Run a pipeline first." />
                <SchemaSection title="warehouse — dim and fact" color="#534AB7" bg="#EEEDFE" tables={tables.schemas?.warehouse || []} onPreview={(s,t) => previewTable(s,t)} emptyMsg="No warehouse tables yet. Run a pipeline first." />
                {tables.schemas?.public?.length > 0 && (
                  <SchemaSection title="public — other tables"  color="#888"    bg="#f3f4f6" tables={tables.schemas?.public    || []} onPreview={(s,t) => previewTable(s,t)} emptyMsg="" />
                )}
                {preview && (
                  <div style={{ ...card, marginTop: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                      <div style={sectionTitle}>{preview.table}</div>
                      <span style={{ fontSize: 11, color: '#888' }}>
                        {preview.row_count?.toLocaleString()} rows
                      </span>
                    </div>
                    <div style={{ overflowX: 'auto' }}>
                      <table style={tbl}>
                        <thead>
                          <tr>{(preview.columns||[]).map(c => <th key={c} style={th}>{c}</th>)}</tr>
                        </thead>
                        <tbody>
                          {(preview.rows||[]).map((row,i) => (
                            <tr key={i}>
                              {row.map((cell,j) => <td key={j} style={td}>{String(cell??'')}</td>)}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

      </PageBody>
    </>
  )
}

function SchemaSection({ title, color, bg, tables, onPreview, emptyMsg }) {
  const schemaName = title.split(' ')[0]
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 10, fontWeight: 600, color, textTransform: 'uppercase',
        letterSpacing: '.04em', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: color }}></div>
        {title}
      </div>
      {!tables.length ? (
        <div style={{ fontSize: 11, color: '#aaa', padding: '7px 10px',
          background: '#f9fafb', borderRadius: 6 }}>{emptyMsg}</div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {tables.map(t => (
            <button key={t.name} onClick={() => onPreview(schemaName, t.name)}
              style={{ background: bg, border: 'none', borderRadius: 6,
                padding: '6px 12px', cursor: 'pointer' }}>
              <div style={{ fontFamily: 'monospace', fontSize: 11, color, fontWeight: 500 }}>
                {t.name}
              </div>
              <div style={{ fontSize: 9, color: '#888', marginTop: 1 }}>
                {t.col_count} cols · {t.size}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function SchemaMetric({ label, tables, color, desc }) {
  return (
    <div style={{ background: '#f9fafb', borderRadius: 8, padding: '10px 12px',
      borderLeft: `3px solid ${color}` }}>
      <div style={{ fontSize: 20, fontWeight: 600, color }}>{tables?.length || 0}</div>
      <div style={{ fontSize: 10, fontWeight: 500, color, marginTop: 1 }}>{label}</div>
      <div style={{ fontSize: 9, color: '#aaa' }}>{desc}</div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: 11, fontWeight: 500,
        color: '#374151', marginBottom: 3 }}>{label}</label>
      {children}
    </div>
  )
}

const inp          = { width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box' }
const card         = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 10 }
const sectionTitle = { fontSize: 10, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }
const tbl          = { width: '100%', borderCollapse: 'collapse', fontSize: 11 }
const th           = { background: '#f9fafb', padding: '5px 8px', textAlign: 'left', fontWeight: 500, color: '#555', borderBottom: '1px solid #e5e7eb', fontSize: 10 }
const td           = { padding: '5px 8px', borderBottom: '1px solid #f3f4f6', fontFamily: 'monospace', fontSize: 10 }
const tagGreen     = { background: '#EAF3DE', color: '#3B6D11', padding: '2px 7px', borderRadius: 20, fontSize: 9, fontWeight: 500 }
const tagBlue      = { background: '#E6F1FB', color: '#185FA5', padding: '2px 7px', borderRadius: 20, fontSize: 9, fontWeight: 500 }
const btnPrimary   = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500, display: 'flex', alignItems: 'center', gap: 4 }
const btnGhost     = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnActive    = { padding: '6px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 20, fontSize: 12, cursor: 'pointer' }
