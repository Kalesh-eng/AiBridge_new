/**
 * Analytics.jsx — BI / Analytics tab
 * v1.5: Voice Mode added — speak your question, hear the answer back.
 *   - Microphone button next to the question textarea
 *   - Web Speech API (no external service, works in Chrome/Edge)
 *   - Text-to-Speech reads back the AI summary after query runs
 *   - Language: en-IN (configurable)
 *
 * v1.4: Report re-run + download (CSV/Excel/PDF) + schedule reports.
 * v1.3: Interactive query refinement with conversation chain + rollback.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { PageHeader, PageBody } from '../components/Layout'
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'
import api from '../api/api'

const COLORS = ['#185FA5','#3B6D11','#854F0B','#534AB7','#A32D2D','#0F6E56','#993C1D','#888780',
                '#1D8A99','#6B4F9E','#B85C00','#2E7D32']
const REFINEMENT_SUGGESTIONS = [
  'Top 10 only', 'Sort by highest first', 'Sort by lowest first',
  'Exclude nulls', 'Add a count column', 'Show as percentage',
  'Group by year', 'Limit to 50 rows',
]
const FREQUENCY_OPTIONS = [
  { value: 'daily',       label: 'Daily',       desc: 'Every day at custom time',    hasTime: true  },
  { value: 'weekly',      label: 'Weekly',      desc: 'Every selected day',          hasTime: true, hasDay: true },
  { value: 'monthly',     label: 'Monthly',     desc: 'Selected date each month',    hasTime: true, hasDate: true },
  { value: 'quarterly',   label: 'Quarterly',   desc: 'Every 3 months',              hasTime: true },
  { value: 'halfyearly',  label: 'Half Yearly', desc: 'Every 6 months',              hasTime: true },
  { value: 'yearly',      label: 'Yearly',      desc: 'Once a year',                 hasTime: true },
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
const DEFAULT_SCHED_CONFIG = { frequency: 'daily', time: '08:00', day_of_week: '1', day_of_month: '1', month: '1' }

function buildScheduleString(cfg) {
  const [hh, mm] = (cfg.time || '08:00').split(':')
  switch (cfg.frequency) {
    case 'daily':      return `daily_${hh}${mm}`
    case 'weekly':     return `weekly_${cfg.day_of_week}_${hh}${mm}`
    case 'monthly':    return `monthly_${cfg.day_of_month}_${hh}${mm}`
    case 'quarterly':  return `quarterly_${hh}${mm}`
    case 'halfyearly': return `halfyearly_${hh}${mm}`
    case 'yearly':     return `yearly_${cfg.month}_${cfg.day_of_month}_${hh}${mm}`
    default:           return `daily_${hh}${mm}`
  }
}
function buildSchedulePreview(cfg) {
  const time = cfg.time || '08:00'
  const dow  = DAYS_OF_WEEK.find(d => d.value === String(cfg.day_of_week))?.label || 'Monday'
  const dom  = cfg.day_of_month || '1'
  const mon  = MONTHS_OF_YEAR.find(m => m.value === String(cfg.month))?.label || 'January'
  const ord  = (n) => { const i = parseInt(n); return i===1||i===21?'st':i===2||i===22?'nd':i===3||i===23?'rd':'th' }
  switch (cfg.frequency) {
    case 'daily':      return `Every day at ${time}`
    case 'weekly':     return `Every ${dow} at ${time}`
    case 'monthly':    return `Every month on the ${dom}${ord(dom)} at ${time}`
    case 'quarterly':  return `Every 3 months on the ${dom}${ord(dom)} at ${time}`
    case 'halfyearly': return `Every 6 months on the ${dom}${ord(dom)} at ${time}`
    case 'yearly':     return `Every year on ${mon} ${dom} at ${time}`
    default:           return `Daily at ${time}`
  }
}

// ── Voice hook ───────────────────────────────────────────────────────────────
function useVoice(onResult) {
  const [listening,  setListening]  = useState(false)
  const [supported,  setSupported]  = useState(false)
  const [voiceOn,    setVoiceOn]    = useState(true)   // text-to-speech toggle
  const recogRef = useRef(null)

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return
    setSupported(true)
    const r = new SR()
    r.continuous      = false
    r.interimResults  = false
    r.lang            = 'en-IN'
    r.onresult = (e) => {
      const text = e.results[0][0].transcript
      onResult(text)
      setListening(false)
    }
    r.onend   = () => setListening(false)
    r.onerror = () => setListening(false)
    recogRef.current = r
  }, [onResult])

  const toggleListen = useCallback(() => {
    if (!recogRef.current) return
    if (listening) {
      recogRef.current.stop()
      setListening(false)
    } else {
      try { recogRef.current.start(); setListening(true) } catch {}
    }
  }, [listening])

  const speak = useCallback((text) => {
    if (!voiceOn || !window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const clean = text
      .replace(/```[\s\S]*?```/g, '')
      .replace(/[#*_`>]/g, '')
      .replace(/\n+/g, ' ')
      .trim()
      .slice(0, 400)
    const utt    = new SpeechSynthesisUtterance(clean)
    utt.lang     = 'en-IN'
    utt.rate     = 0.93
    utt.pitch    = 1
    window.speechSynthesis.speak(utt)
  }, [voiceOn])

  const stopSpeaking = useCallback(() => {
    if (window.speechSynthesis) window.speechSynthesis.cancel()
  }, [])

  return { listening, supported, voiceOn, setVoiceOn, toggleListen, speak, stopSpeaking }
}

export default function Analytics() {
  const [pipelines,        setPipelines]        = useState([])
  const [connectors,       setConnectors]       = useState([])
  const [selectedPipeline, setSelectedPipeline] = useState(null)
  const [question,         setQuestion]         = useState('')
  const [loading,          setLoading]          = useState(false)
  const [executing,        setExecuting]        = useState(false)
  const [error,            setError]            = useState(null)
  const [warehouseInfo,    setWarehouseInfo]    = useState(null)
  const [queryChain,    setQueryChain]    = useState([])
  const [activeStep,    setActiveStep]    = useState(-1)
  const [results,       setResults]       = useState(null)
  const [editedSql,     setEditedSql]     = useState('')
  const [editingSql,    setEditingSql]    = useState(false)
  const [refinement,    setRefinement]    = useState('')
  const [refining,      setRefining]      = useState(false)
  const [chartType,     setChartType]     = useState('bar')
  const [xAxis,         setXAxis]         = useState('')
  const [yAxis,         setYAxis]         = useState('')
  const [savedReports,  setSavedReports]  = useState([])
  const [reportName,    setReportName]    = useState('')
  const [saving,        setSaving]        = useState(false)
  const [savedMsg,      setSavedMsg]      = useState('')
  const [rerunning,     setRerunning]     = useState(null)
  const [rerunResults,  setRerunResults]  = useState({})
  const [rerunError,    setRerunError]    = useState({})
  const [downloading,   setDownloading]   = useState(null)
  const [scheduleModal, setScheduleModal] = useState(null)
  const [schedConfig,   setSchedConfig]   = useState({ ...DEFAULT_SCHED_CONFIG })
  const setSchedC = (key, val) => setSchedConfig(prev => ({ ...prev, [key]: val }))
  const [scheduling,    setScheduling]    = useState(false)
  const [scheduleMsg,   setScheduleMsg]   = useState('')
  // Voice state
  const [voiceStatus,   setVoiceStatus]   = useState('')  // status message shown near mic

  const refinementRef = useRef(null)

  // Voice hook — onResult sets the question and auto-submits
  const handleVoiceResult = useCallback((text) => {
    setQuestion(text)
    setVoiceStatus(`Heard: "${text}"`)
    setTimeout(() => setVoiceStatus(''), 3000)
    // Auto-submit after brief delay so user sees what was heard
    setTimeout(() => {
      setQuestion(text)
      // trigger generateSql via ref pattern
      voiceSubmitRef.current?.(text)
    }, 600)
  }, [])

  const { listening, supported, voiceOn, setVoiceOn, toggleListen, speak, stopSpeaking } = useVoice(handleVoiceResult)
  const voiceSubmitRef = useRef(null)

  useEffect(() => {
    Promise.all([
      api.get('/pipeline/list'),
      api.get('/connector/list')
    ]).then(([pRes, cRes]) => {
      const list  = pRes.data.pipelines || []
      const conns = cRes.data.connectors || []
      setPipelines(list)
      setConnectors(conns)
      if (list.length > 0) selectPipeline(list[0], conns)
    }).catch(() => {})
    const saved = JSON.parse(localStorage.getItem('aibridge_reports') || '[]')
    setSavedReports(saved)
  }, [])

  const resolveWarehouseConnector = (pipeline, conns) => {
    if (!pipeline) return null
    const allConns = conns || connectors
    if (pipeline.target_connector_id) {
      const tgt = allConns.find(c => c.id === pipeline.target_connector_id)
      if (tgt) return tgt
    }
    const src = allConns.find(c => c.id === pipeline.connector_id)
    if (src?.connector_type === 'duckdb') {
      const pg = allConns.find(c => c.connector_type === 'postgres' && c.is_active !== false)
      if (pg) return pg
    }
    return src || null
  }

  const selectPipeline = (pipeline, conns) => {
    setSelectedPipeline(pipeline)
    setWarehouseInfo(resolveWarehouseConnector(pipeline, conns))
    reset()
  }

  // ── SQL generation ──────────────────────────────────────────────────────
  const generateSql = async (questionOverride) => {
    const q = questionOverride || question
    if (!q.trim()) { setError('Enter a question first'); return }
    if (!selectedPipeline) { setError('Select a pipeline first'); return }
    if (!warehouseInfo) { setError('Could not resolve warehouse connector.'); return }
    setError(null); setLoading(true); setResults(null); setQueryChain([])
    try {
      const r = await api.post('/nl/to-sql', { question: q, connector_id: warehouseInfo.id })
      if (!r.data.success) { setError(r.data.error || 'AI could not generate SQL'); setLoading(false); return }
      if (r.data.safety?.blocked) {
        setError(`SQL blocked: ${r.data.safety.violations?.map(v => v.message).join(', ')}`)
        setLoading(false); return
      }
      const step = { instruction: q, sql: r.data.sql, explanation: null }
      setQueryChain([step]); setActiveStep(0); setEditedSql(r.data.sql); setEditingSql(false)
      await runSql(r.data.sql, q)
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Failed to generate SQL')
    }
    setLoading(false)
  }

  // Wire voice submit ref
  useEffect(() => {
    voiceSubmitRef.current = generateSql
  }, [selectedPipeline, warehouseInfo])

  // ── Refinement ──────────────────────────────────────────────────────────
  const applyRefinement = async (instruction) => {
    const text = instruction || refinement
    if (!text.trim()) return
    if (queryChain.length === 0) { setError('Generate a query first'); return }
    setRefining(true); setError(null)
    const currentSql = editedSql || queryChain[activeStep]?.sql || ''
    const history = queryChain.slice(0, activeStep).map(s => ({ instruction: s.instruction, sql: s.sql }))
    try {
      const r = await api.post('/nl/refine-sql', {
        current_sql: currentSql, refinement: text,
        connector_id: warehouseInfo?.id || '', history
      })
      if (!r.data.success) { setError(r.data.error || 'Could not refine SQL'); setRefining(false); return }
      const newStep = { instruction: text, sql: r.data.sql, explanation: r.data.explanation }
      const newChain = [...queryChain.slice(0, activeStep + 1), newStep]
      setQueryChain(newChain); setActiveStep(newChain.length - 1)
      setEditedSql(r.data.sql); setEditingSql(false); setRefinement('')
      await runSql(r.data.sql)
      setTimeout(() => refinementRef.current?.focus(), 100)
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Refinement failed')
    }
    setRefining(false)
  }

  // ── SQL execution ───────────────────────────────────────────────────────
  const runSql = async (sqlToRun, questionCtx) => {
    const sql = sqlToRun || editedSql || queryChain[activeStep]?.sql
    if (!sql || !warehouseInfo) return
    setExecuting(true); setError(null)
    try {
      const r = await api.post('/sql/run', { sql, connector_id: warehouseInfo.id })
      if (!r.data.success) { setError(r.data.error || 'SQL execution failed'); setExecuting(false); return }
      const cols = r.data.columns || []; const rows = r.data.rows || []
      setResults({ columns: cols, rows })
      const numericCols = cols.filter(c => {
        const v = rows[0]?.[cols.indexOf(c)]
        return typeof v === 'number' || (!isNaN(Number(v)) && v !== null && v !== '')
      })
      setXAxis(cols.filter(c => !numericCols.includes(c))[0] || cols[0] || '')
      setYAxis(numericCols[0] || cols[1] || '')

      // 🔊 Speak a summary of the results
      if (rows.length > 0) {
        const q = questionCtx || question
        const top = rows.slice(0, 3).map(row =>
          cols.map((c, i) => `${c}: ${row[i]}`).join(', ')
        ).join('; ')
        speak(`Found ${rows.length} results for "${q}". Top results are: ${top}`)
      }
    } catch (e) { setError(e.response?.data?.detail || e.message || 'Execution failed') }
    setExecuting(false)
  }

  const rollbackToStep = async (idx) => {
    setActiveStep(idx); setEditedSql(queryChain[idx].sql); setEditingSql(false); setResults(null)
    await runSql(queryChain[idx].sql)
  }

  const reset = () => {
    setQuestion(''); setQueryChain([]); setActiveStep(-1)
    setResults(null); setEditedSql(''); setEditingSql(false)
    setError(null); setRefinement(''); setChartType('bar')
    stopSpeaking()
  }

  // ── Download ────────────────────────────────────────────────────────────
  const downloadResults = async (format, reportNameOverride, sqlOverride, questionOverride) => {
    const sql   = sqlOverride   || editedSql || queryChain[activeStep]?.sql
    const rName = reportNameOverride || reportName || question || 'report'
    const q     = questionOverride   || question
    if (!sql || !warehouseInfo) { setError('No SQL to export'); return }
    setDownloading(format)
    try {
      const res = await api.post('/report/export', {
        sql, connector_id: warehouseInfo.id, format, report_name: rName, question: q
      }, { responseType: 'blob' })
      const ext  = format === 'excel' ? 'xlsx' : format
      const url  = URL.createObjectURL(new Blob([res.data]))
      const a    = document.createElement('a')
      a.href     = url
      a.download = `${rName.replace(/\s+/g, '_')}.${ext}`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) { setError('Download failed: ' + (e.response?.data?.detail || e.message)) }
    setDownloading(null)
  }

  // ── Re-run saved report ─────────────────────────────────────────────────
  const rerunReport = async (report) => {
    if (!warehouseInfo) { setError('Could not resolve warehouse connector'); return }
    setRerunning(report.id); setRerunError(prev => ({ ...prev, [report.id]: null }))
    try {
      const r = await api.post('/sql/run', { sql: report.sql, connector_id: warehouseInfo.id })
      if (!r.data.success) {
        setRerunError(prev => ({ ...prev, [report.id]: r.data.error }))
      } else {
        setRerunResults(prev => ({ ...prev, [report.id]: { columns: r.data.columns, rows: r.data.rows } }))
      }
    } catch (e) {
      setRerunError(prev => ({ ...prev, [report.id]: e.response?.data?.detail || e.message }))
    }
    setRerunning(null)
  }

  // ── Schedule ────────────────────────────────────────────────────────────
  const scheduleReport = async () => {
    if (!scheduleModal || !warehouseInfo) return
    setScheduling(true); setScheduleMsg('')
    try {
      await api.post('/report/schedule', {
        report_id:    String(scheduleModal.id),
        report_name:  scheduleModal.name,
        sql:          scheduleModal.sql,
        question:     scheduleModal.question,
        connector_id: warehouseInfo.id,
        schedule:     buildScheduleString(schedConfig),
        schedule_config: schedConfig,
        export_format:'csv',
      })
      setScheduleMsg(`✓ "${scheduleModal.name}" scheduled — ${buildSchedulePreview(schedConfig)}`)
      setTimeout(() => { setScheduleModal(null); setScheduleMsg('') }, 2500)
    } catch (e) { setScheduleMsg('Failed: ' + (e.response?.data?.detail || e.message)) }
    setScheduling(false)
  }

  // ── Saved reports ───────────────────────────────────────────────────────
  const saveReport = () => {
    if (!reportName.trim()) { setError('Enter a report name'); return }
    setSaving(true)
    const report = {
      id: Date.now(), name: reportName,
      pipeline_id: selectedPipeline?.id, pipeline_name: selectedPipeline?.name,
      question, sql: editedSql || queryChain[activeStep]?.sql || '',
      chart_type: chartType, x_axis: xAxis, y_axis: yAxis,
      chain: queryChain.map(s => s.instruction),
      saved_at: new Date().toISOString()
    }
    const updated = [report, ...savedReports]
    setSavedReports(updated)
    localStorage.setItem('aibridge_reports', JSON.stringify(updated))
    setSavedMsg(`✓ Saved "${reportName}"`); setReportName('')
    setTimeout(() => setSavedMsg(''), 3000); setSaving(false)
  }

  const loadReport = async (report) => {
    setQuestion(report.question || '')
    const step = { instruction: report.question || report.name, sql: report.sql, explanation: null }
    setQueryChain([step]); setActiveStep(0); setEditedSql(report.sql); setEditingSql(false)
    setChartType(report.chart_type || 'bar'); setXAxis(report.x_axis || ''); setYAxis(report.y_axis || '')
    setResults(null); setError(null); setRefinement('')
    const p = pipelines.find(p => p.id === report.pipeline_id)
    if (p) {
      setSelectedPipeline(p)
      const wh = resolveWarehouseConnector(p, connectors)
      setWarehouseInfo(wh)
      if (wh && report.sql) {
        setExecuting(true)
        try {
          const r = await api.post('/sql/run', { sql: report.sql, connector_id: wh.id })
          if (r.data.success) {
            const cols = r.data.columns || []; const rows = r.data.rows || []
            setResults({ columns: cols, rows })
            if (report.x_axis && cols.includes(report.x_axis)) setXAxis(report.x_axis)
            else setXAxis(cols[0] || '')
            if (report.y_axis && cols.includes(report.y_axis)) setYAxis(report.y_axis)
            else {
              const numericCols = cols.filter(c => {
                const v = rows[0]?.[cols.indexOf(c)]
                return typeof v === 'number' || (!isNaN(Number(v)) && v !== null && v !== '')
              })
              setYAxis(numericCols[0] || cols[1] || '')
            }
          } else { setError(r.data.error || 'Could not re-execute report SQL') }
        } catch (e) { setError(e.response?.data?.detail || e.message || 'Execution failed') }
        setExecuting(false)
      }
    }
  }

  const deleteReport = (id) => {
    const updated = savedReports.filter(r => r.id !== id)
    setSavedReports(updated)
    localStorage.setItem('aibridge_reports', JSON.stringify(updated))
    setRerunResults(prev => { const n = {...prev}; delete n[id]; return n })
  }

  // ── Chart ───────────────────────────────────────────────────────────────
  const makeChartData = (res) => res ? res.rows.map(row => {
    const obj = {}; res.columns.forEach((col, i) => { obj[col] = row[i] }); return obj
  }) : []

  const renderChart = (res, xA, yA, cType) => {
    const data = makeChartData(res)
    if (!res || data.length === 0) return null
    if (cType === 'bar') return (
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xA} tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} /><Tooltip /><Legend />
          <Bar dataKey={yA}>{data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Bar>
        </BarChart>
      </ResponsiveContainer>
    )
    if (cType === 'line') return (
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xA} tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
          <Tooltip /><Legend />
          <Line type="monotone" dataKey={yA} stroke="#185FA5" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    )
    if (cType === 'pie') return (
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie data={data} dataKey={yA} nameKey={xA} cx="50%" cy="50%" outerRadius={100}
            label={e => e[xA]}>
            {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie><Tooltip /><Legend />
        </PieChart>
      </ResponsiveContainer>
    )
    return null
  }

  const DownloadBar = ({ reportName, sql, question, small }) => (
    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
      {[
        { fmt: 'csv',   label: '⬇ CSV',   color: '#3B6D11' },
        { fmt: 'excel', label: '⬇ Excel', color: '#185FA5' },
        { fmt: 'pdf',   label: '⬇ PDF',   color: '#854F0B' },
      ].map(({ fmt, label, color }) => (
        <button key={fmt}
          style={{ padding: small ? '3px 8px' : '5px 10px', fontSize: small ? 9 : 10,
            borderRadius: 6, cursor: 'pointer', fontWeight: 500,
            background: downloading === fmt ? color : '#fff',
            color: downloading === fmt ? '#fff' : color,
            border: `1px solid ${color}`, opacity: downloading && downloading !== fmt ? 0.5 : 1 }}
          onClick={() => downloadResults(fmt, reportName, sql, question)}
          disabled={!!downloading}>
          {downloading === fmt ? '⏳' : label}
        </button>
      ))}
    </div>
  )

  const warehouseSchema = selectedPipeline?.warehouse_schema
    || selectedPipeline?.artifacts?.warehouse_schema || 'warehouse'
  const currentSql = editedSql || queryChain[activeStep]?.sql || ''
  const hasQuery   = queryChain.length > 0

  return (
    <>
      <PageHeader title="BI / Analytics"
        subtitle="Ask questions in plain English — AI generates SQL, you see charts instantly" />
      <PageBody>
        <div style={{ display: 'grid',
          gridTemplateColumns: savedReports.length > 0 ? '1fr 240px' : '1fr', gap: 16 }}>
          <div>
            {error && (
              <div style={errBox}>{error}
                <button style={{ float:'right', background:'none', border:'none',
                  cursor:'pointer', color:'#991b1b' }} onClick={() => setError(null)}>✕</button>
              </div>
            )}

            {/* Pipeline selector */}
            <div style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div style={sectionTitle}>Select pipeline (warehouse to query)</div>
                {/* 🔊 Voice controls bar */}
                {supported && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 10, color: '#888' }}>🔊 Voice</span>
                    <button
                      title={voiceOn ? 'Mute AI voice' : 'Unmute AI voice'}
                      onClick={() => { setVoiceOn(!voiceOn); stopSpeaking() }}
                      style={{ fontSize: 14, background: 'none', border: 'none', cursor: 'pointer',
                        opacity: voiceOn ? 1 : 0.4, padding: 0 }}>
                      {voiceOn ? '🔊' : '🔇'}
                    </button>
                  </div>
                )}
              </div>
              {pipelines.length === 0 ? (
                <div style={{ fontSize: 12, color: '#888' }}>No pipelines yet. Run the ETL Agent first.</div>
              ) : (
                <>
                  <select style={inp} value={selectedPipeline?.id || ''}
                    onChange={e => { const p = pipelines.find(p => p.id === e.target.value); if (p) selectPipeline(p, connectors) }}>
                    {pipelines.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                  {warehouseInfo && (
                    <div style={{ fontSize: 10, color: '#3B6D11', marginTop: 5 }}>
                      ✓ Querying schema: <span style={{ fontFamily: 'monospace' }}>{warehouseSchema}</span>
                      {' '}on <span style={{ fontFamily: 'monospace' }}>{warehouseInfo.host}:{warehouseInfo.port}/{warehouseInfo.database_name}</span>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Initial question — with voice button */}
            {!hasQuery && (
              <div style={card}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <div style={sectionTitle}>Ask a business question</div>
                  {supported && (
                    <span style={{ fontSize: 10, color: '#888' }}>
                      {listening ? '🔴 Listening...' : '🎤 Click mic to speak'}
                    </span>
                  )}
                </div>

                {/* Textarea + mic button row */}
                <div style={{ position: 'relative' }}>
                  <textarea
                    style={{ ...ta, minHeight: 70, paddingRight: supported ? 48 : 12 }}
                    value={question}
                    placeholder="e.g. Average price by brand / Top 10 cars by mileage / Price by fuel type"
                    onChange={e => setQuestion(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && e.metaKey) generateSql() }}
                  />
                  {/* Microphone button — inside textarea */}
                  {supported && (
                    <button
                      onClick={toggleListen}
                      title={listening ? 'Stop listening' : 'Speak your question'}
                      style={{
                        position: 'absolute', right: 8, top: 8,
                        width: 32, height: 32, borderRadius: '50%',
                        border: listening ? '2px solid #dc2626' : '2px solid #185FA5',
                        background: listening ? '#fef2f2' : '#EBF4FF',
                        cursor: 'pointer', fontSize: 16,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        animation: listening ? 'pulse-mic 1.2s infinite' : 'none',
                        transition: 'all 0.2s',
                      }}>
                      {listening ? '⏹' : '🎤'}
                    </button>
                  )}
                </div>

                {/* Voice status */}
                {voiceStatus && (
                  <div style={{ fontSize: 11, color: '#185FA5', marginTop: 6, fontStyle: 'italic' }}>
                    {voiceStatus}
                  </div>
                )}

                <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
                  <button style={btnPrimary} onClick={() => generateSql()}
                    disabled={loading || !selectedPipeline || !warehouseInfo}>
                    {loading ? '⏳ Generating...' : '🚀 Generate SQL'}
                  </button>
                  {supported && (
                    <span style={{ fontSize: 10, color: '#aaa' }}>
                      or press 🎤 and speak your question
                    </span>
                  )}
                </div>

                {/* Pulse animation */}
                <style>{`
                  @keyframes pulse-mic {
                    0%, 100% { box-shadow: 0 0 0 0 rgba(220,38,38,0.4); }
                    50% { box-shadow: 0 0 0 8px rgba(220,38,38,0); }
                  }
                `}</style>
              </div>
            )}

            {/* Query chain */}
            {hasQuery && (
              <>
                <div style={card}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                    <div style={sectionTitle}>Query chain ({queryChain.length} step{queryChain.length !== 1 ? 's' : ''})</div>
                    <button style={btnGhostSmall} onClick={reset}>✕ Start over</button>
                  </div>
                  {queryChain.map((step, idx) => (
                    <div key={idx} style={{ display: 'flex', gap: 10, alignItems: 'flex-start',
                      padding: '8px 0', borderBottom: idx < queryChain.length - 1 ? '1px solid #f3f4f6' : 'none' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                        <div style={{ width: 22, height: 22, borderRadius: '50%', display: 'flex',
                          alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700,
                          background: idx === activeStep ? '#185FA5' : '#e5e7eb',
                          color: idx === activeStep ? '#fff' : '#888' }}>{idx + 1}</div>
                        {idx < queryChain.length - 1 && <div style={{ width: 2, height: 20, background: '#e5e7eb', marginTop: 2 }} />}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: idx === 0 ? 600 : 400,
                          color: idx === activeStep ? '#185FA5' : '#374151' }}>
                          {idx === 0 ? '🔍 ' : '✦ '}{step.instruction}
                        </div>
                        {step.explanation && <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>→ {step.explanation}</div>}
                      </div>
                      {idx !== activeStep ? (
                        <button style={{ ...btnGhostSmall, flexShrink: 0, fontSize: 9 }} onClick={() => rollbackToStep(idx)}>↩ Use this</button>
                      ) : (
                        <span style={{ fontSize: 9, color: '#3B6D11', fontWeight: 600, flexShrink: 0,
                          padding: '2px 6px', background: '#EAF3DE', borderRadius: 10 }}>Active</span>
                      )}
                    </div>
                  ))}
                </div>

                {/* SQL viewer */}
                <div style={{ ...card, borderColor: '#854F0B', borderWidth: 2 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#854F0B' }}>Current SQL</div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button style={btnGhostSmall} onClick={() => setEditingSql(!editingSql)}>
                        {editingSql ? '✓ Done' : '✎ Edit'}
                      </button>
                      <button style={{ ...btnGhostSmall, background: '#3B6D11', color: '#fff', borderColor: '#3B6D11' }}
                        onClick={() => runSql(currentSql)} disabled={executing}>
                        {executing ? '⏳' : '▶ Re-run'}
                      </button>
                    </div>
                  </div>
                  {editingSql ? (
                    <textarea style={{ ...ta, fontFamily: 'monospace', fontSize: 11,
                      minHeight: 120, background: '#1e1e1e', color: '#d4d4d4', border: '1px solid #555' }}
                      value={editedSql} onChange={e => setEditedSql(e.target.value)} />
                  ) : (
                    <pre style={{ background: '#1e1e1e', color: '#d4d4d4', padding: '10px 14px',
                      borderRadius: 6, fontSize: 11, overflowX: 'auto', lineHeight: 1.6,
                      maxHeight: 160, overflow: 'auto', margin: 0 }}>{currentSql}</pre>
                  )}
                </div>

                {/* Refinement */}
                <div style={{ ...card, borderColor: '#185FA5', borderWidth: 2 }}>
                  <div style={sectionTitle}>✦ Refine this query</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input ref={refinementRef} style={{ ...inp, flex: 1 }} value={refinement}
                      placeholder="e.g. only petrol cars / top 10 / sort by price descending"
                      onChange={e => setRefinement(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') applyRefinement() }} />
                    <button style={btnPrimary} onClick={() => applyRefinement()}
                      disabled={refining || !refinement.trim()}>
                      {refining ? '⏳' : '+ Apply'}
                    </button>
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8 }}>
                    {REFINEMENT_SUGGESTIONS.map(s => (
                      <button key={s} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 12,
                        cursor: 'pointer', background: '#f0f4ff', color: '#185FA5',
                        border: '1px solid #c7d7f5' }} onClick={() => applyRefinement(s)}>{s}</button>
                    ))}
                  </div>
                </div>
              </>
            )}

            {/* Results */}
            {results && (
              <div style={card}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#3B6D11' }}>
                    ✓ {results.rows.length} rows
                    {executing && <span style={{ color: '#888', fontWeight: 400 }}> (refreshing…)</span>}
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    {/* 🔊 Re-read button */}
                    {supported && voiceOn && (
                      <button
                        title="Read results aloud"
                        onClick={() => {
                          const top = results.rows.slice(0, 3).map(row =>
                            results.columns.map((c, i) => `${c}: ${row[i]}`).join(', ')
                          ).join('; ')
                          speak(`${results.rows.length} results. Top entries: ${top}`)
                        }}
                        style={{ fontSize: 16, background: 'none', border: 'none', cursor: 'pointer', padding: '0 4px' }}
                      >🔊</button>
                    )}
                    <DownloadBar reportName={question} sql={currentSql} question={question} />
                    <div style={{ display: 'flex', gap: 4 }}>
                      {['bar','line','pie','table'].map(t => (
                        <button key={t} onClick={() => setChartType(t)}
                          style={{ padding: '4px 8px', fontSize: 10, borderRadius: 6, cursor: 'pointer',
                            background: chartType === t ? '#185FA5' : '#fff',
                            color: chartType === t ? '#fff' : '#555',
                            border: `1px solid ${chartType === t ? '#185FA5' : '#d1d5db'}` }}>
                          {t === 'bar' ? '▥' : t === 'line' ? '📈' : t === 'pie' ? '🥧' : '⊞'}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                {chartType !== 'table' && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
                    <div>
                      <label style={{ fontSize: 10, color: '#888', display: 'block', marginBottom: 3 }}>X Axis</label>
                      <select style={{ ...inp, fontSize: 11 }} value={xAxis} onChange={e => setXAxis(e.target.value)}>
                        {results.columns.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                    <div>
                      <label style={{ fontSize: 10, color: '#888', display: 'block', marginBottom: 3 }}>Y Axis</label>
                      <select style={{ ...inp, fontSize: 11 }} value={yAxis} onChange={e => setYAxis(e.target.value)}>
                        {results.columns.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                  </div>
                )}
                {chartType !== 'table' && renderChart(results, xAxis, yAxis, chartType)}
                <div style={{ overflowX: 'auto', marginTop: chartType !== 'table' ? 14 : 0 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                    <thead><tr>{results.columns.map(c => (
                      <th key={c} style={{ background: '#f9fafb', padding: '6px 10px', textAlign: 'left',
                        borderBottom: '1px solid #e5e7eb', fontWeight: 600, color: '#555',
                        fontSize: 10, textTransform: 'uppercase' }}>{c}</th>
                    ))}</tr></thead>
                    <tbody>{results.rows.slice(0, 100).map((row, i) => (
                      <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                        {row.map((cell, j) => (
                          <td key={j} style={{ padding: '5px 10px', borderBottom: '1px solid #f3f4f6',
                            color: '#333', fontFamily: typeof cell === 'number' ? 'monospace' : 'inherit' }}>
                            {cell === null ? <span style={{ color: '#aaa' }}>null</span> : String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}</tbody>
                  </table>
                  {results.rows.length > 100 && <div style={{ fontSize: 10, color: '#888', padding: '6px 10px' }}>Showing first 100 of {results.rows.length} rows</div>}
                </div>
                <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #f3f4f6' }}>
                  <div style={sectionTitle}>💾 Save as report</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input style={{ ...inp, flex: 1 }} placeholder="Report name"
                      value={reportName} onChange={e => setReportName(e.target.value)} />
                    <button style={btnPrimary} onClick={saveReport} disabled={saving}>Save</button>
                  </div>
                  {savedMsg && <div style={{ fontSize: 11, color: '#3B6D11', marginTop: 6 }}>{savedMsg}</div>}
                </div>
              </div>
            )}
          </div>

          {/* ── SAVED REPORTS ── */}
          {savedReports.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#555',
                textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }}>
                Saved Reports ({savedReports.length})
              </div>
              {savedReports.map(r => (
                <div key={r.id} style={{ ...card, padding: '10px 12px', marginBottom: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                    <div style={{ flex: 1, cursor: 'pointer' }} onClick={() => loadReport(r)}>
                      <div style={{ fontSize: 12, fontWeight: 600, color: '#185FA5' }}>{r.name}</div>
                      <div style={{ fontSize: 10, color: '#888' }}>{r.pipeline_name}</div>
                      <div style={{ fontSize: 11, color: '#555', marginTop: 3, lineHeight: 1.4 }}>{r.question}</div>
                    </div>
                    <button style={{ ...btnGhostSmall, color: '#A32D2D', borderColor: '#A32D2D', fontSize: 9 }}
                      onClick={() => deleteReport(r.id)}>✕</button>
                  </div>
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 6 }}>
                    <button style={{ ...btnGhostSmall, color: '#3B6D11', borderColor: '#3B6D11' }}
                      onClick={() => rerunReport(r)} disabled={rerunning === r.id}>
                      {rerunning === r.id ? '⏳' : '▶ Re-run'}
                    </button>
                    <button style={{ ...btnGhostSmall, color: '#854F0B', borderColor: '#854F0B' }}
                      onClick={() => { setScheduleModal(r); setSchedConfig({ ...DEFAULT_SCHED_CONFIG }) }}>
                      ⏰ Schedule
                    </button>
                    <button style={btnGhostSmall} onClick={() => loadReport(r)}>✎ Edit</button>
                  </div>
                  {rerunError[r.id] && (
                    <div style={{ fontSize: 10, color: '#991b1b', marginBottom: 6 }}>✗ {rerunError[r.id]}</div>
                  )}
                  {rerunResults[r.id] && (
                    <div style={{ marginTop: 6, border: '1px solid #EAF3DE', borderRadius: 6,
                      padding: '8px 10px', background: '#f9fafb' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                        <div style={{ fontSize: 10, fontWeight: 600, color: '#3B6D11' }}>
                          ✓ {rerunResults[r.id].rows.length} rows
                        </div>
                        <DownloadBar reportName={r.name} sql={r.sql} question={r.question} small />
                      </div>
                      {renderChart(rerunResults[r.id], rerunResults[r.id].columns[0],
                        rerunResults[r.id].columns[1], r.chart_type || 'bar')}
                      <div style={{ overflowX: 'auto', marginTop: 8 }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                          <thead><tr>{rerunResults[r.id].columns.map(c => (
                            <th key={c} style={{ background: '#f3f4f6', padding: '4px 8px',
                              textAlign: 'left', borderBottom: '1px solid #e5e7eb',
                              fontSize: 9, color: '#555', textTransform: 'uppercase' }}>{c}</th>
                          ))}</tr></thead>
                          <tbody>{rerunResults[r.id].rows.slice(0, 20).map((row, i) => (
                            <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                              {row.map((cell, j) => (
                                <td key={j} style={{ padding: '3px 8px', borderBottom: '1px solid #f3f4f6', color: '#333' }}>
                                  {cell === null ? <span style={{ color: '#aaa' }}>null</span> : String(cell)}
                                </td>
                              ))}
                            </tr>
                          ))}</tbody>
                        </table>
                        {rerunResults[r.id].rows.length > 20 && (
                          <div style={{ fontSize: 9, color: '#888', padding: '4px 8px' }}>
                            Showing 20 of {rerunResults[r.id].rows.length} rows
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  <div style={{ fontSize: 9, color: '#aaa', marginTop: 6 }}>
                    {new Date(r.saved_at).toLocaleDateString()}
                    {r.chain?.length > 1 && ` · ${r.chain.length} refinements`}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Schedule modal ── */}
        {scheduleModal && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
            zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ background: '#fff', borderRadius: 10, width: 540,
              maxHeight: '90vh', overflowY: 'auto', padding: 20,
              boxShadow: '0 8px 32px rgba(0,0,0,0.15)' }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 2 }}>⏰ Schedule Report</div>
              <div style={{ fontSize: 11, color: '#888', marginBottom: 16 }}>
                {scheduleModal.name}{scheduleModal.question && ` — "${scheduleModal.question}"`}
              </div>
              <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Frequency</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6, marginBottom: 16 }}>
                {FREQUENCY_OPTIONS.map(opt => (
                  <label key={opt.value} style={{ display: 'flex', alignItems: 'flex-start', gap: 8,
                    padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                    border: `1.5px solid ${schedConfig.frequency === opt.value ? '#185FA5' : '#e5e7eb'}`,
                    background: schedConfig.frequency === opt.value ? '#EBF4FF' : '#fff' }}>
                    <input type="radio" name="sched_freq" value={opt.value}
                      checked={schedConfig.frequency === opt.value}
                      onChange={() => setSchedC('frequency', opt.value)}
                      style={{ marginTop: 2 }} />
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 600,
                        color: schedConfig.frequency === opt.value ? '#185FA5' : '#374151' }}>{opt.label}</div>
                      <div style={{ fontSize: 9, color: '#888', marginTop: 1 }}>{opt.desc}</div>
                    </div>
                  </label>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                    textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Run Time</div>
                  <input type="time" value={schedConfig.time}
                    onChange={e => setSchedC('time', e.target.value)}
                    style={{ padding: '6px 10px', fontSize: 13, fontWeight: 600,
                      border: '1px solid #d1d5db', borderRadius: 6, color: '#185FA5' }} />
                </div>
                {schedConfig.frequency === 'weekly' && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                      textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Day of Week</div>
                    <select value={schedConfig.day_of_week}
                      onChange={e => setSchedC('day_of_week', e.target.value)} style={selStyle}>
                      {DAYS_OF_WEEK.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
                    </select>
                  </div>
                )}
                {['monthly','quarterly','halfyearly','yearly'].includes(schedConfig.frequency) && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                      textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Day of Month</div>
                    <select value={schedConfig.day_of_month}
                      onChange={e => setSchedC('day_of_month', e.target.value)} style={selStyle}>
                      {Array.from({ length: 28 }, (_, i) => i + 1).map(d => (
                        <option key={d} value={String(d)}>{d}</option>
                      ))}
                    </select>
                  </div>
                )}
                {schedConfig.frequency === 'yearly' && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: '#888',
                      textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Month</div>
                    <select value={schedConfig.month}
                      onChange={e => setSchedC('month', e.target.value)} style={selStyle}>
                      {MONTHS_OF_YEAR.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                  </div>
                )}
              </div>
              <div style={{ background: '#EBF4FF', borderRadius: 6, padding: '8px 12px',
                marginBottom: 14, fontSize: 11, color: '#185FA5', fontWeight: 600 }}>
                ⏱ {buildSchedulePreview(schedConfig)}
              </div>
              <div style={{ fontSize: 10, color: '#888', marginBottom: 14, padding: '8px 10px',
                background: '#f9fafb', borderRadius: 6 }}>
                💡 On each scheduled run: SQL executes against the warehouse, result is logged. $0 AI cost per run.
              </div>
              {scheduleMsg && (
                <div style={{ fontSize: 11, marginBottom: 10,
                  color: scheduleMsg.startsWith('✓') ? '#3B6D11' : '#991b1b' }}>{scheduleMsg}</div>
              )}
              <div style={{ display: 'flex', gap: 8 }}>
                <button style={btnPrimary} onClick={scheduleReport} disabled={scheduling}>
                  {scheduling ? '⏳ Scheduling...' : '⏰ Save Schedule'}
                </button>
                <button style={btnGhost}
                  onClick={() => { setScheduleModal(null); setScheduleMsg(''); setSchedConfig({ ...DEFAULT_SCHED_CONFIG }) }}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </PageBody>
    </>
  )
}

const inp           = { width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box' }
const ta            = { width: '100%', padding: '8px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, fontFamily: 'system-ui', resize: 'vertical', boxSizing: 'border-box' }
const card          = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }
const errBox        = { background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#991b1b', marginBottom: 10 }
const sectionTitle  = { fontSize: 10, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }
const btnPrimary    = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhost      = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnGhostSmall = { padding: '4px 10px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 10, cursor: 'pointer' }
const selStyle      = { padding: '6px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, background: '#fff', cursor: 'pointer', minWidth: 130 }
