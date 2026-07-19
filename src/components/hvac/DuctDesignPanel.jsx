/**
 * DuctDesignPanel.jsx — Duct sizing tool for .hvac.duct files.
 *
 * Inputs: airflow per zone, duct material (roughness), max friction loss.
 * Outputs: duct cross-section (W×H or diameter), velocity, pressure drop
 *          per segment, total system pressure.
 *
 * Dispatches to:
 *   POST /api/tools/call  { tool: "hvac.size_duct",     args: {...} }
 *   POST /api/tools/call  { tool: "hvac.pressure_drop", args: {...} }
 */

import { useState, useCallback } from 'react'
import { Wind, Plus, Trash2, Calculator, Loader2, AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Tool dispatch
// ---------------------------------------------------------------------------

async function callTool(toolName, args, token) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
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
// ASHRAE roughness catalogue
// ---------------------------------------------------------------------------

export const MATERIAL_OPTIONS = [
  { key: 'galvanised_steel', label: 'Galvanised steel',    roughness_mm: 0.09 },
  { key: 'aluminium',        label: 'Aluminium (flexible)', roughness_mm: 0.2  },
  { key: 'fibreglass_liner', label: 'Fibreglass liner',    roughness_mm: 0.9  },
  { key: 'concrete',         label: 'Concrete duct',       roughness_mm: 1.5  },
  { key: 'unlined_steel',    label: 'Unlined mild steel',  roughness_mm: 0.046},
]

// ---------------------------------------------------------------------------
// Client-side Darcy-Weisbach (mirrors kerf-hvac pressure.py)
// ---------------------------------------------------------------------------

function colebrook(re, epsD) {
  if (re < 2300) return 64 / re
  let f = 0.25 / (Math.log10(epsD / 3.7 + 5.74 / Math.pow(re, 0.9))) ** 2
  for (let i = 0; i < 50; i++) {
    const fn = (1 / (-2 * Math.log10(epsD / 3.7 + 2.51 / (re * Math.sqrt(f))))) ** 2
    if (Math.abs(fn - f) < 1e-8) { f = fn; break }
    f = fn
  }
  return f
}

const RHO = 1.204 // kg/m³
const MU  = 1.81e-5

const FITTING_K = {
  elbow_90_rect:  0.30,
  elbow_90_round: 0.11,
  elbow_45_rect:  0.15,
  tee_main:       0.10,
  tee_branch:     0.90,
  reducer:        0.05,
}

function sizeRect(q_m3s, v_max_ms, maxAR = 4) {
  const A_min = q_m3s / v_max_ms
  const GRID = 0.025 // 25 mm modules
  let best = null
  for (let h = 0.100; h <= 2.0; h += GRID) {
    const w_min = A_min / h
    const w = Math.ceil(w_min / GRID) * GRID
    const ar = w / h
    if (ar > maxAR || ar < 0.25) continue
    const area = w * h
    const v    = q_m3s / area
    const dh   = 4 * area / (2 * (w + h))
    const perim = 2 * (w + h)
    if (!best || perim < best.perim) {
      best = { w_mm: Math.round(w * 1000), h_mm: Math.round(h * 1000), area, v, dh, perim, ar }
    }
  }
  return best
}

export function computeDuctSegment(seg, roughness_mm) {
  const { airflow_cfm, max_velocity_fpm, shape, length_m, fittings } = seg
  const q_m3s  = airflow_cfm * 4.719474432e-4
  const v_max  = max_velocity_fpm * 0.00508

  let w_mm, h_mm, d_mm, area, v, dh_m

  if (shape === 'round') {
    const d = Math.ceil(Math.sqrt(4 * q_m3s / (Math.PI * v_max)) / 0.025) * 0.025
    d_mm = Math.round(d * 1000)
    area = Math.PI * d * d / 4
    v    = q_m3s / area
    dh_m = d
  } else {
    const r = sizeRect(q_m3s, v_max)
    if (!r) return null
    w_mm = r.w_mm; h_mm = r.h_mm; area = r.area; v = r.v; dh_m = r.dh
  }

  const re    = RHO * v * dh_m / MU
  const epsD  = (roughness_mm / 1000) / dh_m
  const f     = colebrook(re, epsD)
  const vp    = 0.5 * RHO * v * v
  const frict = f * (length_m / dh_m) * vp
  const kTotal = (fittings || []).reduce((acc, ft) => acc + (FITTING_K[ft] || 0), 0)
  const minor   = kTotal * vp

  return {
    w_mm, h_mm, d_mm, shape,
    actual_velocity_fpm: +(v / 0.00508).toFixed(0),
    actual_velocity_m_s: +v.toFixed(3),
    hydraulic_diameter_mm: +(dh_m * 1000).toFixed(1),
    friction_pa: +frict.toFixed(2),
    fittings_pa: +minor.toFixed(2),
    total_pa:    +(frict + minor).toFixed(2),
    friction_factor: +f.toFixed(6),
    reynolds: Math.round(re),
  }
}

// ---------------------------------------------------------------------------
// Backend tool-call payload builders — pulled out of `calculate()` as pure
// functions so the exact request shape is independently unit-testable
// (this repo has no jsdom/@testing-library/react install, so these can't be
// exercised via simulated clicks; see DuctDesignPanel.test.jsx).
// ---------------------------------------------------------------------------

/** Build the args object for the `hvac.size_duct` tool call from a segment. */
export function buildSizeDuctArgs(seg) {
  return {
    airflow_cfm: parseFloat(seg.airflow_cfm),
    max_velocity_fpm: parseFloat(seg.max_velocity_fpm),
    shape: seg.shape,
  }
}

/**
 * Build the args object for the `hvac.pressure_drop` tool call from the
 * `hvac.size_duct` response + the originating segment + duct roughness.
 */
export function buildPressureDropArgs(sizeResp, seg, roughness_mm) {
  return {
    velocity_m_s:          sizeResp.actual_velocity_m_s,
    hydraulic_diameter_mm: sizeResp.hydraulic_diameter_mm,
    length_m:              parseFloat(seg.length_m),
    roughness_mm,
    fittings: seg.fittings || [],
  }
}

// ---------------------------------------------------------------------------
// Segment row
// ---------------------------------------------------------------------------

/**
 * TotalPressureDisplay — the "Total system pressure" summary row.
 * Pulled out as its own component (like SegmentRow below) so it can be
 * exercised directly with a fixed value via renderToStaticMarkup, since
 * @testing-library/react isn't installed and the total is only reachable
 * through internal `calculate()` state otherwise.
 */
export function TotalPressureDisplay({ total }) {
  return (
    <div className="flex items-center justify-between p-2.5 rounded-md bg-kerf-300/5 border border-kerf-300/30">
      <span className="text-[11px] text-ink-300 font-medium">Total system pressure</span>
      <span className="text-base font-bold text-kerf-300 font-mono">{total} Pa</span>
    </div>
  )
}

function SegmentRow({ seg, idx, onChange, onRemove, result }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border border-ink-800 rounded-md overflow-hidden">
      <div className="flex items-center gap-2 px-2 py-1.5 bg-ink-900">
        <button type="button" onClick={() => setExpanded(v => !v)} className="text-ink-500 hover:text-ink-200">
          {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </button>
        <span className="text-[10px] font-medium text-ink-300 flex-1">Segment {idx + 1}</span>
        {result && (
          <span className="text-[10px] text-green-400 font-mono">
            {seg.shape === 'round'
              ? `∅${result.d_mm} mm`
              : `${result.w_mm}×${result.h_mm} mm`}
            {' · '}
            {result.total_pa} Pa
          </span>
        )}
        <button type="button" onClick={onRemove} className="text-ink-600 hover:text-red-400">
          <Trash2 size={11} />
        </button>
      </div>

      {expanded && (
        <div className="px-3 py-2 bg-ink-950 grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-ink-500">Airflow (CFM)</span>
            <input type="number" value={seg.airflow_cfm} min="0"
              onChange={e => onChange({ ...seg, airflow_cfm: e.target.value })}
              className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300/60"
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-ink-500">Max velocity (FPM)</span>
            <input type="number" value={seg.max_velocity_fpm} min="0"
              onChange={e => onChange({ ...seg, max_velocity_fpm: e.target.value })}
              className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300/60"
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-ink-500">Shape</span>
            <select value={seg.shape} onChange={e => onChange({ ...seg, shape: e.target.value })}
              className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300/60">
              <option value="rectangular">Rectangular</option>
              <option value="round">Round</option>
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-ink-500">Length (m)</span>
            <input type="number" value={seg.length_m} min="0" step="0.5"
              onChange={e => onChange({ ...seg, length_m: e.target.value })}
              className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300/60"
            />
          </label>

          <div className="col-span-2">
            <span className="text-[10px] text-ink-500">Fittings (multi-select)</span>
            <div className="mt-1 flex flex-wrap gap-1">
              {Object.keys(FITTING_K).map(ft => (
                <label key={ft} className="flex items-center gap-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={(seg.fittings || []).includes(ft)}
                    onChange={e => {
                      const fittings = seg.fittings || []
                      const next = e.target.checked
                        ? [...fittings, ft]
                        : fittings.filter(f => f !== ft)
                      onChange({ ...seg, fittings: next })
                    }}
                    className="accent-kerf-300"
                  />
                  <span className="text-[10px] text-ink-400">{ft.replace(/_/g, ' ')}</span>
                </label>
              ))}
            </div>
          </div>

          {result && (
            <div className="col-span-2 border-t border-ink-800 pt-2 grid grid-cols-3 gap-1">
              {[
                ['Width × Height', result.w_mm ? `${result.w_mm}×${result.h_mm} mm` : `∅${result.d_mm} mm`],
                ['Velocity', `${result.actual_velocity_fpm} FPM`],
                ['Hyd. diameter', `${result.hydraulic_diameter_mm} mm`],
                ['Friction loss', `${result.friction_pa} Pa`],
                ['Fitting loss', `${result.fittings_pa} Pa`],
                ['Total loss', `${result.total_pa} Pa`],
              ].map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5">
                  <span className="text-[9px] text-ink-600">{k}</span>
                  <span className="text-[10px] font-mono text-ink-200">{v}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// DuctDesignPanel
// ---------------------------------------------------------------------------

let _segId = 0
const mkId = () => ++_segId

export default function DuctDesignPanel() {
  const { accessToken } = useAuth()

  const [material, setMaterial] = useState('galvanised_steel')
  const [segments, setSegments] = useState([
    { id: mkId(), airflow_cfm: '1000', max_velocity_fpm: '2000', shape: 'rectangular', length_m: '10', fittings: [] },
  ])
  const [results,  setResults]  = useState({})
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const roughness_mm = MATERIAL_OPTIONS.find(m => m.key === material)?.roughness_mm ?? 0.09

  const addSegment = () =>
    setSegments(prev => [...prev, { id: mkId(), airflow_cfm: '500', max_velocity_fpm: '1500', shape: 'rectangular', length_m: '6', fittings: [] }])

  const updateSegment = (id, next) =>
    setSegments(prev => prev.map(s => s.id === id ? { ...s, ...next } : s))

  const removeSegment = (id) =>
    setSegments(prev => prev.filter(s => s.id !== id))

  const calculate = useCallback(async () => {
    setLoading(true)
    setError(null)

    const newResults = {}
    let totalLoss = 0

    try {
      for (const seg of segments) {
        const q_cfm = parseFloat(seg.airflow_cfm)
        const v_fpm = parseFloat(seg.max_velocity_fpm)
        const L     = parseFloat(seg.length_m)

        // Try backend first
        let segResult = null
        try {
          const sizeResp = await callTool('hvac.size_duct', buildSizeDuctArgs(seg), accessToken)

          const dpResp = await callTool(
            'hvac.pressure_drop',
            buildPressureDropArgs(sizeResp, seg, roughness_mm),
            accessToken,
          )

          segResult = {
            w_mm:   sizeResp.width_mm,
            h_mm:   sizeResp.height_mm,
            d_mm:   sizeResp.diameter_mm,
            shape:  sizeResp.shape,
            actual_velocity_fpm:  sizeResp.actual_velocity_fpm,
            actual_velocity_m_s:  sizeResp.actual_velocity_m_s,
            hydraulic_diameter_mm: sizeResp.hydraulic_diameter_mm,
            friction_pa: dpResp.friction_pa,
            fittings_pa: dpResp.fittings_pa,
            total_pa:    dpResp.total_pa,
            friction_factor: dpResp.friction_factor,
            reynolds: dpResp.reynolds_number,
          }
        } catch {
          // Fallback to client-side
          segResult = computeDuctSegment({
            airflow_cfm: q_cfm,
            max_velocity_fpm: v_fpm,
            shape: seg.shape,
            length_m: L,
            fittings: seg.fittings,
          }, roughness_mm)
        }

        if (segResult) {
          newResults[seg.id] = segResult
          totalLoss += segResult.total_pa || 0
        }
      }

      setResults({ ...newResults, _total: +totalLoss.toFixed(2) })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [segments, roughness_mm, accessToken])

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-3 text-xs">
      <h2 className="text-[11px] font-semibold text-ink-200 uppercase tracking-wider">
        ASHRAE Duct Sizing Tool
      </h2>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-ink-500">Duct material</label>
        <select
          value={material}
          onChange={e => setMaterial(e.target.value)}
          className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300/60"
        >
          {MATERIAL_OPTIONS.map(m => (
            <option key={m.key} value={m.key}>{m.label} (ε={m.roughness_mm} mm)</option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        {segments.map((seg, idx) => (
          <SegmentRow
            key={seg.id}
            seg={seg}
            idx={idx}
            onChange={next => updateSegment(seg.id, next)}
            onRemove={() => removeSegment(seg.id)}
            result={results[seg.id]}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={addSegment}
        className="flex items-center gap-1.5 self-start px-2 py-1 rounded border border-ink-700 text-ink-400 hover:text-ink-200 hover:border-ink-600 text-[11px]"
      >
        <Plus size={11} />
        Add segment
      </button>

      <button
        type="button"
        onClick={calculate}
        disabled={loading || segments.length === 0}
        className="flex items-center justify-center gap-2 w-full py-2 rounded-md bg-kerf-300/15 border border-kerf-300/40 text-kerf-200 hover:bg-kerf-300/25 disabled:opacity-50 text-xs font-medium"
      >
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Calculator size={12} />}
        {loading ? 'Sizing ducts…' : 'Size all segments'}
      </button>

      {error && (
        <div className="flex items-start gap-2 p-2 rounded bg-red-950/40 border border-red-700/40 text-red-300 text-[11px]">
          <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {results._total != null && <TotalPressureDisplay total={results._total} />}

      <div className="text-[10px] text-ink-600 pt-1">
        Darcy-Weisbach / Colebrook-White · ASHRAE HoF 2021 Ch. 21
      </div>
    </div>
  )
}
