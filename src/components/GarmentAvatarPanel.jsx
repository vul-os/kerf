// GarmentAvatarPanel — display panel for garment_avatar_body_form tool results.
//
// Renders the parametric dress-form / body-form as:
//   1. A landmark table (13 ISO 8559-1 landmarks: z_cm, girth_cm, semi-axes).
//   2. A vertical SVG silhouette (front view — ellipses at each landmark height).
//   3. Mesh stats (vertex count, face count, OBJ download affordance).
//
// Props
// ─────
//   result      {Object|string|null}  — output from garment_avatar_body_form tool
//   className   {string}              — extra CSS classes on root
//
// NOTE: This is an ellipsoidal mannequin (no limbs, no pose animation).
// Full 3D cloth-on-avatar simulation is out of scope for this panel.
//
// Exported pure helpers for vitest:
//   parseAvatarResult(raw)           → { kind, data, error? }
//   formatGirth(cm)                  → "NN.N cm" string
//   landmarkDisplayOrder()           → ordered list of landmark names (crown → floor)

import { useMemo } from 'react'
import { User, Download } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/** Ordered landmark names for display (head → feet). */
export function landmarkDisplayOrder() {
  return [
    'crown', 'neck', 'shoulder', 'armscye', 'bust', 'underbust',
    'waist', 'hip', 'crotch', 'knee', 'calf', 'ankle', 'floor',
  ]
}

/**
 * Parse raw garment_avatar_body_form result.
 * Returns { kind: 'ok'|'empty'|'invalid', data, error? }
 */
export function parseAvatarResult(raw) {
  if (raw == null) return { kind: 'empty' }
  const obj = typeof raw === 'string'
    ? (() => { try { return JSON.parse(raw) } catch { return null } })()
    : raw
  if (!obj || typeof obj !== 'object') return { kind: 'invalid', error: 'Expected JSON object' }
  if (obj.error) return { kind: 'invalid', error: obj.error }
  if (!obj.landmarks || typeof obj.landmarks !== 'object')
    return { kind: 'invalid', error: 'Missing landmarks in result' }

  return { kind: 'ok', data: obj }
}

/**
 * Format a girth value in centimetres.
 */
export function formatGirth(cm) {
  if (cm == null || !Number.isFinite(cm)) return '—'
  return `${cm.toFixed(1)} cm`
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/**
 * Vertical SVG silhouette — front view of the body form.
 * Draws width-scaled ellipses at each landmark height.
 */
function BodyFormSilhouette({ landmarks, heightCm }) {
  const order  = landmarkDisplayOrder().filter((n) => n in landmarks)
  if (order.length === 0) return null

  const SVG_W  = 120
  const SVG_H  = 300
  const PAD    = 12

  // Map z_cm to SVG y (crown at top)
  const toY = (z_cm) => PAD + (1 - z_cm / heightCm) * (SVG_H - 2 * PAD)

  // Find widest point for x-scaling
  const maxA = Math.max(...order.map((n) => landmarks[n].half_width_cm ?? 0))
  const scaleX = maxA > 0 ? ((SVG_W / 2 - PAD) / maxA) : 1

  const ellipses = order.map((name) => {
    const lm = landmarks[name]
    const cy  = toY(lm.z_cm)
    const rx  = (lm.half_width_cm ?? 0) * scaleX
    const ry  = Math.max(2, (lm.half_depth_cm ?? lm.half_width_cm ?? 0) * scaleX * 0.25)
    return { name, cy, rx, ry, girth: lm.girth_cm }
  })

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      width={SVG_W}
      height={SVG_H}
      className="mx-auto block"
      aria-label="Body form silhouette"
      data-testid="avatar-silhouette"
    >
      {/* Spine line */}
      <line
        x1={SVG_W / 2}
        y1={PAD}
        x2={SVG_W / 2}
        y2={SVG_H - PAD}
        stroke="rgba(107,212,255,0.18)"
        strokeWidth="0.5"
      />

      {/* Ellipses for each landmark */}
      {ellipses.map(({ name, cy, rx, ry }) => (
        <ellipse
          key={name}
          cx={SVG_W / 2}
          cy={cy}
          rx={Math.max(rx, 1)}
          ry={Math.max(ry, 1)}
          fill="none"
          stroke="rgba(107,212,255,0.55)"
          strokeWidth="0.8"
        />
      ))}

      {/* Landmark dots */}
      {ellipses.filter((e) => ['bust', 'waist', 'hip'].includes(e.name)).map(({ name, cy }) => (
        <circle
          key={name + '-dot'}
          cx={SVG_W / 2}
          cy={cy}
          r={2}
          fill="rgba(107,212,255,0.7)"
        />
      ))}
    </svg>
  )
}

