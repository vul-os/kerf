// circuitJsonPatch.ts — immutable helpers for editing Circuit JSON.
//
// Circuit JSON is the flat array format produced by tscircuit / @tscircuit/core.
// Each element is a plain object with a `type` field and type-specific fields.
// All mutations work on the PCB layer:
//   - pcb_component  { pcb_component_id, center:{x,y}, rotation?, … }
//   - pcb_smtpad     { pcb_smtpad_id, pcb_component_id?, x, y, … }
//   - pcb_plated_hole { pcb_plated_hole_id, pcb_component_id?, x, y, … }
//
// API — every function is pure: takes an array + args, returns a new array.
//
//   addFootprint(circuitJson, { footprintFn, refdes, x, y, rotation })
//     Insert a new component (pcb_component + its child pads) into the array.
//     `footprintFn` is one of the library strings ("res", "cap", "dip", …) or
//     a full tscircuit footprint specifier string. The raw pad/hole elements
//     returned by @tscircuit/footprinter are shifted to (x, y) and the
//     component rotation is applied before insertion.
//
//   rotateFootprint(circuitJson, { pcb_component_id, angleDeg })
//     Rotate a component and its child pads in-place (returns new array).
//     Rotation accumulates (adds to existing).
//
//   moveFootprint(circuitJson, { pcb_component_id, x, y })
//     Translate a component and its child pads (absolute position).
//
//   groupMove(circuitJson, { pcb_component_ids, dx, dy })
//     Translate a group of components by (dx, dy) — relative delta.
//
// Design decisions:
//   - Pure / immutable: never mutates the input array or any of its objects.
//   - Footprinter is used for pad geometry only. We never call the tscircuit
//     render pipeline — no React, no workers. Just geometry maths.
//   - IDs are generated as short random hex strings scoped to the session;
//     they're good enough for in-memory editing and don't need to be globally
//     stable until the user exports / commits circuit JSON.
//   - No Zod / schema validation — keep the dep surface minimal. Defensive
//     guards at each entry point.
//
// --- Typing note: a real impedance mismatch (see src/types/circuit.ts) ---
// `addFootprint()`'s synthesized `pcb_component` does NOT structurally satisfy
// circuit-json's real `PcbComponent` — that requires `source_component_id`,
// `layer`, `width`, `height` (none optional) and has no `name` field at all.
// This file also duck-types "extra elements" (silkscreen paths/text, and
// whatever else footprinter emits alongside pads) on `.route` / `.anchor_position`
// / bare `.x,.y` rather than on `.type`. Cross-checking against circuit-json's
// real silkscreen variants: `PcbSilkscreenPath` does have `.route`,
// `PcbSilkscreenText` does have `.anchor_position`, but `PcbSilkscreenRect`/
// `Circle`/`Pill`/`Oval` use `center: {x,y}`, not bare `x`/`y` — so the final
// "bare el.x,el.y" fallback branch below may not correspond to any real
// circuit-json element footprinter actually emits. Not confirmed either way
// (out of scope to chase down here); flagging it as a possible dead branch
// rather than removing it, since removing it would be a behaviour change.
//
// Given this, `addFootprint`'s synthesized component and its "extra element"
// handling are typed against a local `PatchableElement`/`PatchPcbComponent`
// shape rather than forced through `CircuitElement` — see those types below.
//
// Even the pad/hole handling has the same problem: circuit-json's real
// `PcbSmtPad` union includes `PcbSmtPadPolygon` (a `points` array, no bare
// x/y), and its real `PcbPlatedHole` union includes several "with_rect_pad"
// variants (`PcbHoleWithPolygonPad`, `PcbHolePillWithRectPad`,
// `PcbHoleRotatedPillWithRectPad`, `PcbHoleCircularWithRectPad`) that use
// `hole_offset_x`/`hole_offset_y` instead of bare `x`/`y`. This file assumes
// every footprinter-emitted pad is one of the simple bare-x/y variants
// (Circle/Rect/RotatedRect/Pill/RotatedPill) — true in practice for what
// @tscircuit/footprinter emits, but not guaranteed by circuit-json's schema.
// `PadLike` below is that narrower assumption made explicit, rather than
// `Extract<CircuitElement, {type: 'pcb_smtpad'|'pcb_plated_hole'}>`, which
// would (correctly) include the polygon/rect-pad variants this file can't
// actually handle.

