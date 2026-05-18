// pcbRouting.js — Pure geometry helpers for manual PCB trace routing.
// No React or browser imports — safe to use in vitest and workers.

// ─── Internal geometry primitives ────────────────────────────────────────────

function dist2(a, b) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  return Math.sqrt(dx * dx + dy * dy)
}

// ─── segSegMinDist ─────────────────────────────────────────────────────────────

/**
 * Minimum distance between two line segments [a1,a2] and [b1,b2].
 * Returns 0 when they intersect.
 *
 * @param {{x:number,y:number}} a1
 * @param {{x:number,y:number}} a2
 * @param {{x:number,y:number}} b1
 * @param {{x:number,y:number}} b2
 * @returns {number}
 */
export function segSegMinDist(a1, a2, b1, b2) {
  const dx1 = a2.x - a1.x, dy1 = a2.y - a1.y
  const dx2 = b2.x - b1.x, dy2 = b2.y - b1.y
  const cx = b1.x - a1.x, cy = b1.y - a1.y
  const len1sq = dx1 * dx1 + dy1 * dy1
  const len2sq = dx2 * dx2 + dy2 * dy2

  function ptSegDist(p, a, b) {
    const ddx = b.x - a.x, ddy = b.y - a.y
    const lsq = ddx * ddx + ddy * ddy
    if (lsq === 0) return dist2(p, a)
    const t = Math.max(0, Math.min(1, ((p.x - a.x) * ddx + (p.y - a.y) * ddy) / lsq))
    return dist2(p, { x: a.x + t * ddx, y: a.y + t * ddy })
  }

  if (len1sq === 0 && len2sq === 0) return dist2(a1, b1)
  if (len1sq === 0) return ptSegDist(a1, b1, b2)
  if (len2sq === 0) return ptSegDist(b1, a1, a2)

  const det = dx1 * dy2 - dy1 * dx2
  if (Math.abs(det) > 1e-12) {
    const t = (cx * dy2 - cy * dx2) / det
    const u = (cx * dy1 - cy * dx1) / det
    if (t >= 0 && t <= 1 && u >= 0 && u <= 1) return 0
  }

  return Math.min(
    ptSegDist(a1, b1, b2),
    ptSegDist(a2, b1, b2),
    ptSegDist(b1, a1, a2),
    ptSegDist(b2, a1, a2),
  )
}

// ─── diff-pair geometry ───────────────────────────────────────────────────────

/**
 * Offset a polyline of {x,y} points perpendicularly by `offset` mm.
 * Uses the CCW perpendicular of each segment; at corners the offset vector is
 * the average of the two adjacent normals (miter approximation).
 *
 * @param {Array<{x:number,y:number}>} points
 * @param {number} offset   positive = CCW (left), negative = CW (right)
 * @returns {Array<{x:number,y:number}>}
 */
export function offsetPolyline(points, offset) {
  const n = points.length
  if (n < 2) return points.map(p => ({ ...p }))

  // Per-segment perpendicular unit vectors (CCW)
  const perps = []
  for (let i = 0; i < n - 1; i++) {
    const dx = points[i + 1].x - points[i].x
    const dy = points[i + 1].y - points[i].y
    const len = Math.sqrt(dx * dx + dy * dy) || 1
    perps.push({ x: -dy / len, y: dx / len })
  }

  return points.map((pt, i) => {
    let px, py
    if (i === 0) {
      px = perps[0].x; py = perps[0].y
    } else if (i === n - 1) {
      px = perps[n - 2].x; py = perps[n - 2].y
    } else {
      px = (perps[i - 1].x + perps[i].x) / 2
      py = (perps[i - 1].y + perps[i].y) / 2
      const mag = Math.sqrt(px * px + py * py) || 1
      px /= mag; py /= mag
    }
    return { x: pt.x + px * offset, y: pt.y + py * offset }
  })
}

