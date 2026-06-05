/**
 * PipingDesignPanel.jsx — ASME B31 piping design panel.
 *
 * Tabs:
 *   1. Pressure Drop  — Darcy-Weisbach + Crane TP-410 K-factors (piping_pressure_drop)
 *   2. Wall Thickness — ASME B31.1 §104.1.2 Eq. 7 (piping_min_wall_thickness)
 *   3. Pipe Stress    — B31.1 sustained / thermal / occasional (piping_pipe_stress)
 *   4. B16 Fittings   — ASME B16.9 BOM + B16.5 flange rating (piping_b16_fittings)
 *
 * All calculations dispatch to:
 *   POST /api/tools/call  { tool: "<tool_name>", args: {...} }
 * with client-side fallback for Pressure Drop and Wall Thickness.
 */

import { useState, useCallback } from 'react'
import {
  Gauge, Layers, Activity, Package,
  Plus, Trash2, Calculator, Loader2, AlertTriangle,
  ChevronDown, ChevronRight, CheckCircle, XCircle,
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
// Client-side Colebrook-White (mirrors asme_pressure.py)
// ---------------------------------------------------------------------------

function colebrook(re, epsD) {
  if (re < 2100) return 64 / re
  // Swamee-Jain initial guess
  let f = 0.25 / (Math.log10(epsD / 3.7 + 5.74 / Math.pow(re, 0.9))) ** 2
  for (let i = 0; i < 50; i++) {
    const sqrtF = Math.sqrt(f)
    const arg = epsD / 3.7 + 2.51 / (re * sqrtF)
    const lhs = 1 / sqrtF
    const rhs = -2 * Math.log10(arg)
    const res = lhs - rhs
    const dLhs = -0.5 / Math.pow(f, 1.5)
    const dRhs = (2 / (Math.log(10) * arg)) * (2.51 / (re * 2 * Math.pow(f, 1.5)))
    const jac = dLhs - dRhs
    if (Math.abs(jac) < 1e-15) break
    let fNew = f - res / jac
    if (fNew <= 0) fNew = f / 2
    if (Math.abs(fNew - f) < 1e-8 * f) { f = fNew; break }
    f = fNew
  }
  return f
}

const GPM_TO_FT3S = 0.133681 / 60
const G_C = 32.174
const PSF_TO_PSI = 1 / 144

const FLUID_PROPS = {
  water: { rho: 62.37, mu: 6.720e-4 },
  oil:   { rho: 53.0,  mu: 2.016e-3 },
  air:   { rho: 0.0752, mu: 1.22e-5 },
  steam: { rho: 0.0372, mu: 6.60e-6 },
}

function darcyLoss(diam_in, len_ft, flow_gpm, fluid = 'water', roughness = 0.00015) {
  if (!flow_gpm || !len_ft) return 0
  const { rho, mu } = FLUID_PROPS[fluid] || FLUID_PROPS.water
  const d_ft = diam_in / 12
  const q = flow_gpm * GPM_TO_FT3S
  const area = Math.PI * d_ft ** 2 / 4
  const v = q / area
  const re = rho * v * d_ft / mu
  const epsD = roughness / d_ft
  const f = colebrook(re, epsD)
  const dp_psf = f * (len_ft / d_ft) * rho * v * v / (2 * G_C)
  return dp_psf * PSF_TO_PSI
}

const FITTING_K = {
  '90_elbow_welded': 0.30,
  '45_elbow_welded': 0.20,
  '90_elbow_threaded': 0.50,
  'tee_through': 0.40,
  'tee_branch': 1.00,
  'gate_valve_open': 0.15,
  'globe_valve': 10.0,
  'check_valve': 2.00,
  'ball_valve_open': 0.07,
  'butterfly_valve_open': 0.30,
}

function kToPsi(k, diam_in, flow_gpm, fluid = 'water') {
  if (!flow_gpm || !k) return 0
  const { rho } = FLUID_PROPS[fluid] || FLUID_PROPS.water
  const d_ft = diam_in / 12
  const q = flow_gpm * GPM_TO_FT3S
  const area = Math.PI * d_ft ** 2 / 4
  const v = q / area
  return k * rho * v * v / (2 * G_C) * PSF_TO_PSI
}

// ---------------------------------------------------------------------------
// Shared UI atoms
// ---------------------------------------------------------------------------

function Label({ children }) {
  return <span className="text-[10px] text-ink-500">{children}</span>
}

function NumInput({ value, onChange, step = 'any', min, placeholder }) {
  return (
    <input
      type="number" value={value} step={step} min={min}
      placeholder={placeholder}
      onChange={e => onChange(e.target.value)}
      className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 w-full focus:outline-none focus:border-kerf-300/60"
    />
  )
}

function Sel({ value, onChange, options }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      className="bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 w-full focus:outline-none focus:border-kerf-300/60">
      {options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
    </select>
  )
}

function ResultRow({ label, value, unit, highlight }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-[10px] text-ink-500">{label}</span>
      <span className={`text-[11px] font-mono ${highlight ? 'text-kerf-300 font-bold' : 'text-ink-200'}`}>
        {value} {unit && <span className="text-ink-500 text-[9px]">{unit}</span>}
      </span>
    </div>
  )
}

