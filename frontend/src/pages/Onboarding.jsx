/**
 * Onboarding.jsx
 * 4-step first-run wizard shown to new users.
 * Guides: Connect DB → Run Agent → Execute → Analyse
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/api'

export default function Onboarding({ onComplete }) {
  const navigate = useNavigate()
  const [step,    setStep]    = useState(0)
  const [config,  setConfig]  = useState({
    name: 'My Database', connector_type: 'postgres',
    host: 'localhost', port: 5433,
    database_name: 'postgres', username: 'postgres',
    password: '', role: 'both'
  })
  const [testing,  setTesting]  = useState(false)
  const [testResult,setTestResult]=useState(null)
  const [saving,   setSaving]   = useState(false)
  const [skipped,  setSkipped]  = useState(false)

  const STEPS = [
    { title: 'Welcome to AIBridge',         icon: '🚀' },
    { title: 'Connect your database',        icon: '🔌' },
    { title: 'How AIBridge works',           icon: '⚙️' },
    { title: 'You are ready to go',          icon: '✓'  },
  ]

  const DB_TYPES = [
    { value: 'postgres',  label: 'PostgreSQL',  icon: '🐘', category: 'On-Prem' },
    { value: 'mysql',     label: 'MySQL',        icon: '🐬', category: 'On-Prem' },
    { value: 'sqlserver', label: 'SQL Server',   icon: '🪟', category: 'On-Prem' },
    { value: 'oracle',    label: 'Oracle',       icon: '🔴', category: 'On-Prem' },
    { value: 'sqlite',    label: 'SQLite',       icon: '📁', category: 'On-Prem' },
    { value: 'snowflake', label: 'Snowflake',    icon: '❄️', category: 'Cloud'   },
    { value: 'bigquery',  label: 'BigQuery',     icon: '☁️', category: 'Cloud'   },
    { value: 'redshift',  label: 'Redshift',     icon: '🔴', category: 'Cloud'   },
    { value: 'azuresql',  label: 'Azure SQL',    icon: '🔷', category: 'Cloud'   },
  ]

  const defaultPorts = {
    postgres: 5432, mysql: 3306, sqlserver: 1433,
    oracle: 1521, snowflake: 443, redshift: 5439, azuresql: 1433
  }

  const testConnection = async () => {
    setTesting(true); setTestResult(null)
    try {
      const r = await api.post('/connector/postgres/test', {
        host: config.host, port: config.port,
        database: config.database_name,
        username: config.username, password: config.password
      })
      setTestResult({ ok: r.data.success, msg: r.data.message })
    } catch (e) {
      setTestResult({ ok: false, msg: e.response?.data?.detail || e.message })
    }
    setTesting(false)
  }

  const saveAndContinue = async () => {
    setSaving(true)
    try {
      await api.post('/connector/save', config)
      setStep(2)
    } catch (e) {
      setTestResult({ ok: false, msg: 'Save failed: ' + (e.response?.data?.detail || e.message) })
    }
    setSaving(false)
  }

  const finish = () => {
    onComplete?.()
    navigate('/agent')
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, fontFamily: 'system-ui' }}>
      <div style={{ background: '#fff', borderRadius: 12, width: 520, maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,.2)' }}>

        {/* Progress */}
        <div style={{ padding: '16px 24px', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', gap: 8 }}>
          {STEPS.map((s, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 600, background: i < step ? '#EAF3DE' : i === step ? '#185FA5' : '#f3f4f6', color: i < step ? '#3B6D11' : i === step ? '#fff' : '#aaa' }}>
                {i < step ? '✓' : i + 1}
              </div>
              {i < STEPS.length - 1 && <div style={{ width: 24, height: 2, background: i < step ? '#3B6D11' : '#e5e7eb' }} />}
            </div>
          ))}
          <div style={{ marginLeft: 'auto', fontSize: 11, color: '#888' }}>Step {step + 1} of {STEPS.length}</div>
        </div>

        <div style={{ padding: 24 }}>

          {/* STEP 0 — Welcome */}
          {step === 0 && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 48, marginBottom: 16 }}>🚀</div>
              <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>Welcome to AIBridge</h2>
              <p style={{ fontSize: 13, color: '#555', lineHeight: 1.7, marginBottom: 24 }}>
                AIBridge turns plain English into fully automated data pipelines.
                Connect your database and your data warehouse is ready in minutes — not weeks.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 24 }}>
                {[
                  { icon: '💬', title: 'Describe', desc: 'Tell AI about your data in plain English' },
                  { icon: '⚙️', title: 'Generate', desc: 'AI builds schema, mappings, SQL automatically' },
                  { icon: '📊', title: 'Analyse', desc: 'Query your warehouse, get charts instantly' },
                ].map((item, i) => (
                  <div key={i} style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 10px', textAlign: 'center' }}>
                    <div style={{ fontSize: 24, marginBottom: 6 }}>{item.icon}</div>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 3 }}>{item.title}</div>
                    <div style={{ fontSize: 10, color: '#888', lineHeight: 1.4 }}>{item.desc}</div>
                  </div>
                ))}
              </div>
              <button style={btnPrimary} onClick={() => setStep(1)}>Get started →</button>
              <div style={{ marginTop: 10 }}>
                <button style={btnLink} onClick={finish}>Skip setup, explore on my own</button>
              </div>
            </div>
          )}

          {/* STEP 1 — Connect DB */}
          {step === 1 && (
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>Connect your database</h2>
              <p style={{ fontSize: 12, color: '#888', marginBottom: 16 }}>
                AIBridge will use this as your source and target. You can add more connectors later.
              </p>

              {/* DB type selector */}
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 500, marginBottom: 6 }}>Database type</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6 }}>
                  {DB_TYPES.map(db => (
                    <button key={db.value}
                      style={{ border: `1.5px solid ${config.connector_type === db.value ? '#185FA5' : '#e5e7eb'}`, borderRadius: 8, padding: '8px 6px', background: config.connector_type === db.value ? '#E6F1FB' : '#fff', cursor: 'pointer', textAlign: 'center' }}
                      onClick={() => setConfig({ ...config, connector_type: db.value, port: defaultPorts[db.value] || config.port })}>
                      <div style={{ fontSize: 18, marginBottom: 2 }}>{db.icon}</div>
                      <div style={{ fontSize: 10, fontWeight: 500, color: config.connector_type === db.value ? '#185FA5' : '#555' }}>{db.label}</div>
                      <div style={{ fontSize: 9, color: '#aaa' }}>{db.category}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Connection fields */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
                <Field label="Connection name">
                  <input style={inp} value={config.name} onChange={e => setConfig({...config, name: e.target.value})} />
                </Field>
                <Field label="Host">
                  <input style={inp} value={config.host} onChange={e => setConfig({...config, host: e.target.value})} />
                </Field>
                <Field label="Port">
                  <input style={inp} type="number" value={config.port} onChange={e => setConfig({...config, port: +e.target.value})} />
                </Field>
                <Field label="Database name">
                  <input style={inp} value={config.database_name} onChange={e => setConfig({...config, database_name: e.target.value})} />
                </Field>
                <Field label="Username">
                  <input style={inp} value={config.username} onChange={e => setConfig({...config, username: e.target.value})} />
                </Field>
                <Field label="Password">
                  <input style={inp} type="password" value={config.password} onChange={e => setConfig({...config, password: e.target.value})} />
                </Field>
              </div>

              {testResult && (
                <div style={{ background: testResult.ok ? '#EAF3DE' : '#fef2f2', border: `1px solid ${testResult.ok ? '#a7d9a0' : '#fca5a5'}`, borderRadius: 6, padding: '7px 12px', fontSize: 11, color: testResult.ok ? '#27500A' : '#991b1b', marginBottom: 10 }}>
                  {testResult.ok ? '✓ ' : '✗ '}{testResult.msg}
                </div>
              )}

              <div style={{ display: 'flex', gap: 8 }}>
                <button style={btnPrimary} onClick={testConnection} disabled={testing}>
                  {testing ? 'Testing...' : 'Test connection'}
                </button>
                {testResult?.ok && (
                  <button style={{ ...btnPrimary, background: '#3B6D11' }} onClick={saveAndContinue} disabled={saving}>
                    {saving ? 'Saving...' : 'Save & continue →'}
                  </button>
                )}
                <button style={btnLink} onClick={() => setStep(2)}>Skip for now</button>
              </div>
            </div>
          )}

          {/* STEP 2 — How it works */}
          {step === 2 && (
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>Here is what happens next</h2>
              <p style={{ fontSize: 12, color: '#888', marginBottom: 16 }}>Understanding the AIBridge flow in 60 seconds.</p>
              {[
                { num: 1, color: '#185FA5', title: 'Run ETL Agent', desc: 'Describe your source data and analytics goals. AI generates the complete ETL pipeline — schema analysis, star schema, SQL scripts — automatically.' },
                { num: 2, color: '#534AB7', title: 'Save with connector', desc: 'Link the generated pipeline to your database connection. Choose source tables and schedule.' },
                { num: 3, color: '#3B6D11', title: 'Click Execute', desc: 'One click runs the full pipeline: raw → staging → warehouse. Your dim and fact tables are created automatically.' },
                { num: 4, color: '#854F0B', title: 'Analyse your data', desc: 'Go to BI / Analytics and ask questions in plain English. Get charts instantly from your warehouse.' },
              ].map(item => (
                <div key={item.num} style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
                  <div style={{ width: 28, height: 28, borderRadius: '50%', background: item.color, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 600, flexShrink: 0 }}>
                    {item.num}
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{item.title}</div>
                    <div style={{ fontSize: 11, color: '#888', lineHeight: 1.5 }}>{item.desc}</div>
                  </div>
                </div>
              ))}
              <button style={{ ...btnPrimary, width: '100%', marginTop: 8 }} onClick={() => setStep(3)}>
                Got it, let's go →
              </button>
            </div>
          )}

          {/* STEP 3 — Ready */}
          {step === 3 && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 56, marginBottom: 16 }}>🎉</div>
              <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>You are all set!</h2>
              <p style={{ fontSize: 13, color: '#555', lineHeight: 1.7, marginBottom: 24 }}>
                Your AIBridge workspace is ready. Click below to run your first ETL pipeline.
              </p>
              <button style={{ ...btnPrimary, fontSize: 14, padding: '12px 24px' }} onClick={finish}>
                Run my first pipeline →
              </button>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: '#374151', marginBottom: 3 }}>{label}</label>
      {children}
    </div>
  )
}

const inp      = { width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box' }
const btnPrimary={ padding: '8px 18px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 12, cursor: 'pointer', fontWeight: 500 }
const btnLink  = { background: 'none', border: 'none', color: '#888', fontSize: 11, cursor: 'pointer', textDecoration: 'underline' }
