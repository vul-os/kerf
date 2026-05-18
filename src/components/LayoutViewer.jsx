/**
 * LayoutViewer.jsx — In-browser IC layout viewer (KLayout-style).
 *
 * TODO (parent-side wiring): Parse a GDS-II file via T-237 (gdsLoader.js /
 * the backend route from T-238's routes_layout.py) and pass the resulting
 * shape tree as the `layout` prop.  Expected shape:
 *
 *   {
 *     cells: [
 *       {
 *         name: "top",
 *         shapes: [
 *           { kind: 'box',     layer: 68, x, y, w, h },
 *           { kind: 'polygon', layer: 66, points: [{ x, y }, …] },
 *           { kind: 'path',    layer: 67, points: [{ x, y }, …], width },
 *           { kind: 'text',    layer: 83, x, y, label, size },
 *           { kind: 'ref',     cell: "child_cell_name", shapes: […] },
 *         ],
 *       },
 *       …
 *     ],
 *     topCell: "top",
 *   }
 *
 * Props:
 *   layout    {object|null}  Parsed layout tree (see above). null → placeholder.
 *   pdk       {'sky130'|'gf180'|null}  Which palette to use.
 *   className {string}       Extra CSS classes for the outer container.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { renderLayout, fitBounds, worldToScreen, screenToWorld } from '../lib/layoutCanvas.js'
import { sky130Palette, gf180Palette, getPaletteColor, defaultLayerColor } from '../lib/layoutPalette.js'

// ── Constants ─────────────────────────────────────────────────────────────────

const ZOOM_FACTOR      = 1.12   // per wheel-tick
const MIN_ZOOM         = 1e-6
const MAX_ZOOM         = 1e6
const INITIAL_VIEW     = { offsetX: 0, offsetY: 0, zoom: 1 }

// ── View reducer ─────────────────────────────────────────────────────────────

function viewReducer(state, action) {
  switch (action.type) {
    case 'SET': return action.view
    case 'PAN': return {
      ...state,
      offsetX: state.offsetX + action.dx,
      offsetY: state.offsetY + action.dy,
    }
    case 'ZOOM_TO': {
      // Zoom centred on a screen point (px, py)
      const { factor, px, py } = action
      const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, state.zoom * factor))
      const scale   = newZoom / state.zoom
      return {
        zoom:    newZoom,
        offsetX: px - scale * (px - state.offsetX),
        offsetY: py - scale * (py - state.offsetY),
      }
    }
    default: return state
  }
}

// ── Layer visibility helpers ──────────────────────────────────────────────────

/**
 * Extract every unique layer id from a flat list of shapes (recursive).
 * Returns a sorted array of layer ids (numbers or strings).
 */
function collectLayers(shapes) {
  const ids = new Set()
  function visit(s) {
    if (!s) return
    if (s.layer != null) ids.add(s.layer)
    if (s.kind === 'ref' && Array.isArray(s.shapes)) s.shapes.forEach(visit)
  }
  shapes.forEach(visit)
  return [...ids].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
}

/**
 * Resolve the top-cell shape list from a parsed layout tree.
 */
function resolveTopShapes(layout) {
  if (!layout) return []
  const topName = layout.topCell
  const cells   = layout.cells ?? []
  const top     = topName ? cells.find(c => c.name === topName) : cells[0]
  return top ? (top.shapes ?? []) : []
}

// ── LayersPanel ───────────────────────────────────────────────────────────────

