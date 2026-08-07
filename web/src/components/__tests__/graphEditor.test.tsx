// graphEditor.test.jsx — Vitest assertions for GraphEditor logic.
//
// Follows the same convention as ercWiring.test.jsx: pure data-layer tests,
// no React render overhead, because the interesting logic lives in graph.js /
// graphOps.js which GraphEditor wraps.
//
// Tests cover: default graph, add/remove nodes, connect nodes, evaluate
// (Run), error cases, and output shapes — mirroring what the UI exercises.

import { describe, it, expect } from 'vitest'
import {
  defaultGraph,
  addNode,
  removeNode,
  connectNodes,
  disconnectNode,
  evaluateGraph,
  validateGraph,
} from '../../lib/graph.js'
import { graphOps } from '../../lib/graphOps.js'

// ── Fixture helpers ──────────────────────────────────────────────────────────

function makeSliderPanel(sliderValue = 42) {
  let g = defaultGraph('test')
  g = addNode(g, { op: 'number_slider', params: { value: sliderValue } })
  g = addNode(g, { op: 'panel', params: {} })
  const [slider, panel] = g.nodes
  g = connectNodes(g, slider.id, panel.id, 'value')
  g = { ...g, outputs: [panel.id] }
  return { g, slider, panelNode: panel }
}

// ── 1. Default graph ──────────────────────────────────────────────────────────

describe('defaultGraph', () => {
  it('returns an object with an empty nodes array', () => {
    const g = defaultGraph()
    expect(g).toHaveProperty('nodes')
    expect(Array.isArray(g.nodes)).toBe(true)
    expect(g.nodes).toHaveLength(0)
  })

  it('accepts a name argument', () => {
    const g = defaultGraph('my-graph')
    expect(g.name).toBe('my-graph')
  })

  it('is valid according to validateGraph', () => {
    const { ok } = validateGraph(defaultGraph())
    expect(ok).toBe(true)
  })
})

// ── 2. addNode ────────────────────────────────────────────────────────────────

describe('addNode', () => {
  it('adds a node with the specified op', () => {
    const g = addNode(defaultGraph(), { op: 'number_slider', params: { value: 0 } })
    expect(g.nodes).toHaveLength(1)
    expect(g.nodes[0].op).toBe('number_slider')
  })

  it('assigns a unique id to each new node', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: {} })
    g = addNode(g, { op: 'panel', params: {} })
    g = addNode(g, { op: 'lerp', params: {} })
    const ids = g.nodes.map((n) => n.id)
    expect(new Set(ids).size).toBe(3)
  })

  it('stores params on the node', () => {
    const g = addNode(defaultGraph(), { op: 'number_slider', params: { value: 99 } })
    expect(g.nodes[0].params.value).toBe(99)
  })

  it('does not mutate the original graph', () => {
    const original = defaultGraph()
    addNode(original, { op: 'panel', params: {} })
    expect(original.nodes).toHaveLength(0)
  })
})

// ── 3. removeNode ─────────────────────────────────────────────────────────────

describe('removeNode', () => {
  it('removes the target node', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'panel', params: {} })
    const id = g.nodes[0].id
    const next = removeNode(g, id)
    expect(next.nodes).toHaveLength(0)
  })

  it('leaves other nodes untouched', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'panel', params: {} })
    g = addNode(g, { op: 'number_slider', params: { value: 3 } })
    const idToRemove = g.nodes[0].id
    const idToKeep = g.nodes[1].id
    const next = removeNode(g, idToRemove)
    expect(next.nodes).toHaveLength(1)
    expect(next.nodes[0].id).toBe(idToKeep)
  })

  it('throws when another node depends on the removed one', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 1 } })
    const srcId = g.nodes[0].id
    g = addNode(g, { op: 'lerp', params: { a: `@${srcId}.out`, b: 10, t: 0.5 }, inputs: [srcId] })
    expect(() => removeNode(g, srcId)).toThrow()
  })
})

// ── 4. connectNodes ───────────────────────────────────────────────────────────

describe('connectNodes', () => {
  it('writes @srcId.out into the target param', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 7 } })
    g = addNode(g, { op: 'panel', params: {} })
    const [src, tgt] = g.nodes
    const wired = connectNodes(g, src.id, tgt.id, 'value')
    expect(wired.nodes[1].params.value).toBe(`@${src.id}.out`)
  })

  it('adds source to target inputs array', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 1 } })
    g = addNode(g, { op: 'panel', params: {} })
    const [src, tgt] = g.nodes
    const wired = connectNodes(g, src.id, tgt.id, 'value')
    expect(wired.nodes[1].inputs).toContain(src.id)
  })
})

// ── 5. disconnectNode ─────────────────────────────────────────────────────────

describe('disconnectNode', () => {
  it('removes the @ref from the target param', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 5 } })
    g = addNode(g, { op: 'panel', params: {} })
    const [src, tgt] = g.nodes
    g = connectNodes(g, src.id, tgt.id, 'value')
    const unwired = disconnectNode(g, tgt.id, 'value')
    expect(unwired.nodes[1].params).not.toHaveProperty('value')
  })
})

// ── 6. evaluateGraph (Run) ────────────────────────────────────────────────────

describe('evaluateGraph (Run)', () => {
  it('resolves a slider → panel chain and returns the slider value as output', () => {
    const { g, panelNode } = makeSliderPanel(42)
    const result = evaluateGraph(g, graphOps)
    expect(result.errors).toHaveLength(0)
    expect(result.outputs[panelNode.id]).toBe(42)
  })

  it('evaluateGraph result has outputs + intermediate + errors keys', () => {
    const result = evaluateGraph(defaultGraph(), graphOps)
    expect(result).toHaveProperty('outputs')
    expect(result).toHaveProperty('intermediate')
    expect(result).toHaveProperty('errors')
  })

  it('places non-output nodes in intermediate, not outputs', () => {
    const { g, slider } = makeSliderPanel(7)
    const result = evaluateGraph(g, graphOps)
    expect(Object.keys(result.intermediate)).toContain(slider.id)
    expect(Object.keys(result.outputs)).not.toContain(slider.id)
  })

  it('records an error for an unknown op', () => {
    let g = defaultGraph()
    g = addNode(g, { op: '__bad_op__', params: {} })
    const result = evaluateGraph(g, graphOps)
    expect(result.errors.length).toBeGreaterThan(0)
    expect(result.errors[0]).toMatch(/__bad_op__/)
  })

  it('series op produces correct list length', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'series', params: { start: 0, count: 5, step: 2 } })
    g = { ...g, outputs: [g.nodes[0].id] }
    const result = evaluateGraph(g, graphOps)
    expect(Array.isArray(result.outputs[g.nodes[0].id])).toBe(true)
    expect(result.outputs[g.nodes[0].id]).toHaveLength(5)
  })

  it('lerp op evaluates midpoint correctly', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'lerp', params: { a: 0, b: 100, t: 0.25 } })
    g = { ...g, outputs: [g.nodes[0].id] }
    const result = evaluateGraph(g, graphOps)
    expect(result.outputs[g.nodes[0].id]).toBeCloseTo(25, 5)
  })

  it('backend op emits __defer_to_backend marker without crashing', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'feature_extrude', params: { depth: 10 } })
    g = { ...g, outputs: [g.nodes[0].id] }
    const result = evaluateGraph(g, graphOps)
    // Should not error — graphOps has a stub that returns the marker
    expect(result.errors).toHaveLength(0)
    expect(result.outputs[g.nodes[0].id]).toHaveProperty('__defer_to_backend', true)
  })
})
