/**
 * AirsideSystemPanel.jsx — AHU air-side system model panel.
 *
 * Displays:
 *   - AHU schematic (mixed air → cooling coil → heating coil → fan → zones)
 *   - Psychrometric state points table (T_db, T_dp, W, RH, h)
 *   - Coil energy summary (cooling: sensible + latent + SHR, condensate;
 *     heating: Q_reheat)
 *   - Fan power summary (supply + return, static pressure)
 *   - VAV terminal box table (zone, flow, damper %, load met, unmet)
 *   - Economizer status + free cooling indicator
 *   - Plant coupling (chiller load/power, boiler load)
 *
 * Dispatches to:
 *   POST /api/tools/call  { tool: "hvac.airside_system_model", args: {...} }
 */

import { useState, useCallback } from 'react'
import {
  Wind, Thermometer, Droplets, Zap, Activity,
  ChevronDown, ChevronRight, Loader2, AlertTriangle,
  CheckCircle, XCircle, Plus, Trash2,
} from 'lucide-react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Tool dispatch
// ---------------------------------------------------------------------------

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
// Sub-components
// ---------------------------------------------------------------------------

function Section({ title, icon: Icon, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-zinc-700 rounded-lg overflow-hidden mb-3">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-4 py-2 bg-zinc-800 text-sm font-medium text-zinc-200 hover:bg-zinc-750 transition-colors"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {Icon && <Icon size={14} className="text-zinc-400" />}
        {title}
      </button>
      {open && <div className="p-4 bg-zinc-900">{children}</div>}
    </div>
  )
}

function Stat({ label, value, unit, highlight }) {
  return (
    <div className={`flex flex-col gap-0.5 p-2 rounded ${highlight ? 'bg-blue-900/30 border border-blue-700/40' : 'bg-zinc-800'}`}>
      <span className="text-xs text-zinc-500">{label}</span>
      <span className="text-sm font-mono font-semibold text-zinc-100">
        {value} <span className="text-zinc-400 font-normal">{unit}</span>
      </span>
    </div>
  )
}