function LandmarkTable({ landmarks }) {
  const order = landmarkDisplayOrder().filter((n) => n in landmarks)
  const highlighted = new Set(['bust', 'waist', 'hip'])
  return (
    <div className="overflow-x-auto" data-testid="avatar-landmark-table">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-ink-800">
            <th className="py-1.5 pr-3 text-left font-mono text-[10px] uppercase tracking-wider text-ink-500">
              Landmark
            </th>
            <th className="py-1.5 pr-3 text-right font-mono text-[10px] uppercase tracking-wider text-ink-500">
              Height (cm)
            </th>
            <th className="py-1.5 text-right font-mono text-[10px] uppercase tracking-wider text-ink-500">
              Girth (cm)
            </th>
          </tr>
        </thead>
        <tbody>
          {order.map((name) => {
            const lm = landmarks[name]
            return (
              <tr
                key={name}
                className={`border-b border-ink-800/40 ${highlighted.has(name) ? 'bg-cyan-edge/5' : ''}`}
              >
                <td className={`py-1 pr-3 font-mono capitalize ${highlighted.has(name) ? 'text-cyan-edge' : 'text-ink-300'}`}>
                  {name}
                </td>
                <td className="py-1 pr-3 text-right font-mono text-ink-400">
                  {lm.z_cm?.toFixed(1) ?? '—'}
                </td>
                <td className="py-1 text-right font-mono text-ink-200 font-medium">
                  {formatGirth(lm.girth_cm)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ObjDownload({ obj, fileName }) {
  if (!obj) return null
  const href = 'data:text/plain;charset=utf-8,' + encodeURIComponent(obj)
  return (
    <a
      href={href}
      download={fileName || 'body_form.obj'}
      className="inline-flex items-center gap-1.5 rounded-md border border-ink-700 bg-ink-900/60 px-3 py-1.5 text-xs font-mono text-ink-300 hover:border-ink-600 hover:text-ink-100 transition-colors"
      data-testid="avatar-obj-download"
    >
      <Download size={12} />
      body_form.obj
    </a>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * GarmentAvatarPanel — renders a parametric dress-form / body-form result.
 *
 * @param {Object} props
 * @param {Object|string|null} props.result  — garment_avatar_body_form output
 * @param {string} [props.className]
 */
export default function GarmentAvatarPanel({ result = null, content, className = '' }) {
  // content prop (from panelRegistry) is a JSON string; parse and use as result
  const effectiveResult = useMemo(() => {
    if (content != null) {
      try { return JSON.parse(content) } catch { return result }
    }
    return result
  }, [result, content])
  const parsed = useMemo(() => parseAvatarResult(effectiveResult), [effectiveResult])

  if (parsed.kind === 'empty') {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 py-10 text-ink-500 ${className}`}
        data-testid="avatar-panel-empty"
      >
        <User size={28} className="opacity-40" />
        <p className="text-sm">No body form yet.</p>
        <p className="text-xs opacity-60">
          Ask Kerf to generate a parametric dress form or body form.
        </p>
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div
        className={`rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400 ${className}`}
        data-testid="avatar-panel-error"
      >
        Error: {parsed.error}
      </div>
    )
  }

  const { data } = parsed
  const { landmarks, height_cm, bust_cm, waist_cm, hip_cm, sex,
          n_vertices, n_faces, obj, method } = data

  return (
    <div className={`flex flex-col gap-3 ${className}`} data-testid="garment-avatar-panel">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="grid place-items-center w-5 h-5 rounded bg-cyan-edge/10 border border-cyan-edge/20 text-cyan-edge">
          <User size={11} />
        </span>
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink-400">
          Parametric body form
        </span>
        <span
          className="ml-auto rounded-md border border-ink-700 bg-ink-900/60 px-2 py-0.5 font-mono text-[11px] text-ink-300 capitalize"
          data-testid="avatar-sex-label"
        >
          {sex ?? 'female'}
        </span>
      </div>

      {/* Key measurements */}
      <div className="grid grid-cols-4 gap-1.5 text-xs" data-testid="avatar-key-measurements">
        {[
          ['Height', height_cm != null ? `${height_cm.toFixed(0)} cm` : '—'],
          ['Bust',   formatGirth(bust_cm)],
          ['Waist',  formatGirth(waist_cm)],
          ['Hip',    formatGirth(hip_cm)],
        ].map(([label, value]) => (
          <div key={label} className="rounded border border-ink-800 bg-ink-950/50 px-2 py-1.5 text-center">
            <p className="text-[9px] font-mono uppercase tracking-wider text-ink-500">{label}</p>
            <p className="font-mono text-ink-200 mt-0.5">{value}</p>
          </div>
        ))}
      </div>

      {/* Body silhouette + landmark table */}
      <div className="grid grid-cols-[auto_1fr] gap-3 items-start">
        <BodyFormSilhouette landmarks={landmarks} heightCm={height_cm ?? 168} />
        <LandmarkTable landmarks={landmarks} />
      </div>

      {/* Mesh stats */}
      <div className="flex flex-wrap items-center gap-2 text-[10px] font-mono text-ink-500">
        <span>{n_vertices?.toLocaleString()} vertices</span>
        <span className="text-ink-700">·</span>
        <span>{n_faces?.toLocaleString()} triangles</span>
        {method && (
          <>
            <span className="text-ink-700">·</span>
            <span className="truncate max-w-[220px]" title={method}>{method.split('+')[0].trim()}</span>
          </>
        )}
      </div>

      {/* Disclaimer */}
      <p className="text-[10px] text-ink-600 italic leading-relaxed">
        Simplified torso/leg ellipsoidal mannequin (CAESAR 2002). No arms, head geometry, or
        pose animation. Export the OBJ to use with a mass-spring drape solver for cloth-on-avatar
        fit preview.
      </p>

      {/* OBJ download */}
      {obj && (
        <ObjDownload
          obj={obj}
          fileName={`body_form_${sex ?? 'female'}_${height_cm ?? 168}cm.obj`}
        />
      )}
    </div>
  )
}
