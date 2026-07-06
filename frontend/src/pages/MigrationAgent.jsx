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
  const [uploadMode, setUploadMode]   = useState('repository')  // repository | individual
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)
  const [activeTab, setActiveTab]     = useState('model')
  const [uploadedFiles, setUploadedFiles] = useState([])
  const [scanResult, setScanResult]   = useState(null)
  const [resolvedGaps, setResolvedGaps] = useState({})
  const fileRef = useRef(null)

  const [conn, setConn] = useState({
    host: '', port: '5432', database: '', username: '', password: '',
    warehouse_schema: 'warehouse', connector_type: 'postgres'
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
                <div>
                  <label style={labelStyle}>Warehouse schema</label>
                  <input style={inp} value={conn.warehouse_schema}
                    onChange={e => setConn(c => ({ ...c, warehouse_schema: e.target.value }))} />
                </div>
              </div>
            </div>

            {/* File upload section — import mode only */}
            {subMode === 'import' && (
              <div style={card}>
                <div style={sectionLabel}>Upload mapping files</div>

                {/* Upload mode selector */}
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
                      desc: 'Upload one mapping file per dim/fact table. Supports Informatica XML, dbt YML, SSIS, ODI, BRD.',
                      accepts: '.xml,.yml,.yaml,.dtsx,.pdf,.docx'
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

                {/* Upload zone */}
                <input ref={fileRef} type="file"
                  multiple={uploadMode === 'individual'}
                  accept={uploadMode === 'repository' ? '.xml' : '.xml,.yml,.yaml,.dtsx,.pdf,.docx'}
                  style={{ display: 'none' }} onChange={handleFileUpload} />

                <div style={{ border: '1.5px dashed #d1d5db', borderRadius: 8, padding: 20, textAlign: 'center', cursor: 'pointer', background: '#f9fafb' }}
                  onClick={() => fileRef.current?.click()}>
                  <i className="ti ti-upload" style={{ fontSize: 24, color: '#aaa' }} />
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#374151', marginTop: 8 }}>
                    {uploadMode === 'repository' ? 'Drop Informatica Repository XML here' : 'Drop mapping files here or click to browse'}
                  </div>
                  <div style={{ fontSize: 11, color: '#aaa', marginTop: 4 }}>
                    {uploadMode === 'repository' ? 'One .xml file — all mappings extracted automatically' : 'Informatica XML · dbt YML · SSIS dtsx · ODI xml · BRD PDF/Word'}
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
              <button style={{ ...btnPrimary, background: '#534AB7' }} onClick={handleScan} disabled={loading || !conn.host}>
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
                  { id: 'gaps',     label: `⚠️ Gaps (${(scanResult.gaps || []).length})` },
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
                  <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                    <button style={{ ...btnPrimary, background: '#534AB7' }} onClick={() => goTo(3)}>Generate SQL scripts →</button>
                    {(scanResult.gaps || []).length > 0 && (
                      <button style={btnGhost} onClick={() => setActiveTab('gaps')}>Resolve {scanResult.gaps.length} gaps first</button>
                    )}
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
                  {(scanResult.gaps || []).length === 0 ? (
                    <div style={{ ...card, background: '#EAF3DE', borderColor: '#a7d9a0', textAlign: 'center', padding: 24 }}>
                      <div style={{ fontSize: 16 }}>✅</div>
                      <div style={{ fontSize: 13, color: '#27500A', fontWeight: 600, marginTop: 6 }}>No gaps — all columns are mapped</div>
                    </div>
                  ) : (
                    <div style={{ ...card, borderColor: '#f5c08a' }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: '#854F0B', marginBottom: 12 }}>⚠️ {(scanResult.gaps || []).length} gaps need your input</div>
                      {(scanResult.gaps || []).map((g, i) => (
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

        {/* ── Step 3: Generate & deploy ── */}
        {step === 3 && (
          <div style={{ maxWidth: 520, margin: '0 auto', textAlign: 'center' }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>✅</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: '#111', marginBottom: 8 }}>Migration complete</div>
            <div style={{ fontSize: 13, color: '#888', marginBottom: 24 }}>
              SQL scripts generated and ready to deploy. Your existing warehouse is untouched.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 24 }}>
              {[
                { label: 'Scripts generated', val: (scanResult?.tables || []).length },
                { label: 'Tables mapped',     val: (scanResult?.tables || []).length },
                { label: 'Gaps resolved',     val: `${Object.keys(resolvedGaps).length}/${(scanResult?.gaps || []).length}` },
              ].map(m => (
                <div key={m.label} style={{ background: '#f9fafb', borderRadius: 8, padding: 12 }}>
                  <div style={{ fontSize: 11, color: '#888' }}>{m.label}</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: '#111' }}>{m.val}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              <button style={{ ...btnPrimary, background: '#534AB7' }}>▶ Deploy to warehouse</button>
              <button style={btnGhost}>View SQL scripts</button>
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
