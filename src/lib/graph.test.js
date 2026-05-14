import { describe, it, expect } from 'vitest'
import {
  defaultGraph,
  validateGraph,
  addNode,
  removeNode,
  connectNodes,
  disconnectNode,
  topologicalOrder,
  evaluateGraph,
  BUILTIN_OPS,
} from './graph.js'

// ── defaultGraph ──────────────────────────────────────────────────────────────

describe('defaultGraph', () => {
  it('returns version 1', () => {
    const g = defaultGraph('Test')
    expect(g.version).toBe(1)
    expect(g.name).toBe('Test')
    expect(g.nodes).toEqual([])
    expect(g.outputs).toEqual([])
  })

  it('defaults name to Untitled', () => {
    const g = defaultGraph()
    expect(g.name).toBe('Untitled')
  })
})

// ── validateGraph ─────────────────────────────────────────────────────────────

describe('validateGraph', () => {
  it('validates empty graph', () => {
    const { ok, errors } = validateGraph(defaultGraph())
    expect(ok).toBe(true)
    expect(errors).toHaveLength(0)
  })

  it('rejects non-object', () => {
    expect(validateGraph(null).ok).toBe(false)
    expect(validateGraph('x').ok).toBe(false)
  })

  it('rejects missing nodes array', () => {
    const { ok, errors } = validateGraph({ version: 1, name: 'x' })
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('nodes'))).toBe(true)
  })

  it('rejects duplicate node ids', () => {
    const g = { version: 1, name: 'x', nodes: [
      { id: 'n1', op: 'number_slider', params: {} },
      { id: 'n1', op: 'panel', params: {} },
    ], outputs: [] }
    const { ok, errors } = validateGraph(g)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('duplicate'))).toBe(true)
  })

  it('rejects unresolved param refs', () => {
    const g = { version: 1, name: 'x', nodes: [
      { id: 'n1', op: 'panel', params: { value: '@n99.out' }, inputs: [] },
    ], outputs: [] }
    const { ok, errors } = validateGraph(g)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('n99'))).toBe(true)
  })

  it('detects cycles', () => {
    const g = { version: 1, name: 'cyclic', nodes: [
      { id: 'n1', op: 'panel', params: { value: '@n2.out' }, inputs: ['n2'] },
      { id: 'n2', op: 'panel', params: { value: '@n1.out' }, inputs: ['n1'] },
    ], outputs: [] }
    const { ok, errors } = validateGraph(g)
    expect(ok).toBe(false)
    expect(errors.some(e => e.toLowerCase().includes('cycle'))).toBe(true)
  })

  it('accepts a valid multi-node graph', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 10 } })
    g = addNode(g, { op: 'panel', params: { value: '@n1.out' }, inputs: ['n1'] })
    const { ok } = validateGraph(g)
    expect(ok).toBe(true)
  })
})

// ── addNode / removeNode ──────────────────────────────────────────────────────

describe('addNode', () => {
  it('assigns sequential ids', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 5 } })
    g = addNode(g, { op: 'panel', params: {} })
    expect(g.nodes[0].id).toBe('n1')
    expect(g.nodes[1].id).toBe('n2')
  })

  it('throws without op', () => {
    expect(() => addNode(defaultGraph(), {})).toThrow()
  })
})

describe('removeNode', () => {
  it('removes a standalone node', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 1 } })
    g = removeNode(g, 'n1')
    expect(g.nodes).toHaveLength(0)
  })

  it('refuses to remove a node with dependents', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 1 } })
    g = addNode(g, { op: 'panel', params: { value: '@n1.out' }, inputs: ['n1'] })
    expect(() => removeNode(g, 'n1')).toThrow(/depended on/)
  })
})

// ── connectNodes / disconnectNode ─────────────────────────────────────────────

describe('connectNodes', () => {
  it('sets @ref in target param', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 5 } })
    g = addNode(g, { op: 'panel', params: {} })
    g = connectNodes(g, 'n1', 'n2', 'value')
    const n2 = g.nodes.find(n => n.id === 'n2')
    expect(n2.params.value).toBe('@n1.out')
    expect(n2.inputs).toContain('n1')
  })
})

describe('disconnectNode', () => {
  it('removes @ref from target param', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 5 } })
    g = addNode(g, { op: 'panel', params: { value: '@n1.out' }, inputs: ['n1'] })
    g = disconnectNode(g, 'n2', 'value')
    const n2 = g.nodes.find(n => n.id === 'n2')
    expect(n2.params.value).toBeUndefined()
  })
})

// ── topologicalOrder ──────────────────────────────────────────────────────────

