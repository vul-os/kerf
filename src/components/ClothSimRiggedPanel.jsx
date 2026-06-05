// ClothSimRiggedPanel — display panel for cloth_sim_on_rigged_character results.
//
// Renders:
//   1. Animation controls: frame scrubber over the simulated frame sequence.
//   2. Posed character view: per-frame body mesh silhouette (XZ orthographic).
//   3. Draped garment view: per-frame cloth mesh heatmap (fit-tension coloured).
//   4. Per-frame metrics: energy (J), max penetration (cm), fit quality.
//   5. Simulation metadata: n_frames, cloth grid, physics notes.
//
// Props
// ─────
//   result      {Object|string|null}  — output from cloth_sim_on_rigged_character
//   className   {string}              — extra CSS classes
//
// Exported pure helpers for testing:
//   parseRiggedResult(raw)      → { kind, data, error? }
//   interpolateBodyFrame(frames, idx)  → frame data at idx
//   frameTensionStats(frame)    → { mean, max, min }

import { useState, useMemo, useCallback } from 'react'
import { Shirt, User, ChevronLeft, ChevronRight, Play, Square, AlertTriangle, CheckCircle } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for testing)
// ---------------------------------------------------------------------------

/**
 * Parse raw cloth_sim_on_rigged_character result.
 * Returns { kind: 'ok'|'empty'|'invalid', data, error? }
 */
export function parseRiggedResult(raw) {
  if (raw == null) return { kind: 'empty' }
  const obj =
    typeof raw === 'string'
      ? (() => { try { return JSON.parse(raw) } catch { return null } })()
      : raw
  if (!obj || typeof obj !== 'object') return { kind: 'invalid', error: 'Expected JSON object' }
  if (obj.error) return { kind: 'invalid', error: obj.error }
  if (obj.ok === false) return { kind: 'invalid', error: obj.error || 'Tool returned ok=false' }
  if (!Array.isArray(obj.frames) || obj.frames.length === 0)
    return { kind: 'invalid', error: 'Missing frames array in result' }
  return { kind: 'ok', data: obj }
}

/**
 * Get the frame data at index idx (clamped).
 */
export function interpolateBodyFrame(frames, idx) {
  if (!frames || frames.length === 0) return null
  const i = Math.max(0, Math.min(idx, frames.length - 1))
  return frames[i]
}

/**
 * Compute tension statistics for a single frame.
 */
export function frameTensionStats(frame) {
  if (!frame || !Array.isArray(frame.fit_tension) || frame.fit_tension.length === 0)
    return { mean: 0, max: 0, min: 0 }
  const t = frame.fit_tension
  const sum = t.reduce((a, b) => a + b, 0)
  return {
    mean: sum / t.length,
    max: Math.max(...t),
    min: Math.min(...t),
  }
}

// ---------------------------------------------------------------------------
// Tension colour (same palette as GarmentDrapePanel)
// ---------------------------------------------------------------------------

