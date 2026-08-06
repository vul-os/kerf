/**
 * railings.ts — Pure JS parametric railing / handrail geometry.
 *
 * All dimensions in millimetres.
 */

import type { Vec3 } from '@/types'

// ── Shapes ─────────────────────────────────────────────────────────────────
//
// stairs.js/stairs.ts (outside this slice) exports no reusable types — its exports are all
// implicit-`any` JSDoc. The shapes below are modeled locally from how defaultRailing/
// railingFromStair actually read and produce data.

/** A path point, as used throughout the railing path/post/baluster helpers. */
export interface RailingPoint {
  x: number
  y: number
  z: number
}

export interface RailingProfileSpec {
  profile: string
  size_mm: number
  offset_mm?: number
  height_mm?: number
  spacing_mm?: number
}

export interface RailingDoc {
  version: number
  path: RailingPoint[]
  height_mm: number
  top_rail: RailingProfileSpec
  posts: RailingProfileSpec
  balusters: RailingProfileSpec
}

export interface DefaultRailingOptions {
  path: RailingPoint[]
  height_mm?: number
}

export interface RailingValidationResult {
  ok: boolean
  errors: string[]
}

/** The subset of a stair document (stairs.js) that railingFromStair reads. */
export interface RailingStairFlight {
  start_point: Vec3
  direction: Vec3
  step_count: number
}

export interface RailingStairSource {
  riser_height_mm?: number
  tread_depth_mm?: number
  width_mm?: number
  flights: RailingStairFlight[]
}

export type RailingSide = 'left' | 'right' | 'both'

// ── defaults ───────────────────────────────────────────────────────────────

/**
 * Build a default railing document.
 */
export function defaultRailing({ path, height_mm = 1000 }: DefaultRailingOptions): RailingDoc {
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
 */
export function validateRailing(railing: Partial<RailingDoc>): RailingValidationResult {
  const errors: string[] = []

  if (!Array.isArray(railing.path) || railing.path.length < 2) {
    errors.push('path must be an array with at least 2 points')
  }

  const h = railing.height_mm
  if (typeof h !== 'number' || h < 600 || h > 1200) {
    errors.push(`height_mm (${h}) must be in [600, 1200]`)
  }

  const validProfiles = ['round', 'square', 'flat']

  const tr = railing.top_rail || ({} as Partial<RailingProfileSpec>)
  if (!validProfiles.includes(tr.profile as string)) {
    errors.push(`top_rail.profile must be one of ${validProfiles.join(', ')}`)
  }
  if (typeof tr.size_mm !== 'number' || tr.size_mm <= 0) {
    errors.push('top_rail.size_mm must be a positive number')
  }

  const posts = railing.posts || ({} as Partial<RailingProfileSpec>)
  if (typeof posts.spacing_mm !== 'number' || posts.spacing_mm <= 0) {
    errors.push('posts.spacing_mm must be a positive number')
  }

  const bal = railing.balusters || ({} as Partial<RailingProfileSpec>)
  if (typeof bal.spacing_mm !== 'number' || bal.spacing_mm <= 0) {
    errors.push('balusters.spacing_mm must be a positive number')
  }

  return { ok: errors.length === 0, errors }
}

// ── path utilities ─────────────────────────────────────────────────────────

/**
 * Compute total length of a polyline path.
 */
function pathLength(path: RailingPoint[]): number {
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
 *
 * @param t - distance from start
 */
function interpolatePath(path: RailingPoint[], t: number): RailingPoint {
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
 * @param post_spacing - maximum distance between posts (mm)
 */
export function computePostPositions(path: RailingPoint[], post_spacing: number): RailingPoint[] {
  if (!path || path.length < 2) return []
  const total = pathLength(path)
  if (total <= 0) return [{ ...path[0] }]

  const count = Math.max(2, Math.ceil(total / post_spacing) + 1)
  const step = total / (count - 1)
  const positions: RailingPoint[] = []

  for (let i = 0; i < count; i++) {
    positions.push(interpolatePath(path, i * step))
  }

  return positions
}

/**
 * Compute baluster positions spaced evenly along path.
 * Balusters are placed between posts (not at post positions).
 *
 * @param baluster_spacing - maximum distance between balusters (mm)
 */
export function computeBalusterPositions(path: RailingPoint[], baluster_spacing: number): RailingPoint[] {
  if (!path || path.length < 2) return []
  const total = pathLength(path)
  if (total <= 0) return []

  const count = Math.floor(total / baluster_spacing)
  if (count <= 0) return []

  const step = total / (count + 1)
  const positions: RailingPoint[] = []

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
 * @param stair - stair doc from stairs.js
 * @param options - overrides for defaultRailing
 */
export function railingFromStair(
  stair: RailingStairSource,
  side: RailingSide,
  options: Partial<DefaultRailingOptions> = {},
): RailingDoc | RailingDoc[] {
  const { riser_height_mm = 175, tread_depth_mm = 280, width_mm = 1000 } = stair

  function pathForFlight(flight: RailingStairFlight, offset: number): RailingPoint[] {
    const { start_point, direction, step_count } = flight
    const [dx, dy] = direction
    const dLen = Math.sqrt(dx * dx + dy * dy) || 1
    const ux = dx / dLen
    const uy = dy / dLen

    // Perpendicular for offset
    const px = -uy
    const py = ux

    const path: RailingPoint[] = []
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
  function buildPath(offset: number): RailingPoint[] {
    const allPts: RailingPoint[] = []
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
 */
export function railingFromSketch(
  sketch_points: RailingPoint[],
  options: Partial<DefaultRailingOptions> = {},
): RailingDoc {
  return defaultRailing({ path: sketch_points, ...options })
}
