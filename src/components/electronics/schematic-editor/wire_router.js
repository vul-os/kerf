// wire_router.js — Orthogonal wire routing helper.
//
// routeWire(start, end, grid) → [{x,y}]
//
// Strategy: L-shaped (2-segment) routing that prefers a horizontal-first bend.
// If start and end share an x or y coordinate the path is a single segment.
// For a general case a mid-point "elbow" is chosen at (end.x, start.y), giving
// three points (start → elbow → end) which forms two orthogonal segments.
//
// The grid parameter is used to snap the elbow if provided (default 25 mil).
//
// Returns an array of {x, y} points — at minimum 2 points (1 segment).

export function snapToGrid(v, grid = 25) {
  return Math.round(v / grid) * grid
}

/**
 * routeWire — produce an orthogonal path between two schematic points.
 *
 * @param {{x: number, y: number}} start
 * @param {{x: number, y: number}} end
 * @param {number} [grid=25]
 * @returns {{x: number, y: number}[]}
 */
export function routeWire(start, end, grid = 25) {
  const sx = snapToGrid(start.x, grid)
  const sy = snapToGrid(start.y, grid)
  const ex = snapToGrid(end.x, grid)
  const ey = snapToGrid(end.y, grid)

  // Collinear — single segment
  if (sx === ex || sy === ey) {
    return [
      { x: sx, y: sy },
      { x: ex, y: ey },
    ]
  }

  // General case — horizontal-first elbow at (ex, sy)
  return [
    { x: sx, y: sy },
    { x: ex, y: sy },
    { x: ex, y: ey },
  ]
}

/**
 * segmentsFromPoints — convert a point array into line segments.
 *
 * @param {{x: number, y: number}[]} points
 * @returns {{x1: number, y1: number, x2: number, y2: number}[]}
 */
export function segmentsFromPoints(points) {
  const segs = []
  for (let i = 0; i < points.length - 1; i++) {
    segs.push({
      x1: points[i].x,
      y1: points[i].y,
      x2: points[i + 1].x,
      y2: points[i + 1].y,
    })
  }
  return segs
}

/**
 * hitTestWire — returns true if the point (px, py) is within tolerance of
 * any segment in the wire.
 */
export function hitTestWire(segments, px, py, tol = 6) {
  for (const { x1, y1, x2, y2 } of segments) {
    const dx = x2 - x1
    const dy = y2 - y1
    const lenSq = dx * dx + dy * dy
    if (lenSq === 0) continue
    const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lenSq))
    const cx = x1 + t * dx
    const cy = y1 + t * dy
    if (Math.hypot(px - cx, py - cy) <= tol) return true
  }
  return false
}
