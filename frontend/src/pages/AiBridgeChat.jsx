import { useState, useRef, useEffect } from "react"
import axios from "axios"

const API = axios.create({ baseURL: "http://localhost:8888" })
API.interceptors.request.use(c => {
  const t = localStorage.getItem("aibridge_token")
  if (t) c.headers.Authorization = `Bearer ${t}`
  return c
})

// ── Demo scenarios (kept from original) ──────────────────────────────────
const SCENARIOS = [
  {
    label: "Failed job", icon: "🔴",
    messages: [
      { role: "user", text: "Yesterday's job failed" },
      { role: "agent", intent: "recovery", steps: [
          { agent: "OrchestratorAgent", action: "Intent detected: recovery request", status: "done" },
          { agent: "AnalyticsAgent",    action: "Found: 'school_pipeline' failed at 16:46 yesterday", status: "done" },
          { agent: "RecoveryAgent",     action: "Diagnosed: extract failed — source schema was 'raw' not 'school'", status: "done" },
        ],
        text: "Found it. **school_pipeline** failed yesterday at 16:46.\n\n**Root cause:** Extract phase tried to read from `raw.students` but your data lives in `school.students` — connector source schema was misconfigured.\n\nShall I fix the connector and re-run the pipeline?"
      },
      { role: "user", text: "Yes fix and re-run" },
      { role: "agent", intent: "execution", steps: [
          { agent: "GovernanceValidationAgent", action: "Re-run is safe — no duplicate risk", status: "done" },
          { agent: "ETLAgent",                  action: "Extracting: courses, students, teachers, enrollments", status: "done" },
          { agent: "ExecutionAgent",            action: "Running 5 warehouse scripts", status: "done" },
        ],
        text: "✓ Fixed and re-run complete.\n\n**Extract:** 40 rows across 4 tables\n**Warehouse:**\n• dim_student — 8 rows\n• dim_course — 7 rows\n• dim_teacher — 5 rows\n• dim_date — 4,018 rows\n• fact_enrollments — 20 rows\n\nAll good. Pipeline is healthy."
      }
    ]
  },
  {
    label: "Build new warehouse", icon: "🏗️",
    messages: [
      { role: "user", text: "Build a sales data warehouse from our CRM database" },
      { role: "agent", intent: "new_pipeline", steps: [
          { agent: "OrchestratorAgent",          action: "Intent: new pipeline. Plan: star schema", status: "done" },
          { agent: "SchemaAgent",                action: "Discovered 12 tables, 94 columns, 8 FK relationships", status: "done" },
          { agent: "MetadataAgent",              action: "Profiled data quality: 2 PII columns detected", status: "done" },
          { agent: "BusinessAgent",              action: "Requirements: sales KPIs, customer segments, regional performance", status: "done" },
          { agent: "PlannerAgent",               action: "Plan: Star Schema with 3 fact tables, 6 dimensions", status: "done" },
          { agent: "RelationshipValidationAgent",action: "All FKs valid. No circular joins. No orphaned tables.", status: "done" },
        ],
        text: "Analyzed your CRM. Here's what I'm proposing:\n\n**3 Fact Tables:**\n• fact_orders (grain: one row per order)\n• fact_order_items (grain: one row per line item)\n• fact_customer_activity (grain: one row per event)\n\n**6 Dimensions:**\n• dim_customer, dim_product, dim_region, dim_salesperson, dim_channel, dim_date\n\n⚠️ Found 2 PII columns: `customer_email`, `phone_number` — I'll mask these in staging.\n\nApprove this model to continue?"
      },
      { role: "user", text: "Looks good, approve" },
      { role: "agent", intent: "sql_generation", steps: [
          { agent: "DataModelAgent",        action: "Star schema designed with surrogate keys + SCD types", status: "done" },
          { agent: "SQLAgent",              action: "Generated 9 SQL scripts", status: "done" },
          { agent: "SQLValidationAgent",    action: "Fixed 2 issues: missing stg_ prefix, alias mismatch", status: "done" },
          { agent: "GovernanceValidationAgent", action: "PII masked. No dangerous SQL. All clear.", status: "done" },
        ],
        text: "Generated and validated 9 SQL scripts.\n\n**Auto-fixed:** 2 issues caught by SQLValidationAgent before they reached you.\n\nReview the SQL in Gate 2, then I'll execute. Ready?"
      }
    ]
  },
  {
    label: "Ask your data", icon: "📊",
    messages: [
      { role: "user", text: "Which course has the most enrollments this term?" },
      { role: "agent", intent: "bi_query", steps: [
          { agent: "OrchestratorAgent", action: "Intent: BI query — no pipeline needed", status: "done" },
          { agent: "AnalyticsAgent",    action: "Generated SQL against warehouse.fact_enrollments", status: "done" },
        ],
        text: "Here's the answer:\n\n```sql\nSELECT dc.name, COUNT(*) as enrollments\nFROM warehouse.fact_enrollments fe\nJOIN warehouse.dim_course dc ON dc.course_key = fe.course_key\nGROUP BY dc.name ORDER BY enrollments DESC LIMIT 5\n```\n\n**Results:**\n1. Advanced Mathematics — 18 students\n2. Physics 101 — 15 students\n3. English Literature — 12 students"
      }
    ]
  },
]

