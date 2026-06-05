/**
 * DryUtilityNetworkPanel.jsx — plan + corridor-section view for dry-utility
 * networks (gas mains, electrical duct banks, telecom/fiber ducts).
 *
 * Features
 * ────────
 *   • Plan SVG: nodes (manholes/handholes/valves) + links coloured by kind
 *     (gas=orange, electrical=yellow, telecom=cyan)
 *   • Violations panel: lists all clearance/separation violations from the
 *     civil_dry_utility_clearance_check tool
 *   • Section view: schematic cross-section showing utility positions at
 *     a given station (corridor_offset_m vs depth)
 *   • Toolbar: "Check clearances" button dispatches LLM tool
 *
 * Props
 * ─────
 *   nodes       {Array<{id,x,y,z_surface_m,node_type?}>}
 *   links       {Array<{id,node_from,node_to,length_m,depth_of_cover_m,
 *                        corridor_offset_m,wet_utility_offset_m?,asset}>}
 *                 asset: {kind:'gas'|'electrical'|'telecom', ...}
 *   violations  {Array}   Pre-computed violations (optional).
 *   width       {number}  Plan SVG width (default 600)
 *   height      {number}  Plan SVG height (default 360)
 *   className   {string}
 *   onDispatch  {function} Called with {tool,params} instead of fetch.
 */

import { useMemo, useState } from 'react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ── Colour palette by utility kind ──────────────────────────────────────────
const KIND_COLOUR = {
  gas:        '#f97316',  // orange
  electrical: '#eab308',  // yellow
  telecom:    '#22d3ee',  // cyan
}
const KIND_LABEL = {
  gas:        'Gas',
  electrical: 'Electrical',
  telecom:    'Telecom',
}
const NODE_TYPE_SHAPE = {
  manhole:    'circle',
  handhole:   'square',
  valve:      'diamond',
  regulator:  'diamond',
  splice:     'circle',
}

const PADDING = 48
const NODE_R = 8

// ── Helpers ──────────────────────────────────────────────────────────────────

function fitCoords(pts, w, h) {
  if (!pts.length) return { scale: 1, offX: 0, offY: 0 }
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const [x, y] of pts) {
    if (x < minX) minX = x; if (x > maxX) maxX = x
    if (y < minY) minY = y; if (y > maxY) maxY = y
  }
  const rX = maxX - minX || 1
  const rY = maxY - minY || 1
  const uw = w - PADDING * 2
  const uh = h - PADDING * 2
  const scale = Math.min(uw / rX, uh / rY)
  return {
    scale,
    offX: PADDING + (uw - rX * scale) / 2 - minX * scale,
    offY: PADDING + (uh - rY * scale) / 2 - minY * scale,
  }
}

function violationSeverityColour(vtype) {
  if (vtype === 'cover_depth')           return '#f87171'  // red
  if (vtype === 'inter_utility_separation') return '#fb923c' // orange
  if (vtype === 'wet_utility_separation')  return '#facc15'  // yellow
  return '#94a3b8'
}

// ── Node symbol ─────────────────────────────────────────────────────────────

function NodeSymbol({ node, x, y }) {
  const shape = NODE_TYPE_SHAPE[node.node_type] || 'circle'
  const fill = '#334155'
  const stroke = '#94a3b8'
  const r = NODE_R
  return (
    <g transform={`translate(${x},${y})`} aria-label={`Node ${node.id}`}>
      {shape === 'circle' && (
        <circle r={r} fill={fill} stroke={stroke} strokeWidth="1.5" />
      )}
      {shape === 'square' && (
        <rect x={-r} y={-r} width={r * 2} height={r * 2} fill={fill} stroke={stroke} strokeWidth="1.5" />
      )}
      {shape === 'diamond' && (
        <polygon
          points={`0,${-r} ${r},0 0,${r} ${-r},0`}
          fill={fill}
          stroke={stroke}
          strokeWidth="1.5"
        />
      )}
      <text
        textAnchor="middle"
        y={r + 10}
        fontSize="8"
        fill="#94a3b8"
        fontFamily="monospace"
      >
        {node.id.length > 8 ? node.id.slice(0, 8) + '…' : node.id}
      </text>
    </g>
  )
}

// ── Link edge ─────────────────────────────────────────────────────────────────

