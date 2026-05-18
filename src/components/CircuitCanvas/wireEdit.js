// wireEdit.js — Pure-logic wire drag + nudge for Circuit JSON editing.
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

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

/**
 * Squared distance between two points.
 * @param {{x:number,y:number}} a
 * @param {{x:number,y:number}} b
 * @returns {number}
 */
function dist2Sq(a, b) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  return dx * dx + dy * dy
}

/**
 * Point-to-segment distance.  Returns the distance from point `p` to the
 * line segment [a, b], plus the parameter `t` (0..1) of the closest point.
 * @param {{x:number,y:number}} p
 * @param {{x:number,y:number}} a
 * @param {{x:number,y:number}} b
 * @returns {{ dist: number, t: number, closest: {x:number,y:number} }}
 */
export function pointSegmentDist(p, a, b) {
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

/**
 * Round a value to the nearest grid step.
 * @param {number} v
 * @param {number} grid — grid pitch in mm (default 0.5)
 * @returns {number}
 */
export function snapToGrid(v, grid = 0.5) {
  return Math.round(v / grid) * grid
}

/**
 * Snap a point to the grid.
 * @param {{x:number,y:number}} pt
 * @param {number} grid
 * @returns {{x:number,y:number}}
 */
export function snapPoint(pt, grid = 0.5) {
  return { x: snapToGrid(pt.x, grid), y: snapToGrid(pt.y, grid) }
}

// ---------------------------------------------------------------------------
// Hit testing
// ---------------------------------------------------------------------------

/**
 * Hit-test a point against all pcb_trace segments in a Circuit JSON array.
 * Returns the closest hit within `threshold` mm, or null.
 *
 * @param {Array} circuitJson — flat AnyCircuitElement[]
 * @param {{x:number,y:number}} point — pointer position in PCB mm space
 * @param {number} threshold — pick radius in mm (default 0.3)
 * @returns {{ traceId: string, segIndex: number, t: number, dist: number } | null}
 */
export function hitTestWire(circuitJson, point, threshold = 0.3) {
  if (!Array.isArray(circuitJson)) return null

  let best = null

  for (const el of circuitJson) {
    if (el?.type !== 'pcb_trace') continue
    const route = el.route ?? el.points ?? []
    if (route.length < 2) continue
    const id = el.pcb_trace_id ?? el.id

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
 * @param {Array} circuitJson — Circuit JSON to patch (not mutated)
 * @param {string} traceId
 * @param {number} segIndex — segment index within trace.route
 * @param {{x:number,y:number}} newMidpoint — new midpoint in PCB mm space
 * @param {{ anchorIndex?: number, grid?: number }} [opts]
 * @returns {Array} patched Circuit JSON (new array, trace object replaced)
 */
export function dragWireSegment(circuitJson, traceId, segIndex, newMidpoint, opts = {}) {
  const { anchorIndex, grid = 0.5 } = opts

  if (!Array.isArray(circuitJson)) return circuitJson

  const snapped = snapPoint(newMidpoint, grid)

  return circuitJson.map((el) => {
    const id = el?.pcb_trace_id ?? el?.id
    if (el?.type !== 'pcb_trace' || id !== traceId) return el

    const route = (el.route ?? el.points ?? []).map((pt) => ({ ...pt }))

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
 *
 * @param {Array} circuitJson
 * @param {string} traceId
 * @param {number} anchorIndex — index within route (must be > 0 and < route.length-1)
 * @param {'up'|'down'|'left'|'right'} direction
 * @param {number} delta — step size in mm (default 0.5)
 * @returns {Array} patched Circuit JSON
 */
export function nudgeWireAnchor(circuitJson, traceId, anchorIndex, direction, delta = 0.5) {
  if (!Array.isArray(circuitJson)) return circuitJson

  const dx = direction === 'left' ? -delta : direction === 'right' ? delta : 0
  const dy = direction === 'up' ? -delta : direction === 'down' ? delta : 0

  return circuitJson.map((el) => {
    const id = el?.pcb_trace_id ?? el?.id
    if (el?.type !== 'pcb_trace' || id !== traceId) return el

    const route = (el.route ?? el.points ?? []).map((pt) => ({ ...pt }))
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

/**
 * Delete a wire from the Circuit JSON.
 *
 * @param {Array} circuitJson
 * @param {string} traceId
 * @returns {Array} patched Circuit JSON (trace removed)
 */
export function deleteWire(circuitJson, traceId) {
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
 *
 * @param {Array} circuitJson
 * @param {string} traceId
 * @returns {Array} patched Circuit JSON
 */
export function rerouteWire(circuitJson, traceId) {
  if (!Array.isArray(circuitJson)) return circuitJson

  return circuitJson.map((el) => {
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
 *
 * @param {Array} circuitJson
 * @param {string} traceId
 * @param {number} grid — grid pitch in mm (default 0.5)
 * @returns {Array} patched Circuit JSON
 */
export function pinWireToGrid(circuitJson, traceId, grid = 0.5) {
  if (!Array.isArray(circuitJson)) return circuitJson

  return circuitJson.map((el) => {
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
 *
 * @param {Array} circuitJson — snapshot at drag-start
 * @param {{ traceId: string, segIndex: number }} hit — result from hitTestWire
 * @param {{ grid?: number }} [opts]
 * @returns {{ move: Function, end: Function, traceId: string, segIndex: number }}
 */
export function beginWireDrag(circuitJson, hit, opts = {}) {
  const { grid = 0.5 } = opts
  const { traceId, segIndex } = hit

  // Find the trace and record the anchor index that will be created or moved.
  // If the hit midpoint is already an existing interior point we reuse it;
  // otherwise we insert a new anchor at segIndex+1 on the first move.
  let anchorIndex = null  // determined lazily on first move

  function apply(json, point) {
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
