// railingView.test.jsx — Pure data-layer tests for railing geometry utilities.
//
// Follows the mepView.test.jsx convention: no React render overhead;
// all interesting logic lives in railings.js which RailingView wraps.

import { describe, it, expect } from 'vitest'
import {
  defaultRailing,
  validateRailing,
  computePostPositions,
  computeBalusterPositions,
  railingFromStair,
  railingFromSketch,
} from '../../lib/railings.js'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const simplePath = [
  { x: 0, y: 0, z: 0 },
  { x: 3000, y: 0, z: 0 },
]

const longPath = [
  { x: 0, y: 0, z: 0 },
  { x: 6000, y: 0, z: 0 },
]

// ── 1. defaultRailing ─────────────────────────────────────────────────────────

describe('defaultRailing', () => {
  it('returns version 1', () => {
    expect(defaultRailing({ path: simplePath }).version).toBe(1)
  })

  it('defaults height_mm to 1000', () => {
    expect(defaultRailing({ path: simplePath }).height_mm).toBe(1000)
  })

  it('accepts custom height_mm', () => {
    expect(defaultRailing({ path: simplePath, height_mm: 900 }).height_mm).toBe(900)
  })

  it('stores the path with correct x/y/z keys', () => {
    const r = defaultRailing({ path: simplePath })
    expect(r.path[0]).toMatchObject({ x: 0, y: 0, z: 0 })
    expect(r.path[1]).toMatchObject({ x: 3000, y: 0, z: 0 })
  })

  it('top_rail.profile defaults to round', () => {
    expect(defaultRailing({ path: simplePath }).top_rail.profile).toBe('round')
  })
})

// ── 2. validateRailing ────────────────────────────────────────────────────────

describe('validateRailing', () => {
  it('passes for a valid default railing', () => {
    const { ok } = validateRailing(defaultRailing({ path: simplePath }))
    expect(ok).toBe(true)
  })

  it('fails when path has fewer than 2 points', () => {
    const r = defaultRailing({ path: simplePath })
    const { ok, errors } = validateRailing({ ...r, path: [{ x: 0, y: 0, z: 0 }] })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('path'))).toBe(true)
  })

  it('fails when height_mm out of [600,1200]', () => {
    const { ok, errors } = validateRailing({ ...defaultRailing({ path: simplePath }), height_mm: 400 })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('height_mm'))).toBe(true)
  })

  it('fails when top_rail.profile is invalid', () => {
    const r = defaultRailing({ path: simplePath })
    const { ok, errors } = validateRailing({ ...r, top_rail: { ...r.top_rail, profile: 'oval' } })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('top_rail.profile'))).toBe(true)
  })

  it('fails when posts.spacing_mm is not a positive number', () => {
    const r = defaultRailing({ path: simplePath })
    const { ok } = validateRailing({ ...r, posts: { ...r.posts, spacing_mm: -10 } })
    expect(ok).toBe(false)
  })
})

// ── 3. computePostPositions ───────────────────────────────────────────────────

describe('computePostPositions', () => {
  it('returns empty array for path shorter than 2 points', () => {
    expect(computePostPositions([{ x: 0, y: 0, z: 0 }], 1200)).toHaveLength(0)
  })

  it('always includes start and end points', () => {
    const posts = computePostPositions(simplePath, 1200)
    const first = posts[0]
    const last = posts[posts.length - 1]
    expect(first.x).toBeCloseTo(0, 2)
    expect(last.x).toBeCloseTo(3000, 2)
  })

  it('returns at least 2 posts', () => {
    expect(computePostPositions(simplePath, 5000).length).toBeGreaterThanOrEqual(2)
  })

  it('denser spacing yields more posts', () => {
    const sparse = computePostPositions(longPath, 2000)
    const dense = computePostPositions(longPath, 500)
    expect(dense.length).toBeGreaterThan(sparse.length)
  })
})

// ── 4. computeBalusterPositions ───────────────────────────────────────────────

describe('computeBalusterPositions', () => {
  it('returns empty array for very short path', () => {
    const tinyPath = [{ x: 0, y: 0, z: 0 }, { x: 50, y: 0, z: 0 }]
    expect(computeBalusterPositions(tinyPath, 120)).toHaveLength(0)
  })

  it('does not include start or end points', () => {
    const bals = computeBalusterPositions(longPath, 120)
    if (bals.length > 0) {
      expect(bals[0].x).toBeGreaterThan(0)
      expect(bals[bals.length - 1].x).toBeLessThan(6000)
    }
  })

  it('returns more balusters for smaller spacing', () => {
    const coarse = computeBalusterPositions(longPath, 300)
    const fine = computeBalusterPositions(longPath, 100)
    expect(fine.length).toBeGreaterThan(coarse.length)
  })
})

// ── 5. railingFromSketch ──────────────────────────────────────────────────────

describe('railingFromSketch', () => {
  it('builds a railing from explicit points', () => {
    const r = railingFromSketch(simplePath)
    expect(r.path).toHaveLength(2)
  })

  it('accepts height_mm override', () => {
    const r = railingFromSketch(simplePath, { height_mm: 800 })
    expect(r.height_mm).toBe(800)
  })

  it('passes validation', () => {
    const { ok } = validateRailing(railingFromSketch(simplePath))
    expect(ok).toBe(true)
  })
})

// ── 6. railingFromStair ───────────────────────────────────────────────────────

describe('railingFromStair', () => {
  function makeStair() {
    return {
      riser_height_mm: 175,
      tread_depth_mm: 280,
      width_mm: 1000,
      flights: [
        { id: 'fl1', start_point: [0, 0, 0], direction: [1, 0, 0], step_count: 8 },
      ],
    }
  }

  it('returns a railing object for side=left', () => {
    const r = railingFromStair(makeStair(), 'left')
    expect(r).toHaveProperty('path')
    expect(r.path.length).toBeGreaterThan(1)
  })

  it('returns an array of two railings for side=both', () => {
    const result = railingFromStair(makeStair(), 'both')
    expect(Array.isArray(result)).toBe(true)
    expect(result).toHaveLength(2)
  })

  it('path length matches step_count + 1', () => {
    const r = railingFromStair(makeStair(), 'right')
    expect(r.path).toHaveLength(9) // 8 steps → 9 points
  })
})
