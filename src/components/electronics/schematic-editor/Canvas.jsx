// Canvas.jsx — SVG schematic drawing surface.
//
// Coordinate space: mils (1/1000 inch). ViewBox: 1600×1000 mil. Grid: 25 mil.
//
// Renders:
//   • Grid (25 mil dots/lines)
//   • Placed parts with SVG symbols
//   • Wires (orthogonal poly-lines)
//   • Part pin circles (for connection snapping)
//   • Wire preview during wire mode
//   • Selection highlight
//   • Probe labels
//
// Props:
//   devices         [{id, partId, x, y, props, label}]
//   wires           [{id, points:[{x,y}]}]
//   activeTool      'select'|'wire'|'add'|'probe'|'delete'
//   addingPartId    part type currently being placed (string|null)
//   selectedId      id of selected object (or null)
//   onSelectObject  (id, type) => void
//   onAddDevice     ({partId, x, y}) => void
//   onWireCommit    ([{x,y}]) => void
//   onDeleteObject  (id, type) => void
//   onAddProbe      ({x,y,netLabel}) => void

import { useCallback, useRef, useState } from 'react'
import { PARTS_MAP, GRID, VW, VH } from './parts_library.js'
import { routeWire } from './wire_router.js'

// ── helpers ───────────────────────────────────────────────────────────────────

function snapToGrid(v) {
  return Math.round(v / GRID) * GRID
}

function svgPoint(svgEl, clientX, clientY) {
  const pt = svgEl.createSVGPoint()
  pt.x = clientX
  pt.y = clientY
  const ctm = svgEl.getScreenCTM()
  if (!ctm) return { x: clientX, y: clientY }
  const pt2 = pt.matrixTransform(ctm.inverse())
  return { x: pt2.x, y: pt2.y }
}

// ── Grid ──────────────────────────────────────────────────────────────────────

function Grid() {
  const dots = []
  for (let x = 0; x <= VW; x += GRID) {
    for (let y = 0; y <= VH; y += GRID) {
      dots.push(
        <circle
          key={`${x}-${y}`}
          cx={x}
          cy={y}
          r={x % 100 === 0 && y % 100 === 0 ? 1.5 : 0.8}
          fill={x % 100 === 0 && y % 100 === 0 ? '#334155' : '#1e293b'}
        />
      )
    }
  }
  return <g>{dots}</g>
}

// ── Arc path helper ───────────────────────────────────────────────────────────

function arcPath(a) {
  const { cx, cy, r, a1 = 0, a2 = 180 } = a
  const toRad = (d) => (d * Math.PI) / 180
  const x1 = cx + r * Math.cos(toRad(a1))
  const y1 = cy + r * Math.sin(toRad(a1))
  const x2 = cx + r * Math.cos(toRad(a2))
  const y2 = cy + r * Math.sin(toRad(a2))
  const largeArc = Math.abs(a2 - a1) > 180 ? 1 : 0
  return `M${x1},${y1} A${r},${r} 0 ${largeArc} 1 ${x2},${y2}`
}

// ── Part symbol ───────────────────────────────────────────────────────────────

function PartSymbol({ dev, partDef, selected, onClick, activeTool }) {
  const { symbol } = partDef
  const isDelete = activeTool === 'delete'

  return (
    <g
      transform={`translate(${dev.x},${dev.y})`}
      onClick={onClick}
      style={{ cursor: isDelete ? 'crosshair' : 'pointer' }}
      data-testid={`device-${dev.id}`}
    >
      {/* Selection halo */}
      {selected && (
        <rect
          x={-55} y={-55} width={110} height={110}
          rx={6}
          fill="none"
          stroke="#818cf8"
          strokeWidth={2}
          strokeDasharray="4 2"
          opacity={0.8}
        />
      )}

      {/* Symbol strokes */}
      <g
        stroke={selected ? '#a5b4fc' : '#7dd3fc'}
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {symbol.lines?.map(([x1, y1, x2, y2], i) => (
          <line key={`l${i}`} x1={x1} y1={y1} x2={x2} y2={y2} />
        ))}
        {symbol.arcs?.map((a, i) => (
          <path key={`a${i}`} d={arcPath(a)} />
        ))}
        {symbol.circles?.map((c, i) => (
          <circle
            key={`c${i}`}
            cx={c.cx}
            cy={c.cy}
            r={c.r}
            stroke={selected ? '#a5b4fc' : '#7dd3fc'}
            fill={c.fill !== undefined ? c.fill : 'none'}
          />
        ))}
      </g>

      {/* Pin connection dots */}
      {partDef.pins.map((pin) => (
        <circle
          key={pin.id}
          cx={pin.dx}
          cy={pin.dy}
          r={4}
          fill="#1e3a5f"
          stroke="#38bdf8"
          strokeWidth={1}
        />
      ))}

      {/* Label */}
      <text
        x={0}
        y={58}
        textAnchor="middle"
        fontSize={14}
        fill={selected ? '#a5b4fc' : '#94a3b8'}
        fontFamily="monospace"
      >
        {dev.label}
      </text>
    </g>
  )
}

