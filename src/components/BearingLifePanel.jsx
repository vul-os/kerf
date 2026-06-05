/**
 * BearingLifePanel — Rolling-element bearing selection & life calculator.
 *
 * Implements ISO 281:2007 L10 / adjusted life (Lna) and ISO/TS 16281 modified
 * reference life (Lnm) via the kerf_cad_core.bearings tool suite.
 *
 * Modes
 * -----
 * "select"  — bearing_select: enter loads, speed, target life and series to get
 *             the lightest bearing that meets the target.
 * "life"    — bearing_adjusted_life: enter C, P, n_rpm, a1, a23 to compute Lna.
 * "iso16281"— bearing_modified_reference_life: enter C, P, n_rpm, kappa, eC, Cu_N.
 *
 * Props
 * -----
 * onToast   (msg) => void   — surface errors as toasts (optional)
 *
 * References
 * ----------
 * ISO 281:2007  — Rolling bearings — Dynamic load ratings and rating life
 * ISO/TS 16281:2008 — Modified reference rating life
 * SKF Bearing Catalogue, 2018 edition
 */

import { useState } from 'react'
import { Calculator, ChevronDown, ChevronRight, Loader2, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api.js'

// ---------------------------------------------------------------------------
// Pure helpers — export for tests
// ---------------------------------------------------------------------------

/**
 * Format a number to `dp` decimal places; returns '—' for null/undefined/NaN.
 * @param {number|null|undefined} v
 * @param {number} dp
 */
export function fmtNum(v, dp = 2) {
  if (v == null || !isFinite(v)) return '—'
  return v.toFixed(dp)
}

/**
 * Return the CSS class for a result value tag.
 * @param {boolean|null} ok
 */
export function resultTagClass(ok) {
  if (ok === true) return 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
  if (ok === false) return 'bg-red-500/20 text-red-300 border border-red-500/30'
  return 'bg-ink-800 text-ink-400'
}

/**
 * Build the bearing_select call params from form state.
 * @param {object} s
 */
export function buildSelectParams(s) {
  return {
    series: s.series || '6200',
    Fr: parseFloat(s.Fr) || 0,
    Fa: parseFloat(s.Fa) || 0,
    n_rpm: parseFloat(s.n_rpm) || 0,
    Lh_min: parseFloat(s.Lh_min) || 20000,
    bearing_type: s.bearing_type || 'ball',
    a1: parseFloat(s.a1) || 1.0,
    a23: parseFloat(s.a23) || 1.0,
  }
}

/**
 * Build the bearing_adjusted_life call params from form state.
 * @param {object} s
 */
export function buildLifeParams(s) {
  return {
    C: parseFloat(s.C) || 0,
    P: parseFloat(s.P) || 0,
    n_rpm: parseFloat(s.n_rpm) || 0,
    bearing_type: s.bearing_type || 'ball',
    a1: parseFloat(s.a1) || 1.0,
    a23: parseFloat(s.a23) || 1.0,
  }
}

/**
 * Build bearing_modified_reference_life params from form state.
 * @param {object} s
 */
export function buildIso16281Params(s) {
  return {
    C: parseFloat(s.C) || 0,
    P: parseFloat(s.P) || 0,
    n_rpm: parseFloat(s.n_rpm) || 0,
    kappa: parseFloat(s.kappa) || 1.0,
    eC: parseFloat(s.eC) || 0.5,
    Cu_N: parseFloat(s.Cu_N) || 0,
    bearing_type: s.bearing_type || 'ball',
    a1: parseFloat(s.a1) || 1.0,
    fatigue_limited: s.fatigue_limited ?? false,
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function FieldRow({ label, children, hint }) {
  return (
    <div className="flex items-center gap-2 py-0.5">
      <label className="text-[11px] text-ink-400 w-32 flex-shrink-0">{label}</label>
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

// ---------------------------------------------------------------------------
// Mode: bearing_select
// ---------------------------------------------------------------------------

function SelectMode({ onToast }) {
  const [form, setForm] = useState({
    series: '6200', Fr: '5000', Fa: '1000', n_rpm: '1450',
    Lh_min: '20000', bearing_type: 'ball', a1: '1.0', a23: '1.0',
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
      const data = await api.callTool('bearing_select', buildSelectParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.(e?.message || 'bearing_select failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="bearing-select-mode">
      <FieldRow label="Series" hint="e.g. 6000/6200/6300">
        <NumInput value={form.series} onChange={set('series')} placeholder="6200" data-testid="bs-series" />
      </FieldRow>
      <FieldRow label="Radial load Fr" hint="N">
        <NumInput value={form.Fr} onChange={set('Fr')} min={0} placeholder="5000" data-testid="bs-Fr" />
      </FieldRow>
      <FieldRow label="Axial load Fa" hint="N">
        <NumInput value={form.Fa} onChange={set('Fa')} min={0} placeholder="1000" data-testid="bs-Fa" />
      </FieldRow>
      <FieldRow label="Speed" hint="rpm">
        <NumInput value={form.n_rpm} onChange={set('n_rpm')} min={1} placeholder="1450" data-testid="bs-rpm" />
      </FieldRow>
      <FieldRow label="Target life" hint="hours">
        <NumInput value={form.Lh_min} onChange={set('Lh_min')} min={1} placeholder="20000" data-testid="bs-lh" />
      </FieldRow>
      <FieldRow label="Type">
        <SelectInput value={form.bearing_type} onChange={set('bearing_type')} data-testid="bs-type"
          options={[['ball', 'Ball bearing'], ['roller', 'Roller bearing']]} />
      </FieldRow>
      <FieldRow label="a1 (reliability)" hint="1.0=90%">
        <NumInput value={form.a1} onChange={set('a1')} min={0.01} step={0.01} placeholder="1.0" data-testid="bs-a1" />
      </FieldRow>
      <FieldRow label="a23 (lub/mat)" hint="1.0=std">
        <NumInput value={form.a23} onChange={set('a23')} min={0.01} step={0.01} placeholder="1.0" data-testid="bs-a23" />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="bearing-select-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Calculator size={12} />}
        Select Bearing
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="bearing-select-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="Designation" value={result.bearing?.series_id ?? '—'} />
              <ResultKV label="Bore" value={fmtNum(result.bearing?.bore_mm)} unit="mm" />
              <ResultKV label="OD" value={fmtNum(result.bearing?.OD_mm)} unit="mm" />
              <ResultKV label="C (dynamic)" value={fmtNum(result.bearing?.C_N, 0)} unit="N" />
              <ResultKV label="C₀ (static)" value={fmtNum(result.bearing?.C0_N, 0)} unit="N" />
              <ResultKV label="L10 adjusted" value={fmtNum(result.Lna_hours, 0)} unit="h" />
              <ResultKV label="s₀ (static safety)" value={fmtNum(result.s0, 2)} />
              <WarningList warnings={result.warnings} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode: bearing_adjusted_life (L10 / Lna)
// ---------------------------------------------------------------------------

function LifeMode({ onToast }) {
  const [form, setForm] = useState({
    C: '29100', P: '5000', n_rpm: '1450', bearing_type: 'ball', a1: '1.0', a23: '1.0',
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
      const data = await api.callTool('bearing_adjusted_life', buildLifeParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.(e?.message || 'bearing_adjusted_life failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="bearing-life-mode">
      <FieldRow label="C (dynamic rating)" hint="N">
        <NumInput value={form.C} onChange={set('C')} min={0} placeholder="29100" data-testid="bl-C" />
      </FieldRow>
      <FieldRow label="P (equiv. load)" hint="N">
        <NumInput value={form.P} onChange={set('P')} min={0} placeholder="5000" data-testid="bl-P" />
      </FieldRow>
      <FieldRow label="Speed" hint="rpm">
        <NumInput value={form.n_rpm} onChange={set('n_rpm')} min={1} placeholder="1450" data-testid="bl-rpm" />
      </FieldRow>
      <FieldRow label="Type">
        <SelectInput value={form.bearing_type} onChange={set('bearing_type')} data-testid="bl-type"
          options={[['ball', 'Ball bearing'], ['roller', 'Roller bearing']]} />
      </FieldRow>
      <FieldRow label="a1 (reliability)" hint="1.0=90%">
        <NumInput value={form.a1} onChange={set('a1')} min={0.01} step={0.01} placeholder="1.0" data-testid="bl-a1" />
      </FieldRow>
      <FieldRow label="a23 (lub/mat)" hint="1.0=std">
        <NumInput value={form.a23} onChange={set('a23')} min={0.01} step={0.01} placeholder="1.0" data-testid="bl-a23" />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="bearing-life-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Calculator size={12} />}
        Compute Life
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="bearing-life-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="L10 basic life" value={fmtNum(result.L10_rev, 1)} unit="×10⁶ rev" />
              <ResultKV label="L10 (hours)" value={fmtNum(result.L10_hours, 0)} unit="h" />
              <ResultKV label="Lna adjusted" value={fmtNum(result.Lna_hours, 0)} unit="h" />
              <WarningList warnings={result.warnings} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode: ISO/TS 16281 modified reference life
// ---------------------------------------------------------------------------

function Iso16281Mode({ onToast }) {
  const [form, setForm] = useState({
    C: '29100', P: '5000', n_rpm: '1450',
    kappa: '1.0', eC: '0.5', Cu_N: '500',
    bearing_type: 'ball', a1: '1.0', fatigue_limited: false,
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
      const data = await api.callTool('bearing_modified_reference_life', buildIso16281Params(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.(e?.message || 'bearing_modified_reference_life failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="bearing-iso16281-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        ISO/TS 16281: aISO = f(κ, eC·Cu/P) — lubricant viscosity + contamination
      </p>
      <FieldRow label="C" hint="N">
        <NumInput value={form.C} onChange={set('C')} min={0} placeholder="29100" data-testid="b16-C" />
      </FieldRow>
      <FieldRow label="P (equiv. load)" hint="N">
        <NumInput value={form.P} onChange={set('P')} min={0} placeholder="5000" data-testid="b16-P" />
      </FieldRow>
      <FieldRow label="Speed" hint="rpm">
        <NumInput value={form.n_rpm} onChange={set('n_rpm')} min={1} placeholder="1450" data-testid="b16-rpm" />
      </FieldRow>
      <FieldRow label="κ (visc. ratio)" hint="ν/ν₁">
        <NumInput value={form.kappa} onChange={set('kappa')} min={0.01} step={0.1} placeholder="1.0" data-testid="b16-kappa" />
      </FieldRow>
      <FieldRow label="eC (contamination)" hint="0–1">
        <NumInput value={form.eC} onChange={set('eC')} min={0} max={1} step={0.05} placeholder="0.5" data-testid="b16-eC" />
      </FieldRow>
      <FieldRow label="Cu (fatigue limit)" hint="N">
        <NumInput value={form.Cu_N} onChange={set('Cu_N')} min={0} placeholder="500" data-testid="b16-Cu" />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="bearing-iso16281-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Calculator size={12} />}
        Compute Lnm (ISO/TS 16281)
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="bearing-iso16281-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="aISO" value={fmtNum(result.aISO, 3)} />
              <ResultKV label="L10 basic" value={fmtNum(result.L10_rev, 1)} unit="×10⁶ rev" />
              <ResultKV label="Lnm modified" value={fmtNum(result.Lnm_rev, 1)} unit="×10⁶ rev" />
              <ResultKV label="Lnm (hours)" value={fmtNum(result.Lnm_hours, 0)} unit="h" />
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
  ['select', 'Select Bearing'],
  ['life', 'L10 / Lna Life'],
  ['iso16281', 'ISO/TS 16281 Lnm'],
]

export default function BearingLifePanel({ onToast }) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState('select')

  return (
    <div className="border-t border-ink-800 flex-shrink-0" data-testid="bearing-life-panel">
      {/* Header */}
      <div className="flex items-center px-3 py-1.5 gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 text-[11px] text-ink-400 hover:text-kerf-300 flex-1 min-w-0"
          aria-expanded={open}
          aria-controls="bearing-panel-body"
          data-testid="bearing-panel-toggle">
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          <Calculator size={12} className="text-ink-500" />
          <span className="font-medium">Bearings — ISO 281 / ISO/TS 16281</span>
        </button>
      </div>

      {/* Body */}
      {open && (
        <div id="bearing-panel-body" className="px-3 pb-3" data-testid="bearing-panel-body">
          {/* Mode tabs */}
          <div className="flex gap-1 mb-2">
            {MODES.map(([k, label]) => (
              <button key={k} type="button"
                onClick={() => setMode(k)}
                data-testid={`bearing-mode-${k}`}
                className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                  mode === k
                    ? 'bg-kerf-300/20 text-kerf-300'
                    : 'bg-ink-800 text-ink-400 hover:bg-ink-700'
                }`}>
                {label}
              </button>
            ))}
          </div>

          {mode === 'select'    && <SelectMode onToast={onToast} />}
          {mode === 'life'      && <LifeMode onToast={onToast} />}
          {mode === 'iso16281'  && <Iso16281Mode onToast={onToast} />}
        </div>
      )}
    </div>
  )
}
