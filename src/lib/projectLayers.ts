/**
 * Project-level layers + display-mode helpers.
 * Operates on a plain `.canvas.json` object — no side effects.
 */

export interface CanvasLayer {
  id: string
  name: string
  visible: boolean
  color: string
  linetype: string
  material_id: string | null
  locked: boolean
}

export interface CanvasDisplayMode {
  id: string
  name: string
  wireframe: boolean
  edges: boolean
  shadows?: boolean
  transparency?: number
  background_color?: string
  silhouette?: boolean
}

export interface Canvas {
  version: 1
  layers: CanvasLayer[]
  display_modes: CanvasDisplayMode[]
  active_display_mode: string
  active_layer: string
}

const HEX_RE = /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/

function _nextId(canvas: Canvas): string {
  const existing = new Set(canvas.layers.map((l) => l.id))
  let n = canvas.layers.length + 1
  while (existing.has(`L${String(n).padStart(2, '0')}`)) n++
  return `L${String(n).padStart(2, '0')}`
}

/** Return a fresh canvas with sensible defaults. */
export function defaultCanvas(): Canvas {
  return {
    version: 1,
    layers: [
      {
        id: 'L01',
        name: 'Geometry',
        visible: true,
        color: '#ffffff',
        linetype: 'continuous',
        material_id: null,
        locked: false,
      },
    ],
    display_modes: [
      { id: 'shaded',    name: 'Shaded',    wireframe: false, edges: true,  shadows: false, transparency: 1.0,  background_color: '#1a1a1a' },
      { id: 'wireframe', name: 'Wireframe', wireframe: true,  edges: true },
      { id: 'technical', name: 'Technical', wireframe: false, edges: true,  silhouette: true, shadows: false },
      { id: 'rendered',  name: 'Rendered',  wireframe: false, edges: false, shadows: true,  transparency: 0.95 },
    ],
    active_display_mode: 'shaded',
    active_layer: 'L01',
  }
}

/**
 * Add a new layer. Auto-assigns `id`. Returns new canvas (immutable).
 */
export function addLayer(canvas: Canvas, opts: { name: string; color?: string; linetype?: string; material_id?: string | null; locked?: boolean }): Canvas {
  const { name, color = '#ffffff', linetype = 'continuous', material_id = null, locked = false } = opts
  if (!name || !name.trim()) throw new Error('layer name required')
  const id = _nextId(canvas)
  const layer: CanvasLayer = { id, name: name.trim(), visible: true, color, linetype, material_id, locked }
  return { ...canvas, layers: [...canvas.layers, layer] }
}

/**
 * Remove layer by id. Files that were on the removed layer are implicitly
 * reassigned to `active_layer` by the caller; this function just removes the
 * entry and updates active_layer if it pointed to the removed one.
 */
export function removeLayer(canvas: Canvas, layer_id: string): Canvas {
  const filtered = canvas.layers.filter((l) => l.id !== layer_id)
  if (filtered.length === canvas.layers.length) return canvas // not found — no-op
  if (filtered.length === 0) throw new Error('cannot remove the last layer')
  let active = canvas.active_layer
  if (active === layer_id) active = filtered[0].id
  return { ...canvas, layers: filtered, active_layer: active }
}

export function setLayerVisibility(canvas: Canvas, layer_id: string, visible: boolean): Canvas {
  return {
    ...canvas,
    layers: canvas.layers.map((l) => l.id === layer_id ? { ...l, visible: Boolean(visible) } : l),
  }
}

export function setLayerColor(canvas: Canvas, layer_id: string, color: string): Canvas {
  if (!HEX_RE.test(color)) throw new Error(`invalid hex color: ${color}`)
  return {
    ...canvas,
    layers: canvas.layers.map((l) => l.id === layer_id ? { ...l, color } : l),
  }
}

export function setActiveLayer(canvas: Canvas, layer_id: string): Canvas {
  if (!canvas.layers.find((l) => l.id === layer_id)) throw new Error(`layer ${layer_id} not found`)
  return { ...canvas, active_layer: layer_id }
}

export function setActiveDisplayMode(canvas: Canvas, mode_id: string): Canvas {
  if (!canvas.display_modes.find((m) => m.id === mode_id)) throw new Error(`display mode ${mode_id} not found`)
  return { ...canvas, active_display_mode: mode_id }
}

export function getLayer(canvas: Canvas, layer_id: string): CanvasLayer | null {
  return canvas.layers.find((l) => l.id === layer_id) ?? null
}

/**
 * Validate a canvas object.
 */
export function validateCanvas(canvas: unknown): { ok: boolean; errors: string[] } {
  const errors: string[] = []
  if (!canvas || typeof canvas !== 'object') {
    return { ok: false, errors: ['canvas must be an object'] }
  }
  const c = canvas as Partial<Canvas> & Record<string, unknown>
  if (c.version !== 1) errors.push('version must be 1')
  if (!Array.isArray(c.layers)) {
    errors.push('layers must be an array')
  } else {
    const ids = new Set()
    c.layers.forEach((l: Partial<CanvasLayer>, i: number) => {
      if (!l.id)   errors.push(`layers[${i}] missing id`)
      if (!l.name) errors.push(`layers[${i}] missing name`)
      if (l.color && !HEX_RE.test(l.color)) errors.push(`layers[${i}] invalid color: ${l.color}`)
      if (ids.has(l.id)) errors.push(`duplicate layer id: ${l.id}`)
      ids.add(l.id)
    })
    if (!c.layers.find((l: Partial<CanvasLayer>) => l.id === c.active_layer)) {
      errors.push(`active_layer '${c.active_layer}' not in layers`)
    }
  }
  if (!Array.isArray(c.display_modes)) {
    errors.push('display_modes must be an array')
  } else {
    if (!c.display_modes.find((m: Partial<CanvasDisplayMode>) => m.id === c.active_display_mode)) {
      errors.push(`active_display_mode '${c.active_display_mode}' not in display_modes`)
    }
  }
  return { ok: errors.length === 0, errors }
}
