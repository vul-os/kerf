// mep.js — MEP (Mechanical/Electrical/Plumbing) routing utilities.
//
// Supports three route kinds: 'duct', 'pipe', 'conduit'
// All coordinates are in mm; pressure in Pa.

// ── Constants ─────────────────────────────────────────────────────────────────

const VALID_KINDS = ['duct', 'pipe', 'conduit']
const VALID_SEGMENT_KINDS = ['straight', 'elbow', 'vertical']
const VALID_FITTING_KINDS = ['tee', 'reducer', 'transition', 'cap', 'cross']
const VALID_ENDPOINT_KINDS = ['source', 'sink']

// Darcy friction factors (dimensionless) by material — used for pressure drop
const ROUGHNESS_MM = {
  galvanized_steel: 0.046,
  stainless_steel: 0.015,
  copper: 0.0015,
  pvc: 0.0015,
  hdpe: 0.007,
  cast_iron: 0.26,
  concrete: 1.5,
  default: 0.046,
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function dist3(a, b) {
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  const dz = b[2] - a[2]
  return Math.sqrt(dx * dx + dy * dy + dz * dz)
}

function vecSub(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

function isCoord(v) {
  return Array.isArray(v) && v.length === 3 && v.every(n => typeof n === 'number')
}

// ── Public API ─────────────────────────────────────────────────────────────────

/**
 * Create an empty MEP route.
 * @param {'duct'|'pipe'|'conduit'} kind
 * @param {string} system_name
 * @returns {object}
 */
export function defaultMepRoute(kind = 'duct', system_name = 'Unnamed System') {
  return {
    version: 1,
    kind,
    system_name,
    system_color: '#5da9ff',
    material: kind === 'conduit' ? 'pvc' : kind === 'pipe' ? 'copper' : 'galvanized_steel',
    size_mm: kind === 'duct' ? 400 : kind === 'pipe' ? 50 : 25,
    width_mm: null,
    height_mm: null,
    insulation_thickness_mm: kind === 'duct' ? 25 : 0,
    segments: [],
    fittings: [],
    endpoints: [],
  }
}

/**
 * Validate an MEP route object.
 * @param {object} route
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateMepRoute(route) {
  const errors = []

  if (!route || typeof route !== 'object') {
    return { ok: false, errors: ['route must be an object'] }
  }

  if (route.version !== 1) errors.push(`version must be 1, got ${route.version}`)
  if (!VALID_KINDS.includes(route.kind)) errors.push(`kind must be one of ${VALID_KINDS.join(', ')}`)
  if (!route.system_name || typeof route.system_name !== 'string') errors.push('system_name is required')
  if (typeof route.size_mm !== 'number' || route.size_mm <= 0) {
    // size_mm can be null if rectangular
    if (route.width_mm == null || route.height_mm == null) {
      errors.push('size_mm must be a positive number, or width_mm + height_mm must be provided')
    }
  }
  if (!Array.isArray(route.segments)) errors.push('segments must be an array')
  if (!Array.isArray(route.fittings)) errors.push('fittings must be an array')
  if (!Array.isArray(route.endpoints)) errors.push('endpoints must be an array')

  const segIds = new Set()
  for (const seg of (route.segments || [])) {
    if (!seg.id) { errors.push('segment missing id'); continue }
    if (segIds.has(seg.id)) errors.push(`duplicate segment id: ${seg.id}`)
    segIds.add(seg.id)
    if (!isCoord(seg.from)) errors.push(`segment ${seg.id}: from must be [x,y,z]`)
    if (!isCoord(seg.to)) errors.push(`segment ${seg.id}: to must be [x,y,z]`)
    if (seg.kind && !VALID_SEGMENT_KINDS.includes(seg.kind)) {
      errors.push(`segment ${seg.id}: kind must be one of ${VALID_SEGMENT_KINDS.join(', ')}`)
    }
  }

  const fittingIds = new Set()
  for (const f of (route.fittings || [])) {
    if (!f.id) { errors.push('fitting missing id'); continue }
    if (fittingIds.has(f.id)) errors.push(`duplicate fitting id: ${f.id}`)
    fittingIds.add(f.id)
    if (!VALID_FITTING_KINDS.includes(f.kind)) {
      errors.push(`fitting ${f.id}: kind must be one of ${VALID_FITTING_KINDS.join(', ')}`)
    }
    if (!isCoord(f.position)) errors.push(`fitting ${f.id}: position must be [x,y,z]`)
  }

  const endpointIds = new Set()
  for (const ep of (route.endpoints || [])) {
    if (!ep.id) { errors.push('endpoint missing id'); continue }
    if (endpointIds.has(ep.id)) errors.push(`duplicate endpoint id: ${ep.id}`)
    endpointIds.add(ep.id)
    if (!VALID_ENDPOINT_KINDS.includes(ep.kind)) {
      errors.push(`endpoint ${ep.id}: kind must be one of ${VALID_ENDPOINT_KINDS.join(', ')}`)
    }
    if (!isCoord(ep.position)) errors.push(`endpoint ${ep.id}: position must be [x,y,z]`)
  }

  return { ok: errors.length === 0, errors }
}

/**
 * Add a segment to a route (immutable — returns new route).
 */
export function addSegment(route, segment) {
  const existing = route.segments.find(s => s.id === segment.id)
  if (existing) throw new Error(`segment id already exists: ${segment.id}`)
  return { ...route, segments: [...route.segments, { kind: 'straight', ...segment }] }
}

/**
 * Remove a segment by id.
 */
export function removeSegment(route, segment_id) {
  return { ...route, segments: route.segments.filter(s => s.id !== segment_id) }
}

/**
 * Add a fitting to a route.
 */
export function addFitting(route, fitting) {
  const existing = route.fittings.find(f => f.id === fitting.id)
  if (existing) throw new Error(`fitting id already exists: ${fitting.id}`)
  return { ...route, fittings: [...route.fittings, fitting] }
}

/**
 * Add an endpoint to a route.
 */
export function addEndpoint(route, endpoint) {
  const existing = route.endpoints.find(e => e.id === endpoint.id)
  if (existing) throw new Error(`endpoint id already exists: ${endpoint.id}`)
  return { ...route, endpoints: [...route.endpoints, endpoint] }
}

/**
 * Compute total route length in mm (sum of all segment lengths).
 * @returns {number}
 */
export function computeRouteLength(route) {
  if (!route.segments || route.segments.length === 0) return 0
  return route.segments.reduce((sum, seg) => sum + dist3(seg.from, seg.to), 0)
}

/**
 * Compute pressure drop for the route.
 *
 * For pipes: Darcy-Weisbach  ΔP = f * (L/D) * (ρv²/2)
 * For ducts: equivalent-length method using a fixed friction rate of 1 Pa/m.
 * For conduit: returns 0 (electrical, no fluid).
 *
 * fluid_props defaults: { density_kg_m3: 1000, velocity_m_s: 1.5, viscosity_Pa_s: 0.001 }
 *
 * @param {object} route
 * @param {object} [fluid_props]
 * @returns {number} pressure drop in Pa
 */
export function computePressureDrop(route, fluid_props = {}) {
  if (route.kind === 'conduit') return 0

  const length_m = computeRouteLength(route) / 1000
  if (length_m === 0) return 0

  const diameter_m = (route.size_mm || 200) / 1000

  if (route.kind === 'duct') {
    // Equivalent-length for ducts: ~1 Pa/m friction rate × correction for duct size
    // Reference: ASHRAE Handbook — 1 Pa/m is typical design criterion
    const size_correction = 200 / (route.size_mm || 200)
    return length_m * 1.0 * size_correction
  }

  // Pipe: Darcy-Weisbach
  const rho = fluid_props.density_kg_m3 ?? 1000
  const v = fluid_props.velocity_m_s ?? 1.5
  const mu = fluid_props.viscosity_Pa_s ?? 0.001

  const Re = (rho * v * diameter_m) / mu
  const roughness = ROUGHNESS_MM[route.material] ?? ROUGHNESS_MM.default
  const epsilon_D = (roughness / 1000) / diameter_m

  // Colebrook-White approximation (Swamee-Jain)
  let f
  if (Re < 2300) {
    f = 64 / Re
  } else {
    f = 0.25 / Math.pow(Math.log10(epsilon_D / 3.7 + 5.74 / Math.pow(Re, 0.9)), 2)
  }

  return f * (length_m / diameter_m) * (rho * v * v / 2)
}

// ── A* pathfinding ────────────────────────────────────────────────────────────

/**
 * Find shortest path between two 3D points avoiding axis-aligned box obstacles.
 * Uses a coarse grid (max 100×100×30). If the grid would exceed that, returns a
 * straight-line polyline with a warning.
 *
 * @param {[number,number,number]} start  — mm coords
 * @param {[number,number,number]} end    — mm coords
 * @param {Array<{min:[number,number,number], max:[number,number,number]}>} obstacles — AABB boxes
 * @param {number} gridSize_mm  — cell size in mm
 * @returns {{ polyline: [number,number,number][], warning?: string }}
 */
export function findShortestRoute(start, end, obstacles = [], gridSize_mm = 300) {
  const mins = [
    Math.min(start[0], end[0]),
    Math.min(start[1], end[1]),
    Math.min(start[2], end[2]),
  ]
  const maxs = [
    Math.max(start[0], end[0]),
    Math.max(start[1], end[1]),
    Math.max(start[2], end[2]),
  ]

  // Expand grid slightly to allow routing around obstacles
  const pad = gridSize_mm * 3
  const origin = [mins[0] - pad, mins[1] - pad, mins[2] - pad]
  const span = [
    maxs[0] - mins[0] + pad * 2,
    maxs[1] - mins[1] + pad * 2,
    maxs[2] - mins[2] + pad * 2,
  ]

  const gx = Math.ceil(span[0] / gridSize_mm) + 1
  const gy = Math.ceil(span[1] / gridSize_mm) + 1
  const gz = Math.ceil(span[2] / gridSize_mm) + 1

  if (gx > 100 || gy > 100 || gz > 30) {
    return {
      polyline: [start, end],
      warning: `Grid too large (${gx}×${gy}×${gz} > 100×100×30); returning straight line. Reduce gridSize_mm or routing distance.`,
    }
  }

  function toGrid(pt) {
    return [
      Math.round((pt[0] - origin[0]) / gridSize_mm),
      Math.round((pt[1] - origin[1]) / gridSize_mm),
      Math.round((pt[2] - origin[2]) / gridSize_mm),
    ]
  }

  function toWorld(gi, gj, gk) {
    return [
      origin[0] + gi * gridSize_mm,
      origin[1] + gj * gridSize_mm,
      origin[2] + gk * gridSize_mm,
    ]
  }

  function inBounds(i, j, k) {
    return i >= 0 && i < gx && j >= 0 && j < gy && k >= 0 && k < gz
  }

  // Build obstacle bitmap
  const blocked = new Uint8Array(gx * gy * gz)
  function idx(i, j, k) { return i + gx * (j + gy * k) }

  for (const obs of obstacles) {
    const [oMinX, oMinY, oMinZ] = obs.min
    const [oMaxX, oMaxY, oMaxZ] = obs.max
    const gi0 = Math.floor((oMinX - origin[0]) / gridSize_mm)
    const gj0 = Math.floor((oMinY - origin[1]) / gridSize_mm)
    const gk0 = Math.floor((oMinZ - origin[2]) / gridSize_mm)
    const gi1 = Math.ceil((oMaxX - origin[0]) / gridSize_mm)
    const gj1 = Math.ceil((oMaxY - origin[1]) / gridSize_mm)
    const gk1 = Math.ceil((oMaxZ - origin[2]) / gridSize_mm)
    for (let i = gi0; i <= gi1; i++) {
      for (let j = gj0; j <= gj1; j++) {
        for (let k = gk0; k <= gk1; k++) {
          if (inBounds(i, j, k)) blocked[idx(i, j, k)] = 1
        }
      }
    }
  }

  const [si, sj, sk] = toGrid(start)
  const [ei, ej, ek] = toGrid(end)

  function heuristic(i, j, k) {
    return Math.abs(i - ei) + Math.abs(j - ej) + Math.abs(k - ek)
  }

  // A* — 6-connected grid
  const DIRS = [
    [1, 0, 0], [-1, 0, 0],
    [0, 1, 0], [0, -1, 0],
    [0, 0, 1], [0, 0, -1],
  ]

  const key = (i, j, k) => `${i},${j},${k}`
  const gScore = new Map()
  const fScore = new Map()
  const cameFrom = new Map()
  const open = new Set()

  const startKey = key(si, sj, sk)
  gScore.set(startKey, 0)
  fScore.set(startKey, heuristic(si, sj, sk))
  open.add(startKey)
  const openQueue = [[si, sj, sk]]

  function popBest() {
    let bestKey = null
    let bestF = Infinity
    for (const k of open) {
      const f = fScore.get(k) ?? Infinity
      if (f < bestF) { bestF = f; bestKey = k }
    }
    if (!bestKey) return null
    open.delete(bestKey)
    const [i, j, k2] = bestKey.split(',').map(Number)
    return [i, j, k2]
  }

  let found = false
  let iter = 0
  const MAX_ITER = gx * gy * gz * 2

  while (open.size > 0 && iter++ < MAX_ITER) {
    const cur = popBest()
    if (!cur) break
    const [ci, cj, ck] = cur
    const ck_ = key(ci, cj, ck)
    if (ci === ei && cj === ej && ck === ek) { found = true; break }

    for (const [di, dj, dk] of DIRS) {
      const ni = ci + di, nj = cj + dj, nk = ck + dk
      if (!inBounds(ni, nj, nk)) continue
      if (blocked[idx(ni, nj, nk)]) continue
      const nk_ = key(ni, nj, nk)
      const tentative = (gScore.get(ck_) ?? Infinity) + 1
      if (tentative < (gScore.get(nk_) ?? Infinity)) {
        cameFrom.set(nk_, ck_)
        gScore.set(nk_, tentative)
        fScore.set(nk_, tentative + heuristic(ni, nj, nk))
        open.add(nk_)
      }
    }
  }

  if (!found) {
    return {
      polyline: [start, end],
      warning: 'A* could not find a path (obstacles may fully block route); returning straight line.',
    }
  }

  // Reconstruct path
  const path = []
  let cur = key(ei, ej, ek)
  while (cur) {
    const [i, j, k] = cur.split(',').map(Number)
    path.unshift(toWorld(i, j, k))
    cur = cameFrom.get(cur)
  }

  // Simplify collinear points
  const simplified = simplifyPolyline(path)

  return { polyline: simplified }
}

function simplifyPolyline(pts) {
  if (pts.length <= 2) return pts
  const result = [pts[0]]
  for (let i = 1; i < pts.length - 1; i++) {
    const prev = result[result.length - 1]
    const cur = pts[i]
    const next = pts[i + 1]
    const d1 = vecSub(cur, prev)
    const d2 = vecSub(next, cur)
    // Check if collinear (same direction)
    const cross = [
      d1[1] * d2[2] - d1[2] * d2[1],
      d1[2] * d2[0] - d1[0] * d2[2],
      d1[0] * d2[1] - d1[1] * d2[0],
    ]
    const collinear = cross.every(v => Math.abs(v) < 1e-9)
    if (!collinear) result.push(cur)
  }
  result.push(pts[pts.length - 1])
  return result
}

/**
 * Auto-route between two existing endpoints in a route using A*.
 * Populates route.segments with straight segments and elbows at turns.
 *
 * @param {object} route
 * @param {string} start_id  — endpoint id
 * @param {string} end_id    — endpoint id
 * @param {Array}  obstacles — AABB boxes
 * @param {number} [gridSize_mm]
 * @returns {{ route: object, warning?: string }}
 */
export function connectEndpoints(route, start_id, end_id, obstacles = [], gridSize_mm = 300) {
  const startEp = route.endpoints.find(e => e.id === start_id)
  const endEp = route.endpoints.find(e => e.id === end_id)

  if (!startEp) throw new Error(`endpoint not found: ${start_id}`)
  if (!endEp) throw new Error(`endpoint not found: ${end_id}`)

  const { polyline, warning } = findShortestRoute(startEp.position, endEp.position, obstacles, gridSize_mm)

  // Build segments from polyline
  let updatedRoute = route
  const elbow_radius_mm = (route.size_mm || 200) * 1.5

  for (let i = 0; i < polyline.length - 1; i++) {
    const from = polyline[i]
    const to = polyline[i + 1]
    const isElbow = i > 0

    const seg = {
      id: `auto_s${Date.now()}_${i}`,
      from,
      to,
      kind: from[2] !== to[2] && from[0] === to[0] && from[1] === to[1] ? 'vertical' : (isElbow ? 'elbow' : 'straight'),
    }
    if (seg.kind === 'elbow') seg.elbow_radius_mm = elbow_radius_mm
    updatedRoute = addSegment(updatedRoute, seg)
  }

  return { route: updatedRoute, warning }
}
