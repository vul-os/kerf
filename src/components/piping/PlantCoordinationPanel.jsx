/**
 * PlantCoordinationPanel.jsx — Multi-discipline plant coordination panel.
 *
 * Assembles a federated plant model from structural members, HVAC ducts,
 * pipe routes, civil/equipment elements in a shared 3D coordinate space,
 * then runs cross-discipline clash detection + clearance checking.
 *
 * Features:
 *   - Discipline legend (colour-coded: structural/hvac/piping/civil/equipment)
 *   - Clash list grouped by discipline pair (hard + soft, with severity badge)
 *   - Combined BOM per discipline (element count, weight, cost)
 *   - Iso/plan view: simple SVG isometric projection of element AABBs
 *   - One-click "Assemble + Check" workflow
 *
 * Dispatches to:
 *   POST /api/tools/call  { tool: "plant_coordination_check", args: {...} }
 *
 * References
 * ----------
 * USACE EM 1110-1-1000 §5 — multi-discipline coordination.
 * BS 1192-4:2014 §4.4 — federated model.
 * ASME B31.3 §321 — piping clearance.
 * SMACNA §5.4 — duct clearances.
 */

import { useState, useCallback } from 'react'
import {
  Layers, AlertTriangle, CheckCircle, Loader2, Plus, Trash2,
  Package, Info, Eye, BarChart3,
} from 'lucide-react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

async function callTool(toolName, args, token) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const text = await res.text()
    let msg = text
    try { msg = JSON.parse(text).error || text } catch { /* ignore */ }
    throw new Error(msg || `HTTP ${res.status}`)
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// Discipline legend config
// ---------------------------------------------------------------------------

const DISCIPLINE_META = {
  structural:  { color: '#2563eb', bg: '#dbeafe', label: 'Structural' },
  hvac:        { color: '#16a34a', bg: '#dcfce7', label: 'HVAC' },
  piping:      { color: '#dc2626', bg: '#fee2e2', label: 'Piping' },
  civil:       { color: '#92400e', bg: '#fef3c7', label: 'Civil' },
  equipment:   { color: '#7c3aed', bg: '#ede9fe', label: 'Equipment' },
  electrical:  { color: '#0891b2', bg: '#cffafe', label: 'Electrical' },
  instrument:  { color: '#4b5563', bg: '#f3f4f6', label: 'Instrument' },
}

const DISCIPLINE_OPTIONS = Object.keys(DISCIPLINE_META)

const SEVERITY_STYLE = {
  critical: { color: '#dc2626', bg: '#fee2e2', label: 'CRITICAL' },
  major:    { color: '#d97706', bg: '#fef3c7', label: 'MAJOR' },
  minor:    { color: '#2563eb', bg: '#dbeafe', label: 'MINOR' },
}

// ---------------------------------------------------------------------------
// Discipline legend strip
// ---------------------------------------------------------------------------

