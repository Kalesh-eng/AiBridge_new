/**
 * Approvals.jsx
 * Shows the approval queue — all HIL approvals (pending + history).
 * Lets user review what AI has been doing.
 */

import { useState, useEffect } from 'react'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'

export default function Approvals() {
  const [loading,  setLoading]  = useState(true)
  const [approvals, setApprovals] = useState([])
  const [tab,       setTab]       = useState('pending')
  const [selected,  setSelected]  = useState(null)
  const [detail,    setDetail]    = useState(null)

  useEffect(() => {
    loadApprovals()
  }, [tab])

  const loadApprovals = async () => {
    setLoading(true)
    try {
      const url = tab === 'pending' ? '/approvals/pending' : '/approvals/history'
      const r = await api.get(url)
      setApprovals(r.data.approvals || [])
    } catch (e) {
      console.error(e)
    }
    setLoading(false)
  }

  const openDetail = async (id) => {
    setSelected(id); setDetail(null)
    try {
      const r = await api.get(`/approvals/${id}`)
      setDetail(r.data)
    } catch (e) {
      setDetail({ error: 'Failed to load' })
    }
  }

  const statusColor = {
    pending:  { bg: '#FAEEDA', fg: '#854F0B' },
    approved: { bg: '#EAF3DE', fg: '#3B6D11' },
    rejected: { bg: '#FCEBEB', fg: '#A32D2D' },
    edited:   { bg: '#E6F1FB', fg: '#185FA5' },
    expired:  { bg: '#f3f4f6', fg: '#888' }
  }

  const riskColor = {
    low:    { bg: '#EAF3DE', fg: '#3B6D11' },
    medium: { bg: '#FAEEDA', fg: '#854F0B' },
    high:   { bg: '#FCEBEB', fg: '#A32D2D' }
  }

  return (
    <>
      <PageHeader
        title="Approval Queue"
        subtitle="Review and approve AI decisions — Human-in-the-Loop"
      />
      <PageBody>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 14, borderBottom: '1px solid #e5e7eb' }}>
          {['pending', 'history'].map(t => (
            <button key={t} onClick={() => setTab(t)}
              style={{
                padding: '8px 14px', background: 'none', border: 'none',
                fontSize: 12, cursor: 'pointer',
                color: tab === t ? '#185FA5' : '#888',
                fontWeight: tab === t ? 600 : 400,
                borderBottom: tab === t ? '2px solid #185FA5' : '2px solid transparent',
                marginBottom: -1
              }}>
              {t === 'pending' ? '⏳ Pending' : '📋 History'} ({tab === t ? approvals.length : ''})
            </button>
          ))}
        </div>

        {loading && (
          <div style={{ textAlign: 'center', padding: 40, color: '#888', fontSize: 12 }}>
            Loading...
          </div>
        )}

        {!loading && approvals.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <div style={{ fontSize: 32 }}>👁</div>
            <div style={{ fontSize: 13, fontWeight: 600, marginTop: 8 }}>
              {tab === 'pending' ? 'No pending approvals' : 'No approval history'}
            </div>
            <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
              When you run a pipeline with HIL enabled, approval requests will appear here.
            </div>
          </div>
        )}

        {!loading && approvals.map(a => (
          <div key={a.id}
            style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px',
                     marginBottom: 8, cursor: 'pointer',
                     borderLeft: `3px solid ${riskColor[a.risk_level]?.fg || '#888'}` }}
            onClick={() => openDetail(a.id)}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <span style={{ fontSize: 16 }}>
                {a.approval_type === 'data_model'  ? '🏗️' :
                 a.approval_type === 'sql_scripts' ? '⚙️' :
                 a.approval_type === 'recovery_fix'? '🤖' : '📋'}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{a.title}</div>
                <div style={{ fontSize: 11, color: '#888' }}>{a.description}</div>
              </div>
              <span style={{
                padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500,
                background: statusColor[a.status]?.bg, color: statusColor[a.status]?.fg
              }}>
                {a.status}
              </span>
              <span style={{
                padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500,
                background: riskColor[a.risk_level]?.bg, color: riskColor[a.risk_level]?.fg
              }}>
                {a.risk_level} risk
              </span>
            </div>
            <div style={{ fontSize: 10, color: '#aaa', marginTop: 4 }}>
              {new Date(a.created_at).toLocaleString()}
              {a.decided_at && ` · decided ${new Date(a.decided_at).toLocaleString()}`}
            </div>
            {a.comments && (
              <div style={{ fontSize: 11, color: '#555', marginTop: 6, fontStyle: 'italic',
                            background: '#f9fafb', padding: 6, borderRadius: 4 }}>
                💬 {a.comments}
              </div>
            )}
          </div>
        ))}

        {/* Detail modal */}
        {selected && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}
               onClick={() => setSelected(null)}>
            <div style={{ background: '#fff', borderRadius: 10, padding: 20, width: 720,
                          maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(0,0,0,0.2)' }}
                 onClick={e => e.stopPropagation()}>
              <div style={{ display: 'flex', justifyContent: 'space-between',
                            alignItems: 'center', marginBottom: 14 }}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>Approval Details</div>
                <button onClick={() => setSelected(null)}
                  style={{ padding: '5px 12px', background: '#fff',
                           border: '1px solid #d1d5db', borderRadius: 6,
                           fontSize: 11, cursor: 'pointer' }}>
                  Close
                </button>
              </div>

              {!detail ? <div>Loading...</div> :
               detail.error ? <div style={{ color: 'red' }}>{detail.error}</div> :
               <>
                <div style={{ fontSize: 12, marginBottom: 10 }}>
                  <strong>Type:</strong> {detail.approval_type}<br />
                  <strong>Status:</strong> {detail.status}<br />
                  <strong>Risk:</strong> {detail.risk_level}<br />
                  <strong>Created:</strong> {new Date(detail.created_at).toLocaleString()}
                </div>

                <div style={{ fontSize: 12, fontWeight: 600, marginTop: 12, marginBottom: 6 }}>
                  Description
                </div>
                <div style={{ fontSize: 11, color: '#555' }}>{detail.description}</div>

                <div style={{ fontSize: 12, fontWeight: 600, marginTop: 12, marginBottom: 6 }}>
                  Proposed data
                </div>
                <pre style={{ background: '#1e1e1e', color: '#d4d4d4', padding: 10,
                              borderRadius: 6, fontSize: 9, overflowX: 'auto',
                              maxHeight: 300, lineHeight: 1.4 }}>
                  {JSON.stringify(detail.proposed_data, null, 2)}
                </pre>

                {detail.edited_data && (
                  <>
                    <div style={{ fontSize: 12, fontWeight: 600, marginTop: 12, marginBottom: 6 }}>
                      User edits
                    </div>
                    <pre style={{ background: '#1e1e1e', color: '#a7d9a0', padding: 10,
                                  borderRadius: 6, fontSize: 9, overflowX: 'auto',
                                  maxHeight: 200, lineHeight: 1.4 }}>
                      {JSON.stringify(detail.edited_data, null, 2)}
                    </pre>
                  </>
                )}

                {detail.comments && (
                  <>
                    <div style={{ fontSize: 12, fontWeight: 600, marginTop: 12, marginBottom: 6 }}>
                      User comments
                    </div>
                    <div style={{ fontSize: 11, color: '#555', background: '#f9fafb',
                                  padding: 8, borderRadius: 4 }}>
                      {detail.comments}
                    </div>
                  </>
                )}
               </>
              }
            </div>
          </div>
        )}

      </PageBody>
    </>
  )
}
