// Canvas.jsx — SVG PCB canvas.
//
// Coordinate space: mil units (1/1000 inch). Viewbox 1200×800 mil.
// Grid: 25mil.
//
// Renders:
//   • Grid (25mil)
//   • Pads  (circles, coloured by layer)
//   • Traces (polylines, coloured by layer)
//   • Drill holes (small black circles)
//   • Keepout zones (dashed rectangles)
//   • Route preview while routing
//   • Push-shove highlight when dragging
//
// Props:
//   pads           — [{id, x, y, layer, net, drill, size}]
//   traces         — [{id, points:[{x,y}], layer, width, net}]
//   keepouts       — [{id, x, y, w, h}]
//   activeTool     — 'select'|'route'|'push-shove'|'delete'
//   activeLayer    — 'top'|'bottom'|'inner1'|'inner2'
//   selectedId     — id of selected object
//   onSelectObject — (id, type) => void
//   onRouteCommit  — ({start_pad, end_pad, layer, width}) => void
//   onShoveCommit  — ({trace_id, push_vector}) => void
//   onDeleteObject — (id, type) => void
//   pushedTraceIds — [id]  — traces currently being shoved (highlighted)

import { useCallback, useRef, useState } from 'react'

// ─── constants ────────────────────────────────────────────────────────────────

const VIEW_W = 1200
const VIEW_H = 800
const GRID   = 25   // mil
const TRACE_DEFAULT_WIDTH = 10  // mil

const LAYER_COLOR = {
  top:    '#ef4444',
  bottom: '#3b82f6',
  inner1: '#f59e0b',
  inner2: '#8b5cf6',
}

const LAYER_OPACITY = {
  top:    1,
  bottom: 0.7,
  inner1: 0.85,
  inner2: 0.8,
}

// ─── helpers ──────────────────────────────────────────────────────────────────

function snapToGrid(v) {
  return Math.round(v / GRID) * GRID
}

function svgPoint(svgEl, clientX, clientY) {
  const pt = svgEl.createSVGPoint()
  pt.x = clientX
  pt.y = clientY
  const ctm = svgEl.getScreenCTM()
  if (!ctm) return { x: clientX, y: clientY }
  const inv = ctm.inverse()
  const transformed = pt.matrixTransform(inv)
  return { x: transformed.x, y: transformed.y }
}

// ─── Grid ─────────────────────────────────────────────────────────────────────

function Grid() {
  const lines = []
  for (let x = 0; x <= VIEW_W; x += GRID) {
    lines.push(
      <line key={`vx${x}`} x1={x} y1={0} x2={x} y2={VIEW_H}
        stroke="#ffffff" strokeWidth={x % 100 === 0 ? 0.5 : 0.2} opacity={x % 100 === 0 ? 0.15 : 0.06} />
    )
  }
  for (let y = 0; y <= VIEW_H; y += GRID) {
    lines.push(
      <line key={`hy${y}`} x1={0} y1={y} x2={VIEW_W} y2={y}
        stroke="#ffffff" strokeWidth={y % 100 === 0 ? 0.5 : 0.2} opacity={y % 100 === 0 ? 0.15 : 0.06} />
    )
  }
  return <g data-layer="grid">{lines}</g>
}

// ─── Board outline ─────────────────────────────────────────────────────────────

function BoardOutline() {
  return (
    <rect x={50} y={50} width={VIEW_W - 100} height={VIEW_H - 100}
      fill="none" stroke="#22c55e" strokeWidth={2} strokeDasharray="8,4" opacity={0.5} />
  )
}

// ─── Keepout ──────────────────────────────────────────────────────────────────

function Keepouts({ keepouts }) {
  return (
    <g data-layer="keepout">
      {keepouts.map((k) => (
        <rect key={k.id} x={k.x} y={k.y} width={k.w} height={k.h}
          fill="#f59e0b08" stroke="#f59e0b" strokeWidth={1.5}
          strokeDasharray="6,3" opacity={0.7} />
      ))}
    </g>
  )
}

// ─── Traces ───────────────────────────────────────────────────────────────────

