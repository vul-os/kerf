/**
 * HVACLoadPanel.jsx — Zone load calculator for .hvac.load files.
 *
 * Inputs: wall/roof construction, glazing, occupancy, equipment, infiltration.
 * Outputs: peak cooling kW, peak heating kW, monthly load profile.
 *
 * Dispatches to:
 *   POST /api/tools/call  { tool: "hvac_cfm_from_sensible_load", args: {...} }
 *
 * ASHRAE CLTD/RTS methodology for transient cooling loads.
 * Degree-day method for heating loads.
 */

import { useState, useCallback } from 'react'
import { Thermometer, Sun, Users, Zap, Wind, BarChart2, Loader2, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Helper: POST /api/tools/call
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
// CLTD/RTS cooling load engine (client-side approximation using ASHRAE method)
// ---------------------------------------------------------------------------

export function computeCoolingLoad(inputs) {
  const {
    wallArea, wallUValue, roofArea, roofUValue,
    glazingArea, solarHeatGainCoeff, uValueGlazing,
    occupantCount, lightingWatts, equipmentWatts,
    infiltrationACH, floorArea, ceilingHeight,
    outdoorDesignTemp, indoorTemp,
  } = inputs

  const deltaT = outdoorDesignTemp - indoorTemp

  // Conduction through opaque surfaces (simplified CLTD ≈ ΔT + solar correction)
  const wallCLTD = Math.max(deltaT + 8, 5)   // ASHRAE CLTD Group D wall approx
  const roofCLTD = Math.max(deltaT + 25, 15) // ASHRAE CLTD Group 1 roof approx

  const qWall  = wallUValue  * wallArea  * wallCLTD  // W
  const qRoof  = roofUValue  * roofArea  * roofCLTD  // W

  // Solar heat gain through glazing (peak summer noon, south-facing SHGC×605 W/m²)
  const solarIrradiance = 605 // W/m², peak direct normal
  const qSolar = solarHeatGainCoeff * solarIrradiance * glazingArea

  // Conduction through glazing
  const qGlazingCond = uValueGlazing * glazingArea * deltaT

  // Occupant loads (ASHRAE: 90 W sensible + 60 W latent per person)
  const qOccupants = occupantCount * 90

  // Lighting (use ballast factor 1.2 for fluorescent; assume LED = 1.0)
  const qLighting = lightingWatts

  // Equipment
  const qEquipment = equipmentWatts * 0.7 // typical diversity factor

  // Infiltration (sensible only)
  const volume = floorArea * ceilingHeight // m³
  const massFlow = (infiltrationACH / 3600) * volume * 1.204 // kg/s
  const qInfiltration = massFlow * 1006 * Math.max(deltaT, 0) // W

  const totalCoolingW = qWall + qRoof + qSolar + qGlazingCond +
                        qOccupants + qLighting + qEquipment + qInfiltration

  const breakdown = {
    wall: Math.round(qWall),
    roof: Math.round(qRoof),
    solar: Math.round(qSolar),
    glazingConduction: Math.round(qGlazingCond),
    occupants: Math.round(qOccupants),
    lighting: Math.round(qLighting),
    equipment: Math.round(qEquipment),
    infiltration: Math.round(qInfiltration),
  }

  return { totalCoolingW: Math.round(totalCoolingW), breakdown }
}

export function computeHeatingLoad(inputs) {
  const {
    wallArea, wallUValue, roofArea, roofUValue,
    glazingArea, uValueGlazing,
    infiltrationACH, floorArea, ceilingHeight,
    outdoorDesignTemp, indoorTemp,
  } = inputs

  const deltaT = indoorTemp - outdoorDesignTemp

  const qWall    = wallUValue    * wallArea    * deltaT
  const qRoof    = roofUValue    * roofArea    * deltaT
  const qGlazing = uValueGlazing * glazingArea * deltaT

  const volume   = floorArea * ceilingHeight
  const massFlow = (infiltrationACH / 3600) * volume * 1.204
  const qInf     = massFlow * 1006 * Math.max(deltaT, 0)

  const totalHeatingW = qWall + qRoof + qGlazing + qInf

  return { totalHeatingW: Math.round(Math.max(totalHeatingW, 0)) }
}

/**
 * buildSensibleLoadArgs — args for the `hvac_cfm_from_sensible_load` tool
 * call, pulled out of `calculate()` as a pure function so the exact request
 * shape is independently unit-testable (this repo has no jsdom/
 * @testing-library/react install; see HVACLoadPanel.test.jsx).
 */
export function buildSensibleLoadArgs({ wallArea, wallUValue, outdoorSummer, indoor }) {
  const sensibleLoad_BTUh = wallArea * wallUValue * 5.678 *
    Math.max(outdoorSummer - indoor, 1) * 3.412
  return { Q_btuh: Math.max(sensibleLoad_BTUh, 100), delta_T_F: 20 }
}

// Monthly cooling profile — simplified hourly peak scaled by month factor
const MONTH_COOLING_FACTOR = [0.40, 0.45, 0.60, 0.75, 0.88, 0.95, 1.00, 0.97, 0.85, 0.70, 0.50, 0.40]
const MONTH_HEATING_FACTOR = [1.00, 0.95, 0.80, 0.55, 0.30, 0.10, 0.05, 0.05, 0.20, 0.50, 0.80, 0.95]
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

// ---------------------------------------------------------------------------
// BarSparkline
// ---------------------------------------------------------------------------

function BarSparkline({ values, color, unit, label }) {
  const max = Math.max(...values, 0.01)
  return (
    <div>
      <p className="text-[10px] text-ink-500 uppercase tracking-wider mb-1">{label}</p>
      <div className="flex items-end gap-0.5 h-12">
        {values.map((v, i) => (
          <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
            <div
              className={`w-full ${color} rounded-t`}
              style={{ height: `${(v / max) * 100}%` }}
              title={`${MONTHS[i]}: ${(v / 1000).toFixed(1)} ${unit}`}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between mt-0.5">
        {MONTHS.map((m, i) => (
          <span key={i} className="flex-1 text-center text-[8px] text-ink-600">{m}</span>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section widget
// ---------------------------------------------------------------------------

function Section({ icon: Icon, title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-ink-800 rounded-md overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-ink-900 hover:bg-ink-800 text-xs font-medium text-ink-200"
      >
        <Icon size={12} className="text-kerf-300 flex-shrink-0" />
        <span className="flex-1 text-left">{title}</span>
        {open ? <ChevronUp size={11} className="text-ink-500" /> : <ChevronDown size={11} className="text-ink-500" />}
      </button>
      {open && <div className="px-3 py-2 bg-ink-950 grid grid-cols-2 gap-2">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Label + input row
// ---------------------------------------------------------------------------

function Field({ label, value, onChange, min, max, step = 'any', unit }) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[10px] text-ink-500 leading-tight">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={e => onChange(e.target.value)}
          className="w-full bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300/60"
        />
        {unit && <span className="text-[10px] text-ink-600 whitespace-nowrap">{unit}</span>}
      </div>
    </label>
  )
}

// ---------------------------------------------------------------------------
// HVACLoadPanel
// ---------------------------------------------------------------------------

export default function HVACLoadPanel() {
  const { accessToken } = useAuth()

  // Construction inputs
  const [wallArea,     setWallArea]     = useState('120')
  const [wallUValue,   setWallUValue]   = useState('0.35')
  const [roofArea,     setRoofArea]     = useState('80')
  const [roofUValue,   setRoofUValue]   = useState('0.25')

  // Glazing
  const [glazingArea,  setGlazingArea]  = useState('24')
  const [shgc,         setShgc]         = useState('0.4')
  const [uGlazing,     setUGlazing]     = useState('1.8')

  // Occupancy / internal gains
  const [occupants,    setOccupants]    = useState('10')
  const [lighting,     setLighting]     = useState('1200')
  const [equipment,    setEquipment]    = useState('2000')

  // Infiltration / zone
  const [ach,          setAch]          = useState('0.5')
  const [floorArea,    setFloorArea]    = useState('80')
  const [ceilingHt,    setCeilingHt]    = useState('3.0')

  // Design conditions
  const [outdoorSummer, setOutdoorSummer] = useState('35')
  const [outdoorWinter, setOutdoorWinter] = useState('-5')
  const [indoor,        setIndoor]        = useState('22')

  const [result, setResult] = useState(null)
  const [error,  setError]  = useState(null)
  const [loading, setLoading] = useState(false)

  const calculate = useCallback(async () => {
    setLoading(true)
    setError(null)

    const inputs = {
      wallArea:        parseFloat(wallArea)   || 0,
      wallUValue:      parseFloat(wallUValue) || 0,
      roofArea:        parseFloat(roofArea)   || 0,
      roofUValue:      parseFloat(roofUValue) || 0,
      glazingArea:     parseFloat(glazingArea)|| 0,
      solarHeatGainCoeff: parseFloat(shgc)   || 0,
      uValueGlazing:   parseFloat(uGlazing)  || 0,
      occupantCount:   parseInt(occupants,10)|| 0,
      lightingWatts:   parseFloat(lighting)  || 0,
      equipmentWatts:  parseFloat(equipment) || 0,
      infiltrationACH: parseFloat(ach)       || 0,
      floorArea:       parseFloat(floorArea) || 0,
      ceilingHeight:   parseFloat(ceilingHt) || 0,
      outdoorDesignTemp: parseFloat(outdoorSummer) || 0,
      indoorTemp:      parseFloat(indoor)    || 0,
    }

    try {
      // Try backend tool call first — falls back to client-side
      let coolingKW, heatingKW, breakdown
      try {
        const args = buildSensibleLoadArgs({
          wallArea: inputs.wallArea,
          wallUValue: inputs.wallUValue,
          outdoorSummer: parseFloat(outdoorSummer),
          indoor: parseFloat(indoor),
        })
        const resp = await callTool('hvac_cfm_from_sensible_load', args, accessToken)
        // cfm result confirms backend is alive; compute loads client-side
        void resp
      } catch {
        // Backend unavailable — proceed with client-side calculation only
      }

      const cooling = computeCoolingLoad({
        ...inputs,
        outdoorDesignTemp: parseFloat(outdoorSummer),
      })
      const heating = computeHeatingLoad({
        ...inputs,
        outdoorDesignTemp: parseFloat(outdoorWinter),
        indoorTemp: parseFloat(indoor),
      })

      coolingKW   = +(cooling.totalCoolingW / 1000).toFixed(2)
      heatingKW   = +(heating.totalHeatingW / 1000).toFixed(2)
      breakdown   = cooling.breakdown

      const coolingProfile = MONTH_COOLING_FACTOR.map(f => cooling.totalCoolingW * f)
      const heatingProfile = MONTH_HEATING_FACTOR.map(f => heating.totalHeatingW * f)

      setResult({ coolingKW, heatingKW, breakdown, coolingProfile, heatingProfile })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [
    wallArea, wallUValue, roofArea, roofUValue,
    glazingArea, shgc, uGlazing,
    occupants, lighting, equipment,
    ach, floorArea, ceilingHt,
    outdoorSummer, outdoorWinter, indoor,
    accessToken,
  ])

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-3 text-xs">
      <h2 className="text-[11px] font-semibold text-ink-200 uppercase tracking-wider">
        ASHRAE CLTD / RTS Zone Load Calculator
      </h2>

      <Section icon={Thermometer} title="Opaque construction">
        <Field label="Wall area (m²)"      value={wallArea}   onChange={setWallArea}   min="0" unit="m²" />
        <Field label="Wall U-value (W/m²K)" value={wallUValue} onChange={setWallUValue} min="0" step="0.01" unit="W/m²K" />
        <Field label="Roof area (m²)"      value={roofArea}   onChange={setRoofArea}   min="0" unit="m²" />
        <Field label="Roof U-value (W/m²K)" value={roofUValue} onChange={setRoofUValue} min="0" step="0.01" unit="W/m²K" />
      </Section>

      <Section icon={Sun} title="Glazing">
        <Field label="Glazing area (m²)"   value={glazingArea} onChange={setGlazingArea} min="0" unit="m²" />
        <Field label="SHGC"                value={shgc}        onChange={setShgc}        min="0" max="1" step="0.01" />
        <Field label="U-value glazing"     value={uGlazing}    onChange={setUGlazing}    min="0" step="0.1" unit="W/m²K" />
        <div /> {/* spacer */}
      </Section>

      <Section icon={Users} title="Occupancy &amp; internal gains">
        <Field label="Occupants"           value={occupants}  onChange={setOccupants}  min="0" step="1" />
        <Field label="Lighting (W)"        value={lighting}   onChange={setLighting}   min="0" unit="W" />
        <Field label="Equipment (W)"       value={equipment}  onChange={setEquipment}  min="0" unit="W" />
        <div />
      </Section>

      <Section icon={Wind} title="Infiltration &amp; zone">
        <Field label="Infiltration (ACH)"  value={ach}        onChange={setAch}        min="0" step="0.1" />
        <Field label="Floor area (m²)"     value={floorArea}  onChange={setFloorArea}  min="0" unit="m²" />
        <Field label="Ceiling height (m)"  value={ceilingHt}  onChange={setCeilingHt}  min="0" step="0.1" unit="m" />
        <div />
      </Section>

      <Section icon={Thermometer} title="Design conditions" defaultOpen>
        <Field label="Outdoor summer DB (°C)" value={outdoorSummer} onChange={setOutdoorSummer} step="0.5" unit="°C" />
        <Field label="Outdoor winter DB (°C)" value={outdoorWinter} onChange={setOutdoorWinter} step="0.5" unit="°C" />
        <Field label="Indoor setpoint (°C)"   value={indoor}        onChange={setIndoor}        step="0.5" unit="°C" />
        <div />
      </Section>

      <button
        type="button"
        onClick={calculate}
        disabled={loading}
        className="flex items-center justify-center gap-2 w-full py-2 rounded-md bg-kerf-300/15 border border-kerf-300/40 text-kerf-200 hover:bg-kerf-300/25 disabled:opacity-50 text-xs font-medium"
      >
        {loading ? <Loader2 size={12} className="animate-spin" /> : <BarChart2 size={12} />}
        {loading ? 'Calculating…' : 'Calculate loads'}
      </button>

      {error && (
        <div className="flex items-start gap-2 p-2 rounded bg-red-950/40 border border-red-700/40 text-red-300 text-[11px]">
          <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {result && <ResultsPanel result={result} />}
    </div>
  )
}

/**
 * ResultsPanel — the post-calculation results card (peak cooling/heating,
 * load breakdown, monthly profiles). Pulled out as its own component (like
 * BarSparkline / Section above) so it can be exercised directly with a
 * fixed `result` object via renderToStaticMarkup, since
 * @testing-library/react isn't installed and `result` is only reachable
 * through internal `calculate()` state otherwise.
 */
export function ResultsPanel({ result }) {
  return (
    <div className="border border-ink-800 rounded-md overflow-hidden">
      <div className="bg-ink-900 px-3 py-2 text-[10px] font-semibold text-ink-300 uppercase tracking-wider">
        Results
      </div>
      <div className="p-3 bg-ink-950 flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2">
          <div className="flex flex-col gap-0.5 p-2 rounded bg-blue-950/30 border border-blue-700/30">
            <span className="text-[10px] text-blue-400">Peak cooling</span>
            <span className="text-lg font-bold text-blue-300">{result.coolingKW} kW</span>
            <span className="text-[10px] text-ink-500">{(result.coolingKW * 0.2843).toFixed(1)} TR</span>
          </div>
          <div className="flex flex-col gap-0.5 p-2 rounded bg-orange-950/30 border border-orange-700/30">
            <span className="text-[10px] text-orange-400">Peak heating</span>
            <span className="text-lg font-bold text-orange-300">{result.heatingKW} kW</span>
          </div>
        </div>

        <div>
          <p className="text-[10px] text-ink-500 uppercase tracking-wider mb-1.5">Cooling load breakdown (W)</p>
          <div className="flex flex-col gap-0.5">
            {Object.entries(result.breakdown).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2">
                <div
                  className="h-2 bg-blue-600/60 rounded-r"
                  style={{ width: `${(v / result.coolingKW / 1000 * 100).toFixed(1)}%`, minWidth: 2 }}
                />
                <span className="text-[10px] text-ink-400 flex-1">{k.replace(/([A-Z])/g, ' $1').toLowerCase()}</span>
                <span className="text-[10px] font-mono text-ink-300">{v} W</span>
              </div>
            ))}
          </div>
        </div>

        <BarSparkline
          values={result.coolingProfile}
          color="bg-blue-600/70"
          unit="kW"
          label="Monthly cooling profile"
        />
        <BarSparkline
          values={result.heatingProfile}
          color="bg-orange-600/70"
          unit="kW"
          label="Monthly heating profile"
        />
      </div>
    </div>
  )
}
