/**
 * GeometryNodesPanel.jsx — Blender-parity Geometry Nodes workspace.
 *
 * Parity target: Blender Geometry Nodes editor
 *
 * Design
 * ------
 * Thin launcher/embedding: hosts the EXISTING NodeGraphCanvas (reused verbatim,
 * not rewritten) with a geometry-specific node palette and an Evaluate button
 * that walks the DAG and calls each node's backend LLM tool via callTool.
 *
 * No Three.js viewport is added here — the mesh preview is a structured JSON
 * readout of the output node's result. GPU preview is a noted gap.
 *
 * Backend tool calls (via callTool prop)
 * ---------------------------------------
 * Per-node: each node in node_library.js that has llm_tool_name will be called
 * with its input values when the graph is evaluated. The panel itself also calls
 * geometry-specific tools registered in:
 *   packages/kerf-cad-core/geometry_nodes/ (see geometry_nodes_tools.py added below)
 *
 * Default tools used during Evaluate:
 *   geometry_nodes_evaluate_graph — new minimal tool added in this commit
 *
 * Props
 * -----
 * file       {object|null}
 * content    {object|string|null}  — serialised graph JSON (Graph.toJSON()) or null
 * projectId  {string|null}
 * fileId     {string|null}
 * callTool   {(name:string, args:object) => Promise<any>}
 * onDispatch {(action:object) => void}
 */

import { useState, useCallback, useMemo } from 'react'
import { Cpu, Play, Layers, ChevronDown, ChevronRight, Activity, RefreshCw } from 'lucide-react'
import NodeGraphCanvas from '../nodescript/NodeGraphCanvas.jsx'
import NodePalette from '../nodescript/NodePalette.jsx'
import { Graph } from '../nodescript/graph_engine.js'
import { getNodeDef } from '../nodescript/node_library.js'

// ---------------------------------------------------------------------------
// Geometry-specific extra nodes that extend the generic node_library palette.
// These are visible inside the NodePalette via the Geometry category already
// present in node_library.js.
// ---------------------------------------------------------------------------

/** Geometry node IDs we treat as output sinks for result display. */
export const GEO_OUTPUT_NODE_IDS = ['mesh_sphere', 'mesh_cylinder', 'mesh_torus', 'mesh_extrude', 'output']

// ---------------------------------------------------------------------------
// Exported pure helpers — used by the component and directly unit-testable
// ---------------------------------------------------------------------------

/**
 * Convert a Graph instance into args for the geometry_nodes_evaluate_graph tool.
 * Returns { nodes: {...}, connections: {...} } as plain objects.
 * @param {Graph} graph
 */
