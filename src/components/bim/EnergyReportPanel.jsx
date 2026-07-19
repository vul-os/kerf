/**
 * EnergyReportPanel — EcoDesigner: building energy evaluation + ASHRAE 90.1
 * compliance report UI.
 *
 * Five tabs:
 *   Building Setup  — type, floor area, climate zone, wall/roof/window U-values
 *   HVAC + Lighting — system type, LPD, plug loads
 *   Annual Sim      — Run 8760-hour simulation, progress, EUI, energy breakdown
 *   Compliance      — ASHRAE 90.1 PASS/FAIL banner, baseline comparison, LEED
 *   Export          — PDF report button, recommendations list
 *
 * The actual simulation is done server-side via the
 * `bim_compute_energy_compliance_report` LLM tool (kerf-cad-core).
 * In standalone / demo mode this component calls the Kerf API directly via
 * POST to a project tool endpoint.  When embedded in the Editor, the caller
 * can also pass `onRunSim(params)` as a prop to route through the chat agent.
 *
 * Props:
 *   projectId   {string}  Optional — used for API calls
 *   onClose     {fn}      Optional — close handler
 *   embedded    {bool}    If true, renders without outer card chrome
 */

import { useState, useCallback, useRef } from 'react'
import {
  Building2,
  Thermometer,
  Play,
  BarChart3,
  FileDown,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
  Info,
  Zap,
  Wind,
  Sun,
  Lightbulb,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BUILDING_TYPES = [
  { value: 'office',      label: 'Office' },
  { value: 'residential', label: 'Residential' },
  { value: 'retail',      label: 'Retail' },
  { value: 'warehouse',   label: 'Warehouse' },
  { value: 'hospital',    label: 'Hospital' },
  { value: 'education',   label: 'Education / School' },
]

const CLIMATE_ZONES = [
  { value: '1A', label: '1A — Very Hot, Humid (Miami)' },
  { value: '1B', label: '1B — Very Hot, Dry (Arabian Gulf)' },
  { value: '2A', label: '2A — Hot, Humid (Houston)' },
  { value: '2B', label: '2B — Hot, Dry (Phoenix)' },
  { value: '3A', label: '3A — Warm, Humid (Atlanta)' },
  { value: '3B', label: '3B — Warm, Dry (Las Vegas)' },
  { value: '3C', label: '3C — Warm, Marine (San Francisco)' },
  { value: '4A', label: '4A — Mixed, Humid (Baltimore)' },
  { value: '4B', label: '4B — Mixed, Dry (Albuquerque)' },
  { value: '4C', label: '4C — Mixed, Marine (Seattle)' },
  { value: '5A', label: '5A — Cool, Humid (Chicago)' },
  { value: '5B', label: '5B — Cool, Dry (Denver)' },
  { value: '5C', label: '5C — Cool, Marine (Vancouver)' },
  { value: '6A', label: '6A — Cold, Humid (Minneapolis)' },
  { value: '6B', label: '6B — Cold, Dry (Helena)' },
  { value: '7',  label: '7 — Very Cold (Duluth)' },
  { value: '8',  label: '8 — Subarctic (Fairbanks)' },
]

const HVAC_TYPES = [
  { value: 'VAV',     label: 'VAV — Variable Air Volume (gas + chiller)' },
  { value: 'PTHP',   label: 'PTHP — Packaged Terminal Heat Pump' },
  { value: 'CRAC',   label: 'CRAC — Computer Room AC (data centres)' },
  { value: 'chiller',label: 'Chiller — Central chilled water + gas boiler' },
]

const TABS = [
  { id: 'setup',      label: 'Building Setup', icon: Building2 },
  { id: 'hvac',       label: 'HVAC + Lighting', icon: Thermometer },
  { id: 'sim',        label: 'Annual Sim', icon: Play },
  { id: 'report',     label: 'Compliance Report', icon: BarChart3 },
  { id: 'export',     label: 'Export', icon: FileDown },
]

// Default wall / roof / window assemblies
const DEFAULT_STATE = {
  building_type: 'office',
  floor_area_m2: '1000',
  climate_zone: '4A',
  // wall assemblies: simplified to 4 cardinal directions
  wall_N_U: '0.35',
  wall_N_area: '200',
  wall_S_U: '0.35',
  wall_S_area: '200',
  wall_E_U: '0.35',
  wall_E_area: '150',
  wall_W_U: '0.35',
  wall_W_area: '150',
  // roof
  roof_U: '0.20',
  roof_area: '1000',
  // windows
  win_U: '2.00',
  win_area: '160',
  win_SHGC: '0.40',
  // HVAC + lighting
  hvac_system_type: 'VAV',
  lighting_W_m2: '10',
  plug_W_m2: '12',
  annual_run_hours: '8760',
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function num(v, fallback = 0) {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : fallback
}

function fmtNum(v, dec = 1) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return Number(v).toFixed(dec)
}

function fmtKWh(v) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  const n = Number(v)
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} GWh`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)} MWh`
  return `${n.toFixed(0)} kWh`
}

