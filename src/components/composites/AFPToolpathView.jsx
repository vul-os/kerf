/**
 * AFPToolpathView.jsx
 *
 * Automated Fiber Placement (AFP) toolpath visualiser.
 *
 * Features:
 *  - 2D tape-path canvas: animated course/tow lines on a part outline
 *  - Cure cycle plot: temperature vs time (ramp → dwell → cool-down)
 *  - Dispatch POST /api/composites/afp → composites_afp_pathplan tool
 *  - Parameter controls: course width, steering radius, tow count
 *
 * Design note: dark industrial, grid-paper canvas for the 2D lay-up view,
 * clean SVG chart for the cure cycle. Accent: amber #fbbf24 (AFP gold).
 */

import { useCallback, useRef, useState, useEffect } from 'react'
import { useAuth } from '../../store/auth.js'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------
async function callAFPPathplan(params) {
  const token = useAuth.getState().accessToken
  const res = await fetch(`${API_URL}/api/composites/afp`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ tool: 'composites_afp_pathplan', args: params }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function callAFPExport(params, format) {
  const token = useAuth.getState().accessToken
  const res = await fetch(`${API_URL}/api/composites/afp?format=${format}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ tool: 'composites_afp_pathplan', args: params }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.text()
}

// ---------------------------------------------------------------------------
// Cure cycle data generator
// ---------------------------------------------------------------------------
function buildCureCycle({ rampRate = 2, dwellTemp = 180, dwellTime = 60, coolRate = 3 }) {
  const points = []
  let t = 0, temp = 25
  // Ramp
  while (temp < dwellTemp) {
    points.push({ t, temp })
    temp = Math.min(dwellTemp, temp + rampRate)
    t++
  }
  points.push({ t, temp: dwellTemp })
  // Dwell
  const dwellEnd = t + dwellTime
  for (; t <= dwellEnd; t++) points.push({ t, temp: dwellTemp })
  // Cool
  while (temp > 25) {
    points.push({ t, temp })
    temp = Math.max(25, temp - coolRate)
    t++
  }
  points.push({ t, temp: 25 })
  return points
}

// ---------------------------------------------------------------------------
// AFP 2D canvas — draws grid + tow courses
// ---------------------------------------------------------------------------
function AFPCanvas({ courses, partWidth = 400, partHeight = 260, loading }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width, H = canvas.height

    // Background
    ctx.fillStyle = '#060b14'
    ctx.fillRect(0, 0, W, H)

    // Grid
    ctx.strokeStyle = '#0f172a'
    ctx.lineWidth = 1
    const gridStep = 20
    for (let x = 0; x < W; x += gridStep) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke()
    }
    for (let y = 0; y < H; y += gridStep) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke()
    }

    // Part outline (rounded rect)
    const px = 30, py = 25, pw = W - 60, ph = H - 50
    ctx.strokeStyle = '#334155'
    ctx.lineWidth = 1.5
    ctx.setLineDash([4, 4])
    ctx.strokeRect(px, py, pw, ph)
    ctx.setLineDash([])

    // Part label
    ctx.fillStyle = '#1e293b'
    ctx.font = '9px monospace'
    ctx.fillText(`${partWidth}mm × ${partHeight}mm`, px + 6, py + 14)

    if (loading) {
      ctx.fillStyle = '#fbbf24'
      ctx.font = '10px monospace'
      ctx.fillText('Computing paths…', W / 2 - 55, H / 2)
      return
    }

    // Draw courses — if none provided, draw a default illustration
    const drawCourses = courses && courses.length > 0
      ? courses
      : buildDefaultCourses(px, py, pw, ph)

    drawCourses.forEach(({ paths, color, angle }, ci) => {
      ctx.strokeStyle = color || `hsl(${45 + ci * 30}, 85%, 55%)`
      ctx.lineWidth = 2.5
      ctx.globalAlpha = 0.75
      paths.forEach(([x1, y1, x2, y2]) => {
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.stroke()
      })
      ctx.globalAlpha = 1
    })

    // Axis labels
    ctx.fillStyle = '#475569'
    ctx.font = '8px monospace'
    ctx.fillText('X', W - 16, H - 8)
    ctx.fillText('Y', 6, 14)

    // Origin dot
    ctx.fillStyle = '#fbbf24'
    ctx.beginPath()
    ctx.arc(px, py + ph, 3, 0, Math.PI * 2)
    ctx.fill()
  }, [courses, partWidth, partHeight, loading])

  return (
    <canvas
      ref={canvasRef}
      width={500}
      height={300}
      style={{
        width: '100%',
        height: '100%',
        display: 'block',
        imageRendering: 'crisp-edges',
      }}
      aria-label="AFP toolpath 2D view"
      role="img"
    />
  )
}

function buildDefaultCourses(px, py, pw, ph) {
  const angles = [0, 45, -45, 90]
  const colors = ['#4adeae', '#fbbf24', '#a78bfa', '#f97888']
  return angles.map((angle, ai) => {
    const rad = (angle * Math.PI) / 180
    const cos = Math.cos(rad), sin = Math.sin(rad)
    const paths = []
    const step = 14
    for (let d = -pw; d < pw + ph; d += step) {
      // Clip to part bounds via parametric line + rect clipping
      const cx = px + pw / 2, cy = py + ph / 2
      const x1 = cx + d - ph * cos * 2
      const y1 = cy - d * 0 + d * sin / (Math.abs(cos) + 0.01) - ph * sin * 2
      const x2 = cx + d + ph * cos * 2
      const y2 = cy - d * 0 + d * sin / (Math.abs(cos) + 0.01) + ph * sin * 2

      // Simple rect clip
      const cx1 = Math.max(px, Math.min(px + pw, px + ((d + pw / 2) % pw + pw) % pw))
      const cy1 = py
      const cx2 = cx1
      const cy2 = py + ph

      const lx1 = px + (d < 0 ? 0 : d > pw ? pw : d)
      const lx2 = px + Math.min(pw, Math.max(0, d + step))
      if (angle === 0) {
        paths.push([px, py + d, px + pw, py + d])
      } else if (angle === 90) {
        paths.push([px + d, py, px + d, py + ph])
      } else {
        paths.push([px, py + d - pw * Math.tan(rad), px + pw, py + d])
      }
    }
    return { paths: paths.filter((_, i) => i % 1 === 0).slice(0, 18), color: colors[ai], angle }
  })
}

// ---------------------------------------------------------------------------
// Cure Cycle SVG chart
// ---------------------------------------------------------------------------
function CureCyclePlot({ params }) {
  const data = buildCureCycle(params)
  if (!data.length) return null

  const W = 460, H = 140, pad = { l: 42, r: 16, t: 16, b: 32 }
  const iW = W - pad.l - pad.r
  const iH = H - pad.t - pad.b

  const tMax = data[data.length - 1].t
  const tempMin = 20, tempMax = 200

  const px = (t) => pad.l + (t / tMax) * iW
  const py = (temp) => pad.t + iH - ((temp - tempMin) / (tempMax - tempMin)) * iH

  const linePts = data.map((p) => `${px(p.t)},${py(p.temp)}`).join(' ')

  // Fill area
  const fillPts = [
    `${px(0)},${py(tempMin)}`,
    ...data.map((p) => `${px(p.t)},${py(p.temp)}`),
    `${px(tMax)},${py(tempMin)}`,
  ].join(' ')

  // Dwell zone
  const dwellStart = data.findIndex((p) => p.temp >= params.dwellTemp - 0.5)
  const dwellEnd = data.slice().reverse().findIndex((p) => p.temp >= params.dwellTemp - 0.5)
  const dwellEndIdx = data.length - 1 - dwellEnd

  const gridTemps = [25, 60, 120, 180]
  const gridTimes = [0, 30, 60, 90, 120, tMax]

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      style={{ display: 'block' }}
      role="img"
      aria-label="Cure cycle temperature profile"
    >
      {/* BG */}
      <rect width={W} height={H} fill="#06090f" />
      {/* Grid lines */}
      {gridTemps.map((temp) => (
        <g key={temp}>
          <line
            x1={pad.l} y1={py(temp)} x2={pad.l + iW} y2={py(temp)}
            stroke="#1e293b" strokeWidth={0.5}
          />
          <text x={pad.l - 4} y={py(temp) + 3} fill="#475569" fontSize={7} textAnchor="end" fontFamily="monospace">
            {temp}
          </text>
        </g>
      ))}
      {gridTimes.filter((t) => t <= tMax).map((t) => (
        <g key={t}>
          <line
            x1={px(t)} y1={pad.t} x2={px(t)} y2={pad.t + iH}
            stroke="#1e293b" strokeWidth={0.5}
          />
          <text x={px(t)} y={pad.t + iH + 12} fill="#475569" fontSize={7} textAnchor="middle" fontFamily="monospace">
            {t}m
          </text>
        </g>
      ))}
      {/* Dwell zone highlight */}
      {dwellStart >= 0 && (
        <rect
          x={px(data[dwellStart].t)}
          y={pad.t}
          width={px(data[dwellEndIdx].t) - px(data[dwellStart].t)}
          height={iH}
          fill="rgba(251,191,36,0.06)"
          stroke="rgba(251,191,36,0.2)"
          strokeWidth={0.5}
          strokeDasharray="3 3"
        />
      )}
      {/* Fill */}
      <polygon points={fillPts} fill="rgba(251,191,36,0.07)" />
      {/* Line */}
      <polyline points={linePts} fill="none" stroke="#fbbf24" strokeWidth={1.5} strokeLinejoin="round" />
      {/* Axis labels */}
      <text x={pad.l - 28} y={pad.t + iH / 2 + 3} fill="#64748b" fontSize={7} fontFamily="monospace"
        transform={`rotate(-90, ${pad.l - 28}, ${pad.t + iH / 2 + 3})`} textAnchor="middle">
        °C
      </text>
      <text x={pad.l + iW / 2} y={H - 4} fill="#64748b" fontSize={7} fontFamily="monospace" textAnchor="middle">
        Time (min)
      </text>
      {/* Dwell label */}
      {dwellStart >= 0 && (
        <text
          x={(px(data[dwellStart].t) + px(data[dwellEndIdx].t)) / 2}
          y={pad.t + 10}
          fill="#fbbf24"
          fontSize={7}
          fontFamily="monospace"
          textAnchor="middle"
          opacity={0.7}
        >
          DWELL {params.dwellTemp}°C
        </text>
      )}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function AFPToolpathView({ file, projectId }) {
  const [params, setParams] = useState({
    courseWidth: 6.35,
    minRadius: 600,
    towCount: 8,
    angle: 0,
    rampRate: 2,
    dwellTemp: 180,
    dwellTime: 60,
    coolRate: 3,
  })
  const [courses, setCourses] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [exportMenuOpen, setExportMenuOpen] = useState(false)

  const runPathplan = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await callAFPPathplan(params)
      setResult(res)
      // If backend returns path data, use it; else keep SVG illustration
      if (res?.courses) setCourses(res.courses)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [params])

  const exportCNC = useCallback(async (format) => {
    setExportMenuOpen(false)
    setExporting(true)
    setError(null)
    try {
      const text = await callAFPExport(params, format)
      const ext = format === 'gcode' ? 'gcode' : 'apt'
      const blob = new Blob([text], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `afp_toolpath.${ext}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(`Export failed: ${e.message}`)
    } finally {
      setExporting(false)
    }
  }, [params])

  const update = (field, val) => setParams((p) => ({
    ...p,
    [field]: parseFloat(val) || p[field],
  }))

  const styles = {
    root: {
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: '#07090f',
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
      background: '#05070e',
    },
    title: {
      fontSize: 11,
      fontWeight: 600,
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: '#fbbf24',
    },
    body: {
      display: 'flex',
      flex: 1,
      minHeight: 0,
      overflow: 'hidden',
    },
    controls: {
      width: 180,
      flexShrink: 0,
      borderRight: '1px solid #1e293b',
      padding: '12px 10px',
      overflow: 'auto',
      background: '#060a12',
    },
    ctrlGroup: {
      marginBottom: 16,
    },
    ctrlGroupLabel: {
      fontSize: 9,
      letterSpacing: '0.15em',
      textTransform: 'uppercase',
      color: '#475569',
      marginBottom: 6,
    },
    ctrlRow: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 5,
    },
    ctrlLabel: {
      fontSize: 10,
      color: '#94a3b8',
    },
    ctrlInput: {
      width: 60,
      background: '#0d1321',
      border: '1px solid #1e293b',
      borderRadius: 3,
      color: '#e2e8f0',
      fontFamily: 'inherit',
      fontSize: 10,
      padding: '2px 5px',
      textAlign: 'right',
      outline: 'none',
    },
    main: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      minWidth: 0,
      overflow: 'hidden',
    },
    canvasWrap: {
      flex: '0 0 auto',
      height: 220,
      position: 'relative',
      borderBottom: '1px solid #1e293b',
      overflow: 'hidden',
    },
    sectionLabel: {
      position: 'absolute',
      top: 8,
      left: 10,
      fontSize: 9,
      color: '#fbbf24',
      textTransform: 'uppercase',
      letterSpacing: '0.15em',
      zIndex: 1,
    },
    chartWrap: {
      flex: 1,
      padding: '8px 10px',
      overflow: 'hidden',
    },
    chartLabel: {
      fontSize: 9,
      color: '#fbbf24',
      textTransform: 'uppercase',
      letterSpacing: '0.15em',
      marginBottom: 4,
    },
    runBtn: {
      padding: '5px 14px',
      background: 'rgba(251,191,36,0.1)',
      border: '1px solid rgba(251,191,36,0.35)',
      borderRadius: 3,
      color: '#fbbf24',
      fontFamily: 'inherit',
      fontSize: 9,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      cursor: 'pointer',
    },
    exportWrap: {
      position: 'relative',
      display: 'inline-block',
    },
    exportBtn: {
      padding: '5px 11px',
      background: 'rgba(100,116,139,0.12)',
      border: '1px solid rgba(100,116,139,0.3)',
      borderRadius: 3,
      color: '#94a3b8',
      fontFamily: 'inherit',
      fontSize: 9,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      gap: 4,
    },
    exportMenu: {
      position: 'absolute',
      top: '100%',
      right: 0,
      marginTop: 2,
      background: '#0d1321',
      border: '1px solid #1e293b',
      borderRadius: 3,
      zIndex: 50,
      minWidth: 130,
      boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
    },
    exportMenuItem: {
      display: 'block',
      width: '100%',
      textAlign: 'left',
      padding: '7px 12px',
      background: 'none',
      border: 'none',
      color: '#cbd5e1',
      fontFamily: 'inherit',
      fontSize: 10,
      cursor: 'pointer',
      letterSpacing: '0.05em',
    },
    errorMsg: {
      fontSize: 9,
      color: '#f87171',
      padding: '4px 0',
    },
    resultStats: {
      display: 'flex',
      gap: 12,
      flexWrap: 'wrap',
      marginTop: 6,
      fontSize: 10,
    },
  }

  return (
    <div style={styles.root} data-testid="afp-toolpath-view">
      <div style={styles.header}>
        <span style={styles.title}>AFP Toolpath Planner</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {error && <span style={{ fontSize: 9, color: '#f87171' }}>{error}</span>}
          {/* Export CNC dropdown */}
          <div style={styles.exportWrap}>
            <button
              style={styles.exportBtn}
              type="button"
              disabled={exporting}
              onClick={() => setExportMenuOpen((o) => !o)}
              title="Export toolpath as CNC program"
            >
              {exporting ? '⟳' : '⬇'} Export CNC ▾
            </button>
            {exportMenuOpen && (
              <div style={styles.exportMenu}>
                <button
                  style={styles.exportMenuItem}
                  type="button"
                  onClick={() => exportCNC('gcode')}
                  onMouseEnter={(e) => { e.target.style.background = '#1e293b'; e.target.style.color = '#fbbf24' }}
                  onMouseLeave={(e) => { e.target.style.background = 'none'; e.target.style.color = '#cbd5e1' }}
                >
                  G-code (.gcode)
                </button>
                <button
                  style={styles.exportMenuItem}
                  type="button"
                  onClick={() => exportCNC('apt')}
                  onMouseEnter={(e) => { e.target.style.background = '#1e293b'; e.target.style.color = '#fbbf24' }}
                  onMouseLeave={(e) => { e.target.style.background = 'none'; e.target.style.color = '#cbd5e1' }}
                >
                  APT / CL (.apt)
                </button>
              </div>
            )}
          </div>
          <button style={styles.runBtn} onClick={runPathplan} type="button" disabled={loading}>
            {loading ? '⟳ Running…' : '▶ Plan Paths'}
          </button>
        </div>
      </div>

      <div style={styles.body}>
        {/* Controls */}
        <div style={styles.controls}>
          <div style={styles.ctrlGroup}>
            <div style={styles.ctrlGroupLabel}>AFP Parameters</div>
            {[
              { label: 'Course W (mm)', field: 'courseWidth', step: 0.1 },
              { label: 'Min R (mm)',    field: 'minRadius',  step: 10 },
              { label: 'Tow count',    field: 'towCount',   step: 1 },
              { label: 'Angle (°)',    field: 'angle',      step: 15 },
            ].map(({ label, field, step }) => (
              <div key={field} style={styles.ctrlRow}>
                <span style={styles.ctrlLabel}>{label}</span>
                <input
                  type="number"
                  style={styles.ctrlInput}
                  value={params[field]}
                  step={step}
                  onChange={(e) => update(field, e.target.value)}
                />
              </div>
            ))}
          </div>

          <div style={styles.ctrlGroup}>
            <div style={styles.ctrlGroupLabel}>Cure Cycle</div>
            {[
              { label: 'Ramp (°C/min)', field: 'rampRate',  step: 0.5 },
              { label: 'Dwell (°C)',    field: 'dwellTemp', step: 5 },
              { label: 'Dwell (min)',   field: 'dwellTime', step: 5 },
              { label: 'Cool (°C/min)', field: 'coolRate',  step: 0.5 },
            ].map(({ label, field, step }) => (
              <div key={field} style={styles.ctrlRow}>
                <span style={styles.ctrlLabel}>{label}</span>
                <input
                  type="number"
                  style={styles.ctrlInput}
                  value={params[field]}
                  step={step}
                  onChange={(e) => update(field, e.target.value)}
                />
              </div>
            ))}
          </div>

          {result && (
            <div>
              <div style={{ ...styles.ctrlGroupLabel, marginBottom: 4 }}>Result</div>
              <div style={styles.resultStats}>
                {Object.entries(result).filter(([k]) => !['courses'].includes(k)).slice(0, 6).map(([k, v]) => (
                  <div key={k}>
                    <div style={{ fontSize: 8, color: '#475569' }}>{k}</div>
                    <div style={{ fontSize: 10, color: '#fbbf24' }}>{typeof v === 'number' ? v.toFixed(2) : String(v)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Main panel */}
        <div style={styles.main}>
          <div style={styles.canvasWrap}>
            <span style={styles.sectionLabel}>Tape Layout</span>
            <AFPCanvas courses={courses} loading={loading} />
          </div>
          <div style={styles.chartWrap}>
            <div style={styles.chartLabel}>Cure Cycle Profile</div>
            <CureCyclePlot params={params} />
          </div>
        </div>
      </div>
    </div>
  )
}
