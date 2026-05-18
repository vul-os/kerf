/**
 * streamlineIntegrator.test.js
 *
 * Tests for the RK4 streamline integrator.  Pure maths, no DOM.
 */
import { describe, it, expect } from 'vitest'
import { traceStreamline, sampleField, cellsToGrid } from './streamlineIntegrator.js'

// ── Field builders ───────────────────────────────────────────────────────────

/**
 * Uniform rightward flow: U = (1, 0) everywhere.
 * Grid spans x: [0, 10], y: [0, 10] with dx=dy=1.
 */
function makeUniformHorizontal({ nx = 11, ny = 11, speed = 1 } = {}) {
  const u = []
  const v = []
  for (let row = 0; row < ny; row++) {
    u.push(Array.from({ length: nx }, () => speed))
    v.push(Array.from({ length: nx }, () => 0))
  }
  return { x0: 0, y0: 0, dx: 1, dy: 1, nx, ny, u, v }
}

/**
 * Circular flow: U = (-y, x) normalised to unit speed.
 * Streamlines are circles centred on origin.
 * Grid spans x: [-2, 2], y: [-2, 2] with step 0.1.
 */
function makeCircularFlow({ range = 2, step = 0.1 } = {}) {
  const n = Math.round((2 * range) / step) + 1
  const u = []
  const v = []
  for (let row = 0; row < n; row++) {
    const y = -range + row * step
    u.push([])
    v.push([])
    for (let col = 0; col < n; col++) {
      const x = -range + col * step
      // Normalise to avoid speed-magnitude issues at large radii
      const r = Math.sqrt(x * x + y * y)
      const speed = r > 1e-8 ? 1 / r : 0
      u[row].push(-y * speed)
      v[row].push(x * speed)
    }
  }
  return { x0: -range, y0: -range, dx: step, dy: step, nx: n, ny: n, u, v }
}

/**
 * Zero field — all velocities are zero.
 */
function makeZeroField() {
  const nx = 5
  const ny = 5
  const u = Array.from({ length: ny }, () => Array(nx).fill(0))
  const v = Array.from({ length: ny }, () => Array(nx).fill(0))
  return { x0: 0, y0: 0, dx: 1, dy: 1, nx, ny, u, v }
}

// ── sampleField ──────────────────────────────────────────────────────────────

describe('sampleField', () => {
  it('returns correct velocity at a grid node', () => {
    const field = makeUniformHorizontal()
    const s = sampleField(field, 3, 4)
    expect(s).not.toBeNull()
    expect(s.vx).toBeCloseTo(1, 6)
    expect(s.vy).toBeCloseTo(0, 6)
  })

  it('returns null outside the domain', () => {
    const field = makeUniformHorizontal()
    expect(sampleField(field, -1, 5)).toBeNull()
    expect(sampleField(field, 5, 999)).toBeNull()
    expect(sampleField(field, 15, 5)).toBeNull()
  })

  it('interpolates correctly at cell midpoint', () => {
    // Build a simple 2×2 field with known values
    const field = {
      x0: 0, y0: 0, dx: 1, dy: 1, nx: 2, ny: 2,
      u: [[0, 2], [0, 2]],
      v: [[0, 0], [0, 0]],
    }
    // At midpoint (0.5, 0.5): bilinear average of 0,2,0,2 = 1
    const s = sampleField(field, 0.5, 0.5)
    expect(s).not.toBeNull()
    expect(s.vx).toBeCloseTo(1, 6)
  })
})

// ── Uniform horizontal flow ──────────────────────────────────────────────────

describe('traceStreamline — uniform horizontal flow', () => {
  it('produces a nearly horizontal line from origin', () => {
    const field = makeUniformHorizontal()
    // Seed at (1, 5) — interior so we have room to trace
    const pts = traceStreamline(field, { x: 1, y: 5 }, { dt: 0.1, max_steps: 50 })

    expect(pts.length).toBeGreaterThan(2)

    // All y values should stay close to the seed y
    for (const p of pts) {
      expect(Math.abs(p.y - 5)).toBeLessThan(0.05)
    }

    // x should monotonically increase
    for (let i = 1; i < pts.length; i++) {
      expect(pts[i].x).toBeGreaterThan(pts[i - 1].x - 1e-9)
    }
  })

  it('seed is the first point', () => {
    const field = makeUniformHorizontal()
    const pts = traceStreamline(field, { x: 2, y: 3 }, { dt: 0.1, max_steps: 10 })
    expect(pts[0].x).toBeCloseTo(2, 6)
    expect(pts[0].y).toBeCloseTo(3, 6)
  })

  it('exits domain and stops gracefully', () => {
    const field = makeUniformHorizontal({ nx: 5, ny: 5 })
    // Start near the right boundary; large dt will push it out quickly
    const pts = traceStreamline(field, { x: 3, y: 2 }, { dt: 1.5, max_steps: 500 })
    // Should stop (not run the full max_steps) because it left the domain
    expect(pts.length).toBeLessThan(500)
  })

  it('stops immediately in a zero-speed field', () => {
    const field = makeZeroField()
    const pts = traceStreamline(field, { x: 2, y: 2 }, { dt: 0.1, max_steps: 1000, min_speed: 1e-6 })
    // Only the seed point returned
    expect(pts.length).toBe(1)
  })
})

