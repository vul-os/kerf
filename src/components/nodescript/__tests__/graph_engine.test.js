/**
 * graph_engine.test.js — Vitest unit tests for the DAG engine.
 *
 * Tests:
 *  1. topoSort — 3-node chain returns nodes in correct order
 *  2. Cycle detection raises CycleError
 *  3. Disabled node skipped during run()
 *  4. Type-mismatched connect rejected with TypeMismatchError
 *  5. Two disconnected components both run
 *  6. Empty graph topoSort returns empty array
 *  7. Single node graph evaluates correctly (number node)
 *  8. Math: add node evaluates correctly
 *  9. Math: multiply node evaluates correctly
 * 10. Math: range node returns correct array
 * 11. addConnection with compatible types succeeds
 * 12. addConnection with 'any' type succeeds (wildcard)
 * 13. removeNode strips related connections
 * 14. serialise / deserialise roundtrip preserves node count
 */

import { describe, it, expect } from 'vitest'
import { Graph, CycleError, TypeMismatchError } from '../graph_engine.js'
import { getNodeDef } from '../node_library.js'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeGraph(...defIds) {
  let g = new Graph()
  const nodes = []
  for (const defId of defIds) {
    const def = getNodeDef(defId)
    if (!def) throw new Error(`Unknown node def: ${defId}`)
    g = g.addNode(def, { x: 0, y: 0 })
    nodes.push([...g.nodes.values()].at(-1))
  }
  return { g, nodes }
}

// ---------------------------------------------------------------------------
// 1. topoSort — 3-node chain
// ---------------------------------------------------------------------------

describe('topoSort', () => {
  it('returns 3-node chain (number → add → multiply) in source-first order', () => {
    const { g: g0, nodes: [numNode] } = makeGraph('number')
    const addDef = getNodeDef('add')
    const mulDef = getNodeDef('multiply')

    let g = g0.addNode(addDef, { x: 200, y: 0 })
    const addNode = [...g.nodes.values()].at(-1)

    g = g.addNode(mulDef, { x: 400, y: 0 })
    const mulNode = [...g.nodes.values()].at(-1)

    // number.value → add.a, add.result → multiply.a
    g = g.addConnection(numNode.id, 'value', addNode.id, 'a')
    g = g.addConnection(addNode.id, 'result', mulNode.id, 'a')

    const order = g.topoSort()
    const numIdx = order.indexOf(numNode.id)
    const addIdx = order.indexOf(addNode.id)
    const mulIdx = order.indexOf(mulNode.id)

    expect(numIdx).toBeGreaterThanOrEqual(0)
    expect(addIdx).toBeGreaterThan(numIdx)
    expect(mulIdx).toBeGreaterThan(addIdx)
  })

  it('empty graph returns empty array', () => {
    const g = new Graph()
    expect(g.topoSort()).toEqual([])
  })

  it('single-node graph returns that node id', () => {
    const { g, nodes: [n] } = makeGraph('number')
    expect(g.topoSort()).toEqual([n.id])
  })
})

// ---------------------------------------------------------------------------
// 2. Cycle detection
// ---------------------------------------------------------------------------

describe('cycle detection', () => {
  it('throws CycleError when A → B → A', () => {
    // We need a graph with a back-edge; bypass type-checking by manually
    // constructing the connections map.
    const { g, nodes: [a, b] } = makeGraph('add', 'multiply')
    // a.result → b.a  then b.result → a.b (cycle)
    let g2 = g.addConnection(a.id, 'result', b.id, 'a')
    // Manually inject a back-edge bypassing type check (same type)
    g2 = g2.addConnection(b.id, 'result', a.id, 'b')
    expect(() => g2.topoSort()).toThrow(CycleError)
  })

  it('throws CycleError for a self-loop', () => {
    const { g, nodes: [n] } = makeGraph('add')
    // Inject a self-connection directly
    const backConns = new Map(g.connections)
    const fakeId = 'c_self'
    backConns.set(fakeId, { id: fakeId, fromNodeId: n.id, fromPin: 'result', toNodeId: n.id, toPin: 'a' })
    const gCycle = new Graph(new Map(g.nodes), backConns)
    expect(() => gCycle.topoSort()).toThrow(CycleError)
  })
})

// ---------------------------------------------------------------------------
// 3. Disabled node skipped
// ---------------------------------------------------------------------------

describe('disabled nodes', () => {
  it('disabled node is not present in run() results', async () => {
    const { g: g0, nodes: [numNode] } = makeGraph('number')
    const g = g0.toggleDisabled(numNode.id)

    // run() with a no-op api
    const api = { callTool: async () => ({}) }
    const results = await g.run(api)
    expect(results).not.toHaveProperty(numNode.id)
  })

  it('enabled sibling still runs when one node is disabled', async () => {
    const { g: g0, nodes: [a, b] } = makeGraph('number', 'number')
    const g = g0.toggleDisabled(a.id)
    const api = { callTool: async () => ({}) }
    const results = await g.run(api)
    expect(results).not.toHaveProperty(a.id)
    expect(results).toHaveProperty(b.id)
  })
})

// ---------------------------------------------------------------------------
// 4. Type mismatch rejected
// ---------------------------------------------------------------------------

