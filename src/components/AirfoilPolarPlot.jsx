/**
 * AirfoilPolarPlot.jsx
 *
 * SVG line chart that renders CL-vs-α (and optionally CD-vs-α) from
 * a polar data object returned by /api/aero/airfoil/polar.
 *
 * Usage:
 *   <AirfoilPolarPlot
 *     polar={{ airfoil: 'naca0012', alpha: [...], CL: [...], CD: [...] }}
 *     width={480}
 *     height={300}
 *   />
 *
 * The component is purely presentational — it receives data as props and
 * does not fetch anything itself.  For async fetching combine with
 * airfoilPolarBridge.js.
 */

import { useState } from 'react'

// ---------------------------------------------------------------------------
// Layout constants
// ---------------------------------------------------------------------------

const MARGIN = { top: 24, right: 16, bottom: 40, left: 52 }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scaleLinear(domain, range) {
  const [d0, d1] = domain
  const [r0, r1] = range
  const scale = (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0)
  scale.domain = domain
  scale.range = range
  return scale
}

function niceTicks(min, max, count = 6) {
  const step = (max - min) / (count - 1)
  const magnitude = Math.pow(10, Math.floor(Math.log10(Math.abs(step) || 1)))
  const niceStep = Math.ceil(step / magnitude) * magnitude
  const start = Math.ceil(min / niceStep) * niceStep
  const ticks = []
  for (let v = start; v <= max + niceStep * 0.01; v += niceStep) {
    ticks.push(parseFloat(v.toFixed(6)))
    if (ticks.length > 10) break
  }
  return ticks
}

