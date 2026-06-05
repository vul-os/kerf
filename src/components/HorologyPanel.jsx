/**
 * HorologyPanel.jsx — Mechanical watch movement design calculator.
 *
 * Provides four calculation modes via the kerf-horology LLM tools:
 *
 *   1. Gear Train (horology_train_calculator)
 *      Computes gear-train ratio and barrel power storage for a target
 *      balance frequency and power reserve. Returns 3-stage wheel/pinion
 *      factorisation, achieved_ratio, and ratio_error_pct.
 *
 *   2. Escapement (horology_escapement_geometry)
 *      Swiss lever escapement geometry: draw angle, lift angle, drop,
 *      pallet angles, impulse force, and energy per impulse.
 *      Default parameters model the ETA 2824-2.
 *
 *   3. Balance Wheel (horology_balance_period + horology_isochronism)
 *      Balance-wheel oscillation period, beat rate, and isochronism
 *      check from inertia and hairspring stiffness.
 *
 *   4. Tooth Profile (horology_check_tooth_profile)
 *      Validate involute tooth profile for module, tooth count, and
 *      pressure angle. Reports base/pitch/tip radii and pass/fail.
 *
 * All calculations call POST /api/tools/call. Results display as a
 * key-value table. Errors show a red alert banner.
 *
 * Props: (none required — standalone panel)
 */

import { useState } from 'react'
import { Watch, Cog, Gauge, CheckCircle, XCircle, Loader2, AlertCircle, Calculator } from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Format a number for display. Returns '—' for null/undefined/NaN.
 */
export function fmtNum(n, digits = 4) {
  if (n == null || !Number.isFinite(n)) return '—'
  if (Math.abs(n) === 0) return '0'
  if (Math.abs(n) < 0.001 || Math.abs(n) >= 1e6) return n.toExponential(digits - 1)
  return n.toPrecision(digits)
}

/**
 * Convert beat-rate Hz to bph (beats per hour).
 */
export function hzToBph(hz) {
  return hz * 3600
}

/**
 * Common balance frequencies as [Hz, label] pairs.
 */
export const COMMON_FREQUENCIES = [
  [3.0, '21 600 bph (3 Hz)'],
  [4.0, '28 800 bph (4 Hz)'],
  [5.0, '36 000 bph (5 Hz)'],
  [2.5, '18 000 bph (2.5 Hz)'],
]

/**
 * Build gear-train tool args.
 */
export function buildTrainArgs(form) {
  const args = {
    freq_hz: parseFloat(form.freq_hz),
    power_reserve_hours: parseFloat(form.power_reserve_hours),
  }
  if (form.escape_wheel_teeth) args.escape_wheel_teeth = parseInt(form.escape_wheel_teeth, 10)
  if (form.barrel_turns_per_day) args.barrel_turns_per_day = parseFloat(form.barrel_turns_per_day)
  return args
}

/**
 * Build balance-period tool args.
 */
export function buildBalanceArgs(form) {
  return {
    I_balance_gmm2: parseFloat(form.I_gmm2),
    k_hairspring_Nmmrad: parseFloat(form.k_Nmmrad),
  }
}

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  const data = await res.json()
  if (data.code) throw new Error(data.error || data.code)
  return data
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function FieldRow({ label, children }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <label className="text-ink-400 w-36 flex-shrink-0">{label}</label>
      {children}
    </div>
  )
}

function NumInput({ value, onChange, placeholder, min, step = 'any' }) {
  return (
    <input
      type="number"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      min={min}
      step={step}
      className="flex-1 bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] font-mono text-ink-100 placeholder-ink-600 focus:outline-none focus:border-amber-500/60 w-full"
    />
  )
}

function RunButton({ loading, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-700/70 hover:bg-amber-700 disabled:opacity-50 text-white text-[11px] rounded font-medium transition-colors"
    >
      {loading ? <Loader2 size={12} className="animate-spin" /> : <Calculator size={12} />}
      {children}
    </button>
  )
}

function ErrorBanner({ error }) {
  if (!error) return null
  return (
    <div className="flex items-start gap-2 mt-2 px-3 py-2 bg-red-950/40 border border-red-900/50 rounded-lg text-[11px] text-red-300">
      <AlertCircle size={12} className="mt-0.5 flex-shrink-0" />
      {error}
    </div>
  )
}

