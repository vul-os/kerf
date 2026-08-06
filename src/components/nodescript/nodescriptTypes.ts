// nodescriptTypes.ts — shared types for src/components/nodescript/ (T-510).
//
// Local to this folder (not src/types/) — the Visual Node Scripting DAG's node-library
// catalog shape, graph value-type records, and the ad-hoc result shapes `graph_engine`'s
// run() produces (per-node results are either a locally-evaluated primitive or whatever a
// backend LLM tool call returns — a boundary this slice does not own). Mined from the actual
// field reads in graph_engine.ts / node_library.ts / the four presentational components.

/** Pin data type. `'any'` is a wildcard that connects to/from every other type. */
export type PinType = 'number' | 'vec3' | 'geometry' | 'array' | 'any'

/** One input or output pin on a node-library definition. */
export interface PinDef {
  name: string
  type: PinType
  /** Only present on input pins; unused by output pins. */
  default?: unknown
}

export type NodeCategory = 'Math' | 'Geometry' | 'Boolean' | 'NURBS' | 'Output'

/** A catalog entry from `node_library.ts` — the template a graph node instantiates from. */
export interface NodeDef {
  id: string
  label: string
  category: NodeCategory
  description: string
  inputs: PinDef[]
  outputs: PinDef[]
  /** Backend LLM tool this node maps to, or `null` for a client-evaluated node. */
  llm_tool_name: string | null
  defaultParams: Record<string, unknown>
}

/** A 2D canvas position. */
export interface NodePosition {
  x: number
  y: number
}

/** One placed node instance in a `Graph` (plain-data record, not the def). */
export interface NodeRecord {
  id: string
  defId: string
  label: string
  position: NodePosition
  params: Record<string, unknown>
  disabled: boolean
}

/** One wire between an output pin and an input pin. */
export interface ConnectionRecord {
  id: string
  fromNodeId: string
  fromPin: string
  toNodeId: string
  toPin: string
}

/** `Graph.toJSON()` / `Graph.fromJSON()` wire format. */
export interface GraphJSON {
  nodes: NodeRecord[]
  connections: ConnectionRecord[]
}

/** What `Graph.run()` needs from its caller — the LLM tool-call dispatcher. */
export interface GraphRunApi {
  callTool: (toolName: string, params: Record<string, unknown>) => Promise<unknown>
}

/** A node whose evaluation depends on a later backend/API call that hasn't happened yet
 *  (returned by `_evaluateLocally` for geometry-producing nodes with no `api` available). */
export interface DeferredResult {
  deferred: true
  filename?: string
  defId?: string
  params?: Record<string, unknown>
}

/** A failed node evaluation, surfaced inline instead of throwing (`Graph.run()` catches). */
export interface NodeErrorResult {
  error: string
}

export interface Vec3Value {
  x: number
  y: number
  z: number
}

/**
 * The value stored per node id in `Graph.run()`'s result map. Genuinely open-ended: local
 * Math nodes return a bare number or array, `vector3` returns `Vec3Value`, unresolved
 * geometry nodes return `DeferredResult`, a thrown error becomes `NodeErrorResult`, and any
 * backend tool call result is whatever that tool's JSON response happens to contain.
 */
export type NodeResult =
  | number
  | number[]
  | Vec3Value
  | DeferredResult
  | NodeErrorResult
  | Record<string, unknown>
  | null

/** `Graph.run()`'s return value: node id → its result. */
export type GraphResults = Record<string, NodeResult>