/**
 * Route a differential pair from `start` to `end` along a centreline path.
 * Returns `{ pos, neg }` — two arrays of {x,y} points for P and N conductors.
 *
 * The centreline is constructed as an L-route (horizontal-first then vertical)
 * when start and end are not collinear, giving deterministic geometry.
 *
 * @param {{x:number,y:number}} start
 * @param {{x:number,y:number}} end
 * @param {number} spacingMm  edge-to-edge coupling gap in mm
 * @returns {{ pos: Array<{x,y}>, neg: Array<{x,y}>, centreline: Array<{x,y}> }}
 */
export function routeDiffPairCentreline(start, end, spacingMm) {
  const half = spacingMm / 2
  const dx = end.x - start.x
  const dy = end.y - start.y

  let centreline
  if (Math.abs(dx) < 1e-9 || Math.abs(dy) < 1e-9) {
    centreline = [{ ...start }, { ...end }]
  } else {
    centreline = [{ ...start }, { x: end.x, y: start.y }, { ...end }]
  }

  return {
    pos: offsetPolyline(centreline, +half),
    neg: offsetPolyline(centreline, -half),
    centreline,
  }
}

/**
 * Compute total polyline arc-length for an array of {x,y} points.
 *
 * @param {Array<{x:number,y:number}>} pts
 * @returns {number} length in mm
 */
export function polylineLength(pts) {
  let len = 0
  for (let i = 1; i < pts.length; i++) len += dist2(pts[i - 1], pts[i])
  return len
}

/**
 * Shove existing traces to respect `clearanceMm` + half-width of each side
 * when a new diff-pair segment is being dragged through the board.
 *
 * Only traces on the same `layer` and different `netId` are displaced.
 * The shove translates each offending trace perpendicularly away from the
 * new centreline by the penetration distance (up to `maxPasses` iterations
 * to handle cascading shoves).
 *
 * @param {Array<{id:string, netId:string, layer:string, widthMm:number, points:Array<{x,y}>}>} traces
 * @param {{x:number,y:number}} segStart  new segment start (centreline)
 * @param {{x:number,y:number}} segEnd    new segment end (centreline)
 * @param {string} layer
 * @param {string[]} diffPairNetIds  [netPos, netNeg] — excluded from shove
 * @param {number} clearanceMm
 * @param {number} newWidthMm       half-widths of the new P and N traces
 * @param {number} [maxPasses=4]
 * @returns {{ traces: Array<object>, shovedIds: string[] }}
 */
export function shovePairClearance(
  traces,
  segStart,
  segEnd,
  layer,
  diffPairNetIds,
  clearanceMm,
  newWidthMm,
  maxPasses = 4,
) {
  // Deep-clone so callers' arrays are not mutated.
  let working = traces.map(t => ({ ...t, points: t.points.map(p => ({ ...p })) }))
  const shovedIds = []

  for (let pass = 0; pass < maxPasses; pass++) {
    let changed = false

    for (let i = 0; i < working.length; i++) {
      const tr = working[i]
      if (tr.layer !== layer) continue
      if (diffPairNetIds.includes(tr.netId)) continue

      const trWidth = tr.widthMm ?? 0.25
      const requiredGap = clearanceMm + newWidthMm / 2 + trWidth / 2

      // Check every segment of the trace against the new segment.
      const pts = tr.points
      let minDist = Infinity
      for (let k = 0; k < pts.length - 1; k++) {
        const d = segSegMinDist(segStart, segEnd, pts[k], pts[k + 1])
        if (d < minDist) minDist = d
      }

      if (minDist >= requiredGap - 1e-9) continue

      const penetration = requiredGap - minDist

      // Shove perpendicular to new segment.
      const dx = segEnd.x - segStart.x
      const dy = segEnd.y - segStart.y
      const len = Math.sqrt(dx * dx + dy * dy) || 1
      const px = -dy / len   // CCW perp
      const py = dx / len

      // Determine which side of the new segment the trace centre sits.
      const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length
      const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length
      const mx = (segStart.x + segEnd.x) / 2
      const my = (segStart.y + segEnd.y) / 2
      const sign = ((cx - mx) * px + (cy - my) * py) >= 0 ? 1 : -1

      const shoveX = px * sign * penetration
      const shoveY = py * sign * penetration

      working[i] = {
        ...tr,
        points: tr.points.map(p => ({ x: p.x + shoveX, y: p.y + shoveY })),
      }
      if (!shovedIds.includes(tr.id)) shovedIds.push(tr.id)
      changed = true
    }

    if (!changed) break
  }

  return { traces: working, shovedIds }
}

