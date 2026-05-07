// occtRunner.js — main-thread wrapper around the OCCT Web Worker.
//
// Public API:
//   - runFeatures(tree, sketches)  → Promise<{ meshes, error?, stale?, partial? }>
//   - cancelFeatures()             — drop in-flight runs (their promises resolve
//                                    with `{ stale: true }`)
//   - prewarmOcct()                — kick off the worker boot without enqueueing
//                                    a real evaluation, so the first user-driven
//                                    run pays only the eval cost.
//   - requestFaceOutline(tree, sketches, faceId) — fetch the planar outline of a
//                                    face on the post-evaluation shape; used by
//                                    sketch-on-face and push/pull preview.
//
// Mirrors the JSCAD runner's contract:
//   * Lazy worker boot — first call constructs the Worker; subsequent calls
//     reuse it. We DO NOT spin up the worker until prewarmOcct() or the first
//     runFeatures() invocation, so opening a non-feature file pays no OCCT
//     cost.
//   * Run-id sequencing — each call gets a monotonic id; only the latest
//     resolves with results. Stale runs resolve with { stale: true } so
//     callers can no-op.
//   * Worker errors are surfaced as { error: string } (mirrors jscadRunner).
//     If a worker dies hard, subsequent calls fall back to
//     { error: 'worker-broken' } — there's no main-thread evaluator for OCCT
//     (we DON'T want to load the wasm onto the main thread).

import { substituteFeatureTree, substituteSketch } from './equations.js'

// Equations injection hook — see store/workspace.js loadProject for the
// resolver that walks the project tree, parses every `.equations` file, and
// returns the merged scope. Mirrors setSketchResolver in jscadRunner.js.
let equationsResolver = null
export function setEquationsResolver(fn) {
  // fn: () => Promise<{ values: { [name]: number }, errors, duplicates }> | null
  equationsResolver = fn || null
}

// Active-configuration resolver hook. The workspace store registers a
// closure that returns the current open feature file's active-config
// `params` object (or null when the file has no configurations). The
// resolver is consulted on every runFeatures call so a config switch
// triggers a fresh substitution + re-evaluation. Decoupled from
// FeatureView (which we don't touch) so configurations can layer over
// the existing runner without changing the public API.
let activeConfigResolver = null
export function setActiveConfigResolver(fn) {
  // fn: () => { [name]: number } | null
  activeConfigResolver = fn || null
}

// Apply the equations scope to a tree + sketches pair. The substitution is
// pure JSON-walking so it's safe for arbitrary node shapes — string fields
// containing `${name}` placeholders get expanded; everything else passes
// through. Sketches get the same treatment for dimensional constraint values
// (distance/angle/radius/diameter).
//
// `configParams` is the active configuration's per-file param overrides
// (see src/lib/part.js getActiveConfig). Merged OVER the equations scope
// so configs always win on key collision. Passing null/empty is a no-op.
async function applyEquations(tree, sketches, configParams) {
  let scope = {}
  if (equationsResolver) {
    try {
      const res = await equationsResolver()
      scope = res?.values || {}
    } catch {
      scope = {}
    }
  }
  if (configParams && typeof configParams === 'object') {
    scope = { ...scope, ...configParams }
  }
  if (!scope || Object.keys(scope).length === 0) return { tree, sketches }
  const subTree = substituteFeatureTree(tree || [], scope)
  const subSketches = {}
  for (const [path, raw] of Object.entries(sketches || {})) {
    if (typeof raw !== 'string' || raw === '') {
      subSketches[path] = raw
      continue
    }
    try {
      const obj = JSON.parse(raw)
      const sub = substituteSketch(obj, scope)
      subSketches[path] = JSON.stringify(sub)
    } catch {
      subSketches[path] = raw
    }
  }
  return { tree: subTree, sketches: subSketches }
}

let worker = null
let workerBroken = false
let nextRunId = 1
const pending = new Map()
let latestRunId = 0

