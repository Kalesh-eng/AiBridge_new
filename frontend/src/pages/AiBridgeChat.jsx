import { useState, useRef, useEffect } from "react"

const SCENARIOS = [
  {
    label: "Failed job",
    icon: "🔴",
    messages: [
      { role: "user", text: "Yesterday's job failed" },
      { role: "agent", intent: "recovery", steps: [
          { agent: "OrchestratorAgent", action: "Intent detected: recovery request", status: "done" },
          { agent: "AnalyticsAgent", action: "Found: 'school_pipeline' failed at 16:46 yesterday", status: "done" },
          { agent: "RecoveryAgent", action: "Diagnosed: extract failed — source schema was 'raw' not 'school'", status: "done" },
        ],
        text: "Found it. **school_pipeline** failed yesterday at 16:46.\n\n**Root cause:** Extract phase tried to read from `raw.students` but your data lives in `school.students` — connector source schema was misconfigured.\n\nShall I fix the connector and re-run the pipeline?"
      },
      { role: "user", text: "Yes fix and re-run" },
      { role: "agent", intent: "execution", steps: [
          { agent: "GovernanceValidationAgent", action: "Re-run is safe — no duplicate risk", status: "done" },
          { agent: "ETLAgent", action: "Extracting: courses, students, teachers, enrollments", status: "done" },
          { agent: "ExecutionAgent", action: "Running 5 warehouse scripts", status: "done" },
        ],
        text: "✓ Fixed and re-run complete.\n\n**Extract:** 40 rows across 4 tables\n**Warehouse:**\n• dim_student — 8 rows\n• dim_course — 7 rows\n• dim_teacher — 5 rows\n• dim_date — 4,018 rows\n• fact_enrollments — 20 rows\n\nAll good. Pipeline is healthy."
      }
    ]
  },
  {
    label: "Build new warehouse",
    icon: "🏗️",
    messages: [
      { role: "user", text: "Build a sales data warehouse from our CRM database" },
      { role: "agent", intent: "new_pipeline", steps: [
          { agent: "OrchestratorAgent", action: "Intent: new pipeline. Plan: star schema", status: "done" },
          { agent: "SchemaAgent", action: "Discovered 12 tables, 94 columns, 8 FK relationships", status: "done" },
          { agent: "MetadataAgent", action: "Profiled data quality: 2 PII columns detected", status: "done" },
          { agent: "BusinessAgent", action: "Requirements: sales KPIs, customer segments, regional performance", status: "done" },
          { agent: "PlannerAgent", action: "Plan: Star Schema with 3 fact tables, 6 dimensions", status: "done" },
          { agent: "RelationshipValidationAgent", action: "All FKs valid. No circular joins. No orphaned tables.", status: "done" },
        ],
        text: "Analyzed your CRM. Here's what I'm proposing:\n\n**3 Fact Tables:**\n• fact_orders (grain: one row per order)\n• fact_order_items (grain: one row per line item)\n• fact_customer_activity (grain: one row per event)\n\n**6 Dimensions:**\n• dim_customer, dim_product, dim_region, dim_salesperson, dim_channel, dim_date\n\n⚠️ Found 2 PII columns: `customer_email`, `phone_number` — I'll mask these in staging.\n\nApprove this model to continue?"
      },
      { role: "user", text: "Looks good, approve" },
      { role: "agent", intent: "sql_generation", steps: [
          { agent: "DataModelAgent", action: "Star schema designed with surrogate keys + SCD types", status: "done" },
          { agent: "SQLAgent", action: "Generated 9 SQL scripts", status: "done" },
          { agent: "SQLValidationAgent", action: "Fixed 2 issues: missing stg_ prefix, alias mismatch", status: "done" },
          { agent: "GovernanceValidationAgent", action: "PII masked. No dangerous SQL. All clear.", status: "done" },
        ],
        text: "Generated and validated 9 SQL scripts.\n\n**Auto-fixed:** 2 issues caught by SQLValidationAgent before they reached you.\n\nReview the SQL in Gate 2, then I'll execute. Ready?"
      }
    ]
  },
  {
    label: "Ask a business question",
    icon: "📊",
    messages: [
      { role: "user", text: "Which course has the most enrollments this term?" },
      { role: "agent", intent: "bi_query", steps: [
          { agent: "OrchestratorAgent", action: "Intent: BI query — no pipeline needed", status: "done" },
          { agent: "AnalyticsAgent", action: "Generated SQL against warehouse.fact_enrollments", status: "done" },
        ],
        text: "Here's the answer:\n\n```sql\nSELECT dc.name, COUNT(*) as enrollments\nFROM warehouse.fact_enrollments fe\nJOIN warehouse.dim_course dc ON dc.course_key = fe.course_key\nWHERE fe.term = 'Spring 2026'\nGROUP BY dc.name\nORDER BY enrollments DESC\nLIMIT 10\n```\n\n**Results:**\n1. Advanced Mathematics — 18 students\n2. Physics 101 — 15 students\n3. English Literature — 12 students\n\nShall I save this as a report?"
      }
    ]
  },
  {
    label: "Refresh specific table",
    icon: "🔄",
    messages: [
      { role: "user", text: "Refresh only the students table in school pipeline" },
      { role: "agent", intent: "selective_refresh", steps: [
          { agent: "OrchestratorAgent", action: "Intent: selective refresh — 1 table only", status: "done" },
          { agent: "GovernanceValidationAgent", action: "Safe to refresh — no downstream impact", status: "done" },
          { agent: "ETLAgent", action: "Extracting students only (skipping courses, teachers, enrollments)", status: "done" },
          { agent: "ExecutionAgent", action: "Refreshing warehouse.dim_student", status: "done" },
        ],
        text: "Done. Refreshed `staging.stg_students` ← `school.students` — **8 rows** loaded.\n\n`warehouse.dim_student` updated — 8 rows.\n\nOther tables (courses, teachers, enrollments) were not touched."
      }
    ]
  },
  {
    label: "Change pipeline logic",
    icon: "✏️",
    messages: [
      { role: "user", text: "Update school pipeline — only include students enrolled after 2022" },
      { role: "agent", intent: "modify", steps: [
          { agent: "OrchestratorAgent", action: "Intent: modify existing pipeline logic", status: "done" },
          { agent: "SQLAgent", action: "Adding WHERE clause: enrollment_year > 2022", status: "done" },
          { agent: "SQLValidationAgent", action: "SQL valid. WHERE clause correct.", status: "done" },
          { agent: "GovernanceValidationAgent", action: "Safe change. No PII impact.", status: "done" },
        ],
        text: "Updated the SQL for `dim_student` in school pipeline:\n\n```sql\n-- Added filter:\nWHERE s.enrollment_year > 2022\n```\n\nThis change is ready for your review in Gate 2. Approve to save and re-run with the new filter?"
      }
    ]
  },
  {
    label: "Schedule a pipeline",
    icon: "⏰",
    messages: [
      { role: "user", text: "Run school pipeline every morning at 6am" },
      { role: "agent", intent: "schedule", steps: [
          { agent: "OrchestratorAgent", action: "Intent: schedule pipeline", status: "done" },
          { agent: "SchedulerAgent", action: "Set cron: 0 6 * * * for school_pipeline", status: "done" },
        ],
        text: "Scheduled. **school_pipeline** will now run every day at **6:00 AM**.\n\nNext run: tomorrow at 06:00.\n\nYou'll see results in Pipeline Logs after each run. Want to change the time or add a failure alert?"
      }
    ]
  }
]