/**
 * Adjust the length of a diff-pair arm (array of points) by inserting a
 * one-tooth serpentine meander on the longest segment.  Adds approximately
 * `extraMm` mm of arc length.
 *
 * @param {Array<{x:number,y:number}>} pts
 * @param {number} extraMm
 * @param {number} [amplitude=0.5]  meander half-width in mm
 * @returns {Array<{x:number,y:number}>}
 */
export function insertMeanderPoints(pts, extraMm, amplitude = 0.5) {
  if (!pts || pts.length < 2 || extraMm < 1e-6) return pts

  // Find longest segment.
  let bestI = 0, bestLen = 0
  for (let i = 0; i < pts.length - 1; i++) {
    const l = dist2(pts[i], pts[i + 1])
    if (l > bestLen) { bestLen = l; bestI = i }
  }

  const a = pts[bestI], b = pts[bestI + 1]
  const dx = b.x - a.x, dy = b.y - a.y
  const segLen = Math.sqrt(dx * dx + dy * dy) || 1
  const ux = dx / segLen, uy = dy / segLen
  const px = -uy, py = ux   // CCW perp

  const extraPerTooth = 2 * amplitude
  const nTeeth = Math.max(1, Math.ceil(extraMm / extraPerTooth))

  const newPts = [{ ...a }]
  let sign = 1
  for (let i = 0; i < nTeeth; i++) {
    const t0 = i / nTeeth
    const t1 = (i + 0.5) / nTeeth
    const t2 = (i + 1) / nTeeth
    // start of tooth
    newPts.push({
      x: a.x + ux * segLen * t0, y: a.y + uy * segLen * t0,
    })
    // peak
    newPts.push({
      x: a.x + ux * segLen * t1 + px * amplitude * sign,
      y: a.y + uy * segLen * t1 + py * amplitude * sign,
    })
    // end of tooth
    newPts.push({
      x: a.x + ux * segLen * t2, y: a.y + uy * segLen * t2,
    })
    sign = -sign
  }
  newPts.push({ ...b })

  // Deduplicate within 1e-9.
  const deduped = [newPts[0]]
  for (let i = 1; i < newPts.length; i++) {
    if (dist2(deduped[deduped.length - 1], newPts[i]) > 1e-9) deduped.push(newPts[i])
  }

  return [...pts.slice(0, bestI), ...deduped, ...pts.slice(bestI + 2)]
}

/**
 * Length-match two diff-pair arms so |lenPos − lenNeg| ≤ skewToleranceMm.
 * Inserts a serpentine on the shorter arm.
 *
 * @param {Array<{x,y}>} posPoints
 * @param {Array<{x,y}>} negPoints
 * @param {number} [skewToleranceMm=0.05]
 * @param {number} [amplitude=0.5]
 * @returns {{ pos: Array<{x,y}>, neg: Array<{x,y}>, skewMm: number }}
 */
export function diffPairLengthMatch(posPoints, negPoints, skewToleranceMm = 0.05, amplitude = 0.5) {
  const lenPos = polylineLength(posPoints)
  const lenNeg = polylineLength(negPoints)
  let pos = posPoints, neg = negPoints

  const delta = lenPos - lenNeg
  if (Math.abs(delta) > skewToleranceMm) {
    if (delta > 0) {
      // pos is longer — lengthen neg
      neg = insertMeanderPoints(neg, delta, amplitude)
    } else {
      // neg is longer — lengthen pos
      pos = insertMeanderPoints(pos, -delta, amplitude)
    }
  }

  return {
    pos,
    neg,
    skewMm: Math.abs(polylineLength(pos) - polylineLength(neg)),
  }
}

function ptEq(a, b, tol = 1e-9) {
  return Math.abs(a.x - b.x) <= tol && Math.abs(a.y - b.y) <= tol
}

