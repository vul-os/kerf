/**
 * cfdViz.test.js — Unit tests for CFD visualisation helpers.
 * No DOM, no Three.js, no canvas rendering.
 * We test pure computation functions and mock canvas for draw functions.
 */
import { describe, it, expect, vi } from 'vitest'
import {
  scalarToCssColor,
  buildTransform,
  generateSeeds,
  generateInletSeeds,
  drawStreamlines,
  drawVectorArrows,
  drawPressureContour,
} from './cfdViz.js'

// ── Test field ────────────────────────────────────────────────────────────────

function makeField({ nx = 11, ny = 11, speed = 1 } = {}) {
  const u = Array.from({ length: ny }, () => Array(nx).fill(speed))
  const v = Array.from({ length: ny }, () => Array(nx).fill(0))
  return { x0: 0, y0: 0, dx: 1, dy: 1, nx, ny, u, v }
}

function makePressureField({ nx = 5, ny = 5 } = {}) {
  const field = makeField({ nx, ny })
  field.p = Array.from({ length: ny }, (_, row) =>
    Array.from({ length: nx }, (_, col) => col + row * nx)
  )
  return field
}

// ── Minimal canvas mock ───────────────────────────────────────────────────────

function makeCtx({ width = 300, height = 200 } = {}) {
  const calls = []
  const ctx = {
    canvas: { width, height },
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fillRect: vi.fn(),
    strokeStyle: '',
    fillStyle: '',
    lineWidth: 1,
    lineCap: '',
    lineJoin: '',
    // Track calls for assertions
    _calls: calls,
  }
  return ctx
}

// ── scalarToCssColor ─────────────────────────────────────────────────────────

