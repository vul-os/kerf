/**
 * PipingRoute3DPanel.jsx — 3D intelligent piping route design panel.
 *
 * Capabilities:
 *   - Spec-driven 3D orthogonal pipe routing between two nozzle points
 *     (ASME B31.3 Barlow wall check, pipe class selection)
 *   - AABB obstacle clash avoidance (route around equipment)
 *   - Isometric projection of the 3D centreline
 *   - Fitting BOM with ASME B16.9 centre-to-face dimensions
 *   - Dispatches to: piping_route_3d LLM tool
 *
 * NOTE: Interactive drag-routing in a live 3D plant model is not yet wired
 * to a 3D viewport — the route is displayed as an isometric SVG projection.
 *
 * Dispatches to:
 *   POST /api/tools/call  { tool: "piping_route_3d", args: {...} }
 */

import { useState, useCallback } from 'react'
import {
  GitBranch, Layers, AlertTriangle, CheckCircle, Loader2,
  Plus, Trash2, Package, Info,
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
// Isometric SVG projection
// Transforms 3D waypoints → 2D isometric coords
// ---------------------------------------------------------------------------

function isoProject([x, y, z]) {
  // Standard 30° isometric projection
  const angle = Math.PI / 6  // 30°
  const cx = (x - z) * Math.cos(angle)
  const cy = (x + z) * Math.sin(angle) - y
  return [cx, cy]
}

function IsoRouteView({ centerline, width = 400, height = 300 }) {
  if (!centerline || centerline.length < 2) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-400 text-sm">
        No route to display
      </div>
    )
  }

  const projected = centerline.map(isoProject)
  const xs = projected.map(p => p[0])
  const ys = projected.map(p => p[1])
  const xMin = Math.min(...xs), xMax = Math.max(...xs)
  const yMin = Math.min(...ys), yMax = Math.max(...ys)

  const pad = 30
  const scaleX = xMax !== xMin ? (width - 2 * pad) / (xMax - xMin) : 1
  const scaleY = yMax !== yMin ? (height - 2 * pad) / (yMax - yMin) : 1
  const scale = Math.min(scaleX, scaleY, 80)

  const toSvg = ([px, py]) => [
    pad + (px - xMin) * scale,
    height - pad - (py - yMin) * scale,
  ]

  const svgPts = projected.map(toSvg)
  const pathD = svgPts
    .map(([sx, sy], i) => `${i === 0 ? 'M' : 'L'} ${sx.toFixed(1)} ${sy.toFixed(1)}`)
    .join(' ')

  // Node circles
  const nodes = svgPts.map(([sx, sy], i) => (
    <circle
      key={i}
      cx={sx}
      cy={sy}
      r={i === 0 || i === svgPts.length - 1 ? 5 : 3}
      fill={i === 0 ? '#22c55e' : i === svgPts.length - 1 ? '#ef4444' : '#3b82f6'}
      stroke="white"
      strokeWidth="1"
    />
  ))

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="border border-gray-200 rounded bg-gray-50"
    >
      <text x={pad} y={16} fontSize="10" fill="#6b7280">Isometric projection (30°)</text>
      {/* Grid lines */}
      {[...Array(5)].map((_, i) => (
        <line
          key={`h${i}`}
          x1={pad} y1={pad + i * (height - 2 * pad) / 4}
          x2={width - pad} y2={pad + i * (height - 2 * pad) / 4}
          stroke="#f3f4f6" strokeWidth="1"
        />
      ))}
      {/* Route path */}
      <path d={pathD} fill="none" stroke="#3b82f6" strokeWidth="2.5" strokeLinejoin="round" />
      {/* Elbow nodes */}
      {nodes}
      {/* Legend */}
      <circle cx={pad} cy={height - 10} r={4} fill="#22c55e" />
      <text x={pad + 8} y={height - 6} fontSize="9" fill="#374151">Start</text>
      <circle cx={pad + 50} cy={height - 10} r={4} fill="#ef4444" />
      <text x={pad + 58} y={height - 6} fontSize="9" fill="#374151">End</text>
      <circle cx={pad + 95} cy={height - 10} r={3} fill="#3b82f6" />
      <text x={pad + 103} y={height - 6} fontSize="9" fill="#374151">Elbow</text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// BOM table
// ---------------------------------------------------------------------------

