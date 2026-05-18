// wireEdit.test.js — Vitest unit tests for wire-drag + context-menu actions.
//
// All tests are pure-logic; no React, no DOM, no network.

import { describe, it, expect } from 'vitest'
import {
  pointSegmentDist,
  snapToGrid,
  snapPoint,
  hitTestWire,
  dragWireSegment,
  nudgeWireAnchor,
  deleteWire,
  rerouteWire,
  pinWireToGrid,
  beginWireDrag,
} from './wireEdit.js'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeTrace(id, route, extra = {}) {
  return {
    type: 'pcb_trace',
    pcb_trace_id: id,
    route,
    route_thickness_mm: 0.25,
    ...extra,
  }
}

// A simple L-shaped trace: (0,0) → (5,0) → (5,5)
const TRACE_L = makeTrace('t1', [
  { x: 0, y: 0 },
  { x: 5, y: 0 },
  { x: 5, y: 5 },
])

// A straight horizontal trace at y=2
const TRACE_H = makeTrace('t2', [
  { x: 1, y: 2 },
  { x: 9, y: 2 },
])

const BASE_CIRCUIT = [TRACE_L, TRACE_H]

// ---------------------------------------------------------------------------
// pointSegmentDist
// ---------------------------------------------------------------------------

describe('pointSegmentDist', () => {
  it('returns zero for a point on the segment', () => {
    const { dist, t } = pointSegmentDist({ x: 2.5, y: 0 }, { x: 0, y: 0 }, { x: 5, y: 0 })
    expect(dist).toBeCloseTo(0, 5)
    expect(t).toBeCloseTo(0.5, 5)
  })

  it('returns correct distance for a point off the segment', () => {
    const { dist } = pointSegmentDist({ x: 2.5, y: 1 }, { x: 0, y: 0 }, { x: 5, y: 0 })
    expect(dist).toBeCloseTo(1, 5)
  })

  it('clamps t to 0 for a point before the start', () => {
    const { dist, t } = pointSegmentDist({ x: -1, y: 0 }, { x: 0, y: 0 }, { x: 5, y: 0 })
    expect(t).toBe(0)
    expect(dist).toBeCloseTo(1, 5)
  })

  it('clamps t to 1 for a point after the end', () => {
    const { dist, t } = pointSegmentDist({ x: 6, y: 0 }, { x: 0, y: 0 }, { x: 5, y: 0 })
    expect(t).toBe(1)
    expect(dist).toBeCloseTo(1, 5)
  })

  it('handles zero-length segment (degenerate)', () => {
    const { dist } = pointSegmentDist({ x: 3, y: 4 }, { x: 0, y: 0 }, { x: 0, y: 0 })
    expect(dist).toBeCloseTo(5, 5)
  })
})

// ---------------------------------------------------------------------------
// snapToGrid / snapPoint
// ---------------------------------------------------------------------------

describe('snapToGrid', () => {
  it('snaps to default 0.5 mm grid', () => {
    expect(snapToGrid(1.3)).toBe(1.5)
    expect(snapToGrid(1.2)).toBe(1.0)
    expect(snapToGrid(1.25)).toBe(1.5)  // tie goes to upper (Math.round)
  })

  it('snaps to custom grid', () => {
    expect(snapToGrid(1.6, 1.0)).toBe(2)
    expect(snapToGrid(0.3, 0.1)).toBeCloseTo(0.3, 5)
  })
})

describe('snapPoint', () => {
  it('snaps both axes', () => {
    const p = snapPoint({ x: 1.3, y: 4.8 })
    expect(p.x).toBe(1.5)
    expect(p.y).toBe(5.0)
  })
})

// ---------------------------------------------------------------------------
// hitTestWire
// ---------------------------------------------------------------------------

