/**
 * Analytics.jsx — BI / Analytics tab
 * v1.6: Connection Mode added — query any DB directly without a pipeline.
 * v1.5: Voice Mode — speak questions, hear answers back.
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
  { value: 'daily',       label: 'Daily',       desc: 'Every day at custom time',   hasTime: true  },
  { value: 'weekly',      label: 'Weekly',      desc: 'Every selected day',         hasTime: true, hasDay: true },
  { value: 'monthly',     label: 'Monthly',     desc: 'Selected date each month',   hasTime: true, hasDate: true },
  { value: 'quarterly',   label: 'Quarterly',   desc: 'Every 3 months',             hasTime: true },
  { value: 'halfyearly',  label: 'Half Yearly', desc: 'Every 6 months',             hasTime: true },
  { value: 'yearly',      label: 'Yearly',      desc: 'Once a year',                hasTime: true },
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

// ── Voice hook ────────────────────────────────────────────────────────────────
function useVoice(onResult, voiceLang = "en", languages = []) {
  const [listening, setListening] = useState(false)
  const [supported, setSupported] = useState(false)
  const [voiceOn,   setVoiceOn]   = useState(true)
  const recogRef = useRef(null)

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return
    setSupported(true)
    const r = new SR()
    r.continuous = false; r.interimResults = false; r.lang = languages.find(l => l.code === voiceLang)?.web_speech_code || 'en-IN'
    r.onresult = (e) => { onResult(e.results[0][0].transcript); setListening(false) }
    r.onend = () => setListening(false)
    r.onerror = () => setListening(false)
    recogRef.current = r
  }, [onResult, voiceLang])

  const toggleListen = useCallback(() => {
    if (!recogRef.current) return
    if (listening) { recogRef.current.stop(); setListening(false) }
    else { try { recogRef.current.start(); setListening(true) } catch {} }
  }, [listening])

  const speak = useCallback((text, langCode) => {
    if (!voiceOn || !window.speechSynthesis) return
    window.speechSynthesis.cancel()
    const clean = text.replace(/```[\s\S]*?```/g,'').replace(/[#*_`>]/g,'').replace(/\n+/g,' ').trim().slice(0,400)
    const utt = new SpeechSynthesisUtterance(clean)
    // Use provided langCode or fall back to en-IN
    const langMap = {hi:'hi-IN',ta:'ta-IN',te:'te-IN',ar:'ar-SA',zh:'zh-CN',
      ru:'ru-RU',de:'de-DE',fr:'fr-FR',es:'es-ES',pt:'pt-BR',
      ms:'ms-MY',af:'af-ZA',en:'en-IN'}
    utt.lang = langMap[langCode] || langCode || 'en-IN'
    utt.rate = 0.93; utt.pitch = 1
    window.speechSynthesis.speak(utt)
  }, [voiceOn])

  const stopSpeaking = useCallback(() => { window.speechSynthesis?.cancel() }, [])

  return { listening, supported, voiceOn, setVoiceOn, toggleListen, speak, stopSpeaking }
}

export default function Analytics() {
  // Pipeline mode
  const [pipelines,        setPipelines]        = useState([])
  const [connectors,       setConnectors]       = useState([])
  const [selectedPipeline, setSelectedPipeline] = useState(null)
  const [warehouseInfo,    setWarehouseInfo]    = useState(null)
  // Connection mode
  const [mode,           setMode]           = useState('pipeline')
  const [allConnectors,  setAllConnectors]  = useState([])
  const [selectedConnId, setSelectedConnId] = useState('')
  // Query
  const [question,      setQuestion]      = useState('')
  const [loading,       setLoading]       = useState(false)
  const [executing,     setExecuting]     = useState(false)
  const [error,         setError]         = useState(null)
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
  // Reports
  const [savedReports,  setSavedReports]  = useState([])
  const [reportName,    setReportName]    = useState('')
  const [saving,        setSaving]        = useState(false)
  const [savedMsg,      setSavedMsg]      = useState('')
  const [rerunning,     setRerunning]     = useState(null)
  const [rerunResults,  setRerunResults]  = useState({})
  const [rerunError,    setRerunError]    = useState({})
  const [downloading,   setDownloading]   = useState(null)
  // Schedule
  const [scheduleModal, setScheduleModal] = useState(null)
  const [schedConfig,   setSchedConfig]   = useState({ ...DEFAULT_SCHED_CONFIG })
  const setSchedC = (k, v) => setSchedConfig(p => ({ ...p, [k]: v }))
  const [scheduling,    setScheduling]    = useState(false)
  const [scheduleMsg,   setScheduleMsg]   = useState('')
  // Voice
  const [voiceStatus,   setVoiceStatus]   = useState('')
  const [voiceLang, setVoiceLang] = useState(() => localStorage.getItem('aibridge_voice_lang') || 'en')
  const [languages,     setLanguages]     = useState([
    { code: 'en', name: 'English',  flag: '🇬🇧', web_speech_code: 'en-IN' },
    { code: 'hi', name: 'Hindi',    flag: '🇮🇳', web_speech_code: 'hi-IN' },
    { code: 'ta', name: 'Tamil',    flag: '🇮🇳', web_speech_code: 'ta-IN' },
    { code: 'te', name: 'Telugu',   flag: '🇮🇳', web_speech_code: 'te-IN' },
    { code: 'ar', name: 'Arabic',   flag: '🇸🇦', web_speech_code: 'ar-SA' },
    { code: 'zh', name: 'Chinese',  flag: '🇨🇳', web_speech_code: 'zh-CN' },
    { code: 'ru', name: 'Russian',  flag: '🇷🇺', web_speech_code: 'ru-RU' },
    { code: 'de', name: 'German',   flag: '🇩🇪', web_speech_code: 'de-DE' },
    { code: 'fr', name: 'French',   flag: '🇫🇷', web_speech_code: 'fr-FR' },
    { code: 'es', name: 'Spanish',  flag: '🇪🇸', web_speech_code: 'es-ES' },
    { code: 'sw', name: 'Swahili',  flag: '🇰🇪', web_speech_code: 'sw-KE' },
    { code: 'ha', name: 'Hausa',    flag: '🇳🇬', web_speech_code: 'ha-NE' },
    { code: 'yo', name: 'Yoruba',   flag: '🇳🇬', web_speech_code: 'yo-NG' },
    { code: 'zu', name: 'Zulu',     flag: '🇿🇦', web_speech_code: 'zu-ZA' },
    { code: 'af', name: 'Afrikaans',flag: '🇿🇦', web_speech_code: 'af-ZA' },
    { code: 'sn', name: 'Shona',      flag: '🇿🇼', web_speech_code: 'en-US' },
    { code: 'ms', name: 'Malay',       flag: '🇲🇾', web_speech_code: 'ms-MY' },
  ])
  const refinementRef  = useRef(null)
  const voiceSubmitRef = useRef(null)
  const voiceRefineRef = useRef(null)
  const voiceChainRef  = useRef([])
  const mediaRecorderRef = useRef(null)
  const audioChunksRef   = useRef([])
  const [recording, setRecording] = useState(false)

  // Whisper-based recording for non-English languages
  const WHISPER_LANGS = ['sw','ha','yo','zu','xh','am','af','ig','so','sn','ms']

  const startWhisperRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data)
      }

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop())
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
        setVoiceStatus('Transcribing with Whisper...')
        try {
          const formData = new FormData()
          formData.append('audio', audioBlob, 'recording.webm')
          formData.append('language', voiceLang !== 'en' ? voiceLang : '')
          const res = await api.post('/voice/transcribe', formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
          })
          if (res.data.success && res.data.text) {
            handleVoiceResult(res.data.text)
          } else {
            setVoiceStatus('Could not transcribe audio')
            setTimeout(() => setVoiceStatus(''), 3000)
          }
        } catch(e) {
          setVoiceStatus('Transcription failed: ' + e.message)
          setTimeout(() => setVoiceStatus(''), 3000)
        }
        setRecording(false)
      }

      mediaRecorder.start()
      setRecording(true)
      setVoiceStatus('Recording... speak now')

      // Auto-stop after 8 seconds
      setTimeout(() => {
        if (mediaRecorderRef.current?.state === 'recording') {
          mediaRecorderRef.current.stop()
          setVoiceStatus('Processing...')
        }
      }, 8000)
    } catch(e) {
      setVoiceStatus('Microphone access denied')
      setTimeout(() => setVoiceStatus(''), 3000)
    }
  }

  const stopWhisperRecording = () => {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop()
    }
  }

  const handleMicClick = () => {
    // Always use Whisper — supports 99 languages, private, no internet needed
    if (recording) stopWhisperRecording()
    else startWhisperRecording()
  }

  const handleVoiceResult = useCallback(async (text) => {
    setVoiceStatus(`Heard: "${text}"`)
    
    // If non-English, translate first
    let processedText = text
    if (voiceLang !== 'en') {
      try {
        setVoiceStatus(`Translating from ${languages.find(l=>l.code===voiceLang)?.name}...`)
        const r = await api.post('/voice/translate', { text, source_lang: voiceLang, target_lang: 'en' })
        processedText = r.data.translated || text
        setVoiceStatus(`Heard (${languages.find(l=>l.code===voiceLang)?.name}): "${text}" → "${processedText}"`)
      } catch(e) {
        console.log('Translation failed:', e)
        setVoiceStatus(`Heard: "${text}" (translation failed)`)
      }
    } else {
      setVoiceStatus(`Heard: "${text}"`)
    }
    
    setTimeout(() => setVoiceStatus(''), 4000)
    setTimeout(() => {
      if (voiceChainRef.current && voiceChainRef.current.length > 0) {
        setRefinement(processedText)
        voiceRefineRef.current?.(processedText)
      } else {
        setQuestion(processedText)
        voiceSubmitRef.current?.(processedText)
      }
    }, 600)
  }, [voiceLang, languages])

  const { listening, supported, voiceOn, setVoiceOn, toggleListen, speak, stopSpeaking } = useVoice(handleVoiceResult, voiceLang, languages)

  // gTTS speak — backend TTS, supports 60+ languages including African
  const speakWithGTTS = useCallback(async (text, langCode) => {
    if (!voiceOn) return
    try {
      window.speechSynthesis?.cancel()
      if (window._gttsAudio) { window._gttsAudio.pause(); window._gttsAudio = null }
      const response = await fetch('http://localhost:8888/voice/tts', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + localStorage.getItem('aibridge_token')
        },
        body: JSON.stringify({ text: text.slice(0, 400), lang: langCode || 'en' })
      })
      if (!response.ok) throw new Error('TTS failed')
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      window._gttsAudio = audio
      audio.onended = () => URL.revokeObjectURL(url)
      audio.play()
    } catch(e) {
      console.log('gTTS failed, falling back:', e)
      speak(text, langCode)
    }
  }, [voiceOn, speak])

  useEffect(() => {
    Promise.all([api.get('/pipeline/list'), api.get('/connector/list')])
      .then(([pRes, cRes]) => {
        const list  = pRes.data.pipelines || []
        const conns = cRes.data.connectors || []
        setPipelines(list); setConnectors(conns)
        if (list.length > 0) selectPipeline(list[0], conns)
        const dbConns = conns.filter(c => c.connector_type !== 'duckdb')
        setAllConnectors(dbConns)
        if (dbConns.length > 0) setSelectedConnId(dbConns[0].id)
      }).catch(() => {})
    setSavedReports(JSON.parse(localStorage.getItem('aibridge_reports') || '[]'))
  }, [])

  const resolveWarehouseConnector = (pipeline, conns) => {
    if (!pipeline) return null
    const all = conns || connectors
    if (pipeline.target_connector_id) {
      const tgt = all.find(c => c.id === pipeline.target_connector_id)
      if (tgt) return tgt
    }
    const src = all.find(c => c.id === pipeline.connector_id)
    if (src?.connector_type === 'duckdb') {
      const pg = all.find(c => c.connector_type === 'postgres' && c.is_active !== false)
      if (pg) return pg
    }
    return src || null
  }

  const selectPipeline = (pipeline, conns) => {
    setSelectedPipeline(pipeline)
    setWarehouseInfo(resolveWarehouseConnector(pipeline, conns))
    reset()
  }

  // Active connector ID — depends on mode
  const activeConnId = () => {
    const id = mode === 'connection' ? selectedConnId : warehouseInfo?.id
    console.log('[Debug] activeConnId:', id, 'mode:', mode, 'selectedConnId:', selectedConnId)
    return id
  }

  // ── SQL generation ─────────────────────────────────────────────────────────
  const generateSql = async (questionOverride) => {
    const q = questionOverride || question
    if (!q.trim()) { setError('Enter a question first'); return }
    if (mode === 'pipeline' && !selectedPipeline) { setError('Select a pipeline first'); return }
    if (mode === 'pipeline' && !warehouseInfo) { setError('Could not resolve warehouse connector.'); return }
    if (mode === 'connection' && !selectedConnId) { setError('Select a connection first'); return }
    setError(null); setLoading(true); setResults(null); setQueryChain([])
    try {
      const r = mode === 'connection'
        ? await api.post('/chat', { message: q, connector_id: activeConnId(), history: [] })
        : await api.post('/nl/to-sql', { question: q, connector_id: activeConnId(), pipeline_id: selectedPipeline?.id || '' })
      const isChat = mode === 'connection'
      const sql_data = isChat ? r.data.sql_result : r.data
      if (!isChat && !r.data.success) { setError(r.data.error || 'AI could not generate SQL'); setLoading(false); return }
      if (isChat && !r.data.sql_result) {
        // Auto-extract and execute SQL from markdown blocks in response
        const allBlocks = [...(r.data.response?.matchAll(/```(?:sql)?\s*([\s\S]*?)```/gi) || [])]
        const bestSql = allBlocks.map(m => m[1].trim()).sort((a,b) => b.length - a.length)[0]
        console.log("[AutoExec] blocks found:", allBlocks.length, "bestSql:", bestSql?.slice(0,50))
        if (bestSql) {
          try {
            const runRes = await api.post('/sql/run', { sql: bestSql, connector_id: activeConnId() })
            if (runRes.data.success) {
              r.data.sql_result = { sql: bestSql, columns: runRes.data.columns, rows: runRes.data.rows }
            }
          } catch(e) { console.log('Auto-exec failed:', e) }
        }
        if (!r.data.sql_result) {
          setError(r.data.response?.slice(0, 200) || 'Could not generate SQL')
          setLoading(false); return
        }
      }
      // safety check handled above
      const step = { instruction: q, sql: isChat ? r.data.sql_result?.sql : r.data.sql, explanation: isChat ? r.data.response : null }
      setQueryChain([step]); setActiveStep(0); setEditedSql(r.data.sql); setEditingSql(false)
      await runSql(r.data.sql, q)
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Failed to generate SQL')
    }
    setLoading(false)
  }

  useEffect(() => { voiceSubmitRef.current = generateSql }, [selectedPipeline, warehouseInfo, mode, selectedConnId])
  useEffect(() => { voiceRefineRef.current = applyRefinement }, [queryChain, activeStep, editedSql])

  useEffect(() => { voiceChainRef.current = queryChain }, [queryChain])

  // ── Refinement ─────────────────────────────────────────────────────────────
  const applyRefinement = async (instruction) => {
    const text = instruction || refinement
    if (!text.trim() || queryChain.length === 0) return
    setRefining(true); setError(null)
    const currentSql = editedSql || queryChain[activeStep]?.sql || ''
    const history = queryChain.slice(0, activeStep).map(s => ({ instruction: s.instruction, sql: s.sql }))
    try {
      const r = await api.post('/nl/refine-sql', {
        current_sql: currentSql, refinement: text,
        connector_id: activeConnId() || '', history
      })
      if (!r.data.success) { setError(r.data.error || 'Could not refine SQL'); setRefining(false); return }
      const newStep = { instruction: text, sql: r.data.sql, explanation: r.data.explanation }
      const newChain = [...queryChain.slice(0, activeStep + 1), newStep]
      setQueryChain(newChain); setActiveStep(newChain.length - 1)
      setEditedSql(r.data.sql); setEditingSql(false); setRefinement('')
      await runSql(r.data.sql)
      setTimeout(() => refinementRef.current?.focus(), 100)
    } catch (e) { setError(e.response?.data?.detail || e.message || 'Refinement failed') }
    setRefining(false)
  }

  // ── SQL execution ──────────────────────────────────────────────────────────
  const runSql = async (sqlToRun, questionCtx) => {
    const sql = sqlToRun || editedSql || queryChain[activeStep]?.sql
    if (!sql) return
    setExecuting(true); setError(null)
    try {
      const r = await api.post('/sql/run', { sql, connector_id: activeConnId() })
      if (!r.data.success) { setError(r.data.error || 'SQL execution failed'); setExecuting(false); return }
      const cols = r.data.columns || []; const rows = r.data.rows || []
      setResults({ columns: cols, rows })
      const numericCols = cols.filter(c => {
        const v = rows[0]?.[cols.indexOf(c)]
        return typeof v === 'number' || (!isNaN(Number(v)) && v !== null && v !== '')
      })
      setXAxis(cols.filter(c => !numericCols.includes(c))[0] || cols[0] || '')
      setYAxis(numericCols[0] || cols[1] || '')
      if (rows.length > 0) {
        const q = questionCtx || question
        const top = rows.slice(0,3).map(row => cols.map((c,i) => `${c}: ${row[i]}`).join(', ')).join('; ')
        const englishSummary = `Found ${rows.length} results for "${q}". Top results are: ${top}`
        // Translate answer back to user's language if not English
        const currentLang = localStorage.getItem('aibridge_voice_lang') || voiceLang || 'en'
        console.log('[Debug TTS] voiceLang=', voiceLang, 'localStorage=', currentLang)
        if (currentLang && currentLang !== 'en') {
          api.post('/voice/translate', { text: englishSummary, source_lang: 'en', target_lang: currentLang })
            .then(r => {
              const translated = r.data.translated || englishSummary
              speakWithGTTS(translated, currentLang)
            })
            .catch(() => speakWithGTTS(englishSummary, currentLang))
        } else {
          speakWithGTTS(englishSummary, currentLang)
        }
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

  // ── Download ───────────────────────────────────────────────────────────────
  const downloadResults = async (format, rNameOverride, sqlOverride, qOverride) => {
    const sql   = sqlOverride || editedSql || queryChain[activeStep]?.sql
    const rName = rNameOverride || reportName || question || 'report'
    const q     = qOverride || question
    if (!sql) { setError('No SQL to export'); return }
    setDownloading(format)
    try {
      const res = await api.post('/report/export', {
        sql, connector_id: activeConnId(), format, report_name: rName, question: q
      }, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data]))
      const a   = document.createElement('a')
      a.href = url; a.download = `${rName.replace(/\s+/g,'_')}.${format==='excel'?'xlsx':format}`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) { setError('Download failed: ' + (e.response?.data?.detail || e.message)) }
    setDownloading(null)
  }

  // ── Re-run ────────────────────────────────────────────────────────────────
  const rerunReport = async (report) => {
    setRerunning(report.id); setRerunError(p => ({ ...p, [report.id]: null }))
    try {
      const r = await api.post('/sql/run', { sql: report.sql, connector_id: activeConnId() })
      if (!r.data.success) setRerunError(p => ({ ...p, [report.id]: r.data.error }))
      else setRerunResults(p => ({ ...p, [report.id]: { columns: r.data.columns, rows: r.data.rows } }))
    } catch (e) { setRerunError(p => ({ ...p, [report.id]: e.response?.data?.detail || e.message })) }
    setRerunning(null)
  }

  // ── Schedule ──────────────────────────────────────────────────────────────
  const scheduleReport = async () => {
    if (!scheduleModal) return
    setScheduling(true); setScheduleMsg('')
    try {
      await api.post('/report/schedule', {
        report_id: String(scheduleModal.id), report_name: scheduleModal.name,
        sql: scheduleModal.sql, question: scheduleModal.question,
        connector_id: activeConnId(), schedule: buildScheduleString(schedConfig),
        schedule_config: schedConfig, export_format: 'csv',
      })
      setScheduleMsg(`✓ "${scheduleModal.name}" scheduled — ${buildSchedulePreview(schedConfig)}`)
      setTimeout(() => { setScheduleModal(null); setScheduleMsg('') }, 2500)
    } catch (e) { setScheduleMsg('Failed: ' + (e.response?.data?.detail || e.message)) }
    setScheduling(false)
  }

  // ── Saved reports ─────────────────────────────────────────────────────────
  const saveReport = () => {
    if (!reportName.trim()) { setError('Enter a report name'); return }
    setSaving(true)
    const report = {
      id: Date.now(), name: reportName,
      pipeline_id: selectedPipeline?.id, pipeline_name: selectedPipeline?.name,
      question, sql: editedSql || queryChain[activeStep]?.sql || '',
      chart_type: chartType, x_axis: xAxis, y_axis: yAxis,
      chain: queryChain.map(s => s.instruction), saved_at: new Date().toISOString()
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
              const nc = cols.filter(c => { const v = rows[0]?.[cols.indexOf(c)]; return typeof v==='number'||(!isNaN(Number(v))&&v!==null&&v!=='') })
              setYAxis(nc[0] || cols[1] || '')
            }
          } else setError(r.data.error || 'Could not re-execute report SQL')
        } catch (e) { setError(e.response?.data?.detail || e.message || 'Execution failed') }
        setExecuting(false)
      }
    }
  }

  const deleteReport = (id) => {
    const updated = savedReports.filter(r => r.id !== id)
    setSavedReports(updated)
    localStorage.setItem('aibridge_reports', JSON.stringify(updated))
    setRerunResults(p => { const n={...p}; delete n[id]; return n })
  }

  // ── Chart ─────────────────────────────────────────────────────────────────
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
          <XAxis dataKey={xA} tick={{ fontSize: 11 }} /><YAxis tick={{ fontSize: 11 }} />
          <Tooltip /><Legend />
          <Bar dataKey={yA}>{data.map((_,i) => <Cell key={i} fill={COLORS[i%COLORS.length]} />)}</Bar>
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
          <Pie data={data} dataKey={yA} nameKey={xA} cx="50%" cy="50%" outerRadius={100} label={e => e[xA]}>
            {data.map((_,i) => <Cell key={i} fill={COLORS[i%COLORS.length]} />)}
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
          style={{ padding: small?'3px 8px':'5px 10px', fontSize: small?9:10,
            borderRadius: 6, cursor: 'pointer', fontWeight: 500,
            background: downloading===fmt ? color : '#fff',
            color: downloading===fmt ? '#fff' : color,
            border: `1px solid ${color}`, opacity: downloading&&downloading!==fmt?0.5:1 }}
          onClick={() => downloadResults(fmt, reportName, sql, question)}
          disabled={!!downloading}>
          {downloading===fmt ? '⏳' : label}
        </button>
      ))}
    </div>
  )

  const warehouseSchema = selectedPipeline?.warehouse_schema || selectedPipeline?.artifacts?.warehouse_schema || 'warehouse'
  const currentSql = editedSql || queryChain[activeStep]?.sql || ''
  const hasQuery   = queryChain.length > 0

  return (
    <>
      <PageHeader title="BI / Analytics"
        subtitle="Ask questions in plain English — AI generates SQL, you see charts instantly" />
      <PageBody>
        <div style={{ display: 'grid', gridTemplateColumns: savedReports.length > 0 ? '1fr 240px' : '1fr', gap: 16 }}>
          <div>
            {error && (
              <div style={errBox}>{error}
                <button style={{ float:'right', background:'none', border:'none', cursor:'pointer', color:'#991b1b' }}
                  onClick={() => setError(null)}>✕</button>
              </div>
            )}

            {/* ── Selector card ── */}
            <div style={card}>
              {/* Header row: title + voice + mode toggle */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={sectionTitle}>
                  {mode === 'connection' ? '🔌 Connection Mode — query any database directly' : '📊 Pipeline Mode — query warehouse schema'}
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {supported && (
                    <button title={voiceOn ? 'Mute AI voice' : 'Unmute AI voice'}
                      onClick={() => { setVoiceOn(!voiceOn); stopSpeaking() }}
                      style={{ fontSize: 14, background: 'none', border: 'none', cursor: 'pointer', opacity: voiceOn?1:0.4, padding: 0 }}>
                      {voiceOn ? '🔊' : '🔇'}
                    </button>
                  )}
                  {supported && (
                    <select value={voiceLang} onChange={e => { setVoiceLang(e.target.value); localStorage.setItem('aibridge_voice_lang', e.target.value) }}
                      title="Voice language"
                      style={{ fontSize: 11, padding: '2px 6px', border: '1px solid #E5E7EB',
                        borderRadius: 6, background: '#F9FAFB', cursor: 'pointer', maxWidth: 120 }}>
                      {languages.map(l => (
                        <option key={l.code} value={l.code}>{l.flag} {l.name}</option>
                      ))}
                    </select>
                  )}
                  <button onClick={() => setMode(mode === 'pipeline' ? 'connection' : 'pipeline')} style={{
                    padding: '4px 12px', borderRadius: 12, fontSize: 10, cursor: 'pointer', fontWeight: 600,
                    background: mode === 'connection' ? '#0B5D73' : '#EBF4FF',
                    color: mode === 'connection' ? '#fff' : '#185FA5',
                    border: `1px solid ${mode === 'connection' ? '#0B5D73' : '#185FA5'}`,
                  }}>
                    {mode === 'connection' ? 'Switch to Pipeline Mode' : 'Switch to Connection Mode'}
                  </button>
                </div>
              </div>

              {/* Connection mode selector */}
              {mode === 'connection' && (
                <div>
                  <select style={inp} value={selectedConnId} onChange={e => setSelectedConnId(e.target.value)}>
                    {allConnectors.map(c => (
                      <option key={c.id} value={c.id}>{c.name} — {c.database_name} ({c.connector_type})</option>
                    ))}
                  </select>
                  <div style={{ fontSize: 10, color: '#0B5D73', marginTop: 5 }}>
                    ✓ AI will query this database directly — no pipeline needed. Works on any existing DB.
                  </div>
                </div>
              )}

              {/* Pipeline mode selector */}
              {mode === 'pipeline' && (
                <div>
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
              )}
            </div>

            {/* ── Question input ── */}
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
                <div style={{ position: 'relative' }}>
                  <textarea
                    style={{ ...ta, minHeight: 70, paddingRight: supported ? 48 : 12 }}
                    value={question}
                    placeholder="e.g. Total transactions by channel / Top 5 customers by balance / Revenue by branch"
                    onChange={e => setQuestion(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && e.metaKey) generateSql() }}
                  />
                  {supported && (
                    <button onClick={handleMicClick}
                      title={listening ? 'Stop listening' : 'Speak your question'}
                      style={{
                        position: 'absolute', right: 8, top: 8,
                        width: 32, height: 32, borderRadius: '50%',
                        border: (listening || recording) ? '2px solid #dc2626' : '2px solid #185FA5',
                        background: (listening || recording) ? '#fef2f2' : '#EBF4FF',
                        cursor: 'pointer', fontSize: 16,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        animation: (listening || recording) ? 'pulse-mic 1.2s infinite' : 'none',
                        transition: 'all 0.2s',
                      }}>
                      {(listening || recording) ? '⏹' : '🎤'}
                    </button>
                  )}
                </div>
                {voiceStatus && (
                  <div style={{ fontSize: 11, color: '#185FA5', marginTop: 6, fontStyle: 'italic' }}>
                    {voiceStatus}
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
                  <button style={btnPrimary} onClick={() => generateSql()}
                    disabled={loading || (mode==='pipeline' && (!selectedPipeline || !warehouseInfo)) || (mode==='connection' && !selectedConnId)}>
                    {loading ? '⏳ Generating...' : '🚀 Generate SQL'}
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
            )}

            {/* ── Query chain ── */}
            {hasQuery && (
              <>
                <div style={card}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                    <div style={sectionTitle}>Query chain ({queryChain.length} step{queryChain.length !== 1 ? 's' : ''})</div>
                    <button style={btnGhostSmall} onClick={reset}>✕ Start over</button>
                  </div>
                  {queryChain.map((step, idx) => (
                    <div key={idx} style={{ display: 'flex', gap: 10, alignItems: 'flex-start',
                      padding: '8px 0', borderBottom: idx < queryChain.length-1 ? '1px solid #f3f4f6' : 'none' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                        <div style={{ width: 22, height: 22, borderRadius: '50%', display: 'flex',
                          alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700,
                          background: idx === activeStep ? '#185FA5' : '#e5e7eb',
                          color: idx === activeStep ? '#fff' : '#888' }}>{idx + 1}</div>
                        {idx < queryChain.length-1 && <div style={{ width: 2, height: 20, background: '#e5e7eb', marginTop: 2 }} />}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: idx===0?600:400,
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
                    <div style={{ position: 'relative', flex: 1 }}>
                    <input ref={refinementRef} style={{ ...inp, paddingRight: supported ? 44 : 12 }} value={refinement}
                      placeholder="e.g. only last 30 days / top 10 / sort by amount descending"
                      onChange={e => setRefinement(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') applyRefinement() }} />
                    {supported && (
                      <button onClick={handleMicClick}
                        title={listening ? 'Stop' : 'Speak refinement'}
                        style={{
                          position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)',
                          width: 28, height: 28, borderRadius: '50%',
                          border: (listening || recording) ? '2px solid #dc2626' : '2px solid #185FA5',
                          background: (listening || recording) ? '#fef2f2' : '#EBF4FF',
                          cursor: 'pointer', fontSize: 13,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          animation: (listening || recording) ? 'pulse-mic 1.2s infinite' : 'none',
                        }}>
                        {(listening || recording) ? '⏹' : '🎤'}
                      </button>
                    )}
                  </div>
                    <button style={btnPrimary} onClick={() => applyRefinement()}
                      disabled={refining || !refinement.trim()}>
                      {refining ? '⏳' : '+ Apply'}
                    </button>
                  </div>
                  {voiceStatus && (
                    <div style={{ fontSize: 11, color: '#185FA5', marginTop: 6, fontStyle: 'italic' }}>
                      {voiceStatus}
                    </div>
                  )}
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

            {/* ── Results ── */}
            {results && (
              <div style={card}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#3B6D11' }}>
                    ✓ {results.rows.length} rows
                    {executing && <span style={{ color: '#888', fontWeight: 400 }}> (refreshing…)</span>}
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    {supported && voiceOn && (
                      <button title="Read results aloud"
                        onClick={() => {
                          const top = results.rows.slice(0,3).map(row => results.columns.map((c,i) => `${c}: ${row[i]}`).join(', ')).join('; ')
                          speak(`${results.rows.length} results. Top entries: ${top}`)
                        }}
                        style={{ fontSize: 16, background: 'none', border: 'none', cursor: 'pointer', padding: '0 4px' }}>🔊</button>
                    )}
                    <DownloadBar reportName={question} sql={currentSql} question={question} />
                    <div style={{ display: 'flex', gap: 4 }}>
                      {['bar','line','pie','table'].map(t => (
                        <button key={t} onClick={() => setChartType(t)}
                          style={{ padding: '4px 8px', fontSize: 10, borderRadius: 6, cursor: 'pointer',
                            background: chartType===t ? '#185FA5' : '#fff',
                            color: chartType===t ? '#fff' : '#555',
                            border: `1px solid ${chartType===t ? '#185FA5' : '#d1d5db'}` }}>
                          {t==='bar'?'▥':t==='line'?'📈':t==='pie'?'🥧':'⊞'}
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
                    <tbody>{results.rows.slice(0,100).map((row,i) => (
                      <tr key={i} style={{ background: i%2===0?'#fff':'#f9fafb' }}>
                        {row.map((cell,j) => (
                          <td key={j} style={{ padding: '5px 10px', borderBottom: '1px solid #f3f4f6',
                            color: '#333', fontFamily: typeof cell==='number'?'monospace':'inherit' }}>
                            {cell===null?<span style={{color:'#aaa'}}>null</span>:String(cell)}
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

          {/* ── Saved Reports ── */}
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
                  {rerunError[r.id] && <div style={{ fontSize: 10, color: '#991b1b', marginBottom: 6 }}>✗ {rerunError[r.id]}</div>}
                  {rerunResults[r.id] && (
                    <div style={{ marginTop: 6, border: '1px solid #EAF3DE', borderRadius: 6, padding: '8px 10px', background: '#f9fafb' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                        <div style={{ fontSize: 10, fontWeight: 600, color: '#3B6D11' }}>✓ {rerunResults[r.id].rows.length} rows</div>
                        <DownloadBar reportName={r.name} sql={r.sql} question={r.question} small />
                      </div>
                      {renderChart(rerunResults[r.id], rerunResults[r.id].columns[0], rerunResults[r.id].columns[1], r.chart_type || 'bar')}
                      <div style={{ overflowX: 'auto', marginTop: 8 }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                          <thead><tr>{rerunResults[r.id].columns.map(c => (
                            <th key={c} style={{ background: '#f3f4f6', padding: '4px 8px', textAlign: 'left',
                              borderBottom: '1px solid #e5e7eb', fontSize: 9, color: '#555', textTransform: 'uppercase' }}>{c}</th>
                          ))}</tr></thead>
                          <tbody>{rerunResults[r.id].rows.slice(0,20).map((row,i) => (
                            <tr key={i} style={{ background: i%2===0?'#fff':'#f9fafb' }}>
                              {row.map((cell,j) => (
                                <td key={j} style={{ padding: '3px 8px', borderBottom: '1px solid #f3f4f6', color: '#333' }}>
                                  {cell===null?<span style={{color:'#aaa'}}>null</span>:String(cell)}
                                </td>
                              ))}
                            </tr>
                          ))}</tbody>
                        </table>
                        {rerunResults[r.id].rows.length > 20 && <div style={{ fontSize: 9, color: '#888', padding: '4px 8px' }}>Showing 20 of {rerunResults[r.id].rows.length} rows</div>}
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
              <div style={{ fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Frequency</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6, marginBottom: 16 }}>
                {FREQUENCY_OPTIONS.map(opt => (
                  <label key={opt.value} style={{ display: 'flex', alignItems: 'flex-start', gap: 8,
                    padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                    border: `1.5px solid ${schedConfig.frequency===opt.value?'#185FA5':'#e5e7eb'}`,
                    background: schedConfig.frequency===opt.value?'#EBF4FF':'#fff' }}>
                    <input type="radio" name="sched_freq" value={opt.value}
                      checked={schedConfig.frequency===opt.value}
                      onChange={() => setSchedC('frequency', opt.value)} style={{ marginTop: 2 }} />
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 600, color: schedConfig.frequency===opt.value?'#185FA5':'#374151' }}>{opt.label}</div>
                      <div style={{ fontSize: 9, color: '#888', marginTop: 1 }}>{opt.desc}</div>
                    </div>
                  </label>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
                <div>
                  <div style={{ fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Run Time</div>
                  <input type="time" value={schedConfig.time} onChange={e => setSchedC('time', e.target.value)}
                    style={{ padding: '6px 10px', fontSize: 13, fontWeight: 600, border: '1px solid #d1d5db', borderRadius: 6, color: '#185FA5' }} />
                </div>
                {schedConfig.frequency === 'weekly' && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Day of Week</div>
                    <select value={schedConfig.day_of_week} onChange={e => setSchedC('day_of_week', e.target.value)} style={selStyle}>
                      {DAYS_OF_WEEK.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
                    </select>
                  </div>
                )}
                {['monthly','quarterly','halfyearly','yearly'].includes(schedConfig.frequency) && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Day of Month</div>
                    <select value={schedConfig.day_of_month} onChange={e => setSchedC('day_of_month', e.target.value)} style={selStyle}>
                      {Array.from({ length: 28 }, (_,i) => i+1).map(d => <option key={d} value={String(d)}>{d}</option>)}
                    </select>
                  </div>
                )}
                {schedConfig.frequency === 'yearly' && (
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Month</div>
                    <select value={schedConfig.month} onChange={e => setSchedC('month', e.target.value)} style={selStyle}>
                      {MONTHS_OF_YEAR.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                  </div>
                )}
              </div>
              <div style={{ background: '#EBF4FF', borderRadius: 6, padding: '8px 12px', marginBottom: 14, fontSize: 11, color: '#185FA5', fontWeight: 600 }}>
                ⏱ {buildSchedulePreview(schedConfig)}
              </div>
              <div style={{ fontSize: 10, color: '#888', marginBottom: 14, padding: '8px 10px', background: '#f9fafb', borderRadius: 6 }}>
                💡 On each scheduled run: SQL executes against the warehouse, result is logged. $0 AI cost per run.
              </div>
              {scheduleMsg && <div style={{ fontSize: 11, marginBottom: 10, color: scheduleMsg.startsWith('✓')?'#3B6D11':'#991b1b' }}>{scheduleMsg}</div>}
              <div style={{ display: 'flex', gap: 8 }}>
                <button style={btnPrimary} onClick={scheduleReport} disabled={scheduling}>
                  {scheduling ? '⏳ Scheduling...' : '⏰ Save Schedule'}
                </button>
                <button style={btnGhost} onClick={() => { setScheduleModal(null); setScheduleMsg(''); setSchedConfig({ ...DEFAULT_SCHED_CONFIG }) }}>
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

const inp          = { width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box' }
const ta           = { width: '100%', padding: '8px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, fontFamily: 'system-ui', resize: 'vertical', boxSizing: 'border-box' }
const card         = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }
const errBox       = { background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#991b1b', marginBottom: 10 }
const sectionTitle = { fontSize: 10, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }
const btnPrimary   = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhost     = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnGhostSmall= { padding: '4px 10px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 10, cursor: 'pointer' }
const selStyle     = { padding: '6px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, background: '#fff', cursor: 'pointer', minWidth: 130 }





















