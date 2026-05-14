/**
 * railings.js — Pure JS parametric railing / handrail geometry.
 *
 * All dimensions in millimetres.
 */

// ── defaults ───────────────────────────────────────────────────────────────

/**
 * Build a default railing document.
 * @param {{ path: Array<{x,y,z}>, height_mm?: number }} opts
 * @returns {object}
 */
export function defaultRailing({ path, height_mm = 1000 }) {
  return {
    version: 1,
    path: path.map(p => ({ x: p.x, y: p.y, z: p.z })),
    height_mm,
    top_rail: {
      profile: 'round',
      size_mm: 50,
      offset_mm: 0,
    },
    posts: {
      spacing_mm: 1200,
      profile: 'round',
      size_mm: 40,
      height_mm,
    },
    balusters: {
      spacing_mm: 120,
      profile: 'round',
      size_mm: 14,
      height_mm: height_mm - 100,
    },
  }
}

// ── validation ─────────────────────────────────────────────────────────────

/**
 * Validate a railing document.
 * @param {object} railing
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateRailing(railing) {
  const errors = []

  if (!Array.isArray(railing.path) || railing.path.length < 2) {
    errors.push('path must be an array with at least 2 points')
  }

  const h = railing.height_mm
  if (typeof h !== 'number' || h < 600 || h > 1200) {
    errors.push(`height_mm (${h}) must be in [600, 1200]`)
  }

  const validProfiles = ['round', 'square', 'flat']

  const tr = railing.top_rail || {}
  if (!validProfiles.includes(tr.profile)) {
    errors.push(`top_rail.profile must be one of ${validProfiles.join(', ')}`)
  }
  if (typeof tr.size_mm !== 'number' || tr.size_mm <= 0) {
    errors.push('top_rail.size_mm must be a positive number')
  }

  const posts = railing.posts || {}
  if (typeof posts.spacing_mm !== 'number' || posts.spacing_mm <= 0) {
    errors.push('posts.spacing_mm must be a positive number')
  }

  const bal = railing.balusters || {}
  if (typeof bal.spacing_mm !== 'number' || bal.spacing_mm <= 0) {
    errors.push('balusters.spacing_mm must be a positive number')
  }

  return { ok: errors.length === 0, errors }
}

// ── path utilities ─────────────────────────────────────────────────────────

/**
 * Compute total length of a polyline path.
 * @param {Array<{x,y,z}>} path
 * @returns {number}
 */
function pathLength(path) {
  let total = 0
  for (let i = 1; i < path.length; i++) {
    const dx = path[i].x - path[i - 1].x
    const dy = path[i].y - path[i - 1].y
    const dz = path[i].z - path[i - 1].z
    total += Math.sqrt(dx * dx + dy * dy + dz * dz)
  }
  return total
}

/**
 * Interpolate a point at distance `t` along a polyline.
 * @param {Array<{x,y,z}>} path
 * @param {number} t  distance from start
 * @returns {{x,y,z}}
 */
function interpolatePath(path, t) {
  let remaining = t
  for (let i = 1; i < path.length; i++) {
    const dx = path[i].x - path[i - 1].x
    const dy = path[i].y - path[i - 1].y
    const dz = path[i].z - path[i - 1].z
    const seg = Math.sqrt(dx * dx + dy * dy + dz * dz)
    if (remaining <= seg + 1e-9) {
      const u = seg > 0 ? remaining / seg : 0
      return {
        x: path[i - 1].x + u * dx,
        y: path[i - 1].y + u * dy,
        z: path[i - 1].z + u * dz,
      }
    }
    remaining -= seg
  }
  // Past end — clamp to last point
  return { ...path[path.length - 1] }
}

// ── post and baluster positions ────────────────────────────────────────────

/**
 * Compute post positions spaced evenly along path.
 * Always includes start and end points.
 *
 * @param {Array<{x,y,z}>} path
 * @param {number} post_spacing  — maximum distance between posts (mm)
 * @returns {Array<{x,y,z}>}
 */
export function computePostPositions(path, post_spacing) {
  if (!path || path.length < 2) return []
  const total = pathLength(path)
  if (total <= 0) return [{ ...path[0] }]

  const count = Math.max(2, Math.ceil(total / post_spacing) + 1)
  const step = total / (count - 1)
  const positions = []

  for (let i = 0; i < count; i++) {
    positions.push(interpolatePath(path, i * step))
  }

  return positions
}

/**
 * Compute baluster positions spaced evenly along path.
 * Balusters are placed between posts (not at post positions).
 *
 * @param {Array<{x,y,z}>} path
 * @param {number} baluster_spacing  — maximum distance between balusters (mm)
 * @returns {Array<{x,y,z}>}
 */
export function computeBalusterPositions(path, baluster_spacing) {
  if (!path || path.length < 2) return []
  const total = pathLength(path)
  if (total <= 0) return []

  const count = Math.floor(total / baluster_spacing)
  if (count <= 0) return []

  const step = total / (count + 1)
  const positions = []

  for (let i = 1; i <= count; i++) {
    positions.push(interpolatePath(path, i * step))
  }

  return positions
}

// ── builders ───────────────────────────────────────────────────────────────

/**
 * Build a railing doc that follows the edge of a stair.
 *
 * Walks along the tread nosing edge of each flight. When side='both',
 * returns an array of two railing docs.
 *
 * @param {object} stair  — stair doc from stairs.js
 * @param {'left'|'right'|'both'} side
 * @param {object} [options]  — overrides for defaultRailing
 * @returns {object|object[]}
 */
export function railingFromStair(stair, side, options = {}) {
  const { riser_height_mm = 175, tread_depth_mm = 280, width_mm = 1000 } = stair

  function pathForFlight(flight, offset) {
    const { start_point, direction, step_count } = flight
    const [dx, dy] = direction
    const dLen = Math.sqrt(dx * dx + dy * dy) || 1
    const ux = dx / dLen
    const uy = dy / dLen

    // Perpendicular for offset
    const px = -uy
    const py = ux

    const path = []
    for (let i = 0; i <= step_count; i++) {
      path.push({
        x: start_point[0] + ux * tread_depth_mm * i + px * offset,
        y: start_point[1] + uy * tread_depth_mm * i + py * offset,
        z: start_point[2] + riser_height_mm * i,
      })
    }
    return path
  }

  // Merge paths from all flights
  function buildPath(offset) {
    const allPts = []
    for (const flight of stair.flights) {
      const pts = pathForFlight(flight, offset)
      if (allPts.length === 0) {
        allPts.push(...pts)
      } else {
        // Skip duplicate start point
        allPts.push(...pts.slice(1))
      }
    }
    return allPts
  }

  const height_mm = options.height_mm || 1000

  if (side === 'both') {
    return [
      defaultRailing({ path: buildPath(0), height_mm, ...options }),
      defaultRailing({ path: buildPath(width_mm), height_mm, ...options }),
    ]
  }

  const offset = side === 'right' ? width_mm : 0
  return defaultRailing({ path: buildPath(offset), height_mm, ...options })
}

/**
 * Build a railing doc from an explicit sketch path.
 *
 * @param {Array<{x,y,z}>} sketch_points
 * @param {object} [options]
 * @returns {object}
 */
export function railingFromSketch(sketch_points, options = {}) {
  return defaultRailing({ path: sketch_points, ...options })
}