describe('hitTestWire', () => {
  it('returns null for empty array', () => {
    expect(hitTestWire([], { x: 0, y: 0 })).toBeNull()
  })

  it('returns null when no trace is hit', () => {
    const result = hitTestWire(BASE_CIRCUIT, { x: 0, y: 10 }, 0.1)
    expect(result).toBeNull()
  })

  it('hits the horizontal segment of TRACE_L', () => {
    // Midpoint of (0,0)→(5,0) is (2.5, 0); click slightly above it
    const result = hitTestWire(BASE_CIRCUIT, { x: 2.5, y: 0.1 }, 0.3)
    expect(result).not.toBeNull()
    expect(result.traceId).toBe('t1')
    expect(result.segIndex).toBe(0)
  })

  it('hits the vertical segment of TRACE_L', () => {
    // Midpoint of (5,0)→(5,5) is (5, 2.5); click slightly to the right
    const result = hitTestWire(BASE_CIRCUIT, { x: 5.1, y: 2.5 }, 0.3)
    expect(result).not.toBeNull()
    expect(result.traceId).toBe('t1')
    expect(result.segIndex).toBe(1)
  })

  it('hits TRACE_H when pointer is on it', () => {
    // Use x=3, y=2 — on TRACE_H (1,2)→(9,2) but NOT on TRACE_L
    const result = hitTestWire(BASE_CIRCUIT, { x: 3, y: 2 }, 0.1)
    expect(result).not.toBeNull()
    expect(result.traceId).toBe('t2')
  })

  it('picks the closest trace when two are within range but one is closer', () => {
    // TRACE_H passes through (3, 2) exactly (dist=0).
    // TRACE_L vertical segment (5,0)→(5,5) is 2 mm away at x=3.
    // TRACE_H wins.
    const result = hitTestWire(BASE_CIRCUIT, { x: 3, y: 2 }, 3.0)
    expect(result.traceId).toBe('t2')
  })

  it('ignores non-trace elements', () => {
    const circuit = [
      { type: 'pcb_board', width: 20, height: 20 },
      TRACE_H,
    ]
    const result = hitTestWire(circuit, { x: 5, y: 2 }, 0.1)
    expect(result?.traceId).toBe('t2')
  })
})

// ---------------------------------------------------------------------------
// dragWireSegment
// ---------------------------------------------------------------------------

