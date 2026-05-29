// PVShadingPanel.jsx — PV array partial-shading + bypass-diode + MPPT panel.
//
// Lets the user configure:
//   • Array layout: modules per string, strings per array, tilt/azimuth, location
//   • Latitude — used by the backend to look up TMY3-derived monthly irradiance
//     fractions (NREL TMY3 medians, Wilcox & Marion 2008).  Changing latitude
//     flips the seasonal profile for Southern-hemisphere sites.
//   • Module parameters (defaults = 60-cell 255Wp)
//   • Obstruction polygons (simple list of obstruction descriptions)
//   • Bypass-diode configuration
//
// Run → dispatches to POST /api/projects/:pid/energy/pv-shading which
//   calls pv_mppt_mismatch_loss + pv_energy_yield for each month.
//   Monthly yield chart reflects latitude-aware TMY seasonal distribution.
//
// Output: monthly energy yield bar chart (via MonthlyLoadChart) +
//   mismatch loss, GMPP, annual yield.
//
// Props: { projectId: string }

import { useState, useCallback } from 'react'
import { Sun, Play, AlertTriangle, Plus, Trash2, Zap, MapPin } from 'lucide-react'
import { api } from '../../lib/api.js'
import MonthlyLoadChart from './MonthlyLoadChart.jsx'

// ---------------------------------------------------------------------------
// Default values
// ---------------------------------------------------------------------------

const DEFAULT_MODULE = {
  // Single-diode defaults for a ~255 Wp 60-cell module at STC
  Iph: 9.0,
  Io: 1.5e-10,
  Rs: 0.005,
  Rsh: 400,
  n: 1.3,
  T_C: 25,
  n_cells: 60,
  cells_per_bypass: 20,  // 3 bypass diodes
}

const DEFAULT_SHADING_PATTERN = [
  { cells: 20, irradiance: 200 },   // one substring shaded
  { cells: 40, irradiance: 1000 },  // rest unshaded
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function NumInput({ value, onChange, min, max, step = 'any', disabled, placeholder, className }) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      placeholder={placeholder}
      className={`w-full h-7 bg-ink-900 border border-ink-800 rounded px-2 text-xs text-ink-100 focus:outline-none focus:border-kerf-300 focus-visible:ring-1 focus-visible:ring-kerf-300 disabled:opacity-50 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none ${className || ''}`}
    />
  )
}

function FieldRow({ label, hint, children }) {
  return (
    <div className="flex items-start gap-2 mb-1.5">
      <label className="text-[11px] text-ink-400 w-36 flex-shrink-0 pt-1.5 leading-tight">
        {label}
        {hint && <span className="block text-[10px] text-ink-600">{hint}</span>}
      </label>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  )
}

function ResultRow({ label, value, unit, accent }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-ink-800 last:border-0">
      <span className="text-[11px] text-ink-400">{label}</span>
      <span className={`font-mono tabular-nums text-[11px] ${accent ? 'text-kerf-300 font-semibold' : 'text-ink-200'}`}>
        {value != null && value !== '—' ? `${value}${unit ? ` ${unit}` : ''}` : '—'}
      </span>
    </div>
  )
}

