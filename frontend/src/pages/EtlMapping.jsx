/**
 * EtlMapping.jsx
 * Column-level ETL mapping — source → target with transform rules.
 * Business can mark columns as "Required" (NOT NULL) for quality checks.
 */

import { useState, useEffect } from 'react'
import { pipelineAPI } from '../api/api'
import api from '../api/api'
import { PageHeader, PageBody } from '../components/Layout'

export default function EtlMapping() {
  const [pipelines,      setPipelines]      = useState([])
  const [selected,       setSelected]       = useState(null)
  const [mappings,       setMappings]       = useState(null)
  const [requiredCols,   setRequiredCols]   = useState({})  // { "table.column": true }
  const [loading,        setLoading]        = useState(true)
  const [saving,         setSaving]         = useState(false)
  const [saveMsg,        setSaveMsg]        = useState(null)

  useEffect(() => {
    pipelineAPI.list().then(r => {
      const list = r.data.pipelines || []
      setPipelines(list)
      if (list.length > 0) {
        selectPipeline(list[0])
      }
    }).finally(() => setLoading(false))
  }, [])

  const selectPipeline = (p) => {
    setSelected(p)
    setMappings(p.artifacts?.etl_mappings || null)
    // Load saved required columns from pipeline artifacts
    const saved = p.artifacts?.required_columns || {}
    setRequiredCols(saved)
    setSaveMsg(null)
  }

  const toggleRequired = (targetTable, targetColumn) => {
    const key = `${targetTable}.${targetColumn}`
    setRequiredCols(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const saveRequiredColumns = async () => {
    if (!selected) return
    setSaving(true)
    setSaveMsg(null)
    try {
      await api.post(`/pipeline/${selected.id}/required-columns`, { required_columns: requiredCols })
      setSaveMsg({ type: 'success', text: '✓ Required columns saved — quality checks will use these settings' })
      // Update local pipeline object
      setPipelines(prev => prev.map(p => p.id === selected.id
        ? { ...p, artifacts: { ...p.artifacts, required_columns: requiredCols } }
        : p
      ))
    } catch (e) {
      setSaveMsg({ type: 'error', text: '✗ Could not save: ' + (e.response?.data?.detail || e.message) })
    }
    setSaving(false)
    setTimeout(() => setSaveMsg(null), 4000)
  }

  const requiredCount = Object.values(requiredCols).filter(Boolean).length

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
        subtitle="Column-level source → target mapping. Mark columns as Required to enforce NOT NULL in quality checks."
      />
      <PageBody>
        {loading && <div style={muted}>Loading...</div>}

        {!loading && pipelines.length === 0 && (
          <div style={emptyBox}>No pipelines yet. Run the ETL Agent first.</div>
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

        {/* Save bar */}
        {mappings && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 14, padding: '8px 12px', background: '#f9fafb',
            border: '1px solid #e5e7eb', borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: '#555' }}>
              <span style={{ fontWeight: 600, color: '#185FA5' }}>{requiredCount}</span> columns marked as Required
              {requiredCount > 0 && (
                <span style={{ color: '#888', marginLeft: 6 }}>
                  — QualityAgent will check these for NULL values before warehouse load
                </span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {saveMsg && (
                <span style={{ fontSize: 11,
                  color: saveMsg.type === 'success' ? '#27500A' : '#A32D2D' }}>
                  {saveMsg.text}
                </span>
              )}
              <button style={{ ...btnActive, opacity: saving ? 0.6 : 1 }}
                onClick={saveRequiredColumns} disabled={saving}>
                {saving ? 'Saving...' : '💾 Save Required Columns'}
              </button>
            </div>
          </div>
        )}

        {/* Transform legend */}
        {mappings && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16, alignItems: 'center' }}>
            <span style={{ fontSize: 10, color: '#888', marginRight: 4 }}>Transform:</span>
            {Object.entries(transformColor).filter(([k]) => k !== 'none').map(([type, c]) => (
              <span key={type} style={{ background: c.bg, color: c.color,
                padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }}>
                {type}
              </span>
            ))}
            <span style={{ marginLeft: 12, fontSize: 10, color: '#888' }}>Required:</span>
            <span style={{ background: '#FEF3C7', color: '#92400E',
              padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }}>
              ★ NOT NULL
            </span>
          </div>
        )}

        {/* Mappings */}
        {mappings && (mappings.mappings || []).map((mapping, i) => (
          <div key={i} style={card}>
            {/* Table header */}
            <div style={{ display: 'flex', alignItems: 'center',
              justifyContent: 'space-between', marginBottom: 12 }}>
              <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 600, color: '#111' }}>
                {mapping.target_table}
              </div>
              <span style={{ background: '#E6F1FB', color: '#185FA5',
                padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }}>
                {mapping.columns?.length || 0} columns
              </span>
            </div>

            {/* Column header row */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 40px 1fr 80px 80px',
              gap: 8, padding: '4px 0', borderBottom: '1px solid #e5e7eb',
              fontSize: 10, fontWeight: 600, color: '#888',
              textTransform: 'uppercase', letterSpacing: '.04em' }}>
              <div>Source</div>
              <div></div>
              <div>Target</div>
              <div>Transform</div>
              <div style={{ textAlign: 'center' }}>Required</div>
            </div>

            {/* Column rows */}
            {(mapping.columns || []).map((col, j) => {
              const tc  = transformColor[col.transform_type] || transformColor.none
              const key = `${mapping.target_table}.${col.target_column}`
              const isRequired = !!requiredCols[key]
              return (
                <div key={j} style={{
                  display: 'grid', gridTemplateColumns: '1fr 40px 1fr 80px 80px',
                  gap: 8, padding: '6px 0',
                  borderBottom: j < mapping.columns.length - 1 ? '1px solid #f3f4f6' : 'none',
                  alignItems: 'center',
                  background: isRequired ? '#FFFBEB' : 'transparent'
                }}>
                  {/* Source */}
                  <div>
                    <div style={{ fontFamily: 'monospace', fontSize: 10, background: '#f9fafb',
                      padding: '2px 6px', borderRadius: 4, color: '#333', display: 'inline-block' }}>
                      {col.source_table}.{col.source_column}
                    </div>
                  </div>
                  {/* Arrow */}
                  <div style={{ textAlign: 'center', color: '#aaa' }}>→</div>
                  {/* Target */}
                  <div>
                    <div style={{ fontFamily: 'monospace', fontSize: 10,
                      background: isRequired ? '#FEF3C7' : '#E6F1FB',
                      padding: '2px 6px', borderRadius: 4,
                      color: isRequired ? '#92400E' : '#185FA5',
                      display: 'inline-block', marginBottom: 3 }}>
                      {isRequired && '★ '}{col.target_column}
                    </div>
                    {col.transform_rule && (
                      <div style={{ fontSize: 9, color: '#888', marginTop: 2 }}>{col.transform_rule}</div>
                    )}
                  </div>
                  {/* Transform type */}
                  <div>
                    <span style={{ background: tc.bg, color: tc.color,
                      padding: '2px 6px', borderRadius: 4, fontSize: 9, fontWeight: 500 }}>
                      {col.transform_type}
                    </span>
                  </div>
                  {/* Required toggle */}
                  <div style={{ textAlign: 'center' }}>
                    <label style={{ display: 'inline-flex', alignItems: 'center',
                      gap: 4, cursor: 'pointer', fontSize: 10,
                      color: isRequired ? '#92400E' : '#aaa' }}>
                      <input
                        type="checkbox"
                        checked={isRequired}
                        onChange={() => toggleRequired(mapping.target_table, col.target_column)}
                        style={{ cursor: 'pointer', accentColor: '#d97706' }}
                      />
                      {isRequired ? 'Required' : 'Optional'}
                    </label>
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
