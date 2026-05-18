// ThermalNetworkViewer.jsx — SVG graph visualisation for a thermal network.
//
// Renders nodes as temperature-coloured bubbles and links as directed arrows
// showing heat-flux direction.  Layout is computed by a force-directed
// simulation (thermalNetworkLayout.js).
//
// Props
// ─────
//   network {Object}
//     .nodes  {Array<{id, label?, temperature_K?}>}
//     .links  {Array<{from_id, to_id, type?, flux_W?, natural_length?}>}
//
//   width    {number}  — SVG viewport width  (default 600)
//   height   {number}  — SVG viewport height (default 400)
//   padding  {number}  — padding around layout bounding box (default 40)
//   iterations {number} — force-simulation iterations (default 150)
//   className {string} — extra CSS classes on the <svg> root
//
// The component is pure — it never triggers side-effects after mount (no
// requestAnimationFrame loop; layout runs once in useMemo).

import { useMemo } from 'react'
import { layoutNodes, temperatureToRgb } from '../lib/thermalNetworkLayout.js'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NODE_RADIUS   = 28          // bubble radius in SVG pixels
const ARROW_OFFSET  = NODE_RADIUS + 6  // start/end arrow clear of bubble edge
const ARROW_HEAD_ID = 'kerf-thermal-arrow'

// Default temperature range when no temperature data is present
const DEFAULT_T_MIN = 273.15  // 0 °C
const DEFAULT_T_MAX = 373.15  // 100 °C

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function rgbStr({ r, g, b }) {
  return `rgb(${r},${g},${b})`
}

/**
 * Clamp-map node positions into the given SVG viewport, preserving aspect
 * ratio and centring the layout.
 *
 * @param {{ [id]: {x, y} }} rawPos — positions from layoutNodes
 * @param {number} width
 * @param {number} height
 * @param {number} padding
 * @returns {{ [id]: {x, y} }}
 */
function fitPositions(rawPos, width, height, padding) {
  const ids = Object.keys(rawPos)
  if (ids.length === 0) return rawPos

  let minX =  Infinity, minY =  Infinity
  let maxX = -Infinity, maxY = -Infinity
  for (const id of ids) {
    const { x, y } = rawPos[id]
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  }

  const usableW = width  - padding * 2
  const usableH = height - padding * 2
  const rangeX  = maxX - minX || 1
  const rangeY  = maxY - minY || 1
  const scale   = Math.min(usableW / rangeX, usableH / rangeY)

  const scaledW  = rangeX * scale
  const scaledH  = rangeY * scale
  const offsetX  = padding + (usableW - scaledW) / 2
  const offsetY  = padding + (usableH - scaledH) / 2

  const result = {}
  for (const id of ids) {
    result[id] = {
      x: offsetX + (rawPos[id].x - minX) * scale,
      y: offsetY + (rawPos[id].y - minY) * scale,
    }
  }
  return result
}

/**
 * Given two centre points and a node radius offset, compute the arrow shaft
 * endpoints (pulled back from each node's circumference).
 */