import type { CircuitElement, CircuitJson } from '@/types'
import { getFootprintNames, string as fpString } from '@tscircuit/footprinter'

// ---------------------------------------------------------------------------
// Local honest types (see header comment for why these aren't `CircuitElement`)
// ---------------------------------------------------------------------------

/**
 * The pad/hole shape this file actually operates on — see header comment
 * for why this isn't `Extract<CircuitElement, {type: 'pcb_smtpad'|'pcb_plated_hole'}>`.
 */
interface PadLike {
  type: 'pcb_smtpad' | 'pcb_plated_hole'
  pcb_component_id?: string
  x?: number
  y?: number
  [key: string]: unknown
}

/**
 * The structural superset this file actually reads/writes on "extra"
 * (non-pad) footprint elements — silkscreen paths/text and whatever else
 * @tscircuit/footprinter emits alongside pads. See header comment: no
 * single real circuit-json type has all of `route`/`anchor_position`/bare
 * `x,y`, so this stays a local duck-typed shape rather than a cast onto
 * `CircuitElement` at every property access.
 */
interface PatchableElement {
  type?: string
  pcb_component_id?: string
  route?: Array<{ x?: number; y?: number; [key: string]: unknown }>
  anchor_position?: { x?: number; y?: number; [key: string]: unknown }
  x?: number
  y?: number
  [key: string]: unknown
}

/**
 * addFootprint's synthesized `pcb_component` — doesn't satisfy circuit-json's
 * real `PcbComponent` (missing `source_component_id`/`layer`/`width`/
 * `height`; `name` isn't a schema field at all). Typed honestly as its own
 * shape rather than forced through `PcbComponent`. Fixing the mismatch
 * (making this schema-complete) is a behavioural change for a separate task.
 */
interface PatchPcbComponent {
  type: 'pcb_component'
  pcb_component_id: string
  center: { x: number; y: number }
  rotation: number
  name: string
}

export interface AddFootprintOptions {
  /** Full specifier ("res0402", "dip8", …) or bare family name ("res", "dip", …). */
  footprintFn?: string
  refdes?: string
  x?: number
  y?: number
  rotation?: number
  params?: { imperial?: string; metric?: string; num_pins?: number }
}

export interface RotateFootprintOptions {
  pcb_component_id?: string
  /** Degrees to ADD to the current rotation. */
  angleDeg?: number
}

export interface MoveFootprintOptions {
  pcb_component_id?: string
  /** New absolute X in mm. */
  x?: number
  /** New absolute Y in mm. */
  y?: number
}

