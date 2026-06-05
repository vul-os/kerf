/**
 * textilesWeaveKnitPanel.test.jsx
 *
 * Source-level + pure-helper tests for TextilesWeaveKnitPanel.
 * Follows the clashPanel.test.jsx pattern: read source, test exports,
 * assert structure — no DOM renderer needed.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import {
  parseTextilesResult,
  fmtFloat,
  weaveStatLabel,
} from '../TextilesWeaveKnitPanel.jsx'

const SRC = readFileSync(
  resolve(__dirname, '../TextilesWeaveKnitPanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// Source structure
// ---------------------------------------------------------------------------

describe('TextilesWeaveKnitPanel — source structure', () => {
  it('exports a default function TextilesWeaveKnitPanel', () => {
    expect(SRC).toMatch(/export default function TextilesWeaveKnitPanel/)
  })

  it('has data-testid for empty state', () => {
    expect(SRC).toMatch(/data-testid="textiles-panel-empty"/)
  })

  it('has data-testid for error state', () => {
    expect(SRC).toMatch(/data-testid="textiles-panel-error"/)
  })

  it('has data-testid for main panel', () => {
    expect(SRC).toMatch(/data-testid="textiles-weave-knit-panel"/)
  })

  it('has data-testid for SVG preview', () => {
    expect(SRC).toMatch(/data-testid="textiles-svg-preview"/)
  })

  it('has data-testid for structure name', () => {
    expect(SRC).toMatch(/data-testid="textiles-structure-name"/)
  })

  it('imports useMemo from react', () => {
    expect(SRC).toMatch(/import.*useMemo.*from 'react'/)
  })

  it('exports parseTextilesResult, fmtFloat, weaveStatLabel', () => {
    expect(SRC).toMatch(/export function parseTextilesResult/)
    expect(SRC).toMatch(/export function fmtFloat/)
    expect(SRC).toMatch(/export function weaveStatLabel/)
  })
})

// ---------------------------------------------------------------------------
// parseTextilesResult
// ---------------------------------------------------------------------------

describe('parseTextilesResult', () => {
  it('returns empty for null', () => {
    expect(parseTextilesResult(null).kind).toBe('empty')
  })

  it('returns empty for undefined', () => {
    expect(parseTextilesResult(undefined).kind).toBe('empty')
  })

  it('returns invalid for garbage string', () => {
    expect(parseTextilesResult('not json').kind).toBe('invalid')
  })

  it('returns invalid when result has error key', () => {
    const r = parseTextilesResult({ error: 'unknown weave structure' })
    expect(r.kind).toBe('invalid')
    expect(r.error).toMatch(/unknown/)
  })

  it('detects weave type from float_stats', () => {
    const r = parseTextilesResult({
      name: '2/1 twill',
      float_stats: { warp_mean_float: 1.5, max_float: 2 },
      analytic_warp_mean_float: 1.5,
      analytic_weft_mean_float: 1.0,
      svg: '<svg/>',
    })
    expect(r.kind).toBe('ok')
    expect(r.type).toBe('weave')
    expect(r.name).toBe('2/1 twill')
  })

  it('detects knit type from density_stats', () => {
    const r = parseTextilesResult({
      name: 'jersey',
      density_stats: { wales_per_cm: 5.0, courses_per_cm: 7.0, density_within_1pct: true },
      svg: '<svg/>',
    })
    expect(r.kind).toBe('ok')
    expect(r.type).toBe('knit')
  })

  it('parses weave stats correctly', () => {
    const r = parseTextilesResult({
      analytic_warp_mean_float: 2.0,
      analytic_weft_mean_float: 1.0,
      float_stats: { max_float: 2 },
    })
    expect(r.stats.warp_mean_float).toBe(2.0)
    expect(r.stats.weft_mean_float).toBe(1.0)
  })

  it('parses knit stats correctly', () => {
    const r = parseTextilesResult({
      density_stats: { wales_per_cm: 5, courses_per_cm: 7, density_within_1pct: true },
    })
    expect(r.stats.wales_per_cm).toBe(5)
    expect(r.stats.courses_per_cm).toBe(7)
    expect(r.stats.density_within_1pct).toBe(true)
  })

  it('accepts JSON string input', () => {
    const raw = JSON.stringify({
      name: 'plain',
      float_stats: { warp_mean_float: 1.0 },
    })
    const r = parseTextilesResult(raw)
    expect(r.kind).toBe('ok')
    expect(r.name).toBe('plain')
  })
})

// ---------------------------------------------------------------------------
// fmtFloat
// ---------------------------------------------------------------------------

describe('fmtFloat', () => {
  it('formats a number to 2dp', () => {
    expect(fmtFloat(1.5)).toBe('1.50')
    expect(fmtFloat(2)).toBe('2.00')
  })

  it('returns — for null', () => {
    expect(fmtFloat(null)).toBe('—')
  })

  it('returns — for undefined', () => {
    expect(fmtFloat(undefined)).toBe('—')
  })

  it('returns — for NaN', () => {
    expect(fmtFloat(NaN)).toBe('—')
  })
})

// ---------------------------------------------------------------------------
// weaveStatLabel
// ---------------------------------------------------------------------------

describe('weaveStatLabel', () => {
  it('maps warp_mean_float to human label', () => {
    expect(weaveStatLabel('warp_mean_float')).toContain('Warp')
  })

  it('maps wales_per_cm to human label', () => {
    expect(weaveStatLabel('wales_per_cm')).toContain('Wales')
  })

  it('returns the key unchanged for unknown keys', () => {
    expect(weaveStatLabel('unknown_key_xyz')).toBe('unknown_key_xyz')
  })
})