function LayersPanel({ layers, visible, palette, onToggle, onToggleAll }) {
  return (
    <div
      style={{
        width: 200,
        overflowY: 'auto',
        background: '#1a1f2a',
        borderLeft: '1px solid #2d3348',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
      }}
    >
      <div style={{ padding: '8px 10px', borderBottom: '1px solid #2d3348', display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ color: '#aab4cc', fontSize: 11, fontWeight: 600, letterSpacing: '0.05em', flex: 1 }}>LAYERS</span>
        <button
          onClick={() => onToggleAll(true)}
          style={{ fontSize: 10, color: '#4fd1c5', background: 'none', border: 'none', cursor: 'pointer', padding: '1px 4px' }}
        >all</button>
        <button
          onClick={() => onToggleAll(false)}
          style={{ fontSize: 10, color: '#4fd1c5', background: 'none', border: 'none', cursor: 'pointer', padding: '1px 4px' }}
        >none</button>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
        {layers.length === 0 && (
          <div style={{ color: '#5a6478', fontSize: 11, padding: '8px 10px' }}>No layers</div>
        )}
        {layers.map(lid => {
          const colors = (palette ? getPaletteColor(palette, typeof lid === 'number' ? { layerNum: lid, datatype: 0 } : lid) : null) ?? defaultLayerColor
          const isVisible = visible.has(lid)
          return (
            <div
              key={lid}
              onClick={() => onToggle(lid)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '3px 10px',
                cursor: 'pointer',
                opacity: isVisible ? 1 : 0.4,
                userSelect: 'none',
              }}
            >
              {/* colour swatch */}
              <div style={{
                width: 12,
                height: 12,
                borderRadius: 2,
                background: colors.fill,
                border: `1.5px solid ${colors.stroke}`,
                flexShrink: 0,
              }} />
              <span style={{ color: '#c8d3e8', fontSize: 11, fontFamily: 'monospace' }}>
                {String(lid)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Toolbar ───────────────────────────────────────────────────────────────────

function Toolbar({ onFit, showLayers, onToggleLayers }) {
  return (
    <div style={{
      height: 36,
      background: '#141820',
      borderBottom: '1px solid #2d3348',
      display: 'flex',
      alignItems: 'center',
      gap: 4,
      padding: '0 8px',
      flexShrink: 0,
    }}>
      <button
        onClick={onFit}
        title="Fit to window (F)"
        style={btnStyle}
      >
        Fit
      </button>
      <div style={{ width: 1, height: 20, background: '#2d3348', margin: '0 4px' }} />
      <button
        onClick={onToggleLayers}
        title="Toggle layers panel"
        style={{ ...btnStyle, background: showLayers ? '#2d3a5a' : 'transparent' }}
      >
        Layers
      </button>
      <div style={{ flex: 1 }} />
      <span style={{ color: '#5a6478', fontSize: 10, fontFamily: 'monospace' }}>
        scroll=zoom  drag=pan
      </span>
    </div>
  )
}

const btnStyle = {
  background: 'transparent',
  border: 'none',
  color: '#aab4cc',
  fontSize: 12,
  padding: '2px 8px',
  borderRadius: 4,
  cursor: 'pointer',
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function LayoutViewer({ layout = null, pdk = null, className = '' }) {
  const canvasRef = useRef(null)
  const [view, dispatchView]     = useReducer(viewReducer, INITIAL_VIEW)
  const [showLayers, setShowLayers] = useState(true)
  const [, forceRender]          = useReducer(x => x + 1, 0)

  // Drag state (not React state — avoids re-render on every mousemove)
  const dragRef = useRef(null) // { startX, startY, startOffsetX, startOffsetY }

  // Resolved shape list
  const shapes = useMemo(() => resolveTopShapes(layout), [layout])

  // All unique layer ids
  const layers = useMemo(() => collectLayers(shapes), [shapes])

  // Visible-layer set — starts with all visible
  const visibleRef = useRef(new Set())
  const [visibleGeneration, tickVisible] = useReducer(x => x + 1, 0)

  // When layer list changes re-initialise visibility
  useEffect(() => {
    visibleRef.current = new Set(layers)
    tickVisible()
  }, [layers])

  // Snapshot of visible set (derived from ref + generation counter)
  const visibleLayers = visibleRef.current

  // Choose palette
  const palette = useMemo(() => {
    if (pdk === 'gf180') return gf180Palette
    if (pdk === 'sky130') return sky130Palette
    // Auto-detect: if the layout has a pdk hint, use it; otherwise default sky130
    return sky130Palette
  }, [pdk])

  // Build layerColors Map for the renderer
  const layerColors = useMemo(() => {
    const m = new Map()
    for (const lid of layers) {
      const c = getPaletteColor(
        palette,
        typeof lid === 'number' ? { layerNum: lid, datatype: 0 } : lid,
      ) ?? defaultLayerColor
      m.set(lid, c)
    }
    return m
  }, [layers, palette])

  // ── Fit to window ─────────────────────────────────────────────────────────

  const fitToWindow = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || shapes.length === 0) return
    const v = fitBounds(shapes, { width: canvas.width, height: canvas.height })
    dispatchView({ type: 'SET', view: v })
  }, [shapes])

  // Fit whenever the shape list changes
  useEffect(() => {
    fitToWindow()
  }, [fitToWindow])

  // ── Draw loop ─────────────────────────────────────────────────────────────

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    if (shapes.length === 0) {
      ctx.fillStyle = '#0e1118'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.fillStyle = '#3a4460'
      ctx.font = '13px monospace'
      ctx.textAlign = 'center'
      ctx.fillText('No layout loaded', canvas.width / 2, canvas.height / 2)
      ctx.textAlign = 'left'
      return
    }

    ctx.fillStyle = '#0e1118'
    ctx.fillRect(0, 0, canvas.width, canvas.height)

    renderLayout(ctx, shapes, layerColors, view, visibleLayers)
  }, [view, shapes, layerColors, visibleLayers, visibleGeneration])

  // ── Canvas resize observer ────────────────────────────────────────────────

  const containerRef = useRef(null)

  useEffect(() => {
    const container = containerRef.current
    const canvas    = canvasRef.current
    if (!container || !canvas) return
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        canvas.width  = Math.max(1, Math.round(width))
        canvas.height = Math.max(1, Math.round(height))
        // Re-fit after resize
        if (shapes.length > 0) {
          const v = fitBounds(shapes, { width: canvas.width, height: canvas.height })
          dispatchView({ type: 'SET', view: v })
        }
        forceRender()
      }
    })
    ro.observe(container)
    return () => ro.disconnect()
  }, [shapes])

  // ── Pointer events ────────────────────────────────────────────────────────

  const onMouseDown = useCallback(e => {
    // Left mouse button or any button (middle-mouse drag)
    if (e.button === 0 || e.button === 1) {
      e.preventDefault()
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startOffsetX: view.offsetX,
        startOffsetY: view.offsetY,
      }
    }
  }, [view.offsetX, view.offsetY])

  const onMouseMove = useCallback(e => {
    if (!dragRef.current) return
    const dx = e.clientX - dragRef.current.startX
    const dy = e.clientY - dragRef.current.startY
    dispatchView({
      type: 'SET',
      view: {
        ...view,
        offsetX: dragRef.current.startOffsetX + dx,
        offsetY: dragRef.current.startOffsetY + dy,
      },
    })
  }, [view])

  const onMouseUp = useCallback(() => {
    dragRef.current = null
  }, [])

  const onWheel = useCallback(e => {
    e.preventDefault()
    const rect   = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const px = e.clientX - rect.left
    const py = e.clientY - rect.top
    const factor = e.deltaY < 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR
    dispatchView({ type: 'ZOOM_TO', factor, px, py })
  }, [])

  const onKeyDown = useCallback(e => {
    if (e.key === 'f' || e.key === 'F') fitToWindow()
  }, [fitToWindow])

  // ── Layer toggles ─────────────────────────────────────────────────────────

  const handleToggleLayer = useCallback(lid => {
    const s = visibleRef.current
    if (s.has(lid)) s.delete(lid)
    else s.add(lid)
    tickVisible()
  }, [])

  const handleToggleAll = useCallback(show => {
    if (show) visibleRef.current = new Set(layers)
    else visibleRef.current = new Set()
    tickVisible()
  }, [layers])

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      className={className}
      style={{
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        height: '100%',
        background: '#0e1118',
        overflow: 'hidden',
        outline: 'none',
      }}
      tabIndex={0}
      onKeyDown={onKeyDown}
    >
      <Toolbar
        onFit={fitToWindow}
        showLayers={showLayers}
        onToggleLayers={() => setShowLayers(v => !v)}
      />

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Canvas area */}
        <div
          ref={containerRef}
          style={{ flex: 1, position: 'relative', overflow: 'hidden', cursor: dragRef.current ? 'grabbing' : 'crosshair' }}
        >
          <canvas
            ref={canvasRef}
            style={{ display: 'block', width: '100%', height: '100%' }}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
            onWheel={onWheel}
          />
        </div>

        {/* Layers panel */}
        {showLayers && (
          <LayersPanel
            layers={layers}
            visible={visibleLayers}
            palette={palette}
            onToggle={handleToggleLayer}
            onToggleAll={handleToggleAll}
          />
        )}
      </div>
    </div>
  )
}
