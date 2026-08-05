// circuit.ts — Circuit JSON domain types (T-501).
//
// Circuit JSON is tscircuit's flat-array intermediary format (see src/lib/circuitWorker.js's
// header comment and src/lib/circuitJsonPatch.js). The installed `circuit-json` npm package
// (v0.0.423) ships a complete, actively-maintained zod-inferred TypeScript surface for every
// element kind (`pcb_component`, `pcb_smtpad`, `source_simple_resistor`, `schematic_*`, ...) —
// verified directly against node_modules/circuit-json/dist/index.d.mts:
//   `AnyCircuitElement = z.infer<typeof any_circuit_element>` and `CircuitJson =
//   AnyCircuitElement[]`. (`AnySoupElement`/`AnySoupElementInput` are older deprecated aliases —
//   do not use them.) This file re-exports rather than redeclaring, since hand-rolling would
//   drift from the package's schema.
//
// --- The alias seam (read before repointing) ---
// Goal G2 (see tasks.md T-504/T-531) will eventually replace Circuit JSON with a Kerf-native
// ECAD IR. `CircuitElement`/`CircuitJson` below are that seam: every consumer across the
// migrated slices should import `CircuitElement`/`CircuitJson` from here, never
// `AnyCircuitElement`/`CircuitJson` from `circuit-json` directly. When G2 lands its IR, this file
// is the only place that needs to change.
//
// --- A real impedance mismatch worth flagging for T-504 (circuitJsonPatch.js's owner) ---
// `circuitJsonPatch.js`'s `addFootprint()` constructs a `pcb_component` element as
// `{ type, pcb_component_id, center: {x,y}, rotation, name }`. Introspecting the actual zod
// schema (`circuit-json`'s `pcb_component`) shows real `PcbComponent` requires
// `source_component_id`, `layer`, `width`, `height` (none optional; `obstructs_within_bounds` IS
// optional, defaulted) — and has **no `name` field at all**. So circuitJsonPatch.js's literal
// does not structurally satisfy `PcbComponent` today. That's a pre-existing gap in the JS, not
// introduced by these types; T-501 does not fix it (out of slice, `circuitJsonPatch.js` is a
// different task's file) but flags it here so whoever migrates that file to `.ts` isn't
// surprised when `addFootprint()`'s return value doesn't type-check against `PcbComponent`
// as-is. The same function's "extra elements" pass (silkscreen paths/text) duck-types on
// `el.route` / `el.anchor_position` / bare `el.x,y` rather than on `.type`, so a strict
// discriminated-union narrow over `CircuitElement` won't cleanly cover that branch either —
// another thing for that migration to work through, not this one.

import type { AnyCircuitElement } from 'circuit-json'

/** One element of a Circuit JSON array. Repoint this alias, not its usages, when G2's IR lands. */
export type CircuitElement = AnyCircuitElement

/** The flat array Circuit JSON format itself — tscircuit's `circuit.getCircuitJson()` return shape. */
export type CircuitJson = CircuitElement[]
