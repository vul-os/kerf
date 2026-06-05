// FlutterPanel.jsx — V-g / V-f flutter analysis panel for aeroelastic typical-section model.
//
// Calls the aero_flutter_typical_section LLM tool and renders:
//   - Flutter speed / frequency summary cards
//   - V-g (velocity vs damping) chart — two modes
//   - V-f (velocity vs frequency) chart — two modes
//
// Props
// ─────
//   result  {Object|null}  — parsed JSON response from aero_flutter_typical_section
//   loading {boolean}      — true while the tool call is in flight
//   error   {string|null}  — error message, if any

import { useMemo } from 'react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHART_W = 480
const CHART_H = 200
const PAD = { top: 20, right: 20, bottom: 40, left: 55 }
const INNER_W = CHART_W - PAD.left - PAD.right
const INNER_H = CHART_H - PAD.top - PAD.bottom

const COLORS = ['#60a5fa', '#f97316']  // blue, orange
const FLUTTER_LINE_COLOR = '#ef4444'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scaleLinear(domain, range) {
  const [d0, d1] = domain
  const [r0, r1] = range
  const dSpan = d1 - d0 || 1
  const rSpan = r1 - r0
  return v => r0 + ((v - d0) / dSpan) * rSpan
}

function buildPath(xs, ys, xScale, yScale) {
  const pts = xs
    .map((x, i) => {
      const y = ys[i]
      if (y === null || y === undefined) return null
      return [xScale(x), yScale(y)]
    })
    .filter(Boolean)
  if (pts.length === 0) return ''
  return pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(2)},${p[1].toFixed(2)}`)
    .join(' ')
}

function axisTicks(min, max, n = 5) {
  const step = (max - min) / (n - 1)
  return Array.from({ length: n }, (_, i) => min + i * step)
}

function fmt(v) {
  if (v === null || v === undefined) return '—'
  if (Math.abs(v) < 0.001 || Math.abs(v) >= 10000) return v.toExponential(2)
  return v.toFixed(2)
}

// ---------------------------------------------------------------------------
// SVG mini-chart (V-g or V-f)
// ---------------------------------------------------------------------------

function VgChart({ velocities, mode0, mode1, yLabel, yUnit, flutterSpeed }) {
  const allY = [...(mode0 ?? []), ...(mode1 ?? [])].filter(y => y !== null && isFinite(y))
  const yMin = allY.length ? Math.min(...allY) : -0.2
  const yMax = allY.length ? Math.max(...allY) : 0.2
  const yPad = (yMax - yMin) * 0.1 || 0.05
  const xMin = velocities[0] ?? 0
  const xMax = velocities[velocities.length - 1] ?? 100

  const xS = scaleLinear([xMin, xMax], [0, INNER_W])
  const yS = scaleLinear([yMin - yPad, yMax + yPad], [INNER_H, 0])

  const xTicks = axisTicks(xMin, xMax, 5)
  const yTicks = axisTicks(yMin - yPad, yMax + yPad, 5)

  const path0 = mode0 ? buildPath(velocities, mode0, xS, yS) : ''
  const path1 = mode1 ? buildPath(velocities, mode1, xS, yS) : ''

  const hasFlutter = flutterSpeed !== null && isFinite(flutterSpeed)
  const flutterX = hasFlutter ? xS(flutterSpeed) : null

  return (
    <svg
      width={CHART_W}
      height={CHART_H}
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      className="overflow-visible"
    >
      <g transform={`translate(${PAD.left},${PAD.top})`}>
        {/* Grid lines */}
        {yTicks.map(t => (
          <line
            key={t}
            x1={0} y1={yS(t)} x2={INNER_W} y2={yS(t)}
            stroke="#374151" strokeWidth={0.5} strokeDasharray="3,3"
          />
        ))}
        {xTicks.map(t => (
          <line
            key={t}
            x1={xS(t)} y1={0} x2={xS(t)} y2={INNER_H}
            stroke="#374151" strokeWidth={0.5} strokeDasharray="3,3"
          />
        ))}

        {/* Zero damping line (y=0) */}
        {yLabel === 'Damping g' && (
          <line
            x1={0} y1={yS(0)} x2={INNER_W} y2={yS(0)}
            stroke="#6b7280" strokeWidth={1}
          />
        )}

        {/* Flutter vertical line */}
        {hasFlutter && (
          <line
            x1={flutterX} y1={0} x2={flutterX} y2={INNER_H}
            stroke={FLUTTER_LINE_COLOR} strokeWidth={1.5} strokeDasharray="5,3"
          />
        )}

        {/* Mode curves */}
        {path0 && <path d={path0} fill="none" stroke={COLORS[0]} strokeWidth={2} />}
        {path1 && <path d={path1} fill="none" stroke={COLORS[1]} strokeWidth={2} />}

        {/* Axes */}
        <line x1={0} y1={0} x2={0} y2={INNER_H} stroke="#9ca3af" strokeWidth={1} />
        <line x1={0} y1={INNER_H} x2={INNER_W} y2={INNER_H} stroke="#9ca3af" strokeWidth={1} />

        {/* X ticks */}
        {xTicks.map(t => (
          <g key={t} transform={`translate(${xS(t)},${INNER_H})`}>
            <line y2={4} stroke="#9ca3af" />
            <text y={14} textAnchor="middle" fontSize={9} fill="#9ca3af">
              {t.toFixed(0)}
            </text>
          </g>
        ))}

        {/* Y ticks */}
        {yTicks.map(t => (
          <g key={t} transform={`translate(0,${yS(t)})`}>
            <line x2={-4} stroke="#9ca3af" />
            <text x={-7} textAnchor="end" dominantBaseline="middle" fontSize={9} fill="#9ca3af">
              {t.toFixed(2)}
            </text>
          </g>
        ))}

        {/* Axis labels */}
        <text
          x={INNER_W / 2}
          y={INNER_H + 32}
          textAnchor="middle"
          fontSize={10}
          fill="#d1d5db"
        >
          Velocity (m/s)
        </text>
        <text
          x={-INNER_H / 2}
          y={-42}
          textAnchor="middle"
          fontSize={10}
          fill="#d1d5db"
          transform="rotate(-90)"
        >
          {yLabel} {yUnit ? `(${yUnit})` : ''}
        </text>
      </g>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------

function Legend() {
  return (
    <div className="flex gap-4 text-xs text-gray-400 mt-1">
      <span className="flex items-center gap-1">
        <span style={{ display: 'inline-block', width: 20, height: 2, background: COLORS[0] }} />
        Mode 0 (plunge)
      </span>
      <span className="flex items-center gap-1">
        <span style={{ display: 'inline-block', width: 20, height: 2, background: COLORS[1] }} />
        Mode 1 (torsion)
      </span>
      <span className="flex items-center gap-1">
        <span style={{ display: 'inline-block', width: 20, height: 2, background: FLUTTER_LINE_COLOR, borderTop: '1px dashed' }} />
        Flutter speed
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// FlutterPanel
// ---------------------------------------------------------------------------

export default function FlutterPanel({ result, loading, error }) {
  const data = useMemo(() => {
    if (!result || !result.ok) return null
    return result
  }, [result])

  if (loading) {
    return (
      <div className="p-4 rounded-lg bg-gray-900 border border-gray-700 text-gray-400 text-sm">
        Computing flutter curves...
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 rounded-lg bg-gray-900 border border-red-800 text-red-400 text-sm">
        {error}
      </div>
    )
  }

  if (!data) return null

  const {
    flutter_speed_m_s,
    flutter_freq_hz,
    flutter_speed_nd,
    flutter_freq_rad_s,
    velocities_m_s,
    damping_mode0,
    damping_mode1,
    freq_mode0_rad_s,
    freq_mode1_rad_s,
    method,
  } = data

  const hasFlutter = flutter_speed_m_s !== null

  return (
    <div className="flex flex-col gap-4 p-4 rounded-lg bg-gray-900 border border-gray-700">
      <div className="text-sm font-semibold text-gray-200">Flutter Analysis — Typical Section p-k</div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryCard
          label="Flutter Speed"
          value={hasFlutter ? `${flutter_speed_m_s.toFixed(1)} m/s` : 'Not found'}
          highlight={hasFlutter}
        />
        <SummaryCard
          label="U_F / (b·ω_α)"
          value={hasFlutter && flutter_speed_nd != null ? flutter_speed_nd.toFixed(3) : '—'}
        />
        <SummaryCard
          label="Flutter Freq"
          value={hasFlutter && flutter_freq_hz != null ? `${flutter_freq_hz.toFixed(2)} Hz` : '—'}
        />
        <SummaryCard
          label="ω_F"
          value={hasFlutter && flutter_freq_rad_s != null ? `${flutter_freq_rad_s.toFixed(2)} rad/s` : '—'}
        />
      </div>

      {/* V-g chart */}
      {velocities_m_s && (
        <>
          <div className="text-xs text-gray-400 font-medium mt-2">V-g Diagram (Damping vs Velocity)</div>
          <div className="overflow-x-auto">
            <VgChart
              velocities={velocities_m_s}
              mode0={damping_mode0}
              mode1={damping_mode1}
              yLabel="Damping g"
              yUnit=""
              flutterSpeed={flutter_speed_m_s}
            />
          </div>
        </>
      )}

      {/* V-f chart */}
      {velocities_m_s && (
        <>
          <div className="text-xs text-gray-400 font-medium mt-1">V-f Diagram (Frequency vs Velocity)</div>
          <div className="overflow-x-auto">
            <VgChart
              velocities={velocities_m_s}
              mode0={freq_mode0_rad_s}
              mode1={freq_mode1_rad_s}
              yLabel="Frequency"
              yUnit="rad/s"
              flutterSpeed={flutter_speed_m_s}
            />
          </div>
        </>
      )}

      <Legend />

      <div className="text-xs text-gray-500 mt-1">{method}</div>
    </div>
  )
}

function SummaryCard({ label, value, highlight }) {
  return (
    <div
      className={`rounded p-2 border text-center ${
        highlight
          ? 'border-orange-600 bg-orange-950'
          : 'border-gray-700 bg-gray-800'
      }`}
    >
      <div className="text-xs text-gray-400">{label}</div>
      <div className={`text-sm font-semibold ${highlight ? 'text-orange-300' : 'text-gray-200'}`}>
        {value}
      </div>
    </div>
  )
}
