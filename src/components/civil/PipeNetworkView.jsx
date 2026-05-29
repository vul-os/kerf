/**
 * PipeNetworkView.jsx — 2-D plan view of a pressurised/gravity pipe network.
 *
 * Renders nodes (manholes, junctions, reservoirs) and edges (pipes) in SVG.
 * Clicking a pipe edge opens an inline inspector showing hydraulic results.
 * A "Run network solve" button dispatches `civil_water_network_solve` via
 * POST /api/tools/call and overlays the flow / pressure results.
 *
 * Props
 * ─────
 *   nodes       {Array<{id, x, y, elevation_m?, demand_m3s?, type?}>}
 *                 type: 'junction' | 'reservoir' | 'manhole'
 *   pipes       {Array<{id, node_a, node_b, length_m?, diameter_m?, roughness?,
 *                        slope?, manning_n?}>}
 *   reservoirs  {Array<{id, head_m, x, y}>}   Fixed-head sources.
 *   formula     {'HW'|'DW'}    Head-loss formula (default 'HW').
 *   results     {object}       Pre-computed solve results (optional).
 *   width       {number}       SVG canvas width  (default 600).
 *   height      {number}       SVG canvas height (default 420).
 *   className   {string}
 *   onDispatch  {function}     Called with { tool, params } instead of fetch.
 */

import { useMemo, useState } from 'react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

const NODE_R = 10
const RESERVOIR_R = 14
const PADDING = 50

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fitCoords(allPts, width, height) {
  if (!allPts.length) return { scale: 1, offX: 0, offY: 0 }
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const [x, y] of allPts) {
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  }
  const rangeX = maxX - minX || 1
  const rangeY = maxY - minY || 1
  const usableW = width - PADDING * 2
  const usableH = height - PADDING * 2
  const scale = Math.min(usableW / rangeX, usableH / rangeY)
  const scaledW = rangeX * scale
  const scaledH = rangeY * scale
  return {
    scale,
    offX: PADDING + (usableW - scaledW) / 2 - minX * scale,
    offY: PADDING + (usableH - scaledH) / 2 - minY * scale,
  }
}

function nodeColour(type, pressure) {
  if (type === 'reservoir') return '#38bdf8'
  if (typeof pressure === 'number') {
    if (pressure < 5) return '#f87171'
    if (pressure < 15) return '#fbbf24'
    return '#4ade80'
  }
  return '#64748b'
}

function flowToStrokeWidth(flow) {
  if (!flow && flow !== 0) return 2
  const abs = Math.abs(flow)
  return Math.max(1.5, Math.min(6, abs * 800 + 1.5))
}

