// StudioLightingPicker.test.jsx — Vitest assertions for StudioLightingPicker.
//
// Pure data-layer tests: exercises getPresetMeta and the STUDIO_PRESETS
// registry without React DOM rendering overhead.

import { describe, it, expect } from 'vitest'
import { getPresetMeta } from './StudioLightingPicker.jsx'
import { STUDIO_PRESETS } from '../lib/studioLighting.js'

// ── getPresetMeta ─────────────────────────────────────────────────────────────

describe('getPresetMeta', () => {
  it('returns null for an unknown preset name', () => {
    expect(getPresetMeta('neon-disco')).toBeNull()
  })

  it('returns metadata for each preset in STUDIO_PRESETS', () => {
    STUDIO_PRESETS.forEach((name) => {
      const meta = getPresetMeta(name)
      expect(meta).not.toBeNull()
      expect(typeof meta.label).toBe('string')
      expect(meta.label.length).toBeGreaterThan(0)
      expect(typeof meta.description).toBe('string')
      expect(typeof meta.lightCount).toBe('number')
      expect(meta.lightCount).toBeGreaterThan(0)
    })
  })

  it('three-point has lightCount 3', () => {
    expect(getPresetMeta('three-point').lightCount).toBe(3)
  })

  it('four-point has lightCount 4', () => {
    expect(getPresetMeta('four-point').lightCount).toBe(4)
  })

  it('butterfly has lightCount 2', () => {
    expect(getPresetMeta('butterfly').lightCount).toBe(2)
  })

  it('rembrandt has lightCount 2', () => {
    expect(getPresetMeta('rembrandt').lightCount).toBe(2)
  })

  it('ring-light has lightCount 8', () => {
    expect(getPresetMeta('ring-light').lightCount).toBe(8)
  })

  it('softbox has lightCount 1', () => {
    expect(getPresetMeta('softbox').lightCount).toBe(1)
  })

  it('every preset has a non-empty description', () => {
    STUDIO_PRESETS.forEach((name) => {
      expect(getPresetMeta(name).description.length).toBeGreaterThan(0)
    })
  })
})

// ── STUDIO_PRESETS coverage ────────────────────────────────────────────────────

describe('STUDIO_PRESETS meta coverage', () => {
  it('every preset in STUDIO_PRESETS has a corresponding META entry', () => {
    STUDIO_PRESETS.forEach((name) => {
      expect(getPresetMeta(name)).not.toBeNull()
    })
  })

  it('lightCount values match expected preset counts', () => {
    const expected = {
      'three-point': 3,
      'four-point': 4,
      'butterfly': 2,
      'rembrandt': 2,
      'ring-light': 8,
      'softbox': 1,
    }
    STUDIO_PRESETS.forEach((name) => {
      expect(getPresetMeta(name).lightCount).toBe(expected[name])
    })
  })
})
