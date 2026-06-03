/**
 * NodeScript.jsx — Visual Node Scripting page (Dynamo/Grasshopper equivalent).
 *
 * Three-column layout:
 *   Left:   NodePalette — searchable node library
 *   Center: NodeGraphCanvas — pan/zoom SVG canvas
 *   Right:  PropertyInspector — selected node parameters
 *
 * Bottom:  Result panel — last run outputs per node
 * Top bar: Run / Save / Load controls
 */

import { useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Play, Save, FolderOpen, GitBranch } from 'lucide-react'

import NodeGraphCanvas   from '../components/nodescript/NodeGraphCanvas.jsx'
import NodePalette       from '../components/nodescript/NodePalette.jsx'
import PropertyInspector from '../components/nodescript/PropertyInspector.jsx'
import { Graph, CycleError } from '../components/nodescript/graph_engine.js'
import { getNodeDef }        from '../components/nodescript/node_library.js'

// ---------------------------------------------------------------------------
// Default starting graph
// ---------------------------------------------------------------------------

function makeDefaultGraph() {
  const numDef = getNodeDef('number')
  const addDef = getNodeDef('add')
  const mulDef = getNodeDef('multiply')

  let g = new Graph()
  g = g.addNode(numDef,  { x: 80,  y: 120 }, { value: 3 })
  const [n1] = [...g.nodes.values()]
  g = g.addNode(numDef,  { x: 80,  y: 220 }, { value: 7 })
  const [, n2] = [...g.nodes.values()]
  g = g.addNode(addDef,  { x: 320, y: 160 }, { a: 0, b: 0 })
  const [, , n3] = [...g.nodes.values()]
  g = g.addNode(mulDef,  { x: 560, y: 160 }, { a: 0, b: 2 })
  const [, , , n4] = [...g.nodes.values()]

  try {
    g = g.addConnection(n1.id, 'value', n3.id, 'a')
    g = g.addConnection(n2.id, 'value', n3.id, 'b')
    g = g.addConnection(n3.id, 'result', n4.id, 'a')
  } catch { /* ignore */ }

  return g
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function NodeScriptPage() {
  const navigate = useNavigate()

  const [graph, setGraph]             = useState(makeDefaultGraph)
  const [selectedNodeId, setSelected] = useState(null)
  const [results, setResults]         = useState({})
  const [running, setRunning]         = useState(false)
  const [runError, setRunError]       = useState(null)
  const [paletteCollapsed, setPaletteCollapsed] = useState(false)
  const [resultPanelOpen, setResultPanelOpen]   = useState(false)

  // ── Add node from palette ─────────────────────────────────────────────────

  const handleAddNode = useCallback((def) => {
    // Place near centre with a slight cascade
    const nodeCount = graph.nodes.size
    const x = 200 + (nodeCount % 5) * 220
    const y = 100 + Math.floor(nodeCount / 5) * 160
    setGraph((g) => g.addNode(def, { x, y }))
  }, [graph])

  // ── Run graph ─────────────────────────────────────────────────────────────

  const handleRun = useCallback(async () => {
    setRunning(true)
    setRunError(null)
    try {
      const api = {
        async callTool(toolName, params) {
          const res = await fetch(`/api/llm-tools/${toolName}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
          })
          if (!res.ok) throw new Error(`${toolName} → HTTP ${res.status}`)
          return res.json()
        },
      }
      const r = await graph.run(api)
      setResults(r)
      setResultPanelOpen(true)
    } catch (err) {
      setRunError(err?.message ?? String(err))
    } finally {
      setRunning(false)
    }
  }, [graph])

  // ── Save / Load ──────────────────────────────────────────────────────────

  const handleSave = useCallback(() => {
    const json = JSON.stringify(graph.toJSON(), null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = 'graph.nodescript.json'
    a.click()
    URL.revokeObjectURL(url)
  }, [graph])

  const fileInputRef = useRef(null)

  const handleLoad = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFileChange = useCallback((e) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const json = JSON.parse(ev.target.result)
        setGraph(Graph.fromJSON(json))
        setResults({})
        setSelected(null)
      } catch (err) {
        alert(`Failed to load graph: ${err.message}`)
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }, [])

  // ── Selected node ─────────────────────────────────────────────────────────

  const selectedNode = selectedNodeId ? graph.nodes.get(selectedNodeId) : null
  const selectedDef  = selectedNode ? getNodeDef(selectedNode.defId) : null

  const handleParamChange = useCallback((nodeId, paramName, value) => {
    setGraph((g) => g.updateParams(nodeId, { [paramName]: value }))
  }, [])

  // ── Node result entries for bottom panel ──────────────────────────────────

  const resultEntries = Object.entries(results)

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        background: '#0a0b0d',
        color: '#e2e6ee',
        fontFamily: 'var(--font-sans)',
        overflow: 'hidden',
      }}
    >
      {/* ── Top bar ── */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '0 12px',
          height: 44,
          borderBottom: '1px solid #1a1d24',
          background: '#0f1115',
          flexShrink: 0,
        }}
      >
        <button
          type="button"
          onClick={() => navigate(-1)}
          title="Go back"
          style={{ background: 'none', border: 'none', color: '#5a6275', cursor: 'pointer', display: 'flex', alignItems: 'center', padding: 4, borderRadius: 4 }}
          onMouseEnter={(e) => { e.currentTarget.style.color = '#b8bfcc' }}
          onMouseLeave={(e) => { e.currentTarget.style.color = '#5a6275' }}
        >
          <ArrowLeft size={16} />
        </button>

        <GitBranch size={16} style={{ color: '#6bd4ff' }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e6ee' }}>Node Script</span>
        <span style={{ fontSize: 10, color: '#3a4150', background: '#14171c', border: '1px solid #232730', borderRadius: 3, padding: '1px 6px' }}>
          BETA
        </span>

        <div style={{ flex: 1 }} />

        {/* Run */}
        <button
          type="button"
          onClick={handleRun}
          disabled={running}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 5,
            background: running ? '#232730' : '#6bd4ff22',
            border: `1px solid ${running ? '#2d323d' : '#6bd4ff60'}`,
            borderRadius: 5,
            color: running ? '#5a6275' : '#6bd4ff',
            fontSize: 12,
            fontWeight: 600,
            padding: '4px 12px',
            cursor: running ? 'not-allowed' : 'pointer',
          }}
        >
          <Play size={12} />
          {running ? 'Running…' : 'Run Graph'}
        </button>

        {/* Save */}
        <button
          type="button"
          onClick={handleSave}
          title="Save graph as JSON"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 5,
            background: '#14171c',
            border: '1px solid #2d323d',
            borderRadius: 5,
            color: '#b8bfcc',
            fontSize: 12,
            padding: '4px 10px',
            cursor: 'pointer',
          }}
        >
          <Save size={12} />
          Save
        </button>

        {/* Load */}
        <button
          type="button"
          onClick={handleLoad}
          title="Load graph from JSON"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 5,
            background: '#14171c',
            border: '1px solid #2d323d',
            borderRadius: 5,
            color: '#b8bfcc',
            fontSize: 12,
            padding: '4px 10px',
            cursor: 'pointer',
          }}
        >
          <FolderOpen size={12} />
          Load
        </button>
        <input ref={fileInputRef} type="file" accept=".json" onChange={handleFileChange} style={{ display: 'none' }} />

        {/* Error badge */}
        {runError && (
          <span style={{ fontSize: 11, color: '#ef4444', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            ⚠ {runError}
          </span>
        )}
      </header>

      {/* ── Main 3-column body ── */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left: palette */}
        <NodePalette
          onAddNode={handleAddNode}
          collapsed={paletteCollapsed}
          onToggleCollapse={() => setPaletteCollapsed((v) => !v)}
        />

        {/* Centre: canvas + bottom result panel */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <NodeGraphCanvas
            graph={graph}
            onGraphChange={setGraph}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelected}
            results={results}
          />

          {/* Bottom result panel */}
          {resultPanelOpen && resultEntries.length > 0 && (
            <div
              style={{
                height: 140,
                borderTop: '1px solid #1a1d24',
                background: '#0f1115',
                overflowX: 'auto',
                overflowY: 'hidden',
                display: 'flex',
                gap: 1,
                flexShrink: 0,
              }}
            >
              <button
                type="button"
                onClick={() => setResultPanelOpen(false)}
                style={{
                  alignSelf: 'flex-start',
                  background: 'none',
                  border: 'none',
                  color: '#5a6275',
                  cursor: 'pointer',
                  padding: '6px 8px',
                  fontSize: 11,
                }}
                title="Close results"
              >
                ✕
              </button>
              {resultEntries.map(([nodeId, val]) => {
                const node = graph.nodes.get(nodeId)
                return (
                  <div
                    key={nodeId}
                    style={{
                      width: 200,
                      flexShrink: 0,
                      borderRight: '1px solid #1a1d24',
                      padding: '6px 8px',
                      overflow: 'hidden',
                    }}
                  >
                    <p style={{ margin: '0 0 3px', fontSize: 10, fontWeight: 600, color: '#8a93a6', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {node?.label ?? nodeId}
                    </p>
                    <pre style={{ margin: 0, fontSize: 9, color: val?.error ? '#ef4444' : '#34d399', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 100, overflowY: 'auto' }}>
                      {JSON.stringify(val, null, 1)}
                    </pre>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Right: property inspector */}
        <PropertyInspector
          node={selectedNode}
          def={selectedDef}
          result={selectedNodeId ? results[selectedNodeId] : undefined}
          onChange={handleParamChange}
        />
      </div>
    </div>
  )
}
