// QualityPicker — segmented control for selecting a render quality preset.
//
// Props:
//   value    - Current preset name, one of QUALITY_PRESETS.
//   onChange - Called with the new preset name when user clicks.
//   disabled - When true, all buttons are inert (default false).
//
// Exports getPresetMeta for test access to label/description data.

import { QUALITY_PRESETS } from '../lib/qualityPresets.js'

// ── Preset display metadata ────────────────────────────────────────────────────

export interface QualityPresetMeta {
  label: string
  description: string
  shortDesc: string
}

const PRESET_META: Record<string, QualityPresetMeta> = {
  draft: {
    label: 'Draft',
    description: '1 sample · no AA',
    shortDesc: '1 spp',
  },
  preview: {
    label: 'Preview',
    description: '4 samples · FXAA',
    shortDesc: '4 spp',
  },
  final: {
    label: 'Final',
    description: '64 samples · TAA',
    shortDesc: '64 spp',
  },
  path_traced: {
    label: 'Path',
    description: '512 samples · TAA',
    shortDesc: '512 spp',
  },
}

/**
 * Return display metadata for a preset name.
 */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper consumed directly by tests; not a component
export function getPresetMeta(name: string): QualityPresetMeta {
  return PRESET_META[name] ?? { label: name, description: '', shortDesc: '' }
}

// ── Component ──────────────────────────────────────────────────────────────────

export interface QualityPickerProps {
  value?: string
  onChange?: (name: string) => void
  disabled?: boolean
}

/**
 * QualityPicker — segmented button strip for choosing a render quality preset.
 */
export default function QualityPicker({ value, onChange, disabled = false }: QualityPickerProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Render quality"
      className="inline-flex rounded-md border border-ink-800 overflow-hidden bg-ink-950"
    >
      {QUALITY_PRESETS.map((name: string) => {
        const meta = getPresetMeta(name)
        const isActive = value === name
        return (
          <button
            key={name}
            type="button"
            role="radio"
            aria-checked={isActive}
            aria-label={`${meta.label} — ${meta.description}`}
            disabled={disabled}
            onClick={() => !disabled && onChange?.(name)}
            title={meta.description}
            className={[
              'relative flex flex-col items-center justify-center px-3 py-1.5 text-[10px] font-medium',
              'transition-colors duration-100 select-none outline-none',
              'focus-visible:ring-1 focus-visible:ring-kerf-300/60 focus-visible:z-10',
              'border-r border-ink-800 last:border-r-0',
              disabled
                ? 'opacity-40 cursor-not-allowed'
                : 'cursor-pointer',
              isActive
                ? 'bg-kerf-300/15 text-kerf-300'
                : 'text-ink-400 hover:text-ink-200 hover:bg-ink-800/60',
            ].join(' ')}
          >
            <span className="leading-none">{meta.label}</span>
            <span
              className={[
                'mt-0.5 leading-none text-[9px]',
                isActive ? 'text-kerf-300/70' : 'text-ink-600',
              ].join(' ')}
            >
              {meta.shortDesc}
            </span>
            {isActive && (
              <span
                aria-hidden="true"
                className="absolute bottom-0 left-0 right-0 h-[2px] bg-kerf-300 rounded-t"
              />
            )}
          </button>
        )
      })}
    </div>
  )
}
