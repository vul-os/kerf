import { describe, it, expect } from 'vitest'
import {
  defaultRailing,
  validateRailing,
  computePostPositions,
  computeBalusterPositions,
  railingFromStair,
  railingFromSketch,
} from './railings.js'
import { straightStairFromAB, lShapeStair } from './stairs.js'

// ── helpers ────────────────────────────────────────────────────────────────────

function makePath(n = 3) {
  return Array.from({ length: n }, (_, i) => ({ x: i * 500, y: 0, z: 0 }))
}

// ── defaultRailing ─────────────────────────────────────────────────────────────

describe('defaultRailing', () => {
  it('returns version 1', () => {
    const r = defaultRailing({ path: makePath() })
    expect(r.version).toBe(1)
  })

  it('stores path', () => {
    const path = makePath(4)
    const r = defaultRailing({ path })
    expect(r.path).toHaveLength(4)
  })

  it('uses provided height_mm', () => {
    const r = defaultRailing({ path: makePath(), height_mm: 900 })
    expect(r.height_mm).toBe(900)
  })

  it('defaults to height_mm=1000', () => {
    const r = defaultRailing({ path: makePath() })
    expect(r.height_mm).toBe(1000)
  })

  it('has top_rail with round profile', () => {
    const r = defaultRailing({ path: makePath() })
    expect(r.top_rail.profile).toBe('round')
    expect(r.top_rail.size_mm).toBe(50)
  })

  it('has posts and balusters sub-objects', () => {
    const r = defaultRailing({ path: makePath() })
    expect(r.posts).toBeDefined()
    expect(r.balusters).toBeDefined()
    expect(r.posts.spacing_mm).toBe(1200)
    expect(r.balusters.spacing_mm).toBe(120)
  })
})

// ── validateRailing ────────────────────────────────────────────────────────────

describe('validateRailing', () => {
  function validRailing() {
    return defaultRailing({ path: makePath() })
  }

  it('accepts a valid railing', () => {
    const r = validateRailing(validRailing())
    expect(r.ok).toBe(true)
    expect(r.errors).toHaveLength(0)
  })

  it('rejects path with fewer than 2 points', () => {
    const r = validateRailing({ ...validRailing(), path: [{ x: 0, y: 0, z: 0 }] })
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('path'))).toBe(true)
  })

  it('rejects height_mm below 600', () => {
    const r = validateRailing({ ...validRailing(), height_mm: 500 })
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('height_mm'))).toBe(true)
  })

  it('rejects height_mm above 1200', () => {
    const r = validateRailing({ ...validRailing(), height_mm: 1500 })
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('height_mm'))).toBe(true)
  })

  it('rejects invalid top_rail profile', () => {
    const rail = { ...validRailing(), top_rail: { ...validRailing().top_rail, profile: 'oval' } }
    const r = validateRailing(rail)
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('top_rail.profile'))).toBe(true)
  })
})

// ── computePostPositions ───────────────────────────────────────────────────────

describe('computePostPositions', () => {
  it('returns at least 2 posts for any valid path', () => {
    const path = [{ x: 0, y: 0, z: 0 }, { x: 1000, y: 0, z: 0 }]
    const posts = computePostPositions(path, 1200)
    expect(posts.length).toBeGreaterThanOrEqual(2)
  })

  it('first post is at path start', () => {
    const path = [{ x: 100, y: 200, z: 300 }, { x: 1100, y: 200, z: 300 }]
    const posts = computePostPositions(path, 1200)
    expect(posts[0].x).toBeCloseTo(100, 4)
    expect(posts[0].y).toBeCloseTo(200, 4)
    expect(posts[0].z).toBeCloseTo(300, 4)
  })

  it('last post is at path end', () => {
    const path = [{ x: 0, y: 0, z: 0 }, { x: 2400, y: 0, z: 0 }]
    const posts = computePostPositions(path, 1200)
    const last = posts[posts.length - 1]
    expect(last.x).toBeCloseTo(2400, 3)
  })

  it('spacing between posts does not exceed post_spacing', () => {
    const path = [{ x: 0, y: 0, z: 0 }, { x: 5000, y: 0, z: 0 }]
    const posts = computePostPositions(path, 1200)
    for (let i = 1; i < posts.length; i++) {
      const dx = posts[i].x - posts[i - 1].x
      const dist = Math.sqrt(dx * dx)
      expect(dist).toBeLessThanOrEqual(1200 + 1)
    }
  })

  it('returns [] for empty path', () => {
    expect(computePostPositions([], 1200)).toEqual([])
  })
})

// ── computeBalusterPositions ───────────────────────────────────────────────────

describe('computeBalusterPositions', () => {
  it('returns positions between endpoints', () => {
    const path = [{ x: 0, y: 0, z: 0 }, { x: 1000, y: 0, z: 0 }]
    const bals = computeBalusterPositions(path, 120)
    expect(bals.length).toBeGreaterThan(0)
    for (const b of bals) {
      expect(b.x).toBeGreaterThan(0)
      expect(b.x).toBeLessThan(1000)
    }
  })

  it('returns [] for path shorter than one spacing interval', () => {
    const path = [{ x: 0, y: 0, z: 0 }, { x: 50, y: 0, z: 0 }]
    const bals = computeBalusterPositions(path, 120)
    expect(bals).toHaveLength(0)
  })
})

// ── railingFromStair ───────────────────────────────────────────────────────────

describe('railingFromStair', () => {
  const stairParams = { riser_height_mm: 175, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000 }

  it('returns a railing doc for side=right', () => {
    const stair = straightStairFromAB([0, 0, 0], [3360, 0, 2800], stairParams)
    const rail = railingFromStair(stair, 'right')
    expect(rail.version).toBe(1)
    expect(Array.isArray(rail.path)).toBe(true)
    expect(rail.path.length).toBeGreaterThan(0)
  })

  it('returns a railing doc for side=left', () => {
    const stair = straightStairFromAB([0, 0, 0], [3360, 0, 2800], stairParams)
    const rail = railingFromStair(stair, 'left')
    expect(rail.version).toBe(1)
  })

  it('returns two railings for side=both', () => {
    const stair = straightStairFromAB([0, 0, 0], [3360, 0, 2800], stairParams)
    const rails = railingFromStair(stair, 'both')
    expect(Array.isArray(rails)).toBe(true)
    expect(rails).toHaveLength(2)
  })

  it('railing path length matches flight step count + 1', () => {
    const stair = straightStairFromAB([0, 0, 0], [3360, 0, 2800], stairParams)
    const rail = railingFromStair(stair, 'left')
    const stepCount = stair.flights[0].step_count
    expect(rail.path).toHaveLength(stepCount + 1)
  })

  it('works for L-shaped stair', () => {
    const params = { riser_height_mm: 175, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000, total_rise_mm: 2100 }
    const stair = lShapeStair([0, 0, 0], 1680, 1680, [1200, 1000], params)
    const rail = railingFromStair(stair, 'left')
    expect(Array.isArray(rail.path)).toBe(true)
    expect(rail.path.length).toBeGreaterThan(2)
  })
})

// ── railingFromSketch ──────────────────────────────────────────────────────────

describe('railingFromSketch', () => {
  it('builds a railing from sketch points', () => {
    const pts = [{ x: 0, y: 0, z: 0 }, { x: 500, y: 0, z: 500 }, { x: 1000, y: 0, z: 1000 }]
    const r = railingFromSketch(pts, { height_mm: 900 })
    expect(r.version).toBe(1)
    expect(r.path).toHaveLength(3)
    expect(r.height_mm).toBe(900)
  })
})
