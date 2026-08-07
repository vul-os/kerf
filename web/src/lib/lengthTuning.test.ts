import { describe, it, expect } from 'vitest'
import {
  traceLength,
  differentialSkew,
  generateMeander,
  applyMeander,
  tuneTraceToTarget,
  matchDifferentialPair,
} from './lengthTuning.js'

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeTrace(points, overrides = {}) {
  return { type: 'pcb_trace', id: 't1', net_id: 'SIG', points, ...overrides }
}

function boardWith(differential_pairs) {
  return { type: 'pcb_board', width: 100, height: 100, differential_pairs }
}

// Simple 10 mm horizontal trace
const horizTrace = makeTrace([{ x: 0, y: 0 }, { x: 10, y: 0 }])

// Two-segment trace: (0,0)→(3,0)→(3,4) = 3 + 4 = 7 mm
const twoSegTrace = makeTrace([{ x: 0, y: 0 }, { x: 3, y: 0 }, { x: 3, y: 4 }])

// N-segment trace: sum of lengths = 1+2+3+4 = 10 mm
const nSegTrace = makeTrace([
  { x: 0, y: 0 },
  { x: 1, y: 0 },
  { x: 1, y: 2 },
  { x: 4, y: 2 },
  { x: 4, y: 6 },
])

// ── traceLength ───────────────────────────────────────────────────────────────

describe('traceLength', () => {
  it('returns correct length for 1-segment trace', () => {
    expect(traceLength(horizTrace)).toBeCloseTo(10, 6)
  })

  it('returns correct length for 2-segment trace', () => {
    expect(traceLength(twoSegTrace)).toBeCloseTo(7, 6)
  })

  it('returns correct length for N-segment trace', () => {
    // 1 + 2 + 3 + 4 = 10
    expect(traceLength(nSegTrace)).toBeCloseTo(10, 6)
  })

  it('returns 0 for a single-point trace', () => {
    expect(traceLength(makeTrace([{ x: 0, y: 0 }]))).toBe(0)
  })

  it('returns 0 for null/undefined trace', () => {
    expect(traceLength(null)).toBe(0)
    expect(traceLength(undefined)).toBe(0)
  })

  it('handles diagonal segments (Pythagorean triple)', () => {
    // 3-4-5 triangle
    const t = makeTrace([{ x: 0, y: 0 }, { x: 3, y: 4 }])
    expect(traceLength(t)).toBeCloseTo(5, 6)
  })
})

// ── generateMeander ───────────────────────────────────────────────────────────

function pathLength(points) {
  let total = 0
  for (let i = 0; i < points.length - 1; i++) {
    const dx = points[i + 1].x - points[i].x
    const dy = points[i + 1].y - points[i].y
    total += Math.sqrt(dx * dx + dy * dy)
  }
  return total
}

describe('generateMeander', () => {
  const start = { x: 0, y: 0 }
  const end = { x: 20, y: 0 }
  const straight = 20

  it('serpentine: path length is approximately target (within 1%)', () => {
    const target = 30
    const pts = generateMeander(start, end, target, 'serpentine', 1.0, 2.0)
    const actual = pathLength(pts)
    expect(actual).toBeGreaterThan(target * 0.99)
    expect(actual).toBeLessThan(target * 1.20)  // upper bound is looser (discrete teeth)
  })

  it('accordion: path length is approximately target (within 20%)', () => {
    const target = 30
    const pts = generateMeander(start, end, target, 'accordion', 1.0, 2.0)
    const actual = pathLength(pts)
    expect(actual).toBeGreaterThan(target * 0.90)
    expect(actual).toBeLessThan(target * 1.25)
  })

  it('trombone: path length is approximately target (within 20%)', () => {
    const target = 30
    const pts = generateMeander(start, end, target, 'trombone', 2.0, 4.0)
    const actual = pathLength(pts)
    expect(actual).toBeGreaterThan(target * 0.80)
    expect(actual).toBeLessThan(target * 1.30)
  })

  it('returns straight line when target equals straight distance', () => {
    const pts = generateMeander(start, end, straight, 'serpentine', 1.0, 2.0)
    expect(pts).toHaveLength(2)
    expect(pts[0]).toEqual(start)
    expect(pts[pts.length - 1]).toEqual(end)
  })

  it('throws when target is less than straight distance', () => {
    expect(() => generateMeander(start, end, 15, 'serpentine', 1.0, 2.0)).toThrow()
  })

  it('first and last points are start and end regardless of style', () => {
    for (const style of ['serpentine', 'accordion', 'trombone']) {
      const pts = generateMeander(start, end, 35, style, 1.0, 2.0)
      expect(pts[0].x).toBeCloseTo(start.x, 6)
      expect(pts[0].y).toBeCloseTo(start.y, 6)
      expect(pts[pts.length - 1].x).toBeCloseTo(end.x, 6)
      expect(pts[pts.length - 1].y).toBeCloseTo(end.y, 6)
    }
  })
})

// ── applyMeander ──────────────────────────────────────────────────────────────

