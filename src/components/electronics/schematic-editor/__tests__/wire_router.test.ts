// wire_router.test.js — Unit tests for the orthogonal wire router.

import { describe, it, expect } from 'vitest'
import { routeWire, segmentsFromPoints } from '../wire_router.js'

describe('routeWire', () => {
  it('returns a single segment for collinear horizontal points', () => {
    const pts = routeWire({ x: 0, y: 100 }, { x: 200, y: 100 })
    expect(pts).toHaveLength(2)
    expect(pts[0]).toEqual({ x: 0,   y: 100 })
    expect(pts[1]).toEqual({ x: 200, y: 100 })
  })

  it('returns a single segment for collinear vertical points', () => {
    const pts = routeWire({ x: 50, y: 0 }, { x: 50, y: 300 })
    expect(pts).toHaveLength(2)
    expect(pts[0]).toEqual({ x: 50, y: 0   })
    expect(pts[1]).toEqual({ x: 50, y: 300 })
  })

  it('returns a 3-point L-shaped path for non-collinear points', () => {
    const pts = routeWire({ x: 0, y: 0 }, { x: 100, y: 75 })
    // 3 points → 2 orthogonal segments
    expect(pts).toHaveLength(3)
    // Start unchanged
    expect(pts[0]).toEqual({ x: 0, y: 0 })
    // Elbow shares x with end and y with start
    expect(pts[1].x).toBe(pts[2].x)  // same x as end
    expect(pts[1].y).toBe(pts[0].y)  // same y as start
    // End unchanged (after grid snap, 75 is already on 25-grid)
    expect(pts[2]).toEqual({ x: 100, y: 75 })
  })

  it('snaps coordinates to the grid', () => {
    // 12 → 0 (nearest 25), 37 → 25
    const pts = routeWire({ x: 12, y: 0 }, { x: 37, y: 25 })
    // After snap: (0,0) → (25,25)
    // collinear check: x differ → L-shape
    expect(pts[0]).toEqual({ x: 0, y: 0 })
    expect(pts[2]).toEqual({ x: 25, y: 25 })
  })

  it('produces segments that are all axis-aligned (orthogonal)', () => {
    const cases = [
      [{ x: 0,   y: 0   }, { x: 300, y: 200 }],
      [{ x: 100, y: 50  }, { x: 400, y: 250 }],
      [{ x: 200, y: 300 }, { x: 75,  y: 25  }],
    ]
    for (const [a, b] of cases) {
      const pts = routeWire(a, b)
      const segs = segmentsFromPoints(pts)
      for (const { x1, y1, x2, y2 } of segs) {
        const isHoriz = y1 === y2
        const isVert  = x1 === x2
        expect(isHoriz || isVert).toBe(true)
      }
    }
  })
})

describe('segmentsFromPoints', () => {
  it('converts 3 points into 2 segments', () => {
    const segs = segmentsFromPoints([
      { x: 0,   y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 50 },
    ])
    expect(segs).toHaveLength(2)
    expect(segs[0]).toEqual({ x1: 0, y1: 0, x2: 100, y2: 0 })
    expect(segs[1]).toEqual({ x1: 100, y1: 0, x2: 100, y2: 50 })
  })

  it('converts 2 points into 1 segment', () => {
    const segs = segmentsFromPoints([{ x: 0, y: 0 }, { x: 50, y: 0 }])
    expect(segs).toHaveLength(1)
  })
})
