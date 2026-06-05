// LCAResultsPanel.jsx — Full ISO 14040/44 LCA results UI
//
// Displays:
//   1. Impact-categories bar chart (gwp100, ap, ep, htp, water, pm25)
//      with ±90 % CI error bars (ISO 14044 §4.5 lognormal uncertainty)
//   2. Phase breakdown stacked bar (Phase 1 cradle-to-gate, Phase 2 use,
//      Phase 3 transport, Phase 4 EoL) — Module D shown separately per
//      EN 15978 §11.4
//   3. Circularity / Material breakdown table
//
// Props:
//   result  — output of the lca_report LLM tool (see kerf_lca/report.py)
//   lifecycle — output of lifecycle_phases tool (optional)
//   multi   — output of multi_impact tool (optional)
//   uncertainty — output of lca_impact_uncertainty_bounds tool (optional)
//   className — additional CSS classes

import { useState } from 'react'
import {
  BarChart2,
  ChevronDown,
  ChevronRight,
  Info,
  Leaf,
  RefreshCw,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const IMPACT_LABELS = {
  gwp100: { label: 'GWP100', unit: 'kg CO₂-eq', color: '#22c55e', method: 'IPCC AR6' },
  ap:     { label: 'Acidification', unit: 'kg SO₂-eq', color: '#f59e0b', method: 'CML 2002' },
  ep:     { label: 'Eutrophication', unit: 'kg PO₄-eq', color: '#3b82f6', method: 'CML 2002' },
  htp:    { label: 'Human Toxicity', unit: 'CTUh', color: '#ef4444', method: 'USEtox 2.1' },
  water:  { label: 'Water', unit: 'm³', color: '#06b6d4', method: 'Ecoinvent 3.9' },
  pm25:   { label: 'PM2.5', unit: 'kg PM2.5-eq', color: '#8b5cf6', method: 'ReCiPe 2016' },
}

const PHASE_COLORS = {
  cradle_to_gate: '#22c55e',
  use:            '#3b82f6',
  transport:      '#f59e0b',
  end_of_life:    '#8b5cf6',
  module_d:       '#06b6d4',
}

const PHASE_LABELS = {
  cradle_to_gate: 'Phase A1–A3 Cradle-to-gate',
  use:            'Phase B6 Use (operational energy)',
  transport:      'Phase A4/C2 Transport',
  end_of_life:    'Phase C3/C4 End-of-life',
  module_d:       'Module D Credit (EN 15978)',
}

// ---------------------------------------------------------------------------
// Helper: format a number with appropriate significant figures
// ---------------------------------------------------------------------------

function fmtNum(v, decimals = 4) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  if (Math.abs(n) < 1e-6) return n.toExponential(2)
  if (Math.abs(n) >= 1e6) return n.toExponential(3)
  return n.toFixed(decimals)
}

function fmtSci(v) {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  if (Math.abs(n) < 1e-3 || Math.abs(n) >= 1e4) return n.toExponential(3)
  return n.toPrecision(4)
}

// ---------------------------------------------------------------------------
// Sub-component: ImpactBar — single horizontal bar with optional CI
// ---------------------------------------------------------------------------

