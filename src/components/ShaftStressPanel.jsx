/**
 * ShaftStressPanel — Shaft stress, sizing & critical speed calculator.
 *
 * Two modes:
 *   "stress"  — shaft_diameter: combined bending + torsion (DE-Goodman / Tresca)
 *               per ASME B106.1M-1985 and Shigley's §§ 6-14, 11-9.
 *   "critical" — shaft_critical_speed: first lateral whirl Ncr for a uniform shaft.
 *               Rayleigh–Ritz / Dunkerley: simply-supported or fixed-fixed.
 *
 * References
 * ----------
 * ASME B106.1M-1985 — Design of Transmission Shafting
 * Shigley's Mechanical Engineering Design, 10th ed., §§ 6-12 to 6-16, 7-2
 *
 * Props
 * -----
 * onToast  (msg) => void  — optional
 */

import { useState } from 'react'
import { Zap, ChevronDown, ChevronRight, Loader2, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api.js'

// ---------------------------------------------------------------------------
// Pure helpers — export for tests
// ---------------------------------------------------------------------------

/**
 * Format a number to `dp` decimal places; returns '—' for falsy/NaN/Infinity.
 * @param {number|null|undefined} v
 * @param {number} dp
 */
export function fmtNum(v, dp = 3) {
  if (v == null || !isFinite(v)) return '—'
  return v.toFixed(dp)
}

/**
 * Build the shaft_diameter params from form state.
 * @param {object} s
 */
export function buildShaftDiamParams(s) {
  return {
    M: parseFloat(s.M) || 0,
    T: parseFloat(s.T) || 0,
    sigma_allow: parseFloat(s.sigma_allow) || 0,
    method: s.method || 'DE-Goodman',
    Kf: parseFloat(s.Kf) || 1.0,
    Kfs: parseFloat(s.Kfs) || 1.0,
    safety_factor: parseFloat(s.safety_factor) || 1.5,
  }
}

/**
 * Build shaft_critical_speed params from form state.
 * @param {object} s
 */
export function buildCritSpeedParams(s) {
  return {
    length_m: parseFloat(s.length_m) || 0,
    mass_per_m: parseFloat(s.mass_per_m) || 0,
    E: parseFloat(s.E) || 200e9,
    I: parseFloat(s.I) || 0,
    supports: s.supports || 'simply-supported',
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function FieldRow({ label, children, hint }) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <label className="text-[11px] text-ink-400 w-36 flex-shrink-0">{label}</label>
      <div className="flex-1">{children}</div>
      {hint && <span className="text-[10px] text-ink-600 flex-shrink-0">{hint}</span>}
    </div>
  )
}

function NumInput({ value, onChange, placeholder, min, step, 'data-testid': testid }) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      min={min}
      step={step}
      data-testid={testid}
      className="w-full bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:ring-1 focus:ring-kerf-300/60"
    />
  )
}

function SelectInput({ value, onChange, options, 'data-testid': testid }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      data-testid={testid}
      className="w-full bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:ring-1 focus:ring-kerf-300/60"
    >
      {options.map(([v, label]) => (
        <option key={v} value={v}>{label}</option>
      ))}
    </select>
  )
}

function ResultKV({ label, value, unit }) {
  return (
    <div className="flex items-center justify-between py-0.5 border-b border-ink-900">
      <span className="text-[11px] text-ink-400">{label}</span>
      <span className="text-[11px] text-ink-100 font-mono">
        {value}{unit ? <span className="text-ink-500 ml-1">{unit}</span> : null}
      </span>
    </div>
  )
}