function Traces({ traces, activeLayer, selectedId, pushedTraceIds, onSelect }) {
  return (
    <g data-layer="traces">
      {traces.map((tr) => {
        const pts = tr.points.map((p) => `${p.x},${p.y}`).join(' ')
        const color = LAYER_COLOR[tr.layer] ?? '#888'
        const opacity = LAYER_OPACITY[tr.layer] ?? 0.8
        const isSelected = selectedId === tr.id
        const isPushed = pushedTraceIds?.includes(tr.id)
        return (
          <polyline
            key={tr.id}
            data-id={tr.id}
            data-type="trace"
            points={pts}
            fill="none"
            stroke={isPushed ? '#facc15' : isSelected ? '#ffffff' : color}
            strokeWidth={tr.width ?? TRACE_DEFAULT_WIDTH}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={isPushed ? 1 : isSelected ? 1 : opacity}
            style={{ cursor: 'pointer' }}
            onClick={(e) => { e.stopPropagation(); onSelect(tr.id, 'trace') }}
          />
        )
      })}
    </g>
  )
}

// ─── Pads ─────────────────────────────────────────────────────────────────────

function Pads({ pads, activeLayer, selectedId, routingFromId, onSelect }) {
  return (
    <g data-layer="pads">
      {pads.map((pad) => {
        const color = LAYER_COLOR[pad.layer] ?? '#888'
        const r = (pad.size ?? 20) / 2
        const isSelected = selectedId === pad.id
        const isRouteSource = routingFromId === pad.id
        return (
          <g key={pad.id} data-id={pad.id} data-type="pad"
            style={{ cursor: 'pointer' }}
            onClick={(e) => { e.stopPropagation(); onSelect(pad.id, 'pad') }}>
            {/* Pad copper ring */}
            <circle
              cx={pad.x} cy={pad.y} r={r}
              fill={color + '55'}
              stroke={isRouteSource ? '#ffffff' : isSelected ? '#facc15' : color}
              strokeWidth={isRouteSource || isSelected ? 2.5 : 1.5}
            />
            {/* Drill hole */}
            {pad.drill > 0 && (
              <circle cx={pad.x} cy={pad.y} r={pad.drill / 2}
                fill="#0f172a" stroke="#1e293b" strokeWidth={0.5} />
            )}
            {/* Net label */}
            {pad.net && (
              <text x={pad.x} y={pad.y - r - 4} textAnchor="middle"
                fill="#94a3b8" fontSize={8}>{pad.net}</text>
            )}
          </g>
        )
      })}
    </g>
  )
}

// ─── Route preview ────────────────────────────────────────────────────────────

function RoutePreview({ from, cursor, layer }) {
  if (!from || !cursor) return null
  const color = LAYER_COLOR[layer] ?? '#888'
  return (
    <g data-layer="route-preview">
      <line
        x1={from.x} y1={from.y} x2={cursor.x} y2={cursor.y}
        stroke={color} strokeWidth={TRACE_DEFAULT_WIDTH}
        strokeDasharray="15,8" opacity={0.7} strokeLinecap="round" />
      <circle cx={cursor.x} cy={cursor.y} r={6}
        fill={color + '44'} stroke={color} strokeWidth={1.5} />
    </g>
  )
}

// ─── ShovePreview ─────────────────────────────────────────────────────────────

function ShovePreview({ shoveTrace, dx, dy }) {
  if (!shoveTrace || (dx === 0 && dy === 0)) return null
  const pts = shoveTrace.points.map((p) => `${p.x + dx},${p.y + dy}`).join(' ')
  return (
    <polyline points={pts} fill="none"
      stroke="#facc15" strokeWidth={shoveTrace.width ?? TRACE_DEFAULT_WIDTH}
      strokeLinecap="round" strokeLinejoin="round" opacity={0.85}
      strokeDasharray="12,6" />
  )
}

// ─── Main Canvas ─────────────────────────────────────────────────────────────

