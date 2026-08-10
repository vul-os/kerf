/**
 * Iso286FitsPanel — ISO 286 limits & fits calculator.
 *
 * Three modes:
 *   "fit"    — iso286_fit_analysis: classify a shaft/hole pair (clearance /
 *              transition / interference) and report min/max limits.
 *   "prefer" — iso286_preferred_fits: look up preferred fit pairs (H7/g6 etc.).
 *   "press"  — iso286_press_fit: Lamé thick-cylinder interference analysis:
 *              contact pressure, hub/shaft hoop stresses, assembly force,
 *              shrink-fit temperature.
 *
 * References
 * ----------
 * ISO 286-1:2010 — Limits and fits — Vocabulary, fundamental deviations,
 *                  tolerance grades IT01–IT18
 * ISO 286-2:2010 — Preferred fits and limit deviations
 * Shigley's MED 10th ed. §2-13 (Lamé / press-fit equations)
 *
 * Props
 * -----
 * onToast  (msg) => void  — optional
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { Ruler, ChevronDown, ChevronRight, Loader2, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api.js'

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

// Tool result shapes are loose bags of numeric fields defined server-side;
// not modelled field-by-field here.
type ToolResult = Record<string, any>

interface FitForm {
  nominal_mm: string
  hole_code: string
  hole_grade: string
  shaft_code: string
  shaft_grade: string
}

interface PreferFitForm {
  nominal_mm: string
  fit_name: string
}

interface PressForm {
  nominal_mm: string
  interference_mm: string
  hub_outer_mm: string
  E_shaft_GPa: string
  E_hub_GPa: string
  nu_shaft: string
  nu_hub: string
  mu: string
  length_mm: string
  yield_shaft_MPa: string
  yield_hub_MPa: string
}

// ---------------------------------------------------------------------------
// Pure helpers — export for tests
// ---------------------------------------------------------------------------

/**
 * Format a number to `dp` decimal places with optional unit; '—' for null/NaN/Infinity.
 * @param {number|null|undefined} v
 * @param {number} dp
 */
export function fmtNum(v: number | null | undefined, dp = 3): string {
  if (v == null || !isFinite(v)) return '—'
  return v.toFixed(dp)
}

/**
 * Classify a fit type string into a display class.
 * @param {'clearance'|'transition'|'interference'|string|null} type
 */
export function fitTypeClass(type: string | null | undefined): string {
  if (type === 'clearance')    return 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
  if (type === 'transition')   return 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
  if (type === 'interference') return 'bg-red-500/20 text-red-300 border border-red-500/30'
  return 'bg-ink-800 text-ink-400'
}

/**
 * Build iso286_fit_analysis params from form state.
 * @param {object} s
 */
export function buildFitParams(s: FitForm) {
  return {
    nominal_mm: parseFloat(s.nominal_mm) || 0,
    hole_code: s.hole_code || 'H',
    hole_grade: s.hole_grade || 'IT7',
    shaft_code: s.shaft_code || 'g',
    shaft_grade: s.shaft_grade || 'IT6',
  }
}

/**
 * Build iso286_preferred_fits params from form state.
 * @param {object} s
 */
export function buildPreferFitParams(s: PreferFitForm) {
  return {
    nominal_mm: parseFloat(s.nominal_mm) || 0,
    fit_name: s.fit_name || '',
  }
}

/**
 * Build iso286_press_fit params from form state.
 * @param {object} s
 */