function WarningList({ warnings }) {
  if (!warnings?.length) return null
  return (
    <div className="mt-2 space-y-0.5">
      {warnings.map((w, i) => (
        <div key={i} className="flex items-start gap-1 text-[10px] text-amber-400/80">
          <AlertTriangle size={10} className="mt-0.5 flex-shrink-0" />
          {w}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode: shaft_diameter
// ---------------------------------------------------------------------------

function StressMode({ onToast }) {
  const [form, setForm] = useState({
    M: '200', T: '150', sigma_allow: '200e6',
    method: 'DE-Goodman', Kf: '1.5', Kfs: '1.3', safety_factor: '1.5',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  function set(k) {
    return (v) => setForm((f) => ({ ...f, [k]: v }))
  }

  async function run() {
    setLoading(true)
    setResult(null)
    try {
      const data = await api.callTool('shaft_diameter', buildShaftDiamParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.(e?.message || 'shaft_diameter failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="shaft-stress-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        ASME B106 / Shigley §7-2: combined bending + torsion; DE-Goodman or Tresca
      </p>
      <FieldRow label="Bending moment M" hint="N·m">
        <NumInput value={form.M} onChange={set('M')} min={0} placeholder="200" data-testid="sd-M" />
      </FieldRow>
      <FieldRow label="Torsional moment T" hint="N·m">
        <NumInput value={form.T} onChange={set('T')} min={0} placeholder="150" data-testid="sd-T" />
      </FieldRow>
      <FieldRow label="σ_allow (Se or σ_b)" hint="Pa">
        <NumInput value={form.sigma_allow} onChange={set('sigma_allow')} min={1} placeholder="200e6" data-testid="sd-sigma" />
      </FieldRow>
      <FieldRow label="Method">
        <SelectInput value={form.method} onChange={set('method')} data-testid="sd-method"
          options={[['DE-Goodman', 'DE-Goodman (fatigue)'], ['max-shear', 'Max-shear (Tresca)']]} />
      </FieldRow>
      <FieldRow label="Kf (fatigue SCF)" hint="≥1">
        <NumInput value={form.Kf} onChange={set('Kf')} min={1} step={0.1} placeholder="1.5" data-testid="sd-Kf" />
      </FieldRow>
      <FieldRow label="Kfs (torsion SCF)" hint="≥1">
        <NumInput value={form.Kfs} onChange={set('Kfs')} min={1} step={0.1} placeholder="1.3" data-testid="sd-Kfs" />
      </FieldRow>
      <FieldRow label="Safety factor n" hint="">
        <NumInput value={form.safety_factor} onChange={set('safety_factor')} min={1} step={0.1} placeholder="1.5" data-testid="sd-n" />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="shaft-stress-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
        Compute Required Diameter
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="shaft-stress-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="d_required" value={fmtNum((result.diameter_m ?? 0) * 1000, 2)} unit="mm" />
              <ResultKV label="d_required" value={fmtNum(result.diameter_m, 5)} unit="m" />
              <ResultKV label="Von Mises σ′" value={result.von_mises_Pa != null ? fmtNum(result.von_mises_Pa / 1e6, 1) : '—'} unit="MPa" />
              <WarningList warnings={result.warnings} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode: shaft_critical_speed
// ---------------------------------------------------------------------------

function CritSpeedMode({ onToast }) {
  const [form, setForm] = useState({
    length_m: '1.0', mass_per_m: '7.85', E: '200e9', I: '1e-7',
    supports: 'simply-supported',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  function set(k) {
    return (v) => setForm((f) => ({ ...f, [k]: v }))
  }

  async function run() {
    setLoading(true)
    setResult(null)
    try {
      const data = await api.callTool('shaft_critical_speed', buildCritSpeedParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.(e?.message || 'shaft_critical_speed failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="shaft-critspeed-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        First lateral whirl Ncr — Rayleigh–Ritz / Dunkerley (Shigley §7-3)
      </p>
      <FieldRow label="Shaft length" hint="m">
        <NumInput value={form.length_m} onChange={set('length_m')} min={0.001} placeholder="1.0" data-testid="cs-length" />
      </FieldRow>
      <FieldRow label="Mass per metre" hint="kg/m">
        <NumInput value={form.mass_per_m} onChange={set('mass_per_m')} min={0.001} placeholder="7.85" data-testid="cs-mass" />
      </FieldRow>
      <FieldRow label="E (Young's)" hint="Pa">
        <NumInput value={form.E} onChange={set('E')} min={1} placeholder="200e9" data-testid="cs-E" />
      </FieldRow>
      <FieldRow label="I (2nd moment)" hint="m⁴">
        <NumInput value={form.I} onChange={set('I')} min={1e-12} step={1e-8} placeholder="1e-7" data-testid="cs-I" />
      </FieldRow>
      <FieldRow label="Support type">
        <SelectInput value={form.supports} onChange={set('supports')} data-testid="cs-supports"
          options={[['simply-supported', 'Simply supported'], ['fixed-fixed', 'Fixed–fixed']]} />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="shaft-critspeed-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
        Compute Critical Speed
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="shaft-critspeed-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="N_cr" value={fmtNum(result.Ncr_rpm, 0)} unit="rpm" />
              <ResultKV label="ω_cr" value={fmtNum(result.omega_cr_rads, 1)} unit="rad/s" />
              <WarningList warnings={result.warnings} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const MODES = [
  ['stress', 'Stress & Sizing'],
  ['critical', 'Critical Speed'],
]

export default function ShaftStressPanel({ onToast }) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState('stress')

  return (
    <div className="border-t border-ink-800 flex-shrink-0" data-testid="shaft-stress-panel">
      <div className="flex items-center px-3 py-1.5 gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 text-[11px] text-ink-400 hover:text-kerf-300 flex-1 min-w-0"
          aria-expanded={open}
          aria-controls="shaft-panel-body"
          data-testid="shaft-panel-toggle">
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          <Zap size={12} className="text-ink-500" />
          <span className="font-medium">Shaft Stress &amp; Critical Speed</span>
        </button>
      </div>

      {open && (
        <div id="shaft-panel-body" className="px-3 pb-3" data-testid="shaft-panel-body">
          <div className="flex gap-1 mb-2">
            {MODES.map(([k, label]) => (
              <button key={k} type="button"
                onClick={() => setMode(k)}
                data-testid={`shaft-mode-${k}`}
                className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                  mode === k
                    ? 'bg-kerf-300/20 text-kerf-300'
                    : 'bg-ink-800 text-ink-400 hover:bg-ink-700'
                }`}>
                {label}
              </button>
            ))}
          </div>

          {mode === 'stress'   && <StressMode onToast={onToast} />}
          {mode === 'critical' && <CritSpeedMode onToast={onToast} />}
        </div>
      )}
    </div>
  )
}