describe('dragWireSegment', () => {
  it('inserts a midpoint anchor on first drag (no anchorIndex)', () => {
    const patched = dragWireSegment(BASE_CIRCUIT, 't2', 0, { x: 5, y: 3 })
    const trace = patched.find((e) => e.pcb_trace_id === 't2')
    // Original: 2 points → after insert: 3 points
    expect(trace.route).toHaveLength(3)
    // The anchor is at index 1 (after snapToGrid)
    expect(trace.route[1].x).toBe(5)
    expect(trace.route[1].y).toBe(3)
  })

  it('snaps the inserted anchor to the grid', () => {
    const patched = dragWireSegment(BASE_CIRCUIT, 't2', 0, { x: 4.3, y: 3.1 }, { grid: 0.5 })
    const trace = patched.find((e) => e.pcb_trace_id === 't2')
    expect(trace.route[1].x).toBe(4.5)
    expect(trace.route[1].y).toBe(3.0)
  })

  it('moves an existing anchor when anchorIndex is provided', () => {
    // First, create a trace with an interior anchor
    const withAnchor = dragWireSegment(BASE_CIRCUIT, 't2', 0, { x: 5, y: 3 })
    // Then move that anchor (index 1) to a new position
    const patched = dragWireSegment(withAnchor, 't2', 0, { x: 5, y: 4 }, { anchorIndex: 1 })
    const trace = patched.find((e) => e.pcb_trace_id === 't2')
    // Still 3 points (no extra insertion)
    expect(trace.route).toHaveLength(3)
    expect(trace.route[1].y).toBe(4)
  })

  it('does not mutate the original circuit', () => {
    const original = JSON.parse(JSON.stringify(BASE_CIRCUIT))
    dragWireSegment(BASE_CIRCUIT, 't2', 0, { x: 5, y: 3 })
    expect(BASE_CIRCUIT).toEqual(original)
  })

  it('leaves other traces untouched', () => {
    const patched = dragWireSegment(BASE_CIRCUIT, 't2', 0, { x: 5, y: 3 })
    const t1 = patched.find((e) => e.pcb_trace_id === 't1')
    expect(t1).toEqual(TRACE_L)
  })

  it('preserves non-trace elements', () => {
    const circuit = [{ type: 'pcb_board', width: 20 }, TRACE_H]
    const patched = dragWireSegment(circuit, 't2', 0, { x: 5, y: 3 })
    expect(patched[0]).toEqual({ type: 'pcb_board', width: 20 })
  })

  it('round-trips: drag and read back produce valid Circuit JSON', () => {
    const patched = dragWireSegment(BASE_CIRCUIT, 't2', 0, { x: 5, y: 2.5 })
    // Should still be a valid flat array with type fields
    expect(Array.isArray(patched)).toBe(true)
    for (const el of patched) {
      expect(el).toHaveProperty('type')
    }
    const trace = patched.find((e) => e.pcb_trace_id === 't2')
    expect(trace.route.every((pt) => typeof pt.x === 'number' && typeof pt.y === 'number')).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// nudgeWireAnchor
// ---------------------------------------------------------------------------

describe('nudgeWireAnchor', () => {
  // Create a trace with an interior anchor at index 1
  function circuitWithAnchor() {
    return dragWireSegment(BASE_CIRCUIT, 't2', 0, { x: 5, y: 2 })
  }

  it('nudges anchor up', () => {
    const patched = nudgeWireAnchor(circuitWithAnchor(), 't2', 1, 'up', 0.5)
    const trace = patched.find((e) => e.pcb_trace_id === 't2')
    expect(trace.route[1].y).toBe(1.5)
  })

  it('nudges anchor down', () => {
    const patched = nudgeWireAnchor(circuitWithAnchor(), 't2', 1, 'down', 0.5)
    const trace = patched.find((e) => e.pcb_trace_id === 't2')
    expect(trace.route[1].y).toBe(2.5)
  })

  it('nudges anchor left', () => {
    const patched = nudgeWireAnchor(circuitWithAnchor(), 't2', 1, 'left', 0.5)
    const trace = patched.find((e) => e.pcb_trace_id === 't2')
    expect(trace.route[1].x).toBe(4.5)
  })

  it('nudges anchor right', () => {
    const patched = nudgeWireAnchor(circuitWithAnchor(), 't2', 1, 'right', 1.0)
    const trace = patched.find((e) => e.pcb_trace_id === 't2')
    expect(trace.route[1].x).toBe(6)
  })

  it('does not move endpoint anchors (index 0)', () => {
    const before = circuitWithAnchor()
    const patched = nudgeWireAnchor(before, 't2', 0, 'up', 1)
    expect(patched).toEqual(before)
  })

  it('does not move last endpoint', () => {
    const c = circuitWithAnchor()
    const lastIndex = c.find((e) => e.pcb_trace_id === 't2').route.length - 1
    const patched = nudgeWireAnchor(c, 't2', lastIndex, 'up', 1)
    expect(patched).toEqual(c)
  })
})

// ---------------------------------------------------------------------------
// deleteWire
// ---------------------------------------------------------------------------

describe('deleteWire', () => {
  it('removes the specified trace', () => {
    const patched = deleteWire(BASE_CIRCUIT, 't1')
    expect(patched.find((e) => e.pcb_trace_id === 't1')).toBeUndefined()
  })

  it('leaves other traces intact', () => {
    const patched = deleteWire(BASE_CIRCUIT, 't1')
    expect(patched.find((e) => e.pcb_trace_id === 't2')).toBeDefined()
  })

  it('does not mutate the original', () => {
    const original = [...BASE_CIRCUIT]
    deleteWire(BASE_CIRCUIT, 't1')
    expect(BASE_CIRCUIT).toHaveLength(original.length)
  })

  it('returns the same array if traceId is not found', () => {
    const patched = deleteWire(BASE_CIRCUIT, 'nonexistent')
    expect(patched).toHaveLength(BASE_CIRCUIT.length)
  })
})

// ---------------------------------------------------------------------------
// rerouteWire
// ---------------------------------------------------------------------------

describe('rerouteWire', () => {
  it('replaces interior anchors with a single L-route elbow', () => {
    // Give TRACE_L some extra interior anchors first
    const messy = makeTrace('t3', [
      { x: 0, y: 0 },
      { x: 1, y: 3 },
      { x: 3, y: 1 },
      { x: 4, y: 4 },
      { x: 4, y: 0 },
    ])
    const circuit = [messy]
    const patched = rerouteWire(circuit, 't3')
    const trace = patched.find((e) => e.pcb_trace_id === 't3')
    // Should be exactly 3 points: start, elbow, end
    expect(trace.route).toHaveLength(3)
    // Endpoints preserved
    expect(trace.route[0]).toEqual({ x: 0, y: 0 })
    expect(trace.route[2]).toEqual({ x: 4, y: 0 })
    // Elbow is at (end.x, start.y) = (4, 0) — degenerate collinear case
    // For non-degenerate:
    const messy2 = makeTrace('t4', [
      { x: 0, y: 0 },
      { x: 2, y: 3 },
      { x: 5, y: 5 },
    ])
    const c2 = [messy2]
    const p2 = rerouteWire(c2, 't4')
    const tr2 = p2.find((e) => e.pcb_trace_id === 't4')
    expect(tr2.route).toHaveLength(3)
    expect(tr2.route[0]).toEqual({ x: 0, y: 0 })
    expect(tr2.route[2]).toEqual({ x: 5, y: 5 })
    // Elbow = (end.x, start.y) = (5, 0)
    expect(tr2.route[1]).toEqual({ x: 5, y: 0 })
  })

  it('returns the circuit unchanged for traces with fewer than 2 points', () => {
    const short = makeTrace('t5', [{ x: 0, y: 0 }])
    const circuit = [short]
    const patched = rerouteWire(circuit, 't5')
    expect(patched[0]).toEqual(short)
  })
})

// ---------------------------------------------------------------------------
// pinWireToGrid
// ---------------------------------------------------------------------------

describe('pinWireToGrid', () => {
  it('snaps interior anchors to grid, leaves endpoints unchanged', () => {
    const trace = makeTrace('t6', [
      { x: 0.13, y: 0.23 },   // endpoint — must not snap
      { x: 1.3, y: 2.7 },     // interior — should snap to 0.5 grid
      { x: 3.1, y: 0.1 },     // interior — should snap
      { x: 5.0, y: 5.0 },     // endpoint — must not snap
    ])
    const patched = pinWireToGrid([trace], 't6', 0.5)
    const tr = patched[0]
    // Endpoints unchanged
    expect(tr.route[0]).toEqual({ x: 0.13, y: 0.23 })
    expect(tr.route[3]).toEqual({ x: 5.0, y: 5.0 })
    // Interior point 1: (1.3→1.5, 2.7→2.5)
    expect(tr.route[1].x).toBe(1.5)
    expect(tr.route[1].y).toBe(2.5)
    // Interior point 2: (3.1→3.0, 0.1→0.0)
    expect(tr.route[2].x).toBe(3.0)
    expect(tr.route[2].y).toBe(0.0)
  })
})

// ---------------------------------------------------------------------------
// beginWireDrag — stateful drag session
// ---------------------------------------------------------------------------

describe('beginWireDrag', () => {
  it('returns a session with move/end/traceId/segIndex', () => {
    const hit = { traceId: 't2', segIndex: 0, t: 0.5, dist: 0.05 }
    const session = beginWireDrag(BASE_CIRCUIT, hit)
    expect(session).toHaveProperty('move')
    expect(session).toHaveProperty('end')
    expect(session.traceId).toBe('t2')
    expect(session.segIndex).toBe(0)
  })

  it('move() inserts an anchor and updates it on subsequent calls', () => {
    const hit = { traceId: 't2', segIndex: 0, t: 0.5, dist: 0.05 }
    const session = beginWireDrag(BASE_CIRCUIT, hit, { grid: 0.5 })

    // First move — inserts anchor
    const step1 = session.move(BASE_CIRCUIT, { x: 5, y: 3 })
    const tr1 = step1.find((e) => e.pcb_trace_id === 't2')
    expect(tr1.route).toHaveLength(3)
    expect(tr1.route[1].y).toBe(3)

    // Second move — updates the same anchor (no extra insertion)
    const step2 = session.move(step1, { x: 5, y: 4 })
    const tr2 = step2.find((e) => e.pcb_trace_id === 't2')
    expect(tr2.route).toHaveLength(3)
    expect(tr2.route[1].y).toBe(4)
  })

  it('end() finalises at the released position', () => {
    const hit = { traceId: 't2', segIndex: 0, t: 0.5, dist: 0.05 }
    const session = beginWireDrag(BASE_CIRCUIT, hit, { grid: 0.5 })
    const step1 = session.move(BASE_CIRCUIT, { x: 5, y: 3 })
    const final = session.end(step1, { x: 5, y: 3.7 })
    const tr = final.find((e) => e.pcb_trace_id === 't2')
    expect(tr.route[1].y).toBeCloseTo(3.5, 5)  // snapped
  })

  it('circuit round-trips: result is valid Circuit JSON', () => {
    const hit = { traceId: 't2', segIndex: 0, t: 0.5, dist: 0.05 }
    const session = beginWireDrag(BASE_CIRCUIT, hit)
    const result = session.end(BASE_CIRCUIT, { x: 5, y: 4 })
    expect(Array.isArray(result)).toBe(true)
    for (const el of result) {
      expect(el).toHaveProperty('type')
    }
    const trace = result.find((e) => e.pcb_trace_id === 't2')
    expect(trace.route.every((pt) => Number.isFinite(pt.x) && Number.isFinite(pt.y))).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Context-menu action round-trip
// ---------------------------------------------------------------------------

describe('context-menu action patches', () => {
  it('delete returns correct patch (trace removed)', () => {
    const patch = deleteWire(BASE_CIRCUIT, 't1')
    expect(patch.every((e) => e.pcb_trace_id !== 't1')).toBe(true)
    expect(patch).toHaveLength(BASE_CIRCUIT.length - 1)
  })

  it('re-route returns correct patch (L-route)', () => {
    const patch = rerouteWire(BASE_CIRCUIT, 't1')
    const trace = patch.find((e) => e.pcb_trace_id === 't1')
    // Original TRACE_L already has 3 points; re-route rebuilds as 3 points with orthogonal elbow
    expect(trace.route).toHaveLength(3)
    // Elbow should be at (end.x, start.y)
    const start = { x: 0, y: 0 }
    const end = { x: 5, y: 5 }
    expect(trace.route[1]).toEqual({ x: end.x, y: start.y })
  })

  it('pin returns correct patch (interior anchors on grid)', () => {
    // Give a trace a messy interior anchor
    const messy = makeTrace('t7', [
      { x: 0, y: 0 },
      { x: 1.3, y: 2.7 },
      { x: 5, y: 5 },
    ])
    const patch = pinWireToGrid([messy], 't7', 0.5)
    const tr = patch[0]
    expect(tr.route[1].x).toBe(1.5)
    expect(tr.route[1].y).toBe(2.5)
    // Endpoints untouched
    expect(tr.route[0]).toEqual({ x: 0, y: 0 })
    expect(tr.route[2]).toEqual({ x: 5, y: 5 })
  })
})
