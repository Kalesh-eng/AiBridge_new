/**
 * EtlMapping.jsx
 * Column-level ETL mapping — source → target with transform rules.
 */

import { useState, useEffect } from 'react'
import { pipelineAPI } from '../api/api'
import { PageHeader, PageBody } from '../components/Layout'

export default function EtlMapping() {
  const [pipelines, setPipelines] = useState([])
  const [selected,  setSelected]  = useState(null)
  const [mappings,  setMappings]  = useState(null)
  const [loading,   setLoading]   = useState(true)

  useEffect(() => {
    pipelineAPI.list().then(r => {
      const list = r.data.pipelines || []
      setPipelines(list)
      if (list.length > 0) {
        setSelected(list[0])
        setMappings(list[0].artifacts?.etl_mappings || null)
      }
    }).finally(() => setLoading(false))
  }, [])

  const selectPipeline = (p) => {
    setSelected(p)
    setMappings(p.artifacts?.etl_mappings || null)
  }

  const transformColor = {
    generate:  { bg: '#FAECE7', color: '#993C1D' },
    derive:    { bg: '#FAEEDA', color: '#854F0B' },
    lookup:    { bg: '#EEEDFE', color: '#534AB7' },
    direct:    { bg: '#EAF3DE', color: '#3B6D11' },
    aggregate: { bg: '#E6F1FB', color: '#185FA5' },
    none:      { bg: '#f9fafb', color: '#888'    },
  }

  return (
    <>
      <PageHeader
        title="ETL mapping"
        subtitle="Column-level source → target mapping with transformation rules"
      />
      <PageBody>
        {loading && <div style={muted}>Loading...</div>}

        {!loading && pipelines.length === 0 && (
          <div style={emptyBox}>
            No pipelines yet. Run the ETL Agent first.
          </div>
        )}

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

        {/* Transform legend */}
        {mappings && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
            {Object.entries(transformColor).filter(([k]) => k !== 'none').map(([type, c]) => (
              <span key={type} style={{ background: c.bg, color: c.color, padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }}>
                {type}
              </span>
            ))}
          </div>
        )}

        {/* Mappings */}
        {mappings && (mappings.mappings || []).map((mapping, i) => (
          <div key={i} style={card}>
            {/* Table header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 600, color: '#111' }}>
                {mapping.target_table}
              </div>
              <span style={{ background: '#E6F1FB', color: '#185FA5', padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }}>
                {mapping.columns?.length || 0} columns
              </span>
            </div>

            {/* Column header row */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 50px 1fr 80px', gap: 8, padding: '4px 0', borderBottom: '1px solid #e5e7eb', fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: '.04em' }}>
              <div>Source</div>
              <div></div>
              <div>Target</div>
              <div>Transform</div>
            </div>

            {/* Column rows */}
            {(mapping.columns || []).map((col, j) => {
              const tc = transformColor[col.transform_type] || transformColor.none
              return (
                <div key={j} style={{ display: 'grid', gridTemplateColumns: '1fr 50px 1fr 80px', gap: 8, padding: '6px 0', borderBottom: j < mapping.columns.length - 1 ? '1px solid #f3f4f6' : 'none', alignItems: 'start' }}>
                  {/* Source */}
                  <div>
                    <div style={{ fontFamily: 'monospace', fontSize: 10, background: '#f9fafb', padding: '2px 6px', borderRadius: 4, color: '#333', display: 'inline-block' }}>
                      {col.source_table}.{col.source_column}
                    </div>
                  </div>
                  {/* Arrow */}
                  <div style={{ textAlign: 'center', color: '#aaa', paddingTop: 2 }}>→</div>
                  {/* Target */}
                  <div>
                    <div style={{ fontFamily: 'monospace', fontSize: 10, background: '#E6F1FB', padding: '2px 6px', borderRadius: 4, color: '#185FA5', display: 'inline-block', marginBottom: 3 }}>
                      {col.target_column}
                    </div>
                    {col.transform_rule && (
                      <div style={{ fontSize: 9, color: '#888', marginTop: 2 }}>{col.transform_rule}</div>
                    )}
                  </div>
                  {/* Transform type */}
                  <div>
                    <span style={{ background: tc.bg, color: tc.color, padding: '2px 6px', borderRadius: 4, fontSize: 9, fontWeight: 500 }}>
                      {col.transform_type}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        ))}

        {selected && !mappings && (
          <div style={emptyBox}>No ETL mappings found for this pipeline.</div>
        )}

      </PageBody>
    </>
  )
}

const card      = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }
const emptyBox  = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 32, textAlign: 'center', fontSize: 13, color: '#888' }
const muted     = { fontSize: 13, color: '#888' }
const btnGhost  = { padding: '6px 12px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnActive = { padding: '6px 12px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
