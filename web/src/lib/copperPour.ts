// copperPour.ts — Pure geometry helpers for copper pour rendering.
// No React or browser imports — safe to use in vitest and workers.

const VALID_LAYERS = ['top_copper', 'bottom_copper', 'inner_1', 'inner_2'] as const
type PourLayer = (typeof VALID_LAYERS)[number]

// T-537: the canonical backend shape — emitted by kicad_io.py's
// `_parse_zone_node`, consumed by Gerber/ODB++/via-stitching — uses
// `pcb_copper_pour` for a net-bound pour and `pcb_ground_plane` for a
// no-net fill (T-536 kept those as a distinct type; a ground plane has no
// net_id at all). `copper_pour` (no `pcb_` prefix) is kept accepted too in
// case anything still emits the legacy string — grepping the tree found
// nothing that does today, but removing acceptance is a behaviour change
// this task doesn't need to make.
const VALID_TYPES = ['pcb_copper_pour', 'pcb_ground_plane', 'copper_pour'] as const
type PourType = (typeof VALID_TYPES)[number]

/** A 2-D point, `{x,y}` record form (Circuit-JSON's `Point` convention —
 * deliberately NOT `src/types/geometry.ts`'s `Vec2` tuple, since every
 * polygon point in this file's domain is a named-field record, not a
 * `[x,y]` tuple). */
export interface Point2D {
  x: number
  y: number
}

export interface ThermalRelief {
  gap?: number
  spoke_width?: number
  spoke_count?: number
}

/**
 * The copper-pour shape this module validates/consumes/renders. This is
 * Kerf's own pour shape — the canonical backend form emitted by
 * `kicad_io.py`'s `_parse_zone_node` (packages/kerf-electronics), consumed
 * by `tools/pour.py`, `fab/gerber.py`, `fab/odbpp/writer.py`, and
 * `via_stitching.py` — NOT circuit-json's `PcbCopperPour`/`PcbGroundPlane`
 * (those use a `points` array, `shape: "polygon"`, a `top`/`bottom`/`innerN`
 * `LayerRef` union, and carry no `net_id`/clearance/thermal_relief fields at
 * all — a different shape under the same npm package). Importing
 * `PcbCopperPour` from `@/types` here would silently misdescribe this
 * file's actual contract, so this stays a local type — see T-537 (tasks.md)
 * for the type-string mismatch this file used to have with the real backend
 * output.
 */
export interface Pour {
  type?: string
  polygon: Point2D[]
  layer?: string
  net_id?: string
  clearance_mm?: number
  min_thickness_mm?: number
  priority?: number
  thermal_relief?: ThermalRelief
}

export interface ValidationResult {
  ok: boolean
  errors: string[]
}

/**
 * Validate a copper pour object. Returns { ok: boolean, errors: string[] }.
 *
 * `pour` is typed `unknown` rather than `Pour` — validation is the boundary
 * that turns untrusted/possibly-invalid data into something `Pour`-shaped;
 * every field is checked at runtime before use.
 */
export function validatePour(pour: unknown): ValidationResult {
  const errors: string[] = []
  if (!pour || typeof pour !== 'object') {
    return { ok: false, errors: ['pour must be an object'] }
  }
  const p = pour as Partial<Pour> & Record<string, unknown>
  if (!VALID_TYPES.includes(p.type as PourType)) {
    errors.push(`type must be one of: ${VALID_TYPES.join(', ')}`)
  }
  const isGroundPlane = p.type === 'pcb_ground_plane'
  if (!Array.isArray(p.polygon) || p.polygon.length < 3) {
    errors.push('polygon must be an array of at least 3 {x, y} points')
  } else {
    for (let i = 0; i < p.polygon.length; i++) {
      const pt = p.polygon[i] as Partial<Point2D>
      if (typeof pt.x !== 'number' || typeof pt.y !== 'number') {
        errors.push(`polygon[${i}] must have numeric x and y`)
      }
    }
  }
  if (!p.layer) {
    errors.push('layer is required')
  } else if (!VALID_LAYERS.includes(p.layer as PourLayer)) {
    errors.push(`layer must be one of: ${VALID_LAYERS.join(', ')}`)
  }
  // pcb_ground_plane is a no-net fill (T-536) — net_id doesn't apply there,
  // but if present it must still be a string.
  if (!isGroundPlane) {
    if (!p.net_id || typeof p.net_id !== 'string') {
      errors.push('net_id must be a non-empty string')
    }
  } else if (p.net_id !== undefined && typeof p.net_id !== 'string') {
    errors.push('net_id must be a string')
  }
  if (p.clearance_mm !== undefined && typeof p.clearance_mm !== 'number') {
    errors.push('clearance_mm must be a number')
  }
  if (p.min_thickness_mm !== undefined && typeof p.min_thickness_mm !== 'number') {
    errors.push('min_thickness_mm must be a number')
  }
  if (p.priority !== undefined && typeof p.priority !== 'number') {
    errors.push('priority must be a number')
  }
  if (p.thermal_relief !== undefined) {
    const tr = p.thermal_relief as Partial<ThermalRelief> | null
    if (typeof tr !== 'object' || tr === null) {
      errors.push('thermal_relief must be an object')
    } else {
      if (tr.gap !== undefined && typeof tr.gap !== 'number') errors.push('thermal_relief.gap must be a number')
      if (tr.spoke_width !== undefined && typeof tr.spoke_width !== 'number') errors.push('thermal_relief.spoke_width must be a number')
      if (tr.spoke_count !== undefined && (!Number.isInteger(tr.spoke_count) || tr.spoke_count < 2)) errors.push('thermal_relief.spoke_count must be an integer >= 2')
    }
  }
  return { ok: errors.length === 0, errors }
}

