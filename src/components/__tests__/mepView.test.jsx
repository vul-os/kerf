// mepView.test.jsx — Pure data-layer tests for MEP routing utilities.
//
// Follows the graphEditor.test.jsx convention: no React render overhead;
// all interesting logic lives in mep.js which MEPView wraps.

import { describe, it, expect } from 'vitest'
import {
  defaultMepRoute,
  validateMepRoute,
  addSegment,
  addFitting,
  addEndpoint,
  computeRouteLength,
  computePressureDrop,
  connectEndpoints,
} from '../../lib/mep.js'

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeTwoEndpointRoute(kind = 'pipe') {
  let r = defaultMepRoute(kind)
  r = addEndpoint(r, { id: 'ep_src', kind: 'source', position: [0, 0, 0] })
  r = addEndpoint(r, { id: 'ep_snk', kind: 'sink',   position: [3000, 0, 0] })
  return r
}

// ── 1. defaultMepRoute ────────────────────────────────────────────────────────

describe('defaultMepRoute', () => {
  it('returns an object with version 1', () => {
    expect(defaultMepRoute().version).toBe(1)
  })

  it('defaults to duct kind', () => {
    expect(defaultMepRoute().kind).toBe('duct')
  })

  it('accepts kind and system_name args', () => {
    const r = defaultMepRoute('pipe', 'Domestic HW')
    expect(r.kind).toBe('pipe')
    expect(r.system_name).toBe('Domestic HW')
  })

  it('returns empty segments, fittings and endpoints', () => {
    const r = defaultMepRoute()
    expect(r.segments).toHaveLength(0)
    expect(r.fittings).toHaveLength(0)
    expect(r.endpoints).toHaveLength(0)
  })

  it('passes validateMepRoute with ok: true', () => {
    const { ok } = validateMepRoute(defaultMepRoute('conduit'))
    expect(ok).toBe(true)
  })
})

// ── 2. addSegment immutability ────────────────────────────────────────────────

describe('addSegment', () => {
  it('does not mutate the original route', () => {
    const original = defaultMepRoute()
    addSegment(original, { id: 's1', from: [0,0,0], to: [1000,0,0] })
    expect(original.segments).toHaveLength(0)
  })

  it('appends the segment to the new route', () => {
    const r = addSegment(defaultMepRoute(), { id: 's1', from: [0,0,0], to: [500,0,0] })
    expect(r.segments).toHaveLength(1)
    expect(r.segments[0].id).toBe('s1')
  })

  it('defaults segment kind to straight', () => {
    const r = addSegment(defaultMepRoute(), { id: 's2', from: [0,0,0], to: [100,0,0] })
    expect(r.segments[0].kind).toBe('straight')
  })

  it('throws on duplicate segment id', () => {
    let r = addSegment(defaultMepRoute(), { id: 'dup', from: [0,0,0], to: [1,0,0] })
    expect(() => addSegment(r, { id: 'dup', from: [1,0,0], to: [2,0,0] })).toThrow()
  })
})

// ── 3. computeRouteLength ─────────────────────────────────────────────────────

describe('computeRouteLength', () => {
  it('returns 0 for empty route', () => {
    expect(computeRouteLength(defaultMepRoute())).toBe(0)
  })

  it('returns correct length for a single axis-aligned segment', () => {
    const r = addSegment(defaultMepRoute(), { id: 's1', from: [0,0,0], to: [2000,0,0] })
    expect(computeRouteLength(r)).toBeCloseTo(2000, 5)
  })

  it('sums multiple segments', () => {
    let r = defaultMepRoute()
    r = addSegment(r, { id: 'a', from: [0,0,0], to: [1000,0,0] })
    r = addSegment(r, { id: 'b', from: [1000,0,0], to: [1000,1000,0] })
    expect(computeRouteLength(r)).toBeCloseTo(2000, 5)
  })
})

// ── 4. computePressureDrop ────────────────────────────────────────────────────

describe('computePressureDrop', () => {
  it('returns 0 for conduit (electrical)', () => {
    const r = addSegment(defaultMepRoute('conduit'), { id: 's1', from: [0,0,0], to: [5000,0,0] })
    expect(computePressureDrop(r)).toBe(0)
  })

  it('returns a positive value for a pipe route with length', () => {
    let r = defaultMepRoute('pipe')
    r = addSegment(r, { id: 's1', from: [0,0,0], to: [10000,0,0] })
    expect(computePressureDrop(r)).toBeGreaterThan(0)
  })

  it('returns a positive value for a duct route', () => {
    let r = defaultMepRoute('duct')
    r = addSegment(r, { id: 's1', from: [0,0,0], to: [5000,0,0] })
    expect(computePressureDrop(r)).toBeGreaterThan(0)
  })

  it('larger duct diameter yields lower pressure drop per metre', () => {
    function pdForSize(size) {
      let r = { ...defaultMepRoute('duct'), size_mm: size }
      r = addSegment(r, { id: 's1', from: [0,0,0], to: [1000,0,0] })
      return computePressureDrop(r)
    }
    expect(pdForSize(400)).toBeLessThan(pdForSize(200))
  })
})

// ── 5. connectEndpoints ───────────────────────────────────────────────────────

describe('connectEndpoints', () => {
  it('fills segments on the returned route', () => {
    const r = makeTwoEndpointRoute('pipe')
    const { route: next } = connectEndpoints(r, 'ep_src', 'ep_snk', [])
    expect(next.segments.length).toBeGreaterThan(0)
  })

  it('does not mutate the original route', () => {
    const r = makeTwoEndpointRoute('pipe')
    connectEndpoints(r, 'ep_src', 'ep_snk', [])
    expect(r.segments).toHaveLength(0)
  })

  it('throws if start_id does not exist', () => {
    const r = makeTwoEndpointRoute()
    expect(() => connectEndpoints(r, 'bad_id', 'ep_snk', [])).toThrow()
  })

  it('all auto-generated segments have from/to arrays of length 3', () => {
    const r = makeTwoEndpointRoute()
    const { route: next } = connectEndpoints(r, 'ep_src', 'ep_snk', [])
    for (const seg of next.segments) {
      expect(Array.isArray(seg.from) && seg.from.length === 3).toBe(true)
      expect(Array.isArray(seg.to) && seg.to.length === 3).toBe(true)
    }
  })
})
