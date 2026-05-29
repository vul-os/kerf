/**
 * FiberOrientationContour.jsx
 *
 * 3D laminate part with a color-coded fiber-angle overlay.
 *
 * Renders a simplified laminate cross-section as an SVG-based pseudo-3D
 * exploded view (layer-by-layer hatch fill) with a canvas heatmap contour.
 * Uses the same angle→color mapping as LaminateStackup for consistency.
 *
 * Also dispatches POST /api/composites/fiber_map → composites_drape tool
 * for geodesic drape contour on a 3D surface (result shown as contour legend).
 *
 * Tooltip: hover a grid cell → shows local fiber angle at that point.
 *
 * Design: dark science-lab aesthetic, HSL color map for angles,
 * crisp monospace overlays.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../../store/auth.js'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Angle → color (HSL wheel, distinct from role colors)
// Maps −90…+90 onto full hue range
// ---------------------------------------------------------------------------
function angleToHsl(deg) {
  const normalized = ((deg + 90) / 180)  // 0 → 1
  const hue = normalized * 300            // 0° = 0° hue, 90° = 150° hue
  return `hsl(${hue.toFixed(0)}, 90%, 55%)`
}

function angleToRgb(deg) {
  const normalized = ((deg + 90) / 180)
  const h = normalized * 300 / 360
  // HSL → RGB
  const s = 0.9, l = 0.55
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s
  const p = 2 * l - q
  const hue2rgb = (p, q, t) => {
    if (t < 0) t += 1
    if (t > 1) t -= 1
    if (t < 1/6) return p + (q - p) * 6 * t
    if (t < 1/2) return q
    if (t < 2/3) return p + (q - p) * (2/3 - t) * 6
    return p
  }
  const r = Math.round(hue2rgb(p, q, h + 1/3) * 255)
  const g = Math.round(hue2rgb(p, q, h) * 255)
  const b = Math.round(hue2rgb(p, q, h - 1/3) * 255)
  return [r, g, b]
}

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------
async function callFiberMap(params) {
  const token = useAuth.getState().accessToken
  const res = await fetch(`${API_URL}/api/composites/fiber_map`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ tool: 'composites_drape', args: params }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Contour canvas
// ---------------------------------------------------------------------------
function ContourCanvas({ plies, width = 480, height = 280, tooltip, onCellHover }) {
  const canvasRef = useRef(null)
  const COLS = 32, ROWS = 20

  // Build angle field from ply stack (interpolate across plies per cell)
  function angleAt(col, row, plies) {
    if (!plies || plies.length === 0) return 0
    // Vary angle spatially using a simple sinusoidal warp to simulate drape
    const tx = col / COLS, ty = row / ROWS
    // Pick ply by row position (deeper row = lower ply)
    const plyIdx = Math.floor(ty * (plies.length - 1))
    const ply = plies[plyIdx] || plies[0]
    // Add a small drape-induced deviation that varies with position
    const drape = Math.sin(tx * Math.PI) * Math.cos(ty * Math.PI) * 5
    return (ply.angle || 0) + drape
  }

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width, H = canvas.height

    ctx.fillStyle = '#06090f'
    ctx.fillRect(0, 0, W, H)

    const cw = W / COLS, ch = H / ROWS

    for (let row = 0; row < ROWS; row++) {
      for (let col = 0; col < COLS; col++) {
        const angle = angleAt(col, row, plies)
        const [r, g, b] = angleToRgb(angle)
        ctx.fillStyle = `rgba(${r},${g},${b},0.85)`
        ctx.fillRect(col * cw, row * ch, cw + 0.5, ch + 0.5)
      }
    }

    // Hatching overlay per cell (fiber direction indicator)
    for (let row = 0; row < ROWS; row += 2) {
      for (let col = 0; col < COLS; col += 2) {
        const angle = angleAt(col, row, plies)
        const rad = (angle * Math.PI) / 180
        const cx = col * cw + cw / 2
        const cy = row * ch + ch / 2
        const len = Math.min(cw, ch) * 0.7
        ctx.strokeStyle = 'rgba(0,0,0,0.35)'
        ctx.lineWidth = 0.5
        ctx.beginPath()
        ctx.moveTo(cx - Math.cos(rad) * len, cy - Math.sin(rad) * len)
        ctx.lineTo(cx + Math.cos(rad) * len, cy + Math.sin(rad) * len)
        ctx.stroke()
      }
    }

    // Grid lines (subtle)
    ctx.strokeStyle = 'rgba(0,0,0,0.2)'
    ctx.lineWidth = 0.3
    for (let col = 0; col <= COLS; col++) {
      ctx.beginPath(); ctx.moveTo(col * cw, 0); ctx.lineTo(col * cw, H); ctx.stroke()
    }
    for (let row = 0; row <= ROWS; row++) {
      ctx.beginPath(); ctx.moveTo(0, row * ch); ctx.lineTo(W, row * ch); ctx.stroke()
    }

    // Tooltip cell highlight
    if (tooltip) {
      const { col, row } = tooltip
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 1.5
      ctx.strokeRect(col * cw + 1, row * ch + 1, cw - 2, ch - 2)
    }
  }, [plies, tooltip])

  const handleMouseMove = useCallback((e) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx = (e.clientX - rect.left) * (canvas.width / rect.width)
    const my = (e.clientY - rect.top) * (canvas.height / rect.height)
    const col = Math.floor(mx / (canvas.width / COLS))
    const row = Math.floor(my / (canvas.height / ROWS))
    if (col >= 0 && col < COLS && row >= 0 && row < ROWS) {
      const angle = angleAt(col, row, plies)
      onCellHover?.({ col, row, angle: angle.toFixed(1) })
    }
  }, [plies, onCellHover])

  const handleMouseLeave = useCallback(() => onCellHover?.(null), [onCellHover])

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      style={{ width: '100%', height: '100%', display: 'block', cursor: 'crosshair' }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      role="img"
      aria-label="Fiber orientation contour map"
    />
  )
}

// ---------------------------------------------------------------------------
// Color legend bar
// ---------------------------------------------------------------------------
function AngleLegend({ width = 200 }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width, H = canvas.height
    // Gradient
    for (let x = 0; x < W; x++) {
      const deg = -90 + (x / W) * 180
      const [r, g, b] = angleToRgb(deg)
      ctx.fillStyle = `rgb(${r},${g},${b})`
      ctx.fillRect(x, 0, 1.5, H)
    }
  }, [])

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 9, fontFamily: 'monospace', color: '#64748b' }}>
      <span>−90°</span>
      <canvas ref={canvasRef} width={width} height={10} style={{ width: width, height: 10, borderRadius: 2 }} aria-hidden="true" />
      <span>+90°</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Exploded ply stack view (SVG)
// ---------------------------------------------------------------------------
function ExplodedPlyStack({ plies }) {
  if (!plies || plies.length === 0) return null
  const W = 200, plyH = 14, gap = 4, partW = 160, partX = 20, offsetX = 4
  const totalH = plies.length * (plyH + gap) + 20

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${totalH}`}
      style={{ display: 'block', maxWidth: 200 }}
      role="img"
      aria-label="Exploded ply stack diagram"
    >
      {plies.map((ply, i) => {
        const y = i * (plyH + gap) + 10
        const xOff = i * offsetX * 0.3
        const col = angleToHsl(ply.angle)
        const rad = (ply.angle * Math.PI) / 180
        const hatchSpacing = 8

        return (
          <g key={ply.id || i}>
            {/* Ply face */}
            <rect
              x={partX + xOff}
              y={y}
              width={partW}
              height={plyH}
              fill={col}
              fillOpacity={0.15}
              stroke={col}
              strokeWidth={0.8}
              strokeOpacity={0.6}
              rx={1}
            />
            {/* Hatch lines at fiber angle */}
            <clipPath id={`clip-ply-${i}`}>
              <rect x={partX + xOff} y={y} width={partW} height={plyH} rx={1} />
            </clipPath>
            <g clipPath={`url(#clip-ply-${i})`}>
              {Array.from({ length: Math.ceil(partW / hatchSpacing) + 4 }).map((_, j) => {
                const hx = partX + xOff + j * hatchSpacing - 20
                return (
                  <line
                    key={j}
                    x1={hx}
                    y1={y}
                    x2={hx + plyH * Math.tan(rad)}
                    y2={y + plyH}
                    stroke={col}
                    strokeWidth={0.7}
                    strokeOpacity={0.5}
                  />
                )
              })}
            </g>
            {/* Ply label */}
            <text
              x={partX + xOff + partW + 4}
              y={y + plyH / 2 + 3}
              fill={col}
              fontSize={7}
              fontFamily="monospace"
              opacity={0.9}
            >
              {ply.angle}°
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function FiberOrientationContour({ plies: propPlies, file, projectId }) {
  const defaultPlies = [
    { id: '1', angle: 0,   material: 'T300/Epoxy', thickness: 0.125 },
    { id: '2', angle: 45,  material: 'T300/Epoxy', thickness: 0.125 },
    { id: '3', angle: -45, material: 'T300/Epoxy', thickness: 0.125 },
    { id: '4', angle: 90,  material: 'T300/Epoxy', thickness: 0.125 },
    { id: '5', angle: -45, material: 'T300/Epoxy', thickness: 0.125 },
    { id: '6', angle: 45,  material: 'T300/Epoxy', thickness: 0.125 },
    { id: '7', angle: 0,   material: 'T300/Epoxy', thickness: 0.125 },
  ]

  const plies = propPlies || defaultPlies

  const [tooltip, setTooltip] = useState(null)
  const [tooltipPos, setTooltipPos] = useState(null)
  const [surface, setSurface] = useState('flat')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [drapeResult, setDrapeResult] = useState(null)
  const containerRef = useRef(null)

  const handleCellHover = useCallback((info) => {
    if (!info) { setTooltip(null); setTooltipPos(null); return }
    setTooltip(info)
  }, [])

  const runDrape = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await callFiberMap({
        surface,
        u_range: [0, 100],
        v_range: [0, 100],
        nu: 10,
        nv: 10,
        radius: 150,
      })
      setDrapeResult(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [surface])

  const styles = {
    root: {
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: '#060912',
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
      background: '#040710',
    },
    title: {
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: '#a78bfa',
    },
    body: {
      display: 'flex',
      flex: 1,
      minHeight: 0,
      overflow: 'hidden',
    },
    contourWrap: {
      flex: 1,
      position: 'relative',
      minWidth: 0,
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
    },
    canvasArea: {
      flex: 1,
      position: 'relative',
      overflow: 'hidden',
    },
    tooltipBubble: {
      position: 'absolute',
      top: 8,
      right: 10,
      background: 'rgba(10,14,24,0.92)',
      border: '1px solid #334155',
      borderRadius: 4,
      padding: '5px 10px',
      fontSize: 10,
      color: '#e2e8f0',
      pointerEvents: 'none',
      zIndex: 10,
      minWidth: 90,
    },
    legendBar: {
      padding: '6px 12px',
      borderTop: '1px solid #1e293b',
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      background: '#04070f',
    },
    sidebar: {
      width: 220,
      flexShrink: 0,
      borderLeft: '1px solid #1e293b',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      background: '#050810',
    },
    sidebarHeader: {
      padding: '8px 12px',
      borderBottom: '1px solid #1e293b',
      fontSize: 9,
      letterSpacing: '0.14em',
      textTransform: 'uppercase',
      color: '#475569',
    },
    sidebarBody: {
      flex: 1,
      overflow: 'auto',
      padding: '8px 10px',
    },
    controlRow: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 8,
      fontSize: 10,
    },
    select: {
      background: '#0d1321',
      border: '1px solid #1e293b',
      borderRadius: 3,
      color: '#e2e8f0',
      fontFamily: 'inherit',
      fontSize: 10,
      padding: '2px 6px',
      outline: 'none',
    },
    runBtn: {
      padding: '4px 10px',
      background: 'rgba(167,139,250,0.1)',
      border: '1px solid rgba(167,139,250,0.3)',
      borderRadius: 3,
      color: '#a78bfa',
      fontFamily: 'inherit',
      fontSize: 9,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      cursor: 'pointer',
      marginTop: 4,
      width: '100%',
    },
    drapeStats: {
      marginTop: 10,
      fontSize: 9,
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
    },
    statRow: {
      display: 'flex',
      justifyContent: 'space-between',
    },
    statLabel: { color: '#475569' },
    statVal: { color: '#a78bfa' },
  }

  return (
    <div style={styles.root} data-testid="fiber-orientation-contour">
      <div style={styles.header}>
        <span style={styles.title}>Fiber Orientation Map</span>
        {error && <span style={{ fontSize: 9, color: '#f87171' }}>Error: {error}</span>}
      </div>

      <div style={styles.body}>
        {/* Left: contour heatmap */}
        <div style={styles.contourWrap}>
          <div style={styles.canvasArea}>
            <ContourCanvas
              plies={plies}
              tooltip={tooltip}
              onCellHover={handleCellHover}
            />
            {tooltip && (
              <div style={styles.tooltipBubble}>
                <div style={{ color: '#a78bfa', marginBottom: 2, fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                  Fiber Angle
                </div>
                <div style={{ fontSize: 16, fontWeight: 700 }}>
                  {tooltip.angle}°
                </div>
                <div style={{ color: '#475569', fontSize: 8, marginTop: 2 }}>
                  col {tooltip.col}, row {tooltip.row}
                </div>
              </div>
            )}
          </div>
          <div style={styles.legendBar}>
            <AngleLegend width={180} />
          </div>
        </div>

        {/* Right sidebar: ply stack + drape controls */}
        <div style={styles.sidebar}>
          <div style={styles.sidebarHeader}>Ply Stack</div>
          <div style={styles.sidebarBody}>
            <ExplodedPlyStack plies={plies} />

            <div style={{ borderTop: '1px solid #1e293b', marginTop: 12, paddingTop: 10 }}>
              <div style={{ ...styles.sidebarHeader, padding: 0, marginBottom: 8 }}>Drape Sim</div>
              <div style={styles.controlRow}>
                <span style={{ color: '#94a3b8' }}>Surface</span>
                <select
                  style={styles.select}
                  value={surface}
                  onChange={(e) => setSurface(e.target.value)}
                >
                  <option value="flat">Flat</option>
                  <option value="cylinder_x">Cyl X</option>
                  <option value="cylinder_y">Cyl Y</option>
                </select>
              </div>

              <button style={styles.runBtn} onClick={runDrape} type="button" disabled={loading}>
                {loading ? '⟳ Running…' : '▶ Run Drape'}
              </button>

              {drapeResult && (
                <div style={styles.drapeStats}>
                  {drapeResult.shear_angle_deg && (
                    <>
                      <div style={styles.statRow}>
                        <span style={styles.statLabel}>Mean shear</span>
                        <span style={styles.statVal}>{drapeResult.shear_angle_deg.mean}°</span>
                      </div>
                      <div style={styles.statRow}>
                        <span style={styles.statLabel}>Max shear</span>
                        <span style={styles.statVal}>{drapeResult.shear_angle_deg.max}°</span>
                      </div>
                      <div style={styles.statRow}>
                        <span style={styles.statLabel}>Min shear</span>
                        <span style={styles.statVal}>{drapeResult.shear_angle_deg.min}°</span>
                      </div>
                    </>
                  )}
                  {drapeResult.surface && (
                    <div style={styles.statRow}>
                      <span style={styles.statLabel}>Surface</span>
                      <span style={styles.statVal}>{drapeResult.surface}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