const INTENT_COLORS = {
  recovery:         { bg: "#FEF2F2", border: "#EF4444", label: "🔴 Recovery",        text: "#991B1B" },
  new_pipeline:     { bg: "#EFF6FF", border: "#3B82F6", label: "🏗️ New Pipeline",    text: "#1E40AF" },
  sql_generation:   { bg: "#F5F3FF", border: "#8B5CF6", label: "⚙️ SQL Generation",  text: "#5B21B6" },
  bi_query:         { bg: "#ECFDF5", border: "#10B981", label: "📊 BI Query",         text: "#065F46" },
  execution:        { bg: "#ECFDF5", border: "#10B981", label: "▶ Execution",          text: "#065F46" },
  live:             { bg: "#F0FDF4", border: "#22C55E", label: "⚡ Live Query",        text: "#166534" },
}

const LIVE_SUGGESTIONS = [
  "What tables are in my warehouse?",
  "How many rows in each dimension table?",
  "Top 5 values in dim_car by brand",
  "Average price by transmission type",
  "How many distinct cities in dim_location?",
  "Show pipeline health summary",
]

// ── Agent step component ──────────────────────────────────────────────────
function AgentStep({ step, index, visible }) {
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 8,
      opacity: visible ? 1 : 0,
      transform: visible ? "translateY(0)" : "translateY(4px)",
      transition: `all 0.3s ease ${index * 0.15}s`,
      marginBottom: 4
    }}>
      <div style={{
        width: 18, height: 18, borderRadius: "50%", flexShrink: 0, marginTop: 1,
        background: step.status === "done" ? "#10B981" : "#E5E7EB",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 10, color: "#fff"
      }}>✓</div>
      <div>
        <span style={{ fontSize: 10, fontWeight: 600, color: "#6B7280", fontFamily: "monospace" }}>{step.agent}</span>
        <span style={{ fontSize: 10, color: "#9CA3AF" }}> → </span>
        <span style={{ fontSize: 10, color: "#374151" }}>{step.action}</span>
      </div>
    </div>
  )
}