export interface GroupMoveOptions {
  pcb_component_ids?: string[]
  dx?: number
  dy?: number
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function uid(): string {
  return Math.random().toString(16).slice(2, 10)
}

// Rotate a 2-D point around the origin by `angleDeg` degrees.
function rotatePoint(x: number, y: number, angleDeg: number): { x: number; y: number } {
  const rad = (angleDeg * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  return {
    x: x * cos - y * sin,
    y: x * sin + y * cos,
  }
}

// Translate a pad/hole element by (dx, dy).
function translatePad<T extends { x?: number; y?: number }>(el: T, dx: number, dy: number): T {
  return { ...el, x: (el.x || 0) + dx, y: (el.y || 0) + dy } as T
}

// Rotate a pad/hole element around (cx, cy) by angleDeg.
function rotatePad<T extends { x?: number; y?: number }>(el: T, cx: number, cy: number, angleDeg: number): T {
  const rel = rotatePoint((el.x || 0) - cx, (el.y || 0) - cy, angleDeg)
  return { ...el, x: rel.x + cx, y: rel.y + cy } as T
}

const PAD_TYPES = new Set(['pcb_smtpad', 'pcb_plated_hole'])

function isPadElement(el: unknown): el is PadLike {
  return !!el && typeof el === 'object' && PAD_TYPES.has(String((el as { type?: unknown }).type))
}

// Return true when `el` is a pad/hole that belongs to a given component.
function isPadOf(el: unknown, pcb_component_id: string): el is PadLike {
  return isPadElement(el) && (el as PadLike).pcb_component_id === pcb_component_id
}

// ---------------------------------------------------------------------------
// addFootprint
// ---------------------------------------------------------------------------

// Passive footprint types that require a size argument to produce valid pads.
const PASSIVE_FNS = new Set(['res', 'cap', 'led', 'diode', 'electrolytic', 'melf', 'minimelf', 'micromelf'])

// Default imperial size used when a passive is requested without a size.
const DEFAULT_PASSIVE_SIZE = '0402'

/**
 * Insert a new footprint into circuitJson at position (x, y) with the given
 * rotation. Uses @tscircuit/footprinter to obtain pad geometry.
 *
 * `opts.footprintFn` — full specifier accepted by the footprinter string
 * parser: "res0402", "cap0805", "dip8", "soic8", "qfn16", … OR a bare family
 * name ("res", "cap", "dip") with sizing in opts.params. Bare passives
 * without params default to 0402.
 *
 * Returns a new Circuit JSON array with the footprint appended.
 */
export function addFootprint(circuitJson: CircuitJson, opts: AddFootprintOptions = {}): CircuitJson {
  if (!Array.isArray(circuitJson)) throw new TypeError('circuitJson must be an array')
  const {
    footprintFn = 'res0402',
    refdes,
    x = 0,
    y = 0,
    rotation = 0,
    params = {},
  } = opts

  const known = getFootprintNames()

  // Build the footprinter proxy.
  // We use `fpString(specifier)` which returns a fully configured proxy ready
  // for `.circuitJson()`. This is the canonical API for string specifiers like
  // "res0402", "dip8", "soic16", etc.
  //
  // For bare family names ("res", "dip", …) we construct the specifier from
  // the supplied params so they go through the same path.
  let specifier = String(footprintFn)

  if (typeof footprintFn === 'string' && known.includes(footprintFn)) {
    // Bare family name — build a full specifier.
    if (PASSIVE_FNS.has(footprintFn)) {
      // e.g. "res" → "res0402" (or "res0805" if params.imperial='0805')
      const size = params.imperial || params.metric
        ? (params.metric ? `${params.metric}_metric` : params.imperial)
        : DEFAULT_PASSIVE_SIZE
      specifier = `${footprintFn}${size}`
    } else if (params.num_pins != null) {
      // e.g. "dip" + { num_pins: 8 } → "dip8"
      specifier = `${footprintFn}${params.num_pins}`
    }
    // For all other bare names with no recognized params, pass through as-is
    // and let fpString / footprinter handle or reject.
  }

  let proxy: ReturnType<typeof fpString>
  try {
    proxy = fpString(specifier)
  } catch {
    return circuitJson.slice()
  }

  let rawPads: CircuitElement[]
  try {
    rawPads = proxy.circuitJson()
  } catch {
    // Footprinter failed — return original array unchanged.
    return circuitJson.slice()
  }

  if (!Array.isArray(rawPads)) return circuitJson.slice()

  // Assign a fresh component id.
  const pcb_component_id = `pcb_component_${uid()}`
  const autoRefdes = refdes || `FP${uid().slice(0, 4).toUpperCase()}`

  // Shift pads from footprinter origin to (x, y) and apply rotation.
  //
  // `PadLike` deliberately doesn't extend `CircuitElement` (see header
  // comment), so `Array.prototype.filter`'s type-predicate overload (which
  // requires the narrowed type to extend the array's element type) can't
  // apply here — hence the explicit cast rather than relying on
  // `.filter(isPadElement)` to narrow on its own.
  const processedPads = (rawPads.filter((el) => isPadElement(el)) as unknown as PadLike[])
    .map((el): PadLike => {
      // Rotate first (around footprinter origin), then translate.
      const rotated = rotatePad(el, 0, 0, rotation)
      const translated = translatePad(rotated, x, y)
      const idField = el.type === 'pcb_smtpad' ? 'pcb_smtpad_id' : 'pcb_plated_hole_id'
      return {
        ...translated,
        [idField]: `${el.type}_${uid()}`,
        pcb_component_id,
      } as PadLike
    })

  // Keep non-pad footprinter elements (silkscreen, courtyard, …) shifted too.
  const extraElements = rawPads
    .filter((el) => !isPadElement(el))
    .map((el) => {
      const pel = el as unknown as PatchableElement
      // Silkscreen paths have a `route` array of {x,y} points.
      if (pel.route && Array.isArray(pel.route)) {
        const rotatedRoute = pel.route.map((pt) => {
          const r = rotatePoint(pt.x || 0, pt.y || 0, rotation)
          return { ...pt, x: r.x + x, y: r.y + y }
        })
        return { ...pel, route: rotatedRoute, pcb_component_id }
      }
      // Silkscreen text: shift center.
      if (pel.anchor_position || (pel.x != null && pel.y != null)) {
        if (pel.anchor_position) {
          const r = rotatePoint(pel.anchor_position.x || 0, pel.anchor_position.y || 0, rotation)
          return {
            ...pel,
            anchor_position: { ...pel.anchor_position, x: r.x + x, y: r.y + y },
            pcb_component_id,
          }
        }
        const rotated = rotatePad(pel, 0, 0, rotation)
        return { ...translatePad(rotated, x, y), pcb_component_id }
      }
      return { ...pel, pcb_component_id }
    })

  const pcbComponent: PatchPcbComponent = {
    type: 'pcb_component',
    pcb_component_id,
    center: { x, y },
    rotation,
    name: autoRefdes,
  }

  return [...circuitJson, pcbComponent, ...processedPads, ...extraElements] as CircuitJson
}

// ---------------------------------------------------------------------------
// rotateFootprint
// ---------------------------------------------------------------------------

/** Rotate a component (and its child pads) by `angleDeg` (accumulated). */
export function rotateFootprint(circuitJson: CircuitJson, opts: RotateFootprintOptions = {}): CircuitJson {
  if (!Array.isArray(circuitJson)) throw new TypeError('circuitJson must be an array')
  const { pcb_component_id, angleDeg = 0 } = opts
  if (!pcb_component_id) throw new Error('pcb_component_id is required')
  if (typeof angleDeg !== 'number' || !Number.isFinite(angleDeg)) {
    throw new TypeError('angleDeg must be a finite number')
  }

  // Find the component to get its current centre.
  const comp = circuitJson.find(
    (el) => el && el.type === 'pcb_component' && el.pcb_component_id === pcb_component_id
  )
  if (!comp) return circuitJson.slice()

  const cx = ('center' in comp && comp.center && comp.center.x) || 0
  const cy = ('center' in comp && comp.center && comp.center.y) || 0

  return circuitJson.map((el) => {
    if (!el) return el
    if (el.type === 'pcb_component' && el.pcb_component_id === pcb_component_id) {
      return { ...el, rotation: ((el.rotation || 0) + angleDeg) % 360 }
    }
    if (isPadOf(el, pcb_component_id)) {
      return rotatePad(el, cx, cy, angleDeg)
    }
    // Silkscreen/courtyard elements that belong to this component.
    const pel = el as unknown as PatchableElement
    if (pel.pcb_component_id === pcb_component_id) {
      if (pel.route && Array.isArray(pel.route)) {
        return {
          ...el,
          route: pel.route.map((pt) => {
            const r = rotatePoint((pt.x || 0) - cx, (pt.y || 0) - cy, angleDeg)
            return { ...pt, x: r.x + cx, y: r.y + cy }
          }),
        }
      }
      if (pel.anchor_position) {
        const r = rotatePoint(
          (pel.anchor_position.x || 0) - cx,
          (pel.anchor_position.y || 0) - cy,
          angleDeg
        )
        return {
          ...el,
          anchor_position: { ...pel.anchor_position, x: r.x + cx, y: r.y + cy },
        }
      }
      if (pel.x != null && pel.y != null) {
        return rotatePad(pel, cx, cy, angleDeg)
      }
    }
    return el
  }) as CircuitJson
}

// ---------------------------------------------------------------------------
// moveFootprint
// ---------------------------------------------------------------------------

/** Move a component to an absolute position (x, y). */
export function moveFootprint(circuitJson: CircuitJson, opts: MoveFootprintOptions = {}): CircuitJson {
  if (!Array.isArray(circuitJson)) throw new TypeError('circuitJson must be an array')
  const { pcb_component_id, x = 0, y = 0 } = opts
  if (!pcb_component_id) throw new Error('pcb_component_id is required')
  if (typeof x !== 'number' || !Number.isFinite(x)) throw new TypeError('x must be a finite number')
  if (typeof y !== 'number' || !Number.isFinite(y)) throw new TypeError('y must be a finite number')

  const comp = circuitJson.find(
    (el) => el && el.type === 'pcb_component' && el.pcb_component_id === pcb_component_id
  )
  if (!comp) return circuitJson.slice()

  const oldCx = ('center' in comp && comp.center && comp.center.x) || 0
  const oldCy = ('center' in comp && comp.center && comp.center.y) || 0
  const dx = x - oldCx
  const dy = y - oldCy

  return circuitJson.map((el) => {
    if (!el) return el
    if (el.type === 'pcb_component' && el.pcb_component_id === pcb_component_id) {
      return { ...el, center: { x, y } }
    }
    if (isPadOf(el, pcb_component_id)) {
      return translatePad(el, dx, dy)
    }
    const pel = el as unknown as PatchableElement
    if (pel.pcb_component_id === pcb_component_id) {
      if (pel.route && Array.isArray(pel.route)) {
        return {
          ...el,
          route: pel.route.map((pt) => ({ ...pt, x: (pt.x || 0) + dx, y: (pt.y || 0) + dy })),
        }
      }
      if (pel.anchor_position) {
        return {
          ...el,
          anchor_position: {
            ...pel.anchor_position,
            x: (pel.anchor_position.x || 0) + dx,
            y: (pel.anchor_position.y || 0) + dy,
          },
        }
      }
      if (pel.x != null && pel.y != null) {
        return translatePad(pel, dx, dy)
      }
    }
    return el
  }) as CircuitJson
}

// ---------------------------------------------------------------------------
// groupMove
// ---------------------------------------------------------------------------

/** Move a group of components by a relative delta (dx, dy). */
export function groupMove(circuitJson: CircuitJson, opts: GroupMoveOptions = {}): CircuitJson {
  if (!Array.isArray(circuitJson)) throw new TypeError('circuitJson must be an array')
  const { pcb_component_ids = [], dx = 0, dy = 0 } = opts
  if (!Array.isArray(pcb_component_ids)) throw new TypeError('pcb_component_ids must be an array')
  if (typeof dx !== 'number' || !Number.isFinite(dx)) throw new TypeError('dx must be a finite number')
  if (typeof dy !== 'number' || !Number.isFinite(dy)) throw new TypeError('dy must be a finite number')

  if (pcb_component_ids.length === 0) return circuitJson.slice()

  const idSet = new Set(pcb_component_ids)

  return circuitJson.map((el) => {
    if (!el) return el
    if (el.type === 'pcb_component' && idSet.has(el.pcb_component_id)) {
      const cx = (el.center && el.center.x) || 0
      const cy = (el.center && el.center.y) || 0
      return { ...el, center: { x: cx + dx, y: cy + dy } }
    }
    const pel = el as unknown as PatchableElement
    if (PAD_TYPES.has(String(pel.type)) && idSet.has(String(pel.pcb_component_id))) {
      return translatePad(pel, dx, dy)
    }
    if (pel.pcb_component_id && idSet.has(pel.pcb_component_id)) {
      if (pel.route && Array.isArray(pel.route)) {
        return {
          ...el,
          route: pel.route.map((pt) => ({ ...pt, x: (pt.x || 0) + dx, y: (pt.y || 0) + dy })),
        }
      }
      if (pel.anchor_position) {
        return {
          ...el,
          anchor_position: {
            ...pel.anchor_position,
            x: (pel.anchor_position.x || 0) + dx,
            y: (pel.anchor_position.y || 0) + dy,
          },
        }
      }
      if (pel.x != null && pel.y != null) {
        return translatePad(pel, dx, dy)
      }
    }
    return el
  }) as CircuitJson
}
