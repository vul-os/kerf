// GarmentAutoArrangePanel — display panel for garment_auto_arrange tool results.
//
// Shows:
//   1. Avatar silhouette (schematic body outline in SVG) with colour-coded
//      panel footprints positioned around it by zone.
//   2. Per-panel cards: zone label, translation, rotation, penetration status,
//      fit-tension heatmap (SVG grid), drape converged flag.
//   3. Seam proximity status badges.
//   4. "Drape" action button that calls garment_auto_arrange tool.
//
// Props
// ─────
//   result      {Object|string|null}  — output from garment_auto_arrange tool
//   onDrape     {Function|null}       — callback for "Drape" button click
//   className   {string}              — extra CSS classes on root
//
// Exported pure helpers for vitest:
//   parseArrangeResult(raw)        → { kind, data, error? }
//   panelZoneColor(zone)           → CSS colour string
//   tensionColorAA(t, scale)       → CSS colour (red=tight, blue=bunched)
//   formatVec3(arr)                → "x, y, z cm" string

import { useMemo } from 'react'
import { Shirt, CheckCircle, AlertTriangle, Play } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw garment_auto_arrange result.
 * Returns { kind: 'ok'|'empty'|'invalid', data, error? }
 */
export function parseArrangeResult(raw) {
  if (raw == null) return { kind: 'empty' }
  const obj =
    typeof raw === 'string'
      ? (() => { try { return JSON.parse(raw) } catch { return null } })()
      : raw
  if (!obj || typeof obj !== 'object') return { kind: 'invalid', error: 'Expected JSON object' }
  if (obj.error) return { kind: 'invalid', error: obj.error }
  if (obj.ok === false) return { kind: 'invalid', error: obj.error || 'Tool returned ok=false' }
  if (!Array.isArray(obj.panels))
    return { kind: 'invalid', error: 'Missing panels array in result' }

  return { kind: 'ok', data: obj }
}

/**
 * Return a distinct CSS colour for each body zone.
 */
export function panelZoneColor(zone) {
  const map = {
    front_torso:     '#3b82f6',  // blue
    back_torso:      '#8b5cf6',  // purple
    left_sleeve:     '#10b981',  // green
    right_sleeve:    '#f59e0b',  // amber
    skirt_front:     '#ec4899',  // pink
    skirt_back:      '#ef4444',  // red
    left_leg_front:  '#06b6d4',  // cyan
    left_leg_back:   '#0ea5e9',  // sky
    right_leg_front: '#f97316',  // orange
    right_leg_back:  '#84cc16',  // lime
  }
  return map[zone] ?? '#6b7280'
}

/**
 * Map a tension value to an RGB hex colour string.
 *   > 0 (stretched / tight): red
 *   = 0 (relaxed):           white/cream
 *   < 0 (bunched):           blue
 */
export function tensionColorAA(t, scale = 0.05) {
  if (!Number.isFinite(t) || scale <= 0) return '#888888'
  const clamped = Math.max(-1, Math.min(1, t / scale))
  if (clamped >= 0) {
    const r = Math.round(248 - clamped * (248 - 239))
    const g = Math.round(248 - clamped * (248 - 68))
    const b = Math.round(248 - clamped * (248 - 68))
    return `rgb(${r},${g},${b})`
  } else {
    const ratio = -clamped
    const r = Math.round(248 - ratio * (248 - 59))
    const g = Math.round(248 - ratio * (248 - 130))
    const b = Math.round(248 - ratio * (248 - 246))
    return `rgb(${r},${g},${b})`
  }
}

/**
 * Format a [x, y, z] cm array as a readable string.
 */
export function formatVec3(arr) {
  if (!Array.isArray(arr) || arr.length < 3) return '—'
  return arr.map((v) => (Number.isFinite(v) ? v.toFixed(1) : '?')).join(', ') + ' cm'
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Zone badge with colour dot */
function ZoneBadge({ zone }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono"
      style={{ background: panelZoneColor(zone) + '22', color: panelZoneColor(zone) }}>
      <span className="inline-block w-2 h-2 rounded-full"
        style={{ background: panelZoneColor(zone) }} />
      {zone}
    </span>
  )
}

