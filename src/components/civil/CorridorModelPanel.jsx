/**
 * CorridorModelPanel.jsx — Template-driven corridor model panel.
 *
 * Shows:
 *   1. Cross-section viewer at a selectable station — draws the point-coded
 *      assembly (CL, edge-lane, shoulder, ditch, daylight) as an SVG profile.
 *      Optionally overlays the existing terrain profile at the same station.
 *   2. Mass-haul diagram — Brückner curve (mass ordinate vs station) as an
 *      SVG line chart with cut/fill area fill.
 *   3. Earthwork summary — total cut m³, fill m³, net balance.
 *
 * Props
 * ─────
 *   crossSections  {Array}   Per-station data from civil_corridor_model result:
 *                            [{station_m, cl_elev_m, cut_area_m2, fill_area_m2,
 *                              points:[{offset_m, elev_m, label}]}]
 *   massHaul       {Array}   [{station_m, mass_ordinate_m3, cut_vol_m3, fill_vol_m3}]
 *   earthwork      {Object}  {total_cut_m3, total_fill_m3, net_m3}
 *   alignmentLength {number} Total alignment length (m) — for dispatch.
 *   width          {number}  Panel width (px, default 640).
 *   height         {number}  Panel height (px, default 400).
 *   className      {string}
 *   onDispatch     {function} Called with {tool, params} for "Run model" button.
 *
 * Standalone usage (no pre-loaded data): clicking "Run model" dispatches
 * civil_corridor_model via POST /api/tools/call.
 */

import { useMemo, useState } from 'react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

const LABEL_COLOURS = {
  CL:             '#f8fafc',
  edge_lane_left:  '#60a5fa',
  edge_lane_right: '#60a5fa',
  shoulder_left:   '#34d399',
  shoulder_right:  '#34d399',
  ditch_left:      '#a78bfa',
  ditch_right:     '#a78bfa',
  daylight_left:   '#f87171',
  daylight_right:  '#f87171',
}

function labelColour(label) {
  return LABEL_COLOURS[label] || '#94a3b8'
}

// ---------------------------------------------------------------------------
// Cross-section SVG
// ---------------------------------------------------------------------------

const XS_W = 400
const XS_H = 200
const XS_PAD = 30

