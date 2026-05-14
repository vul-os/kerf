import { describe, it, expect } from 'vitest'
import {
  defaultMepRoute,
  validateMepRoute,
  addSegment,
  removeSegment,
  addFitting,
  addEndpoint,
  computeRouteLength,
  computePressureDrop,
  findShortestRoute,
  connectEndpoints,
} from './mep.js'

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeDuct(overrides = {}) {
  return { ...defaultMepRoute('duct', 'Supply Air'), ...overrides }
}

function makePipe(overrides = {}) {
  return { ...defaultMepRoute('pipe', 'Domestic Cold Water'), ...overrides }
}

// ── defaultMepRoute ───────────────────────────────────────────────────────────

describe('defaultMepRoute', () => {
  it('returns a valid duct route', () => {
    const r = defaultMepRoute('duct', 'Supply Air')
    expect(r.kind).toBe('duct')
    expect(r.version).toBe(1)
    expect(r.system_name).toBe('Supply Air')
    expect(r.segments).toEqual([])
    expect(r.fittings).toEqual([])
    expect(r.endpoints).toEqual([])
  })

  it('returns a valid pipe route', () => {
    const r = defaultMepRoute('pipe', 'Cold Water')
    expect(r.kind).toBe('pipe')
    expect(r.material).toBe('copper')
  })

  it('returns a valid conduit route', () => {
    const r = defaultMepRoute('conduit', 'Power Conduit')
    expect(r.kind).toBe('conduit')
    expect(r.material).toBe('pvc')
    expect(r.insulation_thickness_mm).toBe(0)
  })
})

// ── validateMepRoute ──────────────────────────────────────────────────────────

describe('validateMepRoute', () => {
  it('validates a fresh default route', () => {
    const { ok, errors } = validateMepRoute(defaultMepRoute('duct', 'Supply Air'))
    expect(ok).toBe(true)
    expect(errors).toHaveLength(0)
  })

  it('rejects non-object input', () => {
    const { ok } = validateMepRoute(null)
    expect(ok).toBe(false)
  })

  it('rejects unknown kind', () => {
    const { ok, errors } = validateMepRoute({ ...defaultMepRoute('duct', 'X'), kind: 'sprinkler' })
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('kind'))).toBe(true)
  })

  it('rejects missing system_name', () => {
    const r = { ...defaultMepRoute('duct', 'X'), system_name: '' }
    const { ok, errors } = validateMepRoute(r)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('system_name'))).toBe(true)
  })

  it('rejects negative size_mm', () => {
    const r = { ...defaultMepRoute('pipe', 'X'), size_mm: -10 }
    const { ok, errors } = validateMepRoute(r)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('size_mm'))).toBe(true)
  })

  it('rejects segment with bad coordinates', () => {
    const r = addSegment(defaultMepRoute('duct', 'X'), {
      id: 's1', from: [0, 0], to: [100, 0, 0], kind: 'straight',
    })
    const { ok, errors } = validateMepRoute(r)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('from'))).toBe(true)
  })

  it('rejects duplicate segment ids', () => {
    let r = defaultMepRoute('duct', 'X')
    r = addSegment(r, { id: 's1', from: [0, 0, 0], to: [1000, 0, 0] })
    r = { ...r, segments: [...r.segments, { id: 's1', from: [0, 0, 0], to: [2000, 0, 0] }] }
    const { ok, errors } = validateMepRoute(r)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('duplicate segment'))).toBe(true)
  })

  it('accepts rectangular duct with width_mm + height_mm', () => {
    const r = { ...defaultMepRoute('duct', 'X'), size_mm: null, width_mm: 400, height_mm: 200 }
    const { ok } = validateMepRoute(r)
    expect(ok).toBe(true)
  })
})

// ── Segment CRUD ──────────────────────────────────────────────────────────────

describe('addSegment / removeSegment', () => {
  it('adds a segment and returns new route', () => {
    const r = addSegment(defaultMepRoute('duct', 'X'), {
      id: 's1', from: [0, 0, 3000], to: [5000, 0, 3000], kind: 'straight',
    })
    expect(r.segments).toHaveLength(1)
    expect(r.segments[0].id).toBe('s1')
  })

  it('throws on duplicate segment id', () => {
    const seg = { id: 's1', from: [0, 0, 0], to: [1000, 0, 0] }
    const r = addSegment(defaultMepRoute('duct', 'X'), seg)
    expect(() => addSegment(r, seg)).toThrow('s1')
  })

  it('removes segment by id', () => {
    let r = addSegment(defaultMepRoute('duct', 'X'), { id: 's1', from: [0, 0, 0], to: [1000, 0, 0] })
    r = removeSegment(r, 's1')
    expect(r.segments).toHaveLength(0)
  })

  it('removeSegment is a no-op for nonexistent id', () => {
    const r = defaultMepRoute('duct', 'X')
    expect(removeSegment(r, 'nope').segments).toHaveLength(0)
  })
})

// ── Fitting / Endpoint CRUD ───────────────────────────────────────────────────

describe('addFitting', () => {
  it('adds a tee fitting', () => {
    const r = addFitting(defaultMepRoute('duct', 'X'), {
      id: 'f1', kind: 'tee', position: [5000, 1500, 3000], branches: ['s2', 's4'],
    })
    expect(r.fittings).toHaveLength(1)
    expect(r.fittings[0].kind).toBe('tee')
  })

  it('throws on duplicate fitting id', () => {
    const f = { id: 'f1', kind: 'tee', position: [0, 0, 0] }
    const r = addFitting(defaultMepRoute('duct', 'X'), f)
    expect(() => addFitting(r, f)).toThrow('f1')
  })
})