function polylinePts(xs, ys, xScale, yScale) {
  return xs.map((a, i) => `${xScale(a)},${yScale(ys[i])}`).join(' ')
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

function Tooltip({ x, y, alpha, CL, CD, show }) {
  if (!show) return null
  return (
    <g transform={`translate(${x + 8},${y - 8})`} style={{ pointerEvents: 'none' }}>
      <rect
        x={0}
        y={-16}
        width={110}
        height={CD != null ? 54 : 40}
        rx={4}
        fill="#1a1a2e"
        stroke="#3f3f5a"
        strokeWidth={1}
        opacity={0.95}
      />
      <text fill="#e0e0f0" fontSize={11} fontFamily="monospace">
        <tspan x={6} dy={0}>α = {alpha.toFixed(1)}°</tspan>
        <tspan x={6} dy={16}>CL = {CL.toFixed(4)}</tspan>
        {CD != null && <tspan x={6} dy={16}>CD = {CD.toFixed(5)}</tspan>}
      </text>
    </g>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * @param {{
 *   polar: { airfoil: string, alpha: number[], CL: number[], CD: number[] },
 *   width?: number,
 *   height?: number,
 *   showCD?: boolean,
 *   className?: string,
 * }} props
 */
export default function AirfoilPolarPlot({
  polar,
  width = 480,
  height = 300,
  showCD = false,
  className = '',
}) {
  const [tooltip, setTooltip] = useState(null)

  if (!polar || !polar.alpha || polar.alpha.length === 0) {
    return (
      <div
        className={`flex items-center justify-center text-sm text-ink-400 ${className}`}
        style={{ width, height }}
        aria-label="No polar data"
      >
        No polar data
      </div>
    )
  }

  const { alpha, CL, CD } = polar

  // Axes extents
  const innerW = width - MARGIN.left - MARGIN.right
  const innerH = height - MARGIN.top - MARGIN.bottom

  const aMin = Math.min(...alpha)
  const aMax = Math.max(...alpha)

  const clMin = Math.min(...CL)
  const clMax = Math.max(...CL)
  const clPad = (clMax - clMin) * 0.1 || 0.1

  const xScale = scaleLinear([aMin, aMax], [0, innerW])
  const yScale = scaleLinear([clMin - clPad, clMax + clPad], [innerH, 0])

  const alphaTicks = niceTicks(aMin, aMax, 7)
  const clTicks = niceTicks(clMin - clPad, clMax + clPad, 6)

  // Mouse interaction
  function handleMouseMove(e) {
    const svg = e.currentTarget
    const rect = svg.getBoundingClientRect()
    const mx = e.clientX - rect.left - MARGIN.left
    // Find nearest alpha index
    const alphaVal = aMin + (mx / innerW) * (aMax - aMin)
    let best = 0
    let bestDist = Infinity
    for (let i = 0; i < alpha.length; i++) {
      const d = Math.abs(alpha[i] - alphaVal)
      if (d < bestDist) { bestDist = d; best = i }
    }
    const px = xScale(alpha[best])
    const py = yScale(CL[best])
    setTooltip({
      x: px,
      y: py,
      alpha: alpha[best],
      CL: CL[best],
      CD: CD ? CD[best] : null,
    })
  }

  function handleMouseLeave() {
    setTooltip(null)
  }

  // Zero-CL line (α-axis)
  const zeroY = yScale(0)
  // Zero-alpha line
  const zeroX = xScale(0)

  return (
    <svg
      width={width}
      height={height}
      className={`airfoil-polar-plot ${className}`}
      aria-label={`CL vs α polar for ${polar.airfoil}`}
      role="img"
      style={{ background: '#0f0f1a', borderRadius: 8, overflow: 'visible' }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>

        {/* ── Grid lines ─────────────────────────────────────────────────── */}
        {clTicks.map((v) => (
          <line
            key={`hg-${v}`}
            x1={0} x2={innerW}
            y1={yScale(v)} y2={yScale(v)}
            stroke="#2a2a45"
            strokeWidth={1}
          />
        ))}
        {alphaTicks.map((v) => (
          <line
            key={`vg-${v}`}
            x1={xScale(v)} x2={xScale(v)}
            y1={0} y2={innerH}
            stroke="#2a2a45"
            strokeWidth={1}
          />
        ))}

        {/* ── Zero-CL axis ───────────────────────────────────────────────── */}
        {zeroY >= 0 && zeroY <= innerH && (
          <line
            x1={0} x2={innerW}
            y1={zeroY} y2={zeroY}
            stroke="#4a4a6a"
            strokeWidth={1.5}
            strokeDasharray="4 3"
          />
        )}

        {/* ── Zero-alpha axis ─────────────────────────────────────────────── */}
        {zeroX >= 0 && zeroX <= innerW && (
          <line
            x1={zeroX} x2={zeroX}
            y1={0} y2={innerH}
            stroke="#4a4a6a"
            strokeWidth={1.5}
            strokeDasharray="4 3"
          />
        )}

        {/* ── Axes border ────────────────────────────────────────────────── */}
        <rect x={0} y={0} width={innerW} height={innerH} fill="none" stroke="#3f3f5a" strokeWidth={1} />

        {/* ── CL line ────────────────────────────────────────────────────── */}
        <polyline
          points={polylinePts(alpha, CL, xScale, yScale)}
          fill="none"
          stroke="#4f9cf9"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* ── CD line (optional second series) ──────────────────────────── */}
        {showCD && CD && (
          <>
            {/* CD is typically much smaller — we scale it for visual clarity */}
            <polyline
              points={polylinePts(alpha, CD.map(v => v * 10), xScale, yScale)}
              fill="none"
              stroke="#f97b4f"
              strokeWidth={1.5}
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray="5 3"
            />
            <text x={innerW - 4} y={yScale(CD[CD.length - 1] * 10)} fill="#f97b4f" fontSize={9} textAnchor="end" dy={-4}>
              CD×10
            </text>
          </>
        )}

        {/* ── X-axis ticks + labels ──────────────────────────────────────── */}
        {alphaTicks.map((v) => (
          <g key={`xt-${v}`} transform={`translate(${xScale(v)},${innerH})`}>
            <line y1={0} y2={5} stroke="#6a6a8a" strokeWidth={1} />
            <text y={18} textAnchor="middle" fill="#9090b0" fontSize={10}>
              {v}
            </text>
          </g>
        ))}

        {/* ── Y-axis ticks + labels ──────────────────────────────────────── */}
        {clTicks.map((v) => (
          <g key={`yt-${v}`} transform={`translate(0,${yScale(v)})`}>
            <line x1={0} x2={-5} stroke="#6a6a8a" strokeWidth={1} />
            <text x={-8} textAnchor="end" dominantBaseline="middle" fill="#9090b0" fontSize={10}>
              {v.toFixed(2)}
            </text>
          </g>
        ))}

        {/* ── Axis labels ────────────────────────────────────────────────── */}
        <text
          x={innerW / 2}
          y={innerH + 36}
          textAnchor="middle"
          fill="#c0c0e0"
          fontSize={12}
        >
          α (deg)
        </text>
        <text
          transform={`translate(-38,${innerH / 2}) rotate(-90)`}
          textAnchor="middle"
          fill="#c0c0e0"
          fontSize={12}
        >
          CL
        </text>

        {/* ── Title ──────────────────────────────────────────────────────── */}
        <text
          x={innerW / 2}
          y={-10}
          textAnchor="middle"
          fill="#e0e0f0"
          fontSize={12}
          fontWeight="600"
        >
          {polar.airfoil} — CL vs α
        </text>

        {/* ── Tooltip dot + popup ────────────────────────────────────────── */}
        {tooltip && (
          <>
            <circle
              cx={tooltip.x}
              cy={tooltip.y}
              r={4}
              fill="#4f9cf9"
              stroke="#fff"
              strokeWidth={1}
            />
            <Tooltip
              x={tooltip.x < innerW - 130 ? tooltip.x : tooltip.x - 130}
              y={tooltip.y < 60 ? tooltip.y + 40 : tooltip.y}
              alpha={tooltip.alpha}
              CL={tooltip.CL}
              CD={tooltip.CD}
              show
            />
          </>
        )}
      </g>
    </svg>
  )
}