function ComplianceBadge({ compliant }) {
  if (compliant === undefined || compliant === null) return null
  return compliant
    ? <span className="flex items-center gap-1 text-[10px] text-green-400"><CheckCircle size={10} /> Pass</span>
    : <span className="flex items-center gap-1 text-[10px] text-red-400"><XCircle size={10} /> Fail</span>
}

function CalcBtn({ onClick, loading, disabled, label = 'Calculate' }) {
  return (
    <button type="button" onClick={onClick}
      disabled={loading || disabled}
      className="flex items-center justify-center gap-2 w-full py-2 rounded-md bg-kerf-300/15 border border-kerf-300/40 text-kerf-200 hover:bg-kerf-300/25 disabled:opacity-50 text-xs font-medium">
      {loading ? <Loader2 size={12} className="animate-spin" /> : <Calculator size={12} />}
      {loading ? 'Calculating…' : label}
    </button>
  )
}

function ErrBox({ msg }) {
  if (!msg) return null
  return (
    <div className="flex items-start gap-2 p-2 rounded bg-red-950/40 border border-red-700/40 text-red-300 text-[11px]">
      <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" />
      <span>{msg}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 1 — Pressure Drop
// ---------------------------------------------------------------------------

let _segId = 0
const mkId = () => ++_segId

const DEFAULT_SEGMENT = () => ({
  id: mkId(), diam_in: '4', len_ft: '100', roughness: '0.00015', fluid: '',
})
const DEFAULT_FITTING = () => ({
  id: mkId(), kind: '90_elbow_welded', diam_in: '4', qty: '1',
})

function PressureDropTab({ token }) {
  const [fluid,    setFluid]    = useState('water')
  const [flowGpm,  setFlowGpm]  = useState('100')
  const [segments, setSegments] = useState([DEFAULT_SEGMENT()])
  const [fittings, setFittings] = useState([])
  const [result,   setResult]   = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const calc = useCallback(async () => {
    setLoading(true); setError(null)
    const segs = segments.map(s => ({
      diameter_in: parseFloat(s.diam_in),
      length_ft:   parseFloat(s.len_ft),
      roughness:   parseFloat(s.roughness) || 0.00015,
      ...(s.fluid ? { fluid: s.fluid } : {}),
    }))
    const fits = fittings.map(f => ({
      fitting_kind: f.kind,
      diameter_in:  parseFloat(f.diam_in),
      quantity:     parseInt(f.qty, 10) || 1,
    }))
    try {
      // Backend first
      const r = await callTool('piping_pressure_drop', {
        segments: segs, fittings: fits,
        flow_gpm: parseFloat(flowGpm), fluid,
      }, token)
      setResult(r)
    } catch {
      // Client-side fallback
      let pipeDp = 0, fitDp = 0
      const segDets = segs.map(s => {
        const dp = darcyLoss(s.diameter_in, s.length_ft, parseFloat(flowGpm), fluid, s.roughness)
        pipeDp += dp
        return { diameter_in: s.diameter_in, length_ft: s.length_ft, dp_psi: +dp.toFixed(6) }
      })
      const fitDets = fits.map(f => {
        const k = FITTING_K[f.fitting_kind] ?? 0
        const dp = kToPsi(k, f.diameter_in, parseFloat(flowGpm), fluid) * f.quantity
        fitDp += dp
        return { fitting_kind: f.fitting_kind, diameter_in: f.diameter_in, quantity: f.quantity, K: k, dp_psi: +dp.toFixed(6) }
      })
      setResult({
        total_dp_psi: +(pipeDp + fitDp).toFixed(4),
        pipe_dp_psi: +pipeDp.toFixed(4),
        fitting_dp_psi: +fitDp.toFixed(4),
        segment_details: segDets,
        fitting_details: fitDets,
      })
    }
    setLoading(false)
  }, [segments, fittings, flowGpm, fluid, token])

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <Label>Flow (GPM)</Label>
          <NumInput value={flowGpm} onChange={setFlowGpm} min="0" />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Default fluid</Label>
          <Sel value={fluid} onChange={setFluid}
            options={[['water','Water (60°F)'],['oil','Oil (SG≈0.85)'],['air','Air (68°F)'],['steam','Steam (212°F)']]} />
        </label>
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-medium text-ink-400">Pipe segments</span>
          <button type="button" onClick={() => setSegments(p => [...p, DEFAULT_SEGMENT()])}
            className="flex items-center gap-1 text-[10px] text-kerf-300 hover:text-kerf-200">
            <Plus size={10} /> Add
          </button>
        </div>
        {segments.map((seg, i) => (
          <div key={seg.id} className="grid grid-cols-4 gap-1.5 items-end border border-ink-800 rounded p-1.5">
            <label className="flex flex-col gap-0.5">
              <Label>ID (in)</Label>
              <NumInput value={seg.diam_in} onChange={v => setSegments(p => p.map(s => s.id === seg.id ? {...s, diam_in: v} : s))} />
            </label>
            <label className="flex flex-col gap-0.5">
              <Label>Length (ft)</Label>
              <NumInput value={seg.len_ft} onChange={v => setSegments(p => p.map(s => s.id === seg.id ? {...s, len_ft: v} : s))} />
            </label>
            <label className="flex flex-col gap-0.5">
              <Label>Roughness (ft)</Label>
              <NumInput value={seg.roughness} onChange={v => setSegments(p => p.map(s => s.id === seg.id ? {...s, roughness: v} : s))} />
            </label>
            <button type="button" onClick={() => setSegments(p => p.filter(s => s.id !== seg.id))}
              className="text-ink-600 hover:text-red-400 self-center mt-3">
              <Trash2 size={11} />
            </button>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-medium text-ink-400">Fittings (Crane TP-410)</span>
          <button type="button" onClick={() => setFittings(p => [...p, DEFAULT_FITTING()])}
            className="flex items-center gap-1 text-[10px] text-kerf-300 hover:text-kerf-200">
            <Plus size={10} /> Add
          </button>
        </div>
        {fittings.map(fit => (
          <div key={fit.id} className="grid grid-cols-4 gap-1.5 items-end border border-ink-800 rounded p-1.5">
            <label className="flex flex-col gap-0.5 col-span-2">
              <Label>Fitting type</Label>
              <Sel value={fit.kind}
                onChange={v => setFittings(p => p.map(f => f.id === fit.id ? {...f, kind: v} : f))}
                options={Object.keys(FITTING_K).map(k => [k, k.replace(/_/g,' ')])} />
            </label>
            <label className="flex flex-col gap-0.5">
              <Label>ID (in)</Label>
              <NumInput value={fit.diam_in} onChange={v => setFittings(p => p.map(f => f.id === fit.id ? {...f, diam_in: v} : f))} />
            </label>
            <div className="flex items-end gap-1">
              <label className="flex flex-col gap-0.5 flex-1">
                <Label>Qty</Label>
                <NumInput value={fit.qty} onChange={v => setFittings(p => p.map(f => f.id === fit.id ? {...f, qty: v} : f))} min="1" />
              </label>
              <button type="button" onClick={() => setFittings(p => p.filter(f => f.id !== fit.id))}
                className="text-ink-600 hover:text-red-400 mb-1">
                <Trash2 size={11} />
              </button>
            </div>
          </div>
        ))}
      </div>

      <CalcBtn onClick={calc} loading={loading} label="Calculate pressure drop" />
      <ErrBox msg={error} />

      {result && (
        <div className="flex flex-col gap-1 p-2 rounded bg-ink-900 border border-ink-700">
          <ResultRow label="Total ΔP" value={result.total_dp_psi} unit="psi" highlight />
          <ResultRow label="Pipe friction" value={result.pipe_dp_psi} unit="psi" />
          <ResultRow label="Fittings" value={result.fitting_dp_psi} unit="psi" />
          <ResultRow label="Total ΔP" value={(result.total_dp_psi * 0.0689476).toFixed(4)} unit="bar" />
          {result.segment_details?.length > 0 && (
            <div className="mt-1 border-t border-ink-800 pt-1">
              <span className="text-[9px] text-ink-600">Segment breakdown</span>
              {result.segment_details.map((s, i) => (
                <div key={i} className="flex justify-between text-[10px]">
                  <span className="text-ink-500">Seg {i+1} · {s.diameter_in}″ · {s.length_ft} ft</span>
                  <span className="text-ink-300 font-mono">{s.dp_psi} psi</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      <div className="text-[10px] text-ink-600">Darcy-Weisbach / Colebrook-White · Crane TP-410 §1 &amp; §3 · ASME B31</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 2 — Wall Thickness (ASME B31.1)
// ---------------------------------------------------------------------------

function WallThicknessTab({ token }) {
  const [pressure, setPressure] = useState('300')
  const [diam,     setDiam]     = useState('4')
  const [material, setMaterial] = useState('A106-B')
  const [tempF,    setTempF]    = useState('500')
  const [jointEff, setJointEff] = useState('1.0')
  const [corrAll,  setCorrAll]  = useState('0.0625')
  const [millTol,  setMillTol]  = useState('12.5')
  const [result,   setResult]   = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const calc = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const r = await callTool('piping_min_wall_thickness', {
        pressure_psi: parseFloat(pressure),
        diameter_in:  parseFloat(diam),
        material,
        temp_F:       parseFloat(tempF),
        joint_efficiency: parseFloat(jointEff),
        mill_tolerance_pct: parseFloat(millTol),
        corrosion_allowance_in: parseFloat(corrAll),
      }, token)
      setResult(r)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [pressure, diam, material, tempF, jointEff, millTol, corrAll, token])

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <Label>Pressure (psi)</Label>
          <NumInput value={pressure} onChange={setPressure} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>OD / NPS (in)</Label>
          <NumInput value={diam} onChange={setDiam} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Material</Label>
          <Sel value={material} onChange={setMaterial}
            options={[['A106-B','A106 Gr. B (CS)'],['A53-B','A53 Gr. B'],['A312-304','A312 TP304 SS'],['A312-316','A312 TP316 SS']]} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Temperature (°F)</Label>
          <NumInput value={tempF} onChange={setTempF} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Joint efficiency E</Label>
          <NumInput value={jointEff} onChange={setJointEff} step="0.05" />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Corrosion allow. (in)</Label>
          <NumInput value={corrAll} onChange={setCorrAll} />
        </label>
        <label className="flex flex-col gap-0.5 col-span-2">
          <Label>Mill tolerance (%)</Label>
          <NumInput value={millTol} onChange={setMillTol} />
        </label>
      </div>

      <CalcBtn onClick={calc} loading={loading} label="Size wall thickness" />
      <ErrBox msg={error} />

      {result && !result.error && (
        <div className="flex flex-col gap-1 p-2 rounded bg-ink-900 border border-ink-700">
          <ResultRow label="Min wall required" value={result.min_thickness_in} unit="in" />
          <ResultRow label="Ordered min wall" value={result.ordered_min_thickness_in} unit="in" highlight />
          <ResultRow label="Recommended schedule" value={result.schedule_recommended} highlight />
          <ResultRow label="MAWP" value={result.design_pressure_max_psi} unit="psi" />
          <ResultRow label="Allowable stress" value={result.allowable_stress_psi} unit="psi" />
          <ResultRow label="y coefficient" value={result.y_coefficient} />
        </div>
      )}
      <div className="text-[10px] text-ink-600">ASME B31.1-2022 §104.1.2 Eq. 7 · B36.10M schedule lookup</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 3 — Pipe Stress (ASME B31.1)
// ---------------------------------------------------------------------------

function PipeStressTab({ token }) {
  const [od,       setOd]       = useState('4.5')
  const [wall,     setWall]     = useState('0.237')
  const [pressure, setPressure] = useState('150')
  const [wgt,      setWgt]      = useState('18')
  const [span,     setSpan]     = useState('15')
  const [material, setMaterial] = useState('A106-B')
  const [code,     setCode]     = useState('B31.1')
  const [dT,       setDT]       = useState('0')
  const [mOcc,     setMOcc]     = useState('0')
  const [result,   setResult]   = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const calc = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const r = await callTool('piping_pipe_stress', {
        od_in: parseFloat(od),
        wall_in: parseFloat(wall),
        pressure_psi: parseFloat(pressure),
        weight_lbf_per_ft: parseFloat(wgt),
        span_ft: parseFloat(span),
        material, code,
        delta_T_F: parseFloat(dT) || 0,
        M_occasional_inlbf: parseFloat(mOcc) || 0,
      }, token)
      setResult(r)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [od, wall, pressure, wgt, span, material, code, dT, mOcc, token])

  const sus = result?.sustained
  const th  = result?.thermal
  const occ = result?.occasional

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <Label>OD (in)</Label>
          <NumInput value={od} onChange={setOd} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Wall (in)</Label>
          <NumInput value={wall} onChange={setWall} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Pressure (psi)</Label>
          <NumInput value={pressure} onChange={setPressure} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Weight (lbf/ft)</Label>
          <NumInput value={wgt} onChange={setWgt} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Span (ft)</Label>
          <NumInput value={span} onChange={setSpan} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>ΔT (°F) thermal</Label>
          <NumInput value={dT} onChange={setDT} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Material</Label>
          <Sel value={material} onChange={setMaterial}
            options={[['A106-B','A106 Gr. B'],['A53-B','A53 Gr. B'],['A312-304','TP304 SS'],['A312-316','TP316 SS'],['A333-6','A333 Gr. 6 LT']]} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Code</Label>
          <Sel value={code} onChange={setCode} options={[['B31.1','ASME B31.1'],['B31.3','ASME B31.3']]} />
        </label>
        <label className="flex flex-col gap-0.5 col-span-2">
          <Label>Occasional moment M_occ (in-lbf)</Label>
          <NumInput value={mOcc} onChange={setMOcc} min="0" />
        </label>
      </div>

      <CalcBtn onClick={calc} loading={loading} label="Run stress check" />
      <ErrBox msg={error} />

      {sus && (
        <div className="flex flex-col gap-1 p-2 rounded bg-ink-900 border border-ink-700">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-[10px] font-medium text-ink-300">Sustained (§104.8.1)</span>
            <ComplianceBadge compliant={sus.compliant} />
          </div>
          <ResultRow label="Calculated S_L" value={sus.calculated_psi?.toFixed(0)} unit="psi" highlight />
          <ResultRow label="Allowable S_h" value={sus.allowable_psi?.toFixed(0)} unit="psi" />
          <ResultRow label="Utilisation" value={(sus.utilisation * 100).toFixed(1)} unit="%" />
          <ResultRow label="Hoop component" value={sus.details?.hoop_stress_psi?.toFixed(0)} unit="psi" />
          <ResultRow label="Bending component" value={sus.details?.bending_stress_psi?.toFixed(0)} unit="psi" />
        </div>
      )}

      {th && (
        <div className="flex flex-col gap-1 p-2 rounded bg-ink-900 border border-ink-700">
          <span className="text-[10px] font-medium text-ink-300">Thermal (fully restrained)</span>
          <ResultRow label="Thermal force" value={th.thermal_force_lbf?.toFixed(0)} unit="lbf" highlight />
          <ResultRow label="Thermal stress" value={th.thermal_stress_psi?.toFixed(0)} unit="psi" />
          <ResultRow label="Free expansion" value={th.free_expansion_in_per_ft?.toFixed(5)} unit="in/ft" />
          {th.compliant_note && (
            <p className="text-[10px] text-amber-400 mt-0.5">{th.compliant_note}</p>
          )}
        </div>
      )}

      {occ && (
        <div className="flex flex-col gap-1 p-2 rounded bg-ink-900 border border-ink-700">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-[10px] font-medium text-ink-300">Occasional (§104.8.4)</span>
            <ComplianceBadge compliant={occ.compliant} />
          </div>
          <ResultRow label="Calculated S_L_occ" value={occ.calculated_psi?.toFixed(0)} unit="psi" highlight />
          <ResultRow label="Allowable 1.33·S_h" value={occ.allowable_psi?.toFixed(0)} unit="psi" />
          <ResultRow label="Utilisation" value={(occ.utilisation * 100).toFixed(1)} unit="%" />
        </div>
      )}
      <div className="text-[10px] text-ink-600">ASME B31.1-2022 §104.8 · B31.3-2022 §319.4 · simplified straight-pipe model</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 4 — B16 Fittings (ASME B16.9 / B16.5)
// ---------------------------------------------------------------------------

function B16FittingsTab({ token }) {
  const [dn,         setDn]         = useState('100')
  const [e90lr,      setE90lr]      = useState('2')
  const [e45,        setE45]        = useState('0')
  const [tees,       setTees]       = useState('1')
  const [caps,       setCaps]       = useState('0')
  const [flangeClass,setFlangeClass]= useState('150')
  const [flanges,    setFlanges]    = useState('2')
  const [tempF,      setTempF]      = useState('100')
  const [result,     setResult]     = useState(null)
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState(null)

  const calc = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const r = await callTool('piping_b16_fittings', {
        dn: parseInt(dn, 10),
        elbows_90lr: parseInt(e90lr, 10) || 0,
        elbows_45:   parseInt(e45, 10) || 0,
        tees_equal:  parseInt(tees, 10) || 0,
        caps:        parseInt(caps, 10) || 0,
        flange_class: parseInt(flangeClass, 10) || undefined,
        flanges:     parseInt(flanges, 10) || 0,
        temp_F:      parseFloat(tempF) || 100,
      }, token)
      setResult(r)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [dn, e90lr, e45, tees, caps, flangeClass, flanges, tempF, token])

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-0.5">
          <Label>DN (mm)</Label>
          <Sel value={dn} onChange={setDn}
            options={[['25','DN25'],['40','DN40'],['50','DN50'],['80','DN80'],['100','DN100'],['150','DN150'],['200','DN200'],['250','DN250'],['300','DN300']]} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Flange class (B16.5)</Label>
          <Sel value={flangeClass} onChange={setFlangeClass}
            options={[['150','Class 150'],['300','Class 300'],['600','Class 600'],['900','Class 900'],['1500','Class 1500'],['2500','Class 2500']]} />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>90° LR elbows</Label>
          <NumInput value={e90lr} onChange={setE90lr} min="0" />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>45° elbows</Label>
          <NumInput value={e45} onChange={setE45} min="0" />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Equal tees</Label>
          <NumInput value={tees} onChange={setTees} min="0" />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Caps</Label>
          <NumInput value={caps} onChange={setCaps} min="0" />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Flanges</Label>
          <NumInput value={flanges} onChange={setFlanges} min="0" />
        </label>
        <label className="flex flex-col gap-0.5">
          <Label>Temp (°F) for rating</Label>
          <NumInput value={tempF} onChange={setTempF} />
        </label>
      </div>

      <CalcBtn onClick={calc} loading={loading} label="Get fitting BOM" />
      <ErrBox msg={error} />

      {result && (
        <div className="flex flex-col gap-2">
          {result.flange_rating && (
            <div className="p-2 rounded bg-ink-900 border border-ink-700">
              <span className="text-[10px] font-medium text-ink-300">Flange rating (B16.5 Group 1.1)</span>
              <div className="mt-1 flex flex-col gap-0.5">
                <ResultRow label="Rating at temp" value={result.flange_rating.rating_psi} unit="psi" highlight />
                <ResultRow label="Rating at temp" value={result.flange_rating.rating_bar} unit="bar" />
                <p className="text-[9px] text-ink-600 mt-0.5">{result.flange_rating.note}</p>
              </div>
            </div>
          )}
          <div className="p-2 rounded bg-ink-900 border border-ink-700">
            <div className="flex justify-between mb-1">
              <span className="text-[10px] font-medium text-ink-300">Fitting BOM</span>
              <span className="text-[10px] font-mono text-kerf-300">{result.total_weight_kg} kg total</span>
            </div>
            {result.bom?.map((item, i) => (
              <div key={i} className="flex flex-col gap-0.5 border-t border-ink-800 pt-1 mt-1 first:border-0 first:mt-0 first:pt-0">
                <div className="flex justify-between">
                  <span className="text-[10px] text-ink-300">{item.description || item.fitting_type}</span>
                  <span className="text-[10px] font-mono text-ink-400">×{item.quantity}</span>
                </div>
                {item.center_to_face_mm && (
                  <span className="text-[9px] text-ink-600">C-to-F: {item.center_to_face_mm} mm · {item.standard}</span>
                )}
                {item.overall_length_mm && (
                  <span className="text-[9px] text-ink-600">Length: {item.overall_length_mm} mm · {item.standard}</span>
                )}
                {item.error && (
                  <span className="text-[9px] text-red-400">{item.error}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="text-[10px] text-ink-600">ASME B16.9-2018 butt-weld fittings · ASME B16.5-2017 flanges</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main PipingDesignPanel
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'pressure',  label: 'Pressure Drop',  Icon: Gauge   },
  { id: 'wall',      label: 'Wall Thickness', Icon: Layers  },
  { id: 'stress',    label: 'Pipe Stress',    Icon: Activity },
  { id: 'fittings',  label: 'B16 Fittings',  Icon: Package  },
]

export default function PipingDesignPanel() {
  const { accessToken } = useAuth()
  const [activeTab, setActiveTab] = useState('pressure')

  return (
    <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-0 text-xs">
      {/* Tab bar */}
      <div className="flex border-b border-ink-800 sticky top-0 bg-ink-950 z-10">
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            className={`flex items-center gap-1 px-2.5 py-2 text-[10px] font-medium border-b-2 transition-colors ${
              activeTab === id
                ? 'border-kerf-300 text-kerf-200'
                : 'border-transparent text-ink-500 hover:text-ink-300'
            }`}
          >
            <Icon size={10} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="p-3">
        {activeTab === 'pressure'  && <PressureDropTab  token={accessToken} />}
        {activeTab === 'wall'      && <WallThicknessTab token={accessToken} />}
        {activeTab === 'stress'    && <PipeStressTab    token={accessToken} />}
        {activeTab === 'fittings'  && <B16FittingsTab   token={accessToken} />}
      </div>
    </div>
  )
}
