/**
 * ImplantLibrary — filterable implant catalogue with click-to-place.
 *
 * Manufacturers: Straumann, Nobel Biocare, Zimmer, MIS.
 * Filter by manufacturer, diameter, length.
 * Click-to-place dispatches `dental_surgical_guide` via POST /api/tools/call.
 *
 * Backend tool: packages/kerf-dental/src/kerf_dental/tools.py → dental_surgical_guide
 */

import { useMemo, useState } from 'react'
import { useAuth } from '../../store/auth.js'
import { buildSurgicalGuidePayload } from './dentalDispatch.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Implant catalogue (representative geometry — not a clinical implant library)
// Each entry maps to the dental_surgical_guide `implants` schema.
// ---------------------------------------------------------------------------
const IMPLANT_CATALOGUE = [
  // Straumann
  { id: 'str-rc-33-10', manufacturer: 'Straumann', system: 'Bone Level RC', diameter_mm: 3.3, length_mm: 10, connection: 'RC', material: 'Ti Grade 4', note: 'Narrow platform' },
  { id: 'str-rc-41-10', manufacturer: 'Straumann', system: 'Bone Level RC', diameter_mm: 4.1, length_mm: 10, connection: 'RC', material: 'Ti Grade 4', note: 'Standard platform' },
  { id: 'str-rc-41-12', manufacturer: 'Straumann', system: 'Bone Level RC', diameter_mm: 4.1, length_mm: 12, connection: 'RC', material: 'Ti Grade 4', note: 'Standard platform long' },
  { id: 'str-rc-48-10', manufacturer: 'Straumann', system: 'Bone Level RC', diameter_mm: 4.8, length_mm: 10, connection: 'RC', material: 'Ti Grade 4', note: 'Wide platform' },
  { id: 'str-tl-41-10', manufacturer: 'Straumann', system: 'Tissue Level', diameter_mm: 4.1, length_mm: 10, connection: 'TL', material: 'Ti Grade 4', note: 'Tissue level' },

  // Nobel Biocare
  { id: 'nob-rp-40-10', manufacturer: 'Nobel Biocare', system: 'Replace', diameter_mm: 4.0, length_mm: 10, connection: 'RP', material: 'Ti-6Al-4V', note: 'Regular platform' },
  { id: 'nob-rp-40-13', manufacturer: 'Nobel Biocare', system: 'Replace', diameter_mm: 4.0, length_mm: 13, connection: 'RP', material: 'Ti-6Al-4V', note: 'Regular platform 13 mm' },
  { id: 'nob-np-35-10', manufacturer: 'Nobel Biocare', system: 'Replace', diameter_mm: 3.5, length_mm: 10, connection: 'NP', material: 'Ti-6Al-4V', note: 'Narrow platform' },
  { id: 'nob-cc-35-10', manufacturer: 'Nobel Biocare', system: 'Conical Connection', diameter_mm: 3.5, length_mm: 10, connection: 'CC', material: 'Ti-6Al-4V', note: 'Conical connection' },

  // Zimmer
  { id: 'zmb-ts3-40-10', manufacturer: 'Zimmer', system: 'Tapered Screw-Vent', diameter_mm: 4.0, length_mm: 10, connection: 'AH', material: 'Ti Grade 5', note: 'Hex connection' },
  { id: 'zmb-ts3-35-10', manufacturer: 'Zimmer', system: 'Tapered Screw-Vent', diameter_mm: 3.5, length_mm: 10, connection: 'AH', material: 'Ti Grade 5', note: 'Narrow hex' },
  { id: 'zmb-ts3-45-12', manufacturer: 'Zimmer', system: 'Tapered Screw-Vent', diameter_mm: 4.5, length_mm: 12, connection: 'AH', material: 'Ti Grade 5', note: 'Wide platform 12 mm' },

  // MIS
  { id: 'mis-v3-39-10', manufacturer: 'MIS', system: 'V3', diameter_mm: 3.9, length_mm: 10, connection: 'IC', material: 'Ti-6Al-4V', note: 'Internal conical' },
  { id: 'mis-v3-46-10', manufacturer: 'MIS', system: 'V3', diameter_mm: 4.6, length_mm: 10, connection: 'IC', material: 'Ti-6Al-4V', note: 'Wide platform IC' },
  { id: 'mis-c1-35-08', manufacturer: 'MIS', system: 'C1', diameter_mm: 3.5, length_mm: 8,  connection: 'IC', material: 'Ti-6Al-4V', note: 'Short implant' },
]

const MANUFACTURERS = ['All', 'Straumann', 'Nobel Biocare', 'Zimmer', 'MIS']
const DIAMETERS = ['All', '3.3', '3.5', '3.9', '4.0', '4.1', '4.5', '4.6', '4.8']
const LENGTHS   = ['All', '8', '10', '12', '13']

// Default jaw surface points (a simple flat jaw plane at z=0)
const DEFAULT_JAW_PTS = [
  [0, 0, 0], [20, 0, 0], [20, 15, 0],
  [10, 15, 0], [0, 15, 0],
]

// Default implant axis (upward into jaw)
const DEFAULT_AXIS = [0, 0, 1]

