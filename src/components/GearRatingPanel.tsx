/**
 * GearRatingPanel — Spur/helical gear strength rating (AGMA 2001-D04 / ISO 6336).
 *
 * Three modes:
 *   "power"   — agma_power_rating: max safe power/torque from allowable stresses.
 *   "stress"  — agma_bending_stress + agma_contact_stress + agma_safety_factors.
 *   "life"    — agma_service_life: stress-cycle factors YN / ZN for finite life.
 *
 * References
 * ----------
 * AGMA 2001-D04 — Fundamental Rating Factors and Calculation Methods for
 *                 Involute Spur and Helical Gear Teeth
 * ISO 6336-2:2019 — Calculation of surface durability (pitting)
 * Shigley's Mechanical Engineering Design, 10th ed., §§ 14-1 to 14-5
 *
 * Props
 * -----
 * onToast  (msg) => void  — optional
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { Settings, ChevronDown, ChevronRight, Loader2, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api.js'

// ---------------------------------------------------------------------------
// Pure helpers — export for tests
// ---------------------------------------------------------------------------

/** Format a number to `dp` decimal places; returns '—' for null/NaN/Infinity. */
// eslint-disable-next-line react-refresh/only-export-components -- helper exported alongside the component for tests, pre-existing before this migration.
export function fmtNum(v: number | null | undefined, dp = 3): string {
  if (v == null || !isFinite(v)) return '—'
  return v.toFixed(dp)
}

interface PowerForm {
  S_t: string
  S_c: string
  Cp: string
  b: string
  m_or_Pd: string
  d_p: string
  N_p: string
  N_g: string
  psi_deg: string
  n_rpm: string
  metric: string | boolean
  Ko: string
  Ks: string
  Km: string
  KB: string
  Qv: string
  K_T: string
  K_R: string
  pressure_angle_deg: string
}

/** Build agma_power_rating params from form state. */
// eslint-disable-next-line react-refresh/only-export-components -- helper exported alongside the component for tests, pre-existing before this migration.
export function buildPowerParams(s: PowerForm) {
  return {
    S_t: parseFloat(s.S_t) || 0,
    S_c: parseFloat(s.S_c) || 0,
    Cp: parseFloat(s.Cp) || 191,
    b: parseFloat(s.b) || 0,
    m_or_Pd: parseFloat(s.m_or_Pd) || 0,
    d_p: parseFloat(s.d_p) || 0,
    N_p: parseInt(s.N_p, 10) || 20,
    N_g: parseInt(s.N_g, 10) || 60,
    psi_deg: parseFloat(s.psi_deg) || 0,
    n_rpm: parseFloat(s.n_rpm) || 1450,
    metric: s.metric === 'true' || s.metric === true,
    Ko: parseFloat(s.Ko) || 1.0,
    Ks: parseFloat(s.Ks) || 1.0,
    Km: parseFloat(s.Km) || 1.3,
    KB: parseFloat(s.KB) || 1.0,
    Qv: parseFloat(s.Qv) || 6,
    K_T: parseFloat(s.K_T) || 1.0,
    K_R: parseFloat(s.K_R) || 1.0,
    pressure_angle_deg: parseFloat(s.pressure_angle_deg) || 20,
  }
}

interface BendingForm {
  Wt: string
  Ko: string
  Kv: string
  Ks: string
  Km: string
  KB: string
  b: string
  m_or_Pd: string
  J: string
  metric: string | boolean
}

/** Build agma_bending_stress params from form state. */
// eslint-disable-next-line react-refresh/only-export-components -- helper exported alongside the component for tests, pre-existing before this migration.
export function buildBendingParams(s: BendingForm) {
  return {
    Wt: parseFloat(s.Wt) || 0,
    Ko: parseFloat(s.Ko) || 1.0,
    Kv: parseFloat(s.Kv) || 1.2,
    Ks: parseFloat(s.Ks) || 1.0,
    Km: parseFloat(s.Km) || 1.3,
    KB: parseFloat(s.KB) || 1.0,
    b: parseFloat(s.b) || 0,
    m_or_Pd: parseFloat(s.m_or_Pd) || 0,
    J: parseFloat(s.J) || 0.36,
    metric: s.metric === 'true' || s.metric === true,
  }
}

interface ServiceLifeForm {
  N_cycles: string
  hardness_HB: string
  gear_type: string
}