const INTENT_COLORS = {
  recovery: { bg: "#FEF2F2", border: "#EF4444", label: "🔴 Recovery", text: "#991B1B" },
  new_pipeline: { bg: "#EFF6FF", border: "#3B82F6", label: "🏗️ New Pipeline", text: "#1E40AF" },
  sql_generation: { bg: "#F5F3FF", border: "#8B5CF6", label: "⚙️ SQL Generation", text: "#5B21B6" },
  bi_query: { bg: "#ECFDF5", border: "#10B981", label: "📊 BI Query", text: "#065F46" },
  selective_refresh: { bg: "#FFF7ED", border: "#F59E0B", label: "🔄 Selective Refresh", text: "#92400E" },
  modify: { bg: "#FDF4FF", border: "#A855F7", label: "✏️ Modify Pipeline", text: "#6B21A8" },
  schedule: { bg: "#F0FDF4", border: "#22C55E", label: "⏰ Schedule", text: "#166534" },
  execution: { bg: "#ECFDF5", border: "#10B981", label: "▶ Execution", text: "#065F46" },
}

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
        <span style={{ fontSize: 10, fontWeight: 600, color: "#6B7280", fontFamily: "monospace" }}>
          {step.agent}
        </span>
        <span style={{ fontSize: 10, color: "#9CA3AF" }}> → </span>
        <span style={{ fontSize: 10, color: "#374151" }}>{step.action}</span>
      </div>
    </div>
  )
}

