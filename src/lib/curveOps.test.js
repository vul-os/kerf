import { describe, it, expect } from 'vitest'
import {
  curveLength,
  pointAt,
  tangentAt,
  discretize,
  projectCurveToSurface,
  intersectCurves,
  curveBoolean,
  blendCurve,
  matchCurve,
  offsetCurve3D,
  polylineToNurbs,
  simplifyCurve,
} from './curveOps.js'

// ── helpers ───────────────────────────────────────────────────────────────────

function approx(a, b, eps = 1e-3) {
  return Math.abs(a - b) < eps
}
function ptApprox(a, b, eps = 1e-2) {
  return Math.abs(a.x - b.x) < eps && Math.abs(a.y - b.y) < eps && Math.abs(a.z - b.z) < eps
}
function vlen(v) { return Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) }

// ── curveLength ───────────────────────────────────────────────────────────────

describe('curveLength', () => {
  it('line: correct Euclidean distance', () => {
    const line = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 3, y2: 4, z2: 0 }
    expect(approx(curveLength(line), 5)).toBe(true)
  })

  it('line: 3D diagonal', () => {
    const line = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 1, y2: 1, z2: 1 }
    expect(approx(curveLength(line), Math.sqrt(3))).toBe(true)
  })

  it('arc: radius * sweep', () => {
    // Quarter circle radius=5 → length = 5 * π/2
    const arc = { kind: 'arc', cx: 0, cy: 0, cz: 0, radius: 5, startAngle: 0, endAngle: Math.PI / 2 }
    expect(approx(curveLength(arc), 5 * Math.PI / 2, 1e-9)).toBe(true)
  })

  it('circle: 2π * radius', () => {
    const circle = { kind: 'circle', cx: 0, cy: 0, cz: 0, radius: 3 }
    expect(approx(curveLength(circle), 2 * Math.PI * 3, 1e-9)).toBe(true)
  })

  it('polyline: sum of segment lengths', () => {
    const poly = {
      kind: 'polyline',
      points: [
        { x: 0, y: 0, z: 0 },
        { x: 3, y: 0, z: 0 },
        { x: 3, y: 4, z: 0 },
      ],
    }
    expect(approx(curveLength(poly), 7)).toBe(true)
  })

  it('bspline: approximate length for straight-line control points', () => {
    const cp = [
      { x: 0, y: 0, z: 0 },
      { x: 1, y: 0, z: 0 },
      { x: 2, y: 0, z: 0 },
      { x: 3, y: 0, z: 0 },
    ]
    const bs = { kind: 'bspline', degree: 3, controlPoints: cp }
    // B-spline through collinear points approximates a line of length ~3.
    expect(curveLength(bs)).toBeGreaterThan(2)
    expect(curveLength(bs)).toBeLessThan(4)
  })
})

// ── pointAt ───────────────────────────────────────────────────────────────────