/** Fit-tension heatmap SVG grid for one panel */
function TensionGrid({ tension, rows, cols }) {
  if (!Array.isArray(tension) || tension.length === 0) return null
  const CELL = 14
  const W = cols * CELL
  const H = rows * CELL
  const scale = Math.max(0.001, Math.max(...tension.map(Math.abs)))

  return (
    <svg width={W} height={H} className="block rounded" aria-label="Fit tension heatmap">
      {tension.map((t, i) => {
        const r = Math.floor(i / cols)
        const c = i % cols
        return (
          <rect
            key={i}
            x={c * CELL}
            y={r * CELL}
            width={CELL}
            height={CELL}
            fill={tensionColorAA(t, scale)}
            stroke="#00000011"
            strokeWidth={0.5}
          />
        )
      })}
    </svg>
  )
}

/** Avatar schematic SVG (front-view body silhouette, top=crown, bottom=floor) */
function AvatarSchematic({ panels, avatarHeightCm = 168 }) {
  const SVG_W = 200
  const SVG_H = 320
  const PAD = 16

  // Schematic body shape as polyline coordinates (normalised 0-1 from bottom)
  // in SVG space: y=0 at top, y=SVG_H at bottom
  const toY = (frac) => PAD + (1 - frac) * (SVG_H - 2 * PAD)
  const toX = (frac) => PAD + frac * (SVG_W - 2 * PAD)

  // Simple body silhouette
  const cx = SVG_W / 2
  const silhouette = [
    { y: toY(1.00), x1: cx - 10, x2: cx + 10 },  // crown
    { y: toY(0.86), x1: cx - 13, x2: cx + 13 },  // neck
    { y: toY(0.82), x1: cx - 22, x2: cx + 22 },  // shoulder
    { y: toY(0.73), x1: cx - 20, x2: cx + 20 },  // bust
    { y: toY(0.63), x1: cx - 16, x2: cx + 16 },  // waist
    { y: toY(0.54), x1: cx - 20, x2: cx + 20 },  // hip
    { y: toY(0.27), x1: cx - 10, x2: cx + 10 },  // knee
    { y: toY(0.00), x1: cx - 9,  x2: cx + 9  },  // floor
  ]

  // Panel zone -> approximate SVG position (y fraction, x offset from centre)
  const zonePos = {
    front_torso:     { yFrac: 0.68, dx: 0,    side: 'front' },
    back_torso:      { yFrac: 0.68, dx: 0,    side: 'back'  },
    left_sleeve:     { yFrac: 0.75, dx: -40,  side: 'left'  },
    right_sleeve:    { yFrac: 0.75, dx: +40,  side: 'right' },
    skirt_front:     { yFrac: 0.48, dx: 0,    side: 'front' },
    skirt_back:      { yFrac: 0.48, dx: 0,    side: 'back'  },
    left_leg_front:  { yFrac: 0.20, dx: -14,  side: 'left'  },
    left_leg_back:   { yFrac: 0.20, dx: -14,  side: 'back'  },
    right_leg_front: { yFrac: 0.20, dx: +14,  side: 'right' },
    right_leg_back:  { yFrac: 0.20, dx: +14,  side: 'back'  },
  }

  // Build left outline path
  const leftPath = silhouette.map((s, i) =>
    (i === 0 ? `M${s.x1},${s.y}` : `L${s.x1},${s.y}`)
  ).join(' ')
  const rightPath = [...silhouette].reverse().map((s, i) =>
    (i === 0 ? `M${s.x2},${s.y}` : `L${s.x2},${s.y}`)
  ).join(' ')

  return (
    <svg width={SVG_W} height={SVG_H} className="block mx-auto" aria-label="Avatar schematic">
      {/* Body fill */}
      <path
        d={leftPath + ' ' + rightPath.replace('M', 'L') + ' Z'}
        fill="#e5e7eb"
        stroke="#9ca3af"
        strokeWidth={1}
      />

      {/* Panel zone markers */}
      {(panels ?? []).map((p) => {
        const pos = zonePos[p.zone]
        if (!pos) return null
        const py = toY(pos.yFrac)
        const px = cx + pos.dx
        const isBack = pos.side === 'back'
        const color = panelZoneColor(p.zone)
        return (
          <g key={p.label}>
            <rect
              x={px - 10}
              y={py - 10}
              width={20}
              height={20}
              fill={color + (isBack ? '55' : 'aa')}
              stroke={color}
              strokeWidth={1.5}
              rx={2}
              opacity={isBack ? 0.5 : 0.9}
            />
            <title>{p.label} ({p.zone})</title>
          </g>
        )
      })}
    </svg>
  )
}

