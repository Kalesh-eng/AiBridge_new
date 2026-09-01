/**
 * Login.jsx — AiBridge Sign In v2
 * Modern split-panel design + Oracle + properly wired to useAuth()
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../components/AuthContext'

export default function Login() {
  const navigate           = useNavigate()
  const { login }          = useAuth()
  const [email,    setEmail]    = useState('')
  const [password, setPassword] = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')

  const handleLogin = async () => {
    if (!email.trim() || !password.trim()) { setError('Please enter email and password'); return }
    setLoading(true); setError('')
    try {
      await login(email, password)
      navigate('/dashboard')
    } catch (e) {
      setError(e.response?.data?.detail || 'Invalid email or password')
    }
    setLoading(false)
  }

  return (
    <div style={styles.page}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&display=swap');
        * { box-sizing: border-box; }
        html, body { margin: 0; padding: 0; }
        .li:focus {
          border-color: #2FD6BE !important;
          background: #fff !important;
          box-shadow: 0 0 0 3px rgba(47,214,190,0.16) !important;
          outline: none;
        }
        .lb:hover:not(:disabled) { background: #182238 !important; }
        .lb:disabled { opacity: 0.6; cursor: not-allowed !important; }
      `}</style>

      {/* ── LEFT: Hero ── */}
      <div style={styles.hero}>
        <div style={styles.brand}>
          <span style={styles.mark}>Ai<span style={{ color: '#2FD6BE' }}>Bridge</span></span>
          <span style={styles.tag}>all the way to AI</span>
        </div>

        <svg viewBox="0 0 520 320" fill="none" xmlns="http://www.w3.org/2000/svg"
          style={{ width: '100%', maxWidth: 560, margin: '20px auto', display: 'block' }}>
          <path id="p1" d="M60,40 C170,40 190,160 300,160"  stroke="rgba(255,255,255,0.16)" strokeWidth="1.5"/>
          <path id="p2" d="M60,100 C150,100 220,150 300,160" stroke="rgba(255,255,255,0.16)" strokeWidth="1.5"/>
          <path id="p3" d="M60,160 C150,160 220,160 300,160" stroke="rgba(255,255,255,0.16)" strokeWidth="1.5"/>
          <path id="p4" d="M60,220 C150,220 220,170 300,160" stroke="rgba(255,255,255,0.16)" strokeWidth="1.5"/>
          <path id="p5" d="M60,280 C170,280 190,160 300,160" stroke="rgba(255,255,255,0.16)" strokeWidth="1.5"/>
          <path id="p6" d="M300,160 C370,160 390,160 450,160" stroke="rgba(255,255,255,0.16)" strokeWidth="1.5"/>

          <circle r="3" fill="#2FD6BE"><animateMotion dur="3.6s" begin="0s"    repeatCount="indefinite"><mpath href="#p1"/></animateMotion></circle>
          <circle r="3" fill="#2FD6BE"><animateMotion dur="3.6s" begin="0.72s" repeatCount="indefinite"><mpath href="#p2"/></animateMotion></circle>
          <circle r="3" fill="#2FD6BE"><animateMotion dur="3.6s" begin="1.44s" repeatCount="indefinite"><mpath href="#p3"/></animateMotion></circle>
          <circle r="3" fill="#2FD6BE"><animateMotion dur="3.6s" begin="2.16s" repeatCount="indefinite"><mpath href="#p4"/></animateMotion></circle>
          <circle r="3" fill="#2FD6BE"><animateMotion dur="3.6s" begin="2.88s" repeatCount="indefinite"><mpath href="#p5"/></animateMotion></circle>
          <circle r="3.5" fill="#fff"><animateMotion dur="1.4s" begin="0s" repeatCount="indefinite"><mpath href="#p6"/></animateMotion></circle>

          {[
            { cx: 60, cy: 40,  label: 'PostgreSQL' },
            { cx: 60, cy: 100, label: 'MySQL'       },
            { cx: 60, cy: 160, label: 'Snowflake'   },
            { cx: 60, cy: 220, label: 'BigQuery'     },
            { cx: 60, cy: 280, label: 'Oracle'       },
          ].map((n, i) => (
            <g key={i}>
              <circle cx={n.cx} cy={n.cy} r="20" fill="#101B2E" stroke="rgba(255,255,255,0.18)"/>
              <text x={n.cx} y={n.cy + 32} textAnchor="middle"
                fontFamily="Inter,sans-serif" fontSize="11" fill="#AEB9C4">{n.label}</text>
            </g>
          ))}

          <circle cx="300" cy="160" r="36" fill="#2FD6BE"/>
          <text x="300" y="166" textAnchor="middle"
            fontFamily="Space Grotesk,sans-serif" fontSize="15" fontWeight="600" fill="#0B1220">AI</text>
          <circle cx="450" cy="160" r="26" fill="#fff"/>
          <text x="450" y="200" textAnchor="middle"
            fontFamily="Inter,sans-serif" fontSize="11" fill="#AEB9C4">Your workspace</text>
        </svg>

        <div style={{ maxWidth: 420 }}>
          <h1 style={styles.heroH1}>Every source, one bridge to AI.</h1>
          <p style={styles.heroP}>
            Connect Postgres, MySQL, Snowflake, Oracle and more —
            AiBridge maps the shortest path from raw data to insight.
          </p>
        </div>
      </div>

      {/* ── RIGHT: Form ── */}
      <div style={styles.panel}>
        <div style={{ width: '100%', maxWidth: 340 }}>
          <h2 style={styles.formH2}>Sign in</h2>
          <p style={{ fontSize: 13.5, color: '#5B6B76', margin: '0 0 32px' }}>
            Welcome back to your workspace.
          </p>

          {error && (
            <div style={{ background: '#FEF2F2', border: '1px solid #FCA5A5', borderRadius: 8,
              padding: '10px 14px', fontSize: 13, color: '#991B1B', marginBottom: 20 }}>
              {error}
            </div>
          )}

          <div style={{ marginBottom: 18 }}>
            <label style={styles.lbl}>Email</label>
            <input className="li" type="text" placeholder="name@company.com"
              value={email} onChange={e => setEmail(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleLogin() }}
              style={styles.input} />
          </div>

          <div style={{ marginBottom: 18 }}>
            <label style={styles.lbl}>Password</label>
            <input className="li" type="password" placeholder="Enter your password"
              value={password} onChange={e => setPassword(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleLogin() }}
              style={styles.input} />
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', margin: '-4px 0 22px' }}>
            <a href="#" style={{ fontSize: 12.5, color: '#5B6B76', textDecoration: 'none' }}>
              Forgot password?
            </a>
          </div>

          <button className="lb" onClick={handleLogin} disabled={loading}
            style={styles.btn}>
            {loading ? 'Signing in...' : 'Sign in'}
          </button>

          <p style={{ marginTop: 20, fontSize: 13.5, color: '#5B6B76', textAlign: 'center' }}>
            Don't have an account?{' '}
            <a href="#" style={{ color: '#2FD6BE', textDecoration: 'none', fontWeight: 500 }}>
              Sign up
            </a>
          </p>
        </div>
      </div>
    </div>
  )
}

