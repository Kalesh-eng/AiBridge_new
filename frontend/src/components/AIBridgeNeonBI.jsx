import { useState, useRef, useEffect } from "react";

// ─── Neon palette ───────────────────────────────────────────────
const C = {
  cyan:   "#00f5ff",
  pink:   "#ff00ff",
  green:  "#00ff88",
  amber:  "#ffaa00",
  violet: "#9085e9",
  red:    "#ff4466",
};

const SERIES = [C.cyan, C.pink, C.green, C.amber, C.violet, C.red];

// ─── Shared neon styles ─────────────────────────────────────────
const base = {
  fontFamily: "'Share Tech Mono', 'Courier New', monospace",
  background: "#020b18",
  color: C.cyan,
};

const card = {
  background: "rgba(0,245,255,0.03)",
  border: "1px solid rgba(0,245,255,0.2)",
  borderRadius: 8,
  padding: "14px 16px",
  position: "relative",
  overflow: "hidden",
};

const glow = (color = C.cyan, strength = 10) =>
  `0 0 ${strength}px ${color}, 0 0 ${strength * 2}px ${color}44`;

// ─── Chart renderers ────────────────────────────────────────────

function NeonBarChart({ data, labelKey, valueKey }) {
  const max = Math.max(...data.map(d => d[valueKey]));
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 140, paddingBottom: 24, position: "relative" }}>
      {data.map((d, i) => {
        const pct = (d[valueKey] / max) * 100;
        const color = SERIES[i % SERIES.length];
        return (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4, height: "100%" }}>
            <div style={{ fontSize: 9, color, textShadow: glow(color, 4), marginBottom: 2 }}>
              {typeof d[valueKey] === "number" && d[valueKey] > 999
                ? (d[valueKey] / 1000).toFixed(1) + "k"
                : d[valueKey]}
            </div>
            <div style={{ flex: 1, width: "100%", display: "flex", alignItems: "flex-end" }}>
              <div style={{
                width: "100%", height: `${pct}%`, minHeight: 4,
                background: color, borderRadius: "3px 3px 0 0",
                boxShadow: glow(color, 6), opacity: 0.85,
                transition: "height 0.6s ease",
              }} />
            </div>
            <div style={{ fontSize: 8, color: "rgba(0,245,255,0.5)", textAlign: "center", lineHeight: 1.2 }}>
              {String(d[labelKey]).slice(0, 6)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function NeonLineChart({ data, labelKey, valueKey }) {
  const W = 400, H = 130, pad = 12;
  const vals = data.map(d => d[valueKey]);
  const min = Math.min(...vals), max = Math.max(...vals);
  const x = i => pad + (i / (vals.length - 1)) * (W - pad * 2);
  const y = v => H - pad - ((v - min) / (max - min || 1)) * (H - pad * 2);

  let path = `M${x(0)},${y(vals[0])}`;
  let area = `M${x(0)},${H} L${x(0)},${y(vals[0])}`;
  for (let i = 1; i < vals.length; i++) {
    const cx1 = x(i - 1) + (x(i) - x(i - 1)) / 3;
    const cx2 = x(i) - (x(i) - x(i - 1)) / 3;
    path += ` C${cx1},${y(vals[i - 1])} ${cx2},${y(vals[i])} ${x(i)},${y(vals[i])}`;
    area += ` C${cx1},${y(vals[i - 1])} ${cx2},${y(vals[i])} ${x(i)},${y(vals[i])}`;
  }
  area += ` L${x(vals.length - 1)},${H} Z`;

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ height: 130 }}>
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.pink} stopOpacity="0.35" />
          <stop offset="100%" stopColor={C.pink} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#lg)" />
      <path d={path} fill="none" stroke={C.pink} strokeWidth="2"
        style={{ filter: `drop-shadow(0 0 4px ${C.pink})` }} />
      {vals.map((v, i) => (
        <circle key={i} cx={x(i)} cy={y(v)} r="3.5" fill={C.pink}
          style={{ filter: `drop-shadow(0 0 5px ${C.pink})` }} />
      ))}
      {data.map((d, i) => (
        <text key={i} x={x(i)} y={H - 1} textAnchor="middle"
          fontSize="8" fill="rgba(0,245,255,0.4)">{String(d[labelKey]).slice(0, 5)}</text>
      ))}
    </svg>
  );
}

