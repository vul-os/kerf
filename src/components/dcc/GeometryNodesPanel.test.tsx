/**
 * GeometryNodesPanel.test.jsx
 * ============================
 * Tests for the DCC Geometry Nodes panel.
 *
 * Strategy
 * --------
 * Tier 1 — source inspection: data-testid landmarks, callTool wiring, reuse check.
 * Tier 2 — renderToStaticMarkup smoke tests: mounts, controls present.
 * Tier 3 — exported pure-helper unit tests: makeEvaluateGraphArgs, buildNodeApi.
 * Tier 4 — reuse assertion: NodeGraphCanvas is imported, not redefined.
 */

import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'
import { renderToStaticMarkup } from 'react-dom/server'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(path.resolve(__dirname, './GeometryNodesPanel.jsx'), 'utf8')

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('lucide-react', () => {
  const Stub = () => null
  return {
    Cpu: Stub, Play: Stub, Layers: Stub, ChevronDown: Stub,
    ChevronRight: Stub, Activity: Stub, RefreshCw: Stub,
  }
})

// Mock NodeGraphCanvas (heavyweight SVG + state; sufficient to test wrapper)
vi.mock('../nodescript/NodeGraphCanvas.jsx', () => ({
  default: ({ graph, results }) => (
    <div data-testid="node-graph-canvas-mock">
      nodes:{graph?.nodes?.size ?? 0}
    </div>
  ),
}))

// Mock NodePalette
vi.mock('../nodescript/NodePalette.jsx', () => ({
  default: ({ onAddNode, collapsed }) => (
    <div data-testid="node-palette-mock">palette</div>
  ),
}))

import GeometryNodesPanel, {
  GEO_OUTPUT_NODE_IDS,
  makeEvaluateGraphArgs,
} from './GeometryNodesPanel.jsx'

// ── Source inspection ─────────────────────────────────────────────────────────

describe('GeometryNodesPanel source: required testids + reuse assertions', () => {
  it('has data-testid="geometry-nodes-panel"', () => {
    expect(src).toContain('data-testid="geometry-nodes-panel"')
  })

  it('has data-testid="btn-evaluate-graph"', () => {
    expect(src).toContain('data-testid="btn-evaluate-graph"')
  })

  it('has data-testid="node-graph-canvas-container"', () => {
    expect(src).toContain('data-testid="node-graph-canvas-container"')
  })

  it('has data-testid="geonodes-info-panel"', () => {
    expect(src).toContain('data-testid="geonodes-info-panel"')
  })

  it('imports NodeGraphCanvas from nodescript (reuse, not rewrite)', () => {
    expect(src).toContain("from '../nodescript/NodeGraphCanvas.jsx'")
  })

  it('imports NodePalette from nodescript (reuse)', () => {
    expect(src).toContain("from '../nodescript/NodePalette.jsx'")
  })

  it('imports Graph engine from nodescript (reuse)', () => {
    expect(src).toContain("from '../nodescript/graph_engine.js'")
  })

  it('does NOT define its own NodeGraphCanvas function', () => {
    // Negative check: we did not rewrite the canvas
    expect(src).not.toContain('function NodeGraphCanvas(')
    expect(src).not.toContain('const NodeGraphCanvas ')
  })

  it('dispatches GEONODES_EVALUATED action', () => {
    expect(src).toContain('GEONODES_EVALUATED')
  })

  it('dispatches GEONODES_GRAPH_CHANGED action', () => {
    expect(src).toContain('GEONODES_GRAPH_CHANGED')
  })
})

// ── GEO_OUTPUT_NODE_IDS export ────────────────────────────────────────────────

describe('GEO_OUTPUT_NODE_IDS', () => {
  it('is an array', () => {
    expect(Array.isArray(GEO_OUTPUT_NODE_IDS)).toBe(true)
  })

  it('contains mesh geometry types', () => {
    expect(GEO_OUTPUT_NODE_IDS.some((id) => id.includes('mesh'))).toBe(true)
  })

  it('contains output', () => {
    expect(GEO_OUTPUT_NODE_IDS).toContain('output')
  })
})

// ── SSR smoke tests ───────────────────────────────────────────────────────────

describe('GeometryNodesPanel renderToStaticMarkup', () => {
  it('mounts without throwing', () => {
    expect(() => renderToStaticMarkup(<GeometryNodesPanel />)).not.toThrow()
  })

  it('renders geometry-nodes-panel root', () => {
    const html = renderToStaticMarkup(<GeometryNodesPanel />)
    expect(html).toContain('geometry-nodes-panel')
  })

  it('renders evaluate button', () => {
    const html = renderToStaticMarkup(<GeometryNodesPanel />)
    expect(html).toContain('btn-evaluate-graph')
  })

  it('renders node graph canvas container', () => {
    const html = renderToStaticMarkup(<GeometryNodesPanel />)
    expect(html).toContain('node-graph-canvas-container')
  })

  it('renders geonodes info panel', () => {
    const html = renderToStaticMarkup(<GeometryNodesPanel />)
    expect(html).toContain('geonodes-info-panel')
  })

  it('accepts content prop with graph JSON', () => {
    const content = JSON.stringify({ nodes: {}, connections: {} })
    expect(() => renderToStaticMarkup(<GeometryNodesPanel content={content} />)).not.toThrow()
  })

  it('handles invalid content gracefully', () => {
    expect(() => renderToStaticMarkup(<GeometryNodesPanel content="NOT_JSON" />)).not.toThrow()
  })

  it('renders file name when file prop provided', () => {
    const html = renderToStaticMarkup(<GeometryNodesPanel file={{ name: 'test.geonodes' }} />)
    expect(html).toContain('test.geonodes')
  })

  it('renders node palette placeholder', () => {
    const html = renderToStaticMarkup(<GeometryNodesPanel />)
    expect(html).toContain('node-palette-mock')
  })

  it('renders NodeGraphCanvas placeholder', () => {
    const html = renderToStaticMarkup(<GeometryNodesPanel />)
    expect(html).toContain('node-graph-canvas-mock')
  })

  it('shows 0N · 0C stats for empty graph', () => {
    const html = renderToStaticMarkup(<GeometryNodesPanel />)
    expect(html).toContain('0N')
    expect(html).toContain('0C')
  })
})

// ── makeEvaluateGraphArgs helper ─────────────────────────────────────────────

describe('makeEvaluateGraphArgs — graph → tool call args', () => {
  it('is a function', () => {
    expect(typeof makeEvaluateGraphArgs).toBe('function')
  })

  it('returns nodes and connections keys', () => {
    // Minimal Graph-like object with toJSON
    const mockGraph = {
      nodes: new Map(),
      connections: new Map(),
      toJSON: () => ({ nodes: {}, connections: {} }),
    }
    const args = makeEvaluateGraphArgs(mockGraph)
    expect(args).toHaveProperty('nodes')
    expect(args).toHaveProperty('connections')
  })

  it('nodes and connections are plain objects (not Maps)', () => {
    const mockGraph = {
      nodes: new Map([['n1', { defId: 'number', params: { value: 1 } }]]),
      connections: new Map(),
      toJSON: () => ({ nodes: { n1: { defId: 'number', params: { value: 1 } } }, connections: {} }),
    }
    const args = makeEvaluateGraphArgs(mockGraph)
    // Should be a plain object, not a Map
    expect(args.nodes.constructor).toBe(Object)
    expect(args.connections.constructor).toBe(Object)
  })
})
