/**
 * InteriorSpacePanel.jsx — Space planning panel with FF&E layout and area schedule.
 *
 * Renders:
 *   • SVG floor-plan view with placed furniture footprints and circulation paths
 *   • Room area schedule (area, item count, ADA compliance status)
 *   • Finishes schedule table (floor, ceiling, walls)
 *   • Dispatch buttons for interior_room_layout and interior_make_furniture
 *
 * Dispatches:
 *   • `interior_room_layout`    — room audit (ADA clearances, circulation)
 *   • `interior_make_furniture` — parametric FF&E item generation
 *   via POST /api/tools/call
 *
 * Props
 * ─────
 *   room       {object}  { name, width_mm, depth_mm, ceiling_height_mm }
 *   items      {Array<{id, kind, x_mm, y_mm, width_mm, depth_mm, label?, rotation_deg?}>}
 *              Placed furniture items.
 *   circPaths  {Array<{name, start:[x,y], end:[x,y], clear_width_mm}>}
 *   finishes   {object}  { floor?, ceiling?, walls? }  Free-text finish descriptions.
 *   svgWidth   {number}  Canvas pixel width (default 560).
 *   svgHeight  {number}  Canvas pixel height (default 420).
 *   className  {string}
 *   onDispatch {function}  Called with { tool, params } instead of fetch.
 */

import { useMemo, useState } from 'react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''
const PADDING = 44

// ---------------------------------------------------------------------------
// Furniture fill colours by kind
// ---------------------------------------------------------------------------

