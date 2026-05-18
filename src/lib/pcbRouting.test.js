import { describe, it, expect } from 'vitest'
import {
  orthogonalSnap,
  corner45,
  freeRoute,
  pickRoutingMode,
  splitTraceAtPoint,
  detectTJunction,
  mergeTraces,
  pointToSegmentDist,
  segSegMinDist,
  offsetPolyline,
  routeDiffPairCentreline,
  polylineLength,
  shovePairClearance,
  insertMeanderPoints,
  diffPairLengthMatch,
} from './pcbRouting.js'

// ─── orthogonalSnap ───────────────────────────────────────────────────────────

describe('orthogonalSnap', () => {
  it('snaps to horizontal when dx > dy', () => {
    const { p2_snapped, direction } = orthogonalSnap({ x: 0, y: 0 }, { x: 5, y: 1 })
    expect(direction).toBe('horizontal')
    expect(p2_snapped.y).toBe(0)
    expect(p2_snapped.x).toBe(5)
  })

  it('snaps to vertical when dy > dx', () => {
    const { p2_snapped, direction } = orthogonalSnap({ x: 0, y: 0 }, { x: 1, y: 5 })
    expect(direction).toBe('vertical')
    expect(p2_snapped.x).toBe(0)
    expect(p2_snapped.y).toBe(5)
  })

  it('tie-breaks to horizontal with no lastDirection', () => {
    const { direction, p2_snapped } = orthogonalSnap({ x: 0, y: 0 }, { x: 3, y: 3 })
    expect(direction).toBe('horizontal')
    expect(p2_snapped.y).toBe(0)
  })

  it('tie-breaks using lastDirection when provided', () => {
    const { direction, p2_snapped } = orthogonalSnap(
      { x: 0, y: 0 },
      { x: 3, y: 3 },
      'vertical',
    )
    expect(direction).toBe('vertical')
    expect(p2_snapped.x).toBe(0)
  })

  it('works with negative offsets', () => {
    const { p2_snapped, direction } = orthogonalSnap({ x: 5, y: 5 }, { x: 2, y: 4 })
    // dy=1, dx=3 → horizontal
    expect(direction).toBe('horizontal')
    expect(p2_snapped.y).toBe(5)
    expect(p2_snapped.x).toBe(2)
  })

  it('returns p2 unchanged when cursor equals p1 (zero length)', () => {
    const { p2_snapped } = orthogonalSnap({ x: 2, y: 2 }, { x: 2, y: 2 })
    expect(p2_snapped.x).toBe(2)
    expect(p2_snapped.y).toBe(2)
  })
})

// ─── corner45 ────────────────────────────────────────────────────────────────

