/**
 * Team.jsx
 * Multi-user workspace management.
 * Invite team members, assign roles, manage access.
 */

import { useState, useEffect } from 'react'
import { useAuth } from '../components/AuthContext'
import { PageHeader, PageBody } from '../components/Layout'
import { Spinner, EmptyState, getErrorMessage } from '../components/ErrorBoundary'
import api from '../api/api'

const ROLES = [
  { value: 'admin',   label: 'Admin',   desc: 'Full access — can manage team and all pipelines',  color: '#185FA5' },
  { value: 'editor',  label: 'Editor',  desc: 'Can create and run pipelines, cannot manage team',  color: '#3B6D11' },
  { value: 'viewer',  label: 'Viewer',  desc: 'Read-only — can view pipelines and charts',          color: '#854F0B' },
]

export default function Team() {
  const { user }     = useAuth()
  const [members,    setMembers]    = useState([])
  const [invites,    setInvites]    = useState([])
  const [loading,    setLoading]    = useState(true)
  const [email,      setEmail]      = useState('')
  const [role,       setRole]       = useState('editor')
  const [inviting,   setInviting]   = useState(false)
  const [error,      setError]      = useState(null)
  const [successMsg, setSuccessMsg] = useState(null)

  useEffect(() => { loadTeam() }, [])

  const loadTeam = async () => {
    try {
      const r = await api.get('/team/members')
      setMembers(r.data.members || [])
      setInvites(r.data.invites  || [])
    } catch (e) {
      // Team endpoint may not exist yet — show empty state
      setMembers([{ id: user?.id, email: user?.email, full_name: user?.full_name, role: 'admin', is_owner: true }])
    } finally {
      setLoading(false)
    }
  }

  const inviteMember = async () => {
    if (!email) { setError('Enter an email address'); return }
    setInviting(true); setError(null)
    try {
      await api.post('/team/invite', { email, role })
      setSuccessMsg(`✓ Invitation sent to ${email}`)
      setEmail('')
      loadTeam()
      setTimeout(() => setSuccessMsg(null), 4000)
    } catch (e) {
      setError(getErrorMessage(e))
    }
    setInviting(false)
  }

  const removeMember = async (memberId, memberEmail) => {
    if (!window.confirm(`Remove ${memberEmail} from the workspace?`)) return
    try {
      await api.delete(`/team/members/${memberId}`)
      loadTeam()
    } catch (e) {
      alert(getErrorMessage(e))
    }
  }

  const updateRole = async (memberId, newRole) => {
    try {
      await api.patch(`/team/members/${memberId}`, { role: newRole })
      loadTeam()
    } catch (e) {
      alert(getErrorMessage(e))
    }
  }

  const cancelInvite = async (inviteId) => {
    try {
      await api.delete(`/team/invites/${inviteId}`)
      loadTeam()
    } catch (e) {
      alert(getErrorMessage(e))
    }
  }

  const roleInfo = (r) => ROLES.find(x => x.value === r) || ROLES[2]

  return (
    <>
      <PageHeader
        title="Team"
        subtitle={`Manage who has access to ${user?.workspace?.name}`}
      />
      <PageBody>

        {successMsg && (
          <div style={{ background: '#EAF3DE', border: '1px solid #a7d9a0', borderRadius: 6, padding: '8px 14px', fontSize: 12, color: '#27500A', marginBottom: 14 }}>
            {successMsg}
          </div>
        )}

        {/* Plan info */}
        <div style={{ background: '#E6F1FB', border: '1px solid #93c5fd', borderRadius: 8, padding: '10px 14px', marginBottom: 18, fontSize: 12, color: '#1e40af' }}>
          <strong>Starter plan</strong> — 1 user included.
          Upgrade to Pro for up to 5 users, or Enterprise for unlimited users.
        </div>

        {/* Invite form */}
        <div style={card}>
          <div style={sectionTitle}>Invite a team member</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <label style={lbl}>Email address</label>
              <input style={inp} type="email" value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="colleague@company.com"
                onKeyDown={e => e.key === 'Enter' && inviteMember()}
              />
            </div>
            <div style={{ width: 140 }}>
              <label style={lbl}>Role</label>
              <select style={inp} value={role} onChange={e => setRole(e.target.value)}>
                {ROLES.map(r => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            <button style={btnPrimary} onClick={inviteMember} disabled={inviting}>
              {inviting ? <><Spinner size={12} color="#fff" /> Sending...</> : 'Send invite'}
            </button>
          </div>

          {/* Role descriptions */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginTop: 12 }}>
            {ROLES.map(r => (
              <div key={r.value} style={{ background: '#f9fafb', borderRadius: 6, padding: '8px 10px', border: role === r.value ? `1.5px solid ${r.color}` : '1px solid #e5e7eb' }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: r.color, marginBottom: 2 }}>{r.label}</div>
                <div style={{ fontSize: 10, color: '#888', lineHeight: 1.4 }}>{r.desc}</div>
              </div>
            ))}
          </div>

          {error && (
            <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '7px 12px', fontSize: 11, color: '#991b1b', marginTop: 10 }}>
              {error}
            </div>
          )}
        </div>

        {/* Current members */}
        <div style={sectionTitle}>Current members ({members.length})</div>

        {loading && <div style={{ display: 'flex', justifyContent: 'center', padding: 30 }}><Spinner /></div>}

        {members.map(m => {
          const ri       = roleInfo(m.role)
          const isMe     = m.email === user?.email
          const isOwner  = m.is_owner || m.role === 'admin'
          return (
            <div key={m.id} style={card}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                {/* Avatar */}
                <div style={{ width: 36, height: 36, borderRadius: '50%', background: ri.color, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 600, flexShrink: 0 }}>
                  {(m.full_name || m.email || '?')[0].toUpperCase()}
                </div>
                {/* Info */}
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#111' }}>
                    {m.full_name || m.email}
                    {isMe && <span style={{ fontSize: 10, color: '#888', marginLeft: 6 }}>(you)</span>}
                  </div>
                  <div style={{ fontSize: 11, color: '#888' }}>{m.email}</div>
                </div>
                {/* Role badge */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {!isMe && !m.is_owner ? (
                    <select
                      style={{ fontSize: 11, border: '1px solid #d1d5db', borderRadius: 5, padding: '3px 7px', color: ri.color, background: '#f9fafb' }}
                      value={m.role}
                      onChange={e => updateRole(m.id, e.target.value)}
                    >
                      {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                  ) : (
                    <span style={{ background: '#f9fafb', border: `1px solid ${ri.color}`, color: ri.color, padding: '3px 9px', borderRadius: 20, fontSize: 10, fontWeight: 500 }}>
                      {ri.label}{m.is_owner ? ' (Owner)' : ''}
                    </span>
                  )}
                  {!isMe && !m.is_owner && (
                    <button style={{ ...btnGhost, fontSize: 10, padding: '3px 9px', color: '#991b1b', borderColor: '#fca5a5' }}
                      onClick={() => removeMember(m.id, m.email)}>
                      Remove
                    </button>
                  )}
                </div>
              </div>
            </div>
          )
        })}

        {/* Pending invites */}
        {invites.length > 0 && (
          <>
            <div style={{ ...sectionTitle, marginTop: 16 }}>
              Pending invitations ({invites.length})
            </div>
            {invites.map(inv => (
              <div key={inv.id} style={{ ...card, opacity: .8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ width: 36, height: 36, borderRadius: '50%', background: '#e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}>
                    ✉
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: '#555' }}>{inv.email}</div>
                    <div style={{ fontSize: 10, color: '#aaa' }}>
                      Invited {new Date(inv.created_at).toLocaleDateString()} · Expires {new Date(inv.expires_at).toLocaleDateString()}
                    </div>
                  </div>
                  <span style={{ background: '#FAEEDA', color: '#854F0B', padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }}>
                    Pending · {roleInfo(inv.role).label}
                  </span>
                  <button style={{ ...btnGhost, fontSize: 10, padding: '3px 9px' }}
                    onClick={() => cancelInvite(inv.id)}>
                    Cancel
                  </button>
                </div>
              </div>
            ))}
          </>
        )}

      </PageBody>
    </>
  )
}

const card        = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 8 }
const sectionTitle= { fontSize: 11, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 10, marginTop: 4 }
const lbl         = { display: 'block', fontSize: 11, fontWeight: 500, color: '#374151', marginBottom: 4 }
const inp         = { width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box' }
const btnPrimary  = { padding: '7px 16px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }
const btnGhost    = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