function ImpactBar({ label, unit, value, ciLow, ciHigh, maxValue, color }) {
  const pct = maxValue > 0 ? Math.max(0, Math.min(100, (value / maxValue) * 100)) : 0
  const ciLoPct = maxValue > 0 && ciLow !== undefined ? Math.max(0, (ciLow / maxValue) * 100) : null
  const ciHiPct = maxValue > 0 && ciHigh !== undefined ? Math.min(100, (ciHigh / maxValue) * 100) : null

  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="w-28 shrink-0 text-ink-300 truncate" title={label}>{label}</span>
      <div className="relative flex-1 h-4 bg-ink-800 rounded overflow-visible">
        {/* Main bar */}
        <div
          className="absolute inset-y-0 left-0 rounded transition-all duration-300"
          style={{ width: `${pct}%`, backgroundColor: color, opacity: 0.85 }}
        />
        {/* CI error bar */}
        {ciLoPct !== null && ciHiPct !== null && (
          <div
            className="absolute top-1 bottom-1 border border-ink-100/60 rounded-sm"
            style={{ left: `${ciLoPct}%`, width: `${ciHiPct - ciLoPct}%`, borderWidth: 1 }}
          />
        )}
      </div>
      <span className="w-24 shrink-0 text-right tabular-nums text-ink-200 font-mono">
        {fmtSci(value)} {unit}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-component: PhaseBreakdown
// ---------------------------------------------------------------------------

function PhaseBreakdown({ phases, total }) {
  if (!phases || phases.length === 0) return null

  const maxAbs = Math.max(...phases.map(p => Math.abs(p.gwp_kg_co2_eq || 0)), 0.001)

  return (
    <div className="space-y-1.5">
      {phases.map((phase) => {
        const v = phase.gwp_kg_co2_eq || 0
        const pct = Math.abs(v) / maxAbs * 100
        const color = PHASE_COLORS[phase.phase] || '#6b7280'
        const label = PHASE_LABELS[phase.phase] || phase.phase
        const isNeg = v < 0
        return (
          <div key={phase.phase} className="flex items-center gap-2 text-[11px]">
            <span className="w-48 shrink-0 text-ink-300 truncate" title={label}>{label}</span>
            <div className="relative flex-1 h-3.5 bg-ink-800 rounded overflow-hidden">
              <div
                className={['absolute inset-y-0 rounded transition-all', isNeg ? 'right-0' : 'left-0'].join(' ')}
                style={{
                  width: `${pct}%`,
                  backgroundColor: isNeg ? '#ef4444' : color,
                  opacity: 0.80,
                }}
              />
            </div>
            <span
              className={['w-24 shrink-0 text-right tabular-nums font-mono', isNeg ? 'text-red-300' : 'text-ink-200'].join(' ')}
            >
              {fmtNum(v, 3)} kg CO₂-eq
            </span>
          </div>
        )
      })}
      {total !== undefined && (
        <div className="flex items-center gap-2 text-[11px] border-t border-ink-700 pt-1.5 mt-1">
          <span className="w-48 shrink-0 font-medium text-ink-100">Total</span>
          <div className="flex-1" />
          <span className="w-24 shrink-0 text-right tabular-nums font-mono text-kerf-300 font-semibold">
            {fmtNum(total, 3)} kg CO₂-eq
          </span>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-component: MaterialTable
// ---------------------------------------------------------------------------

function MaterialTable({ byMaterial }) {
  if (!byMaterial || Object.keys(byMaterial).length === 0) return null
  const entries = Object.entries(byMaterial)
  const totalCarbon = entries.reduce((s, [, v]) => s + (v.total_carbon_kg_co2 || 0), 0)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[10px] text-ink-300">
        <thead>
          <tr className="border-b border-ink-700">
            <th className="text-left py-1 pr-2 font-medium text-ink-200">Material</th>
            <th className="text-right py-1 px-2 font-medium text-ink-200">Mass (kg)</th>
            <th className="text-right py-1 px-2 font-medium text-ink-200">CO₂-eq (kg)</th>
            <th className="text-right py-1 pl-2 font-medium text-ink-200">Share</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([mid, mat]) => {
            const share = totalCarbon > 0 ? (mat.total_carbon_kg_co2 / totalCarbon * 100) : 0
            return (
              <tr key={mid} className="border-b border-ink-800 hover:bg-ink-800/40 transition-colors">
                <td className="py-0.5 pr-2 font-mono">{mat.label || mid}</td>
                <td className="text-right py-0.5 px-2 tabular-nums">{fmtNum(mat.total_mass_kg, 2)}</td>
                <td className="text-right py-0.5 px-2 tabular-nums">{fmtNum(mat.total_carbon_kg_co2, 3)}</td>
                <td className="text-right py-0.5 pl-2 tabular-nums">{share.toFixed(1)}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-component: CircularityMeter
// ---------------------------------------------------------------------------

function CircularityMeter({ score }) {
  if (score === null || score === undefined) return null
  const pct = Math.max(0, Math.min(100, Number(score)))
  const color = pct >= 70 ? '#22c55e' : pct >= 40 ? '#f59e0b' : '#ef4444'
  const label = pct >= 70 ? 'High' : pct >= 40 ? 'Medium' : 'Low'

  return (
    <div className="flex items-center gap-3">
      <div className="relative w-10 h-10 shrink-0">
        <svg viewBox="0 0 40 40" className="w-10 h-10 -rotate-90">
          <circle cx="20" cy="20" r="16" strokeWidth="4" stroke="#1e293b" fill="none" />
          <circle
            cx="20" cy="20" r="16" strokeWidth="4"
            stroke={color} fill="none"
            strokeDasharray={`${pct} ${100 - pct}`}
            strokeDashoffset="0"
            pathLength="100"
            strokeLinecap="round"
          />
        </svg>
        <span
          className="absolute inset-0 flex items-center justify-center text-[9px] font-bold rotate-90"
          style={{ color }}
        >
          {pct.toFixed(0)}
        </span>
      </div>
      <div>
        <div className="text-[11px] font-medium text-ink-100">Circularity score: {pct.toFixed(1)} / 100</div>
        <div className="text-[10px] text-ink-400">{label} — weighted avg recycled content × recyclability</div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

/**
 * LCAResultsPanel — display full ISO 14040/44 LCA results.
 *
 * Props:
 *   result      — output of `lca_report` tool (required)
 *   lifecycle   — output of `lifecycle_phases` tool (optional)
 *   multi       — output of `multi_impact` tool (optional)
 *   uncertainty — output of `lca_impact_uncertainty_bounds` for GWP (optional)
 *   className   — additional CSS
 */
export function LCAResultsPanel({ result, lifecycle, multi, uncertainty, className = '' }) {
  const [showMaterials, setShowMaterials] = useState(false)
  const [showWarnings, setShowWarnings] = useState(false)

  if (!result) {
    return (
      <div className={['rounded-xl border border-ink-700 bg-ink-900 p-4 text-[11px] text-ink-400', className].join(' ')}>
        <div className="flex items-center gap-2">
          <Leaf size={14} className="text-kerf-300" />
          <span>No LCA result loaded. Run <code className="font-mono text-kerf-300">lca_report</code> to analyse embodied carbon.</span>
        </div>
      </div>
    )
  }

  const totalCarbon = result.total_carbon_kg_co2 ?? 0
  const circScore = result.circularity_score
  const warnings = [
    ...(result.warnings || []),
    ...(lifecycle?.warnings || []),
    ...(multi?.warnings || []),
  ]

  // Build impact data for chart
  const impactData = []
  if (multi?.impacts) {
    const maxImpact = Math.max(...Object.values(multi.impacts).map(v => Math.abs(Number(v)) || 0), 1e-12)
    for (const [cat, meta] of Object.entries(IMPACT_LABELS)) {
      const v = multi.impacts[cat]
      if (v === undefined || v === null) continue
      impactData.push({
        key: cat,
        label: meta.label,
        unit: meta.unit,
        color: meta.color,
        value: Number(v),
        maxValue: maxImpact,
        ciLow: null,
        ciHigh: null,
      })
    }
  } else {
    // Fall back: show only GWP from lca_report
    impactData.push({
      key: 'gwp100',
      label: 'GWP100',
      unit: 'kg CO₂-eq',
      color: IMPACT_LABELS.gwp100.color,
      value: totalCarbon,
      maxValue: totalCarbon,
      ciLow: uncertainty?.ci_low ?? null,
      ciHigh: uncertainty?.ci_high ?? null,
    })
  }

  return (
    <div className={['rounded-xl border border-ink-700 bg-ink-900 overflow-hidden', className].join(' ')}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-ink-800 flex items-center gap-2">
        <Leaf size={14} className="text-kerf-300 shrink-0" />
        <h3 className="font-display font-semibold text-sm text-ink-100 tracking-tight">
          LCA Results — ISO 14040/44
        </h3>
        {uncertainty && (
          <span className="ml-auto text-[9px] bg-ink-800 border border-ink-700 rounded px-1.5 py-0.5 text-ink-400">
            ±90% CI (ISO 14044 §4.5)
          </span>
        )}
      </div>

      <div className="p-4 space-y-5">
        {/* Total embodied carbon + circularity */}
        <div className="flex items-start gap-4">
          <div>
            <div className="text-[10px] text-ink-400 uppercase tracking-wide">Total embodied carbon</div>
            <div className="text-2xl font-bold text-kerf-300 tabular-nums">
              {fmtNum(totalCarbon, 2)}
            </div>
            <div className="text-[10px] text-ink-400">kg CO₂-eq (cradle-to-gate)</div>
          </div>
          {circScore !== undefined && circScore !== null && (
            <div className="ml-auto">
              <CircularityMeter score={circScore} />
            </div>
          )}
        </div>

        {/* Impact categories chart */}
        {impactData.length > 0 && (
          <section>
            <h4 className="text-[10px] text-ink-400 uppercase tracking-wide mb-2 flex items-center gap-1">
              <BarChart2 size={11} />
              Impact categories
            </h4>
            <div className="space-y-1.5">
              {impactData.map(d => (
                <ImpactBar
                  key={d.key}
                  label={d.label}
                  unit={d.unit}
                  value={d.value}
                  ciLow={d.ciLow}
                  ciHigh={d.ciHigh}
                  maxValue={d.maxValue}
                  color={d.color}
                />
              ))}
            </div>
            {multi?.methods && (
              <div className="mt-1.5 text-[9px] text-ink-500 italic">
                Methods: {Object.entries(IMPACT_LABELS)
                  .filter(([k]) => multi.impacts?.[k] !== undefined)
                  .map(([, v]) => v.method)
                  .filter((v, i, arr) => arr.indexOf(v) === i)
                  .join(' · ')}
              </div>
            )}
          </section>
        )}

        {/* Phase breakdown */}
        {lifecycle?.phases && lifecycle.phases.length > 0 && (
          <section>
            <h4 className="text-[10px] text-ink-400 uppercase tracking-wide mb-2">
              Lifecycle phase breakdown
            </h4>
            <PhaseBreakdown
              phases={lifecycle.phases}
              total={lifecycle.total_gwp_kg_co2_eq}
            />
            {lifecycle.functional_unit && (
              <div className="mt-1 text-[9px] text-ink-500 italic">
                Functional unit: {lifecycle.functional_unit}
              </div>
            )}
          </section>
        )}

        {/* Material table (collapsible) */}
        {result.by_material && Object.keys(result.by_material).length > 0 && (
          <section>
            <button
              type="button"
              onClick={() => setShowMaterials(v => !v)}
              className="flex items-center gap-1.5 text-[10px] text-ink-400 uppercase tracking-wide hover:text-ink-200 transition-colors"
            >
              {showMaterials ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
              Material breakdown
              <span className="text-ink-600">({Object.keys(result.by_material).length} materials)</span>
            </button>
            {showMaterials && (
              <div className="mt-2">
                <MaterialTable byMaterial={result.by_material} />
              </div>
            )}
          </section>
        )}

        {/* Warnings */}
        {warnings.length > 0 && (
          <section>
            <button
              type="button"
              onClick={() => setShowWarnings(v => !v)}
              className="flex items-center gap-1.5 text-[10px] text-amber-400 hover:text-amber-300 transition-colors"
            >
              <Info size={11} />
              {warnings.length} warning{warnings.length !== 1 ? 's' : ''}
              {showWarnings ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            </button>
            {showWarnings && (
              <ul className="mt-1.5 space-y-0.5 text-[10px] text-amber-300/80 list-disc list-inside">
                {warnings.slice(0, 10).map((w, i) => (
                  <li key={i} className="truncate" title={w}>{w}</li>
                ))}
                {warnings.length > 10 && (
                  <li className="opacity-60">…and {warnings.length - 10} more</li>
                )}
              </ul>
            )}
          </section>
        )}

        {/* Citation footer */}
        <div className="text-[9px] text-ink-600 border-t border-ink-800 pt-2">
          Data: ICE v3.0 (Hammond &amp; Jones, Univ. of Bath, 2019) · ISO 14040/44:2006 · EN 15978:2011 ·
          NOT Ecoinvent (license-restricted) · Design-stage estimates only
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Compact inline badge (for BOM rows etc.)
// ---------------------------------------------------------------------------

/**
 * LCABadge — compact single-number carbon badge for inline use.
 *
 * Props:
 *   totalCarbonKgCo2 — number
 *   circularity      — 0-100 circularity score (optional)
 */
export function LCABadge({ totalCarbonKgCo2, circularity }) {
  const v = Number(totalCarbonKgCo2)
  const color = v < 1 ? 'text-emerald-400' : v < 10 ? 'text-amber-400' : 'text-red-400'

  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-mono">
      <Leaf size={10} className="text-kerf-300" />
      <span className={color}>{fmtSci(v)} kg CO₂-eq</span>
      {circularity !== undefined && (
        <span className="text-ink-500">· {Number(circularity).toFixed(0)}% circ.</span>
      )}
    </span>
  )
}

export default LCAResultsPanel
