/**
 * IrrigationPanel.jsx — Sprinkler layout visualiser + zone flow demand panel.
 *
 * Renders:
 *   • SVG plan showing sprinkler head positions with arc coverage circles
 *   • Per-zone GPM table from landscape_flow_demand
 *   • Dispatch buttons for landscape_layout_sprinkler and landscape_flow_demand
 *
 * Dispatches:
 *   • `landscape_layout_sprinkler` — head placement grid (Hunter/Rain Bird/Toro models)
 *   • `landscape_flow_demand`      — per-zone GPM breakdown
 *   via POST /api/tools/call
 *
 * Props
 * ─────
 *   width_ft      {number}  Rectangle width [ft] (default 60).
 *   length_ft     {number}  Rectangle length [ft] (default 40).
 *   sprinklerKind {string}  Key from SPRINKLER_CATALOG (default 'Hunter_PGP').
 *   pattern       {string}  'square'|'triangular'|'oblong' (default 'square').
 *   zoneCount     {number}  Number of irrigation zones (default 4).
 *   svgWidth      {number}  Canvas pixel width (default 560).
 *   svgHeight     {number}  Canvas pixel height (default 360).
 *   className     {string}
 *   onDispatch    {function}  Called with { tool, params } instead of fetch.
 */

import { useMemo, useState } from 'react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''
const PADDING = 40

// ---------------------------------------------------------------------------
// Sprinkler arc colours by arc degree
// ---------------------------------------------------------------------------

const ARC_FILL = {
  90:  'rgba(59,130,246,0.18)',
  180: 'rgba(34,197,94,0.15)',
  270: 'rgba(245,158,11,0.12)',
  360: 'rgba(168,85,247,0.10)',
}
const ARC_STROKE = {
  90:  '#3b82f6',
  180: '#22c55e',
  270: '#f59e0b',
  360: '#a855f7',
}

// ---------------------------------------------------------------------------
// Arc SVG path helper (sector)
// ---------------------------------------------------------------------------

