/**
 * PipingCataloguePanel.jsx — ASME B16.9/B16.5 3D piping component catalogue.
 *
 * Spec-driven catalogue picker for:
 *   - 90° LR/SR elbows (ASME B16.9)
 *   - 45° LR elbows (ASME B16.9)
 *   - Equal tees (ASME B16.9)
 *   - Concentric reducers (ASME B16.9)
 *   - Weld-neck flanges (ASME B16.5)
 *   - Gate / ball valves (ASME B16.10 / API 6D)
 *   - End caps (ASME B16.9)
 *
 * Each component returns:
 *   - 3D nozzle port positions (relative to component origin, mm)
 *   - Face-to-face / centre-to-face dimensions per ASME standard
 *   - Nominal OD from ASME B36.10M
 *   - BOM line for quantity aggregation
 *
 * Dispatches to:
 *   POST /api/tools/call  { tool: "piping_catalogue_component", args: {...} }
 */

import { useState, useCallback } from 'react'
import {
  Package, Loader2, AlertTriangle, Plus, Trash2, Info, CheckCircle,
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
// Constants
// ---------------------------------------------------------------------------

const COMPONENT_TYPES = [
  { value: 'elbow_90_lr',       label: '90° LR Elbow (B16.9)', hasReducer: false, hasFlange: false },
  { value: 'elbow_90_sr',       label: '90° SR Elbow (B16.9)', hasReducer: false, hasFlange: false },
  { value: 'elbow_45_lr',       label: '45° LR Elbow (B16.9)', hasReducer: false, hasFlange: false },
  { value: 'tee_equal',         label: 'Equal Tee (B16.9)',     hasReducer: false, hasFlange: false },
  { value: 'reducer_concentric',label: 'Concentric Reducer (B16.9)', hasReducer: true, hasFlange: false },
  { value: 'flange_weldneck',   label: 'Weld-Neck Flange (B16.5)', hasReducer: false, hasFlange: true },
  { value: 'valve_gate',        label: 'Gate Valve (B16.10)',   hasReducer: false, hasFlange: false },
  { value: 'valve_ball',        label: 'Ball Valve (API 6D)',   hasReducer: false, hasFlange: false },
  { value: 'cap',               label: 'End Cap (B16.9)',       hasReducer: false, hasFlange: false },
]

const DN_OPTIONS = [15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300]
const FLANGE_CLASSES = [150, 300, 600, 900, 1500, 2500]

// ---------------------------------------------------------------------------
// Port diagram (simple ASCII + text)
// ---------------------------------------------------------------------------

function PortDiagram({ ports }) {
  if (!ports || ports.length === 0) return null
  return (
    <div className="mt-3">
      <h4 className="text-xs font-medium text-gray-600 mb-1">Nozzle ports (relative to origin, mm)</h4>
      <div className="space-y-1">
        {ports.map((port, i) => (
          <div key={i} className="flex items-center gap-3 text-xs font-mono bg-gray-50 rounded px-2 py-1">
            <span className="w-14 font-semibold text-blue-700">{port.label}</span>
            <span className="text-gray-500">pos:</span>
            <span>[{port.position_mm.map(v => v.toFixed(1)).join(', ')}]</span>
            <span className="text-gray-500">dir:</span>
            <span>[{port.flow_direction.map(v => v.toFixed(3)).join(', ')}]</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// BOM accumulator
// ---------------------------------------------------------------------------

function useBOM() {
  const [lines, setLines] = useState([])

  const addLine = useCallback((bomLine) => {
    setLines(prev => {
      const key = `${bomLine.item}|${bomLine.dn}|${bomLine.dn_branch ?? ''}|${bomLine.schedule}`
      const existing = prev.find(l =>
        `${l.item}|${l.dn}|${l.dn_branch ?? ''}|${l.schedule}` === key
      )
      if (existing) {
        return prev.map(l =>
          `${l.item}|${l.dn}|${l.dn_branch ?? ''}|${l.schedule}` === key
            ? { ...l, quantity: l.quantity + bomLine.quantity }
            : l
        )
      }
      return [...prev, { ...bomLine }]
    })
  }, [])

  const clearBOM = () => setLines([])
  const removeLine = (idx) => setLines(prev => prev.filter((_, i) => i !== idx))

  return { lines, addLine, clearBOM, removeLine }
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function PipingCataloguePanel() {
  const { token } = useAuth()

  const [compType, setCompType] = useState('elbow_90_lr')
  const [dn, setDn] = useState(100)
  const [schedule, setSchedule] = useState('40')
  const [dnBranch, setDnBranch] = useState(50)
  const [flangeClass, setFlangeClass] = useState(150)
  const [quantity, setQuantity] = useState(1)

  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const { lines: bomLines, addLine, clearBOM, removeLine } = useBOM()

  const selectedType = COMPONENT_TYPES.find(t => t.value === compType)

  const handleLookup = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const args = { component_type: compType, dn, schedule, quantity }
      if (selectedType?.hasReducer) args.dn_branch = dnBranch
      if (selectedType?.hasFlange) args.flange_class = flangeClass

      const data = await callTool('piping_catalogue_component', args, token)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [compType, dn, schedule, dnBranch, flangeClass, quantity, selectedType, token])

  const handleAddToBOM = () => {
    if (result?.bom_line) addLine(result.bom_line)
  }

  return (
    <div className="p-4 space-y-4 max-w-2xl">
      <div className="flex items-center gap-2">
        <Package size={18} className="text-blue-600" />
        <h2 className="text-base font-semibold text-gray-800">
          Piping Component Catalogue (ASME B16.9 / B16.5)
        </h2>
      </div>

      <div className="flex items-start gap-2 text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded p-2">
        <Info size={14} className="mt-0.5 shrink-0" />
        <span>
          Spec-driven ASME catalogue: parametric dimensions, 3D nozzle geometry,
          and BOM line per ASME B16.9-2018, B16.5-2017, B16.10-2000.
          Not a substitute for the primary ASME standard.
        </span>
      </div>

      {/* Component selector */}
      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-3 sm:col-span-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">Component type</label>
          <select
            value={compType}
            onChange={e => setCompType(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 text-sm w-full"
          >
            {COMPONENT_TYPES.map(t => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">DN (mm)</label>
          <select
            value={dn}
            onChange={e => setDn(Number(e.target.value))}
            className="border border-gray-300 rounded px-2 py-1.5 text-sm w-full"
          >
            {DN_OPTIONS.map(d => <option key={d} value={d}>DN{d}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Schedule</label>
          <input
            type="text"
            value={schedule}
            onChange={e => setSchedule(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 text-sm w-full"
            placeholder="40"
          />
        </div>
      </div>

      {/* Reducer / flange options */}
      {(selectedType?.hasReducer || selectedType?.hasFlange) && (
        <div className="grid grid-cols-2 gap-3">
          {selectedType.hasReducer && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">DN branch / small end</label>
              <select
                value={dnBranch}
                onChange={e => setDnBranch(Number(e.target.value))}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm w-full"
              >
                {DN_OPTIONS.filter(d => d < dn).map(d => (
                  <option key={d} value={d}>DN{d}</option>
                ))}
              </select>
            </div>
          )}
          {selectedType.hasFlange && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Flange class (B16.5)</label>
              <select
                value={flangeClass}
                onChange={e => setFlangeClass(Number(e.target.value))}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm w-full"
              >
                {FLANGE_CLASSES.map(c => <option key={c} value={c}>Class {c}</option>)}
              </select>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Quantity</label>
          <input
            type="number"
            min="1"
            value={quantity}
            onChange={e => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
            className="border border-gray-300 rounded px-2 py-1.5 text-sm w-20"
          />
        </div>
        <button
          onClick={handleLookup}
          disabled={loading}
          className="mt-4 flex items-center gap-2 bg-blue-600 hover:bg-blue-700
                     disabled:opacity-50 text-white text-sm px-4 py-2 rounded"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Package size={14} />}
          Look up
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 border border-red-200 rounded p-3">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {result && result.ok && (
        <div className="border border-gray-200 rounded p-4 space-y-3">
          <div className="flex items-start justify-between">
            <div>
              <span className="text-xs font-medium text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                {result.standard}
              </span>
              <p className="mt-1 text-sm font-medium text-gray-800">{result.notes}</p>
            </div>
            <button
              onClick={handleAddToBOM}
              className="flex items-center gap-1 text-xs text-green-600 hover:text-green-800
                         border border-green-200 hover:border-green-400 rounded px-2 py-1"
            >
              <Plus size={12} /> Add to BOM
            </button>
          </div>

          {/* Dimension summary */}
          <div className="grid grid-cols-3 gap-2">
            {[
              ['OD', `${result.od_mm?.toFixed(3)} mm`, 'ASME B36.10M'],
              ['Centre-to-face', `${result.center_to_face_mm?.toFixed(1)} mm`, ''],
              ['Face-to-face', `${result.face_to_face_mm?.toFixed(1)} mm`, ''],
            ].map(([label, val, sub]) => (
              <div key={label} className="bg-gray-50 rounded p-2 text-center">
                <div className="text-xs text-gray-500">{label}</div>
                <div className="font-semibold text-gray-800 text-sm font-mono">{val}</div>
                {sub && <div className="text-xs text-gray-400">{sub}</div>}
              </div>
            ))}
          </div>

          {/* Port geometry */}
          <PortDiagram ports={result.ports} />
        </div>
      )}

      {/* BOM accumulator */}
      {bomLines.length > 0 && (
        <div className="mt-4">
          <div className="flex items-center justify-between mb-2">
            <h4 className="font-medium text-sm text-gray-700 flex items-center gap-1">
              <Package size={14} /> Fitting BOM
            </h4>
            <button onClick={clearBOM} className="text-xs text-red-500 hover:text-red-700">
              Clear all
            </button>
          </div>
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-gray-100">
                <th className="px-2 py-1 text-left border border-gray-200">Type</th>
                <th className="px-2 py-1 text-right border border-gray-200">DN</th>
                <th className="px-2 py-1 text-right border border-gray-200">Sch</th>
                <th className="px-2 py-1 text-right border border-gray-200">Qty</th>
                <th className="px-2 py-1 text-right border border-gray-200">F-to-F (mm)</th>
                <th className="px-2 py-1 text-left border border-gray-200">Standard</th>
                <th className="px-2 py-1 border border-gray-200" />
              </tr>
            </thead>
            <tbody>
              {bomLines.map((row, i) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="px-2 py-1 border border-gray-200 font-mono">{row.item}</td>
                  <td className="px-2 py-1 border border-gray-200 text-right">DN{row.dn}</td>
                  <td className="px-2 py-1 border border-gray-200 text-right">{row.schedule}</td>
                  <td className="px-2 py-1 border border-gray-200 text-right font-semibold">{row.quantity}</td>
                  <td className="px-2 py-1 border border-gray-200 text-right font-mono">
                    {row.face_to_face_mm?.toFixed(1) ?? '—'}
                  </td>
                  <td className="px-2 py-1 border border-gray-200 text-gray-500 text-xs">{row.standard}</td>
                  <td className="px-2 py-1 border border-gray-200">
                    <button onClick={() => removeLine(i)} className="text-red-400 hover:text-red-600">
                      <Trash2 size={10} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-2 text-right text-xs text-gray-400">
            Total items: {bomLines.reduce((s, l) => s + l.quantity, 0)}
          </div>
        </div>
      )}
    </div>
  )
}
