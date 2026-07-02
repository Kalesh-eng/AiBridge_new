/**
 * SqlScripts.jsx
 * View, copy and run generated SQL scripts.
 */

import { useState, useEffect } from 'react'
import { pipelineAPI, sqlAPI } from '../api/api'
import { PageHeader, PageBody } from '../components/Layout'

export default function SqlScripts() {
  const [pipelines,   setPipelines]   = useState([])
  const [selected,    setSelected]    = useState(null)
  const [scripts,     setScripts]     = useState([])
  const [activeIdx,   setActiveIdx]   = useState(0)
  const [loading,     setLoading]     = useState(true)
  const [running,     setRunning]     = useState(false)
  const [runResult,   setRunResult]   = useState(null)
  const [runError,    setRunError]    = useState(null)
  const [copied,      setCopied]      = useState(false)

  useEffect(() => {
    pipelineAPI.list().then(r => {
      const list = r.data.pipelines || []
      setPipelines(list)
      if (list.length > 0) {
        setSelected(list[0])
        setScripts(list[0].artifacts?.sql_scripts?.scripts || [])
      }
    }).finally(() => setLoading(false))
  }, [])

  const selectPipeline = (p) => {
    setSelected(p)
    setScripts(p.artifacts?.sql_scripts?.scripts || [])
    setActiveIdx(0)
    setRunResult(null)
    setRunError(null)
  }

  const copySQL = () => {
    const sql = scripts[activeIdx]?.sql || ''
    navigator.clipboard.writeText(sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const runSQL = async () => {
    const sql = scripts[activeIdx]?.sql || ''
    if (!sql) return
    setRunning(true)
    setRunResult(null)
    setRunError(null)
    try {
      const r = await sqlAPI.run(sql)
      setRunResult(r.data)
    } catch (e) {
      setRunError(e.response?.data?.detail || e.message)
    }
    setRunning(false)
  }

  const downloadAll = () => {
    const content = scripts.map(s =>
      `-- ── ${s.label} ──────────────────────────────\n${s.sql}\n`
    ).join('\n\n')
    const blob = new Blob([content], { type: 'text/sql' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `${selected?.name || 'pipeline'}_scripts.sql`
    a.click()
    URL.revokeObjectURL(url)
  }

  const activeScript = scripts[activeIdx]

  return (
    <>
      <PageHeader
        title="SQL scripts"
        subtitle="Generated staging, dimension load and fact load scripts"
        action={
          scripts.length > 0 && (
            <button style={btnGhost} onClick={downloadAll}>
              ↓ Download all
            </button>
          )
        }
      />
      <PageBody>
        {loading && <div style={muted}>Loading...</div>}

        {!loading && pipelines.length === 0 && (
          <div style={emptyBox}>
            No pipelines yet. Run the ETL Agent first.
          </div>
        )}

        {/* Pipeline selector */}
        {pipelines.length > 1 && (
          <div style={{ marginBottom: 14, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {pipelines.map(p => (
              <button key={p.id}
                style={selected?.id === p.id ? btnActive : btnGhost}
                onClick={() => selectPipeline(p)}>
                {p.name}
              </button>
            ))}
          </div>
        )}

        {/* Script tabs */}
        {scripts.length > 0 && (
          <div style={{ display: 'flex', gap: 5, marginBottom: 12 }}>
            {scripts.map((s, i) => (
              <button key={i}
                style={i === activeIdx ? btnActive : btnGhost}
                onClick={() => { setActiveIdx(i); setRunResult(null); setRunError(null) }}>
                {s.label || s.name}
              </button>
            ))}
          </div>
        )}

        {/* Active script */}
        {activeScript && (
          <div>
            {/* Description */}
            {activeScript.description && (
              <div style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
                {activeScript.description}
              </div>
            )}

            {/* SQL code block */}
            <div style={{ position: 'relative', marginBottom: 10 }}>
              <pre style={sqlBlock}>{activeScript.sql}</pre>
            </div>

            {/* Actions */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <button style={btnPrimary} onClick={copySQL}>
                {copied ? '✓ Copied!' : 'Copy SQL'}
              </button>
              <button style={btnGhost} onClick={runSQL} disabled={running}>
                {running ? 'Running...' : '▶ Run on DuckDB'}
              </button>
              <button style={btnGhost} onClick={downloadAll}>
                ↓ Download all scripts
              </button>
            </div>

            {/* Run result */}
            {runResult && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#3B6D11', marginBottom: 8 }}>
                  ✓ Query executed — {runResult.row_count} rows returned
                </div>
                {runResult.columns?.length > 0 && (
                  <div style={{ overflowX: 'auto' }}>
                    <table style={tbl}>
                      <thead>
                        <tr>
                          {runResult.columns.map(c => (
                            <th key={c} style={th}>{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(runResult.rows || []).slice(0, 20).map((row, i) => (
                          <tr key={i}>
                            {row.map((cell, j) => (
                              <td key={j} style={td}>{String(cell)}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {runResult.row_count > 20 && (
                      <div style={{ fontSize: 11, color: '#888', marginTop: 6 }}>
                        Showing 20 of {runResult.row_count} rows
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Run error */}
            {runError && (
              <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 11, color: '#991b1b', marginTop: 10 }}>
                Error: {runError}
              </div>
            )}
          </div>
        )}

        {selected && scripts.length === 0 && (
          <div style={emptyBox}>No SQL scripts found for this pipeline.</div>
        )}

      </PageBody>
    </>
  )
}

const sqlBlock  = { background: '#1e1e1e', color: '#d4d4d4', borderRadius: 8, padding: '14px 16px', fontSize: 11, fontFamily: 'monospace', overflowX: 'auto', lineHeight: 1.8, whiteSpace: 'pre', border: '1px solid #333' }
const emptyBox  = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 32, textAlign: 'center', fontSize: 13, color: '#888' }
const muted     = { fontSize: 13, color: '#888' }
const tbl       = { width: '100%', borderCollapse: 'collapse', fontSize: 11 }
const th        = { background: '#f9fafb', padding: '6px 8px', textAlign: 'left', fontWeight: 500, color: '#555', borderBottom: '1px solid #e5e7eb', fontSize: 10 }
const td        = { padding: '5px 8px', borderBottom: '1px solid #f3f4f6', color: '#111', fontFamily: 'monospace', fontSize: 10 }
const btnPrimary= { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhost  = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnActive = { padding: '6px 12px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
