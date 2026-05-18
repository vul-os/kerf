// StudioLightingPicker — compact preset selector for studio lighting rigs.
//
// Props:
//   - value (string|null): currently active preset name, or null for none.
//   - onChange(presetName): called when the user picks a preset.
//   - className (string, optional): extra CSS classes for the root element.
//
// Re-exports getPresetMeta for use in data-layer tests without a DOM.

import { STUDIO_PRESETS } from '../lib/studioLighting.js'

// ── Metadata ──────────────────────────────────────────────────────────────────

const META = {
  'three-point': {
    label: 'Three-point',
    description: 'Key + fill + back — the universal workhorse rig.',
    lightCount: 3,
  },
  'four-point': {
    label: 'Four-point',
    description: 'Adds a kicker to the three-point rig for silhouette pop.',
    lightCount: 4,
  },
  'butterfly': {
    label: 'Butterfly',
    description: 'Overhead key + low fill — flattering portrait / beauty look.',
    lightCount: 2,
  },
  'rembrandt': {
    label: 'Rembrandt',
    description: '45° key creates the classic triangle of light under the eye.',
    lightCount: 2,
  },
  'ring-light': {
    label: 'Ring light',
    description: '8 lights in a ring — shadow-free, high-fashion look.',
    lightCount: 8,
  },
  'softbox': {
    label: 'Softbox',
    description: 'Single large overhead area light — clean product photography.',
    lightCount: 1,
  },
}

/**
 * Return display metadata for a preset name.
 * Exported so data-layer tests can use it without a DOM.
 *
 * @param {string} presetName
 * @returns {{ label: string, description: string, lightCount: number } | null}
 */
export function getPresetMeta(presetName) {
  return META[presetName] ?? null
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function StudioLightingPicker({ value, onChange, className = '' }) {
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <span className="text-[10px] uppercase tracking-wider text-ink-500 mb-0.5">
        Studio lighting
      </span>
      <div className="grid grid-cols-2 gap-1.5">
        {STUDIO_PRESETS.map((name) => {
          const meta = META[name]
          const active = value === name
          return (
            <button
              key={name}
              type="button"
              title={meta.description}
              onClick={() => onChange(name)}
              className={
                'flex flex-col gap-0.5 rounded-md border px-2.5 py-2 text-left transition-colors ' +
                (active
                  ? 'border-kerf-300/60 bg-kerf-300/10 text-ink-100'
                  : 'border-ink-800 bg-ink-900 text-ink-300 hover:border-ink-700 hover:text-ink-100')
              }
            >
              <span className="text-xs font-medium leading-snug">{meta.label}</span>
              <span className="text-[10px] text-ink-500 leading-snug">
                {meta.lightCount} light{meta.lightCount === 1 ? '' : 's'}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
