// BuildingEnergyExportPanel.jsx — gbXML / EnergyPlus IDF export panel.
//
// Converts zone thermal properties into a building energy model interchange
// file for import into HVAC simulation tools (TRACE 3D Plus, eQUEST, HAP,
// IDA ICE, EnergyPlus / OpenStudio).
//
// Backend tool: be_export_energy_model
//   - gbXML v0.37 — ASHRAE/buildingSMART interchange standard
//   - EnergyPlus IDF v23.1 — US-DOE simulation engine input format
//
// References:
//   gbXML v0.37 — https://www.gbxml.org/schema_doc/4.0/GreenBuildingXML_Ver4.01.html
//   ASHRAE 90.1-2022 — envelope U-value prescriptive defaults
//   EnergyPlus 23.1 Input-Output Reference
//
// Props: { projectId: string }

import { useState, useCallback } from 'react'
import {
  Building2, Download, Play, AlertTriangle, Plus, Trash2,
  ChevronDown, ChevronUp, FileCode2
} from 'lucide-react'
import { api } from '../../lib/api.js'

// ---------------------------------------------------------------------------
// Climate zones
// ---------------------------------------------------------------------------

const CLIMATE_ZONES = [
  '1A','1B','2A','2B','3A','3B','3C','4A','4B','4C','5A','5B','5C','6A','6B','7','8'
]

// ASHRAE 90.1-2022 Table 5.5-1 to 5.5-8 representative defaults (W/m²·K)
const CZ_DEFAULTS = {
  '1A': { wall: 0.857, roof: 0.273, window: 6.81, shgc: 0.25 },
  '2A': { wall: 0.702, roof: 0.273, window: 3.69, shgc: 0.25 },
  '2B': { wall: 0.702, roof: 0.273, window: 3.69, shgc: 0.25 },
  '3A': { wall: 0.513, roof: 0.273, window: 2.84, shgc: 0.25 },
  '3B': { wall: 0.513, roof: 0.162, window: 2.84, shgc: 0.25 },
  '3C': { wall: 0.513, roof: 0.162, window: 2.84, shgc: 0.40 },
  '4A': { wall: 0.350, roof: 0.162, window: 2.84, shgc: 0.40 },
  '4B': { wall: 0.350, roof: 0.162, window: 2.84, shgc: 0.40 },
  '4C': { wall: 0.350, roof: 0.162, window: 2.84, shgc: 0.40 },
  '5A': { wall: 0.282, roof: 0.162, window: 1.99, shgc: 0.40 },
  '5B': { wall: 0.282, roof: 0.162, window: 1.99, shgc: 0.40 },
  '5C': { wall: 0.282, roof: 0.162, window: 1.99, shgc: 0.40 },
  '6A': { wall: 0.249, roof: 0.119, window: 1.99, shgc: 0.40 },
  '6B': { wall: 0.249, roof: 0.119, window: 1.99, shgc: 0.40 },
  '7':  { wall: 0.210, roof: 0.119, window: 1.99, shgc: 0.40 },
  '8':  { wall: 0.210, roof: 0.119, window: 1.99, shgc: 0.40 },
}

// ---------------------------------------------------------------------------
// Default zone
// ---------------------------------------------------------------------------

function defaultZone(idx) {
  return {
    zone_id:           `zone_${idx}`,
    name:              `Zone ${idx}`,
    floor_area_m2:     80,
    ceiling_height_m:  3.0,
    wall_area_m2:      0,       // 0 = auto (perimeter × height)
    wall_u_value:      0.35,
    window_area_m2:    12,
    window_u_value:    1.8,
    window_shgc:       0.4,
    roof_area_m2:      0,       // 0 = floor_area_m2
    roof_u_value:      0.20,
    floor_u_value:     0.25,
    infiltration_ach:  0.5,
    occupancy_people:  4,
    lighting_w_m2:     10,
    equipment_w_m2:    15,
    setpoint_heating_c: 21,
    setpoint_cooling_c: 26,
    latitude_deg:      0,
    longitude_deg:     0,
    elevation_m:       0,
    _open:             true,
  }
}

// ---------------------------------------------------------------------------
// ZoneEditor
// ---------------------------------------------------------------------------