describe('topologicalOrder', () => {
  it('empty graph returns []', () => {
    expect(topologicalOrder(defaultGraph())).toEqual([])
  })

  it('returns source before dependent', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 5 } })
    g = addNode(g, { op: 'panel', params: { value: '@n1.out' }, inputs: ['n1'] })
    const order = topologicalOrder(g)
    expect(order.indexOf('n1')).toBeLessThan(order.indexOf('n2'))
  })

  it('throws on cycle', () => {
    const g = { version: 1, name: 'x', nodes: [
      { id: 'n1', op: 'panel', params: { value: '@n2.out' }, inputs: ['n2'] },
      { id: 'n2', op: 'panel', params: { value: '@n1.out' }, inputs: ['n1'] },
    ], outputs: [] }
    expect(() => topologicalOrder(g)).toThrow(/[Cc]ycle/)
  })

  it('handles diamond dependency correctly', () => {
    // n1 -> n2, n1 -> n3, n2+n3 -> n4
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 1 } }) // n1
    g = addNode(g, { op: 'panel', params: { value: '@n1.out' }, inputs: ['n1'] }) // n2
    g = addNode(g, { op: 'panel', params: { value: '@n1.out' }, inputs: ['n1'] }) // n3
    g = addNode(g, { op: 'lerp', params: { a: '@n2.out', b: '@n3.out', t: 0.5 }, inputs: ['n2', 'n3'] }) // n4
    const order = topologicalOrder(g)
    expect(order.indexOf('n1')).toBeLessThan(order.indexOf('n2'))
    expect(order.indexOf('n1')).toBeLessThan(order.indexOf('n3'))
    expect(order.indexOf('n2')).toBeLessThan(order.indexOf('n4'))
    expect(order.indexOf('n3')).toBeLessThan(order.indexOf('n4'))
  })
})

// ── evaluateGraph ─────────────────────────────────────────────────────────────

describe('evaluateGraph', () => {
  it('evaluates a simple slider → panel graph', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 42 } }) // n1
    g = addNode(g, { op: 'panel', params: { value: '@n1.out' }, inputs: ['n1'] }) // n2
    g = { ...g, outputs: ['n2'] }
    const { outputs, errors } = evaluateGraph(g)
    expect(errors).toHaveLength(0)
    expect(outputs.n2).toBe(42)
  })

  it('evaluates slider → expression', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 10 } }) // n1
    g = addNode(g, { op: 'expression', params: { expr: 'x * 2', inputs: { x: '@n1.out' } }, inputs: ['n1'] }) // n2
    g = { ...g, outputs: ['n2'] }
    const { outputs, errors } = evaluateGraph(g)
    expect(errors).toHaveLength(0)
    expect(outputs.n2).toBe(20)
  })

  it('evaluates map_each over a series', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'series', params: { start: 0, count: 3, step: 1 } }) // n1: [0,1,2]
    g = addNode(g, { op: 'map_each', params: { array: '@n1.out', op: 'lerp', op_params: { a: 0, b: 10, t: 0.5 } }, inputs: ['n1'] }) // n2: [5,5,5]
    g = { ...g, outputs: ['n2'] }
    const { outputs, errors } = evaluateGraph(g)
    expect(errors).toHaveLength(0)
    // map_each with lerp: all items passed as value param, lerp uses a/b/t from op_params
    expect(outputs.n2).toHaveLength(3)
  })

  it('reports error for unknown op', () => {
    const g = { version: 1, name: 'x', nodes: [
      { id: 'n1', op: 'nonexistent_op', params: {} },
    ], outputs: ['n1'] }
    const { errors } = evaluateGraph(g)
    expect(errors.length).toBeGreaterThan(0)
    expect(errors[0]).toMatch(/unknown op/)
  })

  it('resolves @ref chain across multiple levels', () => {
    let g = defaultGraph()
    g = addNode(g, { op: 'number_slider', params: { value: 100 } }) // n1
    g = addNode(g, { op: 'integer_slider', params: { value: '@n1.out' }, inputs: ['n1'] }) // n2: 100
    g = addNode(g, { op: 'lerp', params: { a: 0, b: '@n2.out', t: 0.5 }, inputs: ['n2'] }) // n3: 50
    g = { ...g, outputs: ['n3'] }
    const { outputs, errors } = evaluateGraph(g)
    expect(errors).toHaveLength(0)
    expect(outputs.n3).toBe(50)
  })

  it('error path does not crash full evaluation', () => {
    const g = { version: 1, name: 'x', nodes: [
      { id: 'n1', op: 'bad_op', params: {} },
      { id: 'n2', op: 'number_slider', params: { value: 7 } },
    ], outputs: ['n2'] }
    const { outputs, errors } = evaluateGraph(g)
    expect(errors.length).toBeGreaterThan(0)
    expect(outputs.n2).toBe(7)
  })
})
