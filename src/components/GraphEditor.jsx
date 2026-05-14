// GraphEditor.jsx — Visual editor for .graph files.
// Uses a pure-SVG DAG canvas (no reactflow) with drag-to-move nodes,
// click-to-connect ports, and a right-side param inspector.

import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { Play, Plus, Trash2, X, ChevronDown } from 'lucide-react'
import { defaultGraph, addNode, removeNode, connectNodes, disconnectNode, evaluateGraph } from '../lib/graph.js'
import { graphOps, BACKEND_OPS } from '../lib/graphOps.js'

// ── Constants ──────────────────────────────────────────────────────────────────

const NODE_W = 160
const NODE_H = 56        // base height; grows with params
const PORT_R = 6
const PARAM_ROW_H = 22
const GRID = 20

// Builtin ops from graph.js (client-side)
const BUILTIN_OP_NAMES = [
  'number_slider',
  'integer_slider',
  'panel',
  'series',
  'range',
  'map_each',
  'lerp',
  'expression',
]

// Kerf LLM tool ops (backend-deferred)
const BACKEND_OP_NAMES = [
  'feature_sweep2',
  'feature_extrude',
  'feature_revolve',
  'feature_loft',
  'feature_chamfer',
  'feature_fillet',
  'feature_shell',
  'feature_mirror',
  'feature_helix',
  'feature_pad',
  'feature_pocket',
  'sketch_offset',
  'sketch_trim',
  'sketch_extend',
  'sketch.read',
  'sketch.create',
  'material.read',
  'material.list',
  'assembly.add_part',
  'assembly.constrain',
]

const ALL_OPS = [...BUILTIN_OP_NAMES, ...BACKEND_OP_NAMES]

// Default param values for new nodes
const DEFAULT_PARAMS = {
  number_slider: { value: 0 },
  integer_slider: { value: 0 },
  panel: { value: '' },
  series: { start: 0, count: 5, step: 1 },
  range: { from: 0, to: 1, count: 10 },
  map_each: { array: [], op: 'number_slider' },
  lerp: { a: 0, b: 1, t: 0.5 },
  expression: { expr: 'a + b', inputs: { a: 0, b: 0 } },
}

// ── Layout helpers ─────────────────────────────────────────────────────────────

function nodeHeight(node) {
  const params = Object.keys(node.params || {})
  return NODE_H + params.length * PARAM_ROW_H
}

function portY(node, index, total) {
  const h = nodeHeight(node)
  if (total <= 1) return h / 2
  return (h / (total + 1)) * (index + 1)
}

function inputPortPos(node, paramIndex, paramCount) {
  const x = node.x ?? 0
  const y = node.y ?? 0
  return {
    x: x,
    y: y + portY(node, paramIndex, paramCount),
  }
}

function outputPortPos(node) {
  const x = node.x ?? 0
  const y = node.y ?? 0
  const h = nodeHeight(node)
  return { x: x + NODE_W, y: y + h / 2 }
}

// ── SVG Canvas ────────────────────────────────────────────────────────────────

function EdgePath({ from, to }) {
  const dx = Math.abs(to.x - from.x) * 0.5
  const d = `M ${from.x} ${from.y} C ${from.x + dx} ${from.y}, ${to.x - dx} ${to.y}, ${to.x} ${to.y}`
  return (
    <path
      d={d}
      stroke="#4ade80"
      strokeWidth={1.5}
      fill="none"
      strokeOpacity={0.7}
    />
  )
}