function CrossSectionView({ xs, terrainPts }) {
  if (!xs || !xs.points || xs.points.length === 0) {
    return (
      <svg width={XS_W} height={XS_H} style={{ background: '#0f172a', borderRadius: 4 }}>
        <text x={XS_W / 2} y={XS_H / 2} textAnchor="middle" fill="#475569" fontSize="12"
          fontFamily="system-ui, sans-serif">
          No cross-section data
        </text>
      </svg>
    )
  }

  const pts = xs.points
  const offsets = pts.map(p => p.offset_m)
  const elevs   = pts.map(p => p.elev_m)

  const minOff = Math.min(...offsets)
  const maxOff = Math.max(...offsets)
  const minElev = Math.min(...elevs) - 0.5
  const maxElev = Math.max(...elevs) + 0.5

  const offRange  = maxOff - minOff  || 1
  const elevRange = maxElev - minElev || 1

  const usableW = XS_W - XS_PAD * 2
  const usableH = XS_H - XS_PAD * 2

  function toScreen(off, elev) {
    const sx = XS_PAD + ((off - minOff) / offRange) * usableW
    const sy = XS_PAD + (1 - (elev - minElev) / elevRange) * usableH
    return [sx, sy]
  }

  // Polyline path for design cross-section
  const polyPath = pts.map((p, i) => {
    const [sx, sy] = toScreen(p.offset_m, p.elev_m)
    return `${i === 0 ? 'M' : 'L'}${sx.toFixed(1)},${sy.toFixed(1)}`
  }).join(' ')

  // Terrain overlay (if provided): list of {offset_m, elev_m}
  let terrainPath = null
  if (terrainPts && terrainPts.length >= 2) {
    terrainPath = terrainPts.map((p, i) => {
      const [sx, sy] = toScreen(p.offset_m, p.elev_m)
      return `${i === 0 ? 'M' : 'L'}${sx.toFixed(1)},${sy.toFixed(1)}`
    }).join(' ')
  }

  // Pavement fill polygon (from leftmost edge-lane to rightmost edge-lane, closed at bottom)
  const pavePts = pts.filter(p =>
    p.label === 'edge_lane_left' || p.label === 'CL' || p.label === 'edge_lane_right'
  )
  let pavePath = null
  if (pavePts.length >= 2) {
    const paveScreenPts = pavePts.map(p => toScreen(p.offset_m, p.elev_m))
    // Close at the bottom
    const botY = XS_PAD + usableH
    const p0 = paveScreenPts[0]
    const p1 = paveScreenPts[paveScreenPts.length - 1]
    const d = paveScreenPts.map(([sx, sy], i) => `${i === 0 ? 'M' : 'L'}${sx.toFixed(1)},${sy.toFixed(1)}`).join(' ')
    pavePath = `${d} L${p1[0].toFixed(1)},${botY} L${p0[0].toFixed(1)},${botY} Z`
  }

  // Axis labels
  const clScreen = toScreen(0, xs.cl_elev_m)

  return (
    <svg width={XS_W} height={XS_H} viewBox={`0 0 ${XS_W} ${XS_H}`}
      style={{ background: '#0f172a', borderRadius: 4 }}
      aria-label="Cross-section view"
      role="img">

      {/* Ground reference line */}
      <line x1={XS_PAD} y1={XS_PAD + usableH} x2={XS_PAD + usableW} y2={XS_PAD + usableH}
        stroke="#334155" strokeWidth="1" />

      {/* Pavement fill */}
      {pavePath && (
        <path d={pavePath} fill="#1e3a5f" opacity="0.6" />
      )}

      {/* Terrain overlay */}
      {terrainPath && (
        <path d={terrainPath} fill="none" stroke="#92400e" strokeWidth="1.5"
          strokeDasharray="4 2" opacity="0.8" />
      )}

      {/* Design cross-section */}
      <path d={polyPath} fill="none" stroke="#64748b" strokeWidth="1.5" />

      {/* Coded points */}
      {pts.map((p, i) => {
        const [sx, sy] = toScreen(p.offset_m, p.elev_m)
        const col = labelColour(p.label)
        return (
          <g key={i}>
            <circle cx={sx} cy={sy} r={3} fill={col} />
            {/* Label abbreviation on significant points */}
            {(p.label === 'CL' || p.label.startsWith('daylight') || p.label.startsWith('shoulder')) && (
              <text x={sx} y={sy - 5} textAnchor="middle" fontSize="7" fill={col}
                fontFamily="monospace">
                {p.label === 'CL' ? 'CL' :
                  p.label.startsWith('daylight') ? 'DT' :
                  p.label.startsWith('shoulder') ? 'SH' : ''}
              </text>
            )}
          </g>
        )
      })}

      {/* CL tick */}
      <line x1={clScreen[0]} y1={XS_PAD} x2={clScreen[0]} y2={XS_PAD + usableH}
        stroke="#475569" strokeWidth="0.5" strokeDasharray="3 3" />

      {/* Axis labels */}
      <text x={XS_W / 2} y={XS_H - 4} textAnchor="middle" fontSize="9"
        fill="#64748b" fontFamily="monospace">
        offset (m) — sta {xs.station_m?.toFixed(0) ?? '?'}
      </text>
      <text x={4} y={XS_PAD} fontSize="9" fill="#64748b" fontFamily="monospace"
        dominantBaseline="hanging">
        {maxElev.toFixed(1)}m
      </text>
      <text x={4} y={XS_H - XS_PAD} fontSize="9" fill="#64748b" fontFamily="monospace">
        {minElev.toFixed(1)}m
      </text>

      {/* Cut/fill area indicators */}
      {xs.cut_area_m2 > 0.001 && (
        <text x={XS_W - 5} y={12} textAnchor="end" fontSize="8" fill="#f87171"
          fontFamily="monospace">
          cut {xs.cut_area_m2.toFixed(2)} m²
        </text>
      )}
      {xs.fill_area_m2 > 0.001 && (
        <text x={XS_W - 5} y={22} textAnchor="end" fontSize="8" fill="#34d399"
          fontFamily="monospace">
          fill {xs.fill_area_m2.toFixed(2)} m²
        </text>
      )}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Mass-haul SVG chart
// ---------------------------------------------------------------------------

const MH_W = 400
const MH_H = 180
const MH_PAD_L = 48
const MH_PAD_R = 12
const MH_PAD_T = 16
const MH_PAD_B = 28

function MassHaulChart({ massHaul }) {
  if (!massHaul || massHaul.length < 2) {
    return (
      <svg width={MH_W} height={MH_H} style={{ background: '#0f172a', borderRadius: 4 }}>
        <text x={MH_W / 2} y={MH_H / 2} textAnchor="middle" fill="#475569" fontSize="11"
          fontFamily="system-ui, sans-serif">
          No mass-haul data
        </text>
      </svg>
    )
  }

  const stations = massHaul.map(m => m.station_m)
  const ordinates = massHaul.map(m => m.mass_ordinate_m3)

  const minSta = Math.min(...stations)
  const maxSta = Math.max(...stations)
  const minOrd = Math.min(0, ...ordinates)
  const maxOrd = Math.max(0, ...ordinates)
  const staRange = maxSta - minSta || 1
  const ordRange = (maxOrd - minOrd) || 1

  const usableW = MH_W - MH_PAD_L - MH_PAD_R
  const usableH = MH_H - MH_PAD_T - MH_PAD_B

  function sx(sta)  { return MH_PAD_L + ((sta - minSta) / staRange) * usableW }
  function sy(ord)  { return MH_PAD_T + (1 - (ord - minOrd) / ordRange) * usableH }

  // Zero line y position
  const zeroY = sy(0)

  // Build path and fill areas
  const linePath = massHaul.map((m, i) =>
    `${i === 0 ? 'M' : 'L'}${sx(m.station_m).toFixed(1)},${sy(m.mass_ordinate_m3).toFixed(1)}`
  ).join(' ')

  // Fill area above zero (cut excess = waste)
  const cutFill = massHaul
    .map(m => [sx(m.station_m), sy(Math.max(0, m.mass_ordinate_m3))])
  const cutFillPath = cutFill.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    + ` L${cutFill[cutFill.length - 1][0].toFixed(1)},${zeroY.toFixed(1)}`
    + ` L${cutFill[0][0].toFixed(1)},${zeroY.toFixed(1)} Z`

  // Fill area below zero (fill deficit = borrow)
  const fillFill = massHaul
    .map(m => [sx(m.station_m), sy(Math.min(0, m.mass_ordinate_m3))])
  const fillFillPath = fillFill.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    + ` L${fillFill[fillFill.length - 1][0].toFixed(1)},${zeroY.toFixed(1)}`
    + ` L${fillFill[0][0].toFixed(1)},${zeroY.toFixed(1)} Z`

  // Axis ticks (stations)
  const tickCount = Math.min(5, massHaul.length)
  const ticks = Array.from({ length: tickCount }, (_, i) =>
    massHaul[Math.round(i * (massHaul.length - 1) / (tickCount - 1))]
  )

  return (
    <svg width={MH_W} height={MH_H} viewBox={`0 0 ${MH_W} ${MH_H}`}
      style={{ background: '#0f172a', borderRadius: 4 }}
      aria-label="Mass haul diagram"
      role="img"
      data-testid="mass-haul-chart">

      {/* Cut fill (positive ordinate = excess/waste) */}
      <path d={cutFillPath} fill="#f87171" opacity="0.25" />

      {/* Fill borrow (negative ordinate = deficit/borrow) */}
      <path d={fillFillPath} fill="#34d399" opacity="0.25" />

      {/* Zero line */}
      <line x1={MH_PAD_L} y1={zeroY} x2={MH_W - MH_PAD_R} y2={zeroY}
        stroke="#475569" strokeWidth="1" />

      {/* Mass haul curve */}
      <path d={linePath} fill="none" stroke="#60a5fa" strokeWidth="1.5" />

      {/* Axes */}
      <line x1={MH_PAD_L} y1={MH_PAD_T} x2={MH_PAD_L} y2={MH_PAD_T + usableH}
        stroke="#475569" strokeWidth="1" />
      <line x1={MH_PAD_L} y1={MH_PAD_T + usableH} x2={MH_W - MH_PAD_R} y2={MH_PAD_T + usableH}
        stroke="#475569" strokeWidth="1" />

      {/* X ticks */}
      {ticks.map((m, i) => (
        <g key={i}>
          <line x1={sx(m.station_m)} y1={MH_PAD_T + usableH}
            x2={sx(m.station_m)} y2={MH_PAD_T + usableH + 4}
            stroke="#475569" strokeWidth="1" />
          <text x={sx(m.station_m)} y={MH_PAD_T + usableH + 13}
            textAnchor="middle" fontSize="8" fill="#64748b" fontFamily="monospace">
            {m.station_m.toFixed(0)}
          </text>
        </g>
      ))}

      {/* Y label */}
      <text x={0} y={MH_PAD_T + usableH / 2} fontSize="8" fill="#64748b"
        fontFamily="monospace" transform={`rotate(-90, 8, ${MH_PAD_T + usableH / 2})`}
        textAnchor="middle">
        mass (m³)
      </text>

      {/* Labels */}
      <text x={MH_W / 2} y={MH_H - 3} textAnchor="middle" fontSize="9"
        fill="#64748b" fontFamily="monospace">
        station (m)
      </text>

      {/* Legend */}
      <rect x={MH_W - 75} y={6} width={8} height={6} fill="#f87171" opacity="0.5" />
      <text x={MH_W - 65} y={13} fontSize="7" fill="#94a3b8" fontFamily="monospace">waste</text>
      <rect x={MH_W - 75} y={16} width={8} height={6} fill="#34d399" opacity="0.5" />
      <text x={MH_W - 65} y={23} fontSize="7" fill="#94a3b8" fontFamily="monospace">borrow</text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CorridorModelPanel({
  crossSections: initialXS,
  massHaul: initialMH,
  earthwork: initialEW,
  alignmentLength = 200.0,
  width = 640,
  height = 400,
  className = '',
  onDispatch,
}) {
  const [crossSections, setCrossSections] = useState(initialXS || null)
  const [massHaul, setMassHaul]           = useState(initialMH || null)
  const [earthwork, setEarthwork]         = useState(initialEW || null)
  const [loading, setLoading]             = useState(false)
  const [error, setError]                 = useState(null)
  const [stationIdx, setStationIdx]       = useState(0)

  const stationCount = crossSections?.length ?? 0
  const currentXS = crossSections?.[stationIdx] ?? null

  // Default params for dispatch
  const defaultParams = {
    alignment_length_m: alignmentLength,
    interval_m: 20.0,
    lane_width_m: 3.65,
    shoulder_width_m: 2.4,
    lanes_each_side: 1,
    crown_slope_pct: 2.0,
    shoulder_slope_pct: 5.0,
    cut_slope: 2.0,
    fill_slope: 2.0,
  }

  async function handleRun() {
    setLoading(true)
    setError(null)
    try {
      if (onDispatch) {
        onDispatch({ tool: 'civil_corridor_model', params: defaultParams })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'civil_corridor_model', params: defaultParams }),
        })
        const data = await res.json()
        if (data.ok) {
          setCrossSections(data.cross_sections)
          setMassHaul(data.mass_haul)
          setEarthwork(data.earthwork)
          setStationIdx(0)
        } else {
          setError(data.reason || data.error || 'Run failed')
        }
      }
    } catch (e) {
      setError(e.message || 'Dispatch failed')
    } finally {
      setLoading(false)
    }
  }

  const hasData = !!crossSections && crossSections.length > 0

  return (
    <div
      className={`flex flex-col gap-3 ${className}`}
      data-testid="corridor-model-panel"
      style={{ width }}
    >
      {/* ── Header / toolbar ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs font-semibold text-slate-400 tracking-wide uppercase">
          Corridor Model
        </span>
        <button
          className="text-xs px-3 py-1 rounded bg-kerf-700 hover:bg-kerf-600 text-white disabled:opacity-50 transition-colors"
          onClick={handleRun}
          disabled={loading}
          data-testid="corridor-run-btn"
        >
          {loading ? 'Running…' : 'Run model'}
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-400 px-1 font-mono" data-testid="corridor-error">
          {error}
        </div>
      )}

      {/* ── Earthwork summary ─────────────────────────────────────────────── */}
      {earthwork && (
        <div
          className="flex gap-4 px-2 py-1 rounded bg-slate-800 text-xs font-mono"
          data-testid="earthwork-summary"
          aria-label="Earthwork summary"
        >
          <span className="text-red-400">
            cut {earthwork.total_cut_m3?.toFixed(1) ?? '–'} m³
          </span>
          <span className="text-green-400">
            fill {earthwork.total_fill_m3?.toFixed(1) ?? '–'} m³
          </span>
          <span className={earthwork.net_m3 >= 0 ? 'text-green-300' : 'text-red-300'}>
            net {earthwork.net_m3 >= 0 ? '+' : ''}{earthwork.net_m3?.toFixed(1) ?? '–'} m³
          </span>
        </div>
      )}

      {/* ── Station slider ────────────────────────────────────────────────── */}
      {hasData && (
        <div className="flex items-center gap-2 px-1">
          <span className="text-xs text-slate-500 font-mono whitespace-nowrap">
            Station:
          </span>
          <input
            type="range"
            min={0}
            max={stationCount - 1}
            value={stationIdx}
            onChange={e => setStationIdx(Number(e.target.value))}
            className="flex-1 accent-kerf-500"
            aria-label="Station selector"
            data-testid="station-slider"
          />
          <span className="text-xs text-slate-300 font-mono whitespace-nowrap w-16 text-right">
            {currentXS?.station_m?.toFixed(1) ?? '–'} m
          </span>
        </div>
      )}

      {/* ── Cross-section + mass-haul side by side ───────────────────────── */}
      <div className="flex flex-wrap gap-3">
        {/* Cross-section */}
        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-500 font-medium px-1">Cross-section</span>
          <CrossSectionView
            xs={currentXS}
            terrainPts={null}
          />
          {/* Point-code legend */}
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 px-1 mt-0.5">
            {Object.entries(LABEL_COLOURS).slice(0, 5).map(([lbl, col]) => (
              <span key={lbl} className="flex items-center gap-1 text-xs font-mono">
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: col }} />
                <span style={{ color: col }}>{lbl.replace(/_left|_right/, '')}</span>
              </span>
            ))}
          </div>
        </div>

        {/* Mass haul */}
        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-500 font-medium px-1">
            Mass Haul (Brückner)
          </span>
          <MassHaulChart massHaul={massHaul} />
        </div>
      </div>

      {/* ── Empty state ───────────────────────────────────────────────────── */}
      {!hasData && !loading && (
        <div className="text-xs text-slate-500 px-1 font-mono">
          Click "Run model" to generate corridor cross-sections and mass-haul diagram.
        </div>
      )}
    </div>
  )
}
