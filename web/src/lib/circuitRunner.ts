// Run a `.circuit.tsx` source through tscircuit and return the resulting
// Circuit JSON, split into the three pragmatic buckets the editor cares about
// (schematic, pcb, and 3D).
//
// Mirrors jscadRunner.js:
//   - Lazy-spun module worker; cancellation via runId.
//   - Falls back to a no-op error result if the worker can't spin up. We
//     deliberately don't run the user's TSX on the main thread because:
//       * sucrase + tscircuit + manifold + react-reconciler push ~6 MB of
//         dependencies. Loading them on the main thread freezes the editor.
//       * Sandbox-eval'ing user TSX inside the renderer process is a
//         security smell. The worker is sandboxed enough.
//
// The split is purely a frontend convenience — it's a flat .filter() over
// the AnyCircuitElement[] returned by tscircuit's getCircuitJson(). Anything
// not in the schematic/pcb/3d buckets stays available via .raw for tools that
// need source_* / errors / simulation_*.
//
// Typing note: `src/types/workers.ts` (T-501) already models this file's
// wire protocol — `CircuitWorkerRequest`/`CircuitWorkerResponse` for the
// postMessage boundary with circuitWorker.js, and `CircuitCompileResult` for
// this file's own main-thread envelope. `splitCircuitJson()`'s return isn't
// quite `CircuitCompileResult`'s success shape, though: it accepts (and its
// own tests exercise) non-array/garbage input defensively, preserving
// whatever `raw` was given verbatim (including `null`) rather than coercing
// it to a `CircuitJson`. So it gets its own slightly looser
// `SplitCircuitJsonResult` return type; `runCircuit()` itself only ever
// calls `splitCircuitJson()` with a real array (guarded above by
// `Array.isArray(ev.data.circuitJson) ? ... : []`), so its call site
// documents why that narrows to `CircuitCompileResult`.

import type {
  CircuitElement,
  CircuitJson,
  CircuitCompileRequest,
  CircuitCompileResult,
  CircuitWorkerResponse,
} from '@/types'

interface PendingEntry {
  resolve: (value: CircuitCompileResult) => void
  reject: (err: Error) => void
}

let worker: Worker | null = null
let workerBroken = false
let nextRunId = 1
let latestRunId = 0
const pending = new Map<number, PendingEntry>()

function ensureWorker(): Worker | null {
  if (workerBroken) return null
  if (worker) return worker
  if (typeof Worker === 'undefined') {
    workerBroken = true
    return null
  }
  try {
    worker = new Worker(new URL('./circuitWorker.js', import.meta.url), { type: 'module' })
    worker.addEventListener('message', (ev: MessageEvent<CircuitWorkerResponse>) => {
      const msg = (ev.data || {}) as Partial<CircuitWorkerResponse>
      const { type, runId } = msg
      if (runId == null) return
      const entry = pending.get(runId)
      if (!entry) return
      pending.delete(runId)
      if (runId !== latestRunId) {
        entry.resolve({ stale: true })
        return
      }
      if (type === 'error') {
        entry.resolve({ error: msg.message || 'unknown circuit worker error' })
        return
      }
      if (type === 'result') {
        const json: CircuitJson = Array.isArray(msg.circuitJson) ? msg.circuitJson : []
        // splitCircuitJson()'s return is only its looser SplitCircuitJsonResult
        // in general (see header comment) — but `json` here is always a real
        // array, which is exactly the case where its shape matches
        // CircuitCompileResult's success variant.
        entry.resolve(splitCircuitJson(json) as CircuitCompileResult)
        return
      }
      entry.resolve({ error: 'unknown circuit worker message' })
    })
    worker.addEventListener('error', (ev: ErrorEvent) => {
      try { worker?.terminate() } catch { /* ignore */ }
      worker = null
      workerBroken = true
      for (const [, entry] of pending) entry.reject(new Error(ev.message || 'circuit worker error'))
      pending.clear()
    })
    return worker
  } catch {
    workerBroken = true
    worker = null
    return null
  }
}

