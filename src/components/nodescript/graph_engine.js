/**
 * graph_engine.js — DAG evaluation engine for Visual Node Scripting.
 *
 * Public API
 * ----------
 * new Graph(nodes?, connections?)  — construct / deserialise
 * graph.addNode(def, position, params?)   → new Graph
 * graph.removeNode(nodeId)                → new Graph
 * graph.addConnection(fromNodeId, fromPin, toNodeId, toPin)  → new Graph
 * graph.removeConnection(id)              → new Graph
 * graph.topoSort()                        → nodeId[]  (throws on cycle)
 * graph.run(api)                          → Promise<{ nodeId → result }>
 * Graph.fromJSON(json)                    → Graph
 * graph.toJSON()                          → plain object
 *
 * Pin types: 'number' | 'vec3' | 'geometry' | 'array' | 'any'
 * Type-checking is enforced on addConnection; mismatched pins throw TypeError.
 * Cycle detection runs inside topoSort and throws CycleError.
 * Disabled nodes are skipped during run().
 */

import { getNodeDef, pinsCompatible } from './node_library.js'

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class CycleError extends Error {
  constructor(msg = 'Graph contains a cycle') {
    super(msg)
    this.name = 'CycleError'
  }
}

export class TypeMismatchError extends Error {
  constructor(from, to) {
    super(`Type mismatch: cannot connect '${from}' → '${to}'`)
    this.name = 'TypeMismatchError'
  }
}

// ---------------------------------------------------------------------------
// ID helpers
// ---------------------------------------------------------------------------

let _nodeSeq = 1
let _connSeq = 1

function newNodeId()  { return `n${_nodeSeq++}` }
function newConnId()  { return `c${_connSeq++}` }

// ---------------------------------------------------------------------------
// Graph (immutable value-type style)
// ---------------------------------------------------------------------------

export class Graph {
  /**
   * @param {Map<string, NodeRecord>} nodes
   * @param {Map<string, ConnectionRecord>} connections
   */
  constructor(nodes = new Map(), connections = new Map()) {
    /** @type {Map<string, NodeRecord>} */
    this.nodes = nodes
    /** @type {Map<string, ConnectionRecord>} */
    this.connections = connections
    Object.freeze(this)
  }

  // ── Mutation helpers (return new Graph) ──────────────────────────────────

  /** Add a node instantiated from a node library definition. */
  addNode(def, position = { x: 100, y: 100 }, params = {}) {
    const id = newNodeId()
    const record = {
      id,
      defId: def.id,
      label: def.label,
      position: { ...position },
      params: { ...(def.defaultParams ?? {}), ...params },
      disabled: false,
    }
    const next = new Map(this.nodes)
    next.set(id, record)
    return new Graph(next, new Map(this.connections))
  }

  /** Remove a node and all connections referencing it. */
  removeNode(nodeId) {
    if (!this.nodes.has(nodeId)) throw new Error(`Node '${nodeId}' not found`)
    const nextNodes = new Map(this.nodes)
    nextNodes.delete(nodeId)
    const nextConns = new Map(this.connections)
    for (const [cid, c] of nextConns) {
      if (c.fromNodeId === nodeId || c.toNodeId === nodeId) nextConns.delete(cid)
    }
    return new Graph(nextNodes, nextConns)
  }

  /** Toggle the disabled flag on a node. */
  toggleDisabled(nodeId) {
    const node = this.nodes.get(nodeId)
    if (!node) throw new Error(`Node '${nodeId}' not found`)
    const nextNodes = new Map(this.nodes)
    nextNodes.set(nodeId, { ...node, disabled: !node.disabled })
    return new Graph(nextNodes, new Map(this.connections))
  }

  /** Update params on a node (shallow merge). */
  updateParams(nodeId, params) {
    const node = this.nodes.get(nodeId)
    if (!node) throw new Error(`Node '${nodeId}' not found`)
    const nextNodes = new Map(this.nodes)
    nextNodes.set(nodeId, { ...node, params: { ...node.params, ...params } })
    return new Graph(nextNodes, new Map(this.connections))
  }

  /** Move a node to a new position. */
  moveNode(nodeId, position) {
    const node = this.nodes.get(nodeId)
    if (!node) throw new Error(`Node '${nodeId}' not found`)
    const nextNodes = new Map(this.nodes)
    nextNodes.set(nodeId, { ...node, position: { ...position } })
    return new Graph(nextNodes, new Map(this.connections))
  }

  /**
   * Add a connection between two pins.
   * Throws TypeMismatchError if pin types are incompatible.
   */
  addConnection(fromNodeId, fromPin, toNodeId, toPin) {
    // Resolve pin types from node defs
    const fromNode = this.nodes.get(fromNodeId)
    const toNode = this.nodes.get(toNodeId)
    if (!fromNode) throw new Error(`Node '${fromNodeId}' not found`)
    if (!toNode)   throw new Error(`Node '${toNodeId}' not found`)

    const fromDef = getNodeDef(fromNode.defId)
    const toDef   = getNodeDef(toNode.defId)

    const outPin = fromDef?.outputs.find((o) => o.name === fromPin)
    const inPin  = toDef?.inputs.find((i) => i.name === toPin)

    if (outPin && inPin && !pinsCompatible(outPin.type, inPin.type)) {
      throw new TypeMismatchError(outPin.type, inPin.type)
    }

    // Remove any existing connection to the same (toNodeId, toPin) — one wire per input
    const nextConns = new Map(this.connections)
    for (const [cid, c] of nextConns) {
      if (c.toNodeId === toNodeId && c.toPin === toPin) nextConns.delete(cid)
    }

    const id = newConnId()
    nextConns.set(id, { id, fromNodeId, fromPin, toNodeId, toPin })
    return new Graph(new Map(this.nodes), nextConns)
  }