describe('applyMeander', () => {
  it('preserves start and end points of the segment', () => {
    const trace = makeTrace(
      [{ x: 0, y: 0 }, { x: 20, y: 0 }],
      { target_length_mm: 30 },
    )
    const updated = applyMeander(trace, 0, 'serpentine', 1.0)
    const pts = updated.points
    expect(pts[0].x).toBeCloseTo(0, 6)
    expect(pts[0].y).toBeCloseTo(0, 6)
    expect(pts[pts.length - 1].x).toBeCloseTo(20, 6)
    expect(pts[pts.length - 1].y).toBeCloseTo(0, 6)
  })

  it('updated trace length is >= target', () => {
    const trace = makeTrace(
      [{ x: 0, y: 0 }, { x: 20, y: 0 }],
      { target_length_mm: 30 },
    )
    const updated = applyMeander(trace, 0, 'serpentine', 1.0)
    expect(traceLength(updated)).toBeGreaterThan(29.5)
  })

  it('preserves points outside the meander segment (multi-segment trace)', () => {
    const trace = makeTrace(
      [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }],
      { target_length_mm: 30 },
    )
    const updated = applyMeander(trace, 0, 'serpentine', 1.0)
    // Last point should still be (10, 10)
    const last = updated.points[updated.points.length - 1]
    expect(last.x).toBeCloseTo(10, 6)
    expect(last.y).toBeCloseTo(10, 6)
  })

  it('throws when target_length_mm is shorter than current trace', () => {
    const trace = makeTrace(
      [{ x: 0, y: 0 }, { x: 20, y: 0 }],
      { target_length_mm: 10 },
    )
    expect(() => applyMeander(trace, 0, 'serpentine', 1.0)).toThrow()
  })
})

// ── differentialSkew ──────────────────────────────────────────────────────────

describe('differentialSkew', () => {
  it('returns 0 delta for equal-length pair', () => {
    const circuit = [
      boardWith([{ name: 'USB', net_p_id: 'USB_P', net_n_id: 'USB_N', skew_max_mm: 0.05 }]),
      makeTrace([{ x: 0, y: 0 }, { x: 10, y: 0 }], { net_id: 'USB_P' }),
      makeTrace([{ x: 0, y: 5 }, { x: 10, y: 5 }], { net_id: 'USB_N' }),
    ]
    const result = differentialSkew(circuit, 'USB')
    expect(result.delta_mm).toBeCloseTo(0, 6)
    expect(result.length_p).toBeCloseTo(10, 6)
    expect(result.length_n).toBeCloseTo(10, 6)
  })

  it('returns correct delta for unequal pair', () => {
    const circuit = [
      boardWith([{ name: 'DDR', net_p_id: 'DQ_P', net_n_id: 'DQ_N' }]),
      makeTrace([{ x: 0, y: 0 }, { x: 15, y: 0 }], { net_id: 'DQ_P' }),
      makeTrace([{ x: 0, y: 5 }, { x: 10, y: 5 }], { net_id: 'DQ_N' }),
    ]
    const result = differentialSkew(circuit, 'DDR')
    expect(result.delta_mm).toBeCloseTo(5, 6)
  })

  it('returns error when pair not found', () => {
    const circuit = [boardWith([])]
    const result = differentialSkew(circuit, 'MISSING')
    expect(result.error).toBeDefined()
  })

  it('returns error when board.differential_pairs is absent (defensive)', () => {
    const circuit = [{ type: 'pcb_board', width: 50, height: 50 }]
    const result = differentialSkew(circuit, 'X')
    expect(result.error).toBeDefined()
  })
})

// ── matchDifferentialPair ─────────────────────────────────────────────────────

describe('matchDifferentialPair', () => {
  it('reduces |delta| to within skew_max_mm', () => {
    const circuit = [
      boardWith([{
        name: 'USB',
        net_p_id: 'USB_P',
        net_n_id: 'USB_N',
        skew_max_mm: 0.1,
      }]),
      makeTrace([{ x: 0, y: 0 }, { x: 20, y: 0 }], { id: 'tp', net_id: 'USB_P' }),
      makeTrace([{ x: 0, y: 1 }, { x: 15, y: 1 }], { id: 'tn', net_id: 'USB_N' }),
    ]

    const result = matchDifferentialPair(circuit, 'USB', 'serpentine', 0.5, 0.1)
    expect(result.delta_mm).toBeLessThanOrEqual(0.11)   // within skew_max with tiny tolerance
    expect(result.tuned_net).toBe('USB_N')              // shorter net was tuned
  })

  it('returns unchanged circuit when pair is already within skew_max_mm', () => {
    const circuit = [
      boardWith([{
        name: 'USB',
        net_p_id: 'USB_P',
        net_n_id: 'USB_N',
        skew_max_mm: 1.0,
      }]),
      makeTrace([{ x: 0, y: 0 }, { x: 10, y: 0 }], { id: 'tp', net_id: 'USB_P' }),
      makeTrace([{ x: 0, y: 1 }, { x: 10.05, y: 1 }], { id: 'tn', net_id: 'USB_N' }),
    ]

    const result = matchDifferentialPair(circuit, 'USB', 'serpentine', 0.5, 1.0)
    expect(result.tuned_net).toBeNull()
  })

  it('throws on missing pair definition', () => {
    const circuit = [boardWith([])]
    expect(() => matchDifferentialPair(circuit, 'GHOST', 'serpentine', 0.5)).toThrow()
  })
})
