// graph.js — Parametric graph (.graph file kind) DAG evaluator.
//
// A graph is a DAG of nodes. Each node has an op name, params, and optional
// input edges. Param values may be literal or `@nX.out` references resolved
// at eval time from upstream node outputs.

// ── Constants ─────────────────────────────────────────────────────────────────

const VERSION = 1

// Built-in op names that are evaluated client-side (pure data, no server call).
const BUILTIN_OP_NAMES = new Set([
  'number_slider',
  'integer_slider',
  'panel',
  'series',
  'range',
  'map_each',
  'lerp',
  'expression',
])

// ── Built-in ops ──────────────────────────────────────────────────────────────

/**
 * Pure-data built-in op implementations.
 * Each receives (params, context) where context.results holds upstream outputs.
 */
export const BUILTIN_OPS = {
  number_slider(params) {
    const v = params.value ?? 0
    return typeof v === 'number' ? v : Number(v)
  },

  integer_slider(params) {
    const v = params.value ?? 0
    return Math.round(Number(v))
  },

  panel(params) {
    return params.value ?? null
  },

  series(params) {
    const start = Number(params.start ?? 0)
    const count = Math.max(0, Math.round(Number(params.count ?? 0)))
    const step = Number(params.step ?? 1)
    const result = []
    for (let i = 0; i < count; i++) result.push(start + i * step)
    return result
  },

  range(params) {
    const from = Number(params.from ?? 0)
    const to = Number(params.to ?? 1)
    const count = Math.max(2, Math.round(Number(params.count ?? 2)))
    const step = (to - from) / (count - 1)
    const result = []
    for (let i = 0; i < count; i++) result.push(from + i * step)
    return result
  },

  map_each(params) {
    const arr = Array.isArray(params.array) ? params.array : []
    const op = params.op
    const op_params = params.op_params ?? {}
    if (!op || !BUILTIN_OPS[op]) {
      // Defer to backend or return marker if op unknown
      return arr.map(item => ({ __defer_to_backend: true, op, params: { ...op_params, value: item } }))
    }
    return arr.map(item => BUILTIN_OPS[op]({ ...op_params, value: item }))
  },

  lerp(params) {
    const a = Number(params.a ?? 0)
    const b = Number(params.b ?? 1)
    const t = Number(params.t ?? 0.5)
    return a + (b - a) * t
  },

  expression(params) {
    // Evaluate a simple math expression. Named inputs are merged into scope.
    // Uses Function() eval with a restricted scope.
    const expr = params.expr ?? ''
    if (!expr) return null
    const inputs = params.inputs ?? {}
    try {
      // Build a scope from named inputs
      const keys = Object.keys(inputs)
      const vals = keys.map(k => inputs[k])
      // eslint-disable-next-line no-new-func
      const fn = new Function(...keys, `"use strict"; return (${expr})`)
      return fn(...vals)
    } catch (e) {
      return { __error: `expression: ${e.message}` }
    }
  },
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Generate a short unique node id. */
function _genId(graph) {
  const existing = new Set(graph.nodes.map(n => n.id))
  let i = graph.nodes.length + 1
  while (existing.has(`n${i}`)) i++
  return `n${i}`
}

/** Resolve a single value — handles string refs, arrays, and plain objects recursively. */
function _resolveValue(v, results) {
  if (typeof v === 'string' && v.startsWith('@')) {
    const m = v.match(/^@([^.]+)\.out$/)
    return m ? (results[m[1]] ?? { __unresolved: v }) : v
  }
  if (Array.isArray(v)) {
    return v.map(el => _resolveValue(el, results))
  }
  if (v !== null && typeof v === 'object') {
    const resolved = {}
    for (const [k2, v2] of Object.entries(v)) resolved[k2] = _resolveValue(v2, results)
    return resolved
  }
  return v
}

/** Resolve `@nX.out` references inside a params object given current results. */
function _resolveParams(params, results) {
  const out = {}
  for (const [k, v] of Object.entries(params)) {
    out[k] = _resolveValue(v, results)
  }
  return out
}

/** Collect all node ids referenced as @nX.out in a value (recursive). */
function _collectRefs(v, refs) {
  if (typeof v === 'string') {
    const m = v.match(/^@([^.]+)\.out$/)
    if (m) refs.push(m[1])
  } else if (Array.isArray(v)) {
    for (const el of v) _collectRefs(el, refs)
  } else if (v !== null && typeof v === 'object') {
    for (const v2 of Object.values(v)) _collectRefs(v2, refs)
  }
}

/** Collect all node ids referenced in a params object. */
function _paramRefs(params) {
  const refs = []
  for (const v of Object.values(params)) _collectRefs(v, refs)
  return refs
}

// ── Core exports ──────────────────────────────────────────────────────────────

/** Return a new empty graph. */
export function defaultGraph(name = 'Untitled') {
  return { version: VERSION, name, nodes: [], outputs: [] }
}

/**
 * Validate graph structure.
 * Returns {ok: bool, errors: string[]}.
 */
export function validateGraph(graph) {
  const errors = []
  if (!graph || typeof graph !== 'object') {
    return { ok: false, errors: ['graph must be an object'] }
  }
  if (!Array.isArray(graph.nodes)) errors.push('graph.nodes must be an array')

  const ids = new Set()
  for (const node of graph.nodes ?? []) {
    if (!node.id) { errors.push(`node missing id`); continue }
    if (ids.has(node.id)) errors.push(`duplicate node id: ${node.id}`)
    ids.add(node.id)
    if (!node.op) errors.push(`node ${node.id} missing op`)
  }

  // Check all input refs resolve
  for (const node of graph.nodes ?? []) {
    for (const ref of _paramRefs(node.params ?? {})) {
      if (!ids.has(ref)) errors.push(`node ${node.id}: param ref @${ref}.out not found`)
    }
    for (const inp of node.inputs ?? []) {
      if (!ids.has(inp)) errors.push(`node ${node.id}: input ref ${inp} not found`)
    }
  }

  // Cycle detection
  try {
    topologicalOrder(graph)
  } catch (e) {
    errors.push(e.message)
  }

  return { ok: errors.length === 0, errors }
}

/**
 * Add a node to the graph. Returns a new graph (immutable update).
 */
export function addNode(graph, { op, params = {}, inputs = [] }) {
  if (!op) throw new Error('op is required')
  const id = _genId(graph)
  const node = { id, op, params, inputs }
  return { ...graph, nodes: [...graph.nodes, node] }
}

/**
 * Remove a node. Throws if other nodes depend on it.
 */
export function removeNode(graph, node_id) {
  const dependents = graph.nodes.filter(n => {
    const paramRefs = _paramRefs(n.params ?? {})
    return paramRefs.includes(node_id) || (n.inputs ?? []).includes(node_id)
  })
  if (dependents.length > 0) {
    throw new Error(`Cannot remove ${node_id}: depended on by ${dependents.map(n => n.id).join(', ')}`)
  }
  return {
    ...graph,
    nodes: graph.nodes.filter(n => n.id !== node_id),
    outputs: (graph.outputs ?? []).filter(id => id !== node_id),
  }
}

/**
 * Wire source_id.out → target_id's target_param.
 */
export function connectNodes(graph, source_id, target_id, target_param) {
  const nodes = graph.nodes.map(n => {
    if (n.id !== target_id) return n
    const inputs = Array.from(new Set([...(n.inputs ?? []), source_id]))
    return { ...n, params: { ...n.params, [target_param]: `@${source_id}.out` }, inputs }
  })
  return { ...graph, nodes }
}

/**
 * Remove @ref wiring from target_id's target_param.
 */
export function disconnectNode(graph, target_id, target_param) {
  const nodes = graph.nodes.map(n => {
    if (n.id !== target_id) return n
    const params = { ...n.params }
    delete params[target_param]
    // Remove from inputs if no other param references it
    const remaining = _paramRefs(params)
    const inputs = (n.inputs ?? []).filter(id => remaining.includes(id))
    return { ...n, params, inputs }
  })
  return { ...graph, nodes }
}

/**
 * Topological order via Kahn's algorithm. Throws on cycle.
 * Returns array of node ids.
 */
export function topologicalOrder(graph) {
  const nodes = graph.nodes ?? []
  const ids = nodes.map(n => n.id)
  const idSet = new Set(ids)

  // Build adjacency and in-degree
  const inDegree = {}
  const adjList = {} // src -> [targets]
  for (const id of ids) { inDegree[id] = 0; adjList[id] = [] }

  for (const node of nodes) {
    const deps = new Set([
      ..._paramRefs(node.params ?? {}),
      ...(node.inputs ?? []),
    ])
    for (const dep of deps) {
      if (idSet.has(dep)) {
        adjList[dep].push(node.id)
        inDegree[node.id] = (inDegree[node.id] ?? 0) + 1
      }
    }
  }

  const queue = ids.filter(id => inDegree[id] === 0)
  const order = []

  while (queue.length > 0) {
    const cur = queue.shift()
    order.push(cur)
    for (const next of adjList[cur]) {
      inDegree[next]--
      if (inDegree[next] === 0) queue.push(next)
    }
  }

  if (order.length !== ids.length) {
    throw new Error('Cycle detected in graph')
  }
  return order
}

/**
 * Evaluate the graph.
 * ops: {[op_name]: (params, context) => result}
 * Returns {outputs, intermediate, errors}.
 */
export function evaluateGraph(graph, ops = {}) {
  const errors = []
  const results = {}
  const allOps = { ...BUILTIN_OPS, ...ops }

  let order
  try {
    order = topologicalOrder(graph)
  } catch (e) {
    return { outputs: {}, intermediate: {}, errors: [e.message] }
  }

  const nodeMap = Object.fromEntries((graph.nodes ?? []).map(n => [n.id, n]))

  for (const id of order) {
    const node = nodeMap[id]
    if (!node) continue
    const opFn = allOps[node.op]
    if (!opFn) {
      errors.push(`unknown op: ${node.op} on node ${id}`)
      results[id] = { __error: `unknown op: ${node.op}` }
      continue
    }
    const resolvedParams = _resolveParams(node.params ?? {}, results)
    try {
      results[id] = opFn(resolvedParams, { results, graph })
    } catch (e) {
      errors.push(`node ${id} (${node.op}): ${e.message}`)
      results[id] = { __error: e.message }
    }
  }

  const outputIds = graph.outputs ?? []
  const outputs = Object.fromEntries(outputIds.map(id => [id, results[id]]))
  const intermediate = Object.fromEntries(
    Object.entries(results).filter(([id]) => !outputIds.includes(id))
  )

  return { outputs, intermediate, errors }
}