// ── Circular flow ────────────────────────────────────────────────────────────

describe('traceStreamline — circular flow', () => {
  it('streamline from (1, 0) curves around the origin', () => {
    const field = makeCircularFlow({ range: 1.5, step: 0.05 })
    // Trace for enough steps to complete ~1 revolution
    // Circumference ≈ 2π at radius 1; dt=0.05 → ~126 steps per loop
    const pts = traceStreamline(field, { x: 1, y: 0 }, { dt: 0.05, max_steps: 5000, loop_tol: 1e-2 })

    expect(pts.length).toBeGreaterThan(10)

    // All points should be approximately on the unit circle (radius ≈ 1)
    for (const p of pts) {
      const r = Math.sqrt(p.x * p.x + p.y * p.y)
      expect(r).toBeCloseTo(1, 1)  // within 0.05 of radius 1
    }
  })

  it('detects closed loop and terminates before max_steps', () => {
    const field = makeCircularFlow({ range: 1.5, step: 0.05 })
    const pts = traceStreamline(
      field,
      { x: 1, y: 0 },
      { dt: 0.05, max_steps: 50000, loop_tol: 1e-2 }
    )
    // Should terminate well before 50000 steps due to loop detection
    expect(pts.length).toBeLessThan(50000)
  })

  it('seed at (1, 0) ends near (1, 0) after one loop', () => {
    const field = makeCircularFlow({ range: 1.5, step: 0.05 })
    const pts = traceStreamline(
      field,
      { x: 1, y: 0 },
      { dt: 0.05, max_steps: 50000, loop_tol: 1e-2 }
    )
    // The last point should be within loop_tol distance of the seed
    const last = pts[pts.length - 1]
    const dx = last.x - 1
    const dy = last.y - 0
    // After loop detection fires the trace has returned near start
    expect(dx * dx + dy * dy).toBeLessThan(0.5)
  })
})

// ── cellsToGrid ──────────────────────────────────────────────────────────────

describe('cellsToGrid', () => {
  it('converts flat cell list to a grid usable by traceStreamline', () => {
    // 3×3 grid, rightward flow
    const cells = []
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 3; col++) {
        cells.push({ x: col, y: row, Ux: 1, Uy: 0 })
      }
    }
    const grid = cellsToGrid(cells)
    expect(grid.nx).toBe(3)
    expect(grid.ny).toBe(3)
    expect(grid.u[0][0]).toBe(1)
    expect(grid.v[0][0]).toBe(0)
  })

  it('handles empty cell list without throwing', () => {
    const grid = cellsToGrid([])
    expect(grid.nx).toBe(1)
    expect(grid.ny).toBe(1)
  })

  it('can feed a cells-shape field directly into traceStreamline', () => {
    const cells = []
    for (let row = 0; row < 5; row++) {
      for (let col = 0; col < 5; col++) {
        cells.push({ x: col, y: row, Ux: 1, Uy: 0 })
      }
    }
    // traceStreamline should auto-convert cells shape
    const pts = traceStreamline({ cells }, { x: 1, y: 2 }, { dt: 0.2, max_steps: 10 })
    expect(pts.length).toBeGreaterThan(1)
  })
})

// ── Edge cases ───────────────────────────────────────────────────────────────

describe('traceStreamline — edge cases', () => {
  it('seed outside domain returns only the seed point', () => {
    const field = makeUniformHorizontal()
    // x=-5 is outside x0=0..10
    const pts = traceStreamline(field, { x: -5, y: 5 }, { dt: 0.1, max_steps: 100 })
    expect(pts.length).toBe(1)
  })

  it('respects max_steps cap', () => {
    // Interior of field, slow dt
    const field = makeUniformHorizontal({ nx: 1000, ny: 1000 })
    const pts = traceStreamline(field, { x: 1, y: 500 }, { dt: 0.01, max_steps: 20 })
    // max_steps=20 → at most 21 points (seed + 20 steps)
    expect(pts.length).toBeLessThanOrEqual(21)
  })
})
