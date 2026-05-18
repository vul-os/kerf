/**
 * CameraLensPicker — camera-lens / projection picker widget.
 *
 * Renders a compact dropdown that lets the user choose between the five
 * supported camera projections (perspective, orthographic, two-point,
 * fisheye, panoramic-360) and, for projections that use a focal length,
 * also exposes controls for focal length and sensor size.
 *
 * Props
 * ─────
 *   projection    {string}   Current projection kind (one of CAMERA_PROJECTIONS).
 *   focalMm       {number}   Current focal length in mm (default 50).
 *   sensor        {string}   Current sensor key (one of SENSOR_SIZES keys).
 *   onProjection  {fn}       Called with (kind: string) when the user picks a projection.
 *   onFocalMm     {fn}       Called with (focal_mm: number) when focal length changes.
 *   onSensor      {fn}       Called with (sensor: string) when sensor changes.
 *
 * All callbacks are optional — the component is usable in read-only mode or
 * in partially-controlled mode.
 */

import { useState } from 'react'
import { Camera, ChevronDown } from 'lucide-react'
import {
  CAMERA_PROJECTIONS,
  SENSOR_SIZES,
  focalToFov,
} from '../lib/cameraProjections.js'

// ── Constants ─────────────────────────────────────────────────────────────────

/** Human-readable labels for each projection kind. */
const PROJECTION_LABELS = {
  'perspective':    'Perspective',
  'orthographic':   'Orthographic',
  'two-point':      'Two-Point',
  'fisheye':        'Fisheye',
  'panoramic-360':  'Panoramic 360°',
}

/** Short tooltip descriptions shown in the picker. */
const PROJECTION_DESCRIPTIONS = {
  'perspective':   'Standard rectilinear projection — the default.',
  'orthographic':  'No perspective foreshortening; parallel lines stay parallel.',
  'two-point':     'Verticals remain parallel; horizontals converge to two vanishing points.',
  'fisheye':       'Stereographic fisheye — ultra-wide hemispheric capture.',
  'panoramic-360': 'Equirectangular 360° panorama via cube-map unproject.',
}

/** Projections that expose focal-length / sensor controls. */
const USES_FOCAL = new Set(['perspective', 'two-point', 'fisheye'])

/** Ordered list of sensor display names. */
const SENSOR_OPTIONS = Object.keys(SENSOR_SIZES).map((key) => ({
  key,
  label: { 'full-frame': 'Full Frame (36mm)', 'aps-c': 'APS-C (23.6mm)', 'cinema-35': 'Cinema 35 (24.89mm)', 'micro-4-3': 'Micro 4/3 (17.3mm)' }[key] ?? key,
}))

/** Common focal-length presets in mm. */
const FOCAL_PRESETS = [14, 24, 35, 50, 85, 135, 200]

// ── Sub-components ────────────────────────────────────────────────────────────

/** Projection option row inside the dropdown menu. */
function ProjectionOption({ kind, active, onSelect }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={() => onSelect(kind)}
      className={[
        'w-full text-left px-3 py-2 flex flex-col gap-0.5 transition-colors',
        active
          ? 'bg-kerf-900/60 text-kerf-200'
          : 'text-ink-300 hover:bg-ink-800 hover:text-ink-100',
      ].join(' ')}
    >
      <span className="text-[12px] font-medium">{PROJECTION_LABELS[kind]}</span>
      <span className="text-[10px] text-ink-500 leading-snug">
        {PROJECTION_DESCRIPTIONS[kind]}
      </span>
    </button>
  )
}

