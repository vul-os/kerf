/**
 * CrownSculptingPanel — anatomic crown sculpting UI.
 *
 * Preset picker (incisor / canine / premolar / molar), cusp height/angle sliders,
 * occlusion-contact SVG overlay, and Run button that dispatches
 * `dental_crown_design` via POST /api/tools/call.
 *
 * Backend tool: packages/kerf-dental/src/kerf_dental/tools.py → dental_crown_design
 */

import { useState } from 'react'
import { useAuth } from '../../store/auth.js'
import { buildCrownDesignPayload } from './dentalDispatch.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Anatomic presets — margin polygon + opposing cusp heights for each tooth type
// ---------------------------------------------------------------------------
const PRESETS = {
  incisor: {
    label: 'Incisor',
    n_cusps: 2,
    cusp_depth_fraction: 0.10,
    margin_line: [
      [0, 0, 0], [3, 0, 0], [3, 6, 0], [0, 6, 0],
    ],
    opposing_cusp_heights_mm: [3.5],
    occlusal_clearance_mm: 0.3,
    description: '2-cusp, flat lingual shelf, 0.3 mm clearance',
  },
  canine: {
    label: 'Canine',
    n_cusps: 2,
    cusp_depth_fraction: 0.15,
    margin_line: [
      [0, 0, 0], [4, 0, 0], [4, 7, 0], [0, 7, 0],
    ],
    opposing_cusp_heights_mm: [4.0, 4.5],
    occlusal_clearance_mm: 0.4,
    description: '2-cusp, prominent cusp tip, 0.4 mm clearance',
  },
  premolar: {
    label: 'Premolar',
    n_cusps: 2,
    cusp_depth_fraction: 0.20,
    margin_line: [
      [0, 0, 0], [5, 0, 0], [5, 7, 0], [0, 7, 0],
    ],
    opposing_cusp_heights_mm: [3.0, 3.5],
    occlusal_clearance_mm: 0.5,
    description: '2-cusp (buccal + lingual), 0.5 mm clearance',
  },
  molar: {
    label: 'Molar',
    n_cusps: 4,
    cusp_depth_fraction: 0.22,
    margin_line: [
      [0, 0, 0], [9, 0, 0], [9, 10, 0], [0, 10, 0],
    ],
    opposing_cusp_heights_mm: [3.0, 3.0, 3.5, 3.5],
    occlusal_clearance_mm: 0.5,
    description: '4-cusp (MB/DB/ML/DL), 0.5 mm clearance',
  },
}

const MATERIALS = ['zirconia', 'PMMA', 'e.max', 'composite', 'gold alloy']