export function buildPressParams(s: PressForm) {
  return {
    nominal_mm: parseFloat(s.nominal_mm) || 0,
    interference_mm: parseFloat(s.interference_mm) || 0,
    hub_outer_mm: parseFloat(s.hub_outer_mm) || 0,
    E_shaft_GPa: parseFloat(s.E_shaft_GPa) || 200,
    E_hub_GPa: parseFloat(s.E_hub_GPa) || 200,
    nu_shaft: parseFloat(s.nu_shaft) || 0.3,
    nu_hub: parseFloat(s.nu_hub) || 0.3,
    mu: parseFloat(s.mu) || 0.12,
    length_mm: parseFloat(s.length_mm) || 0,
    yield_shaft_MPa: parseFloat(s.yield_shaft_MPa) || 0,
    yield_hub_MPa: parseFloat(s.yield_hub_MPa) || 0,
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function FieldRow({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <label className="text-[11px] text-ink-400 w-36 flex-shrink-0">{label}</label>
      <div className="flex-1">{children}</div>
      {hint && <span className="text-[10px] text-ink-600 flex-shrink-0">{hint}</span>}
    </div>
  )
}

function NumInput({ value, onChange, placeholder, min, max, step, 'data-testid': testid }: {
  value: string | number
  onChange: (v: string) => void
  placeholder?: string
  min?: number
  max?: number
  step?: number
  'data-testid'?: string
}) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      min={min}
      max={max}
      step={step}
      data-testid={testid}
      className="w-full bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:ring-1 focus:ring-kerf-300/60"
    />
  )
}

function TextInput({ value, onChange, placeholder, 'data-testid': testid }: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  'data-testid'?: string
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      data-testid={testid}
      className="w-full bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:ring-1 focus:ring-kerf-300/60"
    />
  )
}

