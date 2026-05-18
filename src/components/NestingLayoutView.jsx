// NestingLayoutView — SVG layout view for a `.nest` result file produced by
// the T-53 Python `nest_parts` tool (kerf_cad_core.nesting).
//
// File shape (mirrors NestResult serialised by result_to_dict):
//   {
//     "ok": true,
//     "sheets_used": 2,
//     "utilization": 0.74,          // fraction 0-1
//     "cut_length": 4200.0,         // mm
//     "errors": [],
//     "sheets": [
//       {
//         "sheet": 0,
//         "placements": [
//           { "part": "gusset", "x": 5, "y": 5, "w": 80, "h": 40, "rot": 0 },
//           ...
//         ]
//       },
//       ...
//     ]
//   }
//
// Layout:
//   header — sheet selector (prev/next arrows + "Sheet N / M"), utilization pill
//   SVG canvas — sheet outline + grid + placed part rectangles (coloured by part name)
//   footer stats — parts on this sheet, utilization %, cut length
//
// Pure math helpers (`nestViewport`, `partColorIndex`) are exported so the
// no-DOM vitest suite can exercise the layout/scale logic without mounting.

import { useCallback, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Scissors, AlertTriangle } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure layout / scale helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Compute the SVG viewBox string and a scale factor for fitting a sheet of
 * dimensions sheetW × sheetH into a viewport of viewW × viewH pixels with
 * a given padding.
 *
 * Returns { viewBox, scale, offsetX, offsetY }
 *   viewBox  — SVG viewBox attribute string  "minX minY W H"
 *   scale    — user-space units per pixel (useful for strokeWidth)
 *   padded*  — sheet rect in user space after padding
 */
export function nestViewport(sheetW, sheetH, viewW, viewH, padding = 12) {
  if (!sheetW || !sheetH || !viewW || !viewH) {
    return { viewBox: '0 0 100 100', scale: 1, paddedX: 0, paddedY: 0, paddedW: 100, paddedH: 100 }
  }
  // Add uniform padding around the sheet in sheet-space units.
  const pad = (Math.max(sheetW, sheetH) * padding) / Math.min(viewW, viewH)
  const vbX = -pad
  const vbY = -pad
  const vbW = sheetW + 2 * pad
  const vbH = sheetH + 2 * pad
  // Scale: user-space units per SVG pixel
  const scale = Math.max(vbW / viewW, vbH / viewH)
  return {
    viewBox: `${vbX.toFixed(4)} ${vbY.toFixed(4)} ${vbW.toFixed(4)} ${vbH.toFixed(4)}`,
    scale,
    paddedX: vbX,
    paddedY: vbY,
    paddedW: vbW,
    paddedH: vbH,
  }
}

/**
 * Map a part name to a stable colour-palette index (0-based).
 * Uses a simple djb2-style hash so the same name always maps to the same colour.
 */
export function partColorIndex(name, paletteSize = PART_COLORS.length) {
  let h = 5381
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) + h + name.charCodeAt(i)) >>> 0
  }
  return h % paletteSize
}

/**
 * Format a utilization fraction (0-1) as a percentage string.
 * Returns e.g. "74.3%".
 */
export function fmtUtilization(u) {
  if (u == null || !Number.isFinite(u)) return '—'
  return (u * 100).toFixed(1) + '%'
}

/**
 * Format a cut-length value in mm, abbreviating to metres when >= 1000 mm.
 */
export function fmtCutLength(mm) {
  if (mm == null || !Number.isFinite(mm)) return '—'
  if (mm >= 1000) return (mm / 1000).toFixed(2) + ' m'
  return mm.toFixed(1) + ' mm'
}

/**
 * Infer sheet dimensions from placements when no explicit sheetW/sheetH is
 * stored in the result (the Python NestResult does not include them — only
 * the placements carry x/y/w/h in sheet coordinates).
 *
 * Returns { w, h } — the bounding box of all placed parts plus a 10% margin.
 */
export function inferSheetSize(placements) {
  if (!placements || placements.length === 0) return { w: 100, h: 100 }
  let maxX = 0
  let maxY = 0
  for (const p of placements) {
    maxX = Math.max(maxX, (p.x || 0) + (p.w || 0))
    maxY = Math.max(maxY, (p.y || 0) + (p.h || 0))
  }
  // Grow by 10% or at least 5 mm to show margin context.
  const gx = Math.max(maxX * 0.1, 5)
  const gy = Math.max(maxY * 0.1, 5)
  return { w: maxX + gx, h: maxY + gy }
}

