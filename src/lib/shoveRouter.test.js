import { describe, it, expect } from 'vitest'
import { routeWithShove, segmentMinDistance, shoveSegment } from './shoveRouter.js'

const _trace = (id, net_id, layer, points, width_mm = 0.25) => ({
  id, net_id, layer, width_mm, points
})

const _board = (traces) => ({ pcb_trace: traces })

const _circuit = (traces) => ({
  pcb_board: { pcb_trace: traces || [] }
})

describe('shoveRouter', () => {
  describe('segmentMinDistance', () => {
    it('returns 0 for intersecting segments', () => {
      const seg1 = { points: [{ x: 0, y: 0 }, { x: 10, y: 0 }] }
      const seg2 = { points: [{ x: 5, y: -5 }, { x: 5, y: 5 }] }
      expect(segmentMinDistance(seg1, seg2)).toBe(0)
    })

    it('returns distance for parallel non-intersecting', () => {
      const seg1 = { points: [{ x: 0, y: 0 }, { x: 10, y: 0 }] }
      const seg2 = { points: [{ x: 0, y: 5 }, { x: 10, y: 5 }] }
      expect(segmentMinDistance(seg1, seg2)).toBeCloseTo(5, 5)
    })

    it('returns distance for offset perpendicular', () => {
      const seg1 = { points: [{ x: 0, y: 0 }, { x: 10, y: 0 }] }
      const seg2 = { points: [{ x: 0, y: 10 }, { x: 0, y: 20 }] }
      expect(segmentMinDistance(seg1, seg2)).toBeCloseTo(10, 5)
    })
  })

  describe('shoveSegment', () => {
    it('shoves segment perpendicular by clearance amount', () => {
      const seg = { points: [{ x: 0, y: 0 }, { x: 10, y: 0 }] }
      const perp = { x: 0, y: 1 }
      const result = shoveSegment(seg, perp, 0.5)
      expect(result.points[0].x).toBeCloseTo(0, 5)
      expect(result.points[0].y).toBeCloseTo(0.5, 5)
      expect(result.points[1].x).toBeCloseTo(10, 5)
      expect(result.points[1].y).toBeCloseTo(0.5, 5)
    })
  })

  describe('routeWithShove', () => {
    it('no conflicts means no shove', () => {
      const existing = _trace('t1', 'net1', 'top', [{ x: 0, y: 0 }, { x: 10, y: 0 }])
      const circuit = _circuit([existing])
      const newPts = [[20, 10], [30, 10]]
      const result = routeWithShove(circuit, 'top', newPts, 0.25)
      expect(result.shoved_traces).toHaveLength(0)
      expect(result.conflicts_resolved).toBe(0)
      expect(result.conflicts_unresolved).toBe(0)
    })

    it('perpendicular trace gets shoved by exactly clearance_mm', () => {
      const existing = _trace('t1', 'net1', 'top', [{ x: 5, y: 0 }, { x: 5, y: 10 }])
      const circuit = _circuit([existing])
      const newPts = [[0, 5], [10, 5]]
      const clearance = 0.5
      const result = routeWithShove(circuit, 'top', newPts, clearance)
      expect(result.shoved_traces).toContain('t1')
    })

    it('endpoint on trace body triggers shove (not T-junction)', () => {
      const existing = _trace('t1', 'net1', 'top', [{ x: 0, y: 5 }, { x: 10, y: 5 }])
      const circuit = _circuit([existing])
      const newPts = [[5, 5], [5, 10]]
      const result = routeWithShove(circuit, 'top', newPts, 0.25)
      expect(result.shoved_traces.length).toBeGreaterThan(0)
    })

    it('different-net intersection triggers shove', () => {
      const existing = _trace('t1', 'net1', 'top', [{ x: 0, y: 5 }, { x: 10, y: 5 }])
      const circuit = _circuit([existing])
      const newPts = [[5, 0], [5, 10]]
      const result = routeWithShove(circuit, 'top', newPts, 0.25)
      expect(result.shoved_traces.length).toBeGreaterThan(0)
    })

    it('different layer not affected', () => {
      const existing = _trace('t1', 'net1', 'top', [{ x: 0, y: 5 }, { x: 10, y: 5 }])
      const circuit = _circuit([existing])
      const newPts = [[5, 0], [5, 10]]
      const result = routeWithShove(circuit, 'bottom', newPts, 0.25)
      expect(result.shoved_traces).toHaveLength(0)
    })

    it('returns circuit_json in result', () => {
      const circuit = _circuit([])
      const newPts = [[0, 0], [10, 0]]
      const result = routeWithShove(circuit, 'top', newPts, 0.25)
      expect(result.circuit_json).toBeDefined()
    })

    it('handles empty circuit', () => {
      const result = routeWithShove(null, 'top', [[0, 0], [10, 0]], 0.25)
      expect(result.circuit_json).toBeNull()
      expect(result.shoved_traces).toHaveLength(0)
    })

    it('handles empty traces array', () => {
      const circuit = _circuit([])
      const newPts = [[0, 0], [10, 0]]
      const result = routeWithShove(circuit, 'top', newPts, 0.25)
      expect(result.shoved_traces).toHaveLength(0)
      expect(result.conflicts_resolved).toBe(0)
    })

    it('preserves other traces not involved in conflict', () => {
      const t1 = _trace('t1', 'net1', 'top', [{ x: 0, y: 0 }, { x: 10, y: 0 }])
      const t2 = _trace('t2', 'net2', 'top', [{ x: 0, y: 100 }, { x: 10, y: 100 }])
      const circuit = _circuit([t1, t2])
      const newPts = [[5, 50], [5, 60]]
      const result = routeWithShove(circuit, 'top', newPts, 0.25)
      expect(result.shoved_traces).not.toContain('t2')
    })

    it('recursion cap respected (no infinite loop)', () => {
      const traces = []
      for (let i = 0; i < 10; i++) {
        traces.push(_trace(`t${i}`, `net${i}`, 'top', [{ x: i * 2, y: 5 }, { x: i * 2 + 1, y: 5 }]))
      }
      const circuit = _circuit(traces)
      const newPts = [[0, 0], [100, 0]]
      const result = routeWithShove(circuit, 'top', newPts, 0.25)
      expect(result.conflicts_unresolved).toBe(0)
    })

    it('shoved_traces is unique list', () => {
      const t1 = _trace('t1', 'net1', 'top', [{ x: 0, y: 5 }, { x: 10, y: 5 }])
      const circuit = _circuit([t1])
      const newPts = [[5, 0], [5, 10]]
      const result = routeWithShove(circuit, 'top', newPts, 0.25)
      const unique = [...new Set(result.shoved_traces)]
      expect(result.shoved_traces).toHaveLength(unique.length)
    })

    it('fully blocked returns conflicts_unresolved > 0', () => {
      const t1 = _trace('t1', 'net1', 'top', [{ x: 0, y: 5 }, { x: 10, y: 5 }])
      const t2 = _trace('t2', 'net2', 'top', [{ x: 0, y: 6 }, { x: 10, y: 6 }])
      const circuit = _circuit([t1, t2])
      const newPts = [[5, 5.5], [5, 5.5]]
      const result = routeWithShove(circuit, 'top', newPts, 0.25)
    })
  })
})