function GraphNode({
  node,
  isSelected,
  onSelect,
  onDragStart,
  onOutputPortClick,
  onInputPortClick,
  pendingSourceId,
  results,
}) {
  const h = nodeHeight(node)
  const params = Object.entries(node.params || {})
  const isBackend = BACKEND_OPS.has(node.op)
  const result = results?.[node.id]

  const bgColor = isSelected ? '#1e3a2f' : '#111'
  const borderColor = isSelected ? '#4ade80' : isBackend ? '#7c3aed' : '#2d2d2d'
  const headerColor = isBackend ? '#3b1e6b' : '#1a1a1a'

  const canConnectTo = pendingSourceId && pendingSourceId !== node.id

  return (
    <g
      transform={`translate(${node.x ?? 0}, ${node.y ?? 0})`}
      style={{ cursor: 'grab' }}
      onMouseDown={(e) => {
        e.stopPropagation()
        onDragStart(e, node.id)
        onSelect(node.id)
      }}
    >
      {/* Node body */}
      <rect
        x={0}
        y={0}
        width={NODE_W}
        height={h}
        rx={5}
        fill={bgColor}
        stroke={borderColor}
        strokeWidth={isSelected ? 1.5 : 1}
      />
      {/* Header */}
      <rect
        x={0}
        y={0}
        width={NODE_W}
        height={22}
        rx={5}
        fill={headerColor}
        style={{ pointerEvents: 'none' }}
      />
      <rect x={0} y={17} width={NODE_W} height={5} fill={headerColor} style={{ pointerEvents: 'none' }} />
      <text
        x={8}
        y={14}
        fontSize={10}
        fill={isBackend ? '#c4b5fd' : '#9ca3af'}
        fontFamily="monospace"
        style={{ pointerEvents: 'none', userSelect: 'none' }}
      >
        {node.op}
      </text>
      <text
        x={NODE_W - 8}
        y={14}
        fontSize={9}
        fill="#4b5563"
        textAnchor="end"
        fontFamily="monospace"
        style={{ pointerEvents: 'none', userSelect: 'none' }}
      >
        {node.id}
      </text>

      {/* Param rows */}
      {params.map(([key, val], i) => {
        const isRef = typeof val === 'string' && val.startsWith('@')
        const py = portY(node, i, params.length)
        const displayVal = isRef
          ? val
          : typeof val === 'object'
          ? JSON.stringify(val).slice(0, 12)
          : String(val).slice(0, 12)
        return (
          <g key={key}>
            <text
              x={14}
              y={NODE_H + i * PARAM_ROW_H + 14}
              fontSize={9}
              fill={isRef ? '#86efac' : '#6b7280'}
              fontFamily="monospace"
              style={{ pointerEvents: 'none', userSelect: 'none' }}
            >
              {key}: {displayVal}
            </text>
            {/* Input port circle */}
            <circle
              cx={0}
              cy={py}
              r={PORT_R}
              fill={isRef ? '#4ade80' : '#374151'}
              stroke={canConnectTo ? '#4ade80' : '#4b5563'}
              strokeWidth={canConnectTo ? 2 : 1}
              style={{ cursor: 'crosshair' }}
              onMouseDown={(e) => {
                e.stopPropagation()
                if (canConnectTo) onInputPortClick(node.id, key)
              }}
            />
          </g>
        )
      })}

      {/* Output port */}
      <circle
        cx={NODE_W}
        cy={h / 2}
        r={PORT_R}
        fill={pendingSourceId === node.id ? '#4ade80' : '#374151'}
        stroke={pendingSourceId === node.id ? '#86efac' : '#6b7280'}
        strokeWidth={pendingSourceId === node.id ? 2 : 1}
        style={{ cursor: 'crosshair' }}
        onMouseDown={(e) => {
          e.stopPropagation()
          onOutputPortClick(node.id)
        }}
      />

      {/* Result preview */}
      {result !== undefined && (
        <text
          x={NODE_W / 2}
          y={h - 4}
          fontSize={8}
          fill="#4ade80"
          textAnchor="middle"
          fontFamily="monospace"
          style={{ pointerEvents: 'none', userSelect: 'none' }}
        >
          {String(JSON.stringify(result)).slice(0, 20)}
        </text>
      )}
    </g>
  )
}

// ── Param inspector panel ─────────────────────────────────────────────────────

