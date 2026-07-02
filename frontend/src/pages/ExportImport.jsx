/**
 * ExportImport.jsx — Pipeline Export / Import modal
 * Drop this component into Pipelines.jsx (or any page that has the pipeline list).
 *
 * Usage in Pipelines.jsx:
 *   import { ExportImportModal } from './ExportImport'  (or inline it)
 *   // Add to state: const [showExportImport, setShowExportImport] = useState(false)
 *   // Add button in header or pipeline card: <button onClick={() => setShowExportImport(true)}>📦 Export/Import</button>
 *   // Render modal: <ExportImportModal onClose={() => setShowExportImport(false)} onImported={loadPipelines} />
 */

import { useState, useEffect } from 'react'
import api from '../api/api'

export function ExportImportModal({ onClose, onImported }) {
  const [tab,          setTab]          = useState('export')   // export | import
  const [pipelines,    setPipelines]    = useState([])
  const [connectors,   setConnectors]   = useState([])
  const [loading,      setLoading]      = useState(true)
  const [exporting,    setExporting]    = useState(null)       // pipeline id being exported
  const [error,        setError]        = useState(null)
  const [successMsg,   setSuccessMsg]   = useState('')

  // Import state
  const [bundleJson,   setBundleJson]   = useState('')         // pasted JSON text
  const [bundle,       setBundle]       = useState(null)       // parsed bundle
  const [parseError,   setParseError]   = useState('')
  const [srcConnector, setSrcConnector] = useState('')
  const [tgtConnector, setTgtConnector] = useState('')
  const [nameOverride, setNameOverride] = useState('')
  const [importing,    setImporting]    = useState(false)

  useEffect(() => {
    Promise.all([
      api.get('/pipeline/export-list'),
      api.get('/connector/list'),
    ]).then(([pRes, cRes]) => {
      setPipelines(pRes.data.pipelines || [])
      setConnectors(cRes.data.connectors || [])
    }).catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const exportPipeline = async (pipelineId, pipelineName) => {
    setExporting(pipelineId); setError(null)
    try {
      // Use axios (which already has auth headers configured) with responseType blob
      // to download the export JSON as a file — avoids the 401 that raw fetch
      // gets because it doesn't send the Authorization header automatically.
      const res = await api.get(`/pipeline/export/${pipelineId}`, {
        responseType: 'blob'
      })
      const url  = URL.createObjectURL(new Blob([res.data], { type: 'application/json' }))
      const a    = document.createElement('a')
      a.href     = url
      a.download = `${pipelineName.replace(/\s+/g, '_')}_aibridge_export.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      setSuccessMsg(`✓ "${pipelineName}" exported successfully`)
      setTimeout(() => setSuccessMsg(''), 4000)
    } catch (e) {
      setError('Export failed: ' + (e.response?.data?.detail || e.message || String(e)))
    }
    setExporting(null)
  }

  const parseBundle = (text) => {
    setBundleJson(text)
    setParseError('')
    setBundle(null)
    if (!text.trim()) return
    try {
      const parsed = JSON.parse(text)
      if (parsed.aibridge_export_version !== '1.0') {
        setParseError('Not a valid AIBridge export file (missing aibridge_export_version: 1.0)')
        return
      }
      setBundle(parsed)
      setNameOverride(parsed.pipeline?.name ? `${parsed.pipeline.name} (imported)` : '')
      // Auto-suggest connector mappings by type matching
      const srcHint = parsed.connectors?.source
      const tgtHint = parsed.connectors?.target
      if (srcHint) {
        const match = connectors.find(c =>
          c.connector_type === srcHint.connector_type && c.role !== 'target'
        )
        if (match) setSrcConnector(match.id)
      }
      if (tgtHint) {
        const match = connectors.find(c =>
          c.connector_type === tgtHint.connector_type && c.role !== 'source'
        )
        if (match) setTgtConnector(match.id)
      }
    } catch (e) {
      setParseError('Invalid JSON: ' + e.message)
    }
  }

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => parseBundle(ev.target.result)
    reader.readAsText(file)
  }

  const importPipeline = async () => {
    if (!bundle) { setError('Paste or upload a valid export file first'); return }
    setImporting(true); setError(null)
    try {
      const r = await api.post('/pipeline/import', {
        bundle,
        connector_map: {
          source: srcConnector || undefined,
          target: tgtConnector || undefined,
        },
        name_override: nameOverride || '',
      })
      setSuccessMsg(`✓ ${r.data.message}`)
      setBundleJson(''); setBundle(null); setNameOverride('')
      if (onImported) onImported()
      setTimeout(() => setSuccessMsg(''), 5000)
    } catch (e) {
      setError('Import failed: ' + (e.response?.data?.detail || e.message))
    }
    setImporting(false)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: '#fff', borderRadius: 12, width: '90vw', maxWidth: 700,
        maxHeight: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Header */}
        <div style={{ padding: '14px 18px', borderBottom: '1px solid #e5e7eb',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>📦 Pipeline Export / Import</div>
            <div style={{ fontSize: 11, color: '#888' }}>Move pipelines between environments</div>
          </div>
          <button style={btnGhost} onClick={onClose}>✕ Close</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid #e5e7eb' }}>
          {[{id:'export',label:'⬇ Export'},{id:'import',label:'⬆ Import'}].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              style={{ padding: '10px 20px', fontSize: 12, cursor: 'pointer', border: 'none',
                borderBottom: tab === t.id ? '2px solid #185FA5' : '2px solid transparent',
                background: 'transparent',
                color: tab === t.id ? '#185FA5' : '#888', fontWeight: tab === t.id ? 600 : 400 }}>
              {t.label}
            </button>
          ))}
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: '16px 18px' }}>
          {error && <div style={errBox}>{error}</div>}
          {successMsg && <div style={successBox}>{successMsg}</div>}

          {/* ── EXPORT TAB ── */}
          {tab === 'export' && (
            <>
              <div style={{ fontSize: 12, color: '#555', marginBottom: 14, lineHeight: 1.6 }}>
                Export a pipeline as a JSON bundle — includes the data model, SQL scripts,
                ETL mappings, and version snapshot. <strong>Credentials are not included.</strong>
                Use Import on the destination to re-map connectors.
              </div>
              {loading ? (
                <div style={{ fontSize: 12, color: '#888' }}>⏳ Loading...</div>
              ) : pipelines.length === 0 ? (
                <div style={emptyBox}>No pipelines to export.</div>
              ) : pipelines.map(p => (
                <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 10,
                  padding: '10px 12px', border: '1px solid #e5e7eb', borderRadius: 8, marginBottom: 8 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{p.name}</div>
                    <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>
                      {p.script_count} scripts · v{p.current_version}
                      {p.source_connector && ` · ${p.source_connector}`}
                      {p.target_connector && ` → ${p.target_connector}`}
                    </div>
                  </div>
                  <button
                    style={{ ...btnPrimary, fontSize: 10, padding: '5px 12px' }}
                    onClick={() => exportPipeline(p.id, p.name)}
                    disabled={exporting === p.id}>
                    {exporting === p.id ? '⏳ Exporting...' : '⬇ Export JSON'}
                  </button>
                </div>
              ))}
            </>
          )}

          {/* ── IMPORT TAB ── */}
          {tab === 'import' && (
            <>
              <div style={{ fontSize: 12, color: '#555', marginBottom: 14, lineHeight: 1.6 }}>
                Import a pipeline from an AIBridge export JSON file. Map the source and target
                connectors to ones in this environment — the pipeline's SQL scripts will be ready
                to execute immediately after import.
              </div>

              {/* File upload or paste */}
              <div style={{ ...card, marginBottom: 10 }}>
                <div style={sectionTitle}>1. Load export file</div>
                <input type="file" accept=".json"
                  style={{ display: 'block', marginBottom: 10, fontSize: 11 }}
                  onChange={handleFileUpload} />
                <div style={{ fontSize: 10, color: '#888', marginBottom: 6 }}>
                  Or paste the JSON content directly:
                </div>
                <textarea
                  style={{ width: '100%', minHeight: 100, fontFamily: 'monospace', fontSize: 10,
                    border: `1px solid ${parseError ? '#fca5a5' : '#d1d5db'}`, borderRadius: 6,
                    padding: 8, boxSizing: 'border-box', resize: 'vertical' }}
                  placeholder='{"aibridge_export_version": "1.0", ...}'
                  value={bundleJson}
                  onChange={e => parseBundle(e.target.value)}
                />
                {parseError && <div style={{ fontSize: 11, color: '#991b1b', marginTop: 4 }}>{parseError}</div>}
                {bundle && (
                  <div style={{ marginTop: 8, padding: '8px 10px', background: '#EAF3DE',
                    borderRadius: 6, fontSize: 11, color: '#27500A' }}>
                    ✓ Valid export — <strong>{bundle.pipeline?.name}</strong>
                    {' '}· {bundle.version_snapshot?.sql_scripts?.scripts?.length || 0} scripts
                    · exported {bundle.exported_at?.slice(0,10)}
                  </div>
                )}
              </div>

              {bundle && (
                <>
                  {/* Connector mapping */}
                  <div style={{ ...card, marginBottom: 10 }}>
                    <div style={sectionTitle}>2. Map connectors</div>
                    <div style={{ fontSize: 10, color: '#888', marginBottom: 10 }}>
                      The export came from: source={bundle.connectors?.source?.name || 'none'} ({bundle.connectors?.source?.connector_type || '?'})
                      {bundle.connectors?.target && ` → target=${bundle.connectors.target.name} (${bundle.connectors.target.connector_type})`}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                      <div>
                        <label style={labelStyle}>Source connector (this environment)</label>
                        <select style={inp} value={srcConnector} onChange={e => setSrcConnector(e.target.value)}>
                          <option value="">— none / same as target —</option>
                          {connectors.map(c => (
                            <option key={c.id} value={c.id}>
                              {c.name} ({c.connector_type}) · {c.role}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label style={labelStyle}>Target connector (warehouse)</label>
                        <select style={inp} value={tgtConnector} onChange={e => setTgtConnector(e.target.value)}>
                          <option value="">— same as source —</option>
                          {connectors.filter(c => c.connector_type !== 'duckdb').map(c => (
                            <option key={c.id} value={c.id}>
                              {c.name} ({c.connector_type}) · {c.role}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>

                  {/* Name + import */}
                  <div style={card}>
                    <div style={sectionTitle}>3. Pipeline name</div>
                    <input style={{ ...inp, marginBottom: 12 }}
                      value={nameOverride}
                      onChange={e => setNameOverride(e.target.value)}
                      placeholder="Pipeline name in this environment" />
                    <button style={btnPrimary} onClick={importPipeline} disabled={importing}>
                      {importing ? '⏳ Importing...' : '⬆ Import pipeline'}
                    </button>
                    <div style={{ fontSize: 10, color: '#888', marginTop: 6 }}>
                      A v1 version snapshot will be auto-saved on import.
                    </div>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

const inp          = { width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box' }
const card         = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }
const errBox       = { background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#991b1b', marginBottom: 10 }
const successBox   = { background: '#EAF3DE', border: '1px solid #a7d9a0', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#27500A', marginBottom: 10 }
const emptyBox     = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 20, textAlign: 'center', fontSize: 12, color: '#888' }
const sectionTitle = { fontSize: 10, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }
const labelStyle   = { display: 'block', fontSize: 11, fontWeight: 500, color: '#374151', marginBottom: 4 }
const btnPrimary   = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhost     = { padding: '6px 12px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
