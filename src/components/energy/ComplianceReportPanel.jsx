// ComplianceReportPanel.jsx — ASHRAE 90.1 Appendix G + LEED EAp2 + Title 24
// compliance report panel.
//
// Displays:
//   • Baseline vs. proposed end-use bar chart (heating/cooling/fan/lighting)
//   • Performance Cost Index (PCI) gauge
//   • % better than 90.1 baseline
//   • LEED v4.1 EAp2/EAc2 points (0–18)
//   • ASHRAE 90.1 and Title 24 pass/fail badges
//   • Recommendations list
//   • Honest caveat
//
// Props: { report: object }  — from energy_ashrae901_appendixg_report tool result
//
// NOTE: This panel is read-only (displays pre-computed results). It does NOT
// make live API calls — the parent passes the report object from the LLM tool.

import { useMemo } from 'react'
import {
  Building2, CheckCircle, XCircle, Award, Zap, Thermometer,
  Wind, Lightbulb, AlertTriangle, Info, TrendingDown, TrendingUp,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Colours
// ---------------------------------------------------------------------------
const END_USE_COLORS = {
  heating:  '#ef4444',   // red
  cooling:  '#3b82f6',   // blue
  fan_kwh:  '#8b5cf6',   // violet
  lighting: '#f59e0b',   // amber
}
const END_USE_LABELS = {
  heating:  'Heating',
  cooling:  'Cooling',
  fan_kwh:  'HVAC Fans',
  lighting: 'Lighting',
}
const END_USE_ICONS = {
  heating:  Thermometer,
  cooling:  Wind,
  fan_kwh:  Wind,
  lighting: Lightbulb,
}

// ---------------------------------------------------------------------------
// Helper: format numbers
// ---------------------------------------------------------------------------
function fmt0(n) { return n == null ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: 0 }) }
function fmt1(n) { return n == null ? '—' : n.toFixed(1) }
function fmt3(n) { return n == null ? '—' : n.toFixed(3) }
function fmtPct(n) { return n == null ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(1)}%` }

// ---------------------------------------------------------------------------
// PCI Gauge
// ---------------------------------------------------------------------------
function PCIGauge({ pci }) {
  // Semicircle SVG gauge: 0 = far left (bad), 1 = centre (baseline), 2 = far right (worse)
  // Visual range: 0.5 – 1.5 pci
  const minVal = 0.5
  const maxVal = 1.5
  const clampedPci = Math.max(minVal, Math.min(maxVal, pci))
  const frac = (clampedPci - minVal) / (maxVal - minVal)  // 0=left, 1=right
  const angleDeg = frac * 180 - 90  // -90° (left) to +90° (right)
  const rad = (angleDeg * Math.PI) / 180
  const cx = 100, cy = 100, r = 75
  const nx = cx + r * Math.sin(rad)
  const ny = cy - r * Math.cos(rad)

  const good = pci < 1.0
  const color = good ? '#22c55e' : '#ef4444'

  return (
    <div className="flex flex-col items-center">
      <svg width="200" height="120" viewBox="0 0 200 120">
        {/* Background arc */}
        <path
          d="M 25 100 A 75 75 0 0 1 175 100"
          fill="none" stroke="#e5e7eb" strokeWidth="16" strokeLinecap="round"
        />
        {/* Green zone: left half (< 1.0) */}
        <path
          d="M 25 100 A 75 75 0 0 1 100 25"
          fill="none" stroke="#bbf7d0" strokeWidth="16" strokeLinecap="round"
        />
        {/* Red zone: right half (> 1.0) */}
        <path
          d="M 100 25 A 75 75 0 0 1 175 100"
          fill="none" stroke="#fecaca" strokeWidth="16" strokeLinecap="round"
        />
        {/* Needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny}
          stroke={color} strokeWidth="3" strokeLinecap="round" />
        <circle cx={cx} cy={cy} r="5" fill={color} />
        {/* Labels */}
        <text x="20" y="116" fontSize="10" fill="#6b7280">0.5</text>
        <text x="95" y="18" fontSize="10" fill="#6b7280">1.0</text>
        <text x="166" y="116" fontSize="10" fill="#6b7280">1.5</text>
        {/* PCI value */}
        <text x={cx} y={cy + 30} textAnchor="middle" fontSize="20" fontWeight="bold"
          fill={color}>{fmt3(pci)}</text>
        <text x={cx} y={cy + 45} textAnchor="middle" fontSize="10" fill="#6b7280">PCI</text>
      </svg>
    </div>
  )
}

// ---------------------------------------------------------------------------
// End-use bar chart
// ---------------------------------------------------------------------------
function EndUseBar({ label, baselineKwh, proposedKwh, maxKwh, color, Icon }) {
  const bWidth = maxKwh > 0 ? (baselineKwh / maxKwh) * 100 : 0
  const pWidth = maxKwh > 0 ? (proposedKwh / maxKwh) * 100 : 0
  const delta = proposedKwh - baselineKwh
  const deltaColor = delta < 0 ? '#22c55e' : delta > 0 ? '#ef4444' : '#6b7280'
  return (
    <div className="mb-3">
      <div className="flex items-center justify-between mb-1 text-xs">
        <div className="flex items-center gap-1 text-gray-600 font-medium w-24">
          {Icon && <Icon size={12} className="shrink-0" />}
          <span>{label}</span>
        </div>
        <div className="flex gap-4 text-gray-500">
          <span className="w-20 text-right">{fmt0(baselineKwh)}</span>
          <span className="w-20 text-right">{fmt0(proposedKwh)}</span>
          <span className="w-20 text-right" style={{ color: deltaColor }}>
            {delta >= 0 ? '+' : ''}{fmt0(delta)}
          </span>
        </div>
      </div>
      <div className="space-y-1">
        {/* Baseline bar */}
        <div className="flex items-center gap-2">
          <span className="w-12 text-right text-xs text-gray-400">Baseline</span>
          <div className="flex-1 h-3 bg-gray-100 rounded">
            <div
              className="h-3 rounded"
              style={{ width: `${bWidth}%`, backgroundColor: color, opacity: 0.4 }}
            />
          </div>
        </div>
        {/* Proposed bar */}
        <div className="flex items-center gap-2">
          <span className="w-12 text-right text-xs text-gray-400">Proposed</span>
          <div className="flex-1 h-3 bg-gray-100 rounded">
            <div
              className="h-3 rounded"
              style={{ width: `${pWidth}%`, backgroundColor: color }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------
function Badge({ pass, label, sub }) {
  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${
      pass
        ? 'bg-green-50 border-green-200'
        : 'bg-red-50 border-red-200'
    }`}>
      {pass
        ? <CheckCircle size={18} className="text-green-600 shrink-0" />
        : <XCircle size={18} className="text-red-500 shrink-0" />}
      <div>
        <div className={`text-sm font-semibold ${pass ? 'text-green-700' : 'text-red-600'}`}>
          {label}
        </div>
        {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// LEED points display
// ---------------------------------------------------------------------------
function LeedPoints({ points, prereqMet }) {
  const maxPoints = 18
  return (
    <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
      <div className="flex items-center gap-2 mb-2">
        <Award size={16} className="text-amber-500" />
        <span className="text-sm font-semibold text-gray-700">LEED v4.1 EAp2 / EAc2</span>
      </div>
      {!prereqMet && (
        <div className="text-xs text-red-600 mb-2 flex items-center gap-1">
          <AlertTriangle size={12} />
          EAp2 Prerequisite NOT met (requires ≥5% savings)
        </div>
      )}
      {prereqMet && (
        <div className="text-xs text-green-600 mb-2 flex items-center gap-1">
          <CheckCircle size={12} />
          EAp2 Prerequisite met
        </div>
      )}
      <div className="flex items-end gap-2 mb-2">
        <span className="text-3xl font-bold text-amber-600">{points}</span>
        <span className="text-gray-400 text-sm mb-1">/ {maxPoints} EAc2 pts</span>
      </div>
      {/* Point bar */}
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-2 rounded-full transition-all"
          style={{
            width: `${(points / maxPoints) * 100}%`,
            backgroundColor: points >= 8 ? '#22c55e' : points >= 4 ? '#f59e0b' : '#ef4444',
          }}
        />
      </div>
      <div className="flex justify-between text-xs text-gray-400 mt-1">
        <span>0</span>
        <span>9</span>
        <span>18</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------
export default function ComplianceReportPanel({ report }) {
  const b = report?.baseline_end_use
  const p = report?.proposed_end_use

  const endUseKeys = ['heating', 'cooling', 'fan_kwh', 'lighting']

  const maxKwh = useMemo(() => {
    if (!b || !p) return 1
    const vals = endUseKeys.flatMap(k => [
      b[`${k}_kwh`] ?? b[k] ?? 0,
      p[`${k}_kwh`] ?? p[k] ?? 0,
    ])
    return Math.max(...vals, 1)
  }, [b, p])

  if (!report) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400 text-sm">
        <Building2 size={20} className="mr-2" />
        No compliance report available. Run energy_ashrae901_appendixg_report.
      </div>
    )
  }

  const pci = report.performance_cost_index
  const pctBetter = report.pct_better_than_baseline
  const ashraePasses = report.ashrae_901_compliant
  const leedPrereq = report.leed_eap2_prerequisite_met
  const leedPts = report.leed_eac2_points
  const t24Compliant = report.title24_compliant
  const t24Margin = report.title24_margin_pct

  return (
    <div className="p-4 space-y-5 text-sm max-w-3xl">
      {/* Header */}
      <div className="flex items-center gap-2 pb-2 border-b border-gray-200">
        <Building2 size={18} className="text-blue-600 shrink-0" />
        <div>
          <h2 className="font-semibold text-gray-800 text-base">
            ASHRAE 90.1 Appendix G Compliance Report
          </h2>
          <p className="text-xs text-gray-500">
            Baseline: System {report.baseline_system_number} — {report.baseline_system_name}
          </p>
        </div>
      </div>

      {/* PCI gauge + % better */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-3">
          <div className="text-xs font-medium text-gray-600 mb-1 flex items-center gap-1">
            <Zap size={12} />
            Performance Cost Index
          </div>
          <PCIGauge pci={pci} />
          <div className="text-center mt-1">
            <span className={`text-xs font-semibold ${pci < 1.0 ? 'text-green-600' : 'text-red-600'}`}>
              {pci < 1.0 ? 'Better than baseline' : 'Worse than baseline'}
            </span>
          </div>
        </div>

        <div className="space-y-3">
          <div className="bg-white border border-gray-200 rounded-lg p-3">
            <div className="text-xs text-gray-500 mb-1">% Better than 90.1 Baseline</div>
            <div className="flex items-center gap-2">
              {pctBetter > 0
                ? <TrendingDown size={20} className="text-green-500" />
                : <TrendingUp size={20} className="text-red-500" />}
              <span className={`text-2xl font-bold ${pctBetter > 0 ? 'text-green-600' : 'text-red-600'}`}>
                {fmtPct(pctBetter)}
              </span>
            </div>
            <div className="text-xs text-gray-400 mt-1">
              EUI: Baseline {fmt1(b?.eui_kwh_m2_yr)} → Proposed {fmt1(p?.eui_kwh_m2_yr)} kWh/(m²·yr)
            </div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-xs text-gray-600">
            <div className="mb-1 font-medium">Annual Energy Cost</div>
            <div>Baseline: <span className="font-mono">${fmt0(report.baseline_annual_cost_usd)}</span></div>
            <div>Proposed: <span className="font-mono">${fmt0(report.proposed_annual_cost_usd)}</span></div>
            <div className={`mt-1 font-medium ${pci < 1.0 ? 'text-green-600' : 'text-red-600'}`}>
              Savings: ${fmt0(report.baseline_annual_cost_usd - report.proposed_annual_cost_usd)}/yr
            </div>
          </div>
        </div>
      </div>

      {/* End-use bars */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h3 className="text-xs font-semibold text-gray-700 mb-3 uppercase tracking-wide">
          Annual End-Use Comparison (kWh/yr)
        </h3>
        <div className="flex justify-end text-xs text-gray-400 mb-2 gap-4">
          <span className="w-20 text-right">Baseline</span>
          <span className="w-20 text-right">Proposed</span>
          <span className="w-20 text-right">Delta</span>
        </div>
        {endUseKeys.map(k => {
          const bVal = b?.[`${k}_kwh`] ?? b?.[k] ?? 0
          const pVal = p?.[`${k}_kwh`] ?? p?.[k] ?? 0
          const Icon = END_USE_ICONS[k]
          return (
            <EndUseBar
              key={k}
              label={END_USE_LABELS[k]}
              baselineKwh={bVal}
              proposedKwh={pVal}
              maxKwh={maxKwh}
              color={END_USE_COLORS[k]}
              Icon={Icon}
            />
          )
        })}
      </div>

      {/* Compliance badges */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Badge
          pass={ashraePasses}
          label={`ASHRAE 90.1 ${ashraePasses ? 'COMPLIANT' : 'NON-COMPLIANT'}`}
          sub={`PCI = ${fmt3(pci)}`}
        />
        {t24Compliant != null && (
          <Badge
            pass={t24Compliant}
            label={`Title 24 ${t24Compliant ? 'PASS' : 'FAIL'}`}
            sub={`Margin: ${fmtPct(t24Margin)}`}
          />
        )}
        <Badge
          pass={leedPrereq}
          label={`LEED EAp2 ${leedPrereq ? 'MET' : 'NOT MET'}`}
          sub="≥5% savings required"
        />
      </div>

      {/* LEED points */}
      <LeedPoints points={leedPts} prereqMet={leedPrereq} />

      {/* Recommendations */}
      {report.recommendations?.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle size={14} className="text-amber-600" />
            <span className="text-xs font-semibold text-amber-700 uppercase tracking-wide">
              Recommendations
            </span>
          </div>
          <ul className="space-y-1.5">
            {report.recommendations.map((rec, i) => (
              <li key={i} className="text-xs text-amber-800 flex items-start gap-1.5">
                <span className="shrink-0 font-bold mt-0.5">{i + 1}.</span>
                <span>{rec}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Honest caveat */}
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
        <div className="flex items-start gap-2">
          <Info size={13} className="text-gray-400 shrink-0 mt-0.5" />
          <p className="text-xs text-gray-500 leading-relaxed">
            {report.honest_caveat}
          </p>
        </div>
      </div>
    </div>
  )
}
