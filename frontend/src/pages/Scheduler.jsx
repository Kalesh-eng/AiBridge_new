/**
 * Scheduler.jsx — AIBridge Pipeline Scheduler
 * v2.1: Added Scheduled Reports section alongside pipeline schedules.
 *       Report schedules are managed via /report/schedule endpoints and
 *       show last-run status, row count, and a Run Now button.
 * v2.0: Custom time picker + quarterly/half-yearly/yearly options
 */

import { useState, useEffect } from 'react'
import api from '../api/api'
import { PageHeader, PageBody } from '../components/Layout'

const FREQUENCY_OPTIONS = [
  { value: 'manual',      label: 'Manual only',       desc: 'Run on demand only',              hasTime: false },
  { value: 'hourly',      label: 'Every hour',         desc: 'Runs at :00 each hour',           hasTime: false },
  { value: 'daily',       label: 'Daily',              desc: 'Runs every day at custom time',   hasTime: true  },
  { value: 'weekly',      label: 'Weekly',             desc: 'Runs every selected day',         hasTime: true, hasDay: true },
  { value: 'monthly',     label: 'Monthly',            desc: 'Runs on selected date each month',hasTime: true, hasDate: true },
  { value: 'quarterly',   label: 'Quarterly',          desc: 'Runs every 3 months',             hasTime: true },
  { value: 'halfyearly',  label: 'Half Yearly',        desc: 'Runs every 6 months',             hasTime: true },
  { value: 'yearly',      label: 'Yearly',             desc: 'Runs once a year',                hasTime: true },
]

const DAYS_OF_WEEK = [
  { value: '0', label: 'Sunday' },  { value: '1', label: 'Monday' },
  { value: '2', label: 'Tuesday' }, { value: '3', label: 'Wednesday' },
  { value: '4', label: 'Thursday' },{ value: '5', label: 'Friday' },
  { value: '6', label: 'Saturday' },
]

const MONTHS_OF_YEAR = [
  { value: '1', label: 'January' },  { value: '2', label: 'February' },
  { value: '3', label: 'March' },    { value: '4', label: 'April' },
  { value: '5', label: 'May' },      { value: '6', label: 'June' },
  { value: '7', label: 'July' },     { value: '8', label: 'August' },
  { value: '9', label: 'September' },{ value: '10', label: 'October' },
  { value: '11', label: 'November' },{ value: '12', label: 'December' },
]

const DEFAULT_CONFIG = {
  frequency: 'daily', time: '06:00', day_of_week: '1', day_of_month: '1', month: '1',
}