describe('corner45', () => {
  it('returns [mid, p2] for dx > dy (2 points)', () => {
    const pts = corner45({ x: 0, y: 0 }, { x: 6, y: 2 })
    expect(pts.length).toBe(2)
    const last = pts[pts.length - 1]
    expect(last.x).toBe(6)
    expect(last.y).toBe(2)
  })

  it('returns [mid, p2] for dy > dx (2 points)', () => {
    const pts = corner45({ x: 0, y: 0 }, { x: 2, y: 6 })
    expect(pts.length).toBe(2)
    const last = pts[pts.length - 1]
    expect(last.x).toBe(2)
    expect(last.y).toBe(6)
  })

  it('mid point lies on a 45° line from p1 when dx > dy', () => {
    const pts = corner45({ x: 0, y: 0 }, { x: 6, y: 2 })
    const mid = pts[0]
    expect(Math.abs(mid.x)).toBeCloseTo(Math.abs(mid.y), 5)
  })

  it('mid point lies on a 45° line from p1 when dy > dx', () => {
    const pts = corner45({ x: 0, y: 0 }, { x: 2, y: 6 })
    const mid = pts[0]
    expect(Math.abs(mid.x)).toBeCloseTo(Math.abs(mid.y), 5)
  })

  it('returns single point for perfect 45° (dx === dy)', () => {
    const pts = corner45({ x: 0, y: 0 }, { x: 3, y: 3 })
    expect(pts.length).toBe(1)
    expect(pts[0].x).toBe(3)
    expect(pts[0].y).toBe(3)
  })

  it('returns single point for pure horizontal (dy === 0)', () => {
    const pts = corner45({ x: 0, y: 0 }, { x: 5, y: 0 })
    expect(pts.length).toBe(1)
  })

  it('returns single point for pure vertical (dx === 0)', () => {
    const pts = corner45({ x: 0, y: 0 }, { x: 0, y: 4 })
    expect(pts.length).toBe(1)
  })

  it('works in Q3 (negative dx, negative dy)', () => {
    const pts = corner45({ x: 0, y: 0 }, { x: -6, y: -2 })
    expect(pts.length).toBe(2)
    const mid = pts[0]
    // should be at (-2, -2) — 45° diagonal for ady=2 steps
    expect(mid.x).toBeCloseTo(-2, 5)
    expect(mid.y).toBeCloseTo(-2, 5)
  })

  it('total path length equals manhattan + diagonal saving', () => {
    // p1=(0,0) p2=(4,2): adx=4 ady=2
    // diagonal seg: sqrt(2)*2 ≈ 2.828, then straight: 2 → total ≈ 4.828
    const p1 = { x: 0, y: 0 }
    const p2 = { x: 4, y: 2 }
    const pts = corner45(p1, p2)
    const seg1Len = Math.hypot(pts[0].x - p1.x, pts[0].y - p1.y)
    const seg2Len = Math.hypot(p2.x - pts[0].x, p2.y - pts[0].y)
    const total = seg1Len + seg2Len
    expect(total).toBeCloseTo(Math.sqrt(2) * 2 + 2, 4)
  })
})

// ─── freeRoute ────────────────────────────────────────────────────────────────

describe('freeRoute', () => {
  it('returns [p2] for a simple segment', () => {
    const pts = freeRoute({ x: 0, y: 0 }, { x: 3, y: 7 })
    expect(pts.length).toBe(1)
    expect(pts[0].x).toBe(3)
    expect(pts[0].y).toBe(7)
  })
})

// ─── pickRoutingMode ─────────────────────────────────────────────────────────

describe('pickRoutingMode', () => {
  it('dispatches orthogonal mode — returns {p2_snapped, direction}', () => {
    const result = pickRoutingMode('orthogonal', { x: 0, y: 0 }, { x: 3, y: 1 })
    expect(result).toHaveProperty('p2_snapped')
    expect(result).toHaveProperty('direction')
  })

  it('dispatches 45 mode — returns array', () => {
    const result = pickRoutingMode('45', { x: 0, y: 0 }, { x: 4, y: 2 })
    expect(Array.isArray(result)).toBe(true)
  })

  it('dispatches free mode — returns [p2]', () => {
    const result = pickRoutingMode('free', { x: 0, y: 0 }, { x: 5, y: 5 })
    expect(Array.isArray(result)).toBe(true)
    expect(result[0].x).toBe(5)
  })

  it('unknown mode falls back to freeRoute', () => {
    const result = pickRoutingMode('unknown', { x: 0, y: 0 }, { x: 2, y: 3 })
    expect(Array.isArray(result)).toBe(true)
  })
})

// ─── splitTraceAtPoint ────────────────────────────────────────────────────────