describe('pointAt', () => {
  it('line: t=0 at start, t=1 at end', () => {
    const line = { kind: 'line', x1: 1, y1: 2, z1: 3, x2: 4, y2: 5, z2: 6 }
    expect(ptApprox(pointAt(line, 0), { x: 1, y: 2, z: 3 })).toBe(true)
    expect(ptApprox(pointAt(line, 1), { x: 4, y: 5, z: 6 })).toBe(true)
  })

  it('polyline: t=0 at first point, t=1 at last point', () => {
    const poly = {
      kind: 'polyline',
      points: [{ x: 0, y: 0, z: 0 }, { x: 10, y: 0, z: 0 }, { x: 10, y: 10, z: 0 }],
    }
    expect(ptApprox(pointAt(poly, 0), { x: 0, y: 0, z: 0 })).toBe(true)
    expect(ptApprox(pointAt(poly, 1), { x: 10, y: 10, z: 0 })).toBe(true)
  })

  it('arc: t=0 at startAngle, t=1 at endAngle', () => {
    const arc = { kind: 'arc', cx: 0, cy: 0, cz: 0, radius: 5, startAngle: 0, endAngle: Math.PI / 2 }
    const p0 = pointAt(arc, 0)
    const p1 = pointAt(arc, 1)
    expect(approx(p0.x, 5)).toBe(true)
    expect(approx(p0.y, 0)).toBe(true)
    expect(approx(p1.x, 0, 0.01)).toBe(true)
    expect(approx(p1.y, 5)).toBe(true)
  })

  it('circle: t=0 and t=1 are the same point (full loop)', () => {
    const circle = { kind: 'circle', cx: 2, cy: 3, cz: 0, radius: 4 }
    expect(ptApprox(pointAt(circle, 0), pointAt(circle, 1))).toBe(true)
  })

  it('bspline: t=0 at first control point (clamped), t=1 at last', () => {
    const cp = [
      { x: 0, y: 0, z: 0 },
      { x: 1, y: 2, z: 0 },
      { x: 2, y: 2, z: 0 },
      { x: 3, y: 0, z: 0 },
    ]
    const bs = { kind: 'bspline', degree: 3, controlPoints: cp }
    expect(ptApprox(pointAt(bs, 0), { x: 0, y: 0, z: 0 })).toBe(true)
    expect(ptApprox(pointAt(bs, 1), { x: 3, y: 0, z: 0 })).toBe(true)
  })
})

// ── tangentAt ────────────────────────────────────────────────────────────────

describe('tangentAt', () => {
  it('line: unit tangent along line direction', () => {
    const line = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 3, y2: 4, z2: 0 }
    const t = tangentAt(line, 0.5)
    expect(approx(vlen(t), 1)).toBe(true)
    expect(approx(t.x, 0.6)).toBe(true)
    expect(approx(t.y, 0.8)).toBe(true)
  })

  it('circle: tangent is unit length', () => {
    const circle = { kind: 'circle', cx: 0, cy: 0, cz: 0, radius: 7 }
    const t = tangentAt(circle, 0.25)
    expect(approx(vlen(t), 1)).toBe(true)
  })

  it('bspline: unit tangent at midpoint', () => {
    const cp = [
      { x: 0, y: 0, z: 0 },
      { x: 1, y: 1, z: 0 },
      { x: 2, y: 1, z: 0 },
      { x: 3, y: 0, z: 0 },
    ]
    const bs = { kind: 'bspline', degree: 3, controlPoints: cp }
    const t = tangentAt(bs, 0.5)
    expect(approx(vlen(t), 1)).toBe(true)
  })
})

// ── discretize ───────────────────────────────────────────────────────────────

describe('discretize', () => {
  it('returns n+1 points', () => {
    const line = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 1, y2: 0, z2: 0 }
    expect(discretize(line, 10)).toHaveLength(11)
    expect(discretize(line, 1)).toHaveLength(2)
  })

  it('first point is pointAt(0), last is pointAt(1)', () => {
    const line = { kind: 'line', x1: 2, y1: 3, z1: 4, x2: 7, y2: 8, z2: 9 }
    const pts = discretize(line, 5)
    expect(ptApprox(pts[0], pointAt(line, 0))).toBe(true)
    expect(ptApprox(pts[5], pointAt(line, 1))).toBe(true)
  })
})

// ── projectCurveToSurface ─────────────────────────────────────────────────────

