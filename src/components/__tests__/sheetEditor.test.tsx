// sheetEditor.test.jsx — Pure data-layer tests for SheetEditor helpers.

import { describe, it, expect } from 'vitest'
import {
  VALID_SIZES,
  SHEET_SIZES_MM,
  defaultSheet,
  validateSheet,
  addViewport,
  removeViewport,
  moveViewport,
} from '../../lib/sheet.js'

// ── 1. defaultSheet ───────────────────────────────────────────────────────────

describe('defaultSheet', () => {
  it('creates a valid sheet', () => {
    const s = defaultSheet('Ground Floor Plan', 'A101')
    const { ok } = validateSheet(s)
    expect(ok).toBe(true)
  })

  it('defaults size to A1', () => {
    const s = defaultSheet('Site Plan', 'S001')
    expect(s.size).toBe('A1')
  })

  it('has landscape orientation by default', () => {
    const s = defaultSheet('Detail', 'D001')
    expect(s.orientation).toBe('landscape')
  })

  it('has an empty viewports array', () => {
    const s = defaultSheet('Detail', 'D001')
    expect(s.viewports).toHaveLength(0)
  })
})

// ── 2. validateSheet ──────────────────────────────────────────────────────────

describe('validateSheet', () => {
  it('rejects null', () => {
    const { ok } = validateSheet(null)
    expect(ok).toBe(false)
  })

  it('rejects an invalid size', () => {
    const s = { ...defaultSheet('X', 'X1'), size: 'B5' }
    const { ok } = validateSheet(s)
    expect(ok).toBe(false)
  })

  it('rejects a missing sheet_number', () => {
    const s = { ...defaultSheet('X', 'X1'), sheet_number: '' }
    const { ok, errors } = validateSheet(s)
    expect(ok).toBe(false)
    expect(errors.some((e) => /sheet_number/.test(e))).toBe(true)
  })

  it('rejects a viewport with non-positive scale', () => {
    let s = defaultSheet('X', 'X1')
    s = addViewport(s, 'view-1', [10, 10], 0.02)
    // Manually corrupt scale.
    s.viewports[0].scale = -1
    const { ok } = validateSheet(s)
    expect(ok).toBe(false)
  })
})

// ── 3. addViewport / removeViewport ───────────────────────────────────────────

describe('addViewport / removeViewport', () => {
  it('adds a viewport with the correct fields', () => {
    const s = defaultSheet('Plan', 'P1')
    const next = addViewport(s, 'view-abc', [20, 30], 0.02, 'Ground Floor')
    expect(next.viewports).toHaveLength(1)
    expect(next.viewports[0].view_file_id).toBe('view-abc')
    expect(next.viewports[0].title).toBe('Ground Floor')
    expect(next.viewports[0].scale).toBeCloseTo(0.02)
  })

  it('throws if view_file_id is missing', () => {
    const s = defaultSheet('P', 'P1')
    expect(() => addViewport(s, '', [0, 0], 0.02)).toThrow()
  })

  it('removes a viewport by id', () => {
    let s = defaultSheet('P', 'P1')
    s = addViewport(s, 'v1', [0, 0], 0.02)
    const id = s.viewports[0].id
    const removed = removeViewport(s, id)
    expect(removed.viewports).toHaveLength(0)
  })

  it('is immutable — original sheet unchanged', () => {
    const s = defaultSheet('P', 'P1')
    addViewport(s, 'v1', [0, 0], 0.02)
    expect(s.viewports).toHaveLength(0)
  })
})

// ── 4. moveViewport ───────────────────────────────────────────────────────────

describe('moveViewport', () => {
  it('updates the viewport position', () => {
    let s = defaultSheet('P', 'P1')
    s = addViewport(s, 'v1', [0, 0], 0.02)
    const id = s.viewports[0].id
    const moved = moveViewport(s, id, [100, 200])
    expect(moved.viewports[0].position).toEqual([100, 200])
  })
})

// ── 5. SHEET_SIZES_MM ─────────────────────────────────────────────────────────

describe('SHEET_SIZES_MM', () => {
  it('has entries for all VALID_SIZES', () => {
    for (const size of VALID_SIZES) {
      expect(SHEET_SIZES_MM).toHaveProperty(size)
    }
  })

  it('A4 is 210x297 mm', () => {
    expect(SHEET_SIZES_MM.A4).toEqual([210, 297])
  })
})
