/**
 * SourceTarget.jsx
 * Shows source tables on the left and target DWH tables on the right
 * with clear mapping arrows between them.
 *
 * FIXED: handles both old (string) and new (object) data model formats.
 *   attributes / foreign_keys / measures may now be objects like
 *   {column, type, source} or {column, references_table, ...}
 */

import { useState, useEffect } from 'react'
import { pipelineAPI } from '../api/api'
import { PageHeader, PageBody } from '../components/Layout'

// Pull a string name from anything (string or object {column}/{name}/{references_table})
const nameOf = (x) => {
  if (x == null) return ''
  if (typeof x === 'string') return x
  if (typeof x === 'object') return x.column || x.name || x.references_table || JSON.stringify(x)
  return String(x)
}

export default function SourceTarget() {
  const [pipelines, setPipelines] = useState([])
  const [selected,  setSelected]  = useState(null)
  const [data,      setData]      = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [activeMap, setActiveMap] = useState(null)

  useEffect(() => {
    pipelineAPI.list().then(r => {
      const list = r.data.pipelines || []
      setPipelines(list)
      if (list.length > 0) {
        setSelected(list[0])
        buildData(list[0])
      }
    }).finally(() => setLoading(false))
  }, [])

  const buildData = (pipeline) => {
    const artifacts = pipeline.artifacts || {}
    const schema    = artifacts.schema_analysis  || {}
    const model     = artifacts.data_model       || {}
    const mappings  = artifacts.etl_mappings     || {}

    // Source tables from schema analysis
    const sourceTables = (schema.entities || []).map(e => ({
      name:    e.name,
      type:    e.type,
      columns: (e.columns || []).map(nameOf),
      pk:      nameOf(e.primary_key),
      rows:    e.row_estimate
    }))

    // Target tables from data model — normalize objects to names
    const targetTables = [
      ...(model.fact_tables || []).map(f => ({
        name:    f.name,
        type:    'fact',
        columns: [
          ...(f.foreign_keys || []).map(nameOf),
          ...(f.measures     || []).map(nameOf)
        ],
        grain:   f.grain
      })),
      ...(model.dimension_tables || []).map(d => ({
        name:    d.name,
        type:    'dim',
        columns: [nameOf(d.surrogate_key), ...((d.attributes || []).map(nameOf))],
        source:  d.source_table,
        scd:     d.scd_type
      }))
    ]

    // Flow lines from mappings
    const flows = []
    ;(mappings.mappings || []).forEach(m => {
      const sources = new Set()
      ;(m.columns || []).forEach(col => {
        if (col.source_table) sources.add(col.source_table)
      })
      sources.forEach(src => {
        flows.push({
          from:    src,
          to:      m.target_table,
          columns: m.columns?.filter(c => c.source_table === src) || []
        })
      })
    })

    setData({ sourceTables, targetTables, flows })
    setActiveMap(null)
  }

  const selectPipeline = (p) => {
    setSelected(p)
    buildData(p)
  }

  const typeColor = {
    transaction: { bg: '#E6F1FB', color: '#185FA5', label: 'transaction' },
    master:      { bg: '#EEEDFE', color: '#534AB7', label: 'master'      },
    reference:   { bg: '#EAF3DE', color: '#3B6D11', label: 'reference'   },
    fact:        { bg: '#E6F1FB', color: '#0C447C', label: 'fact'        },
    dim:         { bg: '#EEEDFE', color: '#3C3489', label: 'dimension'   },
  }

  const isHighlighted = (tableName, side) => {
    if (!activeMap) return false
    if (side === 'source') return activeMap.from === tableName
    if (side === 'target') return activeMap.to   === tableName
    return false
  }

  return (
    <>
      <PageHeader
        title="Source → Target"
        subtitle="Data lineage — how source tables map to your data warehouse"
      />
      <PageBody>
        {loading && <div style={muted}>Loading...</div>}

        {!loading && pipelines.length === 0 && (
          <div style={emptyBox}>
            No pipelines yet. Run the ETL Agent first.
          </div>
        )}

        {pipelines.length > 1 && (
          <div style={{ marginBottom: 14, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {pipelines.map(p => (
              <button key={p.id}
                style={selected?.id === p.id ? btnActive : btnGhost}
                onClick={() => selectPipeline(p)}>
                {p.name}
              </button>
            ))}
          </div>
        )}

        {data && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, marginBottom: 20 }}>
              <Metric val={data.sourceTables.length} lbl="Source tables"  color="#185FA5" />
              <Metric val={data.targetTables.length} lbl="Target tables"  color="#534AB7" />
              <Metric val={data.flows.length}        lbl="Data flows"     color="#3B6D11" />
              <Metric val={getTotalCols(data)}       lbl="Columns mapped" color="#854F0B" />
            </div>

            <div style={{ fontSize: 11, color: '#888', marginBottom: 12, background: '#f9fafb', padding: '6px 12px', borderRadius: 6 }}>
              💡 Click any flow row below to highlight source and target tables
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px 1fr', gap: 16, alignItems: 'start' }}>

              {/* SOURCE TABLES */}
              <div>
                <div style={colHeader}>
                  <div style={colDot('#185FA5')}></div>
                  Source tables
                  <span style={badge}>{data.sourceTables.length}</span>
                </div>
                {data.sourceTables.map(t => {
                  const c   = typeColor[t.type] || typeColor.reference
                  const hl  = isHighlighted(t.name, 'source')
                  return (
                    <div key={t.name} style={{ ...tableCard, border: hl ? '2px solid #185FA5' : '1px solid #e5e7eb', background: hl ? '#EEF5FD' : '#fff' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                        <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600 }}>{t.name}</div>
                        <span style={{ ...chip, background: c.bg, color: c.color }}>{c.label}</span>
                      </div>
                      {t.pk && (
                        <div style={{ fontSize: 10, color: '#185FA5', fontFamily: 'monospace', marginBottom: 4 }}>
                          🔑 {t.pk}
                        </div>
                      )}
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                        {t.columns.slice(0, 6).map((cn, i) => (
                          <span key={cn + i} style={colChip}>{cn}</span>
                        ))}
                        {t.columns.length > 6 && (
                          <span style={colChip}>+{t.columns.length - 6} more</span>
                        )}
                      </div>
                      {t.rows && (
                        <div style={{ fontSize: 9, color: '#aaa', marginTop: 5 }}>~{t.rows} rows</div>
                      )}
                    </div>
                  )
                })}
              </div>

              {/* FLOW CENTER */}
              <div>
                <div style={{ ...colHeader, justifyContent: 'center' }}>
                  <div style={colDot('#3B6D11')}></div>
                  Data flows
                </div>
                {data.flows.map((flow, i) => (
                  <div key={i}
                    style={{ ...flowCard, background: activeMap === flow ? '#EAF3DE' : '#f9fafb', border: activeMap === flow ? '1px solid #a7d9a0' : '1px solid #e5e7eb', cursor: 'pointer' }}
                    onClick={() => setActiveMap(activeMap === flow ? null : flow)}
                  >
                    <div style={{ fontSize: 10, fontFamily: 'monospace', color: '#185FA5', marginBottom: 2, textAlign: 'center' }}>{flow.from}</div>
                    <div style={{ textAlign: 'center', color: '#aaa', fontSize: 16, lineHeight: 1 }}>↓</div>
                    <div style={{ fontSize: 10, fontFamily: 'monospace', color: '#534AB7', marginTop: 2, textAlign: 'center' }}>{flow.to}</div>
                    <div style={{ fontSize: 9, color: '#888', textAlign: 'center', marginTop: 3 }}>
                      {flow.columns.length} col{flow.columns.length !== 1 ? 's' : ''}
                    </div>
                  </div>
                ))}

                {data.flows.length === 0 && (
                  <div style={{ fontSize: 11, color: '#aaa', textAlign: 'center', padding: '20px 0' }}>
                    Run ETL Agent to see flows
                  </div>
                )}
              </div>

              {/* TARGET TABLES */}
              <div>
                <div style={colHeader}>
                  <div style={colDot('#534AB7')}></div>
                  Target tables (DWH)
                  <span style={badge}>{data.targetTables.length}</span>
                </div>
                {data.targetTables.map(t => {
                  const c  = typeColor[t.type] || typeColor.dim
                  const hl = isHighlighted(t.name, 'target')
                  return (
                    <div key={t.name} style={{ ...tableCard, border: hl ? '2px solid #534AB7' : '1px solid #e5e7eb', background: hl ? '#F0EFFE' : '#fff' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                        <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600 }}>{t.name}</div>
                        <span style={{ ...chip, background: c.bg, color: c.color }}>{c.label}</span>
                      </div>
                      {t.grain && (
                        <div style={{ fontSize: 9, color: '#888', marginBottom: 4, fontStyle: 'italic' }}>
                          Grain: {t.grain}
                        </div>
                      )}
                      {t.source && (
                        <div style={{ fontSize: 10, color: '#888', marginBottom: 4 }}>
                          ← from: <span style={{ fontFamily: 'monospace', color: '#185FA5' }}>{t.source}</span>
                        </div>
                      )}
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                        {t.columns.slice(0, 6).map((cn, i) => (
                          <span key={cn + i} style={{ ...colChip, background: '#EEEDFE', color: '#534AB7' }}>{cn}</span>
                        ))}
                        {t.columns.length > 6 && (
                          <span style={{ ...colChip, background: '#EEEDFE', color: '#534AB7' }}>+{t.columns.length - 6} more</span>
                        )}
                      </div>
                      {t.scd && (
                        <div style={{ fontSize: 9, color: '#854F0B', marginTop: 5, background: '#FAEEDA', padding: '2px 6px', borderRadius: 4, display: 'inline-block' }}>
                          SCD Type {t.scd}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

            </div>

            {/* Selected flow detail */}
            {activeMap && (
              <div style={{ marginTop: 20, border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px' }}>
                <div style={sectionTitle}>
                  Flow detail: <span style={{ fontFamily: 'monospace', color: '#185FA5' }}>{activeMap.from}</span>
                  {' → '}
                  <span style={{ fontFamily: 'monospace', color: '#534AB7' }}>{activeMap.to}</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 50px 1fr 90px', gap: 8, padding: '4px 0', borderBottom: '1px solid #e5e7eb', fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase' }}>
                  <div>Source column</div><div></div><div>Target column</div><div>Transform</div>
                </div>
                {activeMap.columns.map((col, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 50px 1fr 90px', gap: 8, padding: '5px 0', borderBottom: i < activeMap.columns.length - 1 ? '1px solid #f3f4f6' : 'none', fontSize: 11, alignItems: 'center' }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 10, background: '#f9fafb', padding: '2px 6px', borderRadius: 4 }}>{nameOf(col.source_column)}</span>
                    <span style={{ textAlign: 'center', color: '#aaa' }}>→</span>
                    <span style={{ fontFamily: 'monospace', fontSize: 10, background: '#EEEDFE', color: '#534AB7', padding: '2px 6px', borderRadius: 4 }}>{nameOf(col.target_column)}</span>
                    <span style={{ fontSize: 9, background: '#EAF3DE', color: '#3B6D11', padding: '2px 6px', borderRadius: 4 }}>{col.transform_type || col.transform_rule || ''}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </PageBody>
    </>
  )
}

function Metric({ val, lbl, color }) {
  return (
    <div style={{ background: '#f9fafb', borderRadius: 8, padding: '10px 14px', borderLeft: `3px solid ${color}` }}>
      <div style={{ fontSize: 22, fontWeight: 600, color }}>{val}</div>
      <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>{lbl}</div>
    </div>
  )
}

function getTotalCols(data) {
  return data.flows.reduce((sum, f) => sum + (f.columns?.length || 0), 0)
}

const colDot    = (c) => ({ width: 8, height: 8, borderRadius: '50%', background: c, flexShrink: 0 })
const colHeader = { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 10 }
const badge     = { background: '#e5e7eb', color: '#555', padding: '1px 7px', borderRadius: 20, fontSize: 10, marginLeft: 'auto' }
const tableCard = { borderRadius: 8, padding: '10px 12px', marginBottom: 8, transition: 'all .15s' }
const flowCard  = { borderRadius: 6, padding: '8px 10px', marginBottom: 6, transition: 'all .15s' }
const chip      = { padding: '2px 7px', borderRadius: 20, fontSize: 9, fontWeight: 500 }
const colChip   = { background: '#f3f4f6', color: '#555', padding: '1px 6px', borderRadius: 4, fontSize: 9, fontFamily: 'monospace' }
const emptyBox  = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 32, textAlign: 'center', fontSize: 13, color: '#888' }
const muted     = { fontSize: 13, color: '#888' }
const sectionTitle = { fontSize: 11, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 10 }
const btnGhost  = { padding: '6px 12px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnActive = { padding: '6px 12px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