// ── SQL result table ──────────────────────────────────────────────────────
function SqlResult({ result }) {
  if (!result || result.error) return null
  const { sql, columns, rows } = result
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 10, color: "#6B7280", marginBottom: 4 }}>
        🔒 SQL executed (aggregated — no raw data exposed to AI):
      </div>
      <div style={{
        background: "#1e1e2e", borderRadius: 6, padding: "8px 12px",
        fontSize: 10, color: "#a6e3a1", fontFamily: "monospace",
        marginBottom: 8, overflowX: "auto"
      }}>{sql}</div>
      {columns && rows && rows.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead>
              <tr>{columns.map((c, i) => (
                <th key={i} style={{ padding: "4px 8px", background: "#F3F4F6", border: "1px solid #E5E7EB", textAlign: "left", fontWeight: 600 }}>{c}</th>
              ))}</tr>
            </thead>
            <tbody>
              {rows.slice(0, 10).map((row, i) => (
                <tr key={i}>{row.map((v, j) => (
                  <td key={j} style={{ padding: "3px 8px", border: "1px solid #E5E7EB", color: "#374151" }}>{v}</td>
                ))}</tr>
              ))}
            </tbody>
          </table>
          {rows.length > 10 && <div style={{ fontSize: 10, color: "#9CA3AF", marginTop: 4 }}>Showing 10 of {rows.length} rows</div>}
        </div>
      )}
    </div>
  )
}