/** Looser cousin of `CircuitCompileResult`'s success shape — see header comment. */
export interface SplitCircuitJsonResult {
  raw: unknown
  schematic: CircuitElement[]
  pcb: CircuitElement[]
  threeD: CircuitElement[]
  errors: CircuitElement[]
}

// Bucket the flat circuit_json into the three views the editor tabs render.
//
// Buckets (by `type` prefix):
//   - schematic: schematic_*, source_component (for ref designators / values)
//   - pcb:       pcb_*
//   - threeD:    cad_component, cad_*
// `raw` is the whole array so renderers that already accept circuit-to-svg's
// input shape can pass it straight through (we don't materialise per-bucket
// arrays for them — splitting twice is wasteful).
export function splitCircuitJson(json: unknown): SplitCircuitJsonResult {
  const schematic: CircuitElement[] = []
  const pcb: CircuitElement[] = []
  const threeD: CircuitElement[] = []
  const errors: CircuitElement[] = []
  if (Array.isArray(json)) {
    for (const el of json as unknown[]) {
      if (!el || typeof el !== 'object' || typeof (el as { type?: unknown }).type !== 'string') continue
      const e = el as CircuitElement
      const t = (el as { type: string }).type
      if (t.startsWith('schematic_')) schematic.push(e)
      else if (t === 'source_component' || t === 'source_port' || t === 'source_trace' || t === 'source_net') schematic.push(e)
      else if (t.startsWith('pcb_')) pcb.push(e)
      else if (t === 'cad_component' || t.startsWith('cad_')) threeD.push(e)
      // Errors are buried in *_error records or a top-level error array; we
      // surface anything with an explicit `error_type` field.
      if (typeof (el as { error_type?: unknown }).error_type === 'string') errors.push(e)
    }
  }
  return {
    raw: json,
    schematic,
    pcb,
    threeD,
    errors,
  }
}

// Public API ------------------------------------------------------------------

// Compile a .circuit.tsx source. Resolves to:
//   { raw, schematic, pcb, threeD, errors }    on success
//   { stale: true }                              if a newer call superseded it
//   { error: string }                            on compile/eval failure
export async function runCircuit(source: string): Promise<CircuitCompileResult> {
  const w = ensureWorker()
  if (!w) {
    // No fallback — the dependency surface is too big to import on the main
    // thread. Surface an explicit error and let the editor's error pane render
    // it. This path only triggers in non-Worker environments (Node tests).
    return { error: 'Circuit compiler requires a Web Worker; not available in this environment.' }
  }
  const runId = ++nextRunId
  latestRunId = runId
  return new Promise((resolve, reject) => {
    pending.set(runId, { resolve, reject })
    try {
      const req: CircuitCompileRequest = { type: 'compile', runId, source: source || '' }
      w.postMessage(req)
    } catch (err) {
      pending.delete(runId)
      resolve({ error: (err instanceof Error && err.message) || 'failed to post message' })
    }
  })
}

// Invalidate every in-flight run. Called when the user closes the editor or
// switches off a .circuit.tsx file mid-compile.
export function cancelCircuit(): void {
  latestRunId = ++nextRunId
  for (const [, entry] of pending) entry.resolve({ stale: true })
  pending.clear()
}

// Default seed for a brand-new circuit file. Three-resistor voltage divider —
// minimal but enough to exercise the full pipeline (schematic + PCB + 3D).
export const DEFAULT_CIRCUIT: string = `import { Circuit } from "tscircuit"

// Kerf: default export is a JSX element OR a Circuit instance. The editor
// renders the schematic, PCB, and 3D views in their respective tabs.
export default (
  <board width="20mm" height="20mm">
    <resistor name="R1" resistance="10k" footprint="0402" pcbX={-5} pcbY={0} schX={-3} />
    <resistor name="R2" resistance="10k" footprint="0402" pcbX={0}  pcbY={0} schX={0}  />
    <resistor name="R3" resistance="10k" footprint="0402" pcbX={5}  pcbY={0} schX={3}  />
    <trace from=".R1 .pin2" to=".R2 .pin1" />
    <trace from=".R2 .pin2" to=".R3 .pin1" />
  </board>
)
`
