import { describe, it, expect } from 'vitest'
import { graphOps, deferToBackend, BACKEND_OPS } from './graphOps.js'

// ── number_slider ─────────────────────────────────────────────────────────────

describe('number_slider', () => {
  it('returns numeric value', () => {
    expect(graphOps.number_slider({ value: 42 })).toBe(42)
  })

  it('coerces string to number', () => {
    expect(graphOps.number_slider({ value: '3.14' })).toBe(3.14)
  })

  it('defaults to 0 when missing', () => {
    expect(graphOps.number_slider({})).toBe(0)
  })
})

// ── integer_slider ────────────────────────────────────────────────────────────

describe('integer_slider', () => {
  it('rounds to nearest integer', () => {
    expect(graphOps.integer_slider({ value: 3.7 })).toBe(4)
    expect(graphOps.integer_slider({ value: 3.2 })).toBe(3)
  })

  it('handles exact integer', () => {
    expect(graphOps.integer_slider({ value: 10 })).toBe(10)
  })
})

// ── panel ─────────────────────────────────────────────────────────────────────

describe('panel', () => {
  it('passes through value', () => {
    expect(graphOps.panel({ value: 'hello' })).toBe('hello')
    expect(graphOps.panel({ value: [1, 2, 3] })).toEqual([1, 2, 3])
  })

  it('returns null when no value', () => {
    expect(graphOps.panel({})).toBeNull()
  })
})

// ── series ────────────────────────────────────────────────────────────────────

describe('series', () => {
  it('generates correct series', () => {
    expect(graphOps.series({ start: 0, count: 4, step: 5 })).toEqual([0, 5, 10, 15])
  })

  it('negative step counts down', () => {
    expect(graphOps.series({ start: 10, count: 3, step: -3 })).toEqual([10, 7, 4])
  })

  it('count 0 returns empty array', () => {
    expect(graphOps.series({ start: 0, count: 0, step: 1 })).toEqual([])
  })
})

// ── range ─────────────────────────────────────────────────────────────────────

describe('range', () => {
  it('generates evenly spaced values', () => {
    const r = graphOps.range({ from: 0, to: 1, count: 5 })
    expect(r).toHaveLength(5)
    expect(r[0]).toBe(0)
    expect(r[4]).toBe(1)
    expect(r[2]).toBeCloseTo(0.5)
  })

  it('min count is 2', () => {
    const r = graphOps.range({ from: 0, to: 10, count: 0 })
    expect(r).toHaveLength(2)
  })
})

// ── lerp ──────────────────────────────────────────────────────────────────────

describe('lerp', () => {
  it('interpolates midpoint', () => {
    expect(graphOps.lerp({ a: 0, b: 100, t: 0.5 })).toBe(50)
  })

  it('t=0 returns a', () => {
    expect(graphOps.lerp({ a: 10, b: 20, t: 0 })).toBe(10)
  })

  it('t=1 returns b', () => {
    expect(graphOps.lerp({ a: 10, b: 20, t: 1 })).toBe(20)
  })

  it('extrapolates beyond range', () => {
    expect(graphOps.lerp({ a: 0, b: 10, t: 1.5 })).toBe(15)
  })
})

// ── expression ────────────────────────────────────────────────────────────────

describe('expression', () => {
  it('evaluates simple math', () => {
    expect(graphOps.expression({ expr: '2 + 2', inputs: {} })).toBe(4)
  })

  it('uses named inputs', () => {
    expect(graphOps.expression({ expr: 'x * y', inputs: { x: 3, y: 7 } })).toBe(21)
  })

  it('returns error object on invalid expression', () => {
    const result = graphOps.expression({ expr: 'not valid !!', inputs: {} })
    expect(result).toMatchObject({ __error: expect.stringContaining('expression') })
  })

  it('returns null on empty expr', () => {
    expect(graphOps.expression({ expr: '' })).toBeNull()
  })
})

// ── map_each ──────────────────────────────────────────────────────────────────

describe('map_each', () => {
  it('maps a builtin op over array', () => {
    const result = graphOps.map_each({ array: [1, 2, 3], op: 'lerp', op_params: { a: 0, b: 10, t: 0.5 } })
    expect(result).toHaveLength(3)
    // All items return same lerp(0,10,0.5)=5 since t from op_params
    expect(result[0]).toBe(5)
  })

  it('emits defer marker for unknown backend op', () => {
    const result = graphOps.map_each({ array: ['x', 'y'], op: 'feature_extrude', op_params: { depth: 10 } })
    expect(result[0]).toMatchObject({ __defer_to_backend: true, op: 'feature_extrude' })
  })

  it('handles empty array', () => {
    expect(graphOps.map_each({ array: [], op: 'number_slider', op_params: {} })).toEqual([])
  })
})

// ── Backend op stubs ──────────────────────────────────────────────────────────

describe('backend op stubs', () => {
  it('feature_sweep2 emits defer marker', () => {
    const result = graphOps.feature_sweep2({ rail1: 'x', rail2: 'y' })
    expect(result).toMatchObject({ __defer_to_backend: true, op: 'feature_sweep2' })
  })

  it('sketch_offset emits defer marker', () => {
    const result = graphOps.sketch_offset({ file_id: 'abc', distance: 5 })
    expect(result).toMatchObject({ __defer_to_backend: true, op: 'sketch_offset' })
  })

  it('material.read emits defer marker', () => {
    const result = graphOps['material.read']({ name: 'Steel' })
    expect(result).toMatchObject({ __defer_to_backend: true })
  })
})
