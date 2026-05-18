// nestingLayoutView.test.js — pure layout/scale math for NestingLayoutView.
//
// No DOM mount — exercises the exported pure helpers:
//   nestViewport   — SVG viewBox + scale computation
//   partColorIndex — stable hash-based colour index
//   fmtUtilization — percent formatting
//   fmtCutLength   — mm / m formatting
//   inferSheetSize — bounding-box + margin inference
//   PART_COLORS    — palette sanity

import { describe, it, expect } from 'vitest'
import {
  nestViewport,
  partColorIndex,
  fmtUtilization,
  fmtCutLength,
  inferSheetSize,
  PART_COLORS,
} from '../components/NestingLayoutView.jsx'

// ---------------------------------------------------------------------------
// nestViewport
// ---------------------------------------------------------------------------

describe('nestViewport', () => {
  it('returns a fallback viewBox for zero/null inputs', () => {
    const r = nestViewport(0, 0, 600, 450)
    expect(r.viewBox).toBe('0 0 100 100')
  })

  it('returns a fallback viewBox when viewport dimensions are zero', () => {
    const r = nestViewport(200, 100, 0, 0)
    expect(r.viewBox).toBe('0 0 100 100')
  })

  it('produces a viewBox string with 4 space-separated numbers', () => {
    const r = nestViewport(200, 100, 600, 450)
    const parts = r.viewBox.split(' ')
    expect(parts).toHaveLength(4)
    parts.forEach((p) => expect(Number.isFinite(parseFloat(p))).toBe(true))
  })

  it('viewBox min-x and min-y are negative (padding extends beyond origin)', () => {
    const r = nestViewport(200, 100, 600, 450)
    const [minX, minY] = r.viewBox.split(' ').map(Number)
    expect(minX).toBeLessThan(0)
    expect(minY).toBeLessThan(0)
  })

  it('viewBox width > sheetW (padding added)', () => {
    const r = nestViewport(200, 100, 600, 450)
    const parts = r.viewBox.split(' ').map(Number)
    const vbW = parts[2]
    expect(vbW).toBeGreaterThan(200)
  })

  it('viewBox height > sheetH (padding added)', () => {
    const r = nestViewport(200, 100, 600, 450)
    const parts = r.viewBox.split(' ').map(Number)
    const vbH = parts[3]
    expect(vbH).toBeGreaterThan(100)
  })

  it('scale is positive', () => {
    const r = nestViewport(200, 100, 600, 450)
    expect(r.scale).toBeGreaterThan(0)
  })

  it('scale is larger for a bigger sheet in the same viewport', () => {
    const small = nestViewport(100, 100, 600, 450)
    const large = nestViewport(500, 500, 600, 450)
    expect(large.scale).toBeGreaterThan(small.scale)
  })

  it('scale is smaller for a smaller sheet in the same viewport', () => {
    const big = nestViewport(1000, 1000, 600, 450)
    const tiny = nestViewport(10, 10, 600, 450)
    expect(tiny.scale).toBeLessThan(big.scale)
  })

  it('paddedX equals the negative of min-x from viewBox', () => {
    const r = nestViewport(200, 100, 600, 450)
    const [minX] = r.viewBox.split(' ').map(Number)
    expect(r.paddedX).toBeCloseTo(minX, 3)
  })

  it('paddedW matches the width component of the viewBox', () => {
    const r = nestViewport(200, 100, 600, 450)
    const parts = r.viewBox.split(' ').map(Number)
    expect(r.paddedW).toBeCloseTo(parts[2], 3)
  })

  it('square sheet produces square padded viewport', () => {
    const r = nestViewport(100, 100, 600, 450)
    expect(r.paddedW).toBeCloseTo(r.paddedH, 3)
  })

  it('custom padding=0 means viewBox starts at origin', () => {
    const r = nestViewport(200, 100, 600, 450, 0)
    const [minX, minY] = r.viewBox.split(' ').map(Number)
    expect(minX).toBeCloseTo(0, 3)
    expect(minY).toBeCloseTo(0, 3)
  })
})

// ---------------------------------------------------------------------------
// partColorIndex
// ---------------------------------------------------------------------------

describe('partColorIndex', () => {
  it('returns an integer in range [0, paletteSize)', () => {
    const idx = partColorIndex('gusset')
    expect(idx).toBeGreaterThanOrEqual(0)
    expect(idx).toBeLessThan(PART_COLORS.length)
  })

  it('is deterministic — same name always returns same index', () => {
    expect(partColorIndex('bracket')).toBe(partColorIndex('bracket'))
    expect(partColorIndex('panel-left')).toBe(partColorIndex('panel-left'))
  })

  it('different names typically produce different indices', () => {
    const names = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta', 'iota', 'kappa']
    const indices = names.map((n) => partColorIndex(n))
    const unique = new Set(indices)
    // Not all same — the hash should spread across the palette.
    expect(unique.size).toBeGreaterThan(1)
  })

  it('respects a custom paletteSize', () => {
    for (let i = 0; i < 20; i++) {
      expect(partColorIndex(`part-${i}`, 4)).toBeLessThan(4)
    }
  })

  it('handles an empty string without throwing', () => {
    expect(() => partColorIndex('')).not.toThrow()
    const idx = partColorIndex('')
    expect(idx).toBeGreaterThanOrEqual(0)
  })
})