function MessageBubble({ msg, isNew }) {
  const [stepsVisible, setStepsVisible] = useState(false)
  const intentColor = msg.intent ? INTENT_COLORS[msg.intent] : null

  useEffect(() => {
    if (msg.role === "agent" && isNew) {
      setTimeout(() => setStepsVisible(true), 300)
    } else {
      setStepsVisible(true)
    }
  }, [])

  const formatText = (text) => {
    return text.split('\n').map((line, i) => {
      if (line.startsWith('**') && line.endsWith('**')) {
        return <div key={i} style={{ fontWeight: 600, margin: "4px 0 2px" }}>{line.slice(2, -2)}</div>
      }
      if (line.startsWith('• ')) {
        return <div key={i} style={{ paddingLeft: 12, color: "#374151" }}>{line}</div>
      }
      if (line.startsWith('```')) return null
      if (line.match(/^\d\./)) {
        return <div key={i} style={{ paddingLeft: 12, color: "#374151" }}>{line}</div>
      }
      if (line.includes('`') && !line.startsWith('```')) {
        const parts = line.split('`')
        return <div key={i}>{parts.map((p, j) => j % 2 === 1
          ? <code key={j} style={{ background: "#F3F4F6", padding: "1px 4px", borderRadius: 3, fontFamily: "monospace", fontSize: 11 }}>{p}</code>
          : p)}</div>
      }
      if (line.startsWith('WHERE ') || line.startsWith('SELECT ') || line.startsWith('JOIN ') || line.startsWith('FROM ') || line.startsWith('ORDER ') || line.startsWith('GROUP ') || line.startsWith('LIMIT ') || line.startsWith('--')) {
        return <div key={i} style={{ fontFamily: "monospace", fontSize: 11, color: "#4ADE80", paddingLeft: 8 }}>{line}</div>
      }
      return line ? <div key={i} style={{ marginBottom: 2 }}>{line}</div> : <div key={i} style={{ height: 4 }} />
    })
  }

  if (msg.role === "user") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <div style={{
          background: "#185FA5", color: "#fff", borderRadius: "18px 18px 4px 18px",
          padding: "10px 16px", maxWidth: "70%", fontSize: 13, lineHeight: 1.5
        }}>
          {msg.text}
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "flex-start" }}>
      <div style={{
        width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
        background: "linear-gradient(135deg, #185FA5, #534AB7)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 14, color: "#fff", fontWeight: 700
      }}>A</div>
      <div style={{ flex: 1, maxWidth: "85%" }}>

        {/* Intent badge */}
        {intentColor && (
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            background: intentColor.bg, border: `1px solid ${intentColor.border}`,
            borderRadius: 20, padding: "2px 10px", fontSize: 10,
            color: intentColor.text, fontWeight: 600, marginBottom: 6
          }}>
            {intentColor.label}
          </div>
        )}

        {/* Agent steps */}
        {msg.steps && msg.steps.length > 0 && (
          <div style={{
            background: "#F9FAFB", border: "1px solid #E5E7EB",
            borderRadius: 8, padding: "8px 12px", marginBottom: 8
          }}>
            {msg.steps.map((step, i) => (
              <AgentStep key={i} step={step} index={i} visible={stepsVisible} />
            ))}
          </div>
        )}

        {/* Message text */}
        <div style={{
          background: "#fff", border: "1px solid #E5E7EB",
          borderRadius: "4px 18px 18px 18px",
          padding: "10px 16px", fontSize: 13, lineHeight: 1.6, color: "#111"
        }}>
          {formatText(msg.text)}
        </div>
      </div>
    </div>
  )
}

