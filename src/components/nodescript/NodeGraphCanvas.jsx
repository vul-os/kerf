/**
 * NodeGraphCanvas.jsx — main SVG pan/zoom canvas for the node graph.
 *
 * Features:
 * - Pan: middle-mouse drag or space+left-drag
 * - Zoom: wheel
 * - Drag nodes
 * - Click-drag from output pin → input pin draws a wire
 * - Right-click node → context menu (Delete, Duplicate, Disable)
 * - Selected connection highlighted
 */

import { useCallback, useRef, useState, useEffect } from 'react'
import Node from './Node.jsx'
import Connection from './Connection.jsx'
import { getNodeDef, CATEGORY_COLORS } from './node_library.js'
import { Graph, CycleError, TypeMismatchError } from './graph_engine.js'

export default function NodeGraphCanvas({
  graph,
  onGraphChange,
  selectedNodeId,
  onSelectNode,
  results,
}) {
  const svgRef = useRef(null)
  const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 })

  // Drag state
  const dragNode  = useRef(null)   // { nodeId, startX, startY, origX, origY }
  const panState  = useRef(null)   // { startX, startY, origVx, origVy }
  const spaceDown = useRef(false)

  // Wire-drawing state
  const wireState = useRef(null)   // { fromNodeId, fromPin, fromSide, curX, curY }
  const [wirePreview, setWirePreview] = useState(null)

  // Context menu
  const [ctxMenu, setCtxMenu] = useState(null) // { nodeId, x, y }

  // Selected connection
  const [selectedConnId, setSelectedConnId] = useState(null)

  // Pin position registry: key = `nodeId_pinName_side`
  const pinPositions = useRef({})
  const registerPinPosition = useCallback((key, pos) => {
    pinPositions.current[key] = pos
  }, [])

  // ── Viewport helpers ────────────────────────────────────────────────────

  const svgToWorld = useCallback((svgX, svgY) => {
    const { x, y, scale } = viewport
    return { x: (svgX - x) / scale, y: (svgY - y) / scale }
  }, [viewport])

  const getSVGPoint = useCallback((e) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }, [])

  // ── Keyboard ─────────────────────────────────────────────────────────────

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.code === 'Space' && e.target === document.body) {
        spaceDown.current = true
        e.preventDefault()
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedConnId) {
        try {
          onGraphChange(graph.removeConnection(selectedConnId))
          setSelectedConnId(null)
        } catch { /* ignore */ }
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedNodeId) {
        try {
          onGraphChange(graph.removeNode(selectedNodeId))
          onSelectNode(null)
        } catch { /* ignore */ }
      }
    }
    const onKeyUp = (e) => { if (e.code === 'Space') spaceDown.current = false }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => { window.removeEventListener('keydown', onKeyDown); window.removeEventListener('keyup', onKeyUp) }
  }, [graph, selectedConnId, selectedNodeId, onGraphChange, onSelectNode])

  // ── Mouse handlers ────────────────────────────────────────────────────────

  const handleSVGMouseDown = useCallback((e) => {
    if (e.button === 1 || (e.button === 0 && spaceDown.current)) {
      // Pan
      const pt = getSVGPoint(e)
      panState.current = { startX: pt.x, startY: pt.y, origVx: viewport.x, origVy: viewport.y }
      e.preventDefault()
    } else if (e.button === 0) {
      // Deselect
      onSelectNode(null)
      setCtxMenu(null)
      setSelectedConnId(null)
    }
  }, [viewport, getSVGPoint, onSelectNode])

  const handleMouseMove = useCallback((e) => {
    const pt = getSVGPoint(e)

    // Panning
    if (panState.current) {
      const dx = pt.x - panState.current.startX
      const dy = pt.y - panState.current.startY
      setViewport((v) => ({ ...v, x: panState.current.origVx + dx, y: panState.current.origVy + dy }))
      return
    }

    // Node drag
    if (dragNode.current) {
      const world = svgToWorld(pt.x, pt.y)
      const { nodeId, startWorldX, startWorldY, origX, origY } = dragNode.current
      const dx = world.x - startWorldX
      const dy = world.y - startWorldY
      onGraphChange(graph.moveNode(nodeId, { x: origX + dx, y: origY + dy }))
      return
    }

    // Wire preview
    if (wireState.current) {
      setWirePreview({ ...wireState.current, toX: pt.x, toY: pt.y })
    }
  }, [graph, getSVGPoint, svgToWorld, onGraphChange])

  const handleMouseUp = useCallback((e) => {
    panState.current  = null
    dragNode.current  = null
    wireState.current = null
    setWirePreview(null)
  }, [])

  const handleWheel = useCallback((e) => {
    e.preventDefault()
    const pt = getSVGPoint(e)
    const delta = e.deltaY > 0 ? 0.9 : 1.1
    setViewport((v) => {
      const newScale = Math.max(0.1, Math.min(4, v.scale * delta))
      // Zoom towards cursor
      const sx = pt.x - (pt.x - v.x) * (newScale / v.scale)
      const sy = pt.y - (pt.y - v.y) * (newScale / v.scale)
      return { x: sx, y: sy, scale: newScale }
    })
  }, [getSVGPoint])

  // ── Node interaction ──────────────────────────────────────────────────────

  const handleNodeDragStart = useCallback((nodeId, e) => {
    const pt = getSVGPoint(e)
    const world = svgToWorld(pt.x, pt.y)
    const node = graph.nodes.get(nodeId)
    if (!node) return
    dragNode.current = {
      nodeId,
      startWorldX: world.x,
      startWorldY: world.y,
      origX: node.position.x,
      origY: node.position.y,
    }
  }, [graph, getSVGPoint, svgToWorld])

  const handlePinMouseDown = useCallback((nodeId, pinName, side, e) => {
    if (side !== 'out') return  // only start wires from outputs
    e.stopPropagation()
    const pt = getSVGPoint(e)
    const key = `${nodeId}_${pinName}_out`
    const worldPos = pinPositions.current[key]
    const svgPos = worldPos
      ? { x: worldPos.x * viewport.scale + viewport.x, y: worldPos.y * viewport.scale + viewport.y }
      : pt
    wireState.current = { fromNodeId: nodeId, fromPin: pinName, fromSide: side, fromX: svgPos.x, fromY: svgPos.y }
  }, [getSVGPoint, viewport])

  const handlePinMouseUp = useCallback((nodeId, pinName, side, e) => {
    if (!wireState.current) return
    if (side !== 'in') return  // only land on inputs
    e.stopPropagation()
    const { fromNodeId, fromPin } = wireState.current
    if (fromNodeId === nodeId) { wireState.current = null; setWirePreview(null); return }
    try {
      const newGraph = graph.addConnection(fromNodeId, fromPin, nodeId, pinName)
      onGraphChange(newGraph)
    } catch (err) {
      // Surface type errors briefly in console (keep the UI clean)
      if (err instanceof TypeMismatchError || err instanceof CycleError) {
        console.warn('[NodeScript]', err.message)
      }
    }
    wireState.current = null
    setWirePreview(null)
  }, [graph, onGraphChange])

  // ── Context menu ──────────────────────────────────────────────────────────

  const handleContextMenu = useCallback((nodeId, e) => {
    e.preventDefault()
    const pt = getSVGPoint(e)
    setCtxMenu({ nodeId, x: e.clientX, y: e.clientY })
  }, [getSVGPoint])

  const handleCtxDelete = useCallback(() => {
    if (!ctxMenu) return
    try { onGraphChange(graph.removeNode(ctxMenu.nodeId)) } catch { /* ignore */ }
    if (selectedNodeId === ctxMenu.nodeId) onSelectNode(null)
    setCtxMenu(null)
  }, [ctxMenu, graph, onGraphChange, selectedNodeId, onSelectNode])

  const handleCtxDuplicate = useCallback(() => {
    if (!ctxMenu) return
    const node = graph.nodes.get(ctxMenu.nodeId)
    const def  = getNodeDef(node?.defId)
    if (!node || !def) { setCtxMenu(null); return }
    onGraphChange(graph.addNode(def, { x: node.position.x + 30, y: node.position.y + 30 }, { ...node.params }))
    setCtxMenu(null)
  }, [ctxMenu, graph, onGraphChange])

  const handleCtxDisable = useCallback(() => {
    if (!ctxMenu) return
    onGraphChange(graph.toggleDisabled(ctxMenu.nodeId))
    setCtxMenu(null)
  }, [ctxMenu, graph, onGraphChange])

  // ── Wire preview path ─────────────────────────────────────────────────────

  const wirePreviewPath = wirePreview ? (() => {
    const { fromX, fromY, toX, toY } = wirePreview
    const dx = Math.abs(toX - fromX) * 0.6
    return `M ${fromX},${fromY} C ${fromX + dx},${fromY} ${toX - dx},${toY} ${toX},${toY}`
  })() : null

  // ── Render ────────────────────────────────────────────────────────────────

  const nodes       = [...graph.nodes.values()]
  const connections = [...graph.connections.values()]

  return (
    <div
      style={{ flex: 1, position: 'relative', overflow: 'hidden', background: '#0a0b0d' }}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      {/* Grid background */}
      <svg
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
      >
        <defs>
          <pattern id="grid-small" x={viewport.x % (20 * viewport.scale)} y={viewport.y % (20 * viewport.scale)} width={20 * viewport.scale} height={20 * viewport.scale} patternUnits="userSpaceOnUse">
            <path d={`M ${20 * viewport.scale} 0 L 0 0 0 ${20 * viewport.scale}`} fill="none" stroke="#1a1d24" strokeWidth="0.5" />
          </pattern>
          <pattern id="grid-large" x={viewport.x % (100 * viewport.scale)} y={viewport.y % (100 * viewport.scale)} width={100 * viewport.scale} height={100 * viewport.scale} patternUnits="userSpaceOnUse">
            <path d={`M ${100 * viewport.scale} 0 L 0 0 0 ${100 * viewport.scale}`} fill="none" stroke="#232730" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid-small)" />
        <rect width="100%" height="100%" fill="url(#grid-large)" />
      </svg>

      {/* Main SVG */}
      <svg
        ref={svgRef}
        style={{ width: '100%', height: '100%', display: 'block' }}
        onMouseDown={handleSVGMouseDown}
        onWheel={handleWheel}
        onContextMenu={(e) => e.preventDefault()}
      >
        <g transform={`translate(${viewport.x},${viewport.y}) scale(${viewport.scale})`}>
          {/* Connections */}
          {connections.map((conn) => {
            const fromKey = `${conn.fromNodeId}_${conn.fromPin}_out`
            const toKey   = `${conn.toNodeId}_${conn.toPin}_in`
            const fromPos = pinPositions.current[fromKey]
            const toPos   = pinPositions.current[toKey]
            if (!fromPos || !toPos) return null
            return (
              <Connection
                key={conn.id}
                id={conn.id}
                fromX={fromPos.x}
                fromY={fromPos.y}
                toX={toPos.x}
                toY={toPos.y}
                selected={conn.id === selectedConnId}
                onClick={setSelectedConnId}
              />
            )
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const def = getNodeDef(node.defId)
            return (
              <Node
                key={node.id}
                node={node}
                def={def}
                selected={node.id === selectedNodeId}
                result={results?.[node.id]}
                onSelect={onSelectNode}
                onDragStart={handleNodeDragStart}
                onPinMouseDown={handlePinMouseDown}
                onPinMouseUp={handlePinMouseUp}
                onContextMenu={handleContextMenu}
                registerPinPosition={registerPinPosition}
              />
            )
          })}

          {/* Wire preview (drawn in world space) */}
          {wirePreview && wirePreviewPath && (() => {
            // Convert SVG coords to world coords for the preview path
            const fromWorld = svgToWorld(wirePreview.fromX, wirePreview.fromY)
            const toWorld   = svgToWorld(wirePreview.toX, wirePreview.toY)
            const dx = Math.abs(toWorld.x - fromWorld.x) * 0.6
            const d = `M ${fromWorld.x},${fromWorld.y} C ${fromWorld.x + dx},${fromWorld.y} ${toWorld.x - dx},${toWorld.y} ${toWorld.x},${toWorld.y}`
            return (
              <path
                d={d}
                fill="none"
                stroke="#ffd633"
                strokeWidth={1.5}
                strokeDasharray="5,3"
                strokeOpacity={0.8}
                style={{ pointerEvents: 'none' }}
              />
            )
          })()}
        </g>
      </svg>

      {/* Context menu */}
      {ctxMenu && (
        <div
          style={{
            position: 'fixed',
            left: ctxMenu.x,
            top: ctxMenu.y,
            background: '#14171c',
            border: '1px solid #2d323d',
            borderRadius: 6,
            boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
            zIndex: 100,
            minWidth: 140,
            overflow: 'hidden',
          }}
          onMouseLeave={() => setCtxMenu(null)}
        >
          {[
            { label: 'Duplicate', action: handleCtxDuplicate, color: '#b8bfcc' },
            { label: graph.nodes.get(ctxMenu.nodeId)?.disabled ? 'Enable' : 'Disable', action: handleCtxDisable, color: '#b8bfcc' },
            { label: 'Delete', action: handleCtxDelete, color: '#ef4444' },
          ].map(({ label, action, color }) => (
            <button
              key={label}
              type="button"
              onClick={action}
              style={{
                display: 'block',
                width: '100%',
                background: 'none',
                border: 'none',
                padding: '7px 12px',
                textAlign: 'left',
                fontSize: 12,
                color,
                cursor: 'pointer',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = '#1a1d24' }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'none' }}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {/* Empty state hint */}
      {nodes.length === 0 && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            pointerEvents: 'none',
          }}
        >
          <p style={{ color: '#3a4150', fontSize: 13, textAlign: 'center' }}>
            Click a node in the library to add it to the canvas.<br />
            <span style={{ fontSize: 11 }}>Scroll to zoom · Middle-drag to pan</span>
          </p>
        </div>
      )}
    </div>
  )
}
