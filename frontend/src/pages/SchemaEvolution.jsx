/**
 * SchemaEvolution.jsx
 * Add new columns to existing dimension/fact tables.
 * AI generates ALTER TABLE + updated ETL scripts + backfill.
 */

import { useState, useEffect } from 'react'
import { pipelineAPI, schemaAPI } from '../api/api'
import { PageHeader, PageBody } from '../components/Layout'

export default function SchemaEvolution() {
  const [pipelines,  setPipelines]  = useState([])
  const [selected,   setSelected]   = useState(null)
  const [tables,     setTables]     = useState([])
  const [form,       setForm]       = useState({
    table_name:       '',
    new_column:       '',
    column_type:      'VARCHAR(100)',
    user_instruction: ''
  })
  const [result,   setResult]   = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)
  const [activeTab,setActiveTab]= useState(0)

  useEffect(() => {
    pipelineAPI.list().then(r => {
      const list = r.data.pipelines || []
      setPipelines(list)
      if (list.length > 0) {
        setSelected(list[0])
        setTables(getTablesFromPipeline(list[0]))
      }
    })
  }, [])

  const getTablesFromPipeline = (p) => {
    const model = p.artifacts?.data_model
    if (!model) return []
    const facts = (model.fact_tables || []).map(f => ({ name: f.name, columns: f.measures || [] }))
    const dims  = (model.dimension_tables || []).map(d => ({ name: d.name, columns: d.attributes || [] }))
    return [...facts, ...dims]
  }

  const selectPipeline = (p) => {
    setSelected(p)
    setTables(getTablesFromPipeline(p))
    setResult(null)
    setForm({ table_name: '', new_column: '', column_type: 'VARCHAR(100)', user_instruction: '' })
  }

  const runEvolution = async () => {
    if (!form.table_name || !form.new_column || !form.user_instruction) {
      setError('Please fill in all fields.')
      return
    }
    setError(null)
    setLoading(true)
    setResult(null)
    try {
      const selectedTable = tables.find(t => t.name === form.table_name)
      const existing_cols = selectedTable?.columns || []
      const r = await schemaAPI.evolve(
        form.table_name,
        existing_cols,
        form.new_column,
        form.column_type,
        form.user_instruction
      )
      setResult(r.data.data)
      setActiveTab(0)
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    }
    setLoading(false)
  }

  const columnTypes = [
    'VARCHAR(100)', 'VARCHAR(255)', 'TEXT',
    'INTEGER', 'BIGINT', 'DECIMAL(10,2)',
    'BOOLEAN', 'DATE', 'TIMESTAMP'
  ]

  return (
    <>
      <PageHeader
        title="Schema evolution"
        subtitle="Add new columns to existing tables — AI handles impact analysis and backfill"
      />
      <PageBody>

        {/* Pipeline selector */}
        {pipelines.length > 1 && (
          <div style={{ marginBottom: 16, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {pipelines.map(p => (
              <button key={p.id}
                style={selected?.id === p.id ? btnActive : btnGhost}
                onClick={() => selectPipeline(p)}>
                {p.name}
              </button>
            ))}
          </div>
        )}

        {/* Request form */}
        <div style={card}>
          <div style={sectionTitle}>Describe the change you want to make</div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
            <Field label="Target table">
              <select style={inp} value={form.table_name}
                onChange={e => setForm({ ...form, table_name: e.target.value })}>
                <option value="">Select table...</option>
                {tables.map(t => (
                  <option key={t.name} value={t.name}>{t.name}</option>
                ))}
              </select>
            </Field>
            <Field label="New column name">
              <input style={inp} value={form.new_column}
                onChange={e => setForm({ ...form, new_column: e.target.value })}
                placeholder="e.g. brand" />
            </Field>
            <Field label="Column data type">
              <select style={inp} value={form.column_type}
                onChange={e => setForm({ ...form, column_type: e.target.value })}>
                {columnTypes.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </Field>
          </div>

          <Field label="Instruction — describe what this column is and how to populate it">
            <textarea style={{ ...inp, resize: 'vertical' }} rows={2}
              value={form.user_instruction}
              onChange={e => setForm({ ...form, user_instruction: e.target.value })}
              placeholder="e.g. Add brand column from products source table. Track changes over time with SCD Type 2. Backfill from source for existing rows." />
          </Field>

          {error && (
            <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 11, color: '#991b1b', marginBottom: 10 }}>
              {error}
            </div>
          )}

          <button style={{ ...btnPrimary, marginTop: 10 }} onClick={runEvolution} disabled={loading}>
            {loading ? 'AI is analyzing...' : 'Run schema evolution'}
          </button>
        </div>

        {/* Results */}
        {result && (
          <div>
            {/* Impact analysis */}
            {result.impact_analysis && (
              <div style={{ ...card, borderLeft: '3px solid #854F0B', marginBottom: 12 }}>
                <div style={sectionTitle}>Impact analysis</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12 }}>
                  <div><span style={{ color: '#888' }}>Table: </span>{result.impact_analysis.table_affected}</div>
                  <div><span style={{ color: '#888' }}>Operation: </span>{result.impact_analysis.operation}</div>
                  <div><span style={{ color: '#888' }}>Risk: </span>
                    <span style={{ color: result.impact_analysis.risk_level === 'low' ? '#3B6D11' : '#854F0B', fontWeight: 500 }}>
                      {result.impact_analysis.risk_level}
                    </span>
                  </div>
                  <div><span style={{ color: '#888' }}>Backfill needed: </span>
                    {result.impact_analysis.backfill_needed ? '✓ Yes' : '✗ No'}
                  </div>
                </div>
                {result.impact_analysis.notes && (
                  <div style={{ fontSize: 11, color: '#555', marginTop: 8, padding: '6px 10px', background: '#FAEEDA', borderRadius: 5 }}>
                    {result.impact_analysis.notes}
                  </div>
                )}
                {result.impact_analysis.downstream_affected?.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 10, color: '#888', marginBottom: 4 }}>Objects affected:</div>
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                      {result.impact_analysis.downstream_affected.map((obj, i) => (
                        <span key={i} style={{ background: '#f9fafb', border: '1px solid #e5e7eb', padding: '2px 8px', borderRadius: 4, fontSize: 10 }}>{obj}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* SQL Scripts */}
            {result.scripts?.length > 0 && (
              <div style={card}>
                <div style={sectionTitle}>Generated SQL scripts</div>
                <div style={{ display: 'flex', gap: 5, marginBottom: 10 }}>
                  {result.scripts.map((s, i) => (
                    <button key={i}
                      style={i === activeTab ? btnActive : btnGhost}
                      onClick={() => setActiveTab(i)}>
                      {s.label || s.name}
                    </button>
                  ))}
                </div>
                {result.scripts[activeTab] && (
                  <div>
                    <pre style={sqlBlock}>{result.scripts[activeTab].sql}</pre>
                    <button style={{ ...btnPrimary, marginTop: 8 }}
                      onClick={() => {
                        navigator.clipboard.writeText(result.scripts[activeTab].sql)
                        alert('Copied!')
                      }}>
                      Copy SQL
                    </button>
                  </div>
                )}
              </div>
            )}

            <div style={{ background: '#EAF3DE', border: '1px solid #a7d9a0', borderRadius: 6, padding: '10px 14px', fontSize: 12, color: '#27500A' }}>
              ✓ Schema evolution complete. Copy the ALTER TABLE script and run it on your database. Then update your pipeline and run a backfill.
            </div>
          </div>
        )}

      </PageBody>
    </>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: '#374151', marginBottom: 4 }}>{label}</label>
      {children}
    </div>
  )
}

const inp         = { width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box', fontFamily: 'system-ui' }
const card        = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }
const sectionTitle= { fontSize: 11, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 10 }
const sqlBlock    = { background: '#1e1e1e', color: '#d4d4d4', borderRadius: 6, padding: '12px 14px', fontSize: 10, fontFamily: 'monospace', overflowX: 'auto', lineHeight: 1.8, whiteSpace: 'pre' }
const btnPrimary  = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhost    = { padding: '6px 12px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnActive   = { padding: '6px 12px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