// ---------------------------------------------------------------------------
// fmtUtilization
// ---------------------------------------------------------------------------

describe('fmtUtilization', () => {
  it('returns "—" for null', () => {
    expect(fmtUtilization(null)).toBe('—')
  })

  it('returns "—" for undefined', () => {
    expect(fmtUtilization(undefined)).toBe('—')
  })

  it('returns "—" for NaN', () => {
    expect(fmtUtilization(NaN)).toBe('—')
  })

  it('formats 0 as "0.0%"', () => {
    expect(fmtUtilization(0)).toBe('0.0%')
  })

  it('formats 1.0 as "100.0%"', () => {
    expect(fmtUtilization(1.0)).toBe('100.0%')
  })

  it('formats 0.745 as "74.5%"', () => {
    expect(fmtUtilization(0.745)).toBe('74.5%')
  })

  it('formats 0.3 as "30.0%"', () => {
    expect(fmtUtilization(0.3)).toBe('30.0%')
  })

  it('always ends with "%"', () => {
    expect(fmtUtilization(0.5)).toMatch(/%$/)
  })
})

// ---------------------------------------------------------------------------
// fmtCutLength
// ---------------------------------------------------------------------------

describe('fmtCutLength', () => {
  it('returns "—" for null', () => {
    expect(fmtCutLength(null)).toBe('—')
  })

  it('returns "—" for undefined', () => {
    expect(fmtCutLength(undefined)).toBe('—')
  })

  it('returns "—" for NaN', () => {
    expect(fmtCutLength(NaN)).toBe('—')
  })

  it('formats values < 1000 mm with " mm" suffix', () => {
    expect(fmtCutLength(500)).toMatch(/mm$/)
    expect(fmtCutLength(999.9)).toMatch(/mm$/)
  })

  it('formats values >= 1000 mm in metres', () => {
    expect(fmtCutLength(1000)).toMatch(/m$/)
    expect(fmtCutLength(2500)).toBe('2.50 m')
  })

  it('formats 0 as "0.0 mm"', () => {
    expect(fmtCutLength(0)).toBe('0.0 mm')
  })

  it('formats 123.456 mm as "123.5 mm" (1 decimal)', () => {
    expect(fmtCutLength(123.456)).toBe('123.5 mm')
  })

  it('formats 4200 mm as "4.20 m"', () => {
    expect(fmtCutLength(4200)).toBe('4.20 m')
  })
})

// ---------------------------------------------------------------------------
// inferSheetSize
// ---------------------------------------------------------------------------

describe('inferSheetSize', () => {
  it('returns a default 100×100 for empty placements', () => {
    const r = inferSheetSize([])
    expect(r.w).toBe(100)
    expect(r.h).toBe(100)
  })

  it('returns 100×100 for null input', () => {
    const r = inferSheetSize(null)
    expect(r.w).toBe(100)
    expect(r.h).toBe(100)
  })

  it('inferred size is larger than the rightmost/topmost part edge', () => {
    const placements = [
      { x: 5, y: 5, w: 80, h: 40 },
      { x: 90, y: 50, w: 60, h: 60 },
    ]
    const r = inferSheetSize(placements)
    expect(r.w).toBeGreaterThan(90 + 60)   // 150
    expect(r.h).toBeGreaterThan(50 + 60)   // 110
  })

  it('adds at least 5mm margin on each axis', () => {
    // Very small part: 1×1 at origin — margin must be >= 5 mm
    const placements = [{ x: 0, y: 0, w: 1, h: 1 }]
    const r = inferSheetSize(placements)
    expect(r.w).toBeGreaterThanOrEqual(1 + 5)
    expect(r.h).toBeGreaterThanOrEqual(1 + 5)
  })

  it('single placement maps to part bounding box + margin', () => {
    const placements = [{ x: 10, y: 20, w: 100, h: 50 }]
    const r = inferSheetSize(placements)
    // maxX = 110, maxY = 70; margin = max(110*0.1, 5)=11 and max(70*0.1, 5)=7
    expect(r.w).toBeCloseTo(110 + Math.max(110 * 0.1, 5), 5)
    expect(r.h).toBeCloseTo(70 + Math.max(70 * 0.1, 5), 5)
  })
})

// ---------------------------------------------------------------------------
// PART_COLORS palette
// ---------------------------------------------------------------------------

describe('PART_COLORS', () => {
  it('has at least 8 entries', () => {
    expect(PART_COLORS.length).toBeGreaterThanOrEqual(8)
  })

  it('each entry has fill and stroke strings', () => {
    for (const c of PART_COLORS) {
      expect(typeof c.fill).toBe('string')
      expect(typeof c.stroke).toBe('string')
    }
  })

  it('fill and stroke are distinct', () => {
    for (const c of PART_COLORS) {
      expect(c.fill).not.toBe(c.stroke)
    }
  })

  it('fill colours look like CSS hex colours', () => {
    for (const c of PART_COLORS) {
      expect(c.fill).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })

  it('stroke colours look like CSS hex colours', () => {
    for (const c of PART_COLORS) {
      expect(c.stroke).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })
})