// ── Wire ──────────────────────────────────────────────────────────────────────

function WireElement({ wire, selected, onClick, activeTool }) {
  if (!wire.points?.length) return null
  const pts = wire.points.map((p) => `${p.x},${p.y}`).join(' ')
  const isDelete = activeTool === 'delete'

  return (
    <g onClick={onClick} style={{ cursor: isDelete ? 'crosshair' : 'pointer' }} data-testid={`wire-${wire.id}`}>
      {/* Fat invisible hit area */}
      <polyline
        points={pts}
        fill="none"
        stroke="transparent"
        strokeWidth={12}
      />
      <polyline
        points={pts}
        fill="none"
        stroke={selected ? '#818cf8' : '#38bdf8'}
        strokeWidth={selected ? 2.5 : 1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </g>
  )
}

// ── Ghost (placement preview) ─────────────────────────────────────────────────

function GhostPart({ partId, x, y }) {
  const partDef = PARTS_MAP[partId]
  if (!partDef) return null
  const { symbol } = partDef

  return (
    <g transform={`translate(${x},${y})`} opacity={0.5} pointerEvents="none">
      <g stroke="#a5b4fc" strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round">
        {symbol.lines?.map(([x1, y1, x2, y2], i) => (
          <line key={`l${i}`} x1={x1} y1={y1} x2={x2} y2={y2} />
        ))}
        {symbol.arcs?.map((a, i) => (
          <path key={`a${i}`} d={arcPath(a)} />
        ))}
        {symbol.circles?.map((c, i) => (
          <circle key={`c${i}`} cx={c.cx} cy={c.cy} r={c.r} stroke="#a5b4fc" fill="none" />
        ))}
      </g>
    </g>
  )
}

// ── Main Canvas component ─────────────────────────────────────────────────────

export default function Canvas({
  devices = [],
  wires = [],
  activeTool,
  addingPartId,
  selectedId,
  onSelectObject,
  onAddDevice,
  onWireCommit,
  onDeleteObject,
  onAddProbe,
}) {
  const svgRef = useRef(null)
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })
  const [wirePoints, setWirePoints] = useState([])   // points accumulated in wire mode

  // ── Pointer helpers ──────────────────────────────────────────────────────

  const getSnapped = useCallback((e) => {
    if (!svgRef.current) return { x: 0, y: 0 }
    const raw = svgPoint(svgRef.current, e.clientX, e.clientY)
    return { x: snapToGrid(raw.x), y: snapToGrid(raw.y) }
  }, [])

  // ── Mouse move — update cursor ghost ────────────────────────────────────

  const handleMouseMove = useCallback((e) => {
    const p = getSnapped(e)
    setMousePos(p)
  }, [getSnapped])

  // ── Click on canvas background ────────────────────────────────────────

  const handleBgClick = useCallback((e) => {
    if (e.defaultPrevented) return
    const p = getSnapped(e)

    if (activeTool === 'add' && addingPartId) {
      onAddDevice?.({ partId: addingPartId, x: p.x, y: p.y })
      return
    }

    if (activeTool === 'wire') {
      if (wirePoints.length === 0) {
        // First click — start wire
        setWirePoints([p])
      } else {
        // Subsequent click — add elbow/finish
        const last = wirePoints[wirePoints.length - 1]
        const routed = routeWire(last, p)
        // routed[0] === last, so merge
        const next = [...wirePoints, ...routed.slice(1)]
        setWirePoints(next)
      }
      return
    }

    if (activeTool === 'probe') {
      onAddProbe?.({ x: p.x, y: p.y, netLabel: `N${p.x}_${p.y}` })
      return
    }

    // Deselect when clicking background
    onSelectObject?.(null, null)
  }, [activeTool, addingPartId, wirePoints, onAddDevice, onWireCommit, onSelectObject, onAddProbe, getSnapped])

  // ── Double-click finishes wire ────────────────────────────────────────

  const handleDblClick = useCallback((e) => {
    if (activeTool !== 'wire' || wirePoints.length < 2) return
    e.preventDefault()
    onWireCommit?.(wirePoints)
    setWirePoints([])
  }, [activeTool, wirePoints, onWireCommit])

  // ── Escape during wire mode ────────────────────────────────────────────
  // (handled in parent via keydown; also cancel on Escape here)

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') setWirePoints([])
  }, [])

  // ── Wire preview (rubber-band) ─────────────────────────────────────────

  let previewPts = null
  if (activeTool === 'wire' && wirePoints.length > 0) {
    const last = wirePoints[wirePoints.length - 1]
    const routed = routeWire(last, mousePos)
    previewPts = [...wirePoints, ...routed.slice(1)]
  }

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${VW} ${VH}`}
      className="w-full h-full block bg-[#0d1929]"
      style={{ cursor: activeTool === 'delete' ? 'crosshair' : activeTool === 'wire' ? 'crosshair' : 'default' }}
      onMouseMove={handleMouseMove}
      onClick={handleBgClick}
      onDoubleClick={handleDblClick}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      data-testid="schematic-canvas"
    >
      {/* Background grid */}
      <Grid />

      {/* Wires */}
      {wires.map((wire) => (
        <WireElement
          key={wire.id}
          wire={wire}
          selected={selectedId === wire.id}
          activeTool={activeTool}
          onClick={(e) => {
            e.preventDefault()
            if (activeTool === 'delete') {
              onDeleteObject?.(wire.id, 'wire')
            } else {
              onSelectObject?.(wire.id, 'wire')
            }
          }}
        />
      ))}

      {/* Placed parts */}
      {devices.map((dev) => {
        const partDef = PARTS_MAP[dev.partId]
        if (!partDef) return null
        return (
          <PartSymbol
            key={dev.id}
            dev={dev}
            partDef={partDef}
            selected={selectedId === dev.id}
            activeTool={activeTool}
            onClick={(e) => {
              e.preventDefault()
              if (activeTool === 'delete') {
                onDeleteObject?.(dev.id, 'part')
              } else {
                onSelectObject?.(dev.id, 'part')
              }
            }}
          />
        )
      })}

      {/* Wire preview rubber-band */}
      {previewPts && (
        <polyline
          points={previewPts.map((p) => `${p.x},${p.y}`).join(' ')}
          fill="none"
          stroke="#38bdf8"
          strokeWidth={1.5}
          strokeDasharray="6 3"
          strokeLinecap="round"
          opacity={0.7}
          pointerEvents="none"
        />
      )}

      {/* Ghost part while adding */}
      {activeTool === 'add' && addingPartId && (
        <GhostPart partId={addingPartId} x={mousePos.x} y={mousePos.y} />
      )}

      {/* Crosshair cursor overlay */}
      {(activeTool === 'wire' || activeTool === 'add') && (
        <g pointerEvents="none">
          <line x1={mousePos.x - 12} y1={mousePos.y} x2={mousePos.x + 12} y2={mousePos.y} stroke="#475569" strokeWidth={1} />
          <line x1={mousePos.x} y1={mousePos.y - 12} x2={mousePos.x} y2={mousePos.y + 12} stroke="#475569" strokeWidth={1} />
        </g>
      )}
    </svg>
  )
}
