/**
 * garmentDrapePanel.test.jsx
 *
 * Source-level + pure-helper tests for GarmentDrapePanel.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import {
  parseDrapeResult,
  tensionColor,
  formatTension,
  interpretTension,
} from '../GarmentDrapePanel.jsx'

const SRC = readFileSync(
  resolve(__dirname, '../GarmentDrapePanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// Source structure checks
// ---------------------------------------------------------------------------

describe('GarmentDrapePanel — source structure', () => {
  it('exports default function GarmentDrapePanel', () => {
    expect(SRC).toMatch(/export default function GarmentDrapePanel/)
  })

  it('has data-testid for empty state', () => {
    expect(SRC).toMatch(/data-testid="drape-panel-empty"/)
  })

  it('has data-testid for error state', () => {
    expect(SRC).toMatch(/data-testid="drape-panel-error"/)
  })

  it('has data-testid for main panel', () => {
    expect(SRC).toMatch(/data-testid="garment-drape-panel"/)
  })

  it('has data-testid for fit-tension heatmap', () => {
    expect(SRC).toMatch(/data-testid="fit-tension-heatmap"/)
  })

  it('has data-testid for tension stats table', () => {
    expect(SRC).toMatch(/data-testid="drape-tension-stats"/)
  })

  it('has data-testid for avatar summary', () => {
    expect(SRC).toMatch(/data-testid="drape-avatar-summary"/)
  })

  it('has data-testid for status bar', () => {
    expect(SRC).toMatch(/data-testid="drape-status-bar"/)
  })

  it('has data-testid for fit interpretation', () => {
    expect(SRC).toMatch(/data-testid="drape-fit-interpretation"/)
  })

  it('exports parseDrapeResult, tensionColor, formatTension, interpretTension', () => {
    expect(SRC).toMatch(/export function parseDrapeResult/)
    expect(SRC).toMatch(/export function tensionColor/)
    expect(SRC).toMatch(/export function formatTension/)
    expect(SRC).toMatch(/export function interpretTension/)
  })

  it('references Provot 1995 or Bridson 2003 in physics note', () => {
    expect(SRC).toMatch(/Provot|Bridson/)
  })

  it('has heatmap cell data-testid pattern', () => {
    expect(SRC).toMatch(/data-testid=\{`heatmap-cell/)
  })

  it('has tension legend', () => {
    expect(SRC).toMatch(/data-testid="tension-legend"/)
  })

  it('has region label', () => {
    expect(SRC).toMatch(/data-testid="drape-region-label"/)
  })
})

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const SAMPLE_TENSION = [0.02, -0.01, 0.03, 0.0, 0.05, -0.02, 0.01, 0.04, 0.0]

const SAMPLE_RESULT = {
  ok: true,
  target_region: 'torso',
  panel_rows: 3,
  panel_cols: 3,
  converged: true,
  steps_taken: 1200,
  max_penetration_cm: 0.03,
  no_deep_penetration: true,
  symmetry_error_cm: 0.12,
  fit_tension: SAMPLE_TENSION,
  fit_tension_mean: 0.015,
  fit_tension_max: 0.05,
  fit_tension_min: -0.02,
  fit_tension_rms: 0.024,
  vertices_3d: SAMPLE_TENSION.map((_, i) => [i * 5.0, 100.0, 110.0]),
  avatar: {
    height_cm: 168,
    bust_cm: 92,
    waist_cm: 74,
    hip_cm: 96,
    sex: 'female',
  },
  note: 'Mass-spring cloth solver (Provot 1995) + mesh-triangle collision response (Bridson 2003).',
}

// ---------------------------------------------------------------------------
// parseDrapeResult
// ---------------------------------------------------------------------------

describe('parseDrapeResult', () => {
  it('returns empty for null', () => {
    expect(parseDrapeResult(null).kind).toBe('empty')
  })

  it('returns empty for undefined', () => {
    expect(parseDrapeResult(undefined).kind).toBe('empty')
  })

  it('returns invalid for ok=false result', () => {
    const r = parseDrapeResult({ ok: false, error: 'drape simulation failed' })
    expect(r.kind).toBe('invalid')
    expect(r.error).toMatch(/drape simulation failed/)
  })

  it('returns invalid for error key', () => {
    const r = parseDrapeResult({ error: 'bad input' })
    expect(r.kind).toBe('invalid')
  })

  it('returns invalid when fit_tension missing', () => {
    const r = parseDrapeResult({ ok: true, vertices_3d: [] })
    expect(r.kind).toBe('invalid')
  })

  it('returns invalid when vertices_3d missing', () => {
    const r = parseDrapeResult({ ok: true, fit_tension: [] })
    expect(r.kind).toBe('invalid')
  })

  it('parses valid full result', () => {
    const r = parseDrapeResult(SAMPLE_RESULT)
    expect(r.kind).toBe('ok')
    expect(r.data.target_region).toBe('torso')
    expect(r.data.panel_rows).toBe(3)
  })

  it('parses fit_tension array', () => {
    const r = parseDrapeResult(SAMPLE_RESULT)
    expect(r.kind).toBe('ok')
    expect(r.data.fit_tension).toHaveLength(9)
  })

  it('accepts JSON string input', () => {
    const r = parseDrapeResult(JSON.stringify(SAMPLE_RESULT))
    expect(r.kind).toBe('ok')
    expect(r.data.converged).toBe(true)
  })

  it('parses avatar sub-object', () => {
    const r = parseDrapeResult(SAMPLE_RESULT)
    expect(r.kind).toBe('ok')
    expect(r.data.avatar.bust_cm).toBe(92)
    expect(r.data.avatar.sex).toBe('female')
  })

  it('invalid JSON string returns invalid', () => {
    const r = parseDrapeResult('{bad json}')
    expect(r.kind).toBe('invalid')
  })
})

// ---------------------------------------------------------------------------
// tensionColor
// ---------------------------------------------------------------------------

describe('tensionColor', () => {
  it('returns a CSS rgb() string', () => {
    const c = tensionColor(0.05, 0.05)
    expect(c).toMatch(/^rgb\(\d+,\d+,\d+\)/)
  })

  it('zero tension is near white', () => {
    const c = tensionColor(0.0, 0.05)
    // Should be close to rgb(248, 248, 248)
    expect(c).toMatch(/rgb\(248,248,248\)/)
  })

  it('positive tension goes toward red (first channel high)', () => {
    const c = tensionColor(0.05, 0.05)   // full positive
    // Red component should be higher than blue
    const [, r, g, b] = c.match(/rgb\((\d+),(\d+),(\d+)\)/).map(Number)
    expect(r).toBeGreaterThan(b)
  })

  it('negative tension goes toward blue (third channel high)', () => {
    const c = tensionColor(-0.05, 0.05)  // full negative
    const [, r, g, b] = c.match(/rgb\((\d+),(\d+),(\d+)\)/).map(Number)
    expect(b).toBeGreaterThan(r)
  })

  it('handles NaN input gracefully', () => {
    const c = tensionColor(NaN, 0.05)
    expect(c).toBe('#888888')
  })

  it('handles infinite scale gracefully', () => {
    const c = tensionColor(0.01, 0)   // scale=0 → fallback
    expect(c).toBe('#888888')
  })

  it('clamps tension beyond scale to max colour', () => {
    const c1 = tensionColor(0.05, 0.05)   // exactly at scale
    const c2 = tensionColor(1.0,  0.05)   // way beyond scale
    expect(c1).toBe(c2)                    // both clamp to pure red
  })
})

// ---------------------------------------------------------------------------
// formatTension
// ---------------------------------------------------------------------------

describe('formatTension', () => {
  it('formats positive with + prefix', () => {
    expect(formatTension(0.015)).toBe('+0.015')
  })

  it('formats negative', () => {
    expect(formatTension(-0.01)).toBe('-0.010')
  })

  it('formats zero as +0.000', () => {
    expect(formatTension(0)).toBe('+0.000')
  })

  it('returns — for NaN', () => {
    expect(formatTension(NaN)).toBe('—')
  })

  it('returns — for null', () => {
    expect(formatTension(null)).toBe('—')
  })

  it('uses 3 decimal places', () => {
    expect(formatTension(0.1234)).toBe('+0.123')
  })
})

// ---------------------------------------------------------------------------
// interpretTension
// ---------------------------------------------------------------------------

describe('interpretTension', () => {
  it('positive mean > 0.02 is tight', () => {
    expect(interpretTension(0.03)).toBe('tight')
  })

  it('mean 0.0 is good', () => {
    expect(interpretTension(0.0)).toBe('good')
  })

  it('mean 0.01 is good (within tight threshold)', () => {
    expect(interpretTension(0.01)).toBe('good')
  })

  it('mean < -0.01 is loose', () => {
    expect(interpretTension(-0.02)).toBe('loose')
  })

  it('NaN returns unknown', () => {
    expect(interpretTension(NaN)).toBe('unknown')
  })

  it('exactly at tight threshold (0.02) is tight', () => {
    expect(interpretTension(0.021)).toBe('tight')
  })

  it('exactly at loose threshold (-0.01) is loose', () => {
    expect(interpretTension(-0.011)).toBe('loose')
  })
})