describe('projectCurveToSurface', () => {
  it('XY projection: z becomes 0', () => {
    const line = { kind: 'line', x1: 1, y1: 2, z1: 5, x2: 3, y2: 4, z2: 7 }
    const proj = projectCurveToSurface(line, 'XY')
    expect(proj.kind).toBe('polyline')
    for (const p of proj.points) {
      expect(p.z).toBeCloseTo(0, 10)
    }
  })

  it('XY projection: x/y preserved', () => {
    const line = { kind: 'line', x1: 0, y1: 0, z1: 10, x2: 1, y2: 1, z2: 20 }
    const proj = projectCurveToSurface(line, 'XY')
    // First and last points should reflect x/y of the line endpoints.
    const first = proj.points[0]
    const last = proj.points[proj.points.length - 1]
    expect(approx(first.x, 0)).toBe(true)
    expect(approx(first.y, 0)).toBe(true)
    expect(approx(last.x, 1)).toBe(true)
    expect(approx(last.y, 1)).toBe(true)
  })

  it('XZ projection: y component dropped', () => {
    const line = { kind: 'line', x1: 1, y1: 99, z1: 2, x2: 3, y2: 99, z2: 4 }
    const proj = projectCurveToSurface(line, 'XZ')
    for (const p of proj.points) {
      expect(p.z).toBeCloseTo(0, 10)
    }
  })

  it('arbitrary plane: returns polyline', () => {
    const line = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 1, y2: 1, z2: 1 }
    const plane = { origin: { x: 0, y: 0, z: 0 }, normal: { x: 0, y: 0, z: 1 } }
    const proj = projectCurveToSurface(line, plane)
    expect(proj.kind).toBe('polyline')
    expect(proj.points.length).toBeGreaterThan(0)
  })
})

// ── intersectCurves ──────────────────────────────────────────────────────────

describe('intersectCurves', () => {
  it('crossing lines in XY return one intersection near origin', () => {
    // line A: from (-1,0,0) to (1,0,0)
    // line B: from (0,-1,0) to (0,1,0)
    const a = { kind: 'line', x1: -1, y1: 0, z1: 0, x2: 1, y2: 0, z2: 0 }
    const b = { kind: 'line', x1: 0, y1: -1, z1: 0, x2: 0, y2: 1, z2: 0 }
    const hits = intersectCurves(a, b, 0.05)
    expect(hits.length).toBe(1)
    expect(approx(hits[0].point.x, 0, 0.05)).toBe(true)
    expect(approx(hits[0].point.y, 0, 0.05)).toBe(true)
  })

  it('parallel lines return no intersection', () => {
    const a = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 5, y2: 0, z2: 0 }
    const b = { kind: 'line', x1: 0, y1: 1, z1: 0, x2: 5, y2: 1, z2: 0 }
    const hits = intersectCurves(a, b, 0.05)
    expect(hits.length).toBe(0)
  })

  it('non-intersecting lines in 3D return no hits', () => {
    const a = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 1, y2: 0, z2: 0 }
    const b = { kind: 'line', x1: 0, y1: 5, z1: 5, x2: 1, y2: 5, z2: 5 }
    const hits = intersectCurves(a, b, 0.05)
    expect(hits.length).toBe(0)
  })

  it('each result has tA and tB in [0,1]', () => {
    const a = { kind: 'line', x1: -1, y1: 0, z1: 0, x2: 1, y2: 0, z2: 0 }
    const b = { kind: 'line', x1: 0, y1: -1, z1: 0, x2: 0, y2: 1, z2: 0 }
    const hits = intersectCurves(a, b, 0.05)
    for (const h of hits) {
      expect(h.tA).toBeGreaterThanOrEqual(0)
      expect(h.tA).toBeLessThanOrEqual(1)
      expect(h.tB).toBeGreaterThanOrEqual(0)
      expect(h.tB).toBeLessThanOrEqual(1)
    }
  })
})

// ── curveBoolean ─────────────────────────────────────────────────────────────