// ── Message bubble ────────────────────────────────────────────────────────
function MessageBubble({ msg, isNew }) {
  const [stepsVisible, setStepsVisible] = useState(false)
  const intentColor = msg.intent ? INTENT_COLORS[msg.intent] : null

  useEffect(() => {
    if ((msg.role === "agent" || msg.role === "assistant") && isNew) {
      setTimeout(() => setStepsVisible(true), 300)
    } else { setStepsVisible(true) }
  }, [])

  const formatText = (text) => {
    if (!text) return null
    return text.split('\n').map((line, i) => {
      const parts = line.split(/\*\*(.+?)\*\*/g)
      if (line.startsWith('• ') || line.match(/^\d\./)) {
        return <div key={i} style={{ paddingLeft: 12, color: "#374151", marginBottom: 2 }}>
          {parts.map((p, j) => j % 2 === 1 ? <strong key={j}>{p}</strong> : p)}
        </div>
      }
      if (line.includes('`') && !line.startsWith('```')) {
        const cparts = line.split('`')
        return <div key={i} style={{ marginBottom: 2 }}>{cparts.map((p, j) => j % 2 === 1
          ? <code key={j} style={{ background: "#F3F4F6", padding: "1px 4px", borderRadius: 3, fontFamily: "monospace", fontSize: 11 }}>{p}</code>
          : p)}</div>
      }
      if (line.startsWith('```') || line === '```') return null
      return line ? <div key={i} style={{ marginBottom: 2 }}>
        {parts.map((p, j) => j % 2 === 1 ? <strong key={j}>{p}</strong> : p)}
      </div> : <div key={i} style={{ height: 6 }} />
    })
  }

  const isUser = msg.role === "user"
  if (isUser) {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <div style={{
          background: "#185FA5", color: "#fff",
          borderRadius: "18px 18px 4px 18px",
          padding: "10px 16px", maxWidth: "70%", fontSize: 13, lineHeight: 1.5
        }}>{msg.text || msg.content}</div>
      </div>
    )
  }

  const text = msg.text || msg.content
  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "flex-start" }}>
      <div style={{
        width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
        background: "linear-gradient(135deg, #185FA5, #534AB7)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 14, color: "#fff", fontWeight: 700
      }}>A</div>
      <div style={{ flex: 1, maxWidth: "85%" }}>
        {intentColor && (
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            background: intentColor.bg, border: `1px solid ${intentColor.border}`,
            borderRadius: 20, padding: "2px 10px", fontSize: 10,
            color: intentColor.text, fontWeight: 600, marginBottom: 6
          }}>{intentColor.label}</div>
        )}
        {msg.steps && msg.steps.length > 0 && (
          <div style={{ background: "#F9FAFB", border: "1px solid #E5E7EB", borderRadius: 8, padding: "8px 12px", marginBottom: 8 }}>
            {msg.steps.map((step, i) => <AgentStep key={i} step={step} index={i} visible={stepsVisible} />)}
          </div>
        )}
        <div style={{
          background: "#fff", border: "1px solid #E5E7EB",
          borderRadius: "4px 18px 18px 18px",
          padding: "10px 16px", fontSize: 13, lineHeight: 1.6, color: "#111"
        }}>
          {formatText(text)}
          {msg.sql_result && <SqlResult result={msg.sql_result} />}
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────
export default function AiBridgeChat() {
  const [mode, setMode] = useState("live")  // "live" | "demo"
  const [messages, setMessages] = useState([])
  const [input, setInput]       = useState("")
  const [loading, setLoading]   = useState(false)
  const [pipelines, setPipelines] = useState([])
  const [pipelineId, setPipelineId] = useState("")
  // demo mode state
  const [activeScenario, setActiveScenario] = useState(null)
  const [demoMessages, setDemoMessages]     = useState([])
  const [msgIndex, setMsgIndex]             = useState(0)
  const [typing, setTyping]                 = useState(false)
  const [newMsgIndex, setNewMsgIndex]       = useState(-1)

  const bottomRef = useRef(null)
  const inputRef  = useRef(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages, demoMessages, loading, typing])

  useEffect(() => {
    API.get("/pipeline/list").then(r => {
      const list = Array.isArray(r.data) ? r.data : r.data.pipelines || []
      setPipelines(list.slice(0, 20))
    }).catch(() => {})
  }, [])

  // ── Live mode: send message ──
  const sendMessage = async (text) => {
    const msg = (text || input).trim()
    if (!msg || loading) return
    setInput("")
    const history = messages.map(m => ({ role: m.role === "assistant" ? "assistant" : "user", content: m.text || m.content }))
    setMessages(prev => [...prev, { role: "user", content: msg }])
    setLoading(true)
    try {
      const r = await API.post("/chat", { message: msg, history, pipeline_id: pipelineId })
      setMessages(prev => [...prev, { role: "assistant", content: r.data.response, sql_result: r.data.sql_result, intent: r.data.sql_result ? "live" : null }])
    } catch (e) {
      setMessages(prev => [...prev, { role: "assistant", content: `❌ ${e.response?.data?.detail || e.message}` }])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  // ── Demo mode: scenario playback ──
  const loadScenario = (scenario) => {
    setActiveScenario(scenario); setDemoMessages([]); setMsgIndex(0); setTyping(false); setNewMsgIndex(-1)
    setTimeout(() => playNext(scenario.messages, 0), 300)
  }
  const playNext = (msgs, idx) => {
    if (idx >= msgs.length) return
    const msg = msgs[idx]
    if (msg.role === "agent") {
      setTyping(true)
      setTimeout(() => { setTyping(false); setDemoMessages(prev => [...prev, msg]); setNewMsgIndex(idx); setMsgIndex(idx + 1) }, 1200)
    } else {
      setDemoMessages(prev => [...prev, msg]); setNewMsgIndex(idx); setMsgIndex(idx + 1)
      if (msgs[idx + 1]?.role === "agent") setTimeout(() => playNext(msgs, idx + 1), 800)
    }
  }
  const canContinue = activeScenario && msgIndex < activeScenario.messages.length && !typing

  return (
    <div style={{ fontFamily: "'Inter', system-ui, sans-serif", background: "#F8FAFC", height: "100vh", display: "flex", flexDirection: "column" }}>

      {/* Header */}
      <div style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", padding: "12px 20px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: "linear-gradient(135deg, #185FA5, #534AB7)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 14 }}>A</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#111" }}>AIBridge Chat</div>
            <div style={{ fontSize: 10, color: mode === "live" ? "#10B981" : "#F59E0B" }}>
              {mode === "live" ? "⚡ Live — connected to your warehouse" : "🎬 Demo — scenario walkthrough"}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {mode === "live" && (
            <select value={pipelineId} onChange={e => setPipelineId(e.target.value)}
              style={{ fontSize: 11, padding: "4px 8px", borderRadius: 6, border: "1px solid #E5E7EB", background: "#F9FAFB", color: "#374151" }}>
              <option value="">All pipelines</option>
              {pipelines.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
          <div style={{ display: "flex", background: "#F3F4F6", borderRadius: 8, padding: 2 }}>
            {["live", "demo"].map(m => (
              <button key={m} onClick={() => setMode(m)} style={{
                padding: "4px 12px", borderRadius: 6, fontSize: 11, border: "none", cursor: "pointer",
                background: mode === m ? "#fff" : "transparent",
                color: mode === m ? "#185FA5" : "#6B7280", fontWeight: mode === m ? 600 : 400,
                boxShadow: mode === m ? "0 1px 3px rgba(0,0,0,0.1)" : "none"
              }}>{m === "live" ? "⚡ Live" : "🎬 Demo"}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Demo scenario tabs */}
      {mode === "demo" && (
        <div style={{ background: "#fff", borderBottom: "1px solid #E5E7EB", padding: "10px 20px", display: "flex", gap: 8, flexWrap: "wrap" }}>
          <div style={{ fontSize: 11, color: "#9CA3AF", alignSelf: "center", marginRight: 4 }}>Try a scenario:</div>
          {SCENARIOS.map((s, i) => (
            <button key={i} onClick={() => loadScenario(s)} style={{
              padding: "5px 12px", borderRadius: 20, fontSize: 11, cursor: "pointer",
              border: `1px solid ${activeScenario?.label === s.label ? "#185FA5" : "#E5E7EB"}`,
              background: activeScenario?.label === s.label ? "#EFF6FF" : "#fff",
              color: activeScenario?.label === s.label ? "#185FA5" : "#555",
              fontWeight: activeScenario?.label === s.label ? 600 : 400
            }}>{s.icon} {s.label}</button>
          ))}
        </div>
      )}

      {/* Chat area */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px" }}>

        {/* Live mode empty state */}
        {mode === "live" && messages.length === 0 && !loading && (
          <div style={{ textAlign: "center", padding: "40px 20px" }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>⚡</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: "#374151", marginBottom: 6 }}>Ask your warehouse anything</div>
            <div style={{ fontSize: 12, color: "#6B7280", marginBottom: 24, maxWidth: 400, margin: "0 auto 24px" }}>
              🔒 Privacy-safe: AI sees schema only, never raw data. All queries are aggregated.
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, maxWidth: 560, margin: "0 auto", textAlign: "left" }}>
              {LIVE_SUGGESTIONS.slice(0, 6).map((s, i) => (
                <button key={i} onClick={() => sendMessage(s)} style={{
                  background: "#fff", border: "1px solid #E5E7EB", borderRadius: 8,
                  padding: "8px 12px", cursor: "pointer", fontSize: 12, color: "#374151", textAlign: "left"
                }}>{s}</button>
              ))}
            </div>
          </div>
        )}

        {/* Demo mode empty state */}
        {mode === "demo" && demoMessages.length === 0 && !typing && (
          <div style={{ textAlign: "center", padding: "60px 20px", color: "#9CA3AF" }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🤖</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: "#374151", marginBottom: 6 }}>AIBridge Multi-Agent System</div>
            <div style={{ fontSize: 13, lineHeight: 1.6, maxWidth: 400, margin: "0 auto" }}>
              Pick a scenario above to see how agents work together.
            </div>
          </div>
        )}

        {/* Live messages */}
        {mode === "live" && messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} isNew={i === messages.length - 1} />
        ))}

        {/* Demo messages */}
        {mode === "demo" && demoMessages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} isNew={i === newMsgIndex} />
        ))}

        {/* Loading indicators */}
        {mode === "live" && loading && (
          <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "flex-start" }}>
            <div style={{ width: 32, height: 32, borderRadius: "50%", background: "linear-gradient(135deg, #185FA5, #534AB7)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, color: "#fff", fontWeight: 700 }}>A</div>
            <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: "4px 18px 18px 18px", padding: "12px 16px", display: "flex", gap: 4, alignItems: "center" }}>
              {[0,1,2].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: "#9CA3AF", animation: "bounce 1.2s infinite", animationDelay: `${i * 0.2}s` }} />)}
            </div>
          </div>
        )}
        {mode === "demo" && typing && (
          <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "flex-start" }}>
            <div style={{ width: 32, height: 32, borderRadius: "50%", background: "linear-gradient(135deg, #185FA5, #534AB7)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, color: "#fff", fontWeight: 700 }}>A</div>
            <div style={{ background: "#fff", border: "1px solid #E5E7EB", borderRadius: "4px 18px 18px 18px", padding: "12px 16px", display: "flex", gap: 4, alignItems: "center" }}>
              {[0,1,2].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: "#9CA3AF", animation: "bounce 1.2s infinite", animationDelay: `${i * 0.2}s` }} />)}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div style={{ background: "#fff", borderTop: "1px solid #E5E7EB", padding: "12px 20px" }}>
        {/* Demo continue button */}
        {mode === "demo" && canContinue && (
          <div style={{ marginBottom: 10 }}>
            <button onClick={() => playNext(activeScenario.messages, msgIndex)} style={{
              width: "100%", padding: 10, borderRadius: 8, border: "1px dashed #185FA5",
              background: "#EFF6FF", color: "#185FA5", fontSize: 12, cursor: "pointer", fontWeight: 500
            }}>▶ Continue scenario — see next message</button>
          </div>
        )}

        {/* Live quick suggestions */}
        {mode === "live" && messages.length > 0 && (
          <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
            {LIVE_SUGGESTIONS.slice(0, 3).map((s, i) => (
              <button key={i} onClick={() => sendMessage(s)} style={{
                fontSize: 11, padding: "3px 10px", borderRadius: 12,
                border: "1px solid #E5E7EB", background: "#F9FAFB", color: "#6B7280", cursor: "pointer"
              }}>{s}</button>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 8 }}>
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (mode === "live") sendMessage() } }}
            placeholder={mode === "live" ? "Ask about your warehouse data, pipeline health, or analytics..." : "Type anything — scenarios above show agent workflows"}
            disabled={loading || mode === "demo"}
            style={{ flex: 1, padding: "10px 16px", borderRadius: 24, border: "1px solid #E5E7EB", fontSize: 13, outline: "none", background: "#F9FAFB" }}
          />
          {mode === "live" ? (
            <button onClick={() => sendMessage()} disabled={loading || !input.trim()} style={{
              padding: "10px 18px", borderRadius: 24, border: "none",
              background: loading || !input.trim() ? "#E5E7EB" : "linear-gradient(135deg, #185FA5, #534AB7)",
              color: loading || !input.trim() ? "#9CA3AF" : "#fff",
              cursor: loading || !input.trim() ? "default" : "pointer", fontSize: 13, fontWeight: 600
            }}>{loading ? "..." : "Send"}</button>
          ) : (
            <button style={{ padding: "10px 18px", borderRadius: 24, border: "none", background: "#E5E7EB", color: "#9CA3AF", fontSize: 13 }} disabled>Demo</button>
          )}
        </div>
        <div style={{ fontSize: 10, color: "#9CA3AF", marginTop: 6, textAlign: "center" }}>
          {mode === "live" ? "🔒 Privacy-safe · AI generates SQL · No raw data exposure" : "🎬 Demo mode · Switch to Live to query your actual warehouse"}
        </div>
      </div>

      <style>{`@keyframes bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-4px)} }`}</style>
    </div>
  )
}
