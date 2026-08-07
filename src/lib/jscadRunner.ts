// Run a user's JSCAD source and return parts.
//
// Convention (see backend/llm_docs/jscad.md / seed file): the user's file's default export is
//   function (modeling) { return [{id, geom}, ...] }
// This avoids depending on importmap / module resolution at runtime — we just
// hand them the @jscad/modeling namespace.
//
// We accept a few legacy shapes too:
//   - `export default function ({primitives, ...}) {...}`
//   - The traditional JSCAD `export const main = (params) => ...` returning a
//     single Geom3 or array of Geom3 (we'll wrap with auto-generated ids).
//
// We evaluate by stripping the `export default`/named-export keywords and
// wrapping the body in `new Function('modeling', body)`.
//
// Phase 1 perf change: evaluation runs in a Web Worker so boolean ops don't
// freeze the editor. The worker is created lazily on first call. If the
// worker can't be spun up (e.g. running in a test/Node env, or a runtime
// failure), we fall back to running on the main thread so a worker bug
// can never break the editor entirely.
//
// Cancellation: callers may queue evaluations faster than the worker can
// finish them (typing in Monaco). Each call gets a monotonic runId; only
// the latest run's result is delivered to its caller, older runs resolve
// with `{ stale: true }` so callers can discard them. `cancelJscad()`
// invalidates everything in flight (used when navigating away from a file).

import * as modeling from '@jscad/modeling'
import { parseSketch } from './sketchSolver.js'
import { sketchToGeom2 } from './sketchGeom2.js'
import type { Geom3, JscadPart } from '../types/geometry.js'
import type { JscadWorkerResponse, JscadRunResult } from '../types/workers.js'
import type { EquationsScope } from '../store/workspace.js'

// Equations injection — see store/workspace.js loadProject for the resolver
// that walks the project tree, parses every `.equations` file, evaluates the
// rows, and returns the merged scope. The runner pulls the scope on every
// evaluation so a user editing equations triggers a re-run via the standard
// debounce pipeline (the workspace store touches the JSCAD source after the
// equations file mutates).
// Only `values` is read (see resolveEquationsScope below), so a resolver need not produce a whole
// EquationsScope — the errors/duplicates arrays are the store's concern, not this consumer's.
type ResolvedEquations = Pick<EquationsScope, 'values'>
type EquationsResolver = () => Promise<ResolvedEquations> | ResolvedEquations | null | undefined
let equationsResolver: EquationsResolver | null = null
export function setEquationsResolver(fn: EquationsResolver | null): void {
  equationsResolver = fn || null
}

async function resolveEquationsScope(): Promise<Record<string, number>> {
  if (!equationsResolver) return {}
  try {
    const res = await equationsResolver()
    return res?.values || {}
  } catch {
    return {}
  }
}

// ---- Main-thread fallback (also used inline if the worker never spins up) --

// Pull out `import X from '/foo.sketch'` lines so the main thread can resolve
// each one to a Geom2 (asynchronously, before the worker call). Returns the
// stripped source plus an array of {binding, path}. We deliberately handle
// only the default-import form — `import { ... } from '/foo.sketch'` is not a
// thing in our runtime since sketches export a single profile.
//   Matches: import foo from "/path.sketch"
//            import foo from '/path.sketch'
//            import foo from "./path.sketch"  (resolved later)
export const SKETCH_IMPORT_RE = /^[ \t]*import\s+([A-Za-z_$][\w$]*)\s+from\s+['"]([^'"\n]+\.sketch)['"];?[ \t]*$/gm

interface SketchImport {
  binding: string
  path: string
}

function extractSketchImports(code: string): { stripped: string; imports: SketchImport[] } {
  const imports: SketchImport[] = []
  const stripped = code.replace(SKETCH_IMPORT_RE, (_m, binding, path) => {
    imports.push({ binding, path })
    return `// resolved sketch import: ${binding} <- ${path}`
  })
  return { stripped, imports }
}

function transformSource(code: string): string {
  // Remove top-level imports — the user's code shouldn't need them, but seeded
  // examples sometimes include `import * as modeling from '@jscad/modeling'`.
  // Sketch imports are removed by the caller before we land here.
  let src = code.replace(/^[ \t]*import[^\n;]*['"][^'"\n]+['"][^\n;]*;?[ \t]*$/gm, '')

  // Capture `export default <expr>` and rewrite to `return <expr>`.
  // Also handle `export default function ...` and `export default async function ...`.
  if (/export\s+default\s+/.test(src)) {
    src = src.replace(/export\s+default\s+/, 'return ')
  } else if (/export\s+(?:const|let|var|function)\s+main\b/.test(src)) {
    // Legacy main entry — strip the `export` keyword and `return main` at end.
    src = src.replace(/export\s+(const|let|var|function)\s+main\b/, '$1 main')
    src += '\n;return main;'
  } else {
    // Last resort: assume the file ends with a function expression.
    src += '\n;return (typeof main !== "undefined" ? main : null);'
  }
  return src
}