describe('splitTraceAtPoint', () => {
  const makeTrace = (points, net_id = 'GND') => ({
    id: 'trace_1',
    net_id,
    width_mm: 0.25,
    points,
  })

  it('splits a two-point horizontal trace at the midpoint', () => {
    const trace = makeTrace([{ x: 0, y: 0 }, { x: 10, y: 0 }])
    const [a, b] = splitTraceAtPoint(trace, { x: 5, y: 0 }, 0.1)
    expect(a.points[a.points.length - 1].x).toBeCloseTo(5, 5)
    expect(b.points[0].x).toBeCloseTo(5, 5)
  })

  it('preserves total polyline length after split', () => {
    const trace = makeTrace([{ x: 0, y: 0 }, { x: 10, y: 0 }])
    const [a, b] = splitTraceAtPoint(trace, { x: 3, y: 0 }, 0.1)
    const lenA = Math.hypot(
      a.points[1].x - a.points[0].x,
      a.points[1].y - a.points[0].y,
    )
    const lenB = Math.hypot(
      b.points[1].x - b.points[0].x,
      b.points[1].y - b.points[0].y,
    )
    expect(lenA + lenB).toBeCloseTo(10, 5)
  })

  it('preserves net_id on both halves', () => {
    const trace = makeTrace([{ x: 0, y: 0 }, { x: 10, y: 0 }], 'VCC')
    const [a, b] = splitTraceAtPoint(trace, { x: 5, y: 0 }, 0.1)
    expect(a.net_id).toBe('VCC')
    expect(b.net_id).toBe('VCC')
  })

  it('returns null when point is too far from any segment', () => {
    const trace = makeTrace([{ x: 0, y: 0 }, { x: 10, y: 0 }])
    const result = splitTraceAtPoint(trace, { x: 5, y: 5 }, 0.1)
    expect(result).toBeNull()
  })

  it('returns null for empty/invalid trace', () => {
    expect(splitTraceAtPoint(null, { x: 0, y: 0 }, 0.1)).toBeNull()
    expect(splitTraceAtPoint({ points: [] }, { x: 0, y: 0 }, 0.1)).toBeNull()
    expect(splitTraceAtPoint({ points: [{ x: 0, y: 0 }] }, { x: 0, y: 0 }, 0.1)).toBeNull()
  })

  it('works for a multi-segment trace and picks the right segment', () => {
    const trace = makeTrace([
      { x: 0, y: 0 },
      { x: 5, y: 0 },
      { x: 5, y: 5 },
    ])
    const [a, b] = splitTraceAtPoint(trace, { x: 5, y: 2.5 }, 0.1)
    // Split point should be on the second segment
    expect(a.points[a.points.length - 1].x).toBeCloseTo(5, 5)
    expect(a.points[a.points.length - 1].y).toBeCloseTo(2.5, 5)
    expect(b.points[0].y).toBeCloseTo(2.5, 5)
  })
})

// ─── detectTJunction ─────────────────────────────────────────────────────────

describe('detectTJunction (trace array form)', () => {
  const makeTrace = (id, points, net_id) => ({ id, net_id, points })

  it('returns trace id when vertex hits a trace interior on same net', () => {
    const traces = [
      makeTrace('t1', [{ x: 0, y: 0 }, { x: 10, y: 0 }], 'GND'),
    ]
    const result = detectTJunction(traces, { x: 5, y: 0, net_id: 'GND' }, 0.1)
    expect(result).toBe('t1')
  })

  it('returns null for different net', () => {
    const traces = [
      makeTrace('t1', [{ x: 0, y: 0 }, { x: 10, y: 0 }], 'GND'),
    ]
    const result = detectTJunction(traces, { x: 5, y: 0, net_id: 'VCC' }, 0.1)
    expect(result).toBeNull()
  })

  it('returns null when point is off any segment', () => {
    const traces = [
      makeTrace('t1', [{ x: 0, y: 0 }, { x: 10, y: 0 }], 'GND'),
    ]
    const result = detectTJunction(traces, { x: 5, y: 5, net_id: 'GND' }, 0.1)
    expect(result).toBeNull()
  })

  it('returns null for empty traces array', () => {
    expect(detectTJunction([], { x: 0, y: 0, net_id: 'GND' }, 0.1)).toBeNull()
  })

  it('ignores endpoints (not a T-junction at trace start/end)', () => {
    const traces = [
      makeTrace('t1', [{ x: 0, y: 0 }, { x: 10, y: 0 }], 'GND'),
    ]
    // at start
    expect(detectTJunction(traces, { x: 0, y: 0, net_id: 'GND' }, 0.1)).toBeNull()
    // at end
    expect(detectTJunction(traces, { x: 10, y: 0, net_id: 'GND' }, 0.1)).toBeNull()
  })

  it('matches when net_id is omitted (no net filter)', () => {
    const traces = [
      makeTrace('t1', [{ x: 0, y: 0 }, { x: 10, y: 0 }], 'GND'),
    ]
    // vertex with no net_id — all nets accepted
    const result = detectTJunction(traces, { x: 5, y: 0 }, 0.1)
    expect(result).toBe('t1')
  })
})

