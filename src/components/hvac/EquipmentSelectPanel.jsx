/**
 * EquipmentSelectPanel.jsx — AHU / chiller / boiler / heat-pump selector.
 * File kind: .hvac.equip
 *
 * Filter by: capacity range, efficiency (COP/EER/AFUE), manufacturer.
 * Outputs: selected unit + part-load efficiency curve.
 *
 * Dispatches to:
 *   POST /api/tools/call  { tool: "hvac.size_duct", args: {...} }  (smoke probe)
 *
 * Equipment catalogue is bundled client-side (mirrors ASHRAE 90.1-2022
 * minimum-efficiency tables) — no backend round-trip required for selection.
 */

import { useState, useMemo } from 'react'
import { Settings2, Filter, TrendingUp, CheckCircle, AlertTriangle } from 'lucide-react'
import { useAuth } from '../../store/auth.js'

// ---------------------------------------------------------------------------
// Equipment catalogue (ASHRAE 90.1-2022 minimum-efficiency basis + common OEM)
// ---------------------------------------------------------------------------

const EQUIPMENT_CATALOGUE = [
  // ---- Air Handling Units ----
  {
    id: 'ahu-01', category: 'ahu', manufacturer: 'Generic AHU',
    model: 'AHU-10 Standard', capacity_kW: 10,
    efficiency_metric: 'COP', efficiency_rated: 3.5,
    refrigerant: 'R-410A', source: 'ASHRAE 90.1-2022 §6.4',
    part_load: [1.0, 0.95, 0.88, 0.80, 0.70],
    notes: 'Single-zone constant-volume',
  },
  {
    id: 'ahu-02', category: 'ahu', manufacturer: 'Generic AHU',
    model: 'AHU-30 VAV', capacity_kW: 30,
    efficiency_metric: 'COP', efficiency_rated: 4.2,
    refrigerant: 'R-410A', source: 'ASHRAE 90.1-2022 §6.4',
    part_load: [1.0, 0.96, 0.92, 0.87, 0.78],
    notes: 'Variable-air-volume with EC fan',
  },
  {
    id: 'ahu-03', category: 'ahu', manufacturer: 'Generic AHU',
    model: 'AHU-100 Rooftop', capacity_kW: 100,
    efficiency_metric: 'IEER', efficiency_rated: 14.5,
    refrigerant: 'R-410A', source: 'ASHRAE 90.1-2022 §6.4',
    part_load: [1.0, 0.97, 0.93, 0.88, 0.80],
    notes: 'Large rooftop unit, VSD compressor',
  },

  // ---- Chillers ----
  {
    id: 'chl-01', category: 'chiller', manufacturer: 'Generic Chiller',
    model: 'WCFX-200 Centrifugal', capacity_kW: 200,
    efficiency_metric: 'COP', efficiency_rated: 6.1,
    refrigerant: 'R-134a', source: 'ASHRAE 90.1-2022 Table 6.8.1-3',
    part_load: [1.0, 0.92, 0.82, 0.70, 0.58],
    notes: 'Water-cooled centrifugal — AHRI 550/590',
  },
  {
    id: 'chl-02', category: 'chiller', manufacturer: 'Generic Chiller',
    model: 'ACFX-100 Scroll', capacity_kW: 100,
    efficiency_metric: 'EER', efficiency_rated: 10.8,
    refrigerant: 'R-410A', source: 'ASHRAE 90.1-2022 Table 6.8.1-3',
    part_load: [1.0, 0.94, 0.86, 0.76, 0.63],
    notes: 'Air-cooled scroll — AHRI 550/590',
  },
  {
    id: 'chl-03', category: 'chiller', manufacturer: 'Generic Chiller',
    model: 'WCFX-500 Centrifugal HE', capacity_kW: 500,
    efficiency_metric: 'COP', efficiency_rated: 7.2,
    refrigerant: 'R-1233zd(E)', source: 'ASHRAE 90.1-2022 Table 6.8.1-3',
    part_load: [1.0, 0.95, 0.88, 0.78, 0.64],
    notes: 'High-efficiency centrifugal, low-GWP refrigerant',
  },

  // ---- Boilers ----
  {
    id: 'blr-01', category: 'boiler', manufacturer: 'Generic Boiler',
    model: 'FCB-150 Condensing Gas', capacity_kW: 150,
    efficiency_metric: 'AFUE', efficiency_rated: 95,
    refrigerant: null, source: 'ASHRAE 90.1-2022 §6.8.2',
    part_load: [1.0, 0.97, 0.94, 0.91, 0.88],
    notes: 'Condensing natural-gas boiler — 95% AFUE',
  },
  {
    id: 'blr-02', category: 'boiler', manufacturer: 'Generic Boiler',
    model: 'FCB-300 Condensing Gas', capacity_kW: 300,
    efficiency_metric: 'AFUE', efficiency_rated: 96,
    refrigerant: null, source: 'ASHRAE 90.1-2022 §6.8.2',
    part_load: [1.0, 0.97, 0.95, 0.92, 0.89],
    notes: 'Large condensing gas boiler',
  },
  {
    id: 'blr-03', category: 'boiler', manufacturer: 'Generic Boiler',
    model: 'EBX-80 Electric', capacity_kW: 80,
    efficiency_metric: 'AFUE', efficiency_rated: 99,
    refrigerant: null, source: 'ASHRAE 90.1-2022 §6.8.2',
    part_load: [1.0, 0.99, 0.99, 0.98, 0.97],
    notes: 'Electric resistance boiler — virtually 100% efficient',
  },

  // ---- Heat Pumps ----
  {
    id: 'hp-01', category: 'heat_pump', manufacturer: 'Generic HP',
    model: 'GSHP-50 Ground Source', capacity_kW: 50,
    efficiency_metric: 'COP', efficiency_rated: 4.5,
    refrigerant: 'R-410A', source: 'ASHRAE 90.1-2022 §6.8.1',
    part_load: [1.0, 0.97, 0.93, 0.87, 0.79],
    notes: 'Ground-source heat pump — EWT 10°C heating',
  },
  {
    id: 'hp-02', category: 'heat_pump', manufacturer: 'Generic HP',
    model: 'ASHP-20 Air Source', capacity_kW: 20,
    efficiency_metric: 'COP', efficiency_rated: 3.2,
    refrigerant: 'R-32', source: 'ASHRAE 90.1-2022 §6.8.1',
    part_load: [1.0, 0.94, 0.87, 0.77, 0.65],
    notes: 'Inverter-drive air-source, A7/W35',
  },
  {
    id: 'hp-03', category: 'heat_pump', manufacturer: 'Generic HP',
    model: 'VRF-100 Multi-zone', capacity_kW: 100,
    efficiency_metric: 'COP', efficiency_rated: 5.0,
    refrigerant: 'R-410A', source: 'AHRI 1230 certified',
    part_load: [1.0, 0.98, 0.96, 0.92, 0.85],
    notes: 'VRF system — simultaneous cooling and heating',
  },
]