describe('type checking', () => {
  it('connecting number output to geometry input throws TypeMismatchError', () => {
    const { g, nodes: [numNode, sphereNode] } = makeGraph('number', 'sphere')
    // number.value (number) → sphere.radius (number) is VALID — use sphere → union (geometry → geometry) instead
    // Let's do number → union.a (number → geometry) which IS a mismatch
    const { g: g2, nodes: [, , unionNode] } = makeGraph('number', 'sphere', 'union')
    // number.value (type: number) → union.a (type: geometry) → mismatch
    const numberNode2 = [...g2.nodes.values()][0]
    const unionNode2  = [...g2.nodes.values()][2]
    expect(() => g2.addConnection(numberNode2.id, 'value', unionNode2.id, 'a')).toThrow(TypeMismatchError)
  })

  it('connecting geometry output to geometry input succeeds', () => {
    const { g, nodes: [sphereNode, unionNode2] } = makeGraph('sphere', 'union')
    expect(() => g.addConnection(sphereNode.id, 'geometry', unionNode2.id, 'a')).not.toThrow()
  })

  it('connecting to an "any" type pin always succeeds', () => {
    // export_stl has filename: any — connect a number to it
    const { g, nodes: [numNode, exportNode] } = makeGraph('number', 'export_stl')
    // number → export_stl.filename (any) should succeed
    expect(() => g.addConnection(numNode.id, 'value', exportNode.id, 'filename')).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 5. Two disconnected components both run
// ---------------------------------------------------------------------------

describe('disconnected components', () => {
  it('both components appear in run() results', async () => {
    const { g, nodes: [a, b] } = makeGraph('number', 'number')
    // No connection between a and b — two isolated nodes
    const api = { callTool: async () => ({}) }
    const results = await g.run(api)
    expect(results).toHaveProperty(a.id)
    expect(results).toHaveProperty(b.id)
  })
})

// ---------------------------------------------------------------------------
// 6-7. Local evaluation (client-side Math nodes)
// ---------------------------------------------------------------------------

describe('local evaluation', () => {
  it('number node returns its param value', async () => {
    const def = getNodeDef('number')
    let g = new Graph()
    g = g.addNode(def, { x: 0, y: 0 }, { value: 42 })
    const results = await g.run(null)
    const nodeId = [...g.nodes.keys()][0]
    expect(results[nodeId]).toBe(42)
  })

  it('add node returns sum of its params', async () => {
    const def = getNodeDef('add')
    let g = new Graph()
    g = g.addNode(def, { x: 0, y: 0 }, { a: 3, b: 7 })
    const results = await g.run(null)
    const nodeId = [...g.nodes.keys()][0]
    expect(results[nodeId]).toBe(10)
  })

  it('multiply node returns product of its params', async () => {
    const def = getNodeDef('multiply')
    let g = new Graph()
    g = g.addNode(def, { x: 0, y: 0 }, { a: 4, b: 5 })
    const results = await g.run(null)
    const nodeId = [...g.nodes.keys()][0]
    expect(results[nodeId]).toBe(20)
  })

  it('range node returns array from 0 to 4 with step 1', async () => {
    const def = getNodeDef('range')
    let g = new Graph()
    g = g.addNode(def, { x: 0, y: 0 }, { start: 0, end: 4, step: 1 })
    const results = await g.run(null)
    const nodeId = [...g.nodes.keys()][0]
    expect(results[nodeId]).toEqual([0, 1, 2, 3])
  })

  it('wired number → add propagates value correctly', async () => {
    const numDef = getNodeDef('number')
    const addDef = getNodeDef('add')
    let g = new Graph()
    g = g.addNode(numDef, { x: 0, y: 0 }, { value: 10 })
    const numId = [...g.nodes.keys()][0]
    g = g.addNode(addDef, { x: 200, y: 0 }, { a: 0, b: 5 })
    const addId = [...g.nodes.keys()][1]
    g = g.addConnection(numId, 'value', addId, 'a')
    const results = await g.run(null)
    // 10 (from number) + 5 (static param b) = 15
    expect(results[addId]).toBe(15)
  })
})

// ---------------------------------------------------------------------------
// 11. Serialise / deserialise roundtrip
// ---------------------------------------------------------------------------

describe('serialisation', () => {
  it('toJSON / fromJSON roundtrip preserves node and connection count', () => {
    const { g: g0, nodes: [a, b] } = makeGraph('number', 'add')
    const g = g0.addConnection(a.id, 'value', b.id, 'a')
    const json = g.toJSON()
    const g2 = Graph.fromJSON(json)
    expect(g2.nodes.size).toBe(g.nodes.size)
    expect(g2.connections.size).toBe(g.connections.size)
  })
})

// ---------------------------------------------------------------------------
// 12. removeNode strips connections
// ---------------------------------------------------------------------------

describe('removeNode', () => {
  it('removes the node and all connected edges', () => {
    const { g: g0, nodes: [a, b] } = makeGraph('number', 'add')
    const g = g0.addConnection(a.id, 'value', b.id, 'a')
    expect(g.connections.size).toBe(1)
    const g2 = g.removeNode(a.id)
    expect(g2.nodes.has(a.id)).toBe(false)
    expect(g2.connections.size).toBe(0)
  })
})
