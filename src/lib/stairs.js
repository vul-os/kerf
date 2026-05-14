/**
 * stairs.js — Pure JS parametric staircase geometry.
 *
 * All dimensions in millimetres unless noted.
 * 2R+T comfort formula: 2 × riser_height + tread_depth must be in [550, 700].
 */

// ── defaults ───────────────────────────────────────────────────────────────

/**
 * Build a default stair document.
 * @param {{ total_rise_mm: number, total_run_mm: number }} opts
 * @returns {object}
 */
export function defaultStair({ total_rise_mm, total_run_mm }) {
  return {
    version: 1,
    total_rise_mm,
    total_run_mm,
    tread_depth_mm: 280,
    riser_height_mm: 175,
    nosing_mm: 25,
    width_mm: 1000,
    flights: [],
    landings: [],
    handedness: 'right',
  }
}

// ── validation ─────────────────────────────────────────────────────────────

/**
 * Validate a stair document against building-code comfort rules.
 * @param {object} stair
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateStair(stair) {
  const errors = []

  const r = stair.riser_height_mm
  const t = stair.tread_depth_mm

  if (typeof r !== 'number' || r < 100 || r > 220) {
    errors.push(`riser_height_mm (${r}) must be in [100, 220]`)
  }
  if (typeof t !== 'number' || t < 200 || t > 350) {
    errors.push(`tread_depth_mm (${t}) must be in [200, 350]`)
  }

  if (typeof r === 'number' && typeof t === 'number') {
    const formula = 2 * r + t
    if (formula < 550 || formula > 700) {
      errors.push(`2R+T (${formula}) must be in [550, 700]`)
    }
  }

  if (!stair.flights || !Array.isArray(stair.flights)) {
    errors.push('flights must be an array')
  }
  if (!stair.landings || !Array.isArray(stair.landings)) {
    errors.push('landings must be an array')
  }

  return { ok: errors.length === 0, errors }
}

// ── geometry ───────────────────────────────────────────────────────────────

/**
 * Compute step polygons for a single flight.
 *
 * Each step is described as:
 *   tread  — four corners of the horizontal tread surface
 *   riser  — four corners of the vertical riser face
 *
 * The stair rises in the +z direction and runs in the direction vector.
 *
 * @param {{ id:string, start_point:[x,y,z], direction:[dx,dy,dz], step_count:number }} flight
 * @param {{ riser_height_mm:number, tread_depth_mm:number, nosing_mm:number, width_mm:number }} params
 * @returns {Array<{ tread: number[][], riser: number[][] }>}
 */
export function computeFlightGeometry(flight, params) {
  const { start_point, direction, step_count } = flight
  const { riser_height_mm, tread_depth_mm, nosing_mm, width_mm } = params

  // Normalise direction to unit vector (horizontal component only)
  const [dx, dy] = direction
  const dLen = Math.sqrt(dx * dx + dy * dy) || 1
  const ux = dx / dLen
  const uy = dy / dLen

  // Perpendicular (right-hand) vector for width
  const px = -uy
  const py = ux

  const steps = []
  const [sx, sy, sz] = start_point

  for (let i = 0; i < step_count; i++) {
    // Front-bottom of riser at step i
    const baseX = sx + ux * tread_depth_mm * i
    const baseY = sy + uy * tread_depth_mm * i
    const baseZ = sz + riser_height_mm * i

    // Tread: horizontal surface on top of riser i
    const tZ = baseZ + riser_height_mm
    const nosX = ux * nosing_mm
    const nosY = uy * nosing_mm

    const tread = [
      [baseX - nosX,            baseY - nosY,            tZ],
      [baseX - nosX + px * width_mm, baseY - nosY + py * width_mm, tZ],
      [baseX + ux * tread_depth_mm + px * width_mm, baseY + uy * tread_depth_mm + py * width_mm, tZ],
      [baseX + ux * tread_depth_mm, baseY + uy * tread_depth_mm, tZ],
    ]

    // Riser: vertical face at front of step
    const riser = [
      [baseX,            baseY,            baseZ],
      [baseX + px * width_mm, baseY + py * width_mm, baseZ],
      [baseX + px * width_mm, baseY + py * width_mm, tZ],
      [baseX,            baseY,            tZ],
    ]

    steps.push({ tread, riser })
  }

  return steps
}

// ── mutation helpers ───────────────────────────────────────────────────────

/**
 * Append a flight to a stair document (mutates a copy).
 */
export function addFlight(stair, flight) {
  return { ...stair, flights: [...stair.flights, flight] }
}

/**
 * Append a landing to a stair document (mutates a copy).
 */
export function addLanding(stair, landing) {
  return { ...stair, landings: [...stair.landings, landing] }
}