// AHU schematic SVG — simple block flow diagram
function AHUSchematic({ result }) {
  const free = result?.economizer?.free_cooling_active
  const boxCls = "fill-zinc-700 stroke-zinc-500"
  const activeCls = "fill-blue-900 stroke-blue-500"
  const textCls = "fill-zinc-200 text-xs"

  return (
    <svg
      viewBox="0 0 680 120"
      className="w-full h-28 select-none"
      style={{ fontFamily: 'monospace', fontSize: '11px' }}
    >
      {/* Flow arrow line */}
      <line x1="20" y1="60" x2="660" y2="60" stroke="#52525b" strokeWidth="1.5" strokeDasharray="4 2" />

      {/* OA inlet arrow */}
      <line x1="80" y1="20" x2="80" y2="58" stroke={free ? '#3b82f6' : '#71717a'} strokeWidth="2" markerEnd="url(#arr)" />
      <text x="60" y="16" fill={free ? '#60a5fa' : '#a1a1aa'} fontSize="10">{free ? '100% OA' : 'Min OA'}</text>

      {/* Mixing box */}
      <rect x="60" y="40" width="40" height="40" rx="4" className={boxCls} />
      <text x="63" y="62" fill="#e4e4e7" fontSize="9">Mix</text>
      <text x="63" y="73" fill="#e4e4e7" fontSize="9">Box</text>

      {/* Arrow */}
      <polygon points="108,57 116,60 108,63" fill="#71717a" />

      {/* Cooling coil */}
      <rect x="118" y="40" width="80" height="40" rx="4" fill="#1e3a5f" stroke="#3b82f6" />
      <text x="125" y="58" fill="#93c5fd" fontSize="9">Cooling</text>
      <text x="125" y="70" fill="#93c5fd" fontSize="9">Coil</text>
      {result && (
        <text x="122" y="83" fill="#60a5fa" fontSize="8">
          {(result.cooling_coil?.Q_total_kW || 0).toFixed(1)} kW
        </text>
      )}

      {/* Arrow */}
      <polygon points="206,57 214,60 206,63" fill="#71717a" />

      {/* Heating coil */}
      <rect x="216" y="40" width="80" height="40" rx="4"
        fill={result?.heating_coil?.active ? '#3f1f0f' : '#27272a'}
        stroke={result?.heating_coil?.active ? '#f97316' : '#3f3f46'} />
      <text x="223" y="58" fill={result?.heating_coil?.active ? '#fdba74' : '#71717a'} fontSize="9">Heating</text>
      <text x="223" y="70" fill={result?.heating_coil?.active ? '#fdba74' : '#71717a'} fontSize="9">Coil</text>
      {result?.heating_coil?.active && (
        <text x="220" y="83" fill="#fb923c" fontSize="8">
          {(result.heating_coil?.Q_kW || 0).toFixed(1)} kW
        </text>
      )}

      {/* Arrow */}
      <polygon points="304,57 312,60 304,63" fill="#71717a" />

      {/* Supply fan */}
      <rect x="314" y="40" width="70" height="40" rx="4" fill="#1a2a1a" stroke="#4ade80" />
      <text x="320" y="58" fill="#86efac" fontSize="9">Supply</text>
      <text x="320" y="70" fill="#86efac" fontSize="9">Fan</text>
      {result && (
        <text x="318" y="83" fill="#4ade80" fontSize="8">
          {((result.supply_fan?.motor_power_W || 0) / 1000).toFixed(1)} kW
        </text>
      )}

      {/* Arrow */}
      <polygon points="392,57 400,60 392,63" fill="#71717a" />

      {/* Duct */}
      <rect x="402" y="50" width="60" height="20" rx="2" fill="#27272a" stroke="#52525b" />
      <text x="410" y="64" fill="#a1a1aa" fontSize="9">Ductwork</text>
      {result && (
        <text x="404" y="83" fill="#71717a" fontSize="8">
          {(result.duct_system?.static_pressure_pa || 0).toFixed(0)} Pa
        </text>
      )}

      {/* Arrow */}
      <polygon points="470,57 478,60 470,63" fill="#71717a" />

      {/* VAV boxes */}
      <rect x="480" y="35" width="60" height="50" rx="4" fill="#1a1a2e" stroke="#818cf8" />
      <text x="487" y="55" fill="#a5b4fc" fontSize="9">VAV</text>
      <text x="487" y="67" fill="#a5b4fc" fontSize="9">Zones</text>
      {result && (
        <text x="483" y="80" fill="#818cf8" fontSize="8">
          {result.zone_results?.length || 0} zones
        </text>
      )}

      {/* Return air arrow */}
      <line x1="540" y1="60" x2="560" y2="60" stroke="#71717a" strokeWidth="1" />
      <text x="548" y="98" fill="#a1a1aa" fontSize="9">Return</text>

      {/* Arrow marker */}
      <defs>
        <marker id="arr" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
          <polygon points="0 0, 6 3, 0 6" fill="#71717a" />
        </marker>
      </defs>
    </svg>
  )
}

