// SeakeepingRAOPanel.jsx — Marine seakeeping RAO panel.
//
// Renders output from marine_seakeeping_rao and/or marine_seakeeping_stats tools:
//   - RAO curves (heave, pitch, roll amplitude vs frequency)
//   - Irregular-sea statistics cards (if stats available)
//
// Props
// ─────
//   result      {Object|null}  — parsed JSON from marine_seakeeping_rao
//   statsResult {Object|null}  — parsed JSON from marine_seakeeping_stats (optional)
//   loading     {boolean}
//   error       {string|null}

import { useMemo } from 'react'

// ---------------------------------------------------------------------------
// Chart constants
// ---------------------------------------------------------------------------

const CHART_W = 480
const CHART_H = 200
const PAD = { top: 18, right: 20, bottom: 40, left: 55 }
const INNER_W = CHART_W - PAD.left - PAD.right
const INNER_H = CHART_H - PAD.top - PAD.bottom

const RAO_COLORS = {
  heave: '#34d399',  // green
  pitch: '#60a5fa',  // blue
  roll:  '#f97316',  // orange
}

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
// RAO chart
// ---------------------------------------------------------------------------

function RAOChart({ omegas, heaveAmps, pitchAmps, rollAmps, mode = 'heave_pitch' }) {
  const seriesMap = {
    heave: heaveAmps,
    pitch: pitchAmps,
    roll: rollAmps,
  }

  const activeSeries = Object.entries(seriesMap).filter(([, vals]) => vals && vals.length > 0)
  const allY = activeSeries.flatMap(([, vals]) => vals.filter(v => v !== null && isFinite(v)))

  const xMin = omegas[0]
  const xMax = omegas[omegas.length - 1]
  const yMin = 0
  const yMax = (Math.max(...allY) || 1) * 1.1

  const xS = scaleLinear([xMin, xMax], [0, INNER_W])
  const yS = scaleLinear([yMin, yMax], [INNER_H, 0])

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
        {/* Grid */}
        {yTicks.map(t => (
          <line key={t} x1={0} y1={yS(t)} x2={INNER_W} y2={yS(t)}
            stroke="#374151" strokeWidth={0.5} strokeDasharray="3,3" />
        ))}
        {xTicks.map(t => (
          <line key={t} x1={xS(t)} y1={0} x2={xS(t)} y2={INNER_H}
            stroke="#374151" strokeWidth={0.5} strokeDasharray="3,3" />
        ))}

        {/* Series */}
        {activeSeries.map(([key, vals]) => {
          const path = buildPath(omegas, vals, xS, yS)
          return path ? (
            <path key={key} d={path} fill="none" stroke={RAO_COLORS[key]} strokeWidth={2} />
          ) : null
        })}

        {/* Axes */}
        <line x1={0} y1={0} x2={0} y2={INNER_H} stroke="#9ca3af" strokeWidth={1} />
        <line x1={0} y1={INNER_H} x2={INNER_W} y2={INNER_H} stroke="#9ca3af" strokeWidth={1} />

        {xTicks.map(t => (
          <g key={t} transform={`translate(${xS(t)},${INNER_H})`}>
            <line y2={4} stroke="#9ca3af" />
            <text y={14} textAnchor="middle" fontSize={9} fill="#9ca3af">
              {t.toFixed(2)}
            </text>
          </g>
        ))}
        {yTicks.map(t => (
          <g key={t} transform={`translate(0,${yS(t)})`}>
            <line x2={-4} stroke="#9ca3af" />
            <text x={-7} textAnchor="end" dominantBaseline="middle" fontSize={9} fill="#9ca3af">
              {t.toFixed(3)}
            </text>
          </g>
        ))}

        <text x={INNER_W / 2} y={INNER_H + 30} textAnchor="middle" fontSize={10} fill="#d1d5db">
          Wave frequency ω (rad/s)
        </text>
        <text
          x={-INNER_H / 2} y={-42}
          textAnchor="middle" fontSize={10} fill="#d1d5db"
          transform="rotate(-90)"
        >
          RAO amplitude
        </text>
      </g>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// SeakeepingRAOPanel
// ---------------------------------------------------------------------------

export default function SeakeepingRAOPanel({ result, statsResult, loading, error }) {
  const data = useMemo(() => {
    if (!result) return null
    // May come wrapped or unwrapped
    return result.rao_points ? result : (result.ok ? result : null)
  }, [result])

  const stats = useMemo(() => {
    if (!statsResult) return null
    return statsResult.motions ? statsResult : null
  }, [statsResult])

  if (loading) {
    return (
      <div className="p-4 rounded-lg bg-gray-900 border border-gray-700 text-gray-400 text-sm">
        Computing seakeeping RAOs...
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

  const raoPoints = data.rao_points ?? []
  if (raoPoints.length === 0) return null

  const omegas = raoPoints.map(p => p.omega_rad_s)
  const heaveAmps = raoPoints.map(p => p.rao_heave_amp)
  const pitchAmps = raoPoints.map(p => p.rao_pitch_amp)
  const rollAmps = raoPoints.map(p => p.rao_roll_amp)

  const maxHeave = Math.max(...heaveAmps).toFixed(3)
  const maxPitch = Math.max(...pitchAmps).toFixed(4)
  const maxRoll = Math.max(...rollAmps).toFixed(4)

  return (
    <div className="flex flex-col gap-4 p-4 rounded-lg bg-gray-900 border border-gray-700">
      <div className="text-sm font-semibold text-gray-200">
        Seakeeping RAOs — STF Strip Theory
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <SummaryCard label="Peak Heave" value={`${maxHeave} m/m`} color="text-emerald-300" borderColor="border-emerald-700" />
        <SummaryCard label="Peak Pitch" value={`${maxPitch} rad/m`} color="text-blue-300" borderColor="border-blue-700" />
        <SummaryCard label="Peak Roll" value={`${maxRoll} rad/m`} color="text-orange-300" borderColor="border-orange-700" />
      </div>

      {data.L_m && (
        <div className="text-xs text-gray-400">
          Hull length: {data.L_m} m, sections: {data.n_sections}
        </div>
      )}

      {/* RAO chart */}
      <div className="text-xs text-gray-400 font-medium mt-2">RAO vs Wave Frequency</div>
      <div className="overflow-x-auto">
        <RAOChart
          omegas={omegas}
          heaveAmps={heaveAmps}
          pitchAmps={pitchAmps}
          rollAmps={rollAmps}
        />
      </div>

      {/* Legend */}
      <div className="flex gap-4 text-xs text-gray-400">
        <span className="flex items-center gap-1">
          <span style={{ display: 'inline-block', width: 16, height: 2, background: RAO_COLORS.heave }} />
          Heave (m/m)
        </span>
        <span className="flex items-center gap-1">
          <span style={{ display: 'inline-block', width: 16, height: 2, background: RAO_COLORS.pitch }} />
          Pitch (rad/m)
        </span>
        <span className="flex items-center gap-1">
          <span style={{ display: 'inline-block', width: 16, height: 2, background: RAO_COLORS.roll }} />
          Roll (rad/m)
        </span>
      </div>

      {/* Irregular sea statistics */}
      {stats && stats.motions && (
        <>
          <div className="text-xs text-gray-400 font-medium mt-2">
            Irregular Sea Statistics (Hs={stats.Hs_input_m} m, Tp={stats.Tp_input_s} s, {stats.spectrum})
          </div>
          <div className="grid grid-cols-3 gap-3">
            {stats.motions.map(m => (
              <div key={m.motion} className="rounded p-2 border border-gray-700 bg-gray-800">
                <div className="text-xs text-gray-400 capitalize">{m.motion}</div>
                <div className="text-sm font-semibold text-gray-200">
                  sig: {m.significant_amplitude?.toFixed(4)}
                </div>
                <div className="text-xs text-gray-500">
                  MPM: {m.mpm_100_amplitude?.toFixed(4)}
                  {' '}Tz: {m.mean_zero_crossing_period_s?.toFixed(2)}s
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="text-xs text-gray-500 mt-1">
        Salvesen-Tuck-Faltinsen (1970) strip theory, Lewis-form sections,
        Froude-Krylov + Haskind excitation. Diffraction: Haskind relation (O(Fn) error).
      </div>
    </div>
  )
}

function SummaryCard({ label, value, color = 'text-gray-200', borderColor = 'border-gray-700' }) {
  return (
    <div className={`rounded p-2 border ${borderColor} bg-gray-800 text-center`}>
      <div className="text-xs text-gray-400">{label}</div>
      <div className={`text-sm font-semibold ${color}`}>{value}</div>
    </div>
  )
}