// Hook used by the editor: lets the caller register a project-scoped resolver
// for `.sketch` paths → Geom2. We keep this as a global mutable so the runner
// stays decoupled from the workspace store; jscadRunner.js doesn't import
// from store/workspace.js (which would create a cycle through the store's
// own runJscad call).
type SketchResolver = (path: string) => Promise<{ content: string } | null>
let sketchResolver: SketchResolver | null = null
export function setSketchResolver(fn: SketchResolver | null): void {
  sketchResolver = fn || null
}

// Optional lister: returns a Promise<string[]> of all available .sketch paths
// in the current project. Used to produce a helpful error message when a
// referenced sketch can't be found. If not registered, the error still fires
// but without the suggestions list.
type SketchLister = () => Promise<string[]> | string[]
let sketchLister: SketchLister | null = null
export function setSketchLister(fn: SketchLister | null): void {
  sketchLister = fn || null
}

async function resolveSketchImports(imports: SketchImport[]): Promise<Record<string, unknown>> {
  const out: Record<string, unknown> = {}
  if (!imports || imports.length === 0) return out
  for (const { binding, path } of imports) {
    const file = sketchResolver ? await sketchResolver(path) : null
    if (!file) {
      // Collect available sketches for a diagnostic message.
      let available: string[] = []
      try {
        available = sketchLister ? await sketchLister() : []
      } catch { /* lister failure is non-fatal — still throw */ }
      const listStr = available.length > 0
        ? available.join(', ')
        : '(no .sketch files in project)'
      throw new Error(
        `sketch not found: ${path} — available sketches: ${listStr}`,
      )
    }
    // File found — parse and convert. Parse errors propagate naturally;
    // callers (runJscadOnMainThread / runJscad) catch them and surface via partsError.
    const sketch = parseSketch(file.content || '')
    const geom = sketchToGeom2(sketch)
    out[binding] = geom
  }
  return out
}

// JSCAD's colors.colorize() stamps `geom.color` as [r,g,b] (or [r,g,b,a])
// floats in 0..1. geom3ToBufferGeometry drops it, so unless we lift it onto the
// part here it never reaches the renderer — which is why colorize() used to have
// no visible effect and the viewport always fell back to the index palette.
function geomColorToInt(geom: (Geom3 & { color?: number[] }) | null | undefined): number | undefined {
  const c = geom && geom.color
  if (!Array.isArray(c) || c.length < 3) return undefined
  const ch = (v: number) => Math.max(0, Math.min(255, Math.round((Number(v) || 0) * 255)))
  return (ch(c[0]) << 16) | (ch(c[1]) << 8) | ch(c[2])
}

function toPart(id: string, geom: Geom3, explicitColor?: number): JscadPart {
  const color = explicitColor != null ? explicitColor : geomColorToInt(geom)
  return color != null ? { id, geom, color } : { id, geom }
}

// The user's JSCAD code can return almost any shape — a bare Geom3, a `{id, geom, color}` part, or
// arrays of either — so this boundary is intentionally loose (`any`) rather than modeled exactly;
// mirrors jscadWorker.ts's own `normalizeParts`.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeParts(out: any): JscadPart[] {
  if (out == null) return []
  if (Array.isArray(out)) {
    if (out.length === 0) return []
    if (out[0] && typeof out[0] === 'object' && 'geom' in out[0]) {
      return out.map((p, i) => toPart(p.id ?? `part-${i}`, p.geom, p.color))
    }
    return out.map((g, i) => toPart(`part-${i}`, g))
  }
  if (typeof out === 'object' && 'geom' in out) {
    return [toPart(out.id ?? 'part-0', out.geom, out.color)]
  }
  return [toPart('part-0', out)]
}

const SCOPE_KEYS = [
  'primitives', 'transforms', 'booleans', 'extrusions', 'expansions',
  'measurements', 'colors', 'utils', 'maths', 'curves', 'geometries',
  'hulls', 'text',
] as const

async function runJscadOnMainThread(
  code: string,
  configParams?: Record<string, number> | null,
): Promise<JscadRunResult> {
  if (!code || !code.trim()) return { parts: [] }
  try {
    const { stripped, imports } = extractSketchImports(code)
    const sketchProfiles = await resolveSketchImports(imports)
    const equationsValues = await resolveEquationsScope()
    // Configurations / variants — the active config's params layer over the
    // equations scope (config wins on collision). Passing configParams=null
    // (the common case for a file without configurations) is a no-op.
    const mergedParams = (configParams && typeof configParams === 'object')
      ? { ...equationsValues, ...configParams }
      : equationsValues
    const body = transformSource(stripped)
    const sketchKeys = Object.keys(sketchProfiles)
    const args = ['modeling', 'params', ...SCOPE_KEYS, ...sketchKeys]
    const values = [
      modeling,
      mergedParams,
      ...SCOPE_KEYS.map((k) => modeling[k]),
      ...sketchKeys.map((k) => sketchProfiles[k]),
    ]
    const factory = new Function(...args, body)
    const exported = factory(...values)
    // Build a scope the user's main-export function can destructure.
    // Matches the worker's contract: { ...modeling, params } so a single
    // `function ({ primitives, transforms, params })` argument list works.
    const userScope = { ...modeling, params: mergedParams }
    let result = typeof exported === 'function' ? exported(userScope) : exported
    if (result && typeof result.then === 'function') result = await result
    const parts = normalizeParts(result)
    return { parts }
  } catch (err) {
    return { error: err && (err as Error).message ? (err as Error).message : String(err) }
  }
}

