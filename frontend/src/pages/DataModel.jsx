/**
 * DataModel.jsx
 * Visual star schema with ERD boxes, relationship lines, cardinality.
 *
 * FIXED: handles both old (string) and new (object) data model formats.
 *   foreign_keys may now be {column, references_table, references_column}
 *   attributes  may now be {column, type, source}
 *   measures    may now be {column, type, source, rule}
 *
 * REWRITE: diagram now renders as an absolutely-positioned SVG canvas with
 * the fact table centered and dimension tables arranged radially around it.
 * Each relationship is drawn as a real connector path from the FK row on
 * the fact box to the PK row on its dimension box, with crow's-foot
 * cardinality markers at the correct ends (one bar at the "1" side, a
 * crow's foot at the "many" side) — instead of the old flexbox column of
 * disconnected mini-line widgets.
 */

import { useState, useEffect, useRef, useLayoutEffect } from 'react'
import { pipelineAPI } from '../api/api'
import { PageHeader, PageBody } from '../components/Layout'

// ── Normalizers — pull strings from either string or object form ─────────────

const nameOf = (x) => {
  if (x == null) return ''
  if (typeof x === 'string') return x
  if (typeof x === 'object') return x.column || x.name || ''
  return String(x)
}

const fkRefTable = (fk) => {
  if (typeof fk === 'object' && fk) return fk.references_table || ''
  return ''
}

const fkRefCol = (fk) => {
  if (typeof fk === 'object' && fk) return fk.references_column || ''
  return ''
}


