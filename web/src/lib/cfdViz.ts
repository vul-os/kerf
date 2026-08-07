/**
 * cfdViz.ts — Pure helper functions for CFD viewport visualisation.
 *
 * Covers three visual layers that CfdViewport renders on a <canvas>:
 *   1. Streamlines  — traced by streamlineIntegrator, drawn as polylines
 *   2. Vector-field arrow glyphs — sampled on a sub-grid, drawn as arrows
 *   3. Pressure contour overlay — colour-mapped scalar field on the grid
 *
 * All functions are pure (no side-effects beyond the passed-in ctx).
 * No Three.js dependency — everything is Canvas 2D.
 *
 * Data shapes (from openfoam_bridge.py postprocessing output):
 *
 *   vectorField — grid object used by streamlineIntegrator:
 *     { x0, y0, dx, dy, nx, ny, u[][], v[][] }
 *     or { cells: [{x, y, Ux, Uy, p?}, ...] }
 *
 *   pressureField — same spatial grid but with scalar values:
 *     { x0, y0, dx, dy, nx, ny, p[][] }
 *     or extracted from cells[].p
 */

import { traceStreamlines, cellsToGrid, sampleField } from './streamlineIntegrator.js'
import { scalarToRGB } from './femDisplacement.js'
import type { VectorFieldGrid, VectorField, OpenFoamCell, Point2, TraceOpts } from './streamlineIntegrator.js'

// Re-exported so consumers (e.g. CfdViewport.tsx) can import the field shapes
// straight from this module rather than reaching into streamlineIntegrator.js.
export type { VectorFieldGrid, VectorField, OpenFoamCell, Point2, TraceOpts }

// ── Shared shapes ─────────────────────────────────────────────────────────────

/** {@link OpenFoamCell} plus the optional scalar the pressure overlay reads. */
export interface PressureCell extends OpenFoamCell {
  p?: number | null
}

export interface PressureFieldCells {
  cells: PressureCell[]
}

/** {@link VectorFieldGrid} plus the optional `p[][]` scalar grid. */
export type PressureFieldGrid = VectorFieldGrid & { p?: number[][] | null }

export type PressureField = PressureFieldGrid | PressureFieldCells

export interface CanvasPoint {
  cx: number
  cy: number
}

export interface Transform {
  scale: number
  toCanvas(wx: number, wy: number): CanvasPoint
  toWorld(cx: number, cy: number): { wx: number; wy: number }
}

// ── Colour helpers ───────────────────────────────────────────────────────────

/**
 * Convert a normalised scalar [0..1] to a CSS rgba() string.
 * Uses the same blue→cyan→green→yellow→red palette as the FEM overlay.
 */
export function scalarToCssColor(t: number, alpha = 1): string {
  const [r, g, b] = scalarToRGB(t)
  return `rgba(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)},${alpha})`
}

// ── World ↔ canvas coordinate transforms ─────────────────────────────────────

/**
 * Build a transform from world to canvas pixel space.
 *
 * The returned object exposes:
 *   toCanvas(wx, wy) → {cx, cy}
 *   toWorld(cx, cy)  → {wx, wy}
 *
 * @param field  Grid field (provides x0/y0/dx/dy/nx/ny)
 * @param margin  Pixel padding inside canvas
 */
export function buildTransform(
  field: VectorFieldGrid,
  canvasW: number,
  canvasH: number,
  margin = 10,
): Transform {
  const worldW = (field.nx - 1) * field.dx
  const worldH = (field.ny - 1) * field.dy

  const scaleX = (canvasW - 2 * margin) / (worldW || 1)
  const scaleY = (canvasH - 2 * margin) / (worldH || 1)
  // Keep aspect ratio
  const scale = Math.min(scaleX, scaleY)

  const offsetX = margin + ((canvasW - 2 * margin) - worldW * scale) / 2
  const offsetY = margin + ((canvasH - 2 * margin) - worldH * scale) / 2

  return {
    scale,
    toCanvas(wx: number, wy: number): CanvasPoint {
      return {
        cx: offsetX + (wx - field.x0) * scale,
        // y flipped: world y increases up, canvas y increases down
        cy: canvasH - offsetY - (wy - field.y0) * scale,
      }
    },
    toWorld(cx: number, cy: number): { wx: number; wy: number } {
      return {
        wx: (cx - offsetX) / scale + field.x0,
        wy: (canvasH - cy - offsetY) / scale + field.y0,
      }
    },
  }
}

// ── Streamline rendering ─────────────────────────────────────────────────────