// ---- Worker plumbing --------------------------------------------------------

interface PendingEntry {
  resolve: (value: JscadRunResult) => void
  reject: (reason?: unknown) => void
}

let worker: Worker | null = null
let workerBroken = false
let nextRunId = 1
const pending = new Map<number, PendingEntry>() // runId → { resolve, reject }
let latestRunId = 0

function ensureWorker(): Worker | null {
  if (workerBroken) return null
  if (worker) return worker
  if (typeof Worker === 'undefined') {
    workerBroken = true
    return null
  }
  try {
    worker = new Worker(new URL('./jscadWorker.js', import.meta.url), { type: 'module' })
    worker.addEventListener('message', (ev: MessageEvent<JscadWorkerResponse>) => {
      const data = ev.data
      const runId = data?.runId
      const entry = runId != null ? pending.get(runId) : undefined
      if (!entry) return
      pending.delete(runId)
      if (runId !== latestRunId) {
        // Stale — discard. Caller awaits but receives the canonical
        // empty-stale shape so it can no-op.
        entry.resolve({ stale: true })
        return
      }
      if (data.type === 'error') {
        entry.resolve({ error: data.error })
      } else if (data.type === 'result') {
        entry.resolve({ parts: data.parts || [] })
      } else {
        entry.resolve({ error: 'unknown worker message' })
      }
    })
    worker.addEventListener('error', (ev) => {
      // Fatal worker error: tear it down and mark broken so subsequent calls
      // run inline. Reject any pending callers with an error so they fall back.
      try { worker?.terminate() } catch { /* ignore */ }
      worker = null
      workerBroken = true
      for (const [, entry] of pending) entry.reject(new Error(ev.message || 'jscad worker error'))
      pending.clear()
    })
    return worker
  } catch {
    workerBroken = true
    worker = null
    return null
  }
}

// Public API ------------------------------------------------------------------

// runJscad(code, configParams?) — the optional `configParams` is the active
// configuration's `params` map for the file (per-file parameter overrides;
// see src/lib/part.js getActiveConfig). Merged OVER the equations scope so
// configs always win on key collision. The workspace store passes it; the
// public surface stays backwards compatible (one-arg callers behave as
// before).
export async function runJscad(
  code: string,
  configParams?: Record<string, number> | null,
): Promise<JscadRunResult> {
  const w = ensureWorker()
  // Pre-resolve any `.sketch` imports on the main thread so the worker only
  // ever evaluates pure JSCAD code with sketch profiles already converted to
  // Geom2 values. The transferred Geom2 is structured-cloneable (plain
  // arrays + numbers), so this round-trips cleanly. If there are no sketch
  // imports the work is essentially zero.
  const { stripped, imports } = extractSketchImports(code || '')
  let sketchProfiles: Record<string, unknown>
  try {
    sketchProfiles = imports.length > 0 ? await resolveSketchImports(imports) : {}
  } catch (err) {
    return { error: err && (err as Error).message ? (err as Error).message : String(err) }
  }
  const equationsValues = await resolveEquationsScope()
  const mergedParams = (configParams && typeof configParams === 'object')
    ? { ...equationsValues, ...configParams }
    : equationsValues
  if (!w) {
    // Inline fallback: still respect runId so a later call wins on the main
    // thread too (used by tests and worker-failure paths).
    const runId = ++nextRunId
    latestRunId = runId
    const res = await runJscadOnMainThread(code, configParams)
    if (runId !== latestRunId) return { stale: true }
    return res
  }
  const runId = ++nextRunId
  latestRunId = runId
  try {
    const promise = new Promise<JscadRunResult>((resolve, reject) => {
      pending.set(runId, { resolve, reject })
      // The worker contract uses `equationsValues` as the param map; we send
      // the merged scope so the worker doesn't need to know about configs.
      w.postMessage({ type: 'run', runId, code: stripped, sketchProfiles, equationsValues: mergedParams })
    })
    const res = await promise
    return res
  } catch {
    // Worker died mid-flight → fall back to main thread.
    return runJscadOnMainThread(code, configParams)
  }
}

// Invalidate all in-flight runs so their results are dropped. Called when the
// user navigates away from a file or closes the editor.
export function cancelJscad(): void {
  latestRunId = ++nextRunId
  for (const [, entry] of pending) entry.resolve({ stale: true })
  pending.clear()
}

// Default seed for new files. Backend mirrors this when creating main.jscad.
export const DEFAULT_JSCAD = `// Kerf: default export receives the @jscad/modeling module and returns parts.
export default function ({ primitives, transforms, booleans }) {
  const base = primitives.cuboid({ size: [40, 40, 10] })
  const peg  = transforms.translate([0, 0, 10], primitives.cylinder({ radius: 6, height: 20 }))
  return [
    { id: 'base', geom: base },
    { id: 'peg',  geom: peg  },
  ]
}
`