export default function DataModel() {
  const [pipelines, setPipelines] = useState([])
  const [selected,  setSelected]  = useState(null)
  const [model,     setModel]     = useState(null)
  const [schema,    setSchema]    = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [activeRel, setActiveRel] = useState(null)

  useEffect(() => {
    pipelineAPI.list().then(r => {
      const list = r.data.pipelines || []
      setPipelines(list)
      if (list.length > 0) {
        setSelected(list[0])
        setModel(list[0].artifacts?.data_model       || null)
        setSchema(list[0].artifacts?.schema_analysis || null)
      }
    }).finally(() => setLoading(false))
  }, [])

  const selectPipeline = (p) => {
    setSelected(p)
    setModel(p.artifacts?.data_model       || null)
    setSchema(p.artifacts?.schema_analysis || null)
    setActiveRel(null)
  }

  // Match a fact's FK to a dimension table
  const findDim = (dims, fk) => {
    const fkName = nameOf(fk)
    const refTbl = fkRefTable(fk)
    return dims.find(d => {
      // Match by explicit references_table (new format)
      if (refTbl && d.name === refTbl) return true
      // Match by surrogate_key name
      if (d.surrogate_key === fkName) return true
      // Match by table-name derivation: dim_customer ↔ customer_key
      const dimBase = (d.name || '').replace('dim_', '')
      const fkBase  = fkName.replace('_key', '')
      return dimBase === fkBase
    })
  }

  const buildRelationships = (model, schema) => {
    const rels = []
    if (!model) return rels

    const dims = model.dimension_tables || []

    ;(model.fact_tables || []).forEach(fact => {
      ;(fact.foreign_keys || []).forEach(fk => {
        const dim = findDim(dims, fk)
        if (dim) {
          rels.push({
            from:        fact.name,
            to:          dim.name,
            from_type:   'fact',
            to_type:     'dim',
            join_key:    nameOf(fk),
            cardinality: 'many-to-one',
            label:       'N : 1',
            description: `Many ${fact.name} rows reference one ${dim.name}`
          })
        }
      })
    })

    ;(schema?.relationships || []).forEach(rel => {
      rels.push({
        from:        rel.from_table,
        to:          rel.to_table,
        from_type:   'source',
        to_type:     'source',
        join_key:    nameOf(rel.join_key),
        cardinality: rel.cardinality,
        label:       cardinalityLabel(rel.cardinality),
        description: `${rel.from_table} → ${rel.to_table} on ${nameOf(rel.join_key)}`
      })
    })

    return rels
  }

  const cardinalityLabel = (c) => {
    if (!c) return 'N:1'
    if (c.includes('many-to-many')) return 'N : M'
    if (c.includes('many-to-one'))  return 'N : 1'
    if (c.includes('one-to-many'))  return '1 : N'
    if (c.includes('one-to-one'))   return '1 : 1'
    return 'N : 1'
  }

  const relationships = model ? buildRelationships(model, schema) : []

  return (
    <>
      <PageHeader
        title="Data model"
        subtitle="Star schema with entity relationships and cardinality indicators"
      />
      <PageBody>
        {loading && <div style={muted}>Loading...</div>}

        {!loading && pipelines.length === 0 && (
          <div style={emptyBox}>No pipelines yet. Run the ETL Agent first.</div>
        )}

        {pipelines.length > 1 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
            {pipelines.map(p => (
              <button key={p.id}
                style={selected?.id === p.id ? btnActive : btnGhost}
                onClick={() => selectPipeline(p)}>
                {p.name}
              </button>
            ))}
          </div>
        )}

        {model && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, marginBottom: 20 }}>
              <Metric val={model.fact_tables?.length       || 0} lbl="Fact tables"    color="#185FA5" />
              <Metric val={model.dimension_tables?.length  || 0} lbl="Dimensions"     color="#534AB7" />
              <Metric val={relationships.filter(r=>r.from_type==='fact').length} lbl="Relationships" color="#3B6D11" />
              <Metric val={getTotalColumns(model)}               lbl="Total columns"  color="#854F0B" />
            </div>

            <div style={sectionTitle}>Star schema — entity relationship diagram</div>

            <ErdCanvas
              model={model}
              relationships={relationships}
              findDim={findDim}
              activeRel={activeRel}
              setActiveRel={setActiveRel}
            />

            {/* Relationship detail */}
            {activeRel && (
              <div style={{ ...card, borderLeft: '3px solid #185FA5', marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={sectionTitle}>Relationship detail</div>
                  <button style={{ ...btnGhost, padding: '2px 8px', fontSize: 10 }} onClick={() => setActiveRel(null)}>✕ Close</button>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 10, alignItems: 'center' }}>
                  <div style={{ background: '#E6F1FB', borderRadius: 6, padding: '8px 12px', textAlign: 'center' }}>
                    <div style={{ fontSize: 10, color: '#888', marginBottom: 3 }}>From</div>
                    <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600, color: '#185FA5' }}>{activeRel.from}</div>
                  </div>
                  <div style={{ textAlign: 'center' }}>
                    <CardinalitySymbol cardinality={activeRel.cardinality} />
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#111', marginTop: 4 }}>{activeRel.label}</div>
                    <div style={{ fontSize: 9, color: '#888', fontFamily: 'monospace' }}>on {activeRel.join_key}</div>
                  </div>
                  <div style={{ background: '#EEEDFE', borderRadius: 6, padding: '8px 12px', textAlign: 'center' }}>
                    <div style={{ fontSize: 10, color: '#888', marginBottom: 3 }}>To</div>
                    <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600, color: '#534AB7' }}>{activeRel.to}</div>
                  </div>
                </div>
                <div style={{ fontSize: 11, color: '#555', marginTop: 10, padding: '6px 10px', background: '#f9fafb', borderRadius: 5 }}>
                  {getCardinalityExplanation(activeRel.cardinality, activeRel.from, activeRel.to)}
                </div>
              </div>
            )}

            {/* All relationships table */}
            <div style={sectionTitle}>All relationships — click to highlight</div>
            <div style={card}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 1fr 70px 80px', gap: 8, padding: '4px 0', borderBottom: '1px solid #e5e7eb', fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase' }}>
                <div>From table</div><div></div><div>To table</div><div>Join key</div><div>Cardinality</div>
              </div>
              {relationships.filter(r => r.from_type === 'fact').map((rel, i) => (
                <div key={i}
                  style={{ display: 'grid', gridTemplateColumns: '1fr 80px 1fr 70px 80px', gap: 8, padding: '7px 0', borderBottom: '1px solid #f3f4f6', alignItems: 'center', cursor: 'pointer', background: activeRel?.join_key === rel.join_key ? '#f0f9ff' : 'transparent', borderRadius: 4 }}
                  onClick={() => setActiveRel(activeRel?.join_key === rel.join_key ? null : rel)}
                >
                  <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#185FA5', fontWeight: 500 }}>{rel.from}</div>
                  <div style={{ textAlign: 'center' }}>
                    <span style={{ fontSize: 16, color: '#aaa' }}>{getArrowSymbol(rel.cardinality)}</span>
                  </div>
                  <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#534AB7', fontWeight: 500 }}>{rel.to}</div>
                  <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#888' }}>{rel.join_key}</div>
                  <div>
                    <span style={{ ...cardinalityChip(rel.cardinality), fontSize: 10 }}>{rel.label}</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Source relationships */}
            {schema?.relationships?.length > 0 && (
              <>
                <div style={sectionTitle}>Source schema relationships</div>
                <div style={card}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 1fr 80px 80px', gap: 8, padding: '4px 0', borderBottom: '1px solid #e5e7eb', fontSize: 10, fontWeight: 600, color: '#888', textTransform: 'uppercase' }}>
                    <div>From table</div><div></div><div>To table</div><div>Join key</div><div>Cardinality</div>
                  </div>
                  {(schema.relationships || []).map((rel, i) => (
                    <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 80px 1fr 80px 80px', gap: 8, padding: '6px 0', borderBottom: '1px solid #f3f4f6', alignItems: 'center' }}>
                      <div style={{ fontFamily: 'monospace', fontSize: 11 }}>{rel.from_table}</div>
                      <div style={{ textAlign: 'center', fontSize: 16, color: '#aaa' }}>{getArrowSymbol(rel.cardinality)}</div>
                      <div style={{ fontFamily: 'monospace', fontSize: 11 }}>{rel.to_table}</div>
                      <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#888' }}>{nameOf(rel.join_key)}</div>
                      <div><span style={{ ...cardinalityChip(rel.cardinality), fontSize: 10 }}>{cardinalityLabel(rel.cardinality)}</span></div>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Modeling decisions */}
            {model.modeling_decisions?.length > 0 && (
              <>
                <div style={sectionTitle}>AI modeling decisions</div>
                <div style={card}>
                  {model.modeling_decisions.map((d, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: i < model.modeling_decisions.length - 1 ? '1px solid #f3f4f6' : 'none', fontSize: 12 }}>
                      <span style={{ color: '#3B6D11', flexShrink: 0 }}>✓</span>
                      <span>{typeof d === 'string' ? d : JSON.stringify(d)}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

          </>
        )}

        {selected && !model && (
          <div style={emptyBox}>No data model found. Run the ETL Agent to generate one.</div>
        )}

      </PageBody>
    </>
  )
}

// ── ERD Canvas — centered fact, dims arranged radially, real SVG connectors ──

const BOX_WIDTH    = 190
const ROW_HEIGHT    = 18
const HEADER_HEIGHT = 38
const FOOTER_HEIGHT = 18

function buildErdTable(kind, t) {
  if (kind === 'fact') {
    return {
      name: t.name,
      type: 'fact',
      columns: [
        { name: nameOf(t.surrogate_key) || (t.name.replace('fact_', '') + '_key'), badge: 'PK' },
        ...((t.foreign_keys || []).map(fk => ({ name: nameOf(fk), badge: 'FK', fk }))),
        ...((t.measures || []).map(m => ({ name: nameOf(m), badge: 'M' })))
      ],
      footer: `Grain: ${t.grain || 'one row per event'}`
    }
  }
  return {
    name: t.name,
    type: 'dim',
    columns: [
      { name: nameOf(t.surrogate_key), badge: 'PK' },
      { name: nameOf(t.natural_key_column) || 'source_id', badge: 'NK' },
      ...((t.attributes || []).map(a => ({ name: nameOf(a), badge: null }))),
      { name: `SCD Type ${t.scd_type || '1'}`, badge: 'SCD' }
    ],
    footer: `← ${t.source_table || ''}`
  }
}

function boxHeight(table) {
  return HEADER_HEIGHT + table.columns.length * ROW_HEIGHT + FOOTER_HEIGHT
}

// Arrange the fact table centered, dimension tables distributed evenly
// around it on left and right columns (matches the reference layout: a
// central fact box flanked by dimension boxes, connected by clean paths).
// Horizontal spacing is content-driven — a fixed gap from the fact table —
// rather than stretching dimension columns out to the edges of whatever
// width the container happens to be, which left large dead space on wide
// screens. The whole diagram is then centered within the available width.
function layoutPositions(factTable, dimTables, canvasWidth) {
  const positions = {}
  const gapX = 56    // horizontal gap between fact box and each dim column
  const gapY = 18     // vertical gap between stacked dim boxes

  const factH = boxHeight(factTable)
  const dimHeights = dimTables.map(boxHeight)

  const leftCount  = Math.ceil(dimTables.length / 2)
  const rightCount = dimTables.length - leftCount
  const leftDims   = dimTables.slice(0, leftCount)
  const rightDims  = dimTables.slice(leftCount)
  const leftHeights  = dimHeights.slice(0, leftCount)
  const rightHeights = dimHeights.slice(leftCount)

  const leftTotalH  = leftHeights.reduce((a, b) => a + b, 0) + gapY * Math.max(0, leftHeights.length - 1)
  const rightTotalH = rightHeights.reduce((a, b) => a + b, 0) + gapY * Math.max(0, rightHeights.length - 1)
  const maxSideH = Math.max(leftTotalH, rightTotalH, factH)

  // Natural (content) width of the whole diagram: left col + gap + fact +
  // gap + right col. Center this block within canvasWidth, but never let
  // it be wider than the container itself.
  const hasLeft  = leftDims.length > 0
  const hasRight = rightDims.length > 0
  const contentWidth =
    (hasLeft ? BOX_WIDTH + gapX : 0) +
    BOX_WIDTH +
    (hasRight ? BOX_WIDTH + gapX : 0)
  const startX = Math.max(0, (canvasWidth - contentWidth) / 2)

  const factX = startX + (hasLeft ? BOX_WIDTH + gapX : 0)
  const factY = (maxSideH - factH) / 2

  positions[factTable.name] = { x: factX, y: factY, w: BOX_WIDTH, h: factH, table: factTable }

  const leftX = startX
  let cy = (maxSideH - leftTotalH) / 2
  leftDims.forEach((d, i) => {
    const h = leftHeights[i]
    positions[d.name] = { x: leftX, y: cy, w: BOX_WIDTH, h, table: d }
    cy += h + gapY
  })

  const rightX = factX + BOX_WIDTH + gapX
  cy = (maxSideH - rightTotalH) / 2
  rightDims.forEach((d, i) => {
    const h = rightHeights[i]
    positions[d.name] = { x: rightX, y: cy, w: BOX_WIDTH, h, table: d }
    cy += h + gapY
  })

  return { positions, canvasHeight: maxSideH + 24 }
}

// y-offset of a specific column row inside its box (center of that row)
function rowOffsetY(table, predicate) {
  const idx = table.columns.findIndex(predicate)
  const safeIdx = idx === -1 ? 0 : idx
  return HEADER_HEIGHT + safeIdx * ROW_HEIGHT + ROW_HEIGHT / 2
}

function ErdCanvas({ model, relationships, findDim, activeRel, setActiveRel }) {
  const containerRef = useRef(null)
  const [canvasWidth, setCanvasWidth] = useState(900)
  // Manual drag offsets per table, layered on top of the computed base
  // layout — lets a user nudge any box without breaking the auto layout
  // for everything else. Cleared per-pipeline by keying on model identity
  // isn't needed since this state naturally resets on remount.
  const [dragOffsets, setDragOffsets] = useState({})
  const dragState = useRef(null) // { name, startX, startY, originX, originY }

  useLayoutEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        setCanvasWidth(Math.max(700, containerRef.current.offsetWidth))
      }
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  const handleDragStart = (name, e) => {
    e.preventDefault()
    const offset = dragOffsets[name] || { dx: 0, dy: 0 }
    dragState.current = {
      name,
      startX: e.clientX,
      startY: e.clientY,
      originDx: offset.dx,
      originDy: offset.dy
    }
    window.addEventListener('pointermove', handleDragMove)
    window.addEventListener('pointerup', handleDragEnd)
  }

  const handleDragMove = (e) => {
    if (!dragState.current) return
    const { name, startX, startY, originDx, originDy } = dragState.current
    const dx = originDx + (e.clientX - startX)
    const dy = originDy + (e.clientY - startY)
    setDragOffsets(prev => ({ ...prev, [name]: { dx, dy } }))
  }

  const handleDragEnd = () => {
    dragState.current = null
    window.removeEventListener('pointermove', handleDragMove)
    window.removeEventListener('pointerup', handleDragEnd)
  }

  const facts = model.fact_tables || []
  const dims  = model.dimension_tables || []
  if (facts.length === 0) {
    return <div style={emptyBox}>No fact tables in this model yet.</div>
  }

  // Single-fact star schema is the common case this view is built for —
  // center that fact and arrange all its related dimensions around it.
  const fact = facts[0]
  const factTable = buildErdTable('fact', fact)
  const relatedDimNames = new Set(
    (fact.foreign_keys || []).map(fk => findDim(dims, fk)?.name).filter(Boolean)
  )
  const dimTables = dims
    .filter(d => relatedDimNames.has(d.name))
    .map(d => buildErdTable('dim', d))

  const { positions: basePositions, canvasHeight } = layoutPositions(factTable, dimTables, canvasWidth)

  // Apply manual drag offsets on top of the computed base positions.
  const positions = {}
  Object.entries(basePositions).forEach(([name, pos]) => {
    const off = dragOffsets[name] || { dx: 0, dy: 0 }
    positions[name] = { ...pos, x: pos.x + off.dx, y: pos.y + off.dy }
  })

  // Build connector paths: one per FK, from the FK row on the fact box to
  // the PK row on its dimension box.
  const connectors = (fact.foreign_keys || []).map((fk, i) => {
    const dim = findDim(dims, fk)
    if (!dim) return null
    const fkName = nameOf(fk)
    const rel = relationships.find(r => r.from === fact.name && r.to === dim.name)
    const factPos = positions[fact.name]
    const dimPos  = positions[dim.name]
    if (!factPos || !dimPos) return null

    const isLeft = dimPos.x < factPos.x

    const factY = factPos.y + rowOffsetY(factTable, c => c.badge === 'FK' && c.name === fkName)
    const factEdgeX = isLeft ? factPos.x : factPos.x + factPos.w

    const dimY = dimPos.y + rowOffsetY(buildErdTable('dim', dim), c => c.badge === 'PK')
    const dimEdgeX = isLeft ? dimPos.x + dimPos.w : dimPos.x

    return {
      key: `${fact.name}-${fkName}-${i}`,
      isLeft,
      x1: dimEdgeX,  y1: dimY,      // "one" side (dimension PK)
      x2: factEdgeX, y2: factY,     // "many" side (fact FK)
      label: rel?.label || 'N : 1',
      cardinality: rel?.cardinality || 'many-to-one',
      rel,
      fkName,
      dimName: dim.name
    }
  }).filter(Boolean)

  // Which (table, column) pairs should render with the highlighted-row
  // style right now, derived from the active relationship.
  const highlightedCells = activeRel
    ? new Set([
        `${activeRel.from}::${activeRel.join_key}`,
        // dimension side highlight: PK row of the matched dim table
        ...connectors
          .filter(c => c.fkName === activeRel.join_key)
          .map(c => `${c.dimName}::__pk__`)
      ])
    : new Set()

  return (
    <div ref={containerRef} style={{ overflowX: 'auto', marginBottom: 20 }}>
      <div style={{ position: 'relative', width: '100%', minWidth: 700, height: canvasHeight }}>
        <svg
          width={canvasWidth}
          height={canvasHeight}
          style={{ position: 'absolute', top: 0, left: 0 }}
        >
          {connectors.map(c => (
            <Connector
              key={c.key}
              {...c}
              active={activeRel?.join_key === c.fkName}
              onClick={() => setActiveRel(activeRel?.join_key === c.fkName ? null : c.rel)}
            />
          ))}
        </svg>

        {Object.values(positions).map(pos => (
          <div
            key={pos.table.name}
            style={{ position: 'absolute', left: pos.x, top: pos.y, width: pos.w }}
          >
            <ErdBox
              table={pos.table}
              active={!!(activeRel && (activeRel.to === pos.table.name || activeRel.from === pos.table.name))}
              highlightedCells={highlightedCells}
              onClick={() => setActiveRel(null)}
              onDragStart={(e) => handleDragStart(pos.table.name, e)}
            />
          </div>
        ))}

        {/* Clickable hit-areas for each connector label, sitting above the SVG */}
        {connectors.map(c => {
          const midX = (c.x1 + c.x2) / 2
          const midY = (c.y1 + c.y2) / 2
          return (
            <div
              key={`label-${c.key}`}
              onClick={() => setActiveRel(activeRel?.join_key === c.fkName ? null : c.rel)}
              title={c.rel?.description}
              style={{
                position: 'absolute',
                left: midX - 20,
                top:  midY - 9,
                width: 40,
                height: 18,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 9,
                fontWeight: 700,
                fontFamily: 'monospace',
                color: activeRel?.join_key === c.fkName ? '#185FA5' : '#888',
                background: '#fff',
                borderRadius: 4,
                cursor: 'pointer',
                border: activeRel?.join_key === c.fkName ? '1px solid #185FA5' : '1px solid transparent'
              }}
            >
              {c.label}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// One real connector path between a dimension's PK row and the fact's FK
// row, with a single-bar "one" marker at the dimension end and a crow's
// foot "many" marker at the fact end — drawn with an orthogonal elbow so
// lines stay clean even when boxes are at different heights. A wider,
// invisible stroke sits underneath the visible line so the path itself
// is a comfortable click target, not just the small label.
function Connector({ x1, y1, x2, y2, isLeft, active, onClick }) {
  const color = active ? '#185FA5' : '#c7cbd1'
  const strokeWidth = active ? 2 : 1.3
  const midX = isLeft ? (x1 + x2) / 2 : (x1 + x2) / 2

  const path = `M ${x1} ${y1} L ${midX} ${y1} L ${midX} ${y2} L ${x2} ${y2}`

  // "One" marker sits just outside the dimension box edge (x1,y1).
  // "Many" (crow's foot) marker sits just outside the fact box edge (x2,y2).
  const oneDir  = isLeft ? 1 : -1   // marker drawn pointing back toward the dim box
  const manyDir = isLeft ? -1 : 1   // marker drawn pointing back toward the fact box

  return (
    <g>
      {/* Wide invisible stroke as the actual click target — the visible
          line is thin (1.3-2px), which is too small to click reliably. */}
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={14}
        style={{ cursor: 'pointer', pointerEvents: 'stroke' }}
        onClick={onClick}
      />
      <path d={path} fill="none" stroke={color} strokeWidth={strokeWidth} style={{ pointerEvents: 'none' }} />
      <OneMarker x={x1} y={y1} dir={oneDir} color={color} />
      <CrowsFootMarker x={x2} y={y2} dir={manyDir} color={color} />
    </g>
  )
}

function OneMarker({ x, y, dir, color }) {
  const d = 5
  return <line x1={x + dir * d} y1={y - 6} x2={x + dir * d} y2={y + 6} stroke={color} strokeWidth="1.5" />
}

function CrowsFootMarker({ x, y, dir, color }) {
  const len = 12
  const spread = 6
  const baseX = x + dir * len
  return (
    <g>
      <line x1={x} y1={y} x2={baseX} y2={y} stroke={color} strokeWidth="1.5" />
      <line x1={baseX} y1={y} x2={x + dir * 2} y2={y - spread} stroke={color} strokeWidth="1.5" />
      <line x1={baseX} y1={y} x2={x + dir * 2} y2={y + spread} stroke={color} strokeWidth="1.5" />
    </g>
  )
}

// ── ERD Box component ────────────────────────────────────────────────────────

function ErdBox({ table, active, highlightedCells, onClick, onDragStart }) {
  const isFact = table.type === 'fact'
  const badgeColors = {
    PK:  { bg: '#E6F1FB', color: '#0C447C', title: 'Primary Key' },
    FK:  { bg: '#EEEDFE', color: '#3C3489', title: 'Foreign Key' },
    M:   { bg: '#EAF3DE', color: '#27500A', title: 'Measure'     },
    NK:  { bg: '#f9fafb', color: '#555',    title: 'Natural Key' },
    SCD: { bg: '#FAEEDA', color: '#633806', title: 'SCD Type'    },
  }
  const cells = highlightedCells || new Set()

  return (
    <div
      onClick={onClick}
      style={{
        border:       `${active ? 2 : 1}px solid ${active ? (isFact ? '#185FA5' : '#534AB7') : '#e5e7eb'}`,
        borderRadius: 8,
        overflow:     'hidden',
        width:        '100%',
        background:   active ? (isFact ? '#EEF5FD' : '#F0EFFE') : '#fff',
        cursor:       'pointer',
        transition:   'border-color .15s, background .15s, box-shadow .15s',
        boxShadow:    active ? '0 2px 8px rgba(0,0,0,.1)' : '0 1px 2px rgba(0,0,0,.04)'
      }}
    >
      <div
        onPointerDown={onDragStart}
        style={{
          padding:    '7px 10px',
          background: isFact ? '#E6F1FB' : '#EEEDFE',
          borderBottom: '1px solid #e5e7eb',
          cursor:     'grab',
          userSelect: 'none'
        }}
        title="Drag to move"
      >
        <div style={{ fontSize: 11, fontWeight: 700, color: isFact ? '#0C447C' : '#3C3489', fontFamily: 'monospace' }}>
          {table.name}
        </div>
        <div style={{ fontSize: 9, color: isFact ? '#185FA5' : '#534AB7', marginTop: 2, opacity: .8 }}>
          {isFact ? '📊 Fact table' : '📋 Dimension table'}
        </div>
      </div>

      {table.columns.map((col, i) => {
        const bc = col.badge ? badgeColors[col.badge] : null
        // A row is highlighted when it's the specific FK column matching
        // the active relationship on a fact box, or the PK row on the
        // dimension box at the other end of that relationship.
        const isHighlighted =
          cells.has(`${table.name}::${col.name}`) ||
          (col.badge === 'PK' && cells.has(`${table.name}::__pk__`))
        return (
          <div key={i} style={{
            display:     'flex',
            alignItems:  'center',
            justifyContent: 'space-between',
            padding:     '3px 10px',
            height:      ROW_HEIGHT - 1,
            boxSizing:   'border-box',
            borderBottom:'1px solid #f3f4f6',
            fontSize:    9,
            fontFamily:  'monospace',
            background:  isHighlighted ? '#FFF3CD' : (bc ? bc.bg : 'transparent'),
            boxShadow:   isHighlighted ? 'inset 2px 0 0 #185FA5' : 'none',
            transition:  'background .15s'
          }}>
            <span style={{ color: bc ? bc.color : '#555', fontWeight: (col.badge === 'PK' || col.badge === 'FK' || isHighlighted) ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {col.name}
            </span>
            {col.badge && (
              <span style={{ fontSize: 8, color: bc.color, fontWeight: 600, marginLeft: 4, opacity: .8, flexShrink: 0 }}
                title={bc.title}>
                {col.badge}
              </span>
            )}
          </div>
        )
      })}

      {table.footer && (
        <div style={{ padding: '4px 10px', fontSize: 8, color: '#aaa', borderTop: '1px solid #f3f4f6', fontStyle: 'italic', height: FOOTER_HEIGHT - 1, boxSizing: 'border-box' }}>
          {table.footer}
        </div>
      )}
    </div>
  )
}

function CardinalitySymbol({ cardinality }) {
  const map = {
    'many-to-one':  { symbol: 'N : 1', desc: 'Many to One',  icon: '⋮→|' },
    'one-to-many':  { symbol: '1 : N', desc: 'One to Many',  icon: '|→⋮' },
    'many-to-many': { symbol: 'N : M', desc: 'Many to Many', icon: '⋮→⋮' },
    'one-to-one':   { symbol: '1 : 1', desc: 'One to One',   icon: '|→|' },
  }
  const info = map[cardinality] || map['many-to-one']
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 22, color: '#185FA5', fontFamily: 'monospace' }}>{info.icon}</div>
      <div style={{ fontSize: 10, color: '#888', marginTop: 2 }}>{info.desc}</div>
    </div>
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

function getTotalColumns(model) {
  let total = 0
  model.fact_tables?.forEach(f => total += (f.measures?.length || 0) + (f.foreign_keys?.length || 0) + 1)
  model.dimension_tables?.forEach(d => total += (d.attributes?.length || 0) + 2)
  return total
}

function getArrowSymbol(cardinality) {
  if (!cardinality) return '→'
  if (cardinality.includes('many-to-many')) return '↔'
  return '→'
}

function cardinalityLabel(c) {
  if (!c) return 'N:1'
  if (c.includes('many-to-many')) return 'N : M'
  if (c.includes('many-to-one'))  return 'N : 1'
  if (c.includes('one-to-many'))  return '1 : N'
  if (c.includes('one-to-one'))   return '1 : 1'
  return 'N : 1'
}

function cardinalityChip(cardinality) {
  const styles = {
    'many-to-one':  { background: '#E6F1FB', color: '#185FA5' },
    'one-to-many':  { background: '#EAF3DE', color: '#3B6D11' },
    'many-to-many': { background: '#EEEDFE', color: '#534AB7' },
    'one-to-one':   { background: '#EAF3DE', color: '#3B6D11' },
  }
  const s = styles[cardinality] || styles['many-to-one']
  return { ...s, padding: '2px 7px', borderRadius: 20, fontWeight: 600 }
}

function getCardinalityExplanation(cardinality, from, to) {
  if (cardinality?.includes('many-to-one'))
    return `Many rows in ${from} can reference the same row in ${to}. Example: many sales can belong to one customer.`
  if (cardinality?.includes('one-to-many'))
    return `One row in ${from} can be referenced by many rows in ${to}. Example: one customer can have many orders.`
  if (cardinality?.includes('many-to-many'))
    return `Many rows in ${from} can relate to many rows in ${to}. Typically resolved with a bridge table.`
  if (cardinality?.includes('one-to-one'))
    return `Each row in ${from} corresponds to exactly one row in ${to}.`
  return `${from} relates to ${to}.`
}

const sectionTitle = { fontSize: 11, fontWeight: 600, color: '#555', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 10 }
const card         = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }
const emptyBox     = { border: '1px dashed #e5e7eb', borderRadius: 8, padding: 32, textAlign: 'center', fontSize: 13, color: '#888' }
const muted        = { fontSize: 13, color: '#888' }
const btnGhost     = { padding: '6px 12px', background: '#fff', color: '#555', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
const btnActive    = { padding: '6px 12px', background: '#185FA5', color: '#fff', border: 'none', borderRadius: 6, fontSize: 11, cursor: 'pointer' }
