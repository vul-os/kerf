/**
 * EMFieldPanel.jsx — Electrostatics / Magnetostatics FEM results panel.
 *
 * Renders FEM field results returned by fem_electrostatics and
 * fem_magnetostatics LLM tools.
 *
 * Sections (depending on result type):
 *   1. Scalar metrics table (capacitance / inductance / energy / force)
 *   2. Field colormap — potential φ (electrostatics) or |B| (magnetostatics)
 *      rendered as a canvas heatmap from per-element centroid values.
 *   3. Node count / element count summary.
 *
 * Props
 * -----
 * mode        'electrostatics' | 'magnetostatics'
 * ok          boolean   — whether solver succeeded
 * reason      string    — error reason if ok=false
 * // electrostatics
 * phi         number[]  — nodal potential [V]
 * E_field     [number, number][]  — per-element [Ex, Ey] [V/m]
 * capacitance number    — C [F/m]
 * energy      number    — field energy [J/m]
 * // magnetostatics
 * Az          number[]  — nodal vector potential [Wb/m]
 * B_field     [number, number][]  — per-element [Bx, By] [T]
 * inductance  number    — L [H/m]
 * force       [number, number]  — Lorentz force [N/m]
 * // mesh (for colormap)
 * nodes       [number, number][]
 * elements    number[][]
 */

import { useEffect, useRef } from 'react'
import { Zap, AlertTriangle, CheckCircle, Activity } from 'lucide-react'

// ── Utilities ────────────────────────────────────────────────────────────────

function fmt(v, digits = 4) {
  if (v == null || !Number.isFinite(v)) return '—'
  if (v === 0) return '0'
  if (Math.abs(v) < 0.001 || Math.abs(v) >= 10000) return v.toExponential(3)
  return v.toPrecision(digits)
}

