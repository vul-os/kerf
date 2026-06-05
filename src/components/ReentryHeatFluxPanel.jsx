// ReentryHeatFluxPanel.jsx — Re-entry stagnation heat-flux panel.
//
// Renders output from aero_reentry_heat_flux tool:
//   - Point-mode: summary cards (q_conv, q_rad, q_total)
//   - Trajectory-mode: heat-flux vs altitude or vs velocity SVG chart
//
// Props
// ─────
//   result  {Object|null}  — parsed JSON from aero_reentry_heat_flux
//   loading {boolean}
//   error   {string|null}

import { useMemo } from 'react'

// ---------------------------------------------------------------------------
// Chart constants
// ---------------------------------------------------------------------------

const CHART_W = 480
const CHART_H = 220
const PAD = { top: 20, right: 20, bottom: 42, left: 70 }
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
  const step = (max - min) / (n - 1)
  return Array.from({ length: n }, (_, i) => min + i * step)
}

function fmtFlux(v) {
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)} MW/m²`
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)} kW/m²`
  return `${v.toFixed(1)} W/m²`
}

function fmtCm2(v) {
  if (v === null || v === undefined) return '—'
  return `${v.toFixed(2)} W/cm²`
}

// ---------------------------------------------------------------------------
// Trajectory chart
// ---------------------------------------------------------------------------

