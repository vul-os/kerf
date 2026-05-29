// BuildingEnergyPanel.jsx — Zone-by-zone building energy load editor.
//
// Lets the user configure occupancy, lighting, equipment, infiltration, and
// HVAC efficiency for multiple zones, then dispatches to the backend to get:
//   • Annual energy breakdown (heating/cooling/lighting/equipment) per zone
//   • EnergyPlus IDF export (text format)
//   • Monthly load profile for MonthlyLoadChart
//
// Dispatches via POST /api/projects/:pid/energy/building
//
// Props: { projectId: string }

import { useState, useCallback } from 'react'
import { Building2, Play, Download, AlertTriangle, Plus, Trash2, ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../../lib/api.js'
import MonthlyLoadChart from './MonthlyLoadChart.jsx'

// ---------------------------------------------------------------------------
// Default zone template
// ---------------------------------------------------------------------------

function defaultZone(idx) {
  return {
    id: `zone_${idx}`,
    name: `Zone ${idx + 1}`,
    floor_area_m2: 50,
    height_m: 3.0,
    // Occupancy
    num_people: 2,
    schedule: 'office',       // office | residential | retail | warehouse
    // Envelope
    wall_u_value: 0.35,       // W/(m²·K)
    window_area_m2: 8,
    window_u_value: 1.8,
    window_shgc: 0.4,
    infiltration_ach: 0.5,
    // Internal gains
    lighting_w_m2: 10,
    equipment_w_m2: 15,
    // HVAC
    hvac_cop_heating: 3.5,    // COP (heat pump) or AFUE fraction
    hvac_cop_cooling: 3.0,
    setpoint_heating_c: 21,
    setpoint_cooling_c: 26,
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SCHEDULES = [
  { value: 'office',      label: 'Office (9-17)' },
  { value: 'residential', label: 'Residential (24h)' },
  { value: 'retail',      label: 'Retail (8-20)' },
  { value: 'warehouse',   label: 'Warehouse (6-18)' },
]

function fmt2(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

function fmtKwh(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${n.toFixed(0)} kWh`
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function FieldRow({ label, hint, children }) {
  return (
    <div className="flex items-start gap-2 mb-1.5">
      <label className="text-[11px] text-ink-400 w-36 flex-shrink-0 pt-1.5 leading-tight">
        {label}
        {hint && <span className="block text-[10px] text-ink-600">{hint}</span>}
      </label>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  )
}

function NumInput({ value, onChange, min, step = 'any', disabled, placeholder }) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      min={min}
      step={step}
      disabled={disabled}
      placeholder={placeholder}
      className="w-full h-7 bg-ink-900 border border-ink-800 rounded px-2 text-xs text-ink-100 focus:outline-none focus:border-kerf-300 focus-visible:ring-1 focus-visible:ring-kerf-300 disabled:opacity-50 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
    />
  )
}

function ZoneCard({ zone, idx, onChange, onRemove }) {
  const [expanded, setExpanded] = useState(idx === 0)

  const set = (field, val) => onChange(idx, { ...zone, [field]: val })

  return (
    <div className="border border-ink-800 rounded-md overflow-hidden mb-2">
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-1.5 bg-ink-900 cursor-pointer hover:bg-ink-800/50"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-2">
          <Building2 size={12} className="text-kerf-300" />
          <input
            type="text"
            value={zone.name}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => set('name', e.target.value)}
            className="bg-transparent text-xs text-ink-200 font-medium focus:outline-none focus:text-kerf-300 w-32"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-ink-600">{zone.floor_area_m2} m²</span>
          {expanded ? <ChevronUp size={12} className="text-ink-500" /> : <ChevronDown size={12} className="text-ink-500" />}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onRemove(idx) }}
            aria-label={`Remove ${zone.name}`}
            className="text-ink-600 hover:text-amber-400 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300 rounded"
          >
            <Trash2 size={11} />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="px-3 py-2 space-y-3 bg-ink-950/40">
          {/* Geometry */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-ink-600 mb-1.5">Geometry</div>
            <div className="grid grid-cols-2 gap-x-3">
              <FieldRow label="Floor area (m²)">
                <NumInput value={zone.floor_area_m2} onChange={(v) => set('floor_area_m2', v)} min={1} />
              </FieldRow>
              <FieldRow label="Height (m)">
                <NumInput value={zone.height_m} onChange={(v) => set('height_m', v)} min={1} />
              </FieldRow>
            </div>
          </div>

          {/* Envelope */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-ink-600 mb-1.5">Envelope</div>
            <div className="grid grid-cols-2 gap-x-3">
              <FieldRow label="Wall U (W/m²·K)">
                <NumInput value={zone.wall_u_value} onChange={(v) => set('wall_u_value', v)} min={0} />
              </FieldRow>
              <FieldRow label="Infiltration (ACH)">
                <NumInput value={zone.infiltration_ach} onChange={(v) => set('infiltration_ach', v)} min={0} />
              </FieldRow>
              <FieldRow label="Window area (m²)">
                <NumInput value={zone.window_area_m2} onChange={(v) => set('window_area_m2', v)} min={0} />
              </FieldRow>
              <FieldRow label="Window U (W/m²·K)">
                <NumInput value={zone.window_u_value} onChange={(v) => set('window_u_value', v)} min={0} />
              </FieldRow>
              <FieldRow label="Window SHGC">
                <NumInput value={zone.window_shgc} onChange={(v) => set('window_shgc', v)} min={0} step={0.01} />
              </FieldRow>
            </div>
          </div>

          {/* Occupancy + Internal Gains */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-ink-600 mb-1.5">Occupancy &amp; Internal Gains</div>
            <div className="grid grid-cols-2 gap-x-3">
              <FieldRow label="People">
                <NumInput value={zone.num_people} onChange={(v) => set('num_people', v)} min={0} step={1} />
              </FieldRow>
              <FieldRow label="Schedule">
                <select
                  value={zone.schedule}
                  onChange={(e) => set('schedule', e.target.value)}
                  className="w-full h-7 bg-ink-900 border border-ink-800 rounded px-2 text-xs text-ink-100 focus:outline-none focus:border-kerf-300 focus-visible:ring-1 focus-visible:ring-kerf-300"
                >
                  {SCHEDULES.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </FieldRow>
              <FieldRow label="Lighting (W/m²)">
                <NumInput value={zone.lighting_w_m2} onChange={(v) => set('lighting_w_m2', v)} min={0} />
              </FieldRow>
              <FieldRow label="Equipment (W/m²)">
                <NumInput value={zone.equipment_w_m2} onChange={(v) => set('equipment_w_m2', v)} min={0} />
              </FieldRow>
            </div>
          </div>

          {/* HVAC */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-ink-600 mb-1.5">HVAC</div>
            <div className="grid grid-cols-2 gap-x-3">
              <FieldRow label="Heating COP" hint="or AFUE">
                <NumInput value={zone.hvac_cop_heating} onChange={(v) => set('hvac_cop_heating', v)} min={0.1} />
              </FieldRow>
              <FieldRow label="Cooling COP">
                <NumInput value={zone.hvac_cop_cooling} onChange={(v) => set('hvac_cop_cooling', v)} min={0.1} />
              </FieldRow>
              <FieldRow label="Heat setpoint (°C)">
                <NumInput value={zone.setpoint_heating_c} onChange={(v) => set('setpoint_heating_c', v)} />
              </FieldRow>
              <FieldRow label="Cool setpoint (°C)">
                <NumInput value={zone.setpoint_cooling_c} onChange={(v) => set('setpoint_cooling_c', v)} />
              </FieldRow>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Result display
// ---------------------------------------------------------------------------

function ResultRow({ label, value, unit, accent }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-ink-800 last:border-0">
      <span className="text-[11px] text-ink-400">{label}</span>
      <span className={`font-mono tabular-nums text-[11px] ${accent ? 'text-kerf-300 font-semibold' : 'text-ink-200'}`}>
        {value}{unit ? ` ${unit}` : ''}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function BuildingEnergyPanel({ projectId }) {
  const [zones, setZones] = useState([defaultZone(0)])
  const [location, setLocation] = useState({ latitude: 51.5, longitude: -0.12, hdd: 2700, cdd: 150 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [idfExpanded, setIdfExpanded] = useState(false)

  const handleZoneChange = useCallback((idx, updated) => {
    setZones((prev) => prev.map((z, i) => (i === idx ? updated : z)))
    setResult(null)
  }, [])

  const handleZoneRemove = useCallback((idx) => {
    setZones((prev) => prev.filter((_, i) => i !== idx))
    setResult(null)
  }, [])

  const handleAddZone = useCallback(() => {
    setZones((prev) => [...prev, defaultZone(prev.length)])
  }, [])

  const handleRun = useCallback(async () => {
    if (!projectId) { setError('No project context.'); return }
    if (zones.length === 0) { setError('Add at least one zone.'); return }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const body = {
        zones: zones.map((z) => ({
          name: z.name,
          floor_area_m2: parseFloat(z.floor_area_m2) || 50,
          height_m: parseFloat(z.height_m) || 3,
          num_people: parseInt(z.num_people, 10) || 0,
          schedule: z.schedule,
          wall_u_value: parseFloat(z.wall_u_value) || 0.35,
          window_area_m2: parseFloat(z.window_area_m2) || 0,
          window_u_value: parseFloat(z.window_u_value) || 1.8,
          window_shgc: parseFloat(z.window_shgc) || 0.4,
          infiltration_ach: parseFloat(z.infiltration_ach) || 0.5,
          lighting_w_m2: parseFloat(z.lighting_w_m2) || 0,
          equipment_w_m2: parseFloat(z.equipment_w_m2) || 0,
          hvac_cop_heating: parseFloat(z.hvac_cop_heating) || 3.5,
          hvac_cop_cooling: parseFloat(z.hvac_cop_cooling) || 3.0,
          setpoint_heating_c: parseFloat(z.setpoint_heating_c) ?? 21,
          setpoint_cooling_c: parseFloat(z.setpoint_cooling_c) ?? 26,
        })),
        location: {
          latitude: parseFloat(location.latitude) || 51.5,
          longitude: parseFloat(location.longitude) || -0.12,
          hdd: parseFloat(location.hdd) || 2700,
          cdd: parseFloat(location.cdd) || 150,
        },
        export_idf: true,
      }
      const data = await api.buildingEnergy(projectId, body)
      setResult(data)
    } catch (err) {
      setError(err?.message || 'API error')
    } finally {
      setLoading(false)
    }
  }, [projectId, zones, location])

  const handleDownloadIdf = useCallback(() => {
    if (!result?.idf) return
    const blob = new Blob([result.idf], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'model.idf'
    a.click()
    URL.revokeObjectURL(url)
  }, [result])

  return (
    <div className="h-full flex flex-col min-h-0 bg-ink-950 text-ink-100" data-testid="building-energy-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-ink-800 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Building2 size={14} className="text-kerf-300" aria-hidden="true" />
          <span className="text-xs font-semibold uppercase tracking-wider text-ink-300">
            Building Energy
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRun}
            disabled={loading}
            aria-label={loading ? 'Running…' : 'Run annual energy simulation'}
            className="inline-flex items-center gap-1.5 px-3 py-1 rounded bg-kerf-300 text-ink-950 text-xs font-medium hover:bg-kerf-200 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300"
          >
            <Play size={11} aria-hidden="true" />
            {loading ? 'Running…' : 'Run'}
          </button>
          {result?.idf && (
            <button
              type="button"
              onClick={handleDownloadIdf}
              aria-label="Download EnergyPlus IDF"
              title="Download EnergyPlus IDF"
              className="inline-flex items-center gap-1 px-2 py-1 rounded border border-ink-700 text-ink-400 text-xs hover:border-ink-500 hover:text-ink-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300"
            >
              <Download size={11} /> IDF
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto min-h-0 p-4 space-y-4">

        {/* Location */}
        <section>
          <div className="text-[10px] uppercase tracking-wider text-ink-500 mb-2">Location / Climate</div>
          <div className="grid grid-cols-2 gap-x-3">
            <FieldRow label="Latitude (°)">
              <NumInput value={location.latitude} onChange={(v) => setLocation((l) => ({ ...l, latitude: v }))} />
            </FieldRow>
            <FieldRow label="Longitude (°)">
              <NumInput value={location.longitude} onChange={(v) => setLocation((l) => ({ ...l, longitude: v }))} />
            </FieldRow>
            <FieldRow label="HDD (K·day)" hint="heating degree-days">
              <NumInput value={location.hdd} onChange={(v) => setLocation((l) => ({ ...l, hdd: v }))} min={0} />
            </FieldRow>
            <FieldRow label="CDD (K·day)" hint="cooling degree-days">
              <NumInput value={location.cdd} onChange={(v) => setLocation((l) => ({ ...l, cdd: v }))} min={0} />
            </FieldRow>
          </div>
        </section>

        {/* Zones */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <div className="text-[10px] uppercase tracking-wider text-ink-500">Zones ({zones.length})</div>
            <button
              type="button"
              onClick={handleAddZone}
              aria-label="Add zone"
              className="inline-flex items-center gap-1 text-[11px] text-kerf-300 hover:text-kerf-200 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300 rounded"
            >
              <Plus size={11} /> Add zone
            </button>
          </div>
          {zones.map((zone, i) => (
            <ZoneCard
              key={zone.id}
              zone={zone}
              idx={i}
              onChange={handleZoneChange}
              onRemove={handleZoneRemove}
            />
          ))}
        </section>

        {/* Error */}
        {error && (
          <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30">
            <AlertTriangle size={12} className="text-amber-400 mt-0.5 flex-shrink-0" />
            <span className="text-[11px] text-amber-200">{error}</span>
          </div>
        )}

        {/* Results */}
        {result && (
          <>
            {/* Annual totals */}
            <section>
              <div className="text-[10px] uppercase tracking-wider text-ink-500 mb-2">Annual Totals</div>
              <div className="bg-ink-900 rounded-md px-3 py-1">
                <ResultRow label="Heating" value={fmtKwh(result.totals?.heating_kWh)} />
                <ResultRow label="Cooling" value={fmtKwh(result.totals?.cooling_kWh)} />
                <ResultRow label="Lighting" value={fmtKwh(result.totals?.lighting_kWh)} />
                <ResultRow label="Equipment" value={fmtKwh(result.totals?.equipment_kWh)} />
                <ResultRow
                  label="EUI"
                  value={fmt2(result.totals?.eui_kWh_m2)}
                  unit="kWh/(m²·yr)"
                  accent
                />
              </div>
            </section>

            {/* Monthly chart */}
            {result.monthly && result.monthly.length > 0 && (
              <section>
                <div className="text-[10px] uppercase tracking-wider text-ink-500 mb-2">Monthly Profile</div>
                <div className="bg-ink-900 rounded-md p-3 overflow-x-auto">
                  <MonthlyLoadChart data={result.monthly} width={480} height={200} title="" />
                </div>
              </section>
            )}

            {/* IDF preview */}
            {result.idf && (
              <section>
                <div
                  className="flex items-center justify-between cursor-pointer mb-1"
                  onClick={() => setIdfExpanded((v) => !v)}
                >
                  <div className="text-[10px] uppercase tracking-wider text-ink-500">EnergyPlus IDF</div>
                  {idfExpanded ? <ChevronUp size={12} className="text-ink-600" /> : <ChevronDown size={12} className="text-ink-600" />}
                </div>
                {idfExpanded && (
                  <pre className="text-[10px] font-mono text-ink-400 bg-ink-900 rounded-md p-3 overflow-auto max-h-48 whitespace-pre">
                    {result.idf.slice(0, 3000)}
                    {result.idf.length > 3000 ? '\n[truncated…]' : ''}
                  </pre>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}