function PassBadge({ value }) {
  if (value === true) return (
    <span className="inline-flex items-center gap-1 text-emerald-400 font-medium text-[10px]">
      <CheckCircle size={10} />PASS
    </span>
  )
  if (value === false) return (
    <span className="inline-flex items-center gap-1 text-red-400 font-medium text-[10px]">
      <XCircle size={10} />FAIL
    </span>
  )
  return null
}

function ResultTable({ data }) {
  if (!data || typeof data !== 'object') return null

  // Render stage list separately
  const stages = data.stages
  const rest = Object.entries(data).filter(([k]) => k !== 'stages' && typeof data[k] !== 'object')
  const boolKeys = new Set(['passed', 'is_consistent', 'is_isochronous'])

  return (
    <div className="mt-3 rounded-lg border border-ink-700 overflow-hidden text-[11px]">
      <table className="w-full">
        <tbody>
          {rest.map(([key, val]) => (
            <tr key={key} className="border-b border-ink-800 last:border-0">
              <td className="px-3 py-1.5 text-ink-400 font-mono w-1/2">{key}</td>
              <td className="px-3 py-1.5 text-ink-100 font-mono text-right">
                {boolKeys.has(key)
                  ? <PassBadge value={val} />
                  : typeof val === 'number'
                    ? fmtNum(val)
                    : String(val)
                }
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {stages && stages.length > 0 && (
        <div className="border-t border-ink-800 px-3 py-2">
          <div className="text-[10px] text-ink-500 mb-1">Gear stages</div>
          <table className="w-full text-[10px]">
            <thead>
              <tr className="text-ink-500">
                <th className="text-left py-0.5">Stage</th>
                <th className="text-right py-0.5">Wheel</th>
                <th className="text-right py-0.5">Pinion</th>
                <th className="text-right py-0.5">Ratio</th>
              </tr>
            </thead>
            <tbody>
              {stages.map((s, i) => (
                <tr key={i} className="border-t border-ink-800/50 text-ink-200">
                  <td className="py-0.5">{i + 1}</td>
                  <td className="text-right py-0.5 font-mono">{s.wheel_teeth}</td>
                  <td className="text-right py-0.5 font-mono">{s.pinion_leaves}</td>
                  <td className="text-right py-0.5 font-mono">{fmtNum(s.ratio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.notes && (
        <div className="px-3 py-1.5 bg-ink-900/40 text-ink-500 text-[10px]">
          {Array.isArray(data.notes) ? data.notes.join(' · ') : data.notes}
        </div>
      )}
      {data.consistency_errors && data.consistency_errors.length > 0 && (
        <div className="px-3 py-1.5 bg-red-950/30 text-red-400/80 text-[10px] space-y-0.5">
          {data.consistency_errors.map((e, i) => <div key={i}>{e}</div>)}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Gear train
// ---------------------------------------------------------------------------

function GearTrainTab() {
  const [form, setForm] = useState({
    freq_hz: '4.0',
    power_reserve_hours: '48',
    escape_wheel_teeth: '15',
    barrel_turns_per_day: '7.5',
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }))

  async function run() {
    setLoading(true); setError(null); setResult(null)
    try {
      const data = await callTool('horology_train_calculator', buildTrainArgs(form))
      setResult(data)
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }

  return (
    <div className="space-y-2 p-3">
      <div className="text-[10px] text-ink-500 mb-2">
        Gear-train ratio + 3-stage wheel/pinion factorisation for a target balance
        frequency and power reserve (Daniels §6.1).
      </div>

      <FieldRow label="Balance frequency">
        <div className="flex-1 flex gap-1">
          <NumInput value={form.freq_hz} onChange={set('freq_hz')} placeholder="4.0" min="0.5" step="0.5" />
          <span className="text-ink-500 self-center text-[10px]">Hz</span>
        </div>
      </FieldRow>

      <div className="ml-36 flex gap-1 flex-wrap">
        {COMMON_FREQUENCIES.map(([hz, label]) => (
          <button
            key={hz}
            type="button"
            onClick={() => set('freq_hz')(String(hz))}
            className={`px-2 py-0.5 rounded text-[10px] border transition-colors
              ${parseFloat(form.freq_hz) === hz
                ? 'border-amber-500/60 text-amber-300 bg-amber-950/30'
                : 'border-ink-700 text-ink-500 hover:text-ink-300'}`}
          >
            {label}
          </button>
        ))}
      </div>

      <FieldRow label="Power reserve [h]">
        <NumInput value={form.power_reserve_hours} onChange={set('power_reserve_hours')} placeholder="48" min="1" />
      </FieldRow>
      <FieldRow label="Escape teeth">
        <NumInput value={form.escape_wheel_teeth} onChange={set('escape_wheel_teeth')} placeholder="15" min="10" step="1" />
      </FieldRow>
      <FieldRow label="Barrel turns/day">
        <NumInput value={form.barrel_turns_per_day} onChange={set('barrel_turns_per_day')} placeholder="7.5" min="1" />
      </FieldRow>

      <RunButton loading={loading} onClick={run}>Calculate train</RunButton>
      <ErrorBanner error={error} />
      {result && <ResultTable data={result} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Escapement
// ---------------------------------------------------------------------------

function EscapementTab() {
  const [form, setForm] = useState({
    escape_teeth: '15',
    lift_deg: '8.0',
    draw_deg: '12.0',
    escape_wheel_radius_mm: '1.925',
    lever_arm_mm: '1.6',
    escape_wheel_torque_Nmm: '0.35',
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }))

  async function run() {
    setLoading(true); setError(null); setResult(null)
    try {
      const args = {
        escape_teeth: parseInt(form.escape_teeth, 10),
        lift_deg: parseFloat(form.lift_deg),
        draw_deg: parseFloat(form.draw_deg),
        escape_wheel_radius_mm: parseFloat(form.escape_wheel_radius_mm),
        lever_arm_mm: parseFloat(form.lever_arm_mm),
        escape_wheel_torque_Nmm: parseFloat(form.escape_wheel_torque_Nmm),
      }
      const data = await callTool('horology_escapement_geometry', args)
      setResult(data)
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }

  return (
    <div className="space-y-2 p-3">
      <div className="text-[10px] text-ink-500 mb-2">
        Swiss lever escapement geometry — tooth pitch, pallet angles, impulse force,
        and energy per beat. Defaults model the ETA 2824-2.
      </div>

      <FieldRow label="Escape teeth">
        <NumInput value={form.escape_teeth} onChange={set('escape_teeth')} placeholder="15" min="12" step="1" />
      </FieldRow>
      <FieldRow label="Lift angle [°]">
        <NumInput value={form.lift_deg} onChange={set('lift_deg')} placeholder="8" min="5" />
      </FieldRow>
      <FieldRow label="Draw angle [°]">
        <NumInput value={form.draw_deg} onChange={set('draw_deg')} placeholder="12" min="8" />
      </FieldRow>
      <FieldRow label="EW radius [mm]">
        <NumInput value={form.escape_wheel_radius_mm} onChange={set('escape_wheel_radius_mm')} placeholder="1.925" min="0.5" />
      </FieldRow>
      <FieldRow label="Lever arm [mm]">
        <NumInput value={form.lever_arm_mm} onChange={set('lever_arm_mm')} placeholder="1.6" min="0.5" />
      </FieldRow>
      <FieldRow label="EW torque [N·mm]">
        <NumInput value={form.escape_wheel_torque_Nmm} onChange={set('escape_wheel_torque_Nmm')} placeholder="0.35" min="0.01" />
      </FieldRow>

      <RunButton loading={loading} onClick={run}>Calculate escapement</RunButton>
      <ErrorBanner error={error} />
      {result && <ResultTable data={result} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Balance wheel
// ---------------------------------------------------------------------------

function BalanceTab() {
  const [form, setForm] = useState({
    I_gmm2: '14.4',
    k_Nmmrad: '0.023',
    amp_min_deg: '180',
    amp_max_deg: '300',
  })
  const [periodResult, setPeriodResult] = useState(null)
  const [isoResult, setIsoResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }))

  async function run() {
    setLoading(true); setError(null); setPeriodResult(null); setIsoResult(null)
    try {
      const baseArgs = buildBalanceArgs(form)
      // Run both tools in parallel
      const [period, iso] = await Promise.all([
        callTool('horology_balance_period', baseArgs),
        callTool('horology_isochronism', {
          ...baseArgs,
          amp_min_deg: parseFloat(form.amp_min_deg),
          amp_max_deg: parseFloat(form.amp_max_deg),
        }),
      ])
      setPeriodResult(period)
      setIsoResult(iso)
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }

  return (
    <div className="space-y-2 p-3">
      <div className="text-[10px] text-ink-500 mb-2">
        Balance-wheel period + isochronism check from inertia and hairspring
        stiffness. Default I and k values are typical for an ETA 2824-2.
      </div>

      <FieldRow label="Inertia I [g·mm²]">
        <NumInput value={form.I_gmm2} onChange={set('I_gmm2')} placeholder="14.4" min="0.1" />
      </FieldRow>
      <FieldRow label="Hairspring k [N·mm/rad]">
        <NumInput value={form.k_Nmmrad} onChange={set('k_Nmmrad')} placeholder="0.023" min="0.001" />
      </FieldRow>
      <FieldRow label="Amp min [°]">
        <NumInput value={form.amp_min_deg} onChange={set('amp_min_deg')} placeholder="180" min="90" max="400" step="10" />
      </FieldRow>
      <FieldRow label="Amp max [°]">
        <NumInput value={form.amp_max_deg} onChange={set('amp_max_deg')} placeholder="300" min="90" max="600" step="10" />
      </FieldRow>

      <RunButton loading={loading} onClick={run}>Calculate balance</RunButton>
      <ErrorBanner error={error} />
      {periodResult && (
        <div>
          <div className="text-[10px] text-ink-500 mt-2 mb-1">Period + beat rate</div>
          <ResultTable data={periodResult} />
        </div>
      )}
      {isoResult && (
        <div>
          <div className="text-[10px] text-ink-500 mt-2 mb-1">Isochronism</div>
          <ResultTable data={isoResult} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Tooth profile
// ---------------------------------------------------------------------------

function ToothTab() {
  const [form, setForm] = useState({
    module: '0.10',
    num_teeth: '80',
    pressure_angle_deg: '20',
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }))

  async function run() {
    setLoading(true); setError(null); setResult(null)
    try {
      const args = {
        module: parseFloat(form.module),
        num_teeth: parseInt(form.num_teeth, 10),
        pressure_angle_deg: parseFloat(form.pressure_angle_deg),
      }
      const data = await callTool('horology_check_tooth_profile', args)
      setResult(data)
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }

  return (
    <div className="space-y-2 p-3">
      <div className="text-[10px] text-ink-500 mb-2">
        Validate involute tooth profile geometry. Returns pass/fail, base/pitch/tip
        radii, and undercut check. Typical watch wheel: module 0.08–0.12, 60–120 teeth.
      </div>

      <FieldRow label="Module [mm]">
        <NumInput value={form.module} onChange={set('module')} placeholder="0.10" min="0.01" step="0.01" />
      </FieldRow>
      <FieldRow label="Tooth count">
        <NumInput value={form.num_teeth} onChange={set('num_teeth')} placeholder="80" min="6" step="1" />
      </FieldRow>
      <FieldRow label="Pressure angle [°]">
        <NumInput value={form.pressure_angle_deg} onChange={set('pressure_angle_deg')} placeholder="20" min="14.5" max="25" />
      </FieldRow>

      <RunButton loading={loading} onClick={run}>Check profile</RunButton>
      <ErrorBanner error={error} />
      {result && <ResultTable data={result} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'train', label: 'Train', Icon: Cog },
  { id: 'escapement', label: 'Escapement', Icon: Watch },
  { id: 'balance', label: 'Balance', Icon: Gauge },
  { id: 'tooth', label: 'Tooth', Icon: Calculator },
]

export default function HorologyPanel({ className = '', content }) {
  // Parse content string (from panelRegistry) to seed defaults (not yet used but accepted for compat)
  // eslint-disable-next-line no-unused-vars
  const _defaults = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()
  const [activeTab, setActiveTab] = useState('train')

  return (
    <div className={`flex flex-col h-full bg-ink-950 text-ink-100 ${className}`}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-800 flex-shrink-0">
        <Watch size={14} className="text-amber-400" />
        <span className="text-[12px] font-medium text-ink-200">Horology</span>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-ink-800 flex-shrink-0">
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            className={`
              flex items-center gap-1.5 px-3 py-1.5 text-[11px] transition-colors
              ${activeTab === id
                ? 'text-amber-300 border-b-2 border-amber-400 bg-amber-950/20'
                : 'text-ink-500 hover:text-ink-300'}
            `}
          >
            <Icon size={11} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'train'      && <GearTrainTab />}
        {activeTab === 'escapement' && <EscapementTab />}
        {activeTab === 'balance'    && <BalanceTab />}
        {activeTab === 'tooth'      && <ToothTab />}
      </div>
    </div>
  )
}