function arcPath(cx, cy, r, arcDeg) {
  if (arcDeg >= 360) {
    return `M ${cx} ${cy} m -${r} 0 a ${r} ${r} 0 1 0 ${r * 2} 0 a ${r} ${r} 0 1 0 -${r * 2} 0`
  }
  const startRad = -Math.PI / 2  // start from top
  const endRad = startRad + (arcDeg * Math.PI) / 180
  const x1 = cx + r * Math.cos(startRad)
  const y1 = cy + r * Math.sin(startRad)
  const x2 = cx + r * Math.cos(endRad)
  const y2 = cy + r * Math.sin(endRad)
  const largeArc = arcDeg > 180 ? 1 : 0
  return `M ${cx} ${cy} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function IrrigationPanel({
  width_ft = 60,
  length_ft = 40,
  sprinklerKind = 'Hunter_PGP',
  pattern = 'square',
  zoneCount = 4,
  svgWidth = 560,
  svgHeight = 360,
  className = '',
  onDispatch,
}) {
  const [loading, setLoading] = useState(false)
  const [positions, setPositions] = useState(null)
  const [sprinklerMeta, setSprinklerMeta] = useState(null)
  const [zoneResult, setZoneResult] = useState(null)
  const [error, setError] = useState(null)
  const [activeAction, setActiveAction] = useState(null)

  // Compute scale to fit the rectangle
  const { scaleX, scaleY, offX, offY } = useMemo(() => {
    const usableW = svgWidth - PADDING * 2
    const usableH = svgHeight - PADDING * 2
    const sx = usableW / (width_ft || 1)
    const sy = usableH / (length_ft || 1)
    const s = Math.min(sx, sy)
    return {
      scaleX: s,
      scaleY: s,
      offX: PADDING + (usableW - (width_ft * s)) / 2,
      offY: PADDING + (usableH - (length_ft * s)) / 2,
    }
  }, [svgWidth, svgHeight, width_ft, length_ft])

  function toSVG(xFt, yFt) {
    return [xFt * scaleX + offX, yFt * scaleY + offY]
  }

  // ── Layout sprinklers ──────────────────────────────────────────────────────
  async function handleLayout() {
    setLoading(true)
    setActiveAction('layout')
    setError(null)
    setZoneResult(null)
    const params = { width_ft, length_ft, sprinkler_kind: sprinklerKind, pattern }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'landscape_layout_sprinkler', params })
        setPositions(null)
        setSprinklerMeta(null)
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'landscape_layout_sprinkler', params }),
        })
        const data = await res.json()
        if (data.ok) {
          setPositions(data.positions)
          setSprinklerMeta(data.sprinkler)
        } else {
          setError(data.error || 'Layout failed')
        }
      }
    } catch (e) {
      setError(e.message || 'Layout dispatch failed')
    } finally {
      setLoading(false)
      setActiveAction(null)
    }
  }

  // ── Zone flow demand ───────────────────────────────────────────────────────
  async function handleFlowDemand() {
    if (!positions) return
    setLoading(true)
    setActiveAction('flow')
    setError(null)
    const params = {
      positions,
      zone_count: zoneCount,
      sprinkler_kind: sprinklerKind,
    }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'landscape_flow_demand', params })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'landscape_flow_demand', params }),
        })
        const data = await res.json()
        if (data.ok) {
          setZoneResult(data)
        } else {
          setError(data.error || 'Flow demand failed')
        }
      }
    } catch (e) {
      setError(e.message || 'Flow demand dispatch failed')
    } finally {
      setLoading(false)
      setActiveAction(null)
    }
  }

  const headCount = positions?.length ?? 0
  const radiusFt = sprinklerMeta?.radius_ft ?? 15

  return (
    <div className={`flex flex-col gap-2 ${className}`} data-testid="irrigation-panel">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-slate-500 font-medium tracking-wide uppercase">
          Irrigation Layout
        </span>
        <div className="flex items-center gap-2">
          <button
            className="text-xs px-2 py-1 rounded border border-slate-600 hover:border-slate-400 text-slate-300 disabled:opacity-50 transition-colors"
            onClick={handleLayout}
            disabled={loading}
            data-testid="irrigation-layout-btn"
          >
            {loading && activeAction === 'layout' ? 'Computing…' : 'Place heads'}
          </button>
          <button
            className="text-xs px-2 py-1 rounded bg-kerf-700 hover:bg-kerf-600 text-white disabled:opacity-50 transition-colors"
            onClick={handleFlowDemand}
            disabled={loading || !positions}
            data-testid="irrigation-flow-btn"
          >
            {loading && activeAction === 'flow' ? 'Running…' : 'Zone flow demand'}
          </button>
        </div>
      </div>

      {/* SVG canvas */}
      <svg
        width={svgWidth}
        height={svgHeight}
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="rounded border border-slate-800"
        style={{ background: '#0f172a' }}
        aria-label="Irrigation layout plan"
        role="img"
        data-testid="irrigation-svg"
      >
        {/* Site boundary */}
        <rect
          x={offX}
          y={offY}
          width={width_ft * scaleX}
          height={length_ft * scaleY}
          fill="none"
          stroke="#334155"
          strokeWidth="1.5"
          strokeDasharray="4 3"
        />

        {/* Area label */}
        <text
          x={offX + 4}
          y={offY + 12}
          fontSize="9"
          fill="#475569"
          fontFamily="monospace"
        >
          {width_ft} × {length_ft} ft
        </text>

        {/* No data state */}
        {!positions && (
          <text
            x={svgWidth / 2}
            y={svgHeight / 2}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize="13"
            fill="#475569"
            fontFamily="system-ui, sans-serif"
          >
            Click &quot;Place heads&quot; to generate layout
          </text>
        )}

        {/* Head coverage arcs + symbols */}
        {positions && positions.map((p, i) => {
          const [sx, sy] = toSVG(p.x, p.y)
          const rPx = radiusFt * scaleX
          const arc = p.arc_deg
          const fill = ARC_FILL[arc] || 'rgba(99,102,241,0.1)'
          const stroke = ARC_STROKE[arc] || '#818cf8'
          return (
            <g key={i}>
              {/* Coverage arc */}
              <path
                d={arcPath(sx, sy, rPx, arc)}
                fill={fill}
                stroke={stroke}
                strokeWidth="0.8"
                opacity="0.7"
              />
              {/* Head symbol */}
              <circle cx={sx} cy={sy} r={3} fill={stroke} opacity="0.9" />
              <circle cx={sx} cy={sy} r={5} fill="none" stroke={stroke} strokeWidth="0.8" opacity="0.5" />
            </g>
          )
        })}

        {/* Legend */}
        {positions && (
          <g transform={`translate(${svgWidth - 130}, 8)`} aria-label="Arc legend">
            <rect x="0" y="0" width="122" height="74" rx="4" fill="#1e293b" opacity="0.9" />
            {[
              [90,  '90° corner'],
              [180, '180° edge'],
              [360, '360° interior'],
            ].map(([deg, label], i) => (
              <g key={deg} transform={`translate(6, ${6 + i * 20})`}>
                <circle cx="6" cy="8" r="4" fill={ARC_STROKE[deg]} opacity="0.8" />
                <text x="16" y="12" fontSize="9" fill="#94a3b8" fontFamily="monospace">
                  {label}
                </text>
              </g>
            ))}
            <text x="6" y="66" fontSize="8" fill="#64748b" fontFamily="monospace">
              {headCount} heads · {sprinklerKind}
            </text>
          </g>
        )}
      </svg>

      {/* Zone flow demand table */}
      {zoneResult && zoneResult.zones && (
        <div className="text-xs font-mono px-1" data-testid="zone-flow-table">
          <div className="text-slate-400 mb-1">
            Zone flow demand — {zoneResult.zone_count} zones · total {zoneResult.total_flow_gpm.toFixed(2)} GPM
          </div>
          <table className="w-full text-slate-300 border-collapse">
            <thead>
              <tr className="text-slate-500">
                <th className="text-left pr-3">Zone</th>
                <th className="text-right pr-3">Heads</th>
                <th className="text-right">GPM</th>
              </tr>
            </thead>
            <tbody>
              {zoneResult.zones.map((z) => (
                <tr key={z.zone} className="border-t border-slate-800">
                  <td className="pr-3">Z{z.zone}</td>
                  <td className="text-right pr-3">{z.head_count}</td>
                  <td className="text-right">{z.total_gpm.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-slate-600 mt-1 text-[10px]">
            Per Hunter Irrigation Design Manual (2003). Flow scaled by arc_deg/360.
          </div>
        </div>
      )}

      {error && (
        <div className="text-xs text-red-400 px-1" data-testid="irrigation-error">
          {error}
        </div>
      )}
    </div>
  )
}
