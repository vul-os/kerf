// workers.ts — postMessage request/response discriminated unions for the three Kerf Web
// Workers (T-501).
//
// Sources:
//   - src/lib/occtWorker.js    — the protocol documented in its header comment, cross-checked
//                                against the actual `self.addEventListener('message', ...)`
//                                handler and every `postMessage(...)` call site. Two IN types
//                                (`evaluate`, `face_outline`) and three OUT types are actually
//                                implemented (`result`, `error`, `face_outline_result`). The
//                                header additionally documents a `progress` OUT message as
//                                "rare; reserved for v2" — no producer exists yet, kept here
//                                because the task explicitly asks to encode the *documented*
//                                protocol, with a comment flagging it as not-yet-emitted.
//   - src/lib/occtRunner.js    — the main-thread envelopes `runFeatures()`/`requestFaceOutline()`
//                                resolve with (these wrap the raw worker message with `stale`
//                                handling, per the `worker.addEventListener('message', ...)`
//                                handler in that file).
//   - src/lib/jscadWorker.js   — verified directly: `self.addEventListener('message', ...)` at
//                                the bottom of the file, `runJscadInWorker()`'s return shape.
//   - src/lib/jscadRunner.js   — the main-thread envelope (`{parts}|{error}|{stale:true}`, see
//                                its `worker.addEventListener('message', ...)` handler).
//   - src/lib/circuitWorker.js — verified directly: `self.addEventListener('message', ...)` at
//                                the bottom of the file, `compileCircuitInWorker()`'s return shape.
//   - src/lib/circuitRunner.js — the main-thread envelope, including `splitCircuitJson()`'s
//                                `{raw,schematic,pcb,threeD,errors}` bucketing.
//
// These are the wire shapes; T-506/T-507 own retrofitting occtWorker.js/jscadWorker.js/
// circuitWorker.js themselves to import and use these types.

import type { FeatureNode, Mesh, SketchFrame, FaceNameMap, JscadPart, SketchMap } from './geometry'
import type { CircuitElement, CircuitJson } from './circuit'

// ---------------------------------------------------------------------------
// occtWorker.js
// ---------------------------------------------------------------------------

export interface OcctEvaluateRequest {
  type: 'evaluate'
  runId: number
  tree: FeatureNode[]
  /** occtRunner.js always sends sketches pre-stringified. */
  sketches: Record<string, string>
}

export interface OcctFaceOutlineRequest {
  type: 'face_outline'
  runId: number
  tree: FeatureNode[]
  sketches: Record<string, string>
  faceId: number
}

export type OcctWorkerRequest = OcctEvaluateRequest | OcctFaceOutlineRequest

export interface OcctResultMessage {
  type: 'result'
  runId: number
  meshes: Mesh[]
}

export interface OcctErrorMessage {
  type: 'error'
  runId: number
  message: string
  stack?: string | null
  /** Partial mesh recovered from a failed op, when the OCCT bridge could triangulate it. */
  partial?: Mesh | null
}

/**
 * Documented in occtWorker.js's header comment as "rare; reserved for v2" — no producer exists
 * in the current implementation (verified: the evaluate loop never posts `type: 'progress'`).
 * Kept in the union because the task asks for the protocol to be encoded faithfully as
 * documented; T-506 should drop this if v2 never materializes.
 */
export interface OcctProgressMessage {
  type: 'progress'
  runId: number
  stage: string
}

export interface OcctFaceOutlineOkMessage {
  type: 'face_outline_result'
  runId: number
  ok: true
  frame: SketchFrame
  outline: Array<[number, number]>
  planar: boolean
  faceNames: FaceNameMap
}

export interface OcctFaceOutlineErrMessage {
  type: 'face_outline_result'
  runId: number
  ok: false
  reason: string
}

export type OcctFaceOutlineResultMessage = OcctFaceOutlineOkMessage | OcctFaceOutlineErrMessage

export type OcctWorkerResponse =
  | OcctResultMessage
  | OcctErrorMessage
  | OcctProgressMessage
  | OcctFaceOutlineResultMessage

/**
 * occtRunner.js's `runFeatures()` resolves with this envelope rather than the raw worker
 * message — see that file's `worker.addEventListener('message', ...)` handler.
 */
export type OcctRunFeaturesResult =
  | { meshes: Mesh[] }
  | { error: string; stack?: string | null; partial?: Mesh | null }
  | { stale: true }

/** occtRunner.js's `requestFaceOutline()` resolves with this envelope. */
export type OcctFaceOutlineResult =
  | { ok: true; frame: SketchFrame; outline: Array<[number, number]>; planar: boolean; faceNames?: FaceNameMap }
  | { ok: false; reason: string }

// ---------------------------------------------------------------------------
// jscadWorker.js
// ---------------------------------------------------------------------------

export interface JscadRunRequest {
  type: 'run'
  runId: number
  code: string
  /** `<sketch import binding name> -> Geom2 profile`, injected into scope as extra Function args. */
  sketchProfiles?: Record<string, unknown>
  /** Equations scope, injected into user scope as `params`. */
  equationsValues?: Record<string, number>
}

export type JscadWorkerRequest = JscadRunRequest

export interface JscadResultMessage {
  type: 'result'
  runId: number
  parts: JscadPart[]
}

export interface JscadErrorMessage {
  type: 'error'
  runId: number
  error: string
}

export type JscadWorkerResponse = JscadResultMessage | JscadErrorMessage

/** jscadRunner.js's main-thread envelope (mirrors occtRunner.js's stale/error handling). */
export type JscadRunResult =
  | { parts: JscadPart[] }
  | { error: string }
  | { stale: true }

// ---------------------------------------------------------------------------
// circuitWorker.js
// ---------------------------------------------------------------------------

export interface CircuitCompileRequest {
  type: 'compile'
  runId: number
  source: string
}

export type CircuitWorkerRequest = CircuitCompileRequest

export interface CircuitResultMessage {
  type: 'result'
  runId: number
  circuitJson: CircuitJson
}

export interface CircuitErrorMessage {
  type: 'error'
  runId: number
  /** Note: circuitWorker.js posts the error under `message`, not `error` (unlike jscadWorker.js). */
  message: string
}

export type CircuitWorkerResponse = CircuitResultMessage | CircuitErrorMessage

/**
 * circuitRunner.js's main-thread envelope. `splitCircuitJson()` buckets the flat array by
 * element-type prefix (`schematic_*`/`source_*` -> schematic, `pcb_*` -> pcb, `cad_*` -> threeD)
 * and separately collects any element carrying an `error_type` field into `errors`.
 */
export type CircuitCompileResult =
  | { raw: CircuitJson; schematic: CircuitElement[]; pcb: CircuitElement[]; threeD: CircuitElement[]; errors: CircuitElement[] }
  | { error: string }
  | { stale: true }

// Re-exported for convenience — slice agents typing occtRunner.js's sketch-map parameter can
// import it from here alongside the request/response types instead of reaching into geometry.ts.
export type { SketchMap }
