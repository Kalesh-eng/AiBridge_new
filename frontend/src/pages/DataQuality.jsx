/**
 * DataQuality.jsx — AIBridge Data Quality Dashboard
 */

import { useState, useEffect } from 'react'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'

export default function DataQuality() {
  const [pipelines,      setPipelines]      = useState([])
  const [selected,       setSelected]       = useState(null)
  const [report,         setReport]         = useState(null)
  const [loading,        setLoading]        = useState(true)
  const [reportLoading,  setReportLoading]  = useState(false)
  const [running,        setRunning]        = useState(null)
  const [error,          setError]          = useState(null)
  const [activeTab,      setActiveTab]      = useState('overview')
  const [auditFilter,    setAuditFilter]    = useState('all')
  const [auditRecords,   setAuditRecords]   = useState([])
  const [auditLoading,   setAuditLoading]   = useState(false)

  useEffect(() => { loadPipelines() }, [])

  const loadPipelines = async () => {
    setLoading(true)
    try {
      const r = await api.get('/pipeline/list')
      setPipelines(r.data.pipelines || [])
    } catch (e) {
      setError('Could not load pipelines')
    }
    setLoading(false)
  }

  const loadReport = async (pipeline) => {
    setSelected(pipeline)
    setReport(null)
    setAuditRecords([])
    setReportLoading(true)
    setActiveTab('overview')
    setError(null)
    try {
      const r = await api.get(`/quality/report/${pipeline.id}`)
      setReport(r.data.report)
    } catch (e) {
      setError('Could not load quality report')
    }
    setReportLoading(false)
  }

  const loadAuditRecords = async (pipelineId) => {
    setAuditLoading(true)
    try {
      const r = await api.get(`/quality/audit/${pipelineId}`)
      console.log('Audit response:', r.data)
      setAuditRecords(r.data.records || [])
    } catch (e) {
      console.log('Audit error:', e)
      setAuditRecords([])
    }
    setAuditLoading(false)
  }

  const handleTabChange = (tabId) => {
    setActiveTab(tabId)
    if (tabId === 'audit' && selected && auditRecords.length === 0) {
      loadAuditRecords(selected.id)
    }
  }

  const runQualityCheck = async (pipeline) => {
    setRunning(pipeline.id)
    setError(null)
    try {
      const r = await api.post(`/quality/run/${pipeline.id}`)
      setReport(r.data.report)
      setSelected(pipeline)
      setActiveTab('overview')
      setAuditRecords([])
    } catch (e) {
      setError('Quality check failed: ' + (e.response?.data?.detail || e.message))
    }
    setRunning(null)
  }

  const getPipelineScore = (p) => p.artifacts?.quality_report?.score ?? null

  const scoreChip = (score) => {
    if (score === null) return { label: 'Not run', bg: '#f3f4f6', color: '#888', emoji: '—' }
    if (score >= 95)   return { label: `${score}%`, bg: '#EAF3DE', color: '#27500A', emoji: '✅' }
    if (score >= 80)   return { label: `${score}%`, bg: '#FEF3C7', color: '#92400E', emoji: '⚠️' }
    return               { label: `${score}%`, bg: '#FEE2E2', color: '#991B1B', emoji: '❌' }
  }

  const issueTypeLabel = (type) => {
    const map = {
      load_failure:           { label: 'Load Failure',   bg: '#FEE2E2', color: '#991B1B' },
      data_quality:           { label: 'Null Value',     bg: '#FEF3C7', color: '#92400E' },
      null_value:             { label: 'Null Value',     bg: '#FEF3C7', color: '#92400E' },
      duplicate_key:          { label: 'Duplicate',      bg: '#EDE9FE', color: '#5B21B6' },
      business_rule_violation:{ label: 'Rule Violation', bg: '#FEE2E2', color: '#991B1B' },
      duplicate_check:        { label: 'Duplicate',      bg: '#EDE9FE', color: '#5B21B6' },
    }
    return map[type] || { label: type || '—', bg: '#f3f4f6', color: '#555' }
  }

  const filteredAuditRecords = auditFilter === 'all'
    ? auditRecords
    : auditRecords.filter(r => r.issue_type === auditFilter || r.check_type === auditFilter)

  return (
    <>
      <PageHeader
        title="Data Quality"
        subtitle="Pre-load quality scores, check results and audit log of quarantined records"
      />
      <PageBody>
        {error && (
          <div style={errBox}>
            {error}
            <button style={{ float: 'right', background: 'none', border: 'none',
              cursor: 'pointer', color: '#991b1b' }} onClick={() => setError(null)}>✕</button>
          </div>
        )}

        {loading ? (
          <div style={{ fontSize: 12, color: '#888' }}>⏳ Loading pipelines...</div>
        ) : pipelines.length === 0 ? (
          <div style={emptyBox}>No pipelines yet — create one in the ETL Agent first.</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: selected ? '340px 1fr' : '1fr', gap: 16 }}>

            {/* ── Pipeline list ── */}
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#888',
                textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
                Pipelines
              </div>
              {pipelines.map(p => {
                const score = getPipelineScore(p)
                const chip  = scoreChip(score)
                const isSel = selected?.id === p.id
                return (
                  <div key={p.id} style={{
                    ...card,
                    borderColor: isSel ? '#185FA5' : '#e5e7eb',
                    background:  isSel ? '#F6FAFE' : '#fff',
                    cursor: 'pointer'
                  }} onClick={() => loadReport(p)}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#111' }}>{p.name}</div>
                        <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>
                          {p.artifacts?.sql_scripts?.scripts?.length || 0} scripts
                          · {p.source_tables?.length || 0} tables
                        </div>
                      </div>
                      <span style={{ padding: '2px 8px', borderRadius: 20, fontSize: 10,
                        fontWeight: 600, background: chip.bg, color: chip.color }}>
                        {chip.emoji} {chip.label}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                      <button
                        style={{ ...btnPrimary, fontSize: 10, padding: '3px 10px',
                          background: running === p.id ? '#888' : '#185FA5' }}
                        onClick={e => { e.stopPropagation(); runQualityCheck(p) }}
                        disabled={running === p.id}>
                        {running === p.id ? '⏳ Running...' : '▶ Run Check'}
                      </button>
                      {score !== null && (
                        <button style={btnGhostSmall}
                          onClick={e => { e.stopPropagation(); loadReport(p) }}>
                          📊 View Report
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* ── Right panel ── */}
            {selected && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between',
                  alignItems: 'center', marginBottom: 12 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: '#111' }}>{selected.name}</div>
                  <button style={btnGhostSmall}
                    onClick={() => { setSelected(null); setReport(null); setAuditRecords([]) }}>
                    ✕ Close
                  </button>
                </div>

                {reportLoading ? (
                  <div style={{ fontSize: 12, color: '#888', padding: 20 }}>⏳ Loading quality report...</div>
                ) : !report ? (
                  <div style={emptyBox}>
                    No quality report yet.
                    <br />
                    <button style={{ ...btnPrimary, marginTop: 12 }}
                      onClick={() => runQualityCheck(selected)}
                      disabled={running === selected.id}>
                      {running === selected.id ? '⏳ Running...' : '▶ Run Quality Check'}
                    </button>
                  </div>
                ) : (
                  <>
                    {/* Score banner */}
                    <div style={{
                      ...card,
                      background: scoreChip(report.score).bg,
                      borderColor: scoreChip(report.score).color + '44',
                      marginBottom: 12
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                          <div style={{ fontSize: 28, fontWeight: 800, color: scoreChip(report.score).color }}>
                            {scoreChip(report.score).emoji} {report.score}%
                          </div>
                          <div style={{ fontSize: 12, color: '#555', marginTop: 2 }}>
                            {report.total_passed}/{report.total_checks} checks passed
                            {report.total_removed > 0 && ` · ${report.total_removed} bad rows quarantined`}
                          </div>
                          <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>
                            Domain: {report.domain} · Phase: {report.phase} · Run: {report.run_id}
                          </div>
                        </div>
                        <div style={{ textAlign: 'right' }}>
                          <div style={{ fontSize: 11, color: '#555', marginBottom: 4 }}>Audit table</div>
                          <div style={{ fontSize: 11, fontFamily: 'monospace', color: '#185FA5', fontWeight: 600 }}>
                            {report.audit_table}
                          </div>
                          {report.audit_rows > 0 && (
                            <div style={{ fontSize: 10, color: '#991B1B', marginTop: 2 }}>
                              {report.audit_rows} records logged
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Tabs */}
                    <div style={{ display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap' }}>
                      {[
                        { id: 'overview', label: '📊 Overview' },
                        { id: 'null',     label: `🔍 Null Checks (${report.null_checks?.length || 0})` },
                        { id: 'dup',      label: `🔑 Duplicates (${report.dup_checks?.length || 0})` },
                        { id: 'rules',    label: `📋 Rules (${report.rule_checks?.length || 0})` },
                        { id: 'audit',    label: `🗃 Audit Log (${report.audit_rows || 0})` },
                      ].map(tab => (
                        <button key={tab.id}
                          onClick={() => handleTabChange(tab.id)}
                          style={{
                            padding: '5px 12px', fontSize: 11, borderRadius: 6,
                            cursor: 'pointer', fontWeight: activeTab === tab.id ? 600 : 400,
                            background: activeTab === tab.id ? '#185FA5' : '#fff',
                            color: activeTab === tab.id ? '#fff' : '#555',
                            border: `1px solid ${activeTab === tab.id ? '#185FA5' : '#d1d5db'}`
                          }}>
                          {tab.label}
                        </button>
                      ))}
                    </div>

                    {/* Overview tab */}
                    {activeTab === 'overview' && (
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                        {[
                          { label: 'Null Checks',      checks: report.null_checks || [], emoji: '🔍' },
                          { label: 'Duplicate Checks', checks: report.dup_checks  || [], emoji: '🔑' },
                          { label: 'Business Rules',   checks: report.rule_checks || [], emoji: '📋' },
                        ].map(section => {
                          const passed = section.checks.filter(c => c.passed).length
                          const total  = section.checks.length
                          const pct    = total > 0 ? Math.round((passed / total) * 100) : 100
                          const chip   = scoreChip(pct)
                          return (
                            <div key={section.label} style={{ ...card, textAlign: 'center', padding: '16px 12px' }}>
                              <div style={{ fontSize: 20, marginBottom: 4 }}>{section.emoji}</div>
                              <div style={{ fontSize: 11, color: '#888', marginBottom: 6 }}>{section.label}</div>
                              <div style={{ fontSize: 22, fontWeight: 800, color: chip.color }}>{passed}/{total}</div>
                              <div style={{ fontSize: 10, color: chip.color, fontWeight: 600, marginTop: 2 }}>
                                {chip.emoji} {pct}%
                              </div>
                            </div>
                          )
                        })}

                        {report.failed_items?.length > 0 && (
                          <div style={{ ...card, gridColumn: '1 / -1' }}>
                            <div style={{ fontSize: 12, fontWeight: 600, color: '#991B1B', marginBottom: 8 }}>
                              ✗ Failed Checks — Quarantined to Audit Log
                            </div>
                            {report.failed_items.map((item, i) => {
                              const it = issueTypeLabel(item.issue_type || item.type)
                              return (
                                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8,
                                  padding: '6px 0', borderBottom: i < report.failed_items.length - 1 ? '1px solid #f3f4f6' : 'none' }}>
                                  <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10,
                                    background: it.bg, color: it.color, fontWeight: 600, whiteSpace: 'nowrap' }}>
                                    {it.label}
                                  </span>
                                  <span style={{ fontSize: 11, color: '#374151', flex: 1 }}>{item.check}</span>
                                  <span style={{ fontSize: 10, color: '#991B1B' }}>{item.message}</span>
                                </div>
                              )
                            })}
                          </div>
                        )}

                        {!report.failed_items?.length && (
                          <div style={{ ...card, gridColumn: '1 / -1', textAlign: 'center',
                            padding: 20, background: '#EAF3DE', borderColor: '#a7d9a0' }}>
                            <div style={{ fontSize: 16 }}>✅</div>
                            <div style={{ fontSize: 12, color: '#27500A', fontWeight: 600, marginTop: 4 }}>
                              All checks passed — warehouse contains clean data only
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Null checks tab */}
                    {activeTab === 'null' && (
                      <div style={card}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 10 }}>
                          Null Checks on Staging Tables
                        </div>
                        <table style={tbl}>
                          <thead>
                            <tr>{['Table', 'Column', 'Nulls', 'Total', 'Status', 'Issue Type'].map(h => <th key={h} style={th}>{h}</th>)}</tr>
                          </thead>
                          <tbody>
                            {(report.null_checks || []).filter(c => !c.passed).map((c, i) => (
                              <tr key={i} style={{ background: c.passed ? '#fff' : '#FEF2F2' }}>
                                <td style={td}><code style={code}>{c.table}</code></td>
                                <td style={td}><code style={code}>{c.column}</code></td>
                                <td style={td}>{c.null_count ?? '—'}</td>
                                <td style={td}>{c.total_rows ?? '—'}</td>
                                <td style={td}>
                                  <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10,
                                    background: c.passed ? '#EAF3DE' : '#FEE2E2',
                                    color: c.passed ? '#27500A' : '#991B1B', fontWeight: 600 }}>
                                    {c.passed ? '✓ Pass' : '✗ Fail'}
                                  </span>
                                </td>
                                <td style={td}>
                                  {c.issue_type ? (
                                    <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10,
                                      background: issueTypeLabel(c.issue_type).bg,
                                      color: issueTypeLabel(c.issue_type).color }}>
                                      {issueTypeLabel(c.issue_type).label}
                                    </span>
                                  ) : '—'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Duplicate checks tab */}
                    {activeTab === 'dup' && (
                      <div style={card}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 10 }}>
                          Duplicate Key Checks on Staging Tables
                        </div>
                        <table style={tbl}>
                          <thead>
                            <tr>{['Table', 'Key Column', 'Duplicates', 'Total Rows', 'Status'].map(h => <th key={h} style={th}>{h}</th>)}</tr>
                          </thead>
                          <tbody>
                            {(report.dup_checks || []).map((c, i) => (
                              <tr key={i} style={{ background: c.passed ? '#fff' : '#FEF2F2' }}>
                                <td style={td}><code style={code}>{c.table}</code></td>
                                <td style={td}><code style={code}>{c.column}</code></td>
                                <td style={td}>{c.dup_groups ?? c.dup_count ?? '—'}</td>
                                <td style={td}>{c.total_rows ?? '—'}</td>
                                <td style={td}>
                                  <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10,
                                    background: c.passed ? '#EAF3DE' : '#FEE2E2',
                                    color: c.passed ? '#27500A' : '#991B1B', fontWeight: 600 }}>
                                    {c.passed ? '✓ Pass' : '✗ Fail'}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Business rules tab */}
                    {activeTab === 'rules' && (
                      <div style={card}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 10 }}>
                          Business Rules — AI Generated
                        </div>
                        {!(report.rule_checks || []).length ? (
                          <div style={{ fontSize: 12, color: '#888' }}>No business rules generated yet.</div>
                        ) : (
                          <table style={tbl}>
                            <thead>
                              <tr>{['Table', 'Rule', 'Violations', 'Total', 'Pass Rate', 'Status'].map(h => <th key={h} style={th}>{h}</th>)}</tr>
                            </thead>
                            <tbody>
                              {(report.rule_checks || []).map((c, i) => (
                                <tr key={i} style={{ background: c.passed ? '#fff' : '#FEF2F2' }}>
                                  <td style={td}><code style={code}>{c.table}</code></td>
                                  <td style={td}>{c.check}</td>
                                  <td style={td}>{c.violations ?? '—'}</td>
                                  <td style={td}>{c.total_rows ?? '—'}</td>
                                  <td style={td}>{c.pass_rate != null ? `${c.pass_rate}%` : '—'}</td>
                                  <td style={td}>
                                    <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10,
                                      background: c.passed ? '#EAF3DE' : '#FEE2E2',
                                      color: c.passed ? '#27500A' : '#991B1B', fontWeight: 600 }}>
                                      {c.passed ? '✓ Pass' : '✗ Fail'}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    )}

                    {/* Audit log tab — fetches directly from warehouse.dq_audit_log */}
                    {activeTab === 'audit' && (
                      <div style={card}>
                        <div style={{ display: 'flex', justifyContent: 'space-between',
                          alignItems: 'center', marginBottom: 10 }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>
                            Audit Log — Bad Records Quarantined Before Warehouse Load
                          </div>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            {[
                              { key: 'all',            label: 'All' },
                              { key: 'load_failure',   label: 'Load Failure' },
                              { key: 'null_value',     label: 'Null Value' },
                              { key: 'duplicate_key',  label: 'Duplicate' },
                              { key: 'duplicate_check',label: 'Duplicate' },
                              { key: 'business_rule_violation', label: 'Rule Violation' },
                            ].filter((f, i, arr) => arr.findIndex(x => x.label === f.label) === i)
                            .map(f => (
                              <button key={f.key}
                                onClick={() => setAuditFilter(f.key)}
                                style={{
                                  padding: '3px 8px', fontSize: 10, borderRadius: 6, cursor: 'pointer',
                                  background: auditFilter === f.key ? '#185FA5' : '#fff',
                                  color: auditFilter === f.key ? '#fff' : '#555',
                                  border: `1px solid ${auditFilter === f.key ? '#185FA5' : '#d1d5db'}`
                                }}>
                                {f.label}
                              </button>
                            ))}
                            <button style={btnGhostSmall}
                              onClick={() => loadAuditRecords(selected.id)}>
                              🔄 Refresh
                            </button>
                          </div>
                        </div>

                        {auditLoading ? (
                          <div style={{ fontSize: 12, color: '#888', padding: 20, textAlign: 'center' }}>
                            ⏳ Loading audit records...
                          </div>
                        ) : auditRecords.length === 0 ? (
                          <div style={{ textAlign: 'center', padding: 20,
                            background: '#EAF3DE', borderRadius: 6 }}>
                            <div style={{ fontSize: 16 }}>✅</div>
                            <div style={{ fontSize: 12, color: '#27500A', fontWeight: 600, marginTop: 4 }}>
                              No bad records found in audit log
                            </div>
                          </div>
                        ) : (
                          <>
                            <div style={{ fontSize: 10, color: '#888', marginBottom: 8 }}>
                              Showing {filteredAuditRecords.length} of {auditRecords.length} records from{' '}
                              <code style={code}>{report.audit_table}</code>
                            </div>
                            <table style={tbl}>
                              <thead>
                                <tr>
                                  {['Table', 'Column', 'Issue Type', 'Reason', 'Date'].map(h => (
                                    <th key={h} style={th}>{h}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {filteredAuditRecords.length === 0 ? (
                                  <tr>
                                    <td colSpan={5} style={{ ...td, textAlign: 'center', color: '#888', padding: 16 }}>
                                      No items match this filter
                                    </td>
                                  </tr>
                                ) : filteredAuditRecords.map((item, i) => {
                                  const it = issueTypeLabel(item.issue_type || item.check_type)
                                  return (
                                    <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#fafafa' }}>
                                      <td style={td}><code style={code}>{item.table_name}</code></td>
                                      <td style={td}><code style={code}>{item.column_name || '—'}</code></td>
                                      <td style={td}>
                                        <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10,
                                          background: it.bg, color: it.color, fontWeight: 600 }}>
                                          {it.label}
                                        </span>
                                      </td>
                                      <td style={{ ...td, maxWidth: 250, overflow: 'hidden',
                                        textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {item.reason}
                                      </td>
                                      <td style={{ ...td, whiteSpace: 'nowrap', color: '#888' }}>
                                        {item.check_date ? new Date(item.check_date).toLocaleString() : '—'}
                                      </td>
                                    </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                            <div style={{ fontSize: 10, color: '#888', marginTop: 8 }}>
                              💡 Query full audit log in pgAdmin:
                              <code style={{ ...code, marginLeft: 6 }}>
                                SELECT * FROM {report.audit_table} ORDER BY check_date DESC;
                              </code>
                            </div>
                          </>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </PageBody>
    </>
  )
}

const card        = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 10 }
const errBox      = { background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#991b1b', marginBottom: 10 }
const emptyBox    = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 30, textAlign: 'center', fontSize: 13, color: '#888' }
const btnPrimary  = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhostSmall = { padding: '4px 10px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 10, cursor: 'pointer' }
const tbl         = { width: '100%', borderCollapse: 'collapse', fontSize: 11 }
const th          = { textAlign: 'left', padding: '6px 10px', background: '#f9fafb', borderBottom: '1px solid #e5e7eb', fontWeight: 600, color: '#374151', fontSize: 10 }
const td          = { padding: '7px 10px', borderBottom: '1px solid #f3f4f6', color: '#374151', fontSize: 11 }
const code        = { fontFamily: 'monospace', fontSize: 10, background: '#f3f4f6', padding: '1px 5px', borderRadius: 4, color: '#185FA5' }