/**
 * Minimum distance from point p to segment [a, b].
 */
export function pointToSegmentDist(p, a, b) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) {
    return dist2(p, a)
  }
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq))
  return dist2(p, { x: a.x + t * dx, y: a.y + t * dy })
}

/**
 * Project p onto segment [a, b]; return the t parameter in [0,1].
 */
function projectOntoSegment(p, a, b) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return 0
  return Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq))
}

// ─── orthogonalSnap ───────────────────────────────────────────────────────────

/**
 * Snap p2 so the segment p1→p2 is horizontal or vertical.
 *
 * When `lastDirection` is provided, that axis is preferred in a tie.
 *
 * @param {{x: number, y: number}} p1
 * @param {{x: number, y: number}} p2
 * @param {'horizontal'|'vertical'|undefined} lastDirection
 * @returns {{ p2_snapped: {x: number, y: number}, direction: 'horizontal'|'vertical' }}
 */
export function orthogonalSnap(p1, p2, lastDirection) {
  // Guard: identical points
  if (!p1 || !p2) {
    const pt = p2 || p1 || { x: 0, y: 0 }
    return { p2_snapped: { x: pt.x, y: pt.y }, direction: lastDirection || 'horizontal' }
  }

  const dx = Math.abs(p2.x - p1.x)
  const dy = Math.abs(p2.y - p1.y)

  let direction
  if (dx > dy) {
    direction = 'horizontal'
  } else if (dy > dx) {
    direction = 'vertical'
  } else {
    // Tie — prefer lastDirection, else horizontal
    direction = lastDirection || 'horizontal'
  }

  const p2_snapped =
    direction === 'horizontal'
      ? { x: p2.x, y: p1.y }
      : { x: p1.x, y: p2.y }

  return { p2_snapped, direction }
}

// ─── corner45 ────────────────────────────────────────────────────────────────

/**
 * Generate a 45°-preferred two-segment route from p1 to p2.
 * Returns [mid, p2] where mid is the bend point that minimises total length.
 *
 * Special cases (already 45° or already axis-aligned) return [p2] — one
 * segment, no bend.
 *
 * Strategy: the bend can be placed at the "horizontal-first" position
 * (go 45° then straight in x) or the "vertical-first" position (go 45°
 * then straight in y). Pick whichever gives a shorter total path — they are
 * always equal in this scheme, so we use horizontal-first as default.
 *
 * @param {{x: number, y: number}} p1
 * @param {{x: number, y: number}} p2
 * @returns {Array<{x: number, y: number}>}
 */
export function corner45(p1, p2) {
  if (!p1 || !p2) return [p2 || p1 || { x: 0, y: 0 }]

  const dx = p2.x - p1.x
  const dy = p2.y - p1.y
  const adx = Math.abs(dx)
  const ady = Math.abs(dy)

  // Zero-length or already pure axis-aligned or already 45°
  if (adx === 0 || ady === 0 || adx === ady) {
    return [{ x: p2.x, y: p2.y }]
  }

  const sx = dx > 0 ? 1 : -1
  const sy = dy > 0 ? 1 : -1

  // Candidate A: 45° diagonal first, then straight along dominant axis
  // Candidate B: straight along recessive axis first, then 45° diagonal
  // Both have the same total length. We choose A (diagonal first) as default.

  let mid
  if (adx > ady) {
    // Longer in X — start 45°, then horizontal
    mid = { x: p1.x + sx * ady, y: p1.y + sy * ady }
  } else {
    // Longer in Y — start 45°, then vertical
    mid = { x: p1.x + sx * adx, y: p1.y + sy * adx }
  }

  return [mid, { x: p2.x, y: p2.y }]
}

// ─── freeRoute ────────────────────────────────────────────────────────────────

/**
 * Straight-line route from p1 to p2.
 *
 * @param {{x: number, y: number}} p1
 * @param {{x: number, y: number}} p2
 * @returns {Array<{x: number, y: number}>}
 */
export function freeRoute(p1, p2) {
  if (!p2) return []
  return [{ x: p2.x, y: p2.y }]
}

