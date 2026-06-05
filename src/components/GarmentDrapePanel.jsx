// GarmentDrapePanel — display panel for garment_drape_on_avatar tool results.
//
// Renders:
//   1. Simulation metadata (converged, steps, penetration status).
//   2. Fit-tension heatmap as an SVG grid: each cell is the cloth panel
//      particle, coloured by per-vertex tension (red=tight, blue=bunched,
//      white=relaxed).
//   3. Body fit summary: mean/max/min tension with interpretation labels.
//   4. Avatar measurements used (bust/waist/hip, sex, height).
//
// Props
// ─────
//   result      {Object|string|null}  — output from garment_drape_on_avatar tool
//   className   {string}              — extra CSS classes on root
//
// Exported pure helpers for vitest:
//   parseDrapeResult(raw)          → { kind, data, error? }
//   tensionColor(t, scale)         → CSS hex colour string
//   formatTension(t)               → "+0.012" string
//   interpretTension(mean)         → 'tight'|'good'|'loose' label

import { useMemo } from 'react'
import { Shirt, CheckCircle, AlertTriangle } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw garment_drape_on_avatar result.
 * Returns { kind: 'ok'|'empty'|'invalid', data, error? }
 */
export function parseDrapeResult(raw) {
  if (raw == null) return { kind: 'empty' }
  const obj =
    typeof raw === 'string'
      ? (() => {
          try { return JSON.parse(raw) } catch { return null }
        })()
      : raw
  if (!obj || typeof obj !== 'object') return { kind: 'invalid', error: 'Expected JSON object' }
  if (obj.error) return { kind: 'invalid', error: obj.error }
  if (obj.ok === false) return { kind: 'invalid', error: obj.error || 'Tool returned ok=false' }
  if (!Array.isArray(obj.fit_tension))
    return { kind: 'invalid', error: 'Missing fit_tension array in result' }
  if (!Array.isArray(obj.vertices_3d))
    return { kind: 'invalid', error: 'Missing vertices_3d array in result' }

  return { kind: 'ok', data: obj }
}

/**
 * Map a tension value to an RGB hex colour.
 *   > 0  (stretched / tight): red
 *   ≈ 0  (relaxed):           white/cream
 *   < 0  (bunched):           blue
 *
 * @param {number} t       tension value (dimensionless spring stretch ratio)
 * @param {number} scale   full-scale value (absolute tension at which pure red/blue appears)
 */
export function tensionColor(t, scale = 0.05) {
  if (!Number.isFinite(t) || scale <= 0) return '#888888'
  const clamped = Math.max(-1, Math.min(1, t / scale))
  if (clamped >= 0) {
    // 0 → white (#f8f8f8), 1 → red (#ef4444)
    const r = Math.round(248 - clamped * (248 - 239))
    const g = Math.round(248 - clamped * (248 - 68))
    const b = Math.round(248 - clamped * (248 - 68))
    return `rgb(${r},${g},${b})`
  } else {
    // 0 → white (#f8f8f8), -1 → blue (#3b82f6)
    const ratio = -clamped
    const r = Math.round(248 - ratio * (248 - 59))
    const g = Math.round(248 - ratio * (248 - 130))
    const b = Math.round(248 - ratio * (248 - 246))
    return `rgb(${r},${g},${b})`
  }
}

/**
 * Format a tension value as a signed string with 3 decimal places.
 */
export function formatTension(t) {
  if (!Number.isFinite(t)) return '—'
  const sign = t >= 0 ? '+' : ''
  return `${sign}${t.toFixed(3)}`
}

/**
 * Interpret mean tension for garment fit.
 * Returns 'tight' | 'good' | 'loose'
 */
export function interpretTension(mean) {
  if (!Number.isFinite(mean)) return 'unknown'
  if (mean > 0.02) return 'tight'
  if (mean < -0.01) return 'loose'
  return 'good'
}

// ---------------------------------------------------------------------------
// Fit-tension heatmap SVG
// ---------------------------------------------------------------------------

/**
 * Render a 2D grid heatmap of per-vertex fit tension.
 * The cloth panel is a rows×cols grid; each cell is coloured by tension.
 */
