// ribGeom.js — Pure JS rib profile offset helper for in-browser preview.
// No React or browser globals — safe for vitest and Web Workers.

/**
 * Compute an offset polyline from a closed sketch path for rib extrusion.
 * Uses parallel-segment offset with arc-fitting at corners (standard polygon offset).
 *
 * @param {Array<{x: number, y: number}>} sketchPath  Closed polygon points (CCW order).
 * @param {number} thickness                            Wall thickness in mm. Must be > 0.
 * @param {boolean} bothSides                          Extrude symmetrically.
 * @param {boolean} midplane                           Center extrusion on sketch plane (no offset).
 * @returns {Array<{x: number, y: number}>}            Offset polyline for sweep.
 */
export function computeRibProfile(sketchPath, thickness, bothSides = false, midplane = false) {
  if (!sketchPath || !Array.isArray(sketchPath) || sketchPath.length < 3) return []
  if (!thickness || thickness <= 0) return []

  if (midplane) {
    return sketchPath.map(p => ({ x: p.x, y: p.y }))
  }

  const n = sketchPath.length
  const offsetDist = bothSides ? thickness / 2 : thickness

  const leftNormal = (p0, p1) => {
    const dx = p1.x - p0.x
    const dy = p1.y - p0.y
    const len = Math.hypot(dx, dy) || 1
    return { x: -dy / len, y: dx / len }
  }

  const segments = []
  for (let i = 0; i < n; i++) {
    const prev = sketchPath[(i - 1 + n) % n]
    const curr = sketchPath[i]
    const next = sketchPath[(i + 1) % n]

    const n1 = leftNormal(prev, curr)
    const n2 = leftNormal(curr, next)

    const cosA = Math.max(-1, Math.min(1, n1.x * n2.x + n1.y * n2.y))
    const theta = Math.acos(cosA)
    const sinHalf = Math.sin(theta / 2)
    const clamp = sinHalf < 1e-9 ? 1 : (2 * sinHalf / (sinHalf + 1e-12)) - 1
    const bevel = clamp * offsetDist

    const nx = (n1.x + n2.x) / 2
    const ny = (n1.y + n2.y) / 2
    const nl = Math.hypot(nx, ny) || 1

    segments.push({
      x: curr.x - (nx / nl) * (offsetDist + bevel),
      y: curr.y - (ny / nl) * (offsetDist + bevel),
    })
  }

  return segments
}
