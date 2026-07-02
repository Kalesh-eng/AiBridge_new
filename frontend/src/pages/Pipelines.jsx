/**
 * Pipelines.jsx — Saved pipelines with:
 *   - View runs
 *   - Edit SQL directly
 *   - Re-run AI with new requirements (triggers new version)
 *   - Selective table refresh
 *   - Delete pipeline
 *   - 🗺 Mappings tab — view/edit ETL column mappings, save versions
 *   - 🕐 Versions tab — version history, rollback, compare
 *   - ▶ Execute now runs in the background with a live streaming log panel
 *     and a Stop control, instead of blocking the button until the whole
 *     pipeline finishes (see executePipeline / LiveExecutionPanel below).
 */

import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'
import { ExportImportModal } from './ExportImport'

// ── Live execution log panel with Stop control ────────────────────────────
// Shared pattern with EtlAgent.jsx's LiveExecutionPanel: streams progress
// via SSE from /pipeline/execute-async/{run_id}/stream, exposes a Stop
// button that posts to /pipeline/execute-async/{run_id}/stop, and reports
// the final status back to the parent once the SSE "done" event arrives.
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

    // Batch updates every 500ms to prevent flickering
    const pendingLines = []
    const flushTimer = setInterval(() => {
      if (pendingLines.length > 0) {
        const batch = [...pendingLines]
        pendingLines.length = 0
        setLines(prev => [...prev, ...batch])
      }
    }, 500)

    es.onmessage = (e) => { pendingLines.push(e.data) }

    es.addEventListener('done', (e) => {
      clearInterval(flushTimer)
      if (pendingLines.length > 0) {
        setLines(prev => [...prev, ...pendingLines])
        pendingLines.length = 0
      }
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
      clearInterval(flushTimer)
      if (pendingLines.length > 0) {
        setLines(prev => [...prev, ...pendingLines])
        pendingLines.length = 0
      }
      es.close()
    }

    return () => { clearInterval(flushTimer); es.close() }
  }, [runId])

  useEffect(() => {
    if (autoScroll.current && logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight
    }
  })

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
  const statusChipMap = {
    running:  { label: '⚙️ Running',  bg: '#E6F1FB', fg: '#185FA5' },
    stopping: { label: '🛑 Stopping…', bg: '#FAEEDA', fg: '#854F0B' },
    success:  { label: '✓ Completed', bg: '#EAF3DE', fg: '#3B6D11' },
    failed:   { label: '✗ Failed',    bg: '#FCEBEB', fg: '#A32D2D' },
    stopped:  { label: '⏹ Stopped',   bg: '#FAEEDA', fg: '#854F0B' },
  }
  const chipInfo = statusChipMap[status] || { label: status, bg: '#f3f4f6', fg: '#555' }

  return (
    <div style={{ ...card, border: '2px solid #185FA5', marginTop: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em' }}>
          Live execution log
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ padding: '3px 10px', borderRadius: 20, fontSize: 10, fontWeight: 600,
            background: chipInfo.bg, color: chipInfo.fg }}>
            {chipInfo.label}
          </span>
          {isRunning && (
            <button
              style={{ ...btnGhostSmall, color: '#A32D2D', borderColor: '#A32D2D', opacity: stopRequested ? 0.5 : 1 }}
              onClick={requestStop} disabled={stopRequested}>
              {stopRequested ? 'Stopping…' : '⏹ Stop'}
            </button>
          )}
        </div>
      </div>
      <div
        ref={logBoxRef}
        onScroll={handleScroll}
        style={{ background: '#1e1e1e', color: '#d4d4d4', padding: 10, borderRadius: 6,
          fontFamily: 'monospace', fontSize: 10, lineHeight: 1.5, maxHeight: 260,
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

export default function Pipelines() {
  const navigate = useNavigate()
  const [pipelines,      setPipelines]      = useState([])
  const [loading,        setLoading]        = useState(true)
  const [error,          setError]          = useState(null)
  const [selected,       setSelected]       = useState(null)
  const [mode,           setMode]           = useState(null)
  // SQL editor
  const [scripts,        setScripts]        = useState([])
  const [activeScript,   setActiveScript]   = useState(0)
  const [editedSql,      setEditedSql]      = useState('')
  const [saving,         setSaving]         = useState(false)
  const [savedMsg,       setSavedMsg]       = useState('')
  // Re-run AI
  const [newReqs,        setNewReqs]        = useState('')
  const [rerunning,      setRerunning]      = useState(false)
  // Refresh
  const [tables,         setTables]         = useState([])
  const [selectedTables, setSelectedTables] = useState([])
  const [refreshing,     setRefreshing]     = useState(false)
  const [refreshMsg,     setRefreshMsg]     = useState('')
  // Execute — now tracks a background run_id per pipeline instead of a
  // single blocking in-flight flag, so the live log panel knows which
  // pipeline card to render under.
  const [executing,      setExecuting]      = useState(null)  // pipelineId currently starting (briefly)
  const [activeRuns,     setActiveRuns]     = useState({})    // pipelineId -> run_id
  const [execMsg,        setExecMsg]        = useState({})    // pipelineId -> final message
  // Delete
  const [deleting,       setDeleting]       = useState(null)
  const [confirmDelete,  setConfirmDelete]  = useState(null)
  // Mappings
  const [mappings,       setMappings]       = useState([])
  const [mappingVersions,setMappingVersions]= useState([])
  const [editedMappings, setEditedMappings] = useState([])
  const [mappingName,    setMappingName]    = useState('')
  const [mappingNotes,   setMappingNotes]   = useState('')
  const [savingMapping,  setSavingMapping]  = useState(false)
  const [mappingMsg,     setMappingMsg]     = useState('')
  // Versions
  const [versions,       setVersions]       = useState([])
  const [versionsLoading,setVersionsLoading]= useState(false)
  const [versionLabel,   setVersionLabel]   = useState('')
  const [versionNotes,   setVersionNotes]   = useState('')
  const [savingVersion,  setSavingVersion]  = useState(false)
  const [rollingBack,    setRollingBack]    = useState(null)
  const [compareA,       setCompareA]       = useState(null)
  const [compareB,       setCompareB]       = useState(null)
  const [diffResult,     setDiffResult]     = useState(null)
  const [showExportImport, setShowExportImport] = useState(false)

  useEffect(() => { loadPipelines() }, [])

  const loadPipelines = async () => {
    setLoading(true)
    try {
      const r = await api.get('/pipeline/list')
      setPipelines(r.data.pipelines || [])
    } catch (e) { setError('Could not load pipelines') }
    setLoading(false)
  }

  const openSqlEditor = (pipeline) => {
    setSelected(pipeline); setMode('sql')
    const s = pipeline.artifacts?.sql_scripts?.scripts || []
    setScripts(s); setActiveScript(0); setEditedSql(s[0]?.sql || '')
    setSavedMsg(''); setError(null)
  }

  const openRerun = (pipeline) => {
    setSelected(pipeline); setMode('rerun')
    setNewReqs(''); setSavedMsg(''); setError(null)
  }

  const openRefresh = (pipeline) => {
    setSelected(pipeline); setMode('refresh')
    const t = pipeline.source_tables || []
    setTables(t); setSelectedTables([...t])
    setRefreshMsg(''); setError(null)
  }

  const openMappings = async (pipeline) => {
    setSelected(pipeline); setMode('mappings')
    setSavedMsg(''); setError(null); setMappingMsg('')
    const raw = pipeline.artifacts?.etl_mappings?.mappings || []
    setMappings(raw)
    setEditedMappings(JSON.parse(JSON.stringify(raw)))
    setMappingName(`${pipeline.name} Mapping`)
    setMappingNotes('')
    try {
      const r = await api.get(`/mapping/list/${pipeline.id}`)
      setMappingVersions(r.data.mappings || [])
    } catch (e) { setMappingVersions([]) }
  }

  const openVersions = async (pipeline) => {
    setSelected(pipeline); setMode('versions')
    setSavedMsg(''); setError(null)
    setVersionLabel(''); setVersionNotes('')
    setDiffResult(null); setCompareA(null); setCompareB(null)
    setVersionsLoading(true)
    try {
      const r = await api.get(`/version/list/${pipeline.id}`)
      setVersions(r.data.versions || [])
    } catch (e) { setVersions([]) }
    setVersionsLoading(false)
  }

  const deletePipeline = async (pipeline) => {
    setDeleting(pipeline.id); setError(null)
    try {
      await api.delete(`/pipeline/${pipeline.id}`)
      if (selected?.id === pipeline.id) { setSelected(null); setMode(null) }
      setConfirmDelete(null)
      await loadPipelines()
    } catch (e) { setError('Delete failed: ' + (e.response?.data?.detail || e.message)) }
    setDeleting(null)
  }

  const saveEditedSql = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const updatedScripts   = scripts.map((s, i) => i === activeScript ? { ...s, sql: editedSql } : s)
      const updatedArtifacts = { ...selected.artifacts, sql_scripts: { scripts: updatedScripts } }
      await api.post(`/pipeline/update-artifacts/${selected.id}`, { artifacts: updatedArtifacts })
      setScripts(updatedScripts)
      setSavedMsg('✓ SQL saved. Next execution will use this SQL.')
      setTimeout(() => setSavedMsg(''), 4000)
      await loadPipelines()
    } catch (e) { setError('Could not save: ' + (e.response?.data?.detail || e.message)) }
    setSaving(false)
  }

  const rerunAI = async () => {
    if (!newReqs.trim()) { setError('Enter new requirements'); return }
    if (!selected) return
    setRerunning(true); setError(null)
    try {
      const r = await api.post('/pipeline/regenerate', {
        pipeline_id: selected.id, new_requirements: newReqs
      })
      setSavedMsg('✓ AI regenerated. New version saved automatically.')
      setMode('sql')
      const s = r.data.scripts || []
      setScripts(s); setActiveScript(0); setEditedSql(s[0]?.sql || '')
      await loadPipelines()
      try {
        await api.post('/version/save', {
          pipeline_id:    selected.id,
          version_label:  '',
          change_summary: `AI regenerated: ${newReqs.slice(0, 100)}`
        })
      } catch (e) { console.warn('Could not auto-save version:', e) }
    } catch (e) { setError('Regeneration failed: ' + (e.response?.data?.detail || e.message)) }
    setRerunning(false)
  }

  const runRefresh = async () => {
    if (selectedTables.length === 0) { setError('Select at least one table'); return }
    if (!selected) return
    setRefreshing(true); setError(null)
    try {
      const r = await api.post(`/pipeline/execute/${selected.id}`, { tables_override: selectedTables })
      setRefreshMsg(r.data.success
        ? `✓ Refreshed ${selectedTables.length} table(s) successfully`
        : `✗ Refresh failed: ${r.data.message}`)
    } catch (e) { setError('Refresh failed: ' + (e.response?.data?.detail || e.message)) }
    setRefreshing(false)
  }

  // Starts the pipeline in the background and switches the card into the
  // live-log view instead of blocking on the old synchronous endpoint.
  // executePipeline only handles the brief "starting" state; the actual
  // run's progress and completion are driven by LiveExecutionPanel below,
  // via handleExecutionFinished once the SSE stream's "done" event fires.
  const executePipeline = async (pipelineId) => {
    setExecuting(pipelineId)
    setExecMsg(prev => ({ ...prev, [pipelineId]: '' }))
    try {
      const r = await api.post(`/pipeline/execute-async/${pipelineId}`)
      setActiveRuns(prev => ({ ...prev, [pipelineId]: r.data.run_id }))
    } catch (e) {
      setExecMsg(prev => ({ ...prev, [pipelineId]:
        '✗ Could not start: ' + (e.response?.data?.detail || e.message) }))
    }
    setExecuting(null)
  }

  const handleExecutionFinished = async (pipelineId, runId, payload) => {
    try {
      const r = await api.get(`/pipeline/execute-async/${runId}/status`)
      const result = r.data.result || {}
      setExecMsg(prev => ({ ...prev, [pipelineId]:
        result.message || (payload.status === 'success' ? '✓ Executed successfully'
                          : payload.status === 'stopped' ? '⏹ Stopped by user'
                          : '✗ Execution failed') }))
    } catch {
      setExecMsg(prev => ({ ...prev, [pipelineId]:
        payload.status === 'success' ? '✓ Executed successfully' : '✗ Execution finished with an issue' }))
    }
    // Clear the active run so the live panel is replaced by the result
    // message, then auto-clear the message after a while like before.
    setActiveRuns(prev => {
      const next = { ...prev }
      delete next[pipelineId]
      return next
    })
    setTimeout(() => {
      setExecMsg(prev => {
        const next = { ...prev }
        delete next[pipelineId]
        return next
      })
    }, 8000)
    await loadPipelines()
  }

  // ── AI transform for a specific cell ────────────────────────────────────────
  const [aiTransformKey,  setAiTransformKey]  = useState(null)   // "mapIdx-colIdx"
  const [aiTransformText, setAiTransformText] = useState({})     // key → nl text
  const [aiTransformResult, setAiTransformResult] = useState({}) // key → generated SQL
  const [aiTransforming,  setAiTransforming]  = useState(null)   // key being generated

  const updateMappingCell = (mapIdx, colIdx, field, value) => {
    const updated = JSON.parse(JSON.stringify(editedMappings))
    if (updated[mapIdx]?.columns?.[colIdx]) {
      updated[mapIdx].columns[colIdx][field] = value
    }
    setEditedMappings(updated)
  }

  const generateAiTransform = async (mapIdx, colIdx) => {
    const key     = `${mapIdx}-${colIdx}`
    const col     = editedMappings[mapIdx]?.columns?.[colIdx]
    const nlText  = aiTransformText[key] || ''
    if (!nlText.trim()) return
    setAiTransforming(key)
    try {
      const r = await api.post('/nl/to-sql', {
        question: `Write a PostgreSQL SQL expression to transform the column "${col?.source_column}". 
                   Instruction: ${nlText}. 
                   Return ONLY the SQL expression for this single column (no SELECT, no FROM).
                   Example: UPPER(TRIM(${col?.source_column})) or CAST(${col?.source_column} AS DATE)
                   Return JSON: {"sql": "expression_here"}`
      })
      const expr = r.data?.sql || ''
      setAiTransformResult(prev => ({ ...prev, [key]: expr }))
    } catch (e) {
      setAiTransformResult(prev => ({ ...prev, [key]: 'Error generating expression' }))
    }
    setAiTransforming(null)
  }

  const acceptAiTransform = (mapIdx, colIdx) => {
    const key    = `${mapIdx}-${colIdx}`
    const result = aiTransformResult[key]
    if (!result) return
    updateMappingCell(mapIdx, colIdx, 'transform_rule', 'custom')
    updateMappingCell(mapIdx, colIdx, 'transform_expression', result)
    setAiTransformKey(null)
    setAiTransformResult(prev => ({ ...prev, [key]: null }))
  }

  const saveMapping = async () => {
    if (!selected) return
    if (!mappingName.trim()) { setError('Enter a mapping name'); return }
    setSavingMapping(true); setError(null)
    try {
      await api.post('/mapping/save', {
        pipeline_id: selected.id,
        name:        mappingName,
        mappings:    { mappings: editedMappings },
        notes:       mappingNotes
      })
      setMappingMsg('✓ Mapping saved as new version')
      setTimeout(() => setMappingMsg(''), 4000)
      const r = await api.get(`/mapping/list/${selected.id}`)
      setMappingVersions(r.data.mappings || [])
    } catch (e) { setError('Could not save mapping: ' + (e.response?.data?.detail || e.message)) }
    setSavingMapping(false)
  }

  const activateMapping = async (mappingId) => {
    try {
      await api.post(`/mapping/activate/${mappingId}`)
      const r = await api.get(`/mapping/list/${selected.id}`)
      setMappingVersions(r.data.mappings || [])
      setMappingMsg('✓ Mapping version activated')
      setTimeout(() => setMappingMsg(''), 3000)
    } catch (e) { setError('Could not activate: ' + (e.response?.data?.detail || e.message)) }
  }

  const loadMappingVersion = async (mappingId) => {
    try {
      const r = await api.get(`/mapping/${mappingId}`)
      const raw = r.data.mappings?.mappings || []
      setEditedMappings(raw)
      setMappingMsg('✓ Loaded mapping version into editor')
      setTimeout(() => setMappingMsg(''), 3000)
    } catch (e) { setError('Could not load mapping') }
  }

  // ── Version actions ────────────────────────────────────────────────────────

  const saveVersion = async () => {
    if (!selected) return
    setSavingVersion(true); setError(null)
    try {
      const r = await api.post('/version/save', {
        pipeline_id:    selected.id,
        version_label:  versionLabel,
        change_summary: versionNotes
      })
      setSavedMsg(`✓ Saved as ${r.data.label}`)
      setTimeout(() => setSavedMsg(''), 4000)
      setVersionLabel(''); setVersionNotes('')
      const vr = await api.get(`/version/list/${selected.id}`)
      setVersions(vr.data.versions || [])
    } catch (e) { setError('Could not save version: ' + (e.response?.data?.detail || e.message)) }
    setSavingVersion(false)
  }

  const rollbackVersion = async (versionId, label) => {
    if (!window.confirm(`Rollback to ${label}? Current pipeline will be replaced.`)) return
    setRollingBack(versionId)
    try {
      await api.post('/version/rollback', { pipeline_id: selected.id, version_id: versionId })
      setSavedMsg(`✓ Rolled back to ${label}`)
      setTimeout(() => setSavedMsg(''), 4000)
      await loadPipelines()
      const vr = await api.get(`/version/list/${selected.id}`)
      setVersions(vr.data.versions || [])
    } catch (e) { setError('Rollback failed: ' + (e.response?.data?.detail || e.message)) }
    setRollingBack(null)
  }

  const compareVersions = async () => {
    if (!compareA || !compareB) { setError('Select two versions to compare'); return }
    try {
      const r = await api.get(`/version/compare/${compareA}/${compareB}`)
      setDiffResult(r.data)
    } catch (e) { setError('Compare failed: ' + (e.response?.data?.detail || e.message)) }
  }

  const close = () => {
    setSelected(null); setMode(null); setSavedMsg(''); setError(null)
    setDiffResult(null); setMappingMsg('')
  }

  return (
    <>
      <PageHeader title="Pipelines" subtitle="Manage, edit, version, and execute your saved ETL pipelines" />
      <PageBody>
        {error && (
          <div style={errBox}>{error}
            <button style={{ float:'right', background:'none', border:'none', cursor:'pointer', color:'#991b1b' }}
              onClick={() => setError(null)}>✕</button>
          </div>
        )}

        {loading ? (
          <div style={{ fontSize: 12, color: '#888' }}>⏳ Loading...</div>
        ) : pipelines.length === 0 ? (
          <div style={emptyBox}>
            No pipelines yet. Create one in the ETL Agent.
            <br />
            <button style={{ ...btnPrimary, marginTop: 12 }} onClick={() => navigate('/agent')}>
              Go to ETL Agent →
            </button>
          </div>
        ) : (
          <>
            {/* Export / Import button */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
              <button style={btnGhost} onClick={() => setShowExportImport(true)}>
                📦 Export / Import
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: selected ? '380px 1fr' : '1fr', gap: 16 }}>

            {/* ── Pipeline list ── */}
            <div>
              {pipelines.map(p => (
                <div key={p.id} style={{ ...card,
                  borderColor: selected?.id === p.id ? '#185FA5' : '#e5e7eb',
                  background:  selected?.id === p.id ? '#F6FAFE' : '#fff' }}>

                  {/* Delete confirm */}
                  {confirmDelete?.id === p.id && (
                    <div style={{ background: '#FEF2F2', border: '1px solid #FCA5A5',
                      borderRadius: 6, padding: '10px 14px', marginBottom: 10 }}>
                      <div style={{ fontSize: 12, color: '#991b1b', fontWeight: 600, marginBottom: 6 }}>
                        🗑 Delete "{p.name}"?
                      </div>
                      <div style={{ fontSize: 11, color: '#991b1b', marginBottom: 8 }}>
                        Removes pipeline, cache and versions. Run logs kept.
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button style={{ ...btnDanger, fontSize: 10, padding: '4px 12px' }}
                          onClick={() => deletePipeline(p)} disabled={deleting === p.id}>
                          {deleting === p.id ? '⏳ Deleting...' : '🗑 Yes, delete'}
                        </button>
                        <button style={btnGhostSmall} onClick={() => setConfirmDelete(null)}>Cancel</button>
                      </div>
                    </div>
                  )}

                  <div style={{ display: 'flex', justifyContent: 'space-between',
                    alignItems: 'flex-start', marginBottom: 8 }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: '#111' }}>{p.name}</div>
                      <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>
                        Created {new Date(p.created_at).toLocaleDateString()} · {p.schedule}
                        {p.current_version > 1 && ` · v${p.current_version}`}
                      </div>
                      <div style={{ fontSize: 10, color: '#888' }}>
                        {p.artifacts?.sql_scripts?.scripts?.length || 0} scripts
                        {p.source_tables?.length > 0 && ` · ${p.source_tables.length} tables`}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ ...statusChip,
                        background: p.is_active ? '#EAF3DE' : '#f3f4f6',
                        color:      p.is_active ? '#27500A' : '#888' }}>
                        {p.is_active ? 'Active' : 'Inactive'}
                      </span>
                      <button title="Delete pipeline"
                        style={{ ...btnDangerGhost, padding: '2px 7px', fontSize: 12 }}
                        onClick={() => setConfirmDelete(confirmDelete?.id === p.id ? null : p)}>
                        🗑
                      </button>
                    </div>
                  </div>

                  {/* Final execution result message (after a run finishes) */}
                  {execMsg[p.id] && !activeRuns[p.id] && (
                    <div style={{ fontSize: 11, marginBottom: 8,
                      color: execMsg[p.id].startsWith('✓') ? '#3B6D11'
                           : execMsg[p.id].startsWith('⏹') ? '#854F0B' : '#A32D2D' }}>
                      {execMsg[p.id]}
                    </div>
                  )}

                  {/* Action buttons */}
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                    <button style={btnGhostSmall} onClick={() => navigate('/logs')}>📜 Logs</button>
                    <button style={btnGhostSmall} onClick={() => openRefresh(p)}>🔄 Refresh</button>
                    <button style={btnGhostSmall} onClick={() => openSqlEditor(p)}>✎ SQL</button>
                    <button style={btnGhostSmall} onClick={() => openRerun(p)}>🤖 Re-run AI</button>
                    <button style={btnGhostSmall} onClick={() => openMappings(p)}>🗺 Mappings</button>
                    <button style={btnGhostSmall} onClick={() => openVersions(p)}>🕐 Versions</button>
                    <button style={{ ...btnPrimary, fontSize: 10, padding: '4px 10px' }}
                      onClick={() => executePipeline(p.id)}
                      disabled={executing === p.id || !!activeRuns[p.id]}>
                      {executing === p.id ? '⏳ Starting...'
                        : activeRuns[p.id] ? '⚙️ Running...'
                        : '▶ Execute'}
                    </button>
                  </div>

                  {/* Live execution log — appears directly under this card
                      while its background run is active */}
                  {activeRuns[p.id] && (
                    <LiveExecutionPanel
                      runId={activeRuns[p.id]}
                      onFinished={(payload) => handleExecutionFinished(p.id, activeRuns[p.id], payload)}
                    />
                  )}
                </div>
              ))}
            </div>

            {/* ── Right panel ── */}
            {selected && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between',
                  alignItems: 'center', marginBottom: 10 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>
                    {mode === 'sql'      && `✎ Edit SQL — ${selected.name}`}
                    {mode === 'rerun'    && `🤖 Re-run AI — ${selected.name}`}
                    {mode === 'refresh'  && `🔄 Refresh tables — ${selected.name}`}
                    {mode === 'mappings' && `🗺 ETL Mappings — ${selected.name}`}
                    {mode === 'versions' && `🕐 Version History — ${selected.name}`}
                  </div>
                  <button style={btnGhostSmall} onClick={close}>✕ Close</button>
                </div>

                {savedMsg  && <div style={successBox}>{savedMsg}</div>}
                {refreshMsg && <div style={refreshMsg.startsWith('✓') ? successBox : errBox}>{refreshMsg}</div>}
                {mappingMsg && <div style={successBox}>{mappingMsg}</div>}

                {/* ── SQL Editor ── */}
                {mode === 'sql' && (
                  <div style={card}>
                    {scripts.length > 0 ? (
                      <>
                        <div style={{ display: 'flex', gap: 4, marginBottom: 10, flexWrap: 'wrap' }}>
                          {scripts.map((s, i) => (
                            <button key={i}
                              onClick={() => { setActiveScript(i); setEditedSql(s.sql || '') }}
                              style={{ padding: '4px 10px', fontSize: 10, borderRadius: 6,
                                cursor: 'pointer',
                                background: i === activeScript ? '#185FA5' : '#fff',
                                color:      i === activeScript ? '#fff' : '#555',
                                border: '1px solid #d1d5db' }}>
                              {s.name || `script_${i+1}`}
                            </button>
                          ))}
                        </div>
                        <div style={{ fontSize: 10, color: '#888', marginBottom: 6 }}>
                          {scripts[activeScript]?.label || ''} — script {activeScript + 1} of {scripts.length}
                        </div>
                        <textarea
                          style={{ width: '100%', minHeight: 320, fontFamily: 'monospace',
                            fontSize: 11, background: '#1e1e1e', color: '#d4d4d4',
                            padding: 12, borderRadius: 6, border: '1px solid #555',
                            boxSizing: 'border-box', resize: 'vertical' }}
                          value={editedSql} onChange={e => setEditedSql(e.target.value)} />
                        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                          <button style={{ ...btnPrimary, background: '#3B6D11' }}
                            onClick={saveEditedSql} disabled={saving}>
                            {saving ? '⏳ Saving...' : '💾 Save SQL'}
                          </button>
                          <button style={btnGhost}
                            onClick={() => setEditedSql(scripts[activeScript]?.sql || '')}>
                            ↺ Revert
                          </button>
                        </div>
                        <div style={{ fontSize: 10, color: '#888', marginTop: 6 }}>
                          ⚠ SQL changes take effect on next execution.
                        </div>
                      </>
                    ) : (
                      <div style={{ fontSize: 12, color: '#888' }}>No SQL scripts saved.</div>
                    )}
                  </div>
                )}

                {/* ── Re-run AI ── */}
                {mode === 'rerun' && (
                  <div style={card}>
                    <div style={{ fontSize: 12, color: '#555', marginBottom: 8, lineHeight: 1.6 }}>
                      Describe what you want to change. AI will redesign the data model and
                      regenerate all SQL scripts. A new version is saved automatically.
                    </div>
                    <div style={{ background: '#FEF3C7', borderRadius: 6, padding: '8px 12px',
                      fontSize: 11, color: '#92400E', marginBottom: 12 }}>
                      💡 Current version: v{selected.current_version || 1} — a new version will be
                      created after AI regeneration so you can rollback if needed.
                    </div>
                    <label style={{ fontSize: 11, fontWeight: 500, color: '#374151',
                      display: 'block', marginBottom: 4 }}>
                      New or updated requirements
                    </label>
                    <textarea style={{ ...ta, minHeight: 140 }} value={newReqs}
                      placeholder="e.g. Add customer_segment to fact table. Exclude failed transactions. Add a loan fact table with outstanding amount."
                      onChange={e => setNewReqs(e.target.value)} />
                    <button style={{ ...btnPrimary, marginTop: 10 }}
                      onClick={rerunAI} disabled={rerunning}>
                      {rerunning ? '⏳ AI regenerating...' : '🤖 Regenerate with AI'}
                    </button>
                    <div style={{ fontSize: 10, color: '#888', marginTop: 6 }}>
                      ⚠ Runs full AI pipeline (Phase 1 + Phase 2). New version auto-saved.
                    </div>
                  </div>
                )}

                {/* ── Refresh ── */}
                {mode === 'refresh' && (
                  <div style={card}>
                    <div style={{ fontSize: 12, color: '#555', marginBottom: 10 }}>
                      Select which tables to re-extract from the source.
                    </div>
                    {tables.length === 0 ? (
                      <div style={{ fontSize: 12, color: '#888' }}>No source tables saved.</div>
                    ) : (
                      <>
                        <div style={{ border: '1px solid #e5e7eb', borderRadius: 6,
                          overflow: 'hidden', marginBottom: 10 }}>
                          {tables.map(t => (
                            <label key={t} style={{ display: 'flex', alignItems: 'center',
                              gap: 10, padding: '8px 12px', borderBottom: '1px solid #f3f4f6',
                              cursor: 'pointer',
                              background: selectedTables.includes(t) ? '#F6FAFE' : '#fff' }}>
                              <input type="checkbox" checked={selectedTables.includes(t)}
                                onChange={e => {
                                  if (e.target.checked) setSelectedTables(prev => [...prev, t])
                                  else setSelectedTables(prev => prev.filter(x => x !== t))
                                }} />
                              <span style={{ fontFamily: 'monospace', fontSize: 12,
                                color: selectedTables.includes(t) ? '#185FA5' : '#555' }}>{t}</span>
                              {selectedTables.includes(t) &&
                                <span style={{ fontSize: 9, color: '#3B6D11' }}>→ stg_{t} will refresh</span>}
                            </label>
                          ))}
                        </div>
                        <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
                          <button style={btnGhostSmall} onClick={() => setSelectedTables([...tables])}>Select all</button>
                          <button style={btnGhostSmall} onClick={() => setSelectedTables([])}>Clear all</button>
                        </div>
                        <button style={{ ...btnPrimary, background: '#3B6D11' }}
                          onClick={runRefresh} disabled={refreshing}>
                          {refreshing ? '⏳ Refreshing...' : `🔄 Refresh ${selectedTables.length} table(s)`}
                        </button>
                      </>
                    )}
                  </div>
                )}

                {/* ── Mappings tab ── */}
                {mode === 'mappings' && (
                  <div>
                    {mappingVersions.length > 0 && (
                      <div style={{ ...card, marginBottom: 10 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
                          Saved Mapping Versions
                        </div>
                        {mappingVersions.map(mv => (
                          <div key={mv.id} style={{ display: 'flex', alignItems: 'center',
                            gap: 8, padding: '5px 0',
                            borderBottom: '1px solid #f3f4f6' }}>
                            <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 10,
                              background: mv.is_active ? '#EAF3DE' : '#f3f4f6',
                              color: mv.is_active ? '#27500A' : '#888', fontWeight: 600 }}>
                              v{mv.version}
                            </span>
                            <span style={{ fontSize: 11, flex: 1, color: '#374151' }}>{mv.name}</span>
                            <span style={{ fontSize: 10, color: '#888' }}>
                              {new Date(mv.created_at).toLocaleDateString()}
                            </span>
                            <button style={btnGhostSmall}
                              onClick={() => loadMappingVersion(mv.id)}>
                              Load
                            </button>
                            {!mv.is_active && (
                              <button style={btnGhostSmall}
                                onClick={() => activateMapping(mv.id)}>
                                Activate
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    <div style={card}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: '#374151', marginBottom: 10 }}>
                        Column Mappings — Edit Transform Rules
                      </div>

                      {editedMappings.length === 0 ? (
                        <div style={{ fontSize: 12, color: '#888', padding: '10px 0' }}>
                          No mappings found. Run the ETL Agent first to generate mappings.
                        </div>
                      ) : (
                        editedMappings.map((mapping, mapIdx) => (
                          <div key={mapIdx} style={{ marginBottom: 16 }}>
                            <div style={{ fontSize: 11, fontWeight: 700, color: '#185FA5',
                              marginBottom: 6, padding: '4px 8px', background: '#EBF4FF',
                              borderRadius: 4 }}>
                              {mapping.target_table}
                            </div>
                            <table style={tbl}>
                              <thead>
                                <tr>
                                  {['Source Table', 'Source Column', 'Target Column', 'Transform Rule / Expression'].map(h => (
                                    <th key={h} style={th}>{h}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {(mapping.columns || []).map((col, colIdx) => {
                                  const key        = `${mapIdx}-${colIdx}`
                                  const rule       = col.transform_rule || 'direct'
                                  const isAiMode   = aiTransformKey === key
                                  const aiResult   = aiTransformResult[key]
                                  const needsExpr  = ['CAST','COALESCE','custom'].includes(rule)

                                  return (
                                    <tr key={colIdx} style={{
                                      background: rule === 'exclude' ? '#FEF2F2' : 'transparent'
                                    }}>
                                      <td style={td}>
                                        <code style={codeStyle}>{col.source_table?.replace('staging.', '')}</code>
                                      </td>
                                      <td style={td}>
                                        <code style={codeStyle}>{col.source_column}</code>
                                      </td>
                                      <td style={td}>
                                        <input
                                          value={col.target_column || ''}
                                          onChange={e => updateMappingCell(mapIdx, colIdx, 'target_column', e.target.value)}
                                          style={{ ...inpSmall, width: '100%',
                                            textDecoration: rule === 'exclude' ? 'line-through' : 'none',
                                            color: rule === 'exclude' ? '#aaa' : '#111' }} />
                                      </td>
                                      <td style={{ ...td, minWidth: 280 }}>
                                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                          <select
                                            value={rule}
                                            onChange={e => {
                                              updateMappingCell(mapIdx, colIdx, 'transform_rule', e.target.value)
                                              if (e.target.value !== 'ai') setAiTransformKey(null)
                                            }}
                                            style={{ ...inpSmall, flex: 1, minWidth: 100,
                                              color: rule === 'exclude' ? '#991B1B' :
                                                     rule === 'ai'     ? '#185FA5' : '#111' }}>
                                            <optgroup label="Simple">
                                              <option value="direct">direct — copy as-is</option>
                                              <option value="UPPER">UPPER(column)</option>
                                              <option value="LOWER">LOWER(column)</option>
                                              <option value="TRIM">TRIM(column)</option>
                                              <option value="exclude">exclude — skip column</option>
                                            </optgroup>
                                            <optgroup label="Expression needed">
                                              <option value="CAST">CAST(column AS ...)</option>
                                              <option value="COALESCE">COALESCE(column, ...)</option>
                                              <option value="custom">custom SQL expression</option>
                                            </optgroup>
                                            <optgroup label="AI">
                                              <option value="ai">🤖 AI transform (natural language)</option>
                                            </optgroup>
                                            <optgroup label="Lookup">
                                              <option value="lookup">lookup (dim surrogate key)</option>
                                            </optgroup>
                                          </select>
                                        </div>

                                        {needsExpr && (
                                          <div style={{ marginTop: 4 }}>
                                            <input
                                              value={col.transform_expression || ''}
                                              placeholder={
                                                rule === 'CAST'     ? 'e.g. INTEGER, DATE, NUMERIC(10,2)' :
                                                rule === 'COALESCE' ? 'e.g. 0, "unknown", current_date' :
                                                'e.g. UPPER(TRIM(column))'
                                              }
                                              onChange={e => updateMappingCell(mapIdx, colIdx, 'transform_expression', e.target.value)}
                                              style={{ ...inpSmall, width: '100%', fontFamily: 'monospace', fontSize: 10 }} />
                                            {col.transform_expression && (
                                              <div style={{ fontSize: 9, color: '#185FA5',
                                                fontFamily: 'monospace', marginTop: 2, padding: '2px 4px',
                                                background: '#EBF4FF', borderRadius: 3 }}>
                                                Preview: {
                                                  rule === 'CAST'     ? `CAST(${col.source_column} AS ${col.transform_expression})` :
                                                  rule === 'COALESCE' ? `COALESCE(${col.source_column}, ${col.transform_expression})` :
                                                  col.transform_expression
                                                }
                                              </div>
                                            )}
                                          </div>
                                        )}

                                        {rule === 'ai' && (
                                          <div style={{ marginTop: 6, padding: '8px 10px',
                                            background: '#EBF4FF', borderRadius: 6,
                                            border: '1px solid #93C5FD' }}>
                                            <div style={{ fontSize: 10, color: '#185FA5',
                                              fontWeight: 600, marginBottom: 4 }}>
                                              🤖 Describe the transformation in plain English
                                            </div>
                                            <div style={{ display: 'flex', gap: 4 }}>
                                              <input
                                                placeholder="e.g. convert to uppercase and trim spaces"
                                                value={aiTransformText[key] || ''}
                                                onChange={e => setAiTransformText(prev => ({
                                                  ...prev, [key]: e.target.value
                                                }))}
                                                onKeyDown={e => e.key === 'Enter' && generateAiTransform(mapIdx, colIdx)}
                                                style={{ ...inpSmall, flex: 1, fontSize: 10 }} />
                                              <button
                                                style={{ ...btnPrimary, padding: '3px 8px', fontSize: 10 }}
                                                onClick={() => generateAiTransform(mapIdx, colIdx)}
                                                disabled={aiTransforming === key}>
                                                {aiTransforming === key ? '⏳' : 'Generate →'}
                                              </button>
                                            </div>

                                            {aiResult && (
                                              <div style={{ marginTop: 6 }}>
                                                <div style={{ fontSize: 9, color: '#555',
                                                  marginBottom: 3 }}>Generated expression:</div>
                                                <div style={{ fontFamily: 'monospace', fontSize: 11,
                                                  background: '#fff', padding: '4px 8px',
                                                  borderRadius: 4, border: '1px solid #93C5FD',
                                                  color: '#185FA5', marginBottom: 4 }}>
                                                  {aiResult}
                                                </div>
                                                <div style={{ display: 'flex', gap: 4 }}>
                                                  <button
                                                    style={{ ...btnPrimary, background: '#27500A',
                                                      padding: '3px 10px', fontSize: 10 }}
                                                    onClick={() => acceptAiTransform(mapIdx, colIdx)}>
                                                    ✓ Accept
                                                  </button>
                                                  <button
                                                    style={{ ...btnGhostSmall, fontSize: 10 }}
                                                    onClick={() => generateAiTransform(mapIdx, colIdx)}>
                                                    ↺ Regenerate
                                                  </button>
                                                  <button
                                                    style={{ ...btnGhostSmall, fontSize: 10 }}
                                                    onClick={() => setAiTransformResult(prev => ({ ...prev, [key]: null }))}>
                                                    ✕ Dismiss
                                                  </button>
                                                </div>
                                              </div>
                                            )}

                                            {!aiResult && !aiTransforming && (
                                              <div style={{ marginTop: 6, display: 'flex',
                                                gap: 4, flexWrap: 'wrap' }}>
                                                {[
                                                  'convert to uppercase',
                                                  'extract year from date',
                                                  'if null use 0',
                                                  'round to 2 decimals',
                                                  'convert to date format YYYY-MM-DD',
                                                ].map(s => (
                                                  <button key={s}
                                                    style={{ fontSize: 9, padding: '2px 6px',
                                                      borderRadius: 10, cursor: 'pointer',
                                                      background: '#fff', color: '#185FA5',
                                                      border: '1px solid #93C5FD' }}
                                                    onClick={() => {
                                                      setAiTransformText(prev => ({ ...prev, [key]: s }))
                                                      setTimeout(() => generateAiTransform(mapIdx, colIdx), 100)
                                                    }}>
                                                    {s}
                                                  </button>
                                                ))}
                                              </div>
                                            )}
                                          </div>
                                        )}

                                        {rule === 'custom' && col.transform_expression && !needsExpr && (
                                          <div style={{ fontSize: 9, fontFamily: 'monospace',
                                            color: '#185FA5', marginTop: 2,
                                            padding: '2px 4px', background: '#EBF4FF',
                                            borderRadius: 3 }}>
                                            {col.transform_expression}
                                          </div>
                                        )}
                                      </td>
                                    </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                          </div>
                        ))
                      )}

                      {editedMappings.length > 0 && (
                        <div style={{ borderTop: '1px solid #e5e7eb', paddingTop: 12, marginTop: 8 }}>
                          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                            <input placeholder="Mapping name (e.g. Banking ETL v2)"
                              value={mappingName}
                              onChange={e => setMappingName(e.target.value)}
                              style={{ ...inpSmall, flex: 1 }} />
                            <input placeholder="What changed? (optional)"
                              value={mappingNotes}
                              onChange={e => setMappingNotes(e.target.value)}
                              style={{ ...inpSmall, flex: 1 }} />
                          </div>
                          <button style={{ ...btnPrimary, background: '#3B6D11' }}
                            onClick={saveMapping} disabled={savingMapping}>
                            {savingMapping ? '⏳ Saving...' : '💾 Save Mapping Version'}
                          </button>
                          <span style={{ fontSize: 10, color: '#888', marginLeft: 10 }}>
                            Saves current mapping as a new version
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* ── Versions tab ── */}
                {mode === 'versions' && (
                  <div>
                    <div style={card}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
                        Save Current Design as Version
                      </div>
                      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                        <input placeholder="Version label (e.g. Added loan fact table)"
                          value={versionLabel}
                          onChange={e => setVersionLabel(e.target.value)}
                          style={{ ...inpSmall, flex: 1 }} />
                        <input placeholder="Change notes (optional)"
                          value={versionNotes}
                          onChange={e => setVersionNotes(e.target.value)}
                          style={{ ...inpSmall, flex: 1 }} />
                      </div>
                      <button style={btnPrimary} onClick={saveVersion} disabled={savingVersion}>
                        {savingVersion ? '⏳ Saving...' : '💾 Save Version'}
                      </button>
                    </div>

                    {versionsLoading ? (
                      <div style={{ fontSize: 12, color: '#888', padding: 10 }}>⏳ Loading versions...</div>
                    ) : versions.length === 0 ? (
                      <div style={{ ...emptyBox, padding: 16 }}>
                        No versions saved yet. Save a version above.
                      </div>
                    ) : (
                      <div style={card}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: '#374151', marginBottom: 10 }}>
                          Version History
                        </div>

                        <div style={{ display: 'flex', gap: 8, marginBottom: 12,
                          padding: '8px 10px', background: '#f9fafb', borderRadius: 6 }}>
                          <span style={{ fontSize: 10, color: '#888', alignSelf: 'center' }}>Compare:</span>
                          <select value={compareA || ''} onChange={e => setCompareA(e.target.value)}
                            style={{ ...inpSmall, flex: 1 }}>
                            <option value="">Select version A</option>
                            {versions.map(v => (
                              <option key={v.id} value={v.id}>{v.version_label || `v${v.version}`}</option>
                            ))}
                          </select>
                          <span style={{ fontSize: 10, color: '#888', alignSelf: 'center' }}>vs</span>
                          <select value={compareB || ''} onChange={e => setCompareB(e.target.value)}
                            style={{ ...inpSmall, flex: 1 }}>
                            <option value="">Select version B</option>
                            {versions.map(v => (
                              <option key={v.id} value={v.id}>{v.version_label || `v${v.version}`}</option>
                            ))}
                          </select>
                          <button style={btnGhostSmall} onClick={compareVersions}>Compare</button>
                        </div>

                        {diffResult && (
                          <div style={{ background: '#F8FAFC', borderRadius: 6,
                            padding: '10px 12px', marginBottom: 12,
                            border: '1px solid #e5e7eb' }}>
                            <div style={{ fontSize: 11, fontWeight: 600, color: '#374151', marginBottom: 6 }}>
                              Diff: {diffResult.version_a?.label || `v${diffResult.version_a?.version}`}
                              {' → '}
                              {diffResult.version_b?.label || `v${diffResult.version_b?.version}`}
                            </div>
                            {Object.entries(diffResult.diff || {}).map(([key, val]) => {
                              if (!val || (Array.isArray(val) && val.length === 0) || val === false) return null
                              return (
                                <div key={key} style={{ fontSize: 11, color: '#374151', marginBottom: 3 }}>
                                  <span style={{ color: '#888' }}>{key.replace(/_/g, ' ')}: </span>
                                  {Array.isArray(val)
                                    ? val.map(v => (
                                        <span key={v} style={{ fontSize: 10, padding: '1px 6px',
                                          borderRadius: 10, background: '#EAF3DE',
                                          color: '#27500A', marginRight: 4 }}>{v}</span>
                                      ))
                                    : <span style={{ color: '#991B1B' }}>{String(val)}</span>
                                  }
                                </div>
                              )
                            })}
                          </div>
                        )}

                        {versions.map((v, i) => (
                          <div key={v.id} style={{ display: 'flex', alignItems: 'flex-start',
                            gap: 10, padding: '10px 0',
                            borderBottom: i < versions.length - 1 ? '1px solid #f3f4f6' : 'none' }}>
                            <div style={{ display: 'flex', flexDirection: 'column',
                              alignItems: 'center', paddingTop: 2 }}>
                              <div style={{ width: 10, height: 10, borderRadius: '50%',
                                background: v.is_active ? '#185FA5' : '#d1d5db',
                                border: '2px solid', flexShrink: 0,
                                borderColor: v.is_active ? '#185FA5' : '#d1d5db' }} />
                              {i < versions.length - 1 && (
                                <div style={{ width: 2, height: 24, background: '#e5e7eb', marginTop: 2 }} />
                              )}
                            </div>

                            <div style={{ flex: 1 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                                <span style={{ fontSize: 12, fontWeight: 600, color: '#111' }}>
                                  {v.version_label || `v${v.version}`}
                                </span>
                                {v.is_active && (
                                  <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 10,
                                    background: '#EAF3DE', color: '#27500A', fontWeight: 600 }}>
                                    Active
                                  </span>
                                )}
                                <span style={{ fontSize: 9, color: '#888' }}>
                                  {v.fact_count} facts · {v.dim_count} dims · {v.script_count} scripts
                                </span>
                              </div>
                              {v.change_summary && (
                                <div style={{ fontSize: 10, color: '#555', marginBottom: 3 }}>
                                  {v.change_summary}
                                </div>
                              )}
                              <div style={{ fontSize: 9, color: '#aaa' }}>
                                {new Date(v.created_at).toLocaleString()}
                              </div>
                            </div>

                            <div style={{ display: 'flex', gap: 5 }}>
                              {!v.is_active && (
                                <button style={{ ...btnGhostSmall, color: '#185FA5',
                                  borderColor: '#185FA5' }}
                                  onClick={() => rollbackVersion(v.id, v.version_label || `v${v.version}`)}
                                  disabled={rollingBack === v.id}>
                                  {rollingBack === v.id ? '⏳' : '↩ Rollback'}
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {showExportImport && (
            <ExportImportModal
              onClose={() => setShowExportImport(false)}
              onImported={loadPipelines}
            />
          )}
          </>
        )}
      </PageBody>
    </>
  )
}

const ta           = { width: '100%', padding: '8px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, fontFamily: 'system-ui', resize: 'vertical', boxSizing: 'border-box' }
const card         = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 10 }
const errBox       = { background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#991b1b', marginBottom: 10 }
const successBox   = { background: '#EAF3DE', border: '1px solid #a7d9a0', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#27500A', marginBottom: 10 }
const emptyBox     = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 30, textAlign: 'center', fontSize: 13, color: '#888' }
const statusChip   = { padding: '2px 8px', borderRadius: 20, fontSize: 9, fontWeight: 500 }
const btnPrimary   = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhost     = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnGhostSmall = { padding: '4px 10px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 10, cursor: 'pointer' }
const btnDanger    = { padding: '7px 14px', background: '#DC2626', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnDangerGhost = { background: '#fff', color: '#DC2626', border: '1px solid #FCA5A5', borderRadius: 6, cursor: 'pointer', fontSize: 11 }
const tbl          = { width: '100%', borderCollapse: 'collapse', fontSize: 11 }
const th           = { textAlign: 'left', padding: '5px 8px', background: '#f9fafb', borderBottom: '1px solid #e5e7eb', fontWeight: 600, color: '#374151', fontSize: 10 }
const td           = { padding: '5px 8px', borderBottom: '1px solid #f3f4f6', fontSize: 11 }
const codeStyle    = { fontFamily: 'monospace', fontSize: 10, background: '#f3f4f6', padding: '1px 5px', borderRadius: 4, color: '#185FA5' }
const inpSmall     = { padding: '4px 8px', fontSize: 11, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box' }
