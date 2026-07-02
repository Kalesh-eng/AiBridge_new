/**
 * Login.jsx
 * Login and signup page with logo.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../components/AuthContext'
import { authAPI } from '../api/api'

export default function Login() {
  const [mode, setMode] = useState('login') // login | signup
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const { login } = useAuth()
  const navigate = useNavigate()

  const handle = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      if (mode === 'login') {
        await login(email, password)
        navigate('/')
      } else {
        const res = await authAPI.signup(email, password, name)

        if (res.data.success) {
          setError(
            'Account created! Please check your email to confirm, then log in.'
          )
          setMode('login')
        }
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong')
    }

    setLoading(false)
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f9fafb',
        fontFamily: 'system-ui'
      }}
    >
      <div
        style={{
          width: 360,
          background: '#fff',
          border: '1px solid #e5e7eb',
          borderRadius: 12,
          padding: 32,
          boxShadow: '0 4px 16px rgba(0,0,0,0.05)'
        }}
      >
        {/* Logo Section */}
        <div style={{ textAlign: 'center', marginBottom: 10 }}>
          <img
            src="/AiBridge_logo.png"
            alt="AIBridge Logo"
            style={{
              width: 240,
              height: 360,
              objectFit: 'contain',
              marginBottom: 4,
              background: 'transparent',
              mixBlendMode: 'multiply'
            }}
          />

          <div
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: '#6b7280',
              marginBottom: -10
            }}
          >
                      </div>

          <div
            style={{
              fontSize: 13,
              color: '#6b7280'
            }}
          >
            {mode === 'login'
              ? 'Sign in to your workspace'
              : 'Create your free account'}
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handle}>
          {mode === 'signup' && (
            <div style={{ marginBottom: 14 }}>
              <label style={lbl}>Full name</label>

              <input
                style={inp}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                required
              />
            </div>
          )}

          <div style={{ marginBottom: 14 }}>
            <label style={lbl}>Email</label>

            <input
              style={inp}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              required
            />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={lbl}>Password</label>

            <input
              style={inp}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min 6 characters"
              required
            />
          </div>

          {error && (
            <div
              style={{
                background: '#fef2f2',
                border: '1px solid #fca5a5',
                borderRadius: 6,
                padding: '8px 12px',
                fontSize: 12,
                color: '#991b1b',
                marginBottom: 14
              }}
            >
              {error}
            </div>
          )}

          <button
            style={{
              ...btn,
              background: '#185FA5',
              color: '#fff',
              borderColor: '#185FA5',
              width: '100%'
            }}
            disabled={loading}
          >
            {loading
              ? 'Please wait...'
              : mode === 'login'
              ? 'Sign in'
              : 'Create account'}
          </button>
        </form>

        {/* Footer */}
        <div
          style={{
            textAlign: 'center',
            marginTop: 18,
            fontSize: 12,
            color: '#888'
          }}
        >
          {mode === 'login' ? (
            <>
              Don't have an account?{' '}
              <span
                style={{
                  color: '#185FA5',
                  cursor: 'pointer',
                  fontWeight: 600
                }}
                onClick={() => setMode('signup')}
              >
                Sign up
              </span>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <span
                style={{
                  color: '#185FA5',
                  cursor: 'pointer',
                  fontWeight: 600
                }}
                onClick={() => setMode('login')}
              >
                Sign in
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

const lbl = {
  display: 'block',
  fontSize: 12,
  fontWeight: 500,
  color: '#374151',
  marginBottom: 5
}

const inp = {
  width: '100%',
  padding: '10px 12px',
  fontSize: 13,
  border: '1px solid #d1d5db',
  borderRadius: 6,
  outline: 'none',
  boxSizing: 'border-box'
}

const btn = {
  padding: '10px 18px',
  border: '1px solid #d1d5db',
  borderRadius: 6,
  background: '#fff',
  fontSize: 14,
  cursor: 'pointer',
  fontWeight: 600
}