// ─── pickRoutingMode ──────────────────────────────────────────────────────────

/**
 * Dispatch to the correct routing helper based on `mode`.
 *
 * @param {'orthogonal'|'45'|'free'} mode
 * @param {{x: number, y: number}} p1
 * @param {{x: number, y: number}} p2
 * @param {'horizontal'|'vertical'|undefined} lastDirection  — passed through to orthogonalSnap
 * @returns {Array<{x: number, y: number}>|{ p2_snapped: {x,y}, direction: string }}
 */
export function pickRoutingMode(mode, p1, p2, lastDirection) {
  switch (mode) {
    case 'orthogonal':
      return orthogonalSnap(p1, p2, lastDirection)
    case '45':
      return corner45(p1, p2)
    case 'free':
      return freeRoute(p1, p2)
    default:
      return freeRoute(p1, p2)
  }
}

// ─── splitTraceAtPoint ────────────────────────────────────────────────────────

/**
 * Split a trace at a point near one of its segments. Returns [traceA, traceB]
 * where traceA ends at the split point and traceB starts from it. The union
 * of both traces covers the same total polyline length.
 *
 * @param {{ id: string, points: Array<{x,y}>, net_id: string, [string]: any }} trace
 * @param {{x: number, y: number}} point
 * @param {number} tolerance
 * @returns {[object, object]|null}  null if no segment within tolerance found
 */
export function splitTraceAtPoint(trace, point, tolerance = 0.1) {
  if (!trace || !trace.points || trace.points.length < 2) return null
  if (!point) return null

  const pts = trace.points
  let bestSegIdx = -1
  let bestDist = Infinity

  for (let i = 0; i < pts.length - 1; i++) {
    const d = pointToSegmentDist(point, pts[i], pts[i + 1])
    if (d < bestDist) {
      bestDist = d
      bestSegIdx = i
    }
  }

  if (bestSegIdx === -1 || bestDist > tolerance) return null

  const a = pts[bestSegIdx]
  const b = pts[bestSegIdx + 1]

  // Snap the split point onto the segment
  const t = projectOntoSegment(point, a, b)
  const snap = {
    x: a.x + t * (b.x - a.x),
    y: a.y + t * (b.y - a.y),
  }

  // If the snap lands on an existing endpoint, bail — can't split at an endpoint
  if (ptEq(snap, a, tolerance) || ptEq(snap, b, tolerance)) return null

  const base = { net_id: trace.net_id, width_mm: trace.width_mm, layer: trace.layer }

  const traceA = {
    ...base,
    id: trace.id ? `${trace.id}_a` : undefined,
    points: [...pts.slice(0, bestSegIdx + 1), snap],
  }
  const traceB = {
    ...base,
    id: trace.id ? `${trace.id}_b` : undefined,
    points: [snap, ...pts.slice(bestSegIdx + 1)],
  }

  return [traceA, traceB]
}

// ─── detectTJunction ─────────────────────────────────────────────────────────

/**
 * Find any trace in `traces` whose interior (non-endpoint) passes through
 * `vertex` on the SAME net. Returns the matching trace id, or null.
 *
 * "SAME net" means `trace.net_id === vertex_net_id`. Pass `vertex` as
 * `{x, y, net_id}` or pass `net_id` as a separate argument.
 *
 * Overload:
 *   detectTJunction(traces, vertex, tolerance)
 *   detectTJunction(segA, segB, point, tol)  ← legacy two-segment form
 *
 * @param {Array<{id, points, net_id}>} traces
 * @param {{x: number, y: number, net_id?: string}} vertex
 * @param {number} tolerance
 * @returns {string|null}
 */