/**
 * Generate thermal relief spokes connecting a pad to the surrounding pour.
 * Returns an array of line segments { x1, y1, x2, y2 }.
 *
 * @param pour       - pour object (for context; unused directly here)
 * @param padCenter
 * @param padRadius  - pad radius in mm
 * @param spokeCount - number of spokes (typically 4)
 * @param spokeWidth - width of each spoke in mm
 * @param gap        - gap between pad edge and start of spoke in mm
 */
export function thermalReliefSpokes(
  pour: Pour,
  padCenter: Point2D,
  padRadius: number,
  spokeCount: number,
  spokeWidth: number,
  gap: number
): Array<{ x1: number; y1: number; x2: number; y2: number }> {
  const cx = padCenter.x
  const cy = padCenter.y
  const spokes: Array<{ x1: number; y1: number; x2: number; y2: number }> = []
  const count = Math.max(2, Math.round(spokeCount))
  for (let i = 0; i < count; i++) {
    const angle = (2 * Math.PI * i) / count
    const x1 = cx + (padRadius + gap) * Math.cos(angle)
    const y1 = cy + (padRadius + gap) * Math.sin(angle)
    const x2 = cx + (padRadius + gap + spokeWidth * 4) * Math.cos(angle)
    const y2 = cy + (padRadius + gap + spokeWidth * 4) * Math.sin(angle)
    spokes.push({ x1, y1, x2, y2 })
  }
  return spokes
}

/**
 * Merge pours that share the same net_id and layer, combining overlapping polygons.
 * Non-overlapping pours on the same net/layer are left as separate entries.
 * Returns a new array (does not mutate input).
 */