function arrowEndpoints(x1, y1, x2, y2, offset) {
  const dx = x2 - x1
  const dy = y2 - y1
  const dist = Math.sqrt(dx * dx + dy * dy) || 1
  const ux = dx / dist
  const uy = dy / dist
  return {
    x1: x1 + ux * offset,
    y1: y1 + uy * offset,
    x2: x2 - ux * offset,
    y2: y2 - uy * offset,
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ArrowMarkerDef({ id }) {
  return (
    <defs>
      <marker
        id={id}
        markerWidth="8"
        markerHeight="6"
        refX="6"
        refY="3"
        orient="auto"
      >
        <path d="M0,0 L8,3 L0,6 Z" fill="#94a3b8" />
      </marker>
    </defs>
  )
}

function LinkArrow({ link, positions }) {
  const pA = positions[link.from_id]
  const pB = positions[link.to_id]
  if (!pA || !pB) return null

  const ep = arrowEndpoints(pA.x, pA.y, pB.x, pB.y, ARROW_OFFSET)

  // Radiative links rendered as dashed; conductive as solid
  const isRadiative = link.type === 'radiative'
  const strokeDash  = isRadiative ? '6 4' : undefined

  // Optional flux label at the midpoint
  const mx = (ep.x1 + ep.x2) / 2
  const my = (ep.y1 + ep.y2) / 2
  const fluxLabel = typeof link.flux_W === 'number'
    ? `${link.flux_W.toFixed(1)} W`
    : null

  return (
    <g role="img" aria-label={`Link from ${link.from_id} to ${link.to_id}`}>
      <line
        x1={ep.x1}
        y1={ep.y1}
        x2={ep.x2}
        y2={ep.y2}
        stroke="#94a3b8"
        strokeWidth={isRadiative ? 1.5 : 2}
        strokeDasharray={strokeDash}
        markerEnd={`url(#${ARROW_HEAD_ID})`}
      />
      {fluxLabel && (
        <text
          x={mx}
          y={my - 6}
          textAnchor="middle"
          fontSize="10"
          fill="#64748b"
          fontFamily="monospace"
        >
          {fluxLabel}
        </text>
      )}
    </g>
  )
}

function NodeBubble({ node, position, tMin, tMax }) {
  const temp = typeof node.temperature_K === 'number'
    ? node.temperature_K
    : (tMin + tMax) / 2

  const colour = rgbStr(temperatureToRgb(temp, tMin, tMax))
  const label  = node.label ?? node.id
  const tempLabel = typeof node.temperature_K === 'number'
    ? `${(node.temperature_K - 273.15).toFixed(1)} °C`
    : null

  return (
    <g
      role="img"
      aria-label={`Node ${label}${tempLabel ? `, ${tempLabel}` : ''}`}
      transform={`translate(${position.x},${position.y})`}
    >
      {/* Drop shadow */}
      <circle
        r={NODE_RADIUS + 2}
        fill="rgba(0,0,0,0.15)"
        cx={2}
        cy={2}
      />
      {/* Colour bubble */}
      <circle
        r={NODE_RADIUS}
        fill={colour}
        stroke="white"
        strokeWidth={2}
      />
      {/* Node label */}
      <text
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="11"
        fontWeight="600"
        fill="white"
        fontFamily="system-ui, sans-serif"
        style={{ textShadow: '0 1px 2px rgba(0,0,0,0.6)' }}
      >
        {label.length > 6 ? label.slice(0, 6) + '…' : label}
      </text>
      {/* Temperature sub-label */}
      {tempLabel && (
        <text
          y={NODE_RADIUS + 13}
          textAnchor="middle"
          fontSize="9"
          fill="#475569"
          fontFamily="monospace"
        >
          {tempLabel}
        </text>
      )}
    </g>
  )
}

// ---------------------------------------------------------------------------
// ThermalNetworkViewer (default export)
// ---------------------------------------------------------------------------

/**
 * ThermalNetworkViewer
 *
 * SVG graph of a thermal network.  Nodes are coloured by temperature (blue =
 * cool, red = hot).  Links are drawn as directed arrows — solid for conductive
 * links, dashed for radiative.  An optional flux label is shown on each link
 * when `flux_W` is present.
 *
 * @param {{ network, width?, height?, padding?, iterations?, className? }} props
 */
export default function ThermalNetworkViewer({
  network,
  width      = 600,
  height     = 400,
  padding    = 40,
  iterations = 150,
  className  = '',
}) {
  const nodes = network?.nodes ?? []
  const links = network?.links ?? []

  // Compute temperature range for colour mapping
  const { tMin, tMax } = useMemo(() => {
    const temps = nodes
      .filter(n => typeof n.temperature_K === 'number')
      .map(n => n.temperature_K)
    if (temps.length === 0) return { tMin: DEFAULT_T_MIN, tMax: DEFAULT_T_MAX }
    const mn = Math.min(...temps)
    const mx = Math.max(...temps)
    // If all nodes have same temperature, add small range so colour is defined
    return { tMin: mn, tMax: mx === mn ? mn + 1 : mx }
  }, [nodes])

  // Run force-directed layout (deterministic, runs once per nodes/links change)
  const positions = useMemo(() => {
    if (nodes.length === 0) return {}
    const rawPos = layoutNodes(nodes, links, iterations)
    return fitPositions(rawPos, width, height, padding)
  }, [nodes, links, iterations, width, height, padding])

  if (nodes.length === 0) {
    return (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className={className}
        aria-label="Thermal network (empty)"
        role="img"
      >
        <text
          x={width / 2}
          y={height / 2}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize="14"
          fill="#94a3b8"
          fontFamily="system-ui, sans-serif"
        >
          No nodes
        </text>
      </svg>
    )
  }

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      aria-label="Thermal network graph"
      role="img"
    >
      <ArrowMarkerDef id={ARROW_HEAD_ID} />

      {/* Background */}
      <rect width={width} height={height} fill="#f8fafc" rx={8} />

      {/* Links layer (drawn below nodes) */}
      <g aria-label="Links">
        {links.map((link, i) => (
          <LinkArrow
            key={`${link.from_id}-${link.to_id}-${i}`}
            link={link}
            positions={positions}
          />
        ))}
      </g>

      {/* Nodes layer */}
      <g aria-label="Nodes">
        {nodes.map(node => {
          const pos = positions[node.id]
          if (!pos) return null
          return (
            <NodeBubble
              key={node.id}
              node={node}
              position={pos}
              tMin={tMin}
              tMax={tMax}
            />
          )
        })}
      </g>
    </svg>
  )
}