export interface DrawStreamlinesOpts {
  traceOpts?: TraceOpts
  color?: string
  lineWidth?: number
  transform?: Transform
  canvasW?: number
  canvasH?: number
}

/**
 * Draw streamlines onto a 2D canvas context.
 *
 * @param seeds  World-space seed points
 */
export function drawStreamlines(
  ctx: CanvasRenderingContext2D,
  vectorField: VectorField,
  seeds: Point2[],
  opts: DrawStreamlinesOpts = {},
): void {
  const {
    traceOpts = {},
    color = 'rgba(100,180,255,0.75)',
    lineWidth = 1.2,
    canvasW = ctx.canvas?.width ?? 300,
    canvasH = ctx.canvas?.height ?? 200,
  } = opts

  const cells = (vectorField as { cells?: OpenFoamCell[] }).cells
  const field = cells ? cellsToGrid(cells) : (vectorField as VectorFieldGrid)
  const transform = opts.transform || buildTransform(field, canvasW, canvasH)
  const lines = traceStreamlines(field, seeds, traceOpts)

  ctx.save()
  ctx.strokeStyle = color
  ctx.lineWidth = lineWidth
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  for (const pts of lines) {
    if (pts.length < 2) continue
    ctx.beginPath()
    for (let i = 0; i < pts.length; i++) {
      const { cx, cy } = transform.toCanvas(pts[i].x, pts[i].y)
      if (i === 0) ctx.moveTo(cx, cy)
      else ctx.lineTo(cx, cy)
    }
    ctx.stroke()
  }

  ctx.restore()
}

// ── Vector field arrow glyphs ────────────────────────────────────────────────

export interface DrawVectorArrowsOpts {
  gridStep?: number
  arrowScale?: number
  color?: string
  lineWidth?: number
  canvasW?: number
  canvasH?: number
  transform?: Transform
}

/**
 * Draw vector-field arrow glyphs sampled on a coarse sub-grid.
 *
 * @param opts.gridStep  Sample every N grid cells
 * @param opts.arrowScale  Max arrow length in canvas pixels (default auto)
 */
export function drawVectorArrows(
  ctx: CanvasRenderingContext2D,
  vectorField: VectorField,
  opts: DrawVectorArrowsOpts = {},
): void {
  const {
    gridStep = 4,
    color = 'rgba(255,220,100,0.85)',
    lineWidth = 1,
    canvasW = ctx.canvas?.width ?? 300,
    canvasH = ctx.canvas?.height ?? 200,
  } = opts

  const cells = (vectorField as { cells?: OpenFoamCell[] }).cells
  const field = cells ? cellsToGrid(cells) : (vectorField as VectorFieldGrid)
  const transform = opts.transform || buildTransform(field, canvasW, canvasH)

  // Compute max speed for normalisation
  let maxSpeed = 0
  for (let row = 0; row < field.ny; row += gridStep) {
    for (let col = 0; col < field.nx; col += gridStep) {
      const vx = field.u[row][col]
      const vy = field.v[row][col]
      const speed = Math.sqrt(vx * vx + vy * vy)
      if (speed > maxSpeed) maxSpeed = speed
    }
  }

  const cellPx = transform.scale * field.dx * gridStep
  const arrowScale = opts.arrowScale ?? Math.max(cellPx * 0.45, 4)
  const norm = maxSpeed > 0 ? 1 / maxSpeed : 1

  ctx.save()
  ctx.strokeStyle = color
  ctx.fillStyle = color
  ctx.lineWidth = lineWidth

  for (let row = 0; row < field.ny; row += gridStep) {
    for (let col = 0; col < field.nx; col += gridStep) {
      const wx = field.x0 + col * field.dx
      const wy = field.y0 + row * field.dy

      const sample = sampleField(field, wx, wy)
      if (!sample) continue

      const speed = Math.sqrt(sample.vx * sample.vx + sample.vy * sample.vy)
      if (speed < 1e-10) continue

      const len = speed * norm * arrowScale
      const angle = Math.atan2(-sample.vy, sample.vx)  // canvas y is flipped

      const { cx, cy } = transform.toCanvas(wx, wy)

      const ex = cx + len * Math.cos(angle)
      const ey = cy + len * Math.sin(angle)

      // Shaft
      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.lineTo(ex, ey)
      ctx.stroke()

      // Arrowhead
      const headLen = Math.max(len * 0.3, 3)
      const headAngle = 0.45  // radians
      ctx.beginPath()
      ctx.moveTo(ex, ey)
      ctx.lineTo(
        ex - headLen * Math.cos(angle - headAngle),
        ey - headLen * Math.sin(angle - headAngle)
      )
      ctx.moveTo(ex, ey)
      ctx.lineTo(
        ex - headLen * Math.cos(angle + headAngle),
        ey - headLen * Math.sin(angle + headAngle)
      )
      ctx.stroke()
    }
  }

  ctx.restore()
}