function fmt2(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

function fmt0(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(0)
}

// ---------------------------------------------------------------------------
// Obstruction row
// ---------------------------------------------------------------------------

function ObstructionRow({ obs, idx, onChange, onRemove }) {
  const inputCls = 'bg-ink-900 border border-ink-700 rounded px-1 py-0.5 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300 w-20 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none'

  return (
    <div className="flex items-center gap-2 py-1 border-b border-ink-800/50">
      <span className="text-[10px] text-ink-600 w-4">{idx + 1}</span>
      <div className="flex items-center gap-1">
        <span className="text-[10px] text-ink-500">Cells shaded:</span>
        <input
          type="number"
          value={obs.cells}
          min={1}
          onChange={(e) => onChange(idx, { ...obs, cells: e.target.value })}
          className={inputCls}
          aria-label={`Obstruction ${idx + 1} shaded cells`}
        />
        <span className="text-[10px] text-ink-500">Irr (W/m²):</span>
        <input
          type="number"
          value={obs.irradiance}
          min={0}
          max={1200}
          onChange={(e) => onChange(idx, { ...obs, irradiance: e.target.value })}
          className={inputCls}
          aria-label={`Obstruction ${idx + 1} irradiance`}
        />
      </div>
      <button
        type="button"
        onClick={() => onRemove(idx)}
        aria-label={`Remove obstruction ${idx + 1}`}
        className="ml-auto text-ink-600 hover:text-amber-400 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300 rounded"
      >
        <Trash2 size={11} />
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function PVShadingPanel({ projectId }) {
  // Array layout
  const [modulesPerString, setModulesPerString] = useState(10)
  const [stringsInParallel, setStringsInParallel] = useState(2)
  const [tiltDeg, setTiltDeg] = useState(30)
  const [azimuthDeg, setAzimuthDeg] = useState(180)  // South
  // Latitude — drives TMY-aware monthly yield fractions; default 30°N for compat
  const [latitude, setLatitude] = useState(30)
  const [poa_annual, setPoa_annual] = useState(1200)  // kWh/m²/yr
  const [pr, setPr] = useState(0.80)  // Performance ratio

  // Module params
  const [module, setModule] = useState(DEFAULT_MODULE)

  // Shading pattern (cells + irradiance per substring)
  const [shadingPattern, setShadingPattern] = useState(DEFAULT_SHADING_PATTERN)

  // Bypass diodes
  const [bypassDiodes, setBypassDiodes] = useState(true)
  const [bypassFwdV, setBypassFwdV] = useState(0.7)

  // State
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const handleObsChange = useCallback((idx, updated) => {
    setShadingPattern((prev) => prev.map((o, i) => (i === idx ? updated : o)))
    setResult(null)
  }, [])

  const handleObsRemove = useCallback((idx) => {
    setShadingPattern((prev) => prev.filter((_, i) => i !== idx))
    setResult(null)
  }, [])

  const handleObsAdd = useCallback(() => {
    setShadingPattern((prev) => [...prev, { cells: 20, irradiance: 500 }])
    setResult(null)
  }, [])

  const handleRun = useCallback(async () => {
    if (!projectId) { setError('No project context.'); return }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const latVal = parseFloat(latitude)
      const body = {
        // Array geometry
        modules_per_string: parseInt(modulesPerString, 10) || 10,
        strings_in_parallel: parseInt(stringsInParallel, 10) || 1,
        tilt_deg: parseFloat(tiltDeg) || 30,
        azimuth_deg: parseFloat(azimuthDeg) || 180,
        // Latitude drives TMY monthly fractions on the backend
        latitude: Number.isFinite(latVal) ? latVal : 30,
        poa_annual_kWh_m2: parseFloat(poa_annual) || 1200,
        pr: parseFloat(pr) || 0.80,
        // Module
        module: {
          Iph: parseFloat(module.Iph) || 9.0,
          Io: parseFloat(module.Io) || 1.5e-10,
          Rs: parseFloat(module.Rs) || 0.005,
          Rsh: parseFloat(module.Rsh) || 400,
          n: parseFloat(module.n) || 1.3,
          T_C: parseFloat(module.T_C) || 25,
          n_cells: parseInt(module.n_cells, 10) || 60,
          cells_per_bypass: parseInt(module.cells_per_bypass, 10) || 20,
        },
        // Shading: each string gets the same pattern for now (homogeneous)
        shading_pattern: shadingPattern.map((o) => ({
          cells: parseInt(o.cells, 10) || 20,
          irradiance: parseFloat(o.irradiance) ?? 1000,
        })),
        bypass_diodes: bypassDiodes,
        bypass_fwd_v: parseFloat(bypassFwdV) || 0.7,
      }
      const data = await api.pvShading(projectId, body)
      setResult(data)
    } catch (err) {
      setError(err?.message || 'API error')
    } finally {
      setLoading(false)
    }
  }, [
    projectId, modulesPerString, stringsInParallel, tiltDeg, azimuthDeg,
    latitude, poa_annual, pr, module, shadingPattern, bypassDiodes, bypassFwdV,
  ])

  // Build chart data from monthly yield if available
  // monthly_yield comes from the backend with latitude-aware TMY fractions
  const monthlyChartData = result?.monthly_yield
    ? result.monthly_yield.map((m) => ({
        heating_kWh:   0,
        cooling_kWh:   0,
        lighting_kWh:  0,
        equipment_kWh: m.yield_kWh ?? 0,
      }))
    : null

  // Hemisphere label for UI hint
  const latVal = parseFloat(latitude)
  const hemisphereHint = Number.isFinite(latVal)
    ? latVal >= 0
      ? `${latVal.toFixed(1)}°N — NH profile`
      : `${Math.abs(latVal).toFixed(1)}°S — SH flipped`
    : ''

  return (
    <div className="h-full flex flex-col min-h-0 bg-ink-950 text-ink-100" data-testid="pv-shading-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-ink-800 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Sun size={14} className="text-amber-400" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wider text-ink-300">
            PV Shading + MPPT
          </span>
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={loading}
          aria-label={loading ? 'Running simulation…' : 'Run PV shading simulation'}
          className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-amber-500 text-ink-950 text-xs font-medium hover:bg-amber-400 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          <Play size={11} aria-hidden="true" />
          {loading ? 'Running…' : 'Run'}
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto min-h-0 p-4 space-y-4">

        {/* Array layout */}
        <section>
          <div className="text-[10px] uppercase tracking-wider text-ink-500 mb-2">Array Layout</div>
          <div className="grid grid-cols-2 gap-x-3">
            <FieldRow label="Modules / string">
              <NumInput value={modulesPerString} onChange={setModulesPerString} min={1} step={1} />
            </FieldRow>
            <FieldRow label="Strings (parallel)">
              <NumInput value={stringsInParallel} onChange={setStringsInParallel} min={1} step={1} />
            </FieldRow>
            <FieldRow label="Tilt (°)">
              <NumInput value={tiltDeg} onChange={setTiltDeg} min={0} max={90} />
            </FieldRow>
            <FieldRow label="Azimuth (°)" hint="180 = south">
              <NumInput value={azimuthDeg} onChange={setAzimuthDeg} min={0} max={360} />
            </FieldRow>
            <FieldRow
              label={
                <span className="flex items-center gap-1">
                  <MapPin size={9} className="text-amber-400 inline" />
                  Latitude (°)
                </span>
              }
              hint={hemisphereHint || '+N / −S; drives TMY monthly fractions'}
            >
              <NumInput
                value={latitude}
                onChange={(v) => { setLatitude(v); setResult(null) }}
                min={-90}
                max={90}
                step={0.1}
                aria-label="Site latitude in decimal degrees, positive north, negative south"
              />
            </FieldRow>
            <FieldRow label="POA annual (kWh/m²)">
              <NumInput value={poa_annual} onChange={setPoa_annual} min={0} />
            </FieldRow>
            <FieldRow label="Perf. ratio (PR)">
              <NumInput value={pr} onChange={setPr} min={0.1} max={1} step={0.01} />
            </FieldRow>
          </div>
          <p className="text-[10px] text-ink-600 mt-1">
            Monthly yield uses TMY3-derived irradiance fractions keyed to latitude
            (NREL/TP-581-43156).  Southern-hemisphere sites get the seasonally-flipped profile.
          </p>
        </section>

        {/* Module params */}
        <section>
          <div className="text-[10px] uppercase tracking-wider text-ink-500 mb-2">Module Parameters (STC)</div>
          <div className="grid grid-cols-2 gap-x-3">
            <FieldRow label="Iph (A)" hint="photo-current">
              <NumInput value={module.Iph} onChange={(v) => setModule((m) => ({ ...m, Iph: v }))} min={0} />
            </FieldRow>
            <FieldRow label="Io (A)" hint="dark saturation">
              <NumInput value={module.Io} onChange={(v) => setModule((m) => ({ ...m, Io: v }))} min={0} step={1e-12} />
            </FieldRow>
            <FieldRow label="Rs (Ω)">
              <NumInput value={module.Rs} onChange={(v) => setModule((m) => ({ ...m, Rs: v }))} min={0} step={0.001} />
            </FieldRow>
            <FieldRow label="Rsh (Ω)">
              <NumInput value={module.Rsh} onChange={(v) => setModule((m) => ({ ...m, Rsh: v }))} min={1} />
            </FieldRow>
            <FieldRow label="Ideality (n)">
              <NumInput value={module.n} onChange={(v) => setModule((m) => ({ ...m, n: v }))} min={1} max={2} step={0.05} />
            </FieldRow>
            <FieldRow label="Cells">
              <NumInput value={module.n_cells} onChange={(v) => setModule((m) => ({ ...m, n_cells: v }))} min={1} step={1} />
            </FieldRow>
            <FieldRow label="Cells / bypass">
              <NumInput value={module.cells_per_bypass} onChange={(v) => setModule((m) => ({ ...m, cells_per_bypass: v }))} min={1} step={1} />
            </FieldRow>
          </div>
        </section>

        {/* Shading pattern */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <div className="text-[10px] uppercase tracking-wider text-ink-500">Obstruction / Shading Pattern</div>
            <button
              type="button"
              onClick={handleObsAdd}
              aria-label="Add obstruction"
              className="inline-flex items-center gap-1 text-[11px] text-amber-400 hover:text-amber-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-amber-400 rounded"
            >
              <Plus size={11} /> Add
            </button>
          </div>
          <div className="bg-ink-900 rounded-md px-3 py-1">
            {shadingPattern.length === 0 ? (
              <div className="text-[11px] text-ink-600 py-2">No obstructions — full-sun simulation.</div>
            ) : (
              shadingPattern.map((obs, i) => (
                <ObstructionRow
                  key={i}
                  obs={obs}
                  idx={i}
                  onChange={handleObsChange}
                  onRemove={handleObsRemove}
                />
              ))
            )}
          </div>
        </section>

        {/* Bypass diodes */}
        <section>
          <div className="text-[10px] uppercase tracking-wider text-ink-500 mb-2">Bypass Diodes</div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-ink-300 cursor-pointer">
              <input
                type="checkbox"
                checked={bypassDiodes}
                onChange={(e) => setBypassDiodes(e.target.checked)}
                className="accent-amber-400"
              />
              Enable bypass diodes
            </label>
            {bypassDiodes && (
              <FieldRow label="Fwd voltage (V)">
                <NumInput
                  value={bypassFwdV}
                  onChange={setBypassFwdV}
                  min={0.1}
                  max={1.5}
                  step={0.05}
                  className="w-24"
                />
              </FieldRow>
            )}
          </div>
        </section>

        {/* Error */}
        {error && (
          <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30">
            <AlertTriangle size={12} className="text-amber-400 mt-0.5 flex-shrink-0" />
            <span className="text-[11px] text-amber-200">{error}</span>
          </div>
        )}

        {/* Results */}
        {result && (
          <>
            <section>
              <div className="text-[10px] uppercase tracking-wider text-ink-500 mb-2">
                <Zap size={10} className="inline mr-1" />
                Simulation Results
              </div>
              <div className="bg-ink-900 rounded-md px-3 py-1">
                <ResultRow
                  label="String GMPP"
                  value={fmt2(result.string_gmpp_p_w)}
                  unit="W"
                />
                <ResultRow
                  label="Sum module GMPPs"
                  value={fmt2(result.sum_module_gmpp_p_w)}
                  unit="W"
                />
                <ResultRow
                  label="Mismatch loss"
                  value={fmt2(result.mismatch_loss_w)}
                  unit="W"
                />
                <ResultRow
                  label="Mismatch loss"
                  value={fmt2(result.mismatch_loss_pct)}
                  unit="%"
                  accent
                />
                <ResultRow
                  label="Annual yield (yr 1)"
                  value={fmt0(result.annual_yield_yr1_kWh)}
                  unit="kWh"
                  accent
                />
                <ResultRow
                  label="Specific yield"
                  value={fmt0(result.specific_yield_kWh_kWp)}
                  unit="kWh/kWp"
                />
                <ResultRow
                  label="Array kWp"
                  value={fmt2(result.array_kWp)}
                  unit="kWp"
                />
              </div>
            </section>

            {/* Monthly energy yield chart */}
            {monthlyChartData && (
              <section>
                <div className="text-[10px] uppercase tracking-wider text-ink-500 mb-2">
                  Monthly Energy Yield
                  {result.latitude_deg != null && (
                    <span className="ml-2 normal-case text-ink-600">
                      ({result.latitude_deg >= 0
                        ? `${result.latitude_deg}°N`
                        : `${Math.abs(result.latitude_deg)}°S`} TMY profile)
                    </span>
                  )}
                </div>
                <div className="bg-ink-900 rounded-md p-3 overflow-x-auto">
                  <MonthlyLoadChart
                    data={monthlyChartData}
                    width={480}
                    height={200}
                    title=""
                  />
                  <div className="text-[10px] text-ink-600 mt-1 text-right">
                    Equipment series = PV yield (kWh) · TMY3 latitude-adjusted fractions
                  </div>
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}