function ZoneEditor({ zone, onChange, onRemove, idx }) {
  const [open, setOpen] = useState(zone._open ?? true)

  const set = (key, val) => onChange({ ...zone, [key]: val })

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
      <div
        className="flex items-center justify-between px-3 py-2 cursor-pointer"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2">
          <Building2 size={14} className="text-blue-500" />
          <span className="text-sm font-medium text-gray-800 dark:text-white">
            {zone.name || `Zone ${idx}`}
          </span>
          <span className="text-xs text-gray-400">{zone.floor_area_m2} m²</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={e => { e.stopPropagation(); onRemove() }}
            className="text-gray-400 hover:text-red-500 transition-colors"
          >
            <Trash2 size={13} />
          </button>
          {open ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
        </div>
      </div>

      {open && (
        <div className="px-3 pb-3 space-y-3">
          {/* Identity */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">Zone ID</label>
              <input
                value={zone.zone_id}
                onChange={e => set('zone_id', e.target.value.replace(/\s/g,'_'))}
                className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-xs dark:text-white"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">Zone Name</label>
              <input
                value={zone.name}
                onChange={e => set('name', e.target.value)}
                className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-xs dark:text-white"
              />
            </div>
          </div>

          {/* Geometry */}
          <div className="grid grid-cols-3 gap-2">
            {[
              ['Floor Area (m²)',      'floor_area_m2',    0.1],
              ['Ceiling Height (m)',   'ceiling_height_m', 0.1],
              ['Window Area (m²)',     'window_area_m2',   0.5],
            ].map(([label, key, step]) => (
              <div key={key}>
                <label className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">{label}</label>
                <input
                  type="number" step={step} value={zone[key]}
                  onChange={e => set(key, parseFloat(e.target.value))}
                  className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-xs dark:text-white"
                />
              </div>
            ))}
          </div>

          {/* Envelope */}
          <div className="grid grid-cols-4 gap-2">
            {[
              ['Wall U (W/m²K)',   'wall_u_value',   0.01],
              ['Window U (W/m²K)','window_u_value',  0.01],
              ['Window SHGC',     'window_shgc',     0.01],
              ['Roof U (W/m²K)',  'roof_u_value',    0.01],
            ].map(([label, key, step]) => (
              <div key={key}>
                <label className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">{label}</label>
                <input
                  type="number" step={step} value={zone[key]}
                  onChange={e => set(key, parseFloat(e.target.value))}
                  className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-xs dark:text-white"
                />
              </div>
            ))}
          </div>

          {/* Gains + HVAC */}
          <div className="grid grid-cols-4 gap-2">
            {[
              ['Infil. ACH',        'infiltration_ach',    0.1],
              ['Lighting (W/m²)',   'lighting_w_m2',       1],
              ['Equip. (W/m²)',     'equipment_w_m2',      1],
              ['Occupants',         'occupancy_people',    1],
            ].map(([label, key, step]) => (
              <div key={key}>
                <label className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">{label}</label>
                <input
                  type="number" step={step} value={zone[key]}
                  onChange={e => set(key, parseFloat(e.target.value))}
                  className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-xs dark:text-white"
                />
              </div>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-2">
            {[
              ['Heating SP (°C)', 'setpoint_heating_c', 1],
              ['Cooling SP (°C)', 'setpoint_cooling_c', 1],
            ].map(([label, key, step]) => (
              <div key={key}>
                <label className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">{label}</label>
                <input
                  type="number" step={step} value={zone[key]}
                  onChange={e => set(key, parseFloat(e.target.value))}
                  className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-xs dark:text-white"
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Panel
// ---------------------------------------------------------------------------

export default function BuildingEnergyExportPanel({ projectId }) {
  const [zones, setZones] = useState([defaultZone(1)])
  const [buildingName, setBuildingName] = useState('My Building')
  const [climateZone, setClimateZone] = useState('4A')
  const [fmt, setFmt] = useState('gbxml')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const updateZone = (idx, z) => {
    const next = [...zones]
    next[idx] = z
    setZones(next)
  }

  const removeZone = (idx) => setZones(z => z.filter((_, i) => i !== idx))

  const addZone = () => {
    const idx = zones.length + 1
    setZones(z => [...z, defaultZone(idx)])
  }

  const applyClimateDefaults = useCallback(() => {
    const d = CZ_DEFAULTS[climateZone]
    if (!d) return
    setZones(z => z.map(zone => ({
      ...zone,
      wall_u_value:   d.wall,
      roof_u_value:   d.roof,
      window_u_value: d.window,
      window_shgc:    d.shgc,
    })))
  }, [climateZone])

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await api.post(`/projects/${projectId}/tools/run`, {
        tool: 'be_export_energy_model',
        args: {
          format: fmt,
          building_name: buildingName,
          climate_zone: climateZone,
          zones: zones.map(({ _open, ...z }) => z),
        },
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.message || body.reason || `Request failed (${res.status})`)
        return
      }

      const body = await res.json()
      if (body.ok === false) {
        setError(body.reason || body.message || 'Export failed')
        return
      }
      setResult(body)
    } catch (err) {
      setError(err.message || 'Network error')
    } finally {
      setLoading(false)
    }
  }, [projectId, zones, buildingName, climateZone, fmt])

  const downloadResult = () => {
    if (!result?.content) return
    const blob = new Blob([result.content], { type: result.mime_type || 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = result.filename || `building_energy.${fmt}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-100 dark:bg-blue-900/40">
          <FileCode2 size={18} className="text-blue-600 dark:text-blue-400" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Building Energy Model Export</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            gbXML v0.37 · EnergyPlus IDF v23.1 · TRACE 3D / eQUEST / OpenStudio import
          </p>
        </div>
      </div>

      {/* Building settings */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="col-span-2">
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
            Building Name
          </label>
          <input
            value={buildingName}
            onChange={e => setBuildingName(e.target.value)}
            className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm dark:text-white"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
            ASHRAE Climate Zone
          </label>
          <div className="flex gap-1">
            <select
              value={climateZone}
              onChange={e => setClimateZone(e.target.value)}
              className="flex-1 rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm dark:text-white"
            >
              {CLIMATE_ZONES.map(cz => (
                <option key={cz} value={cz}>{cz}</option>
              ))}
            </select>
            <button
              onClick={applyClimateDefaults}
              title="Apply ASHRAE 90.1-2022 prescriptive U-values for this climate zone"
              className="rounded border border-blue-300 dark:border-blue-600 bg-blue-50 dark:bg-blue-900/30 px-2 py-1 text-xs text-blue-600 dark:text-blue-300 hover:bg-blue-100 transition-colors"
            >
              Apply defaults
            </button>
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
            Export Format
          </label>
          <select
            value={fmt}
            onChange={e => setFmt(e.target.value)}
            className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm dark:text-white"
          >
            <option value="gbxml">gbXML v0.37</option>
            <option value="idf">EnergyPlus IDF v23.1</option>
          </select>
        </div>
      </div>

      {/* Zones */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">
            Thermal Zones ({zones.length})
          </span>
          <button
            onClick={addZone}
            className="flex items-center gap-1 rounded px-2 py-1 text-xs text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors"
          >
            <Plus size={12} />Add Zone
          </button>
        </div>
        {zones.map((zone, idx) => (
          <ZoneEditor
            key={zone.zone_id + idx}
            zone={zone}
            idx={idx + 1}
            onChange={z => updateZone(idx, z)}
            onRemove={() => removeZone(idx)}
          />
        ))}
      </div>

      {/* Export button */}
      <button
        onClick={run}
        disabled={loading || zones.length === 0}
        className="flex items-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 text-sm font-semibold text-white transition-colors"
      >
        <Play size={14} />
        {loading ? 'Exporting…' : `Export ${fmt === 'gbxml' ? 'gbXML' : 'EnergyPlus IDF'}`}
      </button>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2">
          <AlertTriangle size={14} className="text-red-500 shrink-0" />
          <span className="text-xs text-red-600 dark:text-red-400">{error}</span>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="space-y-3">
          <div className="rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold text-green-800 dark:text-green-300">
                  Export complete — {result.filename}
                </div>
                <div className="text-xs text-green-700 dark:text-green-400 mt-0.5">
                  {result.n_zones} zone{result.n_zones !== 1 ? 's' : ''} · {result.climate_zone} climate zone · {result.byte_count.toLocaleString()} bytes
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {result.format === 'gbxml'
                    ? 'Import into TRACE 3D Plus, eQUEST, HAP, IDA ICE, or OpenStudio via File → Import gbXML.'
                    : 'Open in EnergyPlus 23.1 or OpenStudio. Attach an EPW weather file before simulation.'}
                </div>
              </div>
              <button
                onClick={downloadResult}
                className="flex items-center gap-1.5 rounded-lg border border-green-300 dark:border-green-600 bg-white dark:bg-green-900/30 px-3 py-1.5 text-sm text-green-700 dark:text-green-300 hover:bg-green-50 transition-colors"
              >
                <Download size={14} />
                Download
              </button>
            </div>
          </div>

          {/* Preview (first 60 lines) */}
          <div>
            <div className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Preview (first 50 lines):</div>
            <pre className="rounded bg-gray-900 text-gray-100 p-3 text-xs overflow-auto max-h-64 font-mono leading-relaxed">
              {result.content.split('\n').slice(0, 50).join('\n')}
              {result.content.split('\n').length > 50 ? '\n…' : ''}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
