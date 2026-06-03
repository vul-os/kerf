/**
 * Node.jsx — single node card rendered on the canvas.
 *
 * Rendered as an SVG foreignObject so we can use HTML/Tailwind inside,
 * while the canvas itself remains SVG for pan/zoom.
 *
 * Props:
 *   node       – { id, defId, label, position, params, disabled }
 *   def        – full node definition from node_library
 *   selected   – bool
 *   result     – last run result for this node (any)
 *   onSelect   – (id) → void
 *   onDragStart– (id, e) → void
 *   onPinMouseDown – (nodeId, pinName, pinSide, e) → void  (start drag-wire)
 *   onPinMouseUp   – (nodeId, pinName, pinSide, e) → void  (end drag-wire)
 *   onContextMenu  – (id, e) → void
 *   pinPositions   – ref map set by this component: { [nodeId_pinName_side]: {x,y} }
 */

import { useRef, useLayoutEffect } from 'react'
import { CATEGORY_COLORS } from './node_library.js'

const NODE_WIDTH  = 180
const PIN_RADIUS  = 5
const HEADER_H    = 28
const ROW_H       = 22
const PADDING     = 8

function pinTypeColor(type) {
  switch (type) {
    case 'number':   return '#6bd4ff'
    case 'vec3':     return '#a78bfa'
    case 'geometry': return '#34d399'
    case 'array':    return '#fb923c'
    default:         return '#9ca3af'
  }
}

