/**
 * Layout.jsx — with Approvals + Recovery Agent + Pipeline Logs + Quality + Scheduler + AI Costs
 */

import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'

const NAV = [
  { path: '/',               label: 'Dashboard',           color: '#185FA5', section: 'Main' },
  { path: '/agent',          label: 'ETL Agent',           color: '#534AB7' },
  { path: '/source-target',  label: 'Source → Target',     color: '#185FA5' },
  { path: '/model',          label: 'Data model',          color: '#854F0B' },
  { path: '/mapping',        label: 'ETL mapping',         color: '#0F6E56' },
  { path: '/sql',            label: 'SQL scripts',         color: '#993C1D' },
  { path: '/evolution',      label: 'Schema evolution',    color: '#534AB7' },
  { path: '/plug-and-play',  label: '🔌 Plug & Play',       color: '#0B5D73', section: 'Analytics' },
  { path: '/analytics',      label: 'BI / Analytics',      color: '#3B6D11', section: 'Analytics' },
  { path: '/neon-bi',        label: '⚡ Neon BI',           color: '#00aa88' },
  { path: '/pipelines',      label: 'Pipelines',           color: '#185FA5' },
  { path: '/quality',        label: '✅ Data Quality',     color: '#27500A' },
  { path: '/scheduler',      label: '⏰ Scheduler',        color: '#854F0B' },
  { path: '/cost',           label: '💰 AI Costs',         color: '#854F0B' },
  { path: '/approvals',      label: '👁 Approvals (HIL)',  color: '#854F0B', section: 'Agents' },
  { path: '/logs',           label: '📜 Pipeline Logs',    color: '#185FA5' },
  { path: '/recovery-logs',  label: '🤖 Recovery Agent',   color: '#A32D2D' },
  { path: '/connectors',     label: 'Connectors',          color: '#888780', section: 'Settings' },
  { path: '/team',           label: 'Team',                color: '#185FA5' },
  { path: '/settings',       label: 'AI provider',         color: '#888780' },
]

export default function Layout({ children }) {
  const navigate  = useNavigate()
  const location  = useLocation()
  const { user, logout } = useAuth()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '210px 1fr', height: '100vh', fontFamily: 'system-ui, sans-serif' }}>
      {/* Sidebar */}
      <div style={{ background: '#f9fafb', borderRight: '1px solid #e5e7eb', display: 'flex', flexDirection: 'column', padding: '12px 8px', overflowY: 'auto' }}>
        <div style={{ padding: '6px 8px 14px', borderBottom: '1px solid #e5e7eb', marginBottom: '8px' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#111' }}>AIBridge</div>
          <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>
            {user?.workspace?.name || 'Workspace'}
          </div>
        </div>

        {NAV.map((item) => {
          const active = location.pathname === item.path
          return (
            <div key={item.path}>
              {item.section && (
                <div style={{ fontSize: 9, fontWeight: 600, color: '#aaa', textTransform: 'uppercase', letterSpacing: '.06em', padding: '8px 8px 2px' }}>
                  {item.section}
                </div>
              )}
              <div onClick={() => navigate(item.path)} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 8px', borderRadius: 6, cursor: 'pointer', fontSize: 12, marginBottom: 1, background: active ? '#fff' : 'transparent', color: active ? '#111' : '#555', fontWeight: active ? 600 : 400, border: active ? '1px solid #e5e7eb' : '1px solid transparent', transition: 'all .12s' }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: item.color, flexShrink: 0 }} />
                {item.label}
              </div>
            </div>
          )
        })}

        <div style={{ marginTop: 'auto', padding: '10px 8px', borderTop: '1px solid #e5e7eb' }}>
          <div style={{ fontSize: 11, color: '#555', marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {user?.email}
          </div>
          <div onClick={handleLogout} style={{ fontSize: 11, color: '#888', cursor: 'pointer' }}>
            Sign out
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#fff' }}>
        {children}
      </div>
    </div>
  )
}

export function PageHeader({ title, subtitle, action }) {
  return (
    <div style={{ padding: '14px 20px', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
      <div>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#111' }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{subtitle}</div>}
      </div>
      {action}
    </div>
  )
}

export function PageBody({ children }) {
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
      {children}
    </div>
  )
}
