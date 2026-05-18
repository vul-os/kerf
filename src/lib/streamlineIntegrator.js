/**
 * streamlineIntegrator.js — RK4 streamline tracer over a 2-D vector field.
 *
 * The vector field is defined on a regular grid:
 *   vectorField.u[row][col]  — x-component at grid node (col, row)
 *   vectorField.v[row][col]  — y-component at grid node (col, row)
 *   vectorField.x0, .y0     — world coordinate of col=0, row=0
 *   vectorField.dx, .dy     — grid spacing (world units per cell)
 *   vectorField.nx, .ny     — number of columns / rows
 *
 * Alternatively the field may be supplied in the flat OpenFOAM bridge shape:
 *   vectorField.cells        — [{x, y, Ux, Uy}, ...]
 *   in which case it is converted to grid form on first call.
 *
 * Public API
 * ----------
 * traceStreamline(vectorField, seed, options) → [{x, y}, ...]
 *
 *   seed      {x, y}  — world-space starting position
 *   options:
 *     max_steps  (number, default 2000)  — iteration cap
 *     dt         (number, default 0.05)  — Euler/RK4 step size in world units
 *     min_speed  (number, default 1e-6)  — bail when |v| drops below this
 *     loop_tol   (number, default 1e-3)  — squared distance for closed-loop detection
 *
 * Returns array of {x, y} world-space points along the streamline,
 * including the seed as the first point.
 */

// ── Bilinear sampling ────────────────────────────────────────────────────────

/**
 * Bilinearly sample the vector field at world position (wx, wy).
 * Returns {vx, vy} or null when outside the domain.
 */
export function sampleField(field, wx, wy) {
  const { x0, y0, dx, dy, nx, ny, u, v } = field

  // Map to fractional grid indices
  const fx = (wx - x0) / dx
  const fy = (wy - y0) / dy

  // Domain check (strict: bail at boundary)
  if (fx < 0 || fy < 0 || fx >= nx - 1 || fy >= ny - 1) return null

  const col = Math.floor(fx)
  const row = Math.floor(fy)
  const s = fx - col  // fractional part in x
  const t = fy - row  // fractional part in y

  // Four corners
  const u00 = u[row][col]
  const u10 = u[row][col + 1]
  const u01 = u[row + 1][col]
  const u11 = u[row + 1][col + 1]

  const v00 = v[row][col]
  const v10 = v[row][col + 1]
  const v01 = v[row + 1][col]
  const v11 = v[row + 1][col + 1]

  // Bilinear interpolation
  const vx = u00 * (1 - s) * (1 - t) + u10 * s * (1 - t) + u01 * (1 - s) * t + u11 * s * t
  const vy = v00 * (1 - s) * (1 - t) + v10 * s * (1 - t) + v01 * (1 - s) * t + v11 * s * t

  return { vx, vy }
}

// ── RK4 step ────────────────────────────────────────────────────────────────

/**
 * Advance position (px, py) by one RK4 step of size dt.
 * Returns {x, y, vx, vy} or null if any intermediate sample leaves the domain.
 */
function rk4Step(field, px, py, dt) {
  const k1 = sampleField(field, px, py)
  if (!k1) return null

  const k2 = sampleField(field, px + 0.5 * dt * k1.vx, py + 0.5 * dt * k1.vy)
  if (!k2) return null

  const k3 = sampleField(field, px + 0.5 * dt * k2.vx, py + 0.5 * dt * k2.vy)
  if (!k3) return null

  const k4 = sampleField(field, px + dt * k3.vx, py + dt * k3.vy)
  if (!k4) return null

  const nx = px + (dt / 6) * (k1.vx + 2 * k2.vx + 2 * k3.vx + k4.vx)
  const ny = py + (dt / 6) * (k1.vy + 2 * k2.vy + 2 * k3.vy + k4.vy)
  const vx = (k1.vx + 2 * k2.vx + 2 * k3.vx + k4.vx) / 6
  const vy = (k1.vy + 2 * k2.vy + 2 * k3.vy + k4.vy) / 6

  return { x: nx, y: ny, vx, vy }
}

