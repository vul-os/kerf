/**
 * MicrofluidicsPanel.jsx — Design calculator panel for microfluidic devices.
 *
 * Provides three calculation modes via the kerf-microfluidics LLM tools:
 *
 *   1. Channel Design (microfluidics_pressure_drop)
 *      Computes pressure drop and Reynolds number for rectangular,
 *      trapezoidal, or semicircular channels. Bruus 2008 Fourier-series
 *      friction factor for rectangular cross-sections.
 *
 *   2. Droplet Generation (microfluidics_droplet)
 *      Predicts droplet size, volume, and generation frequency for
 *      T-junction (Garstecki 2006 / van Steijn 2010) and flow-focusing
 *      (Anna 2003) geometries. Automatically selects squeezing vs dripping
 *      regime based on capillary number.
 *
 *   3. Rayleigh-Plateau Breakup (microfluidics_rayleigh_plateau)
 *      Computes most-unstable wavelength, e-folding breakup time, and
 *      expected droplet diameter from thread-radius + fluid properties.
 *
 * All calculations call POST /api/tools/call. Results are displayed inline
 * as a structured key-value table. Errors show a red alert banner.
 *
 * Props: (none required — standalone panel)
 */

import { useState } from 'react'
import { Droplets, Waves, Calculator, Loader2, AlertCircle, CheckCircle } from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Format a number for display with appropriate precision.
 * Returns '—' for null/undefined/NaN.
 */
export function fmtNum(n, digits = 4) {
  if (n == null || !Number.isFinite(n)) return '—'
  if (Math.abs(n) === 0) return '0'
  if (Math.abs(n) < 0.001 || Math.abs(n) >= 1e6) {
    return n.toExponential(digits - 1)
  }
  return n.toPrecision(digits)
}

/**
 * Parse capillary number and classify regime.
 */
export function classifyRegime(ca) {
  if (ca == null || !Number.isFinite(ca)) return null
  return ca < 0.01 ? 'squeezing' : 'dripping'
}

/**
 * Build the args object for microfluidics_pressure_drop tool.
 */
export function buildPressureDropArgs(form) {
  const base = {
    shape: form.shape,
    length_um: parseFloat(form.length_um),
    flow_rate_ul_min: parseFloat(form.flow_rate_ul_min),
  }
  if (form.shape === 'rectangular') {
    base.width_um = parseFloat(form.width_um)
    base.height_um = parseFloat(form.height_um)
  } else if (form.shape === 'trapezoidal') {
    base.width_top_um = parseFloat(form.width_top_um)
    base.width_bottom_um = parseFloat(form.width_bottom_um)
    base.trap_height_um = parseFloat(form.trap_height_um)
  } else if (form.shape === 'semicircular') {
    base.radius_um = parseFloat(form.radius_um)
  }
  return base
}

/**
 * Build the args object for microfluidics_droplet tool.
 */
export function buildDropletArgs(form) {
  const base = {
    geometry: form.geometry,
    q_continuous_ul_min: parseFloat(form.q_continuous_ul_min),
    q_dispersed_ul_min: parseFloat(form.q_dispersed_ul_min),
    channel_width_um: parseFloat(form.channel_width_um),
    channel_height_um: parseFloat(form.channel_height_um),
  }
  if (form.viscosity_pa_s) base.viscosity_continuous_pa_s = parseFloat(form.viscosity_pa_s)
  if (form.surface_tension) base.surface_tension_n_per_m = parseFloat(form.surface_tension)
  return base
}

// ---------------------------------------------------------------------------
// API call helper
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
// Sub-components
// ---------------------------------------------------------------------------

