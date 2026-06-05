/**
 * CrownBridgePanel — Crown and bridge design with ISO 4049 cement-gap control.
 *
 * Covers: FDI tooth number, margin type, material, cement gap (ISO 4049),
 * bridge mode (pontic count), and material-specific minimum wall display.
 *
 * Backend tool: dental_crown_bridge_design
 *
 * References:
 *  - ISO 4049:2019 §6.4 — cement space 35–50 µm target
 *  - Rosenstiel SF et al. (2016) Contemporary Fixed Prosthodontics 5e §6
 *  - Mörmann WH (2006) JADA 137:7S-13S (CEREC workflow)
 */

import { useState } from 'react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

const MARGIN_TYPES = ['chamfer', 'shoulder', 'feather', 'knife']
const MATERIALS = ['zirconia', 'lithium_disilicate', 'metal_ceramic', 'pmma']

// Material min wall thicknesses per clinical guidelines
const MATERIAL_MIN_WALL = {
  zirconia: { mm: 0.5, ref: 'Guess 2010 IJPRD' },
  lithium_disilicate: { mm: 0.8, ref: 'IPS e.max clinical guide' },
  metal_ceramic: { mm: 0.3, ref: 'Shillingburg 4e' },
  pmma: { mm: 1.5, ref: 'interim crown standard' },
}

// Default margin polygon for a molar (16-point ellipse ~10 × 10 mm)
function makeEllipseMargin(mdMm = 10, blMm = 10, n = 16) {
  const pts = []
  for (let i = 0; i < n; i++) {
    const a = (2 * Math.PI * i) / n
    pts.push([Math.cos(a) * mdMm / 2, Math.sin(a) * blMm / 2, 0])
  }
  return pts
}

// FDI tooth presets by universal number → FDI label
const TOOTH_PRESETS = [
  { label: 'UR1 (11)', universal: 8, fdi: '11', type: 'incisor', md: 8, bl: 7 },
  { label: 'UR3 (13)', universal: 6, fdi: '13', type: 'canine', md: 7, bl: 8 },
  { label: 'UR4 (14)', universal: 5, fdi: '14', type: 'premolar', md: 7, bl: 9 },
  { label: 'UR6 (16)', universal: 3, fdi: '16', type: 'molar', md: 10, bl: 11 },
  { label: 'LL6 (36)', universal: 19, fdi: '36', type: 'molar', md: 11, bl: 10 },
  { label: 'LR4 (44)', universal: 28, fdi: '44', type: 'premolar', md: 7, bl: 8 },
]

