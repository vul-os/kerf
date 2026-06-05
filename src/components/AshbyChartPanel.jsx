/**
 * AshbyChartPanel.jsx
 *
 * Ashby-style log-log material-property chart with optional Pareto-front
 * overlay and performance-index guide lines.
 *
 * Props
 * -----
 *   points      — Array of { name, x, y, family } — scatter data
 *                 (from matsel_tradeoff all_points or matsel_filter output)
 *   pareto      — Array of { name, x, y } on the Pareto front
 *   xLabel      — x-axis property label (e.g. "E (GPa)")
 *   yLabel      — y-axis property label (e.g. "σy (MPa)")
 *   title       — Chart title (default "Ashby Material Chart")
 *   indexLines  — Array of { slope, label } — log-log guide lines of the form
 *                 y = C · x^slope (Ashby merit indices)
 *   width       — SVG width  (default 560)
 *   height      — SVG height (default 460)
 *   className   — extra CSS class
 *
 * The component is purely presentational.
 *
 * References
 * ----------
 * Ashby, M.F. "Materials Selection in Mechanical Design" 5e (Butterworth-Heinemann)
 */

import { useState } from 'react'

// ---------------------------------------------------------------------------
// Colour palette per family
// ---------------------------------------------------------------------------

const FAMILY_COLORS = {
  steel:           '#ef5350',
  stainless_steel: '#ff7043',
  aluminium:       '#42a5f5',
  titanium:        '#ab47bc',
  magnesium:       '#26c6da',
  polymer:         '#66bb6a',
  composite:       '#ffa726',
  wood:            '#8d6e63',
  ceramic:         '#ec407a',
  cast_iron:       '#78909c',
  copper:          '#26a69a',
  _default:        '#bdbdbd',
}

function familyColor(family) {
  return FAMILY_COLORS[family] || FAMILY_COLORS._default
}

// ---------------------------------------------------------------------------
// Layout constants
// ---------------------------------------------------------------------------

const MAR = { top: 40, right: 30, bottom: 56, left: 68 }

// ---------------------------------------------------------------------------
// Scale helpers (log10)
// ---------------------------------------------------------------------------

function scaleLog(domMin, domMax, rangeMin, rangeMax) {
  const lmin = Math.log10(domMin)
  const lmax = Math.log10(domMax)
  const den = lmax - lmin
  return (v) => {
    if (v <= 0) return rangeMin
    return rangeMin + ((Math.log10(v) - lmin) / den) * (rangeMax - rangeMin)
  }
}

function logTicks(min, max) {
  const ticks = []
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e++) {
    const v = Math.pow(10, e)
    if (v >= min * 0.9 && v <= max * 1.1) ticks.push(v)
  }
  return ticks.length ? ticks : [min, max]
}

// ---------------------------------------------------------------------------
// Guide-line helper (y = C · x^slope in log-log space is a straight line)
// ---------------------------------------------------------------------------