function formatFlow(v) {
  if (v == null) return '—'
  return `${(v * 1000).toFixed(2)} L/s`
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function NodeSymbol({ node, x, y, pressure }) {
  const isRes = node.type === 'reservoir'
  const fill = nodeColour(node.type, pressure)
  return (
    <g transform={`translate(${x},${y})`} aria-label={`Node ${node.id}`}>
      {isRes ? (
        <>
          <circle r={RESERVOIR_R} fill={fill} stroke="#cbd5e1" strokeWidth="1.5" />
          {/* tank symbol */}
          <rect x={-6} y={-4} width={12} height={8} fill="none" stroke="white" strokeWidth="1" />
          <line x1={-6} y1={0} x2={6} y2={0} stroke="white" strokeWidth="1" />
        </>
      ) : (
        <circle r={NODE_R} fill={fill} stroke="#cbd5e1" strokeWidth="1.5" />
      )}
      <text
        textAnchor="middle"
        y={isRes ? RESERVOIR_R + 12 : NODE_R + 11}
        fontSize="9"
        fill="#94a3b8"
        fontFamily="monospace"
      >
        {node.id.length > 8 ? node.id.slice(0, 8) + '…' : node.id}
      </text>
      {typeof pressure === 'number' && (
        <text
          textAnchor="middle"
          y={isRes ? RESERVOIR_R + 21 : NODE_R + 20}
          fontSize="8"
          fill="#64748b"
          fontFamily="monospace"
        >
          {pressure.toFixed(1)} m
        </text>
      )}
    </g>
  )
}

function PipeEdge({ pipe, x1, y1, x2, y2, flow, selected, onClick }) {
  const w = flowToStrokeWidth(flow)
  const positive = flow == null || flow >= 0
  const stroke = selected ? '#f59e0b' : (flow == null ? '#475569' : '#60a5fa')

  // Direction arrow midpoint
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  const dx = (positive ? x2 - x1 : x1 - x2)
  const dy = (positive ? y2 - y1 : y1 - y2)
  const len = Math.sqrt(dx * dx + dy * dy) || 1
  const ux = dx / len, uy = dy / len
  const arrowSize = 6

  return (
    <g
      style={{ cursor: 'pointer' }}
      onClick={onClick}
      aria-label={`Pipe ${pipe.id}`}
      data-testid={`pipe-${pipe.id}`}
    >
      {/* Wide invisible hit area */}
      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke="transparent"
        strokeWidth="12"
      />
      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={stroke}
        strokeWidth={w}
        opacity={0.85}
      />
      {/* Arrow */}
      {flow != null && (
        <polygon
          points={`
            ${mx + ux * arrowSize},${my + uy * arrowSize}
            ${mx - ux * arrowSize - uy * arrowSize * 0.6},${my - uy * arrowSize + ux * arrowSize * 0.6}
            ${mx - ux * arrowSize + uy * arrowSize * 0.6},${my - uy * arrowSize - ux * arrowSize * 0.6}
          `}
          fill={stroke}
          opacity="0.8"
        />
      )}
    </g>
  )
}

// ---------------------------------------------------------------------------
// Inspector panel
// ---------------------------------------------------------------------------

function PipeInspector({ pipe, flow, onClose }) {
  if (!pipe) return null
  return (
    <div
      className="absolute top-2 right-2 bg-slate-900 border border-slate-700 rounded-lg p-3 text-xs font-mono text-slate-300 shadow-xl min-w-[180px]"
      data-testid="pipe-inspector"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-slate-100 font-semibold">{pipe.id}</span>
        <button
          onClick={onClose}
          className="text-slate-500 hover:text-slate-300 ml-2"
          aria-label="Close inspector"
        >
          ✕
        </button>
      </div>
      <table className="w-full border-separate" style={{ borderSpacing: '0 2px' }}>
        <tbody>
          <tr>
            <td className="text-slate-500 pr-2">Flow</td>
            <td>{formatFlow(flow)}</td>
          </tr>
          {pipe.length_m != null && (
            <tr>
              <td className="text-slate-500 pr-2">Length</td>
              <td>{pipe.length_m.toFixed(1)} m</td>
            </tr>
          )}
          {pipe.diameter_m != null && (
            <tr>
              <td className="text-slate-500 pr-2">Diameter</td>
              <td>{(pipe.diameter_m * 1000).toFixed(0)} mm</td>
            </tr>
          )}
          {pipe.slope != null && (
            <tr>
              <td className="text-slate-500 pr-2">Slope</td>
              <td>{(pipe.slope * 1000).toFixed(2)} ‰</td>
            </tr>
          )}
          {pipe.manning_n != null && (
            <tr>
              <td className="text-slate-500 pr-2">Manning n</td>
              <td>{pipe.manning_n}</td>
            </tr>
          )}
          {pipe.roughness != null && (
            <tr>
              <td className="text-slate-500 pr-2">Roughness</td>
              <td>{pipe.roughness}</td>
            </tr>
          )}
          {flow != null && (
            <tr>
              <td className="text-slate-500 pr-2">Direction</td>
              <td>{flow >= 0 ? `${pipe.node_a}→${pipe.node_b}` : `${pipe.node_b}→${pipe.node_a}`}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function PipeNetworkView({
  nodes = [],
  pipes = [],
  reservoirs = [],
  formula = 'HW',
  results: propResults = null,
  width = 600,
  height = 420,
  className = '',
  onDispatch,
}) {
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState(propResults)
  const [error, setError] = useState(null)
  const [selectedPipe, setSelectedPipe] = useState(null)

  // Merge reservoirs into node list for layout
  const allNodes = useMemo(() => [
    ...nodes,
    ...reservoirs.map(r => ({ ...r, type: 'reservoir' })),
  ], [nodes, reservoirs])

  // Compute screen coordinates
  const { scale, offX, offY } = useMemo(() => {
    const pts = allNodes.filter(n => n.x != null && n.y != null).map(n => [n.x, n.y])
    return fitCoords(pts, width, height)
  }, [allNodes, width, height])

  const posMap = useMemo(() => {
    const m = {}
    for (const n of allNodes) {
      if (n.x != null && n.y != null) {
        m[n.id] = [n.x * scale + offX, n.y * scale + offY]
      }
    }
    return m
  }, [allNodes, scale, offX, offY])

  // Extract result maps
  const flowMap = results?.pipe_flows_m3s || {}
  const pressureMap = results?.nodal_pressures_m || {}

  // ── Dispatch ───────────────────────────────────────────────────────────────
  async function handleSolve() {
    setLoading(true)
    setError(null)
    const params = {
      nodes: nodes.map(n => ({
        id: n.id,
        elevation_m: n.elevation_m ?? 0,
        demand_m3s: n.demand_m3s ?? 0,
      })),
      reservoirs: reservoirs.map(r => ({ id: r.id, head_m: r.head_m ?? 30 })),
      pipes: pipes.map(p => ({
        id: p.id,
        node_a: p.node_a,
        node_b: p.node_b,
        length_m: p.length_m ?? 100,
        diameter_m: p.diameter_m ?? 0.2,
        roughness: p.roughness ?? 130,
      })),
      formula,
    }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'civil_water_network_solve', params })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'civil_water_network_solve', params }),
        })
        const data = await res.json()
        setResults(data)
      }
    } catch (e) {
      setError(e.message || 'Solve failed')
    } finally {
      setLoading(false)
    }
  }

  const selPipeObj = pipes.find(p => p.id === selectedPipe) ||
    reservoirs.find(r => r.id === selectedPipe) || null

  const isEmpty = allNodes.length === 0

  return (
    <div
      className={`flex flex-col gap-2 ${className}`}
      data-testid="pipe-network-view"
    >
      {/* Toolbar */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-slate-500 font-medium tracking-wide uppercase">
          Pipe Network
        </span>
        <div className="flex items-center gap-2">
          {results?.converged != null && (
            <span className={`text-xs font-mono ${results.converged ? 'text-green-400' : 'text-yellow-400'}`}>
              {results.converged ? `Converged (${results.iterations} iter)` : 'Not converged'}
            </span>
          )}
          <button
            className="text-xs px-3 py-1 rounded bg-kerf-700 hover:bg-kerf-600 text-white disabled:opacity-50 transition-colors"
            onClick={handleSolve}
            disabled={loading || isEmpty}
            data-testid="pipe-solve-btn"
          >
            {loading ? 'Solving…' : 'Run network solve'}
          </button>
        </div>
      </div>

      {/* SVG canvas */}
      <div className="relative">
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="rounded border border-slate-800"
          style={{ background: '#0f172a' }}
          aria-label="Pipe network plan view"
          role="img"
        >
          {isEmpty ? (
            <text
              x={width / 2}
              y={height / 2}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize="14"
              fill="#475569"
              fontFamily="system-ui, sans-serif"
            >
              No network data — pass nodes + pipes props
            </text>
          ) : (
            <>
              {/* Grid background */}
              <defs>
                <pattern id="pipeGrid" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" strokeWidth="0.5" />
                </pattern>
              </defs>
              <rect width={width} height={height} fill="url(#pipeGrid)" />

              {/* Pipe edges */}
              <g aria-label="Pipes">
                {pipes.map(pipe => {
                  const posA = posMap[pipe.node_a]
                  const posB = posMap[pipe.node_b]
                  if (!posA || !posB) return null
                  return (
                    <PipeEdge
                      key={pipe.id}
                      pipe={pipe}
                      x1={posA[0]}
                      y1={posA[1]}
                      x2={posB[0]}
                      y2={posB[1]}
                      flow={flowMap[pipe.id]}
                      selected={selectedPipe === pipe.id}
                      onClick={() => setSelectedPipe(selectedPipe === pipe.id ? null : pipe.id)}
                    />
                  )
                })}
              </g>

              {/* Nodes */}
              <g aria-label="Nodes">
                {allNodes.map(node => {
                  const pos = posMap[node.id]
                  if (!pos) return null
                  return (
                    <NodeSymbol
                      key={node.id}
                      node={node}
                      x={pos[0]}
                      y={pos[1]}
                      pressure={pressureMap[node.id]}
                    />
                  )
                })}
              </g>

              {/* Legend */}
              <g transform={`translate(${width - 120}, 12)`} aria-label="Legend">
                <rect x="0" y="0" width="110" height="56" rx="4" fill="#1e293b" opacity="0.9" />
                <circle cx="12" cy="12" r="6" fill="#4ade80" />
                <text x="22" y="16" fontSize="9" fill="#94a3b8" fontFamily="monospace">p≥15 m OK</text>
                <circle cx="12" cy="28" r="6" fill="#fbbf24" />
                <text x="22" y="32" fontSize="9" fill="#94a3b8" fontFamily="monospace">5&lt;p&lt;15 m</text>
                <circle cx="12" cy="44" r="6" fill="#f87171" />
                <text x="22" y="48" fontSize="9" fill="#94a3b8" fontFamily="monospace">p&lt;5 m low</text>
              </g>
            </>
          )}
        </svg>

        {/* Pipe inspector overlay */}
        {selectedPipe && (
          <PipeInspector
            pipe={selPipeObj}
            flow={flowMap[selectedPipe]}
            onClose={() => setSelectedPipe(null)}
          />
        )}
      </div>

      {error && (
        <div className="text-xs text-red-400 px-1">{error}</div>
      )}
    </div>
  )
}
