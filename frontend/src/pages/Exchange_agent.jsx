/**
 * Exchange_agent.jsx v2 — Universal Data Exchange with:
 * 1. Save Mapping + Schedule
 * 2. Column-level rename + table requirements
 * 3. Load order + dependencies
 * 4. Run selected tables only
 */
import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'

const LOAD_MODES = [
  { value: 'full',        label: 'Full Load',    desc: 'Replace all data' },
  { value: 'incremental', label: 'Incremental',  desc: 'Append new rows' },
  { value: 'upsert',      label: 'Upsert',       desc: 'Insert or update' },
]

const TABS = ['📥 Load', '🗂️ Mappings', '📜 History']

export default function ExchangeAgent() {
  const navigate  = useNavigate()
  const fileRef   = useRef(null)
  const [tab, setTab] = useState(0)

  // Connectors
  const [connectors,   setConnectors]   = useState([])
  const [targetConnId, setTargetConnId] = useState('')
  const [targetSchema, setTargetSchema] = useState('exchange')

  // Files + table configs
  const [files,        setFiles]        = useState([])  // {file, tableName, order, enabled, loadMode, requirements, columns:[]}
  const [activeFile,   setActiveFile]   = useState(null) // index of expanded file
  const [transformModal, setTransformModal] = useState(null) // {fileIdx, colIdx, value}

  // Global settings
  const [globalReq,    setGlobalReq]    = useState('')
  const [mappingName,  setMappingName]  = useState('')
  const [scheduleCron, setScheduleCron] = useState('')

  // Status
  const [loading,      setLoading]      = useState(false)
  const [status,       setStatus]       = useState(null)
  const [error,        setError]        = useState(null)
  const [result,       setResult]       = useState(null)

  // Saved mappings + history
  const [mappings,     setMappings]     = useState([])
  const [history,      setHistory]      = useState([])

  useEffect(() => {
    api.get('/connector/list').then(r => {
      const conns = r.data.connectors || []
      setConnectors(conns)
      const pg = conns.find(c => c.connector_type === 'postgres' && c.name !== 'exchange')
      if (pg) setTargetConnId(pg.id)
    }).catch(() => {})
    loadMappings()
    loadHistory()
  }, [])

  const loadMappings = () => {
    api.get('/exchange/mappings').then(r => setMappings(r.data.mappings || [])).catch(() => {})
  }

  const loadHistory = () => {
    api.get('/exchange/history').then(r => setHistory(r.data.history || [])).catch(() => {})
  }

  const runSavedMapping = async (mapping) => {
    setTab(0)
    setMappingName(mapping.name)
    setTargetSchema(mapping.target_schema || 'exchange_dwh')
    if (mapping.target_connector_id) setTargetConnId(mapping.target_connector_id)
    setStatus('Mapping loaded — please add your files and click Run Now or Save & Run')
    setError(null)
  }

  const deleteSavedMapping = async (mappingId, mappingName) => {
    if (!window.confirm('Delete mapping "' + mappingName + '"?')) return
    try {
      await api.delete('/exchange/mapping/' + mappingId)
      loadMappings()
    } catch(e) {
      alert('Could not delete mapping')
    }
  }

  // File handling
  const handleDrop = (e) => {
    e.preventDefault()
    addFiles(Array.from(e.dataTransfer.files))
  }

  const addFiles = (newFiles) => {
    const mapped = newFiles.map((f, idx) => ({
      file:         f,
      name:         f.name,
      tableName:    f.name.replace(/\.(csv|xlsx|xls|json|txt)$/i, '').toLowerCase().replace(/[^a-z0-9]/g, '_'),
      order:        files.length + idx + 1,
      enabled:      true,
      loadMode:     'full',
      requirements: '',
      rowLimit:     null,
      rowFilter:    '',
      dependsOn:    [],
      columns:      [],  // populated after preview
      preview:      null,
    }))
    setFiles(prev => [...prev, ...mapped])
  }

  const updateFile = (idx, key, val) => {
    setFiles(prev => prev.map((f, i) => i === idx ? { ...f, [key]: val } : f))
  }

  const updateColumn = (fileIdx, colIdx, key, val) => {
    setFiles(prev => prev.map((f, i) => {
      if (i !== fileIdx) return f
      const cols = f.columns.map((c, j) => j === colIdx ? { ...c, [key]: val } : c)
      return { ...f, columns: cols }
    }))
  }

  const removeFile = (idx) => {
    setFiles(prev => prev.filter((_, i) => i !== idx))
    setActiveFile(null)
  }

  const moveFile = (idx, dir) => {
    setFiles(prev => {
      const arr = [...prev]
      const swap = idx + dir
      if (swap < 0 || swap >= arr.length) return arr
      ;[arr[idx], arr[swap]] = [arr[swap], arr[idx]]
      return arr.map((f, i) => ({ ...f, order: i + 1 }))
    })
  }

  // Preview file columns
  const previewFile = async (idx) => {
    const f = files[idx]
    if (f.columns.length > 0) { setActiveFile(idx); return }
    try {
      const formData = new FormData()
      formData.append('file', f.file)
      const r = await api.post('/exchange/preview', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      if (r.data.columns) {
        const cols = r.data.columns.map(c => ({
          source: c.name, target: c.name, type: c.type,
          include: true, transformation: '', isPk: false
        }))
        updateFile(idx, 'columns', cols)
        updateFile(idx, 'preview', r.data.sample)
      }
    } catch (e) { console.log('Preview error:', e) }
    setActiveFile(activeFile === idx ? null : idx)
  }

  // Run exchange
  const runExchange = async (mappingId = null, selectedOnly = false) => {
    const enabledFiles = files.filter(f => f.enabled)
    if (enabledFiles.length === 0) { setError('No files selected to load'); return }
    if (!targetConnId) { setError('Select a target connection'); return }

    setLoading(true); setError(null); setResult(null)
    setStatus('Uploading files...')

    try {
      // Upload files and get connector IDs
      const uploadedFiles = []
      for (const f of enabledFiles) {
        setStatus(`Uploading ${f.name}...`)
        const formData = new FormData()
        formData.append('file', f.file)
        formData.append('table_name', f.tableName)
        const r = await api.post('/connector/file/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })
        if (r.data.connector_id) {
          uploadedFiles.push({
            connector_id:  r.data.connector_id,
            table_name:    f.tableName,
            file_name:     f.name,
            load_mode:     f.loadMode,
            requirements:  f.requirements || globalReq,
            row_limit:     f.rowLimit,
            row_filter:    f.rowFilter,
            depends_on:    f.dependsOn,
            columns:       f.columns.filter(c => c.include).map(c => ({
              source: c.source, target: c.target,
              transformation: c.transformation
            })),
          })
        }
      }

      setStatus(`Running exchange for ${uploadedFiles.length} tables...`)

      const r = await api.post('/exchange/run', {
        source_files:        uploadedFiles,
        target_connector_id: targetConnId,
        target_schema:       targetSchema,
        load_mode:           'full',
        requirements:        globalReq,
        mapping_name:        mappingName,
        schedule_cron:       scheduleCron,
      })

      if (r.data.success) {
        setResult(r.data)
        setStatus('✅ Exchange complete!')
        loadMappings()
        loadHistory()
      } else {
        setError(r.data.error || 'Exchange failed')
      }
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    }
    setLoading(false)
  }

  const dbConnectors = connectors.filter(c => !['csv','excel','duckdb'].includes(c.connector_type))

  const card = { border:'1px solid #E5E7EB', borderRadius:10, padding:'14px 16px', marginBottom:12, background:'#fff' }
  const lbl  = { display:'block', fontSize:10, fontWeight:700, color:'#6B7280', marginBottom:4, textTransform:'uppercase', letterSpacing:'0.04em' }
  const inp  = { width:'100%', padding:'7px 10px', fontSize:12, border:'1px solid #D1D5DB', borderRadius:6, boxSizing:'border-box' }

  return (
    <>
      <PageHeader title="🔄 Exchange Agent"
        subtitle="Load files into any database — with column mapping, load order & scheduling" />
      <PageBody>

        {/* Tabs */}
        <div style={{ display:'flex', gap:4, marginBottom:16, borderBottom:'1px solid #E5E7EB', paddingBottom:0 }}>
          {TABS.map((t,i) => (
            <button key={i} onClick={() => setTab(i)} style={{
              padding:'8px 16px', border:'none', borderBottom: tab===i ? '2px solid #185FA5' : '2px solid transparent',
              background:'none', cursor:'pointer', fontSize:12, fontWeight: tab===i ? 700 : 400,
              color: tab===i ? '#185FA5' : '#6B7280',
            }}>{t}</button>
          ))}
        </div>

        {/* ── TAB 0: LOAD ── */}
        {tab === 0 && (
          <div>
            {/* File Drop Zone */}
            <div style={card}>
              <div style={{ fontSize:10, fontWeight:700, color:'#6B7280', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>
                📥 Source Files
              </div>
              <div
                onDrop={handleDrop} onDragOver={e => e.preventDefault()}
                onClick={() => fileRef.current?.click()}
                style={{ border:'2px dashed #BFDBFE', borderRadius:10, padding:'20px',
                  textAlign:'center', cursor:'pointer', background:'#F0F9FF', marginBottom:12 }}>
                <div style={{ fontSize:28, marginBottom:6 }}>📁</div>
                <div style={{ fontSize:13, fontWeight:600, color:'#185FA5' }}>Drop files or click to browse</div>
                <div style={{ fontSize:11, color:'#9CA3AF', marginTop:4 }}>CSV, Excel, JSON, TXT — multiple files</div>
                <input ref={fileRef} type="file" multiple accept=".csv,.xlsx,.xls,.json,.txt"
                  style={{ display:'none' }} onChange={e => addFiles(Array.from(e.target.files))} />
              </div>

              {/* File list with order controls */}
              {files.length > 0 && (
                <div>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
                    <div style={{ fontSize:10, fontWeight:700, color:'#6B7280', textTransform:'uppercase' }}>
                      {files.length} files — drag to reorder, configure each table
                    </div>
                    <button onClick={() => setFiles(prev => prev.map(f => ({ ...f, enabled: true })))}
                      style={{ fontSize:10, padding:'2px 8px', border:'1px solid #D1D5DB',
                        borderRadius:6, background:'#fff', cursor:'pointer', color:'#6B7280' }}>
                      Select All
                    </button>
                  </div>

                  {files.map((f, i) => (
                    <div key={i} style={{ marginBottom:8 }}>
                      {/* File row */}
                      <div style={{
                        display:'flex', alignItems:'center', gap:8, padding:'10px 12px',
                        background: f.enabled ? '#F9FAFB' : '#FFF5F5',
                        borderRadius:activeFile===i ? '8px 8px 0 0' : 8,
                        border: `1px solid ${activeFile===i ? '#185FA5' : '#E5E7EB'}`,
                        borderBottom: activeFile===i ? 'none' : undefined,
                      }}>
                        {/* Order number */}
                        <div style={{ fontSize:11, fontWeight:700, color:'#9CA3AF',
                          width:20, textAlign:'center' }}>{i+1}</div>

                        {/* Enable toggle */}
                        <input type="checkbox" checked={f.enabled}
                          onChange={() => updateFile(i, 'enabled', !f.enabled)}
                          style={{ width:14, height:14, cursor:'pointer' }} />

                        {/* File icon */}
                        <span style={{ fontSize:16 }}>
                          {f.name.endsWith('.xlsx') || f.name.endsWith('.xls') ? '📊' : '📄'}
                        </span>

                        {/* File name */}
                        <div style={{ fontSize:11, color:'#6B7280', minWidth:120,
                          overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                          {f.name}
                        </div>

                        {/* Arrow */}
                        <span style={{ fontSize:12, color:'#9CA3AF' }}>{'→'}</span>

                        {/* Target table name */}
                        <input value={f.tableName}
                          onChange={e => updateFile(i, 'tableName', e.target.value)}
                          style={{ fontSize:11, padding:'3px 8px', border:'1px solid #D1D5DB',
                            borderRadius:5, flex:1, fontFamily:'monospace',
                            background: f.enabled ? '#fff' : '#FFF5F5' }} />

                        {/* Load mode */}
                        <select value={f.loadMode} onChange={e => updateFile(i, 'loadMode', e.target.value)}
                          style={{ fontSize:10, padding:'3px 6px', border:'1px solid #D1D5DB',
                            borderRadius:5, background:'#fff', cursor:'pointer' }}>
                          {LOAD_MODES.map(m => (
                            <option key={m.value} value={m.value}>{m.label}</option>
                          ))}
                        </select>

                        {/* Order controls */}
                        <div style={{ display:'flex', gap:2 }}>
                          <button onClick={() => moveFile(i, -1)} disabled={i===0}
                            style={{ fontSize:10, padding:'2px 5px', border:'1px solid #E5E7EB',
                              borderRadius:4, background:'#fff', cursor:'pointer',
                              opacity: i===0 ? 0.3 : 1 }}>↑</button>
                          <button onClick={() => moveFile(i, 1)} disabled={i===files.length-1}
                            style={{ fontSize:10, padding:'2px 5px', border:'1px solid #E5E7EB',
                              borderRadius:4, background:'#fff', cursor:'pointer',
                              opacity: i===files.length-1 ? 0.3 : 1 }}>↓</button>
                        </div>

                        {/* Configure button */}
                        <button onClick={() => previewFile(i)}
                          style={{ fontSize:10, padding:'3px 8px', border:'1px solid #185FA5',
                            borderRadius:5, background: activeFile===i ? '#185FA5' : '#fff',
                            color: activeFile===i ? '#fff' : '#185FA5',
                            cursor:'pointer', whiteSpace:'nowrap' }}>
                          {activeFile===i ? '▼ Config' : '▶ Config'}
                        </button>

                        {/* Remove */}
                        <button onClick={() => removeFile(i)}
                          style={{ background:'none', border:'none', cursor:'pointer',
                            color:'#EF4444', fontSize:16, padding:0, lineHeight:1 }}>✕</button>
                      </div>

                      {/* Expanded config panel */}
                      {activeFile === i && (
                        <div style={{ border:'1px solid #185FA5', borderTop:'none',
                          borderRadius:'0 0 8px 8px', padding:'14px', background:'#FAFCFF' }}>

                          {/* Table requirements */}
                          <div style={{ marginBottom:12 }}>
                            <label style={lbl}>Table Requirements (natural language)</label>
                            <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:6 }}>
                              {[
                                '1:1 direct load',
                                'Remove duplicates',
                                'Sample 100 rows only',
                                'Standardize dates to YYYY-MM-DD',
                                'Trim whitespace',
                              ].map((t,j) => (
                                <button key={j} onClick={() => updateFile(i, 'requirements', t)}
                                  style={{ fontSize:10, padding:'2px 8px', borderRadius:10,
                                    border:'1px solid #D1D5DB', background:'#F9FAFB',
                                    cursor:'pointer', color:'#6B7280' }}>{t}</button>
                              ))}
                            </div>
                            <textarea value={f.requirements}
                              onChange={e => updateFile(i, 'requirements', e.target.value)}
                              style={{ ...inp, minHeight:50, resize:'vertical', fontFamily:'system-ui' }}
                              placeholder="e.g. Only load records from last 6 months, remove test accounts..." />
                          </div>

                          {/* Row filter + limit */}
                          <div style={{ display:'grid', gridTemplateColumns:'1fr 120px', gap:10, marginBottom:12 }}>
                            <div>
                              <label style={lbl}>Row Filter (WHERE clause)</label>
                              <input style={inp} value={f.rowFilter}
                                onChange={e => updateFile(i, 'rowFilter', e.target.value)}
                                placeholder='e.g. status != "test" AND date > "2024-01-01"' />
                            </div>
                            <div>
                              <label style={lbl}>Row Limit</label>
                              <input style={inp} type="number" value={f.rowLimit || ''}
                                onChange={e => updateFile(i, 'rowLimit', e.target.value ? parseInt(e.target.value) : null)}
                                placeholder="All rows" />
                            </div>
                          </div>

                          {/* Depends on */}
                          <div style={{ marginBottom:12 }}>
                            <label style={lbl}>Depends On (load after these tables)</label>
                            <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
                              {files.filter((_, j) => j !== i).map((of, j) => (
                                <label key={j} style={{ display:'flex', alignItems:'center', gap:4,
                                  fontSize:11, cursor:'pointer' }}>
                                  <input type="checkbox"
                                    checked={f.dependsOn.includes(of.tableName)}
                                    onChange={() => {
                                      const deps = f.dependsOn.includes(of.tableName)
                                        ? f.dependsOn.filter(d => d !== of.tableName)
                                        : [...f.dependsOn, of.tableName]
                                      updateFile(i, 'dependsOn', deps)
                                    }} />
                                  {of.tableName}
                                </label>
                              ))}
                              {files.filter((_, j) => j !== i).length === 0 && (
                                <span style={{ fontSize:11, color:'#9CA3AF' }}>Add more files to set dependencies</span>
                              )}
                            </div>
                          </div>

                          {/* Column mapping */}
                          {f.columns.length > 0 && (
                            <div>
                              <div style={{ display:'flex', justifyContent:'space-between', marginBottom:8 }}>
                                <label style={lbl}>Column Mapping</label>
                                <div style={{ display:'flex', gap:6 }}>
                                  <button onClick={() => {
                                    f.columns.forEach((_, j) => updateColumn(i, j, 'include', true))
                                  }} style={{ fontSize:10, padding:'2px 8px', border:'1px solid #D1D5DB',
                                    borderRadius:5, background:'#fff', cursor:'pointer', color:'#15803D' }}>
                                    Include All
                                  </button>
                                  <button onClick={() => {
                                    f.columns.forEach((_, j) => updateColumn(i, j, 'include', false))
                                  }} style={{ fontSize:10, padding:'2px 8px', border:'1px solid #D1D5DB',
                                    borderRadius:5, background:'#fff', cursor:'pointer', color:'#DC2626' }}>
                                    Exclude All
                                  </button>
                                </div>
                              </div>
                              <div style={{ maxHeight:200, overflowY:'auto' }}>
                                {/* Header */}
                                <div style={{ display:'grid', gridTemplateColumns:'30px 1fr 1fr 100px 80px',
                                  gap:6, fontSize:9, fontWeight:700, color:'#9CA3AF',
                                  textTransform:'uppercase', marginBottom:4, padding:'0 4px' }}>
                                  <span>✓</span><span>Source Column</span>
                                  <span>Target Column</span><span>Transform</span><span>Type</span>
                                </div>
                                {f.columns.map((col, j) => (
                                  <div key={j} style={{ display:'grid',
                                    gridTemplateColumns:'30px 1fr 1fr 100px 80px',
                                    gap:6, marginBottom:4, alignItems:'center',
                                    opacity: col.include ? 1 : 0.4 }}>
                                    <input type="checkbox" checked={col.include}
                                      onChange={() => updateColumn(i, j, 'include', !col.include)}
                                      style={{ width:14, height:14 }} />
                                    <div style={{ fontSize:11, fontFamily:'monospace',
                                      color:'#6B7280', padding:'3px 0',
                                      overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                                      {col.source}
                                    </div>
                                    <input value={col.target}
                                      onChange={e => updateColumn(i, j, 'target', e.target.value)}
                                      disabled={!col.include}
                                      style={{ fontSize:11, padding:'3px 6px', border:'1px solid #D1D5DB',
                                        borderRadius:4, fontFamily:'monospace' }} />
                                    <div onClick={() => col.include && setTransformModal({fileIdx:i, colIdx:j, value: col.transformation || ''})}
                                      style={{ fontSize:10, padding:'3px 6px', border:'1px solid #D1D5DB',
                                        borderRadius:4, cursor: col.include ? 'pointer' : 'default',
                                        color: col.transformation ? '#185FA5' : '#9CA3AF',
                                        background: col.include ? '#fff' : '#F9FAFB',
                                        minHeight:24, display:'flex', alignItems:'center' }}>
                                      {col.transformation ? col.transformation.slice(0,20) + (col.transformation.length>20?'...':'') : '+ Add transform'}
                                    </div>
                                    <div style={{ fontSize:10, color:'#9CA3AF' }}>{col.type}</div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {f.columns.length === 0 && (
                            <div style={{ fontSize:11, color:'#9CA3AF', textAlign:'center', padding:'10px 0' }}>
                              Click Configure to load column mapping
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Target + Settings */}
            {files.length > 0 && (
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:12 }}>
                {/* Target */}
                <div style={card}>
                  <div style={{ fontSize:10, fontWeight:700, color:'#6B7280',
                    textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>
                    📤 Target Database
                  </div>
                  <label style={lbl}>Connection</label>
                  <select style={{ ...inp, marginBottom:10 }} value={targetConnId}
                    onChange={e => setTargetConnId(e.target.value)}>
                    <option value="">Select connection...</option>
                    {dbConnectors.map(c => (
                      <option key={c.id} value={c.id}>{c.name} — {c.database_name}</option>
                    ))}
                  </select>
                  <label style={lbl}>Target Schema</label>
                  <input style={inp} value={targetSchema}
                    onChange={e => setTargetSchema(e.target.value)}
                    placeholder="e.g. exchange, suitecrm_dwh" />
                </div>

                {/* Save + Schedule */}
                <div style={card}>
                  <div style={{ fontSize:10, fontWeight:700, color:'#6B7280',
                    textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>
                    💾 Save Mapping
                  </div>
                  <label style={lbl}>Mapping Name</label>
                  <input style={{ ...inp, marginBottom:10 }} value={mappingName}
                    onChange={e => setMappingName(e.target.value)}
                    placeholder="e.g. SuiteCRM Daily Load" autoComplete="off" />
                  <label style={lbl}>Schedule (Cron)</label>
                  <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:6 }}>
                    {[
                      { label:'Daily 6AM',  cron:'0 6 * * *' },
                      { label:'Weekly Mon', cron:'0 6 * * 1' },
                      { label:'Hourly',     cron:'0 * * * *' },
                      { label:'Manual',     cron:'' },
                    ].map((s, j) => (
                      <button key={j} onClick={() => setScheduleCron(s.cron)}
                        style={{ fontSize:10, padding:'2px 8px', borderRadius:10,
                          border:`1px solid ${scheduleCron===s.cron ? '#185FA5' : '#D1D5DB'}`,
                          background: scheduleCron===s.cron ? '#EBF4FF' : '#F9FAFB',
                          color: scheduleCron===s.cron ? '#185FA5' : '#6B7280',
                          cursor:'pointer' }}>{s.label}</button>
                    ))}
                  </div>
                  <input style={inp} value={scheduleCron}
                    onChange={e => setScheduleCron(e.target.value)}
                    placeholder="0 6 * * * (or leave empty for manual)" />
                </div>
              </div>
            )}

            {/* Global Requirements */}
            {files.length > 0 && (
              <div style={card}>
                <div style={{ fontSize:10, fontWeight:700, color:'#6B7280',
                  textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:8 }}>
                  🧠 Global Requirements
                </div>
                <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:8 }}>
                  {[
                    { label:'1:1 Load',         text:'Load each file as-is into its own table. Direct one-to-one mapping.' },
                    { label:'Sample 100 rows',  text:'Load only first 100 rows from each file for testing.' },
                    { label:'Build Warehouse',  text:'Detect relationships, build star schema with fact and dimension tables.' },
                    { label:'CRM Analytics',    text:'CRM data. Build analytics: lead conversion, pipeline by stage, inactive accounts, sales performance.' },
                    { label:'Clean & Load',     text:'Remove duplicates, fix nulls, standardize dates, trim whitespace before loading.' },
                  ].map((t, j) => (
                    <button key={j} onClick={() => setGlobalReq(t.text)}
                      style={{ fontSize:10, padding:'3px 10px', borderRadius:10, cursor:'pointer',
                        border:`1px solid ${globalReq===t.text ? '#185FA5' : '#D1D5DB'}`,
                        background: globalReq===t.text ? '#EBF4FF' : '#F9FAFB',
                        color: globalReq===t.text ? '#185FA5' : '#6B7280',
                        fontWeight: globalReq===t.text ? 600 : 400 }}>{t.label}</button>
                  ))}
                </div>
                <textarea style={{ ...inp, minHeight:60, resize:'vertical', fontFamily:'system-ui' }}
                  value={globalReq} onChange={e => setGlobalReq(e.target.value)}
                  placeholder="Global requirements that apply to all files..." />
              </div>
            )}

            {/* Run Summary */}
            {files.length > 0 && (
              <div style={{ ...card, background:'#F0FDF4', borderColor:'#BBF7D0' }}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                  <div>
                    <div style={{ fontSize:13, fontWeight:600, color:'#15803D', marginBottom:4 }}>
                      Load Summary
                    </div>
                    <div style={{ fontSize:12, color:'#374151' }}>
                      <strong>{files.filter(f=>f.enabled).length}</strong> of {files.length} files selected
                      {' → '}
                      <strong>{dbConnectors.find(c=>c.id===targetConnId)?.name || '?'}.{targetSchema}</strong>
                    </div>
                    {/* Load order preview */}
                    <div style={{ display:'flex', gap:4, flexWrap:'wrap', marginTop:8 }}>
                      {files.filter(f=>f.enabled).map((f, i) => (
                        <div key={i} style={{ display:'flex', alignItems:'center', gap:3 }}>
                          {i > 0 && <span style={{ fontSize:10, color:'#9CA3AF' }}>{'→'}</span>}
                          <span style={{ fontSize:10, padding:'2px 8px', borderRadius:10,
                            background:'#DCFCE7', color:'#15803D', border:'1px solid #BBF7D0' }}>
                            {i+1}. {f.tableName}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                    <button style={{
                      padding:'10px 22px', background: loading ? '#9CA3AF' : '#15803D',
                      color:'#fff', border:'none', borderRadius:8, fontSize:13,
                      cursor: loading ? 'not-allowed' : 'pointer', fontWeight:700,
                    }} onClick={() => runExchange()} disabled={loading}>
                      {loading ? '⏳ Loading...' : '🚀 Run Now'}
                    </button>
                    <button style={{
                      padding:'8px 16px', background:'#fff', color:'#15803D',
                      border:'1px solid #15803D', borderRadius:8, fontSize:12,
                      cursor: loading || !mappingName ? 'not-allowed' : 'pointer', fontWeight:600,
                      opacity: mappingName ? 1 : 0.4,
                    }} onClick={() => mappingName && runExchange()} disabled={loading || !mappingName}
                      title={!mappingName ? 'Enter a mapping name above to save' : 'Save mapping and run'}>
                      💾 Save & Run
                    </button>
                    <button style={{
                      padding:'8px 16px', background:'#fff', color:'#185FA5',
                      border:'1px solid #185FA5', borderRadius:8, fontSize:12,
                      cursor: loading || !mappingName ? 'not-allowed' : 'pointer', fontWeight:600,
                      opacity: mappingName ? 1 : 0.4,
                    }} onClick={() => mappingName && runExchange()} disabled={loading || !mappingName}
                      title={!mappingName ? 'Enter a mapping name to save without running' : 'Save mapping only'}>
                      💾 Save Only
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Status */}
            {status && !error && (
              <div style={{ ...card, background:'#EBF4FF', borderColor:'#BFDBFE' }}>
                <div style={{ fontSize:13, color:'#185FA5' }}>
                  {loading ? '⏳ ' : '✅ '}{status}
                </div>
              </div>
            )}
            {error && (
              <div style={{ ...card, background:'#FEF2F2', borderColor:'#FCA5A5' }}>
                <div style={{ fontSize:13, color:'#991B1B' }}>❌ {error}</div>
              </div>
            )}

            {/* Result */}
            {result && (
              <div style={card}>
                <div style={{ fontSize:13, fontWeight:700, color:'#15803D', marginBottom:12 }}>
                  ✅ Exchange Complete
                </div>
                <div style={{ display:'flex', gap:12, marginBottom:14 }}>
                  {[
                    { val: result.tables_loaded, label:'Tables', color:'#185FA5' },
                    { val: result.total_rows,    label:'Rows',   color:'#15803D' },
                    { val: result.duration,      label:'Time',   color:'#854F0B' },
                  ].map((s,i) => (
                    <div key={i} style={{ background:'#F9FAFB', border:'1px solid #E5E7EB',
                      borderRadius:8, padding:'10px 16px', textAlign:'center' }}>
                      <div style={{ fontSize:20, fontWeight:700, color:s.color }}>{s.val}</div>
                      <div style={{ fontSize:10, color:'#9CA3AF', textTransform:'uppercase' }}>{s.label}</div>
                    </div>
                  ))}
                </div>
                <div style={{ display:'flex', gap:10 }}>
                  <button style={{ padding:'8px 16px', background:'#185FA5', color:'#fff',
                    border:'none', borderRadius:6, fontSize:12, cursor:'pointer', fontWeight:600 }}
                    onClick={() => navigate('/analytics')}>
                    📊 Go to Analytics →
                  </button>
                  <button style={{ padding:'8px 14px', background:'#fff', color:'#185FA5',
                    border:'1px solid #185FA5', borderRadius:6, fontSize:12, cursor:'pointer' }}
                    onClick={() => navigate('/plug-and-play')}>
                    🔌 Explore Data →
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── TAB 1: SAVED MAPPINGS ── */}
        {tab === 1 && (
          <div>
            {mappings.length === 0 ? (
              <div style={{ ...card, textAlign:'center', padding:'40px' }}>
                <div style={{ fontSize:32, marginBottom:12 }}>🗂️</div>
                <div style={{ fontSize:14, fontWeight:600, color:'#374151', marginBottom:6 }}>
                  No saved mappings yet
                </div>
                <div style={{ fontSize:12, color:'#9CA3AF' }}>
                  Run an exchange with a mapping name to save it here
                </div>
              </div>
            ) : (
              mappings.map((m, i) => (
                <div key={i} style={card}>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                    <div>
                      <div style={{ fontSize:13, fontWeight:600, color:'#111', marginBottom:4 }}>
                        {m.name}
                      </div>
                      <div style={{ fontSize:11, color:'#6B7280' }}>
                        {m.table_count} tables · {m.target_schema} ·{' '}
                        {m.schedule_cron ? `⏰ ${m.schedule_cron}` : 'Manual'}
                      </div>
                      {m.last_run_at && (
                        <div style={{ fontSize:10, color:'#9CA3AF', marginTop:4 }}>
                          Last run: {new Date(m.last_run_at).toLocaleString()} — {m.last_run_status}
                        </div>
                      )}
                    </div>
                    <div style={{ display:'flex', gap:8 }}>
                      <button onClick={() => runSavedMapping(m)}
                        style={{ padding:'6px 14px', background:'#15803D', color:'#fff',
                        border:'none', borderRadius:6, fontSize:11, cursor:'pointer', fontWeight:600 }}>
                        ▶ Load & Run
                      </button>
                      <button onClick={() => { setMappingName(m.name); setTargetSchema(m.target_schema); setTab(0) }}
                        style={{ padding:'6px 12px', background:'#fff', color:'#185FA5',
                        border:'1px solid #185FA5', borderRadius:6, fontSize:11, cursor:'pointer' }}>
                        ✎ Edit
                      </button>
                      <button onClick={() => deleteSavedMapping(m.id, m.name)}
                        style={{ padding:'6px 10px', background:'#fff', color:'#DC2626',
                        border:'1px solid #DC2626', borderRadius:6, fontSize:11, cursor:'pointer' }}>
                        🗑
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* ── TAB 2: HISTORY ── */}
        {tab === 2 && (
          <div>
            {history.length === 0 ? (
              <div style={{ ...card, textAlign:'center', padding:'40px' }}>
                <div style={{ fontSize:32, marginBottom:12 }}>📜</div>
                <div style={{ fontSize:14, fontWeight:600, color:'#374151' }}>No run history yet</div>
              </div>
            ) : (
              history.map((h, i) => (
                <div key={i} style={card}>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                    <div>
                      <div style={{ fontSize:12, fontWeight:600, color:'#111', marginBottom:4 }}>
                        {h.mapping_name || 'Manual Run'}
                      </div>
                      <div style={{ fontSize:11, color:'#6B7280' }}>
                        {h.tables_loaded} tables · {h.total_rows} rows · {h.duration}
                      </div>
                      <div style={{ fontSize:10, color:'#9CA3AF', marginTop:4 }}>
                        {new Date(h.started_at).toLocaleString()}
                      </div>
                    </div>
                    <div style={{
                      padding:'4px 12px', borderRadius:12, fontSize:11, fontWeight:600,
                      background: h.status==='success' ? '#DCFCE7' : '#FEF2F2',
                      color: h.status==='success' ? '#15803D' : '#DC2626',
                    }}>
                      {h.status === 'success' ? '✅ Success' : '❌ Failed'}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

      </PageBody>
      {/* Transform Modal */}
      {transformModal && (
        <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.5)',
          zIndex:1000, display:'flex', alignItems:'center', justifyContent:'center' }}
          onClick={() => setTransformModal(null)}>
          <div style={{ background:'#fff', borderRadius:12, padding:24, width:500,
            boxShadow:'0 20px 60px rgba(0,0,0,0.3)' }}
            onClick={e => e.stopPropagation()}>
            <div style={{ fontSize:14, fontWeight:700, color:'#111', marginBottom:4 }}>
              Column Transformation
            </div>
            <div style={{ fontSize:11, color:'#6B7280', marginBottom:16 }}>
              Column: <strong style={{fontFamily:'monospace'}}>
                {files[transformModal.fileIdx]?.columns[transformModal.colIdx]?.source}
              </strong> → <strong style={{fontFamily:'monospace'}}>
                {files[transformModal.fileIdx]?.columns[transformModal.colIdx]?.target}
              </strong>
            </div>
            {/* Quick options */}
            <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:12 }}>
              {[
                'Capitalize first letter',
                'Convert to uppercase',
                'Convert to lowercase',
                'Remove leading/trailing spaces',
                'Convert to date format YYYY-MM-DD',
                'Remove special characters',
                'Convert to integer',
                'Replace empty values with 0',
                'Combine with next column',
                'Extract year from date',
              ].map((t, j) => (
                <button key={j} onClick={() => setTransformModal(prev => ({...prev, value: t}))}
                  style={{ fontSize:10, padding:'3px 10px', borderRadius:10, cursor:'pointer',
                    border:`1px solid ${transformModal.value===t ? '#185FA5' : '#D1D5DB'}`,
                    background: transformModal.value===t ? '#EBF4FF' : '#F9FAFB',
                    color: transformModal.value===t ? '#185FA5' : '#6B7280' }}>{t}</button>
              ))}
            </div>
            <textarea
              autoFocus
              value={transformModal.value}
              onChange={e => setTransformModal(prev => ({...prev, value: e.target.value}))}
              placeholder="Describe the transformation in plain English...&#10;e.g. Combine first_name and last_name with a space&#10;e.g. Convert MM/DD/YYYY to YYYY-MM-DD&#10;e.g. Remove $ sign and convert to number"
              style={{ width:'100%', padding:'10px 12px', fontSize:12, border:'1px solid #D1D5DB',
                borderRadius:8, minHeight:100, resize:'vertical', boxSizing:'border-box',
                fontFamily:'system-ui', marginBottom:14 }} />
            <div style={{ display:'flex', gap:10, justifyContent:'flex-end' }}>
              <button onClick={() => {
                updateColumn(transformModal.fileIdx, transformModal.colIdx, 'transformation', '')
                setTransformModal(null)
              }} style={{ padding:'8px 16px', background:'#fff', color:'#6B7280',
                border:'1px solid #D1D5DB', borderRadius:6, fontSize:12, cursor:'pointer' }}>
                Clear
              </button>
              <button onClick={() => setTransformModal(null)}
                style={{ padding:'8px 16px', background:'#fff', color:'#374151',
                  border:'1px solid #D1D5DB', borderRadius:6, fontSize:12, cursor:'pointer' }}>
                Cancel
              </button>
              <button onClick={() => {
                updateColumn(transformModal.fileIdx, transformModal.colIdx, 'transformation', transformModal.value)
                setTransformModal(null)
              }} style={{ padding:'8px 20px', background:'#185FA5', color:'#fff',
                border:'none', borderRadius:6, fontSize:12, cursor:'pointer', fontWeight:600 }}>
                Apply
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}


