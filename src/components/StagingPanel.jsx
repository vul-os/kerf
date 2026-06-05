// StagingPanel.jsx — Multi-stage rocket staging / Tsiolkovsky ΔV panel.
//
// Renders output from aero_staging tool:
//   - Total ΔV, payload fraction, total wet mass summary
//   - Per-stage breakdown table (ΔV, mass ratio, mass flow)
//   - ΔV bar chart per stage
//
// Props
// ─────
//   result  {Object|null}  — parsed JSON from aero_staging
//   loading {boolean}
//   error   {string|null}

import { useMemo } from 'react'

const STAGE_COLORS = ['#60a5fa', '#34d399', '#f97316', '#a78bfa', '#fb923c']

// ---------------------------------------------------------------------------
// Bar chart
// ---------------------------------------------------------------------------

function DvBarChart({ stages }) {
  if (!stages || stages.length === 0) return null

  const dvs = stages.map(s => s.delta_v_ms ?? s.delta_v_kms * 1000 ?? 0)
  const maxDv = Math.max(...dvs, 1)
  const barH = 28
  const barGap = 8
  const labelW = 80
  const barAreaW = 260
  const svgW = labelW + barAreaW + 60
  const svgH = stages.length * (barH + barGap) + 20

  return (
    <svg width={svgW} height={svgH} viewBox={`0 0 ${svgW} ${svgH}`}>
      {stages.map((s, i) => {
        const dv = dvs[i]
        const barLen = (dv / maxDv) * barAreaW
        const y = 10 + i * (barH + barGap)
        const color = STAGE_COLORS[i % STAGE_COLORS.length]
        return (
          <g key={i}>
            <text x={0} y={y + barH / 2 + 4} fontSize={11} fill="#9ca3af">
              {s.stage ?? `Stage ${i + 1}`}
            </text>
            <rect x={labelW} y={y} width={barLen} height={barH} rx={3} fill={color} opacity={0.8} />
            <text x={labelW + barLen + 6} y={y + barH / 2 + 4} fontSize={11} fill="#e5e7eb">
              {(dv / 1000).toFixed(2)} km/s
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Stage table
// ---------------------------------------------------------------------------

function StageTable({ stages }) {
  if (!stages || stages.length === 0) return null

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs text-gray-300 border-collapse">
        <thead>
          <tr className="text-gray-500 border-b border-gray-700">
            <th className="text-left py-1 pr-3">Stage</th>
            <th className="text-right py-1 pr-3">ΔV (m/s)</th>
            <th className="text-right py-1 pr-3">Isp (s)</th>
            <th className="text-right py-1 pr-3">MR</th>
            <th className="text-right py-1 pr-3">m₀ (kg)</th>
            <th className="text-right py-1">mf (kg)</th>
          </tr>
        </thead>
        <tbody>
          {stages.map((s, i) => (
            <tr key={i} className="border-b border-gray-800">
              <td className="py-1 pr-3 font-medium" style={{ color: STAGE_COLORS[i % STAGE_COLORS.length] }}>
                {s.stage ?? `Stage ${i + 1}`}
              </td>
              <td className="text-right py-1 pr-3">
                {(s.delta_v_ms ?? (s.delta_v_kms * 1000))?.toFixed(1) ?? '—'}
              </td>
              <td className="text-right py-1 pr-3">{s.isp?.toFixed(1) ?? '—'}</td>
              <td className="text-right py-1 pr-3">{s.mass_ratio?.toFixed(3) ?? '—'}</td>
              <td className="text-right py-1 pr-3">{s.m0?.toFixed(1) ?? '—'}</td>
              <td className="text-right py-1">{s.mf?.toFixed(1) ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// StagingPanel
// ---------------------------------------------------------------------------

export default function StagingPanel({ result, loading, error, content }) {
  // Backward-compatible content string: JSON.parse it and merge into result.
  if (content != null && result == null) {
    try { result = JSON.parse(content) } catch { /* ignore */ }
  }
  const data = useMemo(() => {
    if (!result || !result.ok) return null
    return result
  }, [result])

  if (loading) {
    return (
      <div className="p-4 rounded-lg bg-gray-900 border border-gray-700 text-gray-400 text-sm">
        Computing staging analysis...
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
    total_delta_v_m_s,
    total_delta_v_km_s,
    n_stages,
    payload_fraction,
    total_wet_mass_kg,
    stage_results,
    mode,
    equal_split,
  } = data

  return (
    <div className="flex flex-col gap-4 p-4 rounded-lg bg-gray-900 border border-gray-700">
      <div className="text-sm font-semibold text-gray-200">
        Multi-Stage Rocket — Tsiolkovsky ΔV
        {mode === 'optimal_split' && ' (Optimal Split)'}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryCard label="Total ΔV" value={`${total_delta_v_km_s?.toFixed(3) ?? '—'} km/s`} highlight />
        <SummaryCard label="Stages" value={n_stages ?? '—'} />
        {payload_fraction != null && (
          <SummaryCard label="Payload Fraction" value={`${(payload_fraction * 100).toFixed(2)}%`} />
        )}
        {total_wet_mass_kg != null && (
          <SummaryCard label="Total Wet Mass" value={`${total_wet_mass_kg?.toFixed(1) ?? '—'} kg`} />
        )}
      </div>

      {equal_split && (
        <div className="text-xs text-emerald-400">
          Equal ΔV split per stage is optimal for identical Isp / structural fraction.
        </div>
      )}

      {/* Bar chart */}
      {stage_results && stage_results.length > 0 && (
        <>
          <div className="text-xs text-gray-400 font-medium mt-2">ΔV per Stage</div>
          <div className="overflow-x-auto">
            <DvBarChart stages={stage_results} />
          </div>
        </>
      )}

      {/* Table */}
      {stage_results && stage_results.length > 0 && (
        <>
          <div className="text-xs text-gray-400 font-medium mt-1">Stage Breakdown</div>
          <StageTable stages={stage_results} />
        </>
      )}

      <div className="text-xs text-gray-500 mt-1">
        ΔV = Isp · g₀ · ln(m₀/mf). Ref: Sutton &amp; Biblarz RPE 9th ed. §4.
      </div>
    </div>
  )
}

function SummaryCard({ label, value, highlight }) {
  return (
    <div className={`rounded p-2 border text-center ${
      highlight ? 'border-emerald-600 bg-emerald-950' : 'border-gray-700 bg-gray-800'
    }`}>
      <div className="text-xs text-gray-400">{label}</div>
      <div className={`text-sm font-semibold ${highlight ? 'text-emerald-300' : 'text-gray-200'}`}>
        {value}
      </div>
    </div>
  )
}