function NeonDonutChart({ data, labelKey, valueKey }) {
  const total = data.reduce((s, d) => s + d[valueKey], 0);
  const cx = 70, cy = 70, r = 52, inner = 32;
  let angle = -Math.PI / 2;
  const slices = data.map((d, i) => {
    const color = SERIES[i % SERIES.length];
    const sweep = (d[valueKey] / total) * 2 * Math.PI;
    const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(angle + sweep), y2 = cy + r * Math.sin(angle + sweep);
    const xi1 = cx + inner * Math.cos(angle), yi1 = cy + inner * Math.sin(angle);
    const xi2 = cx + inner * Math.cos(angle + sweep), yi2 = cy + inner * Math.sin(angle + sweep);
    const large = sweep > Math.PI ? 1 : 0;
    const path = `M${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} L${xi2},${yi2} A${inner},${inner} 0 ${large} 0 ${xi1},${yi1} Z`;
    angle += sweep;
    return { path, color, label: d[labelKey], pct: Math.round(d[valueKey] / total * 100) };
  });

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <svg width="140" height="140" viewBox="0 0 140 140" style={{ flexShrink: 0 }}>
        {slices.map((s, i) => (
          <path key={i} d={s.path} fill={s.color} opacity="0.85"
            style={{ filter: `drop-shadow(0 0 5px ${s.color})` }} />
        ))}
        <text x="70" y="65" textAnchor="middle" fontFamily="'Orbitron',monospace"
          fontSize="18" fontWeight="700" fill={C.cyan}
          style={{ filter: `drop-shadow(0 0 8px ${C.cyan})` }}>
          {slices[0]?.pct}%
        </text>
        <text x="70" y="80" textAnchor="middle" fontSize="8" fill="rgba(0,245,255,0.5)">
          {slices[0]?.label}
        </text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {slices.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: s.color, boxShadow: glow(s.color, 4), flexShrink: 0 }} />
            <span style={{ color: "rgba(0,245,255,0.7)" }}>{s.label}</span>
            <span style={{ marginLeft: "auto", paddingLeft: 8, color: s.color, textShadow: glow(s.color, 3) }}>{s.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function NeonTable({ columns, rows }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr>
            {columns.map((col, i) => (
              <th key={i} style={{
                padding: "6px 10px", textAlign: "left", fontSize: 9,
                letterSpacing: "0.1em", color: C.cyan,
                textShadow: glow(C.cyan, 3),
                borderBottom: "1px solid rgba(0,245,255,0.2)",
              }}>{String(col).toUpperCase()}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 10).map((row, i) => (
            <tr key={i} style={{ borderBottom: "1px solid rgba(0,245,255,0.06)" }}>
              {row.map((cell, j) => (
                <td key={j} style={{
                  padding: "6px 10px",
                  color: j === 0 ? C.cyan : "rgba(0,245,255,0.6)",
                  textShadow: j === 0 ? glow(C.cyan, 3) : "none",
                }}>{cell === null ? "—" : String(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Chart type detector ────────────────────────────────────────
function detectChartType(question, columns, rows) {
  const q = question.toLowerCase();
  const numericCols = columns.filter((_, i) =>
    rows.length > 0 && typeof rows[0][i] === "number"
  );
  const hasMultipleRows = rows.length > 2;

  if (q.includes("trend") || q.includes("over time") || q.includes("by year") || q.includes("monthly"))
    return "line";
  if (q.includes("split") || q.includes("proportion") || q.includes("breakdown") || q.includes("distribution"))
    return "donut";
  if ((q.includes("top") || q.includes("rank") || q.includes("most") || q.includes("highest") || q.includes("count")) && hasMultipleRows)
    return "bar";
  if (numericCols.length >= 1 && hasMultipleRows && rows.length <= 20)
    return "bar";
  return "table";
}

function buildChartData(columns, rows, chartType) {
  if (!rows.length) return null;
  const numericIdx = columns.findIndex((_, i) =>
    rows.some(r => typeof r[i] === "number")
  );
  const labelIdx = numericIdx > 0 ? 0 : (numericIdx === 0 ? 1 : 0);
  const valueIdx = numericIdx >= 0 ? numericIdx : 1;

  return rows.map(row => ({
    label: row[labelIdx],
    value: row[valueIdx],
    ...Object.fromEntries(columns.map((c, i) => [c, row[i]])),
  }));
}

// ─── Smart chart renderer ───────────────────────────────────────
function SmartChart({ question, columns, rows }) {
  const chartType = detectChartType(question, columns, rows);
  const data = buildChartData(columns, rows, chartType);

  if (!data || data.length === 0) {
    return <div style={{ color: "rgba(0,245,255,0.4)", fontSize: 12, padding: "20px 0" }}>No data to visualize.</div>;
  }

  if (chartType === "bar") return <NeonBarChart data={data} labelKey="label" valueKey="value" />;
  if (chartType === "line") return <NeonLineChart data={data} labelKey="label" valueKey="value" />;
  if (chartType === "donut") return <NeonDonutChart data={data} labelKey="label" valueKey="value" />;
  return <NeonTable columns={columns} rows={rows} />;
}

// ─── Typing animation ───────────────────────────────────────────
function TypingDots() {
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
      {[0, 1, 2].map(i => (
        <span key={i} style={{
          width: 5, height: 5, borderRadius: "50%", background: C.cyan,
          boxShadow: glow(C.cyan, 4),
          animation: `blink 1.2s ${i * 0.2}s infinite`,
          display: "inline-block",
        }} />
      ))}
      <style>{`@keyframes blink{0%,80%,100%{opacity:0.2}40%{opacity:1}}`}</style>
    </span>
  );
}

// ─── Main component ─────────────────────────────────────────────
export default function AIBridgeNeonBI() {
  const [messages, setMessages] = useState([
    {
      role: "system",
      text: "AIBRIDGE BI ONLINE — Ask anything about your warehouse data.",
      chartType: null,
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [pipeline, setPipeline] = useState("67b29244");
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // ── Call AIBridge backend ──
  async function ask() {
    const q = input.trim();
    if (!q || loading) return;
    setInput("");
    setMessages(m => [...m, { role: "user", text: q }]);
    setLoading(true);

    try {
      // Step 1: NL → SQL
      const nlRes = await fetch("http://localhost:8888/nl/to-sql", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer demo-token" },
        body: JSON.stringify({ question: q, pipeline_id: pipeline }),
      });
      const nlData = await nlRes.json();
      const sql = nlData.sql || nlData.query;

      if (!sql) throw new Error("Could not generate SQL for that question.");

      // Step 2: Run SQL
      const runRes = await fetch("http://localhost:8888/sql/run", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer demo-token" },
        body: JSON.stringify({ sql, connector_id: "d225a3d1-3874-4b66-9171-b8fda46461e7" }),
      });
      const runData = await runRes.json();

      setMessages(m => [...m, {
        role: "assistant",
        text: nlData.explanation || `Query executed — ${runData.row_count} rows returned.`,
        sql,
        columns: runData.columns || [],
        rows: runData.rows || [],
        question: q,
      }]);
    } catch (err) {
      setMessages(m => [...m, {
        role: "error",
        text: `⚠ ${err.message}`,
      }]);
    } finally {
      setLoading(false);
    }
  }

  // ── Suggested questions ──
  const suggestions = [
    "Top 5 brands by average price",
    "Price trend by year",
    "Fuel type breakdown",
    "Listings by city",
    "Manual vs automatic count",
  ];

  return (
    <div style={{ ...base, minHeight: 600, display: "flex", flexDirection: "column" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700&display=swap');
        ::-webkit-scrollbar{width:4px;} ::-webkit-scrollbar-track{background:transparent;}
        ::-webkit-scrollbar-thumb{background:rgba(0,245,255,0.3);border-radius:2px;}
        textarea:focus,input:focus{outline:none;}
        .msg-user{animation:fadeIn 0.3s ease;}
        .msg-ai{animation:fadeIn 0.4s ease;}
        @keyframes fadeIn{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:none;}}
        .send-btn:hover{background:rgba(0,245,255,0.15)!important;cursor:pointer;}
        .sugg:hover{background:rgba(0,245,255,0.1)!important;cursor:pointer;border-color:rgba(0,245,255,0.5)!important;}
        .scan::after{content:'';position:absolute;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,0.04) 2px,rgba(0,0,0,0.04) 4px);pointer-events:none;border-radius:8px;}
      `}</style>

      {/* Header */}
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid rgba(0,245,255,0.15)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        background: "rgba(0,245,255,0.02)",
      }}>
        <div style={{
          fontFamily: "'Orbitron',monospace", fontSize: 14, fontWeight: 700,
          letterSpacing: "0.2em", color: C.cyan, textShadow: glow(C.cyan, 8),
        }}>◈ AIBRIDGE BI</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{
            width: 6, height: 6, borderRadius: "50%", background: C.green,
            boxShadow: glow(C.green, 5),
            animation: "blink 2s infinite",
          }} />
          <span style={{ fontSize: 9, color: "rgba(0,245,255,0.5)", letterSpacing: "0.1em" }}>
            LIVE · WAREHOUSE CONNECTED
          </span>
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: 16, minHeight: 300 }}>
        {messages.map((msg, i) => (
          <div key={i} className={msg.role === "user" ? "msg-user" : "msg-ai"}>

            {/* System message */}
            {msg.role === "system" && (
              <div style={{ textAlign: "center", fontSize: 10, color: "rgba(0,245,255,0.3)", letterSpacing: "0.08em", padding: "8px 0" }}>
                {msg.text}
              </div>
            )}

            {/* User message */}
            {msg.role === "user" && (
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <div style={{
                  background: "rgba(0,245,255,0.08)", border: "1px solid rgba(0,245,255,0.25)",
                  borderRadius: "8px 8px 0 8px", padding: "8px 14px",
                  fontSize: 12, color: C.cyan, maxWidth: "70%",
                  textShadow: glow(C.cyan, 3),
                }}>{msg.text}</div>
              </div>
            )}

            {/* Error */}
            {msg.role === "error" && (
              <div style={{
                ...card, borderColor: "rgba(255,68,102,0.4)",
                fontSize: 11, color: C.red, textShadow: glow(C.red, 4),
              }}>{msg.text}</div>
            )}

            {/* Assistant with chart */}
            {msg.role === "assistant" && (
              <div className="scan" style={{ ...card }}>
                <div style={{
                  fontSize: 9, letterSpacing: "0.12em",
                  color: "rgba(0,245,255,0.4)", marginBottom: 10,
                  fontFamily: "'Orbitron',monospace",
                }}>◈ AIBRIDGE ANALYSIS</div>

                <div style={{ fontSize: 11, color: "rgba(0,245,255,0.7)", marginBottom: 12, lineHeight: 1.6 }}>
                  {msg.text}
                </div>

                {/* Chart */}
                {msg.rows?.length > 0 && (
                  <SmartChart question={msg.question} columns={msg.columns} rows={msg.rows} />
                )}

                {/* SQL toggle */}
                {msg.sql && (
                  <details style={{ marginTop: 12 }}>
                    <summary style={{
                      fontSize: 9, color: "rgba(0,245,255,0.35)", cursor: "pointer",
                      letterSpacing: "0.08em", listStyle: "none",
                    }}>⟨/⟩ VIEW SQL</summary>
                    <pre style={{
                      marginTop: 8, padding: 10,
                      background: "rgba(0,0,0,0.4)", borderRadius: 4,
                      border: "1px solid rgba(0,245,255,0.1)",
                      fontSize: 10, color: "rgba(0,245,255,0.5)",
                      overflowX: "auto", lineHeight: 1.5, whiteSpace: "pre-wrap",
                    }}>{msg.sql}</pre>
                  </details>
                )}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div style={{ ...card, display: "flex", alignItems: "center", gap: 10 }}>
            <TypingDots />
            <span style={{ fontSize: 11, color: "rgba(0,245,255,0.5)" }}>generating query and visualization...</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      {messages.length <= 2 && (
        <div style={{ padding: "0 16px 12px", display: "flex", flexWrap: "wrap", gap: 6 }}>
          {suggestions.map((s, i) => (
            <button key={i} className="sugg" onClick={() => setInput(s)} style={{
              background: "rgba(0,245,255,0.04)", border: "1px solid rgba(0,245,255,0.2)",
              borderRadius: 20, padding: "4px 12px", fontSize: 10,
              color: "rgba(0,245,255,0.6)", cursor: "pointer", fontFamily: "'Share Tech Mono',monospace",
              transition: "all 0.2s",
            }}>{s}</button>
          ))}
        </div>
      )}

      {/* Input */}
      <div style={{
        padding: "12px 16px", borderTop: "1px solid rgba(0,245,255,0.15)",
        background: "rgba(0,245,255,0.02)", display: "flex", gap: 10, alignItems: "flex-end",
      }}>
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }}
          placeholder="Ask your warehouse anything..."
          rows={1}
          style={{
            flex: 1, background: "rgba(0,245,255,0.05)",
            border: "1px solid rgba(0,245,255,0.25)", borderRadius: 6,
            padding: "8px 12px", color: C.cyan, fontSize: 12,
            fontFamily: "'Share Tech Mono',monospace", resize: "none",
            caretColor: C.cyan, lineHeight: 1.5,
          }}
        />
        <button className="send-btn" onClick={ask} disabled={loading || !input.trim()} style={{
          background: "rgba(0,245,255,0.08)", border: "1px solid rgba(0,245,255,0.3)",
          borderRadius: 6, padding: "8px 16px", color: loading ? "rgba(0,245,255,0.3)" : C.cyan,
          fontFamily: "'Orbitron',monospace", fontSize: 10, letterSpacing: "0.1em",
          textShadow: loading ? "none" : glow(C.cyan, 4), cursor: loading ? "not-allowed" : "pointer",
          transition: "all 0.2s",
        }}>
          {loading ? "..." : "RUN ▶"}
        </button>
      </div>
    </div>
  );
}
