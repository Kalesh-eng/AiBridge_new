/**
 * Dashboard.jsx
 * Home screen with:
 * - Pipeline health metrics
 * - Auto-generated BI charts from warehouse data
 * - Quick actions
 * - Recent run history
 */

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../components/AuthContext'
import { pipelineAPI } from '../api/api'
import { Spinner, EmptyState } from '../components/ErrorBoundary'
import api from '../api/api'

export default function Dashboard() {
  const { user }    = useAuth()
  const navigate    = useNavigate()
  const [pipelines, setPipelines] = useState([])
  const [runs,      setRuns]      = useState([])
  const [charts,    setCharts]    = useState([])
  const [loading,   setLoading]   = useState(true)
  const [chartsLoading, setChartsLoading] = useState(false)
  const [connector, setConnector] = useState(null)

  const hour     = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const name     = user?.full_name?.split(' ')[0] || user?.email?.split('@')[0] || 'there'

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      // Load pipelines
      const pr = await pipelineAPI.list()
      const pl = pr.data.pipelines || []
      setPipelines(pl)

      // Load recent runs for first pipeline
      if (pl.length > 0) {
        const rr = await pipelineAPI.getRuns(pl[0].id)
        setRuns((rr.data.runs || []).slice(0, 5))
      }

      // Load connector for charts
      const cr = await api.get('/connector/list')
      const connectors = cr.data.connectors || []
      if (connectors.length > 0) {
        setConnector(connectors[0])
        loadCharts(connectors[0].id, pl)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const loadCharts = async (connectorId, pipelines) => {
    if (!connectorId) return
    setChartsLoading(true)
    const chartQueries = [
      {
        id:    'monthly_revenue',
        title: 'Monthly Revenue',
        icon:  '📈',
        sql:   `SELECT TO_CHAR(order_date,'Mon YYYY') AS month,
                       ROUND(SUM(line_total)::numeric, 0) AS revenue
                FROM warehouse.fact_sales
                GROUP BY DATE_TRUNC('month', order_date), TO_CHAR(order_date,'Mon YYYY')
                ORDER BY DATE_TRUNC('month', order_date) LIMIT 12`,
        type:  'bar',
        xKey:  'month',
        yKey:  'revenue',
        color: '#185FA5'
      },
      {
        id:    'sales_by_category',
        title: 'Sales by Category',
        icon:  '🛒',
        sql:   `SELECT p.category, ROUND(SUM(f.line_total)::numeric, 0) AS total
                FROM warehouse.fact_sales f
                JOIN warehouse.dim_product p ON p.product_key = f.product_key
                GROUP BY p.category ORDER BY total DESC LIMIT 8`,
        type:  'bar',
        xKey:  'category',
        yKey:  'total',
        color: '#534AB7'
      },
      {
        id:    'top_customers',
        title: 'Top 5 Customers',
        icon:  '👥',
        sql:   `SELECT c.customer_name, ROUND(SUM(f.line_total)::numeric, 0) AS revenue
                FROM warehouse.fact_sales f
                JOIN warehouse.dim_customer c ON c.customer_key = f.customer_key
                WHERE c.is_current = TRUE
                GROUP BY c.customer_name ORDER BY revenue DESC LIMIT 5`,
        type:  'bar',
        xKey:  'customer_name',
        yKey:  'revenue',
        color: '#3B6D11'
      },
      {
        id:    'payment_methods',
        title: 'Payment Methods',
        icon:  '💳',
        sql:   `SELECT method, COUNT(*) AS count,
                       ROUND(SUM(amount)::numeric, 0) AS total
                FROM warehouse.fact_payments
                GROUP BY method ORDER BY total DESC`,
        type:  'bar',
        xKey:  'method',
        yKey:  'total',
        color: '#854F0B'
      }
    ]

    const results = []
    for (const q of chartQueries) {
      try {
        const r = await api.post('/sql/run', {
          sql:          q.sql,
          connector_id: connectorId
        })
        if (r.data.success && r.data.rows?.length > 0) {
          results.push({
            ...q,
            columns: r.data.columns,
            rows:    r.data.rows,
            total:   r.data.row_count
          })
        }
      } catch (e) {
        // Table might not exist yet — skip silently
      }
    }
    setCharts(results)
    setChartsLoading(false)
  }

  const successCount = runs.filter(r => r.status === 'success').length
  const totalRows    = runs.reduce((s, r) => s + (r.rows_loaded || 0), 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* Topbar */}
      <div style={{ padding: '14px 20px', borderBottom: '1px solid #e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, color: '#111' }}>
            {greeting}, {name}! 👋
          </div>
          <div style={{ fontSize: 11, color: '#888', marginTop: 2 }}>
            {user?.workspace?.name} · {new Date().toLocaleDateString('en-IN', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={btnPrimary} onClick={() => navigate('/agent')}>
            + Run ETL Agent
          </button>
          <button style={btnGhost} onClick={() => navigate('/analytics')}>
            📊 Analytics
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>

        {loading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
            <Spinner size={32} />
          </div>
        )}

        {!loading && (
          <>
            {/* KPI metrics */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: 22 }}>
              <KPI val={pipelines.length}                   lbl="Pipelines"      color="#185FA5" icon="⚙️" />
              <KPI val={runs.length > 0 ? successCount : 0} lbl="Successful runs" color="#3B6D11" icon="✓"  />
              <KPI val={totalRows.toLocaleString()}          lbl="Rows loaded"    color="#534AB7" icon="📦" />
              <KPI val={charts.length > 0 ? 'Live' : 'None'} lbl="BI charts"     color="#854F0B" icon="📈" />
            </div>

            {/* No pipeline state */}
            {pipelines.length === 0 && (
              <div style={{ background: '#f9fafb', border: '1px dashed #e5e7eb', borderRadius: 12, padding: 40, textAlign: 'center', marginBottom: 20 }}>
                <div style={{ fontSize: 48, marginBottom: 12 }}>🚀</div>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>Build your first data warehouse</div>
                <div style={{ fontSize: 13, color: '#888', marginBottom: 20, maxWidth: 400, margin: '0 auto 20px' }}>
                  Run the ETL Agent to connect your database, generate a star schema, and execute your first pipeline automatically.
                </div>
                <button style={{ ...btnPrimary, fontSize: 13, padding: '10px 24px' }} onClick={() => navigate('/agent')}>
                  Run ETL Agent →
                </button>
              </div>
            )}

            {/* BI Charts */}
            {chartsLoading && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '20px 0', color: '#888', fontSize: 13 }}>
                <Spinner size={16} /> Loading charts from warehouse...
              </div>
            )}

            {charts.length > 0 && (
              <>
                <div style={sectionTitle}>
                  📊 Live analytics — from your warehouse
                  <span style={{ fontSize: 10, color: '#888', fontWeight: 400, marginLeft: 8 }}>
                    Auto-generated from warehouse.fact_* tables
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 14, marginBottom: 22 }}>
                  {charts.map(chart => (
                    <ChartCard key={chart.id} chart={chart} />
                  ))}
                </div>
              </>
            )}

            {!chartsLoading && charts.length === 0 && pipelines.length > 0 && (
              <div style={{ background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 8, padding: '16px 20px', marginBottom: 20, fontSize: 12, color: '#888' }}>
                📊 Charts will appear here after you execute a pipeline and load data into the warehouse.
                <button style={{ ...btnGhost, marginLeft: 12, fontSize: 11 }} onClick={() => navigate('/pipelines')}>
                  Go to Pipelines →
                </button>
              </div>
            )}

            {/* Recent runs */}
            {runs.length > 0 && (
              <>
                <div style={sectionTitle}>Recent pipeline runs</div>
                {runs.map(r => (
                  <div key={r.id} style={card}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ fontSize: 12, fontFamily: 'monospace', color: '#555' }}>{r.run_id}</div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {r.rows_loaded > 0 && (
                          <span style={{ fontSize: 11, color: '#888' }}>{r.rows_loaded.toLocaleString()} rows</span>
                        )}
                        <span style={r.status === 'success' ? chipGreen : r.status === 'running' ? chipBlue : chipRed}>
                          {r.status}
                        </span>
                      </div>
                    </div>
                    <div style={{ fontSize: 10, color: '#aaa', marginTop: 3 }}>
                      {r.started_at ? new Date(r.started_at).toLocaleString() : '—'}
                    </div>
                  </div>
                ))}
                <button style={btnGhost} onClick={() => navigate('/pipelines')}>
                  View all runs →
                </button>
              </>
            )}

          </>
        )}
      </div>
    </div>
  )
}

