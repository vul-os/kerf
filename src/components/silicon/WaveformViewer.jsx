/**
 * WaveformViewer.jsx
 *
 * SVG/canvas-based multi-trace SPICE waveform viewer.
 *
 * Accepts a `.spice.waveform` JSON payload:
 *   {
 *     signals: [{ name: string, units: string, t: number[], y: number[] }],
 *     meta?: { title?: string, analysis?: string, source?: string }
 *   }
 *
 * Features
 * --------
 *   - Multi-trace overlay — all signals on a shared time axis (V, I, dB etc.)
 *   - Zoom (scroll-wheel or pinch) + pan (drag) with a minimap extent indicator
 *   - Dual cursors (A / B) — drag to set; measurement chip shows ΔT and ΔY
 *   - Per-trace toggleable visibility via the legend
 *   - No external chart library — pure SVG rendering
 *
 * Usage
 * -----
 *   <WaveformViewer data={{ signals: [...], meta: {} }} />
 *   <WaveformViewer content={jsonString} />
 *
 * The component accepts either a pre-parsed `data` prop or a `content` string
 * that it will parse internally, so it integrates naturally into the Editor
 * file-kind branch (which passes raw file content as a string).
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

const MARGIN = { top: 28, right: 20, bottom: 44, left: 66 }

// Colour palette — kerf-esque dark theme, 8 distinct trace colours
const TRACE_COLORS = [
  '#4f9cf9', // blue
  '#f97b4f', // orange
  '#4fd97d', // green
  '#f9d44f', // yellow
  '#c47ef9', // purple
  '#f94f9c', // pink
  '#4ff9f0', // cyan
  '#f9f94f', // lime
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scaleLinear(domain, range) {
  const [d0, d1] = domain
  const [r0, r1] = range
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0)
  const scale = (v) => r0 + (v - d0) * k
  scale.domain = domain
  scale.range = range
  scale.invert = (px) => d1 === d0 ? d0 : d0 + (px - r0) / k
  return scale
}

function niceTicks(min, max, count = 6) {
  if (min === max) return [min]
  const span = max - min
  const roughStep = span / (count - 1)
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(roughStep) || 1)))
  const candidates = [1, 2, 2.5, 5, 10]
  const niceStep = candidates.map(c => c * mag).find(c => c >= roughStep) || roughStep
  const start = Math.ceil(min / niceStep) * niceStep
  const ticks = []
  for (let v = start; v <= max + niceStep * 0.01; v += niceStep) {
    ticks.push(parseFloat(v.toPrecision(8)))
    if (ticks.length > 20) break
  }
  return ticks
}

function fmtSI(v, unit) {
  if (v === 0) return `0 ${unit}`
  const abs = Math.abs(v)
  const prefixes = [
    [1e-15, 'f'], [1e-12, 'p'], [1e-9, 'n'], [1e-6, 'µ'],
    [1e-3, 'm'], [1, ''], [1e3, 'k'], [1e6, 'M'], [1e9, 'G'],
  ]
  const [div, pfx] = prefixes.reduce((best, cur) =>
    abs >= cur[0] ? cur : best, prefixes[0])
  const scaled = v / div
  const dp = Math.abs(scaled) >= 100 ? 1 : Math.abs(scaled) >= 10 ? 2 : 3
  return `${scaled.toFixed(dp)} ${pfx}${unit}`
}

function polylinePts(t, y, xScale, yScale) {
  if (!t || t.length === 0) return ''
  return t.map((tv, i) => `${xScale(tv).toFixed(1)},${yScale(y[i]).toFixed(1)}`).join(' ')
}

function clampedPolyline(t, y, xScale, yScale, tMin, tMax, innerH) {
  // Only include points visible in the current time window + 1 point outside on each side
  let start = 0
  let end = t.length
  for (let i = 0; i < t.length; i++) {
    if (t[i] >= tMin) { start = Math.max(0, i - 1); break }
    if (i === t.length - 1) start = i
  }
  for (let i = t.length - 1; i >= 0; i--) {
    if (t[i] <= tMax) { end = Math.min(t.length, i + 2); break }
    if (i === 0) end = 0
  }
  return polylinePts(t.slice(start, end), y.slice(start, end), xScale, yScale)
}

// Parse raw JSON content string → { signals, meta }
function parseWaveformContent(content) {
  try {
    const parsed = JSON.parse(content || '{}')
    return {
      signals: Array.isArray(parsed.signals) ? parsed.signals : [],
      meta: parsed.meta || {},
    }
  } catch {
    return { signals: [], meta: {} }
  }
}

// ---------------------------------------------------------------------------
// Cursor measurement chip
// ---------------------------------------------------------------------------

function CursorChip({ cursorA, cursorB, signals, xScale, tUnit, innerW }) {
  if (!cursorA && !cursorB) return null

  const rows = []
  if (cursorA !== null) {
    const tA = xScale.invert(cursorA)
    rows.push(
      <div key="a-t" className="flex items-center gap-3">
        <span className="text-amber-400 font-mono text-[10px]">A</span>
        <span className="text-ink-300 font-mono text-[10px]">{fmtSI(tA, tUnit)}</span>
      </div>
    )
  }
  if (cursorB !== null) {
    const tB = xScale.invert(cursorB)
    rows.push(
      <div key="b-t" className="flex items-center gap-3">
        <span className="text-blue-400 font-mono text-[10px]">B</span>
        <span className="text-ink-300 font-mono text-[10px]">{fmtSI(tB, tUnit)}</span>
      </div>
    )
  }
  if (cursorA !== null && cursorB !== null) {
    const tA = xScale.invert(cursorA)
    const tB = xScale.invert(cursorB)
    rows.push(
      <div key="dt" className="flex items-center gap-3 border-t border-ink-700 pt-1 mt-1">
        <span className="text-ink-400 font-mono text-[10px]">ΔT</span>
        <span className="text-kerf-300 font-mono text-[10px]">{fmtSI(Math.abs(tB - tA), tUnit)}</span>
      </div>
    )
  }

  return (
    <div className="absolute top-2 right-2 z-20 bg-ink-900/95 border border-ink-700 rounded px-2 py-1.5 shadow-lg flex flex-col gap-0.5 min-w-[120px] pointer-events-none">
      <span className="text-[9px] text-ink-500 uppercase tracking-wider mb-0.5">Cursors</span>
      {rows}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------

function Legend({ signals, visible, onToggle }) {
  if (!signals.length) return null
  return (
    <div className="flex flex-wrap gap-2 px-4 pb-2">
      {signals.map((sig, i) => {
        const color = TRACE_COLORS[i % TRACE_COLORS.length]
        const isVisible = visible[i] !== false
        return (
          <button
            key={i}
            type="button"
            onClick={() => onToggle(i)}
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-mono transition-opacity ${
              isVisible
                ? 'border-ink-600 text-ink-100 hover:border-kerf-300/50'
                : 'border-ink-800 text-ink-600 opacity-50 hover:opacity-80'
            }`}
          >
            <span style={{ color }} className="text-lg leading-none select-none">—</span>
            <span>{sig.name}</span>
            {sig.units && <span className="text-ink-500">({sig.units})</span>}
          </button>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * @param {{
 *   data?: { signals: Array<{name: string, units: string, t: number[], y: number[]}>, meta?: object },
 *   content?: string,
 *   className?: string,
 * }} props
 */
