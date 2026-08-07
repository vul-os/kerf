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

export interface VectorFieldGrid {
  /** World x-coordinate of the col=0 grid line. */
  x0: number
  /** World y-coordinate of the row=0 grid line. */
  y0: number
  /** Grid spacing (world units per cell), x and y. */
  dx: number
  dy: number
  /** Column / row count. */
  nx: number
  ny: number
  /** `u[row][col]` — x-component; `v[row][col]` — y-component. */
  u: number[][]
  v: number[][]
}

/** The flat OpenFOAM bridge shape — converted to {@link VectorFieldGrid} via cellsToGrid(). */
export interface OpenFoamCell {
  x: number
  y: number
  Ux?: number
  Uy?: number
}

export interface VectorFieldCells {
  cells: OpenFoamCell[]
}

export type VectorField = VectorFieldGrid | VectorFieldCells

export interface Point2 {
  x: number
  y: number
}

export interface FieldSample {
  vx: number
  vy: number
}

export interface TraceOpts {
  /** Iteration cap. Default 2000. */
  max_steps?: number
  /** Euler/RK4 step size in world units. Default 0.05. */
  dt?: number
  /** Bail when |v| drops below this. Default 1e-6. */
  min_speed?: number
  /** Squared distance for closed-loop detection. Default 1e-3. */
  loop_tol?: number
}

// ── Bilinear sampling ────────────────────────────────────────────────────────

/**
 * Bilinearly sample the vector field at world position (wx, wy).
 * Returns {vx, vy} or null when outside the domain.
 */
export function sampleField(field: VectorFieldGrid, wx: number, wy: number): FieldSample | null {
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
interface Rk4Result extends Point2, FieldSample {}

function rk4Step(field: VectorFieldGrid, px: number, py: number, dt: number): Rk4Result | null {
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
export function cellsToGrid(cells: OpenFoamCell[] | null | undefined): VectorFieldGrid {
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
  const map = new Map<string, OpenFoamCell>()
  for (const c of cells) {
    map.set(`${c.x},${c.y}`, c)
  }

  const u: number[][] = []
  const v: number[][] = []
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
 * @param vectorField  Grid field (see module doc) or {cells:[...]} shape
 * @param seed  World-space starting position
 * @returns Array of world-space points, including the seed as the first point.
 */
export function traceStreamline(vectorField: VectorField, seed: Point2, opts: TraceOpts = {}): Point2[] {
  const {
    max_steps = 2000,
    dt = 0.05,
    min_speed = 1e-6,
    loop_tol = 1e-3,
  } = opts

  // Normalise to grid form if needed. Matches the original untyped truthiness check
  // (`vectorField.cells ? ... : ...`) rather than `'cells' in vectorField`, which would
  // subtly differ if a caller ever passed `{ cells: undefined, ... }`.
  const cells = (vectorField as VectorFieldCells).cells
  const field = cells ? cellsToGrid(cells) : (vectorField as VectorFieldGrid)

  const points: Point2[] = [{ x: seed.x, y: seed.y }]
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
 * @returns One array of points per seed.
 */
export function traceStreamlines(vectorField: VectorField, seeds: Point2[], opts: TraceOpts = {}): Point2[][] {
  return seeds.map(seed => traceStreamline(vectorField, seed, opts))
}