// ── Pressure contour overlay ─────────────────────────────────────────────────

export interface DrawPressureContourOpts {
  alpha?: number
  minVal?: number | null
  maxVal?: number | null
  canvasW?: number
  canvasH?: number
  transform?: Transform
}

/**
 * Draw a pressure (or generic scalar) contour colour overlay.
 * Renders one filled rectangle per grid cell, coloured by the scalar value.
 *
 * @param pressureField  { x0, y0, dx, dy, nx, ny, p[][] } or { cells: [{x, y, p},...] }
 *   (cells must have .p)
 */
export function drawPressureContour(
  ctx: CanvasRenderingContext2D,
  pressureField: PressureField,
  opts: DrawPressureContourOpts = {},
): void {
  const {
    alpha = 0.45,
    canvasW = ctx.canvas?.width ?? 300,
    canvasH = ctx.canvas?.height ?? 200,
  } = opts

  // Normalise to grid with p[][] array
  let field: PressureFieldGrid
  const cells = (pressureField as PressureFieldCells).cells
  if (cells) {
    const base: PressureFieldGrid = cellsToGrid(cells)
    const pMap = new Map<string, number>()
    for (const c of cells) {
      pMap.set(`${c.x},${c.y}`, c.p ?? 0)
    }
    const xs = [...new Set(cells.map(c => c.x))].sort((a, b) => a - b)
    const ys = [...new Set(cells.map(c => c.y))].sort((a, b) => a - b)
    base.p = ys.map(y => xs.map(x => pMap.get(`${x},${y}`) ?? 0))
    field = base
  } else {
    field = pressureField as PressureFieldGrid
  }

  if (!field.p) return

  // Find range
  let minVal = opts.minVal ?? Infinity
  let maxVal = opts.maxVal ?? -Infinity
  if (opts.minVal == null || opts.maxVal == null) {
    for (let row = 0; row < field.ny; row++) {
      for (let col = 0; col < field.nx; col++) {
        const pv = field.p[row]?.[col] ?? 0
        if (pv < minVal) minVal = pv
        if (pv > maxVal) maxVal = pv
      }
    }
  }
  const range = maxVal - minVal || 1

  const transform = opts.transform || buildTransform(field, canvasW, canvasH)
  const cellW = Math.max(1, transform.scale * field.dx)
  const cellH = Math.max(1, transform.scale * field.dy)

  ctx.save()

  for (let row = 0; row < field.ny; row++) {
    for (let col = 0; col < field.nx; col++) {
      const pv = field.p[row]?.[col] ?? 0
      const t = Math.max(0, Math.min(1, (pv - minVal) / range))
      const cssColor = scalarToCssColor(t, alpha)

      const wx = field.x0 + col * field.dx
      const wy = field.y0 + row * field.dy
      const { cx, cy } = transform.toCanvas(wx, wy)

      ctx.fillStyle = cssColor
      // Top-left of the cell in canvas coords (y is flipped)
      ctx.fillRect(cx, cy - cellH, cellW, cellH)
    }
  }

  ctx.restore()
}

// ── Auto-seed generator ──────────────────────────────────────────────────────

/**
 * Generate a uniform grid of seed positions inside the field domain.
 *
 * @param count  Approximate number of seeds
 */
export function generateSeeds(field: VectorFieldGrid, count = 20): Point2[] {
  const cols = Math.max(1, Math.ceil(Math.sqrt(count)))
  const rows = Math.max(1, Math.ceil(count / cols))

  const worldW = (field.nx - 1) * field.dx
  const worldH = (field.ny - 1) * field.dy

  const seeds: Point2[] = []
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      seeds.push({
        x: field.x0 + (worldW * (c + 0.5)) / cols,
        y: field.y0 + (worldH * (r + 0.5)) / rows,
      })
    }
  }
  return seeds
}

/**
 * Generate seeds along the inlet edge (left column) of the field.
 *
 * @param n  Number of seeds
 */
export function generateInletSeeds(field: VectorFieldGrid, n = 10): Point2[] {
  const seeds: Point2[] = []
  const worldH = (field.ny - 1) * field.dy
  for (let i = 0; i < n; i++) {
    seeds.push({
      x: field.x0 + field.dx * 0.5,                // just inside left boundary
      y: field.y0 + (worldH * (i + 0.5)) / n,
    })
  }
  return seeds
}