/** Focal-length row: preset chips + numeric input. */
function FocalLengthRow({ focalMm, sensor, onFocalMm }) {
  const sensorWidth = SENSOR_SIZES[sensor] ?? SENSOR_SIZES['full-frame']
  const fov_deg     = focalToFov(focalMm, sensorWidth) * (180 / Math.PI)

  function handleInput(e) {
    const v = parseFloat(e.target.value)
    if (!isNaN(v) && v > 0 && typeof onFocalMm === 'function') onFocalMm(v)
  }

  return (
    <div className="px-3 py-2 border-t border-ink-800">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase tracking-wider text-ink-500 font-semibold">
          Focal Length
        </span>
        <span className="text-[10px] font-mono text-ink-400 tabular-nums">
          {fov_deg.toFixed(1)}° hFOV
        </span>
      </div>
      {/* Preset chips */}
      <div className="flex flex-wrap gap-1 mb-2">
        {FOCAL_PRESETS.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => typeof onFocalMm === 'function' && onFocalMm(f)}
            className={[
              'px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors',
              focalMm === f
                ? 'bg-kerf-700 text-kerf-100'
                : 'bg-ink-800 text-ink-400 hover:bg-ink-700 hover:text-ink-200',
            ].join(' ')}
            aria-pressed={focalMm === f}
          >
            {f}
          </button>
        ))}
      </div>
      {/* Numeric input */}
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          min="1"
          max="1000"
          step="1"
          value={focalMm}
          onChange={handleInput}
          aria-label="Focal length in millimetres"
          className="w-20 rounded bg-ink-800 border border-ink-700 px-2 py-1 text-[11px] font-mono text-ink-100 focus:outline-none focus:border-kerf-500"
        />
        <span className="text-[10px] text-ink-500">mm</span>
      </div>
    </div>
  )
}

/** Sensor-size row: a compact select. */
function SensorRow({ sensor, onSensor }) {
  return (
    <div className="px-3 py-2 border-t border-ink-800">
      <div className="text-[10px] uppercase tracking-wider text-ink-500 font-semibold mb-1.5">
        Sensor Size
      </div>
      <select
        value={sensor}
        onChange={(e) => typeof onSensor === 'function' && onSensor(e.target.value)}
        aria-label="Sensor size"
        className="w-full rounded bg-ink-800 border border-ink-700 px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-500"
      >
        {SENSOR_OPTIONS.map(({ key, label }) => (
          <option key={key} value={key}>{label}</option>
        ))}
      </select>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

/**
 * CameraLensPicker — dropdown widget for picking camera projection + lens settings.
 *
 * @param {{ projection?: string, focalMm?: number, sensor?: string,
 *           onProjection?: (kind: string) => void,
 *           onFocalMm?: (mm: number) => void,
 *           onSensor?: (key: string) => void }} props
 */
export default function CameraLensPicker({
  projection = 'perspective',
  focalMm    = 50,
  sensor     = 'full-frame',
  onProjection,
  onFocalMm,
  onSensor,
}) {
  const [open, setOpen] = useState(false)

  const label = PROJECTION_LABELS[projection] ?? projection

  function handleProjection(kind) {
    if (typeof onProjection === 'function') onProjection(kind)
    // Close immediately for orthographic / panoramic (no focal sub-controls).
    if (!USES_FOCAL.has(kind)) setOpen(false)
  }

  return (
    <div className="relative inline-block" data-testid="camera-lens-picker">
      {/* Trigger button */}
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        title="Camera projection and lens settings"
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-ink-900/85 border border-ink-700 text-[11px] font-mono text-ink-300 hover:text-kerf-300 hover:border-kerf-300/50 backdrop-blur shadow-lg shadow-black/30 transition-colors"
      >
        <Camera size={13} aria-hidden="true" />
        {label}
        <ChevronDown
          size={12}
          aria-hidden="true"
          className={`text-ink-500 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <>
          {/* Click-away backdrop */}
          <div
            className="fixed inset-0 z-0"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />

          {/* Dropdown panel */}
          <div
            role="menu"
            aria-label="Camera projection"
            className="absolute left-0 mt-1.5 z-10 w-64 rounded-lg border border-ink-700 bg-ink-900 shadow-2xl shadow-black/50 overflow-hidden"
          >
            {/* Projection list */}
            <div className="px-3 py-1.5 border-b border-ink-800 text-[10px] uppercase tracking-wider text-ink-500 font-semibold">
              Projection
            </div>
            <div role="group" aria-label="Projection options">
              {CAMERA_PROJECTIONS.map((kind) => (
                <ProjectionOption
                  key={kind}
                  kind={kind}
                  active={kind === projection}
                  onSelect={handleProjection}
                />
              ))}
            </div>

            {/* Focal length + sensor controls — only for relevant projections */}
            {USES_FOCAL.has(projection) && (
              <>
                <FocalLengthRow
                  focalMm={focalMm}
                  sensor={sensor}
                  onFocalMm={onFocalMm}
                />
                <SensorRow sensor={sensor} onSensor={onSensor} />
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