/** Build agma_service_life params from form state. */
// eslint-disable-next-line react-refresh/only-export-components -- helper exported alongside the component for tests, pre-existing before this migration.
export function buildServiceLifeParams(s: ServiceLifeForm) {
  return {
    N_cycles: parseFloat(s.N_cycles) || 1e7,
    hardness_HB: parseFloat(s.hardness_HB) || 200,
    gear_type: s.gear_type || 'spur',
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface FieldRowProps {
  label: string
  children: ReactNode
  hint?: string
}

function FieldRow({ label, children, hint }: FieldRowProps) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <label className="text-[11px] text-ink-400 w-36 flex-shrink-0">{label}</label>
      <div className="flex-1">{children}</div>
      {hint && <span className="text-[10px] text-ink-600 flex-shrink-0">{hint}</span>}
    </div>
  )
}

interface NumInputProps {
  value: string | number
  onChange: (v: string) => void
  placeholder?: string
  min?: number
  max?: number
  step?: number
  'data-testid'?: string
}

function NumInput({ value, onChange, placeholder, min, step, 'data-testid': testid }: NumInputProps) {
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

interface SelectInputProps {
  value: string
  onChange: (v: string) => void
  options: [string, string][]
  'data-testid'?: string
}

function SelectInput({ value, onChange, options, 'data-testid': testid }: SelectInputProps) {
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

interface ResultKVProps {
  label: string
  value: ReactNode
  unit?: string
}

function ResultKV({ label, value, unit }: ResultKVProps) {
  return (
    <div className="flex items-center justify-between py-0.5 border-b border-ink-900">
      <span className="text-[11px] text-ink-400">{label}</span>
      <span className="text-[11px] text-ink-100 font-mono">
        {value}{unit ? <span className="text-ink-500 ml-1">{unit}</span> : null}
      </span>
    </div>
  )
}

function SafetyBadge({ value }: { value: number | null | undefined }) {
  if (value == null || !isFinite(value)) return <span className="text-ink-500">—</span>
  const cls = value >= 1.2
    ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
    : value >= 1.0
      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
      : 'bg-red-500/20 text-red-300 border border-red-500/30'
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono ${cls}`}>
      {value.toFixed(2)}
    </span>
  )
}

function WarningList({ warnings }: { warnings?: string[] }) {
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
// Mode: agma_power_rating
// ---------------------------------------------------------------------------

interface PowerRatingResult {
  ok?: boolean
  reason?: string
  power_bending_limit_hp?: number
  power_bending_limit_kW?: number
  power_contact_limit_hp?: number
  power_contact_limit_kW?: number
  power_hp?: number
  power_kW?: number
  torque_lbfin?: number
  torque_Nmm?: number
  SF?: number
  SH?: number
  warnings?: string[]
  result?: PowerRatingResult
}

interface OnToastProps {
  onToast?: (msg: string) => void
}

// Local form state always stores `metric` as a string ('true'/'false'); the
// `boolean` branch in PowerForm.metric only matters to buildPowerParams callers
// outside this component (see tests).
type PowerFormState = Omit<PowerForm, 'metric'> & { metric: string }

function PowerMode({ onToast }: OnToastProps) {
  const [form, setForm] = useState<PowerFormState>({
    S_t: '55000', S_c: '170000', Cp: '2300',
    b: '1.5', m_or_Pd: '8', d_p: '3.0',
    N_p: '20', N_g: '60', psi_deg: '0',
    n_rpm: '1750', metric: 'false',
    Ko: '1.0', Ks: '1.0', Km: '1.3', KB: '1.0',
    Qv: '6', K_T: '1.0', K_R: '1.0',
    pressure_angle_deg: '20',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<PowerRatingResult | null>(null)

  function set(k: keyof PowerFormState) {
    return (v: string) => setForm((f) => ({ ...f, [k]: v }))
  }

  async function run() {
    setLoading(true)
    setResult(null)
    try {
      const data = await api.callTool<PowerRatingResult>('agma_power_rating', buildPowerParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.((e as Error)?.message || 'agma_power_rating failed')
    } finally {
      setLoading(false)
    }
  }

  const isMetric = form.metric === 'true'

  return (
    <div className="space-y-1" data-testid="gear-power-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        AGMA 2001-D04 §14: max safe transmitted power from S_t and S_c allowables
      </p>
      <FieldRow label="Unit system">
        <SelectInput value={form.metric} onChange={set('metric')} data-testid="gp-metric"
          options={[['false', 'English (lbf/in/hp)'], ['true', 'Metric (N/mm/kW)']]} />
      </FieldRow>
      <FieldRow label="S_t allowable" hint={isMetric ? 'MPa' : 'psi'}>
        <NumInput value={form.S_t} onChange={set('S_t')} min={1} placeholder="55000" data-testid="gp-St" />
      </FieldRow>
      <FieldRow label="S_c allowable" hint={isMetric ? 'MPa' : 'psi'}>
        <NumInput value={form.S_c} onChange={set('S_c')} min={1} placeholder="170000" data-testid="gp-Sc" />
      </FieldRow>
      <FieldRow label="Cp (elastic coeff)" hint={isMetric ? '√MPa' : '√psi'}>
        <NumInput value={form.Cp} onChange={set('Cp')} min={1} placeholder="2300" data-testid="gp-Cp" />
      </FieldRow>
      <FieldRow label="Face width b" hint={isMetric ? 'mm' : 'in'}>
        <NumInput value={form.b} onChange={set('b')} min={0.001} step={0.1} placeholder="1.5" data-testid="gp-b" />
      </FieldRow>
      <FieldRow label={isMetric ? 'Module m' : 'Diametral pitch Pd'} hint={isMetric ? 'mm' : 'teeth/in'}>
        <NumInput value={form.m_or_Pd} onChange={set('m_or_Pd')} min={0.001} step={0.5} placeholder="8" data-testid="gp-mPd" />
      </FieldRow>
      <FieldRow label="Pinion pitch dia d_p" hint={isMetric ? 'mm' : 'in'}>
        <NumInput value={form.d_p} onChange={set('d_p')} min={0.001} step={0.1} placeholder="3.0" data-testid="gp-dp" />
      </FieldRow>
      <FieldRow label="Pinion teeth N_p">
        <NumInput value={form.N_p} onChange={set('N_p')} min={4} step={1} placeholder="20" data-testid="gp-Np" />
      </FieldRow>
      <FieldRow label="Gear teeth N_g">
        <NumInput value={form.N_g} onChange={set('N_g')} min={4} step={1} placeholder="60" data-testid="gp-Ng" />
      </FieldRow>
      <FieldRow label="Helix angle ψ" hint="deg">
        <NumInput value={form.psi_deg} onChange={set('psi_deg')} min={0} max={45} step={5} placeholder="0" data-testid="gp-psi" />
      </FieldRow>
      <FieldRow label="Speed" hint="rpm">
        <NumInput value={form.n_rpm} onChange={set('n_rpm')} min={1} placeholder="1750" data-testid="gp-rpm" />
      </FieldRow>
      <FieldRow label="Kv quality Qv">
        <NumInput value={form.Qv} onChange={set('Qv')} min={3} max={12} step={1} placeholder="6" data-testid="gp-Qv" />
      </FieldRow>
      <FieldRow label="Load factor Ko">
        <NumInput value={form.Ko} onChange={set('Ko')} min={1} step={0.1} placeholder="1.0" data-testid="gp-Ko" />
      </FieldRow>
      <FieldRow label="Size factor Ks">
        <NumInput value={form.Ks} onChange={set('Ks')} min={1} step={0.1} placeholder="1.0" data-testid="gp-Ks" />
      </FieldRow>
      <FieldRow label="Load-dist Km">
        <NumInput value={form.Km} onChange={set('Km')} min={1} step={0.1} placeholder="1.3" data-testid="gp-Km" />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="gear-power-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Settings size={12} />}
        Rate Gear Pair
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="gear-power-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="Max power (bending limit)"
                value={fmtNum(result.power_bending_limit_hp ?? result.power_bending_limit_kW, 2)}
                unit={isMetric ? 'kW' : 'hp'} />
              <ResultKV label="Max power (contact limit)"
                value={fmtNum(result.power_contact_limit_hp ?? result.power_contact_limit_kW, 2)}
                unit={isMetric ? 'kW' : 'hp'} />
              <ResultKV label="Governing power"
                value={fmtNum(result.power_hp ?? result.power_kW, 2)}
                unit={isMetric ? 'kW' : 'hp'} />
              <ResultKV label="Max torque"
                value={fmtNum(result.torque_lbfin ?? result.torque_Nmm, 1)}
                unit={isMetric ? 'N·mm' : 'lbf·in'} />
              <div className="flex items-center gap-3 mt-1.5">
                <span className="text-[10px] text-ink-500">SF (bending)</span>
                <SafetyBadge value={result.SF} />
                <span className="text-[10px] text-ink-500">SH (contact)</span>
                <SafetyBadge value={result.SH} />
              </div>
              <WarningList warnings={result.warnings} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode: agma_service_life (stress-cycle factors)
// ---------------------------------------------------------------------------

interface ServiceLifeResult {
  ok?: boolean
  reason?: string
  YN?: number
  ZN?: number
  warnings?: string[]
  result?: ServiceLifeResult
}

function ServiceLifeMode({ onToast }: OnToastProps) {
  const [form, setForm] = useState<ServiceLifeForm>({
    N_cycles: '1e7', hardness_HB: '200', gear_type: 'spur',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ServiceLifeResult | null>(null)

  function set(k: keyof ServiceLifeForm) {
    return (v: string) => setForm((f) => ({ ...f, [k]: v }))
  }

  async function run() {
    setLoading(true)
    setResult(null)
    try {
      const data = await api.callTool<ServiceLifeResult>('agma_service_life', buildServiceLifeParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.((e as Error)?.message || 'agma_service_life failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="gear-life-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        AGMA 2001-D04 Figs 14-14/15: YN (bending) and ZN (contact) stress-cycle factors
      </p>
      <FieldRow label="Stress cycles N">
        <NumInput value={form.N_cycles} onChange={set('N_cycles')} min={1} placeholder="1e7" data-testid="gl-N" />
      </FieldRow>
      <FieldRow label="Brinell hardness" hint="HB">
        <NumInput value={form.hardness_HB} onChange={set('hardness_HB')} min={100} max={400} step={5} placeholder="200" data-testid="gl-HB" />
      </FieldRow>
      <FieldRow label="Gear type">
        <SelectInput value={form.gear_type} onChange={set('gear_type')} data-testid="gl-type"
          options={[['spur', 'Spur'], ['helical', 'Helical']]} />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="gear-life-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Settings size={12} />}
        Compute Cycle Factors
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="gear-life-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="YN (bending)" value={fmtNum(result.YN, 4)} />
              <ResultKV label="ZN (contact)" value={fmtNum(result.ZN, 4)} />
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

const MODES: [string, string][] = [
  ['power', 'Power Rating'],
  ['life', 'Service Life'],
]

export interface Props {
  onToast?: (msg: string) => void
  content?: string
}

interface ParsedContent {
  open?: boolean
  mode?: string
}

export default function GearRatingPanel({ onToast, content }: Props = {}) {
  // content prop: JSON string optionally pre-seeding mode/open state.
  const _parsed: ParsedContent = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()
  const [open, setOpen] = useState(_parsed.open ?? false)
  const [mode, setMode] = useState(_parsed.mode || 'power')

  return (
    <div className="border-t border-ink-800 flex-shrink-0" data-testid="gear-rating-panel">
      <div className="flex items-center px-3 py-1.5 gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 text-[11px] text-ink-400 hover:text-kerf-300 flex-1 min-w-0"
          aria-expanded={open}
          aria-controls="gear-panel-body"
          data-testid="gear-panel-toggle">
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          <Settings size={12} className="text-ink-500" />
          <span className="font-medium">Gear Rating — AGMA 2001-D04 / ISO 6336</span>
        </button>
      </div>

      {open && (
        <div id="gear-panel-body" className="px-3 pb-3" data-testid="gear-panel-body">
          <div className="flex gap-1 mb-2">
            {MODES.map(([k, label]) => (
              <button key={k} type="button"
                onClick={() => setMode(k)}
                data-testid={`gear-mode-${k}`}
                className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                  mode === k
                    ? 'bg-kerf-300/20 text-kerf-300'
                    : 'bg-ink-800 text-ink-400 hover:bg-ink-700'
                }`}>
                {label}
              </button>
            ))}
          </div>

          {mode === 'power' && <PowerMode onToast={onToast} />}
          {mode === 'life'  && <ServiceLifeMode onToast={onToast} />}
        </div>
      )}
    </div>
  )
}