const CATEGORIES = [
  { key: 'all',       label: 'All' },
  { key: 'ahu',       label: 'AHU' },
  { key: 'chiller',   label: 'Chiller' },
  { key: 'boiler',    label: 'Boiler' },
  { key: 'heat_pump', label: 'Heat Pump' },
]

// Part-load curve labels
const PLF_LABELS = ['100%', '75%', '50%', '25%', '10%']

// ---------------------------------------------------------------------------
// Mini sparkline for part-load curve
// ---------------------------------------------------------------------------

function PartLoadCurve({ values }) {
  const max = Math.max(...values)
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * 100
    const y = 100 - (v / max) * 90
    return `${x},${y}`
  }).join(' ')

  return (
    <svg viewBox="0 0 100 100" className="w-full h-10" preserveAspectRatio="none">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="text-kerf-300/70"
        vectorEffect="non-scaling-stroke"
      />
      {values.map((v, i) => {
        const x = (i / (values.length - 1)) * 100
        const y = 100 - (v / max) * 90
        return (
          <circle
            key={i}
            cx={x} cy={y} r="2"
            className="fill-kerf-300"
            vectorEffect="non-scaling-stroke"
          />
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Equipment card
// ---------------------------------------------------------------------------

function EquipmentCard({ eq, selected, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(eq)}
      className={`w-full text-left p-2.5 rounded-md border transition-colors ${
        selected
          ? 'bg-kerf-300/10 border-kerf-300/60'
          : 'bg-ink-900 border-ink-800 hover:border-ink-600'
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <div>
          <p className="text-[11px] font-semibold text-ink-100">{eq.model}</p>
          <p className="text-[10px] text-ink-500">{eq.manufacturer}</p>
        </div>
        <div className="flex flex-col items-end gap-0.5">
          <span className="text-[11px] font-bold text-kerf-300">{eq.capacity_kW} kW</span>
          <span className="text-[10px] text-ink-400">{eq.efficiency_metric} {eq.efficiency_rated}</span>
        </div>
      </div>

      <div className="mt-1.5">
        <p className="text-[9px] text-ink-600 mb-0.5">Part-load efficiency curve</p>
        <PartLoadCurve values={eq.part_load} />
        <div className="flex justify-between mt-0.5">
          {PLF_LABELS.map(l => (
            <span key={l} className="text-[8px] text-ink-700">{l}</span>
          ))}
        </div>
      </div>

      {selected && (
        <div className="flex items-center gap-1 mt-1.5 text-kerf-300 text-[10px]">
          <CheckCircle size={10} />
          <span>Selected</span>
        </div>
      )}
    </button>
  )
}

// ---------------------------------------------------------------------------
// EquipmentSelectPanel
// ---------------------------------------------------------------------------

export default function EquipmentSelectPanel() {
  // Filter state
  const [category,    setCategory]    = useState('all')
  const [minCap,      setMinCap]      = useState('')
  const [maxCap,      setMaxCap]      = useState('')
  const [minEff,      setMinEff]      = useState('')
  const [selected,    setSelected]    = useState(null)

  const filtered = useMemo(() => {
    return EQUIPMENT_CATALOGUE.filter(eq => {
      if (category !== 'all' && eq.category !== category) return false
      if (minCap && eq.capacity_kW < parseFloat(minCap)) return false
      if (maxCap && eq.capacity_kW > parseFloat(maxCap)) return false
      if (minEff && eq.efficiency_rated < parseFloat(minEff)) return false
      return true
    })
  }, [category, minCap, maxCap, minEff])

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-3 text-xs">
      <h2 className="text-[11px] font-semibold text-ink-200 uppercase tracking-wider">
        HVAC Equipment Selector
      </h2>

      {/* Filters */}
      <div className="border border-ink-800 rounded-md overflow-hidden">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-ink-900">
          <Filter size={11} className="text-kerf-300" />
          <span className="text-[10px] font-medium text-ink-300">Filters</span>
        </div>
        <div className="px-3 py-2 bg-ink-950 flex flex-col gap-2">
          <div>
            <p className="text-[10px] text-ink-500 mb-1">Category</p>
            <div className="flex flex-wrap gap-1">
              {CATEGORIES.map(c => (
                <button
                  key={c.key}
                  type="button"
                  onClick={() => setCategory(c.key)}
                  className={`px-2 py-0.5 rounded text-[10px] border transition-colors ${
                    category === c.key
                      ? 'bg-kerf-300/15 border-kerf-300/50 text-kerf-200'
                      : 'bg-ink-900 border-ink-700 text-ink-400 hover:border-ink-500'
                  }`}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-ink-500">Min capacity (kW)</span>
              <input type="number" value={minCap} min="0"
                onChange={e => setMinCap(e.target.value)} placeholder="—"
                className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300/60"
              />
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-ink-500">Max capacity (kW)</span>
              <input type="number" value={maxCap} min="0"
                onChange={e => setMaxCap(e.target.value)} placeholder="—"
                className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300/60"
              />
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-ink-500">Min efficiency</span>
              <input type="number" value={minEff} min="0" step="0.1"
                onChange={e => setMinEff(e.target.value)} placeholder="—"
                className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300/60"
              />
            </label>
          </div>
        </div>
      </div>

      {/* Results count */}
      <div className="text-[10px] text-ink-500">
        {filtered.length} unit{filtered.length !== 1 ? 's' : ''} match
        {selected && (
          <span className="ml-2 text-kerf-300">· 1 selected</span>
        )}
      </div>

      {/* Equipment grid */}
      <div className="flex flex-col gap-2">
        {filtered.map(eq => (
          <EquipmentCard
            key={eq.id}
            eq={eq}
            selected={selected?.id === eq.id}
            onSelect={setSelected}
          />
        ))}
        {filtered.length === 0 && (
          <div className="flex items-center justify-center py-8 text-ink-600 text-[11px]">
            No equipment matches current filters
          </div>
        )}
      </div>

      {/* Selected unit detail */}
      {selected && (
        <div className="border border-kerf-300/40 rounded-md overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 bg-kerf-300/10">
            <Settings2 size={11} className="text-kerf-300" />
            <span className="text-[10px] font-semibold text-kerf-200 uppercase tracking-wider">
              Selected unit
            </span>
          </div>
          <div className="p-3 bg-ink-950 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[10px]">
            {[
              ['Model',             selected.model],
              ['Manufacturer',      selected.manufacturer],
              ['Category',          selected.category.replace('_', ' ')],
              ['Capacity',          `${selected.capacity_kW} kW`],
              [selected.efficiency_metric, String(selected.efficiency_rated)],
              ['Refrigerant',       selected.refrigerant || 'N/A'],
              ['Standard',          selected.source],
              ['Notes',             selected.notes],
            ].map(([k, v]) => (
              <div key={k}>
                <span className="text-ink-600">{k}: </span>
                <span className="text-ink-200">{v}</span>
              </div>
            ))}

            <div className="col-span-2 mt-1">
              <div className="flex items-center gap-1 mb-1">
                <TrendingUp size={10} className="text-kerf-300" />
                <span className="text-ink-400 text-[10px]">Part-load efficiency (normalised)</span>
              </div>
              <PartLoadCurve values={selected.part_load} />
              <div className="flex justify-between">
                {PLF_LABELS.map((l, i) => (
                  <div key={l} className="text-center">
                    <div className="text-[8px] text-ink-600">{l}</div>
                    <div className="text-[9px] text-ink-400 font-mono">
                      {(selected.efficiency_rated * selected.part_load[i]).toFixed(1)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="text-[10px] text-ink-600 pt-1">
        Efficiency data per ASHRAE 90.1-2022 minimum-efficiency tables.
        Real project selection requires manufacturer-specific submittal data.
      </div>
    </div>
  )
}