function TrajectoryChart({ trajectory }) {
  const alts = trajectory.map(p => p.altitude_km)
  const fluxes = trajectory.map(p => p.q_total_W_m2)
  const convs = trajectory.map(p => p.q_convective_W_m2)
  const rads = trajectory.map(p => p.q_radiative_W_m2)

  const xMin = Math.min(...alts)
  const xMax = Math.max(...alts)
  const yMin = 0
  const yMax = Math.max(...fluxes) * 1.1 || 1e6

  const xS = scaleLinear([xMin, xMax], [0, INNER_W])
  const yS = scaleLinear([yMin, yMax], [INNER_H, 0])

  const pathTotal = buildPath(alts, fluxes, xS, yS)
  const pathConv = buildPath(alts, convs, xS, yS)
  const pathRad = buildPath(alts, rads, xS, yS)

  const yTicks = axisTicks(yMin, yMax, 5)
  const xTicks = axisTicks(xMin, xMax, 5)

  const peakIdx = fluxes.indexOf(Math.max(...fluxes))
  const peakAlt = alts[peakIdx]
  const peakFlux = fluxes[peakIdx]

  return (
    <div>
      <svg
        width={CHART_W}
        height={CHART_H}
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        className="overflow-visible"
      >
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {/* Grid */}
          {yTicks.map(t => (
            <line key={t} x1={0} y1={yS(t)} x2={INNER_W} y2={yS(t)}
              stroke="#374151" strokeWidth={0.5} strokeDasharray="3,3" />
          ))}
          {xTicks.map(t => (
            <line key={t} x1={xS(t)} y1={0} x2={xS(t)} y2={INNER_H}
              stroke="#374151" strokeWidth={0.5} strokeDasharray="3,3" />
          ))}

          {/* Curves */}
          {pathConv && <path d={pathConv} fill="none" stroke="#60a5fa" strokeWidth={1.5} strokeDasharray="4,2" />}
          {pathRad && <path d={pathRad} fill="none" stroke="#f97316" strokeWidth={1.5} strokeDasharray="4,2" />}
          {pathTotal && <path d={pathTotal} fill="none" stroke="#a78bfa" strokeWidth={2.5} />}

          {/* Peak marker */}
          {peakIdx >= 0 && (
            <g transform={`translate(${xS(peakAlt)},${yS(peakFlux)})`}>
              <circle r={4} fill="#a78bfa" />
            </g>
          )}

          {/* Axes */}
          <line x1={0} y1={0} x2={0} y2={INNER_H} stroke="#9ca3af" strokeWidth={1} />
          <line x1={0} y1={INNER_H} x2={INNER_W} y2={INNER_H} stroke="#9ca3af" strokeWidth={1} />

          {/* Ticks */}
          {xTicks.map(t => (
            <g key={t} transform={`translate(${xS(t)},${INNER_H})`}>
              <line y2={4} stroke="#9ca3af" />
              <text y={14} textAnchor="middle" fontSize={9} fill="#9ca3af">
                {t.toFixed(0)}
              </text>
            </g>
          ))}
          {yTicks.map(t => (
            <g key={t} transform={`translate(0,${yS(t)})`}>
              <line x2={-4} stroke="#9ca3af" />
              <text x={-7} textAnchor="end" dominantBaseline="middle" fontSize={9} fill="#9ca3af">
                {(t / 1e6).toFixed(1)}
              </text>
            </g>
          ))}

          {/* Labels */}
          <text x={INNER_W / 2} y={INNER_H + 32} textAnchor="middle" fontSize={10} fill="#d1d5db">
            Altitude (km)
          </text>
          <text
            x={-INNER_H / 2} y={-58}
            textAnchor="middle" fontSize={10} fill="#d1d5db"
            transform="rotate(-90)"
          >
            Heat Flux (MW/m²)
          </text>
        </g>
      </svg>

      <div className="flex gap-4 text-xs text-gray-400 mt-1">
        <span className="flex items-center gap-1">
          <span style={{ display: 'inline-block', width: 20, height: 2, background: '#a78bfa' }} />
          Total
        </span>
        <span className="flex items-center gap-1">
          <span style={{ display: 'inline-block', width: 20, height: 2, background: '#60a5fa', borderTop: '1px dashed' }} />
          Convective
        </span>
        <span className="flex items-center gap-1">
          <span style={{ display: 'inline-block', width: 20, height: 2, background: '#f97316', borderTop: '1px dashed' }} />
          Radiative
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ReentryHeatFluxPanel
// ---------------------------------------------------------------------------

export default function ReentryHeatFluxPanel({ result, loading, error }) {
  const data = useMemo(() => {
    if (!result || !result.ok) return null
    return result
  }, [result])

  if (loading) {
    return (
      <div className="p-4 rounded-lg bg-gray-900 border border-gray-700 text-gray-400 text-sm">
        Computing re-entry heat flux...
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

  // Trajectory mode
  if (data.trajectory) {
    const pts = data.trajectory
    const peakFlux = Math.max(...pts.map(p => p.q_total_W_m2))
    const peakPt = pts.find(p => p.q_total_W_m2 === peakFlux)

    return (
      <div className="flex flex-col gap-4 p-4 rounded-lg bg-gray-900 border border-gray-700">
        <div className="text-sm font-semibold text-gray-200">Re-entry Heat Flux — Trajectory</div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <SummaryCard label="Points" value={data.n_points} />
          <SummaryCard label="Peak Total" value={fmtFlux(peakFlux)} highlight />
          <SummaryCard label="Peak (W/cm²)" value={fmtCm2(peakFlux / 1e4)} />
        </div>

        {peakPt && (
          <div className="text-xs text-gray-400">
            Peak at {peakPt.altitude_km} km, {(peakPt.velocity_m_s / 1000).toFixed(2)} km/s
          </div>
        )}

        <div className="overflow-x-auto">
          <TrajectoryChart trajectory={pts} />
        </div>

        <div className="text-xs text-gray-500 mt-1">
          Sutton-Graves convective (NASA TR R-376) + Tauber-Sutton radiative.
          Nose radius: {data.nose_radius_m} m.
        </div>
      </div>
    )
  }

  // Point mode
  const { altitude_km, velocity_m_s, q_convective_W_m2, q_radiative_W_m2, q_total_W_m2, q_total_W_cm2, nose_radius_m, method } = data

  return (
    <div className="flex flex-col gap-4 p-4 rounded-lg bg-gray-900 border border-gray-700">
      <div className="text-sm font-semibold text-gray-200">Re-entry Heat Flux — Point</div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryCard label="Altitude" value={`${altitude_km} km`} />
        <SummaryCard label="Velocity" value={`${(velocity_m_s / 1000).toFixed(2)} km/s`} />
        <SummaryCard label="Convective" value={fmtFlux(q_convective_W_m2)} />
        <SummaryCard label="Radiative" value={fmtFlux(q_radiative_W_m2)} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <SummaryCard label="Total Heat Flux" value={fmtFlux(q_total_W_m2)} highlight />
        <SummaryCard label="Total (W/cm²)" value={fmtCm2(q_total_W_cm2)} highlight />
      </div>

      <div className="text-xs text-gray-500 mt-1">
        {method}. Nose radius: {nose_radius_m} m.
      </div>
    </div>
  )
}

function SummaryCard({ label, value, highlight }) {
  return (
    <div className={`rounded p-2 border text-center ${
      highlight ? 'border-purple-600 bg-purple-950' : 'border-gray-700 bg-gray-800'
    }`}>
      <div className="text-xs text-gray-400">{label}</div>
      <div className={`text-sm font-semibold ${highlight ? 'text-purple-300' : 'text-gray-200'}`}>
        {value}
      </div>
    </div>
  )
}