// ---------------------------------------------------------------------------
// Occlusion contact SVG overlay
// A simplified 2-D occlusal view: crown outline + cusp contact dots.
// ---------------------------------------------------------------------------
function OcclusionOverlay({ preset, nCusps, cuspDepth }) {
  if (!preset) return null

  const W = 200
  const H = 160
  const PAD = 20

  // Scale the margin polygon to the SVG viewport
  const pts = preset.margin_line
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const rangeX = Math.max(...xs) - minX || 1
  const rangeY = Math.max(...ys) - minY || 1
  const toSvg = (x, y) => [
    PAD + ((x - minX) / rangeX) * (W - 2 * PAD),
    PAD + ((y - minY) / rangeY) * (H - 2 * PAD),
  ]

  const polygon = pts.map((p) => toSvg(p[0], p[1]).join(',')).join(' ')

  // Place cusp contact dots evenly inside the outline
  const cx = PAD + (W - 2 * PAD) / 2
  const cy = PAD + (H - 2 * PAD) / 2
  const cuspRadius = Math.max(3, cuspDepth * 20)
  const cuspDots = []
  if (nCusps === 2) {
    cuspDots.push([cx - (W - 2 * PAD) * 0.25, cy])
    cuspDots.push([cx + (W - 2 * PAD) * 0.25, cy])
  } else {
    // 4 cusps: 2x2 grid
    const dx = (W - 2 * PAD) * 0.22
    const dy = (H - 2 * PAD) * 0.22
    cuspDots.push([cx - dx, cy - dy])
    cuspDots.push([cx + dx, cy - dy])
    cuspDots.push([cx - dx, cy + dy])
    cuspDots.push([cx + dx, cy + dy])
  }

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      aria-label="Occlusal contact overlay"
      className="rounded border border-ink-700 bg-ink-950"
    >
      {/* Crown outline */}
      <polygon
        points={polygon}
        fill="none"
        stroke="#4ade80"
        strokeWidth="1.5"
        opacity="0.7"
      />
      {/* Contact area fill */}
      <polygon
        points={polygon}
        fill="#4ade80"
        fillOpacity="0.06"
      />
      {/* Cusp contact dots */}
      {cuspDots.map(([x, y], i) => (
        <circle
          key={i}
          cx={x}
          cy={y}
          r={cuspRadius}
          fill="#f59e0b"
          fillOpacity="0.85"
          stroke="#fbbf24"
          strokeWidth="1"
        />
      ))}
      {/* Labels */}
      <text x="6" y="14" fontSize="9" fill="#6b7280" fontFamily="monospace">
        occlusal view
      </text>
      {cuspDots.map(([x, y], i) => (
        <text key={`l${i}`} x={x - 3} y={y + 12} fontSize="8" fill="#fbbf24" fontFamily="monospace">
          C{i + 1}
        </text>
      ))}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------
export default function CrownSculptingPanel({ projectId }) {
  const { accessToken } = useAuth()
  const [presetKey, setPresetKey] = useState('molar')
  const [material, setMaterial] = useState('zirconia')
  const [cuspDepth, setCuspDepth] = useState(PRESETS.molar.cusp_depth_fraction)
  const [clearance, setClearance] = useState(PRESETS.molar.occlusal_clearance_mm)
  const [nCusps, setNCusps] = useState(PRESETS.molar.n_cusps)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const preset = PRESETS[presetKey]

  function handlePresetChange(key) {
    const p = PRESETS[key]
    setPresetKey(key)
    setCuspDepth(p.cusp_depth_fraction)
    setClearance(p.occlusal_clearance_mm)
    setNCusps(p.n_cusps)
    setResult(null)
    setError(null)
  }

  async function handleRun() {
    setRunning(true)
    setResult(null)
    setError(null)
    try {
      const body = buildCrownDesignPayload({
        margin_line: preset.margin_line,
        opposing_cusp_heights_mm: preset.opposing_cusp_heights_mm,
        material,
        occlusal_clearance_mm: clearance,
        n_cusps: nCusps,
        cusp_depth_fraction: cuspDepth,
      })
      const res = await fetch(`${API_URL}/api/tools/call`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data?.error || `HTTP ${res.status}`)
      } else {
        setResult(data)
      }
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4 text-ink-100" data-testid="crown-sculpting-panel">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-mono uppercase tracking-widest text-ink-400">Crown Sculpting</span>
        <span className="ml-auto text-[10px] text-ink-600 font-mono">dental_crown_design</span>
      </div>

      {/* Anatomic preset picker */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">Tooth type</label>
        <div className="grid grid-cols-4 gap-1">
          {Object.entries(PRESETS).map(([key, p]) => (
            <button
              key={key}
              type="button"
              onClick={() => handlePresetChange(key)}
              className={`py-1.5 px-1 rounded text-xs font-medium border transition-colors ${
                presetKey === key
                  ? 'bg-emerald-500/20 border-emerald-400/60 text-emerald-200'
                  : 'bg-ink-800 border-ink-700 text-ink-300 hover:bg-ink-700'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <p className="mt-1 text-[10px] text-ink-500">{preset.description}</p>
      </div>

      {/* Material */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">Material</label>
        <select
          value={material}
          onChange={(e) => setMaterial(e.target.value)}
          className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1.5 text-xs text-ink-100 outline-none focus:border-emerald-400/60"
        >
          {MATERIALS.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

      {/* Sliders */}
      <div className="flex flex-col gap-3">
        {/* n_cusps */}
        <div>
          <label className="flex items-center justify-between text-[11px] text-ink-400 mb-1">
            <span>Cusps</span>
            <span className="font-mono text-emerald-300">{nCusps}</span>
          </label>
          <input
            type="range"
            min="2"
            max="4"
            step="2"
            value={nCusps}
            onChange={(e) => setNCusps(Number(e.target.value))}
            className="w-full accent-emerald-400"
          />
          <div className="flex justify-between text-[10px] text-ink-600">
            <span>2 (premolar)</span>
            <span>4 (molar)</span>
          </div>
        </div>

        {/* cusp_depth_fraction */}
        <div>
          <label className="flex items-center justify-between text-[11px] text-ink-400 mb-1">
            <span>Cusp depth fraction</span>
            <span className="font-mono text-emerald-300">{cuspDepth.toFixed(2)}</span>
          </label>
          <input
            type="range"
            min="0.10"
            max="0.30"
            step="0.01"
            value={cuspDepth}
            onChange={(e) => setCuspDepth(parseFloat(e.target.value))}
            className="w-full accent-emerald-400"
          />
          <div className="flex justify-between text-[10px] text-ink-600">
            <span>0.10 (shallow)</span>
            <span>0.30 (deep)</span>
          </div>
        </div>

        {/* occlusal_clearance_mm */}
        <div>
          <label className="flex items-center justify-between text-[11px] text-ink-400 mb-1">
            <span>Occlusal clearance</span>
            <span className="font-mono text-emerald-300">{clearance.toFixed(1)} mm</span>
          </label>
          <input
            type="range"
            min="0.2"
            max="1.0"
            step="0.1"
            value={clearance}
            onChange={(e) => setClearance(parseFloat(e.target.value))}
            className="w-full accent-emerald-400"
          />
          <div className="flex justify-between text-[10px] text-ink-600">
            <span>0.2 mm</span>
            <span>1.0 mm</span>
          </div>
        </div>
      </div>

      {/* Occlusion contact SVG overlay */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">Occlusion contacts</label>
        <OcclusionOverlay preset={preset} nCusps={nCusps} cuspDepth={cuspDepth} />
      </div>

      {/* Run button */}
      <button
        type="button"
        onClick={handleRun}
        disabled={running}
        className="flex items-center justify-center gap-2 px-4 py-2 rounded bg-emerald-500/20 border border-emerald-400/50 text-emerald-200 text-xs font-medium hover:bg-emerald-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {running ? (
          <>
            <span className="w-3 h-3 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
            Running…
          </>
        ) : (
          'Run dental_crown_design'
        )}
      </button>

      {/* Result */}
      {result && (
        <div
          className="rounded border border-emerald-700/50 bg-emerald-950/30 p-3 text-[11px] font-mono text-emerald-300 space-y-1"
          data-testid="crown-result"
        >
          <div className="text-emerald-400 font-semibold mb-1">Crown designed</div>
          {result.crown_radius_mm != null && (
            <div>radius: <span className="text-emerald-200">{result.crown_radius_mm} mm</span></div>
          )}
          {result.crown_height_mm != null && (
            <div>height: <span className="text-emerald-200">{result.crown_height_mm} mm</span></div>
          )}
          {result.material && (
            <div>material: <span className="text-emerald-200">{result.material}</span></div>
          )}
          {result.n_cusps != null && (
            <div>cusps: <span className="text-emerald-200">{result.n_cusps}</span></div>
          )}
          {result.validate_body_ok && (
            <div className="text-emerald-400">validate_body: OK</div>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          className="rounded border border-red-700/50 bg-red-950/30 p-3 text-[11px] font-mono text-red-300"
          data-testid="crown-error"
        >
          {error}
        </div>
      )}
    </div>
  )
}