function tensionColor(t, scale = 0.05) {
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

// ---------------------------------------------------------------------------
// Cloth heatmap: renders the cloth panel grid coloured by per-vertex tension
// ---------------------------------------------------------------------------

function ClothHeatmap({ fitTension, rows, cols, scale }) {
  if (!fitTension || fitTension.length === 0) return null
  const CELL = 14
  const PAD = 2
  const W = cols * CELL + 2 * PAD
  const H = rows * CELL + 2 * PAD

  const cells = []
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const idx = r * cols + c
      const t = idx < fitTension.length ? fitTension[idx] : 0
      cells.push(
        <rect
          key={`${r}-${c}`}
          x={PAD + c * CELL}
          y={PAD + r * CELL}
          width={CELL - 1}
          height={CELL - 1}
          fill={tensionColor(t, scale)}
          rx={1}
          data-testid={`cloth-cell-${r}-${c}`}
        />
      )
    }
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      className="block"
      aria-label="Cloth fit tension heatmap"
      data-testid="cloth-heatmap"
    >
      <rect x={0} y={0} width={W} height={H} fill="rgba(10,10,14,0.8)" rx={3} />
      {cells}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Body silhouette: XZ orthographic projection of body mesh as dots
// ---------------------------------------------------------------------------

function BodySilhouette({ bodyVerts, clothVerts }) {
  // Very simple orthographic projection: X → svgX, Z (height) → inverted svgY
  if (!bodyVerts || bodyVerts.length === 0) return null

  const W = 80
  const H = 120
  const PAD = 4

  // Compute bounding box across both body and cloth verts
  const allVerts = [...bodyVerts, ...(clothVerts || [])]
  const xs = allVerts.map(v => v[0])
  const zs = allVerts.map(v => v[2])
  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  const zMin = Math.min(...zs)
  const zMax = Math.max(...zs)
  const xRange = xMax - xMin || 1
  const zRange = zMax - zMin || 1

  const toSvg = (x, z) => [
    PAD + ((x - xMin) / xRange) * (W - 2 * PAD),
    H - PAD - ((z - zMin) / zRange) * (H - 2 * PAD),  // invert Z for screen
  ]

  const bodyDots = bodyVerts.slice(0, 300).map((v, i) => {
    const [sx, sy] = toSvg(v[0], v[2])
    return <circle key={i} cx={sx} cy={sy} r={0.8} fill="rgba(100,120,180,0.5)" />
  })

  const clothDots = (clothVerts || []).map((v, i) => {
    const [sx, sy] = toSvg(v[0], v[2])
    return <circle key={i} cx={sx} cy={sy} r={1.2} fill="rgba(239,100,80,0.8)" />
  })

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      className="block"
      aria-label="Body and cloth silhouette"
      data-testid="body-silhouette"
    >
      <rect x={0} y={0} width={W} height={H} fill="rgba(10,10,14,0.8)" rx={3} />
      {bodyDots}
      {clothDots}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Frame scrubber
// ---------------------------------------------------------------------------

function FrameScrubber({ frameIdx, totalFrames, onChange }) {
  return (
    <div className="flex items-center gap-2" data-testid="frame-scrubber">
      <button
        onClick={() => onChange(Math.max(0, frameIdx - 1))}
        className="p-0.5 rounded text-ink-400 hover:text-ink-200 disabled:opacity-30"
        disabled={frameIdx === 0}
        aria-label="Previous frame"
      >
        <ChevronLeft size={14} />
      </button>

      <input
        type="range"
        min={0}
        max={totalFrames - 1}
        value={frameIdx}
        onChange={e => onChange(Number(e.target.value))}
        className="flex-1 h-1.5 rounded accent-violet-500 cursor-pointer"
        aria-label="Frame scrubber"
        data-testid="frame-range-input"
      />

      <button
        onClick={() => onChange(Math.min(totalFrames - 1, frameIdx + 1))}
        className="p-0.5 rounded text-ink-400 hover:text-ink-200 disabled:opacity-30"
        disabled={frameIdx === totalFrames - 1}
        aria-label="Next frame"
      >
        <ChevronRight size={14} />
      </button>

      <span className="font-mono text-[10px] text-ink-500 w-12 text-right">
        {frameIdx + 1}/{totalFrames}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Metric chip
// ---------------------------------------------------------------------------

function Chip({ label, value, color = 'text-ink-300' }) {
  return (
    <div className="rounded border border-ink-800 bg-ink-950/50 px-2 py-1 text-center">
      <p className="text-[9px] font-mono uppercase tracking-wider text-ink-500">{label}</p>
      <p className={`font-mono mt-0.5 text-xs ${color}`}>{value}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

/**
 * ClothSimRiggedPanel — renders cloth-on-rigged-character simulation results.
 */
export default function ClothSimRiggedPanel({ result = null, content, className = '' }) {
  const [frameIdx, setFrameIdx] = useState(0)

  const effectiveResult = useMemo(() => {
    if (content != null) {
      try { return JSON.parse(content) } catch { return result }
    }
    return result
  }, [result, content])

  const parsed = useMemo(() => parseRiggedResult(effectiveResult), [effectiveResult])

  // Reset frame when result changes
  const handleFrameChange = useCallback((idx) => setFrameIdx(idx), [])

  if (parsed.kind === 'empty') {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 py-10 text-ink-500 ${className}`}
        data-testid="rigged-panel-empty"
      >
        <User size={28} className="opacity-40" />
        <p className="text-sm">No cloth simulation yet.</p>
        <p className="text-xs opacity-60">
          Ask Kerf to run cloth_sim_on_rigged_character with a pose sequence.
        </p>
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div
        className={`rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400 ${className}`}
        data-testid="rigged-panel-error"
      >
        Error: {parsed.error}
      </div>
    )
  }

  const { data } = parsed
  const {
    pose_type,
    n_frames,
    n_sampled_frames,
    n_cloth_particles,
    cloth_rows,
    cloth_cols,
    converged_static,
    energy_mean_j,
    energy_max_j,
    max_penetration_mean_cm,
    frames,
    notes,
    avatar,
    note,
  } = data

  const clampedIdx = Math.min(frameIdx, frames.length - 1)
  const currentFrame = interpolateBodyFrame(frames, clampedIdx)
  const stats = frameTensionStats(currentFrame)
  const heatmapScale = Math.max(0.005, Math.abs(stats.max) * 1.5 || 0.05)

  const penetrationOk = (currentFrame?.max_penetration_cm ?? 0) < 0.5
  const statusIcon = penetrationOk
    ? <CheckCircle size={12} className="text-green-400" />
    : <AlertTriangle size={12} className="text-yellow-400" />

  const poseLabel = {
    arm_raise: 'Arm raise',
    squat: 'Squat',
    static: 'Static T-pose',
    custom: 'Custom pose',
  }[pose_type] ?? pose_type

  return (
    <div className={`flex flex-col gap-3 ${className}`} data-testid="rigged-cloth-panel">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="grid place-items-center w-5 h-5 rounded bg-violet-500/10 border border-violet-500/20 text-violet-400">
          <Shirt size={11} />
        </span>
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink-400">
          Cloth on rigged character
        </span>
        <span
          className="ml-auto rounded-md border border-ink-700 bg-ink-900/60 px-2 py-0.5 font-mono text-[11px] text-ink-300"
          data-testid="pose-type-label"
        >
          {poseLabel}
        </span>
      </div>

      {/* Status bar */}
      <div
        className="flex flex-wrap items-center gap-2 text-[10px] font-mono"
        data-testid="rigged-status-bar"
      >
        <span className="flex items-center gap-1">
          {statusIcon}
          <span className={penetrationOk ? 'text-green-400' : 'text-yellow-400'}>
            {penetrationOk ? 'clean collision' : 'penetration'}
          </span>
        </span>
        <span className="text-ink-700">·</span>
        <span className="text-ink-500">
          {converged_static ? 'settled' : 'not settled'} on bind pose
        </span>
        <span className="text-ink-700">·</span>
        <span className="text-ink-500">
          {n_frames} frames · {cloth_rows}×{cloth_cols} cloth grid
        </span>
      </div>

      {/* Avatar measurements */}
      {avatar && (
        <div className="grid grid-cols-4 gap-1 text-xs" data-testid="avatar-measurements">
          {[
            ['Height', avatar.height_cm != null ? `${Math.round(avatar.height_cm)} cm` : '—'],
            ['Bust',   avatar.bust_cm  != null ? `${avatar.bust_cm.toFixed(0)} cm` : '—'],
            ['Waist',  avatar.waist_cm != null ? `${avatar.waist_cm.toFixed(0)} cm` : '—'],
            ['Hip',    avatar.hip_cm   != null ? `${avatar.hip_cm.toFixed(0)} cm` : '—'],
          ].map(([label, value]) => (
            <Chip key={label} label={label} value={value} />
          ))}
        </div>
      )}

      {/* Frame scrubber */}
      <div className="flex flex-col gap-1" data-testid="frame-controls">
        <p className="text-[9px] font-mono uppercase tracking-wider text-ink-500">
          Animation frame
        </p>
        <FrameScrubber
          frameIdx={clampedIdx}
          totalFrames={frames.length}
          onChange={handleFrameChange}
        />
      </div>

      {/* Main view: silhouette + heatmap + stats */}
      <div className="grid grid-cols-[auto_auto_1fr] gap-3 items-start" data-testid="rigged-main-view">
        {/* Body silhouette */}
        <div className="flex flex-col gap-1 items-center">
          <p className="text-[9px] font-mono uppercase tracking-wider text-ink-500 self-start">
            Body pose
          </p>
          <BodySilhouette
            bodyVerts={currentFrame?.cloth_positions_cm ?? []}
            clothVerts={null}
          />
        </div>

        {/* Cloth heatmap */}
        <div className="flex flex-col gap-1 items-center">
          <p className="text-[9px] font-mono uppercase tracking-wider text-ink-500 self-start">
            Garment drape
          </p>
          <ClothHeatmap
            fitTension={currentFrame?.fit_tension ?? []}
            rows={cloth_rows ?? 8}
            cols={cloth_cols ?? 8}
            scale={heatmapScale}
          />
          {/* Legend */}
          <div className="flex items-center gap-1 text-[9px] font-mono text-ink-500">
            <span className="inline-block w-3 h-2 rounded-sm bg-blue-500/70" />
            <span>loose</span>
            <span className="mx-1">→</span>
            <span className="inline-block w-3 h-2 rounded-sm bg-red-500/70" />
            <span>tight</span>
          </div>
        </div>

        {/* Per-frame metrics */}
        <div className="flex flex-col gap-2">
          <p className="text-[9px] font-mono uppercase tracking-wider text-ink-500">
            Frame {clampedIdx + 1} metrics
          </p>
          <div className="grid grid-cols-2 gap-1">
            <Chip
              label="Energy"
              value={currentFrame ? `${currentFrame.energy_j?.toFixed(4)} J` : '—'}
            />
            <Chip
              label="Penetration"
              value={currentFrame ? `${currentFrame.max_penetration_cm?.toFixed(3)} cm` : '—'}
              color={penetrationOk ? 'text-green-400' : 'text-yellow-400'}
            />
            <Chip
              label="Tension mean"
              value={Number.isFinite(stats.mean) ? `${stats.mean > 0 ? '+' : ''}${stats.mean.toFixed(3)}` : '—'}
            />
            <Chip
              label="Tension max"
              value={Number.isFinite(stats.max) ? `+${stats.max.toFixed(3)}` : '—'}
            />
          </div>

          {/* Global summary */}
          <div className="text-[10px] font-mono text-ink-500 space-y-0.5 mt-1">
            <div>Avg energy: <span className="text-ink-300">{energy_mean_j?.toFixed(4)} J</span></div>
            <div>Max energy: <span className="text-ink-300">{energy_max_j?.toFixed(4)} J</span></div>
            <div>
              Avg pen:{' '}
              <span className={max_penetration_mean_cm < 0.5 ? 'text-green-400' : 'text-yellow-400'}>
                {max_penetration_mean_cm?.toFixed(3)} cm
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Simulation notes */}
      {notes && notes.length > 0 && (
        <div className="space-y-0.5" data-testid="sim-notes">
          {notes.map((n, i) => (
            <p key={i} className="text-[9px] font-mono text-ink-600 italic">{n}</p>
          ))}
        </div>
      )}

      {/* Physics / honesty note */}
      <p className="text-[10px] text-ink-600 italic leading-relaxed" data-testid="physics-note">
        {note ?? (
          'Cloth on rigged avatar: LBS (Mohr & Gleicher 2003) + Provot (1995) mass-spring ' +
          '+ Bridson (2003) mesh collision. Gaps: LBS only (no dual-quaternion), ' +
          'no self-collision, kinematic body, FK animation only.'
        )}
      </p>
    </div>
  )
}