// ── builder helpers ────────────────────────────────────────────────────────

/**
 * Build a single-flight straight stair connecting pointA to pointB.
 *
 * @param {[x,y,z]} pointA  — bottom of stair
 * @param {[x,y,z]} pointB  — top of stair
 * @param {{ riser_height_mm:number, tread_depth_mm:number, nosing_mm:number, width_mm:number }} params
 * @returns {object}  stair doc
 */
export function straightStairFromAB(pointA, pointB, params) {
  const total_rise_mm = pointB[2] - pointA[2]
  const dx = pointB[0] - pointA[0]
  const dy = pointB[1] - pointA[1]
  const total_run_mm = Math.sqrt(dx * dx + dy * dy)

  const riser_height_mm = params.riser_height_mm || 175
  const step_count = Math.round(total_rise_mm / riser_height_mm)

  const dirLen = total_run_mm || 1
  const direction = [dx / dirLen, dy / dirLen, 0]

  const stair = {
    ...defaultStair({ total_rise_mm, total_run_mm }),
    ...params,
    flights: [],
    landings: [],
  }

  const flight = {
    id: 'flight-1',
    start_point: [...pointA],
    direction,
    step_count,
  }

  return addFlight(stair, flight)
}

/**
 * Build a 90-degree L-shaped two-flight stair.
 *
 * @param {[x,y,z]} start
 * @param {number} leg1_run  — horizontal run of first leg (mm)
 * @param {number} leg2_run  — horizontal run of second leg (mm) — runs perpendicular
 * @param {[w,d]} landing_size  — [width, depth] of intermediate landing (mm)
 * @param {object} params
 * @returns {object}  stair doc
 */
export function lShapeStair(start, leg1_run, leg2_run, landing_size, params) {
  const riser_height_mm = params.riser_height_mm || 175
  const total_run_mm = leg1_run + leg2_run
  const total_rise_mm = params.total_rise_mm || riser_height_mm * 12

  const stepsPerLeg = Math.round((total_rise_mm / riser_height_mm) / 2)

  const [sx, sy, sz] = start

  // Leg 1: runs along +x
  const flight1 = {
    id: 'flight-1',
    start_point: [sx, sy, sz],
    direction: [1, 0, 0],
    step_count: stepsPerLeg,
  }

  // Landing at end of leg 1
  const landingX = sx + leg1_run
  const landingZ = sz + stepsPerLeg * riser_height_mm

  const landing = {
    id: 'landing-1',
    position: [landingX, sy, landingZ],
    size_mm: landing_size,
  }

  // Leg 2: turns 90°, runs along +y
  const flight2 = {
    id: 'flight-2',
    start_point: [landingX, sy, landingZ],
    direction: [0, 1, 0],
    step_count: stepsPerLeg,
  }

  const stair = {
    ...defaultStair({ total_rise_mm, total_run_mm }),
    ...params,
    flights: [],
    landings: [],
  }

  return addLanding(addFlight(addFlight(stair, flight1), flight2), landing)
}

/**
 * Build a 180-degree U-shaped stair (two flights with parallel legs).
 *
 * @param {[x,y,z]} start
 * @param {number} leg_run  — run of each leg (mm)
 * @param {[w,d]} landing_size
 * @param {object} params
 * @returns {object}  stair doc
 */
export function uShapeStair(start, leg_run, landing_size, params) {
  const riser_height_mm = params.riser_height_mm || 175
  const total_run_mm = leg_run * 2
  const total_rise_mm = params.total_rise_mm || riser_height_mm * 12

  const stepsPerLeg = Math.round((total_rise_mm / riser_height_mm) / 2)

  const [sx, sy, sz] = start
  const width_mm = params.width_mm || 1000

  // Leg 1: runs along +x
  const flight1 = {
    id: 'flight-1',
    start_point: [sx, sy, sz],
    direction: [1, 0, 0],
    step_count: stepsPerLeg,
  }

  // Landing at end of leg 1
  const landingX = sx + leg_run
  const landingZ = sz + stepsPerLeg * riser_height_mm

  const landing = {
    id: 'landing-1',
    position: [landingX, sy, landingZ],
    size_mm: landing_size,
  }

  // Leg 2: returns along -x, offset in +y by width
  const flight2 = {
    id: 'flight-2',
    start_point: [landingX, sy + width_mm, landingZ],
    direction: [-1, 0, 0],
    step_count: stepsPerLeg,
  }

  const stair = {
    ...defaultStair({ total_rise_mm, total_run_mm }),
    ...params,
    flights: [],
    landings: [],
  }

  return addLanding(addFlight(addFlight(stair, flight1), flight2), landing)
}