function UtilityLinkEdge({ link, x1, y1, x2, y2, selected, onClick }) {
  const colour = KIND_COLOUR[link.asset?.kind] || '#64748b'
  const dash = link.asset?.kind === 'telecom' ? '5,3' : null
  return (
    <g style={{ cursor: 'pointer' }} onClick={onClick} aria-label={`Link ${link.id}`} data-testid={`link-${link.id}`}>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={12} />
      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={colour}
        strokeWidth={selected ? 3.5 : 2}
        strokeDasharray={dash}
        opacity={0.85}
      />
    </g>
  )
}

// ── Violation badge ───────────────────────────────────────────────────────────

function ViolationBadge({ count }) {
  if (!count) return <span className="text-xs text-green-400 font-mono">No violations</span>
  return (
    <span className="text-xs font-mono bg-red-900/60 text-red-300 border border-red-700 rounded px-2 py-0.5">
      {count} violation{count !== 1 ? 's' : ''}
    </span>
  )
}

// ── Section view ─────────────────────────────────────────────────────────────

function SectionView({ links, width = 600, height = 140 }) {
  if (!links.length) {
    return (
      <div className="text-xs text-slate-500 text-center py-4">
        No links — corridor cross-section will appear here
      </div>
    )
  }

  const offsets = links.map(l => l.corridor_offset_m ?? 0)
  const depths  = links.map(l => l.depth_of_cover_m  ?? 0)
  const minOff = Math.min(...offsets)
  const maxOff = Math.max(...offsets)
  const maxDep = Math.max(...depths) + 0.3

  const scaleX = (maxOff - minOff < 0.01) ? 80 : (width - 80) / (maxOff - minOff)
  const scaleY = (height - 40) / maxDep

  const toX = o => 40 + (o - minOff) * scaleX
  const toY = d => 20 + d * scaleY

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="rounded border border-slate-800"
      style={{ background: '#0f172a' }}
      aria-label="Utility corridor cross-section"
    >
      {/* Ground line */}
      <line x1={20} y1={18} x2={width - 20} y2={18} stroke="#475569" strokeWidth="2" />
      <text x={22} y={14} fontSize="8" fill="#475569" fontFamily="monospace">Grade</text>

      {/* Depth ticks */}
      {[0.3, 0.6, 0.9, 1.2].map(d => (
        d <= maxDep && (
          <g key={d}>
            <line x1={16} y1={toY(d)} x2={width - 16} y2={toY(d)} stroke="#1e293b" strokeWidth="0.8" />
            <text x={4} y={toY(d) + 3} fontSize="7" fill="#475569" fontFamily="monospace">
              {d}m
            </text>
          </g>
        )
      ))}

      {/* Utilities */}
      {links.map(lk => {
        const cx = toX(lk.corridor_offset_m ?? 0)
        const cy = toY(lk.depth_of_cover_m  ?? 0)
        const colour = KIND_COLOUR[lk.asset?.kind] || '#64748b'
        const r = 7
        return (
          <g key={lk.id}>
            <circle cx={cx} cy={cy} r={r} fill={colour} opacity={0.85} />
            <text x={cx} y={cy + r + 9} textAnchor="middle" fontSize="7" fill={colour} fontFamily="monospace">
              {lk.id.length > 6 ? lk.id.slice(0, 6) + '…' : lk.id}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function DryUtilityNetworkPanel({
  nodes = [],
  links = [],
  violations: propViolations = null,
  width = 600,
  height = 360,
  className = '',
  onDispatch,
}) {
  const [loading, setLoading] = useState(false)
  const [violations, setViolations] = useState(propViolations)
  const [error, setError] = useState(null)
  const [selectedLink, setSelectedLink] = useState(null)
  const [tab, setTab] = useState('plan')  // 'plan' | 'section' | 'violations'

  // Coordinate projection
  const { scale, offX, offY } = useMemo(() => {
    const pts = nodes.filter(n => n.x != null && n.y != null).map(n => [n.x, n.y])
    return fitCoords(pts, width, height)
  }, [nodes, width, height])

  const posMap = useMemo(() => {
    const m = {}
    for (const n of nodes) {
      if (n.x != null && n.y != null) {
        m[n.id] = [n.x * scale + offX, n.y * scale + offY]
      }
    }
    return m
  }, [nodes, scale, offX, offY])

  // Build violation set for quick link lookup
  const violatedLinkIds = useMemo(() => {
    if (!violations) return new Set()
    return new Set(violations.flatMap(v => [v.link_id, v.link_id_b].filter(Boolean)))
  }, [violations])

  // ── Dispatch clearance check ─────────────────────────────────────────────
  async function handleCheckClearances() {
    setLoading(true)
    setError(null)
    const params = { nodes, links }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'civil_dry_utility_clearance_check', params })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'civil_dry_utility_clearance_check', params }),
        })
        const data = await res.json()
        if (data.violations) setViolations(data.violations)
      }
    } catch (e) {
      setError(e.message || 'Check failed')
    } finally {
      setLoading(false)
    }
  }

  const isEmpty = nodes.length === 0

  const selLinkObj = links.find(l => l.id === selectedLink) || null

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className={`flex flex-col gap-2 ${className}`} data-testid="dry-utility-panel">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500 font-medium tracking-wide uppercase">
            Dry Utility Network
          </span>
          {violations != null && <ViolationBadge count={violations.length} />}
        </div>
        <div className="flex items-center gap-2">
          {/* Tab switcher */}
          {['plan', 'section', 'violations'].map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                tab === t
                  ? 'bg-slate-700 text-slate-100'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
          <button
            className="text-xs px-3 py-1 rounded bg-kerf-700 hover:bg-kerf-600 text-white disabled:opacity-50 transition-colors"
            onClick={handleCheckClearances}
            disabled={loading || isEmpty}
            data-testid="clearance-check-btn"
          >
            {loading ? 'Checking…' : 'Check clearances'}
          </button>
        </div>
      </div>

      {/* Tab: Plan view */}
      {tab === 'plan' && (
        <div className="relative">
          <svg
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            className="rounded border border-slate-800"
            style={{ background: '#0f172a' }}
            aria-label="Dry utility network plan view"
            role="img"
          >
            {isEmpty ? (
              <text
                x={width / 2} y={height / 2}
                textAnchor="middle" dominantBaseline="middle"
                fontSize="13" fill="#475569" fontFamily="system-ui, sans-serif"
              >
                No network data — pass nodes + links props
              </text>
            ) : (
              <>
                <defs>
                  <pattern id="duGrid" width="40" height="40" patternUnits="userSpaceOnUse">
                    <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" strokeWidth="0.5" />
                  </pattern>
                </defs>
                <rect width={width} height={height} fill="url(#duGrid)" />

                {/* Links */}
                <g aria-label="Utility links">
                  {links.map(lk => {
                    const pA = posMap[lk.node_from]
                    const pB = posMap[lk.node_to]
                    if (!pA || !pB) return null
                    return (
                      <UtilityLinkEdge
                        key={lk.id}
                        link={lk}
                        x1={pA[0]} y1={pA[1]}
                        x2={pB[0]} y2={pB[1]}
                        selected={selectedLink === lk.id || violatedLinkIds.has(lk.id)}
                        onClick={() => setSelectedLink(selectedLink === lk.id ? null : lk.id)}
                      />
                    )
                  })}
                </g>

                {/* Nodes */}
                <g aria-label="Utility nodes">
                  {nodes.map(n => {
                    const pos = posMap[n.id]
                    if (!pos) return null
                    return <NodeSymbol key={n.id} node={n} x={pos[0]} y={pos[1]} />
                  })}
                </g>

                {/* Legend */}
                <g transform={`translate(${width - 110}, 10)`} aria-label="Legend">
                  <rect x={0} y={0} width={100} height={62} rx={4} fill="#1e293b" opacity={0.92} />
                  {Object.entries(KIND_COLOUR).map(([kind, colour], i) => (
                    <g key={kind} transform={`translate(8, ${10 + i * 17})`}>
                      <rect x={0} y={-6} width={14} height={4} fill={colour} rx={1} />
                      <text x={18} y={0} fontSize="9" fill="#94a3b8" fontFamily="monospace">
                        {KIND_LABEL[kind]}
                      </text>
                    </g>
                  ))}
                </g>
              </>
            )}
          </svg>

          {/* Link inspector overlay */}
          {selLinkObj && (
            <div
              className="absolute top-2 right-2 bg-slate-900 border border-slate-700 rounded-lg p-3 text-xs font-mono text-slate-300 shadow-xl min-w-[190px]"
              data-testid="link-inspector"
            >
              <div className="flex items-center justify-between mb-2">
                <span
                  className="font-semibold"
                  style={{ color: KIND_COLOUR[selLinkObj.asset?.kind] || '#fff' }}
                >
                  {selLinkObj.id}
                </span>
                <button
                  onClick={() => setSelectedLink(null)}
                  className="text-slate-500 hover:text-slate-300 ml-2"
                  aria-label="Close inspector"
                >
                  ✕
                </button>
              </div>
              <table className="w-full border-separate" style={{ borderSpacing: '0 2px' }}>
                <tbody>
                  <tr>
                    <td className="text-slate-500 pr-2">Kind</td>
                    <td>{KIND_LABEL[selLinkObj.asset?.kind] || '—'}</td>
                  </tr>
                  <tr>
                    <td className="text-slate-500 pr-2">Length</td>
                    <td>{selLinkObj.length_m?.toFixed(1)} m</td>
                  </tr>
                  <tr>
                    <td className="text-slate-500 pr-2">Cover</td>
                    <td>{((selLinkObj.depth_of_cover_m || 0) * 1000).toFixed(0)} mm</td>
                  </tr>
                  <tr>
                    <td className="text-slate-500 pr-2">Offset</td>
                    <td>{selLinkObj.corridor_offset_m?.toFixed(2)} m</td>
                  </tr>
                  {selLinkObj.asset?.diameter_mm != null && (
                    <tr>
                      <td className="text-slate-500 pr-2">Dia</td>
                      <td>{selLinkObj.asset.diameter_mm} mm</td>
                    </tr>
                  )}
                  {selLinkObj.asset?.voltage_class != null && (
                    <tr>
                      <td className="text-slate-500 pr-2">Voltage</td>
                      <td>{selLinkObj.asset.voltage_class}</td>
                    </tr>
                  )}
                  {violatedLinkIds.has(selLinkObj.id) && (
                    <tr>
                      <td colSpan={2} className="text-red-400 pt-1">Violation detected</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tab: Section view */}
      {tab === 'section' && (
        <SectionView links={links} width={width} height={160} />
      )}

      {/* Tab: Violations */}
      {tab === 'violations' && (
        <div
          className="rounded border border-slate-800 bg-slate-950 overflow-y-auto text-xs font-mono"
          style={{ maxHeight: height, minHeight: 120 }}
          data-testid="violations-panel"
        >
          {!violations ? (
            <div className="text-slate-500 text-center py-6">
              Run "Check clearances" to see violations
            </div>
          ) : violations.length === 0 ? (
            <div className="text-green-400 text-center py-6">
              All clearances satisfied — no violations
            </div>
          ) : (
            <table className="w-full border-separate" style={{ borderSpacing: 0 }}>
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="px-3 py-2 text-left">Type</th>
                  <th className="px-3 py-2 text-left">Link(s)</th>
                  <th className="px-3 py-2 text-right">Required</th>
                  <th className="px-3 py-2 text-right">Actual</th>
                  <th className="px-3 py-2 text-right">Deficit</th>
                </tr>
              </thead>
              <tbody>
                {violations.map((v, i) => (
                  <tr
                    key={i}
                    className="border-b border-slate-900 hover:bg-slate-900/50"
                  >
                    <td
                      className="px-3 py-1.5 whitespace-nowrap"
                      style={{ color: violationSeverityColour(v.violation_type) }}
                    >
                      {v.violation_type.replace(/_/g, ' ')}
                    </td>
                    <td className="px-3 py-1.5 text-slate-300">
                      {v.link_id}{v.link_id_b ? ` / ${v.link_id_b}` : ''}
                    </td>
                    <td className="px-3 py-1.5 text-right text-slate-400">
                      {(v.required_m * 1000).toFixed(0)} mm
                    </td>
                    <td className="px-3 py-1.5 text-right text-slate-300">
                      {(v.actual_m * 1000).toFixed(0)} mm
                    </td>
                    <td className="px-3 py-1.5 text-right text-red-400">
                      −{(v.deficit_m * 1000).toFixed(0)} mm
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {error && (
        <div className="text-xs text-red-400 px-1">{error}</div>
      )}
    </div>
  )
}
