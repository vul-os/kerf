/**
 * layoutCanvas.js — Pure coordinate-math helpers for the layout viewer.
 *
 * No DOM, no React, no Canvas API — all functions accept plain objects and
 * return plain objects so they are trivially unit-testable.
 *
 * View state is a plain object:
 *   { offsetX, offsetY, zoom }
 *
 * where (offsetX, offsetY) is the screen-space position of world origin (0,0),
 * and zoom is pixels-per-world-unit.
 *
 * World coordinates use the layout coordinate system (µm or nm as-is).
 * Screen coordinates are canvas pixels (Y down, as usual for HTML Canvas).
 */

// ── Coordinate transforms ─────────────────────────────────────────────────────

/**
 * Convert a world-space point to a canvas-pixel point.
 *
 * @param {{ x: number, y: number }} p   World point
 * @param {{ offsetX: number, offsetY: number, zoom: number }} view
 * @returns {{ x: number, y: number }}   Screen point
 */
export function worldToScreen(p, view) {
  return {
    x: p.x * view.zoom + view.offsetX,
    y: -p.y * view.zoom + view.offsetY, // Y is flipped: layout Y-up → screen Y-down
  }
}

/**
 * Convert a canvas-pixel point back to world-space.
 *
 * @param {{ x: number, y: number }} p   Screen point
 * @param {{ offsetX: number, offsetY: number, zoom: number }} view
 * @returns {{ x: number, y: number }}   World point
 */
export function screenToWorld(p, view) {
  return {
    x: (p.x - view.offsetX) / view.zoom,
    y: -((p.y - view.offsetY) / view.zoom), // invert the Y-flip
  }
}

// ── Bounds / fit ──────────────────────────────────────────────────────────────

/**
 * Compute the axis-aligned bounding box of a flat array of shapes.
 *
 * Supported shape kinds:
 *   Box:       { kind: 'box',     x, y, w, h }
 *   Polygon:   { kind: 'polygon', points: [{ x, y }, …] }
 *   Path:      { kind: 'path',    points: [{ x, y }, …], width }
 *   Text:      { kind: 'text',    x, y }   (single point, no extent)
 *   Reference: { kind: 'ref',     shapes: […] }  (recursive)
 *
 * @param {Array} shapes
 * @returns {{ minX, minY, maxX, maxY } | null}
 */
export function shapeBounds(shapes) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity

  function visit(s) {
    if (!s) return
    if (s.kind === 'box') {
      minX = Math.min(minX, s.x)
      minY = Math.min(minY, s.y)
      maxX = Math.max(maxX, s.x + s.w)
      maxY = Math.max(maxY, s.y + s.h)
    } else if (s.kind === 'polygon' || s.kind === 'path') {
      if (Array.isArray(s.points)) {
        for (const pt of s.points) {
          minX = Math.min(minX, pt.x)
          minY = Math.min(minY, pt.y)
          maxX = Math.max(maxX, pt.x)
          maxY = Math.max(maxY, pt.y)
        }
      }
    } else if (s.kind === 'text') {
      minX = Math.min(minX, s.x)
      minY = Math.min(minY, s.y)
      maxX = Math.max(maxX, s.x)
      maxY = Math.max(maxY, s.y)
    } else if (s.kind === 'ref') {
      if (Array.isArray(s.shapes)) {
        for (const child of s.shapes) visit(child)
      }
    }
  }

  for (const s of shapes) visit(s)

  if (!isFinite(minX)) return null
  return { minX, minY, maxX, maxY }
}

/**
 * Compute the initial view that fits all shapes inside the given viewport with
 * 10 % padding on each side.
 *
 * @param {Array} shapes
 * @param {{ width: number, height: number }} viewport  Canvas pixel dimensions
 * @returns {{ offsetX: number, offsetY: number, zoom: number }}
 */
export function fitBounds(shapes, viewport) {
  const PADDING = 0.10 // 10 %

  const bb = shapeBounds(shapes)
  if (!bb) {
    // No shapes — return identity view centred at origin
    return { offsetX: viewport.width / 2, offsetY: viewport.height / 2, zoom: 1 }
  }

  const worldW = bb.maxX - bb.minX
  const worldH = bb.maxY - bb.minY

  const availW = viewport.width  * (1 - 2 * PADDING)
  const availH = viewport.height * (1 - 2 * PADDING)

  let zoom
  if (worldW === 0 && worldH === 0) {
    zoom = 1
  } else if (worldW === 0) {
    zoom = availH / worldH
  } else if (worldH === 0) {
    zoom = availW / worldW
  } else {
    zoom = Math.min(availW / worldW, availH / worldH)
  }

  // World centroid
  const cx = (bb.minX + bb.maxX) / 2
  const cy = (bb.minY + bb.maxY) / 2

  // The centroid should map to the screen centre
  // worldToScreen: screenX = cx * zoom + offsetX  =>  offsetX = screenCX - cx * zoom
  // worldToScreen: screenY = -cy * zoom + offsetY  =>  offsetY = screenCY + cy * zoom
  const offsetX = viewport.width  / 2 - cx * zoom
  const offsetY = viewport.height / 2 + cy * zoom

  return { offsetX, offsetY, zoom }
}

// ── Hit testing ───────────────────────────────────────────────────────────────