// ── Chart card component ──────────────────────────────────────────────────────

function ChartCard({ chart }) {
  const navigate = useNavigate()
  const rows     = chart.rows || []
  const xIdx     = chart.columns.indexOf(chart.xKey)
  const yIdx     = chart.columns.indexOf(chart.yKey)
  const maxVal   = Math.max(...rows.map(r => parseFloat(r[yIdx]) || 0), 1)

  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 10, overflow: 'hidden', background: '#fff' }}>
      {/* Chart header */}
      <div style={{ padding: '12px 14px', borderBottom: '1px solid #f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#111', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span>{chart.icon}</span> {chart.title}
        </div>
        <button style={{ ...btnGhost, fontSize: 10, padding: '3px 8px' }} onClick={() => navigate('/analytics')}>
          Explore →
        </button>
      </div>

      {/* Bar chart */}
      <div style={{ padding: '14px' }}>
        {rows.map((row, i) => {
          const label = String(row[xIdx] || '')
          const val   = parseFloat(row[yIdx]) || 0
          const pct   = (val / maxVal) * 100
          const display = val >= 1000
            ? val >= 100000
              ? `₹${(val/100000).toFixed(1)}L`
              : `₹${(val/1000).toFixed(0)}K`
            : String(val)

          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <div style={{ width: 90, fontSize: 10, color: '#555', textAlign: 'right', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                title={label}>
                {label}
              </div>
              <div style={{ flex: 1, background: '#f3f4f6', borderRadius: 4, height: 20, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: chart.color, borderRadius: 4, minWidth: 4, transition: 'width .6s' }} />
              </div>
              <div style={{ width: 50, fontSize: 10, color: chart.color, fontWeight: 600, flexShrink: 0, textAlign: 'right' }}>
                {display}
              </div>
            </div>
          )
        })}
      </div>

      {/* Chart footer */}
      <div style={{ padding: '6px 14px', background: '#f9fafb', borderTop: '1px solid #f3f4f6', fontSize: 9, color: '#aaa', fontFamily: 'monospace' }}>
        {chart.sql.substring(0, 60)}...
      </div>
    </div>
  )
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KPI({ val, lbl, color, icon }) {
  return (
    <div style={{ background: '#f9fafb', borderRadius: 10, padding: '14px 16px', borderLeft: `3px solid ${color}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 16 }}>{icon}</span>
        <span style={{ fontSize: 22, fontWeight: 700, color }}>{val}</span>
      </div>
      <div style={{ fontSize: 11, color: '#888' }}>{lbl}</div>
    </div>
  )
}

const sectionTitle = { fontSize: 11, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 10, display: 'flex', alignItems: 'center' }
const card         = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 14px', marginBottom: 6, cursor: 'pointer' }
const chipGreen    = { background: '#EAF3DE', color: '#3B6D11', padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }
const chipBlue     = { background: '#E6F1FB', color: '#185FA5', padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }
const chipRed      = { background: '#FCEBEB', color: '#A32D2D', padding: '2px 8px', borderRadius: 20, fontSize: 10, fontWeight: 500 }
const btnPrimary   = { padding: '7px 14px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer', fontWeight: 500 }
const btnGhost     = { padding: '7px 14px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