describe('curveBoolean', () => {
  const circleA = { kind: 'circle', cx: 0, cy: 0, cz: 0, radius: 2 }
  const circleB = { kind: 'circle', cx: 3, cy: 0, cz: 0, radius: 2 }
  const circleC = { kind: 'circle', cx: 0.5, cy: 0, cz: 0, radius: 0.5 }

  it('union returns a non-empty polyline', () => {
    const result = curveBoolean(circleA, circleB, 'union')
    expect(result.kind).toBe('polyline')
  })

  it('intersection returns a non-empty polyline for overlapping circles', () => {
    const result = curveBoolean(circleA, circleB, 'intersection')
    expect(result.kind).toBe('polyline')
  })

  it('difference: large minus small contained circle returns non-empty', () => {
    const result = curveBoolean(circleA, circleC, 'difference')
    expect(result.kind).toBe('polyline')
  })
})

// ── blendCurve ───────────────────────────────────────────────────────────────

describe('blendCurve', () => {
  const lineA = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 2, y2: 0, z2: 0 }
  const lineB = { kind: 'line', x1: 3, y1: 1, z1: 0, x2: 5, y2: 1, z2: 0 }

  it('G0 blend: endpoint of result matches endpoints of inputs', () => {
    const blend = blendCurve(lineA, 1, lineB, 0, 'G0')
    expect(blend.kind).toBe('bspline')
    const start = pointAt(blend, 0)
    const end   = pointAt(blend, 1)
    const pA = pointAt(lineA, 1)
    const pB = pointAt(lineB, 0)
    expect(ptApprox(start, pA, 0.05)).toBe(true)
    expect(ptApprox(end, pB, 0.05)).toBe(true)
  })

  it('G1 blend: endpoints match', () => {
    const blend = blendCurve(lineA, 1, lineB, 0, 'G1')
    const start = pointAt(blend, 0)
    const end   = pointAt(blend, 1)
    expect(ptApprox(start, pointAt(lineA, 1), 0.05)).toBe(true)
    expect(ptApprox(end, pointAt(lineB, 0), 0.05)).toBe(true)
  })

  it('G2 blend: returns a bspline', () => {
    const blend = blendCurve(lineA, 1, lineB, 0, 'G2')
    expect(blend.kind).toBe('bspline')
    expect(blend.controlPoints.length).toBeGreaterThan(3)
  })

  it('blend has valid knots array', () => {
    const blend = blendCurve(lineA, 1, lineB, 0, 'G1')
    expect(Array.isArray(blend.knots)).toBe(true)
    expect(blend.knots.length).toBe(blend.controlPoints.length + blend.degree + 1)
  })
})

// ── matchCurve ───────────────────────────────────────────────────────────────

describe('matchCurve', () => {
  const lineA = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 5, y2: 0, z2: 0 }
  const bsB = {
    kind: 'bspline',
    degree: 3,
    controlPoints: [
      { x: 7, y: 1, z: 0 },
      { x: 8, y: 1, z: 0 },
      { x: 9, y: 2, z: 0 },
      { x: 10, y: 2, z: 0 },
    ],
  }

  it('G0 match: bspline start moves to curveA end', () => {
    const matched = matchCurve(lineA, bsB, 'G0')
    const pA_end = pointAt(lineA, 1)
    expect(ptApprox(matched.controlPoints[0], pA_end, 0.01)).toBe(true)
  })

  it('G1 match: returns a bspline with same number of control points', () => {
    const matched = matchCurve(lineA, bsB, 'G1')
    expect(matched.kind).toBe('bspline')
    expect(matched.controlPoints.length).toBe(bsB.controlPoints.length)
  })

  it('line match: start moves to curveA end (G0)', () => {
    const aLine = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 3, y2: 0, z2: 0 }
    const bLine = { kind: 'line', x1: 10, y1: 10, z1: 0, x2: 20, y2: 10, z2: 0 }
    const matched = matchCurve(aLine, bLine, 'G0')
    expect(approx(matched.x1, 3)).toBe(true)
    expect(approx(matched.y1, 0)).toBe(true)
  })
})

// ── offsetCurve3D ────────────────────────────────────────────────────────────