export default function Scheduler() {
  const [pipelines,      setPipelines]      = useState([])
  const [jobs,           setJobs]           = useState([])
  const [reportSchedules,setReportSchedules]= useState([])
  const [loading,        setLoading]        = useState(true)
  const [saving,         setSaving]         = useState(null)
  const [running,        setRunning]        = useState(null)
  const [removing,       setRemoving]       = useState(null)
  const [editMode,       setEditMode]       = useState(null)
  const [config,         setConfig]         = useState({ ...DEFAULT_CONFIG })
  const [error,          setError]          = useState(null)
  const [successMsg,     setSuccessMsg]     = useState('')

  // Report schedule state
  const [removingReport, setRemovingReport] = useState(null)
  const [runningReport,  setRunningReport]  = useState(null)
  const [reportRunResult,setReportRunResult]= useState({})  // scheduleId -> {columns,rows,row_count,ran_at}

  useEffect(() => { loadAll() }, [])

  const loadAll = async () => {
    setLoading(true)
    try {
      const [pr, jr, rr] = await Promise.all([
        api.get('/pipeline/list'),
        api.get('/scheduler/jobs'),
        api.get('/report/schedules').catch(() => ({ data: { schedules: [] } })),
      ])
      setPipelines(pr.data.pipelines || [])
      setJobs(jr.data.jobs || [])
      setReportSchedules(rr.data.schedules || [])
    } catch (e) {
      setError('Could not load data')
    }
    setLoading(false)
  }

  const getJob = (pipelineId) =>
    jobs.find(j => j.pipeline_id === pipelineId || j.id === pipelineId)

  const formatNextRun = (job) => {
    if (!job) return null
    const nr = job.next_run_time || job.next_run
    if (!nr) return 'Not scheduled'
    try {
      const d = new Date(nr); const now = new Date(); const diff = d - now
      if (diff < 0)        return 'Overdue'
      if (diff < 60000)    return 'Less than 1 min'
      if (diff < 3600000)  return `${Math.round(diff/60000)} min`
      if (diff < 86400000) return `${Math.round(diff/3600000)}h ${Math.round((diff%3600000)/60000)}m`
      return d.toLocaleString()
    } catch { return nr }
  }

  const scheduleLabel = (p) => {
    const sc = p.schedule_config
    if (!sc || p.schedule === 'manual') return 'Manual only'
    const freq = sc.frequency || p.schedule
    const time = sc.time || '06:00'
    switch (freq) {
      case 'manual':     return 'Manual only'
      case 'hourly':     return 'Every hour'
      case 'daily':      return `Daily at ${time}`
      case 'weekly': {
        const day = DAYS_OF_WEEK.find(d => d.value === String(sc.day_of_week))?.label || 'Monday'
        return `Weekly — ${day} at ${time}`
      }
      case 'monthly':    return `Monthly — day ${sc.day_of_month || 1} at ${time}`
      case 'quarterly':  return `Quarterly at ${time}`
      case 'halfyearly': return `Half Yearly at ${time}`
      case 'yearly': {
        const mon = MONTHS_OF_YEAR.find(m => m.value === String(sc.month))?.label || 'January'
        return `Yearly — ${mon} ${sc.day_of_month || 1} at ${time}`
      }
      default: return freq
    }
  }

  const buildScheduleString = (cfg) => {
    const [hh, mm] = (cfg.time || '06:00').split(':')
    switch (cfg.frequency) {
      case 'manual':     return 'manual'
      case 'hourly':     return 'hourly'
      case 'daily':      return `daily_${hh}${mm}`
      case 'weekly':     return `weekly_${cfg.day_of_week}_${hh}${mm}`
      case 'monthly':    return `monthly_${cfg.day_of_month}_${hh}${mm}`
      case 'quarterly':  return `quarterly_${hh}${mm}`
      case 'halfyearly': return `halfyearly_${hh}${mm}`
      case 'yearly':     return `yearly_${cfg.month}_${cfg.day_of_month}_${hh}${mm}`
      default:           return cfg.frequency
    }
  }

  const openEdit = (pipeline) => {
    const existing = pipeline.schedule_config
    setConfig(existing ? { ...DEFAULT_CONFIG, ...existing } : { ...DEFAULT_CONFIG })
    setEditMode(pipeline.id); setError(null)
  }

  const saveSchedule = async (pipeline) => {
    if (config.frequency === 'manual') { await removeSchedule(pipeline, true); return }
    setSaving(pipeline.id); setError(null)
    try {
      const schedStr = buildScheduleString(config)
      await api.post('/scheduler/add', {
        pipeline_id: pipeline.id, pipeline_name: pipeline.name,
        sql_scripts: pipeline.artifacts?.sql_scripts?.scripts || [],
        schedule: schedStr, schedule_config: config,
      })
      flash(`✓ ${pipeline.name} scheduled: ${scheduleLabel({ schedule: schedStr, schedule_config: config })}`)
      setEditMode(null); await loadAll()
    } catch (e) { setError('Could not save: ' + (e.response?.data?.detail || e.message)) }
    setSaving(null)
  }

  const removeSchedule = async (pipeline, silent = false) => {
    setRemoving(pipeline.id)
    try {
      await api.delete(`/scheduler/${pipeline.id}`)
      if (!silent) flash(`✓ Schedule removed for ${pipeline.name}`)
      setEditMode(null); await loadAll()
    } catch (e) { setError('Could not remove: ' + (e.response?.data?.detail || e.message)) }
    setRemoving(null)
  }

  const runNow = async (pipeline) => {
    setRunning(pipeline.id); setError(null)
    try {
      await api.post(`/pipeline/execute/${pipeline.id}`)
      flash(`✓ ${pipeline.name} executed successfully`)
    } catch (e) { setError('Run failed: ' + (e.response?.data?.detail || e.message)) }
    setRunning(null)
  }

  // ── Report schedule handlers ──────────────────────────────────────────────

  const removeReportSchedule = async (id, name) => {
    setRemovingReport(id)
    try {
      await api.delete(`/report/schedule/${id}`)
      flash(`✓ Schedule removed for "${name}"`)
      await loadAll()
    } catch (e) { setError('Could not remove: ' + (e.response?.data?.detail || e.message)) }
    setRemovingReport(null)
  }

  const runReportNow = async (schedule) => {
    setRunningReport(schedule.id); setError(null)
    try {
      const r = await api.post(`/report/run-now/${schedule.id}`)
      setReportRunResult(prev => ({ ...prev, [schedule.id]: r.data }))
      flash(`✓ "${schedule.report_name}" ran — ${r.data.row_count} rows`)
    } catch (e) { setError('Run failed: ' + (e.response?.data?.detail || e.message)) }
    setRunningReport(null)
  }

  const flash = (msg) => { setSuccessMsg(msg); setTimeout(() => setSuccessMsg(''), 4000) }
  const setC  = (key, val) => setConfig(prev => ({ ...prev, [key]: val }))

  const scheduled = pipelines.filter(p => p.schedule && p.schedule !== 'manual')
  const manual    = pipelines.filter(p => !p.schedule || p.schedule === 'manual')
  const freqOpt   = FREQUENCY_OPTIONS.find(o => o.value === config.frequency) || {}

  return (
    <>
      <PageHeader
        title="Scheduler"
        subtitle="Automate pipeline runs and reports — set custom schedules, monitor next runs"
      />
      <PageBody>
        {error      && <div style={errBox}>{error}<button style={closeBtn} onClick={() => setError(null)}>✕</button></div>}
        {successMsg && <div style={successBox}>{successMsg}</div>}

        {loading ? (
          <div style={{ fontSize: 12, color: '#888' }}>⏳ Loading...</div>
        ) : (
          <>
            {/* Stats */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12, marginBottom: 20 }}>
              {[
                { label: 'Total Pipelines',    value: pipelines.length,       color: '#185FA5', emoji: '📋' },
                { label: 'Scheduled Pipelines',value: scheduled.length,       color: '#27500A', emoji: '⏰' },
                { label: 'Manual Only',         value: manual.length,          color: '#888',    emoji: '🖐' },
                { label: 'Scheduled Reports',   value: reportSchedules.length, color: '#534AB7', emoji: '📊' },
              ].map(s => (
                <div key={s.label} style={{ ...card, textAlign: 'center', padding: '14px 10px' }}>
                  <div style={{ fontSize: 20, marginBottom: 4 }}>{s.emoji}</div>
                  <div style={{ fontSize: 24, fontWeight: 800, color: s.color }}>{s.value}</div>
                  <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{s.label}</div>
                </div>
              ))}
            </div>

            {pipelines.length === 0 && reportSchedules.length === 0 ? (
              <div style={emptyBox}>No pipelines yet — create one in the ETL Agent first.</div>
            ) : (
              <>
                {scheduled.length > 0 && <SectionLabel>⏰ Scheduled Pipelines</SectionLabel>}
                {scheduled.map(p => (
                  <PipelineRow key={p.id} pipeline={p} job={getJob(p.id)}
                    editMode={editMode} config={config} freqOpt={freqOpt}
                    saving={saving} running={running} removing={removing}
                    formatNextRun={formatNextRun} scheduleLabel={scheduleLabel}
                    openEdit={openEdit} setC={setC}
                    saveSchedule={saveSchedule} removeSchedule={removeSchedule}
                    runNow={runNow} setEditMode={setEditMode} />
                ))}

                {manual.length > 0 && <SectionLabel style={{ marginTop: scheduled.length > 0 ? 16 : 0 }}>🖐 Manual Pipelines</SectionLabel>}
                {manual.map(p => (
                  <PipelineRow key={p.id} pipeline={p} job={getJob(p.id)}
                    editMode={editMode} config={config} freqOpt={freqOpt}
                    saving={saving} running={running} removing={removing}
                    formatNextRun={formatNextRun} scheduleLabel={scheduleLabel}
                    openEdit={openEdit} setC={setC}
                    saveSchedule={saveSchedule} removeSchedule={removeSchedule}
                    runNow={runNow} setEditMode={setEditMode} />
                ))}

                {/* ── Scheduled Reports ── */}
                {reportSchedules.length > 0 && (
                  <>
                    <SectionLabel style={{ marginTop: 20 }}>📊 Scheduled Reports</SectionLabel>
                    {reportSchedules.map(rs => (
                      <div key={rs.id} style={{ ...card, borderColor: '#534AB7', borderWidth: 1.5 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div style={{ flex: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                              <div style={{ fontSize: 13, fontWeight: 600, color: '#534AB7' }}>
                                {rs.report_name}
                              </div>
                              <span style={{ fontSize: 9, padding: '2px 7px', borderRadius: 10,
                                fontWeight: 600, background: '#EEEDFE', color: '#534AB7' }}>
                                ● Report
                              </span>
                            </div>
                            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                              <div style={{ fontSize: 10, color: '#555' }}>
                                <span style={{ color: '#888' }}>Schedule: </span>
                                <strong>{rs.schedule}</strong>
                              </div>
                              <div style={{ fontSize: 10, color: '#555' }}>
                                <span style={{ color: '#888' }}>Format: </span>
                                <strong>{(rs.export_format || 'csv').toUpperCase()}</strong>
                              </div>
                              {rs.last_run_at ? (
                                <div style={{ fontSize: 10, color: '#555' }}>
                                  <span style={{ color: '#888' }}>Last run: </span>
                                  <strong>{new Date(rs.last_run_at).toLocaleString()}</strong>
                                  {' '}· {rs.last_run_rows} rows
                                  {' '}
                                  <span style={{ color: rs.last_run_status === 'success' ? '#3B6D11' : '#A32D2D' }}>
                                    ({rs.last_run_status})
                                  </span>
                                </div>
                              ) : (
                                <div style={{ fontSize: 10, color: '#888' }}>Not run yet</div>
                              )}
                            </div>
                            {rs.question && (
                              <div style={{ fontSize: 11, color: '#888', marginTop: 4, fontStyle: 'italic' }}>
                                "{rs.question}"
                              </div>
                            )}
                          </div>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            <button
                              style={{ ...btnPrimary, fontSize: 10, padding: '4px 10px', background: '#534AB7' }}
                              onClick={() => runReportNow(rs)} disabled={runningReport === rs.id}>
                              {runningReport === rs.id ? '⏳ Running...' : '▶ Run Now'}
                            </button>
                            <button
                              style={{ ...btnGhostSmall, color: '#991B1B', borderColor: '#FCA5A5' }}
                              onClick={() => removeReportSchedule(rs.id, rs.report_name)}
                              disabled={removingReport === rs.id}>
                              {removingReport === rs.id ? '⏳' : '✕ Remove'}
                            </button>
                          </div>
                        </div>

                        {/* Inline run result */}
                        {reportRunResult[rs.id] && (
                          <div style={{ marginTop: 10, padding: '8px 12px', background: '#EEEDFE',
                            borderRadius: 6 }}>
                            <div style={{ fontSize: 11, fontWeight: 600, color: '#534AB7', marginBottom: 6 }}>
                              ✓ {reportRunResult[rs.id].row_count} rows
                              · ran at {new Date(reportRunResult[rs.id].ran_at).toLocaleTimeString()}
                            </div>
                            <div style={{ overflowX: 'auto' }}>
                              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                                <thead>
                                  <tr>{(reportRunResult[rs.id].columns || []).map(c => (
                                    <th key={c} style={{ background: '#534AB7', color: '#fff',
                                      padding: '3px 8px', textAlign: 'left', fontSize: 9 }}>{c}</th>
                                  ))}</tr>
                                </thead>
                                <tbody>
                                  {(reportRunResult[rs.id].rows || []).slice(0, 5).map((row, i) => (
                                    <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                                      {row.map((cell, j) => (
                                        <td key={j} style={{ padding: '3px 8px', fontSize: 10, color: '#333' }}>
                                          {cell === null ? '—' : String(cell)}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                              {(reportRunResult[rs.id].rows || []).length > 5 && (
                                <div style={{ fontSize: 9, color: '#888', marginTop: 4 }}>
                                  Showing 5 of {reportRunResult[rs.id].row_count} rows — go to Analytics to download full results
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </>
                )}
              </>
            )}
          </>
        )}
      </PageBody>
    </>
  )
}

function SectionLabel({ children, style }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 600, color: '#888',
      textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8, ...style }}>
      {children}
    </div>
  )
}

function PipelineRow({
  pipeline, job, editMode, config, freqOpt,
  saving, running, removing,
  formatNextRun, scheduleLabel,
  openEdit, setC, saveSchedule, removeSchedule, runNow, setEditMode
}) {
  const p       = pipeline
  const isEdit  = editMode === p.id
  const nextRun = formatNextRun(job)
  const isActive = p.schedule && p.schedule !== 'manual'

  return (
    <div style={{ ...card, borderColor: isEdit ? '#185FA5' : '#e5e7eb',
      background: isEdit ? '#F6FAFE' : '#fff' }}>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#111' }}>{p.name}</div>
            <span style={{ fontSize: 9, padding: '2px 7px', borderRadius: 10, fontWeight: 600,
              background: isActive ? '#EAF3DE' : '#f3f4f6',
              color: isActive ? '#27500A' : '#888' }}>
              {isActive ? '● Active' : '○ Manual'}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 10, color: '#555' }}>
              <span style={{ color: '#888' }}>Schedule: </span>
              <strong>{scheduleLabel(p)}</strong>
            </div>
            {nextRun && isActive && (
              <div style={{ fontSize: 10, color: '#555' }}>
                <span style={{ color: '#888' }}>Next run: </span>
                <strong style={{ color: '#185FA5' }}>⏱ {nextRun}</strong>
              </div>
            )}
            <div style={{ fontSize: 10, color: '#888' }}>
              {p.artifacts?.sql_scripts?.scripts?.length || 0} scripts · {p.source_tables?.length || 0} tables
            </div>
          </div>
        </div>

        {!isEdit && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <button style={btnGhostSmall} onClick={() => openEdit(p)}>⏰ Set Schedule</button>
            {isActive && (
              <button style={{ ...btnGhostSmall, color: '#991B1B', borderColor: '#FCA5A5' }}
                onClick={() => removeSchedule(p)} disabled={removing === p.id}>
                {removing === p.id ? '⏳' : '✕ Remove'}
              </button>
            )}
            <button style={{ ...btnPrimary, fontSize: 10, padding: '4px 10px' }}
              onClick={() => runNow(p)} disabled={running === p.id}>
              {running === p.id ? '⏳ Running...' : '▶ Run Now'}
            </button>
          </div>
        )}
      </div>

      {isEdit && (
        <div style={{ marginTop: 12, padding: '14px 16px', background: '#F8FAFC',
          borderRadius: 6, border: '1px solid #e5e7eb' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 12 }}>
            Set Schedule for <span style={{ color: '#185FA5' }}>{p.name}</span>
          </div>

          <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
            textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>Frequency</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
            gap: 6, marginBottom: 14 }}>
            {FREQUENCY_OPTIONS.map(opt => (
              <label key={opt.value} style={{ display: 'flex', alignItems: 'flex-start', gap: 8,
                padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                border: `1px solid ${config.frequency === opt.value ? '#185FA5' : '#e5e7eb'}`,
                background: config.frequency === opt.value ? '#EBF4FF' : '#fff' }}>
                <input type="radio" name={`freq_${p.id}`} value={opt.value}
                  checked={config.frequency === opt.value}
                  onChange={() => setC('frequency', opt.value)} style={{ marginTop: 2 }} />
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600,
                    color: config.frequency === opt.value ? '#185FA5' : '#374151' }}>{opt.label}</div>
                  <div style={{ fontSize: 9, color: '#888', marginTop: 1 }}>{opt.desc}</div>
                </div>
              </label>
            ))}
          </div>

          {config.frequency !== 'manual' && config.frequency !== 'hourly' && (
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                  textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Run Time</div>
                <input type="time" value={config.time} onChange={e => setC('time', e.target.value)}
                  style={{ padding: '6px 10px', fontSize: 13, fontWeight: 600,
                    border: '1px solid #d1d5db', borderRadius: 6, color: '#185FA5', background: '#fff' }} />
              </div>
              {freqOpt.hasDay && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                    textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Day of Week</div>
                  <select value={config.day_of_week} onChange={e => setC('day_of_week', e.target.value)}
                    style={selectStyle}>
                    {DAYS_OF_WEEK.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
                  </select>
                </div>
              )}
              {(freqOpt.hasDate || ['monthly','quarterly','halfyearly','yearly'].includes(config.frequency)) && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                    textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Day of Month</div>
                  <select value={config.day_of_month} onChange={e => setC('day_of_month', e.target.value)}
                    style={selectStyle}>
                    {Array.from({ length: 28 }, (_, i) => i + 1).map(d => (
                      <option key={d} value={String(d)}>{d}</option>
                    ))}
                  </select>
                </div>
              )}
              {config.frequency === 'yearly' && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                    textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Month</div>
                  <select value={config.month} onChange={e => setC('month', e.target.value)} style={selectStyle}>
                    {MONTHS_OF_YEAR.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                  </select>
                </div>
              )}
            </div>
          )}

          {config.frequency !== 'manual' && (
            <div style={{ background: '#EBF4FF', borderRadius: 6, padding: '8px 12px',
              marginBottom: 12, fontSize: 11, color: '#185FA5', fontWeight: 600 }}>
              ⏱ Preview: {buildPreview(config)}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button style={btnPrimary} onClick={() => saveSchedule(p)} disabled={saving === p.id}>
              {saving === p.id ? '⏳ Saving...' : '💾 Save Schedule'}
            </button>
            <button style={btnGhost} onClick={() => setEditMode(null)}>Cancel</button>
            {isActive && (
              <button style={{ ...btnGhost, color: '#991B1B', borderColor: '#FCA5A5', marginLeft: 'auto' }}
                onClick={() => removeSchedule(p)} disabled={removing === p.id}>
                {removing === p.id ? '⏳' : '🗑 Remove Schedule'}
              </button>
            )}
          </div>
          <div style={{ fontSize: 10, color: '#888', marginTop: 8 }}>
            ⚠ Schedule runs the full pipeline (extract → quality check → warehouse load).
          </div>
        </div>
      )}
    </div>
  )
}

function buildPreview(cfg) {
  const time = cfg.time || '06:00'
  const dow  = DAYS_OF_WEEK.find(d => d.value === String(cfg.day_of_week))?.label || 'Monday'
  const dom  = cfg.day_of_month || '1'
  const mon  = MONTHS_OF_YEAR.find(m => m.value === String(cfg.month))?.label || 'January'
  switch (cfg.frequency) {
    case 'manual':     return 'Run on demand only'
    case 'hourly':     return 'Runs every hour at :00'
    case 'daily':      return `Runs every day at ${time}`
    case 'weekly':     return `Runs every ${dow} at ${time}`
    case 'monthly':    return `Runs on the ${dom}${ordinal(dom)} of every month at ${time}`
    case 'quarterly':  return `Runs every 3 months on the ${dom}${ordinal(dom)} at ${time}`
    case 'halfyearly': return `Runs every 6 months on the ${dom}${ordinal(dom)} at ${time}`
    case 'yearly':     return `Runs every year on ${mon} ${dom} at ${time}`
    default:           return cfg.frequency
  }
}

function ordinal(n) {
  const num = parseInt(n)
  if (num === 1 || num === 21) return 'st'
  if (num === 2 || num === 22) return 'nd'
  if (num === 3 || num === 23) return 'rd'
  return 'th'
}

const card        = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 10 }
const errBox      = { background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#991b1b', marginBottom: 10 }
const successBox  = { background: '#EAF3DE', border: '1px solid #a7d9a0', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#27500A', marginBottom: 10 }
const emptyBox    = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 30, textAlign: 'center', fontSize: 13, color: '#888' }
const btnPrimary  = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhost    = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnGhostSmall = { padding: '4px 10px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 10, cursor: 'pointer' }
const closeBtn    = { float: 'right', background: 'none', border: 'none', cursor: 'pointer', color: '#991b1b' }
const selectStyle = { padding: '6px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, background: '#fff', cursor: 'pointer', minWidth: 130 }