function fmtUnit(v, unit, digits = 4) {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${fmt(v, digits)} ${unit}`
}

// ── Colour mapping (viridis-like, blue→cyan→green→yellow) ──────────────────

function scalarToRGB(t) {
  // t in [0, 1] → viridis-inspired palette
  // r: 0.267→0.993, g: 0.005→0.906, b: 0.329→0.144
  const r = Math.round(255 * (0.267 + 0.726 * t))
  const g = Math.round(255 * (0.005 + 0.901 * t * (1 - 0.3 * t)))
  const b = Math.round(255 * (0.329 * (1 - t * 1.5)))
  return `rgb(${Math.min(255, r)},${Math.min(255, g)},${Math.max(0, b)})`
}

// ── Colormap canvas ──────────────────────────────────────────────────────────

function FieldColormap({ nodes, elements, values, label, unit }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    if (!nodes || !elements || !values || !canvasRef.current) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    const W = canvas.width
    const H = canvas.height

    ctx.clearRect(0, 0, W, H)

    const n_elem = elements.length
    if (n_elem === 0) return

    // Bounding box
    let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity
    for (const [x, y] of nodes) {
      if (x < xMin) xMin = x
      if (x > xMax) xMax = x
      if (y < yMin) yMin = y
      if (y > yMax) yMax = y
    }
    const dx = xMax - xMin || 1
    const dy = yMax - yMin || 1
    const scale = Math.min((W - 20) / dx, (H - 20) / dy)
    const ox = (W - dx * scale) / 2 - xMin * scale
    const oy = (H - dy * scale) / 2 - yMin * scale

    function px(x) { return x * scale + ox }
    function py(y) { return H - (y * scale + oy) }

    // Value range
    const finite = values.filter(Number.isFinite)
    if (finite.length === 0) return
    const vMin = Math.min(...finite)
    const vMax = Math.max(...finite)
    const vRange = vMax - vMin || 1

    // Draw each triangle coloured by scalar value
    for (let e = 0; e < n_elem; e++) {
      const [n0, n1, n2] = elements[e]
      const v = values[e]
      if (!Number.isFinite(v)) continue
      const t = (v - vMin) / vRange
      ctx.fillStyle = scalarToRGB(t)
      ctx.beginPath()
      ctx.moveTo(px(nodes[n0][0]), py(nodes[n0][1]))
      ctx.lineTo(px(nodes[n1][0]), py(nodes[n1][1]))
      ctx.lineTo(px(nodes[n2][0]), py(nodes[n2][1]))
      ctx.closePath()
      ctx.fill()
    }

    // Colorbar (right side, 12 px wide)
    const cbX = W - 14
    const cbH = H - 30
    const cbY0 = 15
    for (let i = 0; i < cbH; i++) {
      const t = 1 - i / cbH
      ctx.fillStyle = scalarToRGB(t)
      ctx.fillRect(cbX, cbY0 + i, 10, 1)
    }
    ctx.strokeStyle = '#374151'
    ctx.strokeRect(cbX, cbY0, 10, cbH)

    // Colorbar labels
    ctx.fillStyle = '#9ca3af'
    ctx.font = '9px ui-monospace, monospace'
    ctx.textAlign = 'right'
    ctx.fillText(fmt(vMax, 3), cbX - 2, cbY0 + 8)
    ctx.fillText(fmt(vMin, 3), cbX - 2, cbY0 + cbH)
    ctx.fillText(unit, cbX - 2, cbY0 + cbH / 2 + 4)

  }, [nodes, elements, values, label, unit])

  return (
    <div style={{ marginTop: 8 }}>
      <div style={styles.sectionTitle}>{label}</div>
      <canvas
        ref={canvasRef}
        width={280}
        height={200}
        style={{
          borderRadius: 4,
          border: '1px solid #1f2937',
          display: 'block',
          background: '#0d1117',
          marginTop: 4,
        }}
      />
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────────

export default function EMFieldPanel(props) {
  const {
    mode = 'electrostatics',
    ok,
    reason,
    phi,
    E_field,
    capacitance,
    Az,
    B_field,
    inductance,
    force,
    energy,
    nodes,
    elements,
  } = props

  const isElectro = mode !== 'magnetostatics'
  const title = isElectro ? 'Electrostatics FEM' : 'Magnetostatics FEM'

  // Scalar values for colormap
  const colormapValues = isElectro
    ? (E_field ? E_field.map(([Ex, Ey]) => Math.sqrt(Ex * Ex + Ey * Ey)) : null)
    : (B_field ? B_field.map(([Bx, By]) => Math.sqrt(Bx * Bx + By * By)) : null)

  const colormapLabel = isElectro ? '|E| field magnitude' : '|B| flux density'
  const colormapUnit = isElectro ? 'V/m' : 'T'

  const hasColormap = nodes && elements && colormapValues && colormapValues.length > 0

  return (
    <div style={styles.root}>
      {/* Header */}
      <div style={styles.header}>
        <Zap size={15} style={{ color: '#a78bfa' }} />
        <span style={styles.title}>{title}</span>
        {ok != null && (
          <span style={{ marginLeft: 'auto' }}>
            {ok
              ? <CheckCircle size={14} style={{ color: '#34d399' }} />
              : <AlertTriangle size={14} style={{ color: '#f87171' }} />}
          </span>
        )}
      </div>

      {/* Error */}
      {ok === false && reason && (
        <div style={styles.errorBox}>
          <AlertTriangle size={13} />
          <span style={{ marginLeft: 6 }}>{reason}</span>
        </div>
      )}

      {/* Metrics */}
      {ok !== false && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>
            <Activity size={12} />
            <span style={{ marginLeft: 4 }}>Field Quantities</span>
          </div>
          <table style={styles.table}>
            <tbody>
              {isElectro ? (
                <>
                  {capacitance != null && (
                    <tr>
                      <td style={styles.td}>Capacitance C</td>
                      <td style={{ ...styles.td, ...styles.mono }}>{fmtUnit(capacitance, 'F/m')}</td>
                    </tr>
                  )}
                  {energy != null && (
                    <tr>
                      <td style={styles.td}>Field energy W</td>
                      <td style={{ ...styles.td, ...styles.mono }}>{fmtUnit(energy, 'J/m')}</td>
                    </tr>
                  )}
                  {E_field && (
                    <tr>
                      <td style={styles.td}>Max |E|</td>
                      <td style={{ ...styles.td, ...styles.mono }}>
                        {fmtUnit(
                          Math.max(...E_field.map(([Ex, Ey]) => Math.sqrt(Ex * Ex + Ey * Ey))),
                          'V/m',
                        )}
                      </td>
                    </tr>
                  )}
                  {phi && (
                    <tr>
                      <td style={styles.td}>φ range</td>
                      <td style={{ ...styles.td, ...styles.mono }}>
                        {fmt(Math.min(...phi.filter(Number.isFinite)), 3)}
                        {' → '}
                        {fmt(Math.max(...phi.filter(Number.isFinite)), 3)} V
                      </td>
                    </tr>
                  )}
                  {nodes && (
                    <tr>
                      <td style={styles.td}>Nodes / Elements</td>
                      <td style={{ ...styles.td, ...styles.mono }}>
                        {nodes.length} / {(elements || []).length}
                      </td>
                    </tr>
                  )}
                </>
              ) : (
                <>
                  {inductance != null && (
                    <tr>
                      <td style={styles.td}>Inductance L</td>
                      <td style={{ ...styles.td, ...styles.mono }}>{fmtUnit(inductance, 'H/m')}</td>
                    </tr>
                  )}
                  {energy != null && (
                    <tr>
                      <td style={styles.td}>Field energy W</td>
                      <td style={{ ...styles.td, ...styles.mono }}>{fmtUnit(energy, 'J/m')}</td>
                    </tr>
                  )}
                  {force && (
                    <>
                      <tr>
                        <td style={styles.td}>Force Fx</td>
                        <td style={{ ...styles.td, ...styles.mono }}>{fmtUnit(force[0], 'N/m')}</td>
                      </tr>
                      <tr>
                        <td style={styles.td}>Force Fy</td>
                        <td style={{ ...styles.td, ...styles.mono }}>{fmtUnit(force[1], 'N/m')}</td>
                      </tr>
                    </>
                  )}
                  {B_field && (
                    <tr>
                      <td style={styles.td}>Max |B|</td>
                      <td style={{ ...styles.td, ...styles.mono }}>
                        {fmtUnit(
                          Math.max(...B_field.map(([Bx, By]) => Math.sqrt(Bx * Bx + By * By))),
                          'T',
                        )}
                      </td>
                    </tr>
                  )}
                  {Az && (
                    <tr>
                      <td style={styles.td}>Az range</td>
                      <td style={{ ...styles.td, ...styles.mono }}>
                        {fmt(Math.min(...Az.filter(Number.isFinite)), 3)}
                        {' → '}
                        {fmt(Math.max(...Az.filter(Number.isFinite)), 3)} Wb/m
                      </td>
                    </tr>
                  )}
                  {nodes && (
                    <tr>
                      <td style={styles.td}>Nodes / Elements</td>
                      <td style={{ ...styles.td, ...styles.mono }}>
                        {nodes.length} / {(elements || []).length}
                      </td>
                    </tr>
                  )}
                </>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Field colormap */}
      {hasColormap && (
        <FieldColormap
          nodes={nodes}
          elements={elements}
          values={colormapValues}
          label={colormapLabel}
          unit={colormapUnit}
        />
      )}
    </div>
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────

const styles = {
  root: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 12,
    color: '#e5e7eb',
    background: '#111827',
    borderRadius: 8,
    padding: 14,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
    minWidth: 300,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 7,
    borderBottom: '1px solid #1f2937',
    paddingBottom: 9,
  },
  title: {
    fontWeight: 600,
    fontSize: 13,
    color: '#f3f4f6',
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  sectionTitle: {
    display: 'flex',
    alignItems: 'center',
    fontSize: 11,
    color: '#9ca3af',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    marginBottom: 2,
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
  },
  td: {
    padding: '3px 6px',
    borderBottom: '1px solid #1f2937',
    color: '#d1d5db',
    fontSize: 12,
  },
  mono: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    color: '#a78bfa',
    textAlign: 'right',
  },
  errorBox: {
    display: 'flex',
    alignItems: 'flex-start',
    background: '#1f0707',
    border: '1px solid #7f1d1d',
    borderRadius: 5,
    padding: '6px 10px',
    color: '#fca5a5',
    fontSize: 12,
  },
}