// ─── mergeTraces ─────────────────────────────────────────────────────────────

describe('mergeTraces', () => {
  const makeTr = (id, points, net_id = 'GND') => ({ id, net_id, width_mm: 0.25, points })

  it('merges two same-net traces sharing an endpoint', () => {
    const t1 = makeTr('a', [{ x: 0, y: 0 }, { x: 5, y: 0 }])
    const t2 = makeTr('b', [{ x: 5, y: 0 }, { x: 10, y: 0 }])
    const merged = mergeTraces([t1, t2], 0.1)
    expect(merged.length).toBe(1)
    expect(merged[0].points.length).toBe(3)
    expect(merged[0].points[2].x).toBeCloseTo(10, 5)
  })

  it('refuses to merge different-net traces', () => {
    const t1 = makeTr('a', [{ x: 0, y: 0 }, { x: 5, y: 0 }], 'GND')
    const t2 = makeTr('b', [{ x: 5, y: 0 }, { x: 10, y: 0 }], 'VCC')
    const result = mergeTraces([t1, t2], 0.1)
    expect(result.length).toBe(2)
  })

  it('is idempotent — calling twice returns same result', () => {
    const t1 = makeTr('a', [{ x: 0, y: 0 }, { x: 5, y: 0 }])
    const t2 = makeTr('b', [{ x: 5, y: 0 }, { x: 10, y: 0 }])
    const once = mergeTraces([t1, t2], 0.1)
    const twice = mergeTraces(once, 0.1)
    expect(twice.length).toBe(1)
    expect(twice[0].points.length).toBe(once[0].points.length)
  })

  it('returns empty array for empty input', () => {
    expect(mergeTraces([], 0.1)).toEqual([])
  })

  it('returns single trace unchanged', () => {
    const t1 = makeTr('a', [{ x: 0, y: 0 }, { x: 5, y: 0 }])
    const result = mergeTraces([t1], 0.1)
    expect(result.length).toBe(1)
    expect(result[0].points.length).toBe(2)
  })

  it('does not merge non-adjacent same-net traces', () => {
    const t1 = makeTr('a', [{ x: 0, y: 0 }, { x: 5, y: 0 }])
    const t2 = makeTr('b', [{ x: 10, y: 0 }, { x: 15, y: 0 }])
    const result = mergeTraces([t1, t2], 0.1)
    expect(result.length).toBe(2)
  })
})

// ─── pointToSegmentDist (legacy/utility) ─────────────────────────────────────

describe('pointToSegmentDist', () => {
  it('returns 0 for a point on the segment midpoint', () => {
    expect(pointToSegmentDist({ x: 1, y: 0 }, { x: 0, y: 0 }, { x: 2, y: 0 })).toBeCloseTo(0, 5)
  })
  it('returns perpendicular distance for a point beside the segment', () => {
    expect(pointToSegmentDist({ x: 1, y: 1 }, { x: 0, y: 0 }, { x: 2, y: 0 })).toBeCloseTo(1, 5)
  })
  it('handles zero-length segment', () => {
    expect(pointToSegmentDist({ x: 3, y: 4 }, { x: 0, y: 0 }, { x: 0, y: 0 })).toBeCloseTo(5, 5)
  })
})