export function detectTJunction(traces, vertex, tolerance = 0.1) {
  // Legacy two-argument segment form: detectTJunction(segA, segB, point, tol)
  if (
    traces &&
    !Array.isArray(traces) &&
    typeof traces.x === 'number' &&
    typeof vertex.x === 'number'
  ) {
    const segA = traces
    const segB = vertex
    const p = tolerance
    const tol = arguments[3] !== undefined ? arguments[3] : 0.1
    return _detectTJunctionSegment(segA, segB, p, tol)
  }

  if (!Array.isArray(traces) || traces.length === 0) return null
  if (!vertex) return null

  const netId = vertex.net_id

  for (const trace of traces) {
    if (netId !== undefined && trace.net_id !== netId) continue
    const pts = trace.points
    if (!pts || pts.length < 2) continue

    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i]
      const b = pts[i + 1]

      // Check if vertex is within tolerance of this segment
      const d = pointToSegmentDist(vertex, a, b)
      if (d > tolerance) continue

      // Exclude if it's at an endpoint of the whole trace
      const atStart = ptEq(vertex, pts[0], tolerance)
      const atEnd = ptEq(vertex, pts[pts.length - 1], tolerance)
      if (atStart || atEnd) continue

      return trace.id ?? null
    }
  }

  return null
}

/** @private Legacy two-point-segment form used by existing tests */
function _detectTJunctionSegment(segA, segB, p, tol) {
  const distToA = dist2(p, segA)
  const distToB = dist2(p, segB)
  if (distToA < tol || distToB < tol) {
    return { hit: false, point: { x: p.x, y: p.y } }
  }
  const d = pointToSegmentDist(p, segA, segB)
  if (d <= tol) {
    const dx = segB.x - segA.x
    const dy = segB.y - segA.y
    const lenSq = dx * dx + dy * dy
    const t = lenSq > 0
      ? Math.max(0, Math.min(1, ((p.x - segA.x) * dx + (p.y - segA.y) * dy) / lenSq))
      : 0
    return { hit: true, point: { x: segA.x + t * dx, y: segA.y + t * dy } }
  }
  return { hit: false, point: { x: p.x, y: p.y } }
}

// ─── mergeTraces ──────────────────────────────────────────────────────────────

/**
 * Merge traces that share endpoints AND are on the same net. Returns a new
 * array with merged traces; idempotent (calling again produces the same
 * result).
 *
 * Refuses to merge traces on different nets (different net_id).
 *
 * @param {Array<{id, points, net_id, [string]: any}>} traces
 * @param {number} tolerance
 * @returns {Array<object>}
 */
export function mergeTraces(traces, tolerance = 0.1) {
  if (!Array.isArray(traces) || traces.length === 0) return []

  // Work on a mutable copy keyed by index
  let working = traces.map((t, i) => ({ ...t, _idx: i }))
  let merged = true

  while (merged) {
    merged = false
    outer:
    for (let i = 0; i < working.length; i++) {
      for (let j = i + 1; j < working.length; j++) {
        const a = working[i]
        const b = working[j]

        // Must be same net
        if (a.net_id !== b.net_id) continue

        const ptsA = a.points
        const ptsB = b.points
        if (!ptsA || !ptsB || ptsA.length < 2 || ptsB.length < 2) continue

        const aStart = ptsA[0]
        const aEnd = ptsA[ptsA.length - 1]
        const bStart = ptsB[0]
        const bEnd = ptsB[ptsB.length - 1]

        let mergedPoints = null

        if (ptEq(aEnd, bStart, tolerance)) {
          // a → b
          mergedPoints = [...ptsA, ...ptsB.slice(1)]
        } else if (ptEq(aStart, bEnd, tolerance)) {
          // b → a
          mergedPoints = [...ptsB, ...ptsA.slice(1)]
        } else if (ptEq(aEnd, bEnd, tolerance)) {
          // a → reverse(b)
          mergedPoints = [...ptsA, ...[...ptsB].reverse().slice(1)]
        } else if (ptEq(aStart, bStart, tolerance)) {
          // reverse(a) → b
          mergedPoints = [...[...ptsA].reverse(), ...ptsB.slice(1)]
        }

        if (mergedPoints) {
          const newTrace = {
            ...a,
            points: mergedPoints,
            id: a.id || b.id,
          }
          delete newTrace._idx
          // Replace a, remove b
          working.splice(j, 1)
          working[i] = newTrace
          merged = true
          break outer
        }
      }
    }
  }

  // Strip internal bookkeeping
  return working.map(({ _idx, ...rest }) => rest)
}
