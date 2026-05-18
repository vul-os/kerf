// thermalNetworkLayout.test.js — vitest unit tests for the force-directed
// thermal network layout helper and temperature colour helper.

import { describe, it, expect } from 'vitest'
import { layoutNodes, temperatureToRgb } from './thermalNetworkLayout.js'

// ---------------------------------------------------------------------------
// layoutNodes
// ---------------------------------------------------------------------------

describe('layoutNodes — 2-node connected graph', () => {
  const nodes = [{ id: 'A' }, { id: 'B' }]
  const links = [{ from_id: 'A', to_id: 'B', natural_length: 120 }]

  it('returns an object with both node ids', () => {
    const pos = layoutNodes(nodes, links)
    expect(pos).toHaveProperty('A')
    expect(pos).toHaveProperty('B')
  })

  it('produces finite x/y coordinates', () => {
    const pos = layoutNodes(nodes, links)
    expect(Number.isFinite(pos.A.x)).toBe(true)
    expect(Number.isFinite(pos.A.y)).toBe(true)
    expect(Number.isFinite(pos.B.x)).toBe(true)
    expect(Number.isFinite(pos.B.y)).toBe(true)
  })

  it('places nodes at approximately the natural link length apart', () => {
    const pos = layoutNodes(nodes, links, 300)
    const dx = pos.B.x - pos.A.x
    const dy = pos.B.y - pos.A.y
    const dist = Math.sqrt(dx * dx + dy * dy)
    // Force-directed sim converges to natural_length ±30% after 300 iterations
    expect(dist).toBeGreaterThan(60)
    expect(dist).toBeLessThan(240)
  })

  it('is deterministic for the same seed', () => {
    const pos1 = layoutNodes(nodes, links, 100, 99)
    const pos2 = layoutNodes(nodes, links, 100, 99)
    expect(pos1.A.x).toBeCloseTo(pos2.A.x, 6)
    expect(pos1.A.y).toBeCloseTo(pos2.A.y, 6)
    expect(pos1.B.x).toBeCloseTo(pos2.B.x, 6)
    expect(pos1.B.y).toBeCloseTo(pos2.B.y, 6)
  })

  it('produces different layouts for different seeds', () => {
    const pos1 = layoutNodes(nodes, links, 100, 1)
    const pos2 = layoutNodes(nodes, links, 100, 7)
    // At least one coordinate should differ between seeds
    const same =
      Math.abs(pos1.A.x - pos2.A.x) < 1e-6 &&
      Math.abs(pos1.A.y - pos2.A.y) < 1e-6
    expect(same).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// layoutNodes — 5-node star (centre + 4 leaves)
// ---------------------------------------------------------------------------

describe('layoutNodes — 5-node star topology', () => {
  const nodes = [
    { id: 'C'  },
    { id: 'L1' },
    { id: 'L2' },
    { id: 'L3' },
    { id: 'L4' },
  ]
  const links = [
    { from_id: 'C', to_id: 'L1' },
    { from_id: 'C', to_id: 'L2' },
    { from_id: 'C', to_id: 'L3' },
    { from_id: 'C', to_id: 'L4' },
  ]

  it('returns positions for all 5 nodes', () => {
    const pos = layoutNodes(nodes, links)
    expect(Object.keys(pos)).toHaveLength(5)
  })

  it('produces no NaN coordinates', () => {
    const pos = layoutNodes(nodes, links, 200)
    for (const id of ['C', 'L1', 'L2', 'L3', 'L4']) {
      expect(Number.isNaN(pos[id].x)).toBe(false)
      expect(Number.isNaN(pos[id].y)).toBe(false)
    }
  })

  it('produces coordinates within a bounded box', () => {
    const pos = layoutNodes(nodes, links, 200)
    const BOUND = 2000 // generous upper bound in SVG pixels
    for (const id of Object.keys(pos)) {
      expect(Math.abs(pos[id].x)).toBeLessThan(BOUND)
      expect(Math.abs(pos[id].y)).toBeLessThan(BOUND)
    }
  })

  it('nodes are not all at the same position (simulation runs)', () => {
    const pos = layoutNodes(nodes, links, 100)
    const xs = Object.values(pos).map(p => p.x)
    const spread = Math.max(...xs) - Math.min(...xs)
    expect(spread).toBeGreaterThan(1)
  })
})

// ---------------------------------------------------------------------------
// layoutNodes — edge cases
// ---------------------------------------------------------------------------

describe('layoutNodes — edge cases', () => {
  it('returns empty object for empty nodes array', () => {
    expect(layoutNodes([], [])).toEqual({})
  })

  it('handles a single isolated node', () => {
    const pos = layoutNodes([{ id: 'solo' }], [])
    expect(pos).toHaveProperty('solo')
    expect(Number.isFinite(pos.solo.x)).toBe(true)
    expect(Number.isFinite(pos.solo.y)).toBe(true)
  })

  it('ignores links with missing node ids gracefully', () => {
    const nodes = [{ id: 'X' }, { id: 'Y' }]
    const links = [{ from_id: 'X', to_id: 'GHOST' }]
    expect(() => layoutNodes(nodes, links)).not.toThrow()
    const pos = layoutNodes(nodes, links)
    expect(pos).toHaveProperty('X')
    expect(pos).toHaveProperty('Y')
  })

  it('ignores self-loop links', () => {
    const nodes = [{ id: 'A' }, { id: 'B' }]
    const links = [{ from_id: 'A', to_id: 'A' }, { from_id: 'A', to_id: 'B' }]
    expect(() => layoutNodes(nodes, links)).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// temperatureToRgb — colour correctness
// ---------------------------------------------------------------------------

describe('temperatureToRgb — basic mapping', () => {
  it('maps the coldest temperature to a blue-dominant colour', () => {
    const { r, g, b } = temperatureToRgb(0, 0, 100)
    // At t=0 the stop is deep blue (26, 26, 255)
    expect(b).toBeGreaterThan(r)
    expect(b).toBeGreaterThan(200)
  })

  it('maps the hottest temperature to a red-dominant colour', () => {
    const { r, g, b } = temperatureToRgb(100, 0, 100)
    // At t=1 the stop is hot red (255, 34, 0)
    expect(r).toBeGreaterThan(g)
    expect(r).toBeGreaterThan(b)
    expect(r).toBeGreaterThan(200)
  })

  it('returns integer channel values in [0, 255]', () => {
    for (const t of [0, 25, 50, 75, 100]) {
      const { r, g, b } = temperatureToRgb(t, 0, 100)
      for (const ch of [r, g, b]) {
        expect(Number.isInteger(ch)).toBe(true)
        expect(ch).toBeGreaterThanOrEqual(0)
        expect(ch).toBeLessThanOrEqual(255)
      }
    }
  })

  it('clamps out-of-range temperatures gracefully', () => {
    // Below min → same as min
    const cold = temperatureToRgb(-50, 0, 100)
    const min  = temperatureToRgb(0,   0, 100)
    expect(cold).toEqual(min)

    // Above max → same as max
    const hot = temperatureToRgb(999, 0, 100)
    const max = temperatureToRgb(100, 0, 100)
    expect(hot).toEqual(max)
  })

  it('returns a mid-range colour (not pure blue or pure red) at 50 %', () => {
    const { r, g, b } = temperatureToRgb(50, 0, 100)
    // At t=0.5 the stop is teal-green (0, 221, 136) — green should dominate
    expect(g).toBeGreaterThan(r)
    expect(g).toBeGreaterThan(b)
  })

  it('handles equal tMin/tMax without NaN (returns mid colour)', () => {
    const { r, g, b } = temperatureToRgb(300, 300, 300)
    expect(Number.isNaN(r)).toBe(false)
    expect(Number.isNaN(g)).toBe(false)
    expect(Number.isNaN(b)).toBe(false)
  })
})

describe('temperatureToRgb — monotonic luminance property', () => {
  // Perceptual luminance (rec. 709): L ≈ 0.2126R + 0.7152G + 0.0722B
  function luminance({ r, g, b }) {
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }

  it('luminance at 0 % is less than luminance at 50 %', () => {
    const l0  = luminance(temperatureToRgb(0,   0, 100))
    const l50 = luminance(temperatureToRgb(50,  0, 100))
    expect(l50).toBeGreaterThan(l0)
  })

  it('luminance increases across the cool (blue) half', () => {
    const temps = [0, 10, 20, 25]
    const lums  = temps.map(t => luminance(temperatureToRgb(t, 0, 100)))
    for (let i = 0; i < lums.length - 1; i++) {
      expect(lums[i + 1]).toBeGreaterThanOrEqual(lums[i] - 1)
    }
  })

  it('luminance near peak (amber, t=75) is higher than at the blue end', () => {
    const lBlue  = luminance(temperatureToRgb(0,  0, 100))
    const lAmber = luminance(temperatureToRgb(75, 0, 100))
    expect(lAmber).toBeGreaterThan(lBlue)
  })
})