function ResultKV({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="flex items-center justify-between py-0.5 border-b border-ink-900">
      <span className="text-[11px] text-ink-400">{label}</span>
      <span className="text-[11px] text-ink-100 font-mono">
        {value}{unit ? <span className="text-ink-500 ml-1">{unit}</span> : null}
      </span>
    </div>
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
// Mode: fit_analysis
// ---------------------------------------------------------------------------

function FitMode({ onToast }: { onToast?: (msg: string) => void }) {
  const [form, setForm] = useState<FitForm>({
    nominal_mm: '50', hole_code: 'H', hole_grade: 'IT7',
    shaft_code: 'g', shaft_grade: 'IT6',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ToolResult | null>(null)

  function set(k: keyof FitForm) {
    return (v: string) => setForm((f) => ({ ...f, [k]: v }))
  }

  async function run() {
    setLoading(true)
    setResult(null)
    try {
      const data: any = await api.callTool('iso286_fit_analysis', buildFitParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.((e as Error)?.message || 'iso286_fit_analysis failed')
    } finally {
      setLoading(false)
    }
  }

  const ft = result?.fit_type
  const ftClass = fitTypeClass(ft)

  return (
    <div className="space-y-1" data-testid="iso286-fit-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        ISO 286-1:2010 — shaft/hole pair → clearance/transition/interference + limit deviations
      </p>
      <FieldRow label="Nominal size" hint="mm">
        <NumInput value={form.nominal_mm} onChange={set('nominal_mm')} min={0.001} placeholder="50" data-testid="fa-nominal" />
      </FieldRow>
      <FieldRow label="Hole code" hint="e.g. H">
        <TextInput value={form.hole_code} onChange={set('hole_code')} placeholder="H" data-testid="fa-hole-code" />
      </FieldRow>
      <FieldRow label="Hole grade" hint="e.g. IT7">
        <TextInput value={form.hole_grade} onChange={set('hole_grade')} placeholder="IT7" data-testid="fa-hole-grade" />
      </FieldRow>
      <FieldRow label="Shaft code" hint="e.g. g">
        <TextInput value={form.shaft_code} onChange={set('shaft_code')} placeholder="g" data-testid="fa-shaft-code" />
      </FieldRow>
      <FieldRow label="Shaft grade" hint="e.g. IT6">
        <TextInput value={form.shaft_grade} onChange={set('shaft_grade')} placeholder="IT6" data-testid="fa-shaft-grade" />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="iso286-fit-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Ruler size={12} />}
        Analyse Fit
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="iso286-fit-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[11px] text-ink-400">Fit type</span>
                <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono ${ftClass}`}
                  data-testid="fit-type-badge">
                  {ft ?? '—'}
                </span>
              </div>
              <ResultKV label="Hole: ES (upper dev)" value={fmtNum(result.ES_um)} unit="µm" />
              <ResultKV label="Hole: EI (lower dev)" value={fmtNum(result.EI_um)} unit="µm" />
              <ResultKV label="Shaft: es (upper dev)" value={fmtNum(result.es_um)} unit="µm" />
              <ResultKV label="Shaft: ei (lower dev)" value={fmtNum(result.ei_um)} unit="µm" />
              <ResultKV label="Max clearance / min interf" value={fmtNum(result.max_clearance_um ?? result.max_interference_um)} unit="µm" />
              <ResultKV label="Min clearance / max interf" value={fmtNum(result.min_clearance_um ?? result.min_interference_um)} unit="µm" />
              <WarningList warnings={result.warnings} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode: preferred_fits
// ---------------------------------------------------------------------------

function PreferFitMode({ onToast }: { onToast?: (msg: string) => void }) {
  const [form, setForm] = useState<PreferFitForm>({
    nominal_mm: '50', fit_name: 'H7/g6',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ToolResult | null>(null)

  function set(k: keyof PreferFitForm) {
    return (v: string) => setForm((f) => ({ ...f, [k]: v }))
  }

  async function run() {
    setLoading(true)
    setResult(null)
    try {
      const data: any = await api.callTool('iso286_preferred_fits', buildPreferFitParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.((e as Error)?.message || 'iso286_preferred_fits failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="iso286-prefer-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        ISO 286-2:2010 preferred fit table — e.g. H7/g6, H7/k6, H7/p6
      </p>
      <FieldRow label="Nominal size" hint="mm">
        <NumInput value={form.nominal_mm} onChange={set('nominal_mm')} min={0.001} placeholder="50" data-testid="pf-nominal" />
      </FieldRow>
      <FieldRow label="Fit designation" hint="e.g. H7/g6">
        <TextInput value={form.fit_name} onChange={set('fit_name')} placeholder="H7/g6" data-testid="pf-fitname" />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="iso286-prefer-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Ruler size={12} />}
        Look Up Preferred Fit
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="iso286-prefer-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="Designation" value={result.fit_name ?? '—'} />
              <ResultKV label="Fit type" value={result.fit_type ?? '—'} />
              <ResultKV label="Max clearance" value={fmtNum(result.max_clearance_um)} unit="µm" />
              <ResultKV label="Min clearance" value={fmtNum(result.min_clearance_um)} unit="µm" />
              <WarningList warnings={result.warnings} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode: press_fit
// ---------------------------------------------------------------------------

function PressMode({ onToast }: { onToast?: (msg: string) => void }) {
  const [form, setForm] = useState<PressForm>({
    nominal_mm: '50', interference_mm: '0.05',
    hub_outer_mm: '100', E_shaft_GPa: '200',
    E_hub_GPa: '200', nu_shaft: '0.3',
    nu_hub: '0.3', mu: '0.12',
    length_mm: '80', yield_shaft_MPa: '350',
    yield_hub_MPa: '350',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ToolResult | null>(null)

  function set(k: keyof PressForm) {
    return (v: string) => setForm((f) => ({ ...f, [k]: v }))
  }

  async function run() {
    setLoading(true)
    setResult(null)
    try {
      const data: any = await api.callTool('iso286_press_fit', buildPressParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.((e as Error)?.message || 'iso286_press_fit failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="iso286-press-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        Lamé thick-cylinder: contact pressure, hoop stress, assembly force, shrink temp
      </p>
      <FieldRow label="Nominal diameter" hint="mm">
        <NumInput value={form.nominal_mm} onChange={set('nominal_mm')} min={1} placeholder="50" data-testid="pp-nominal" />
      </FieldRow>
      <FieldRow label="Interference δ" hint="mm">
        <NumInput value={form.interference_mm} onChange={set('interference_mm')} min={0} step={0.001} placeholder="0.05" data-testid="pp-interference" />
      </FieldRow>
      <FieldRow label="Hub outer dia" hint="mm">
        <NumInput value={form.hub_outer_mm} onChange={set('hub_outer_mm')} min={1} placeholder="100" data-testid="pp-hub-outer" />
      </FieldRow>
      <FieldRow label="E shaft" hint="GPa">
        <NumInput value={form.E_shaft_GPa} onChange={set('E_shaft_GPa')} min={1} placeholder="200" data-testid="pp-E-shaft" />
      </FieldRow>
      <FieldRow label="E hub" hint="GPa">
        <NumInput value={form.E_hub_GPa} onChange={set('E_hub_GPa')} min={1} placeholder="200" data-testid="pp-E-hub" />
      </FieldRow>
      <FieldRow label="Friction µ">
        <NumInput value={form.mu} onChange={set('mu')} min={0} max={1} step={0.01} placeholder="0.12" data-testid="pp-mu" />
      </FieldRow>
      <FieldRow label="Contact length" hint="mm">
        <NumInput value={form.length_mm} onChange={set('length_mm')} min={1} placeholder="80" data-testid="pp-length" />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="iso286-press-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Ruler size={12} />}
        Analyse Press Fit (Lamé)
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="iso286-press-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="Contact pressure p" value={fmtNum(result.pressure_MPa, 1)} unit="MPa" />
              <ResultKV label="Shaft bore σ_t" value={fmtNum(result.shaft_hoop_MPa, 1)} unit="MPa" />
              <ResultKV label="Hub bore σ_t" value={fmtNum(result.hub_hoop_bore_MPa, 1)} unit="MPa" />
              <ResultKV label="Assembly force F" value={fmtNum(result.assembly_force_kN, 2)} unit="kN" />
              <ResultKV label="Shrink temp ΔT" value={result.shrink_temp_C != null ? fmtNum(result.shrink_temp_C, 1) : '—'} unit="°C" />
              <ResultKV label="Transmissible torque" value={fmtNum(result.max_torque_Nm, 1)} unit="N·m" />
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
  ['fit', 'Fit Analysis'],
  ['prefer', 'Preferred Fits'],
  ['press', 'Press Fit (Lamé)'],
]

interface Iso286FitsPanelProps {
  onToast?: (msg: string) => void
  content?: string | null
}

export default function Iso286FitsPanel({ onToast, content }: Iso286FitsPanelProps = {}) {
  // content prop: JSON string optionally pre-seeding mode/open state.
  const _parsed: { open?: boolean; mode?: string } = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()
  const [open, setOpen] = useState(_parsed.open ?? false)
  const [mode, setMode] = useState(_parsed.mode || 'fit')

  return (
    <div className="border-t border-ink-800 flex-shrink-0" data-testid="iso286-fits-panel">
      <div className="flex items-center px-3 py-1.5 gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 text-[11px] text-ink-400 hover:text-kerf-300 flex-1 min-w-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
          aria-expanded={open}
          aria-controls="iso286-panel-body"
          data-testid="iso286-panel-toggle">
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          <Ruler size={12} className="text-ink-500" />
          <span className="font-medium">Limits &amp; Fits — ISO 286</span>
        </button>
      </div>

      {open && (
        <div id="iso286-panel-body" className="px-3 pb-3" data-testid="iso286-panel-body">
          <div className="flex gap-1 mb-2 flex-wrap">
            {MODES.map(([k, label]) => (
              <button key={k} type="button"
                onClick={() => setMode(k)}
                data-testid={`iso286-mode-${k}`}
                className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                  mode === k
                    ? 'bg-kerf-300/20 text-kerf-300'
                    : 'bg-ink-800 text-ink-400 hover:bg-ink-700'
                } focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70`}>
                {label}
              </button>
            ))}
          </div>

          {mode === 'fit'    && <FitMode onToast={onToast} />}
          {mode === 'prefer' && <PreferFitMode onToast={onToast} />}
          {mode === 'press'  && <PressMode onToast={onToast} />}
        </div>
      )}
    </div>
  )
}