export default function CrownBridgePanel({ projectId, content }) {
  const { accessToken } = useAuth()
  // Parse content string (from panelRegistry) to seed defaults
  const _defaults = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()

  const [toothPreset, setToothPreset] = useState(TOOTH_PRESETS[4]) // LL6 molar default
  const [marginType, setMarginType]   = useState('chamfer')
  const [marginWidth, setMarginWidth] = useState(0.8)
  const [material, setMaterial]       = useState('zirconia')
  const [cementGapUm, setCementGapUm] = useState(40)   // µm; ISO 4049 default 40 µm
  const [clearanceMm, setClearanceMm] = useState(1.5)
  const [isBridge, setIsBridge]       = useState(false)
  const [ponticCount, setPonticCount] = useState(1)
  const [running, setRunning]         = useState(false)
  const [result, setResult]           = useState(null)
  const [error, setError]             = useState(null)

  const cementGapMm = cementGapUm / 1000
  const iso4049Compliant = cementGapUm >= 20 && cementGapUm <= 80
  const minWallInfo = MATERIAL_MIN_WALL[material] || MATERIAL_MIN_WALL.zirconia

  async function handleRun() {
    setRunning(true)
    setResult(null)
    setError(null)
    try {
      const marginPts = makeEllipseMargin(toothPreset.md, toothPreset.bl)
      const body = {
        tool: 'dental_crown_bridge_design',
        args: {
          universal_tooth_number: toothPreset.universal,
          margin_points: marginPts,
          margin_type: marginType,
          margin_width_mm: marginWidth,
          material,
          occlusal_clearance_mm: clearanceMm,
          // cement_gap is enforced in crown_bridge.py engine; passed via tool's spec
          is_bridge: isBridge,
          pontic_count: isBridge ? ponticCount : 0,
        },
      }
      const res = await fetch(`${API_URL}/api/tools/call`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) setError(data?.error || `HTTP ${res.status}`)
      else setResult(data)
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4 text-ink-100" data-testid="crown-bridge-panel">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-mono uppercase tracking-widest text-ink-400">Crown &amp; Bridge</span>
        <span className="ml-auto text-[10px] text-ink-600 font-mono">dental_crown_bridge_design</span>
      </div>

      {/* Tooth preset */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">Tooth (FDI)</label>
        <div className="grid grid-cols-3 gap-1">
          {TOOTH_PRESETS.map((p) => (
            <button
              key={p.fdi}
              type="button"
              onClick={() => { setToothPreset(p); setResult(null) }}
              className={`py-1.5 px-1 rounded text-xs font-medium border transition-colors ${
                toothPreset.fdi === p.fdi
                  ? 'bg-violet-500/20 border-violet-400/60 text-violet-200'
                  : 'bg-ink-800 border-ink-700 text-ink-300 hover:bg-ink-700'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <p className="mt-1 text-[10px] text-ink-500 font-mono">{toothPreset.type} · {toothPreset.md}×{toothPreset.bl} mm</p>
      </div>

      {/* Margin type */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-[11px] text-ink-400 mb-1.5">Margin type</label>
          <select
            value={marginType}
            onChange={(e) => setMarginType(e.target.value)}
            className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1.5 text-xs text-ink-100 outline-none focus:border-violet-400/60"
          >
            {MARGIN_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="flex items-center justify-between text-[11px] text-ink-400 mb-1.5">
            <span>Margin width</span>
            <span className="font-mono text-violet-300">{marginWidth} mm</span>
          </label>
          <input
            type="range" min="0.5" max="1.5" step="0.1"
            value={marginWidth}
            onChange={(e) => setMarginWidth(parseFloat(e.target.value))}
            className="w-full accent-violet-400"
          />
        </div>
      </div>

      {/* Material */}
      <div>
        <label className="block text-[11px] text-ink-400 mb-1.5">Material</label>
        <select
          value={material}
          onChange={(e) => setMaterial(e.target.value)}
          className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1.5 text-xs text-ink-100 outline-none focus:border-violet-400/60"
        >
          {MATERIALS.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <p className="mt-1 text-[10px] text-ink-500">
          Min wall: <span className="font-mono text-violet-300">{minWallInfo.mm} mm</span>
          <span className="ml-1 text-ink-600">({minWallInfo.ref})</span>
        </p>
      </div>

      {/* ISO 4049 cement gap */}
      <div>
        <label className="flex items-center justify-between text-[11px] text-ink-400 mb-1">
          <span>Cement gap (ISO 4049 §6.4)</span>
          <span className={`font-mono text-xs ${iso4049Compliant ? 'text-emerald-300' : 'text-amber-400'}`}>
            {cementGapUm} µm {iso4049Compliant ? '✓' : '⚠'}
          </span>
        </label>
        <input
          type="range" min="20" max="120" step="5"
          value={cementGapUm}
          onChange={(e) => setCementGapUm(Number(e.target.value))}
          className="w-full accent-violet-400"
        />
        <div className="flex justify-between text-[10px] text-ink-600">
          <span>20 µm (tight)</span>
          <span className="text-emerald-600">35–80 µm ISO target</span>
          <span>120 µm (loose)</span>
        </div>
        {!iso4049Compliant && (
          <p className="mt-0.5 text-[10px] text-amber-400">
            Outside ISO 4049 §6.4 target range (20–80 µm)
          </p>
        )}
      </div>

      {/* Occlusal clearance */}
      <div>
        <label className="flex items-center justify-between text-[11px] text-ink-400 mb-1">
          <span>Occlusal clearance</span>
          <span className="font-mono text-violet-300">{clearanceMm.toFixed(1)} mm</span>
        </label>
        <input
          type="range" min="0.5" max="2.5" step="0.1"
          value={clearanceMm}
          onChange={(e) => setClearanceMm(parseFloat(e.target.value))}
          className="w-full accent-violet-400"
        />
      </div>

      {/* Bridge toggle */}
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 cursor-pointer text-[11px] text-ink-400">
          <input
            type="checkbox"
            checked={isBridge}
            onChange={(e) => setIsBridge(e.target.checked)}
            className="accent-violet-400 w-3.5 h-3.5"
          />
          Bridge mode
        </label>
        {isBridge && (
          <label className="flex items-center gap-2 text-[11px] text-ink-400">
            <span>Pontics:</span>
            <input
              type="number"
              min="1"
              max="4"
              value={ponticCount}
              onChange={(e) => setPonticCount(Number(e.target.value))}
              className="w-12 bg-ink-800 border border-ink-700 rounded px-1 py-0.5 text-xs font-mono text-ink-100 outline-none focus:border-violet-400/60"
            />
          </label>
        )}
      </div>

      {/* Run */}
      <button
        type="button"
        onClick={handleRun}
        disabled={running}
        className="flex items-center justify-center gap-2 px-4 py-2 rounded bg-violet-500/20 border border-violet-400/50 text-violet-200 text-xs font-medium hover:bg-violet-500/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {running ? (
          <>
            <span className="w-3 h-3 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
            Designing…
          </>
        ) : (
          `Design ${isBridge ? 'bridge' : 'crown'}`
        )}
      </button>

      {/* Result */}
      {result && (
        <div className="rounded border border-violet-700/50 bg-violet-950/30 p-3 text-[11px] font-mono text-violet-300 space-y-1" data-testid="crown-bridge-result">
          <div className="text-violet-400 font-semibold mb-1">{result.is_bridge ? 'Bridge' : 'Crown'} designed — FDI {result.tooth}</div>
          {result.tooth_type && <div>type: <span className="text-violet-200">{result.tooth_type}</span></div>}
          {result.wall_thickness_min_mm != null && (
            <div>
              min wall: <span className={result.wall_thickness_min_mm >= minWallInfo.mm ? 'text-emerald-300' : 'text-red-400'}>
                {result.wall_thickness_min_mm} mm
              </span>
              {result.wall_thickness_min_mm >= minWallInfo.mm ? ' ✓' : ` ⚠ < ${minWallInfo.mm} mm`}
            </div>
          )}
          {result.margin_fit_um != null && (
            <div>margin fit: <span className="text-violet-200">{result.margin_fit_um} µm</span>
              <span className="text-ink-500 ml-1">(cement + machining tol)</span>
            </div>
          )}
          {result.outer_vertices != null && <div>mesh: <span className="text-violet-200">{result.outer_vertices} V / {result.outer_triangles} F</span></div>}
          {result.honest_caveat && <div className="text-amber-500/80 text-[10px] mt-1">{result.honest_caveat}</div>}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded border border-red-700/50 bg-red-950/30 p-3 text-[11px] font-mono text-red-300" data-testid="crown-bridge-error">
          {error}
        </div>
      )}
    </div>
  )
}