function BOMTable({ bom }) {
  if (!bom || bom.length === 0) return null
  return (
    <div className="mt-4">
      <h4 className="font-medium text-sm text-gray-700 mb-2 flex items-center gap-1">
        <Package size={14} /> Fitting Bill of Materials
      </h4>
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-gray-100">
            <th className="px-2 py-1 text-left border border-gray-200">Item</th>
            <th className="px-2 py-1 text-left border border-gray-200">Description</th>
            <th className="px-2 py-1 text-right border border-gray-200">Qty</th>
            <th className="px-2 py-1 text-right border border-gray-200">C-to-F (mm)</th>
            <th className="px-2 py-1 text-left border border-gray-200">Standard</th>
          </tr>
        </thead>
        <tbody>
          {bom.map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              <td className="px-2 py-1 border border-gray-200 font-mono">{row.item}</td>
              <td className="px-2 py-1 border border-gray-200">{row.description}</td>
              <td className="px-2 py-1 border border-gray-200 text-right">
                {row.quantity ?? row.total_length_m?.toFixed(3) + ' m'}
              </td>
              <td className="px-2 py-1 border border-gray-200 text-right font-mono">
                {row.center_to_face_mm != null ? row.center_to_face_mm.toFixed(1) : '—'}
              </td>
              <td className="px-2 py-1 border border-gray-200 text-gray-500">
                {row.standard ?? ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const PIPE_SPECS = ['', 'CS-A', 'CS-HH', 'SS-316L', 'API-X52']
const PREFER_AXES = ['Z', 'X', 'Y']
const DN_OPTIONS = [15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300]

const DEFAULT_OBSTACLE = () => ({
  id: Date.now(),
  label: '',
  min: ['', '', ''],
  max: ['', '', ''],
})

export default function PipingRoute3DPanel() {
  const { token } = useAuth()

  const [start, setStart] = useState(['0', '0', '0'])
  const [end, setEnd] = useState(['5', '0', '3'])
  const [dn, setDn] = useState(50)
  const [schedule, setSchedule] = useState('40')
  const [pipeSpec, setPipeSpec] = useState('')
  const [preferAxis, setPreferAxis] = useState('Z')
  const [clearance, setClearance] = useState('0.3')
  const [obstacles, setObstacles] = useState([])

  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const addObstacle = () => setObstacles(obs => [...obs, DEFAULT_OBSTACLE()])
  const removeObstacle = (id) => setObstacles(obs => obs.filter(o => o.id !== id))
  const updateObstacle = (id, field, idx, val) => {
    setObstacles(obs => obs.map(o => {
      if (o.id !== id) return o
      const arr = [...o[field]]
      arr[idx] = val
      return { ...o, [field]: arr }
    }))
  }

  const handleRoute = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const args = {
        start: start.map(Number),
        end: end.map(Number),
        dn,
        prefer_axis: preferAxis,
        clearance_m: parseFloat(clearance) || 0.3,
      }
      if (pipeSpec) args.pipe_spec = pipeSpec
      else args.schedule = schedule

      if (obstacles.length > 0) {
        args.obstacles = obstacles
          .filter(o => o.min.every(v => v !== '') && o.max.every(v => v !== ''))
          .map(o => ({
            min: o.min.map(Number),
            max: o.max.map(Number),
            label: o.label,
          }))
      }

      const data = await callTool('piping_route_3d', args, token)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [start, end, dn, schedule, pipeSpec, preferAxis, clearance, obstacles, token])

  return (
    <div className="p-4 space-y-4 max-w-2xl">
      <div className="flex items-center gap-2">
        <GitBranch size={18} className="text-blue-600" />
        <h2 className="text-base font-semibold text-gray-800">
          3D Pipe Route Design (ASME B31.3)
        </h2>
      </div>

      {/* Note on interactive routing */}
      <div className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
        <Info size={14} className="mt-0.5 shrink-0" />
        <span>
          Orthogonal (manhattan) routing with ASME B16.9 elbows at direction changes.
          Interactive drag-routing in a 3D plant viewport is not yet wired — route is
          displayed as an isometric projection.
        </span>
      </div>

      {/* Start / End */}
      <div className="grid grid-cols-2 gap-4">
        {[['Start nozzle', start, setStart], ['End nozzle', end, setEnd]].map(([label, val, setter]) => (
          <div key={label}>
            <label className="block text-xs font-medium text-gray-600 mb-1">{label} [x, y, z] (m)</label>
            <div className="flex gap-1">
              {['x', 'y', 'z'].map((ax, i) => (
                <input
                  key={ax}
                  type="number"
                  value={val[i]}
                  onChange={e => {
                    const arr = [...val]
                    arr[i] = e.target.value
                    setter(arr)
                  }}
                  className="w-16 border border-gray-300 rounded px-1.5 py-1 text-xs font-mono"
                  placeholder={ax}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Pipe params */}
      <div className="grid grid-cols-4 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">DN (mm)</label>
          <select
            value={dn}
            onChange={e => setDn(Number(e.target.value))}
            className="border border-gray-300 rounded px-2 py-1 text-xs w-full"
          >
            {DN_OPTIONS.map(d => <option key={d} value={d}>DN{d}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Pipe Spec</label>
          <select
            value={pipeSpec}
            onChange={e => setPipeSpec(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1 text-xs w-full"
          >
            {PIPE_SPECS.map(s => <option key={s} value={s}>{s || '— manual —'}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Schedule</label>
          <input
            type="text"
            value={schedule}
            onChange={e => setSchedule(e.target.value)}
            disabled={!!pipeSpec}
            className="border border-gray-300 rounded px-2 py-1 text-xs w-full disabled:bg-gray-100"
            placeholder="40"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Prefer axis</label>
          <select
            value={preferAxis}
            onChange={e => setPreferAxis(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1 text-xs w-full"
          >
            {PREFER_AXES.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      </div>

      {/* Obstacles */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-medium text-gray-600">
            AABB Obstacles (clash avoidance)
          </label>
          <button
            onClick={addObstacle}
            className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800"
          >
            <Plus size={12} /> Add obstacle
          </button>
        </div>
        {obstacles.map(obs => (
          <div key={obs.id} className="flex items-center gap-2 mb-2 text-xs">
            <input
              type="text"
              placeholder="Label"
              value={obs.label}
              onChange={e => setObstacles(o => o.map(x => x.id === obs.id ? { ...x, label: e.target.value } : x))}
              className="border border-gray-300 rounded px-1.5 py-1 w-20"
            />
            {['min', 'max'].map(field => (
              <div key={field} className="flex items-center gap-0.5">
                <span className="text-gray-400">{field}[</span>
                {[0, 1, 2].map(i => (
                  <input
                    key={i}
                    type="number"
                    placeholder="0"
                    value={obs[field][i]}
                    onChange={e => updateObstacle(obs.id, field, i, e.target.value)}
                    className="w-12 border border-gray-300 rounded px-1 py-1"
                  />
                ))}
                <span className="text-gray-400">]</span>
              </div>
            ))}
            <input
              type="number"
              placeholder="0.3"
              value={clearance}
              onChange={e => setClearance(e.target.value)}
              className="w-14 border border-gray-300 rounded px-1.5 py-1"
              title="Clearance (m)"
            />
            <span className="text-gray-400 text-xs">m clr</span>
            <button onClick={() => removeObstacle(obs.id)} className="text-red-400 hover:text-red-600">
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>

      <button
        onClick={handleRoute}
        disabled={loading}
        className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50
                   text-white text-sm px-4 py-2 rounded"
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : <GitBranch size={14} />}
        Route pipe
      </button>

      {error && (
        <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 border border-red-200 rounded p-3">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {result && result.ok && (
        <div className="space-y-4">
          {/* Summary stats */}
          <div className="grid grid-cols-4 gap-3">
            {[
              ['Total length', `${result.total_length_m?.toFixed(3)} m`],
              ['Elbows 90°', result.elbows_90],
              ['DN / Sch', `DN${result.dn} / ${result.schedule}`],
              ['Clashes avoided', result.clashes_avoided ?? 0],
            ].map(([label, val]) => (
              <div key={label} className="bg-blue-50 rounded p-2 text-center">
                <div className="text-lg font-semibold text-blue-700">{val}</div>
                <div className="text-xs text-gray-500">{label}</div>
              </div>
            ))}
          </div>

          {/* Elbow dimensions */}
          {result.elbow_center_to_face_mm > 0 && (
            <div className="text-xs text-gray-600 bg-gray-50 border border-gray-200 rounded p-2">
              <span className="font-medium">ASME B16.9 LR elbow:</span>{' '}
              centre-to-face A = {result.elbow_center_to_face_mm?.toFixed(1)} mm,
              centreline radius R = {result.elbow_radius_mm?.toFixed(1)} mm
            </div>
          )}

          {/* Isometric view */}
          <div>
            <h4 className="font-medium text-sm text-gray-700 mb-2 flex items-center gap-1">
              <Layers size={14} /> Route centreline (isometric projection)
            </h4>
            <IsoRouteView centerline={result.centerline} width={480} height={260} />
          </div>

          {/* Warnings */}
          {result.warnings && result.warnings.length > 0 && (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
              {result.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
            </div>
          )}

          <BOMTable bom={result.bom} />

          <p className="text-xs text-gray-400">
            ASME B16.9-2018 / B31.3-2022 — not a substitute for licensed engineer review.
          </p>
        </div>
      )}
    </div>
  )
}