export function mergePours(pours: Pour[]): Pour[] {
  if (!Array.isArray(pours) || pours.length === 0) return []

  // Group by net_id + layer
  const groups = new Map<string, Pour[]>()
  for (const pour of pours) {
    const key = `${pour.net_id}::${pour.layer}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(pour)
  }

  const result: Pour[] = []
  for (const [, group] of groups) {
    if (group.length === 1) {
      result.push(group[0])
      continue
    }
    // Try to merge overlapping polygons within the group
    // Use a simple union: repeatedly merge polygons that share any vertex proximity
    const merged = _mergePolygonGroup(group)
    result.push(...merged)
  }
  return result
}

/**
 * Attempt to union overlapping polygons in a group of same-net/layer pours.
 * Uses a bounding-box overlap test to identify candidates, then builds a
 * convex hull approximation for merged pairs. Non-overlapping pours are kept separate.
 */
function _mergePolygonGroup(group: Pour[]): Pour[] {
  // Work with mutable copies; track which have been consumed
  const remaining: Array<Pour & { _idx: number }> = group.map((p, i) => ({ ...p, _idx: i }))
  const out: Pour[] = []

  while (remaining.length > 0) {
    let base = remaining.shift() as Pour & { _idx: number }
    let merged = true
    while (merged) {
      merged = false
      for (let i = 0; i < remaining.length; i++) {
        if (_polygonsOverlap(base.polygon, remaining[i].polygon)) {
          // Merge: convex hull of combined vertices as approximation
          const combined = [...base.polygon, ...remaining[i].polygon]
          base = { ...base, polygon: _convexHull(combined) }
          remaining.splice(i, 1)
          merged = true
          break
        }
      }
    }
    const { _idx, ...clean } = base
    out.push(clean)
  }
  return out
}

/** Axis-aligned bounding-box overlap test for two polygons. */
function _polygonsOverlap(a: Point2D[], b: Point2D[]): boolean {
  const aMinX = Math.min(...a.map(p => p.x))
  const aMaxX = Math.max(...a.map(p => p.x))
  const aMinY = Math.min(...a.map(p => p.y))
  const aMaxY = Math.max(...a.map(p => p.y))
  const bMinX = Math.min(...b.map(p => p.x))
  const bMaxX = Math.max(...b.map(p => p.x))
  const bMinY = Math.min(...b.map(p => p.y))
  const bMaxY = Math.max(...b.map(p => p.y))
  return aMinX <= bMaxX && aMaxX >= bMinX && aMinY <= bMaxY && aMaxY >= bMinY
}

/**
 * Compute 2D convex hull (Andrew's monotone chain).
 * Returns CCW-wound polygon vertices.
 */
function _convexHull(pts: Point2D[]): Point2D[] {
  const sorted = [...pts].sort((a, b) => a.x !== b.x ? a.x - b.x : a.y - b.y)
  if (sorted.length <= 2) return sorted

  function cross(O: Point2D, A: Point2D, B: Point2D): number {
    return (A.x - O.x) * (B.y - O.y) - (A.y - O.y) * (B.x - O.x)
  }

  const lower: Point2D[] = []
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop()
    lower.push(p)
  }
  const upper: Point2D[] = []
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i]
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop()
    upper.push(p)
  }
  // Remove last point of each half because it's repeated
  lower.pop()
  upper.pop()
  return [...lower, ...upper]
}

/**
 * Ray-casting point-in-polygon test.
 * Returns true if point p is strictly inside the polygon.
 */
export function pointInPolygon(p: Point2D, polygon: Point2D[]): boolean {
  if (!polygon || polygon.length < 3) return false
  let inside = false
  const n = polygon.length
  let j = n - 1
  for (let i = 0; i < n; i++) {
    const xi = polygon[i].x
    const yi = polygon[i].y
    const xj = polygon[j].x
    const yj = polygon[j].y
    const intersect =
      yi > p.y !== yj > p.y &&
      p.x < ((xj - xi) * (p.y - yi)) / (yj - yi) + xi
    if (intersect) inside = !inside
    j = i
  }
  return inside
}

/**
 * Offset a polygon outward by `amount` mm using a simple per-vertex normal
 * average. Not as accurate as Shapely but good enough for a frontend preview.
 *
 * @param amount - offset distance (positive = outward)
 */
export function offsetPolygon(polygon: Point2D[], amount: number): Point2D[] {
  if (!polygon || polygon.length < 3) return polygon
  const n = polygon.length
  const result: Point2D[] = []
  for (let i = 0; i < n; i++) {
    const prev = polygon[(i + n - 1) % n]
    const curr = polygon[i]
    const next = polygon[(i + 1) % n]

    // Edge normals (pointing outward for CCW winding, inward for CW — we normalise)
    const e1x = curr.x - prev.x
    const e1y = curr.y - prev.y
    const e1len = Math.hypot(e1x, e1y) || 1
    const n1x = -e1y / e1len
    const n1y = e1x / e1len

    const e2x = next.x - curr.x
    const e2y = next.y - curr.y
    const e2len = Math.hypot(e2x, e2y) || 1
    const n2x = -e2y / e2len
    const n2y = e2x / e2len

    // Bisector normal
    const bx = n1x + n2x
    const by = n1y + n2y
    const blen = Math.hypot(bx, by) || 1
    const scale = amount / blen

    result.push({ x: curr.x + bx * scale, y: curr.y + by * scale })
  }
  return result
}

/**
 * Approximate circular clearance holes for a list of pad objects.
 * Each hole is an octagon approximating a circle of (pad.radius + clearanceMm).
 *
 * @returns array of hole polygons
 */
export function padClearanceHoles(
  pads: Array<{ x: number; y: number; diameter_mm?: number }>,
  clearanceMm: number
): Point2D[][] {
  if (!pads || pads.length === 0) return []
  const SIDES = 8
  return pads.map((pad) => {
    const r = (pad.diameter_mm != null ? pad.diameter_mm / 2 : 0.5) + clearanceMm
    const cx = pad.x || 0
    const cy = pad.y || 0
    const pts: Point2D[] = []
    for (let i = 0; i < SIDES; i++) {
      const angle = (2 * Math.PI * i) / SIDES
      pts.push({ x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) })
    }
    return pts
  })
}

/**
 * Build an SVG path `d` string for a polygon-with-holes using the even-odd
 * fill rule. Each subpath (outer + each hole) is a separate "M ... Z" segment.
 *
 * @param outer - outer boundary
 * @param holes - array of hole polygons
 * @returns SVG path `d` attribute
 */
export function pourToSvgPath(outer: Point2D[], holes: Point2D[][]): string {
  function ringToPath(pts: Point2D[]): string {
    if (!pts || pts.length === 0) return ''
    const start = pts[0]
    let d = `M ${_fmt(start.x)} ${_fmt(start.y)}`
    for (let i = 1; i < pts.length; i++) {
      d += ` L ${_fmt(pts[i].x)} ${_fmt(pts[i].y)}`
    }
    d += ' Z'
    return d
  }

  const parts: string[] = []
  if (outer && outer.length > 0) parts.push(ringToPath(outer))
  if (holes) {
    for (const hole of holes) {
      if (hole && hole.length > 0) parts.push(ringToPath(hole))
    }
  }
  return parts.join(' ')
}

/** Format a number for SVG path output — up to 4 decimal places. */
function _fmt(n: number): string {
  if (!Number.isFinite(n)) return '0'
  const s = Number(n.toFixed(4))
  return String(s)
}