export default function AiBridgeChat() {
  const [activeScenario, setActiveScenario] = useState(null)
  const [messages, setMessages] = useState([])
  const [msgIndex, setMsgIndex] = useState(0)
  const [input, setInput] = useState("")
  const [typing, setTyping] = useState(false)
  const [newMsgIndex, setNewMsgIndex] = useState(-1)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, typing])

  const loadScenario = (scenario) => {
    setActiveScenario(scenario)
    setMessages([])
    setMsgIndex(0)
    setTyping(false)
    setNewMsgIndex(-1)
    setTimeout(() => playNext(scenario.messages, 0), 300)
  }

  const playNext = (msgs, idx) => {
    if (idx >= msgs.length) return
    const msg = msgs[idx]
    if (msg.role === "agent") {
      setTyping(true)
      setTimeout(() => {
        setTyping(false)
        setMessages(prev => [...prev, msg])
        setNewMsgIndex(idx)
        setMsgIndex(idx + 1)
      }, 1200)
    } else {
      setMessages(prev => [...prev, msg])
      setNewMsgIndex(idx)
      setMsgIndex(idx + 1)
      if (msgs[idx + 1]?.role === "agent") {
        setTimeout(() => playNext(msgs, idx + 1), 800)
      }
    }
  }

  const continueScenario = () => {
    if (!activeScenario || msgIndex >= activeScenario.messages.length) return
    playNext(activeScenario.messages, msgIndex)
  }

  const canContinue = activeScenario &&
    msgIndex < activeScenario.messages.length &&
    !typing

  return (
    <div style={{
      fontFamily: "'Inter', system-ui, sans-serif",
      background: "#F8FAFC", minHeight: "100vh",
      display: "flex", flexDirection: "column"
    }}>

      {/* Header */}
      <div style={{
        background: "#fff", borderBottom: "1px solid #E5E7EB",
        padding: "12px 20px", display: "flex", alignItems: "center",
        justifyContent: "space-between"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: "linear-gradient(135deg, #185FA5, #534AB7)",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#fff", fontWeight: 700, fontSize: 14
          }}>A</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#111" }}>AIBridge</div>
            <div style={{ fontSize: 10, color: "#10B981", display: "flex", alignItems: "center", gap: 3 }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#10B981" }} />
              12 agents active
            </div>
          </div>
        </div>
        <div style={{ fontSize: 11, color: "#9CA3AF" }}>
          Multi-agent ETL Orchestrator
        </div>
      </div>

      {/* Scenario selector */}
      <div style={{
        background: "#fff", borderBottom: "1px solid #E5E7EB",
        padding: "10px 20px", display: "flex", gap: 8, flexWrap: "wrap"
      }}>
        <div style={{ fontSize: 11, color: "#9CA3AF", alignSelf: "center", marginRight: 4 }}>
          Try a scenario:
        </div>
        {SCENARIOS.map((s, i) => (
          <button key={i} onClick={() => loadScenario(s)}
            style={{
              padding: "5px 12px", borderRadius: 20, fontSize: 11, cursor: "pointer",
              border: `1px solid ${activeScenario?.label === s.label ? "#185FA5" : "#E5E7EB"}`,
              background: activeScenario?.label === s.label ? "#EFF6FF" : "#fff",
              color: activeScenario?.label === s.label ? "#185FA5" : "#555",
              fontWeight: activeScenario?.label === s.label ? 600 : 400
            }}>
            {s.icon} {s.label}
          </button>
        ))}
      </div>

      {/* Chat area */}
      <div style={{ flex: 1, overflowY: "auto", padding: "20px" }}>
        {messages.length === 0 && !typing && (
          <div style={{ textAlign: "center", padding: "60px 20px", color: "#9CA3AF" }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🤖</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: "#374151", marginBottom: 6 }}>
              AIBridge Multi-Agent System
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.6, maxWidth: 400, margin: "0 auto" }}>
              Pick a scenario above to see how the agents work together.
              Each request is automatically routed to the right combination of agents.
            </div>
            <div style={{
              display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8,
              maxWidth: 500, margin: "24px auto 0", textAlign: "left"
            }}>
              {[
                ["🔴 Job failures", "Auto-diagnosed and fixed"],
                ["🏗️ New warehouse", "Full agent pipeline"],
                ["📊 Business questions", "Direct BI query"],
                ["🔄 Selective refresh", "Only what changed"],
                ["✏️ Logic changes", "AI-assisted SQL update"],
                ["⏰ Scheduling", "Natural language cron"],
              ].map(([t, d], i) => (
                <div key={i} style={{
                  background: "#fff", border: "1px solid #E5E7EB",
                  borderRadius: 8, padding: "8px 12px"
                }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "#111" }}>{t}</div>
                  <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 2 }}>{d}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} isNew={i === newMsgIndex} />
        ))}

        {typing && (
          <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "flex-start" }}>
            <div style={{
              width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
              background: "linear-gradient(135deg, #185FA5, #534AB7)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 14, color: "#fff", fontWeight: 700
            }}>A</div>
            <div style={{
              background: "#fff", border: "1px solid #E5E7EB",
              borderRadius: "4px 18px 18px 18px",
              padding: "12px 16px", display: "flex", gap: 4, alignItems: "center"
            }}>
              {[0, 1, 2].map(i => (
                <div key={i} style={{
                  width: 6, height: 6, borderRadius: "50%", background: "#9CA3AF",
                  animation: "bounce 1.2s infinite",
                  animationDelay: `${i * 0.2}s`
                }} />
              ))}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Continue / Input */}
      <div style={{
        background: "#fff", borderTop: "1px solid #E5E7EB",
        padding: "12px 20px"
      }}>
        {canContinue && (
          <div style={{ marginBottom: 10 }}>
            <button onClick={continueScenario} style={{
              width: "100%", padding: "10px", borderRadius: 8, border: "1px dashed #185FA5",
              background: "#EFF6FF", color: "#185FA5", fontSize: 12, cursor: "pointer",
              fontWeight: 500
            }}>
              ▶ Continue scenario — see next message
            </button>
          </div>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          <input
            style={{
              flex: 1, padding: "10px 16px", borderRadius: 24,
              border: "1px solid #E5E7EB", fontSize: 13, outline: "none",
              background: "#F9FAFB"
            }}
            placeholder="Type anything — e.g. 'Why did my pipeline fail?' or 'Show me sales by region'"
            value={input}
            onChange={e => setInput(e.target.value)}
          />
          <button style={{
            padding: "10px 18px", borderRadius: 24, border: "none",
            background: "#185FA5", color: "#fff", fontSize: 13,
            cursor: "pointer", fontWeight: 500
          }}>Send</button>
        </div>
        <div style={{ fontSize: 10, color: "#9CA3AF", marginTop: 6, textAlign: "center" }}>
          OrchestratorAgent routes your request to the right agents automatically
        </div>
      </div>

      <style>{`
        @keyframes bounce {
          0%, 60%, 100% { transform: translateY(0); }
          30% { transform: translateY(-4px); }
        }
      `}</style>
    </div>
  )
}
