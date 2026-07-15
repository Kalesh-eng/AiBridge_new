/**
 * MigrationAgent.jsx — AIBridge Migration Mode v2
 * Supports three modes:
 *   1. Reverse Engineer — scan existing warehouse, rebuild data model
 *   2. Import Mappings — upload Informatica/dbt/SSIS/ODI/BRD files
 *   3. Extend Existing — add new tables without breaking existing ones
 *
 * Upload options for Import Mappings:
 *   - Repository XML (recommended) — one file, all mappings extracted
 *   - Individual files — one file per dim/fact table
 */
import { useState, useRef } from 'react'
import { PageHeader, PageBody } from '../components/Layout'
import api from '../api/api'

const STEPS = ['Choose mode', 'Connect & upload', 'Scan & analyze', 'Review & deploy']

export default function MigrationAgent() {
  const [step, setStep]               = useState(0)
  const [subMode, setSubMode]         = useState(null)   // reverse | import | extend
  const [technology, setTechnology]   = useState('informatica')  // informatica | dbt
  const [uploadMode, setUploadMode]   = useState('repository')  // repository | individual
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)
  const [activeTab, setActiveTab]     = useState('model')
  const [uploadedFiles, setUploadedFiles] = useState([])
  const [scanResult, setScanResult]   = useState(null)
  const [resolvedGaps, setResolvedGaps] = useState({})
  const [sqlScripts, setSqlScripts]   = useState(null)
  const [sqlLoading, setSqlLoading]   = useState(false)
  const [sqlError, setSqlError]       = useState(null)
  const [expandedScript, setExpandedScript] = useState(null)
  const [approvalId, setApprovalId]         = useState(null)
  const [approvalStatus, setApprovalStatus] = useState(null) // null | 'pending' | 'approved' | 'rejected' | 'blocked'
  const [approvalRiskLevel, setApprovalRiskLevel] = useState(null)
  const [approvalLoading, setApprovalLoading] = useState(false)
  const [approvalError, setApprovalError]     = useState(null)
  const [safetyBlock, setSafetyBlock]         = useState(null) // {violations, warnings, message} when blocked
  const [understandDestructive, setUnderstandDestructive] = useState(false)
  const [deploySourceConnector, setDeploySourceConnector] = useState('')
  const [deployLoading, setDeployLoading] = useState(false)
  const [deployError, setDeployError]     = useState(null)
  const [deployResult, setDeployResult]   = useState(null)
  const fileRef = useRef(null)

  const [connectors, setConnectors]       = useState([])
  const [selectedConnector, setSelectedConnector] = useState('')
  const [useExisting, setUseExisting]     = useState(true)

  // Load saved connectors on mount
  useState(() => {
    api.get('/connector/list').then(r => {
      setConnectors(r.data.connectors || [])
    }).catch(() => {})
  })

  const [conn, setConn] = useState({
    host: '', port: '5432', database: '', username: '', password: '',
    source_schema: 'raw', staging_schema: 'staging', warehouse_schema: 'warehouse',
    connector_type: 'postgres'
  })

  const goTo = (n) => { setStep(n); setError(null) }

  const handleFileUpload = (e) => {
    const files = Array.from(e.target.files || [])
    setUploadedFiles(prev => [...prev, ...files.map(f => ({
      name: f.name,
      type: f.name.endsWith('.xml') ? 'informatica' :
            f.name.endsWith('.yml') || f.name.endsWith('.yaml') ? 'dbt' :
            f.name.endsWith('.dtsx') ? 'ssis' :
            f.name.endsWith('.pdf') || f.name.endsWith('.docx') ? 'brd' : 'other',
      uploadMode: uploadMode,
      assignedTable: null,  // for individual mode
      status: 'ready',
      file: f
    }))])
  }

  const handleScan = async () => {
    setLoading(true); setError(null)
    try {
      const formData = new FormData()
      formData.append('connection', JSON.stringify(conn))
      formData.append('sub_mode', subMode)
      formData.append('upload_mode', uploadMode)
      formData.append('technology', technology)
      uploadedFiles.forEach(f => formData.append('files', f.file))
      const r = await api.post('/migration/scan', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setScanResult(r.data)
      goTo(2)
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Scan failed')
    }
    setLoading(false)
  }

  const handleGenerateSql = async () => {
    setSqlLoading(true); setSqlError(null)
    try {
      const resolutions = {}
      Object.entries(resolvedGaps).forEach(([idx, text]) => {
        const gapColumn = scanResult?.gaps?.[idx]?.column
        if (gapColumn) resolutions[gapColumn] = text
        resolutions[idx] = text
      })
      const r = await api.post('/migration/generate-sql', {
        technology:  scanResult.technology || technology,
        tables:      scanResult.tables || [],
        mappings:    scanResult.mappings || [],
        gaps:        scanResult.gaps || [],
        resolutions,
        domain:      scanResult.domain || '',
        source_schema:    conn.source_schema,
        staging_schema:   conn.staging_schema,
        warehouse_schema: conn.warehouse_schema,
        dbt_deployment_order: scanResult.dbt_deployment_order,
        dbt_source_lookup:    scanResult.dbt_source_lookup
      })
      setSqlScripts(r.data.sql_scripts?.scripts || [])
      setApprovalId(r.data.approval_id)
      setApprovalStatus('pending')
      setApprovalRiskLevel(r.data.risk_level)
      setSafetyBlock(null)
      setDeployResult(null)
      goTo(3)
    } catch (e) {
      setSqlError(e.response?.data?.detail || e.message || 'SQL generation failed')
    }
    setSqlLoading(false)
  }

  // Reuses the SAME /pipeline/approve-sql endpoint native pipelines use for
  // their Gate 2 SQL review — no migration-specific approval endpoint needed.
  const handleApprove = async () => {
    if (!approvalId) return
    setApprovalLoading(true); setApprovalError(null)
    try {
      const r = await api.post('/pipeline/approve-sql', {
        approval_id: approvalId,
        i_understand_destructive: understandDestructive
      })
      if (r.data.blocked) {
        setSafetyBlock({
          violations: r.data.violations || [],
          warnings:   r.data.warnings || [],
          message:    r.data.message || 'This SQL contains destructive operations that need explicit confirmation.'
        })
        setApprovalStatus('blocked')
      } else {
        setApprovalStatus('approved')
        setSafetyBlock(null)
      }
    } catch (e) {
      setApprovalError(e.response?.data?.detail || e.message || 'Approval failed')
    }
    setApprovalLoading(false)
  }

  const handleReject = async () => {
    if (!approvalId) return
    setApprovalLoading(true); setApprovalError(null)
    try {
      await api.post('/pipeline/reject', { approval_id: approvalId, comments: 'Rejected from Migration Agent review', regenerate: true })
      setApprovalStatus('rejected')
    } catch (e) {
      setApprovalError(e.response?.data?.detail || e.message || 'Rejection failed')
    }
    setApprovalLoading(false)
  }

  // Source tables to extract are derived from the parsed mappings'
  // source_table field (e.g. "SRC_CAR") — deduplicated, in first-seen order,
  // excluding anything flagged needs_review (not a real extractable table).
  const derivedSourceTables = Array.from(new Set(
    (scanResult?.mappings || [])
      .filter(m => !m.needs_review)
      .map(m => m.source_table)
      .filter(Boolean)
  ))

  const [exportLoading, setExportLoading] = useState(null) // null | 'docx' | 'pdf'
  const [exportError, setExportError] = useState(null)

  const handleExportDocs = async (format) => {
    setExportLoading(format); setExportError(null)
    try {
      const r = await api.post('/migration/export-docs', {
        tables:      scanResult.tables || [],
        mappings:    scanResult.mappings || [],
        gaps:        scanResult.gaps || [],
        domain:      scanResult.domain || '',
        ai_summary:  scanResult.ai_summary || '',
        resolutions: resolvedGaps || {},
        format
      }, { responseType: 'blob' })

      const blob = new Blob([r.data])
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `migration_requirements.${format}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      let message = e.message || 'Export failed'
      // Blob error responses need to be read as text to get the real detail
      if (e.response?.data instanceof Blob) {
        try {
          const text = await e.response.data.text()
          message = JSON.parse(text).detail || message
        } catch { /* keep default message */ }
      } else {
        message = e.response?.data?.detail || message
      }
      setExportError(message)
    }
    setExportLoading(null)
  }

  const handleDeploy = async () => {
    if (approvalStatus !== 'approved') {
      setDeployError('These SQL scripts must be approved before deploying — use the Approve button above.')
      return
    }
    if (!deploySourceConnector) {
      setDeployError('Select the source system connector first — this is where the legacy data actually lives.')
      return
    }
    if (!selectedConnector) {
      setDeployError('No target warehouse connector selected — go back to Step 1 and pick one.')
      return
    }
    setDeployLoading(true); setDeployError(null); setDeployResult(null)
    try {
      const r = await api.post('/migration/deploy', {
        approval_id:          approvalId,
        project_name:         `Migration: ${scanResult?.domain || 'warehouse'} — ${new Date().toLocaleDateString()}`,
        source_connector_id:  deploySourceConnector,
        target_connector_id:  selectedConnector,
        source_schema:        conn.source_schema,
        staging_schema:       conn.staging_schema || 'staging',
        warehouse_schema:     conn.warehouse_schema || 'warehouse',
        source_tables:        derivedSourceTables,
        data_model:           { domain: scanResult?.domain, tables: scanResult?.tables }
      })
      setDeployResult(r.data)
    } catch (e) {
      setDeployError(e.response?.data?.detail || e.message || 'Deployment failed')
    }
    setDeployLoading(false)
  }

  const fileTypeIcon = (type) => ({
    informatica: { icon: 'ti-file-type-xml', color: '#185FA5', label: 'Informatica' },
    dbt:         { icon: 'ti-file-type-yml', color: '#3B6D11', label: 'dbt' },
    ssis:        { icon: 'ti-file-zip',      color: '#854F0B', label: 'SSIS' },
    brd:         { icon: 'ti-file-description', color: '#534AB7', label: 'BRD' },
    other:       { icon: 'ti-file',          color: '#888',    label: 'File' },
  })[type] || { icon: 'ti-file', color: '#888', label: 'File' }

  return (
    <>
      <PageHeader
        title="Migration Agent"
        subtitle="Reverse engineer, extend, or migrate an existing data warehouse"
      />
      <PageBody>
        {/* Step progress */}
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${STEPS.length}, 1fr)`, gap: 4, marginBottom: 20 }}>
          {STEPS.map((s, i) => (
            <div key={i}>
              <div style={{ height: 3, borderRadius: 2, background: i <= step ? '#534AB7' : '#e5e7eb', marginBottom: 4 }} />
              <div style={{ fontSize: 9, color: i === step ? '#534AB7' : '#aaa', textAlign: 'center' }}>{s}</div>
            </div>
          ))}
        </div>

        {error && (
          <div style={errBox}>
            {error}
            <button style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', color: '#991b1b' }} onClick={() => setError(null)}>✕</button>
          </div>
        )}

        {/* ── Step 0: Choose sub-mode ── */}
        {step === 0 && (
          <div>
            <div style={{ textAlign: 'center', marginBottom: 24 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#111', marginBottom: 6 }}>What do you want to do?</div>
              <div style={{ fontSize: 12, color: '#888' }}>Choose the migration approach that fits your situation.</div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14, maxWidth: 640, margin: '0 auto 24px' }}>
              {[
                { id: 'reverse', icon: 'ti-scan',           color: '#534AB7', bg: '#EEEDFE', title: 'Reverse engineer',  desc: 'Scan existing warehouse, rebuild data model and documentation automatically.', bestFor: 'Understanding an existing DWH' },
                { id: 'import',  icon: 'ti-file-import',    color: '#3B6D11', bg: '#EAF3DE', title: 'Import mappings',   desc: 'Upload Informatica XML, dbt YML, SSIS or ODI files to extract transformation logic.', bestFor: 'Migrating ETL to new platform' },
                { id: 'extend',  icon: 'ti-arrows-exchange',color: '#854F0B', bg: '#FAEEDA', title: 'Extend existing',   desc: 'Add new dimensions or fact tables without breaking current warehouse tables.', bestFor: 'Adding new data sources' },
              ].map(opt => (
                <div key={opt.id} onClick={() => setSubMode(opt.id)} style={{
                  border: subMode === opt.id ? `2px solid ${opt.color}` : '1px solid #e5e7eb',
                  background: subMode === opt.id ? opt.bg : '#fff',
                  borderRadius: 10, padding: 16, cursor: 'pointer'
                }}>
                  <div style={{ width: 36, height: 36, background: opt.bg, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 10 }}>
                    <i className={`ti ${opt.icon}`} style={{ fontSize: 20, color: opt.color }} />
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#111', marginBottom: 6 }}>{opt.title}</div>
                  <div style={{ fontSize: 11, color: '#555', lineHeight: 1.5, marginBottom: 10 }}>{opt.desc}</div>
                  <div style={{ fontSize: 10, color: '#888' }}>Best for: {opt.bestFor}</div>
                </div>
              ))}
            </div>
            <div style={{ textAlign: 'center' }}>
              <button style={{ ...btnPrimary, background: '#534AB7', opacity: subMode ? 1 : 0.5 }}
                onClick={() => subMode && goTo(1)} disabled={!subMode}>
                Continue →
              </button>
            </div>
          </div>
        )}

        {/* ── Step 1: Connect & upload ── */}
        {step === 1 && (
          <div style={{ maxWidth: 600, margin: '0 auto' }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#111', marginBottom: 4 }}>
              {subMode === 'import' ? 'Connect warehouse & upload mapping files' : 'Connect existing warehouse'}
            </div>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 16 }}>
              {subMode === 'reverse' && 'AIBridge will scan the warehouse in read-only mode.'}
              {subMode === 'import' && 'Connect to the warehouse and upload your mapping files.'}
              {subMode === 'extend' && 'Connect to the warehouse you want to extend.'}
            </div>

            {/* Connection form */}
            <div style={card}>
              <div style={sectionLabel}>Warehouse connection</div>

              {/* Toggle: use existing connector or new */}
              <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
                <button onClick={() => setUseExisting(true)} style={{
                  padding: '5px 14px', fontSize: 11, borderRadius: 6, cursor: 'pointer',
                  background: useExisting ? '#534AB7' : '#fff',
                  color: useExisting ? '#fff' : '#555',
                  border: `1px solid ${useExisting ? '#534AB7' : '#d1d5db'}`
                }}>Use saved connector</button>
                <button onClick={() => setUseExisting(false)} style={{
                  padding: '5px 14px', fontSize: 11, borderRadius: 6, cursor: 'pointer',
                  background: !useExisting ? '#534AB7' : '#fff',
                  color: !useExisting ? '#fff' : '#555',
                  border: `1px solid ${!useExisting ? '#534AB7' : '#d1d5db'}`
                }}>New connection</button>
              </div>

              {useExisting ? (
                /* Existing connector selector */
                connectors.length > 0 ? (
                  <div>
                    <label style={labelStyle}>Select warehouse connector</label>
                    <select style={inp} value={selectedConnector}
                      onChange={e => {
                        setSelectedConnector(e.target.value)
                        const c = connectors.find(c => c.id === e.target.value)
                        if (c) setConn({
                          host: c.host, port: String(c.port),
                          database: c.database_name, username: c.username,
                          password: '', source_schema: 'raw', staging_schema: 'staging', warehouse_schema: 'warehouse',
                          connector_type: c.connector_type
                        })
                      }}>
                      <option value="">— Select connector —</option>
                      {connectors.map(c => (
                        <option key={c.id} value={c.id}>
                          {c.name} — {c.connector_type} / {c.host}/{c.database_name}
                        </option>
                      ))}
                    </select>
                    {selectedConnector && (
                      <div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginTop: 10 }}>
                          <div>
                            <label style={labelStyle}>Source schema</label>
                            <input style={inp} value={conn.source_schema} placeholder="raw"
                              onChange={e => setConn(c => ({ ...c, source_schema: e.target.value }))} />
                          </div>
                          <div>
                            <label style={labelStyle}>Staging schema</label>
                            <input style={inp} value={conn.staging_schema} placeholder="staging"
                              onChange={e => setConn(c => ({ ...c, staging_schema: e.target.value }))} />
                          </div>
                          <div>
                            <label style={labelStyle}>Warehouse schema</label>
                            <input style={inp} value={conn.warehouse_schema} placeholder="warehouse"
                              onChange={e => setConn(c => ({ ...c, warehouse_schema: e.target.value }))} />
                          </div>
                        </div>
                        <label style={{ ...labelStyle, marginTop: 8 }}>Password (re-enter for security)</label>
                        <input style={inp} type="password" value={conn.password}
                          onChange={e => setConn(c => ({ ...c, password: e.target.value }))} />
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{ fontSize: 12, color: '#888', padding: '10px 0' }}>
                    No connectors saved yet. Use "New connection" or add one in Connectors.
                  </div>
                )
              ) : (
                /* New connection form */
                <div>
                  <div style={{ marginBottom: 10 }}>
                    <label style={labelStyle}>Database type</label>
                    <select style={inp} value={conn.connector_type}
                      onChange={e => setConn(c => ({ ...c, connector_type: e.target.value }))}>
                      <option value="postgres">PostgreSQL</option>
                      <option value="mysql">MySQL / MariaDB</option>
                      <option value="sqlserver">SQL Server / Azure SQL</option>
                      <option value="snowflake">Snowflake</option>
                      <option value="bigquery">BigQuery</option>
                      <option value="redshift">Amazon Redshift</option>
                      <option value="oracle">Oracle</option>
                    </select>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                    {[
                      { key: 'host',     label: 'Host',     placeholder: 'localhost' },
                      { key: 'port',     label: 'Port',     placeholder: '5432' },
                      { key: 'database', label: 'Database', placeholder: 'my_warehouse' },
                      { key: 'username', label: 'Username', placeholder: 'readonly_user' },
                    ].map(f => (
                      <div key={f.key}>
                        <label style={labelStyle}>{f.label}</label>
                        <input style={inp} value={conn[f.key]} placeholder={f.placeholder}
                          onChange={e => setConn(c => ({ ...c, [f.key]: e.target.value }))} />
                      </div>
                    ))}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    <div>
                      <label style={labelStyle}>Password</label>
                      <input style={inp} type="password" value={conn.password}
                        onChange={e => setConn(c => ({ ...c, password: e.target.value }))} />
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginTop: 10 }}>
                    <div>
                      <label style={labelStyle}>Source schema</label>
                      <input style={inp} value={conn.source_schema} placeholder="raw"
                        onChange={e => setConn(c => ({ ...c, source_schema: e.target.value }))} />
                    </div>
                    <div>
                      <label style={labelStyle}>Staging schema</label>
                      <input style={inp} value={conn.staging_schema} placeholder="staging"
                        onChange={e => setConn(c => ({ ...c, staging_schema: e.target.value }))} />
                    </div>
                    <div>
                      <label style={labelStyle}>Warehouse schema</label>
                      <input style={inp} value={conn.warehouse_schema} placeholder="warehouse"
                        onChange={e => setConn(c => ({ ...c, warehouse_schema: e.target.value }))} />
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* File upload section — import mode only */}
            {subMode === 'import' && (
              <div style={card}>
                <div style={sectionLabel}>Source technology</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 18 }}>
                  {[
                    {
                      id: 'informatica', icon: 'ti-git-branch',
                      color: '#185FA5', bg: '#E6F1FB',
                      title: 'Informatica PowerCenter',
                      desc: 'Upload a repository/mapping XML export. AIBridge traces the transformation graph automatically.',
                    },
                    {
                      id: 'dbt', icon: 'ti-brand-git',
                      color: '#FF694A', bg: '#FFEEE9',
                      title: 'dbt',
                      desc: 'Upload your dbt project\u2019s .sql model files + sources.yml/schema.yml. Models are already real SQL \u2014 no reconstruction needed.',
                    },
                  ].map(opt => (
                    <div key={opt.id} onClick={() => { setTechnology(opt.id); setUploadedFiles([]) }} style={{
                      border: technology === opt.id ? `2px solid ${opt.color}` : '1px solid #e5e7eb',
                      background: technology === opt.id ? opt.bg : '#f9fafb',
                      borderRadius: 8, padding: 14, cursor: 'pointer'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                        <i className={`ti ${opt.icon}`} style={{ fontSize: 18, color: opt.color }} />
                        <span style={{ fontSize: 13, fontWeight: 600, color: '#111' }}>{opt.title}</span>
                      </div>
                      <div style={{ fontSize: 11, color: '#555', lineHeight: 1.5 }}>{opt.desc}</div>
                    </div>
                  ))}
                </div>

                <div style={sectionLabel}>Upload mapping files</div>

                {/* Upload mode selector — Informatica only; dbt is always multi-file */}
                {technology === 'informatica' && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
                    {[
                      {
                        id: 'repository',
                        icon: 'ti-package',
                        color: '#185FA5', bg: '#E6F1FB',
                        title: 'Repository XML',
                        badge: 'Recommended',
                        desc: 'Upload one Informatica repository XML — AIBridge extracts ALL mappings automatically.',
                        accepts: '.xml'
                      },
                      {
                        id: 'individual',
                        icon: 'ti-files',
                        color: '#534AB7', bg: '#EEEDFE',
                        title: 'Individual files',
                        badge: 'More control',
                        desc: 'Upload one mapping file per dim/fact table.',
                        accepts: '.xml'
                      },
                    ].map(opt => (
                      <div key={opt.id} onClick={() => setUploadMode(opt.id)} style={{
                        border: uploadMode === opt.id ? `2px solid ${opt.color}` : '1px solid #e5e7eb',
                        background: uploadMode === opt.id ? opt.bg : '#f9fafb',
                        borderRadius: 8, padding: 14, cursor: 'pointer'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                          <i className={`ti ${opt.icon}`} style={{ fontSize: 18, color: opt.color }} />
                          <span style={{ fontSize: 13, fontWeight: 600, color: '#111' }}>{opt.title}</span>
                          <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 20, background: opt.bg, color: opt.color, marginLeft: 'auto' }}>{opt.badge}</span>
                        </div>
                        <div style={{ fontSize: 11, color: '#555', lineHeight: 1.5 }}>{opt.desc}</div>
                      </div>
                    ))}
                  </div>
                )}

                {technology === 'dbt' && (
                  <div style={{ fontSize: 11, color: '#888', marginBottom: 14, padding: '8px 10px', background: '#FFF7ED', borderRadius: 6 }}>
                    Select every <code>.sql</code> model file in your project, plus <code>sources.yml</code> and any <code>schema.yml</code> files. dbt models form a dependency graph (via <code>ref()</code>/<code>source()</code>) \u2014 AIBridge deploys them in the correct order automatically.
                  </div>
                )}

                {/* Upload zone */}
                <input ref={fileRef} type="file"
                  multiple={technology === 'dbt' || uploadMode === 'individual'}
                  accept={technology === 'dbt' ? '.sql,.yml,.yaml' : (uploadMode === 'repository' ? '.xml' : '.xml')}
                  style={{ display: 'none' }} onChange={handleFileUpload} />

                <div style={{ border: '1.5px dashed #d1d5db', borderRadius: 8, padding: 20, textAlign: 'center', cursor: 'pointer', background: '#f9fafb' }}
                  onClick={() => fileRef.current?.click()}>
                  <i className="ti ti-upload" style={{ fontSize: 24, color: '#aaa' }} />
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#374151', marginTop: 8 }}>
                    {technology === 'dbt' ? 'Drop your dbt project files here (.sql + .yml)' : (uploadMode === 'repository' ? 'Drop Informatica Repository XML here' : 'Drop mapping files here or click to browse')}
                  </div>
                  <div style={{ fontSize: 11, color: '#aaa', marginTop: 4 }}>
                    {technology === 'dbt' ? 'Select all model files + sources.yml/schema.yml at once' : (uploadMode === 'repository' ? 'One .xml file — all mappings extracted automatically' : 'Informatica repository/mapping XML')}
                  </div>
                </div>

                {/* Uploaded files list */}
                {uploadedFiles.length > 0 && (
                  <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {uploadedFiles.map((f, i) => {
                      const ic = fileTypeIcon(f.type)
                      return (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 6 }}>
                          <i className={`ti ${ic.icon}`} style={{ fontSize: 16, color: ic.color }} />
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 12, color: '#374151' }}>{f.name}</div>
                            <div style={{ fontSize: 10, color: '#888' }}>{ic.label} · {uploadMode === 'repository' ? 'All mappings will be extracted' : 'Individual mapping'}</div>
                          </div>
                          {uploadMode === 'individual' && (
                            <select style={{ fontSize: 11, padding: '3px 6px', border: '1px solid #d1d5db', borderRadius: 4, background: '#fff' }}
                              value={f.assignedTable || ''}
                              onChange={e => setUploadedFiles(prev => prev.map((uf, j) => j === i ? { ...uf, assignedTable: e.target.value } : uf))}>
                              <option value="">Assign to table...</option>
                              <option value="dim_customer">dim_customer</option>
                              <option value="dim_product">dim_product</option>
                              <option value="fact_sales">fact_sales</option>
                            </select>
                          )}
                          <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 20, background: '#EAF3DE', color: '#3B6D11' }}>Ready</span>
                          <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#aaa' }}
                            onClick={() => setUploadedFiles(prev => prev.filter((_, j) => j !== i))}>✕</button>
                        </div>
                      )
                    })}
                  </div>
                )}

                {/* Info box */}
                <div style={{ marginTop: 10, padding: '8px 12px', background: uploadMode === 'repository' ? '#E6F1FB' : '#EEEDFE', borderRadius: 6, fontSize: 11, color: uploadMode === 'repository' ? '#185FA5' : '#534AB7' }}>
                  {uploadMode === 'repository'
                    ? '💡 Repository XML contains all mappings, workflows and transformations. AIBridge will automatically match each mapping to your warehouse tables.'
                    : '💡 Upload one file per table. Use the dropdown to assign each file to its target warehouse table.'}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', gap: 8 }}>
              <button style={btnGhost} onClick={() => goTo(0)}>← Back</button>
              <button style={{ ...btnPrimary, background: '#534AB7' }} onClick={handleScan} disabled={loading || (!conn.host && !selectedConnector)}>
                {loading ? '⏳ Scanning...' : '🔍 Scan warehouse'}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Scan results ── */}
        {step === 2 && scanResult && (
          <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 0, border: '1px solid #e5e7eb', borderRadius: 10, overflow: 'hidden' }}>
            {/* Sidebar */}
            <div style={{ borderRight: '1px solid #e5e7eb', padding: 14, background: '#fafafa' }}>
              <div style={sectionLabel}>Discovered tables</div>
              {(scanResult.tables || []).map((t, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '5px 6px', borderRadius: 6, marginBottom: 2 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 20, background: t.type === 'dim' ? '#EEEDFE' : '#FAEEDA', color: t.type === 'dim' ? '#534AB7' : '#854F0B' }}>{t.type}</span>
                    <span style={{ fontSize: 11, color: '#374151', fontFamily: 'monospace' }}>{t.name}</span>
                  </div>
                  <span style={{ fontSize: 10, color: '#aaa' }}>{t.row_count}</span>
                </div>
              ))}
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid #e5e7eb' }}>
                <div style={sectionLabel}>Summary</div>
                <div style={{ fontSize: 11, color: '#555', lineHeight: 2 }}>
                  <div>Domain: <strong>{scanResult.domain || '—'}</strong></div>
                  <div>Dims: <strong>{(scanResult.tables || []).filter(t => t.type === 'dim').length}</strong></div>
                  <div>Facts: <strong>{(scanResult.tables || []).filter(t => t.type === 'fact').length}</strong></div>
                  <div>Gaps: <strong style={{ color: '#854F0B' }}>{(scanResult.gaps || []).length}</strong></div>
                  {scanResult.upload_mode && (
                    <div>Files: <strong>{scanResult.upload_mode === 'repository' ? 'Repository' : 'Individual'}</strong></div>
                  )}
                </div>
              </div>
            </div>

            {/* Main panel */}
            <div style={{ padding: 14 }}>
              <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
                {[
                  { id: 'model',    label: '📊 Data model' },
                  { id: 'mappings', label: `🔗 Mappings (${(scanResult.mappings || []).length})` },
                  { id: 'gaps',     label: `⚠️ Gaps (${(scanResult.gaps || []).length + (scanResult.mappings || []).filter(m => m.needs_review).length})` },
                  { id: 'dict',     label: '📖 Dictionary' },
                ].map(tab => (
                  <button key={tab.id} onClick={() => setActiveTab(tab.id)} style={{
                    padding: '5px 12px', fontSize: 11, borderRadius: 6, cursor: 'pointer',
                    fontWeight: activeTab === tab.id ? 600 : 400,
                    background: activeTab === tab.id ? '#534AB7' : '#fff',
                    color: activeTab === tab.id ? '#fff' : '#555',
                    border: `1px solid ${activeTab === tab.id ? '#534AB7' : '#d1d5db'}`
                  }}>{tab.label}</button>
                ))}
              </div>

              {/* Model tab */}
              {activeTab === 'model' && (
                <div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 14 }}>
                    {[
                      { label: 'Tables',   val: (scanResult.tables || []).length },
                      { label: 'Coverage', val: `${scanResult.coverage || 0}%`, color: '#3B6D11' },
                      { label: 'Gaps',     val: (scanResult.gaps || []).length, color: '#854F0B' },
                    ].map(m => (
                      <div key={m.label} style={{ background: '#f9fafb', borderRadius: 8, padding: 12, textAlign: 'center' }}>
                        <div style={{ fontSize: 11, color: '#888' }}>{m.label}</div>
                        <div style={{ fontSize: 22, fontWeight: 700, color: m.color || '#111' }}>{m.val}</div>
                      </div>
                    ))}
                  </div>
                  {scanResult.ai_summary && (
                    <div style={{ ...card, background: '#E6F1FB', borderColor: '#b5d4f4', marginBottom: 12, fontSize: 12, color: '#185FA5', lineHeight: 1.6 }}>
                      <strong>🤖 AI analysis:</strong> {scanResult.ai_summary}
                    </div>
                  )}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    <div style={card}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: '#534AB7', marginBottom: 8 }}>Dimensions</div>
                      {(scanResult.tables || []).filter(t => t.type === 'dim').map((t, i) => (
                        <div key={i} style={{ fontSize: 11, padding: '3px 8px', background: '#EEEDFE', borderRadius: 6, marginBottom: 4, color: '#534AB7' }}>
                          {t.name} · {t.row_count}
                        </div>
                      ))}
                    </div>
                    <div style={card}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: '#854F0B', marginBottom: 8 }}>Facts</div>
                      {(scanResult.tables || []).filter(t => t.type === 'fact').map((t, i) => (
                        <div key={i} style={{ fontSize: 11, padding: '3px 8px', background: '#FAEEDA', borderRadius: 6, marginBottom: 4, color: '#854F0B' }}>
                          {t.name} · {t.row_count}
                        </div>
                      ))}
                    </div>
                  </div>
                  {sqlError && (
                    <div style={{ ...errBox, marginTop: 12 }}>
                      {sqlError}
                      <button style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', color: '#991b1b' }} onClick={() => setSqlError(null)}>✕</button>
                    </div>
                  )}
                  {exportError && (
                    <div style={{ ...errBox, marginTop: 12 }}>
                      {exportError}
                      <button style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', color: '#991b1b' }} onClick={() => setExportError(null)}>✕</button>
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
                    <button style={{ ...btnPrimary, background: '#534AB7', opacity: sqlLoading ? 0.6 : 1 }}
                      onClick={handleGenerateSql} disabled={sqlLoading}>
                      {sqlLoading ? '⏳ Generating SQL...' : 'Generate SQL scripts →'}
                    </button>
                    <button style={btnGhost} onClick={() => handleExportDocs('docx')} disabled={exportLoading !== null}>
                      {exportLoading === 'docx' ? '⏳ Exporting...' : '📄 Export Word'}
                    </button>
                    <button style={btnGhost} onClick={() => handleExportDocs('pdf')} disabled={exportLoading !== null}>
                      {exportLoading === 'pdf' ? '⏳ Exporting...' : '📕 Export PDF'}
                    </button>
                  {(() => {
                    const trueGapsCount = (scanResult.gaps || []).length
                    const needsReviewList = (scanResult.mappings || []).filter(m => m.needs_review)
                    const trueGapsResolved = (scanResult.gaps || []).filter((g, i) => resolvedGaps[i]).length
                    const needsReviewResolved = needsReviewList.filter(m => resolvedGaps[m.target]).length
                    const totalUnresolved = (trueGapsCount - trueGapsResolved) + (needsReviewList.length - needsReviewResolved)
                    return totalUnresolved > 0 && (
                      <button style={btnGhost} onClick={() => setActiveTab('gaps')}>
                        {totalUnresolved} issue{totalUnresolved !== 1 ? 's' : ''} still unresolved
                      </button>
                    )
                  })()}
                  </div>
                </div>
              )}

              {/* Mappings tab */}
              {activeTab === 'mappings' && (
                <div style={card}>
                  {(scanResult.mappings || []).length === 0 ? (
                    <div style={{ fontSize: 12, color: '#888', padding: 20, textAlign: 'center' }}>
                      {subMode === 'import'
                        ? 'No mappings parsed yet — upload Informatica/dbt files to see column mappings.'
                        : 'Column mappings are available after uploading mapping files.'}
                    </div>
                  ) : (
                    <>
                      <div style={{ display: 'grid', gridTemplateColumns: '2fr 2fr 2fr 1fr', gap: 8, padding: '6px 0', borderBottom: '1px solid #e5e7eb', fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                        <div>Target column</div><div>Source</div><div>Transformation</div><div>Status</div>
                      </div>
                      {(scanResult.mappings || []).map((m, i) => (
                        <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 2fr 2fr 1fr', gap: 8, padding: '6px 0', borderBottom: '1px solid #f3f4f6', fontSize: 11, alignItems: 'center' }}>
                          <div style={{ fontFamily: 'monospace', color: '#374151' }}>{m.target}</div>
                          <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#555' }}>{m.source || '—'}</div>
                          <div style={{ color: '#555' }}>{m.transformation || '—'}</div>
                          <div><span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 20, background: m.mapped ? '#EAF3DE' : '#FAEEDA', color: m.mapped ? '#3B6D11' : '#854F0B' }}>{m.mapped ? 'Mapped' : 'Gap'}</span></div>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}

              {/* Gaps tab */}
              {activeTab === 'gaps' && (
                <div>
                  {(() => {
                    const needsReviewMappings = (scanResult.mappings || []).filter(m => m.needs_review)
                    const trueGaps = scanResult.gaps || []
                    const totalIssues = trueGaps.length + needsReviewMappings.length

                    if (totalIssues === 0) {
                      return (
                        <div style={{ ...card, background: '#EAF3DE', borderColor: '#a7d9a0', textAlign: 'center', padding: 24 }}>
                          <div style={{ fontSize: 16 }}>✅</div>
                          <div style={{ fontSize: 13, color: '#27500A', fontWeight: 600, marginTop: 6 }}>No gaps — all columns are mapped</div>
                        </div>
                      )
                    }

                    return (
                      <>
                        {trueGaps.length > 0 && (
                          <div style={{ ...card, borderColor: '#f5c08a', marginBottom: needsReviewMappings.length > 0 ? 12 : 0 }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: '#854F0B', marginBottom: 12 }}>⚠️ {trueGaps.length} unmapped column{trueGaps.length !== 1 ? 's' : ''}</div>
                            {trueGaps.map((g, i) => (
                              <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid #f3f4f6', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                                <div style={{ flex: 1 }}>
                                  <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#854F0B', marginBottom: 4 }}>{g.column}</div>
                                  <div style={{ fontSize: 12, color: '#555' }}>{g.reason}</div>
                                  {resolvedGaps[i] && (
                                    <div style={{ fontSize: 11, color: '#3B6D11', marginTop: 4 }}>✓ Resolution: {resolvedGaps[i]}</div>
                                  )}
                                </div>
                                {!resolvedGaps[i] ? (
                                  <button style={{ ...btnGhost, fontSize: 11, padding: '4px 10px', whiteSpace: 'nowrap' }}
                                    onClick={() => {
                                      const resolution = prompt(`How should ${g.column} be derived?\n\nExample: "Bucket date_of_birth into 5-year age ranges"`)
                                      if (resolution) setResolvedGaps(prev => ({ ...prev, [i]: resolution }))
                                    }}>Resolve ↗</button>
                                ) : (
                                  <span style={{ fontSize: 10, padding: '3px 8px', borderRadius: 20, background: '#EAF3DE', color: '#3B6D11' }}>✓ Resolved</span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}

                        {needsReviewMappings.length > 0 && (
                          <div style={{ ...card, borderColor: '#fca5a5' }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: '#991b1b', marginBottom: 4 }}>🔍 {needsReviewMappings.length} column{needsReviewMappings.length !== 1 ? 's' : ''} need manual review</div>
                            <div style={{ fontSize: 11, color: '#888', marginBottom: 12 }}>
                              These ARE mapped to a source, but the parser couldn't confirm it traces to a real,
                              extractable table (usually a Lookup transformation without enough info in the mapping file).
                            </div>
                            {needsReviewMappings.map((m, i) => (
                              <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid #f3f4f6', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                                <div style={{ flex: 1 }}>
                                  <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#991b1b', marginBottom: 4 }}>{m.target}</div>
                                  <div style={{ fontSize: 12, color: '#555' }}>{m.review_reason || 'Source could not be confirmed as a real table.'}</div>
                                  {m.lookup_join_hint && (
                                    <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
                                      Hint: likely keyed by <span style={{ fontFamily: 'monospace' }}>{m.lookup_join_hint.fed_by_table}.{m.lookup_join_hint.fed_by_column}</span> (unconfirmed)
                                    </div>
                                  )}
                                  {resolvedGaps[m.target] && (
                                    <div style={{ fontSize: 11, color: '#3B6D11', marginTop: 4 }}>✓ Resolution: {resolvedGaps[m.target]}</div>
                                  )}
                                </div>
                                {!resolvedGaps[m.target] ? (
                                  <button style={{ ...btnGhost, fontSize: 11, padding: '4px 10px', whiteSpace: 'nowrap' }}
                                    onClick={() => {
                                      const hintText = m.lookup_join_hint ? `\n\nHint: likely keyed by ${m.lookup_join_hint.fed_by_table}.${m.lookup_join_hint.fed_by_column}` : ''
                                      const resolution = prompt(`How should ${m.target} actually be derived?${hintText}\n\nExample: "JOIN staging.stg_CAR_MAKE ON make_code, use make_name column"`)
                                      if (resolution) setResolvedGaps(prev => ({ ...prev, [m.target]: resolution }))
                                    }}>Resolve ↗</button>
                                ) : (
                                  <span style={{ fontSize: 10, padding: '3px 8px', borderRadius: 20, background: '#EAF3DE', color: '#3B6D11' }}>✓ Resolved</span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )
                  })()}
                </div>
              )}

              {/* Dictionary tab */}
              {activeTab === 'dict' && (
                <div style={card}>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 10, color: '#374151' }}>Auto-generated data dictionary</div>
                  {(scanResult.dictionary || []).map((d, i) => (
                    <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #f3f4f6' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600, color: '#374151' }}>{d.table}</span>
                        <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 20, background: d.type === 'dim' ? '#EEEDFE' : '#FAEEDA', color: d.type === 'dim' ? '#534AB7' : '#854F0B' }}>{d.type}</span>
                        <span style={{ fontSize: 10, color: '#aaa', marginLeft: 'auto' }}>{d.row_count}</span>
                      </div>
                      <div style={{ fontSize: 12, color: '#555' }}>{d.description}</div>
                    </div>
                  ))}
                  {(scanResult.dictionary || []).length === 0 && (
                    <div style={{ fontSize: 12, color: '#888' }}>Dictionary will be generated after scanning.</div>
                  )}
                  <button style={{ ...btnGhost, marginTop: 12, fontSize: 12 }}>
                    <i className="ti ti-download" style={{ marginRight: 6 }} />Export as Word/PDF
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Step 3: Generated SQL & deploy ── */}
        {step === 3 && (
          <div style={{ maxWidth: 760, margin: '0 auto' }}>
            <div style={{ textAlign: 'center', marginBottom: 20 }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>✅</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: '#111', marginBottom: 8 }}>SQL scripts generated</div>
              <div style={{ fontSize: 13, color: '#888' }}>
                Review each script below. Nothing has been run yet — your existing warehouse is untouched.
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 20 }}>
              {[
                { label: 'Scripts generated', val: (sqlScripts || []).length },
                { label: 'Tables covered',    val: (scanResult?.tables || []).filter(t => t.type === 'dim' || t.type === 'fact').length },
                { label: 'Issues resolved',   val: (() => {
                    const trueGaps = scanResult?.gaps || []
                    const needsReviewList = (scanResult?.mappings || []).filter(m => m.needs_review)
                    const total = trueGaps.length + needsReviewList.length
                    const resolved = trueGaps.filter((g, i) => resolvedGaps[i]).length + needsReviewList.filter(m => resolvedGaps[m.target]).length
                    return `${resolved}/${total}`
                  })() },
              ].map(m => (
                <div key={m.label} style={{ background: '#f9fafb', borderRadius: 8, padding: 12, textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: '#888' }}>{m.label}</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: '#111' }}>{m.val}</div>
                </div>
              ))}
            </div>

            {(sqlScripts || []).length === 0 ? (
              <div style={{ ...card, textAlign: 'center', color: '#888', fontSize: 12 }}>
                No scripts to show. Go back and click "Generate SQL scripts" from the Data model tab.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {sqlScripts.map((s, i) => {
                  const badgeType = s.name?.startsWith('fact_') ? 'fact' : 'dim'
                  return (
                    <div key={i} style={card}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
                        onClick={() => setExpandedScript(expandedScript === i ? null : i)}>
                        <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 20, background: badgeType === 'dim' ? '#EEEDFE' : '#FAEEDA', color: badgeType === 'dim' ? '#534AB7' : '#854F0B' }}>{badgeType}</span>
                        <span style={{ fontSize: 12, fontWeight: 600, color: '#374151', fontFamily: 'monospace' }}>{s.schema}.{s.name}</span>
                        <span style={{ fontSize: 11, color: '#aaa' }}>{s.label}</span>
                        {s.columns_mapped != null && (
                          <span style={{ fontSize: 11, color: '#888', marginLeft: 'auto' }}>{s.columns_mapped}/{s.columns_total} columns mapped</span>
                        )}
                        <i className={`ti ${expandedScript === i ? 'ti-chevron-up' : 'ti-chevron-down'}`} style={{ color: '#aaa' }} />
                      </div>
                      {expandedScript === i && (
                        <pre style={{
                          marginTop: 10, padding: 12, background: '#0f172a', color: '#e2e8f0',
                          borderRadius: 6, fontSize: 11, overflowX: 'auto', whiteSpace: 'pre-wrap'
                        }}>{s.sql}</pre>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {(sqlScripts || []).length > 0 && !deployResult && (
              <div style={{ ...card, marginTop: 16, borderColor: approvalStatus === 'approved' ? '#86efac' : '#fde68a' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <div style={sectionLabel}>Human review</div>
                  {approvalRiskLevel && (
                    <span style={{
                      fontSize: 9, padding: '1px 6px', borderRadius: 20,
                      background: approvalRiskLevel === 'high' ? '#fee2e2' : approvalRiskLevel === 'medium' ? '#fef3c7' : '#dcfce7',
                      color: approvalRiskLevel === 'high' ? '#991b1b' : approvalRiskLevel === 'medium' ? '#92400e' : '#166534'
                    }}>{approvalRiskLevel} risk</span>
                  )}
                </div>

                {approvalStatus === 'pending' && (
                  <>
                    <div style={{ fontSize: 12, color: '#888', marginBottom: 10 }}>
                      Review the generated scripts above before approving. Nothing runs against your
                      warehouse until you approve — same review gate native AIBridge pipelines use.
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button style={{ ...btnPrimary, background: '#16a34a', opacity: approvalLoading ? 0.6 : 1 }}
                        onClick={handleApprove} disabled={approvalLoading}>
                        {approvalLoading ? '⏳ Checking...' : '✓ Approve SQL'}
                      </button>
                      <button style={btnGhost} onClick={handleReject} disabled={approvalLoading}>✕ Reject</button>
                    </div>
                  </>
                )}

                {approvalStatus === 'blocked' && safetyBlock && (
                  <div>
                    <div style={{ ...errBox, marginBottom: 10 }}>
                      {safetyBlock.message}
                      {safetyBlock.violations.length > 0 && (
                        <ul style={{ margin: '6px 0 0 16px', padding: 0 }}>
                          {safetyBlock.violations.map((v, i) => <li key={i} style={{ fontSize: 11 }}>{typeof v === 'string' ? v : JSON.stringify(v)}</li>)}
                        </ul>
                      )}
                    </div>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 10, cursor: 'pointer' }}>
                      <input type="checkbox" checked={understandDestructive}
                        onChange={e => setUnderstandDestructive(e.target.checked)} />
                      I understand this contains destructive operations and want to proceed anyway
                    </label>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button style={{ ...btnPrimary, background: understandDestructive ? '#dc2626' : '#d1d5db', cursor: understandDestructive ? 'pointer' : 'not-allowed' }}
                        onClick={handleApprove} disabled={!understandDestructive || approvalLoading}>
                        {approvalLoading ? '⏳ Checking...' : '⚠ Override & Approve'}
                      </button>
                      <button style={btnGhost} onClick={handleReject} disabled={approvalLoading}>✕ Reject instead</button>
                    </div>
                  </div>
                )}

                {approvalStatus === 'approved' && (
                  <div style={{ fontSize: 12, color: '#166534', fontWeight: 600 }}>✓ Approved — ready to deploy below.</div>
                )}

                {approvalStatus === 'rejected' && (
                  <div style={{ fontSize: 12, color: '#991b1b' }}>
                    ✕ Rejected. Go back to the Data model tab and regenerate, adjusting gap resolutions if needed.
                  </div>
                )}

                {approvalError && (
                  <div style={{ ...errBox, marginTop: 10 }}>{approvalError}</div>
                )}
              </div>
            )}

            {(sqlScripts || []).length > 0 && !deployResult && approvalStatus === 'approved' && (
              <div style={{ ...card, marginTop: 16 }}>
                <div style={sectionLabel}>Deploy configuration</div>
                <div style={{ fontSize: 12, color: '#888', marginBottom: 10 }}>
                  These scripts read from staging tables. Pick the source system connector so
                  AIBridge knows where to extract the underlying data from before loading the warehouse.
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                  <div>
                    <label style={labelStyle}>Source system connector</label>
                    <select style={inp} value={deploySourceConnector}
                      onChange={e => setDeploySourceConnector(e.target.value)}>
                      <option value="">— Select connector —</option>
                      {connectors.map(c => (
                        <option key={c.id} value={c.id}>
                          {c.name} — {c.connector_type} / {c.host}/{c.database_name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label style={labelStyle}>Source schema</label>
                    <input style={inp} value={conn.source_schema}
                      onChange={e => setConn(c => ({ ...c, source_schema: e.target.value }))} placeholder="raw" />
                  </div>
                </div>
                {derivedSourceTables.length > 0 && (
                  <div style={{ fontSize: 11, color: '#888' }}>
                    Tables to extract: <span style={{ fontFamily: 'monospace' }}>{derivedSourceTables.join(', ')}</span>
                  </div>
                )}
              </div>
            )}

            {deployError && (
              <div style={{ ...errBox, marginTop: 12 }}>
                {deployError}
                <button style={{ float: 'right', background: 'none', border: 'none', cursor: 'pointer', color: '#991b1b' }} onClick={() => setDeployError(null)}>✕</button>
              </div>
            )}

            {deployResult && (
              <div style={{ marginTop: 16 }}>
                <div style={{
                  ...card, marginBottom: 12,
                  background: deployResult.success ? '#f0fdf4' : '#fef7ed',
                  borderColor: deployResult.success ? '#86efac' : '#fdba74'
                }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: deployResult.success ? '#166534' : '#9a3412' }}>
                    {deployResult.success
                      ? `✅ All ${(deployResult.pipelines || []).length} pipeline(s) deployed successfully`
                      : `⚠ ${(deployResult.pipelines || []).filter(p => p.success).length}/${(deployResult.pipelines || []).length} pipeline(s) succeeded`}
                  </div>
                  <div style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
                    Each table below ran as its own independent pipeline — a failure in one does not affect the others.
                  </div>
                </div>

                {(deployResult.pipelines || []).map((p, i) => (
                  <div key={i} style={{
                    ...card, marginBottom: 8,
                    background: p.success ? '#fff' : '#fef2f2',
                    borderColor: p.success ? '#e5e7eb' : '#fca5a5'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 14 }}>{p.success ? '✅' : '✗'}</span>
                      <span style={{ fontSize: 12, fontWeight: 600, fontFamily: 'monospace' }}>{p.table}</span>
                      <span style={{ fontSize: 10, color: '#888' }}>({p.mapping_name})</span>
                      {!p.success && p.stage && (
                        <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 20, background: '#fee2e2', color: '#991b1b', marginLeft: 'auto' }}>failed: {p.stage}</span>
                      )}
                    </div>
                    {p.error && <div style={{ fontSize: 11, color: '#991b1b', marginTop: 4 }}>{p.error}</div>}
                    {p.warehouse && (
                      <div style={{ fontSize: 11, color: '#555', marginTop: 4 }}>Rows loaded: {p.warehouse.total_rows ?? 'n/a'}</div>
                    )}
                    {p.quality && (
                      <div style={{ fontSize: 11, color: '#555' }}>Quality: {p.quality.status} ({p.quality.score}%)</div>
                    )}
                    <div style={{ fontSize: 10, color: '#aaa', marginTop: 4 }}>Pipeline ID: {p.pipeline_id}</div>
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 20 }}>
              {!deployResult ? (
                <button style={{ ...btnPrimary, background: '#534AB7', opacity: deployLoading ? 0.6 : 1 }}
                  onClick={handleDeploy} disabled={(sqlScripts || []).length === 0 || deployLoading || approvalStatus !== 'approved'}>
                  {deployLoading ? '⏳ Deploying...' : '▶ Deploy to warehouse'}
                </button>
              ) : (
                <button style={btnGhost} onClick={() => setDeployResult(null)}>Deploy again</button>
              )}
              <button style={btnGhost} onClick={() => goTo(2)}>← Back to data model</button>
              <button style={btnGhost}>Export docs</button>
            </div>
          </div>
        )}
      </PageBody>
    </>
  )
}

const card        = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 10 }
const errBox      = { background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#991b1b', marginBottom: 10 }
const sectionLabel = { fontSize: 11, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }
const labelStyle  = { display: 'block', fontSize: 11, fontWeight: 500, color: '#374151', marginBottom: 4 }
const inp         = { width: '100%', padding: '7px 10px', fontSize: 12, border: '1px solid #d1d5db', borderRadius: 6, boxSizing: 'border-box', background: '#f9fafb', color: '#374151' }
const btnPrimary  = { padding: '8px 20px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 12, cursor: 'pointer', fontWeight: 500 }
const btnGhost    = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 12, cursor: 'pointer' }