const KIND_FILL = {
  chair: '#1d4ed8',
  desk:  '#15803d',
  sofa:  '#7c3aed',
  table: '#b45309',
}
const KIND_STROKE = {
  chair: '#3b82f6',
  desk:  '#22c55e',
  sofa:  '#a78bfa',
  table: '#f59e0b',
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function InteriorSpacePanel({
  content,
  room: room_prop = { name: 'Room', width_mm: 6000, depth_mm: 5000, ceiling_height_mm: 2700 },
  items: items_prop = [],
  circPaths: circPaths_prop = [],
  finishes: finishes_prop = {},
  svgWidth = 560,
  svgHeight = 420,
  className = '',
  onDispatch,
}) {
  // Accept a `content` string (JSON) from the panel registry.
  const _p = (() => { if (!content) return {}; try { return JSON.parse(content) } catch { return {} } })()
  const room      = _p.room      ?? room_prop
  const items     = _p.items     ?? items_prop
  const circPaths = _p.circPaths ?? circPaths_prop
  const finishes  = _p.finishes  ?? finishes_prop
  const [loading, setLoading] = useState(false)
  const [activeAction, setActiveAction] = useState(null)
  const [auditResult, setAuditResult] = useState(null)
  const [error, setError] = useState(null)

  const roomW = room.width_mm || 6000
  const roomD = room.depth_mm || 5000

  // Compute scale to fit room
  const { scaleX, scaleY, offX, offY } = useMemo(() => {
    const usableW = svgWidth - PADDING * 2
    const usableH = svgHeight - PADDING * 2
    const sx = usableW / roomW
    const sy = usableH / roomD
    const s = Math.min(sx, sy)
    return {
      scaleX: s,
      scaleY: s,
      offX: PADDING + (usableW - roomW * s) / 2,
      offY: PADDING + (usableH - roomD * s) / 2,
    }
  }, [svgWidth, svgHeight, roomW, roomD])

  function toSVG(xMm, yMm) {
    return [xMm * scaleX + offX, yMm * scaleY + offY]
  }

  const areaM2 = ((roomW / 1000) * (roomD / 1000)).toFixed(1)

  // ── Run room audit ─────────────────────────────────────────────────────────
  async function handleAudit() {
    setLoading(true)
    setActiveAction('audit')
    setError(null)
    const params = {
      name: room.name || 'Room',
      width_mm: roomW,
      depth_mm: roomD,
      ceiling_height_mm: room.ceiling_height_mm || 2700,
      circulation_paths: circPaths.map(cp => ({
        name: cp.name,
        start: cp.start,
        end: cp.end,
        clear_width_mm: cp.clear_width_mm,
      })),
    }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'interior_room_layout', params })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'interior_room_layout', params }),
        })
        const data = await res.json()
        if (data.ok !== false) {
          setAuditResult(data)
        } else {
          setError(data.error || 'Audit failed')
        }
      }
    } catch (e) {
      setError(e.message || 'Audit dispatch failed')
    } finally {
      setLoading(false)
      setActiveAction(null)
    }
  }

  const adaCompliant = auditResult ? auditResult.ada_violations === 0 : null

  return (
    <div className={`flex flex-col gap-2 ${className}`} data-testid="interior-space-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-slate-500 font-medium tracking-wide uppercase">
          Interior Space Plan
        </span>
        <div className="flex items-center gap-2">
          <button
            className="text-xs px-2 py-1 rounded border border-slate-600 hover:border-slate-400 text-slate-300 disabled:opacity-50 transition-colors"
            onClick={handleAudit}
            disabled={loading}
            data-testid="interior-audit-btn"
          >
            {loading && activeAction === 'audit' ? 'Auditing…' : 'ADA audit'}
          </button>
        </div>
      </div>

      {/* SVG floor plan */}
      <svg
        width={svgWidth}
        height={svgHeight}
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="rounded border border-slate-800"
        style={{ background: '#0f172a' }}
        aria-label="Interior floor plan"
        role="img"
        data-testid="interior-svg"
      >
        {/* Room boundary */}
        <rect
          x={offX}
          y={offY}
          width={roomW * scaleX}
          height={roomD * scaleY}
          fill="#111827"
          stroke="#374151"
          strokeWidth="2"
        />

        {/* Room label */}
        <text
          x={offX + 6}
          y={offY + 14}
          fontSize="9"
          fill="#6b7280"
          fontFamily="monospace"
        >
          {room.name} · {(roomW / 1000).toFixed(1)} × {(roomD / 1000).toFixed(1)} m
        </text>

        {/* Circulation paths */}
        {circPaths.map((cp, i) => {
          const [x1, y1] = toSVG(cp.start[0], cp.start[1])
          const [x2, y2] = toSVG(cp.end[0], cp.end[1])
          const widthPx = (cp.clear_width_mm || 1000) * scaleX
          const compliant = cp.clear_width_mm >= 914
          return (
            <g key={i} aria-label={`Circulation: ${cp.name}`}>
              <line
                x1={x1} y1={y1} x2={x2} y2={y2}
                stroke={compliant ? '#22c55e' : '#ef4444'}
                strokeWidth={Math.max(1, widthPx)}
                strokeOpacity="0.12"
              />
              <line
                x1={x1} y1={y1} x2={x2} y2={y2}
                stroke={compliant ? '#22c55e' : '#ef4444'}
                strokeWidth="1"
                strokeDasharray="4 3"
                strokeOpacity="0.5"
              />
              <text
                x={(x1 + x2) / 2}
                y={(y1 + y2) / 2 - 4}
                textAnchor="middle"
                fontSize="8"
                fill={compliant ? '#4ade80' : '#f87171'}
                fontFamily="monospace"
              >
                {cp.name} ({(cp.clear_width_mm / 1000).toFixed(2)} m)
              </text>
            </g>
          )
        })}

        {/* Furniture items */}
        {items.map((item, i) => {
          const [sx, sy] = toSVG(item.x_mm ?? 0, item.y_mm ?? 0)
          const fw = (item.width_mm ?? 600) * scaleX
          const fd = (item.depth_mm ?? 600) * scaleY
          const fill = KIND_FILL[item.kind] || '#374151'
          const stroke = KIND_STROKE[item.kind] || '#6b7280'
          return (
            <g key={i} aria-label={`Furniture: ${item.label || item.kind}`}>
              <rect
                x={sx}
                y={sy}
                width={fw}
                height={fd}
                fill={fill}
                fillOpacity="0.5"
                stroke={stroke}
                strokeWidth="1"
              />
              <text
                x={sx + fw / 2}
                y={sy + fd / 2 + 3}
                textAnchor="middle"
                fontSize="8"
                fill={stroke}
                fontFamily="monospace"
              >
                {item.label || item.kind}
              </text>
            </g>
          )
        })}

        {/* ADA compliance badge */}
        {adaCompliant !== null && (
          <g transform={`translate(8, ${svgHeight - 20})`}>
            <rect
              x="0" y="0" width="110" height="16" rx="3"
              fill={adaCompliant ? '#14532d' : '#7f1d1d'}
              opacity="0.9"
            />
            <text x="6" y="11" fontSize="9" fill={adaCompliant ? '#4ade80' : '#f87171'} fontFamily="monospace">
              {adaCompliant ? '✓ ADA compliant' : `✗ ${auditResult.ada_violations} ADA violation(s)`}
            </text>
          </g>
        )}

        {/* Empty state */}
        {items.length === 0 && circPaths.length === 0 && (
          <text
            x={svgWidth / 2}
            y={svgHeight / 2 + 20}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize="12"
            fill="#475569"
            fontFamily="system-ui, sans-serif"
          >
            Pass items / circPaths props to show floor plan
          </text>
        )}
      </svg>

      {/* Area schedule */}
      <div className="px-1 flex flex-wrap gap-x-6 gap-y-1 text-xs font-mono text-slate-400" data-testid="area-schedule">
        <span><span className="text-slate-600">Area:</span> {areaM2} m²</span>
        <span><span className="text-slate-600">H:</span> {((room.ceiling_height_mm || 2700) / 1000).toFixed(2)} m</span>
        <span><span className="text-slate-600">Items:</span> {items.length}</span>
        <span><span className="text-slate-600">Paths:</span> {circPaths.length}</span>
      </div>

      {/* Finishes schedule */}
      {(finishes.floor || finishes.ceiling || finishes.walls) && (
        <div className="mx-1 rounded border border-slate-800 bg-slate-900 p-2 text-xs font-mono" data-testid="finishes-schedule">
          <div className="text-slate-500 text-[10px] uppercase mb-1">Finishes Schedule</div>
          {finishes.floor && (
            <div className="text-slate-300"><span className="text-slate-600">Floor:</span> {finishes.floor}</div>
          )}
          {finishes.ceiling && (
            <div className="text-slate-300"><span className="text-slate-600">Ceiling:</span> {finishes.ceiling}</div>
          )}
          {finishes.walls && (
            <div className="text-slate-300"><span className="text-slate-600">Walls:</span> {finishes.walls}</div>
          )}
        </div>
      )}

      {/* ADA violations list */}
      {auditResult && auditResult.violations && auditResult.violations.length > 0 && (
        <div className="mx-1 text-xs font-mono" data-testid="ada-violations">
          {auditResult.violations.map((v, i) => (
            <div key={i} className="text-red-400">
              ✗ {v.message}
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="text-xs text-red-400 px-1" data-testid="interior-error">
          {error}
        </div>
      )}
    </div>
  )
}
