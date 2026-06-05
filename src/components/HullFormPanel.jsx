// HullFormPanel.jsx — Parametric hull form panel for Kerf Marine.
//
// Wires the marine_hull_form LLM tool:
//   marine_hull_form — generate body plan from L/B/T/Cb/Cm + Lackenby shift
//
// Renders:
//   - Hull parameter inputs (L, B, T, Cb, Cm, LCB fraction)
//   - Body-plan SVG (section curves at each station)
//   - Waterlines plan-view SVG
//   - Summary card (achieved Cb, Cp, LCB, volume)
//   - Feed-to-hydrostatics button
//
// Pattern: dark mono palette, no external chart deps.

import { useState, useCallback, useMemo } from 'react'
import {
  Ship,
  Sliders,
  Play,
  Loader2,
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Waves,
  Ruler,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const API_URL =
  typeof import.meta !== 'undefined' && import.meta.env
    ? import.meta.env.VITE_API_URL || ''
    : ''

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  const data = await res.json()
  if (typeof data.result === 'string') {
    try { return JSON.parse(data.result) } catch { return data.result }
  }
  return data.result ?? data
}

function scaleLinear(domain, range) {
  const [d0, d1] = domain
  const [r0, r1] = range
  const dSpan = d1 - d0 || 1
  return v => r0 + ((v - d0) / dSpan) * (r1 - r0)
}

// ---------------------------------------------------------------------------
// Body plan chart (half-breadth vs waterline per section)
// ---------------------------------------------------------------------------

const BP_W = 500
const BP_H = 200
const BP_PAD = { top: 14, right: 14, bottom: 36, left: 44 }
const BP_IW = BP_W - BP_PAD.left - BP_PAD.right
const BP_IH = BP_H - BP_PAD.top - BP_PAD.bottom

const SECTION_COLORS = [
  '#34d399', '#60a5fa', '#f97316', '#a78bfa', '#fb7185',
  '#fbbf24', '#2dd4bf', '#e879f9',
]