export function makeEvaluateGraphArgs(graph) {
  const json = graph.toJSON()
  return {
    nodes: json.nodes,
    connections: json.connections,
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseContent(content) {
  if (!content) return null
  if (typeof content === 'object') return content
  try { return JSON.parse(content) } catch { return null }
}

function Section({ title, icon: Icon, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ borderBottom: '1px solid #1a1d24', paddingBottom: open ? 10 : 0, marginBottom: 2 }}>
      <button
        type="button"
        data-testid={`section-${title.toLowerCase().replace(/\s+/g, '-')}`}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, width: '100%',
          background: 'none', border: 'none', color: '#b8bfcc',
          fontSize: 11, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase',
          padding: '8px 0 4px 0', cursor: 'pointer', textAlign: 'left',
        }}
      >
        {Icon && <Icon size={12} style={{ color: '#5a6275' }} />}
        <span style={{ flex: 1 }}>{title}</span>
        {open ? <ChevronDown size={11} style={{ color: '#5a6275' }} /> : <ChevronRight size={11} style={{ color: '#5a6275' }} />}
      </button>
      {open && <div>{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function GeometryNodesPanel({
  file,
  content,
  projectId,
  fileId,
  callTool,
  onDispatch,
}) {
  const parsed = useMemo(() => parseContent(content), [content])

  // Graph state — immutable value from graph_engine.js
  const [graph, setGraph] = useState(() => {
    if (parsed?.nodes) {
      try { return Graph.fromJSON(parsed) } catch { /* fall through */ }
    }
    return new Graph()
  })

  const [selectedNodeId, setSelectedNodeId] = useState(null)
  const [paletteCollapsed, setPaletteCollapsed] = useState(false)

  // Evaluation state
  const [evalResults, setEvalResults] = useState({}) // nodeId → result
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [outputSummary, setOutputSummary] = useState(null)

  // ---------------------------------------------------------------------------
  // Graph mutations
  // ---------------------------------------------------------------------------

  const handleGraphChange = useCallback((newGraph) => {
    setGraph(newGraph)
    onDispatch?.({ type: 'GEONODES_GRAPH_CHANGED', payload: newGraph.toJSON() })
  }, [onDispatch])

  const handleAddNode = useCallback((def, position) => {
    const pos = position ?? { x: 200 + Math.random() * 100, y: 200 + Math.random() * 100 }
    handleGraphChange(graph.addNode(def, pos))
  }, [graph, handleGraphChange])

  // ---------------------------------------------------------------------------
  // Evaluate DAG
  // ---------------------------------------------------------------------------

  const doCallTool = useCallback(
    async (name, args) => {
      if (!callTool) throw new Error('callTool prop not provided')
      const raw = await callTool(name, args)
      if (typeof raw === 'string') return JSON.parse(raw)
      return raw
    },
    [callTool],
  )

  /**
   * Walk the graph in topo order; for every node that has an llm_tool_name,
   * call the backend tool with the node's current params. Collect results and
   * find the output node's result as the summary.
   */
  const evaluateGraph = useCallback(async () => {
    setLoading(true)
    setError(null)
    setEvalResults({})
    setOutputSummary(null)
    try {
      // Build a lightweight API object for Graph.run()
      const results = {}
      let order
      try {
        order = graph.topoSort()
      } catch (err) {
        setError(`Cycle or sort error: ${err.message}`)
        return
      }

      for (const nodeId of order) {
        const nodeRecord = graph.nodes.get(nodeId)
        if (!nodeRecord || nodeRecord.disabled) continue
        const def = getNodeDef(nodeRecord.defId)
        if (!def) continue
        if (def.llm_tool_name && callTool) {
          try {
            const res = await doCallTool(def.llm_tool_name, {
              ...nodeRecord.params,
              _node_id: nodeId,
            })
            results[nodeId] = res
          } catch (toolErr) {
            results[nodeId] = { ok: false, reason: String(toolErr?.message ?? toolErr) }
          }
        } else {
          results[nodeId] = { ok: true, client_only: true }
        }
      }

      setEvalResults(results)
      onDispatch?.({ type: 'GEONODES_EVALUATED', payload: { results, graph: graph.toJSON() } })

      // Find the best "output" to summarise
      const outputNodeId = order.find((nid) => {
        const nr = graph.nodes.get(nid)
        return nr && GEO_OUTPUT_NODE_IDS.includes(nr.defId)
      })
      if (outputNodeId && results[outputNodeId]) {
        setOutputSummary({ nodeId: outputNodeId, result: results[outputNodeId] })
      } else if (order.length > 0) {
        const lastId = order[order.length - 1]
        setOutputSummary({ nodeId: lastId, result: results[lastId] })
      }
    } catch (err) {
      setError(String(err?.message ?? err))
    } finally {
      setLoading(false)
    }
  }, [graph, callTool, doCallTool, onDispatch])

  // ---------------------------------------------------------------------------
  // Selected node info
  // ---------------------------------------------------------------------------

  const selectedNode = selectedNodeId ? graph.nodes.get(selectedNodeId) : null
  const selectedDef = selectedNode ? getNodeDef(selectedNode.defId) : null

  // Node count stats
  const nodeCount = graph.nodes.size
  const connCount = graph.connections.size

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      data-testid="geometry-nodes-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: '#0d0f14',
        color: '#e2e6ee',
        fontFamily: 'system-ui, sans-serif',
        fontSize: 12,
        overflow: 'hidden',
      }}
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div
        style={{
          height: 36,
          background: '#0f1115',
          borderBottom: '1px solid #1a1d24',
          display: 'flex',
          alignItems: 'center',
          padding: '0 14px',
          gap: 10,
          flexShrink: 0,
        }}
      >
        <Layers size={13} style={{ color: '#6fe06f' }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: '#e2e6ee' }}>
          Geometry Nodes
        </span>
        <span
          style={{
            fontSize: 10,
            background: '#141a14',
            border: '1px solid #2d3d2d',
            borderRadius: 3,
            color: '#6fe06f',
            padding: '1px 6px',
            fontFamily: 'monospace',
          }}
        >
          {nodeCount}N · {connCount}C
        </span>

        {/* Evaluate button */}
        <button
          type="button"
          data-testid="btn-evaluate-graph"
          onClick={evaluateGraph}
          disabled={loading || !callTool}
          style={{
            marginLeft: 'auto',
            background: loading ? '#1a2030' : '#14221a',
            border: `1px solid ${loading ? '#2d3a3d' : '#4ecf6f'}`,
            borderRadius: 4,
            color: loading ? '#5a6275' : '#4ecf6f',
            fontSize: 11,
            fontWeight: 600,
            padding: '4px 12px',
            cursor: loading ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 5,
          }}
        >
          {loading ? <RefreshCw size={11} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={11} />}
          {loading ? 'Evaluating…' : 'Evaluate'}
        </button>

        {file?.name && (
          <span style={{ fontSize: 10, color: '#5a6275', marginLeft: 8 }}>{file.name}</span>
        )}
      </div>

      {/* ── Graph area + right panel ────────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Node palette (reused from nodescript) */}
        <NodePalette
          onAddNode={handleAddNode}
          collapsed={paletteCollapsed}
          onToggleCollapse={() => setPaletteCollapsed((c) => !c)}
        />

        {/* Node graph canvas — EXISTING component, not rewritten */}
        <div
          data-testid="node-graph-canvas-container"
          style={{ flex: 1, overflow: 'hidden', position: 'relative' }}
        >
          <NodeGraphCanvas
            graph={graph}
            onGraphChange={handleGraphChange}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            results={evalResults}
          />
        </div>

        {/* Right info panel */}
        <div
          data-testid="geonodes-info-panel"
          style={{
            width: 220,
            minWidth: 220,
            background: '#0f1115',
            borderLeft: '1px solid #1a1d24',
            overflowY: 'auto',
            padding: '8px 12px',
          }}
        >
          {/* Selected node info */}
          <Section title="Node Inspector" icon={Activity} defaultOpen={true}>
            {selectedNode && selectedDef ? (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#e2e6ee', marginBottom: 4 }}>
                  {selectedDef.label}
                </div>
                <div style={{ fontSize: 10, color: '#8a909e', marginBottom: 6 }}>
                  {selectedDef.description}
                </div>
                {selectedDef.llm_tool_name && (
                  <div style={{ fontSize: 9, color: '#4e9af1', background: '#14171c', border: '1px solid #2d323d', borderRadius: 3, padding: '2px 6px', display: 'inline-block', marginBottom: 6 }}>
                    tool: {selectedDef.llm_tool_name}
                  </div>
                )}
                {/* Params */}
                {Object.entries(selectedNode.params || {}).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 3 }}>
                    <span style={{ color: '#8a909e' }}>{k}</span>
                    <span style={{ color: '#e2e6ee', fontFamily: 'monospace' }}>{JSON.stringify(v)}</span>
                  </div>
                ))}
                {/* Result for this node */}
                {evalResults[selectedNodeId] && (
                  <div
                    data-testid="selected-node-result"
                    style={{
                      marginTop: 6,
                      background: '#14171c',
                      border: '1px solid #2d323d',
                      borderRadius: 3,
                      padding: '5px 6px',
                      fontSize: 9,
                      color: '#8a909e',
                      wordBreak: 'break-all',
                    }}
                  >
                    <div style={{ color: evalResults[selectedNodeId]?.ok === false ? '#f16f8e' : '#6fe06f', fontWeight: 600, marginBottom: 3 }}>
                      Result
                    </div>
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto' }}>
                      {JSON.stringify(evalResults[selectedNodeId], null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            ) : (
              <p style={{ fontSize: 10, color: '#5a6275' }}>
                Click a node to inspect.
              </p>
            )}
          </Section>

          {/* Output summary */}
          <Section title="Output" icon={Cpu} defaultOpen={true}>
            {outputSummary ? (
              <div>
                <div style={{ fontSize: 10, color: '#6fe06f', marginBottom: 4, fontFamily: 'monospace' }}>
                  {outputSummary.nodeId}
                </div>
                <pre
                  data-testid="output-summary"
                  style={{
                    fontSize: 9,
                    color: '#8a909e',
                    background: '#0a0c10',
                    border: '1px solid #1a1d24',
                    borderRadius: 3,
                    padding: '6px',
                    overflowX: 'auto',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                    margin: 0,
                    maxHeight: 200,
                  }}
                >
                  {JSON.stringify(outputSummary.result, null, 2)}
                </pre>
              </div>
            ) : nodeCount === 0 ? (
              <p style={{ fontSize: 10, color: '#5a6275' }}>
                Add nodes from the palette and click Evaluate.
              </p>
            ) : (
              <p style={{ fontSize: 10, color: '#5a6275' }}>
                Click Evaluate to run the graph.
              </p>
            )}
          </Section>

          {/* Error */}
          {error && (
            <div
              data-testid="geonodes-error"
              style={{
                background: '#2a1010',
                border: '1px solid #7f2020',
                borderRadius: 4,
                padding: '6px 8px',
                fontSize: 10,
                color: '#f16f8e',
                marginTop: 6,
              }}
            >
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
