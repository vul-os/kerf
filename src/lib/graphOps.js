// graphOps.js — Op registry binding op_name → computation.
//
// Built-in ops: pure-data, evaluate client-side.
// Kerf tool ops: emit a {__defer_to_backend} marker for server evaluation.

// ── Known Kerf LLM tool op names ──────────────────────────────────────────────
// These map to backend LLM tool executors and cannot run client-side.
const BACKEND_OPS = new Set([
  'feature_extrude',
  'feature_revolve',
  'feature_sweep2',
  'feature_loft',
  'feature_chamfer',
  'feature_fillet',
  'feature_shell',
  'feature_mirror',
  'feature_helix',
  'sketch.read',
  'sketch.create',
  'sketch_offset',
  'sketch_trim',
  'sketch_extend',
  'material.read',
  'material.list',
  'assembly.add_part',
  'assembly.constrain',
])

/** Marker returned for ops that must execute on the backend. */
function deferToBackend(op, params) {
  return { __defer_to_backend: true, op, params }
}

// ── Built-in op implementations ───────────────────────────────────────────────

function number_slider(params) {
  return typeof params.value === 'number' ? params.value : Number(params.value ?? 0)
}

function integer_slider(params) {
  return Math.round(Number(params.value ?? 0))
}

function panel(params) {
  return params.value ?? null
}

function series(params) {
  const start = Number(params.start ?? 0)
  const count = Math.max(0, Math.round(Number(params.count ?? 0)))
  const step = Number(params.step ?? 1)
  const result = []
  for (let i = 0; i < count; i++) result.push(start + i * step)
  return result
}

function range(params) {
  const from = Number(params.from ?? 0)
  const to = Number(params.to ?? 1)
  const count = Math.max(2, Math.round(Number(params.count ?? 2)))
  const step = (to - from) / (count - 1)
  const result = []
  for (let i = 0; i < count; i++) result.push(from + i * step)
  return result
}

function map_each(params, context) {
  const arr = Array.isArray(params.array) ? params.array : []
  const op = params.op
  const op_params = params.op_params ?? {}
  const opFn = graphOps[op]
  if (!opFn) {
    // Backend op or unknown — defer each item
    return arr.map(item => deferToBackend(op, { ...op_params, input: item }))
  }
  return arr.map(item => opFn({ ...op_params, value: item }, context))
}

function lerp(params) {
  const a = Number(params.a ?? 0)
  const b = Number(params.b ?? 1)
  const t = Number(params.t ?? 0.5)
  return a + (b - a) * t
}

function expression(params) {
  const expr = params.expr ?? ''
  if (!expr) return null
  const inputs = params.inputs ?? {}
  // Resolve any already-resolved values in inputs
  const scope = {}
  for (const [k, v] of Object.entries(inputs)) {
    scope[k] = typeof v === 'number' ? v : Number(v)
  }
  try {
    const keys = Object.keys(scope)
    const vals = keys.map(k => scope[k])
    // eslint-disable-next-line no-new-func
    const fn = new Function(...keys, `"use strict"; return (${expr})`)
    return fn(...vals)
  } catch (e) {
    return { __error: `expression: ${e.message}` }
  }
}

// ── Op registry ───────────────────────────────────────────────────────────────

const graphOps = {
  number_slider,
  integer_slider,
  panel,
  series,
  range,
  map_each,
  lerp,
  expression,
}

// Populate backend op stubs
for (const name of BACKEND_OPS) {
  graphOps[name] = (params, _ctx) => deferToBackend(name, params)
}

export default graphOps
export { graphOps, BACKEND_OPS, deferToBackend }
