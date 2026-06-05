/**
 * ThermoCyclePanel.jsx — Thermodynamic cycle analysis panel.
 *
 * Wraps the kerf LLM tools:
 *   thermo_otto_cycle          — air-standard Otto (SI) cycle
 *   thermo_diesel_cycle        — air-standard Diesel (CI) cycle
 *   thermo_brayton_cycle       — Brayton gas-turbine cycle (with regeneration)
 *   thermo_rankine_cycle_ideal — simplified ideal Rankine (steam) cycle
 *   thermo_carnot_efficiency   — Carnot upper bound
 *
 * References: Cengel & Boles "Thermodynamics" 8th ed.; Moran et al. FET 7th ed.
 *
 * Props: { projectId?: string }
 */

import { useState, useCallback } from 'react'
import { Activity, Play, AlertTriangle, Info } from 'lucide-react'

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

function fmt(n, dp = 4) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(dp)
}

function fmtPct(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${(n * 100).toFixed(2)}%`
}

function fmtKJ(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${(n / 1000).toFixed(2)} kJ/kg`
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
      {unit && <span className="text-[10px] text-ink-500 flex-shrink-0 w-10">{unit}</span>}
    </div>
  )
}

function FieldRow({ label, hint, children }) {
  return (
    <div className="flex items-start gap-2 mb-1.5">
      <label className="text-[11px] text-ink-400 w-32 flex-shrink-0 pt-1.5 leading-tight">
        {label}
        {hint && <span className="block text-[10px] text-ink-600">{hint}</span>}
      </label>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  )
}