// ── Grid builder from flat cell list (OpenFOAM bridge shape) ─────────────────

/**
 * Convert a flat cell list [{x, y, Ux, Uy}, ...] into a structured grid.
 * Assumes cells are on a regular Cartesian grid; derives x0/y0/dx/dy/nx/ny.
 *
 * Returns a grid object usable by sampleField/traceStreamline.
 * If the cell list is empty, returns a 1×1 zero-field grid.
 */
export function cellsToGrid(cells) {
  if (!cells || cells.length === 0) {
    return { x0: 0, y0: 0, dx: 1, dy: 1, nx: 1, ny: 1, u: [[0]], v: [[0]] }
  }

  const xs = [...new Set(cells.map(c => c.x))].sort((a, b) => a - b)
  const ys = [...new Set(cells.map(c => c.y))].sort((a, b) => a - b)

  const nx = xs.length
  const ny = ys.length
  const dx = nx > 1 ? xs[1] - xs[0] : 1
  const dy = ny > 1 ? ys[1] - ys[0] : 1

  // Build lookup map
  const map = new Map()
  for (const c of cells) {
    map.set(`${c.x},${c.y}`, c)
  }

  const u = []
  const v = []
  for (let row = 0; row < ny; row++) {
    u.push([])
    v.push([])
    for (let col = 0; col < nx; col++) {
      const key = `${xs[col]},${ys[row]}`
      const c = map.get(key)
      u[row].push(c ? (c.Ux || 0) : 0)
      v[row].push(c ? (c.Uy || 0) : 0)
    }
  }

  return { x0: xs[0], y0: ys[0], dx, dy, nx, ny, u, v }
}

// ── Main tracer ──────────────────────────────────────────────────────────────

/**
 * Trace a streamline through the vector field using RK4 integration.
 *
 * @param {object} vectorField  Grid field (see module doc) or {cells:[...]} shape
 * @param {{x:number, y:number}} seed  World-space starting position
 * @param {object} [opts]
 * @param {number} [opts.max_steps=2000]
 * @param {number} [opts.dt=0.05]
 * @param {number} [opts.min_speed=1e-6]
 * @param {number} [opts.loop_tol=1e-3]  Squared-distance threshold for closed-loop
 * @returns {{x:number, y:number}[]}  Array of world-space points
 */
export function traceStreamline(vectorField, seed, opts = {}) {
  const {
    max_steps = 2000,
    dt = 0.05,
    min_speed = 1e-6,
    loop_tol = 1e-3,
  } = opts

  // Normalise to grid form if needed
  const field = vectorField.cells ? cellsToGrid(vectorField.cells) : vectorField

  const points = [{ x: seed.x, y: seed.y }]
  let px = seed.x
  let py = seed.y

  // Store seed for closed-loop detection (compare against every 50 steps to
  // avoid O(n²) but catch the closure reliably)
  const seedX = seed.x
  const seedY = seed.y
  const CHECK_INTERVAL = 50

  for (let step = 0; step < max_steps; step++) {
    const result = rk4Step(field, px, py, dt)
    if (!result) break  // left domain

    const speed2 = result.vx * result.vx + result.vy * result.vy
    if (speed2 < min_speed * min_speed) break  // stagnation

    px = result.x
    py = result.y
    points.push({ x: px, y: py })

    // Closed-loop detection: after some initial travel, check distance to seed
    if (step > CHECK_INTERVAL && step % CHECK_INTERVAL === 0) {
      const dx = px - seedX
      const dy = py - seedY
      if (dx * dx + dy * dy < loop_tol) break
    }
  }

  return points
}

/**
 * Trace multiple streamlines from an array of seed positions.
 *
 * @param {object} vectorField
 * @param {{x:number, y:number}[]} seeds
 * @param {object} [opts]  Same as traceStreamline opts
 * @returns {{x:number, y:number}[][]}  One array of points per seed
 */
export function traceStreamlines(vectorField, seeds, opts = {}) {
  return seeds.map(seed => traceStreamline(vectorField, seed, opts))
}