const styles = {
  page:   { display: 'flex', width: '100%', minHeight: '100vh', fontFamily: "'Inter',sans-serif" },
  hero:   { flex: 1.35, background: '#0B1220',
            backgroundImage: 'radial-gradient(circle at 15% 10%,#101B2E,transparent 45%)',
            color: '#fff', padding: '56px 60px', display: 'flex', flexDirection: 'column',
            justifyContent: 'space-between', overflow: 'hidden', minHeight: '100vh' },
  brand:  { display: 'flex', alignItems: 'baseline', gap: 10 },
  mark:   { fontFamily: "'Space Grotesk',sans-serif", fontWeight: 700, fontSize: 22 },
  tag:    { fontSize: 13, color: '#AEB9C4' },
  heroH1: { fontFamily: "'Space Grotesk',sans-serif", fontSize: 28, lineHeight: 1.25,
            fontWeight: 600, margin: '0 0 10px', letterSpacing: '-0.01em' },
  heroP:  { fontSize: 14.5, lineHeight: 1.6, color: '#AEB9C4', margin: 0 },
  panel:  { flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 40, minHeight: '100vh', background: '#fff' },
  formH2: { fontFamily: "'Space Grotesk',sans-serif", fontSize: 22, fontWeight: 600,
            margin: '0 0 6px', letterSpacing: '-0.01em', color: '#16202A' },
  lbl:    { display: 'block', fontSize: 13, fontWeight: 500, color: '#16202A', marginBottom: 6 },
  input:  { width: '100%', height: 42, border: '1px solid #E4E9EC', background: '#F5F7F8',
            borderRadius: 8, padding: '0 14px', fontSize: 14, fontFamily: "'Inter',sans-serif",
            color: '#16202A', outline: 'none', transition: 'all .15s ease' },
  btn:    { width: '100%', height: 44, border: 'none', borderRadius: 8, background: '#0B1220',
            color: '#fff', fontFamily: "'Inter',sans-serif", fontSize: 14, fontWeight: 500,
            cursor: 'pointer', transition: 'background .15s ease' },
}