// ---------------------------------------------------------------------------
// Colour palette — muted fills that work on a dark background
// ---------------------------------------------------------------------------

export const PART_COLORS = [
  { fill: '#3b3f6b', stroke: '#818cf8' },  // indigo
  { fill: '#2d4a3e', stroke: '#34d399' },  // emerald
  { fill: '#3b2f4a', stroke: '#c084fc' },  // purple
  { fill: '#4a3b2f', stroke: '#fb923c' },  // amber
  { fill: '#2f3e4a', stroke: '#38bdf8' },  // sky
  { fill: '#4a2f35', stroke: '#f87171' },  // red
  { fill: '#3f4a2f', stroke: '#a3e635' },  // lime
  { fill: '#4a402f', stroke: '#fbbf24' },  // yellow
  { fill: '#2f4a47', stroke: '#2dd4bf' },  // teal
  { fill: '#4a2f44', stroke: '#f472b6' },  // pink
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * NestingLayoutView
 *
 * Props:
 *   parsedContent — the already-parsed JSON of a `.nest` file, or null.
 *   sheetW        — optional explicit sheet width  (mm); inferred if omitted.
 *   sheetH        — optional explicit sheet height (mm); inferred if omitted.
 */
export default function NestingLayoutView({ parsedContent, sheetW: propSheetW, sheetH: propSheetH }) {
  const [sheetIdx, setSheetIdx] = useState(0)
  const svgRef = useRef(null)

  // Pan/zoom state
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const isPanning = useRef(false)
  const panStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 })

  const onMouseDown = useCallback((e) => {
    if (e.button !== 0 && e.button !== 1) return
    isPanning.current = true
    panStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y }
    e.preventDefault()
  }, [pan])

  const onMouseMove = useCallback((e) => {
    if (!isPanning.current) return
    setPan({
      x: panStart.current.panX + (e.clientX - panStart.current.x),
      y: panStart.current.panY + (e.clientY - panStart.current.y),
    })
  }, [])

  const onMouseUp = useCallback(() => { isPanning.current = false }, [])

  const onWheel = useCallback((e) => {
    e.preventDefault()
    setZoom((z) => Math.max(0.05, Math.min(50, z * (e.deltaY > 0 ? 0.9 : 1.1))))
  }, [])

  const handleResetView = () => { setZoom(1); setPan({ x: 0, y: 0 }) }

  // -- Parse content --
  const data = parsedContent
  const ok = data?.ok ?? false
  const sheets = Array.isArray(data?.sheets) ? data.sheets : []
  const sheetsUsed = data?.sheets_used ?? sheets.length
  const utilization = data?.utilization ?? null
  const cutLength = data?.cut_length ?? null
  const errors = Array.isArray(data?.errors) ? data.errors : []

  const isEmpty = sheets.length === 0

  // Clamp sheetIdx
  const clampedIdx = Math.min(sheetIdx, Math.max(0, sheets.length - 1))
  const currentSheet = sheets[clampedIdx] || null
  const placements = currentSheet?.placements || []

  // Determine sheet dimensions
  const { w: inferredW, h: inferredH } = inferSheetSize(placements)
  const sheetW = propSheetW && propSheetW > 0 ? propSheetW : inferredW
  const sheetH = propSheetH && propSheetH > 0 ? propSheetH : inferredH

  // SVG viewport — 4:3 aspect, will be stretched by CSS
  const vpW = 600
  const vpH = 450
  const vp = nestViewport(sheetW, sheetH, vpW, vpH)

  // Stroke width in user-space units: ~0.3% of the sheet's larger dimension
  const strokeW = Math.max(sheetW, sheetH) * 0.003

  return (
    <div style={styles.root}>
      {/* Header */}
      <div style={styles.header}>
        <Scissors size={15} style={{ color: '#34d399', flexShrink: 0 }} />
        <span style={styles.title}>Nesting Layout</span>
        {utilization != null && (
          <span style={{ ...styles.pill, background: utilizationBg(utilization) }}>
            {fmtUtilization(utilization)} utilization
          </span>
        )}
      </div>

      {/* Errors */}
      {errors.length > 0 && (
        <div style={styles.errorBox}>
          <AlertTriangle size={13} style={{ flexShrink: 0 }} />
          <div style={{ marginLeft: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
            {errors.map((e, i) => <span key={i}>{e}</span>)}
          </div>
        </div>
      )}

      {/* Empty state */}
      {isEmpty && !errors.length && (
        <div style={styles.emptyState}>
          No placements yet. Run <code style={{ color: '#a78bfa' }}>nest_parts</code> to generate a nesting layout.
        </div>
      )}

      {!isEmpty && (
        <>
          {/* Sheet selector */}
          {sheetsUsed > 1 && (
            <div style={styles.sheetNav}>
              <button
                type="button"
                onClick={() => setSheetIdx((i) => Math.max(0, i - 1))}
                disabled={clampedIdx === 0}
                style={{ ...styles.navBtn, opacity: clampedIdx === 0 ? 0.3 : 1 }}
                title="Previous sheet"
                aria-label="Previous sheet"
              >
                <ChevronLeft size={14} />
              </button>
              <span style={styles.sheetLabel}>
                Sheet {clampedIdx + 1} / {sheetsUsed}
              </span>
              <button
                type="button"
                onClick={() => setSheetIdx((i) => Math.min(sheetsUsed - 1, i + 1))}
                disabled={clampedIdx >= sheetsUsed - 1}
                style={{ ...styles.navBtn, opacity: clampedIdx >= sheetsUsed - 1 ? 0.3 : 1 }}
                title="Next sheet"
                aria-label="Next sheet"
              >
                <ChevronRight size={14} />
              </button>
              <button
                type="button"
                onClick={handleResetView}
                style={styles.resetBtn}
                title="Reset pan/zoom"
              >
                reset view
              </button>
            </div>
          )}

          {sheetsUsed <= 1 && (
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button type="button" onClick={handleResetView} style={styles.resetBtn}>reset view</button>
            </div>
          )}

          {/* SVG canvas */}
          <div
            style={styles.canvas}
            onWheel={onWheel}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
          >
            <svg
              ref={svgRef}
              width="100%"
              height="100%"
              viewBox={vp.viewBox}
              preserveAspectRatio="xMidYMid meet"
              style={{ transform: `translate(${pan.x}px,${pan.y}px) scale(${zoom})`, transformOrigin: '50% 50%' }}
            >
              {/* Background grid */}
              <defs>
                <pattern
                  id="nl-grid"
                  width={Math.max(sheetW, sheetH) * 0.05}
                  height={Math.max(sheetW, sheetH) * 0.05}
                  patternUnits="userSpaceOnUse"
                >
                  <path
                    d={`M ${Math.max(sheetW, sheetH) * 0.05} 0 L 0 0 0 ${Math.max(sheetW, sheetH) * 0.05}`}
                    fill="none"
                    stroke="#1f2937"
                    strokeWidth={strokeW * 0.4}
                  />
                </pattern>
              </defs>
              <rect
                x={vp.paddedX}
                y={vp.paddedY}
                width={vp.paddedW}
                height={vp.paddedH}
                fill="url(#nl-grid)"
              />

              {/* Sheet outline */}
              <rect
                x={0}
                y={0}
                width={sheetW}
                height={sheetH}
                fill="#0d1117"
                stroke="#374151"
                strokeWidth={strokeW * 1.5}
                strokeDasharray={`${strokeW * 4},${strokeW * 2}`}
              />

              {/* Sheet dimension labels */}
              <text
                x={sheetW / 2}
                y={-strokeW * 4}
                textAnchor="middle"
                fontSize={strokeW * 6}
                fill="#6b7280"
              >
                {sheetW % 1 === 0 ? sheetW : sheetW.toFixed(1)} mm
              </text>
              <text
                x={-strokeW * 4}
                y={sheetH / 2}
                textAnchor="middle"
                fontSize={strokeW * 6}
                fill="#6b7280"
                transform={`rotate(-90, ${-strokeW * 4}, ${sheetH / 2})`}
              >
                {sheetH % 1 === 0 ? sheetH : sheetH.toFixed(1)} mm
              </text>

              {/* Placed parts */}
              {placements.map((p, i) => {
                const ci = partColorIndex(p.part || String(i))
                const color = PART_COLORS[ci]
                const labelFontSize = Math.min(p.w, p.h) * 0.22
                const showLabel = labelFontSize > strokeW * 2
                return (
                  <g key={i}>
                    <rect
                      x={p.x}
                      y={p.y}
                      width={p.w}
                      height={p.h}
                      fill={color.fill}
                      stroke={color.stroke}
                      strokeWidth={strokeW}
                      rx={strokeW * 0.5}
                    />
                    {p.rot === 90 && (
                      <text
                        x={p.x + p.w - strokeW * 2}
                        y={p.y + strokeW * 4}
                        fontSize={strokeW * 4}
                        fill={color.stroke}
                        opacity={0.7}
                        textAnchor="end"
                      >
                        ↻
                      </text>
                    )}
                    {showLabel && (
                      <text
                        x={p.x + p.w / 2}
                        y={p.y + p.h / 2 + labelFontSize * 0.35}
                        textAnchor="middle"
                        fontSize={labelFontSize}
                        fill={color.stroke}
                        fontFamily="ui-monospace,SFMono-Regular,Menlo,monospace"
                      >
                        {p.part}
                      </text>
                    )}
                  </g>
                )
              })}
            </svg>
          </div>

          {/* Footer stats */}
          <div style={styles.statsRow}>
            <StatItem label="Parts on sheet" value={placements.length} />
            {utilization != null && (
              <StatItem label="Utilization" value={fmtUtilization(utilization)} mono />
            )}
            {cutLength != null && (
              <StatItem label="Est. cut length" value={fmtCutLength(cutLength)} mono />
            )}
            {sheetsUsed > 1 && (
              <StatItem label="Total sheets" value={sheetsUsed} />
            )}
          </div>

          {/* Parts legend */}
          {placements.length > 0 && (
            <PartLegend placements={placements} />
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatItem({ label, value, mono }) {
  return (
    <div style={styles.statItem}>
      <span style={styles.statLabel}>{label}</span>
      <span style={{ ...styles.statValue, ...(mono ? styles.mono : {}) }}>{value}</span>
    </div>
  )
}

function PartLegend({ placements }) {
  // Deduplicate by part name
  const seen = new Set()
  const parts = []
  for (const p of placements) {
    if (!seen.has(p.part)) {
      seen.add(p.part)
      parts.push(p.part)
    }
  }
  if (parts.length === 0) return null
  return (
    <div style={styles.legend}>
      {parts.map((name) => {
        const ci = partColorIndex(name)
        const color = PART_COLORS[ci]
        const count = placements.filter((p) => p.part === name).length
        return (
          <div key={name} style={styles.legendItem}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: color.fill, border: `1px solid ${color.stroke}`, flexShrink: 0 }} />
            <span style={{ color: '#d1d5db', fontSize: 11 }}>{name}</span>
            {count > 1 && <span style={{ color: '#6b7280', fontSize: 10 }}>×{count}</span>}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function utilizationBg(u) {
  if (u >= 0.8) return '#14532d44'
  if (u >= 0.6) return '#1e3a5f44'
  return '#3b2f0044'
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  root: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 13,
    color: '#e5e7eb',
    background: '#111827',
    borderRadius: 8,
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
    minWidth: 0,
    width: '100%',
    height: '100%',
    overflowY: 'auto',
    boxSizing: 'border-box',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    borderBottom: '1px solid #1f2937',
    paddingBottom: 10,
    flexWrap: 'wrap',
  },
  title: { fontWeight: 600, fontSize: 14, color: '#f3f4f6' },
  pill: {
    marginLeft: 'auto',
    padding: '2px 8px',
    borderRadius: 9999,
    fontSize: 11,
    fontWeight: 600,
    border: '1px solid #374151',
    color: '#d1d5db',
  },
  sheetNav: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  sheetLabel: { fontSize: 12, color: '#9ca3af', minWidth: 90, textAlign: 'center' },
  navBtn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '2px 4px',
    cursor: 'pointer',
    width: 26,
    height: 26,
  },
  resetBtn: {
    marginLeft: 'auto',
    fontSize: 10,
    color: '#6b7280',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    padding: 0,
  },
  canvas: {
    minHeight: 200,
    maxHeight: 'min(60vh, 480px)',
    aspectRatio: '4/3',
    width: '100%',
    background: '#0d1117',
    borderRadius: 6,
    border: '1px solid #1f2937',
    overflow: 'hidden',
    position: 'relative',
    cursor: 'grab',
  },
  statsRow: {
    display: 'flex',
    gap: 16,
    flexWrap: 'wrap',
    borderTop: '1px solid #1f2937',
    paddingTop: 8,
  },
  statItem: { display: 'flex', flexDirection: 'column', gap: 2 },
  statLabel: { fontSize: 10, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' },
  statValue: { fontSize: 13, color: '#e5e7eb', fontWeight: 600 },
  mono: { fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', color: '#a78bfa' },
  legend: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    borderTop: '1px solid #1f2937',
    paddingTop: 8,
  },
  legendItem: { display: 'flex', alignItems: 'center', gap: 4 },
  emptyState: { color: '#6b7280', fontSize: 12, padding: '12px 0' },
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
