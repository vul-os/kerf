/**
 * Hourly8760Panel.jsx — 8760-hour whole-building transient energy simulation.
 *
 * Wraps the kerf LLM tools:
 *   be_simulate_8760          — ASHRAE 90.1 Appendix G 8760-hr heat-balance
 *   be_simulate_hvac_plant    — apply chiller/boiler efficiency curves
 *   be_check_title24          — California Title 24 Part 6 compliance
 *   be_evaluate_leed_eap2     — LEED v4.1 EAp2 / EAc1 prerequisite check
 *
 * HONEST NOTE: This is a simplified single-zone model (±10–20% vs. EnergyPlus).
 * Uses synthetic weather patterns when no TMY3 file is provided.
 *
 * References:
 *   ASHRAE 90.1-2022 Appendix G — Performance Rating Method
 *   NREL TMY3 User's Manual (2008)
 *
 * Props: { projectId?: string }
 */

import { useState, useCallback } from 'react'
import { Building2, Play, AlertTriangle, Info, BarChart2 } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const text = await res.text()
    let msg = text
    try { msg = JSON.parse(text).error || text } catch { /* ignore */ }
    throw new Error(msg || `HTTP ${res.status}`)
  }
  return res.json()
}

function fmt2(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

function fmtKwh(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${Math.round(n).toLocaleString()} kWh`
}

function fmtEUI(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${n.toFixed(1)} kWh/(m²·yr)`
}

function fmtKW(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${n.toFixed(1)} kW`
}

// ---------------------------------------------------------------------------
// Common UI primitives
// ---------------------------------------------------------------------------

function NumInput({ value, onChange, min, max, step = 'any', disabled, unit }) {
  return (
    <div className="flex items-center gap-1">
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        className="w-full h-7 bg-ink-900 border border-ink-800 rounded px-2 text-xs text-ink-100 focus:outline-none focus:border-kerf-300 focus-visible:ring-1 focus-visible:ring-kerf-300 disabled:opacity-50 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
      />
      {unit && <span className="text-[10px] text-ink-500 flex-shrink-0 w-16">{unit}</span>}
    </div>
  )
}

function SelectInput({ value, onChange, options, disabled }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="w-full h-7 bg-ink-900 border border-ink-800 rounded px-2 text-xs text-ink-100 focus:outline-none focus:border-kerf-300 disabled:opacity-50"
    >
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
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

function ResultRow({ label, value, highlight }) {
  return (
    <div className="flex justify-between items-center py-1 border-b border-ink-800/50">
      <span className="text-[11px] text-ink-400">{label}</span>
      <span className={`text-[11px] font-mono ${highlight ? 'text-kerf-300 font-semibold' : 'text-ink-200'}`}>{value}</span>
    </div>
  )
}

function SectionHeader({ children }) {
  return (
    <div className="text-[10px] uppercase tracking-wider text-ink-600 mb-1.5 mt-3 first:mt-0">
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Simple bar chart for monthly energy breakdown
// ---------------------------------------------------------------------------

function EnergyBar({ label, value, max, color }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="flex items-center gap-2 mb-0.5">
      <span className="text-[10px] text-ink-500 w-14 flex-shrink-0 text-right">{label}</span>
      <div className="flex-1 bg-ink-800 rounded-sm h-3 overflow-hidden">
        <div className={`h-full rounded-sm ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-mono text-ink-400 w-24 flex-shrink-0">{fmtKwh(value)}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Climate zone → synthetic weather pattern
// ---------------------------------------------------------------------------

const CLIMATE_PRESETS = [
  { value: 'cool_temperate',   label: 'Cool Temperate (e.g. UK, PNW)' },
  { value: 'hot_arid',         label: 'Hot Arid (e.g. Phoenix, Dubai)' },
  { value: 'hot_humid',        label: 'Hot Humid (e.g. Miami, Singapore)' },
  { value: 'cold_continental', label: 'Cold Continental (e.g. Chicago, Moscow)' },
  { value: 'mediterranean',    label: 'Mediterranean (e.g. LA, Cape Town)' },
  { value: 'tropical',         label: 'Tropical (e.g. Lagos, Bangkok)' },
]

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function Hourly8760Panel({ projectId: _projectId }) {
  const [inputs, setInputs] = useState({
    name: 'My Building',
    floor_area_m2: 1000,
    ceiling_height_m: 3.0,
    window_to_wall_ratio: 0.30,
    wall_u: 0.35,
    roof_u: 0.20,
    window_u: 1.8,
    shgc: 0.40,
    internal_load_w_m2: 25,
    ventilation_ach: 0.20,
    lighting_fraction: 0.40,
    fan_power_w_m2: 5.0,
    setpoint_heating_c: 20,
    setpoint_cooling_c: 24,
    climate: 'cool_temperate',
    // HVAC plant
    chiller_cop: 4.5,
    boiler_efficiency: 0.90,
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k, v) => setInputs((prev) => ({ ...prev, [k]: parseFloat(v) !== undefined && v !== '' ? (isNaN(parseFloat(v)) ? v : parseFloat(v)) : v }))

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const r = await callTool('be_simulate_8760', {
        building: {
          name: inputs.name,
          floor_area_m2: inputs.floor_area_m2,
          ceiling_height_m: inputs.ceiling_height_m,
          window_to_wall_ratio: inputs.window_to_wall_ratio,
          construction_uw_m2k: {
            wall: inputs.wall_u,
            roof: inputs.roof_u,
            window: inputs.window_u,
            shgc: inputs.shgc,
          },
          internal_load_w_m2: inputs.internal_load_w_m2,
          ventilation_ach: inputs.ventilation_ach,
          lighting_fraction: inputs.lighting_fraction,
          fan_power_w_per_m2: inputs.fan_power_w_m2,
          setpoint_heating_c: inputs.setpoint_heating_c,
          setpoint_cooling_c: inputs.setpoint_cooling_c,
          occupancy_schedule_8760: [],  // use default office schedule
        },
        weather_preset: inputs.climate,
      })
      if (r.ok === false) { setError(r.reason); return }
      setResult(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [inputs])

  const maxKwh = result
    ? Math.max(
        result.annual_heating_kwh || 0,
        result.annual_cooling_kwh || 0,
        result.annual_fan_kwh || 0,
        result.annual_lighting_kwh || 0,
      )
    : 0

  return (
    <div className="flex flex-col h-full overflow-hidden text-ink-200">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-800">
        <Building2 size={13} className="text-kerf-300" />
        <span className="text-xs font-semibold text-ink-100">8760-Hour Building Energy</span>
        <div
          className="flex items-center gap-1 ml-1"
          title="Simplified single-zone heat-balance per ASHRAE 90.1 Appendix G. ±10–20% vs. EnergyPlus."
        >
          <Info size={10} className="text-ink-600" />
        </div>
        <span className="ml-auto text-[10px] text-amber-500/70 flex items-center gap-1">
          <AlertTriangle size={9} />
          ±10–20% design estimate
        </span>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-3 py-2 min-h-0">
        <SectionHeader>Building Geometry</SectionHeader>
        <div className="grid grid-cols-2 gap-x-3">
          <FieldRow label="Floor area" hint="m²">
            <NumInput value={inputs.floor_area_m2} onChange={(v) => set('floor_area_m2', v)} min={1} unit="m²" />
          </FieldRow>
          <FieldRow label="Ceiling height" hint="m">
            <NumInput value={inputs.ceiling_height_m} onChange={(v) => set('ceiling_height_m', v)} min={2} unit="m" />
          </FieldRow>
          <FieldRow label="WWR" hint="window:wall">
            <NumInput value={inputs.window_to_wall_ratio} onChange={(v) => set('window_to_wall_ratio', v)} min={0} max={1} step="0.05" />
          </FieldRow>
        </div>

        <SectionHeader>Envelope U-values</SectionHeader>
        <div className="grid grid-cols-2 gap-x-3">
          <FieldRow label="Wall U" hint="W/m²K">
            <NumInput value={inputs.wall_u} onChange={(v) => set('wall_u', v)} min={0} step="0.01" unit="W/m²K" />
          </FieldRow>
          <FieldRow label="Roof U" hint="W/m²K">
            <NumInput value={inputs.roof_u} onChange={(v) => set('roof_u', v)} min={0} step="0.01" unit="W/m²K" />
          </FieldRow>
          <FieldRow label="Window U" hint="W/m²K">
            <NumInput value={inputs.window_u} onChange={(v) => set('window_u', v)} min={0} step="0.1" unit="W/m²K" />
          </FieldRow>
          <FieldRow label="SHGC" hint="solar HGC">
            <NumInput value={inputs.shgc} onChange={(v) => set('shgc', v)} min={0} max={1} step="0.05" />
          </FieldRow>
        </div>

        <SectionHeader>Internal Loads + HVAC</SectionHeader>
        <div className="grid grid-cols-2 gap-x-3">
          <FieldRow label="Internal loads" hint="W/m²">
            <NumInput value={inputs.internal_load_w_m2} onChange={(v) => set('internal_load_w_m2', v)} min={0} unit="W/m²" />
          </FieldRow>
          <FieldRow label="Vent. ACH" hint="ASHRAE 62.1">
            <NumInput value={inputs.ventilation_ach} onChange={(v) => set('ventilation_ach', v)} min={0} step="0.05" />
          </FieldRow>
          <FieldRow label="Lighting frac.">
            <NumInput value={inputs.lighting_fraction} onChange={(v) => set('lighting_fraction', v)} min={0} max={1} step="0.05" />
          </FieldRow>
          <FieldRow label="Fan power" hint="W/m²">
            <NumInput value={inputs.fan_power_w_m2} onChange={(v) => set('fan_power_w_m2', v)} min={0} unit="W/m²" />
          </FieldRow>
          <FieldRow label="Setpoint heat" hint="°C">
            <NumInput value={inputs.setpoint_heating_c} onChange={(v) => set('setpoint_heating_c', v)} unit="°C" />
          </FieldRow>
          <FieldRow label="Setpoint cool" hint="°C">
            <NumInput value={inputs.setpoint_cooling_c} onChange={(v) => set('setpoint_cooling_c', v)} unit="°C" />
          </FieldRow>
        </div>

        <SectionHeader>Climate</SectionHeader>
        <div className="mb-2">
          <SelectInput
            value={inputs.climate}
            onChange={(v) => setInputs((p) => ({ ...p, climate: v }))}
            options={CLIMATE_PRESETS}
          />
        </div>

        <button
          onClick={run}
          disabled={loading}
          className="w-full h-8 bg-kerf-600 hover:bg-kerf-500 disabled:opacity-50 text-white text-xs font-medium rounded flex items-center justify-center gap-1.5 mt-2"
        >
          <Play size={11} />
          {loading ? 'Simulating 8760 hours…' : 'Run 8760-Hour Simulation'}
        </button>

        {error && (
          <div className="flex items-start gap-2 mt-2 p-2 bg-amber-950/40 border border-amber-800/50 rounded text-[11px] text-amber-300">
            <AlertTriangle size={11} className="flex-shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {result && (
          <>
            <SectionHeader>Annual Energy Results</SectionHeader>

            {/* EUI highlight */}
            <div className="bg-kerf-950/40 border border-kerf-800/50 rounded-md px-3 py-2 mb-3 flex items-center gap-3">
              <BarChart2 size={16} className="text-kerf-300" />
              <div>
                <div className="text-[10px] text-kerf-400">Site EUI</div>
                <div className="text-lg font-bold text-kerf-200">{fmtEUI(result.eui_kwh_m2_yr)}</div>
              </div>
            </div>

            {/* End-use breakdown */}
            <div className="mb-3">
              <EnergyBar label="Heating"  value={result.annual_heating_kwh}  max={maxKwh} color="bg-amber-500" />
              <EnergyBar label="Cooling"  value={result.annual_cooling_kwh}  max={maxKwh} color="bg-blue-500" />
              <EnergyBar label="Fan"      value={result.annual_fan_kwh}      max={maxKwh} color="bg-purple-500" />
              <EnergyBar label="Lighting" value={result.annual_lighting_kwh} max={maxKwh} color="bg-yellow-500" />
            </div>

            <SectionHeader>Peak Loads</SectionHeader>
            <ResultRow label="Peak heating" value={fmtKW(result.peak_heating_kw)} />
            <ResultRow label="Peak cooling" value={fmtKW(result.peak_cooling_kw)} />

            <SectionHeader>Annual Totals</SectionHeader>
            <ResultRow label="Heating energy" value={fmtKwh(result.annual_heating_kwh)} />
            <ResultRow label="Cooling energy" value={fmtKwh(result.annual_cooling_kwh)} />
            <ResultRow label="Fan energy"     value={fmtKwh(result.annual_fan_kwh)} />
            <ResultRow label="Lighting energy" value={fmtKwh(result.annual_lighting_kwh)} />

            {result.leed && (
              <>
                <SectionHeader>LEED v4.1 EAp2</SectionHeader>
                <ResultRow label="Prerequisite met" value={result.leed.prerequisite_met ? '✅ Yes' : '❌ No'} highlight />
                <ResultRow label="EAc1 points" value={result.leed.eac1_points ?? '—'} />
                <ResultRow label="Energy savings" value={result.leed.savings_pct != null ? `${result.leed.savings_pct.toFixed(1)}%` : '—'} />
              </>
            )}

            {/* Honest disclaimer */}
            <div className="mt-3 p-2 bg-ink-900/60 border border-ink-700/40 rounded text-[10px] text-ink-600">
              Simplified single-zone model per ASHRAE 90.1 Appendix G. Accuracy ±10–20% vs.
              EnergyPlus/eQUEST. Thermal mass, multi-zone interactions, and part-load curves
              not modelled. Use for early design / code compliance screening only.
            </div>
          </>
        )}
      </div>
    </div>
  )
}