// Psychrometric state points table
function StatePointsTable({ statePoints }) {
  if (!statePoints) return null
  const order = ['outdoor_air', 'mixed_air', 'post_cooling_coil', 'supply_air', 'return_air']
  const labels = {
    outdoor_air: 'Outdoor Air (OA)',
    mixed_air: 'Mixed Air',
    post_cooling_coil: 'Post Cooling Coil',
    supply_air: 'Supply Air',
    return_air: 'Return Air (RA)',
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="border-b border-zinc-700">
            <th className="text-left text-zinc-400 py-1 pr-3">State Point</th>
            <th className="text-right text-zinc-400 py-1 px-2">T_db (°C)</th>
            <th className="text-right text-zinc-400 py-1 px-2">T_dp (°C)</th>
            <th className="text-right text-zinc-400 py-1 px-2">T_wb (°C)</th>
            <th className="text-right text-zinc-400 py-1 px-2">W (g/kg)</th>
            <th className="text-right text-zinc-400 py-1 px-2">RH (%)</th>
            <th className="text-right text-zinc-400 py-1 px-2">h (kJ/kg)</th>
          </tr>
        </thead>
        <tbody>
          {order.map(k => {
            const sp = statePoints[k]
            if (!sp) return null
            const highlight = k === 'supply_air'
            return (
              <tr key={k}
                className={`border-b border-zinc-800 ${highlight ? 'bg-blue-950/30' : ''}`}>
                <td className={`py-1 pr-3 ${highlight ? 'text-blue-300' : 'text-zinc-300'}`}>
                  {labels[k]}
                </td>
                <td className="text-right py-1 px-2 text-zinc-200">{sp.T_db_C?.toFixed(1)}</td>
                <td className="text-right py-1 px-2 text-zinc-400">{sp.T_dp_C?.toFixed(1)}</td>
                <td className="text-right py-1 px-2 text-zinc-400">{sp.T_wb_C?.toFixed(1)}</td>
                <td className="text-right py-1 px-2 text-zinc-300">
                  {sp.W_kg_kgda != null ? (sp.W_kg_kgda * 1000).toFixed(2) : '—'}
                </td>
                <td className="text-right py-1 px-2 text-zinc-300">
                  {sp.rh_fraction != null ? (sp.rh_fraction * 100).toFixed(0) : '—'}
                </td>
                <td className="text-right py-1 px-2 text-zinc-200">{sp.h_kj_kgda?.toFixed(1)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// VAV zone table
function VAVTable({ zones }) {
  if (!zones?.length) return <p className="text-zinc-500 text-xs">No zones.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="border-b border-zinc-700">
            <th className="text-left text-zinc-400 py-1 pr-3">Zone</th>
            <th className="text-right text-zinc-400 py-1 px-2">Flow (m³/s)</th>
            <th className="text-right text-zinc-400 py-1 px-2">T_supply (°C)</th>
            <th className="text-right text-zinc-400 py-1 px-2">Damper (%)</th>
            <th className="text-right text-zinc-400 py-1 px-2">Load Met (W)</th>
            <th className="text-right text-zinc-400 py-1 px-2">Unmet (W)</th>
          </tr>
        </thead>
        <tbody>
          {zones.map((z, i) => {
            const unmet = z.unmet_load_W
            const abs_unmet = Math.abs(unmet)
            const warn = abs_unmet > 200
            return (
              <tr key={i} className="border-b border-zinc-800 hover:bg-zinc-800/50">
                <td className="py-1 pr-3 text-zinc-300">{z.zone}</td>
                <td className="text-right py-1 px-2 text-zinc-200">{z.supply_flow_m3s?.toFixed(3)}</td>
                <td className="text-right py-1 px-2 text-zinc-200">{z.supply_T_C?.toFixed(1)}</td>
                <td className="text-right py-1 px-2">
                  <span className={`px-1 rounded text-xs ${
                    z.damper_position_pct > 90 ? 'bg-amber-900/50 text-amber-300' :
                    z.damper_position_pct < 30 ? 'bg-zinc-700 text-zinc-400' :
                    'text-zinc-200'
                  }`}>
                    {z.damper_position_pct?.toFixed(0)}%
                  </span>
                </td>
                <td className="text-right py-1 px-2 text-green-400">{z.zone_load_met_W?.toFixed(0)}</td>
                <td className={`text-right py-1 px-2 ${warn ? 'text-amber-400' : 'text-zinc-500'}`}>
                  {unmet?.toFixed(0)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Default form state
// ---------------------------------------------------------------------------

const DEFAULT_OA = { T_db_C: 32, rh_fraction: 0.60 }
const DEFAULT_RA = { T_db_C: 24, rh_fraction: 0.50 }
const DEFAULT_ZONES = [
  { name: 'Office-A', design_flow_m3s: 0.5, zone_load_W: 5000, zone_T_setpoint_C: 22, zone_T_current_C: 26, min_flow_fraction: 0.25 },
  { name: 'Office-B', design_flow_m3s: 0.3, zone_load_W: 2500, zone_T_setpoint_C: 22, zone_T_current_C: 24.5, min_flow_fraction: 0.25 },
  { name: 'Conference', design_flow_m3s: 0.4, zone_load_W: 7000, zone_T_setpoint_C: 22, zone_T_current_C: 27, min_flow_fraction: 0.25 },
]
const DEFAULT_AHU = {
  name: 'AHU-1', min_oa_fraction: 0.15, economizer_setpoint_C: 18,
  chw_supply_T_C: 7, chw_return_T_C: 12, cooling_coil_bypass_factor: 0.10,
  hw_supply_T_C: 60, supply_fan_efficiency: 0.70, duct_equivalent_length_m: 100,
}
const DEFAULT_PLANT = { chiller_cop: 5.5, boiler_efficiency: 0.92 }

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function AirsideSystemPanel() {
  const { token } = useAuth()

  const [oa, setOa] = useState(DEFAULT_OA)
  const [ra, setRa] = useState(DEFAULT_RA)
  const [zones, setZones] = useState(DEFAULT_ZONES)
  const [ahuCfg, setAhuCfg] = useState(DEFAULT_AHU)
  const [plantCfg, setPlantCfg] = useState(DEFAULT_PLANT)

  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const addZone = () => setZones(z => [...z, {
    name: `Zone-${z.length + 1}`,
    design_flow_m3s: 0.3,
    zone_load_W: 3000,
    zone_T_setpoint_C: 22,
    zone_T_current_C: 25,
    min_flow_fraction: 0.25,
  }])

  const removeZone = i => setZones(z => z.filter((_, j) => j !== i))

  const updateZone = (i, field, val) => setZones(z =>
    z.map((zone, j) => j === i ? { ...zone, [field]: val } : zone)
  )

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await callTool('hvac.airside_system_model', {
        outdoor_air: oa,
        return_air: ra,
        zones,
        ahu: ahuCfg,
        plant: plantCfg,
      }, token)
      if (res.error) throw new Error(res.error)
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [oa, ra, zones, ahuCfg, plantCfg, token])

  const F = ({ label, value, set, type = 'number', step = 0.1 }) => (
    <label className="flex flex-col gap-0.5">
      <span className="text-xs text-zinc-500">{label}</span>
      <input
        type={type} value={value} step={step}
        onChange={e => set(type === 'number' ? parseFloat(e.target.value) : e.target.value)}
        className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 w-full font-mono focus:outline-none focus:border-blue-500"
      />
    </label>
  )

  return (
    <div className="flex flex-col gap-4 p-4 text-zinc-200 max-w-4xl">
      <div className="flex items-center gap-3">
        <Wind size={20} className="text-blue-400" />
        <div>
          <h2 className="text-base font-semibold">AHU Air-Side System Model</h2>
          <p className="text-xs text-zinc-500">
            Psychrometrics · Cooling/Heating Coils · Economizer · VAV Boxes · Fan Power · Plant Coupling
          </p>
        </div>
      </div>

      {/* ---- Inputs ---- */}
      <Section title="Air Conditions" icon={Thermometer}>
        <div className="grid grid-cols-2 gap-6">
          <div>
            <p className="text-xs font-semibold text-zinc-400 mb-2">Outdoor Air</p>
            <div className="grid grid-cols-2 gap-2">
              <F label="T_db (°C)" value={oa.T_db_C} set={v => setOa(o => ({ ...o, T_db_C: v }))} />
              <F label="RH (0–1)" value={oa.rh_fraction} set={v => setOa(o => ({ ...o, rh_fraction: v }))} step={0.01} />
            </div>
          </div>
          <div>
            <p className="text-xs font-semibold text-zinc-400 mb-2">Return Air</p>
            <div className="grid grid-cols-2 gap-2">
              <F label="T_db (°C)" value={ra.T_db_C} set={v => setRa(o => ({ ...o, T_db_C: v }))} />
              <F label="RH (0–1)" value={ra.rh_fraction} set={v => setRa(o => ({ ...o, rh_fraction: v }))} step={0.01} />
            </div>
          </div>
        </div>
      </Section>

      <Section title="VAV Zones" icon={Activity}>
        <div className="space-y-2">
          {zones.map((z, i) => (
            <div key={i} className="grid grid-cols-6 gap-2 items-end bg-zinc-800/50 p-2 rounded">
              <label className="flex flex-col gap-0.5">
                <span className="text-xs text-zinc-500">Name</span>
                <input type="text" value={z.name}
                  onChange={e => updateZone(i, 'name', e.target.value)}
                  className="bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-xs text-zinc-200 font-mono focus:outline-none focus:border-blue-500" />
              </label>
              <label className="flex flex-col gap-0.5">
                <span className="text-xs text-zinc-500">Flow (m³/s)</span>
                <input type="number" step="0.1" value={z.design_flow_m3s}
                  onChange={e => updateZone(i, 'design_flow_m3s', parseFloat(e.target.value))}
                  className="bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-xs text-zinc-200 font-mono focus:outline-none focus:border-blue-500" />
              </label>
              <label className="flex flex-col gap-0.5">
                <span className="text-xs text-zinc-500">Load (W)</span>
                <input type="number" step="500" value={z.zone_load_W}
                  onChange={e => updateZone(i, 'zone_load_W', parseFloat(e.target.value))}
                  className="bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-xs text-zinc-200 font-mono focus:outline-none focus:border-blue-500" />
              </label>
              <label className="flex flex-col gap-0.5">
                <span className="text-xs text-zinc-500">Setpoint (°C)</span>
                <input type="number" step="0.5" value={z.zone_T_setpoint_C}
                  onChange={e => updateZone(i, 'zone_T_setpoint_C', parseFloat(e.target.value))}
                  className="bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-xs text-zinc-200 font-mono focus:outline-none focus:border-blue-500" />
              </label>
              <label className="flex flex-col gap-0.5">
                <span className="text-xs text-zinc-500">T_current (°C)</span>
                <input type="number" step="0.5" value={z.zone_T_current_C}
                  onChange={e => updateZone(i, 'zone_T_current_C', parseFloat(e.target.value))}
                  className="bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-xs text-zinc-200 font-mono focus:outline-none focus:border-blue-500" />
              </label>
              <button onClick={() => removeZone(i)}
                className="self-end flex items-center justify-center h-7 w-7 rounded bg-red-900/30 hover:bg-red-900/60 text-red-400 transition-colors">
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          <button onClick={addZone}
            className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors mt-1">
            <Plus size={13} /> Add Zone
          </button>
        </div>
      </Section>

      <Section title="AHU Configuration" icon={Wind} defaultOpen={false}>
        <div className="grid grid-cols-4 gap-3">
          <F label="Min OA fraction" value={ahuCfg.min_oa_fraction} set={v => setAhuCfg(c => ({ ...c, min_oa_fraction: v }))} step={0.01} />
          <F label="Economizer setpoint (°C)" value={ahuCfg.economizer_setpoint_C} set={v => setAhuCfg(c => ({ ...c, economizer_setpoint_C: v }))} />
          <F label="CHW supply (°C)" value={ahuCfg.chw_supply_T_C} set={v => setAhuCfg(c => ({ ...c, chw_supply_T_C: v }))} />
          <F label="CHW return (°C)" value={ahuCfg.chw_return_T_C} set={v => setAhuCfg(c => ({ ...c, chw_return_T_C: v }))} />
          <F label="Coil bypass factor" value={ahuCfg.cooling_coil_bypass_factor} set={v => setAhuCfg(c => ({ ...c, cooling_coil_bypass_factor: v }))} step={0.01} />
          <F label="Fan efficiency" value={ahuCfg.supply_fan_efficiency} set={v => setAhuCfg(c => ({ ...c, supply_fan_efficiency: v }))} step={0.01} />
          <F label="Duct equiv. length (m)" value={ahuCfg.duct_equivalent_length_m} set={v => setAhuCfg(c => ({ ...c, duct_equivalent_length_m: v }))} step={10} />
          <div className="grid grid-cols-2 gap-2 col-span-2">
            <F label="Chiller COP" value={plantCfg.chiller_cop} set={v => setPlantCfg(p => ({ ...p, chiller_cop: v }))} step={0.1} />
            <F label="Boiler efficiency" value={plantCfg.boiler_efficiency} set={v => setPlantCfg(p => ({ ...p, boiler_efficiency: v }))} step={0.01} />
          </div>
        </div>
      </Section>

      {/* Run button */}
      <button
        onClick={run}
        disabled={loading}
        className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-colors"
      >
        {loading ? <Loader2 size={15} className="animate-spin" /> : <Zap size={15} />}
        {loading ? 'Simulating…' : 'Run AHU Simulation'}
      </button>

      {error && (
        <div className="flex items-center gap-2 p-3 bg-red-950 border border-red-800 rounded-lg text-red-300 text-sm">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {/* ---- Results ---- */}
      {result && (
        <>
          {/* AHU Schematic */}
          <Section title="AHU Schematic" icon={Wind}>
            <AHUSchematic result={result} />
          </Section>

          {/* Economizer */}
          <Section title="Economizer" icon={Wind}>
            <div className="flex items-center gap-3 mb-3">
              {result.economizer?.free_cooling_active
                ? <><CheckCircle size={16} className="text-green-400" /><span className="text-green-300 text-sm font-medium">Free Cooling Active</span></>
                : <><XCircle size={16} className="text-zinc-500" /><span className="text-zinc-400 text-sm">Free Cooling Inactive</span></>
              }
              <span className="text-xs text-zinc-500 ml-2">{result.economizer?.oa_description}</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="OA Fraction" value={(result.economizer?.oa_fraction * 100).toFixed(0)} unit="%" highlight={result.economizer?.free_cooling_active} />
              <Stat label="Free Cooling Offset" value={((result.economizer?.free_cooling_load_W || 0) / 1000).toFixed(1)} unit="kW" />
            </div>
          </Section>

          {/* State Points */}
          <Section title="Psychrometric State Points" icon={Thermometer}>
            <StatePointsTable statePoints={result.state_points} />
          </Section>

          {/* Coil Energy */}
          <Section title="Coil Energy" icon={Droplets}>
            <div className="grid grid-cols-2 gap-6">
              <div>
                <p className="text-xs font-semibold text-blue-400 mb-2">Cooling Coil</p>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Total Load" value={result.cooling_coil?.Q_total_kW?.toFixed(1)} unit="kW" highlight />
                  <Stat label="Sensible" value={(result.cooling_coil?.Q_sensible_W / 1000).toFixed(1)} unit="kW" />
                  <Stat label="Latent" value={(result.cooling_coil?.Q_latent_W / 1000).toFixed(1)} unit="kW" />
                  <Stat label="SHR" value={result.cooling_coil?.SHR?.toFixed(3)} unit="" />
                  <Stat label="ADP" value={result.cooling_coil?.ADP_C?.toFixed(1)} unit="°C" />
                  <Stat label="Bypass Factor" value={result.cooling_coil?.bypass_factor?.toFixed(2)} unit="" />
                  <Stat label="Effectiveness" value={(result.cooling_coil?.effectiveness * 100).toFixed(0)} unit="%" />
                  <Stat label="Condensate" value={result.cooling_coil?.condensate_L_hr?.toFixed(1)} unit="L/hr" />
                </div>
              </div>
              <div>
                <p className={`text-xs font-semibold mb-2 ${result.heating_coil?.active ? 'text-orange-400' : 'text-zinc-500'}`}>
                  Heating Coil {!result.heating_coil?.active && '(inactive)'}
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Reheat Load" value={result.heating_coil?.Q_kW?.toFixed(1)} unit="kW" highlight={result.heating_coil?.active} />
                </div>
              </div>
            </div>
          </Section>

          {/* Fan Power */}
          <Section title="Fan Energy" icon={Activity}>
            <div className="grid grid-cols-4 gap-2">
              <Stat label="Supply Fan" value={(result.supply_fan?.motor_power_W / 1000).toFixed(2)} unit="kW" highlight />
              <Stat label="Supply Static" value={result.supply_fan?.static_pressure_pa?.toFixed(0)} unit="Pa" />
              <Stat label="Supply Temp Rise" value={result.supply_fan?.temp_rise_C?.toFixed(2)} unit="°C" />
              <Stat label="Return Fan" value={(result.return_fan?.motor_power_W / 1000).toFixed(2)} unit="kW" />
              <Stat label="Total Fan Power" value={(result.total_fan_power_kW)?.toFixed(2)} unit="kW" highlight />
              <Stat label="Duct Static" value={result.duct_system?.static_pressure_pa?.toFixed(0)} unit="Pa" />
            </div>
          </Section>

          {/* VAV Zones */}
          <Section title="VAV Terminal Boxes" icon={Activity}>
            <div className="mb-3">
              <Stat label="Total Zone Flow" value={result.total_zone_flow_m3s?.toFixed(3)} unit="m³/s" />
            </div>
            <VAVTable zones={result.vav_zones} />
          </Section>

          {/* Plant Coupling */}
          <Section title="Plant Coupling (Water-Side)" icon={Zap}>
            <div className="grid grid-cols-4 gap-2">
              <Stat label="Chiller Load" value={result.plant?.chiller_load_kW?.toFixed(1)} unit="kW" highlight />
              <Stat label="Chiller Power" value={result.plant?.chiller_power_kW?.toFixed(1)} unit="kW" />
              <Stat label="Boiler Load" value={(result.plant?.boiler_load_W / 1000).toFixed(1)} unit="kW" />
              <Stat label="Total System" value={result.plant?.total_system_power_kW?.toFixed(1)} unit="kW" />
            </div>
          </Section>
        </>
      )}

      <p className="text-xs text-zinc-600 italic mt-2">
        ASHRAE HOF 2021 psychrometrics + steady-state coil/fan models. Single design-point simulation.
        No transient controls or detailed duct-network solver.
      </p>
    </div>
  )
}
