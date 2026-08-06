// stairView.test.jsx — Pure data-layer tests for stair geometry utilities.
//
// Follows the mepView.test.jsx convention: no React render overhead;
// all interesting logic lives in stairs.js which StairView wraps.

import { describe, it, expect } from 'vitest'
import {
  defaultStair,
  validateStair,
  addFlight,
  addLanding,
  computeFlightGeometry,
  straightStairFromAB,
  lShapeStair,
  uShapeStair,
} from '../../lib/stairs.js'

// ── 1. defaultStair ───────────────────────────────────────────────────────────

describe('defaultStair', () => {
  it('returns version 1', () => {
    expect(defaultStair({ total_rise_mm: 2800, total_run_mm: 4200 }).version).toBe(1)
  })

  it('stores total_rise_mm and total_run_mm', () => {
    const s = defaultStair({ total_rise_mm: 3000, total_run_mm: 5000 })
    expect(s.total_rise_mm).toBe(3000)
    expect(s.total_run_mm).toBe(5000)
  })

  it('defaults tread_depth_mm to 280', () => {
    expect(defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 }).tread_depth_mm).toBe(280)
  })

  it('defaults riser_height_mm to 175', () => {
    expect(defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 }).riser_height_mm).toBe(175)
  })

  it('has empty flights and landings arrays', () => {
    const s = defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 })
    expect(s.flights).toHaveLength(0)
    expect(s.landings).toHaveLength(0)
  })
})

// ── 2. validateStair ──────────────────────────────────────────────────────────

describe('validateStair', () => {
  it('passes for a default stair with 2R+T in range', () => {
    // default: 2*175+280 = 630 — in [550,700]
    const { ok } = validateStair(defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 }))
    expect(ok).toBe(true)
  })

  it('fails when riser_height_mm out of [100,220]', () => {
    const { ok, errors } = validateStair({ ...defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 }), riser_height_mm: 250 })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('riser_height_mm'))).toBe(true)
  })

  it('fails when 2R+T out of [550,700]', () => {
    // riser=200, tread=200 → 2*200+200=600 — OK. Try riser=220, tread=350 → 790
    const { ok, errors } = validateStair({ ...defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 }), riser_height_mm: 220, tread_depth_mm: 350 })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('2R+T'))).toBe(true)
  })

  it('fails when flights is not an array', () => {
    const { ok, errors } = validateStair({ ...defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 }), flights: null })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('flights'))).toBe(true)
  })
})

// ── 3. addFlight immutability ─────────────────────────────────────────────────

describe('addFlight', () => {
  it('does not mutate the original stair', () => {
    const original = defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 })
    addFlight(original, { id: 'fl1', start_point: [0, 0, 0], direction: [1, 0, 0], step_count: 8 })
    expect(original.flights).toHaveLength(0)
  })

  it('appends flight to the new stair', () => {
    const s = addFlight(defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 }), { id: 'fl1', start_point: [0, 0, 0], direction: [1, 0, 0], step_count: 8 })
    expect(s.flights).toHaveLength(1)
    expect(s.flights[0].id).toBe('fl1')
  })
})

// ── 4. addLanding ─────────────────────────────────────────────────────────────

describe('addLanding', () => {
  it('appends landing without mutating original', () => {
    const original = defaultStair({ total_rise_mm: 2800, total_run_mm: 4000 })
    const next = addLanding(original, { id: 'ld1', position: [2000, 0, 1400], size_mm: [1000, 1000] })
    expect(original.landings).toHaveLength(0)
    expect(next.landings).toHaveLength(1)
    expect(next.landings[0].id).toBe('ld1')
  })
})

// ── 5. computeFlightGeometry ──────────────────────────────────────────────────

describe('computeFlightGeometry', () => {
  const flight = { id: 'fl1', start_point: [0, 0, 0], direction: [1, 0, 0], step_count: 4 }
  const params = { riser_height_mm: 175, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000 }

  it('returns one entry per step', () => {
    expect(computeFlightGeometry(flight, params)).toHaveLength(4)
  })

  it('each step has tread and riser arrays', () => {
    const steps = computeFlightGeometry(flight, params)
    expect(Array.isArray(steps[0].tread)).toBe(true)
    expect(Array.isArray(steps[0].riser)).toBe(true)
  })

  it('tread corners are at correct z height', () => {
    const steps = computeFlightGeometry(flight, params)
    // Step 0 tread z = 0 + riser_height_mm = 175
    expect(steps[0].tread[0][2]).toBeCloseTo(175, 3)
  })

  it('each step rises by riser_height_mm', () => {
    const steps = computeFlightGeometry(flight, params)
    const z0 = steps[0].tread[0][2]
    const z1 = steps[1].tread[0][2]
    expect(z1 - z0).toBeCloseTo(175, 3)
  })
})

// ── 6. straightStairFromAB ────────────────────────────────────────────────────

describe('straightStairFromAB', () => {
  it('creates a stair with one flight', () => {
    const s = straightStairFromAB([0, 0, 0], [4200, 0, 2800], { riser_height_mm: 175, tread_depth_mm: 280, nosing_mm: 25, width_mm: 1000 })
    expect(s.flights).toHaveLength(1)
  })

  it('computes correct total_rise_mm', () => {
    const s = straightStairFromAB([0, 0, 0], [4200, 0, 2800], { riser_height_mm: 175 })
    expect(s.total_rise_mm).toBeCloseTo(2800, 3)
  })
})

// ── 7. lShapeStair ────────────────────────────────────────────────────────────

describe('lShapeStair', () => {
  it('creates two flights and one landing', () => {
    const s = lShapeStair([0, 0, 0], 2100, 2100, [1000, 1000], { riser_height_mm: 175, total_rise_mm: 2800 })
    expect(s.flights).toHaveLength(2)
    expect(s.landings).toHaveLength(1)
  })

  it('first flight runs along +x', () => {
    const s = lShapeStair([0, 0, 0], 2100, 2100, [1000, 1000], { riser_height_mm: 175, total_rise_mm: 2800 })
    expect(s.flights[0].direction[0]).toBeCloseTo(1, 3)
  })
})

// ── 8. uShapeStair ────────────────────────────────────────────────────────────

describe('uShapeStair', () => {
  it('creates two flights and one landing', () => {
    const s = uShapeStair([0, 0, 0], 2800, [1000, 1000], { riser_height_mm: 175, total_rise_mm: 2800 })
    expect(s.flights).toHaveLength(2)
    expect(s.landings).toHaveLength(1)
  })

  it('second flight runs in opposite x direction', () => {
    const s = uShapeStair([0, 0, 0], 2800, [1000, 1000], { riser_height_mm: 175, total_rise_mm: 2800 })
    expect(s.flights[1].direction[0]).toBeCloseTo(-1, 3)
  })
})