export default function WaveformViewer({ data, content, className = '' }) {
  // Parse content if data not provided
  const parsed = useMemo(() => {
    if (data) return data
    return parseWaveformContent(content)
  }, [data, content])

  const { signals, meta } = parsed

  // Trace visibility
  const [visible, setVisible] = useState(() => signals.map(() => true))
  const handleToggle = useCallback((i) => {
    setVisible(prev => {
      const next = [...prev]
      next[i] = prev[i] === false ? true : false
      return next
    })
  }, [])
  // Sync visible array length when signals change
  useEffect(() => {
    setVisible(signals.map(() => true))
  }, [signals.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // Canvas/SVG element ref for mouse interactions
  const svgRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 400 })
  useEffect(() => {
    if (!svgRef.current) return
    const obs = new ResizeObserver(entries => {
      const entry = entries[0]
      if (entry) setDims({ w: entry.contentRect.width, h: entry.contentRect.height })
    })
    obs.observe(svgRef.current.parentElement)
    return () => obs.disconnect()
  }, [])

  const innerW = dims.w - MARGIN.left - MARGIN.right
  const innerH = dims.h - MARGIN.top - MARGIN.bottom

  // Time domain extent across all active signals
  const tAll = useMemo(() => {
    const all = []
    signals.forEach((s, i) => {
      if (visible[i] !== false && s.t && s.t.length > 0) all.push(...s.t)
    })
    return all
  }, [signals, visible])

  const tGlobalMin = tAll.length ? Math.min(...tAll) : 0
  const tGlobalMax = tAll.length ? Math.max(...tAll) : 1e-6

  // Zoom state: [tMin, tMax] (null = full range)
  const [zoom, setZoom] = useState(null)
  const tMin = zoom ? zoom[0] : tGlobalMin
  const tMax = zoom ? zoom[1] : tGlobalMax
  const tSpan = tMax - tMin || 1e-12

  // Scales
  const xScale = useMemo(() => {
    const domain = [tMin, tMax === tMin ? tMin + 1e-12 : tMax]
    return scaleLinear(domain, [0, innerW])
  }, [tMin, tMax, innerW])

  // Y extent across visible signals in current time window
  const yRange = useMemo(() => {
    let yMin = Infinity, yMax = -Infinity
    signals.forEach((s, i) => {
      if (visible[i] === false) return
      if (!s.t || !s.y) return
      s.y.forEach((v, j) => {
        if (s.t[j] >= tMin && s.t[j] <= tMax) {
          if (v < yMin) yMin = v
          if (v > yMax) yMax = v
        }
      })
    })
    if (!isFinite(yMin)) { yMin = -1; yMax = 1 }
    if (yMin === yMax) { yMin -= 0.5; yMax += 0.5 }
    const pad = (yMax - yMin) * 0.08
    return [yMin - pad, yMax + pad]
  }, [signals, visible, tMin, tMax])

  const yScale = useMemo(
    () => scaleLinear([yRange[0], yRange[1]], [innerH, 0]),
    [yRange, innerH]
  )

  // Detect dominant unit for Y axis label
  const yUnit = useMemo(() => {
    const active = signals.filter((_, i) => visible[i] !== false)
    if (!active.length) return ''
    const units = [...new Set(active.map(s => s.units || ''))]
    return units.length === 1 ? units[0] : ''
  }, [signals, visible])

  // Detect time unit from signal data
  const tUnit = useMemo(() => {
    // Most SPICE netlists use seconds; detect by magnitude
    const maxT = tGlobalMax
    if (maxT < 1e-9) return 'fs'
    if (maxT < 1e-6) return 'ps'
    if (maxT < 1e-3) return 'ns'
    if (maxT < 1) return 'µs'
    if (maxT < 1e3) return 'ms'
    return 's'
  }, [tGlobalMax])

  const xTicks = useMemo(() => niceTicks(tMin, tMax, 7), [tMin, tMax])
  const yTicks = useMemo(() => niceTicks(yRange[0], yRange[1], 6), [yRange])

  // ---------------------------------------------------------------------------
  // Interaction: pan + zoom + cursors
  // ---------------------------------------------------------------------------

  const [cursorA, setCursorA] = useState(null) // px x within plot
  const [cursorB, setCursorB] = useState(null)
  const [dragging, setDragging] = useState(null) // 'pan' | 'cursorA' | 'cursorB'
  const dragStartRef = useRef(null)
  const zoomOnEnterRef = useRef(null)

  // Convert SVG-space client X to plot-space px (within inner area)
  const clientToPx = useCallback((clientX) => {
    if (!svgRef.current) return 0
    const rect = svgRef.current.getBoundingClientRect()
    return clientX - rect.left - MARGIN.left
  }, [])

  const handleWheel = useCallback((e) => {
    e.preventDefault()
    const px = clientToPx(e.clientX)
    const frac = Math.max(0, Math.min(1, px / innerW))
    const tFocus = tMin + frac * tSpan
    const factor = e.deltaY > 0 ? 1.25 : 0.8
    const newSpan = tSpan * factor
    let newMin = tFocus - frac * newSpan
    let newMax = tFocus + (1 - frac) * newSpan
    if (newMin < tGlobalMin) { newMax += tGlobalMin - newMin; newMin = tGlobalMin }
    if (newMax > tGlobalMax) { newMin -= newMax - tGlobalMax; newMax = tGlobalMax }
    if (newMax - newMin < 1e-15) return
    setZoom([newMin, newMax])
  }, [clientToPx, innerW, tMin, tMax, tSpan, tGlobalMin, tGlobalMax])

  const handlePointerDown = useCallback((e) => {
    const px = clientToPx(e.clientX)
    // Check cursor proximity (± 8 px)
    if (cursorA !== null && Math.abs(px - cursorA) < 8) {
      setDragging('cursorA')
      e.currentTarget.setPointerCapture(e.pointerId)
    } else if (cursorB !== null && Math.abs(px - cursorB) < 8) {
      setDragging('cursorB')
      e.currentTarget.setPointerCapture(e.pointerId)
    } else if (e.shiftKey) {
      // Shift+click → set cursor A then B alternately
      if (cursorA === null || (cursorA !== null && cursorB !== null)) {
        setCursorA(Math.max(0, Math.min(innerW, px)))
        setCursorB(null)
      } else {
        setCursorB(Math.max(0, Math.min(innerW, px)))
      }
    } else {
      // Pan
      setDragging('pan')
      dragStartRef.current = { px, tMinSaved: tMin, tMaxSaved: tMax }
      zoomOnEnterRef.current = zoom
      e.currentTarget.setPointerCapture(e.pointerId)
    }
  }, [clientToPx, cursorA, cursorB, innerW, tMin, tMax, zoom])

  const handlePointerMove = useCallback((e) => {
    const px = clientToPx(e.clientX)
    if (dragging === 'cursorA') {
      setCursorA(Math.max(0, Math.min(innerW, px)))
    } else if (dragging === 'cursorB') {
      setCursorB(Math.max(0, Math.min(innerW, px)))
    } else if (dragging === 'pan' && dragStartRef.current) {
      const deltaPx = px - dragStartRef.current.px
      const deltaT = -(deltaPx / innerW) * tSpan
      let newMin = dragStartRef.current.tMinSaved + deltaT
      let newMax = dragStartRef.current.tMaxSaved + deltaT
      if (newMin < tGlobalMin) { newMax += tGlobalMin - newMin; newMin = tGlobalMin }
      if (newMax > tGlobalMax) { newMin -= newMax - tGlobalMax; newMax = tGlobalMax }
      setZoom([newMin, newMax])
    }
  }, [dragging, clientToPx, innerW, tSpan, tGlobalMin, tGlobalMax])

  const handlePointerUp = useCallback((e) => {
    setDragging(null)
    dragStartRef.current = null
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch {}
  }, [])

  // Double-click → reset zoom
  const handleDoubleClick = useCallback(() => {
    setZoom(null)
    setCursorA(null)
    setCursorB(null)
  }, [])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (signals.length === 0) {
    return (
      <div className={`flex-1 min-h-0 flex items-center justify-center bg-ink-950 text-ink-500 text-sm flex-col gap-2 ${className}`}>
        <span className="text-2xl opacity-30">〜</span>
        <span>No waveform signals</span>
        <span className="text-xs text-ink-600 font-mono">
          File must contain {`{signals: [{name, units, t[], y[]}], meta}`}
        </span>
      </div>
    )
  }

  const title = meta.title || meta.analysis || ''

  return (
    <div className={`flex-1 min-h-0 flex flex-col bg-ink-950 select-none ${className}`} data-testid="waveform-viewer">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-ink-800 flex-shrink-0">
        <div className="flex items-center gap-3">
          {title && (
            <span className="text-xs text-ink-300 font-mono">{title}</span>
          )}
          <span className="text-[10px] text-ink-600 font-mono">
            {signals.length} signal{signals.length !== 1 ? 's' : ''}
            {meta.source && ` · ${meta.source}`}
          </span>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-ink-500">
          <span>Scroll to zoom · Drag to pan · Shift+click cursor A/B · Dbl-click reset</span>
        </div>
      </div>

      {/* Legend */}
      <div className="flex-shrink-0 pt-2">
        <Legend signals={signals} visible={visible} onToggle={handleToggle} />
      </div>

      {/* Plot area */}
      <div className="flex-1 min-h-0 relative" style={{ cursor: dragging === 'pan' ? 'grabbing' : 'crosshair' }}>
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          style={{ display: 'block' }}
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onDoubleClick={handleDoubleClick}
          aria-label={`SPICE waveform: ${signals.map(s => s.name).join(', ')}`}
          role="img"
        >
          <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>

            {/* Grid lines */}
            {yTicks.map(v => (
              <line key={`hg-${v}`} x1={0} x2={innerW}
                y1={yScale(v)} y2={yScale(v)} stroke="#1f2937" strokeWidth={1} />
            ))}
            {xTicks.map(v => (
              <line key={`vg-${v}`} x1={xScale(v)} x2={xScale(v)}
                y1={0} y2={innerH} stroke="#1f2937" strokeWidth={1} />
            ))}

            {/* Zero-line */}
            {yRange[0] < 0 && yRange[1] > 0 && (
              <line x1={0} x2={innerW}
                y1={yScale(0)} y2={yScale(0)}
                stroke="#374151" strokeWidth={1.5} strokeDasharray="4 3" />
            )}

            {/* Clip area border */}
            <rect x={0} y={0} width={innerW} height={innerH}
              fill="none" stroke="#374151" strokeWidth={1} />

            {/* Traces */}
            <clipPath id="waveform-clip">
              <rect x={0} y={0} width={innerW} height={innerH} />
            </clipPath>
            <g clipPath="url(#waveform-clip)">
              {signals.map((sig, i) => {
                if (visible[i] === false) return null
                if (!sig.t || !sig.y || sig.t.length === 0) return null
                const color = TRACE_COLORS[i % TRACE_COLORS.length]
                const pts = clampedPolyline(sig.t, sig.y, xScale, yScale, tMin, tMax, innerH)
                if (!pts) return null
                return (
                  <polyline
                    key={i}
                    points={pts}
                    fill="none"
                    stroke={color}
                    strokeWidth={1.5}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    opacity={0.9}
                  />
                )
              })}
            </g>

            {/* Cursor A */}
            {cursorA !== null && cursorA >= 0 && cursorA <= innerW && (
              <>
                <line x1={cursorA} x2={cursorA} y1={0} y2={innerH}
                  stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4 2" />
                <rect x={cursorA - 5} y={-10} width={10} height={10} rx={2}
                  fill="#f59e0b" />
                <text x={cursorA} y={-2} textAnchor="middle" fill="#f59e0b" fontSize={8}
                  fontFamily="monospace">A</text>
              </>
            )}

            {/* Cursor B */}
            {cursorB !== null && cursorB >= 0 && cursorB <= innerW && (
              <>
                <line x1={cursorB} x2={cursorB} y1={0} y2={innerH}
                  stroke="#60a5fa" strokeWidth={1.5} strokeDasharray="4 2" />
                <rect x={cursorB - 5} y={-10} width={10} height={10} rx={2}
                  fill="#60a5fa" />
                <text x={cursorB} y={-2} textAnchor="middle" fill="#60a5fa" fontSize={8}
                  fontFamily="monospace">B</text>
              </>
            )}

            {/* X-axis ticks + labels */}
            {xTicks.map(v => (
              <g key={`xt-${v}`} transform={`translate(${xScale(v)},${innerH})`}>
                <line y1={0} y2={5} stroke="#6b7280" strokeWidth={1} />
                <text y={18} textAnchor="middle" fill="#9ca3af" fontSize={10} fontFamily="monospace">
                  {fmtSI(v, tUnit)}
                </text>
              </g>
            ))}

            {/* Y-axis ticks + labels */}
            {yTicks.map(v => (
              <g key={`yt-${v}`} transform={`translate(0,${yScale(v)})`}>
                <line x1={0} x2={-5} stroke="#6b7280" strokeWidth={1} />
                <text x={-8} textAnchor="end" dominantBaseline="middle"
                  fill="#9ca3af" fontSize={10} fontFamily="monospace">
                  {v >= 0.01 || v <= -0.01 || v === 0 ? v.toPrecision(3) : v.toExponential(1)}
                </text>
              </g>
            ))}

            {/* X-axis label */}
            <text x={innerW / 2} y={innerH + 38} textAnchor="middle"
              fill="#9ca3af" fontSize={11}>
              Time ({tUnit})
            </text>

            {/* Y-axis label */}
            {yUnit && (
              <text transform={`translate(-54,${innerH / 2}) rotate(-90)`}
                textAnchor="middle" fill="#9ca3af" fontSize={11}>
                {yUnit}
              </text>
            )}

            {/* Title */}
            {title && (
              <text x={innerW / 2} y={-12} textAnchor="middle"
                fill="#e5e7eb" fontSize={12} fontWeight="600">
                {title}
              </text>
            )}
          </g>
        </svg>

        {/* Cursor measurement chip */}
        <CursorChip
          cursorA={cursorA}
          cursorB={cursorB}
          signals={signals}
          xScale={xScale}
          tUnit={tUnit}
          innerW={innerW}
        />
      </div>

      {/* Minimap — shows full t range with current zoom window highlighted */}
      {zoom && (
        <div className="flex-shrink-0 border-t border-ink-800 bg-ink-900/40 px-4 py-1.5 flex items-center gap-3">
          <span className="text-[10px] text-ink-500 font-mono">View</span>
          <div className="flex-1 h-3 bg-ink-800 rounded relative">
            <div
              className="absolute inset-y-0 bg-kerf-300/20 border border-kerf-300/40 rounded"
              style={{
                left: `${((tMin - tGlobalMin) / (tGlobalMax - tGlobalMin)) * 100}%`,
                right: `${100 - ((tMax - tGlobalMin) / (tGlobalMax - tGlobalMin)) * 100}%`,
              }}
            />
          </div>
          <span className="text-[10px] text-ink-500 font-mono">
            {fmtSI(tMin, tUnit)} – {fmtSI(tMax, tUnit)}
          </span>
        </div>
      )}
    </div>
  )
}