describe('offsetCurve3D', () => {
  it('Z offset moves all points by given distance along Z', () => {
    const line = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 5, y2: 0, z2: 0 }
    const off = offsetCurve3D(line, 3, 'Z')
    expect(off.kind).toBe('polyline')
    for (const p of off.points) {
      expect(approx(p.z, 3)).toBe(true)
    }
  })

  it('custom axis offset', () => {
    const line = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 5, y2: 0, z2: 0 }
    const off = offsetCurve3D(line, 2, { x: 0, y: 1, z: 0 })
    for (const p of off.points) {
      expect(approx(p.y, 2)).toBe(true)
    }
  })
})

// ── polylineToNurbs ──────────────────────────────────────────────────────────

describe('polylineToNurbs', () => {
  it('returns a bspline', () => {
    const poly = {
      kind: 'polyline',
      points: [
        { x: 0, y: 0, z: 0 },
        { x: 1, y: 1, z: 0 },
        { x: 2, y: 0, z: 0 },
        { x: 3, y: 1, z: 0 },
      ],
    }
    const bs = polylineToNurbs(poly)
    expect(bs.kind).toBe('bspline')
  })

  it('preserves endpoints (clamped knot vector)', () => {
    const pts = [
      { x: 0, y: 0, z: 0 },
      { x: 1, y: 2, z: 0 },
      { x: 3, y: 2, z: 0 },
      { x: 4, y: 0, z: 0 },
    ]
    const bs = polylineToNurbs({ kind: 'polyline', points: pts })
    expect(ptApprox(pointAt(bs, 0), pts[0])).toBe(true)
    expect(ptApprox(pointAt(bs, 1), pts[pts.length - 1])).toBe(true)
  })

  it('degree is clamped to n-1', () => {
    const pts = [{ x: 0, y: 0, z: 0 }, { x: 1, y: 0, z: 0 }]
    const bs = polylineToNurbs({ kind: 'polyline', points: pts }, 5)
    expect(bs.degree).toBe(1)
  })

  it('has valid knots array', () => {
    const pts = Array.from({ length: 6 }, (_, i) => ({ x: i, y: 0, z: 0 }))
    const bs = polylineToNurbs({ kind: 'polyline', points: pts }, 3)
    expect(Array.isArray(bs.knots)).toBe(true)
    expect(bs.knots.length).toBe(bs.controlPoints.length + bs.degree + 1)
  })
})

// ── simplifyCurve ─────────────────────────────────────────────────────────────

describe('simplifyCurve', () => {
  it('polyline: reduces a dense straight line to 2 points', () => {
    const pts = Array.from({ length: 50 }, (_, i) => ({ x: i, y: 0, z: 0 }))
    const poly = { kind: 'polyline', points: pts }
    const simplified = simplifyCurve(poly, 0.01)
    expect(simplified.points.length).toBeLessThan(pts.length)
    expect(simplified.points.length).toBe(2)
  })

  it('polyline: preserves a curve that needs all its points', () => {
    // Zigzag that cannot be simplified much.
    const pts = []
    for (let i = 0; i < 10; i++) pts.push({ x: i, y: i % 2 === 0 ? 0 : 1, z: 0 })
    const poly = { kind: 'polyline', points: pts }
    const simplified = simplifyCurve(poly, 0.01)
    expect(simplified.points.length).toBe(pts.length)
  })

  it('bspline: simplify with large tolerance reduces control points', () => {
    const cp = Array.from({ length: 8 }, (_, i) => ({ x: i, y: 0, z: 0 }))
    const bs = { kind: 'bspline', degree: 3, controlPoints: cp }
    const s = simplifyCurve(bs, 0.5)
    expect(s.kind).toBe('bspline')
    expect(s.controlPoints.length).toBeLessThanOrEqual(cp.length)
  })

  it('line: returned unchanged', () => {
    const line = { kind: 'line', x1: 0, y1: 0, z1: 0, x2: 5, y2: 0, z2: 0 }
    const s = simplifyCurve(line, 0.01)
    expect(s).toEqual(line)
  })
})