function EnergyBar({ label, kWh, total, color, icon: Icon }) {
  const pct = total > 0 ? Math.min(100, (kWh / total) * 100) : 0
  return (
    <div className="flex items-center gap-2 text-[11px]">
      {Icon && <Icon size={12} className="text-ink-500 flex-shrink-0" />}
      <span className="w-24 text-ink-400 truncate">{label}</span>
      <div className="flex-1 h-2 bg-ink-800 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="w-16 text-right font-mono text-ink-300">{fmtKWh(kWh)}</span>
      <span className="w-10 text-right text-ink-500">{pct.toFixed(0)}%</span>
    </div>
  )
}

function LeedBadge({ credits }) {
  if (credits <= 0) return (
    <span className="px-2 py-0.5 rounded bg-ink-800 text-ink-400 text-[10px] font-medium">0 credits</span>
  )
  const color = credits >= 14 ? '#10b981' : credits >= 8 ? '#3b82f6' : '#f59e0b'
  return (
    <span
      className="px-2 py-0.5 rounded text-[10px] font-medium text-white"
      style={{ backgroundColor: color }}
    >
      {credits} LEED credit{credits !== 1 ? 's' : ''}
    </span>
  )
}

function ComplianceBanner({ compliant, eui, baseline, pct }) {
  if (compliant == null) return null
  return (
    <div
      className={`rounded-lg p-4 flex items-start gap-3 ${
        compliant
          ? 'bg-emerald-900/30 border border-emerald-700/40'
          : 'bg-red-900/30 border border-red-700/40'
      }`}
    >
      {compliant
        ? <CheckCircle2 size={20} className="text-emerald-400 flex-shrink-0 mt-0.5" />
        : <XCircle size={20} className="text-red-400 flex-shrink-0 mt-0.5" />
      }
      <div>
        <div className={`font-semibold text-sm ${compliant ? 'text-emerald-300' : 'text-red-300'}`}>
          ASHRAE 90.1-2022 — {compliant ? 'PASS' : 'FAIL'}
        </div>
        <div className="text-[12px] text-ink-300 mt-0.5">
          Proposed EUI: <span className="font-mono font-medium text-white">{fmtNum(eui, 1)} kWh/(m²·yr)</span>
          {' '}vs baseline <span className="font-mono font-medium text-white">{fmtNum(baseline, 1)} kWh/(m²·yr)</span>
          {' '}
          <span className={pct >= 0 ? 'text-emerald-400' : 'text-red-400'}>
            ({pct >= 0 ? '+' : ''}{fmtNum(pct, 1)}% {pct >= 0 ? 'better' : 'worse'} than baseline)
          </span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Input components
// ---------------------------------------------------------------------------

function Field({ label, unit, value, onChange, type = 'number', min, step = '0.01', children, help }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1">
        <label className="text-[11px] text-ink-400">{label}</label>
        {help && (
          <span className="text-ink-600 cursor-help group relative" title={help}>
            <Info size={10} />
          </span>
        )}
      </div>
      {children || (
        <div className="flex items-center gap-1">
          <input
            type={type}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            min={min}
            step={step}
            className="flex-1 bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[12px] text-ink-100 font-mono focus:outline-none focus:border-kerf-500"
          />
          {unit && <span className="text-[10px] text-ink-500 whitespace-nowrap">{unit}</span>}
        </div>
      )}
    </div>
  )
}

function Select({ label, value, onChange, options, help }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1">
        <label className="text-[11px] text-ink-400">{label}</label>
        {help && <span className="text-ink-600 cursor-help" title={help}><Info size={10} /></span>}
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[12px] text-ink-100 focus:outline-none focus:border-kerf-500"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

function WallRow({ label, U, area, onU, onArea }) {
  return (
    <div className="grid grid-cols-3 gap-2 items-center">
      <span className="text-[11px] text-ink-400">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number" value={U} onChange={(e) => onU(e.target.value)}
          min="0.01" step="0.01"
          className="flex-1 bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[12px] text-ink-100 font-mono focus:outline-none focus:border-kerf-500"
        />
        <span className="text-[10px] text-ink-500">W/m²K</span>
      </div>
      <div className="flex items-center gap-1">
        <input
          type="number" value={area} onChange={(e) => onArea(e.target.value)}
          min="0" step="1"
          className="flex-1 bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[12px] text-ink-100 font-mono focus:outline-none focus:border-kerf-500"
        />
        <span className="text-[10px] text-ink-500">m²</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function EnergyReportPanel({ projectId, onClose, embedded = false }) {
  const [tab, setTab] = useState('setup')
  const [form, setForm] = useState(DEFAULT_STATE)
  const [simState, setSimState] = useState('idle') // idle | running | done | error
  const [simProgress, setSimProgress] = useState(0)
  const [report, setReport] = useState(null)
  const [simError, setSimError] = useState(null)
  const [caveatsOpen, setCaveatsOpen] = useState(false)
  const intervalRef = useRef(null)

  function setField(key) {
    return (val) => setForm((f) => ({ ...f, [key]: val }))
  }

  // Build the spec payload from form state
  function buildSpec() {
    return {
      building_type: form.building_type,
      floor_area_m2: num(form.floor_area_m2, 1000),
      climate_zone: form.climate_zone,
      wall_assemblies: [
        { U: num(form.wall_N_U, 0.35), area_m2: num(form.wall_N_area, 200) },
        { U: num(form.wall_S_U, 0.35), area_m2: num(form.wall_S_area, 200) },
        { U: num(form.wall_E_U, 0.35), area_m2: num(form.wall_E_area, 150) },
        { U: num(form.wall_W_U, 0.35), area_m2: num(form.wall_W_area, 150) },
      ].filter((w) => w.area_m2 > 0),
      roof_assembly: {
        U: num(form.roof_U, 0.20),
        area_m2: num(form.roof_area, 1000),
      },
      window_specs: [
        {
          U: num(form.win_U, 2.0),
          area_m2: num(form.win_area, 160),
          SHGC: num(form.win_SHGC, 0.40),
        },
      ].filter((w) => w.area_m2 > 0),
      lighting_load_W_per_m2: num(form.lighting_W_m2, 10),
      plug_load_W_per_m2: num(form.plug_W_m2, 12),
      hvac_system_type: form.hvac_system_type,
      annual_run_hours: Math.max(1, Math.min(8760, parseInt(form.annual_run_hours, 10) || 8760)),
    }
  }

  const runSim = useCallback(async () => {
    setSimState('running')
    setSimProgress(0)
    setReport(null)
    setSimError(null)
    setTab('sim')

    // Simulate progress animation (8760-hour sim is fast on backend)
    let prog = 0
    intervalRef.current = setInterval(() => {
      prog = Math.min(prog + Math.random() * 8 + 2, 90)
      setSimProgress(Math.round(prog))
    }, 80)

    try {
      const spec = buildSpec()

      // Call the backend tool endpoint.
      // Fallback: if no projectId, do a client-side mock for demo.
      let result
      if (projectId) {
        const API_URL = import.meta.env?.VITE_API_URL || ''
        const token = (() => {
          try {
            // eslint-disable-next-line no-undef
            return typeof useAuth !== 'undefined' ? useAuth.getState().accessToken : null
          } catch { return null }
        })()
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            tool: 'bim_compute_energy_compliance_report',
            args: spec,
            project_id: projectId,
          }),
        })
        if (!res.ok) {
          const txt = await res.text()
          throw new Error(`Server error ${res.status}: ${txt.slice(0, 200)}`)
        }
        result = await res.json()
      } else {
        // Client-side demo calculation (simplified; mirrors backend logic)
        result = _clientSideMockReport(spec)
      }

      clearInterval(intervalRef.current)
      setSimProgress(100)
      setReport(result)
      setSimState('done')
      setTab('report')
    } catch (err) {
      clearInterval(intervalRef.current)
      setSimError(err.message || 'Simulation failed')
      setSimState('error')
    }
  }, [form, projectId]) // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // Client-side demo report (no backend required)
  // ---------------------------------------------------------------------------
  function _clientSideMockReport(spec) {
    // Very simplified model for demo — mirrors the Python logic roughly
    const BASELINE = {
      office: { 1: 175, 2: 170, 3: 165, 4: 160, 5: 165, 6: 170, 7: 185, 8: 200 },
      residential: { 1: 100, 2: 110, 3: 115, 4: 120, 5: 130, 6: 140, 7: 160, 8: 180 },
      retail: { 1: 190, 2: 185, 3: 180, 4: 175, 5: 180, 6: 185, 7: 200, 8: 215 },
      warehouse: { 1: 60, 2: 62, 3: 65, 4: 70, 5: 75, 6: 80, 7: 90, 8: 100 },
      hospital: { 1: 400, 2: 420, 3: 430, 4: 440, 5: 460, 6: 480, 7: 500, 8: 520 },
      education: { 1: 130, 2: 135, 3: 140, 4: 145, 5: 150, 6: 160, 7: 175, 8: 190 },
    }
    const CZ_NUM = parseInt(spec.climate_zone, 10) || 4
    const baselineEUI = (BASELINE[spec.building_type] || BASELINE.office)[CZ_NUM] || 160

    // Rough EUI estimate: lighting + plug + hvac factor
    const lightKWh = spec.lighting_load_W_per_m2 * spec.floor_area_m2 * spec.annual_run_hours * 0.85 / 1000
    const plugKWh = spec.plug_load_W_per_m2 * spec.floor_area_m2 * spec.annual_run_hours * 0.70 / 1000
    // UA-based rough HVAC
    const UA = spec.wall_assemblies.reduce((s, w) => s + w.U * w.area_m2, 0) +
      spec.roof_assembly.U * spec.roof_assembly.area_m2 +
      spec.window_specs.reduce((s, w) => s + w.U * w.area_m2, 0)
    const HDD = [0, 200, 700, 900, 2500, 3500, 4500, 6000, 8000][CZ_NUM] || 2500
    const CDD = [0, 2900, 2000, 1600, 700, 400, 200, 80, 10][CZ_NUM] || 700
    const heatKWh = (UA * HDD * 24 / 1000) / 0.85
    const coolKWh = (UA * CDD * 24 / 1000) / 3.0
    const fanKWh = (heatKWh + coolKWh) * 0.18
    const total = heatKWh + coolKWh + lightKWh + plugKWh + fanKWh
    const eui = total / spec.floor_area_m2
    const pctBetter = (baselineEUI - eui) / baselineEUI * 100

    const LEED_TABLE = [
      [50, 18], [46, 17], [42, 16], [38, 15], [34, 14], [30, 13], [28, 12],
      [26, 11], [24, 10], [22, 9], [20, 8], [18, 7], [16, 6], [14, 5],
      [12, 4], [10, 3], [8, 2], [6, 1],
    ]
    const leedCredits = LEED_TABLE.find(([p]) => pctBetter >= p)?.[1] ?? 0

    const recs = []
    if (eui > baselineEUI) recs.push(`EUI is ${(-pctBetter).toFixed(1)}% above baseline. Improve insulation and HVAC efficiency.`)
    if (spec.lighting_load_W_per_m2 > 10) recs.push(`Lighting ${spec.lighting_load_W_per_m2} W/m² is above ASHRAE 90.1 target. Switch to LED with occupancy sensors.`)
    if (spec.hvac_system_type === 'CRAC') recs.push('CRAC systems are inefficient outside data centres. Consider PTHP or VAV.')
    if (!recs.length) recs.push('Building meets ASHRAE 90.1 baseline. Consider on-site PV to reduce net EUI further.')

    return {
      ok: true,
      total_annual_energy_kWh: Math.round(total),
      energy_use_intensity_kWh_per_m2: Math.round(eui * 10) / 10,
      ashrae_90_1_compliance: eui <= baselineEUI,
      ashrae_baseline_eui: baselineEUI,
      percent_better_than_baseline: Math.round(pctBetter * 10) / 10,
      leed_credits_earned: leedCredits,
      recommendations: recs,
      honest_caveat:
        'Client-side demo estimate only — simplified UA×DD model. ' +
        'Run with projectId for the full 8760-hour simulation via the Kerf backend.',
      energy_breakdown: {
        heating_kWh: Math.round(heatKWh),
        cooling_kWh: Math.round(coolKWh),
        lighting_kWh: Math.round(lightKWh),
        plug_loads_kWh: Math.round(plugKWh),
        hvac_fans_kWh: Math.round(fanKWh),
      },
    }
  }

  // ---------------------------------------------------------------------------
  // Export helpers
  // ---------------------------------------------------------------------------
  function exportText() {
    if (!report) return
    const lines = [
      '=== KERF EcoDesigner — ASHRAE 90.1-2022 Compliance Report ===',
      `Building type:       ${form.building_type}`,
      `Floor area:          ${form.floor_area_m2} m²`,
      `Climate zone:        ${form.climate_zone}`,
      `HVAC system:         ${form.hvac_system_type}`,
      '',
      `Total annual energy: ${fmtKWh(report.total_annual_energy_kWh)}`,
      `Site EUI:            ${fmtNum(report.energy_use_intensity_kWh_per_m2, 1)} kWh/(m²·yr)`,
      `ASHRAE 90.1 baseline:${report.ashrae_baseline_eui} kWh/(m²·yr)`,
      `% vs baseline:       ${report.percent_better_than_baseline >= 0 ? '+' : ''}${fmtNum(report.percent_better_than_baseline, 1)}%`,
      `ASHRAE compliance:   ${report.ashrae_90_1_compliance ? 'PASS' : 'FAIL'}`,
      `LEED credits earned: ${report.leed_credits_earned}`,
      '',
      '--- Energy Breakdown ---',
      ...Object.entries(report.energy_breakdown || {}).map(
        ([k, v]) => `  ${k.padEnd(20)} ${fmtKWh(v)}`
      ),
      '',
      '--- Recommendations ---',
      ...report.recommendations.map((r, i) => `${i + 1}. ${r}`),
      '',
      '--- Caveat ---',
      report.honest_caveat,
      '',
      `Generated: ${new Date().toISOString()} by Kerf EcoDesigner`,
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `kerf-energy-report-${form.building_type}-${form.climate_zone}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  function renderSetupTab() {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Select
            label="Building type"
            value={form.building_type}
            onChange={setField('building_type')}
            options={BUILDING_TYPES}
          />
          <Select
            label="Climate zone (ASHRAE 169)"
            value={form.climate_zone}
            onChange={setField('climate_zone')}
            options={CLIMATE_ZONES}
          />
        </div>
        <Field
          label="Gross conditioned floor area"
          unit="m²"
          value={form.floor_area_m2}
          onChange={setField('floor_area_m2')}
          min="1"
          step="50"
          help="Total conditioned floor area including all storeys"
        />

        <div className="border-t border-ink-800 pt-3">
          <div className="text-[11px] text-ink-500 uppercase tracking-wider mb-2">Wall assemblies</div>
          <div className="grid grid-cols-3 gap-1 mb-1 text-[10px] text-ink-600 uppercase">
            <span>Face</span><span>U-value</span><span>Area</span>
          </div>
          <div className="space-y-1.5">
            <WallRow label="North" U={form.wall_N_U} area={form.wall_N_area} onU={setField('wall_N_U')} onArea={setField('wall_N_area')} />
            <WallRow label="South" U={form.wall_S_U} area={form.wall_S_area} onU={setField('wall_S_U')} onArea={setField('wall_S_area')} />
            <WallRow label="East"  U={form.wall_E_U} area={form.wall_E_area} onU={setField('wall_E_U')} onArea={setField('wall_E_area')} />
            <WallRow label="West"  U={form.wall_W_U} area={form.wall_W_area} onU={setField('wall_W_U')} onArea={setField('wall_W_area')} />
          </div>
        </div>

        <div className="border-t border-ink-800 pt-3">
          <div className="text-[11px] text-ink-500 uppercase tracking-wider mb-2">Roof</div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Roof U-value" unit="W/(m²·K)" value={form.roof_U} onChange={setField('roof_U')} min="0.01" />
            <Field label="Roof area" unit="m²" value={form.roof_area} onChange={setField('roof_area')} min="1" step="10" />
          </div>
        </div>

        <div className="border-t border-ink-800 pt-3">
          <div className="text-[11px] text-ink-500 uppercase tracking-wider mb-2">Glazing (all windows)</div>
          <div className="grid grid-cols-3 gap-2">
            <Field label="Window U-value" unit="W/(m²·K)" value={form.win_U} onChange={setField('win_U')} min="0.3" />
            <Field label="Total area" unit="m²" value={form.win_area} onChange={setField('win_area')} min="0" step="5" />
            <Field label="SHGC" value={form.win_SHGC} onChange={setField('win_SHGC')} min="0.1" step="0.05"
              help="Solar Heat Gain Coefficient — fraction of solar radiation admitted (0–1)" />
          </div>
        </div>
      </div>
    )
  }

  function renderHvacTab() {
    return (
      <div className="space-y-4">
        <Select
          label="HVAC system type"
          value={form.hvac_system_type}
          onChange={setField('hvac_system_type')}
          options={HVAC_TYPES}
          help="Affects heating COP (0.85 gas / 2.5 HP) and cooling COP (3.0–4.0)"
        />
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Lighting power density (LPD)"
            unit="W/m²"
            value={form.lighting_W_m2}
            onChange={setField('lighting_W_m2')}
            min="0"
            step="1"
            help="ASHRAE 90.1-2022 office target: 9–10 W/m²; hospital: 14–18 W/m²"
          />
          <Field
            label="Plug / equipment load"
            unit="W/m²"
            value={form.plug_W_m2}
            onChange={setField('plug_W_m2')}
            min="0"
            step="1"
            help="Typical office: 10–15 W/m²; hospital: 30–50 W/m²"
          />
        </div>
        <Field
          label="Annual operating hours"
          unit="h/yr"
          value={form.annual_run_hours}
          onChange={setField('annual_run_hours')}
          min="1"
          max="8760"
          step="100"
          help="8760 = continuous (hospital / 24×7). Office typical: 2500–3500 h/yr"
        />

        <div className="border-t border-ink-800 pt-3 space-y-1.5 text-[11px] text-ink-400">
          <div className="text-[10px] text-ink-600 uppercase tracking-wider mb-1">Reference values (ASHRAE 90.1-2022)</div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
            <div>VAV heating AFUE: 85%</div>
            <div>VAV cooling COP: 3.2</div>
            <div>PTHP heating COP: 2.5</div>
            <div>PTHP cooling COP: 3.0</div>
            <div>Chiller COP: 4.0</div>
            <div>CRAC COP: 2.8</div>
          </div>
        </div>
      </div>
    )
  }

  function renderSimTab() {
    return (
      <div className="space-y-4">
        <div className="rounded-lg bg-ink-900 border border-ink-700 p-4">
          <div className="flex items-start gap-3">
            <Zap size={16} className="text-kerf-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="text-sm font-medium text-ink-100 mb-1">8760-hour Annual Simulation</div>
              <div className="text-[11px] text-ink-400">
                Runs a simplified whole-building heat-balance simulation across all 8760 hours
                of the year using ASHRAE 90.1 Appendix G methodology. Heating, cooling, lighting,
                and plug loads are accumulated into site EUI.
              </div>
            </div>
          </div>
        </div>

        {simState === 'idle' && (
          <button
            onClick={runSim}
            className="w-full flex items-center justify-center gap-2 bg-kerf-600 hover:bg-kerf-500 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
          >
            <Play size={15} />
            Run 8760-Hour Simulation
          </button>
        )}

        {simState === 'running' && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-ink-300">
              <Loader2 size={14} className="animate-spin text-kerf-400" />
              Simulating {simProgress < 30 ? 'envelope heat transfer' : simProgress < 60 ? 'HVAC loads' : simProgress < 85 ? 'lighting & plug loads' : 'compliance check'}…
            </div>
            <div className="h-2 bg-ink-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-kerf-500 rounded-full transition-all duration-150"
                style={{ width: `${simProgress}%` }}
              />
            </div>
            <div className="text-[10px] text-ink-600 font-mono">{simProgress}% complete</div>
          </div>
        )}

        {simState === 'error' && (
          <div className="rounded-lg bg-red-900/30 border border-red-700/40 p-3 flex gap-2">
            <AlertCircle size={14} className="text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <div className="text-[12px] text-red-300 font-medium">Simulation failed</div>
              <div className="text-[11px] text-red-400 mt-0.5">{simError}</div>
            </div>
          </div>
        )}

        {simState === 'done' && report && (
          <div className="space-y-3">
            <div className="rounded-lg bg-ink-900 border border-ink-700 p-3">
              <div className="text-[10px] text-ink-500 uppercase tracking-wider mb-2">Energy breakdown</div>
              <div className="space-y-1.5">
                <EnergyBar label="Heating" kWh={report.energy_breakdown?.heating_kWh} total={report.total_annual_energy_kWh} color="#f59e0b" icon={Thermometer} />
                <EnergyBar label="Cooling" kWh={report.energy_breakdown?.cooling_kWh} total={report.total_annual_energy_kWh} color="#3b82f6" icon={Wind} />
                <EnergyBar label="Lighting" kWh={report.energy_breakdown?.lighting_kWh} total={report.total_annual_energy_kWh} color="#fcd34d" icon={Lightbulb} />
                <EnergyBar label="Plug loads" kWh={report.energy_breakdown?.plug_loads_kWh} total={report.total_annual_energy_kWh} color="#a78bfa" icon={Zap} />
                <EnergyBar label="HVAC fans" kWh={report.energy_breakdown?.hvac_fans_kWh} total={report.total_annual_energy_kWh} color="#6b7280" icon={Wind} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div className="rounded bg-ink-900 border border-ink-700 p-2.5">
                <div className="text-ink-500 mb-0.5">Site EUI</div>
                <div className="text-lg font-mono font-bold text-white">
                  {fmtNum(report.energy_use_intensity_kWh_per_m2, 1)}
                  <span className="text-[10px] font-normal text-ink-400 ml-1">kWh/(m²·yr)</span>
                </div>
              </div>
              <div className="rounded bg-ink-900 border border-ink-700 p-2.5">
                <div className="text-ink-500 mb-0.5">Total annual</div>
                <div className="text-lg font-mono font-bold text-white">
                  {fmtKWh(report.total_annual_energy_kWh)}
                </div>
              </div>
            </div>

            <button
              onClick={() => setTab('report')}
              className="w-full text-center text-[12px] text-kerf-400 hover:text-kerf-300 underline underline-offset-2"
            >
              View full compliance report →
            </button>
          </div>
        )}

        {(simState === 'done' || simState === 'error') && (
          <button
            onClick={runSim}
            className="w-full flex items-center justify-center gap-2 border border-ink-700 hover:border-ink-600 text-ink-300 hover:text-ink-200 rounded-lg py-2 text-[12px] transition-colors"
          >
            <Play size={12} />
            Re-run simulation
          </button>
        )}
      </div>
    )
  }

  function renderReportTab() {
    if (!report) {
      return (
        <div className="text-center py-8 text-ink-500 text-[12px]">
          <BarChart3 size={32} className="mx-auto mb-3 opacity-30" />
          Run the 8760-hour simulation first to see the compliance report.
          <br />
          <button onClick={() => setTab('sim')} className="mt-2 text-kerf-400 underline underline-offset-2">
            Go to Annual Sim →
          </button>
        </div>
      )
    }

    return (
      <div className="space-y-4">
        <ComplianceBanner
          compliant={report.ashrae_90_1_compliance}
          eui={report.energy_use_intensity_kWh_per_m2}
          baseline={report.ashrae_baseline_eui}
          pct={report.percent_better_than_baseline}
        />

        <div className="grid grid-cols-3 gap-2">
          <div className="rounded bg-ink-900 border border-ink-700 p-2.5 text-center">
            <div className="text-[10px] text-ink-500 mb-0.5">Site EUI</div>
            <div className="font-mono font-bold text-white text-base">
              {fmtNum(report.energy_use_intensity_kWh_per_m2, 1)}
            </div>
            <div className="text-[9px] text-ink-500">kWh/(m²·yr)</div>
          </div>
          <div className="rounded bg-ink-900 border border-ink-700 p-2.5 text-center">
            <div className="text-[10px] text-ink-500 mb-0.5">Baseline EUI</div>
            <div className="font-mono font-bold text-ink-300 text-base">
              {fmtNum(report.ashrae_baseline_eui, 0)}
            </div>
            <div className="text-[9px] text-ink-500">kWh/(m²·yr)</div>
          </div>
          <div className="rounded bg-ink-900 border border-ink-700 p-2.5 text-center">
            <div className="text-[10px] text-ink-500 mb-0.5">LEED EA Cred.</div>
            <div className="font-mono font-bold text-base" style={{
              color: report.leed_credits_earned >= 14 ? '#10b981' : report.leed_credits_earned >= 8 ? '#3b82f6' : '#f59e0b'
            }}>
              {report.leed_credits_earned}
            </div>
            <div className="text-[9px] text-ink-500">of 18 max</div>
          </div>
        </div>

        {/* LEED credit bar */}
        <div className="rounded bg-ink-900 border border-ink-700 p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[10px] text-ink-500 uppercase tracking-wider">LEED v4 EA Opt 1 — Optimize Energy</div>
            <LeedBadge credits={report.leed_credits_earned} />
          </div>
          <div className="flex gap-0.5">
            {Array.from({ length: 18 }, (_, i) => (
              <div
                key={i}
                className="flex-1 h-3 rounded-sm transition-colors"
                style={{
                  backgroundColor: i < report.leed_credits_earned
                    ? (report.leed_credits_earned >= 14 ? '#10b981' : report.leed_credits_earned >= 8 ? '#3b82f6' : '#f59e0b')
                    : '#1f2937',
                }}
              />
            ))}
          </div>
          <div className="flex justify-between text-[9px] text-ink-600 mt-0.5">
            <span>0</span><span>6%</span><span>20%</span><span>35%</span><span>50%+</span>
          </div>
        </div>

        {/* Energy breakdown */}
        <div className="rounded bg-ink-900 border border-ink-700 p-3">
          <div className="text-[10px] text-ink-500 uppercase tracking-wider mb-2">Energy breakdown</div>
          <div className="space-y-1.5">
            <EnergyBar label="Heating" kWh={report.energy_breakdown?.heating_kWh} total={report.total_annual_energy_kWh} color="#f59e0b" icon={Thermometer} />
            <EnergyBar label="Cooling" kWh={report.energy_breakdown?.cooling_kWh} total={report.total_annual_energy_kWh} color="#3b82f6" icon={Wind} />
            <EnergyBar label="Lighting" kWh={report.energy_breakdown?.lighting_kWh} total={report.total_annual_energy_kWh} color="#fcd34d" icon={Lightbulb} />
            <EnergyBar label="Plug loads" kWh={report.energy_breakdown?.plug_loads_kWh} total={report.total_annual_energy_kWh} color="#a78bfa" icon={Zap} />
            <EnergyBar label="HVAC fans" kWh={report.energy_breakdown?.hvac_fans_kWh} total={report.total_annual_energy_kWh} color="#6b7280" icon={Wind} />
          </div>
          <div className="border-t border-ink-800 mt-2 pt-2 flex justify-between text-[11px]">
            <span className="text-ink-400">Total</span>
            <span className="font-mono font-medium text-white">{fmtKWh(report.total_annual_energy_kWh)}</span>
          </div>
        </div>

        {/* Recommendations preview */}
        <div className="rounded bg-ink-900 border border-ink-700 p-3">
          <div className="text-[10px] text-ink-500 uppercase tracking-wider mb-2">Top recommendations</div>
          <div className="space-y-1.5">
            {(report.recommendations || []).slice(0, 3).map((rec, i) => (
              <div key={i} className="flex gap-2 text-[11px] text-ink-300">
                <span className="text-kerf-400 flex-shrink-0 font-medium">{i + 1}.</span>
                <span>{rec}</span>
              </div>
            ))}
          </div>
          {report.recommendations?.length > 3 && (
            <button onClick={() => setTab('export')} className="mt-2 text-[11px] text-kerf-400 underline underline-offset-2">
              See all {report.recommendations.length} recommendations →
            </button>
          )}
        </div>
      </div>
    )
  }

  function renderExportTab() {
    return (
      <div className="space-y-4">
        {!report ? (
          <div className="text-center py-8 text-ink-500 text-[12px]">
            Run the simulation to generate the report before exporting.
            <br />
            <button onClick={() => setTab('sim')} className="mt-2 text-kerf-400 underline underline-offset-2">
              Go to Annual Sim →
            </button>
          </div>
        ) : (
          <>
            <button
              onClick={exportText}
              className="w-full flex items-center justify-center gap-2 bg-kerf-600 hover:bg-kerf-500 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
            >
              <FileDown size={15} />
              Download Report (.txt)
            </button>

            <div className="rounded bg-ink-900 border border-ink-700 p-3">
              <div className="text-[10px] text-ink-500 uppercase tracking-wider mb-2.5">All recommendations</div>
              <div className="space-y-2">
                {(report.recommendations || []).map((rec, i) => (
                  <div key={i} className="flex gap-2 text-[12px] text-ink-300">
                    <span className="text-kerf-400 font-medium flex-shrink-0 w-4">{i + 1}.</span>
                    <span>{rec}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Caveat */}
            <div className="rounded bg-amber-900/20 border border-amber-800/30 overflow-hidden">
              <button
                onClick={() => setCaveatsOpen((v) => !v)}
                className="w-full flex items-center justify-between px-3 py-2 text-[11px] text-amber-400 hover:bg-amber-900/10"
              >
                <div className="flex items-center gap-1.5">
                  <AlertCircle size={12} />
                  Methodology caveat
                </div>
                {caveatsOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </button>
              {caveatsOpen && (
                <div className="px-3 pb-3 text-[11px] text-amber-300/80 leading-relaxed">
                  {report.honest_caveat}
                </div>
              )}
            </div>

            {/* Standards reference */}
            <div className="rounded bg-ink-900 border border-ink-700 p-3 text-[10px] text-ink-500 space-y-0.5">
              <div className="text-ink-400 font-medium mb-1">Standards reference</div>
              <div>• ASHRAE 90.1-2022 — Energy Standard for Buildings</div>
              <div>• ASHRAE 90.1-2022 Appendix G — Performance Rating Method</div>
              <div>• LEED v4 BD+C — EA Credit: Optimize Energy Performance</div>
              <div>• IECC 2021 — International Energy Conservation Code</div>
              <div>• ASHRAE 62.1-2022 — Ventilation for Acceptable Indoor Air Quality</div>
            </div>
          </>
        )}
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Main render
  // ---------------------------------------------------------------------------

  const content = (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      {!embedded && (
        <div className="flex items-center justify-between px-4 py-3 border-b border-ink-800 flex-shrink-0">
          <div className="flex items-center gap-2">
            <Sun size={16} className="text-amber-400" />
            <span className="font-semibold text-sm text-ink-100">EcoDesigner</span>
            <span className="text-[10px] text-ink-500 uppercase tracking-wider ml-1 bg-ink-800 px-1.5 py-0.5 rounded">
              ASHRAE 90.1
            </span>
          </div>
          {onClose && (
            <button onClick={onClose} className="text-ink-500 hover:text-ink-300 text-[18px] leading-none">&times;</button>
          )}
        </div>
      )}

      {/* Tab bar */}
      <div className="flex border-b border-ink-800 flex-shrink-0 overflow-x-auto">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-[11px] whitespace-nowrap border-b-2 transition-colors ${
              tab === id
                ? 'border-kerf-500 text-kerf-300'
                : 'border-transparent text-ink-500 hover:text-ink-300'
            }`}
          >
            <Icon size={11} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {tab === 'setup'  && renderSetupTab()}
        {tab === 'hvac'   && renderHvacTab()}
        {tab === 'sim'    && renderSimTab()}
        {tab === 'report' && renderReportTab()}
        {tab === 'export' && renderExportTab()}
      </div>
    </div>
  )

  if (embedded) return content

  return (
    <div className="bg-ink-950 border border-ink-800 rounded-xl shadow-2xl w-[480px] h-[640px] flex flex-col overflow-hidden">
      {content}
    </div>
  )
}