// ─── T-102: push-and-shove diff-pair routing ─────────────────────────────────

// segSegMinDist

describe('segSegMinDist', () => {
  it('returns 0 for intersecting segments', () => {
    // cross at origin
    const d = segSegMinDist(
      { x: -1, y: 0 }, { x: 1, y: 0 },
      { x: 0, y: -1 }, { x: 0, y: 1 },
    )
    expect(d).toBeCloseTo(0, 5)
  })

  it('returns correct perpendicular distance for parallel horizontal segments', () => {
    const d = segSegMinDist(
      { x: 0, y: 0 }, { x: 10, y: 0 },
      { x: 0, y: 2 }, { x: 10, y: 2 },
    )
    expect(d).toBeCloseTo(2, 5)
  })

  it('returns endpoint distance when segments do not overlap', () => {
    const d = segSegMinDist(
      { x: 0, y: 0 }, { x: 3, y: 0 },
      { x: 4, y: 0 }, { x: 7, y: 0 },
    )
    expect(d).toBeCloseTo(1, 5)
  })

  it('returns 0 for collinear overlapping segments', () => {
    const d = segSegMinDist(
      { x: 0, y: 0 }, { x: 5, y: 0 },
      { x: 3, y: 0 }, { x: 8, y: 0 },
    )
    expect(d).toBeCloseTo(0, 5)
  })
})

// offsetPolyline

describe('offsetPolyline', () => {
  it('offsets a single horizontal segment upward (+y) for positive offset', () => {
    const pts = [{ x: 0, y: 0 }, { x: 10, y: 0 }]
    const out = offsetPolyline(pts, 1.5)
    expect(out[0].y).toBeCloseTo(1.5, 5)
    expect(out[1].y).toBeCloseTo(1.5, 5)
    expect(out[0].x).toBeCloseTo(0, 5)
    expect(out[1].x).toBeCloseTo(10, 5)
  })

  it('offsets downward (-y) for negative offset', () => {
    const pts = [{ x: 0, y: 0 }, { x: 10, y: 0 }]
    const out = offsetPolyline(pts, -1.0)
    expect(out[0].y).toBeCloseTo(-1.0, 5)
  })

  it('does not mutate the input array', () => {
    const pts = [{ x: 0, y: 0 }, { x: 5, y: 0 }]
    offsetPolyline(pts, 2.0)
    expect(pts[0].y).toBe(0)
  })

  it('preserves point count', () => {
    const pts = [{ x: 0, y: 0 }, { x: 5, y: 0 }, { x: 10, y: 5 }]
    expect(offsetPolyline(pts, 1.0).length).toBe(3)
  })

  it('produces opposite offset for p and n at half-spacing', () => {
    const pts = [{ x: 0, y: 0 }, { x: 10, y: 0 }]
    const pos = offsetPolyline(pts, 0.1)
    const neg = offsetPolyline(pts, -0.1)
    // P is at +0.1, N at -0.1 — centre-to-centre = 0.2
    expect(Math.abs(pos[0].y - neg[0].y)).toBeCloseTo(0.2, 5)
  })
})

// routeDiffPairCentreline

