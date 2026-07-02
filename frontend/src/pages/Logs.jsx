/**
 * Logs.jsx — Pipeline execution logs viewer
 *
 * Shows all pipeline runs with status, timestamps, duration.
 * Click any run to see full log lines + recovery agent activity.
 * Auto-refreshes every 5 seconds.
 * Features: white log, maximize, download as text
 */

import { useState, useEffect, useMemo } from 'react'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'

export default function Logs() {
  const [runs,          setRuns]          = useState([])
  const [loading,       setLoading]       = useState(true)
  const [selectedRun,   setSelectedRun]   = useState(null)
  const [runDetail,     setRunDetail]     = useState(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [filter,        setFilter]        = useState('all')
  const [searchTerm,    setSearchTerm]    = useState('')
  const [autoRefresh,   setAutoRefresh]   = useState(true)
  const [maximized,     setMaximized]     = useState(false)

  const loadRuns = async () => {
    try {
      const r = await api.get('/pipeline/runs')
      setRuns(r.data.runs || [])
    } catch (e) {
      console.error('Could not load runs:', e)
    } finally {
      setLoading(false)
    }
  }

  const loadDetail = async (runId) => {
    setLoadingDetail(true)
    try {
      const r = await api.get(`/pipeline/run/${runId}`)
      setRunDetail(r.data)
    } catch (e) {
      console.error('Could not load run detail:', e)
      setRunDetail(null)
    }
    setLoadingDetail(false)
  }

  useEffect(() => {
    loadRuns()
    if (!autoRefresh) return
    const t = setInterval(loadRuns, 5000)
    return () => clearInterval(t)
  }, [autoRefresh])

  useEffect(() => {
    if (selectedRun) loadDetail(selectedRun)
    else setRunDetail(null)
  }, [selectedRun])

  useEffect(() => {
    if (!selectedRun || !autoRefresh) return
    const status = runDetail?.run?.status
    if (status === 'success' || status === 'failed' || status === 'partial') return
    const t = setInterval(() => loadDetail(selectedRun), 5000)
    return () => clearInterval(t)
  }, [selectedRun, runDetail, autoRefresh])

  const filteredRuns = useMemo(() => {
    let list = runs
    if (filter !== 'all') list = list.filter(r => r.status === filter)
    if (searchTerm) {
      const q = searchTerm.toLowerCase()
      list = list.filter(r =>
        (r.pipeline_name || '').toLowerCase().includes(q) ||
        (r.run_id || '').toLowerCase().includes(q)
      )
    }
    return list
  }, [runs, filter, searchTerm])

  const counts = useMemo(() => ({
    all:     runs.length,
    success: runs.filter(r => r.status === 'success').length,
    partial: runs.filter(r => r.status === 'partial').length,
    failed:  runs.filter(r => r.status === 'failed').length,
  }), [runs])

  const statusColor = (s) => {
    if (s === 'success') return { bg: '#EAF3DE', fg: '#27500A', label: '✓ Success' }
    if (s === 'partial') return { bg: '#FAEEDA', fg: '#854F0B', label: '⚠ Partial' }
    if (s === 'failed')  return { bg: '#FCEBEB', fg: '#A32D2D', label: '✗ Failed'  }
    return { bg: '#E6F1FB', fg: '#185FA5', label: '⏳ Running' }
  }

  const duration = (start, end) => {
    if (!start || !end) return '—'
    const s = new Date(start)
    const e = new Date(end)
    const sec = Math.round((e - s) / 1000)
    if (sec < 60) return `${sec}s`
    if (sec < 3600) return `${Math.floor(sec/60)}m ${sec%60}s`
    return `${Math.floor(sec/3600)}h ${Math.floor((sec%3600)/60)}m`
  }

  const lineColor = (line) => {
    if (line.includes('✗') || line.includes('FAILED') || line.includes('Error')) return '#dc2626'
    if (line.includes('✓')) return '#16a34a'
    if (line.includes('⚠') || line.includes('WARNING')) return '#d97706'
    if (line.includes('🤖')) return '#534AB7'
    if (line.includes('━━━')) return '#185FA5'
    return '#374151'
  }

  const downloadLog = () => {
    if (!runDetail) return
    const text = runDetail.run.log_lines.join('\n')
    const blob = new Blob([text], { type: 'text/plain' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `pipeline_log_${runDetail.run.run_id}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const LogPanel = ({ maxHeight = 500 }) => (
    <div style={{
      background: '#f8fafc', color: '#374151', borderRadius: 6,
      padding: '12px 14px', fontFamily: 'monospace', fontSize: 11,
      maxHeight, overflowY: 'auto', lineHeight: 1.7,
      border: '1px solid #e5e7eb'
    }}>
      {runDetail.run.log_lines.length === 0 ? (
        <div style={{ color: '#aaa' }}>(no log captured)</div>
      ) : (
        runDetail.run.log_lines.map((line, i) => (
          <div key={i} style={{ color: lineColor(line) }}>
            <span style={{ color: '#aaa', marginRight: 8, userSelect: 'none' }}>
              {String(i+1).padStart(3, '0')}
            </span>
            {line || ' '}
          </div>
        ))
      )}
    </div>
  )

  return (
    <>
      <PageHeader
        title="Pipeline logs"
        subtitle="View execution history, errors, and Recovery Agent activity for every pipeline run"
      />
      <PageBody>

        {/* Filter bar */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 4 }}>
            {[
              { key: 'all',     label: `All (${counts.all})` },
              { key: 'success', label: `✓ Success (${counts.success})` },
              { key: 'partial', label: `⚠ Partial (${counts.partial})` },
              { key: 'failed',  label: `✗ Failed (${counts.failed})`  },
            ].map(b => (
              <button key={b.key}
                style={filter === b.key ? btnFilterActive : btnFilter}
                onClick={() => setFilter(b.key)}>
                {b.label}
              </button>
            ))}
          </div>
          <input type="text" placeholder="🔍 Search by pipeline name..."
            style={{ ...inp, flex: 1, maxWidth: 280 }}
            value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#555', cursor: 'pointer' }}>
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
            Auto-refresh
          </label>
          <button style={btnGhostSmall} onClick={loadRuns}>🔄 Refresh now</button>
        </div>

        {loading && <div style={{ fontSize: 12, color: '#888', padding: 20 }}>⏳ Loading...</div>}

        {!loading && filteredRuns.length === 0 && (
          <div style={emptyBox}>
            {runs.length === 0
              ? 'No pipeline runs yet. Execute a pipeline from the ETL Agent to see logs here.'
              : `No runs match the current filter (${filter}).`}
          </div>
        )}

        {/* Master-detail layout */}
        <div style={{ display: 'grid', gridTemplateColumns: selectedRun ? '380px 1fr' : '1fr', gap: 14 }}>

          {/* LEFT — Runs list */}
          {filteredRuns.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' }}>
              {filteredRuns.map(r => {
                const c = statusColor(r.status)
                const isSelected = selectedRun === r.run_id
                return (
                  <div key={r.run_id}
                    onClick={() => setSelectedRun(isSelected ? null : r.run_id)}
                    style={{
                      ...runCard,
                      borderColor: isSelected ? '#185FA5' : '#e5e7eb',
                      background: isSelected ? '#F6FAFE' : '#fff',
                      cursor: 'pointer'
                    }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#111', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                        {r.pipeline_name}
                      </div>
                      <span style={{ ...statusChip, background: c.bg, color: c.fg }}>{c.label}</span>
                    </div>
                    <div style={{ fontSize: 10, color: '#888', display: 'flex', justifyContent: 'space-between' }}>
                      <span>{new Date(r.started_at).toLocaleString()}</span>
                      <span>{duration(r.started_at, r.ended_at)}</span>
                    </div>
                    <div style={{ fontSize: 10, color: '#aaa', marginTop: 2 }}>
                      {r.rows_loaded} rows · {r.run_id.slice(-8)}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {/* RIGHT — Run detail */}
          {selectedRun && (
            <div>
              {loadingDetail && !runDetail ? (
                <div style={{ fontSize: 12, color: '#888', padding: 20 }}>⏳ Loading log...</div>
              ) : runDetail ? (
                <>
                  {/* Run header */}
                  <div style={card}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 600 }}>{runDetail.run.pipeline_name}</div>
                        <div style={{ fontSize: 11, color: '#888', fontFamily: 'monospace', marginTop: 2 }}>
                          Run ID: {runDetail.run.run_id}
                        </div>
                      </div>
                      <span style={{ ...statusChip, ...statusColor(runDetail.run.status), padding: '4px 12px', fontSize: 11 }}>
                        {statusColor(runDetail.run.status).label}
                      </span>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 10 }}>
                      <Metric val={duration(runDetail.run.started_at, runDetail.run.ended_at)} lbl="Duration" />
                      <Metric val={runDetail.run.rows_loaded || 0} lbl="Rows loaded" />
                      <Metric val={runDetail.recoveries.length} lbl="Recoveries" />
                      <Metric val={runDetail.run.log_lines.length} lbl="Log lines" />
                    </div>
                  </div>

                  {/* Recovery summary */}
                  {runDetail.recoveries.length > 0 && (
                    <div style={card}>
                      <div style={sectionTitle}>🤖 Recovery Agent activity ({runDetail.recoveries.length})</div>
                      {runDetail.recoveries.map((rec, i) => (
                        <div key={i} style={{
                          padding: '8px 12px', marginBottom: 6, borderRadius: 6,
                          background: rec.recovered ? '#EAF3DE' : '#FCEBEB',
                          borderLeft: `3px solid ${rec.recovered ? '#3B6D11' : '#A32D2D'}`
                        }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                            <span style={{ fontSize: 12, fontWeight: 600, fontFamily: 'monospace' }}>
                              {rec.recovered ? '✓' : '✗'} {rec.failed_script}
                            </span>
                            <span style={{ fontSize: 10, color: '#888' }}>{rec.fix_method}</span>
                          </div>
                          <div style={{ fontSize: 11, color: '#555' }}>{rec.summary}</div>
                          {rec.error_message && (
                            <div style={{ fontSize: 10, fontFamily: 'monospace', color: '#777', marginTop: 4, padding: '4px 8px', background: 'rgba(0,0,0,0.05)', borderRadius: 4 }}>
                              {rec.error_message.slice(0, 200)}
                              {rec.error_message.length > 200 && '...'}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Full log */}
                  <div style={card}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                      <div style={sectionTitle}>📜 Full log ({runDetail.run.log_lines.length} lines)</div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button style={btnGhostSmall} onClick={downloadLog} title="Download as text file">
                          ⬇ Download
                        </button>
                        <button style={btnGhostSmall} onClick={() => setMaximized(true)} title="Maximize log">
                          ⛶ Maximize
                        </button>
                        <button style={btnGhostSmall}
                          onClick={() => {
                            navigator.clipboard?.writeText(runDetail.run.log || '')
                            alert('Log copied to clipboard')
                          }}>
                          📋 Copy
                        </button>
                      </div>
                    </div>
                    <LogPanel maxHeight={500} />
                  </div>
                </>
              ) : (
                <div style={{ fontSize: 12, color: '#888', padding: 20 }}>Could not load run detail.</div>
              )}
            </div>
          )}
        </div>

        {/* Maximized log modal */}
        {maximized && runDetail && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
            <div style={{ background: '#fff', borderRadius: 10, width: '100%', maxWidth: 1100, maxHeight: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>{runDetail.run.pipeline_name}</div>
                  <div style={{ fontSize: 11, color: '#888', fontFamily: 'monospace' }}>{runDetail.run.run_id}</div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button style={btnGhostSmall} onClick={downloadLog}>⬇ Download</button>
                  <button style={{ ...btnGhostSmall, color: '#A32D2D', borderColor: '#A32D2D' }} onClick={() => setMaximized(false)}>✕ Close</button>
                </div>
              </div>
              <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
                <LogPanel maxHeight={99999} />
              </div>
            </div>
          </div>
        )}

      </PageBody>
    </>
  )
}

function Metric({ val, lbl }) {
  return (
    <div style={{ background: '#f9fafb', borderRadius: 6, padding: '8px 10px' }}>
      <div style={{ fontSize: 16, fontWeight: 600, color: '#185FA5' }}>{val}</div>
      <div style={{ fontSize: 10, color: '#888' }}>{lbl}</div>
    </div>
  )
}

const inp = { padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6 }
const card = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 10 }
const runCard = { border: '1px solid #e5e7eb', borderRadius: 6, padding: '10px 12px', transition: 'all .15s' }
const emptyBox = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 30, textAlign: 'center', fontSize: 13, color: '#888' }
const sectionTitle = { fontSize: 11, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 0 }
const statusChip = { padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }
const btnFilter = { padding: '5px 10px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 20, fontSize: 11, cursor: 'pointer' }
const btnFilterActive = { padding: '5px 10px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 20, fontSize: 11, cursor: 'pointer' }
const btnGhostSmall = { padding: '4px 10px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 10, cursor: 'pointer' }
