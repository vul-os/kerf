// wireEdit.ts — Pure-logic wire drag + nudge for Circuit JSON editing.
//
// No React or browser imports — safe in vitest and workers.
//
// TODO(parent): wire into <CircuitCanvas> via the existing drag-handler dispatch
//
// Circuit JSON wire format (pcb_trace):
//   {
//     type: 'pcb_trace',
//     pcb_trace_id: string,
//     route: Array<{ x: number, y: number, route_type?: 'wire'|'via', layer?: string }>,
//     route_thickness_mm?: number,
//     source_trace_id?: string,
//     connected_source_port_ids?: string[],
//   }
//
// All coordinates are in millimetres (PCB space).
//
// See circuitCanvasTypes.ts's header comment for why this module's element/point types
// (`PcbElementArray`/`PcbTraceLike`/`TraceRoutePoint`) are looser than the real
// `CircuitJson`/`CircuitElement` seam in `src/types` — real Circuit JSON values are
// structurally compatible with the types used here, but the reverse isn't true.

import type {
  PcbPoint, PcbElementArray, PcbTraceLike, TraceRoutePoint,
  WireHit, DragWireOpts, WireDragSession, NudgeDirection,
} from './circuitCanvasTypes'

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

/** Squared distance between two points. */
function dist2Sq(a: PcbPoint, b: PcbPoint): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  return dx * dx + dy * dy
}

/**
 * Point-to-segment distance.  Returns the distance from point `p` to the
 * line segment [a, b], plus the parameter `t` (0..1) of the closest point.
 */
export function pointSegmentDist(p: PcbPoint, a: PcbPoint, b: PcbPoint): { dist: number; t: number; closest: PcbPoint } {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) {
    const d = Math.sqrt(dist2Sq(p, a))
    return { dist: d, t: 0, closest: { x: a.x, y: a.y } }
  }
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq))
  const closest = { x: a.x + t * dx, y: a.y + t * dy }
  const dist = Math.sqrt(dist2Sq(p, closest))
  return { dist, t, closest }
}

/** Round a value to the nearest grid step (default 0.5mm). */
export function snapToGrid(v: number, grid = 0.5): number {
  return Math.round(v / grid) * grid
}

/** Snap a point to the grid. */
export function snapPoint(pt: PcbPoint, grid = 0.5): PcbPoint {
  return { x: snapToGrid(pt.x, grid), y: snapToGrid(pt.y, grid) }
}

// ---------------------------------------------------------------------------
// Hit testing
// ---------------------------------------------------------------------------

/**
 * Hit-test a point against all pcb_trace segments in a Circuit JSON array.
 * Returns the closest hit within `threshold` mm, or null.
 */
export function hitTestWire(circuitJson: PcbElementArray, point: PcbPoint, threshold = 0.3): WireHit | null {
  if (!Array.isArray(circuitJson)) return null

  let best: WireHit | null = null

  for (const el of circuitJson) {
    if (el?.type !== 'pcb_trace') continue
    const route = el.route ?? el.points ?? []
    if (route.length < 2) continue
    const id = el.pcb_trace_id ?? el.id ?? ''

    for (let i = 0; i < route.length - 1; i++) {
      const a = route[i]
      const b = route[i + 1]
      const { dist, t } = pointSegmentDist(point, a, b)
      if (dist <= threshold) {
        if (!best || dist < best.dist) {
          best = { traceId: id, segIndex: i, t, dist }
        }
      }
    }
  }

  return best
}

// ---------------------------------------------------------------------------
// Wire drag — move a segment's midpoint anchor
// ---------------------------------------------------------------------------

/**
 * Apply a pointer-drag to a wire segment.  The drag moves the segment
 * perpendicularly (orthogonal nudge) by inserting / updating a midpoint
 * anchor, keeping the wire's two adjacent points fixed.
 *
 * The segment [route[segIndex], route[segIndex+1]] is replaced by two
 * shorter segments connected through a new anchor at `newMidpoint`.
 *
 * If `anchorIndex` is provided (a prior midpoint is being dragged), that
 * point is moved instead of inserting a new one.
 *
 * @returns patched Circuit JSON (new array, trace object replaced)
 */
export function dragWireSegment(
  circuitJson: PcbElementArray,
  traceId: string,
  segIndex: number,
  newMidpoint: PcbPoint,
  opts: DragWireOpts = {},
): PcbElementArray {
  const { anchorIndex, grid = 0.5 } = opts

  if (!Array.isArray(circuitJson)) return circuitJson

  const snapped = snapPoint(newMidpoint, grid)

  return circuitJson.map((el): PcbTraceLike => {
    const id = el?.pcb_trace_id ?? el?.id
    if (el?.type !== 'pcb_trace' || id !== traceId) return el

    const route: TraceRoutePoint[] = (el.route ?? el.points ?? []).map((pt) => ({ ...pt }))

    if (anchorIndex !== undefined && anchorIndex > 0 && anchorIndex < route.length - 1) {
      // Move an existing interior anchor point.
      route[anchorIndex] = { ...route[anchorIndex], x: snapped.x, y: snapped.y }
    } else {
      // Insert a new midpoint anchor after route[segIndex].
      const insertAt = segIndex + 1
      if (insertAt < 0 || insertAt > route.length) return el
      route.splice(insertAt, 0, { x: snapped.x, y: snapped.y })
    }

    const routeKey = el.route ? 'route' : 'points'
    return { ...el, [routeKey]: route }
  })
}