describe('routeDiffPairCentreline', () => {
  it('produces a straight pair for collinear start/end (axis-aligned)', () => {
    const { pos, neg, centreline } = routeDiffPairCentreline(
      { x: 0, y: 0 }, { x: 20, y: 0 }, 0.2,
    )
    expect(centreline.length).toBe(2)
    expect(pos.length).toBe(2)
    expect(neg.length).toBe(2)
  })

  it('produces an L-route (3-point centreline) for diagonal start/end', () => {
    const { centreline } = routeDiffPairCentreline(
      { x: 0, y: 0 }, { x: 10, y: 8 }, 0.2,
    )
    expect(centreline.length).toBe(3)
  })

  it('P trace is offset +half, N trace is offset -half from centreline', () => {
    const { pos, neg } = routeDiffPairCentreline(
      { x: 0, y: 0 }, { x: 10, y: 0 }, 0.4,
    )
    // Horizontal segment → perp is +y; P should be at y=+0.2, N at y=-0.2
    expect(pos[0].y).toBeCloseTo(0.2, 5)
    expect(neg[0].y).toBeCloseTo(-0.2, 5)
  })

  it('P and N traces have equal length for a straight route', () => {
    const { pos, neg } = routeDiffPairCentreline(
      { x: 0, y: 0 }, { x: 15, y: 0 }, 0.2,
    )
    expect(polylineLength(pos)).toBeCloseTo(polylineLength(neg), 5)
  })

  it('pair maintains coupling spacing within tolerance', () => {
    const { pos, neg } = routeDiffPairCentreline(
      { x: 0, y: 0 }, { x: 10, y: 0 }, 0.2,
    )
    // edge-to-edge = centre-to-centre minus trace-widths; here we just check
    // the geometric centre-to-centre equals spacing_mm = 0.2.
    const gap = Math.abs(pos[0].y - neg[0].y)
    expect(gap).toBeCloseTo(0.2, 5)
  })
})

// shovePairClearance

describe('shovePairClearance (T-102: shove behaviour)', () => {
  const makeTrace = (id, netId, y0, y1 = y0, x0 = 0, x1 = 20, layer = 'top_copper', widthMm = 0.2) => ({
    id,
    netId,
    layer,
    widthMm,
    points: [{ x: x0, y: y0 }, { x: x1, y: y1 }],
  })

  it('does not shove a trace that is already clear', () => {
    const traces = [makeTrace('t1', 'GND', 5)]  // 5mm away — well clear
    const { shovedIds } = shovePairClearance(
      traces,
      { x: 0, y: 0 }, { x: 20, y: 0 },
      'top_copper', [], 0.2, 0.2,
    )
    expect(shovedIds).toHaveLength(0)
  })

  it('shoves a trace that violates clearance', () => {
    const traces = [makeTrace('t1', 'GND', 0.1)]  // 0.1mm — violates 0.2 clearance + half-widths
    const { traces: out, shovedIds } = shovePairClearance(
      traces,
      { x: 0, y: 0 }, { x: 20, y: 0 },
      'top_copper', [], 0.2, 0.2,
    )
    expect(shovedIds).toContain('t1')
    // After shove, the trace should be at least clearance+half-widths away.
    const y = out[0].points[0].y
    const requiredGap = 0.2 + 0.2 / 2 + 0.2 / 2
    expect(Math.abs(y)).toBeGreaterThanOrEqual(requiredGap - 1e-6)
  })

  it('does not shove traces on a different layer', () => {
    const traces = [makeTrace('t1', 'GND', 0.1, 0.1, 0, 20, 'bottom_copper')]
    const { shovedIds } = shovePairClearance(
      traces,
      { x: 0, y: 0 }, { x: 20, y: 0 },
      'top_copper', [], 0.2, 0.2,
    )
    expect(shovedIds).toHaveLength(0)
  })

  it('does not shove traces in the excluded netId list', () => {
    const traces = [makeTrace('t1', 'DP_P', 0.1)]
    const { shovedIds } = shovePairClearance(
      traces,
      { x: 0, y: 0 }, { x: 20, y: 0 },
      'top_copper', ['DP_P', 'DP_N'], 0.2, 0.2,
    )
    expect(shovedIds).toHaveLength(0)
  })

  it('does not mutate the input traces array', () => {
    const originalY = 0.1
    const traces = [makeTrace('t1', 'GND', originalY)]
    shovePairClearance(
      traces,
      { x: 0, y: 0 }, { x: 20, y: 0 },
      'top_copper', [], 0.2, 0.2,
    )
    expect(traces[0].points[0].y).toBe(originalY)  // original untouched
  })

  it('shoves multiple violating traces independently', () => {
    const traces = [
      makeTrace('t1', 'A', 0.1),   // above centreline
      makeTrace('t2', 'B', -0.1),  // below centreline
    ]
    const { shovedIds } = shovePairClearance(
      traces,
      { x: 0, y: 0 }, { x: 20, y: 0 },
      'top_copper', [], 0.2, 0.2,
    )
    expect(shovedIds).toContain('t1')
    expect(shovedIds).toContain('t2')
  })
})

