/**
 * MissionControl.jsx — AI Team Mission Control Dashboard
 * Visual view of all AI agents, their status, tasks, and HIL queue
 */
import { useState, useEffect, useCallback } from 'react'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'

const STATUS_COLORS = {
  online:  { bg: '#DCFCE7', text: '#15803D', dot: '#16A34A' },
  busy:    { bg: '#FEF9C3', text: '#854F0B', dot: '#CA8A04' },
  offline: { bg: '#F3F4F6', text: '#6B7280', dot: '#9CA3AF' },
  error:   { bg: '#FEF2F2', text: '#DC2626', dot: '#DC2626' },
}

const RISK_COLORS = {
  low:      { bg: '#F0FDF4', border: '#BBF7D0', text: '#15803D' },
  medium:   { bg: '#FFFBEB', border: '#FED7AA', text: '#D97706' },
  high:     { bg: '#FEF2F2', border: '#FCA5A5', text: '#DC2626' },
  critical: { bg: '#FFF1F2', border: '#FB7185', text: '#BE123C' },
}

export default function MissionControl() {
  const [agents,      setAgents]      = useState([])
  const [hilQueue,    setHilQueue]    = useState([])
  const [comms,       setComms]       = useState([])
  const [tasks,       setTasks]       = useState([])
  const [view,        setView]        = useState('team') // team | hil | comms | timeline
  const [loading,     setLoading]     = useState(true)
  const [chatAgent,   setChatAgent]   = useState(null)
  const [chatMsg,     setChatMsg]     = useState('')
  const [chatHistory, setChatHistory] = useState([])
  const [chatLoading, setChatLoading] = useState(false)

  const loadData = useCallback(async () => {
    try {
      const [agentsR, hilR, commsR, tasksR] = await Promise.all([
        api.get('/agents/list'),
        api.get('/agents/hil-queue'),
        api.get('/agents/comms'),
        api.get('/agents/tasks'),
      ])
      setAgents(agentsR.data.agents || [])
      setHilQueue(hilR.data.queue || [])
      setComms(commsR.data.comms || [])
      setTasks(tasksR.data.tasks || [])
    } catch(e) {
      console.log('Mission Control load error:', e)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 30000) // refresh every 30s
    return () => clearInterval(interval)
  }, [loadData])

  const approveHIL = async (id, response) => {
    try {
      await api.post('/agents/hil/' + id + '/respond', { response })
      loadData()
    } catch(e) { console.log('HIL response error:', e) }
  }

  const sendChat = async () => {
    if (!chatMsg.trim() || !chatAgent) return
    const userMsg = { role: 'user', content: chatMsg }
    setChatHistory(prev => [...prev, userMsg])
    setChatMsg('')
    setChatLoading(true)
    try {
      const r = await api.post('/agents/chat', {
        agent_id: chatAgent.id,
        message: chatMsg,
        history: chatHistory,
      })
      setChatHistory(prev => [...prev, { role: 'assistant', content: r.data.response, agent: chatAgent.name }])
    } catch(e) {
      setChatHistory(prev => [...prev, { role: 'assistant', content: 'Error: ' + e.message, agent: chatAgent.name }])
    }
    setChatLoading(false)
  }

  const companyAgents  = agents.filter(a => a.layer === 'company')
  const internalAgents = agents.filter(a => a.layer === 'internal')
  const pendingHIL     = hilQueue.filter(h => h.status === 'pending')

  const card = { border:'1px solid #E5E7EB', borderRadius:10, padding:'14px 16px', background:'#fff' }

  return (
    <>
      <PageHeader
        title="🏢 Mission Control"
        subtitle="AI Team — real-time status, HIL approvals, agent communications"
        action={
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            {pendingHIL.length > 0 && (
              <div style={{ background:'#DC2626', color:'#fff', borderRadius:20,
                padding:'4px 12px', fontSize:11, fontWeight:700 }}>
                {pendingHIL.length} pending approval{pendingHIL.length > 1 ? 's' : ''}
              </div>
            )}
            <button onClick={loadData} style={{ fontSize:11, padding:'6px 12px',
              border:'1px solid #E5E7EB', borderRadius:6, background:'#fff',
              cursor:'pointer', color:'#6B7280' }}>↻ Refresh</button>
          </div>
        }
      />
      <PageBody>

        {/* View tabs */}
        <div style={{ display:'flex', gap:4, marginBottom:16,
          borderBottom:'1px solid #E5E7EB', paddingBottom:0 }}>
          {[
            { key:'team',     label:'🏢 Team' },
            { key:'hil',      label:`⏳ HIL Queue ${pendingHIL.length > 0 ? '('+pendingHIL.length+')' : ''}` },
            { key:'comms',    label:'💬 Communications' },
            { key:'timeline', label:'📜 Timeline' },
          ].map(t => (
            <button key={t.key} onClick={() => setView(t.key)} style={{
              padding:'8px 16px', border:'none',
              borderBottom: view===t.key ? '2px solid #185FA5' : '2px solid transparent',
              background:'none', cursor:'pointer', fontSize:12,
              fontWeight: view===t.key ? 700 : 400,
              color: view===t.key ? '#185FA5' : '#6B7280',
            }}>{t.label}</button>
          ))}
        </div>

        {loading && (
          <div style={{ textAlign:'center', padding:'40px', color:'#9CA3AF' }}>
            Loading team status...
          </div>
        )}

        {/* ── TEAM VIEW ── */}
        {!loading && view === 'team' && (
          <div>
            {/* CEO Card */}
            <div style={{ ...card, background:'linear-gradient(135deg, #1e3a5f 0%, #185FA5 100%)',
              color:'#fff', marginBottom:16, display:'flex', alignItems:'center', gap:16 }}>
              <div style={{ fontSize:48 }}>👨‍💼</div>
              <div>
                <div style={{ fontSize:16, fontWeight:700 }}>Kalesh Venna — Founder</div>
                <div style={{ fontSize:12, opacity:0.8, marginTop:2 }}>
                  Senior AI & Data Architect · AIBridge Founder
                </div>
                <div style={{ fontSize:11, opacity:0.7, marginTop:4 }}>
                  All agents report here · HIL approvals required for critical actions
                </div>
              </div>
              <div style={{ marginLeft:'auto', textAlign:'right' }}>
                <div style={{ fontSize:11, opacity:0.8 }}>Pending approvals</div>
                <div style={{ fontSize:32, fontWeight:700 }}>{pendingHIL.length}</div>
              </div>
            </div>

            {/* Company Layer */}
            <div style={{ fontSize:10, fontWeight:700, color:'#6B7280',
              textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>
              🏢 Company Team — Reports to Kalesh
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(220px, 1fr))',
              gap:10, marginBottom:20 }}>
              {companyAgents.map(agent => (
                <AgentCard key={agent.id} agent={agent}
                  onChat={() => { setChatAgent(agent); setChatHistory([]) }} />
              ))}
              {companyAgents.length === 0 && (
                <div style={{ ...card, textAlign:'center', color:'#9CA3AF', padding:'30px' }}>
                  No company agents yet
                </div>
              )}
            </div>

            {/* Internal Layer */}
            <div style={{ fontSize:10, fontWeight:700, color:'#6B7280',
              textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>
              📊 Data Team — Client-facing agents inside AIBridge
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(220px, 1fr))',
              gap:10 }}>
              {internalAgents.map(agent => (
                <AgentCard key={agent.id} agent={agent}
                  onChat={() => { setChatAgent(agent); setChatHistory([]) }} />
              ))}
              {internalAgents.length === 0 && (
                <div style={{ ...card, textAlign:'center', color:'#9CA3AF', padding:'30px' }}>
                  No internal agents yet
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── HIL QUEUE ── */}
        {!loading && view === 'hil' && (
          <div>
            {hilQueue.length === 0 ? (
              <div style={{ ...card, textAlign:'center', padding:'40px' }}>
                <div style={{ fontSize:32, marginBottom:12 }}>✅</div>
                <div style={{ fontSize:14, fontWeight:600, color:'#374151' }}>
                  No pending approvals
                </div>
                <div style={{ fontSize:12, color:'#9CA3AF', marginTop:4 }}>
                  All agents are operating within approved boundaries
                </div>
              </div>
            ) : (
              hilQueue.map(item => (
                <div key={item.id} style={{
                  ...card, marginBottom:10,
                  borderLeft: `4px solid ${RISK_COLORS[item.risk_level]?.dot || '#D97706'}`,
                  background: RISK_COLORS[item.risk_level]?.bg || '#FFFBEB',
                }}>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start' }}>
                    <div style={{ flex:1 }}>
                      <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:6 }}>
                        <span style={{ fontSize:11, fontWeight:700,
                          color: RISK_COLORS[item.risk_level]?.text,
                          padding:'2px 8px', borderRadius:10,
                          background: item.status==='pending' ? '#FEF9C3' : '#F0FDF4',
                          border: '1px solid ' + (RISK_COLORS[item.risk_level]?.border || '#FED7AA') }}>
                          {item.risk_level?.toUpperCase()} RISK
                        </span>
                        <span style={{ fontSize:11, color:'#6B7280' }}>
                          {item.agent_name}
                        </span>
                        <span style={{ fontSize:10, color:'#9CA3AF', marginLeft:'auto' }}>
                          {new Date(item.created_at).toLocaleTimeString()}
                        </span>
                      </div>
                      <div style={{ fontSize:13, fontWeight:600, color:'#111', marginBottom:6 }}>
                        {item.title}
                      </div>
                      <div style={{ fontSize:11, color:'#374151', marginBottom:10 }}>
                        {item.description}
                      </div>
                      {item.status === 'pending' ? (
                        <div style={{ display:'flex', gap:8 }}>
                          <button onClick={() => approveHIL(item.id, 'approved')}
                            style={{ padding:'6px 16px', background:'#15803D', color:'#fff',
                              border:'none', borderRadius:6, fontSize:11, cursor:'pointer',
                              fontWeight:600 }}>✅ Approve</button>
                          <button onClick={() => approveHIL(item.id, 'rejected')}
                            style={{ padding:'6px 14px', background:'#fff', color:'#DC2626',
                              border:'1px solid #DC2626', borderRadius:6, fontSize:11,
                              cursor:'pointer' }}>❌ Reject</button>
                          <button style={{ padding:'6px 12px', background:'#fff', color:'#185FA5',
                            border:'1px solid #185FA5', borderRadius:6, fontSize:11,
                            cursor:'pointer' }}>👁 View Details</button>
                        </div>
                      ) : (
                        <div style={{ fontSize:11, fontWeight:600,
                          color: item.status==='approved' ? '#15803D' : '#DC2626' }}>
                          {item.status === 'approved' ? '✅ Approved' : '❌ Rejected'}
                          {item.responded_at && ` · ${new Date(item.responded_at).toLocaleString()}`}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* ── COMMUNICATIONS ── */}
        {!loading && view === 'comms' && (
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            {/* Recent comms */}
            <div>
              <div style={{ fontSize:10, fontWeight:700, color:'#6B7280',
                textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>
                Recent Messages
              </div>
              {comms.length === 0 ? (
                <div style={{ ...card, textAlign:'center', padding:'30px', color:'#9CA3AF' }}>
                  No messages yet
                </div>
              ) : (
                comms.map((c, i) => (
                  <div key={i} style={{ ...card, marginBottom:8 }}>
                    <div style={{ display:'flex', gap:8, alignItems:'center', marginBottom:4 }}>
                      <span style={{ fontSize:11, fontWeight:600, color:'#185FA5' }}>{c.from_agent}</span>
                      <span style={{ fontSize:10, color:'#9CA3AF' }}>→</span>
                      <span style={{ fontSize:11, fontWeight:600, color:'#374151' }}>{c.to_agent}</span>
                      <span style={{ fontSize:10, color:'#9CA3AF', marginLeft:'auto' }}>
                        {new Date(c.created_at).toLocaleTimeString()}
                      </span>
                    </div>
                    <div style={{ fontSize:11, color:'#374151' }}>{c.message}</div>
                  </div>
                ))
              )}
            </div>

            {/* Chat with agent */}
            <div>
              <div style={{ fontSize:10, fontWeight:700, color:'#6B7280',
                textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>
                Chat with Agent
              </div>
              <div style={{ ...card }}>
                {!chatAgent ? (
                  <div>
                    <div style={{ fontSize:12, color:'#6B7280', marginBottom:12 }}>
                      Select an agent to chat:
                    </div>
                    <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
                      {agents.map(a => (
                        <button key={a.id} onClick={() => { setChatAgent(a); setChatHistory([]) }}
                          style={{ fontSize:11, padding:'5px 12px', borderRadius:20,
                            border:'1px solid #E5E7EB', background:'#F9FAFB',
                            cursor:'pointer' }}>
                          {a.emoji} {a.name}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div>
                    <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:12 }}>
                      <span style={{ fontSize:20 }}>{chatAgent.emoji}</span>
                      <div>
                        <div style={{ fontSize:12, fontWeight:700 }}>{chatAgent.name}</div>
                        <div style={{ fontSize:10, color:'#6B7280' }}>{chatAgent.role}</div>
                      </div>
                      <button onClick={() => setChatAgent(null)}
                        style={{ marginLeft:'auto', fontSize:10, padding:'2px 8px',
                          border:'1px solid #E5E7EB', borderRadius:4, background:'#fff',
                          cursor:'pointer', color:'#9CA3AF' }}>← Back</button>
                    </div>
                    <div style={{ height:200, overflowY:'auto', marginBottom:10,
                      border:'1px solid #E5E7EB', borderRadius:6, padding:10 }}>
                      {chatHistory.length === 0 && (
                        <div style={{ fontSize:11, color:'#9CA3AF', fontStyle:'italic' }}>
                          {chatAgent.personality}
                        </div>
                      )}
                      {chatHistory.map((m, i) => (
                        <div key={i} style={{ marginBottom:8,
                          textAlign: m.role==='user' ? 'right' : 'left' }}>
                          <div style={{ display:'inline-block', maxWidth:'85%',
                            padding:'6px 10px', borderRadius:8, fontSize:11,
                            background: m.role==='user' ? '#185FA5' : '#F3F4F6',
                            color: m.role==='user' ? '#fff' : '#374151' }}>
                            {m.role === 'assistant' && (
                              <div style={{ fontSize:9, fontWeight:700,
                                marginBottom:2, opacity:0.7 }}>{m.agent}</div>
                            )}
                            {m.content}
                          </div>
                        </div>
                      ))}
                      {chatLoading && (
                        <div style={{ fontSize:11, color:'#9CA3AF', fontStyle:'italic' }}>
                          {chatAgent.name} is typing...
                        </div>
                      )}
                    </div>
                    <div style={{ display:'flex', gap:6 }}>
                      <input value={chatMsg} onChange={e => setChatMsg(e.target.value)}
                        onKeyDown={e => e.key==='Enter' && sendChat()}
                        placeholder={`Message ${chatAgent.name}...`}
                        style={{ flex:1, padding:'7px 10px', fontSize:11,
                          border:'1px solid #D1D5DB', borderRadius:6 }} />
                      <button onClick={sendChat} disabled={chatLoading}
                        style={{ padding:'7px 14px', background:'#185FA5', color:'#fff',
                          border:'none', borderRadius:6, fontSize:11, cursor:'pointer',
                          fontWeight:600 }}>Send</button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── TIMELINE ── */}
        {!loading && view === 'timeline' && (
          <div>
            <div style={{ fontSize:10, fontWeight:700, color:'#6B7280',
              textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:12 }}>
              Today's Activity Timeline
            </div>
            {tasks.length === 0 ? (
              <div style={{ ...card, textAlign:'center', padding:'40px', color:'#9CA3AF' }}>
                No activity today yet
              </div>
            ) : (
              <div style={{ position:'relative', paddingLeft:24 }}>
                <div style={{ position:'absolute', left:8, top:0, bottom:0,
                  width:2, background:'#E5E7EB' }} />
                {tasks.map((t, i) => (
                  <div key={i} style={{ position:'relative', marginBottom:16 }}>
                    <div style={{ position:'absolute', left:-20, top:4,
                      width:10, height:10, borderRadius:'50%',
                      background: t.status==='done' ? '#16A34A' : t.status==='failed' ? '#DC2626' : '#CA8A04',
                      border:'2px solid #fff', boxShadow:'0 0 0 2px #E5E7EB' }} />
                    <div style={{ ...card, marginLeft:8 }}>
                      <div style={{ display:'flex', justifyContent:'space-between',
                        alignItems:'center', marginBottom:4 }}>
                        <span style={{ fontSize:11, fontWeight:700, color:'#374151' }}>
                          {t.agent_name} — {t.task_type}
                        </span>
                        <span style={{ fontSize:10, color:'#9CA3AF' }}>
                          {new Date(t.created_at).toLocaleTimeString()}
                        </span>
                      </div>
                      <div style={{ fontSize:11, color:'#6B7280' }}>{t.description}</div>
                      {t.hil_required && (
                        <div style={{ fontSize:10, marginTop:4,
                          color: t.hil_approved ? '#15803D' : '#D97706' }}>
                          {t.hil_approved ? '✅ HIL Approved' : '⏳ Awaiting HIL Approval'}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

      </PageBody>
    </>
  )
}

function AgentCard({ agent, onChat }) {
  const sc = STATUS_COLORS[agent.status] || STATUS_COLORS.online

  return (
    <div style={{ border:'1px solid #E5E7EB', borderRadius:10, padding:'14px',
      background:'#fff', display:'flex', flexDirection:'column', gap:8 }}>
      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', gap:10 }}>
        <div style={{ fontSize:28 }}>{agent.emoji}</div>
        <div style={{ flex:1 }}>
          <div style={{ fontSize:12, fontWeight:700, color:'#111' }}>{agent.name}</div>
          <div style={{ fontSize:10, color:'#6B7280' }}>{agent.role}</div>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:4,
          padding:'2px 8px', borderRadius:20,
          background: sc.bg }}>
          <div style={{ width:6, height:6, borderRadius:'50%', background: sc.dot }} />
          <span style={{ fontSize:9, fontWeight:700, color: sc.text,
            textTransform:'uppercase' }}>{agent.status}</span>
        </div>
      </div>

      {/* Current task */}
      <div style={{ fontSize:11, color:'#6B7280', fontStyle:'italic',
        minHeight:16 }}>
        {agent.current_task || 'Waiting for tasks...'}
      </div>

      {/* Stats */}
      <div style={{ display:'flex', gap:12 }}>
        <div style={{ textAlign:'center' }}>
          <div style={{ fontSize:16, fontWeight:700, color:'#185FA5' }}>
            {agent.tasks_today || 0}
          </div>
          <div style={{ fontSize:9, color:'#9CA3AF', textTransform:'uppercase' }}>Today</div>
        </div>
        <div style={{ textAlign:'center' }}>
          <div style={{ fontSize:16, fontWeight:700, color:'#374151' }}>
            {agent.tasks_total || 0}
          </div>
          <div style={{ fontSize:9, color:'#9CA3AF', textTransform:'uppercase' }}>Total</div>
        </div>
        <div style={{ marginLeft:'auto' }}>
          <div style={{ fontSize:10, color:'#9CA3AF' }}>
            {agent.last_active ? new Date(agent.last_active).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '--'}
          </div>
          <div style={{ fontSize:9, color:'#9CA3AF', textTransform:'uppercase' }}>Last active</div>
        </div>
      </div>

      {/* Capabilities */}
      <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
        {(agent.capabilities || []).slice(0, 3).map((cap, i) => (
          <span key={i} style={{ fontSize:9, padding:'2px 6px', borderRadius:8,
            background:'#F3F4F6', color:'#6B7280' }}>
            {cap.replace(/_/g, ' ')}
          </span>
        ))}
        {(agent.capabilities || []).length > 3 && (
          <span style={{ fontSize:9, padding:'2px 6px', borderRadius:8,
            background:'#F3F4F6', color:'#9CA3AF' }}>
            +{agent.capabilities.length - 3} more
          </span>
        )}
      </div>

      {/* Actions */}
      <button onClick={onChat}
        style={{ padding:'6px', background:'#EBF4FF', color:'#185FA5',
          border:'1px solid #BFDBFE', borderRadius:6, fontSize:11,
          cursor:'pointer', fontWeight:600 }}>
        💬 Chat with {agent.name.split(' ')[0]}
      </button>
    </div>
  )
}