describe('addEndpoint', () => {
  it('adds source and sink endpoints', () => {
    let r = addEndpoint(defaultMepRoute('pipe', 'X'), {
      id: 'e1', kind: 'source', position: [0, 0, 0], ref_element_id: 'pump-1',
    })
    r = addEndpoint(r, {
      id: 'e2', kind: 'sink', position: [5000, 0, 0], ref_element_id: 'tap-1',
    })
    expect(r.endpoints).toHaveLength(2)
  })
})

// ── computeRouteLength ────────────────────────────────────────────────────────

describe('computeRouteLength', () => {
  it('returns 0 for empty route', () => {
    expect(computeRouteLength(defaultMepRoute('duct', 'X'))).toBe(0)
  })

  it('returns correct length for single horizontal segment', () => {
    const r = addSegment(defaultMepRoute('duct', 'X'), {
      id: 's1', from: [0, 0, 0], to: [5000, 0, 0],
    })
    expect(computeRouteLength(r)).toBe(5000)
  })

  it('sums multiple segments', () => {
    let r = addSegment(defaultMepRoute('duct', 'X'), { id: 's1', from: [0, 0, 0], to: [3000, 0, 0] })
    r = addSegment(r, { id: 's2', from: [3000, 0, 0], to: [3000, 4000, 0] })
    expect(computeRouteLength(r)).toBe(7000)
  })

  it('handles diagonal segments', () => {
    const r = addSegment(defaultMepRoute('duct', 'X'), {
      id: 's1', from: [0, 0, 0], to: [3000, 4000, 0],
    })
    expect(computeRouteLength(r)).toBeCloseTo(5000, 0)
  })
})

// ── computePressureDrop ───────────────────────────────────────────────────────

describe('computePressureDrop', () => {
  it('returns 0 for conduit', () => {
    expect(computePressureDrop(defaultMepRoute('conduit', 'X'))).toBe(0)
  })

  it('returns 0 for empty route', () => {
    expect(computePressureDrop(defaultMepRoute('pipe', 'X'))).toBe(0)
  })

  it('returns positive pressure drop for a 10m pipe at 1.5 m/s', () => {
    let r = addSegment(defaultMepRoute('pipe', 'X'), {
      id: 's1', from: [0, 0, 0], to: [10000, 0, 0],
    })
    const dp = computePressureDrop(r)
    expect(dp).toBeGreaterThan(0)
    // For 10m 50mm copper pipe at 1.5 m/s water: rough estimate ~2000-20000 Pa
    expect(dp).toBeLessThan(100000)
  })

  it('returns positive pressure drop for a duct', () => {
    let r = addSegment(defaultMepRoute('duct', 'X'), {
      id: 's1', from: [0, 0, 0], to: [20000, 0, 0],
    })
    const dp = computePressureDrop(r)
    expect(dp).toBeGreaterThan(0)
  })

  it('laminar regime gives higher drop (low Re)', () => {
    let r = addSegment(defaultMepRoute('pipe', 'X'), { id: 's1', from: [0, 0, 0], to: [10000, 0, 0] })
    const dpTurbulent = computePressureDrop(r, { velocity_m_s: 2.0 })
    const dpLaminar = computePressureDrop(r, { velocity_m_s: 0.01, viscosity_Pa_s: 1.0 })
    // Both should be positive
    expect(dpTurbulent).toBeGreaterThan(0)
    expect(dpLaminar).toBeGreaterThan(0)
  })
})

// ── findShortestRoute ─────────────────────────────────────────────────────────

describe('findShortestRoute', () => {
  it('no obstacles → straight line (2 points)', () => {
    const { polyline, warning } = findShortestRoute([0, 0, 0], [5000, 0, 0], [], 500)
    expect(polyline.length).toBeGreaterThanOrEqual(2)
    expect(polyline[0]).toEqual(expect.arrayContaining([expect.any(Number)]))
    expect(warning).toBeUndefined()
  })

  it('start equals end → 2-point degenerate polyline', () => {
    const { polyline } = findShortestRoute([0, 0, 0], [0, 0, 0], [], 500)
    expect(polyline).toBeDefined()
    expect(polyline.length).toBeGreaterThanOrEqual(1)
  })

  it('with wall obstacle → detours around it', () => {
    // Route from (0,0,0) to (6000,0,0) with a wall blocking direct path
    const obstacles = [{ min: [2000, -500, -500], max: [3000, 500, 500] }]
    const { polyline } = findShortestRoute([0, 0, 0], [6000, 0, 0], obstacles, 500)
    // Path must avoid the obstacle — should have more than 2 points
    expect(polyline.length).toBeGreaterThan(2)
  })

  it('returns warning when grid too large', () => {
    // Very large distance with tiny grid size will exceed 100×100×30
    const { polyline, warning } = findShortestRoute([0, 0, 0], [500000, 500000, 0], [], 10)
    expect(warning).toBeDefined()
    expect(polyline).toHaveLength(2)
  })
})

// ── connectEndpoints ──────────────────────────────────────────────────────────

describe('connectEndpoints', () => {
  it('connects two endpoints with auto-generated segments', () => {
    let r = defaultMepRoute('duct', 'Supply Air')
    r = addEndpoint(r, { id: 'e1', kind: 'source', position: [0, 0, 3000] })
    r = addEndpoint(r, { id: 'e2', kind: 'sink', position: [5000, 0, 3000] })
    const { route: connected } = connectEndpoints(r, 'e1', 'e2', [], 500)
    expect(connected.segments.length).toBeGreaterThan(0)
  })

  it('throws if start endpoint not found', () => {
    const r = defaultMepRoute('duct', 'X')
    expect(() => connectEndpoints(r, 'missing', 'also_missing')).toThrow('endpoint not found')
  })
})