// ---------------------------------------------------------------------------
// Wire nudge — keyboard-driven orthogonal nudge of an interior anchor
// ---------------------------------------------------------------------------

/**
 * Nudge a wire anchor point by `delta` in mm.
 * `direction` is 'up'|'down'|'left'|'right'.
 */
export function nudgeWireAnchor(
  circuitJson: PcbElementArray,
  traceId: string,
  anchorIndex: number,
  direction: NudgeDirection,
  delta = 0.5,
): PcbElementArray {
  if (!Array.isArray(circuitJson)) return circuitJson

  const dx = direction === 'left' ? -delta : direction === 'right' ? delta : 0
  const dy = direction === 'up' ? -delta : direction === 'down' ? delta : 0

  return circuitJson.map((el): PcbTraceLike => {
    const id = el?.pcb_trace_id ?? el?.id
    if (el?.type !== 'pcb_trace' || id !== traceId) return el

    const route: TraceRoutePoint[] = (el.route ?? el.points ?? []).map((pt) => ({ ...pt }))
    if (anchorIndex <= 0 || anchorIndex >= route.length - 1) return el

    route[anchorIndex] = {
      ...route[anchorIndex],
      x: route[anchorIndex].x + dx,
      y: route[anchorIndex].y + dy,
    }

    const routeKey = el.route ? 'route' : 'points'
    return { ...el, [routeKey]: route }
  })
}

// ---------------------------------------------------------------------------
// Context-menu actions
// ---------------------------------------------------------------------------

/** Delete a wire from the Circuit JSON. */
export function deleteWire(circuitJson: PcbElementArray, traceId: string): PcbElementArray {
  if (!Array.isArray(circuitJson)) return circuitJson
  return circuitJson.filter((el) => {
    const id = el?.pcb_trace_id ?? el?.id
    return !(el?.type === 'pcb_trace' && id === traceId)
  })
}

/**
 * Re-route a wire using a simple L-shaped (orthogonal) path between its
 * first and last route points.  All interior anchors are discarded and
 * replaced with a single elbow at (end.x, start.y).
 */
export function rerouteWire(circuitJson: PcbElementArray, traceId: string): PcbElementArray {
  if (!Array.isArray(circuitJson)) return circuitJson

  return circuitJson.map((el): PcbTraceLike => {
    const id = el?.pcb_trace_id ?? el?.id
    if (el?.type !== 'pcb_trace' || id !== traceId) return el

    const route = el.route ?? el.points ?? []
    if (route.length < 2) return el

    const start = route[0]
    const end = route[route.length - 1]

    // Build an orthogonal L-route: start → elbow → end.
    // Elbow is at (end.x, start.y) — horizontal-first routing convention.
    const elbow = { x: end.x, y: start.y }
    const newRoute = [{ ...start }, elbow, { ...end }]

    const routeKey = el.route ? 'route' : 'points'
    return { ...el, [routeKey]: newRoute }
  })
}

/**
 * Pin a wire's interior anchors to the grid.  All points except first and
 * last are snapped to the nearest grid position.
 */
export function pinWireToGrid(circuitJson: PcbElementArray, traceId: string, grid = 0.5): PcbElementArray {
  if (!Array.isArray(circuitJson)) return circuitJson

  return circuitJson.map((el): PcbTraceLike => {
    const id = el?.pcb_trace_id ?? el?.id
    if (el?.type !== 'pcb_trace' || id !== traceId) return el

    const route = el.route ?? el.points ?? []
    if (route.length < 2) return el

    const newRoute = route.map((pt, i) => {
      if (i === 0 || i === route.length - 1) return { ...pt }
      return { ...pt, ...snapPoint(pt, grid) }
    })

    const routeKey = el.route ? 'route' : 'points'
    return { ...el, [routeKey]: newRoute }
  })
}

// ---------------------------------------------------------------------------
// Pointer-event helpers  (framework-agnostic)
// ---------------------------------------------------------------------------

/**
 * Stateful drag session.  Create one on pointerdown, call `move` on
 * pointermove, call `end` on pointerup.  Returns patched Circuit JSON at
 * each step without mutating the original.
 *
 * Usage:
 *   const session = beginWireDrag(circuitJson, hit)
 *   // on each pointermove:
 *   const next = session.move(circuitJson, { x, y })
 *   // on pointerup:
 *   const final = session.end(circuitJson, { x, y })
 */
export function beginWireDrag(
  circuitJson: PcbElementArray,
  hit: { traceId: string; segIndex: number },
  opts: { grid?: number } = {},
): WireDragSession {
  const { grid = 0.5 } = opts
  const { traceId, segIndex } = hit

  // Find the trace and record the anchor index that will be created or moved.
  // If the hit midpoint is already an existing interior point we reuse it;
  // otherwise we insert a new anchor at segIndex+1 on the first move.
  let anchorIndex: number | null = null  // determined lazily on first move

  function apply(json: PcbElementArray, point: PcbPoint): PcbElementArray {
    const snap = snapPoint(point, grid)

    if (anchorIndex === null) {
      // First move: insert anchor and record its index.
      const patched = dragWireSegment(json, traceId, segIndex, snap, { grid })
      // The new anchor is always at segIndex+1 after insertion.
      anchorIndex = segIndex + 1
      return patched
    }

    return dragWireSegment(json, traceId, segIndex, snap, { anchorIndex, grid })
  }

  return {
    traceId,
    segIndex,
    move(json, point) { return apply(json, point) },
    end(json, point) { return apply(json, point) },
  }
}
