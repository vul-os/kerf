/**
 * LandscapeView.jsx — plan view with planting symbols and irrigation zones.
 *
 * Renders:
 *   • Irrigation zones as coloured polygon fills (SVG polygon/path)
 *   • Plant symbols (circles with species-coded fill and a dot pattern)
 *   • Hardscape elements (rectangles, paths)
 *
 * Dispatches:
 *   • `landscape_plants`             — place / spec plant list
 *   • `landscape_irrigation_schedule` — schedule irrigation run times
 *   via POST /api/tools/call
 *
 * Props
 * ─────
 *   plants    {Array<{id, x, y, species?, canopy_m?, type?}>}
 *   zones     {Array<{id, label?, points:[[x,y]…], area_m2?, precipitation_rate_mm_hr?,
 *                      soil_type?}>}
 *   hardscape {Array<{id, type:'path'|'patio'|'deck', points:[[x,y]…]}>}
 *   area_m2   {number}  Total site area for scheduling (default 0).
 *   width     {number}  SVG canvas width  (default 600).
 *   height    {number}  SVG canvas height (default 420).
 *   className {string}
 *   onDispatch {function}  Called with { tool, params } instead of fetch.
 */

import { useMemo, useState } from 'react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''
const PADDING = 50

// ---------------------------------------------------------------------------
// Colour palette for irrigation zones (cycles)
// ---------------------------------------------------------------------------

const ZONE_COLOURS = [
  '#3b82f6', '#22c55e', '#f59e0b', '#a855f7',
  '#ec4899', '#06b6d4', '#84cc16', '#ef4444',
]

// ---------------------------------------------------------------------------
// Plant symbol colours by type / category
// ---------------------------------------------------------------------------

const PLANT_COLOURS = {
  tree: '#166534',
  shrub: '#4ade80',
  groundcover: '#a3e635',
  grass: '#bef264',
  perennial: '#fb923c',
  annual: '#f472b6',
  default: '#6ee7b7',
}

// ---------------------------------------------------------------------------
// Fit coordinates to viewport
// ---------------------------------------------------------------------------

function fitPlan(allPts, width, height) {
  if (!allPts.length) return { scale: 1, offX: 0, offY: 0 }
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const [x, y] of allPts) {
    if (x < minX) minX = x; if (x > maxX) maxX = x
    if (y < minY) minY = y; if (y > maxY) maxY = y
  }
  const rangeX = maxX - minX || 1
  const rangeY = maxY - minY || 1
  const usableW = width - PADDING * 2
  const usableH = height - PADDING * 2
  const scale = Math.min(usableW / rangeX, usableH / rangeY)
  const scaledW = rangeX * scale
  const scaledH = rangeY * scale
  return {
    scale,
    offX: PADDING + (usableW - scaledW) / 2 - minX * scale,
    offY: PADDING + (usableH - scaledH) / 2 - minY * scale,
  }
}

// ---------------------------------------------------------------------------
// Plant symbol
// ---------------------------------------------------------------------------