export default function Canvas({
  pads = [],
  traces = [],
  keepouts = [],
  activeTool,
  activeLayer,
  selectedId,
  onSelectObject,
  onRouteCommit,
  onShoveCommit,
  onDeleteObject,
  pushedTraceIds = [],
}) {
  const svgRef = useRef(null)
  const [cursor, setCursor] = useState(null)     // snapped cursor position
  const [routingFrom, setRoutingFrom] = useState(null)   // {id, x, y}
  const [shoveState, setShoveState] = useState(null)     // {trace, startPt}
  const [shoveDelta, setShoveDelta] = useState({ dx: 0, dy: 0 })

  // ── pointer helpers ─────────────────────────────────────────────────────────

  const getSvgPos = useCallback((e) => {
    if (!svgRef.current) return { x: 0, y: 0 }
    const raw = svgPoint(svgRef.current, e.clientX, e.clientY)
    return { x: snapToGrid(raw.x), y: snapToGrid(raw.y) }
  }, [])

  // ── pointer move ────────────────────────────────────────────────────────────

  const handleMouseMove = useCallback((e) => {
    const pos = getSvgPos(e)
    setCursor(pos)

    if (activeTool === 'push-shove' && shoveState) {
      const dx = pos.x - shoveState.startPt.x
      const dy = pos.y - shoveState.startPt.y
      setShoveDelta({ dx, dy })
    }
  }, [activeTool, shoveState, getSvgPos])

  // ── click on background ─────────────────────────────────────────────────────

  const handleBgClick = useCallback((e) => {
    if (activeTool === 'route' && routingFrom) {
      // cancel routing if clicking on empty space
      setRoutingFrom(null)
    } else {
      onSelectObject && onSelectObject(null, null)
    }
  }, [activeTool, routingFrom, onSelectObject])

  // ── pad / trace click ───────────────────────────────────────────────────────

  const handleObjectSelect = useCallback((id, type) => {
    if (activeTool === 'delete') {
      onDeleteObject && onDeleteObject(id, type)
      return
    }

    if (activeTool === 'route') {
      if (type === 'pad') {
        if (!routingFrom) {
          // Start routing from this pad
          const pad = pads.find((p) => p.id === id)
          if (pad) setRoutingFrom({ id, x: pad.x, y: pad.y })
        } else {
          // Complete route to this pad
          if (id !== routingFrom.id) {
            onRouteCommit && onRouteCommit({
              start_pad: routingFrom.id,
              end_pad: id,
              layer: activeLayer,
              width: TRACE_DEFAULT_WIDTH,
            })
          }
          setRoutingFrom(null)
        }
      }
      return
    }

    if (activeTool === 'push-shove') {
      if (type === 'trace') {
        const tr = traces.find((t) => t.id === id)
        if (tr) {
          setShoveState({ trace: tr, startPt: cursor ?? { x: 0, y: 0 } })
          setShoveDelta({ dx: 0, dy: 0 })
        }
      }
      return
    }

    // select mode
    onSelectObject && onSelectObject(id, type)
  }, [activeTool, routingFrom, pads, traces, cursor, activeLayer, onRouteCommit, onDeleteObject, onSelectObject])

  // ── pointer up (commit shove) ────────────────────────────────────────────────

  const handleMouseUp = useCallback(() => {
    if (activeTool === 'push-shove' && shoveState) {
      const { dx, dy } = shoveDelta
      if (Math.abs(dx) > GRID || Math.abs(dy) > GRID) {
        onShoveCommit && onShoveCommit({
          trace_id: shoveState.trace.id,
          push_vector: [dx, dy],
        })
      }
      setShoveState(null)
      setShoveDelta({ dx: 0, dy: 0 })
    }
  }, [activeTool, shoveState, shoveDelta, onShoveCommit])

  // ── cursor style ────────────────────────────────────────────────────────────

  const cursorStyle = {
    select:       'default',
    route:        'crosshair',
    'push-shove': 'grab',
    delete:       'not-allowed',
  }[activeTool] ?? 'default'

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      width="100%"
      height="100%"
      style={{ cursor: cursorStyle, display: 'block', background: '#0f172a' }}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onClick={handleBgClick}
    >
      <Grid />
      <BoardOutline />
      <Keepouts keepouts={keepouts} />
      <Traces
        traces={traces}
        activeLayer={activeLayer}
        selectedId={selectedId}
        pushedTraceIds={pushedTraceIds}
        onSelect={handleObjectSelect}
      />
      <Pads
        pads={pads}
        activeLayer={activeLayer}
        selectedId={selectedId}
        routingFromId={routingFrom?.id}
        onSelect={handleObjectSelect}
      />
      {activeTool === 'route' && routingFrom && (
        <RoutePreview from={routingFrom} cursor={cursor} layer={activeLayer} />
      )}
      {activeTool === 'push-shove' && shoveState && (
        <ShovePreview
          shoveTrace={shoveState.trace}
          dx={shoveDelta.dx}
          dy={shoveDelta.dy}
        />
      )}
      {/* Crosshair cursor dot */}
      {cursor && activeTool !== 'select' && (
        <circle cx={cursor.x} cy={cursor.y} r={3}
          fill="none" stroke="#94a3b8" strokeWidth={1} opacity={0.6} />
      )}
    </svg>
  )
}