describe('scalarToCssColor', () => {
  it('returns a valid rgba() string', () => {
    const css = scalarToCssColor(0.5)
    expect(css).toMatch(/^rgba\(\d+,\d+,\d+,[\d.]+\)$/)
  })

  it('t=0 → blue (r≈0, g≈0, b≈255)', () => {
    const css = scalarToCssColor(0)
    // blue: scalarToRGB(0) = [0, 0, 1]
    expect(css).toMatch(/rgba\(0,0,255,/)
  })

  it('t=1 → red (r≈255, g≈0, b≈0)', () => {
    const css = scalarToCssColor(1)
    expect(css).toMatch(/rgba\(255,0,0,/)
  })

  it('respects alpha parameter', () => {
    const css = scalarToCssColor(0.5, 0.4)
    expect(css).toContain('0.4')
  })

  it('clamps out-of-range values', () => {
    expect(() => scalarToCssColor(-1)).not.toThrow()
    expect(() => scalarToCssColor(2)).not.toThrow()
  })
})

// ── buildTransform ────────────────────────────────────────────────────────────

describe('buildTransform', () => {
  it('maps field origin to canvas top-left + margin region', () => {
    const field = makeField({ nx: 11, ny: 11 })
    const t = buildTransform(field, 300, 200, 10)
    const { cx, cy } = t.toCanvas(field.x0, field.y0)
    // Should be within the margin area
    expect(cx).toBeGreaterThanOrEqual(10)
    expect(cy).toBeLessThanOrEqual(200 - 10)
  })

  it('toCanvas and toWorld are approximate inverses', () => {
    const field = makeField({ nx: 11, ny: 11 })
    const t = buildTransform(field, 400, 300, 10)
    const wx = 3.5
    const wy = 7.2
    const { cx, cy } = t.toCanvas(wx, wy)
    const { wx: wx2, wy: wy2 } = t.toWorld(cx, cy)
    expect(wx2).toBeCloseTo(wx, 5)
    expect(wy2).toBeCloseTo(wy, 5)
  })

  it('field corner maps to expected canvas position', () => {
    const field = makeField({ nx: 11, ny: 11 })
    const t = buildTransform(field, 200, 200, 0)
    // x0=0, y0=0 → bottom-left in world = bottom-left in canvas (y flipped)
    const origin = t.toCanvas(0, 0)
    const far = t.toCanvas(10, 10)
    // Far corner (10,10) is top-right in world → top-right in canvas
    expect(far.cx).toBeGreaterThan(origin.cx)
    expect(far.cy).toBeLessThan(origin.cy)
  })
})

// ── generateSeeds ─────────────────────────────────────────────────────────────

describe('generateSeeds', () => {
  it('generates approximately the requested count', () => {
    const field = makeField()
    const seeds = generateSeeds(field, 20)
    // grid rounding: could be slightly more
    expect(seeds.length).toBeGreaterThanOrEqual(16)
    expect(seeds.length).toBeLessThanOrEqual(30)
  })

  it('all seeds are inside the domain', () => {
    const field = makeField()
    const seeds = generateSeeds(field, 20)
    for (const s of seeds) {
      expect(s.x).toBeGreaterThanOrEqual(field.x0)
      expect(s.x).toBeLessThanOrEqual(field.x0 + (field.nx - 1) * field.dx)
      expect(s.y).toBeGreaterThanOrEqual(field.y0)
      expect(s.y).toBeLessThanOrEqual(field.y0 + (field.ny - 1) * field.dy)
    }
  })

  it('count=1 returns at least one seed', () => {
    const field = makeField()
    expect(generateSeeds(field, 1).length).toBeGreaterThanOrEqual(1)
  })
})

// ── generateInletSeeds ────────────────────────────────────────────────────────

describe('generateInletSeeds', () => {
  it('seeds are near the left boundary', () => {
    const field = makeField()
    const seeds = generateInletSeeds(field, 5)
    expect(seeds.length).toBe(5)
    for (const s of seeds) {
      expect(s.x).toBeCloseTo(field.x0 + field.dx * 0.5, 3)
    }
  })

  it('seeds are spread across the y range', () => {
    const field = makeField({ nx: 11, ny: 11 })
    const seeds = generateInletSeeds(field, 10)
    const ys = seeds.map(s => s.y).sort((a, b) => a - b)
    expect(ys[0]).toBeGreaterThan(field.y0)
    expect(ys[ys.length - 1]).toBeLessThan(field.y0 + (field.ny - 1) * field.dy)
  })
})

// ── drawStreamlines ───────────────────────────────────────────────────────────

describe('drawStreamlines', () => {
  it('calls ctx drawing methods without throwing', () => {
    const field = makeField()
    const ctx = makeCtx()
    const seeds = [{ x: 1, y: 5 }, { x: 1, y: 3 }]
    expect(() =>
      drawStreamlines(ctx, field, seeds, { traceOpts: { max_steps: 20, dt: 0.5 } })
    ).not.toThrow()
    expect(ctx.save).toHaveBeenCalled()
    expect(ctx.restore).toHaveBeenCalled()
  })

  it('draws lines (beginPath + stroke called)', () => {
    const field = makeField()
    const ctx = makeCtx()
    const seeds = [{ x: 1, y: 5 }]
    drawStreamlines(ctx, field, seeds, { traceOpts: { max_steps: 5, dt: 0.5 } })
    expect(ctx.beginPath).toHaveBeenCalled()
    expect(ctx.stroke).toHaveBeenCalled()
  })

  it('handles empty seeds array without throwing', () => {
    const field = makeField()
    const ctx = makeCtx()
    expect(() => drawStreamlines(ctx, field, [])).not.toThrow()
  })

  it('handles cells-shape field', () => {
    const cells = []
    for (let row = 0; row < 5; row++)
      for (let col = 0; col < 5; col++)
        cells.push({ x: col, y: row, Ux: 1, Uy: 0 })
    const ctx = makeCtx()
    expect(() =>
      drawStreamlines(ctx, { cells }, [{ x: 1, y: 2 }], { traceOpts: { max_steps: 5 } })
    ).not.toThrow()
  })
})

// ── drawVectorArrows ──────────────────────────────────────────────────────────

describe('drawVectorArrows', () => {
  it('renders without throwing on a valid field', () => {
    const field = makeField()
    const ctx = makeCtx()
    expect(() => drawVectorArrows(ctx, field, { gridStep: 3 })).not.toThrow()
    expect(ctx.save).toHaveBeenCalled()
    expect(ctx.restore).toHaveBeenCalled()
  })

  it('calls stroke for at least one arrow', () => {
    const field = makeField()
    const ctx = makeCtx()
    drawVectorArrows(ctx, field, { gridStep: 3 })
    expect(ctx.stroke).toHaveBeenCalled()
  })

  it('does not throw on zero-velocity field', () => {
    const u = Array.from({ length: 5 }, () => Array(5).fill(0))
    const v = Array.from({ length: 5 }, () => Array(5).fill(0))
    const field = { x0: 0, y0: 0, dx: 1, dy: 1, nx: 5, ny: 5, u, v }
    const ctx = makeCtx()
    expect(() => drawVectorArrows(ctx, field)).not.toThrow()
  })
})

// ── drawPressureContour ───────────────────────────────────────────────────────

describe('drawPressureContour', () => {
  it('renders without throwing on a valid pressure field', () => {
    const field = makePressureField()
    const ctx = makeCtx()
    expect(() => drawPressureContour(ctx, field, { alpha: 0.4 })).not.toThrow()
    expect(ctx.fillRect).toHaveBeenCalled()
  })

  it('calls fillRect for each grid cell', () => {
    const field = makePressureField({ nx: 3, ny: 3 })
    const ctx = makeCtx()
    drawPressureContour(ctx, field)
    expect(ctx.fillRect).toHaveBeenCalledTimes(9)
  })

  it('handles cells-shape pressure field', () => {
    const cells = []
    for (let row = 0; row < 4; row++)
      for (let col = 0; col < 4; col++)
        cells.push({ x: col, y: row, Ux: 1, Uy: 0, p: col + row })
    const ctx = makeCtx()
    expect(() => drawPressureContour(ctx, { cells })).not.toThrow()
    expect(ctx.fillRect).toHaveBeenCalled()
  })

  it('returns early when field has no p array', () => {
    const field = makeField()  // no p
    const ctx = makeCtx()
    drawPressureContour(ctx, field)
    expect(ctx.fillRect).not.toHaveBeenCalled()
  })

  it('respects minVal/maxVal overrides', () => {
    const field = makePressureField()
    const ctx = makeCtx()
    expect(() =>
      drawPressureContour(ctx, field, { minVal: 0, maxVal: 100 })
    ).not.toThrow()
  })
})
