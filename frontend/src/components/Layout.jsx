/**
 * Layout.jsx — with tooltips on nav items + Help button
 */

import { useState, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'

const NAV = [
  { path: '/',               label: 'Dashboard',          color: '#185FA5', section: 'Main',      tip: 'Overview of your pipelines, recent runs, and system status' },
  { path: '/agent',          label: 'ETL Agent',          color: '#534AB7',                        tip: 'AI-powered pipeline designer — describe your data, get a full star schema and SQL automatically' },
  { path: '/source-target',  label: 'Source → Target',    color: '#185FA5',                        tip: 'Configure which connector is the data source and which is the warehouse target' },
  { path: '/model',          label: 'Data model',         color: '#854F0B',                        tip: 'View and edit the AI-generated star schema (fact tables + dimension tables)' },
  { path: '/mapping',        label: 'ETL mapping',        color: '#0F6E56',                        tip: 'Column-level mappings showing how source fields map to warehouse columns' },
  { path: '/sql',            label: 'SQL scripts',        color: '#993C1D',                        tip: 'View, edit, and validate the generated SQL scripts before execution' },
  { path: '/evolution',      label: 'Schema evolution',   color: '#534AB7',                        tip: 'AI-assisted schema migration — safely add or modify columns in existing warehouse tables' },
  { path: '/analytics',      label: 'BI / Analytics',     color: '#3B6D11', section: 'Analytics',  tip: 'Ask questions about your warehouse data in plain English — get SQL and charts instantly' },
  { path: '/pipelines',      label: 'Pipelines',          color: '#185FA5',                        tip: 'Manage all pipelines — execute, schedule, view run history, compare versions' },
  { path: '/quality',        label: '✅ Data Quality',    color: '#27500A',                        tip: 'Data quality scores, null checks, duplicate detection, and audit log of quarantined rows' },
  { path: '/scheduler',      label: '⏰ Scheduler',       color: '#854F0B',                        tip: 'Schedule pipelines and reports to run automatically on a time-based cadence' },
  { path: '/cost',           label: '💰 AI Costs',        color: '#854F0B',                        tip: 'Track AI API usage and cost per pipeline run, with peak vs off-peak pricing breakdown' },
  { path: '/approvals',      label: '👁 Approvals (HIL)', color: '#854F0B', section: 'Agents',     tip: 'Human-in-the-Loop review queue — approve or reject AI-generated data models and SQL' },
  { path: '/logs',           label: '📜 Pipeline Logs',   color: '#185FA5',                        tip: 'Full execution logs for every pipeline run — filter, search, and diagnose issues' },
  { path: '/recovery-logs',  label: '🤖 Recovery Agent',  color: '#A32D2D',                        tip: 'Auto-recovery history — see which failed scripts the AI fixed and how' },
  { path: '/connectors',     label: 'Connectors',         color: '#888780', section: 'Settings',   tip: 'Manage database connections and file uploads (CSV/Excel)' },
  { path: '/team',           label: 'Team',               color: '#185FA5',                        tip: 'Invite team members and manage workspace access' },
  { path: '/settings',       label: 'AI provider',        color: '#888780',                        tip: 'Switch AI provider (DeepSeek, OpenAI, Claude, Ollama for on-premises)' },
  { path: '/help',           label: '❓ Help & Docs',     color: '#534AB7', section: 'Help',       tip: 'Full documentation, getting-started guide, and feature reference' },
]

function NavTooltip({ text, children }) {
  const [pos, setPos] = useState(null)
  const timer = useRef(null)

  const show = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    timer.current = setTimeout(() => setPos({
      top: rect.top + rect.height / 2,
      left: rect.right + 10
    }), 200)
  }

  const hide = () => {
    clearTimeout(timer.current)
    setPos(null)
  }

  return (
    <div onMouseEnter={show} onMouseLeave={hide}>
      {children}
      {pos && text && (
        <div style={{
          position: 'fixed',
          top: pos.top,
          left: pos.left,
          transform: 'translateY(-50%)',
          zIndex: 99999,
          pointerEvents: 'none',
          background: '#1e293b',
          color: '#fff',
          fontSize: 11,
          padding: '6px 10px',
          borderRadius: 5,
          width: 210,
          lineHeight: 1.5,
          boxShadow: '0 4px 12px rgba(0,0,0,.3)',
        }}>
          <div style={{
            position: 'absolute',
            right: '100%',
            top: '50%',
            transform: 'translateY(-50%)',
            width: 0, height: 0,
            border: '5px solid transparent',
            borderRightColor: '#1e293b'
          }} />
          {text}
        </div>
      )}
    </div>
  )
}

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
              <NavTooltip text={item.tip}>
                <div onClick={() => navigate(item.path)} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 8px', borderRadius: 6, cursor: 'pointer', fontSize: 12, marginBottom: 1, background: active ? '#fff' : 'transparent', color: active ? '#111' : '#555', fontWeight: active ? 600 : 400, border: active ? '1px solid #e5e7eb' : '1px solid transparent', transition: 'all .12s' }}>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: item.color, flexShrink: 0 }} />
                  {item.label}
                </div>
              </NavTooltip>
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
  const navigate = useNavigate()
  return (
    <div style={{ padding: '14px 20px', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
      <div>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#111' }}>{title}</div>
        {subtitle && <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{subtitle}</div>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {action}
        <div onClick={() => navigate('/help')} title="Help & Documentation" style={{ width: 28, height: 28, borderRadius: '50%', border: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: 13, color: '#888', fontWeight: 600, background: '#f9fafb', flexShrink: 0 }}>
          ?
        </div>
      </div>
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

export { NavTooltip }