function guideLine(slope, xMin, xMax, xScale, yScale, yMin, yMax, color, label, idx) {
  // Pick C so the line passes through the middle of the chart
  const xMid = Math.sqrt(xMin * xMax)
  const yMid = Math.sqrt(yMin * yMax)
  const C = yMid / Math.pow(xMid, slope)

  // Clamp to chart domain
  const xArr = [xMin, xMax]
  const yArr = xArr.map((x) => C * Math.pow(x, slope))

  const x1 = xScale(xArr[0])
  const y1 = yScale(yArr[0])
  const x2 = xScale(xArr[1])
  const y2 = yScale(yArr[1])

  if (!Number.isFinite(x1) || !Number.isFinite(x2)) return null
  if (!Number.isFinite(y1) || !Number.isFinite(y2)) return null

  return (
    <g key={`guide-${idx}`}>
      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={color}
        strokeWidth={1.5}
        strokeDasharray="6 3"
        opacity={0.7}
      />
      <text
        x={(x1 + x2) / 2 + 4}
        y={(y1 + y2) / 2 - 4}
        fill={color}
        fontSize={10}
        fontFamily="sans-serif"
        opacity={0.9}
      >
        {label}
      </text>
    </g>
  )
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

function Tooltip({ x, y, name, xVal, yVal, xLabel, yLabel, show }) {
  if (!show) return null
  return (
    <g transform={`translate(${x + 10},${y - 10})`} style={{ pointerEvents: 'none' }}>
      <rect x={0} y={-20} width={160} height={62} rx={4} fill="#1a1a2e" stroke="#3f3f5a" strokeWidth={1} opacity={0.97} />
      <text fill="#e0e0f0" fontSize={11} fontFamily="sans-serif">
        <tspan x={6} dy={0} fontWeight="bold">{name}</tspan>
        <tspan x={6} dy={16} fill="#aaa">{xLabel}: {xVal?.toPrecision(4)}</tspan>
        <tspan x={6} dy={14} fill="#aaa">{yLabel}: {yVal?.toPrecision(4)}</tspan>
      </text>
    </g>
  )
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------

function Legend({ families, width }) {
  if (!families.length) return null
  const cols = Math.min(3, families.length)
  return (
    <g transform={`translate(${MAR.left},${6})`}>
      {families.map((f, i) => {
        const col = i % cols
        const row = Math.floor(i / cols)
        const colW = (width - MAR.left - MAR.right) / cols
        return (
          <g key={f} transform={`translate(${col * colW},${row * 14})`}>
            <circle cx={5} cy={5} r={5} fill={familyColor(f)} />
            <text x={14} y={9} fill="#bbb" fontSize={10} fontFamily="sans-serif">
              {f.replace(/_/g, ' ')}
            </text>
          </g>
        )
      })}
    </g>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AshbyChartPanel({
  points = [],
  pareto = [],
  xLabel = 'Property X',
  yLabel = 'Property Y',
  title = 'Ashby Material Chart',
  indexLines = [],
  width = 560,
  height = 460,
  className = '',
}) {
  const [tooltip, setTooltip] = useState(null)

  const innerW = width - MAR.left - MAR.right
  const innerH = height - MAR.top - MAR.bottom

  // Determine domains
  const allX = [...points, ...pareto].map((p) => p.x).filter((v) => v > 0)
  const allY = [...points, ...pareto].map((p) => p.y).filter((v) => v > 0)

  if (!allX.length || !allY.length) {
    return (
      <div
        className={className}
        style={{
          width, height,
          background: '#0d0d1a',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: 4,
          color: '#555',
          fontFamily: 'sans-serif',
          fontSize: 13,
        }}
      >
        No material data
      </div>
    )
  }

  const xMin = Math.min(...allX)
  const xMax = Math.max(...allX)
  const yMin = Math.min(...allY)
  const yMax = Math.max(...allY)

  // Add 30% log-space padding
  const xMinP = Math.pow(10, Math.log10(xMin) - 0.15)
  const xMaxP = Math.pow(10, Math.log10(xMax) + 0.15)
  const yMinP = Math.pow(10, Math.log10(yMin) - 0.15)
  const yMaxP = Math.pow(10, Math.log10(yMax) + 0.15)

  const xS = scaleLog(xMinP, xMaxP, MAR.left, MAR.left + innerW)
  const yS = scaleLog(yMinP, yMaxP, MAR.top + innerH, MAR.top)

  const xTicks = logTicks(xMinP, xMaxP)
  const yTicks = logTicks(yMinP, yMaxP)

  // Families for legend
  const families = [...new Set(points.map((p) => p.family || '_default'))]

  // Pareto front polyline (sorted by x)
  const paretoSorted = [...pareto].sort((a, b) => a.x - b.x)
  const paretoPts = paretoSorted
    .map((p) => {
      const x = xS(p.x)
      const y = yS(p.y)
      return Number.isFinite(x) && Number.isFinite(y) ? `${x.toFixed(1)},${y.toFixed(1)}` : null
    })
    .filter(Boolean)
    .join(' ')

  // Guide lines
  const GUIDE_COLORS = ['#ffd54f', '#80cbc4', '#ffab91', '#ce93d8', '#a5d6a7']

  return (
    <div className={`ashby-chart-panel ${className}`} style={{ display: 'inline-block' }}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`${title}: ${xLabel} vs ${yLabel}, ${points.length} materials`}
        onMouseLeave={() => setTooltip(null)}
      >
        <rect width={width} height={height} fill="#0d0d1a" rx={4} />

        {/* Title */}
        <text x={width / 2} y={18} textAnchor="middle" fill="#e0e0f0" fontSize={13} fontFamily="sans-serif" fontWeight="bold">
          {title}
        </text>

        {/* Grid lines */}
        {xTicks.map((t) => {
          const x = xS(t)
          return Number.isFinite(x) ? (
            <line key={t} x1={x} x2={x} y1={MAR.top} y2={MAR.top + innerH} stroke="#1e1e2e" strokeWidth={1} />
          ) : null
        })}
        {yTicks.map((t) => {
          const y = yS(t)
          return Number.isFinite(y) ? (
            <line key={t} x1={MAR.left} x2={MAR.left + innerW} y1={y} y2={y} stroke="#1e1e2e" strokeWidth={1} />
          ) : null
        })}

        {/* Axis tick labels */}
        {xTicks.map((t) => {
          const x = xS(t)
          if (!Number.isFinite(x)) return null
          const label = t >= 1000 ? `${t / 1000}k` : t >= 1 ? String(+t.toPrecision(3)) : String(+t.toPrecision(2))
          return (
            <text key={t} x={x} y={MAR.top + innerH + 18} textAnchor="middle" fill="#888" fontSize={10} fontFamily="monospace">
              {label}
            </text>
          )
        })}
        {yTicks.map((t) => {
          const y = yS(t)
          if (!Number.isFinite(y)) return null
          const label = t >= 1000 ? `${t / 1000}k` : t >= 1 ? String(+t.toPrecision(3)) : String(+t.toPrecision(2))
          return (
            <text key={t} x={MAR.left - 6} y={y + 4} textAnchor="end" fill="#888" fontSize={10} fontFamily="monospace">
              {label}
            </text>
          )
        })}

        {/* Axis labels */}
        <text x={MAR.left + innerW / 2} y={height - 8} textAnchor="middle" fill="#aaa" fontSize={11} fontFamily="sans-serif">
          {xLabel}
        </text>
        <text
          transform={`rotate(-90) translate(${-(MAR.top + innerH / 2)},${MAR.left - 52})`}
          textAnchor="middle"
          fill="#aaa"
          fontSize={11}
          fontFamily="sans-serif"
        >
          {yLabel}
        </text>

        {/* Guide lines (Ashby performance index lines) */}
        {indexLines.map((il, i) =>
          guideLine(
            il.slope, xMinP, xMaxP, xS, yS, yMinP, yMaxP,
            GUIDE_COLORS[i % GUIDE_COLORS.length],
            il.label,
            i,
          )
        )}

        {/* Pareto front */}
        {paretoPts && (
          <polyline points={paretoPts} fill="none" stroke="#ffd54f" strokeWidth={2.5} strokeDasharray="8 3" opacity={0.9} />
        )}

        {/* Scatter points */}
        {points.map((p, i) => {
          const x = xS(p.x)
          const y = yS(p.y)
          if (!Number.isFinite(x) || !Number.isFinite(y)) return null
          const color = familyColor(p.family)
          const isPareto = pareto.some((pp) => pp.name === p.name)
          return (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={isPareto ? 7 : 5}
              fill={color}
              stroke={isPareto ? '#ffd54f' : 'none'}
              strokeWidth={isPareto ? 2 : 0}
              opacity={0.85}
              style={{ cursor: 'pointer' }}
              onMouseEnter={(e) =>
                setTooltip({
                  svgX: x,
                  svgY: y,
                  name: p.name,
                  x: p.x,
                  y: p.y,
                })
              }
            />
          )
        })}

        {/* Tooltip */}
        {tooltip && (
          <Tooltip
            x={tooltip.svgX}
            y={tooltip.svgY}
            name={tooltip.name}
            xVal={tooltip.x}
            yVal={tooltip.y}
            xLabel={xLabel}
            yLabel={yLabel}
            show
          />
        )}

        {/* Legend */}
        <Legend families={families} width={width} />

        {/* Pareto legend */}
        {pareto.length > 0 && (
          <g transform={`translate(${MAR.left + innerW - 110},${MAR.top + 6})`}>
            <line x1={0} y1={6} x2={20} y2={6} stroke="#ffd54f" strokeWidth={2} strokeDasharray="8 3" />
            <text x={24} y={10} fill="#ffd54f" fontSize={10} fontFamily="sans-serif">Pareto front</text>
          </g>
        )}
      </svg>

      {/* Material count */}
      <div style={{ marginTop: 4, fontFamily: 'monospace', fontSize: 11, color: '#666' }}>
        {points.length} materials{pareto.length > 0 ? ` · ${pareto.length} on Pareto front` : ''}
      </div>
    </div>
  )
}
