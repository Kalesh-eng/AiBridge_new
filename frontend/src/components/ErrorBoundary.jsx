/**
 * ErrorBoundary.jsx
 * Global error boundary — catches any React crash and shows friendly message.
 * 
 * Toast.jsx
 * Global toast notification system for success/error/info messages.
 */

import { Component, createContext, useContext, useState, useCallback } from 'react'

// ── Error Boundary ────────────────────────────────────────────────────────────

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('AIBridge error:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, fontFamily: 'system-ui', textAlign: 'center', maxWidth: 500, margin: '60px auto' }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
          <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8, color: '#111' }}>
            Something went wrong
          </h2>
          <p style={{ fontSize: 13, color: '#888', lineHeight: 1.6, marginBottom: 20 }}>
            AIBridge encountered an unexpected error. This has been logged.
            Try refreshing the page.
          </p>
          <div style={{ background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6, padding: '10px 14px', fontSize: 11, fontFamily: 'monospace', color: '#555', textAlign: 'left', marginBottom: 20 }}>
            {this.state.error?.message || 'Unknown error'}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{ padding: '8px 20px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
            Refresh page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}


// ── Toast context ─────────────────────────────────────────────────────────────

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const addToast = useCallback((message, type = 'info', duration = 4000) => {
    const id = Date.now()
    setToasts(prev => [...prev, { id, message, type }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, duration)
  }, [])

  const removeToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }

  const colors = {
    success: { bg: '#EAF3DE', border: '#a7d9a0', color: '#27500A', icon: '✓' },
    error:   { bg: '#fef2f2', border: '#fca5a5', color: '#991b1b', icon: '✗' },
    info:    { bg: '#E6F1FB', border: '#93c5fd', color: '#1e40af', icon: 'ℹ' },
    warning: { bg: '#FAEEDA', border: '#fcd34d', color: '#92400e', icon: '!' },
  }

  return (
    <ToastContext.Provider value={{ toast: addToast }}>
      {children}
      {/* Toast container */}
      <div style={{ position: 'fixed', bottom: 20, right: 20, zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 360 }}>
        {toasts.map(t => {
          const c = colors[t.type] || colors.info
          return (
            <div key={t.id} style={{ background: c.bg, border: `1px solid ${c.border}`, borderRadius: 8, padding: '10px 14px', display: 'flex', alignItems: 'flex-start', gap: 8, boxShadow: '0 4px 12px rgba(0,0,0,.1)', animation: 'slideIn .2s ease', fontFamily: 'system-ui' }}>
              <span style={{ color: c.color, fontWeight: 700, flexShrink: 0, fontSize: 14 }}>{c.icon}</span>
              <span style={{ fontSize: 12, color: c.color, flex: 1, lineHeight: 1.5 }}>{t.message}</span>
              <button onClick={() => removeToast(t.id)} style={{ background: 'none', border: 'none', color: c.color, cursor: 'pointer', fontSize: 14, opacity: .6, flexShrink: 0, padding: 0 }}>✕</button>
            </div>
          )
        })}
      </div>
      <style>{`@keyframes slideIn { from { opacity:0; transform:translateX(20px) } to { opacity:1; transform:translateX(0) } }`}</style>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside ToastProvider')
  return ctx.toast
}


// ── API Error handler ─────────────────────────────────────────────────────────

export function getErrorMessage(error) {
  /**
   * Convert any API error into a friendly user-facing message.
   */
  if (!error) return 'An unknown error occurred'

  const detail = error.response?.data?.detail

  if (typeof detail === 'string') {
    // Map common backend errors to friendly messages
    const map = {
      'Not authenticated':            'Your session has expired. Please log in again.',
      'Invalid or expired token':     'Your session has expired. Please log in again.',
      'Email already registered':     'This email is already registered. Try logging in.',
      'Invalid email or password':    'Incorrect email or password. Please try again.',
      'Connector not found':          'Database connection not found. Please check your connectors.',
      'Pipeline not found':           'Pipeline not found. It may have been deleted.',
      'No connector linked':          'No database connected. Please save the pipeline with a connector selected.',
      'Connection refused':           'Cannot connect to database. Check if the server is running.',
      'password authentication failed':'Wrong database password. Check your connector settings.',
      'getaddrinfo failed':           'Cannot find database server. Check the host address.',
    }
    for (const [key, msg] of Object.entries(map)) {
      if (detail.includes(key)) return msg
    }
    return detail
  }

  if (error.message === 'Network Error') {
    return 'Cannot reach AIBridge server. Make sure the backend is running on port 8888.'
  }

  return error.message || 'Something went wrong. Please try again.'
}


// ── Loading spinner ───────────────────────────────────────────────────────────

export function Spinner({ size = 20, color = '#185FA5' }) {
  return (
    <div style={{ display: 'inline-block', width: size, height: size }}>
      <svg viewBox="0 0 24 24" fill="none" style={{ animation: 'spin 1s linear infinite', width: size, height: size }}>
        <circle cx="12" cy="12" r="10" stroke={color} strokeWidth="3" opacity=".2" />
        <path d="M12 2a10 10 0 0 1 10 10" stroke={color} strokeWidth="3" strokeLinecap="round" />
      </svg>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}


// ── Empty state ───────────────────────────────────────────────────────────────

export function EmptyState({ icon = '📭', title, message, action, actionLabel }) {
  return (
    <div style={{ textAlign: 'center', padding: '40px 20px', fontFamily: 'system-ui' }}>
      <div style={{ fontSize: 48, marginBottom: 12 }}>{icon}</div>
      <div style={{ fontSize: 15, fontWeight: 600, color: '#111', marginBottom: 6 }}>{title}</div>
      {message && <div style={{ fontSize: 13, color: '#888', lineHeight: 1.6, marginBottom: 16, maxWidth: 360, margin: '0 auto 16px' }}>{message}</div>}
      {action && (
        <button onClick={action} style={{ padding: '8px 18px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 12, cursor: 'pointer', fontWeight: 500 }}>
          {actionLabel}
        </button>
      )}
    </div>
  )
}
