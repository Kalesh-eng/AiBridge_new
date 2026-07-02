/**
 * EtlAgent.jsx — v1.7.0
 *
 * v1.7.0: Background execution + live log streaming + Stop control.
 *   Execute now starts the pipeline in the background (returns instantly
 *   with a run_id) instead of blocking the request until the whole
 *   pipeline finishes. A live log panel streams progress via SSE, and a
 *   Stop button lets the user cancel a run at its next safe checkpoint
 *   instead of needing to restart the backend to interrupt a stuck run.
 *
 * v1.6.0: Three new features:
 *   Feature 1 — Smart Table Selection: AI recommends tables from large schemas
 *   Feature 2 — Smart Mode toggle: disable profiling on re-runs to save AI cost
 *   Feature 3 — Edit Pipeline SQL: edit saved pipeline scripts after save
 *
 * v1.5.1: Fixed missing closing tags in SchemaCombobox.
 * v1.5: Schema combobox + table/column search + auto-expand on match
 * v1.4: Column picker, target picker, custom schemas
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'

const STEPS = [
  'Requirements', 'AI designs model', '⏸ Review model',
  'AI generates SQL', '⏸ Review SQL', 'Save & execute'
]

const PII_HINTS = ['pan','aadhaar','aadhar','ssn','passport','password','pwd',
                   'email','phone','mobile','dob','date_of_birth','salary',
                   'account_number','card','cvv','ifsc','credit']

const isPII = (col) => {
  const c = String(col).toLowerCase()
  return PII_HINTS.some(h => c.includes(h))
}

function formatError(e) {
  if (!e) return 'Unknown error'
  if (typeof e === 'string') return e
  if (e.response?.data?.detail) {
    const detail = e.response.data.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(d => typeof d === 'string' ? d : (d.msg ? `${(d.loc||[]).join('.')}: ${d.msg}` : JSON.stringify(d))).join(' | ')
    if (typeof detail === 'object') return JSON.stringify(detail)
  }
  if (e.message) return e.message
  return JSON.stringify(e)
}

// ── Schema Combobox ──────────────────────────────────────────────────────────
function SchemaCombobox({ value, onChange, schemas, loading, onRefresh, placeholder }) {
  const [open, setOpen] = useState(false)
  const filtered = (schemas || []).filter(s => s.toLowerCase().includes(String(value || '').toLowerCase()))
  const isExisting = (schemas || []).includes(value)
  return (
    <div style={{ position: 'relative' }}>
      <div style={{ display: 'flex', gap: 6 }}>
        <input style={{ ...inp, flex: 1 }} value={value} placeholder={placeholder}
          onChange={e => { onChange(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 200)} />
        <button style={{ ...btnGhost, whiteSpace: 'nowrap' }} onClick={onRefresh} disabled={loading}>
          {loading ? '⏳' : '🔄'}
        </button>
      </div>
      {value && (
        <div style={{ fontSize: 9, marginTop: 3, color: isExisting ? '#3B6D11' : '#185FA5' }}>
          {isExisting ? '✓ existing schema' : '✨ will be created'}
        </div>
      )}
      {open && (
        <div style={{ position: 'absolute', top: 'calc(100% + 2px)', left: 0, right: 0,
          background: '#fff', border: '1px solid #d1d5db', borderRadius: 6,
          maxHeight: 200, overflowY: 'auto', zIndex: 100, boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}>
          <div style={{ padding: '5px 10px', fontSize: 9, color: '#888', borderBottom: '1px solid #f3f4f6', background: '#f9fafb' }}>
            EXISTING SCHEMAS — click to use, or type a new name
          </div>
          {filtered.length === 0 ? (
            <div style={{ padding: '8px 10px', fontSize: 11, color: '#aaa' }}>
              {loading ? '⏳ Loading...' : `"${value}" — will be created as new schema`}
            </div>
          ) : filtered.map(s => (
            <div key={s} onMouseDown={() => { onChange(s); setOpen(false) }}
              style={{ padding: '6px 10px', fontSize: 11, fontFamily: 'monospace', cursor: 'pointer',
                borderBottom: '1px solid #f3f4f6', background: s === value ? '#E6F1FB' : 'transparent' }}>
              {s}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Feature 1: Smart Table Selection ─────────────────────────────────────────
function SmartTableSelector({ connectorId, availableTables, sourceTables, setSourceTables, onDone }) {
  const [loading, setLoading]   = useState(false)
  const [recs, setRecs]         = useState(null)
  const [error, setError]       = useState(null)
  const [localSel, setLocalSel] = useState(new Set(sourceTables))

  const analyze = async () => {
    setLoading(true); setError(null)
    try {
      const res = await api.post(`/connector/${connectorId}/recommend-tables`, {
        table_names: availableTables
      })
      setRecs(res.data)
      const recommended = new Set(res.data.recommended || [])
      setLocalSel(recommended)
    } catch (e) {
      setError(formatError(e))
    }
    setLoading(false)
  }

  useEffect(() => { if (availableTables.length > 0) analyze() }, [])

  const toggle = (t) => {
    setLocalSel(prev => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t); else next.add(t)
      return next
    })
  }

  const confirm = () => {
    setSourceTables([...localSel])
    onDone()
  }

  if (loading) return (
    <div style={{ textAlign: 'center', padding: '30px 0' }}>
      <div style={{ fontSize: 20, marginBottom: 8 }}>🤖</div>
      <div style={{ fontSize: 13, color: '#185FA5', fontWeight: 500 }}>
        AI is analysing {availableTables.length} tables...
      </div>
      <div style={{ fontSize: 11, color: '#aaa', marginTop: 4 }}>Takes a few seconds</div>
    </div>
  )

  if (error) return (
    <div>
      <div style={errBox}>{error}</div>
      <button style={btnGhost} onClick={analyze}>Retry</button>
      <button style={{ ...btnGhost, marginLeft: 8 }} onClick={onDone}>Skip — select manually</button>
    </div>
  )

  if (!recs) return null

  const categories = [
    { key: 'recommended', label: '✅ Recommended', color: '#3B6D11', bg: '#EAF3DE', desc: 'Core business tables — include these' },
    { key: 'optional',    label: '⚠️ Optional',     color: '#854F0B', bg: '#FAEEDA', desc: 'May add value depending on your goals' },
    { key: 'excluded',    label: '❌ Excluded',     color: '#A32D2D', bg: '#FCEBEB', desc: 'System/temp tables — likely not needed' },
  ]

  return (
    <div>
      <div style={{ background: '#E6F1FB', border: '2px solid #185FA5', borderRadius: 8, padding: '12px 14px', marginBottom: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#185FA5', marginBottom: 4 }}>
          🤖 AI analysed {availableTables.length} tables
        </div>
        <div style={{ fontSize: 11, color: '#185FA5' }}>
          Recommended {(recs.recommended || []).length} tables for your warehouse.
          Review and adjust below.
        </div>
      </div>

      {categories.map(cat => {
        const tables = recs[cat.key] || []
        if (tables.length === 0) return null
        return (
          <div key={cat.key} style={{ ...card, borderLeft: `3px solid ${cat.color}`, marginBottom: 8 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: cat.color, marginBottom: 6 }}>
              {cat.label} ({tables.length} tables)
              <span style={{ fontSize: 10, fontWeight: 400, color: '#888', marginLeft: 8 }}>{cat.desc}</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {tables.map(t => {
                const selected = localSel.has(t)
                const reason   = recs.reasons?.[t] || ''
                return (
                  <label key={t} title={reason}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
                      background: selected ? cat.bg : '#f9fafb',
                      border: `1px solid ${selected ? cat.color : '#e5e7eb'}`,
                      borderRadius: 6, padding: '4px 10px', fontSize: 11 }}>
                    <input type="checkbox" checked={selected} onChange={() => toggle(t)} />
                    <span style={{ fontFamily: 'monospace', color: selected ? cat.color : '#888' }}>{t}</span>
                    {reason && <span style={{ fontSize: 9, color: '#aaa' }}>ⓘ</span>}
                  </label>
                )
              })}
            </div>
          </div>
        )
      })}

      <div style={{ display: 'flex', gap: 8, marginTop: 14, alignItems: 'center' }}>
        <button style={{ ...btnPrimary, background: '#3B6D11', borderColor: '#3B6D11' }} onClick={confirm}>
          ✓ Use {localSel.size} selected tables
        </button>
        <button style={btnGhost} onClick={() => { setLocalSel(new Set(availableTables)); onDone() }}>
          Select all {availableTables.length} tables manually
        </button>
        <span style={{ fontSize: 10, color: '#aaa' }}>Tip: hover table name to see AI reasoning</span>
      </div>
    </div>
  )
}

// ── Feature 3: Edit Pipeline SQL (shown on Pipelines page via prop) ──────────
export function EditPipelineSQL({ pipeline, onClose, onSaved }) {
  const [scripts, setScripts] = useState(
    (pipeline?.artifacts?.sql_scripts?.scripts || []).map(s => ({ ...s }))
  )
  const [activeIdx, setActiveIdx] = useState(0)
  const [saving, setSaving]       = useState(false)
  const [saved,  setSaved]        = useState(false)
  const [error,  setError]        = useState(null)

  const updateScript = (idx, newSql) => {
    const updated = [...scripts]
    updated[idx]  = { ...updated[idx], sql: newSql }
    setScripts(updated)
    setSaved(false)
  }

  const save = async () => {
    setSaving(true); setError(null)
    try {
      const newArtifacts = {
        ...pipeline.artifacts,
        sql_scripts: { scripts }
      }
      await api.post(`/pipeline/update-artifacts/${pipeline.id}`, { artifacts: newArtifacts })
      setSaved(true)
      if (onSaved) onSaved(newArtifacts)
    } catch (e) {
      setError(formatError(e))
    }
    setSaving(false)
  }

  const active = scripts[activeIdx]

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: '#fff', borderRadius: 12, width: '90vw', maxWidth: 900, maxHeight: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>✎ Edit Pipeline SQL</div>
            <div style={{ fontSize: 11, color: '#888' }}>{pipeline.name} — {scripts.length} scripts</div>
          </div>
          <button style={btnGhost} onClick={onClose}>✕ Close</button>
        </div>

        <div style={{ padding: '10px 18px', borderBottom: '1px solid #f3f4f6', display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {scripts.map((s, i) => (
            <button key={i} onClick={() => setActiveIdx(i)}
              style={{ padding: '4px 12px', background: i === activeIdx ? '#185FA5' : '#fff',
                color: i === activeIdx ? '#fff' : '#555',
                border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }}>
              {s.name || `script_${i + 1}`}
            </button>
          ))}
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: '12px 18px' }}>
          {active && (
            <>
              <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
                <strong>{active.name}</strong> — {active.label || ''}
              </div>
              <div style={{ fontSize: 10, color: '#aaa', marginBottom: 6 }}>
                💡 Edit SQL directly. Changes are saved to the pipeline — next execution uses updated SQL.
              </div>
              <textarea
                style={{ width: '100%', minHeight: 350, fontFamily: 'monospace', fontSize: 11,
                  background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6,
                  border: '1px solid #555', boxSizing: 'border-box', resize: 'vertical' }}
                value={active.sql || ''}
                onChange={e => updateScript(activeIdx, e.target.value)}
              />
            </>
          )}
        </div>

        <div style={{ padding: '12px 18px', borderTop: '1px solid #e5e7eb', display: 'flex', gap: 8, alignItems: 'center' }}>
          {error && <span style={{ fontSize: 11, color: '#991b1b' }}>{error}</span>}
          {saved && <span style={{ fontSize: 11, color: '#3B6D11' }}>✓ Saved — next execution uses updated SQL</span>}
          <div style={{ flex: 1 }} />
          <button style={btnGhost} onClick={onClose}>Cancel</button>
          <button style={{ ...btnPrimary, background: '#3B6D11', borderColor: '#3B6D11' }}
            onClick={save} disabled={saving}>
            {saving ? 'Saving...' : '💾 Save SQL changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Feature: Live execution log panel with Stop control ──────────────────────
function LiveExecutionPanel({ runId, onFinished }) {
  const [lines, setLines]   = useState([])
  const [status, setStatus] = useState('running')
  const [stopRequested, setStopRequested] = useState(false)
  const logBoxRef  = useRef(null)
  const autoScroll = useRef(true)

  useEffect(() => {
    if (!runId) return
    const base = api.defaults?.baseURL || ''
    const es = new EventSource(`${base}/pipeline/execute-async/${runId}/stream`, { withCredentials: true })

    es.onmessage = (e) => {
      setLines(prev => [...prev, e.data])
    }
    es.addEventListener('done', (e) => {
      try {
        const payload = JSON.parse(e.data)
        setStatus(payload.status)
        if (onFinished) onFinished(payload)
      } catch {
        setStatus('failed')
      }
      es.close()
    })
    es.onerror = () => {
      setLines(prev => [...prev, '⚠ Log stream disconnected.'])
      es.close()
    }

    return () => es.close()
  }, [runId])

  useEffect(() => {
    if (autoScroll.current && logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight
    }
  }, [lines])

  const handleScroll = () => {
    const el = logBoxRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
    autoScroll.current = atBottom
  }

  const requestStop = async () => {
    if (!runId || stopRequested) return
    setStopRequested(true)
    try {
      await api.post(`/pipeline/execute-async/${runId}/stop`)
      setStatus('stopping')
    } catch (e) {
      setStopRequested(false)
    }
  }

  const isRunning = status === 'running' || status === 'stopping'
  const statusChip = {
    running:  { label: '⚙️ Running',  bg: '#E6F1FB', fg: '#185FA5' },
    stopping: { label: '🛑 Stopping…', bg: '#FAEEDA', fg: '#854F0B' },
    success:  { label: '✓ Completed', bg: '#EAF3DE', fg: '#3B6D11' },
    failed:   { label: '✗ Failed',    bg: '#FCEBEB', fg: '#A32D2D' },
    stopped:  { label: '⏹ Stopped',   bg: '#FAEEDA', fg: '#854F0B' },
  }[status] || { label: status, bg: '#f3f4f6', fg: '#555' }

  return (
    <div style={{ ...card, border: '2px solid #185FA5' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={sectionTitle}>Live execution log</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ ...statusChipStyle, background: statusChip.bg, color: statusChip.fg }}>
            {statusChip.label}
          </span>
          {isRunning && (
            <button
              style={{ ...btnGhost, color: '#A32D2D', borderColor: '#A32D2D', opacity: stopRequested ? 0.5 : 1 }}
              onClick={requestStop} disabled={stopRequested}>
              {stopRequested ? 'Stopping…' : '⏹ Stop'}
            </button>
          )}
        </div>
      </div>
      <div
        ref={logBoxRef}
        onScroll={handleScroll}
        style={{ background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6,
          fontFamily: 'monospace', fontSize: 11, lineHeight: 1.6, maxHeight: 360,
          overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
      >
        {lines.length === 0 ? (
          <div style={{ color: '#888' }}>Waiting for output…</div>
        ) : lines.map((line, i) => (
          <div key={i} style={{
            color: line.includes('✗') || line.includes('ERROR') ? '#f87171'
                 : line.includes('✓')   ? '#86efac'
                 : line.includes('⚠')   ? '#fbbf24'
                 : line.includes('🛑')  ? '#fb923c'
                 : '#d4d4d4'
          }}>
            {line}
          </div>
        ))}
        {isRunning && <div style={{ color: '#666' }}>▌</div>}
      </div>
    </div>
  )
}

// ── Main ETL Agent ────────────────────────────────────────────────────────────
export default function EtlAgent() {
  const navigate = useNavigate()
  const [step,    setStep]    = useState(0)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const [connectors,   setConnectors]   = useState([])
  const [connectorId,  setConnectorId]  = useState('')
  const [targetId,     setTargetId]     = useState('')
  const [stagingSchema,   setStagingSchema]   = useState('staging')
  const [warehouseSchema, setWarehouseSchema] = useState('warehouse')
  const [targetSchemas,   setTargetSchemas]   = useState([])
  const [loadingSchemas,  setLoadingSchemas]  = useState(false)

  const [smartMode,    setSmartMode]    = useState('auto')
  const [hilEnabled,   setHilEnabled]   = useState(true)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [pipelineName, setPipelineName] = useState('')
  const [schedule,     setSchedule]     = useState('manual')

  const [showSmartSelector, setShowSmartSelector] = useState(false)
  const [tableSelDone,      setTableSelDone]      = useState(false)

  const [availableTables, setAvailableTables] = useState([])
  const [sourceTables,    setSourceTables]    = useState([])
  const [columnsByTable,  setColumnsByTable]  = useState({})
  const [selectedColumns, setSelectedColumns] = useState({})
  const [expandedTables,  setExpandedTables]  = useState(new Set())
  const [fetchingTables,  setFetchingTables]  = useState(false)
  const [searchTerm,      setSearchTerm]      = useState('')

  const [form, setForm] = useState({
    source_description: '', raw_schema: '', business_requirements: ''
  })

  const [phase1Result,     setPhase1Result]     = useState(null)
  const [modelApprovalId,  setModelApprovalId]  = useState(null)
  const [editedModel,      setEditedModel]      = useState(null)
  const [phase2Result,     setPhase2Result]      = useState(null)
  const [sqlApprovalId,    setSqlApprovalId]    = useState(null)
  const [editedScripts,    setEditedScripts]    = useState(null)
  const [editingScriptIdx, setEditingScriptIdx] = useState(-1)
  const [sqlWarnings,      setSqlWarnings]      = useState([])
  const [savedPipelineId,  setSavedPipelineId]  = useState(null)
  const [saved,            setSaved]            = useState(false)
  const [executing,        setExecuting]        = useState(false)
  const [executed,         setExecuted]         = useState(false)
  const [execResult,       setExecResult]       = useState(null)
  const [finalArtifacts,   setFinalArtifacts]   = useState(null)
  const [cacheHit,         setCacheHit]         = useState(false)

  const [runId, setRunId] = useState(null)

  useEffect(() => {
    api.get('/connector/list').then(r => {
      const list = r.data.connectors || []
      setConnectors(list)
      if (list.length > 0) setConnectorId(list[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => { if (connectorId) fetchTablesFromConnector() }, [connectorId])

  useEffect(() => {
    const tgt = targetId || connectorId
    if (tgt) loadTargetSchemas(tgt)
  }, [targetId, connectorId])

  const loadTargetSchemas = async (tgtId) => {
    if (!tgtId) { setTargetSchemas([]); return }
    setLoadingSchemas(true)
    try {
      const r = await api.get(`/connector/${tgtId}/schemas`)
      setTargetSchemas(r.data?.schemas || [])
    } catch { setTargetSchemas([]) }
    setLoadingSchemas(false)
  }

  const targetConnectors = connectors.filter(c => c.role === 'target' || c.role === 'both')

  const fetchTablesFromConnector = async () => {
    if (!connectorId) return
    setFetchingTables(true)
    try {
      const r = await api.get(`/connector/${connectorId}/tables`)
      const rawTables = (r.data?.schemas?.raw || []).map(t => t.name)
      setAvailableTables(rawTables)
      setSourceTables(rawTables)
      await fetchColumns(rawTables)
      if (rawTables.length > 10) {
        setShowSmartSelector(true)
        setTableSelDone(false)
      } else {
        setShowSmartSelector(false)
        setTableSelDone(true)
      }
    } catch (e) {
      setAvailableTables([])
    }
    setFetchingTables(false)
  }

  const fetchColumns = async (tables) => {
    if (!tables.length) { setColumnsByTable({}); setSelectedColumns({}); return }
    try {
      const r = await api.post(`/connector/${connectorId}/columns`, { table_names: tables })
      const byTable = r.data?.tables || {}
      setColumnsByTable(byTable)
      const sel = {}
      Object.keys(byTable).forEach(t => { sel[t] = new Set(byTable[t].map(c => c.name)) })
      setSelectedColumns(sel)
    } catch {}
  }

  const filteredTables = useMemo(() => {
    const q = searchTerm.trim().toLowerCase()
    if (!q) return availableTables
    return availableTables.filter(t => {
      if (t.toLowerCase().includes(q)) return true
      return (columnsByTable[t] || []).some(c => c.name.toLowerCase().includes(q))
    })
  }, [availableTables, columnsByTable, searchTerm])

  const matchedColumns = useMemo(() => {
    const q = searchTerm.trim().toLowerCase()
    if (!q) return null
    const result = {}
    Object.keys(columnsByTable).forEach(t => {
      const matches = (columnsByTable[t] || []).filter(c => c.name.toLowerCase().includes(q))
      if (matches.length > 0) result[t] = new Set(matches.map(c => c.name))
    })
    return result
  }, [columnsByTable, searchTerm])

  useEffect(() => {
    if (matchedColumns && Object.keys(matchedColumns).length > 0) {
      setExpandedTables(new Set(Object.keys(matchedColumns)))
    }
  }, [matchedColumns])

  const toggleExpand = (table) => {
    setExpandedTables(prev => {
      const next = new Set(prev)
      if (next.has(table)) next.delete(table); else next.add(table)
      return next
    })
  }

  const toggleTable = (table, checked) => {
    setSourceTables(prev => checked ? [...prev, table] : prev.filter(t => t !== table))
  }

  const toggleColumn = (table, col) => {
    setSelectedColumns(prev => {
      const next = { ...prev }
      const set  = new Set(next[table] || [])
      if (set.has(col)) set.delete(col); else set.add(col)
      next[table] = set
      return next
    })
  }

  const setAllColumns = (table, on) => {
    setSelectedColumns(prev => ({
      ...prev,
      [table]: on ? new Set((columnsByTable[table] || []).map(c => c.name)) : new Set()
    }))
  }

  const buildSchemaFromSelection = () => {
    const lines = []; const cols = {}
    sourceTables.forEach(t => {
      const sel = Array.from(selectedColumns[t] || [])
      if (sel.length) { lines.push(`${t}: ${sel.join(', ')}`); cols[t] = sel }
    })
    return { schemaText: lines.join('\n'), sourceColumns: cols }
  }

  const loadDemo = () => {
    setForm({
      source_description: 'E-commerce PostgreSQL database',
      raw_schema: `orders: order_id, customer_id, order_date, status, total_amount
customers: customer_id, first_name, last_name, email, city, segment
order_items: item_id, order_id, product_id, qty, unit_price
products: product_id, name, category, cost_price`,
      business_requirements: 'Sales by region and product category, customer lifetime value, daily revenue trends'
    })
    setPipelineName('Demo Pipeline ' + new Date().toLocaleDateString())
  }

  const reset = () => {
    setStep(0); setError(null)
    setPhase1Result(null); setModelApprovalId(null); setEditedModel(null)
    setPhase2Result(null); setSqlApprovalId(null); setEditedScripts(null)
    setSavedPipelineId(null); setSaved(false); setExecuted(false)
    setExecResult(null); setFinalArtifacts(null); setSqlWarnings([])
    setSearchTerm(''); setCacheHit(false); setRunId(null)
  }

  const resolveSmartMode = () => {
    if (smartMode === 'off') return false
    if (smartMode === 'on')  return true
    return true
  }

  const runPhase1 = async () => {
    const { schemaText } = buildSchemaFromSelection()
    const effectiveSchema = form.raw_schema || schemaText
    if (!form.source_description || !effectiveSchema || !form.business_requirements) {
      setError('Fill in description, goals, and select at least one table/column.'); return
    }
    if (!connectorId) { setError('Add a database connection first.'); return }
    setError(null); setLoading(true); setStep(1)
    try {
      const endpoint = hilEnabled ? '/pipeline/run-phase-1' : '/pipeline/run'
      const res = await api.post(endpoint, {
        source_description:    form.source_description,
        raw_schema:            effectiveSchema,
        business_requirements: form.business_requirements,
        connector_id:          resolveSmartMode() ? connectorId : '',
        staging_schema:        stagingSchema,
        warehouse_schema:      warehouseSchema
      })
      if (hilEnabled) {
        setPhase1Result(res.data.data)
        setModelApprovalId(res.data.approval_id)
        setCacheHit(res.data.cache_hit || false)
        setStep(2)
      } else {
        setFinalArtifacts(res.data.data); setStep(5)
      }
    } catch (e) { setError(formatError(e)); setStep(0) }
    setLoading(false)
  }

  const approveModel = async () => {
    setError(null); setLoading(true); setStep(3)
    try {
      const payload = { approval_id: modelApprovalId, comments: '' }
      if (editedModel && typeof editedModel === 'object') payload.edited_model = editedModel
      const res = await api.post('/pipeline/approve-model', payload)
      setPhase2Result(res.data.data)
      setSqlApprovalId(res.data.approval_id); setStep(4)
    } catch (e) { setError(formatError(e)); setStep(2) }
    setLoading(false)
  }

  const rejectModel = async () => {
    const reason = prompt('Why are you rejecting?')
    if (!reason) return
    setLoading(true)
    try {
      await api.post('/pipeline/reject', { approval_id: modelApprovalId, comments: reason, regenerate: true })
      await runPhase1()
    } catch (e) { setError(formatError(e)) }
    setLoading(false)
  }

  const approveSql = async () => {
    setError(null); setLoading(true)
    try {
      const payload = { approval_id: sqlApprovalId, comments: '' }
      if (editedScripts?.length) payload.edited_scripts = editedScripts
      const res = await api.post('/pipeline/approve-sql', payload)
      if (res.data.blocked) {
        const violations   = res.data.violations || []
        const violationTxt = violations.map(v => `• ${v.name}\n  ${v.message}`).join('\n\n')
        const proceed = window.confirm(`🛑 SQL SAFETY GUARD BLOCKED\n\n${res.data.message}\n\n${violationTxt}\n\nOverride?`)
        if (proceed) {
          payload.i_understand_destructive = true
          const r2 = await api.post('/pipeline/approve-sql', payload)
          if (r2.data.blocked) { setError('Override failed.'); setLoading(false); return }
          setFinalArtifacts(r2.data.data); setSqlWarnings(r2.data.warnings || []); setStep(5)
        } else { setError('SQL approval cancelled.') }
        setLoading(false); return
      }
      setFinalArtifacts(res.data.data); setSqlWarnings(res.data.warnings || []); setStep(5)
    } catch (e) { setError(formatError(e)) }
    setLoading(false)
  }

  const rejectSql = async () => {
    const reason = prompt('Why are you rejecting?')
    if (!reason) return
    setLoading(true)
    try {
      await api.post('/pipeline/reject', { approval_id: sqlApprovalId, comments: reason, regenerate: true })
      const retryPayload = { approval_id: modelApprovalId, comments: 'Retry: ' + reason }
      if (editedModel && typeof editedModel === 'object') retryPayload.edited_model = editedModel
      const res = await api.post('/pipeline/approve-model', retryPayload)
      setPhase2Result(res.data.data); setSqlApprovalId(res.data.approval_id)
    } catch (e) { setError(formatError(e)) }
    setLoading(false)
  }

  const savePipeline = async () => {
    if (!pipelineName) { setError('Enter a pipeline name'); return }
    if (sourceTables.length === 0) { setError('Select at least one source table'); return }
    const { sourceColumns } = buildSchemaFromSelection()
    try {
      const res = await api.post('/pipeline/save', {
        name: pipelineName, artifacts: finalArtifacts, schedule,
        source_description: form.source_description,
        raw_schema: form.raw_schema,
        business_requirements: form.business_requirements,
        connector_id: connectorId,
        source_tables: sourceTables,
        source_columns: sourceColumns,
        target_connector_id: targetId || '',
        staging_schema: stagingSchema,
        warehouse_schema: warehouseSchema
      })
      setSavedPipelineId(res.data.pipeline?.id); setSaved(true); setError(null)
    } catch (e) { setError('Save failed: ' + formatError(e)) }
  }

  const executePipeline = async () => {
    if (!savedPipelineId) { setError('Save the pipeline first'); return }
    setExecuting(true); setError(null)
    try {
      const res = await api.post(`/pipeline/execute-async/${savedPipelineId}`)
      setRunId(res.data.run_id)
      setExecuted(true)
    } catch (e) {
      setError('Could not start execution: ' + formatError(e))
    }
    setExecuting(false)
  }

  const handleExecutionFinished = async (payload) => {
    try {
      const r = await api.get(`/pipeline/execute-async/${runId}/status`)
      setExecResult(r.data.result || {
        success: payload.status === 'success',
        message: payload.message || (payload.status === 'stopped' ? 'Execution stopped.' : 'Execution finished.')
      })
    } catch {
      setExecResult({ success: payload.status === 'success', message: payload.message || '' })
    }
  }

  const totalSelectedCols = sourceTables.reduce((sum, t) => sum + (selectedColumns[t]?.size || 0), 0)

  return (
    <>
      <PageHeader title="ETL Agent" subtitle="Universal AI ETL — works for any database, any domain" />
      <PageBody>

        <div style={{ display: 'flex', gap: 4, marginBottom: 20 }}>
          {STEPS.map((s, i) => (
            <div key={i} style={{ flex: 1 }}>
              <div style={{ height: 3, borderRadius: 2, background: i <= step ? '#185FA5' : '#e5e7eb', marginBottom: 4 }} />
              <div style={{ fontSize: 9, color: i === step ? '#185FA5' : '#aaa', textAlign: 'center' }}>{s}</div>
            </div>
          ))}
        </div>

        {error && <div style={errBox}>{typeof error === 'string' ? error : formatError(error)}</div>}

        {step === 0 && (
          <div>
            {connectors.length > 0 && (
              <Field label="Source connection">
                <select style={inp} value={connectorId} onChange={e => setConnectorId(e.target.value)}>
                  {connectors.map(c => (
                    <option key={c.id} value={c.id}>{c.name} — {c.host}/{c.database_name} · {c.source_schema}</option>
                  ))}
                </select>
              </Field>
            )}
            {connectors.length > 0 && (
              <Field label="Target connection (where warehouse is written)">
                {targetConnectors.length > 0 ? (
                  <select style={inp} value={targetId} onChange={e => setTargetId(e.target.value)}>
                    <option value="">↳ Same as source (default)</option>
                    {targetConnectors.map(c => (
                      <option key={c.id} value={c.id}>{c.name} — {c.host}/{c.database_name}</option>
                    ))}
                  </select>
                ) : (
                  <div style={{ fontSize: 11, color: '#888', padding: '7px 10px', background: '#f9fafb', borderRadius: 6 }}>
                    No target connectors — warehouse written to source connection.
                  </div>
                )}
              </Field>
            )}

            <Field label="Source system description">
              <textarea style={ta} rows={2} value={form.source_description}
                placeholder="e.g. School management DB / Banking transactions / Hospital records"
                onChange={e => setForm({ ...form, source_description: e.target.value })} />
            </Field>

            <Field label="Analytics goals — what do you want to measure?">
              <textarea style={ta} rows={2} value={form.business_requirements}
                placeholder="e.g. Enrollment by course, grades by teacher, revenue by region"
                onChange={e => setForm({ ...form, business_requirements: e.target.value })} />
            </Field>

            {connectorId && (
              <Field label={`Source tables & columns (${sourceTables.length} tables, ${totalSelectedCols} columns selected)`}>
                {fetchingTables ? (
                  <div style={{ fontSize: 11, color: '#888', padding: 8 }}>⏳ Reading database…</div>
                ) : availableTables.length === 0 ? (
                  <div style={{ background: '#FAEEDA', borderRadius: 6, padding: '10px 14px', fontSize: 11, color: '#854F0B', display: 'flex', justifyContent: 'space-between' }}>
                    <span>⚠ No tables found. Check the connector's source schema.</span>
                    <button style={btnGhostSmall} onClick={fetchTablesFromConnector}>Refresh</button>
                  </div>
                ) : showSmartSelector && !tableSelDone ? (
                  <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '14px 16px' }}>
                    <SmartTableSelector
                      connectorId={connectorId}
                      availableTables={availableTables}
                      sourceTables={sourceTables}
                      setSourceTables={setSourceTables}
                      onDone={() => setTableSelDone(true)}
                    />
                  </div>
                ) : (
                  <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden' }}>
                    {availableTables.length > 10 && tableSelDone && (
                      <div style={{ padding: '6px 12px', background: '#E6F1FB', borderBottom: '1px solid #d1e3f8', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 10, color: '#185FA5' }}>
                          🤖 {sourceTables.length} of {availableTables.length} tables selected
                        </span>
                        <button style={btnGhostSmall} onClick={() => { setShowSmartSelector(true); setTableSelDone(false) }}>
                          Re-run AI selection
                        </button>
                      </div>
                    )}
                    <div style={{ padding: '8px 12px', background: '#f9fafb', borderBottom: '1px solid #e5e7eb', display: 'flex', gap: 6, alignItems: 'center' }}>
                      <span style={{ fontSize: 13 }}>🔍</span>
                      <input type="text" style={{ ...inp, flex: 1, fontSize: 11 }}
                        placeholder="Search tables and columns..."
                        value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
                      {searchTerm && <button style={btnGhostSmall} onClick={() => setSearchTerm('')}>✕</button>}
                    </div>
                    {filteredTables.map(t => {
                      const isSel    = sourceTables.includes(t)
                      const cols     = columnsByTable[t] || []
                      const selSet   = selectedColumns[t] || new Set()
                      const expanded = expandedTables.has(t)
                      const matched  = matchedColumns?.[t]
                      const displayCols = matched ? cols.filter(c => matched.has(c.name)) : cols
                      return (
                        <div key={t} style={{ borderBottom: '1px solid #f3f4f6' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: isSel ? '#F6FAFE' : '#fff' }}>
                            <input type="checkbox" checked={isSel} onChange={e => toggleTable(t, e.target.checked)} />
                            <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600, color: isSel ? '#185FA5' : '#888', flex: 1 }}>{t}</span>
                            <span style={{ fontSize: 10, color: '#888' }}>{selSet.size}/{cols.length} cols</span>
                            <button style={btnGhostSmall} onClick={() => toggleExpand(t)}>
                              {expanded ? '▲ Hide' : '▾ Columns'}
                            </button>
                          </div>
                          {expanded && (
                            <div style={{ padding: '6px 12px 10px 34px', background: '#fafafa' }}>
                              <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                                <button style={btnGhostSmall} onClick={() => setAllColumns(t, true)}>Select all</button>
                                <button style={btnGhostSmall} onClick={() => setAllColumns(t, false)}>Clear</button>
                              </div>
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                                {displayCols.map(col => {
                                  const on  = selSet.has(col.name)
                                  const pii = isPII(col.name)
                                  return (
                                    <label key={col.name} title={`${col.type}${col.key ? ' · ' + col.key : ''}`}
                                      style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, cursor: 'pointer',
                                        background: on ? (pii ? '#FAEEDA' : '#E6F1FB') : '#fff',
                                        border: `1px solid ${on ? (pii ? '#EF9F27' : '#185FA5') : '#e5e7eb'}`,
                                        borderRadius: 6, padding: '3px 8px' }}>
                                      <input type="checkbox" checked={on} onChange={() => toggleColumn(t, col.name)} />
                                      <span style={{ fontFamily: 'monospace', color: on ? (pii ? '#854F0B' : '#185FA5') : '#888' }}>
                                        {pii && '⚠️ '}{col.name}
                                      </span>
                                      {col.key && <span style={{ fontSize: 8, color: '#888', fontWeight: 600 }}>{col.key}</span>}
                                    </label>
                                  )
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      )
                    })}
                    <div style={{ display: 'flex', gap: 6, padding: '6px 12px', background: '#f9fafb' }}>
                      <button style={btnGhostSmall} onClick={() => setSourceTables([...availableTables])}>Select all</button>
                      <button style={btnGhostSmall} onClick={() => setSourceTables([])}>Clear all</button>
                      <button style={btnGhostSmall} onClick={fetchTablesFromConnector}>🔄 Refresh</button>
                    </div>
                  </div>
                )}
              </Field>
            )}

            <div style={{ marginBottom: 10 }}>
              <button style={btnGhostSmall} onClick={() => setShowAdvanced(!showAdvanced)}>
                {showAdvanced ? '▲ Hide advanced' : '▾ Advanced (target schemas / manual schema text)'}
              </button>
            </div>
            {showAdvanced && (
              <div style={{ ...card, background: '#fafafa' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                  <Field label="Staging schema">
                    <SchemaCombobox value={stagingSchema} onChange={setStagingSchema}
                      schemas={targetSchemas} loading={loadingSchemas}
                      onRefresh={() => loadTargetSchemas(targetId || connectorId)}
                      placeholder="e.g. staging" />
                  </Field>
                  <Field label="Warehouse schema">
                    <SchemaCombobox value={warehouseSchema} onChange={setWarehouseSchema}
                      schemas={targetSchemas} loading={loadingSchemas}
                      onRefresh={() => loadTargetSchemas(targetId || connectorId)}
                      placeholder="e.g. warehouse" />
                  </Field>
                </div>
                <Field label="Manual schema text (overrides table picker if filled)">
                  <textarea style={ta} rows={5} value={form.raw_schema}
                    placeholder="table_name: col1, col2, col3"
                    onChange={e => setForm({ ...form, raw_schema: e.target.value })} />
                  <button style={{ ...btnGhostSmall, marginTop: 6 }} onClick={loadDemo}>Load e-commerce demo</button>
                </Field>
              </div>
            )}

            {connectors.length > 0 && (
              <div style={{ border: '1.5px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
                  ✨ Smart Mode — data profiling
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {[
                    { value: 'auto', label: '🤖 Auto', desc: 'Profile on first run, skip if cached ($0 on re-runs)' },
                    { value: 'on',   label: '⚡ Always on', desc: 'Always profile — most accurate, costs slightly more' },
                    { value: 'off',  label: '🚫 Off', desc: 'Never profile — fastest, cheapest, less accurate' },
                  ].map(opt => (
                    <label key={opt.value} title={opt.desc}
                      style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
                        background: smartMode === opt.value ? '#E6F1FB' : '#f9fafb',
                        border: `1.5px solid ${smartMode === opt.value ? '#185FA5' : '#e5e7eb'}`,
                        borderRadius: 6, padding: '6px 12px', fontSize: 11 }}>
                      <input type="radio" name="smartMode" value={opt.value}
                        checked={smartMode === opt.value} onChange={() => setSmartMode(opt.value)} />
                      <span style={{ fontWeight: smartMode === opt.value ? 600 : 400,
                        color: smartMode === opt.value ? '#185FA5' : '#555' }}>{opt.label}</span>
                    </label>
                  ))}
                </div>
                <div style={{ fontSize: 10, color: '#888', marginTop: 6 }}>
                  {smartMode === 'auto' && '🤖 Auto: profiles schema on first design, uses cache on re-runs — recommended'}
                  {smartMode === 'on'   && '⚡ Always on: re-profiles every time — use when schema frequently changes'}
                  {smartMode === 'off'  && '🚫 Off: skips profiling — use for fastest results or when schema is well-known'}
                </div>
              </div>
            )}

            <div style={{ background: hilEnabled ? '#FAEEDA' : '#f9fafb',
              border: `1.5px solid ${hilEnabled ? '#854F0B' : '#e5e7eb'}`,
              borderRadius: 8, padding: '12px 14px', marginBottom: 14 }}>
              <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' }}>
                <input type="checkbox" checked={hilEnabled} onChange={e => setHilEnabled(e.target.checked)}
                  style={{ marginTop: 3, width: 16, height: 16 }} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: hilEnabled ? '#854F0B' : '#555' }}>
                    👁 Human-in-the-Loop — approve AI decisions
                  </div>
                  <div style={{ fontSize: 11, color: hilEnabled ? '#854F0B' : '#888', marginTop: 4 }}>
                    {hilEnabled ? 'AI pauses at 2 checkpoints: model review + SQL review.' : 'AI runs end-to-end without pauses.'}
                  </div>
                </div>
              </label>
            </div>

            <button style={btnPrimary} onClick={runPhase1} disabled={loading || connectors.length === 0}>
              {loading ? 'Running...' : hilEnabled ? '🚀 Start ETL Agent (with HIL)' : '▶ Run ETL Agent (no HIL)'}
            </button>
          </div>
        )}

        {loading && (step === 1 || step === 3) && (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <div style={{ fontSize: 24, marginBottom: 10 }}>⚙️</div>
            <div style={{ fontSize: 14, color: '#185FA5', fontWeight: 500 }}>
              {step === 1 ? 'AI analyzing your data and designing model...' : 'AI generating SQL scripts...'}
            </div>
            <div style={{ fontSize: 11, color: '#aaa', marginTop: 6 }}>Takes 1-3 minutes</div>
          </div>
        )}

        {step === 2 && phase1Result && !loading && (
          <>
            {cacheHit && (
              <div style={{ background: '#EAF3DE', border: '1px solid #a7d9a0', borderRadius: 6,
                padding: '8px 14px', fontSize: 11, color: '#27500A', marginBottom: 10 }}>
                ⚡ Schema cache HIT — reusing saved design. <strong>$0 AI cost this run.</strong>
              </div>
            )}
            <ModelReview data={phase1Result} onApprove={approveModel} onReject={rejectModel} onEdit={setEditedModel} />
          </>
        )}

        {step === 4 && phase2Result && !loading && (
          <SqlReview data={phase2Result} onApprove={approveSql} onReject={rejectSql}
            editedScripts={editedScripts} setEditedScripts={setEditedScripts}
            editingIdx={editingScriptIdx} setEditingIdx={setEditingScriptIdx} />
        )}

        {step === 5 && finalArtifacts && (
          <div>
            <div style={successBanner}>✓ All approvals complete. Save your pipeline and execute.</div>
            {sqlWarnings.length > 0 && (
              <div style={warnBox}>
                <strong>⚠ Safety warnings:</strong>
                <ul style={{ margin: '4px 0 0 20px' }}>{sqlWarnings.map((w, i) => <li key={i}>{String(w)}</li>)}</ul>
              </div>
            )}
            {!saved ? (
              <div style={{ ...card, border: '2px solid #185FA5' }}>
                <div style={sectionTitle}>Save pipeline</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <Field label="Pipeline name">
                    <input style={inp} value={pipelineName} onChange={e => setPipelineName(e.target.value)} />
                  </Field>
                  <Field label="Schedule">
                    <select style={inp} value={schedule} onChange={e => setSchedule(e.target.value)}>
                      <option value="manual">Manual only</option>
                      <option value="hourly">Every hour</option>
                      <option value="daily">Daily at 2 AM</option>
                      <option value="weekly">Weekly Monday</option>
                    </select>
                  </Field>
                </div>
                <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
                  Extract <strong>{sourceTables.length}</strong> tables ({totalSelectedCols} columns) →
                  staging <span style={{ fontFamily: 'monospace', color: '#185FA5' }}>{stagingSchema}</span> →
                  warehouse <span style={{ fontFamily: 'monospace', color: '#534AB7' }}>{warehouseSchema}</span>
                </div>
                <button style={btnPrimary} onClick={savePipeline}>Save pipeline</button>
              </div>
            ) : (
              <div style={{ background: '#EAF3DE', borderRadius: 6, padding: '10px 14px', fontSize: 12, color: '#27500A', marginBottom: 10 }}>
                ✓ Saved as "{pipelineName}"
              </div>
            )}
            {saved && !executed && (
              <div style={{ ...card, border: '2px solid #3B6D11' }}>
                <div style={sectionTitle}>Execute</div>
                <button style={{ ...btnPrimary, background: '#3B6D11', borderColor: '#3B6D11' }}
                  onClick={executePipeline} disabled={executing}>
                  {executing ? '⚙️ Starting...' : '▶ Execute pipeline now'}
                </button>
              </div>
            )}
            {executed && runId && !execResult && (
              <LiveExecutionPanel runId={runId} onFinished={handleExecutionFinished} />
            )}
            {executed && execResult && (
              <div style={{ ...card, border: '2px solid #3B6D11' }}>
                <div style={sectionTitle}>Execution complete</div>
                <div style={{ fontSize: 12, color: execResult.success ? '#3B6D11' : '#A32D2D', marginBottom: 10 }}>
                  {execResult.message}
                </div>
                {(execResult.warehouse?.logs || []).map((log, i) => (
                  <div key={i} style={{ fontSize: 11, fontFamily: 'monospace',
                    color: String(log).includes('✗') ? '#991b1b' : String(log).includes('✓') ? '#3B6D11' : '#555',
                    padding: '2px 0' }}>{String(log)}</div>
                ))}
                <button style={btnPrimary} onClick={reset}>Run another pipeline</button>
                <button style={{ ...btnGhost, marginLeft: 8 }} onClick={() => navigate('/connectors')}>View warehouse →</button>
              </div>
            )}
          </div>
        )}
      </PageBody>
    </>
  )
}

function ModelReview({ data, onApprove, onReject, onEdit }) {
  const [showJson, setShowJson] = useState(false)
  const dm   = data.data_model || {}
  const facts = dm.fact_tables || []
  const dims  = dm.dimension_tables || []
  const rels  = (data.schema_analysis || {}).relationships || []
  const nm = (x) => typeof x === 'string' ? x : (x?.column || x?.name || JSON.stringify(x))

  return (
    <div>
      <div style={{ background: '#FAEEDA', border: '2px solid #854F0B', borderRadius: 8, padding: '14px 16px', marginBottom: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#854F0B', marginBottom: 4 }}>👁 HIL Gate 1 — Review proposed data model</div>
        <div style={{ fontSize: 11, color: '#854F0B' }}>AI analyzed your data and designed this star schema.</div>
      </div>
      <div style={card}>
        <div style={sectionTitle}>Fact tables ({facts.length})</div>
        {facts.map((f, i) => (
          <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #f3f4f6' }}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{String(f.name || '')}</div>
            <div style={{ fontSize: 11, color: '#888' }}>Grain: {String(f.grain || '')}</div>
            <div style={{ fontSize: 11, color: '#555' }}>Measures: {(f.measures || []).map(nm).join(', ')}</div>
            <div style={{ fontSize: 11, color: '#555' }}>FKs: {(f.foreign_keys || []).map(nm).join(', ')}</div>
          </div>
        ))}
      </div>
      <div style={card}>
        <div style={sectionTitle}>Dimension tables ({dims.length})</div>
        {dims.map((d, i) => (
          <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #f3f4f6' }}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{String(d.name || '')}
              <span style={{ fontSize: 10, color: '#888', fontWeight: 400 }}> (SCD Type {String(d.scd_type || '?')})</span>
            </div>
            <div style={{ fontSize: 11, color: '#888' }}>Source: {String(d.source_table || '')}</div>
            <div style={{ fontSize: 11, color: '#555' }}>Attributes: {(d.attributes || []).map(nm).join(', ')}</div>
          </div>
        ))}
      </div>
      <div style={card}>
        <div style={sectionTitle}>Detected relationships ({rels.length})</div>
        {rels.map((r, i) => (
          <div key={i} style={{ fontSize: 11, padding: '4px 0' }}>
            <span style={{ fontFamily: 'monospace' }}>{String(r.from_table || '')}.{String(r.join_key || '')}</span>
            {' → '}<span style={{ fontFamily: 'monospace' }}>{String(r.to_table || '')}</span>
            <span style={{ ...chip(r.confidence), marginLeft: 8 }}>{String(r.confidence || 'medium')}</span>
          </div>
        ))}
      </div>
      <div style={card}>
        <div style={{ cursor: 'pointer' }} onClick={() => setShowJson(!showJson)}>
          <span style={{ fontSize: 11, color: '#185FA5' }}>{showJson ? '▲ Hide' : '▼ Show'} raw JSON (edit advanced)</span>
        </div>
        {showJson && (
          <textarea style={{ ...ta, fontFamily: 'monospace', fontSize: 10, marginTop: 8, minHeight: 200 }}
            defaultValue={JSON.stringify(dm, null, 2)}
            onChange={e => { try { const p = JSON.parse(e.target.value); if (p && typeof p === 'object') onEdit(p) } catch {} }} />
        )}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        <button style={{ ...btnPrimary, background: '#3B6D11', borderColor: '#3B6D11' }} onClick={onApprove}>✓ Approve — continue to SQL</button>
        <button style={{ ...btnGhost, color: '#A32D2D', borderColor: '#A32D2D' }} onClick={onReject}>✗ Reject — regenerate</button>
      </div>
    </div>
  )
}

function SqlReview({ data, onApprove, onReject, editedScripts, setEditedScripts, editingIdx, setEditingIdx }) {
  const [activeIdx, setActiveIdx]     = useState(0)
  const [scriptSearch, setScriptSearch] = useState('')
  const scripts = editedScripts || data.sql_scripts?.scripts || []
  const filteredScripts = scriptSearch
    ? scripts.filter(s => (s.name || '').toLowerCase().includes(scriptSearch.toLowerCase()))
    : scripts
  const active = scripts[activeIdx]

  const updateScript = (idx, newSql) => {
    const updated = [...scripts]; updated[idx] = { ...updated[idx], sql: newSql }; setEditedScripts(updated)
  }

  const isDangerous = (sql) => {
    const u = String(sql || '').toUpperCase()
    return (u.includes('DROP TABLE') && !u.includes('IF EXISTS')) ||
           (u.includes('DELETE FROM') && !u.includes('WHERE')) ||
           u.includes('TRUNCATE')
  }

  return (
    <div>
      <div style={{ background: '#FAEEDA', border: '2px solid #854F0B', borderRadius: 8, padding: '14px 16px', marginBottom: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#854F0B', marginBottom: 4 }}>👁 HIL Gate 2 — Review SQL scripts</div>
        <div style={{ fontSize: 11, color: '#854F0B' }}>{scripts.length} SQL scripts ready. Click each tab to review and edit.</div>
      </div>
      <div style={card}>
        {scripts.length > 5 && (
          <div style={{ marginBottom: 8 }}>
            <input type="text" style={{ ...inp, fontSize: 11 }} placeholder="🔍 Search scripts..."
              value={scriptSearch} onChange={e => setScriptSearch(e.target.value)} />
          </div>
        )}
        <div style={{ display: 'flex', gap: 4, marginBottom: 10, flexWrap: 'wrap' }}>
          {filteredScripts.map((s) => {
            const i = scripts.indexOf(s)
            return (
              <button key={i} onClick={() => setActiveIdx(i)}
                style={{ padding: '5px 12px', background: i === activeIdx ? '#185FA5' : '#fff',
                  color: i === activeIdx ? '#fff' : '#555',
                  border: `1px solid ${isDangerous(s.sql) ? '#A32D2D' : '#d1d5db'}`,
                  borderRadius: 6, fontSize: 11, cursor: 'pointer' }}>
                {isDangerous(s.sql) && '⚠ '}{String(s.name || `script_${i + 1}`)}
              </button>
            )
          })}
        </div>
        {active && (
          <>
            <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>
              <strong>{String(active.name || '')}</strong> ({String(active.label || '')})
            </div>
            {isDangerous(active.sql) && <div style={{ ...warnBox, marginBottom: 6 }}>⚠ Dangerous SQL — review carefully.</div>}
            {editingIdx === activeIdx ? (
              <textarea style={{ width: '100%', minHeight: 250, fontFamily: 'monospace', fontSize: 11,
                background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6,
                border: '1px solid #555' }}
                value={active.sql || ''} onChange={e => updateScript(activeIdx, e.target.value)} />
            ) : (
              <pre style={{ background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6,
                fontSize: 10, overflowX: 'auto', lineHeight: 1.6, maxHeight: 400, overflow: 'auto' }}>
                {String(active.sql || '')}
              </pre>
            )}
            <button style={{ ...btnGhost, marginTop: 8 }} onClick={() => setEditingIdx(editingIdx === activeIdx ? -1 : activeIdx)}>
              {editingIdx === activeIdx ? '✓ Done editing' : '✎ Edit this SQL'}
            </button>
          </>
        )}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        <button style={{ ...btnPrimary, background: '#3B6D11', borderColor: '#3B6D11' }} onClick={onApprove}>✓ Approve all SQL — proceed to save</button>
        <button style={{ ...btnGhost, color: '#A32D2D', borderColor: '#A32D2D' }} onClick={onReject}>✗ Reject — regenerate SQL</button>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: '#374151', marginBottom: 4 }}>{label}</label>
      {children}
    </div>
  )
}

const chip = (confidence) => {
  const colors = { high: { bg: '#EAF3DE', fg: '#3B6D11' }, medium: { bg: '#FAEEDA', fg: '#854F0B' }, low: { bg: '#FCEBEB', fg: '#A32D2D' } }
  const c = colors[String(confidence || 'medium')] || colors.medium
  return { background: c.bg, color: c.fg, padding: '2px 8px', borderRadius: 20, fontSize: 9, fontWeight: 500 }
}

const ta           = { width: '100%', padding: '8px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, fontFamily: 'system-ui', resize: 'vertical', boxSizing: 'border-box' }
const inp          = { width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box' }
const card         = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 10 }
const errBox       = { background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#991b1b', marginBottom: 10 }
const warnBox      = { background: '#FAEEDA', border: '1px solid #f5c08a', borderRadius: 6, padding: '8px 12px', fontSize: 11, color: '#854F0B', marginBottom: 10 }
const successBanner = { background: '#EAF3DE', border: '1px solid #a7d9a0', borderRadius: 8, padding: '12px 16px', fontSize: 12, color: '#27500A', marginBottom: 14 }
const sectionTitle = { fontSize: 10, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }
const statusChipStyle = { padding: '3px 10px', borderRadius: 20, fontSize: 10, fontWeight: 600 }
const btnPrimary   = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhost     = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnGhostSmall = { padding: '4px 10px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 10, cursor: 'pointer' }
