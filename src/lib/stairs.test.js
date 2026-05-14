import { describe, it, expect } from 'vitest'
import {
  defaultStair,
  validateStair,
  computeFlightGeometry,
  addFlight,
  addLanding,
  straightStairFromAB,
  lShapeStair,
  uShapeStair,
} from './stairs.js'

// ── defaultStair ──────────────────────────────────────────────────────────────

describe('defaultStair', () => {
  it('returns version 1', () => {
    const s = defaultStair({ total_rise_mm: 2800, total_run_mm: 3360 })
    expect(s.version).toBe(1)
  })

  it('preserves total_rise_mm and total_run_mm', () => {
    const s = defaultStair({ total_rise_mm: 2100, total_run_mm: 3000 })
    expect(s.total_rise_mm).toBe(2100)
    expect(s.total_run_mm).toBe(3000)
  })

  it('sets sensible defaults', () => {
    const s = defaultStair({ total_rise_mm: 2800, total_run_mm: 3360 })
    expect(s.tread_depth_mm).toBe(280)
    expect(s.riser_height_mm).toBe(175)
    expect(s.nosing_mm).toBe(25)
    expect(s.width_mm).toBe(1000)
    expect(s.handedness).toBe('right')
    expect(Array.isArray(s.flights)).toBe(true)
    expect(Array.isArray(s.landings)).toBe(true)
  })
})

// ── validateStair ─────────────────────────────────────────────────────────────

describe('validateStair', () => {
  function validStair() {
    return defaultStair({ total_rise_mm: 2800, total_run_mm: 3360 })
  }

  it('accepts a valid stair with 2R+T = 630', () => {
    const s = validStair()
    // 2×175 + 280 = 630 ✓
    const r = validateStair(s)
    expect(r.ok).toBe(true)
    expect(r.errors).toHaveLength(0)
  })

  it('rejects riser_height_mm below 100', () => {
    const s = { ...validStair(), riser_height_mm: 80 }
    const r = validateStair(s)
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('riser_height_mm'))).toBe(true)
  })

  it('rejects riser_height_mm above 220', () => {
    const s = { ...validStair(), riser_height_mm: 230 }
    const r = validateStair(s)
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('riser_height_mm'))).toBe(true)
  })

  it('rejects tread_depth_mm below 200', () => {
    const s = { ...validStair(), tread_depth_mm: 180 }
    const r = validateStair(s)
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('tread_depth_mm'))).toBe(true)
  })

  it('rejects tread_depth_mm above 350', () => {
    const s = { ...validStair(), tread_depth_mm: 360 }
    const r = validateStair(s)
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('tread_depth_mm'))).toBe(true)
  })

  it('rejects 2R+T below 550', () => {
    // 2×100 + 340 = 540 — riser at min, tread just in range but formula fails
    const s = { ...validStair(), riser_height_mm: 100, tread_depth_mm: 340 }
    const r = validateStair(s)
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('2R+T'))).toBe(true)
  })

  it('rejects 2R+T above 700', () => {
    // 2×220 + 280 = 720 — both in range individually but formula fails
    const s = { ...validStair(), riser_height_mm: 220, tread_depth_mm: 280 }
    const r = validateStair(s)
    expect(r.ok).toBe(false)
    expect(r.errors.some(e => e.includes('2R+T'))).toBe(true)
  })

  it('accepts boundary 2R+T = 550', () => {
    // 2×150 + 250 = 550
    const s = { ...validStair(), riser_height_mm: 150, tread_depth_mm: 250 }
    const r = validateStair(s)
    expect(r.ok).toBe(true)
  })

  it('accepts boundary 2R+T = 700', () => {
    // 2×200 + 300 = 700
    const s = { ...validStair(), riser_height_mm: 200, tread_depth_mm: 300 }
    const r = validateStair(s)
    expect(r.ok).toBe(true)
  })
})

// ── computeFlightGeometry ──────────────────────────────────────────────────────

describe('computeFlightGeometry', () => {
  const params = {
    riser_height_mm: 175,
    tread_depth_mm: 280,
    nosing_mm: 25,
    width_mm: 1000,
  }

  function makeFlight(step_count) {
    return {
      id: 'flight-1',
      start_point: [0, 0, 0],
      direction: [1, 0, 0],
      step_count,
    }
  }

  it('returns exactly step_count steps', () => {
    const steps = computeFlightGeometry(makeFlight(12), params)
    expect(steps).toHaveLength(12)
  })

  it('each step has tread and riser arrays', () => {
    const steps = computeFlightGeometry(makeFlight(5), params)
    for (const step of steps) {
      expect(Array.isArray(step.tread)).toBe(true)
      expect(Array.isArray(step.riser)).toBe(true)
      expect(step.tread).toHaveLength(4)
      expect(step.riser).toHaveLength(4)
    }
  })

  it('tread corners are 3-element arrays', () => {
    const steps = computeFlightGeometry(makeFlight(3), params)
    for (const step of steps) {
      for (const pt of step.tread) {
        expect(pt).toHaveLength(3)
      }
    }
  })

  it('first step tread z equals riser_height_mm above start', () => {
    const steps = computeFlightGeometry(makeFlight(1), params)
    const treadZ = steps[0].tread[0][2]
    expect(treadZ).toBeCloseTo(175, 5)
  })

  it('steps rise monotonically in z', () => {
    const steps = computeFlightGeometry(makeFlight(10), params)
    for (let i = 1; i < steps.length; i++) {
      expect(steps[i].tread[0][2]).toBeGreaterThan(steps[i - 1].tread[0][2])
    }
  })

  it('returns empty for step_count=0', () => {
    const steps = computeFlightGeometry(makeFlight(0), params)
    expect(steps).toHaveLength(0)
  })

  it('total z rise equals step_count × riser_height', () => {
    const steps = computeFlightGeometry(makeFlight(8), params)
    const topZ = steps[steps.length - 1].tread[0][2]
    expect(topZ).toBeCloseTo(8 * 175, 5)
  })
})