function DisciplineLegend({ present = [] }) {
  return (
    <div className="flex flex-wrap gap-2 mb-4">
      {DISCIPLINE_OPTIONS.map(d => {
        const meta = DISCIPLINE_META[d]
        const active = present.includes(d)
        return (
          <span
            key={d}
            style={{
              background: active ? meta.bg : '#f3f4f6',
              color: active ? meta.color : '#9ca3af',
              border: `1px solid ${active ? meta.color + '66' : '#e5e7eb'}`,
              opacity: active ? 1.0 : 0.5,
            }}
            className="px-2 py-0.5 rounded text-xs font-semibold"
          >
            {meta.label}
          </span>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Clash list by discipline pair
// ---------------------------------------------------------------------------

function ClashList({ clashesByPair }) {
  if (!clashesByPair || Object.keys(clashesByPair).length === 0) {
    return (
      <div className="flex items-center gap-2 text-green-700 text-sm py-3">
        <CheckCircle size={16} />
        No clashes detected — all discipline pairs clear.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {Object.entries(clashesByPair).map(([pairKey, clashes]) => {
        const [discA, discB] = pairKey.split('--')
        const metaA = DISCIPLINE_META[discA] || { color: '#6b7280', label: discA }
        const metaB = DISCIPLINE_META[discB] || { color: '#6b7280', label: discB }
        const hardCount = clashes.filter(c => c.clash_type === 'hard').length
        const softCount = clashes.filter(c => c.clash_type === 'soft').length

        return (
          <div key={pairKey} className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 border-b border-gray-200">
              <span
                style={{ background: metaA.bg, color: metaA.color }}
                className="px-2 py-0.5 rounded text-xs font-semibold"
              >
                {(metaA.label || discA).toUpperCase()}
              </span>
              <span className="text-gray-400 text-xs">↔</span>
              <span
                style={{ background: metaB.bg, color: metaB.color }}
                className="px-2 py-0.5 rounded text-xs font-semibold"
              >
                {(metaB.label || discB).toUpperCase()}
              </span>
              <span className="ml-auto text-xs text-gray-500">
                {hardCount > 0 && (
                  <span className="text-red-600 font-bold mr-2">{hardCount} hard</span>
                )}
                {softCount > 0 && (
                  <span className="text-amber-600 mr-2">{softCount} soft</span>
                )}
                {clashes.length} total
              </span>
            </div>

            <div className="divide-y divide-gray-100">
              {clashes.slice(0, 8).map((c, i) => {
                const sev = SEVERITY_STYLE[c.severity] || SEVERITY_STYLE.minor
                return (
                  <div key={i} className="flex items-start gap-3 px-3 py-2 text-xs">
                    <span
                      style={{ background: sev.bg, color: sev.color }}
                      className="mt-0.5 px-1.5 py-0.5 rounded font-bold shrink-0"
                    >
                      {sev.label}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-gray-700">
                        {c.element_a} ↔ {c.element_b}
                      </div>
                      <div className="text-gray-400 mt-0.5">
                        Type: {c.clash_type} · Gap: {(c.gap_m * 1000).toFixed(1)} mm
                        {c.clash_type === 'hard' && (
                          <> · Overlap: {(c.overlap_volume_m3 * 1e6).toFixed(2)} cm³</>
                        )}
                        {c.clash_type === 'soft' && (
                          <> · Shortfall: {(c.shortfall_m * 1000).toFixed(1)} mm</>
                        )}
                        {' · Required: '}{(c.required_clearance_m * 1000).toFixed(0)} mm clearance
                      </div>
                      <div className="text-gray-400 mt-0.5">
                        @ [{c.location_m?.map(v => v.toFixed(2)).join(', ')}] m
                      </div>
                    </div>
                  </div>
                )
              })}
              {clashes.length > 8 && (
                <div className="px-3 py-2 text-xs text-gray-400">
                  … and {clashes.length - 8} more clashes in this pair
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Isometric SVG view of element AABBs
// ---------------------------------------------------------------------------

function isoProject([x, y, z]) {
  // Standard dimetric isometric: 30° angle
  const a = Math.PI / 6
  const cx = (x - y) * Math.cos(a)
  const cy = (x + y) * Math.sin(a) - z
  return [cx, cy]
}

function IsoPlantView({ elements = [], width = 400, height = 240 }) {
  if (elements.length === 0) {
    return (
      <div className="flex items-center justify-center h-36 text-gray-400 text-sm border border-dashed rounded-lg">
        No elements — add discipline elements to visualise
      </div>
    )
  }

  // Collect all 8 corners of every AABB, project to 2D
  const allPts2d = []
  const elemPts = elements.map(e => {
    const [lo, hi] = [e.bbox_min, e.bbox_max]
    const corners = [
      [lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]],
      [lo[0], hi[1], lo[2]], [hi[0], hi[1], lo[2]],
      [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
      [lo[0], hi[1], hi[2]], [hi[0], hi[1], hi[2]],
    ]
    const pts2d = corners.map(isoProject)
    allPts2d.push(...pts2d)
    return { disc: e.discipline, pts2d }
  })

  if (allPts2d.length === 0) return null

  const xs = allPts2d.map(p => p[0])
  const ys = allPts2d.map(p => p[1])
  const xMin = Math.min(...xs), xMax = Math.max(...xs)
  const yMin = Math.min(...ys), yMax = Math.max(...ys)
  const pad = 20
  const scaleX = xMax !== xMin ? (width - 2 * pad) / (xMax - xMin) : 1
  const scaleY = yMax !== yMin ? (height - 2 * pad) / (yMax - yMin) : 1
  const scale = Math.min(scaleX, scaleY, 40)

  function toSvg([px, py]) {
    return [
      pad + (px - xMin) * scale,
      pad + (py - yMin) * scale,
    ]
  }

  // Draw bottom face of each AABB (rectangle in iso projection)
  const FACE_IDX = [[0, 1, 3, 2], [0, 1, 5, 4], [0, 2, 6, 4]]

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="w-full border border-gray-200 rounded-lg bg-gray-50"
    >
      {elemPts.map((ep, idx) => {
        const meta = DISCIPLINE_META[ep.disc] || { color: '#6b7280', bg: '#f3f4f6' }
        return FACE_IDX.map((face, fi) => {
          const pts = face.map(ci => toSvg(ep.pts2d[ci]))
          const dPath = `M ${pts.map(([x, y]) => `${x},${y}`).join(' L ')} Z`
          return (
            <path
              key={`${idx}-${fi}`}
              d={dPath}
              fill={meta.bg}
              stroke={meta.color}
              strokeWidth="0.8"
              opacity="0.7"
            />
          )
        })
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// BOM table
// ---------------------------------------------------------------------------

function BomTable({ bomByDiscipline }) {
  if (!bomByDiscipline || Object.keys(bomByDiscipline).length === 0) {
    return <div className="text-sm text-gray-400 py-2">No BOM data</div>
  }

  return (
    <div className="space-y-3">
      {Object.entries(bomByDiscipline).map(([disc, items]) => {
        const meta = DISCIPLINE_META[disc] || { color: '#6b7280', bg: '#f3f4f6', label: disc }
        const totalWeight = items.reduce((s, i) => s + (i.weight_kg || 0) * (i.quantity || 1), 0)
        const totalCost = items.reduce((s, i) => s + (i.total_cost || 0), 0)

        return (
          <div key={disc} className="border border-gray-200 rounded-lg overflow-hidden">
            <div
              style={{ background: meta.bg, color: meta.color, borderBottom: `1px solid ${meta.color}33` }}
              className="flex items-center justify-between px-3 py-1.5"
            >
              <span className="text-xs font-bold uppercase">{meta.label || disc}</span>
              <span className="text-xs">
                {items.length} elements · {totalWeight.toFixed(1)} kg
                {totalCost > 0 && <> · ${totalCost.toFixed(0)}</>}
              </span>
            </div>
            <div className="divide-y divide-gray-50 max-h-40 overflow-y-auto">
              {items.slice(0, 12).map((item, i) => (
                <div key={i} className="flex items-center gap-2 px-3 py-1 text-xs">
                  <span className="text-gray-600 font-medium truncate flex-1">{item.label || item.element_id}</span>
                  {item.material && (
                    <span className="text-gray-400 shrink-0">{item.material}</span>
                  )}
                  {item.weight_kg > 0 && (
                    <span className="text-gray-500 shrink-0">{(item.weight_kg * item.quantity).toFixed(1)} kg</span>
                  )}
                </div>
              ))}
              {items.length > 12 && (
                <div className="px-3 py-1 text-xs text-gray-400">… +{items.length - 12} more</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Element editor row
// ---------------------------------------------------------------------------

const DEFAULT_ELEMENT = {
  element_id: '',
  discipline: 'structural',
  bbox_min: [0, 0, 0],
  bbox_max: [1, 0.3, 0.3],
  label: '',
  system: '',
  material: '',
  quantity: 1,
  unit: 'ea',
  weight_kg: 0,
  unit_cost: 0,
}

function ElementRow({ elem, onChange, onRemove }) {
  const handleField = (field, val) =>
    onChange({ ...elem, [field]: val })

  const handleBboxVal = (kind, idx, val) => {
    const next = [...(elem[kind] || [0, 0, 0])]
    next[idx] = parseFloat(val) || 0
    onChange({ ...elem, [kind]: next })
  }

  const meta = DISCIPLINE_META[elem.discipline] || {}

  return (
    <div
      className="border rounded-lg p-3 space-y-2 text-xs"
      style={{ borderColor: meta.color ? meta.color + '66' : '#e5e7eb', background: meta.bg || '#fff' }}
    >
      <div className="flex items-center gap-2">
        <input
          type="text"
          placeholder="Element ID"
          value={elem.element_id}
          onChange={e => handleField('element_id', e.target.value)}
          className="flex-1 border rounded px-2 py-1 text-xs font-mono"
        />
        <select
          value={elem.discipline}
          onChange={e => handleField('discipline', e.target.value)}
          className="border rounded px-2 py-1 text-xs font-semibold"
          style={{ color: meta.color }}
        >
          {DISCIPLINE_OPTIONS.map(d => (
            <option key={d} value={d}>{DISCIPLINE_META[d].label}</option>
          ))}
        </select>
        <button
          onClick={onRemove}
          className="p-1 text-gray-400 hover:text-red-500"
          title="Remove element"
        >
          <Trash2 size={14} />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <div className="text-gray-500 mb-0.5">Min corner (m)</div>
          <div className="flex gap-1">
            {['X', 'Y', 'Z'].map((ax, i) => (
              <input
                key={ax}
                type="number"
                step="0.1"
                value={elem.bbox_min?.[i] ?? 0}
                onChange={e => handleBboxVal('bbox_min', i, e.target.value)}
                className="w-16 border rounded px-1 py-0.5 text-xs font-mono"
                title={`Min ${ax}`}
              />
            ))}
          </div>
        </div>
        <div>
          <div className="text-gray-500 mb-0.5">Max corner (m)</div>
          <div className="flex gap-1">
            {['X', 'Y', 'Z'].map((ax, i) => (
              <input
                key={ax}
                type="number"
                step="0.1"
                value={elem.bbox_max?.[i] ?? 1}
                onChange={e => handleBboxVal('bbox_max', i, e.target.value)}
                className="w-16 border rounded px-1 py-0.5 text-xs font-mono"
                title={`Max ${ax}`}
              />
            ))}
          </div>
        </div>
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Label (optional)"
          value={elem.label || ''}
          onChange={e => handleField('label', e.target.value)}
          className="flex-1 border rounded px-2 py-0.5 text-xs"
        />
        <input
          type="text"
          placeholder="Material"
          value={elem.material || ''}
          onChange={e => handleField('material', e.target.value)}
          className="w-28 border rounded px-2 py-0.5 text-xs"
        />
        <input
          type="number"
          placeholder="kg"
          value={elem.weight_kg || 0}
          onChange={e => handleField('weight_kg', parseFloat(e.target.value) || 0)}
          className="w-16 border rounded px-2 py-0.5 text-xs"
          title="Weight (kg)"
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Panel
// ---------------------------------------------------------------------------

const DEMO_ELEMENTS = [
  {
    element_id: 'BEAM-01', discipline: 'structural',
    bbox_min: [0, 4.9, 3.0], bbox_max: [8.0, 5.1, 3.3],
    label: 'IPE330 beam', material: 'S275', weight_kg: 110,
  },
  {
    element_id: 'COL-01', discipline: 'structural',
    bbox_min: [7.9, 4.9, 0], bbox_max: [8.1, 5.1, 8.0],
    label: 'HEA200 column', material: 'S275', weight_kg: 220,
  },
  {
    element_id: 'STEAM-HEADER', discipline: 'piping',
    bbox_min: [0, 4.95, 3.1], bbox_max: [8.0, 6.05, 3.2],
    label: 'DN150 steam header', material: 'ASTM A106 Gr.B', weight_kg: 62,
  },
  {
    element_id: 'DUCT-MAIN', discipline: 'hvac',
    bbox_min: [0, 0, 4.0], bbox_max: [12.0, 0.6, 4.6],
    label: '600×600 supply duct', material: 'galv steel', weight_kg: 80,
  },
  {
    element_id: 'FND-01', discipline: 'civil',
    bbox_min: [-1, -1, -1.5], bbox_max: [9, 9, 0],
    label: 'RC foundation slab', material: 'C30/37', weight_kg: 4000,
  },
  {
    element_id: 'PUMP-101', discipline: 'equipment',
    bbox_min: [2, 2, 0], bbox_max: [4, 4, 1.5],
    label: 'Centrifugal pump P-101', material: 'cast iron',
  },
]

export default function PlantCoordinationPanel() {
  const { token } = useAuth()

  const [projectId, setProjectId] = useState('PLANT-001')
  const [elements, setElements] = useState(DEMO_ELEMENTS.map(e => ({ ...e })))
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState('clashes')

  const addElement = useCallback(() => {
    setElements(prev => [
      ...prev,
      { ...DEFAULT_ELEMENT, element_id: `ELEM-${prev.length + 1}` },
    ])
  }, [])

  const removeElement = useCallback((idx) => {
    setElements(prev => prev.filter((_, i) => i !== idx))
  }, [])

  const updateElement = useCallback((idx, updated) => {
    setElements(prev => prev.map((e, i) => i === idx ? updated : e))
  }, [])

  const runCheck = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await callTool('plant_coordination_check', {
        project_id: projectId,
        elements: elements.map(e => ({
          element_id: e.element_id,
          discipline: e.discipline,
          bbox_min: e.bbox_min,
          bbox_max: e.bbox_max,
          label: e.label,
          material: e.material,
          weight_kg: e.weight_kg || 0,
          quantity: e.quantity || 1,
          unit: e.unit || 'ea',
          unit_cost: e.unit_cost || 0,
        })),
      }, token)
      if (res.error) throw new Error(res.error)
      setResult(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [projectId, elements, token])

  const disciplinesPresent = [...new Set(elements.map(e => e.discipline))]
  const totalClashes = result
    ? (result.hard_clash_count || 0) + (result.soft_clash_count || 0)
    : null

  return (
    <div className="flex flex-col h-full gap-4 p-4 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Layers size={18} className="text-blue-600" />
        <h2 className="text-base font-semibold text-gray-800">
          Multi-Discipline Plant Coordination
        </h2>
      </div>

      {/* Discipline legend */}
      <DisciplineLegend present={disciplinesPresent} />

      {/* Isometric preview */}
      <div>
        <div className="text-xs font-medium text-gray-600 mb-1 flex items-center gap-1">
          <Eye size={12} /> Plant view (isometric AABB projection)
        </div>
        <IsoPlantView elements={elements} width={420} height={200} />
      </div>

      {/* Project ID + Run button */}
      <div className="flex items-center gap-2">
        <label className="text-xs text-gray-600 shrink-0">Project:</label>
        <input
          type="text"
          value={projectId}
          onChange={e => setProjectId(e.target.value)}
          className="border rounded px-2 py-1 text-xs font-mono flex-1"
          placeholder="Project ID"
        />
        <button
          onClick={runCheck}
          disabled={loading || elements.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading
            ? <><Loader2 size={14} className="animate-spin" /> Running…</>
            : <><CheckCircle size={14} /> Assemble + Check</>
          }
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 text-red-700 bg-red-50 border border-red-200 rounded p-2 text-xs">
          <AlertTriangle size={14} className="shrink-0" />
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          {/* Summary bar */}
          <div className="flex items-center gap-3 px-3 py-2 bg-gray-50 border-b border-gray-200 text-xs">
            <span className="font-semibold text-gray-700">
              {result.total_elements} elements
            </span>
            <span className="text-gray-400">·</span>
            {result.hard_clash_count > 0
              ? <span className="text-red-600 font-bold">{result.hard_clash_count} hard</span>
              : <span className="text-green-600">0 hard</span>
            }
            <span className="text-gray-400">·</span>
            {result.soft_clash_count > 0
              ? <span className="text-amber-600">{result.soft_clash_count} soft</span>
              : <span className="text-green-600">0 soft</span>
            }
            <span className="text-gray-400">·</span>
            <span className="text-gray-500">
              {Object.keys(result.bom_by_discipline || {}).join(', ')}
            </span>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-200 bg-white">
            {[
              { id: 'clashes', icon: <AlertTriangle size={12} />, label: `Clashes (${totalClashes ?? 0})` },
              { id: 'bom', icon: <Package size={12} />, label: 'BOM' },
              { id: 'zones', icon: <BarChart3 size={12} />, label: 'Zones' },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1 px-3 py-2 text-xs border-b-2 transition-colors ${
                  activeTab === tab.id
                    ? 'border-blue-600 text-blue-600 font-medium'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </div>

          <div className="p-3">
            {activeTab === 'clashes' && (
              <ClashList clashesByPair={result.clashes_by_pair} />
            )}
            {activeTab === 'bom' && (
              <BomTable bomByDiscipline={result.bom_by_discipline} />
            )}
            {activeTab === 'zones' && (
              <div className="space-y-2">
                {Object.entries(result.zone_summary || {}).map(([zid, info]) => (
                  <div key={zid} className="flex items-center justify-between text-xs px-2 py-1 bg-gray-50 rounded">
                    <span className="font-medium text-gray-700">{zid}</span>
                    <span className="text-gray-500">{info.element_count} elements</span>
                  </div>
                ))}
                {Object.keys(result.zone_summary || {}).length === 0 && (
                  <div className="text-xs text-gray-400 py-2">
                    No zones configured — all elements are unzoned.
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Warnings */}
          {result.warnings?.length > 0 && (
            <div className="px-3 pb-3 space-y-1">
              {result.warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-2 text-amber-700 bg-amber-50 rounded p-2 text-xs">
                  <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                  {w}
                </div>
              ))}
            </div>
          )}

          {/* Honest gap note */}
          {result.honest_gap && (
            <div className="flex items-start gap-2 mx-3 mb-3 text-xs text-gray-500 bg-gray-50 rounded p-2">
              <Info size={12} className="mt-0.5 shrink-0" />
              {result.honest_gap}
            </div>
          )}
        </div>
      )}

      {/* Element editor */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-gray-700">
            Discipline Elements ({elements.length})
          </h3>
          <button
            onClick={addElement}
            className="flex items-center gap-1 px-2 py-1 border border-gray-300 rounded text-xs text-gray-600 hover:bg-gray-50"
          >
            <Plus size={12} /> Add element
          </button>
        </div>
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {elements.map((elem, idx) => (
            <ElementRow
              key={idx}
              elem={elem}
              onChange={updated => updateElement(idx, updated)}
              onRemove={() => removeElement(idx)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
