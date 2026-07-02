/**
 * Cost.jsx — AI Cost Tracking dashboard
 * Shows total spend, token usage, peak vs off-peak breakdown,
 * per-agent costs, daily trend, and recent call log.
 */

import { useState, useEffect } from 'react'
import { PageHeader, PageBody } from '../components/Layout'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell
} from 'recharts'
import api from '../api/api'

const COLORS = ['#185FA5','#3B6D11','#854F0B','#534AB7','#A32D2D','#0F6E56']

export default function Cost() {
  const [summary,   setSummary]   = useState(null)
  const [calls,     setCalls]     = useState([])
  const [pricing,   setPricing]   = useState(null)
  const [days,      setDays]      = useState(30)
  const [loading,   setLoading]   = useState(true)
  const [tab,       setTab]       = useState('overview')  // overview | calls | pricing

  useEffect(() => { load() }, [days])

  const load = async () => {
    setLoading(true)
    try {
      const [sRes, cRes, pRes] = await Promise.all([
        api.get(`/cost/summary?days=${days}`),
        api.get('/cost/calls?limit=100'),
        api.get('/cost/pricing'),
      ])
      setSummary(sRes.data)
      setCalls(cRes.data.calls || [])
      setPricing(pRes.data)
    } catch (e) {
      console.error('Cost load error:', e)
    }
    setLoading(false)
  }

  const fmt = (n) => n === undefined || n === null ? '0' : Number(n).toLocaleString()
  const fmtCost = (n) => `$${(Number(n) || 0).toFixed(4)}`
  const fmtCostFull = (n) => `$${(Number(n) || 0).toFixed(6)}`

  return (
    <>
      <PageHeader
        title="AI Cost Tracking"
        subtitle="Token usage, spend, peak/off-peak breakdown across all AI calls"
      />
      <PageBody>
        {/* Period selector */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 16, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: '#888' }}>Period:</span>
          {[7, 30, 90].map(d => (
            <button key={d}
              style={{ padding: '4px 12px', fontSize: 10, borderRadius: 6, cursor: 'pointer',
                background: days === d ? '#185FA5' : '#fff',
                color:      days === d ? '#fff' : '#555',
                border: `1px solid ${days === d ? '#185FA5' : '#d1d5db'}` }}
              onClick={() => setDays(d)}>
              {d} days
            </button>
          ))}
          {pricing && (
            <span style={{ marginLeft: 'auto', fontSize: 11,
              color: pricing.is_peak_now ? '#A32D2D' : '#3B6D11',
              background: pricing.is_peak_now ? '#FCEBEB' : '#EAF3DE',
              padding: '3px 10px', borderRadius: 10, fontWeight: 600 }}>
              {pricing.is_peak_now ? '⚡ PEAK HOURS NOW (2×)' : '✓ Off-peak hours'}
              {' '}<span style={{ fontWeight: 400, opacity: .8 }}>UTC {pricing.utc_hour}:00</span>
            </span>
          )}
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid #e5e7eb' }}>
          {[
            { id: 'overview', label: '📊 Overview' },
            { id: 'calls',    label: '📋 Call Log' },
            { id: 'pricing',  label: '💲 Pricing' },
          ].map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              style={{ padding: '7px 14px', fontSize: 11, cursor: 'pointer', border: 'none',
                borderBottom: tab === t.id ? '2px solid #185FA5' : '2px solid transparent',
                background: 'transparent',
                color: tab === t.id ? '#185FA5' : '#888', fontWeight: tab === t.id ? 600 : 400 }}>
              {t.label}
            </button>
          ))}
        </div>

        {loading && <div style={{ fontSize: 12, color: '#888' }}>⏳ Loading cost data...</div>}

        {/* ── OVERVIEW ── */}
        {!loading && tab === 'overview' && summary && (
          <>
            {/* KPI cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: 16 }}>
              <KpiCard label="Total spend" value={fmtCost(summary.total_cost)}
                sub={`${fmt(summary.calls)} calls`} color="#185FA5" />
              <KpiCard label="Peak spend" value={fmtCost(summary.peak_cost)}
                sub={summary.total_cost > 0
                  ? `${((summary.peak_cost / summary.total_cost) * 100).toFixed(0)}% of total`
                  : '0%'}
                color="#A32D2D" />
              <KpiCard label="Total tokens" value={fmt(summary.total_tokens)}
                sub={`${fmt(summary.input_tokens)} in / ${fmt(summary.output_tokens)} out`}
                color="#3B6D11" />
              <KpiCard label="Cache hits" value={fmt(summary.cache_hits)}
                sub={summary.calls > 0
                  ? `${((summary.cache_hits / summary.calls) * 100).toFixed(0)}% of calls ($0 cost)`
                  : '—'}
                color="#534AB7" />
            </div>

            {/* Daily trend chart */}
            {summary.daily_trend?.length > 0 && (
              <div style={card}>
                <div style={sectionTitle}>Daily spend — last {Math.min(days, 14)} days</div>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={[...summary.daily_trend].reverse()}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 10 }}
                      tickFormatter={d => d?.slice(5)} />
                    <YAxis tick={{ fontSize: 10 }}
                      tickFormatter={v => `$${v.toFixed(4)}`} />
                    <Tooltip formatter={(v) => [`$${v.toFixed(6)}`, 'Cost']} />
                    <Bar dataKey="cost_usd">
                      {summary.daily_trend.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Per-agent breakdown */}
            {summary.by_agent?.length > 0 && (
              <div style={card}>
                <div style={sectionTitle}>Cost by agent</div>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <thead>
                    <tr>
                      {['Agent', 'Calls', 'Tokens', 'Cost', '% of total'].map(h => (
                        <th key={h} style={th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_agent.map((a, i) => (
                      <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                        <td style={td}>
                          <span style={{ fontFamily: 'monospace', color: '#185FA5' }}>{a.agent}</span>
                        </td>
                        <td style={td}>{fmt(a.calls)}</td>
                        <td style={td}>{fmt(a.tokens)}</td>
                        <td style={td}>{fmtCostFull(a.cost_usd)}</td>
                        <td style={td}>
                          {summary.total_cost > 0
                            ? `${((a.cost_usd / summary.total_cost) * 100).toFixed(1)}%`
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Per-provider breakdown */}
            {summary.by_provider?.length > 0 && (
              <div style={card}>
                <div style={sectionTitle}>Cost by provider</div>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  {summary.by_provider.map((p, i) => (
                    <div key={i} style={{ ...card, flex: '1 1 180px', marginBottom: 0,
                      borderLeft: `3px solid ${COLORS[i % COLORS.length]}` }}>
                      <div style={{ fontSize: 12, fontWeight: 600,
                        color: COLORS[i % COLORS.length] }}>{p.provider}</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: '#111', margin: '4px 0' }}>
                        {fmtCost(p.cost_usd)}
                      </div>
                      <div style={{ fontSize: 10, color: '#888' }}>
                        {fmt(p.calls)} calls · {fmt(p.tokens)} tokens
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {summary.calls === 0 && (
              <div style={emptyBox}>
                No AI calls recorded yet. Run an ETL Agent pipeline to start tracking costs.
              </div>
            )}
          </>
        )}

        {/* ── CALL LOG ── */}
        {!loading && tab === 'calls' && (
          <div style={card}>
            <div style={sectionTitle}>Recent AI calls ({calls.length})</div>
            {calls.length === 0 ? (
              <div style={{ fontSize: 12, color: '#888' }}>No calls recorded yet.</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <thead>
                    <tr>
                      {['Time', 'Provider', 'Agent', 'In', 'Out', 'Cost', 'Peak', 'Cache', 'Duration'].map(h => (
                        <th key={h} style={th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {calls.map((c, i) => (
                      <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                        <td style={td}>
                          <span style={{ fontSize: 10, color: '#888', fontFamily: 'monospace' }}>
                            {c.ts?.slice(11, 19)} UTC
                          </span>
                        </td>
                        <td style={td}>
                          <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 10,
                            background: '#E6F1FB', color: '#185FA5', fontWeight: 600 }}>
                            {c.provider}
                          </span>
                        </td>
                        <td style={td}>
                          <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#534AB7' }}>
                            {c.agent_name || '—'}
                          </span>
                        </td>
                        <td style={td}>{fmt(c.input_tokens)}</td>
                        <td style={td}>{fmt(c.output_tokens)}</td>
                        <td style={{ ...td, fontFamily: 'monospace', color: c.cost_usd > 0.001 ? '#A32D2D' : '#3B6D11' }}>
                          {fmtCostFull(c.cost_usd)}
                        </td>
                        <td style={td}>
                          {c.is_peak
                            ? <span style={{ color: '#A32D2D', fontWeight: 600 }}>⚡ 2×</span>
                            : <span style={{ color: '#aaa' }}>—</span>}
                        </td>
                        <td style={td}>
                          {c.is_cache_hit
                            ? <span style={{ color: '#3B6D11', fontWeight: 600 }}>✓ hit</span>
                            : <span style={{ color: '#aaa' }}>miss</span>}
                        </td>
                        <td style={{ ...td, color: '#888' }}>{c.duration_s?.toFixed(1)}s</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── PRICING ── */}
        {!loading && tab === 'pricing' && pricing && (
          <div>
            <div style={card}>
              <div style={sectionTitle}>Current provider: {pricing.provider}</div>

              {/* Peak status banner */}
              <div style={{
                padding: '10px 14px', borderRadius: 6, marginBottom: 14,
                background: pricing.is_peak_now ? '#FCEBEB' : '#EAF3DE',
                border: `1px solid ${pricing.is_peak_now ? '#fca5a5' : '#a7d9a0'}`
              }}>
                <div style={{ fontSize: 13, fontWeight: 600,
                  color: pricing.is_peak_now ? '#A32D2D' : '#3B6D11' }}>
                  {pricing.is_peak_now ? '⚡ Peak hours active — 2× pricing in effect' : '✓ Off-peak hours — regular pricing'}
                </div>
                <div style={{ fontSize: 11, color: '#555', marginTop: 4 }}>
                  Current UTC hour: {pricing.utc_hour}:00
                </div>
              </div>

              {/* Rate table */}
              <div style={sectionTitle}>Rates (USD per 1M tokens)</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    <th style={th}>Item</th>
                    <th style={th}>Off-peak rate</th>
                    <th style={th}>Peak rate (2×)</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['Input tokens (cache miss)',  pricing.pricing?.input_per_m],
                    ['Input tokens (cache hit)',   pricing.pricing?.input_cached_per_m],
                    ['Output tokens',              pricing.pricing?.output_per_m],
                  ].map(([label, rate], i) => (
                    <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb' }}>
                      <td style={td}>{label}</td>
                      <td style={{ ...td, fontFamily: 'monospace', color: '#3B6D11' }}>
                        ${Number(rate || 0).toFixed(3)}
                      </td>
                      <td style={{ ...td, fontFamily: 'monospace', color: '#A32D2D' }}>
                        ${(Number(rate || 0) * (pricing.pricing?.peak_multiplier || 1)).toFixed(3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* Peak windows */}
              {pricing.peak_windows_utc?.length > 0 && (
                <div style={{ marginTop: 14, padding: '10px 12px', background: '#f9fafb',
                  borderRadius: 6, fontSize: 11 }}>
                  <div style={{ fontWeight: 600, color: '#374151', marginBottom: 4 }}>
                    Peak billing windows (UTC):
                  </div>
                  {pricing.peak_windows_utc.map(([s, e], i) => (
                    <div key={i} style={{ color: '#555' }}>
                      • {String(s).padStart(2,'0')}:00 – {String(e).padStart(2,'0')}:00 UTC
                      <span style={{ color: '#888', marginLeft: 8 }}>
                        (IST: {String((s+5)%24).padStart(2,'0')}:30 – {String((e+5)%24).padStart(2,'0')}:30)
                      </span>
                    </div>
                  ))}
                  <div style={{ marginTop: 6, fontSize: 10, color: '#888' }}>
                    💡 Schedule heavy pipelines outside these windows to halve your AI spend.
                  </div>
                </div>
              )}
            </div>

            {/* Cost estimation */}
            <div style={card}>
              <div style={sectionTitle}>Typical cost per pipeline run</div>
              {[
                { label: 'Schema design (Phase 1)', tokens: 8000,  note: 'SchemaAgent + DataModelAgent' },
                { label: 'SQL generation (Phase 2)', tokens: 6000, note: 'SQLAgent + ValidationAgent' },
                { label: 'NL-to-SQL query',          tokens: 2000, note: 'Single Analytics question' },
                { label: 'Full pipeline run',         tokens: 20000, note: 'All agents combined' },
              ].map((item, i) => {
                const rate = pricing.pricing?.input_per_m || 0
                const outRate = pricing.pricing?.output_per_m || 0
                const offPeak = ((item.tokens * 0.6 / 1e6 * rate) + (item.tokens * 0.4 / 1e6 * outRate))
                const peak    = offPeak * (pricing.pricing?.peak_multiplier || 1)
                return (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10,
                    padding: '7px 0', borderBottom: '1px solid #f3f4f6' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, fontWeight: 500 }}>{item.label}</div>
                      <div style={{ fontSize: 10, color: '#888' }}>{item.note} · ~{fmt(item.tokens)} tokens</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 12, fontFamily: 'monospace', color: '#3B6D11' }}>
                        ${offPeak.toFixed(5)} off-peak
                      </div>
                      <div style={{ fontSize: 11, fontFamily: 'monospace', color: '#A32D2D' }}>
                        ${peak.toFixed(5)} peak
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </PageBody>
    </>
  )
}

function KpiCard({ label, value, sub, color }) {
  return (
    <div style={{ background: '#f9fafb', borderRadius: 8, padding: '12px 14px',
      borderLeft: `3px solid ${color}` }}>
      <div style={{ fontSize: 10, color: '#888', textTransform: 'uppercase',
        letterSpacing: '.04em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color, fontFamily: 'monospace' }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: '#888', marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

const card         = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }
const emptyBox     = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 32, textAlign: 'center', fontSize: 13, color: '#888' }
const sectionTitle = { fontSize: 10, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }
const th           = { textAlign: 'left', padding: '5px 10px', background: '#f9fafb', borderBottom: '1px solid #e5e7eb', fontWeight: 600, color: '#555', fontSize: 10, textTransform: 'uppercase' }
const td           = { padding: '5px 10px', borderBottom: '1px solid #f3f4f6' }