function ensureWorker() {
  if (workerBroken) return null
  if (worker) return worker
  if (typeof Worker === 'undefined') {
    workerBroken = true
    return null
  }
  try {
    // Vite-friendly worker URL. The URL form lets Vite pick up dependencies
    // (opencascade.js + its wasm) and emit them as separate chunks.
    worker = new Worker(new URL('./occtWorker.js', import.meta.url), { type: 'module' })
    worker.addEventListener('message', (ev) => {
      const { type, runId } = ev.data || {}
      const entry = pending.get(runId)
      if (!entry) return
      pending.delete(runId)
      // Face-outline requests are *not* part of the latest-run sequencing —
      // they're explicit RPCs the UI fires for a specific face id, and we
      // always want the answer.
      if (type === 'face_outline_result') {
        entry.resolve(ev.data)
        return
      }
      if (entry.kind !== 'evaluate' && entry.kind !== 'prewarm') {
        // Defensive: unknown kind, just resolve with the raw payload.
        entry.resolve(ev.data)
        return
      }
      // Run-id sequencing: only the latest evaluate gets fresh meshes.
      // Prewarm runs ride alongside without claiming the latest slot.
      if (entry.kind === 'evaluate' && runId !== latestRunId) {
        entry.resolve({ stale: true })
        return
      }
      if (type === 'error') {
        entry.resolve({ error: ev.data.message || 'occt error', stack: ev.data.stack || null, partial: ev.data.partial || null })
      } else if (type === 'result') {
        entry.resolve({ meshes: ev.data.meshes || [] })
      } else {
        entry.resolve({ error: 'unknown worker message' })
      }
    })
    worker.addEventListener('error', (ev) => {
      try { worker.terminate() } catch { /* */ }
      worker = null
      workerBroken = true
      for (const [, entry] of pending) {
        entry.resolve({ error: ev.message || 'occt worker crashed' })
      }
      pending.clear()
    })
    return worker
  } catch {
    workerBroken = true
    worker = null
    return null
  }
}

// Send the worker an empty tree so the Wasm module gets eagerly compiled.
// Useful right after the user opens a Feature file — by the time they edit a
// param the OCCT instance is warm.
export function prewarmOcct() {
  const w = ensureWorker()
  if (!w) return Promise.resolve(null)
  const runId = ++nextRunId
  // Warm-up runs are NOT made the latest run — they're orthogonal. We don't
  // bump latestRunId so they can't accidentally win against a real evaluation.
  return new Promise((resolve) => {
    pending.set(runId, { resolve, kind: 'prewarm' })
    w.postMessage({ type: 'evaluate', runId, tree: [], sketches: {} })
  })
}

// Run a feature tree. Returns the mesh list or an error envelope.
//
// `configParams` is optional — the active configuration's per-file param
// overrides. Merged OVER the equations scope before `${name}` substitution.
// Callers without configurations pass null/undefined; we then consult the
// registered activeConfigResolver (set by the workspace store on project
// load) so existing call sites (FeatureView) pick up configs without
// changing their signature.
export async function runFeatures(tree, sketches, configParams) {
  const w = ensureWorker()
  if (!w) return { error: 'occt worker unavailable in this environment' }
  if (configParams == null && activeConfigResolver) {
    try { configParams = activeConfigResolver() || null } catch { configParams = null }
  }
  const { tree: subTree, sketches: subSketches } = await applyEquations(tree || [], sketches || {}, configParams)
  const runId = ++nextRunId
  latestRunId = runId
  const promise = new Promise((resolve) => {
    pending.set(runId, { resolve, kind: 'evaluate' })
  })
  try {
    w.postMessage({ type: 'evaluate', runId, tree: subTree, sketches: subSketches })
  } catch (err) {
    pending.delete(runId)
    return { error: `failed to dispatch occt run: ${err?.message || String(err)}` }
  }
  return promise
}

