// RatsnestLayer — SVG overlay that draws MST airwires for unrouted nets.
//
// Renders one <line> per MST edge returned by `computeRatsnest(circuitJson)`.
// Lines are drawn in a net-coloured or uniform style, classed so the parent
// canvas can control visibility via CSS.
//
// Props
// -----
// circuitJson  : AnyCircuitElement[]  — flat CircuitJSON array (from tscircuit)
// viewBox      : [minX, minY, width, height]  — SVG viewBox of the parent canvas
// visible      : bool  (default true)  — hide layer without unmounting
// strokeWidth  : number  (default 0.1)  — line weight in SVG/board units (mm)
// color        : string  (default '#00d9ff')  — uniform stroke colour
// opacity      : number  (default 0.75)
//
// TODO: wire this component into PCBView (or a parent CircuitCanvas wrapper)
//       by importing and mounting it as a sibling of the main SVG content,
//       inside the pan/zoom <g> transform group, passing the same viewBox
//       and circuitJson that PCBView already uses.
//
// See circuitCanvasTypes.ts's header comment for why `extractPadsByNet` reads pads through
// the loose `PadLike` shape rather than the real `CircuitElement` — `net_id`/`net`/`net_name`
// don't exist on circuit-json's actual `PcbSmtPad`/`PcbPlatedHole` types.

import { useMemo } from 'react'
import type {
  PadLike, PcbPoint, RatsnestPad, RatsnestMstEdge, RatsnestEdge,
} from './circuitCanvasTypes'

export interface Props {
  circuitJson?: PadLike[]
  viewBox?: [number, number, number, number] | null
  visible?: boolean
  strokeWidth?: number
  color?: string
  opacity?: number
}

// ---------------------------------------------------------------------------
// Pure MST computation (mirrors ratsnest.py — pure JS, no Python dependency).
// The Python module is the authoritative backend; this JS copy is used for
// live preview only and must stay in sync with the Python algorithm.
// ---------------------------------------------------------------------------

function dist(a: PcbPoint, b: PcbPoint): number {
  return Math.hypot(b.x - a.x, b.y - a.y)
}

/** Prim's MST over a list of {x, y, padId} objects. */
function computeNetMST(pads: RatsnestPad[]): RatsnestMstEdge[] {
  const n = pads.length
  if (n < 2) return []

  const inTree = new Array<boolean>(n).fill(false)
  const minDist = new Array<number>(n).fill(Infinity)
  const parent = new Array<number>(n).fill(-1)
  minDist[0] = 0

  const edges: RatsnestMstEdge[] = []

  for (let step = 0; step < n; step++) {
    // Pick minimum-distance out-of-tree node
    let u = -1
    let best = Infinity
    for (let i = 0; i < n; i++) {
      if (!inTree[i] && minDist[i] < best) {
        best = minDist[i]
        u = i
      }
    }
    if (u === -1) break

    inTree[u] = true

    if (parent[u] !== -1) {
      edges.push({
        from: pads[parent[u]],
        to: pads[u],
        lengthMm: dist(pads[parent[u]], pads[u]),
      })
    }

    for (let v = 0; v < n; v++) {
      if (!inTree[v]) {
        const d = dist(pads[u], pads[v])
        if (d < minDist[v]) {
          minDist[v] = d
          parent[v] = u
        }
      }
    }
  }

  return edges
}

const PAD_TYPES = new Set(['pcb_smtpad', 'pcb_plated_hole'])

/** Extract pads grouped by net from a flat CircuitJSON array. */
function extractPadsByNet(circuitJson: PadLike[]): Map<string, RatsnestPad[]> {
  const nets = new Map<string, RatsnestPad[]>()
  let serial = 0
  for (const elem of circuitJson) {
    if (!elem?.type || !PAD_TYPES.has(elem.type)) continue
    const netId = elem.net_id || elem.net || elem.net_name
    if (!netId) continue
    const x = elem.x
    const y = elem.y
    if (x == null || y == null) continue
    const padId =
      elem.pcb_smtpad_id ||
      elem.pcb_plated_hole_id ||
      elem.id ||
      `pad_${serial++}`
    if (!nets.has(netId)) nets.set(netId, [])
    nets.get(netId)!.push({ x: Number(x), y: Number(y), padId: String(padId) })
  }
  return nets
}

/** Compute all MST ratsnest edges from a flat CircuitJSON array. */
// Pre-existing: this file exports a non-component alongside the default component export,
// which breaks Vite Fast Refresh for this module; not a behavior change for this slice.
// eslint-disable-next-line react-refresh/only-export-components
export function computeRatsnest(circuitJson: PadLike[]): RatsnestEdge[] {
  if (!Array.isArray(circuitJson)) return []
  const padsByNet = extractPadsByNet(circuitJson)
  const result: RatsnestEdge[] = []
  for (const [netId, pads] of padsByNet) {
    for (const edge of computeNetMST(pads)) {
      result.push({ netId, ...edge })
    }
  }
  return result
}

// ---------------------------------------------------------------------------
// React component
// ---------------------------------------------------------------------------

export default function RatsnestLayer({
  circuitJson,
  viewBox: _viewBox = null,
  visible = true,
  strokeWidth = 0.1,
  color = '#00d9ff',
  opacity = 0.75,
}: Props) {
  const edges = useMemo(
    () => (visible && Array.isArray(circuitJson) ? computeRatsnest(circuitJson) : []),
    [circuitJson, visible],
  )

  if (!visible || edges.length === 0) return null

  // When embedded inside a parent SVG this component renders a <g> group.
  // The parent is responsible for applying the pan/zoom transform to this
  // group (or to a common ancestor).
  return (
    <g
      className="ratsnest-layer"
      style={{ pointerEvents: 'none' }}
      data-edge-count={edges.length}
    >
      {edges.map((edge, idx) => (
        <line
          key={idx}
          x1={edge.from.x}
          y1={edge.from.y}
          x2={edge.to.x}
          y2={edge.to.y}
          stroke={color}
          strokeWidth={strokeWidth}
          strokeOpacity={opacity}
          strokeDasharray={`${strokeWidth * 3} ${strokeWidth * 2}`}
          className="ratsnest-edge"
          data-net-id={edge.netId}
        />
      ))}
    </g>
  )
}
