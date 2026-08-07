// circuitCanvasTypes.ts — shared types for src/components/CircuitCanvas/ (T-510).
//
// Local to this folder (not src/types/) — the PCB-space geometry helpers and the loosely-
// duck-typed Circuit JSON element shapes this folder's wire-edit/DRC/ratsnest logic reads and
// writes.
//
// --- Why these are NOT `CircuitElement`/`CircuitJson` from src/types ---
// `src/types/circuit.ts` is the canonical seam (`CircuitElement`/`CircuitJson`, re-exporting
// circuit-json's real zod-inferred `AnyCircuitElement`/`CircuitJson`) and every consumer in
// this codebase should reach for it instead of importing `circuit-json` directly — this file
// does not import from the `circuit-json` package. But the *real* schema doesn't match what
// this folder's pure-logic helpers (wireEdit.ts, RatsnestLayer.tsx) actually read and write,
// confirmed against `node_modules/circuit-json/dist/index.d.mts`:
//   - `PcbTrace.route` items are `PcbTraceRoutePointWire | PcbTraceRoutePointVia`, both of
//     which *require* `width`/`layer`/`route_type`. wireEdit.ts's route points are bare
//     `{x, y}` — confirmed against wireEdit.test.js's own fixtures, which never set those
//     fields either.
//   - `PcbTrace` has no `points` field at all; wireEdit.ts's `el.route ?? el.points ?? []`
//     fallback reads a field the real type doesn't have (looks like dead legacy code — see
//     the migration report for this slice).
//   - `PcbSmtPad`/`PcbPlatedHole` have no `net_id`/`net`/`net_name` field; net membership in
//     real Circuit JSON is tracked indirectly via ports/traces, not a direct property on the
//     pad. RatsnestLayer.tsx's `extractPadsByNet` reads exactly those three fallback field
//     names, and ratsnest.test.jsx's fixtures set `net_id` directly the same way.
// This is a pre-existing, real impedance mismatch between this folder and the actual Circuit
// JSON schema — not introduced by this slice, and out of scope to fix here (the fix belongs
// wherever these elements are actually produced upstream, e.g. circuitJsonPatch.js/T-504,
// which src/types/circuit.ts's own header comment already flags for the same reason). The
// types below describe the shape this folder's code and tests actually agree on today.

/** A point in PCB space (millimetres). */
export interface PcbPoint {
  x: number
  y: number
}

/** One route point as wireEdit.ts actually reads/writes it — see the file header for why
 *  this is looser than circuit-json's real `PcbTraceRoutePointWire | PcbTraceRoutePointVia`. */
export interface TraceRoutePoint extends PcbPoint {
  [field: string]: unknown
}

/** A `pcb_trace`-shaped element as this folder's logic actually duck-types it (by `.type`,
 *  reading `route` or the nonexistent legacy `points` fallback, and either id field). Any
 *  real `CircuitElement` value is structurally assignable here (every field is optional). */
export interface PcbTraceLike {
  type?: string
  pcb_trace_id?: string
  id?: string
  route?: TraceRoutePoint[]
  points?: TraceRoutePoint[]
  route_thickness_mm?: number
  [field: string]: unknown
}

/** The flat Circuit JSON array as wireEdit.ts/RatsnestLayer.tsx consume it: real `CircuitJson`
 *  values satisfy this (see above), but so do the folder's own test fixtures, which don't
 *  fully conform to the real per-element schema. */
export type PcbElementArray = PcbTraceLike[]

/** `hitTestWire()`'s result. */
export interface WireHit {
  traceId: string
  segIndex: number
  t: number
  dist: number
}

/** Options accepted by `dragWireSegment()`. */
export interface DragWireOpts {
  anchorIndex?: number
  grid?: number
}

/** A stateful drag session returned by `beginWireDrag()`. */
export interface WireDragSession {
  traceId: string
  segIndex: number
  move: (json: PcbElementArray, point: PcbPoint) => PcbElementArray
  end: (json: PcbElementArray, point: PcbPoint) => PcbElementArray
}

export type NudgeDirection = 'up' | 'down' | 'left' | 'right'

// ---------------------------------------------------------------------------
// RatsnestLayer.tsx
// ---------------------------------------------------------------------------

/** A pad as `extractPadsByNet` reads it — see the file header for the net-id field mismatch. */
export interface PadLike {
  type?: string
  x?: number | string
  y?: number | string
  net_id?: string
  net?: string
  net_name?: string
  pcb_smtpad_id?: string
  pcb_plated_hole_id?: string
  id?: string
  [field: string]: unknown
}

export interface RatsnestPad extends PcbPoint {
  padId: string
}

export interface RatsnestMstEdge {
  from: RatsnestPad
  to: RatsnestPad
  lengthMm: number
}

export interface RatsnestEdge extends RatsnestMstEdge {
  netId: string
}

// ---------------------------------------------------------------------------
// FootprintLibrary.tsx / PlacementMode.tsx
// ---------------------------------------------------------------------------

/** Sizing params passed alongside a footprint family name (`onSelect`/`onPlace`). */
export interface FootprintParams {
  imperial?: string
  num_pins?: number
}

/** A confirmed footprint placement — `onPlace()`'s argument. */
export interface FootprintPlacement extends PcbPoint {
  rotation: number
  footprintFn: string
  params: FootprintParams
}

/** The canvas element PlacementMode.tsx attaches native listeners to — either an HTML or an
 *  SVG element both work (both carry `.style` and support `addEventListener`). */
export type PlacementCanvasElement = HTMLElement | SVGElement

// ---------------------------------------------------------------------------
// DRCOverlay.tsx
// ---------------------------------------------------------------------------

export type DrcSeverity = 'error' | 'warning'

/** One DRC violation — same schema as `kerf_electronics/drc.py` and `src/lib/pcbDRC.ts`
 *  (that module is untyped — a T-502..T-505 file, not this slice's — so this interface is
 *  mined from its literal `{ kind, message, ... }` construction sites plus this component's
 *  own header-comment schema). */
export interface DrcViolation {
  kind: string
  severity: DrcSeverity
  x: number
  y: number
  message: string
  trace_id?: string
  [field: string]: unknown
}