  /** Remove a connection by its id. */
  removeConnection(connId) {
    if (!this.connections.has(connId)) throw new Error(`Connection '${connId}' not found`)
    const nextConns = new Map(this.connections)
    nextConns.delete(connId)
    return new Graph(new Map(this.nodes), nextConns)
  }

  // ── Topological sort ─────────────────────────────────────────────────────

  /**
   * Returns node IDs in topological order (sources first).
   * Throws CycleError if the graph contains a cycle.
   * Disabled nodes are included in the sort (skipped later in run()).
   */
  topoSort() {
    // Build adjacency: from → [to]
    const adj = new Map() // nodeId → Set<nodeId> (nodes that depend on it)
    const inDeg = new Map()

    for (const id of this.nodes.keys()) {
      adj.set(id, new Set())
      inDeg.set(id, 0)
    }

    for (const { fromNodeId, toNodeId } of this.connections.values()) {
      // Only add edge if both endpoints exist (defensive)
      if (!this.nodes.has(fromNodeId) || !this.nodes.has(toNodeId)) continue
      adj.get(fromNodeId).add(toNodeId)
      inDeg.set(toNodeId, (inDeg.get(toNodeId) ?? 0) + 1)
    }

    // Kahn's algorithm
    const queue = []
    for (const [id, deg] of inDeg) {
      if (deg === 0) queue.push(id)
    }

    const order = []
    while (queue.length > 0) {
      const cur = queue.shift()
      order.push(cur)
      for (const next of adj.get(cur)) {
        const d = inDeg.get(next) - 1
        inDeg.set(next, d)
        if (d === 0) queue.push(next)
      }
    }

    if (order.length !== this.nodes.size) {
      throw new CycleError()
    }

    return order
  }

  // ── Evaluation ────────────────────────────────────────────────────────────

  /**
   * Evaluate the graph in topological order.
   * @param {object} api — must expose: { callTool(toolName, params) → Promise<any> }
   * @returns {Promise<{ [nodeId: string]: any }>} map of node id → result
   */
  async run(api) {
    const order = this.topoSort()
    const results = {}  // nodeId → result

    for (const nodeId of order) {
      const node = this.nodes.get(nodeId)
      if (!node) continue
      if (node.disabled) continue

      const def = getNodeDef(node.defId)
      if (!def) {
        results[nodeId] = { error: `Unknown node type: ${node.defId}` }
        continue
      }

      // Resolve inputs: wire-connected values override node params
      const resolvedParams = { ...node.params }
      for (const conn of this.connections.values()) {
        if (conn.toNodeId !== nodeId) continue
        if (conn.fromNodeId in results) {
          resolvedParams[conn.toPin] = results[conn.fromNodeId]
        }
      }

      try {
        if (def.llm_tool_name && api?.callTool) {
          results[nodeId] = await api.callTool(def.llm_tool_name, resolvedParams)
        } else {
          results[nodeId] = _evaluateLocally(def, resolvedParams)
        }
      } catch (err) {
        results[nodeId] = { error: String(err?.message ?? err) }
      }
    }

    return results
  }

  // ── Serialisation ─────────────────────────────────────────────────────────

  toJSON() {
    return {
      nodes: Array.from(this.nodes.values()),
      connections: Array.from(this.connections.values()),
    }
  }

  static fromJSON(json) {
    const nodes = new Map()
    const connections = new Map()
    for (const n of (json.nodes ?? [])) nodes.set(n.id, n)
    for (const c of (json.connections ?? [])) connections.set(c.id, c)
    return new Graph(nodes, connections)
  }
}

// ---------------------------------------------------------------------------
// Local (client-side) evaluation for non-LLM nodes
// ---------------------------------------------------------------------------

function _evaluateLocally(def, params) {
  switch (def.id) {
    case 'number':
      return Number(params.value ?? 0)

    case 'add':
      return Number(params.a ?? 0) + Number(params.b ?? 0)

    case 'multiply':
      return Number(params.a ?? 1) * Number(params.b ?? 1)

    case 'range': {
      const start = Number(params.start ?? 0)
      const end   = Number(params.end   ?? 10)
      const step  = Number(params.step  ?? 1)
      const arr = []
      if (step === 0) return arr
      const dir = step > 0 ? 1 : -1
      for (let v = start; dir * (v - end) < 0; v += step) arr.push(v)
      return arr
    }

    case 'vector3':
      return { x: Number(params.x ?? 0), y: Number(params.y ?? 0), z: Number(params.z ?? 0) }

    case 'preview':
      // No-op output node — pass through the geometry for display
      return params.geometry ?? null

    case 'export_stl':
      // Deferred to run() where api is present; locally just return a stub
      return { deferred: true, filename: params.filename ?? 'model.stl' }

    default:
      // All other nodes (geometry / boolean / nurbs) require the backend
      return { deferred: true, defId: def.id, params }
  }
}