// ── addFlight / addLanding ─────────────────────────────────────────────────────

describe('addFlight / addLanding', () => {
  it('addFlight appends without mutating original', () => {
    const s = defaultStair({ total_rise_mm: 2800, total_run_mm: 3360 })
    const f = { id: 'flight-1', start_point: [0, 0, 0], direction: [1, 0, 0], step_count: 12 }
    const s2 = addFlight(s, f)
    expect(s.flights).toHaveLength(0)
    expect(s2.flights).toHaveLength(1)
  })

  it('addLanding appends without mutating original', () => {
    const s = defaultStair({ total_rise_mm: 2800, total_run_mm: 3360 })
    const l = { id: 'landing-1', position: [2000, 0, 1000], size_mm: [1200, 1000] }
    const s2 = addLanding(s, l)
    expect(s.landings).toHaveLength(0)
    expect(s2.landings).toHaveLength(1)
  })
})

// ── straightStairFromAB ────────────────────────────────────────────────────────

describe('straightStairFromAB', () => {
  it('creates exactly one flight', () => {
    const s = straightStairFromAB([0, 0, 0], [3360, 0, 2800], { riser_height_mm: 175, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000 })
    expect(s.flights).toHaveLength(1)
  })

  it('flight starts at pointA', () => {
    const s = straightStairFromAB([100, 200, 300], [3460, 200, 3100], { riser_height_mm: 175, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000 })
    expect(s.flights[0].start_point).toEqual([100, 200, 300])
  })

  it('step count derived from total_rise / riser_height', () => {
    const rise = 2800
    const riser = 175
    const s = straightStairFromAB([0, 0, 0], [3360, 0, rise], { riser_height_mm: riser, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000 })
    expect(s.flights[0].step_count).toBe(Math.round(rise / riser))
  })

  it('total_rise_mm reflects pointB - pointA z', () => {
    const s = straightStairFromAB([0, 0, 500], [3360, 0, 3300], { riser_height_mm: 175, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000 })
    expect(s.total_rise_mm).toBe(2800)
  })
})

// ── lShapeStair ────────────────────────────────────────────────────────────────

describe('lShapeStair', () => {
  const params = { riser_height_mm: 175, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000, total_rise_mm: 2100 }

  it('creates two flights', () => {
    const s = lShapeStair([0, 0, 0], 1680, 1680, [1200, 1000], params)
    expect(s.flights).toHaveLength(2)
  })

  it('creates one landing', () => {
    const s = lShapeStair([0, 0, 0], 1680, 1680, [1200, 1000], params)
    expect(s.landings).toHaveLength(1)
  })

  it('first flight starts at given start point', () => {
    const s = lShapeStair([50, 100, 200], 1680, 1680, [1200, 1000], params)
    expect(s.flights[0].start_point).toEqual([50, 100, 200])
  })

  it('flight directions are perpendicular (dot product = 0)', () => {
    const s = lShapeStair([0, 0, 0], 1680, 1680, [1200, 1000], params)
    const d1 = s.flights[0].direction
    const d2 = s.flights[1].direction
    const dot = d1[0] * d2[0] + d1[1] * d2[1] + d1[2] * d2[2]
    expect(Math.abs(dot)).toBeCloseTo(0, 10)
  })
})

// ── uShapeStair ────────────────────────────────────────────────────────────────

describe('uShapeStair', () => {
  const params = { riser_height_mm: 175, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000, total_rise_mm: 2100 }

  it('creates two flights', () => {
    const s = uShapeStair([0, 0, 0], 1680, [1200, 1000], params)
    expect(s.flights).toHaveLength(2)
  })

  it('creates one landing', () => {
    const s = uShapeStair([0, 0, 0], 1680, [1200, 1000], params)
    expect(s.landings).toHaveLength(1)
  })

  it('flights run in opposite directions (antiparallel)', () => {
    const s = uShapeStair([0, 0, 0], 1680, [1200, 1000], params)
    const d1 = s.flights[0].direction
    const d2 = s.flights[1].direction
    // d1 = [1,0,0], d2 = [-1,0,0] → dot = -1
    const dot = d1[0] * d2[0] + d1[1] * d2[1] + d1[2] * d2[2]
    expect(dot).toBeCloseTo(-1, 10)
  })

  it('second flight is offset in y by width_mm', () => {
    const s = uShapeStair([0, 0, 0], 1680, [1200, 1000], params)
    const f1y = s.flights[0].start_point[1]
    const f2y = s.flights[1].start_point[1]
    expect(f2y - f1y).toBeCloseTo(params.width_mm, 5)
  })
})