function ResultRow({ label, value, highlight }) {
  return (
    <div className={`flex justify-between items-center py-1 border-b border-ink-800/50`}>
      <span className="text-[11px] text-ink-400">{label}</span>
      <span className={`text-[11px] font-mono ${highlight ? 'text-kerf-300 font-semibold' : 'text-ink-200'}`}>
        {value}
      </span>
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

function RunButton({ loading, label, onClick }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="w-full h-8 bg-kerf-600 hover:bg-kerf-500 disabled:opacity-50 text-white text-xs font-medium rounded flex items-center justify-center gap-1.5 mt-3"
    >
      <Play size={11} />
      {loading ? 'Computing…' : label}
    </button>
  )
}

function ErrorAlert({ error }) {
  if (!error) return null
  return (
    <div className="flex items-start gap-2 mt-2 p-2 bg-amber-950/40 border border-amber-800/50 rounded text-[11px] text-amber-300">
      <AlertTriangle size={11} className="flex-shrink-0 mt-0.5" />
      {error}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Otto cycle sub-panel
// ---------------------------------------------------------------------------

function OttoPanel() {
  const [inp, setInp] = useState({ r: 9.0, T1: 300, T3: 2000, k: 1.4 })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const set = (k, v) => setInp((p) => ({ ...p, [k]: parseFloat(v) || v }))

  const run = useCallback(async () => {
    setLoading(true); setError(null); setResult(null)
    try {
      const r = await callTool('thermo_otto_cycle', { r: inp.r, T1: inp.T1, T3: inp.T3, k: inp.k })
      if (r.ok === false) { setError(r.reason); return }
      setResult(r)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [inp])

  return (
    <div>
      <div className="text-[10px] text-ink-600 mb-2">
        Air-standard Otto cycle (SI engine). η = 1 − 1/r^(k−1).
      </div>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="Compression ratio r"><NumInput value={inp.r} onChange={(v) => set('r', v)} min={1.1} step="0.1" /></FieldRow>
        <FieldRow label="T1 (BDC inlet)" hint="K"><NumInput value={inp.T1} onChange={(v) => set('T1', v)} min={200} unit="K" /></FieldRow>
        <FieldRow label="T3 (peak)" hint="K"><NumInput value={inp.T3} onChange={(v) => set('T3', v)} min={500} unit="K" /></FieldRow>
        <FieldRow label="k (γ = cp/cv)"><NumInput value={inp.k} onChange={(v) => set('k', v)} min={1.0} max={2.0} step="0.01" /></FieldRow>
      </div>
      <RunButton loading={loading} label="Compute Otto Cycle" onClick={run} />
      <ErrorAlert error={error} />
      {result && (
        <div className="mt-3">
          <SectionHeader>Results</SectionHeader>
          <ResultRow label="Thermal efficiency η" value={fmtPct(result.eta)} highlight />
          <ResultRow label="Net work w_net" value={fmtKJ(result.w_net_J_kg)} highlight />
          <ResultRow label="Heat in q_in" value={fmtKJ(result.q_in_J_kg)} />
          <ResultRow label="Heat out q_out" value={fmtKJ(result.q_out_J_kg)} />
          <ResultRow label="T2 (end compression)" value={`${fmt(result.T2_K, 1)} K`} />
          <ResultRow label="T3 (peak)" value={`${fmt(result.T3_K, 1)} K`} />
          <ResultRow label="T4 (end expansion)" value={`${fmt(result.T4_K, 1)} K`} />
          <ResultRow label="Back-work ratio" value={fmt(result.BWR, 4)} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Diesel cycle sub-panel
// ---------------------------------------------------------------------------

function DieselPanel() {
  const [inp, setInp] = useState({ r: 18.0, r_c: 2.0, T1: 300, k: 1.4 })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const set = (k, v) => setInp((p) => ({ ...p, [k]: parseFloat(v) || v }))

  const run = useCallback(async () => {
    setLoading(true); setError(null); setResult(null)
    try {
      const r = await callTool('thermo_diesel_cycle', { r: inp.r, r_c: inp.r_c, T1: inp.T1, k: inp.k })
      if (r.ok === false) { setError(r.reason); return }
      setResult(r)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [inp])

  return (
    <div>
      <div className="text-[10px] text-ink-600 mb-2">
        Air-standard Diesel cycle (CI engine). η = 1 − (r_c^k − 1)/(k·r^(k−1)·(r_c − 1)).
      </div>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="Compression ratio r"><NumInput value={inp.r} onChange={(v) => set('r', v)} min={1.1} step="0.5" /></FieldRow>
        <FieldRow label="Cutoff ratio r_c"><NumInput value={inp.r_c} onChange={(v) => set('r_c', v)} min={1.01} max={inp.r} step="0.1" /></FieldRow>
        <FieldRow label="T1 (inlet)" hint="K"><NumInput value={inp.T1} onChange={(v) => set('T1', v)} min={200} unit="K" /></FieldRow>
        <FieldRow label="k (γ)"><NumInput value={inp.k} onChange={(v) => set('k', v)} min={1.0} max={2.0} step="0.01" /></FieldRow>
      </div>
      <RunButton loading={loading} label="Compute Diesel Cycle" onClick={run} />
      <ErrorAlert error={error} />
      {result && (
        <div className="mt-3">
          <SectionHeader>Results</SectionHeader>
          <ResultRow label="Thermal efficiency η" value={fmtPct(result.eta)} highlight />
          <ResultRow label="Net work w_net" value={fmtKJ(result.w_net_J_kg)} highlight />
          <ResultRow label="Heat in q_in" value={fmtKJ(result.q_in_J_kg)} />
          <ResultRow label="T2 (end compression)" value={`${fmt(result.T2_K, 1)} K`} />
          <ResultRow label="T3 (peak)" value={`${fmt(result.T3_K, 1)} K`} />
          <ResultRow label="T4 (end expansion)" value={`${fmt(result.T4_K, 1)} K`} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Brayton cycle sub-panel
// ---------------------------------------------------------------------------

function BraytonPanel() {
  const [inp, setInp] = useState({
    r_p: 10.0, T1: 300, T3: 1400,
    k: 1.4, eta_c: 0.85, eta_t: 0.90, eta_regen: 0.0,
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const set = (k, v) => setInp((p) => ({ ...p, [k]: parseFloat(v) || v }))

  const run = useCallback(async () => {
    setLoading(true); setError(null); setResult(null)
    try {
      const r = await callTool('thermo_brayton_cycle', {
        r_p: inp.r_p, T1: inp.T1, T3: inp.T3,
        k: inp.k, eta_c: inp.eta_c, eta_t: inp.eta_t,
        ...(inp.eta_regen > 0 ? { eta_regen: inp.eta_regen } : {}),
      })
      if (r.ok === false) { setError(r.reason); return }
      setResult(r)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [inp])

  return (
    <div>
      <div className="text-[10px] text-ink-600 mb-2">
        Brayton cycle (gas turbine). Optional regeneration. Isentropic component efficiencies supported.
      </div>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="Pressure ratio r_p"><NumInput value={inp.r_p} onChange={(v) => set('r_p', v)} min={1.1} step="0.5" /></FieldRow>
        <FieldRow label="T1 (compressor in)" hint="K"><NumInput value={inp.T1} onChange={(v) => set('T1', v)} min={200} unit="K" /></FieldRow>
        <FieldRow label="T3 (turbine in)" hint="K"><NumInput value={inp.T3} onChange={(v) => set('T3', v)} min={500} unit="K" /></FieldRow>
        <FieldRow label="k (γ)"><NumInput value={inp.k} onChange={(v) => set('k', v)} min={1.0} max={2.0} step="0.01" /></FieldRow>
        <FieldRow label="η_compressor"><NumInput value={inp.eta_c} onChange={(v) => set('eta_c', v)} min={0.5} max={1.0} step="0.01" /></FieldRow>
        <FieldRow label="η_turbine"><NumInput value={inp.eta_t} onChange={(v) => set('eta_t', v)} min={0.5} max={1.0} step="0.01" /></FieldRow>
        <FieldRow label="η_regen" hint="0 = none"><NumInput value={inp.eta_regen} onChange={(v) => set('eta_regen', v)} min={0} max={0.99} step="0.05" /></FieldRow>
      </div>
      <RunButton loading={loading} label="Compute Brayton Cycle" onClick={run} />
      <ErrorAlert error={error} />
      {result && (
        <div className="mt-3">
          <SectionHeader>Results</SectionHeader>
          <ResultRow label="Thermal efficiency η" value={fmtPct(result.eta)} highlight />
          <ResultRow label="Net work w_net" value={fmtKJ(result.w_net_J_kg)} highlight />
          <ResultRow label="Back-work ratio BWR" value={fmtPct(result.BWR)} />
          <ResultRow label="w_compressor" value={fmtKJ(result.w_c_J_kg)} />
          <ResultRow label="w_turbine" value={fmtKJ(result.w_t_J_kg)} />
          <ResultRow label="q_in" value={fmtKJ(result.q_in_J_kg)} />
          <ResultRow label="T2s (ideal comp out)" value={`${fmt(result.T2s_K, 1)} K`} />
          <ResultRow label="T2 (actual comp out)" value={`${fmt(result.T2_K, 1)} K`} />
          <ResultRow label="T4s (ideal turb out)" value={`${fmt(result.T4s_K, 1)} K`} />
          <ResultRow label="T4 (actual turb out)" value={`${fmt(result.T4_K, 1)} K`} />
          {result.T_regen_K != null && (
            <ResultRow label="T after regenerator" value={`${fmt(result.T_regen_K, 1)} K`} />
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Rankine cycle sub-panel
// ---------------------------------------------------------------------------

function RankinePanel() {
  const [inp, setInp] = useState({
    p_high: 5_000_000,   // 5 MPa
    p_low: 10_000,       // 10 kPa
    T_superheat: null,
    eta_pump: 0.85,
    eta_turbine: 0.88,
    T_reheat: null,
    p_reheat: null,
  })
  const [useSuperheat, setUseSuperheat] = useState(false)
  const [useReheat, setUseReheat] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const set = (k, v) => setInp((p) => ({ ...p, [k]: v === '' ? null : (parseFloat(v) || null) }))

  const run = useCallback(async () => {
    setLoading(true); setError(null); setResult(null)
    try {
      const args = {
        p_high: inp.p_high,
        p_low: inp.p_low,
        eta_pump: inp.eta_pump,
        eta_turbine: inp.eta_turbine,
      }
      if (useSuperheat && inp.T_superheat) args.T_superheat = inp.T_superheat
      if (useReheat && inp.T_reheat) {
        args.T_reheat = inp.T_reheat
        if (inp.p_reheat) args.p_reheat = inp.p_reheat
      }
      const r = await callTool('thermo_rankine_cycle_ideal', args)
      if (r.ok === false) { setError(r.reason); return }
      setResult(r)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [inp, useSuperheat, useReheat])

  return (
    <div>
      <div className="text-[10px] text-ink-600 mb-2">
        Simplified ideal Rankine (steam) cycle. Antoine approximation for Tsat.
        For accurate steam tables, also see fluids_steam_if97.
      </div>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="p_high" hint="Pa"><NumInput value={inp.p_high} onChange={(v) => set('p_high', v)} min={0} unit="Pa" /></FieldRow>
        <FieldRow label="p_low" hint="Pa"><NumInput value={inp.p_low} onChange={(v) => set('p_low', v)} min={0} unit="Pa" /></FieldRow>
        <FieldRow label="η_pump"><NumInput value={inp.eta_pump} onChange={(v) => set('eta_pump', v)} min={0.5} max={1.0} step="0.01" /></FieldRow>
        <FieldRow label="η_turbine"><NumInput value={inp.eta_turbine} onChange={(v) => set('eta_turbine', v)} min={0.5} max={1.0} step="0.01" /></FieldRow>
      </div>

      {/* Options */}
      <div className="flex gap-3 mt-1 mb-2">
        <label className="flex items-center gap-1 text-[11px] text-ink-400 cursor-pointer">
          <input type="checkbox" checked={useSuperheat} onChange={(e) => setUseSuperheat(e.target.checked)} className="w-3 h-3" />
          Superheat
        </label>
        <label className="flex items-center gap-1 text-[11px] text-ink-400 cursor-pointer">
          <input type="checkbox" checked={useReheat} onChange={(e) => setUseReheat(e.target.checked)} className="w-3 h-3" />
          Reheat
        </label>
      </div>

      {useSuperheat && (
        <FieldRow label="T_superheat" hint="K">
          <NumInput value={inp.T_superheat ?? ''} onChange={(v) => set('T_superheat', v)} min={300} unit="K" />
        </FieldRow>
      )}
      {useReheat && (
        <div className="grid grid-cols-2 gap-x-3">
          <FieldRow label="T_reheat" hint="K"><NumInput value={inp.T_reheat ?? ''} onChange={(v) => set('T_reheat', v)} min={300} unit="K" /></FieldRow>
          <FieldRow label="p_reheat" hint="Pa"><NumInput value={inp.p_reheat ?? ''} onChange={(v) => set('p_reheat', v)} min={0} unit="Pa" /></FieldRow>
        </div>
      )}

      <RunButton loading={loading} label="Compute Rankine Cycle" onClick={run} />
      <ErrorAlert error={error} />
      {result && (
        <div className="mt-3">
          <SectionHeader>Results</SectionHeader>
          <ResultRow label="Thermal efficiency η" value={fmtPct(result.eta)} highlight />
          <ResultRow label="Net work w_net" value={fmtKJ(result.w_net_J_kg)} highlight />
          <ResultRow label="Turbine work w_t" value={fmtKJ(result.w_t_J_kg)} />
          <ResultRow label="Pump work w_p" value={fmtKJ(result.w_p_J_kg)} />
          <ResultRow label="Heat added q_in" value={fmtKJ(result.q_in_J_kg)} />
          <ResultRow label="T_sat (high p)" value={`${fmt(result.T_sat_high_K, 1)} K`} />
          <ResultRow label="T_sat (low p)" value={`${fmt(result.T_sat_low_K, 1)} K`} />
          <ResultRow label="Carnot η (ref)" value={fmtPct(result.eta_carnot)} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Carnot sub-panel
// ---------------------------------------------------------------------------

function CarnotPanel() {
  const [inp, setInp] = useState({ T_H: 1000, T_L: 300 })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const set = (k, v) => setInp((p) => ({ ...p, [k]: parseFloat(v) || v }))

  const run = useCallback(async () => {
    setLoading(true); setError(null); setResult(null)
    try {
      const r = await callTool('thermo_carnot_efficiency', { T_H: inp.T_H, T_L: inp.T_L })
      if (r.ok === false) { setError(r.reason); return }
      // Also compute COP_R and COP_HP
      const [rr, rHP] = await Promise.all([
        callTool('thermo_carnot_cop_refrigeration', { T_H: inp.T_H, T_L: inp.T_L }),
        callTool('thermo_carnot_cop_heat_pump', { T_H: inp.T_H, T_L: inp.T_L }),
      ])
      setResult({ ...r, COP_R: rr.COP_R, COP_HP: rHP.COP_HP })
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [inp])

  return (
    <div>
      <div className="text-[10px] text-ink-600 mb-2">
        Carnot upper bound for heat engine + reverse-Carnot limits for refrigerator and heat pump.
      </div>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="T_H (hot reservoir)" hint="K">
          <NumInput value={inp.T_H} onChange={(v) => set('T_H', v)} min={1} unit="K" />
        </FieldRow>
        <FieldRow label="T_L (cold reservoir)" hint="K">
          <NumInput value={inp.T_L} onChange={(v) => set('T_L', v)} min={1} unit="K" />
        </FieldRow>
      </div>
      <RunButton loading={loading} label="Compute Carnot Limits" onClick={run} />
      <ErrorAlert error={error} />
      {result && (
        <div className="mt-3">
          <SectionHeader>Results</SectionHeader>
          <ResultRow label="Carnot η (heat engine)" value={fmtPct(result.eta_carnot)} highlight />
          <ResultRow label="COP_R (refrigerator)" value={fmt(result.COP_R)} highlight />
          <ResultRow label="COP_HP (heat pump)" value={fmt(result.COP_HP)} highlight />
          <ResultRow label="T_H" value={`${fmt(result.T_H_K ?? inp.T_H, 1)} K`} />
          <ResultRow label="T_L" value={`${fmt(result.T_L_K ?? inp.T_L, 1)} K`} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

const CYCLES = [
  { id: 'otto',    label: 'Otto (SI)' },
  { id: 'diesel',  label: 'Diesel (CI)' },
  { id: 'brayton', label: 'Brayton (GT)' },
  { id: 'rankine', label: 'Rankine' },
  { id: 'carnot',  label: 'Carnot' },
]

export default function ThermoCyclePanel({ projectId: _projectId }) {
  const [cycle, setCycle] = useState('brayton')

  return (
    <div className="flex flex-col h-full overflow-hidden text-ink-200">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-800">
        <Activity size={13} className="text-kerf-300" />
        <span className="text-xs font-semibold text-ink-100">Thermodynamic Cycles</span>
        <div className="flex items-center gap-1 ml-1" title="Otto / Diesel / Brayton / Rankine / Carnot — Cengel & Boles 8th ed.">
          <Info size={10} className="text-ink-600" />
        </div>
      </div>

      {/* Cycle tabs */}
      <div className="flex border-b border-ink-800 overflow-x-auto">
        {CYCLES.map((c) => (
          <button
            key={c.id}
            onClick={() => setCycle(c.id)}
            className={`px-3 py-1.5 text-[11px] font-medium border-b-2 transition-colors whitespace-nowrap ${
              cycle === c.id
                ? 'border-kerf-400 text-kerf-300'
                : 'border-transparent text-ink-500 hover:text-ink-300'
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-3 py-2 min-h-0">
        {cycle === 'otto'    && <OttoPanel />}
        {cycle === 'diesel'  && <DieselPanel />}
        {cycle === 'brayton' && <BraytonPanel />}
        {cycle === 'rankine' && <RankinePanel />}
        {cycle === 'carnot'  && <CarnotPanel />}
      </div>
    </div>
  )
}