function BodyPlanChart({ sections, B, T }) {
  if (!sections || sections.length === 0) return null

  const xS = scaleLinear([0, B / 2], [0, BP_IW])
  const yS = scaleLinear([0, T], [BP_IH, 0])

  const stride = Math.max(1, Math.floor(sections.length / 12))
  const displayed = sections.filter((_, i) => i % stride === 0 || i === sections.length - 1)

  return (
    <div>
      <p className="text-xs text-gray-500 mb-1">Body plan (half-section, starboard)</p>
      <svg width={BP_W} height={BP_H} viewBox={`0 0 ${BP_W} ${BP_H}`} className="overflow-visible">
        <g transform={`translate(${BP_PAD.left},${BP_PAD.top})`}>
          {/* Grid */}
          {[0, T * 0.25, T * 0.5, T * 0.75, T].map(z => (
            <line key={z} x1={0} y1={yS(z)} x2={BP_IW} y2={yS(z)}
              stroke="#1f2937" strokeWidth={0.5} />
          ))}
          {[0, B / 8, B / 4, B * 3 / 8, B / 2].map(y => (
            <line key={y} x1={xS(y)} y1={0} x2={xS(y)} y2={BP_IH}
              stroke="#1f2937" strokeWidth={0.5} />
          ))}

          {/* Sections */}
          {displayed.map((sec, ci) => {
            const pts = sec.points || []
            if (pts.length < 2) return null
            const d = pts.map((p, i) => {
              const x = xS(p.half_breadth_m)
              const y = yS(p.waterline_m)
              return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
            }).join(' ')
            const color = SECTION_COLORS[ci % SECTION_COLORS.length]
            return <path key={ci} d={d} fill="none" stroke={color} strokeWidth={1.5} />
          })}

          {/* Axes */}
          <line x1={0} y1={0} x2={0} y2={BP_IH} stroke="#6b7280" strokeWidth={1} />
          <line x1={0} y1={BP_IH} x2={BP_IW} y2={BP_IH} stroke="#6b7280" strokeWidth={1} />
          {/* DWL line */}
          <line x1={0} y1={yS(T)} x2={BP_IW} y2={yS(T)} stroke="#60a5fa" strokeWidth={1} strokeDasharray="4,2" />

          {/* X-axis labels */}
          {[0, B / 4, B / 2].map(y => (
            <text key={y} x={xS(y)} y={BP_IH + 14} textAnchor="middle" fontSize={9} fill="#6b7280">
              {y.toFixed(1)}
            </text>
          ))}
          <text x={BP_IW / 2} y={BP_IH + 26} textAnchor="middle" fontSize={8} fill="#4b5563">
            Half-breadth (m)
          </text>

          {/* Y-axis labels */}
          {[0, T * 0.5, T].map(z => (
            <text key={z} x={-6} y={yS(z)} textAnchor="end" dominantBaseline="middle" fontSize={9} fill="#6b7280">
              {z.toFixed(1)}
            </text>
          ))}
          <text
            transform={`translate(-32,${BP_IH / 2}) rotate(-90)`}
            textAnchor="middle" fontSize={8} fill="#4b5563"
          >
            Waterline (m)
          </text>

          {/* Labels */}
          <text x={BP_IW} y={yS(T) - 4} textAnchor="end" fontSize={8} fill="#60a5fa">DWL</text>
        </g>
      </svg>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Waterlines plan-view chart
// ---------------------------------------------------------------------------

const WL_W = 500
const WL_H = 160
const WL_PAD = { top: 14, right: 14, bottom: 36, left: 44 }
const WL_IW = WL_W - WL_PAD.left - WL_PAD.right
const WL_IH = WL_H - WL_PAD.top - WL_PAD.bottom

function WaterlinesChart({ waterlines, L }) {
  if (!waterlines || waterlines.length === 0) return null

  const xS = scaleLinear([0, L], [0, WL_IW])
  const allHB = waterlines.flatMap(wl => wl.half_breadths_m || [])
  const maxHB = Math.max(...allHB) || 1
  const yS = scaleLinear([-maxHB, maxHB], [WL_IH, 0])

  return (
    <div>
      <p className="text-xs text-gray-500 mb-1">Waterlines plan (CL = centre, both sides)</p>
      <svg width={WL_W} height={WL_H} viewBox={`0 0 ${WL_W} ${WL_H}`} className="overflow-visible">
        <g transform={`translate(${WL_PAD.left},${WL_PAD.top})`}>
          {/* CL */}
          <line x1={0} y1={yS(0)} x2={WL_IW} y2={yS(0)} stroke="#374151" strokeWidth={0.5} strokeDasharray="4,2" />

          {/* Waterlines */}
          {waterlines.map((wl, wi) => {
            const stns = wl.stations_m || []
            const hbs = wl.half_breadths_m || []
            if (stns.length < 2) return null
            const color = SECTION_COLORS[wi % SECTION_COLORS.length]

            const dPort = stns.map((s, i) =>
              `${i === 0 ? 'M' : 'L'}${xS(s).toFixed(1)},${yS(hbs[i]).toFixed(1)}`
            ).join(' ')
            const dStarboard = stns.map((s, i) =>
              `${i === 0 ? 'M' : 'L'}${xS(s).toFixed(1)},${yS(-hbs[i]).toFixed(1)}`
            ).join(' ')

            return (
              <g key={wi}>
                <path d={dPort} fill="none" stroke={color} strokeWidth={1.5} />
                <path d={dStarboard} fill="none" stroke={color} strokeWidth={1.5} strokeDasharray="2,2" />
                <text x={xS(stns[stns.length - 1]) + 4} y={yS(hbs[hbs.length - 1])}
                  fontSize={8} fill={color} dominantBaseline="middle">
                  {wl.draft_m?.toFixed(1)}m
                </text>
              </g>
            )
          })}

          {/* Axes */}
          <line x1={0} y1={0} x2={0} y2={WL_IH} stroke="#6b7280" strokeWidth={1} />
          <line x1={0} y1={WL_IH} x2={WL_IW} y2={WL_IH} stroke="#6b7280" strokeWidth={1} />

          {[0, L / 4, L / 2, L * 3 / 4, L].map(s => (
            <g key={s} transform={`translate(${xS(s)},${WL_IH})`}>
              <line y2={3} stroke="#6b7280" />
              <text y={13} textAnchor="middle" fontSize={9} fill="#6b7280">{s.toFixed(0)}</text>
            </g>
          ))}
          <text x={WL_IW / 2} y={WL_IH + 26} textAnchor="middle" fontSize={8} fill="#4b5563">
            Station from AP (m)
          </text>
        </g>
      </svg>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary card
// ---------------------------------------------------------------------------

function SummaryCard({ hull }) {
  if (!hull) return null
  const rows = [
    ['Block coeff. Cb', hull.Cb?.toFixed(3)],
    ['Midship coeff. Cm', hull.Cm?.toFixed(3)],
    ['Prismatic coeff. Cp', hull.Cp?.toFixed(3)],
    ['LCB (frac. of L)', hull.lcb_frac?.toFixed(3)],
    ['LCB from AP', `${hull.lcb_m_from_ap?.toFixed(2)} m`],
    ['Volume ∇', `${hull.volume_m3?.toFixed(1)} m³`],
    ['L × B × T', `${hull.L_m} × ${hull.B_m} × ${hull.T_m} m`],
    ['Sections', hull.n_sections],
    ['Waterlines', hull.n_waterlines],
    ['Buttocks', hull.n_buttocks],
  ]
  return (
    <div className="rounded-lg border border-gray-700 p-3 bg-gray-900">
      <p className="text-xs font-semibold text-gray-300 mb-2 uppercase tracking-wide">Hull Form Summary</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {rows.map(([label, val]) => (
          <div key={label} className="flex justify-between text-xs">
            <span className="text-gray-500">{label}</span>
            <span className="text-gray-200 font-mono">{val ?? '—'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const DEFAULT_PARAMS = {
  L: 60,
  B: 10,
  T: 4,
  Cb: 0.60,
  Cm: 0.90,
  lcb_frac: '',
  n_stations: 21,
  n_wl_curves: 5,
  n_buttocks: 5,
}

export default function HullFormPanel({ onHullReady, initialParams, content }) {
  // Backward-compatible content string: JSON.parse it and merge initial params.
  let _parsedParams = null
  if (content != null) {
    try {
      const _p = JSON.parse(content)
      if (_p && typeof _p === 'object' && !Array.isArray(_p)) _parsedParams = _p
    } catch { /* ignore */ }
  }
  const _initParams = initialParams ?? _parsedParams ?? null
  const [params, setParams] = useState(_initParams ? { ...DEFAULT_PARAMS, ..._initParams } : DEFAULT_PARAMS)
  const [hull, setHull] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showAdvanced, setShowAdvanced] = useState(false)

  const handleChange = useCallback((key, val) => {
    setParams(p => ({ ...p, [key]: val }))
  }, [])

  const handleGenerate = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const args = {
        L: Number(params.L),
        B: Number(params.B),
        T: Number(params.T),
        Cb: Number(params.Cb),
        Cm: Number(params.Cm),
        n_stations: Number(params.n_stations),
        n_wl_curves: Number(params.n_wl_curves),
        n_buttocks: Number(params.n_buttocks),
      }
      if (params.lcb_frac !== '' && params.lcb_frac !== null) {
        args.lcb_frac = Number(params.lcb_frac)
      }
      const result = await callTool('marine_hull_form', args)
      if (result?.error) throw new Error(result.error)
      setHull(result)
      onHullReady?.(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [params, onHullReady])

  return (
    <div className="flex flex-col gap-4 p-4 bg-gray-950 text-gray-200 rounded-xl min-w-[540px]">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Ship size={18} className="text-cyan-400" />
        <span className="font-semibold text-gray-100">Hull Form Modelling</span>
        <span className="text-xs text-gray-500 ml-auto">NURBS parametric hull · Lackenby shift</span>
      </div>

      {/* Parameter inputs */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { key: 'L', label: 'L (m)', hint: 'LBP' },
          { key: 'B', label: 'B (m)', hint: 'Breadth' },
          { key: 'T', label: 'T (m)', hint: 'Draft' },
          { key: 'Cb', label: 'Cb', hint: '0.40–0.85' },
          { key: 'Cm', label: 'Cm', hint: '0.85–0.99' },
          { key: 'lcb_frac', label: 'LCB/L', hint: 'e.g. 0.51 (optional)' },
        ].map(({ key, label, hint }) => (
          <label key={key} className="flex flex-col gap-1">
            <span className="text-xs text-gray-400">{label}</span>
            <input
              type="number"
              step="any"
              value={params[key]}
              placeholder={hint}
              onChange={e => handleChange(key, e.target.value)}
              className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-cyan-500 w-full"
            />
            <span className="text-[10px] text-gray-600">{hint}</span>
          </label>
        ))}
      </div>

      {/* Advanced */}
      <button
        onClick={() => setShowAdvanced(v => !v)}
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 w-fit"
      >
        {showAdvanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Advanced options
      </button>
      {showAdvanced && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { key: 'n_stations', label: 'Stations', hint: '11–41' },
            { key: 'n_wl_curves', label: 'Waterlines', hint: '3–9' },
            { key: 'n_buttocks', label: 'Buttocks', hint: '3–7' },
          ].map(({ key, label, hint }) => (
            <label key={key} className="flex flex-col gap-1">
              <span className="text-xs text-gray-400">{label}</span>
              <input
                type="number"
                step="1"
                value={params[key]}
                onChange={e => handleChange(key, e.target.value)}
                className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100 focus:outline-none focus:border-cyan-500 w-full"
              />
              <span className="text-[10px] text-gray-600">{hint}</span>
            </label>
          ))}
        </div>
      )}

      {/* Generate button */}
      <button
        onClick={handleGenerate}
        disabled={loading}
        className="flex items-center justify-center gap-2 rounded-lg bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 px-4 py-2 text-sm font-medium text-white transition-colors"
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
        {loading ? 'Generating…' : 'Generate Hull Form'}
      </button>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-800 bg-red-950/40 p-3 text-sm text-red-300">
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {/* Results */}
      {hull && (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2 text-xs text-green-400">
            <CheckCircle size={12} />
            Hull form generated — {hull.n_sections} sections, {hull.n_waterlines} waterlines, {hull.n_buttocks} buttocks
          </div>

          <SummaryCard hull={hull} />

          <BodyPlanChart
            sections={hull.sections || []}
            B={hull.B_m}
            T={hull.T_m}
          />

          <WaterlinesChart
            waterlines={hull.waterlines || []}
            L={hull.L_m}
          />

          {/* Method notes */}
          <div className="rounded border border-gray-800 bg-gray-900/50 p-3 text-[10px] text-gray-500 leading-relaxed">
            <span className="text-gray-400 font-semibold">Method: </span>
            Lewis (1954) power-law prismatic sectional-area distribution;
            {params.lcb_frac !== '' && params.lcb_frac !== null
              ? ' Lackenby (1950) Δ(Ac)/Δ(Af) shift applied for LCB.'
              : ' no Lackenby shift (specify LCB/L to enable).'}
            <br />
            Ref: Lackenby 1950 RINA Trans. 92; SNAME PNA Vol. II §2.2–2.5.
          </div>
        </div>
      )}
    </div>
  )
}
