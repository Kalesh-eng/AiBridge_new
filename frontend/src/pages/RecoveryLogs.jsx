/**
 * RecoveryLogs.jsx
 * Shows all Recovery Agent activations.
 * - Stats: total errors auto-fixed
 * - List: every recovery attempt with details
 * - Drill-down: click any log to see step-by-step reasoning
 */

import { useState, useEffect } from 'react'
import { PageHeader, PageBody } from '../components/Layout'
import { Spinner, EmptyState, getErrorMessage } from '../components/ErrorBoundary'
import api from '../api/api'

export default function RecoveryLogs() {
  const [logs,        setLogs]       = useState([])
  const [stats,       setStats]      = useState(null)
  const [loading,     setLoading]    = useState(true)
  const [selectedLog, setSelectedLog]= useState(null)
  const [logDetail,   setLogDetail]  = useState(null)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      const [statsRes, logsRes] = await Promise.all([
        api.get('/recovery/stats'),
        api.get('/recovery/logs?limit=100')
      ])
      setStats(statsRes.data)
      setLogs(logsRes.data.logs || [])
    } catch (e) {
      console.error(getErrorMessage(e))
    }
    setLoading(false)
  }

  const openLog = async (logId) => {
    setSelectedLog(logId)
    setLogDetail(null)
    try {
      const r = await api.get(`/recovery/logs/${logId}`)
      setLogDetail(r.data)
    } catch (e) {
      setLogDetail({ error: getErrorMessage(e) })
    }
  }

  return (
    <>
      <PageHeader
        title="Recovery Agent — Activity Log"
        subtitle="Every error the agent has auto-fixed in your pipelines"
      />
      <PageBody>

        {loading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
            <Spinner />
          </div>
        )}

        {!loading && stats && (
          <>
            {/* Stats summary */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: 18 }}>
              <KPI label="Total activations"  val={stats.total}        color="#185FA5" icon="🤖" />
              <KPI label="Auto-recovered"      val={stats.recovered}    color="#3B6D11" icon="✓"  />
              <KPI label="Could not fix"      val={stats.failed}       color="#A32D2D" icon="✗"  />
              <KPI label="Success rate"        val={`${stats.success_rate}%`} color="#534AB7" icon="📊" />
            </div>

            {/* Top error patterns */}
            {stats.top_actions && stats.top_actions.length > 0 && (
              <div style={card}>
                <div style={sectionTitle}>Most common recovery actions</div>
                {stats.top_actions.map(([action, count]) => (
                  <div key={action} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0', fontSize: 12 }}>
                    <span style={{ fontFamily: 'monospace', color: '#185FA5', minWidth: 200 }}>{action}</span>
                    <div style={{ flex: 1, background: '#f3f4f6', borderRadius: 4, height: 12 }}>
                      <div style={{
                        width: `${(count / stats.total) * 100}%`,
                        height: '100%',
                        background: '#185FA5',
                        borderRadius: 4
                      }} />
                    </div>
                    <span style={{ color: '#555', minWidth: 30, textAlign: 'right' }}>{count}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Empty state */}
        {!loading && logs.length === 0 && (
          <EmptyState
            icon="🤖"
            title="No Recovery Agent activity yet"
            message="The Recovery Agent activates only when a pipeline script fails. As soon as something fails, the agent will try to fix it and log everything here."
          />
        )}

        {/* Log list */}
        {!loading && logs.length > 0 && (
          <>
            <div style={sectionTitle}>Recovery Agent activations ({logs.length})</div>

            {logs.map(log => (
              <div
                key={log.id}
                style={{
                  ...card,
                  borderLeft: `3px solid ${log.recovered ? '#3B6D11' : '#A32D2D'}`,
                  cursor: 'pointer'
                }}
                onClick={() => openLog(log.id)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                  <span style={{ fontSize: 16 }}>
                    {log.recovered ? '✓' : '✗'}
                  </span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#111' }}>
                      {log.failed_script}
                    </div>
                    <div style={{ fontSize: 11, color: '#888' }}>
                      {log.action_taken} · {log.fix_method}
                    </div>
                  </div>
                  <span style={log.recovered ? chipGreen : chipRed}>
                    {log.recovered ? 'Recovered' : 'Failed'}
                  </span>
                  <span style={{ fontSize: 10, color: '#aaa' }}>
                    {log.started_at ? new Date(log.started_at).toLocaleString() : ''}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: '#991b1b', fontFamily: 'monospace', background: '#fef2f2', padding: '4px 8px', borderRadius: 4 }}>
                  {log.error_message}
                </div>
                <div style={{ fontSize: 11, color: '#555', marginTop: 6 }}>
                  Summary: {log.summary}
                </div>
              </div>
            ))}
          </>
        )}

        {/* Detail modal */}
        {selectedLog && (
          <div style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100
          }} onClick={() => setSelectedLog(null)}>
            <div style={{
              background: '#fff', borderRadius: 10, padding: 20, width: 720,
              maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)'
            }} onClick={e => e.stopPropagation()}>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>Recovery Agent — Step-by-step log</div>
                <button onClick={() => setSelectedLog(null)} style={btnGhost}>Close</button>
              </div>

              {!logDetail ? (
                <Spinner />
              ) : logDetail.error ? (
                <div style={{ color: '#991b1b', fontSize: 12 }}>{logDetail.error}</div>
              ) : (
                <>
                  <div style={{ fontSize: 12, color: '#555', marginBottom: 10 }}>
                    <strong>Failed script:</strong> {logDetail.failed_script}<br />
                    <strong>Action taken:</strong> {logDetail.action_taken}<br />
                    <strong>Method:</strong> {logDetail.fix_method}<br />
                    <strong>Result:</strong> {logDetail.recovered ? '✓ Recovered' : '✗ Failed'}
                  </div>

                  <div style={sectionTitle}>Error</div>
                  <div style={{ background: '#fef2f2', padding: 10, borderRadius: 6, fontSize: 11, fontFamily: 'monospace', color: '#991b1b', marginBottom: 12 }}>
                    {logDetail.error_message}
                  </div>

                  <div style={sectionTitle}>Agent reasoning (step-by-step)</div>
                  <div style={{ background: '#1e1e1e', padding: 12, borderRadius: 6, marginBottom: 12 }}>
                    {(logDetail.attempts || []).map((attempt, i) => (
                      <div key={i} style={{
                        fontSize: 11, fontFamily: 'monospace', marginBottom: 4,
                        color: attempt.level === 'error'   ? '#fca5a5' :
                               attempt.level === 'success' ? '#a7d9a0' :
                               attempt.level === 'warning' ? '#fde68a' : '#d4d4d4'
                      }}>
                        <span style={{ color: '#888' }}>
                          {new Date(attempt.timestamp).toLocaleTimeString()}
                        </span>
                        {' '}— {attempt.message}
                      </div>
                    ))}
                  </div>

                  {logDetail.fix_sql && (
                    <>
                      <div style={sectionTitle}>Fix SQL generated</div>
                      <pre style={{ background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6, fontSize: 10, overflowX: 'auto', lineHeight: 1.6 }}>
                        {logDetail.fix_sql}
                      </pre>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        )}

      </PageBody>
    </>
  )
}

function KPI({ label, val, color, icon }) {
  return (
    <div style={{ background: '#f9fafb', borderRadius: 8, padding: '12px 14px', borderLeft: `3px solid ${color}` }}>
      <div style={{ fontSize: 18 }}>{icon}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color, marginTop: 4 }}>{val}</div>
      <div style={{ fontSize: 10, color: '#888' }}>{label}</div>
    </div>
  )
}

const card         = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 8 }
const sectionTitle = { fontSize: 10, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8, marginTop: 4 }
const chipGreen    = { background: '#EAF3DE', color: '#3B6D11', padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }
const chipRed      = { background: '#FCEBEB', color: '#A32D2D', padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }
const btnGhost     = { padding: '5px 12px', background: '#fff', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer', color: '#555' }