function ResultTable({ data }) {
  if (!data || typeof data !== 'object') return null
  const skip = new Set(['model', 'disclaimer', 'flow_regime', 'regime'])
  const rows = Object.entries(data).filter(([k]) => !skip.has(k))
  const notes = [data.flow_regime, data.regime, data.model].filter(Boolean)

  return (
    <div className="mt-3 rounded-lg border border-ink-700 overflow-hidden text-[11px]">
      <table className="w-full">
        <tbody>
          {rows.map(([key, val]) => (
            <tr key={key} className="border-b border-ink-800 last:border-0">
              <td className="px-3 py-1.5 text-ink-400 font-mono w-1/2">{key}</td>
              <td className="px-3 py-1.5 text-ink-100 font-mono text-right">
                {typeof val === 'number' ? fmtNum(val) : String(val)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {notes.length > 0 && (
        <div className="px-3 py-1.5 bg-ink-900/40 text-ink-500 text-[10px] space-y-0.5">
          {notes.map((n, i) => <div key={i}>{n}</div>)}
        </div>
      )}
      {data.disclaimer && (
        <div className="px-3 py-1.5 bg-amber-950/30 text-amber-400/70 text-[10px]">
          {data.disclaimer}
        </div>
      )}
    </div>
  )
}

function FieldRow({ label, children }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <label className="text-ink-400 w-36 flex-shrink-0">{label}</label>
      {children}
    </div>
  )
}

function NumInput({ value, onChange, placeholder, min }) {
  return (
    <input
      type="number"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      min={min}
      step="any"
      className="flex-1 bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] font-mono text-ink-100 placeholder-ink-600 focus:outline-none focus:border-blue-500/60 w-full"
    />
  )
}

function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="flex-1 bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-blue-500/60"
    >
      {options.map(([v, label]) => (
        <option key={v} value={v}>{label}</option>
      ))}
    </select>
  )
}

function RunButton({ loading, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={loading}
      className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600/80 hover:bg-blue-600 disabled:opacity-50 text-white text-[11px] rounded font-medium transition-colors"
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

// ---------------------------------------------------------------------------
// Tab: Channel pressure drop
// ---------------------------------------------------------------------------

function ChannelTab() {
  const [form, setForm] = useState({
    shape: 'rectangular',
    length_um: '1000',
    flow_rate_ul_min: '1',
    width_um: '100',
    height_um: '50',
    width_top_um: '120',
    width_bottom_um: '80',
    trap_height_um: '50',
    radius_um: '25',
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }))

  async function run() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const args = buildPressureDropArgs(form)
      const data = await callTool('microfluidics_pressure_drop', args)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2 p-3">
      <div className="text-[10px] text-ink-500 mb-2">
        Pressure drop and Reynolds number for a single microchannel.
        Uses Bruus 2008 Fourier-series friction factor for rectangular channels.
      </div>

      <FieldRow label="Cross-section">
        <Select
          value={form.shape}
          onChange={set('shape')}
          options={[
            ['rectangular', 'Rectangular'],
            ['trapezoidal', 'Trapezoidal (DRIE)'],
            ['semicircular', 'Semicircular'],
          ]}
        />
      </FieldRow>

      <FieldRow label="Length [µm]">
        <NumInput value={form.length_um} onChange={set('length_um')} placeholder="1000" min="0" />
      </FieldRow>

      <FieldRow label="Flow rate [µL/min]">
        <NumInput value={form.flow_rate_ul_min} onChange={set('flow_rate_ul_min')} placeholder="1" min="0" />
      </FieldRow>

      {form.shape === 'rectangular' && (
        <>
          <FieldRow label="Width [µm]">
            <NumInput value={form.width_um} onChange={set('width_um')} placeholder="100" min="0" />
          </FieldRow>
          <FieldRow label="Height [µm]">
            <NumInput value={form.height_um} onChange={set('height_um')} placeholder="50" min="0" />
          </FieldRow>
        </>
      )}

      {form.shape === 'trapezoidal' && (
        <>
          <FieldRow label="Top width [µm]">
            <NumInput value={form.width_top_um} onChange={set('width_top_um')} placeholder="120" />
          </FieldRow>
          <FieldRow label="Bottom width [µm]">
            <NumInput value={form.width_bottom_um} onChange={set('width_bottom_um')} placeholder="80" />
          </FieldRow>
          <FieldRow label="Height [µm]">
            <NumInput value={form.trap_height_um} onChange={set('trap_height_um')} placeholder="50" />
          </FieldRow>
        </>
      )}

      {form.shape === 'semicircular' && (
        <FieldRow label="Radius [µm]">
          <NumInput value={form.radius_um} onChange={set('radius_um')} placeholder="25" />
        </FieldRow>
      )}

      <RunButton loading={loading} onClick={run}>Calculate</RunButton>
      <ErrorBanner error={error} />
      {result && <ResultTable data={result} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Droplet generation
// ---------------------------------------------------------------------------

function DropletTab() {
  const [form, setForm] = useState({
    geometry: 't_junction',
    q_continuous_ul_min: '2',
    q_dispersed_ul_min: '0.5',
    channel_width_um: '100',
    channel_height_um: '100',
    viscosity_pa_s: '0.001',
    surface_tension: '0.04',
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }))

  async function run() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const args = buildDropletArgs(form)
      const data = await callTool('microfluidics_droplet', args)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2 p-3">
      <div className="text-[10px] text-ink-500 mb-2">
        Predict droplet size, volume, and generation frequency.
        T-junction: Garstecki 2006 / van Steijn 2010. Flow-focusing: Anna 2003.
      </div>

      <FieldRow label="Geometry">
        <Select
          value={form.geometry}
          onChange={set('geometry')}
          options={[
            ['t_junction', 'T-junction'],
            ['flow_focusing', 'Flow-focusing'],
          ]}
        />
      </FieldRow>

      <FieldRow label="Q continuous [µL/min]">
        <NumInput value={form.q_continuous_ul_min} onChange={set('q_continuous_ul_min')} placeholder="2" min="0" />
      </FieldRow>

      <FieldRow label="Q dispersed [µL/min]">
        <NumInput value={form.q_dispersed_ul_min} onChange={set('q_dispersed_ul_min')} placeholder="0.5" min="0" />
      </FieldRow>

      <FieldRow label="Channel width [µm]">
        <NumInput value={form.channel_width_um} onChange={set('channel_width_um')} placeholder="100" min="0" />
      </FieldRow>

      <FieldRow label="Channel height [µm]">
        <NumInput value={form.channel_height_um} onChange={set('channel_height_um')} placeholder="100" min="0" />
      </FieldRow>

      <FieldRow label="Viscosity [Pa·s]">
        <NumInput value={form.viscosity_pa_s} onChange={set('viscosity_pa_s')} placeholder="0.001" />
      </FieldRow>

      <FieldRow label="Surface tension [N/m]">
        <NumInput value={form.surface_tension} onChange={set('surface_tension')} placeholder="0.04" />
      </FieldRow>

      <RunButton loading={loading} onClick={run}>Calculate</RunButton>
      <ErrorBanner error={error} />
      {result && <ResultTable data={result} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Rayleigh-Plateau
// ---------------------------------------------------------------------------

function RayleighTab() {
  const [form, setForm] = useState({
    thread_radius_um: '25',
    density_kg_m3: '1000',
    surface_tension: '0.072',
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const set = (k) => (v) => setForm(f => ({ ...f, [k]: v }))

  async function run() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const args = {
        thread_radius_um: parseFloat(form.thread_radius_um),
        density_kg_m3: parseFloat(form.density_kg_m3),
        surface_tension_n_per_m: parseFloat(form.surface_tension),
      }
      const data = await callTool('microfluidics_rayleigh_plateau', args)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2 p-3">
      <div className="text-[10px] text-ink-500 mb-2">
        Rayleigh-Plateau instability for a liquid thread or jet.
        Computes λ_max ≈ 9.02 r₀, breakup time, and expected droplet diameter.
        Rayleigh 1878 (inviscid).
      </div>

      <FieldRow label="Thread radius [µm]">
        <NumInput value={form.thread_radius_um} onChange={set('thread_radius_um')} placeholder="25" min="0" />
      </FieldRow>

      <FieldRow label="Density [kg/m³]">
        <NumInput value={form.density_kg_m3} onChange={set('density_kg_m3')} placeholder="1000" min="0" />
      </FieldRow>

      <FieldRow label="Surface tension [N/m]">
        <NumInput value={form.surface_tension} onChange={set('surface_tension')} placeholder="0.072" />
      </FieldRow>

      <RunButton loading={loading} onClick={run}>Calculate</RunButton>
      <ErrorBanner error={error} />
      {result && <ResultTable data={result} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'channel', label: 'Channel', Icon: Waves },
  { id: 'droplet', label: 'Droplets', Icon: Droplets },
  { id: 'rayleigh', label: 'Jet / Thread', Icon: Calculator },
]

export default function MicrofluidicsPanel({ className = '' }) {
  const [activeTab, setActiveTab] = useState('channel')

  return (
    <div className={`flex flex-col h-full bg-ink-950 text-ink-100 ${className}`}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-800 flex-shrink-0">
        <Droplets size={14} className="text-blue-400" />
        <span className="text-[12px] font-medium text-ink-200">Microfluidics</span>
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
                ? 'text-blue-300 border-b-2 border-blue-400 bg-blue-950/20'
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
        {activeTab === 'channel' && <ChannelTab />}
        {activeTab === 'droplet' && <DropletTab />}
        {activeTab === 'rayleigh' && <RayleighTab />}
      </div>
    </div>
  )
}