/**
 * Decide whether a world-space point is inside / on a shape.
 *
 * Returns true if the point hits the shape, false otherwise.
 *
 * Supported: box, polygon, path (approximated as line segments with width),
 *            text (point equality within tolerance), ref (recursive any-hit).
 *
 * @param {object} shape
 * @param {{ x: number, y: number }} point  World-space point
 * @returns {boolean}
 */
export function hitTest(shape, point) {
  if (!shape) return false

  if (shape.kind === 'box') {
    return (
      point.x >= shape.x &&
      point.x <= shape.x + shape.w &&
      point.y >= shape.y &&
      point.y <= shape.y + shape.h
    )
  }

  if (shape.kind === 'polygon') {
    return _pointInPolygon(point, shape.points ?? [])
  }

  if (shape.kind === 'path') {
    const halfW = (shape.width ?? 0) / 2
    const pts = shape.points ?? []
    for (let i = 0; i < pts.length - 1; i++) {
      if (_distPointSegment(point, pts[i], pts[i + 1]) <= halfW) return true
    }
    return false
  }

  if (shape.kind === 'text') {
    const TOL = 1e-6
    return Math.abs(point.x - shape.x) < TOL && Math.abs(point.y - shape.y) < TOL
  }

  if (shape.kind === 'ref') {
    for (const child of (shape.shapes ?? [])) {
      if (hitTest(child, point)) return true
    }
    return false
  }

  return false
}

// ── Private helpers ───────────────────────────────────────────────────────────

/**
 * Ray-casting point-in-polygon (even-odd rule).
 * @param {{ x, y }} pt
 * @param {Array<{ x, y }>} poly
 * @returns {boolean}
 */
function _pointInPolygon(pt, poly) {
  if (poly.length < 3) return false
  let inside = false
  const n = poly.length
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = poly[i].x, yi = poly[i].y
    const xj = poly[j].x, yj = poly[j].y
    const intersect =
      yi > pt.y !== yj > pt.y &&
      pt.x < ((xj - xi) * (pt.y - yi)) / (yj - yi) + xi
    if (intersect) inside = !inside
  }
  return inside
}

/**
 * Perpendicular distance from point p to segment (a, b).
 */
function _distPointSegment(p, a, b) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) {
    // Degenerate segment
    return Math.hypot(p.x - a.x, p.y - a.y)
  }
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  const projX = a.x + t * dx
  const projY = a.y + t * dy
  return Math.hypot(p.x - projX, p.y - projY)
}

// ── Canvas draw helpers (DOM-coupled, but isolated here for reuse) ────────────

/**
 * Draw a single shape onto a Canvas 2D context using the provided colours.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {object} shape
 * @param {{ fill: string, stroke: string }} colors
 * @param {{ offsetX, offsetY, zoom }} view
 */
export function drawShape(ctx, shape, colors, view) {
  if (!shape) return

  ctx.fillStyle   = colors.fill
  ctx.strokeStyle = colors.stroke
  ctx.lineWidth   = Math.max(1, view.zoom * 0.02)

  if (shape.kind === 'box') {
    const s = worldToScreen({ x: shape.x, y: shape.y + shape.h }, view)
    const w = shape.w * view.zoom
    const h = shape.h * view.zoom
    ctx.beginPath()
    ctx.rect(s.x, s.y, w, h)
    ctx.fill()
    ctx.stroke()
    return
  }

  if (shape.kind === 'polygon' || shape.kind === 'path') {
    const pts = shape.points ?? []
    if (pts.length < 2) return
    ctx.beginPath()
    const p0 = worldToScreen(pts[0], view)
    ctx.moveTo(p0.x, p0.y)
    for (let i = 1; i < pts.length; i++) {
      const p = worldToScreen(pts[i], view)
      ctx.lineTo(p.x, p.y)
    }
    if (shape.kind === 'polygon') {
      ctx.closePath()
      ctx.fill()
    }
    ctx.stroke()
    return
  }

  if (shape.kind === 'text') {
    const s = worldToScreen({ x: shape.x, y: shape.y }, view)
    const fontSize = Math.max(8, view.zoom * (shape.size ?? 1))
    ctx.font = `${fontSize}px monospace`
    ctx.fillStyle = colors.stroke // text in stroke colour
    ctx.fillText(shape.label ?? '', s.x, s.y)
    return
  }

  if (shape.kind === 'ref') {
    for (const child of (shape.shapes ?? [])) {
      drawShape(ctx, child, colors, view)
    }
  }
}

/**
 * Render all shapes for a complete layout cell onto the canvas.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {Array} shapes
 * @param {Map<number|string, { fill, stroke }>} layerColors
 *   Map from layer id (number or name-string) to fill/stroke colours.
 * @param {{ offsetX, offsetY, zoom }} view
 * @param {Set<number|string>} visibleLayers
 *   Set of layer ids that are currently visible.
 */
export function renderLayout(ctx, shapes, layerColors, view, visibleLayers) {
  const fallback = { fill: 'rgba(180,180,180,0.3)', stroke: 'rgba(120,120,120,0.8)' }

  function visitShape(s) {
    if (!s) return

    if (s.kind === 'ref') {
      for (const child of (s.shapes ?? [])) visitShape(child)
      return
    }

    const lid = s.layer ?? s.layerNum ?? 0
    if (visibleLayers && !visibleLayers.has(lid)) return

    const colors = layerColors.get(lid) ?? fallback
    drawShape(ctx, s, colors, view)
  }

  for (const s of shapes) visitShape(s)
}