// ---------------------------------------------------------------------------
// ImplantCard — renders one entry in the list
// ---------------------------------------------------------------------------
function ImplantCard({ implant, selected, onSelect, onPlace, placing }) {
  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded border text-xs cursor-pointer transition-colors ${
        selected
          ? 'bg-cyan-500/15 border-cyan-400/50 text-cyan-200'
          : 'bg-ink-800 border-ink-700 text-ink-300 hover:bg-ink-700 hover:text-ink-100'
      }`}
      onClick={() => onSelect(implant.id)}
      data-testid={`implant-card-${implant.id}`}
    >
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{implant.system}</div>
        <div className="text-[10px] text-ink-500 font-mono">
          {implant.manufacturer} · ⌀{implant.diameter_mm} × {implant.length_mm} mm · {implant.connection}
        </div>
        <div className="text-[10px] text-ink-600">{implant.note}</div>
      </div>
      {selected && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onPlace(implant) }}
          disabled={placing}
          className="flex-shrink-0 px-2 py-1 rounded bg-cyan-500/20 border border-cyan-400/40 text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-50 whitespace-nowrap"
        >
          {placing ? (
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
              Placing…
            </span>
          ) : (
            'Place'
          )}
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------
export default function ImplantLibrary({ projectId }) {
  const { accessToken } = useAuth()
  const [manufacturer, setManufacturer] = useState('All')
  const [diameter, setDiameter]         = useState('All')
  const [length, setLength]             = useState('All')
  const [selectedId, setSelectedId]     = useState(null)
  const [placing, setPlacing]           = useState(false)
  const [result, setResult]             = useState(null)
  const [error, setError]               = useState(null)

  const filtered = useMemo(() => {
    return IMPLANT_CATALOGUE.filter((imp) => {
      if (manufacturer !== 'All' && imp.manufacturer !== manufacturer) return false
      if (diameter !== 'All' && String(imp.diameter_mm) !== diameter) return false
      if (length !== 'All' && String(imp.length_mm) !== length) return false
      return true
    })
  }, [manufacturer, diameter, length])

  function handleSelect(id) {
    setSelectedId((prev) => (prev === id ? null : id))
    setResult(null)
    setError(null)
  }

  async function handlePlace(implant) {
    setPlacing(true)
    setResult(null)
    setError(null)
    try {
      const body = buildSurgicalGuidePayload({
        jaw_surface_pts: DEFAULT_JAW_PTS,
        implants: [
          {
            position: [0, 0, 0],
            axis_direction: DEFAULT_AXIS,
            diameter_mm: implant.diameter_mm,
            length_mm: implant.length_mm,
          },
        ],
      })
      const res = await fetch(`${API_URL}/api/tools/call`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data?.error || `HTTP ${res.status}`)
      } else {
        setResult({ implant, response: data })
      }
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setPlacing(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4 text-ink-100" data-testid="implant-library-panel">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-mono uppercase tracking-widest text-ink-400">Implant Library</span>
        <span className="ml-auto text-[10px] text-ink-600 font-mono">dental_surgical_guide</span>
      </div>

      {/* Filters */}
      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="block text-[10px] text-ink-500 mb-1">Manufacturer</label>
          <select
            value={manufacturer}
            onChange={(e) => { setManufacturer(e.target.value); setSelectedId(null) }}
            className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-cyan-400/60"
          >
            {MANUFACTURERS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-ink-500 mb-1">Diameter (mm)</label>
          <select
            value={diameter}
            onChange={(e) => { setDiameter(e.target.value); setSelectedId(null) }}
            className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-cyan-400/60"
          >
            {DIAMETERS.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-ink-500 mb-1">Length (mm)</label>
          <select
            value={length}
            onChange={(e) => { setLength(e.target.value); setSelectedId(null) }}
            className="w-full bg-ink-800 border border-ink-700 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-cyan-400/60"
          >
            {LENGTHS.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
      </div>

      {/* Count */}
      <div className="text-[10px] text-ink-500 font-mono">
        {filtered.length} implant{filtered.length !== 1 ? 's' : ''} matched
      </div>

      {/* Implant list */}
      <div className="flex flex-col gap-1.5 max-h-72 overflow-y-auto pr-0.5">
        {filtered.length === 0 && (
          <div className="text-center text-ink-500 text-xs py-6">No implants match the current filters.</div>
        )}
        {filtered.map((imp) => (
          <ImplantCard
            key={imp.id}
            implant={imp}
            selected={selectedId === imp.id}
            onSelect={handleSelect}
            onPlace={handlePlace}
            placing={placing && selectedId === imp.id}
          />
        ))}
      </div>

      {/* Result */}
      {result && (
        <div
          className="rounded border border-cyan-700/50 bg-cyan-950/30 p-3 text-[11px] font-mono text-cyan-300 space-y-1"
          data-testid="implant-place-result"
        >
          <div className="text-cyan-400 font-semibold mb-1">Placed: {result.implant.system}</div>
          <div>manufacturer: <span className="text-cyan-200">{result.implant.manufacturer}</span></div>
          <div>diameter: <span className="text-cyan-200">{result.implant.diameter_mm} mm</span></div>
          <div>length: <span className="text-cyan-200">{result.implant.length_mm} mm</span></div>
          {result.response?.sleeve_count != null && (
            <div>sleeves: <span className="text-cyan-200">{result.response.sleeve_count}</span></div>
          )}
          {result.response?.max_angular_error_deg != null && (
            <div>max angular error: <span className="text-cyan-200">{result.response.max_angular_error_deg}°</span></div>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          className="rounded border border-red-700/50 bg-red-950/30 p-3 text-[11px] font-mono text-red-300"
          data-testid="implant-error"
        >
          {error}
        </div>
      )}

      {/* Footer note */}
      <p className="text-[10px] text-ink-600 leading-relaxed">
        Implant geometry is representative. Not a certified clinical implant library.
        Place sends fixture dimensions to the surgical guide backend for drill-sleeve positioning.
      </p>
    </div>
  )
}
