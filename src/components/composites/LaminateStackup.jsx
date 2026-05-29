/**
 * LaminateStackup.jsx
 *
 * Ply table editor for composite laminate design.
 *
 * Features:
 *  - Ply table: ply # / material / thickness [mm] / orientation [°]
 *  - Drag-to-reorder rows (HTML5 drag API, no extra dep)
 *  - Auto-computed weight + cost rollup (density × volume per unit area)
 *  - Balance / symmetry check indicators
 *  - Click any ply → dispatches layup_analysis via POST /api/composites/clt
 *    (stiffness matrix preview displayed inline)
 *  - Aesthetic: deep-charcoal engineering panel, monospace readouts,
 *    accent color kerf-300 for interactive states
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../../store/auth.js'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Default ply materials catalogue
// ---------------------------------------------------------------------------
const MATERIAL_PRESETS = {
  'T300/Epoxy': { E1: 181, E2: 10.3, G12: 7.17, nu12: 0.28, rho: 1.6, costPerKg: 45 },
  'IM7/Epoxy':  { E1: 164, E2:  8.9, G12: 5.6,  nu12: 0.32, rho: 1.58, costPerKg: 65 },
  'AS4/PEEK':   { E1: 138, E2:  9.0, G12: 5.5,  nu12: 0.30, rho: 1.60, costPerKg: 120 },
  'E-glass/Ep': { E1:  45, E2: 12.0, G12: 5.0,  nu12: 0.28, rho: 1.95, costPerKg: 12 },
  'Kevlar/Ep':  { E1:  76, E2:  5.5, G12: 2.1,  nu12: 0.34, rho: 1.38, costPerKg: 80 },
}

const MAT_NAMES = Object.keys(MATERIAL_PRESETS)

function defaultPly(i) {
  const mat = MAT_NAMES[i % MAT_NAMES.length]
  return {
    id: crypto.randomUUID(),
    material: mat,
    thickness: 0.125,
    angle: [0, 45, -45, 90][i % 4],
    ...MATERIAL_PRESETS[mat],
  }
}

const INITIAL_PLIES = [0, 1, 2, 3, 2, 1, 0].map(defaultPly)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function isSymmetric(plies) {
  const n = plies.length
  for (let i = 0; i < Math.floor(n / 2); i++) {
    const a = plies[i], b = plies[n - 1 - i]
    if (a.angle !== b.angle || a.material !== b.material || a.thickness !== b.thickness)
      return false
  }
  return true
}

function isBalanced(plies) {
  const counts = {}
  for (const p of plies) {
    const key = Math.abs(p.angle)
    counts[key] = (counts[key] || 0) + Math.sign(p.angle || 1)
  }
  return Object.values(counts).every((v) => v === 0)
}

function fmtNum(v, dp = 3) {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(dp)
}

// Hue rotation for fiber angle: 0°=teal, 45°=gold, 90°=rose, -45°=violet
function angleColor(deg) {
  const a = ((deg % 180) + 180) % 180
  if (a === 0)   return '#4adeae'
  if (a === 90)  return '#f97888'
  if (a === 45)  return '#fbbf24'
  if (a === 135) return '#a78bfa'
  // blend
  const t = (a % 90) / 90
  if (a < 45)  return `color-mix(in srgb, #4adeae ${Math.round((1-t)*100)}%, #fbbf24)`
  if (a < 90)  return `color-mix(in srgb, #fbbf24 ${Math.round((1-t)*100)}%, #f97888)`
  if (a < 135) return `color-mix(in srgb, #f97888 ${Math.round((1-t)*100)}%, #a78bfa)`
  return `color-mix(in srgb, #a78bfa ${Math.round((1-t)*100)}%, #4adeae)`
}

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------
async function callCLT(plies) {
  const token = useAuth.getState().accessToken
  const body = {
    tool: 'layup_analysis',
    args: {
      plies: plies.map((p) => ({
        angle: p.angle,
        E1: p.E1,
        E2: p.E2,
        G12: p.G12,
        nu12: p.nu12,
        thickness: p.thickness,
      })),
      name: 'ui_layup',
    },
  }
  const res = await fetch(`${API_URL}/api/composites/clt`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Stiffness matrix mini-display
// ---------------------------------------------------------------------------
function MatrixDisplay({ label, rows }) {
  if (!rows) return null
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        fontFamily: 'monospace',
        fontSize: 10,
        color: '#7dd3fc',
        textTransform: 'uppercase',
        letterSpacing: '0.12em',
        marginBottom: 4,
      }}>
        {label}
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 2,
        fontFamily: 'monospace',
        fontSize: 11,
      }}>
        {rows.flat().map((v, i) => (
          <span key={i} style={{
            background: '#1e293b',
            border: '1px solid #334155',
            borderRadius: 3,
            padding: '2px 4px',
            color: Math.abs(v) < 1e-6 ? '#475569' : '#94a3b8',
            textAlign: 'right',
            fontSize: 10,
          }}>
            {Math.abs(v) > 999 ? v.toExponential(2) : fmtNum(v, 2)}
          </span>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function LaminateStackup({ initialPlies, onResult }) {
  const [plies, setPlies] = useState(initialPlies || INITIAL_PLIES)
  const [selected, setSelected] = useState(null)
  const [dragging, setDragging] = useState(null)
  const [dragOver, setDragOver] = useState(null)
  const [cltResult, setCltResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const dragRef = useRef(null)

  // Rollup calculations
  const totalThickness = plies.reduce((s, p) => s + p.thickness, 0)
  const areaM2 = 1.0 // per m²
  const weight = plies.reduce((s, p) => s + p.rho * (p.thickness / 1000) * 1e6 * areaM2, 0) // g/m²
  const cost   = plies.reduce((s, p) => s + p.rho * (p.thickness / 1000) * 1000 * p.costPerKg * areaM2, 0) // USD/m²
  const symmetric = isSymmetric(plies)
  const balanced  = isBalanced(plies)

  // Drag-to-reorder
  const handleDragStart = useCallback((e, i) => {
    setDragging(i)
    dragRef.current = i
    e.dataTransfer.effectAllowed = 'move'
  }, [])

  const handleDragEnter = useCallback((i) => setDragOver(i), [])

  const handleDrop = useCallback((e, target) => {
    e.preventDefault()
    const src = dragRef.current
    if (src == null || src === target) { setDragging(null); setDragOver(null); return }
    setPlies((prev) => {
      const next = [...prev]
      const [removed] = next.splice(src, 1)
      next.splice(target, 0, removed)
      return next
    })
    setDragging(null)
    setDragOver(null)
  }, [])

  // Add / remove ply
  const addPly = () => setPlies((p) => [...p, defaultPly(p.length)])
  const removePly = (i) => setPlies((p) => p.filter((_, k) => k !== i))

  // Field edit
  const updatePly = (i, field, val) => setPlies((p) => {
    const next = [...p]
    const prev = next[i]
    const matPreset = MATERIAL_PRESETS[val] || {}
    if (field === 'material') {
      next[i] = { ...prev, material: val, ...matPreset }
    } else if (field === 'angle') {
      next[i] = { ...prev, angle: parseFloat(val) || 0 }
    } else if (field === 'thickness') {
      next[i] = { ...prev, thickness: parseFloat(val) || 0.125 }
    } else {
      next[i] = { ...prev, [field]: parseFloat(val) || 0 }
    }
    return next
  })

  // Dispatch CLT analysis
  const runCLT = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await callCLT(plies)
      setCltResult(result)
      onResult?.(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [plies, onResult])

  // Auto-run on ply change (debounced)
  const timerRef = useRef(null)
  useEffect(() => {
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => runCLT(), 900)
    return () => clearTimeout(timerRef.current)
  }, [plies]) // eslint-disable-line

  const styles = {
    root: {
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: '#0a0f1a',
      fontFamily: '"IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace',
      color: '#e2e8f0',
      overflow: 'hidden',
    },
    header: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '10px 14px 8px',
      borderBottom: '1px solid #1e293b',
      background: '#080d16',
    },
    title: {
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: '#7dd3fc',
    },
    badges: {
      display: 'flex',
      gap: 6,
      alignItems: 'center',
    },
    badge: (ok) => ({
      fontSize: 9,
      letterSpacing: '0.14em',
      textTransform: 'uppercase',
      padding: '2px 7px',
      borderRadius: 2,
      background: ok ? 'rgba(74,222,128,0.12)' : 'rgba(248,113,113,0.12)',
      border: `1px solid ${ok ? 'rgba(74,222,128,0.4)' : 'rgba(248,113,113,0.4)'}`,
      color: ok ? '#4ade80' : '#f87171',
    }),
    table: {
      flex: 1,
      overflow: 'auto',
    },
    tHead: {
      position: 'sticky',
      top: 0,
      background: '#0d1321',
      zIndex: 2,
    },
    th: {
      padding: '5px 10px',
      fontSize: 9,
      letterSpacing: '0.15em',
      textTransform: 'uppercase',
      color: '#475569',
      fontWeight: 600,
      whiteSpace: 'nowrap',
      borderBottom: '1px solid #1e293b',
    },
    tr: (i, selected, dragOver) => ({
      background: selected === i
        ? 'rgba(125,211,252,0.08)'
        : dragOver === i
          ? 'rgba(125,211,252,0.04)'
          : i % 2 === 0 ? '#080d16' : '#0a1020',
      cursor: 'grab',
      borderLeft: selected === i ? '2px solid #7dd3fc' : '2px solid transparent',
      transition: 'background 80ms',
    }),
    td: {
      padding: '5px 10px',
      fontSize: 11,
      verticalAlign: 'middle',
      borderBottom: '1px solid #111827',
    },
    input: {
      background: 'transparent',
      border: 'none',
      borderBottom: '1px solid #334155',
      color: '#e2e8f0',
      fontFamily: 'inherit',
      fontSize: 11,
      width: '100%',
      padding: '1px 2px',
      outline: 'none',
    },
    select: {
      background: '#0d1321',
      border: '1px solid #1e293b',
      color: '#e2e8f0',
      fontFamily: 'inherit',
      fontSize: 10,
      padding: '2px 4px',
      borderRadius: 3,
      outline: 'none',
      width: '100%',
    },
    rollup: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 1,
      borderTop: '1px solid #1e293b',
      background: '#060b14',
    },
    rollupCell: {
      padding: '8px 12px',
      borderRight: '1px solid #0f172a',
    },
    rollupLabel: {
      fontSize: 9,
      color: '#475569',
      textTransform: 'uppercase',
      letterSpacing: '0.12em',
      marginBottom: 2,
    },
    rollupValue: {
      fontSize: 14,
      fontWeight: 700,
      color: '#e2e8f0',
    },
    rollupUnit: {
      fontSize: 9,
      color: '#64748b',
      marginLeft: 3,
    },
    resultPanel: {
      padding: '10px 14px',
      borderTop: '1px solid #1e293b',
      background: '#060b14',
      maxHeight: 220,
      overflow: 'auto',
    },
    resultLabel: {
      fontSize: 9,
      color: '#475569',
      textTransform: 'uppercase',
      letterSpacing: '0.15em',
      marginBottom: 8,
      display: 'flex',
      alignItems: 'center',
      gap: 6,
    },
    addBtn: {
      display: 'flex',
      alignItems: 'center',
      gap: 5,
      padding: '4px 10px',
      background: 'rgba(125,211,252,0.08)',
      border: '1px solid rgba(125,211,252,0.25)',
      borderRadius: 3,
      color: '#7dd3fc',
      fontSize: 10,
      letterSpacing: '0.1em',
      cursor: 'pointer',
    },
    removeBtn: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: 16,
      height: 16,
      background: 'transparent',
      border: 'none',
      borderRadius: 2,
      color: '#475569',
      cursor: 'pointer',
      fontSize: 11,
      lineHeight: 1,
    },
    runBtn: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      padding: '3px 9px',
      background: loading ? 'rgba(125,211,252,0.04)' : 'rgba(125,211,252,0.12)',
      border: '1px solid rgba(125,211,252,0.3)',
      borderRadius: 3,
      color: loading ? '#475569' : '#7dd3fc',
      fontSize: 9,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      cursor: loading ? 'default' : 'pointer',
    },
  }

  return (
    <div style={styles.root} data-testid="laminate-stackup">
      {/* Header */}
      <div style={styles.header}>
        <span style={styles.title}>Laminate Stackup</span>
        <div style={styles.badges}>
          <span style={styles.badge(symmetric)}>
            {symmetric ? 'Sym ✓' : 'Asym'}
          </span>
          <span style={styles.badge(balanced)}>
            {balanced ? 'Bal ✓' : 'Unbal'}
          </span>
          <button style={styles.addBtn} onClick={addPly} type="button">
            + Ply
          </button>
        </div>
      </div>

      {/* Table */}
      <div style={styles.table}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead style={styles.tHead}>
            <tr>
              {['#', 'Material', 'Thick mm', 'Angle °', 'E₁ GPa', 'E₂ GPa', ''].map((h, i) => (
                <th key={i} style={{ ...styles.th, textAlign: i === 0 ? 'center' : 'left' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {plies.map((ply, i) => (
              <tr
                key={ply.id}
                style={styles.tr(i, selected, dragOver)}
                draggable
                onDragStart={(e) => handleDragStart(e, i)}
                onDragEnter={() => handleDragEnter(i)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => handleDrop(e, i)}
                onDragEnd={() => { setDragging(null); setDragOver(null) }}
                onClick={() => setSelected(i === selected ? null : i)}
              >
                <td style={{ ...styles.td, textAlign: 'center', color: '#475569', fontSize: 10, width: 28 }}>
                  {i + 1}
                </td>
                <td style={styles.td}>
                  <select
                    style={styles.select}
                    value={ply.material}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => updatePly(i, 'material', e.target.value)}
                  >
                    {MAT_NAMES.map((m) => <option key={m}>{m}</option>)}
                  </select>
                </td>
                <td style={styles.td}>
                  <input
                    style={styles.input}
                    type="number"
                    min="0.01"
                    step="0.025"
                    value={ply.thickness}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => updatePly(i, 'thickness', e.target.value)}
                  />
                </td>
                <td style={{ ...styles.td, position: 'relative' }}>
                  {/* Color swatch */}
                  <span style={{
                    display: 'inline-block',
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: angleColor(ply.angle),
                    marginRight: 5,
                    verticalAlign: 'middle',
                    flexShrink: 0,
                  }} />
                  <input
                    style={{ ...styles.input, width: 'calc(100% - 14px)' }}
                    type="number"
                    min="-90"
                    max="90"
                    step="15"
                    value={ply.angle}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => updatePly(i, 'angle', e.target.value)}
                  />
                </td>
                <td style={{ ...styles.td, color: '#94a3b8', fontSize: 10 }}>
                  {fmtNum(ply.E1, 1)}
                </td>
                <td style={{ ...styles.td, color: '#94a3b8', fontSize: 10 }}>
                  {fmtNum(ply.E2, 1)}
                </td>
                <td style={{ ...styles.td, width: 24 }}>
                  <button
                    style={styles.removeBtn}
                    onClick={(e) => { e.stopPropagation(); removePly(i) }}
                    type="button"
                    aria-label={`Remove ply ${i + 1}`}
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Rollup bar */}
      <div style={styles.rollup}>
        {[
          { label: 'Plies', value: plies.length, unit: '' },
          { label: 'Thickness', value: fmtNum(totalThickness, 2), unit: 'mm' },
          { label: 'Areal wt', value: fmtNum(weight, 0), unit: 'g/m²' },
          { label: 'Mat cost', value: `$${fmtNum(cost, 2)}`, unit: '/m²' },
        ].map(({ label, value, unit }) => (
          <div key={label} style={styles.rollupCell}>
            <div style={styles.rollupLabel}>{label}</div>
            <div style={styles.rollupValue}>
              {value}
              <span style={styles.rollupUnit}>{unit}</span>
            </div>
          </div>
        ))}
      </div>

      {/* CLT result panel */}
      <div style={styles.resultPanel}>
        <div style={styles.resultLabel}>
          <span>CLT Stiffness</span>
          <button style={styles.runBtn} onClick={runCLT} type="button" disabled={loading}>
            {loading ? '⟳ Running…' : '▶ Run Analysis'}
          </button>
          {error && (
            <span style={{ color: '#f87171', fontSize: 9 }}>Error: {error}</span>
          )}
        </div>
        {cltResult && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
            <MatrixDisplay label="A [N/mm]" rows={cltResult.A_matrix_N_per_mm} />
            <MatrixDisplay label="B [N]"    rows={cltResult.B_matrix_N} />
            <MatrixDisplay label="D [N·mm]" rows={cltResult.D_matrix_N_mm} />
          </div>
        )}
        {cltResult?.effective_moduli && (
          <div style={{
            display: 'flex',
            gap: 14,
            marginTop: 8,
            flexWrap: 'wrap',
            fontSize: 10,
            color: '#7dd3fc',
            fontFamily: 'monospace',
          }}>
            {Object.entries(cltResult.effective_moduli).map(([k, v]) => (
              <span key={k}>
                <span style={{ color: '#475569' }}>{k}: </span>
                {fmtNum(v, 3)} GPa
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
