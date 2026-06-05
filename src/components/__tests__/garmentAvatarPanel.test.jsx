/**
 * garmentAvatarPanel.test.jsx
 *
 * Source-level + pure-helper tests for GarmentAvatarPanel.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import {
  parseAvatarResult,
  formatGirth,
  landmarkDisplayOrder,
} from '../GarmentAvatarPanel.jsx'

const SRC = readFileSync(
  resolve(__dirname, '../GarmentAvatarPanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// Source structure
// ---------------------------------------------------------------------------

describe('GarmentAvatarPanel — source structure', () => {
  it('exports default function GarmentAvatarPanel', () => {
    expect(SRC).toMatch(/export default function GarmentAvatarPanel/)
  })

  it('has data-testid for empty state', () => {
    expect(SRC).toMatch(/data-testid="avatar-panel-empty"/)
  })

  it('has data-testid for error state', () => {
    expect(SRC).toMatch(/data-testid="avatar-panel-error"/)
  })

  it('has data-testid for main panel', () => {
    expect(SRC).toMatch(/data-testid="garment-avatar-panel"/)
  })

  it('has data-testid for landmark table', () => {
    expect(SRC).toMatch(/data-testid="avatar-landmark-table"/)
  })

  it('has data-testid for silhouette SVG', () => {
    expect(SRC).toMatch(/data-testid="avatar-silhouette"/)
  })

  it('has data-testid for sex label', () => {
    expect(SRC).toMatch(/data-testid="avatar-sex-label"/)
  })

  it('has data-testid for key measurements', () => {
    expect(SRC).toMatch(/data-testid="avatar-key-measurements"/)
  })

  it('has data-testid for OBJ download', () => {
    expect(SRC).toMatch(/data-testid="avatar-obj-download"/)
  })

  it('exports parseAvatarResult, formatGirth, landmarkDisplayOrder', () => {
    expect(SRC).toMatch(/export function parseAvatarResult/)
    expect(SRC).toMatch(/export function formatGirth/)
    expect(SRC).toMatch(/export function landmarkDisplayOrder/)
  })

  it('mentions CAESAR (methodology disclosure)', () => {
    expect(SRC).toMatch(/CAESAR/)
  })

  it('includes a disclaimer about simplified mannequin', () => {
    expect(SRC).toMatch(/Simplified/)
  })
})

// ---------------------------------------------------------------------------
// parseAvatarResult
// ---------------------------------------------------------------------------

const SAMPLE_LANDMARKS = {
  crown:    { z_cm: 168, height_pct: 100, girth_cm: 34, half_width_cm: 9, half_depth_cm: 6.5 },
  neck:     { z_cm: 144, height_pct: 86,  girth_cm: 36, half_width_cm: 9.5, half_depth_cm: 7  },
  bust:     { z_cm: 122, height_pct: 73,  girth_cm: 92, half_width_cm: 18, half_depth_cm: 13  },
  waist:    { z_cm: 106, height_pct: 63,  girth_cm: 74, half_width_cm: 14, half_depth_cm: 10  },
  hip:      { z_cm: 91,  height_pct: 54,  girth_cm: 96, half_width_cm: 19, half_depth_cm: 14  },
  knee:     { z_cm: 45,  height_pct: 27,  girth_cm: 35, half_width_cm: 8,  half_depth_cm: 6   },
  floor:    { z_cm: 0,   height_pct: 0,   girth_cm: 20, half_width_cm: 5,  half_depth_cm: 3.6 },
}

const SAMPLE_RESULT = {
  height_cm: 168,
  bust_cm: 92,
  waist_cm: 74,
  hip_cm: 96,
  sex: 'female',
  n_slices: 48,
  n_vertices: 1602,
  n_faces: 3136,
  landmarks: SAMPLE_LANDMARKS,
  method: 'CAESAR ellipsoidal cross-section (Robinette 2002) + Ramanujan 1914',
  note: 'Simplified torso+leg mannequin.',
  obj: '# kerf-apparel body form\no body_form\nv 0 0 0\nf 1 1 1',
}

describe('parseAvatarResult', () => {
  it('returns empty for null', () => {
    expect(parseAvatarResult(null).kind).toBe('empty')
  })

  it('returns invalid for error key', () => {
    const r = parseAvatarResult({ error: 'height_cm must be positive' })
    expect(r.kind).toBe('invalid')
    expect(r.error).toMatch(/height_cm/)
  })

  it('returns invalid when landmarks is missing', () => {
    const r = parseAvatarResult({ height_cm: 168, n_vertices: 100 })
    expect(r.kind).toBe('invalid')
  })

  it('returns invalid for non-object landmarks', () => {
    const r = parseAvatarResult({ landmarks: 'bad' })
    expect(r.kind).toBe('invalid')
  })

  it('parses valid full result', () => {
    const r = parseAvatarResult(SAMPLE_RESULT)
    expect(r.kind).toBe('ok')
    expect(r.data.height_cm).toBe(168)
    expect(r.data.bust_cm).toBe(92)
    expect(r.data.sex).toBe('female')
  })

  it('parses landmarks', () => {
    const r = parseAvatarResult(SAMPLE_RESULT)
    expect(r.kind).toBe('ok')
    expect(r.data.landmarks.bust.girth_cm).toBe(92)
    expect(r.data.landmarks.waist.girth_cm).toBe(74)
  })

  it('accepts JSON string input', () => {
    const raw = JSON.stringify(SAMPLE_RESULT)
    const r = parseAvatarResult(raw)
    expect(r.kind).toBe('ok')
  })

  it('returns ok with obj included in data', () => {
    const r = parseAvatarResult(SAMPLE_RESULT)
    expect(r.data.obj).toMatch(/^# kerf-apparel/)
  })
})

// ---------------------------------------------------------------------------
// formatGirth
// ---------------------------------------------------------------------------

describe('formatGirth', () => {
  it('formats 92 cm to "92.0 cm"', () => {
    expect(formatGirth(92)).toBe('92.0 cm')
  })

  it('returns — for null', () => {
    expect(formatGirth(null)).toBe('—')
  })

  it('returns — for NaN', () => {
    expect(formatGirth(NaN)).toBe('—')
  })

  it('formats fractional cm', () => {
    expect(formatGirth(74.3)).toBe('74.3 cm')
  })
})

// ---------------------------------------------------------------------------
// landmarkDisplayOrder
// ---------------------------------------------------------------------------

describe('landmarkDisplayOrder', () => {
  it('returns an array with at least 10 entries', () => {
    const order = landmarkDisplayOrder()
    expect(order.length).toBeGreaterThanOrEqual(10)
  })

  it('crown is first', () => {
    expect(landmarkDisplayOrder()[0]).toBe('crown')
  })

  it('floor is last', () => {
    const order = landmarkDisplayOrder()
    expect(order[order.length - 1]).toBe('floor')
  })

  it('contains bust, waist, hip', () => {
    const order = landmarkDisplayOrder()
    expect(order).toContain('bust')
    expect(order).toContain('waist')
    expect(order).toContain('hip')
  })

  it('has no duplicates', () => {
    const order = landmarkDisplayOrder()
    expect(new Set(order).size).toBe(order.length)
  })
})