// Request the planar outline of a face on the post-evaluation shape. Used by
// the sketch-on-face placement flow and the push/pull face inspector.
//
// Returns:
//   { ok: true, frame: { origin, normal, uDir, vDir }, outline: [[u,v]...], planar }
//   { ok: false, reason }
export async function requestFaceOutline(tree, sketches, faceId, configParams) {
  const w = ensureWorker()
  if (!w) return { ok: false, reason: 'occt worker unavailable' }
  if (configParams == null && activeConfigResolver) {
    try { configParams = activeConfigResolver() || null } catch { configParams = null }
  }
  const { tree: subTree, sketches: subSketches } = await applyEquations(tree || [], sketches || {}, configParams)
  const runId = ++nextRunId
  const promise = new Promise((resolve) => {
    pending.set(runId, { resolve, kind: 'face_outline' })
  })
  try {
    w.postMessage({ type: 'face_outline', runId, tree: subTree, sketches: subSketches, faceId })
  } catch (err) {
    pending.delete(runId)
    return { ok: false, reason: `failed to dispatch face_outline: ${err?.message || String(err)}` }
  }
  return promise
}

// Drop in-flight runs. Their resolvers receive { stale: true } so callers
// can no-op cleanly. Does not destroy the worker — the next runFeatures()
// call will reuse it.
export function cancelFeatures() {
  latestRunId = ++nextRunId
  for (const [, entry] of pending) entry.resolve({ stale: true })
  pending.clear()
}

// Tear down the worker entirely. Called by the workspace store on project
// unload so the OCCT heap from the previous project isn't carried into the
// next one (~70 MB depending on what was modeled).
export function destroyOcct() {
  cancelFeatures()
  if (worker) {
    try { worker.terminate() } catch { /* */ }
  }
  worker = null
  workerBroken = false
}

// Default seed for a new .feature file. The LLM tool's create_feature uses
// the same JSON shape so editor + tool produce identical starts.
export const DEFAULT_FEATURE = JSON.stringify({
  version: 1,
  name: 'New feature',
  features: [],
}, null, 2)

// Parse a .feature file's content into the canonical tree shape. Tolerant
// of empty / malformed input — returns an empty tree in those cases.
//
// Configurations / variants (see src/lib/part.js for the canonical shape):
// a `.feature` file may declare per-file parameter overrides. The active
// config's `params` are merged OVER the equations scope before the OCCT
// worker substitutes `${name}` placeholders inside feature node fields.
export function parseFeature(content) {
  const text = (content || '').trim()
  if (!text) return { version: 1, name: 'New feature', features: [], default_config: '', configurations: [] }
  try {
    const obj = JSON.parse(text)
    return {
      version: obj.version || 1,
      name: obj.name || 'New feature',
      features: Array.isArray(obj.features) ? obj.features : [],
      metadata: obj.metadata || {},
      default_config: typeof obj.default_config === 'string' ? obj.default_config : '',
      configurations: Array.isArray(obj.configurations)
        ? obj.configurations.map(normalizeFeatureConfiguration).filter(Boolean)
        : [],
    }
  } catch {
    return { version: 1, name: 'New feature', features: [], default_config: '', configurations: [] }
  }
}

function normalizeFeatureConfiguration(raw) {
  if (!raw || typeof raw !== 'object') return null
  const id = typeof raw.id === 'string' ? raw.id.trim() : ''
  if (!id) return null
  return {
    id,
    label: typeof raw.label === 'string' && raw.label ? raw.label : id,
    params: raw.params && typeof raw.params === 'object' && !Array.isArray(raw.params)
      ? raw.params : {},
  }
}

// Serialize a parsed feature tree back to JSON. Stable ordering for diffs.
export function serializeFeature(parsed) {
  const out = {
    version: parsed?.version || 1,
    name: parsed?.name || 'New feature',
    features: Array.isArray(parsed?.features) ? parsed.features : [],
  }
  if (parsed?.metadata && typeof parsed.metadata === 'object') {
    out.metadata = parsed.metadata
  }
  if (typeof parsed?.default_config === 'string' && parsed.default_config) {
    out.default_config = parsed.default_config
  }
  if (Array.isArray(parsed?.configurations) && parsed.configurations.length > 0) {
    out.configurations = parsed.configurations.map((c) => ({
      id: c.id,
      label: c.label || c.id,
      params: c.params && typeof c.params === 'object' ? c.params : {},
    }))
  }
  return JSON.stringify(out, null, 2)
}

// Produce a fresh feature node id. Short enough for visual debugging,
// random enough that re-evaluation can't collide.
export function newFeatureId(prefix = 'feat') {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`
}