export default function Node({
  node,
  def,
  selected,
  result,
  onSelect,
  onDragStart,
  onPinMouseDown,
  onPinMouseUp,
  onContextMenu,
  registerPinPosition,
}) {
  const inputs  = def?.inputs  ?? []
  const outputs = def?.outputs ?? []
  const rows    = Math.max(inputs.length, outputs.length, 1)
  const bodyH   = rows * ROW_H + PADDING * 2
  const totalH  = HEADER_H + bodyH
  const catColor = CATEGORY_COLORS[def?.category] ?? '#6bd4ff'

  const { x, y } = node.position

  // Notify parent of pin world positions after first render
  const groupRef = useRef(null)

  // We compute pin positions based on SVG layout math (no DOM measurement needed)
  // so the canvas can draw wires without layout side-effects.
  const pinPos = {}
  inputs.forEach((pin, i) => {
    const py = y + HEADER_H + PADDING + i * ROW_H + ROW_H / 2
    pinPos[`${node.id}_${pin.name}_in`] = { x, y: py }
  })
  outputs.forEach((pin, i) => {
    const py = y + HEADER_H + PADDING + i * ROW_H + ROW_H / 2
    pinPos[`${node.id}_${pin.name}_out`] = { x: x + NODE_WIDTH, y: py }
  })

  // Push positions to parent map
  if (registerPinPosition) {
    for (const [k, v] of Object.entries(pinPos)) {
      registerPinPosition(k, v)
    }
  }

  const opacity = node.disabled ? 0.4 : 1

  return (
    <g
      ref={groupRef}
      style={{ opacity, cursor: 'grab', userSelect: 'none' }}
      onMouseDown={(e) => {
        if (e.target.classList.contains('pin-hit')) return
        onSelect?.(node.id)
        onDragStart?.(node.id, e)
      }}
      onContextMenu={(e) => {
        e.preventDefault()
        onContextMenu?.(node.id, e)
      }}
    >
      {/* Shadow */}
      {selected && (
        <rect
          x={x - 3}
          y={y - 3}
          width={NODE_WIDTH + 6}
          height={totalH + 6}
          rx={8}
          fill="none"
          stroke={catColor}
          strokeWidth={2}
          strokeOpacity={0.6}
          style={{ pointerEvents: 'none' }}
        />
      )}

      {/* Body */}
      <rect
        x={x}
        y={y}
        width={NODE_WIDTH}
        height={totalH}
        rx={6}
        fill="#1a1d24"
        stroke={selected ? catColor : '#2d323d'}
        strokeWidth={selected ? 1.5 : 1}
      />

      {/* Header */}
      <rect
        x={x}
        y={y}
        width={NODE_WIDTH}
        height={HEADER_H}
        rx={6}
        fill={catColor + '22'}
        style={{ pointerEvents: 'none' }}
      />
      {/* Header bottom clip (square bottom corners) */}
      <rect
        x={x}
        y={y + HEADER_H - 6}
        width={NODE_WIDTH}
        height={6}
        fill={catColor + '22'}
        style={{ pointerEvents: 'none' }}
      />
      {/* Category stripe */}
      <rect
        x={x}
        y={y}
        width={4}
        height={HEADER_H}
        rx={3}
        fill={catColor}
        style={{ pointerEvents: 'none' }}
      />

      {/* Header label */}
      <text
        x={x + 12}
        y={y + HEADER_H / 2 + 1}
        fill={catColor}
        fontSize={11}
        fontWeight="600"
        fontFamily="var(--font-sans)"
        dominantBaseline="middle"
        style={{ pointerEvents: 'none' }}
      >
        {node.label}
      </text>

      {/* Disabled badge */}
      {node.disabled && (
        <text
          x={x + NODE_WIDTH - 6}
          y={y + HEADER_H / 2 + 1}
          fill="#9ca3af"
          fontSize={9}
          textAnchor="end"
          dominantBaseline="middle"
          style={{ pointerEvents: 'none' }}
        >
          OFF
        </text>
      )}

      {/* Input pins */}
      {inputs.map((pin, i) => {
        const py = y + HEADER_H + PADDING + i * ROW_H + ROW_H / 2
        const pColor = pinTypeColor(pin.type)
        return (
          <g key={pin.name}>
            <circle
              className="pin-hit"
              cx={x}
              cy={py}
              r={PIN_RADIUS + 4}
              fill="transparent"
              onMouseDown={(e) => { e.stopPropagation(); onPinMouseDown?.(node.id, pin.name, 'in', e) }}
              onMouseUp={(e)   => { e.stopPropagation(); onPinMouseUp?.(node.id, pin.name, 'in', e) }}
              style={{ cursor: 'crosshair' }}
            />
            <circle cx={x} cy={py} r={PIN_RADIUS} fill={pColor} stroke="#0f1115" strokeWidth={1.5} style={{ pointerEvents: 'none' }} />
            <text
              x={x + PIN_RADIUS + 5}
              y={py}
              fill="#8a93a6"
              fontSize={10}
              dominantBaseline="middle"
              style={{ pointerEvents: 'none' }}
            >
              {pin.name}
            </text>
          </g>
        )
      })}

      {/* Output pins */}
      {outputs.map((pin, i) => {
        const py = y + HEADER_H + PADDING + i * ROW_H + ROW_H / 2
        const pColor = pinTypeColor(pin.type)
        return (
          <g key={pin.name}>
            <circle
              className="pin-hit"
              cx={x + NODE_WIDTH}
              cy={py}
              r={PIN_RADIUS + 4}
              fill="transparent"
              onMouseDown={(e) => { e.stopPropagation(); onPinMouseDown?.(node.id, pin.name, 'out', e) }}
              onMouseUp={(e)   => { e.stopPropagation(); onPinMouseUp?.(node.id, pin.name, 'out', e) }}
              style={{ cursor: 'crosshair' }}
            />
            <circle cx={x + NODE_WIDTH} cy={py} r={PIN_RADIUS} fill={pColor} stroke="#0f1115" strokeWidth={1.5} style={{ pointerEvents: 'none' }} />
            <text
              x={x + NODE_WIDTH - PIN_RADIUS - 5}
              y={py}
              fill="#8a93a6"
              fontSize={10}
              textAnchor="end"
              dominantBaseline="middle"
              style={{ pointerEvents: 'none' }}
            >
              {pin.name}
            </text>
          </g>
        )
      })}

      {/* Result badge */}
      {result !== undefined && result !== null && (
        <text
          x={x + NODE_WIDTH / 2}
          y={y + totalH - 5}
          fill="#5a6275"
          fontSize={9}
          textAnchor="middle"
          style={{ pointerEvents: 'none' }}
        >
          {typeof result === 'object'
            ? (result.deferred ? '⏳ deferred' : result.error ? '⚠ error' : '✓')
            : String(result).slice(0, 16)}
        </text>
      )}
    </g>
  )
}

export { NODE_WIDTH, HEADER_H, ROW_H, PADDING, PIN_RADIUS }