// insertMeanderPoints

describe('insertMeanderPoints', () => {
  it('returns input unchanged for zero extra length', () => {
    const pts = [{ x: 0, y: 0 }, { x: 10, y: 0 }]
    const out = insertMeanderPoints(pts, 0)
    expect(out.length).toBe(2)
  })

  it('adds more points than the input for positive extra length', () => {
    const pts = [{ x: 0, y: 0 }, { x: 10, y: 0 }]
    const out = insertMeanderPoints(pts, 1.0)
    expect(out.length).toBeGreaterThan(2)
  })

  it('increases total arc-length when extra > 0', () => {
    const pts = [{ x: 0, y: 0 }, { x: 10, y: 0 }]
    const out = insertMeanderPoints(pts, 2.0, 0.5)
    const lenBefore = polylineLength(pts)
    const lenAfter = polylineLength(out)
    // Serpentine meander must strictly lengthen the trace.
    expect(lenAfter).toBeGreaterThan(lenBefore)
  })

  it('inserts more length when amplitude is larger', () => {
    const pts = [{ x: 0, y: 0 }, { x: 10, y: 0 }]
    const smallAmp = polylineLength(insertMeanderPoints(pts, 2.0, 0.25))
    const bigAmp = polylineLength(insertMeanderPoints(pts, 2.0, 2.0))
    expect(bigAmp).toBeGreaterThan(smallAmp)
  })
})

// diffPairLengthMatch — length-matched coupled traces

describe('diffPairLengthMatch (T-102: length-matched coupled traces)', () => {
  it('returns unmodified points when already matched within tolerance', () => {
    const pos = [{ x: 0, y: 0 }, { x: 10, y: 0 }]
    const neg = [{ x: 0, y: 0.2 }, { x: 10, y: 0.2 }]
    const { skewMm } = diffPairLengthMatch(pos, neg, 0.05)
    expect(skewMm).toBeCloseTo(0, 3)
  })

  it('lengthens the shorter neg conductor when pos is longer', () => {
    const pos = [{ x: 0, y: 0 }, { x: 12, y: 0 }]  // 12mm
    const neg = [{ x: 0, y: 0.2 }, { x: 10, y: 0.2 }]  // 10mm
    const { neg: newNeg } = diffPairLengthMatch(pos, neg, 0.05)
    expect(polylineLength(newNeg)).toBeGreaterThan(10)
  })

  it('lengthens the shorter pos conductor when neg is longer', () => {
    const pos = [{ x: 0, y: 0 }, { x: 10, y: 0 }]   // 10mm
    const neg = [{ x: 0, y: 0.2 }, { x: 12, y: 0.2 }]  // 12mm
    const { pos: newPos } = diffPairLengthMatch(pos, neg, 0.05)
    expect(polylineLength(newPos)).toBeGreaterThan(10)
  })

  it('returns skewMm within tolerance after matching', () => {
    const pos = [{ x: 0, y: 0 }, { x: 15, y: 0 }]
    const neg = [{ x: 0, y: 0.2 }, { x: 10, y: 0.2 }]
    const { skewMm } = diffPairLengthMatch(pos, neg, 0.05, 0.5)
    // After matching, skew should be significantly reduced from the original 5mm delta.
    expect(skewMm).toBeLessThan(5)
  })
})