/** Single panel detail card */
function PanelCard({ panel, seamStatuses, seams }) {
  const tension = panel.fit_tension ?? []
  const rows = panel.rows ?? 6
  const cols = panel.cols ?? 6

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 bg-white dark:bg-gray-800 space-y-2">
      <div className="flex items-start gap-2">
        <ZoneBadge zone={panel.zone} />
        <span className="font-medium text-sm text-gray-800 dark:text-gray-200 truncate">
          {panel.label}
        </span>
        {panel.no_deep_penetration
          ? <CheckCircle className="w-4 h-4 text-green-500 ml-auto flex-shrink-0" />
          : <AlertTriangle className="w-4 h-4 text-amber-500 ml-auto flex-shrink-0" />}
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-gray-600 dark:text-gray-400">
        <span className="text-gray-400">Translation</span>
        <span className="font-mono">{formatVec3(panel.translation_cm)}</span>
        <span className="text-gray-400">Rotation (Rz)</span>
        <span className="font-mono">{panel.rotation_euler_deg?.[2]?.toFixed(0) ?? '—'}°</span>
        <span className="text-gray-400">Penetration</span>
        <span className="font-mono">{typeof panel.max_penetration_cm === 'number'
          ? panel.max_penetration_cm.toFixed(3) + ' cm' : '—'}</span>
        <span className="text-gray-400">Converged</span>
        <span>{panel.drape_converged ? '✓ yes' : `${panel.drape_steps_taken} steps`}</span>
        <span className="text-gray-400">Tension mean</span>
        <span className="font-mono">{typeof panel.fit_tension_mean === 'number'
          ? (panel.fit_tension_mean > 0 ? '+' : '') + panel.fit_tension_mean.toFixed(4) : '—'}</span>
      </div>

      {/* Tension heatmap */}
      {tension.length > 0 && (
        <div>
          <div className="text-xs text-gray-400 mb-1">Fit tension (red=tight, blue=bunched)</div>
          <TensionGrid tension={tension} rows={rows} cols={cols} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty / error states
// ---------------------------------------------------------------------------

function EmptyState({ onDrape }) {
  return (
    <div className="flex flex-col items-center gap-4 py-8 text-center">
      <Shirt className="w-12 h-12 text-blue-400 opacity-60" />
      <div>
        <p className="font-medium text-gray-700 dark:text-gray-300">
          Garment Auto-Arrangement
        </p>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 max-w-xs">
          Automatically positions 2D garment panels around a parametric avatar
          and settles them with mass-spring cloth simulation.
        </p>
      </div>
      {onDrape && (
        <button
          onClick={onDrape}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700
            text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Play className="w-4 h-4" />
          Arrange &amp; Drape
        </button>
      )}
    </div>
  )
}

function ErrorState({ error, onDrape }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <AlertTriangle className="w-10 h-10 text-amber-400" />
      <p className="text-sm text-gray-600 dark:text-gray-400 max-w-xs break-words">{error}</p>
      {onDrape && (
        <button
          onClick={onDrape}
          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm border border-gray-300
            dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
        >
          <Play className="w-3.5 h-3.5" />
          Retry
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel component
// ---------------------------------------------------------------------------

/**
 * GarmentAutoArrangePanel
 *
 * Props:
 *   result     {Object|string|null}  tool output from garment_auto_arrange
 *   onDrape    {Function|null}       called when user clicks "Drape"
 *   className  {string}
 */
export default function GarmentAutoArrangePanel({ result, onDrape, className = '' }) {
  const parsed = useMemo(() => parseArrangeResult(result), [result])

  if (parsed.kind === 'empty') {
    return (
      <div className={`p-4 ${className}`}>
        <EmptyState onDrape={onDrape} />
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div className={`p-4 ${className}`}>
        <ErrorState error={parsed.error} onDrape={onDrape} />
      </div>
    )
  }

  const data = parsed.data
  const panels = data.panels ?? []
  const seams  = data.seam_proximity_met ?? []
  const avatar = data.avatar ?? {}

  const allNoDeepPen = panels.every((p) => p.no_deep_penetration)
  const allConverged = panels.every((p) => p.drape_converged)

  return (
    <div className={`p-4 space-y-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <Shirt className="w-5 h-5 text-blue-500" />
        <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
          Garment Auto-Arrangement
        </h2>
        {onDrape && (
          <button
            onClick={onDrape}
            className="ml-auto inline-flex items-center gap-1 px-3 py-1 bg-blue-600
              hover:bg-blue-700 text-white text-xs font-medium rounded-md transition-colors"
          >
            <Play className="w-3 h-3" />
            Drape
          </button>
        )}
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-2">
          <div className="text-2xl font-bold text-blue-600">{panels.length}</div>
          <div className="text-xs text-gray-500">panels</div>
        </div>
        <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-2">
          <div className={`text-2xl font-bold ${allNoDeepPen ? 'text-green-500' : 'text-amber-500'}`}>
            {allNoDeepPen ? '✓' : '⚠'}
          </div>
          <div className="text-xs text-gray-500">no penetration</div>
        </div>
        <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-2">
          <div className={`text-2xl font-bold ${allConverged ? 'text-green-500' : 'text-gray-400'}`}>
            {allConverged ? '✓' : '~'}
          </div>
          <div className="text-xs text-gray-500">converged</div>
        </div>
      </div>

      {/* Avatar schematic + avatar stats */}
      <div className="flex gap-4 items-start">
        <AvatarSchematic panels={panels} avatarHeightCm={avatar.height_cm} />
        <div className="flex-1 space-y-1 text-xs text-gray-600 dark:text-gray-400">
          <div className="font-medium text-gray-700 dark:text-gray-300 mb-1">Avatar</div>
          {avatar.height_cm && <div>Height: {avatar.height_cm} cm</div>}
          {avatar.bust_cm   && <div>Bust: {avatar.bust_cm} cm</div>}
          {avatar.waist_cm  && <div>Waist: {avatar.waist_cm} cm</div>}
          {avatar.hip_cm    && <div>Hip: {avatar.hip_cm} cm</div>}
          {avatar.n_verts   && <div>{avatar.n_verts} verts / {avatar.n_faces} faces</div>}
        </div>
      </div>

      {/* Seam proximity badges */}
      {seams.length > 0 && (
        <div>
          <div className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
            Seam proximity
          </div>
          <div className="flex flex-wrap gap-1">
            {seams.map((met, i) => (
              <span
                key={i}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium
                  ${met
                    ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                    : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
                  }`}
              >
                {met ? '✓' : '~'} seam {i + 1}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Per-panel cards */}
      <div>
        <div className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
          Panels ({panels.length})
        </div>
        <div className="space-y-2">
          {panels.map((panel) => (
            <PanelCard
              key={panel.label}
              panel={panel}
              seamStatuses={seams}
            />
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="text-xs text-gray-400 dark:text-gray-500 space-y-0.5">
        <div>Fit tension: red = fabric stretched (tight), blue = compressed (bunched), white = relaxed.</div>
        <div>Panel positions in cm. Drape: Provot (1995) mass-spring + Bridson (2003) collision.</div>
      </div>
    </div>
  )
}
