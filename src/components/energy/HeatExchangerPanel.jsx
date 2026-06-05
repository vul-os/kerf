/**
 * HeatExchangerPanel.jsx — Heat Exchanger design via LMTD and ε-NTU methods.
 *
 * Wraps the kerf LLM tools:
 *   hx_lmtd                  — LMTD sizing (Q = U·A·F·ΔTlm)
 *   hx_effectiveness_ntu     — ε-NTU method
 *   hx_shell_tube_bell_delaware — full Bell-Delaware S&T design
 *
 * References: Incropera §11; Bell-Delaware method; TEMA standards.
 *
 * Props: { projectId?: string }
 */

import { useState, useCallback } from 'react'
import { Waves, Play, AlertTriangle, ChevronDown, ChevronUp, Info } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Utility: POST /api/tools/call
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(n, dp = 3) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(dp)
}

function fmtSI(n, unit, dp = 2) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${n.toFixed(dp)} ${unit}`
}

function NumInput({ value, onChange, min, step = 'any', disabled, placeholder, unit }) {
  return (
    <div className="flex items-center gap-1">
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        min={min}
        step={step}
        disabled={disabled}
        placeholder={placeholder}
        className="w-full h-7 bg-ink-900 border border-ink-800 rounded px-2 text-xs text-ink-100 focus:outline-none focus:border-kerf-300 focus-visible:ring-1 focus-visible:ring-kerf-300 disabled:opacity-50 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
      />
      {unit && <span className="text-[10px] text-ink-500 flex-shrink-0">{unit}</span>}
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
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
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
    <div className={`flex justify-between items-center py-1 border-b border-ink-800/50 ${highlight ? 'text-kerf-300' : ''}`}>
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
// Method tabs
// ---------------------------------------------------------------------------

const METHODS = [
  { id: 'lmtd',   label: 'LMTD' },
  { id: 'entu',   label: 'ε-NTU' },
  { id: 'bell_delaware', label: 'Bell-Delaware S&T' },
]

const FLOW_OPTIONS = [
  { value: 'counter',           label: 'Counter-flow' },
  { value: 'parallel',          label: 'Parallel-flow' },
  { value: 'crossflow_unmixed', label: 'Cross-flow (unmixed)' },
]

// ---------------------------------------------------------------------------
// LMTD method panel
// ---------------------------------------------------------------------------

function LMTDPanel() {
  const [inputs, setInputs] = useState({
    T_h_in: 353.15,   // 80°C
    T_h_out: 323.15,  // 50°C
    T_c_in: 293.15,   // 20°C
    T_c_out: 333.15,  // 60°C
    U: 500,
    A: 10,
    flow: 'counter',
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k, v) => setInputs((prev) => ({ ...prev, [k]: parseFloat(v) || v }))

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const r = await callTool('hx_lmtd', {
        T_h_in: inputs.T_h_in,
        T_h_out: inputs.T_h_out,
        T_c_in: inputs.T_c_in,
        T_c_out: inputs.T_c_out,
        U: inputs.U,
        A: inputs.A,
        flow: inputs.flow,
      })
      setResult(r.ok === false ? null : r)
      if (r.ok === false) setError(r.reason || 'Computation failed')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [inputs])

  return (
    <div className="space-y-0.5">
      <SectionHeader>Temperatures</SectionHeader>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="Hot inlet T" hint="K">
          <NumInput value={inputs.T_h_in} onChange={(v) => set('T_h_in', v)} min={0} unit="K" />
        </FieldRow>
        <FieldRow label="Hot outlet T" hint="K">
          <NumInput value={inputs.T_h_out} onChange={(v) => set('T_h_out', v)} min={0} unit="K" />
        </FieldRow>
        <FieldRow label="Cold inlet T" hint="K">
          <NumInput value={inputs.T_c_in} onChange={(v) => set('T_c_in', v)} min={0} unit="K" />
        </FieldRow>
        <FieldRow label="Cold outlet T" hint="K">
          <NumInput value={inputs.T_c_out} onChange={(v) => set('T_c_out', v)} min={0} unit="K" />
        </FieldRow>
      </div>

      <SectionHeader>HX Parameters</SectionHeader>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="Overall U" hint="W/(m²·K)">
          <NumInput value={inputs.U} onChange={(v) => set('U', v)} min={0} unit="W/m²K" />
        </FieldRow>
        <FieldRow label="HX area A" hint="m²">
          <NumInput value={inputs.A} onChange={(v) => set('A', v)} min={0} unit="m²" />
        </FieldRow>
      </div>

      <SectionHeader>Flow Arrangement</SectionHeader>
      <div className="mb-2">
        <SelectInput
          value={inputs.flow}
          onChange={(v) => set('flow', v)}
          options={FLOW_OPTIONS}
        />
      </div>

      <button
        onClick={run}
        disabled={loading}
        className="w-full h-8 bg-kerf-600 hover:bg-kerf-500 disabled:opacity-50 text-white text-xs font-medium rounded flex items-center justify-center gap-1.5 mt-2"
      >
        <Play size={11} />
        {loading ? 'Computing…' : 'Compute LMTD'}
      </button>

      {error && (
        <div className="flex items-start gap-2 mt-2 p-2 bg-amber-950/40 border border-amber-800/50 rounded text-[11px] text-amber-300">
          <AlertTriangle size={11} className="flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 space-y-0.5">
          <SectionHeader>Results</SectionHeader>
          <ResultRow label="Heat transfer Q" value={fmtSI(result.Q_W, 'W', 0)} highlight />
          <ResultRow label="LMTD" value={fmtSI(result.LMTD_K, 'K')} highlight />
          <ResultRow label="Correction factor F" value={fmt(result.F)} />
          <ResultRow label="ΔT₁" value={fmtSI(result.deltaT1, 'K')} />
          <ResultRow label="ΔT₂" value={fmtSI(result.deltaT2, 'K')} />
          <ResultRow label="Flow arrangement" value={result.flow} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ε-NTU method panel
// ---------------------------------------------------------------------------

function ENTUPanel() {
  const [inputs, setInputs] = useState({
    C_min: 1000,
    C_max: 2000,
    NTU: 2.0,
    flow: 'counter',
    T_h_in: 353.15,
    T_c_in: 293.15,
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k, v) => setInputs((prev) => ({ ...prev, [k]: parseFloat(v) || v }))

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const r = await callTool('hx_effectiveness_ntu', {
        C_min: inputs.C_min,
        C_max: inputs.C_max,
        NTU: inputs.NTU,
        flow: inputs.flow,
      })
      setResult(r.ok === false ? null : r)
      if (r.ok === false) setError(r.reason || 'Computation failed')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [inputs])

  // Compute Q if temperatures are provided
  const Q = result
    ? result.epsilon * inputs.C_min * (inputs.T_h_in - inputs.T_c_in)
    : null

  return (
    <div className="space-y-0.5">
      <SectionHeader>Heat Capacity Rates</SectionHeader>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="C_min" hint="W/K">
          <NumInput value={inputs.C_min} onChange={(v) => set('C_min', v)} min={0} unit="W/K" />
        </FieldRow>
        <FieldRow label="C_max" hint="W/K">
          <NumInput value={inputs.C_max} onChange={(v) => set('C_max', v)} min={0} unit="W/K" />
        </FieldRow>
      </div>

      <SectionHeader>NTU + Flow</SectionHeader>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="NTU">
          <NumInput value={inputs.NTU} onChange={(v) => set('NTU', v)} min={0} step="0.1" />
        </FieldRow>
        <FieldRow label="Flow">
          <SelectInput
            value={inputs.flow}
            onChange={(v) => set('flow', v)}
            options={FLOW_OPTIONS}
          />
        </FieldRow>
      </div>

      <SectionHeader>Temperatures (optional Q)</SectionHeader>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="Hot inlet T" hint="K">
          <NumInput value={inputs.T_h_in} onChange={(v) => set('T_h_in', v)} min={0} unit="K" />
        </FieldRow>
        <FieldRow label="Cold inlet T" hint="K">
          <NumInput value={inputs.T_c_in} onChange={(v) => set('T_c_in', v)} min={0} unit="K" />
        </FieldRow>
      </div>

      <button
        onClick={run}
        disabled={loading}
        className="w-full h-8 bg-kerf-600 hover:bg-kerf-500 disabled:opacity-50 text-white text-xs font-medium rounded flex items-center justify-center gap-1.5 mt-2"
      >
        <Play size={11} />
        {loading ? 'Computing…' : 'Compute ε-NTU'}
      </button>

      {error && (
        <div className="flex items-start gap-2 mt-2 p-2 bg-amber-950/40 border border-amber-800/50 rounded text-[11px] text-amber-300">
          <AlertTriangle size={11} className="flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 space-y-0.5">
          <SectionHeader>Results</SectionHeader>
          <ResultRow label="Effectiveness ε" value={fmt(result.epsilon, 4)} highlight />
          <ResultRow label="C_r = C_min/C_max" value={fmt(result.C_r, 4)} />
          <ResultRow label="NTU" value={fmt(result.NTU)} />
          <ResultRow label="C_min" value={fmtSI(result.C_min, 'W/K')} />
          <ResultRow label="C_max" value={fmtSI(result.C_max, 'W/K')} />
          <ResultRow label="Flow" value={result.flow} />
          {Q != null && Number.isFinite(Q) && (
            <ResultRow label="Q (at given ΔT)" value={fmtSI(Q, 'W', 0)} highlight />
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Bell-Delaware shell-and-tube panel (simplified inputs)
// ---------------------------------------------------------------------------

function BellDelawarePanel() {
  const [inputs, setInputs] = useState({
    duty_W: 1_000_000,
    t_hot_in: 80,   // °C
    t_hot_out: 50,
    t_cold_in: 20,
    t_cold_out: 60,
    // Shell-side (kerosene-like)
    shell_rho: 820, shell_mu: 2e-3, shell_cp: 2000, shell_k: 0.15,
    shell_m_dot: 50,
    // Tube-side (water)
    tube_rho: 995, tube_mu: 8e-4, tube_cp: 4180, tube_k: 0.62,
    tube_m_dot: 60,
    // Geometry
    D_s: 0.50, tube_od: 0.0254, tube_id: 0.02, pitch: 0.032,
    layout: 'triangular_30', L_tube: 3.0, N_t: 100,
    n_passes: 2, N_b: 20, B: 0.25, baffle_cut: 0.25,
    k_wall: 50.0, R_foul_t: 0.0002, R_foul_s: 0.0002,
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const set = (k, v) => setInputs((prev) => ({ ...prev, [k]: parseFloat(v) || v }))

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const r = await callTool('hx_shell_tube_bell_delaware', {
        duty_W: inputs.duty_W,
        t_hot_in: inputs.t_hot_in,
        t_hot_out: inputs.t_hot_out,
        t_cold_in: inputs.t_cold_in,
        t_cold_out: inputs.t_cold_out,
        shell_props: {
          rho: inputs.shell_rho, mu: inputs.shell_mu,
          cp: inputs.shell_cp, k: inputs.shell_k,
          m_dot: inputs.shell_m_dot,
        },
        tube_props: {
          rho: inputs.tube_rho, mu: inputs.tube_mu,
          cp: inputs.tube_cp, k: inputs.tube_k,
          m_dot: inputs.tube_m_dot,
        },
        geometry: {
          D_s: inputs.D_s, tube_od: inputs.tube_od,
          tube_id: inputs.tube_id, pitch: inputs.pitch,
          layout: inputs.layout, L_tube: inputs.L_tube,
          N_t: Math.round(inputs.N_t), n_passes: Math.round(inputs.n_passes),
          N_b: Math.round(inputs.N_b), B: inputs.B,
          baffle_cut: inputs.baffle_cut, k_wall: inputs.k_wall,
          R_foul_t: inputs.R_foul_t, R_foul_s: inputs.R_foul_s,
        },
      })
      setResult(r.ok === false ? null : r)
      if (r.ok === false) setError(r.reason || 'Computation failed')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [inputs])

  const LAYOUT_OPTIONS = [
    { value: 'triangular_30', label: '30° Triangular' },
    { value: 'rotated_60',    label: '60° Rotated' },
    { value: 'square_90',     label: '90° Square' },
    { value: 'rotated_45',    label: '45° Rotated' },
  ]

  return (
    <div className="space-y-0.5">
      <SectionHeader>Duty + Terminal Temperatures</SectionHeader>
      <FieldRow label="Duty" hint="W">
        <NumInput value={inputs.duty_W} onChange={(v) => set('duty_W', v)} min={0} unit="W" />
      </FieldRow>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="Hot in" hint="°C">
          <NumInput value={inputs.t_hot_in} onChange={(v) => set('t_hot_in', v)} unit="°C" />
        </FieldRow>
        <FieldRow label="Hot out" hint="°C">
          <NumInput value={inputs.t_hot_out} onChange={(v) => set('t_hot_out', v)} unit="°C" />
        </FieldRow>
        <FieldRow label="Cold in" hint="°C">
          <NumInput value={inputs.t_cold_in} onChange={(v) => set('t_cold_in', v)} unit="°C" />
        </FieldRow>
        <FieldRow label="Cold out" hint="°C">
          <NumInput value={inputs.t_cold_out} onChange={(v) => set('t_cold_out', v)} unit="°C" />
        </FieldRow>
      </div>

      <SectionHeader>Geometry</SectionHeader>
      <div className="grid grid-cols-2 gap-x-3">
        <FieldRow label="Shell ID" hint="m">
          <NumInput value={inputs.D_s} onChange={(v) => set('D_s', v)} min={0} unit="m" />
        </FieldRow>
        <FieldRow label="Tube OD" hint="m">
          <NumInput value={inputs.tube_od} onChange={(v) => set('tube_od', v)} min={0} unit="m" />
        </FieldRow>
        <FieldRow label="Tube pitch" hint="m">
          <NumInput value={inputs.pitch} onChange={(v) => set('pitch', v)} min={0} unit="m" />
        </FieldRow>
        <FieldRow label="Tube count">
          <NumInput value={inputs.N_t} onChange={(v) => set('N_t', v)} min={1} step={1} />
        </FieldRow>
        <FieldRow label="Tube passes">
          <NumInput value={inputs.n_passes} onChange={(v) => set('n_passes', v)} min={1} step={1} />
        </FieldRow>
        <FieldRow label="Layout">
          <SelectInput value={inputs.layout} onChange={(v) => setInputs((p) => ({...p, layout: v}))} options={LAYOUT_OPTIONS} />
        </FieldRow>
      </div>

      {/* Advanced section */}
      <button
        type="button"
        onClick={() => setAdvancedOpen((v) => !v)}
        className="flex items-center gap-1 text-[10px] text-ink-500 hover:text-ink-300 mt-2"
      >
        {advancedOpen ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
        Fluid properties + baffles
      </button>

      {advancedOpen && (
        <div className="mt-1 space-y-0.5 pl-2 border-l border-ink-800">
          <SectionHeader>Shell-side fluid</SectionHeader>
          <div className="grid grid-cols-2 gap-x-3">
            <FieldRow label="ρ" hint="kg/m³"><NumInput value={inputs.shell_rho} onChange={(v) => set('shell_rho', v)} min={0} /></FieldRow>
            <FieldRow label="μ" hint="Pa·s"><NumInput value={inputs.shell_mu} onChange={(v) => set('shell_mu', v)} min={0} step="0.0001" /></FieldRow>
            <FieldRow label="cp" hint="J/kg·K"><NumInput value={inputs.shell_cp} onChange={(v) => set('shell_cp', v)} min={0} /></FieldRow>
            <FieldRow label="k" hint="W/m·K"><NumInput value={inputs.shell_k} onChange={(v) => set('shell_k', v)} min={0} /></FieldRow>
            <FieldRow label="ṁ" hint="kg/s"><NumInput value={inputs.shell_m_dot} onChange={(v) => set('shell_m_dot', v)} min={0} /></FieldRow>
          </div>
          <SectionHeader>Tube-side fluid</SectionHeader>
          <div className="grid grid-cols-2 gap-x-3">
            <FieldRow label="ρ" hint="kg/m³"><NumInput value={inputs.tube_rho} onChange={(v) => set('tube_rho', v)} min={0} /></FieldRow>
            <FieldRow label="μ" hint="Pa·s"><NumInput value={inputs.tube_mu} onChange={(v) => set('tube_mu', v)} min={0} step="0.0001" /></FieldRow>
            <FieldRow label="cp" hint="J/kg·K"><NumInput value={inputs.tube_cp} onChange={(v) => set('tube_cp', v)} min={0} /></FieldRow>
            <FieldRow label="k" hint="W/m·K"><NumInput value={inputs.tube_k} onChange={(v) => set('tube_k', v)} min={0} /></FieldRow>
            <FieldRow label="ṁ" hint="kg/s"><NumInput value={inputs.tube_m_dot} onChange={(v) => set('tube_m_dot', v)} min={0} /></FieldRow>
          </div>
          <SectionHeader>Baffles + fouling</SectionHeader>
          <div className="grid grid-cols-2 gap-x-3">
            <FieldRow label="N baffles"><NumInput value={inputs.N_b} onChange={(v) => set('N_b', v)} min={1} step={1} /></FieldRow>
            <FieldRow label="Baffle spacing" hint="m"><NumInput value={inputs.B} onChange={(v) => set('B', v)} min={0} /></FieldRow>
            <FieldRow label="Baffle cut %"><NumInput value={inputs.baffle_cut} onChange={(v) => set('baffle_cut', v)} min={0.1} max={0.5} step="0.05" /></FieldRow>
            <FieldRow label="R_foul shell" hint="m²K/W"><NumInput value={inputs.R_foul_s} onChange={(v) => set('R_foul_s', v)} min={0} step="0.0001" /></FieldRow>
          </div>
        </div>
      )}

      <button
        onClick={run}
        disabled={loading}
        className="w-full h-8 bg-kerf-600 hover:bg-kerf-500 disabled:opacity-50 text-white text-xs font-medium rounded flex items-center justify-center gap-1.5 mt-3"
      >
        <Play size={11} />
        {loading ? 'Computing…' : 'Run Bell-Delaware Design'}
      </button>

      {error && (
        <div className="flex items-start gap-2 mt-2 p-2 bg-amber-950/40 border border-amber-800/50 rounded text-[11px] text-amber-300">
          <AlertTriangle size={11} className="flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {result && (
        <div className="mt-3 space-y-0.5">
          <SectionHeader>Overall Performance</SectionHeader>
          <ResultRow label="Overall U" value={fmtSI(result.U_W_m2K, 'W/m²K')} highlight />
          <ResultRow label="Required area" value={fmtSI(result.A_req_m2, 'm²')} highlight />
          <ResultRow label="Actual area" value={fmtSI(result.A_actual_m2, 'm²')} />
          <ResultRow label="Over-design" value={result.overdesign != null ? `${(result.overdesign * 100).toFixed(1)}%` : '—'} />
          <ResultRow label="LMTD" value={fmtSI(result.LMTD_K, 'K')} />
          <SectionHeader>Coefficients</SectionHeader>
          <ResultRow label="h_shell (Bell-Delaware)" value={fmtSI(result.h_s_W_m2K, 'W/m²K')} />
          <ResultRow label="h_tube (Dittus-Boelter)" value={fmtSI(result.h_t_W_m2K, 'W/m²K')} />
          <ResultRow label="Re_tube" value={result.Re_t?.toFixed(0) ?? '—'} />
          <ResultRow label="Re_shell" value={result.Re_s?.toFixed(0) ?? '—'} />
          <SectionHeader>Geometry</SectionHeader>
          <ResultRow label="N_tubes" value={result.N_tubes} />
          <ResultRow label="N_baffles" value={result.N_baffles} />
          <SectionHeader>Pressure Drop</SectionHeader>
          <ResultRow label="ΔP tube-side" value={fmtSI(result.dP_tube_Pa, 'Pa', 0)} />
          <ResultRow label="ΔP shell-side" value={fmtSI(result.dP_shell_Pa, 'Pa', 0)} />
          {result.factors && (
            <>
              <SectionHeader>Bell-Delaware Factors</SectionHeader>
              <ResultRow label="Jc (baffle cut)" value={fmt(result.factors.Jc)} />
              <ResultRow label="Jl (leakage)" value={fmt(result.factors.Jl)} />
              <ResultRow label="Jb (bypass)" value={fmt(result.factors.Jb)} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

export default function HeatExchangerPanel({ projectId: _projectId }) {
  const [method, setMethod] = useState('lmtd')

  return (
    <div className="flex flex-col h-full overflow-hidden text-ink-200">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-800">
        <Waves size={13} className="text-kerf-300" />
        <span className="text-xs font-semibold text-ink-100">Heat Exchanger Design</span>
        <div className="flex items-center gap-1 ml-1" title="LMTD + ε-NTU + Bell-Delaware per Incropera §11 / TEMA">
          <Info size={10} className="text-ink-600" />
        </div>
      </div>

      {/* Method tabs */}
      <div className="flex border-b border-ink-800">
        {METHODS.map((m) => (
          <button
            key={m.id}
            onClick={() => setMethod(m.id)}
            className={`px-3 py-1.5 text-[11px] font-medium border-b-2 transition-colors ${
              method === m.id
                ? 'border-kerf-400 text-kerf-300'
                : 'border-transparent text-ink-500 hover:text-ink-300'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-3 py-2 min-h-0">
        {method === 'lmtd' && <LMTDPanel />}
        {method === 'entu' && <ENTUPanel />}
        {method === 'bell_delaware' && <BellDelawarePanel />}
      </div>
    </div>
  )
}