function ParamField({ paramKey, value, onUpdate }) {
  const isRef = typeof value === 'string' && value.startsWith('@')

  if (isRef) {
    return (
      <div className="flex items-center gap-2 py-1">
        <span className="text-xs text-ink-400 w-24 truncate font-mono">{paramKey}</span>
        <span className="flex-1 text-xs text-kerf-300 font-mono truncate bg-ink-850 px-2 py-0.5 rounded">
          {value}
        </span>
        <button
          type="button"
          onClick={() => onUpdate(paramKey, '')}
          className="text-ink-500 hover:text-red-400"
          title="Disconnect"
        >
          <X size={11} />
        </button>
      </div>
    )
  }

  if (typeof value === 'number') {
    return (
      <div className="flex items-center gap-2 py-1">
        <span className="text-xs text-ink-400 w-24 truncate font-mono">{paramKey}</span>
        <input
          type="number"
          value={value}
          onChange={(e) => onUpdate(paramKey, Number(e.target.value))}
          className="flex-1 bg-ink-850 border border-ink-700 rounded px-2 py-0.5 text-xs text-ink-100 font-mono outline-none focus:border-kerf-300/60"
        />
      </div>
    )
  }

  if (typeof value === 'string') {
    return (
      <div className="flex items-center gap-2 py-1">
        <span className="text-xs text-ink-400 w-24 truncate font-mono">{paramKey}</span>
        <input
          type="text"
          value={value}
          onChange={(e) => onUpdate(paramKey, e.target.value)}
          className="flex-1 bg-ink-850 border border-ink-700 rounded px-2 py-0.5 text-xs text-ink-100 font-mono outline-none focus:border-kerf-300/60"
        />
      </div>
    )
  }

  if (typeof value === 'object' && value !== null) {
    const jsonStr = JSON.stringify(value, null, 2)
    return (
      <div className="flex flex-col gap-1 py-1">
        <span className="text-xs text-ink-400 font-mono">{paramKey}</span>
        <textarea
          value={jsonStr}
          rows={Math.min(6, jsonStr.split('\n').length)}
          onChange={(e) => {
            try {
              onUpdate(paramKey, JSON.parse(e.target.value))
            } catch { /* ignore invalid JSON mid-type */ }
          }}
          className="w-full bg-ink-850 border border-ink-700 rounded px-2 py-1 text-xs text-ink-100 font-mono outline-none focus:border-kerf-300/60 resize-y"
        />
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 py-1">
      <span className="text-xs text-ink-400 w-24 truncate font-mono">{paramKey}</span>
      <span className="text-xs text-ink-500 font-mono">{String(value)}</span>
    </div>
  )
}

function InspectorPanel({ node, results, onParamUpdate, onDelete, onClose }) {
  if (!node) {
    return (
      <div className="w-64 border-l border-ink-800 bg-ink-900 flex items-center justify-center text-xs text-ink-500 p-4 text-center">
        Select a node to inspect
      </div>
    )
  }

  const result = results?.[node.id]

  return (
    <div className="w-64 border-l border-ink-800 bg-ink-900 flex flex-col min-h-0">
      <div className="flex items-center justify-between px-3 py-2 border-b border-ink-800 bg-ink-850 flex-shrink-0">
        <div>
          <div className="text-xs font-medium text-ink-100 font-mono">{node.op}</div>
          <div className="text-[10px] text-ink-500 font-mono">{node.id}</div>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onDelete(node.id)}
            title="Delete node"
            className="p-1 rounded text-ink-500 hover:text-red-400 hover:bg-ink-800"
          >
            <Trash2 size={12} />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-ink-500 hover:text-ink-100 hover:bg-ink-800"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2 min-h-0">
        <div className="text-[10px] text-ink-500 uppercase tracking-wider mb-2">Parameters</div>
        {Object.entries(node.params || {}).map(([key, val]) => (
          <ParamField
            key={key}
            paramKey={key}
            value={val}
            onUpdate={onParamUpdate}
          />
        ))}
        {Object.keys(node.params || {}).length === 0 && (
          <div className="text-xs text-ink-600 italic">No params</div>
        )}

        {result !== undefined && (
          <div className="mt-4">
            <div className="text-[10px] text-ink-500 uppercase tracking-wider mb-1">Output</div>
            <pre className="text-[10px] text-kerf-300 font-mono bg-ink-850 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main GraphEditor ──────────────────────────────────────────────────────────

export default function GraphEditor({ content, fileName, onContentChange }) {
  // Parse or default
  const [graph, setGraph] = useState(() => {
    try {
      const parsed = JSON.parse(content || '{}')
      return (parsed && parsed.nodes) ? parsed : defaultGraph(fileName || 'graph')
    } catch {
      return defaultGraph(fileName || 'graph')
    }
  })

  // Resync when content changes externally (e.g. LLM write)
  const prevContentRef = useRef(content)
  useEffect(() => {
    if (content !== prevContentRef.current) {
      prevContentRef.current = content
      try {
        const parsed = JSON.parse(content || '{}')
        if (parsed && parsed.nodes) setGraph(parsed)
      } catch { /* bad JSON, leave graph as-is */ }
    }
  }, [content])

  // Node positions (local only; written into graph on next save)
  // Seed from graph.nodes[*].x/y if present, else auto-layout
  const [positions, setPositions] = useState(() => {
    const pos = {}
    const nodes = graph.nodes || []
    nodes.forEach((n, i) => {
      pos[n.id] = { x: n.x ?? 80 + (i % 4) * 200, y: n.y ?? 80 + Math.floor(i / 4) * 160 }
    })
    return pos
  })

  const [selectedId, setSelectedId] = useState(null)
  const [pendingSourceId, setPendingSourceId] = useState(null) // output port click pending
  const [runResult, setRunResult] = useState(null)
  const [showRunPanel, setShowRunPanel] = useState(false)
  const [addDropdownOpen, setAddDropdownOpen] = useState(false)
  const [nodeResults, setNodeResults] = useState({})

  // Dragging state
  const draggingRef = useRef(null) // { nodeId, startMouse, startPos }
  const svgRef = useRef(null)

  // Debounce timer for onContentChange
  const changeTimerRef = useRef(null)

  // Merge positions into graph nodes and call onContentChange
  const flushChanges = useCallback((g, pos) => {
    if (changeTimerRef.current) clearTimeout(changeTimerRef.current)
    changeTimerRef.current = setTimeout(() => {
      const withPos = {
        ...g,
        nodes: g.nodes.map((n) => ({
          ...n,
          x: pos[n.id]?.x ?? n.x ?? 0,
          y: pos[n.id]?.y ?? n.y ?? 0,
        })),
      }
      const json = JSON.stringify(withPos, null, 2)
      prevContentRef.current = json
      onContentChange?.(json)
    }, 250)
  }, [onContentChange])

  // Run evaluation
  const handleRun = useCallback(() => {
    const result = evaluateGraph(graph, graphOps)
    setRunResult(result)
    setNodeResults({ ...result.outputs, ...result.intermediate })
    setShowRunPanel(true)
  }, [graph])

  // Add node
  const handleAddNode = useCallback((op) => {
    const params = DEFAULT_PARAMS[op] ?? {}
    const next = addNode(graph, { op, params })
    const newNode = next.nodes[next.nodes.length - 1]
    const nodesCount = next.nodes.length
    const nextPos = {
      ...positions,
      [newNode.id]: {
        x: 80 + ((nodesCount - 1) % 4) * 200,
        y: 80 + Math.floor((nodesCount - 1) / 4) * 160,
      },
    }
    setGraph(next)
    setPositions(nextPos)
    setAddDropdownOpen(false)
    setSelectedId(newNode.id)
    flushChanges(next, nextPos)
  }, [graph, positions, flushChanges])

  // Delete selected node
  const handleDeleteNode = useCallback((nodeId) => {
    try {
      const next = removeNode(graph, nodeId)
      const nextPos = { ...positions }
      delete nextPos[nodeId]
      setGraph(next)
      setPositions(nextPos)
      if (selectedId === nodeId) setSelectedId(null)
      flushChanges(next, nextPos)
    } catch (err) {
      alert(err.message)
    }
  }, [graph, positions, selectedId, flushChanges])

  // Update a param on the selected node
  const handleParamUpdate = useCallback((paramKey, value) => {
    if (!selectedId) return
    const next = {
      ...graph,
      nodes: graph.nodes.map((n) =>
        n.id !== selectedId ? n : { ...n, params: { ...n.params, [paramKey]: value } }
      ),
    }
    setGraph(next)
    flushChanges(next, positions)
  }, [graph, positions, selectedId, flushChanges])

  // Output port click — start pending connection
  const handleOutputPortClick = useCallback((nodeId) => {
    setPendingSourceId((prev) => prev === nodeId ? null : nodeId)
  }, [])

  // Input port click — complete connection
  const handleInputPortClick = useCallback((targetId, paramKey) => {
    if (!pendingSourceId || pendingSourceId === targetId) {
      setPendingSourceId(null)
      return
    }
    try {
      const next = connectNodes(graph, pendingSourceId, targetId, paramKey)
      setGraph(next)
      flushChanges(next, positions)
    } catch (err) {
      alert(err.message)
    }
    setPendingSourceId(null)
  }, [graph, positions, pendingSourceId, flushChanges])

  // Drag node start
  const handleDragStart = useCallback((e, nodeId) => {
    const pt = svgRef.current?.getBoundingClientRect()
    draggingRef.current = {
      nodeId,
      startMouseX: e.clientX,
      startMouseY: e.clientY,
      startX: positions[nodeId]?.x ?? 0,
      startY: positions[nodeId]?.y ?? 0,
    }
  }, [positions])

  // Mouse move / up on SVG
  const handleSvgMouseMove = useCallback((e) => {
    if (!draggingRef.current) return
    const { nodeId, startMouseX, startMouseY, startX, startY } = draggingRef.current
    const dx = e.clientX - startMouseX
    const dy = e.clientY - startMouseY
    const x = Math.round((startX + dx) / GRID) * GRID
    const y = Math.round((startY + dy) / GRID) * GRID
    setPositions((prev) => ({ ...prev, [nodeId]: { x, y } }))
  }, [])

  const handleSvgMouseUp = useCallback(() => {
    if (draggingRef.current) {
      const { nodeId } = draggingRef.current
      draggingRef.current = null
      // Flush position change
      setPositions((prev) => {
        flushChanges(graph, prev)
        return prev
      })
    }
  }, [graph, flushChanges])

  // Cancel connection on canvas click
  const handleCanvasClick = useCallback(() => {
    if (pendingSourceId) setPendingSourceId(null)
    else setSelectedId(null)
  }, [pendingSourceId])

  // Build edges from param refs
  const edges = useMemo(() => {
    const out = []
    for (const node of graph.nodes || []) {
      const params = Object.entries(node.params || {})
      params.forEach(([paramKey, val], paramIdx) => {
        if (typeof val === 'string' && val.startsWith('@')) {
          const m = val.match(/^@([^.]+)\.out$/)
          if (!m) return
          const srcId = m[1]
          const srcNode = graph.nodes.find((n) => n.id === srcId)
          if (!srcNode) return
          const srcPos = positions[srcId] || { x: srcNode.x ?? 0, y: srcNode.y ?? 0 }
          const dstPos = positions[node.id] || { x: node.x ?? 0, y: node.y ?? 0 }
          const fromX = srcPos.x + NODE_W
          const fromY = srcPos.y + (srcNode.y !== undefined ? 0 : 0) + nodeHeight(srcNode) / 2
          const toX = dstPos.x
          const toY = dstPos.y + portY(node, paramIdx, params.length)
          out.push({ key: `${srcId}->${node.id}.${paramKey}`, from: { x: fromX, y: fromY }, to: { x: toX, y: toY } })
        }
      })
    }
    return out
  }, [graph, positions])

  // Enrich nodes with positions
  const positionedNodes = useMemo(() => {
    return (graph.nodes || []).map((n) => ({
      ...n,
      x: positions[n.id]?.x ?? n.x ?? 0,
      y: positions[n.id]?.y ?? n.y ?? 0,
    }))
  }, [graph, positions])

  const selectedNode = positionedNodes.find((n) => n.id === selectedId) ?? null

  return (
    <div className="flex flex-col h-full min-h-0 bg-ink-950 text-ink-100" data-testid="graph-editor">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-ink-800 bg-ink-900 flex-shrink-0">
        <span className="text-[10px] text-ink-500 uppercase tracking-wider mr-1">Graph</span>

        {/* Add Node dropdown */}
        <div className="relative">
          <button
            type="button"
            data-testid="add-node-btn"
            onClick={() => setAddDropdownOpen((v) => !v)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded bg-ink-800 border border-ink-700 text-xs text-ink-200 hover:text-kerf-300 hover:border-kerf-300/40"
          >
            <Plus size={11} />
            Add Node
            <ChevronDown size={10} />
          </button>
          {addDropdownOpen && (
            <div className="absolute top-full left-0 mt-1 w-52 bg-ink-900 border border-ink-700 rounded shadow-xl z-50 py-1 max-h-80 overflow-y-auto">
              <div className="px-2 py-0.5 text-[9px] text-ink-500 uppercase tracking-wider">Built-in</div>
              {BUILTIN_OP_NAMES.map((op) => (
                <button
                  key={op}
                  type="button"
                  onClick={() => handleAddNode(op)}
                  className="w-full text-left px-3 py-1 text-xs text-ink-200 hover:bg-ink-800 hover:text-kerf-300 font-mono"
                >
                  {op}
                </button>
              ))}
              <div className="px-2 py-0.5 mt-1 text-[9px] text-ink-500 uppercase tracking-wider border-t border-ink-800">Kerf LLM tools</div>
              {BACKEND_OP_NAMES.map((op) => (
                <button
                  key={op}
                  type="button"
                  onClick={() => handleAddNode(op)}
                  className="w-full text-left px-3 py-1 text-xs text-ink-200 hover:bg-ink-800 hover:text-purple-300 font-mono"
                >
                  {op}
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          type="button"
          data-testid="run-btn"
          onClick={handleRun}
          className="inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-xs"
        >
          <Play size={11} />
          Run
        </button>

        {pendingSourceId && (
          <span className="text-xs text-kerf-300 animate-pulse ml-2">
            Click an input port to connect from {pendingSourceId}
          </span>
        )}

        <div className="flex-1" />

        <span className="text-[10px] text-ink-600 font-mono">{graph.nodes?.length ?? 0} nodes</span>

        {showRunPanel && (
          <button
            type="button"
            onClick={() => setShowRunPanel(false)}
            className="text-ink-500 hover:text-ink-100"
          >
            <X size={12} />
          </button>
        )}
      </div>

      {/* Main area */}
      <div className="flex-1 flex min-h-0">
        {/* SVG Canvas */}
        <div className="flex-1 min-w-0 min-h-0 relative overflow-hidden bg-ink-950">
          <svg
            ref={svgRef}
            className="w-full h-full"
            data-testid="graph-canvas"
            style={{ background: 'radial-gradient(circle, #1a1a1a 1px, transparent 1px) 0 0 / 20px 20px' }}
            onMouseMove={handleSvgMouseMove}
            onMouseUp={handleSvgMouseUp}
            onMouseLeave={handleSvgMouseUp}
            onClick={handleCanvasClick}
          >
            {/* Edges */}
            <g>
              {edges.map((edge) => (
                <EdgePath key={edge.key} from={edge.from} to={edge.to} />
              ))}
            </g>

            {/* Nodes */}
            <g>
              {positionedNodes.map((node) => (
                <GraphNode
                  key={node.id}
                  node={node}
                  isSelected={node.id === selectedId}
                  onSelect={setSelectedId}
                  onDragStart={handleDragStart}
                  onOutputPortClick={handleOutputPortClick}
                  onInputPortClick={handleInputPortClick}
                  pendingSourceId={pendingSourceId}
                  results={nodeResults}
                />
              ))}
            </g>

            {/* Empty state */}
            {positionedNodes.length === 0 && (
              <text x="50%" y="50%" textAnchor="middle" fill="#4b5563" fontSize={13} fontFamily="monospace">
                Add a node to get started
              </text>
            )}
          </svg>
        </div>

        {/* Right panel: inspector + optional run output */}
        <div className="flex flex-col min-h-0 border-l border-ink-800">
          <InspectorPanel
            node={selectedNode}
            results={nodeResults}
            onParamUpdate={handleParamUpdate}
            onDelete={handleDeleteNode}
            onClose={() => setSelectedId(null)}
          />
          {showRunPanel && runResult && (
            <div className="w-64 border-t border-ink-800 bg-ink-900 flex flex-col min-h-0 max-h-64">
              <div className="flex items-center justify-between px-3 py-1.5 border-b border-ink-800 flex-shrink-0">
                <span className="text-[10px] text-ink-400 uppercase tracking-wider">Run Output</span>
                {runResult.errors?.length > 0 && (
                  <span className="text-[10px] text-red-400">{runResult.errors.length} error(s)</span>
                )}
              </div>
              <div className="flex-1 overflow-y-auto px-2 py-2 min-h-0">
                {runResult.errors?.length > 0 && (
                  <div className="mb-2">
                    {runResult.errors.map((e, i) => (
                      <div key={i} className="text-[10px] text-red-400 font-mono mb-0.5">{e}</div>
                    ))}
                  </div>
                )}
                <pre
                  className="text-[10px] text-kerf-300 font-mono whitespace-pre-wrap break-all"
                  data-testid="run-output"
                >
                  {JSON.stringify({ outputs: runResult.outputs, intermediate: runResult.intermediate }, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
