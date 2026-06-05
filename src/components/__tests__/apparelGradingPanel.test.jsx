/**
 * apparelGradingPanel.test.jsx
 *
 * Source-level + pure-helper tests for ApparelGradingPanel.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import {
  parseGradingResult,
  formatGradeDelta,
  sizeColor,
} from '../ApparelGradingPanel.jsx'

const SRC = readFileSync(
  resolve(__dirname, '../ApparelGradingPanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// Source structure
// ---------------------------------------------------------------------------

describe('ApparelGradingPanel — source structure', () => {
  it('exports default function ApparelGradingPanel', () => {
    expect(SRC).toMatch(/export default function ApparelGradingPanel/)
  })

  it('has data-testid for empty state', () => {
    expect(SRC).toMatch(/data-testid="grading-panel-empty"/)
  })

  it('has data-testid for error state', () => {
    expect(SRC).toMatch(/data-testid="grading-panel-error"/)
  })

  it('has data-testid for main panel', () => {
    expect(SRC).toMatch(/data-testid="apparel-grading-panel"/)
  })

  it('has data-testid for size-run table', () => {
    expect(SRC).toMatch(/data-testid="grading-size-run-table"/)
  })

  it('has data-testid for single-grade view', () => {
    expect(SRC).toMatch(/data-testid="grading-single-view"/)
  })

  it('has data-testid for block label', () => {
    expect(SRC).toMatch(/data-testid="grading-block-label"/)
  })

  it('exports parseGradingResult, formatGradeDelta, sizeColor', () => {
    expect(SRC).toMatch(/export function parseGradingResult/)
    expect(SRC).toMatch(/export function formatGradeDelta/)
    expect(SRC).toMatch(/export function sizeColor/)
  })
})

// ---------------------------------------------------------------------------
// parseGradingResult
// ---------------------------------------------------------------------------

describe('parseGradingResult', () => {
  it('returns empty for null', () => {
    expect(parseGradingResult(null).kind).toBe('empty')
  })

  it('returns invalid for error key', () => {
    const r = parseGradingResult({ error: 'bad_args' })
    expect(r.kind).toBe('invalid')
  })

  it('detects size_run type from sizes key', () => {
    const r = parseGradingResult({
      base_size: 'M',
      block: 'bodice_front',
      spec: 'women_us',
      sizes: {
        S: { bust_girth_cm: 86, width_cm: 42, height_cm: 60, area_cm2: 500 },
        M: { bust_girth_cm: 92, width_cm: 44, height_cm: 62, area_cm2: 530 },
        L: { bust_girth_cm: 98, width_cm: 46, height_cm: 64, area_cm2: 560 },
      },
    })
    expect(r.kind).toBe('ok')
    expect(r.type).toBe('size_run')
    expect(r.data.sizes).toBeDefined()
    expect(Object.keys(r.data.sizes)).toHaveLength(3)
  })

  it('detects single type from from_size/to_size', () => {
    const r = parseGradingResult({
      block: 'bodice_front',
      from_size: 'M',
      to_size: 'L',
      spec: 'women_us',
      grade_dx_mm: 5.0,
      grade_dy_mm: 3.0,
      from_bbox_cm: { width: 44.0, height: 62.0 },
      to_bbox_cm:   { width: 46.0, height: 64.0 },
      from_area_cm2: 530.0,
      to_area_cm2:   560.0,
    })
    expect(r.kind).toBe('ok')
    expect(r.type).toBe('single')
    expect(r.data.from_size).toBe('M')
    expect(r.data.to_size).toBe('L')
  })

  it('returns invalid for unrecognised shape', () => {
    const r = parseGradingResult({ block: 'sleeve' }) // no sizes, no from_size/to_size
    expect(r.kind).toBe('invalid')
  })

  it('accepts JSON string input', () => {
    const raw = JSON.stringify({ base_size: 'M', sizes: { M: { width_cm: 44 } } })
    const r = parseGradingResult(raw)
    expect(r.kind).toBe('ok')
    expect(r.type).toBe('size_run')
  })
})

// ---------------------------------------------------------------------------
// formatGradeDelta
// ---------------------------------------------------------------------------

describe('formatGradeDelta', () => {
  it('formats positive deltas with + sign', () => {
    const s = formatGradeDelta(5.0, 3.0)
    expect(s).toContain('+5.0')
    expect(s).toContain('+3.0')
  })

  it('formats negative deltas with minus sign', () => {
    const s = formatGradeDelta(-5.0, -3.0)
    expect(s).toContain('−5.0')
    expect(s).toContain('−3.0')
  })

  it('returns — for null/null', () => {
    expect(formatGradeDelta(null, null)).toBe('—')
  })

  it('handles zero deltas', () => {
    const s = formatGradeDelta(0, 0)
    expect(s).toContain('+0.0')
  })
})

// ---------------------------------------------------------------------------
// sizeColor
// ---------------------------------------------------------------------------

describe('sizeColor', () => {
  it('returns a Tailwind text class for standard sizes', () => {
    const colour = sizeColor('M')
    expect(colour).toMatch(/^text-/)
  })

  it('returns a fallback class for unknown sizes', () => {
    const colour = sizeColor('XXXL')
    expect(colour).toMatch(/^text-/)
  })

  it('is case-insensitive', () => {
    expect(sizeColor('m')).toBe(sizeColor('M'))
  })

  it('XS → S → M → L → XL all map to distinct colours', () => {
    const colours = ['XS', 'S', 'M', 'L', 'XL'].map(sizeColor)
    const unique = new Set(colours)
    expect(unique.size).toBe(5)
  })
})