function FitTensionHeatmap({ fitTension, rows, cols, scale }) {
  if (!fitTension || fitTension.length === 0) return null

  const CELL = 16
  const PAD  = 2
  const W = cols * CELL + 2 * PAD
  const H = rows * CELL + 2 * PAD

  const cells = []
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const idx = r * cols + c
      const t = idx < fitTension.length ? fitTension[idx] : 0
      const fill = tensionColor(t, scale)
      cells.push(
        <rect
          key={`${r}-${c}`}
          x={PAD + c * CELL}
          y={PAD + r * CELL}
          width={CELL - 1}
          height={CELL - 1}
          fill={fill}
          rx={1}
          data-testid={`heatmap-cell-${r}-${c}`}
        />,
      )
    }
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      className="block"
      aria-label="Fit tension heatmap"
      data-testid="fit-tension-heatmap"
    >
      {/* Background */}
      <rect x={0} y={0} width={W} height={H} fill="rgba(15,15,18,0.7)" rx={3} />
      {cells}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Colour-scale legend
// ---------------------------------------------------------------------------

function TensionLegend({ scale }) {
  const stops = 20
  const W = 120
  const H = 12

  const rects = []
  for (let i = 0; i < stops; i++) {
    const t = scale * (2 * i / (stops - 1) - 1)  // -scale → +scale
    const fill = tensionColor(t, scale)
    rects.push(
      <rect
        key={i}
        x={(i / stops) * W}
        y={0}
        width={W / stops + 0.5}
        height={H}
        fill={fill}
      />,
    )
  }

  return (
    <div className="flex items-center gap-2 text-[10px] font-mono text-ink-500">
      <span>loose</span>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width={W}
        height={H}
        className="rounded-sm overflow-hidden"
        data-testid="tension-legend"
      >
        {rects}
      </svg>
      <span>tight</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * GarmentDrapePanel — renders garment-on-avatar drape simulation results.
 *
 * @param {Object} props
 * @param {Object|string|null} props.result  — garment_drape_on_avatar output
 * @param {string} [props.className]
 */
export default function GarmentDrapePanel({ result = null, className = '' }) {
  const parsed = useMemo(() => parseDrapeResult(result), [result])

  if (parsed.kind === 'empty') {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 py-10 text-ink-500 ${className}`}
        data-testid="drape-panel-empty"
      >
        <Shirt size={28} className="opacity-40" />
        <p className="text-sm">No drape simulation yet.</p>
        <p className="text-xs opacity-60">
          Ask Kerf to drape a garment panel on an avatar body form.
        </p>
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div
        className={`rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400 ${className}`}
        data-testid="drape-panel-error"
      >
        Error: {parsed.error}
      </div>
    )
  }

  const { data } = parsed
  const {
    target_region,
    panel_rows,
    panel_cols,
    converged,
    steps_taken,
    max_penetration_cm,
    no_deep_penetration,
    symmetry_error_cm,
    fit_tension,
    fit_tension_mean,
    fit_tension_max,
    fit_tension_min,
    fit_tension_rms,
    avatar,
    note,
  } = data

  const interpretation = interpretTension(fit_tension_mean)
  // Auto-scale the heatmap to ±2× the RMS tension (shows variation well)
  const heatmapScale = Math.max(0.005, (data.fit_tension_rms ?? 0.02) * 2.5)

  const statusIcon = no_deep_penetration ? (
    <CheckCircle size={12} className="text-green-400" />
  ) : (
    <AlertTriangle size={12} className="text-yellow-400" />
  )

  const interpretColors = {
    tight:   'text-red-400',
    good:    'text-green-400',
    loose:   'text-blue-400',
    unknown: 'text-ink-500',
  }

  return (
    <div className={`flex flex-col gap-3 ${className}`} data-testid="garment-drape-panel">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="grid place-items-center w-5 h-5 rounded bg-violet-500/10 border border-violet-500/20 text-violet-400">
          <Shirt size={11} />
        </span>
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink-400">
          Garment drape on avatar
        </span>
        <span
          className="ml-auto rounded-md border border-ink-700 bg-ink-900/60 px-2 py-0.5 font-mono text-[11px] text-ink-300 capitalize"
          data-testid="drape-region-label"
        >
          {target_region ?? 'torso'}
        </span>
      </div>

      {/* Simulation status bar */}
      <div className="flex flex-wrap items-center gap-2 text-[10px] font-mono" data-testid="drape-status-bar">
        <span className="flex items-center gap-1">
          {statusIcon}
          <span className={no_deep_penetration ? 'text-green-400' : 'text-yellow-400'}>
            {no_deep_penetration ? 'no deep penetration' : 'penetration detected'}
          </span>
        </span>
        <span className="text-ink-700">·</span>
        <span className="text-ink-500">
          {converged ? 'converged' : 'max steps'} in {steps_taken?.toLocaleString()} steps
        </span>
        <span className="text-ink-700">·</span>
        <span className="text-ink-500">
          {panel_rows}×{panel_cols} grid
        </span>
      </div>

      {/* Avatar measurement summary */}
      {avatar && (
        <div className="grid grid-cols-4 gap-1.5 text-xs" data-testid="drape-avatar-summary">
          {[
            ['Height', avatar.height_cm != null ? `${Math.round(avatar.height_cm)} cm` : '—'],
            ['Bust',   avatar.bust_cm  != null ? `${avatar.bust_cm.toFixed(0)} cm` : '—'],
            ['Waist',  avatar.waist_cm != null ? `${avatar.waist_cm.toFixed(0)} cm` : '—'],
            ['Hip',    avatar.hip_cm   != null ? `${avatar.hip_cm.toFixed(0)} cm`  : '—'],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-ink-800 bg-ink-950/50 px-2 py-1.5 text-center">
              <p className="text-[9px] font-mono uppercase tracking-wider text-ink-500">{label}</p>
              <p className="font-mono text-ink-200 mt-0.5 text-xs">{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Heatmap + fit quality summary */}
      <div className="grid grid-cols-[auto_1fr] gap-3 items-start" data-testid="drape-heatmap-section">
        {/* Left: heatmap */}
        <div className="flex flex-col gap-1.5 items-center">
          <p className="text-[9px] font-mono uppercase tracking-wider text-ink-500 self-start">
            Fit tension
          </p>
          <FitTensionHeatmap
            fitTension={fit_tension}
            rows={panel_rows ?? 10}
            cols={panel_cols ?? 10}
            scale={heatmapScale}
          />
          <TensionLegend scale={heatmapScale} />
        </div>

        {/* Right: numeric summary */}
        <div className="flex flex-col gap-2">
          <p className="text-[9px] font-mono uppercase tracking-wider text-ink-500">
            Fit quality
          </p>

          {/* Fit interpretation */}
          <div
            className={`text-sm font-semibold capitalize ${interpretColors[interpretation]}`}
            data-testid="drape-fit-interpretation"
          >
            {interpretation}
          </div>

          {/* Tension stats table */}
          <table className="text-[10px] font-mono w-full" data-testid="drape-tension-stats">
            <tbody>
              {[
                ['Mean', fit_tension_mean],
                ['Max',  fit_tension_max],
                ['Min',  fit_tension_min],
                ['RMS',  fit_tension_rms],
              ].map(([label, val]) => (
                <tr key={label} className="border-b border-ink-800/30">
                  <td className="py-0.5 pr-3 text-ink-500">{label}</td>
                  <td className="py-0.5 text-right text-ink-200">{formatTension(val)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Penetration detail */}
          <div className="text-[10px] font-mono text-ink-500 mt-1">
            <span>Max penetration: </span>
            <span className={no_deep_penetration ? 'text-ink-300' : 'text-yellow-400'}>
              {max_penetration_cm != null ? `${max_penetration_cm.toFixed(2)} cm` : '—'}
            </span>
          </div>

          {/* Symmetry */}
          {symmetry_error_cm != null && symmetry_error_cm > 0 && (
            <div className="text-[10px] font-mono text-ink-500">
              <span>Symmetry error: </span>
              <span className="text-ink-300">{symmetry_error_cm.toFixed(2)} cm</span>
            </div>
          )}
        </div>
      </div>

      {/* Physics note */}
      <p className="text-[10px] text-ink-600 italic leading-relaxed" data-testid="drape-physics-note">
        {note ?? (
          'Mass-spring cloth solver (Provot 1995) + mesh-triangle collision response (Bridson 2003). ' +
          'Tension > 0: stretched (tight); tension < 0: compressed (bunched). ' +
          'GPU real-time simulation and rigged-character drape not yet supported.'
        )}
      </p>
    </div>
  )
}
