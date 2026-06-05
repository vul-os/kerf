// SixDOFPanel.jsx — 6-DOF rigid-body flight dynamics panel.
//
// Renders output from aero_sixdof_simulate tool:
//   - Final state summary cards (altitude, airspeed, Euler angles)
//   - Altitude vs time trajectory SVG chart
//   - Airspeed vs time chart
//
// Props
// ─────
//   result  {Object|null}  — parsed JSON from aero_sixdof_simulate
//   loading {boolean}
//   error   {string|null}

import { useMemo } from 'react'

// ---------------------------------------------------------------------------
// Chart constants
// ---------------------------------------------------------------------------

const CHART_W = 480
const CHART_H = 180
const PAD = { top: 16, right: 20, bottom: 38, left: 60 }
const INNER_W = CHART_W - PAD.left - PAD.right
const INNER_H = CHART_H - PAD.top - PAD.bottom

function scaleLinear(domain, range) {
  const [d0, d1] = domain
  const [r0, r1] = range
  const dSpan = d1 - d0 || 1
  return v => r0 + ((v - d0) / dSpan) * (r1 - r0)
}

function buildPath(xs, ys, xS, yS) {
  return xs
    .map((x, i) => {
      const y = ys[i]
      if (y === null || !isFinite(y)) return null
      return `${i === 0 ? 'M' : 'L'}${xS(x).toFixed(2)},${yS(y).toFixed(2)}`
    })
    .filter(Boolean)
    .join(' ')
}

function axisTicks(min, max, n = 5) {
  const step = (max - min) / (n - 1) || 1
  return Array.from({ length: n }, (_, i) => min + i * step)
}

// ---------------------------------------------------------------------------
// Simple line chart
// ---------------------------------------------------------------------------

function LineChart({ times, values, yLabel, yUnit, color = '#60a5fa' }) {
  if (!times || times.length === 0) return null

  const xMin = times[0]
  const xMax = times[times.length - 1]
  const yMin = Math.min(...values) * 0.98
  const yMax = Math.max(...values) * 1.02 || 1

  const xS = scaleLinear([xMin, xMax], [0, INNER_W])
  const yS = scaleLinear([yMin, yMax], [INNER_H, 0])

  const path = buildPath(times, values, xS, yS)
  const xTicks = axisTicks(xMin, xMax, 5)
  const yTicks = axisTicks(yMin, yMax, 4)

  return (
    <svg
      width={CHART_W}
      height={CHART_H}
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      className="overflow-visible"
    >
      <g transform={`translate(${PAD.left},${PAD.top})`}>
        {yTicks.map(t => (
          <line key={t} x1={0} y1={yS(t)} x2={INNER_W} y2={yS(t)}
            stroke="#374151" strokeWidth={0.5} strokeDasharray="3,3" />
        ))}
        {path && <path d={path} fill="none" stroke={color} strokeWidth={2} />}

        <line x1={0} y1={0} x2={0} y2={INNER_H} stroke="#9ca3af" strokeWidth={1} />
        <line x1={0} y1={INNER_H} x2={INNER_W} y2={INNER_H} stroke="#9ca3af" strokeWidth={1} />

        {xTicks.map(t => (
          <g key={t} transform={`translate(${xS(t)},${INNER_H})`}>
            <line y2={4} stroke="#9ca3af" />
            <text y={14} textAnchor="middle" fontSize={9} fill="#9ca3af">
              {t.toFixed(1)}
            </text>
          </g>
        ))}
        {yTicks.map(t => (
          <g key={t} transform={`translate(0,${yS(t)})`}>
            <line x2={-4} stroke="#9ca3af" />
            <text x={-7} textAnchor="end" dominantBaseline="middle" fontSize={9} fill="#9ca3af">
              {t.toFixed(1)}
            </text>
          </g>
        ))}

        <text x={INNER_W / 2} y={INNER_H + 30} textAnchor="middle" fontSize={10} fill="#d1d5db">
          Time (s)
        </text>
        <text
          x={-INNER_H / 2} y={-48}
          textAnchor="middle" fontSize={10} fill="#d1d5db"
          transform="rotate(-90)"
        >
          {yLabel}{yUnit ? ` (${yUnit})` : ''}
        </text>
      </g>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// SixDOFPanel
// ---------------------------------------------------------------------------

export default function SixDOFPanel({ result, loading, error }) {
  const data = useMemo(() => {
    if (!result || !result.ok) return null
    return result
  }, [result])

  if (loading) {
    return (
      <div className="p-4 rounded-lg bg-gray-900 border border-gray-700 text-gray-400 text-sm">
        Simulating 6-DOF flight dynamics...
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
    n_steps,
    duration_s,
    final_altitude_m,
    final_airspeed_m_s,
    final_euler_deg,
    max_altitude_m,
    min_altitude_m,
    trajectory_summary,
  } = data

  const times = trajectory_summary?.map(p => p.t_s) ?? []
  const altitudes = trajectory_summary?.map(p => p.altitude_m) ?? []
  const airspeeds = trajectory_summary?.map(p => p.airspeed_m_s) ?? []

  const [roll, pitch, yaw] = final_euler_deg ?? [0, 0, 0]

  return (
    <div className="flex flex-col gap-4 p-4 rounded-lg bg-gray-900 border border-gray-700">
      <div className="text-sm font-semibold text-gray-200">6-DOF Flight Dynamics — NED / Quaternion</div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryCard label="Final Alt" value={`${final_altitude_m?.toFixed(1) ?? '—'} m`} />
        <SummaryCard label="Final Speed" value={`${final_airspeed_m_s?.toFixed(2) ?? '—'} m/s`} />
        <SummaryCard label="Alt Range"
          value={`${min_altitude_m?.toFixed(0) ?? '—'} – ${max_altitude_m?.toFixed(0) ?? '—'} m`} />
        <SummaryCard label="Steps" value={`${n_steps} (Δt=${(duration_s/n_steps).toFixed(3)}s)`} />
      </div>

      <div className="grid grid-cols-3 gap-3">
        <SummaryCard label="Roll" value={`${roll?.toFixed(2) ?? '—'}°`} />
        <SummaryCard label="Pitch" value={`${pitch?.toFixed(2) ?? '—'}°`} />
        <SummaryCard label="Yaw" value={`${yaw?.toFixed(2) ?? '—'}°`} />
      </div>

      {/* Altitude chart */}
      {times.length > 1 && (
        <>
          <div className="text-xs text-gray-400 font-medium mt-2">Altitude vs Time</div>
          <div className="overflow-x-auto">
            <LineChart times={times} values={altitudes} yLabel="Altitude" yUnit="m" color="#34d399" />
          </div>
        </>
      )}

      {/* Airspeed chart */}
      {times.length > 1 && (
        <>
          <div className="text-xs text-gray-400 font-medium mt-1">Airspeed vs Time</div>
          <div className="overflow-x-auto">
            <LineChart times={times} values={airspeeds} yLabel="Airspeed" yUnit="m/s" color="#60a5fa" />
          </div>
        </>
      )}

      <div className="text-xs text-gray-500 mt-1">
        Stevens &amp; Lewis 6-DOF NED frame, quaternion kinematics, RK4 integration.
        Gravity applied from attitude; constant external forces/moments only.
      </div>
    </div>
  )
}

function SummaryCard({ label, value }) {
  return (
    <div className="rounded p-2 border border-gray-700 bg-gray-800 text-center">
      <div className="text-xs text-gray-400">{label}</div>
      <div className="text-sm font-semibold text-gray-200">{value}</div>
    </div>
  )
}