function PlantSymbol({ x, y, canopyPx, type }) {
  const fill = PLANT_COLOURS[type] || PLANT_COLOURS.default
  const isTree = type === 'tree'
  const r = Math.max(6, canopyPx ?? (isTree ? 16 : 10))
  return (
    <g>
      {/* Canopy circle */}
      <circle cx={x} cy={y} r={r} fill={fill} opacity="0.45" stroke={fill} strokeWidth="1" />
      {/* Trunk / centre dot */}
      <circle cx={x} cy={y} r={isTree ? 3 : 2} fill={fill} opacity="0.9" />
      {/* Tree: radial frond lines */}
      {isTree && [0, 60, 120, 180, 240, 300].map((deg) => {
        const rad = (deg * Math.PI) / 180
        const ex = x + Math.cos(rad) * r * 0.7
        const ey = y + Math.sin(rad) * r * 0.7
        return (
          <line
            key={deg}
            x1={x} y1={y} x2={ex} y2={ey}
            stroke={fill}
            strokeWidth="1"
            opacity="0.5"
          />
        )
      })}
    </g>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function LandscapeView({
  plants = [],
  zones = [],
  hardscape = [],
  area_m2 = 0,
  width = 600,
  height = 420,
  className = '',
  onDispatch,
}) {
  const [loading, setLoading] = useState(false)
  const [schedResult, setSchedResult] = useState(null)
  const [error, setError] = useState(null)
  const [activeAction, setActiveAction] = useState(null)

  // Collect all 2-D points for viewport fitting
  const allPts = useMemo(() => {
    const pts = []
    for (const p of plants) if (p.x != null) pts.push([p.x, p.y])
    for (const z of zones) for (const pt of (z.points || [])) pts.push(pt)
    for (const h of hardscape) for (const pt of (h.points || [])) pts.push(pt)
    return pts
  }, [plants, zones, hardscape])

  const { scale, offX, offY } = useMemo(
    () => fitPlan(allPts, width, height),
    [allPts, width, height],
  )

  function toS(x, y) { return [x * scale + offX, y * scale + offY] }
  function ptsToPath(pts) {
    if (!pts?.length) return ''
    const [first, ...rest] = pts
    const [fx, fy] = toS(first[0], first[1])
    return `M${fx.toFixed(1)},${fy.toFixed(1)}` +
      rest.map(([x, y]) => { const [sx, sy] = toS(x, y); return `L${sx.toFixed(1)},${sy.toFixed(1)}` }).join('') +
      'Z'
  }

  // ── Dispatch: place plants ─────────────────────────────────────────────────
  async function handlePlants() {
    setLoading(true)
    setActiveAction('plants')
    setError(null)
    const params = {
      plants: plants.map(p => ({
        id: p.id,
        species: p.species || 'Unspecified',
        type: p.type || 'shrub',
        x: p.x ?? 0,
        y: p.y ?? 0,
        canopy_m: p.canopy_m ?? 1.5,
      })),
    }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'landscape_plants', params })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'landscape_plants', params }),
        })
        await res.json()
      }
    } catch (e) {
      setError(e.message || 'Dispatch failed')
    } finally {
      setLoading(false)
      setActiveAction(null)
    }
  }

  // ── Dispatch: irrigation schedule ─────────────────────────────────────────
  async function handleIrrigationSchedule() {
    setLoading(true)
    setActiveAction('irrigation')
    setError(null)
    const params = {
      zones: zones.map(z => ({
        id: z.id,
        area_m2: z.area_m2 ?? 50,
        precipitation_rate_mm_hr: z.precipitation_rate_mm_hr ?? 25,
        soil_type: z.soil_type || 'loam',
      })),
      area_m2: area_m2 || zones.reduce((s, z) => s + (z.area_m2 ?? 50), 0),
    }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'landscape_irrigation_schedule', params })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'landscape_irrigation_schedule', params }),
        })
        const data = await res.json()
        setSchedResult(data)
      }
    } catch (e) {
      setError(e.message || 'Dispatch failed')
    } finally {
      setLoading(false)
      setActiveAction(null)
    }
  }

  const isEmpty = allPts.length === 0

  return (
    <div
      className={`flex flex-col gap-2 ${className}`}
      data-testid="landscape-view"
    >
      {/* Toolbar */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-slate-500 font-medium tracking-wide uppercase">
          Landscape Plan
        </span>
        <div className="flex items-center gap-2">
          <button
            className="text-xs px-2 py-1 rounded border border-slate-600 hover:border-slate-400 text-slate-300 disabled:opacity-50 transition-colors"
            onClick={handlePlants}
            disabled={loading || plants.length === 0}
            data-testid="landscape-plants-btn"
          >
            {loading && activeAction === 'plants' ? 'Running…' : 'Spec plants'}
          </button>
          <button
            className="text-xs px-2 py-1 rounded bg-kerf-700 hover:bg-kerf-600 text-white disabled:opacity-50 transition-colors"
            onClick={handleIrrigationSchedule}
            disabled={loading || zones.length === 0}
            data-testid="landscape-irrigation-btn"
          >
            {loading && activeAction === 'irrigation' ? 'Running…' : 'Irrigation schedule'}
          </button>
        </div>
      </div>

      {/* SVG canvas */}
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="rounded border border-slate-800"
        style={{ background: '#0f172a' }}
        aria-label="Landscape plan view"
        role="img"
      >
        {isEmpty ? (
          <text
            x={width / 2}
            y={height / 2}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize="14"
            fill="#475569"
            fontFamily="system-ui, sans-serif"
          >
            No landscape data — pass plants / zones props
          </text>
        ) : (
          <>
            {/* Background */}
            <rect width={width} height={height} fill="#0d2410" />

            {/* Irrigation zones */}
            <g aria-label="Irrigation zones">
              {zones.map((z, zi) => {
                const d = ptsToPath(z.points)
                if (!d) return null
                const fill = ZONE_COLOURS[zi % ZONE_COLOURS.length]
                // Label at centroid
                const cx = (z.points || []).reduce((s, p) => s + p[0], 0) / (z.points?.length || 1)
                const cy2 = (z.points || []).reduce((s, p) => s + p[1], 0) / (z.points?.length || 1)
                const [lx, ly] = toS(cx, cy2)
                return (
                  <g key={z.id} aria-label={`Zone ${z.label || z.id}`}>
                    <path d={d} fill={fill} opacity="0.15" stroke={fill} strokeWidth="1.5" strokeDasharray="4 3" />
                    <text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle"
                      fontSize="9" fill={fill} fontFamily="monospace" opacity="0.8">
                      {z.label || z.id}
                    </text>
                  </g>
                )
              })}
            </g>

            {/* Hardscape */}
            <g aria-label="Hardscape">
              {hardscape.map((h) => {
                const d = ptsToPath(h.points)
                if (!d) return null
                const fill = h.type === 'deck' ? '#78350f' : '#374151'
                return (
                  <path key={h.id} d={d} fill={fill} opacity="0.6" stroke="#6b7280" strokeWidth="1" />
                )
              })}
            </g>

            {/* Plants */}
            <g aria-label="Plants">
              {plants.map((p) => {
                if (p.x == null || p.y == null) return null
                const [sx, sy] = toS(p.x, p.y)
                const canopyPx = p.canopy_m ? p.canopy_m * scale : undefined
                return (
                  <PlantSymbol
                    key={p.id}
                    x={sx}
                    y={sy}
                    canopyPx={canopyPx}
                    type={p.type || 'shrub'}
                  />
                )
              })}
            </g>

            {/* Plant legend */}
            <g transform={`translate(${width - 120}, 12)`} aria-label="Plant legend">
              <rect x="0" y="0" width="110" height="84" rx="4" fill="#1e293b" opacity="0.9" />
              {['tree', 'shrub', 'groundcover', 'perennial'].map((t, ti) => {
                const fill = PLANT_COLOURS[t]
                return (
                  <g key={t} transform={`translate(8, ${8 + ti * 18})`}>
                    <circle cx="6" cy="6" r="5" fill={fill} opacity="0.7" />
                    <text x="16" y="10" fontSize="9" fill="#94a3b8" fontFamily="monospace">{t}</text>
                  </g>
                )
              })}
            </g>
          </>
        )}
      </svg>

      {/* Schedule result */}
      {schedResult && (
        <div className="text-xs text-slate-400 font-mono px-1">
          {schedResult.ok
            ? `Schedule: ${schedResult.zones?.length || ''} zones · total ${schedResult.total_run_time_min?.toFixed(0) ?? '?'} min`
            : schedResult.error || 'Schedule computed'}
        </div>
      )}
      {error && (
        <div className="text-xs text-red-400 px-1">{error}</div>
      )}
    </div>
  )
}
