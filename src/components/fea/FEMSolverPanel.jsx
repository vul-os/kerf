// FEMSolverPanel.jsx — Extended FEM solver panel wiring 20+ backend tools.
//
// Sections / tabs:
//   Nonlinear & Dynamic  — fem_nonlinear_static, fem_nonlinear_bar, fem_truss_plastic,
//                          fem_explicit_dynamics, fem_explicit
//   Thermal              — fem_thermal (steady/transient via analysis_type)
//   Acoustics & EM       — fem_acoustics, fem_electrostatics, fem_magnetostatics,
//                          fem_em_highfreq
//   CFD                  — cfd_navier_stokes_steady, cfd_potential_cylinder
//   Plate & Uncertainty  — fem_plate_static_solve, fem_propagate_uncertainty
//
// Each card: compact inputs + Run + status badge + result table/viz.
// Dispatch pattern mirrors BucklingPanel.jsx / LinearStaticPanel.jsx:
//   POST /api/projects/{pid}/files/{fid}/fem  → submitFemJob
//   poll /fem/status                          → pollFemStatus
//
// Props: { projectId, fileId }

import { useState, useRef } from 'react'
import {
  Activity, AlertTriangle, CheckCircle, Loader2, Play,
  Thermometer, Zap, BarChart3, Square, Waves,
  Wind, Layers, Cpu,
} from 'lucide-react'
import { useAuth } from '../../store/auth.js'
import { submitFemJob, pollFemStatus } from './feaApi.js'
import { s, badgeStyle } from './feaStyles.js'

// ── shared helpers ─────────────────────────────────────────────────────────────

function fmtMPa(pa) {
  if (pa == null || !isFinite(pa)) return '—'
  return (pa / 1e6).toFixed(3) + ' MPa'
}
function fmtMm(m) {
  if (m == null || !isFinite(m)) return '—'
  return (m * 1000).toFixed(4) + ' mm'
}
function fmtSci(v, unit = '') {
  if (v == null || !isFinite(Number(v))) return '—'
  return Number(v).toExponential(3) + (unit ? ' ' + unit : '')
}

function ResultRow({ label, value }) {
  return (
    <tr>
      <td style={s.td}>{label}</td>
      <td style={{ ...s.td, ...s.mono }}>{value}</td>
    </tr>
  )
}

function StatusArea({ jobStatus, error, runningMsg }) {
  if (error) return (
    <div style={s.errorBox} role="alert">
      <AlertTriangle size={13} />
      <span>{error}</span>
    </div>
  )
  if (jobStatus === 'error') return null  // caller renders status?.error
  if (jobStatus === 'queued' || jobStatus === 'running') return (
    <div style={s.infoBox}>
      <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
      <span>{jobStatus === 'queued' ? 'Queued…' : (runningMsg || 'Solving…')}</span>
    </div>
  )
  return null
}

// Generic run-button + poll hook
function useFemJob({ projectId, fileId }) {
  const [running, setRunning]   = useState(false)
  const [status, setStatus]     = useState(null)
  const [error, setError]       = useState(null)
  const pollRef = useRef(null)

  function stopPoll() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  async function run(body) {
    if (!projectId || !fileId) return
    setError(null)
    setRunning(true)
    setStatus(null)
    stopPoll()
    try {
      const token = useAuth.getState().accessToken
      const ctx = { pid: projectId, fid: fileId, token }
      const queued = await submitFemJob(ctx, body)
      setStatus({ status: 'queued', job_id: queued.job_id })
      pollRef.current = setInterval(async () => {
        const st = await pollFemStatus(ctx)
        setStatus(st)
        if (st.status === 'done' || st.status === 'error') {
          stopPoll()
          setRunning(false)
        }
      }, 3000)
    } catch (e) {
      setError(e.message)
      setRunning(false)
    }
  }

  return { running, status, error, run, stopPoll }
}

// ── Section header ─────────────────────────────────────────────────────────────

function SectionHeader({ icon: Icon, label, color }) {
  return (
    <div style={{ ...s.header, marginBottom: 4 }}>
      <Icon size={15} style={{ color }} />
      <span style={{ ...s.title, color }}>{label}</span>
    </div>
  )
}

// ── Material presets shared ────────────────────────────────────────────────────

const MATERIALS = {
  steel:     { label: 'Steel S275',       E: 200e9, nu: 0.3,   rho: 7850, yield_strength: 275e6 },
  al_6061:   { label: 'Aluminium 6061-T6', E: 68.9e9, nu: 0.33, rho: 2700, yield_strength: 276e6 },
  titanium:  { label: 'Ti-6Al-4V',         E: 113.8e9, nu: 0.342, rho: 4430, yield_strength: 880e6 },
}

// ══════════════════════════════════════════════════════════════════════════════
// NONLINEAR STATIC  — fem_nonlinear_static
// ══════════════════════════════════════════════════════════════════════════════

function NonlinearStaticCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [mat, setMat]               = useState('steel')
  const [nSteps, setNSteps]         = useState('10')
  const [loadMag, setLoadMag]       = useState('5e5')
  const [arcLength, setArcLength]   = useState(false)
  const [faceTag, setFaceTag]       = useState('1')
  const [loadFace, setLoadFace]     = useState('2')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    const m = MATERIALS[mat]
    run({
      analysis_type: 'nonlinear_static',
      material_props: { E: m.E, nu: m.nu, rho: m.rho, yield_strength: m.yield_strength },
      boundary_conditions: [{ type: 'fixed', face_tags: [parseInt(faceTag, 10) || 1] }],
      loads: [{ type: 'force', face_tags: [parseInt(loadFace, 10) || 2], value: parseFloat(loadMag) || 5e5 }],
      mesh_size: 0.02,
      solver: 'fenicsx',
      // nonlinear_static specific
      n_load_steps: parseInt(nSteps, 10) || 10,
      arc_length: arcLength,
      plasticity: 'J2',
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="nonlinear-static-card">
      <SectionHeader icon={Activity} label="Nonlinear Static (J2 + arc-length)" color="#fb923c" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Material</label>
          <select value={mat} onChange={e => setMat(e.target.value)} style={s.select} disabled={running}>
            {Object.entries(MATERIALS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>Load magnitude (N)</label>
          <input type="number" value={loadMag} onChange={e => setLoadMag(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Load steps</label>
          <input type="number" value={nSteps} min="1" max="100" onChange={e => setNSteps(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Fixed BC face</label>
          <input type="number" value={faceTag} min="0" onChange={e => setFaceTag(e.target.value)} style={{ ...s.input, flex: '0 0 50px' }} disabled={running} />
          <label style={{ ...s.label, width: 60 }}>Load face</label>
          <input type="number" value={loadFace} min="0" onChange={e => setLoadFace(e.target.value)} style={{ ...s.input, flex: '0 0 50px' }} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Arc-length</label>
          <input type="checkbox" checked={arcLength} onChange={e => setArcLength(e.target.checked)} disabled={running} />
          <span style={{ color: '#9ca3af', fontSize: 11, marginLeft: 4 }}>(Riks / snap-through)</span>
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#7c2d12', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run NL Static</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="NR iterations…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>NL Static Results</span></div>
          <table style={s.table}><tbody>
            {result.max_vonmises_stress != null && <ResultRow label="Max von Mises" value={fmtMPa(result.max_vonmises_stress)} />}
            {result.max_displacement != null && <ResultRow label="Max disp." value={fmtMm(result.max_displacement)} />}
            {result.converged != null && <ResultRow label="Converged" value={result.converged ? 'yes' : 'no'} />}
            {result.load_steps_completed != null && <ResultRow label="Steps done" value={String(result.load_steps_completed)} />}
            {result.plastic_strain_max != null && <ResultRow label="Max plastic strain" value={fmtSci(result.plastic_strain_max)} />}
          </tbody></table>
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// NONLINEAR BAR  — fem_nonlinear_bar
// ══════════════════════════════════════════════════════════════════════════════

function NonlinearBarCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [E, setE]               = useState('200e9')
  const [sigY, setSigY]         = useState('275e6')
  const [H, setH]               = useState('2e9')
  const [stepsStr, setStepsStr] = useState('0.001,0.002,0.003,0.004,0.003,0.001,-0.001')
  const [forceCtrl, setForceCtrl] = useState(false)

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    const steps = stepsStr.split(',').map(v => parseFloat(v.trim())).filter(isFinite)
    run({
      analysis_type: 'nonlinear_bar',
      E: parseFloat(E) || 200e9,
      sigma_y0: parseFloat(sigY) || 275e6,
      H: parseFloat(H) || 2e9,
      load_steps: steps,
      force_controlled: forceCtrl,
      // generic fallback fields
      material_props: { E: parseFloat(E) || 200e9, nu: 0.3, rho: 7850, yield_strength: parseFloat(sigY) || 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: 1.0 }],
      mesh_size: 0.01,
      solver: 'fenicsx',
    })
  }

  const stressHist = Array.isArray(result?.stress_history) ? result.stress_history : []
  const strainHist = Array.isArray(result?.strain_history) ? result.strain_history : []

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="nonlinear-bar-card">
      <SectionHeader icon={BarChart3} label="Nonlinear Bar (J2 plasticity)" color="#f97316" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>E (Pa)</label>
          <input type="text" value={E} onChange={e => setE(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>σ_y0 (Pa)</label>
          <input type="text" value={sigY} onChange={e => setSigY(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>H hardening (Pa)</label>
          <input type="text" value={H} onChange={e => setH(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Force-ctrl</label>
          <input type="checkbox" checked={forceCtrl} onChange={e => setForceCtrl(e.target.checked)} disabled={running} />
        </div>
        <div style={s.sectionTitle}>Load steps (comma-separated)</div>
        <textarea value={stepsStr} onChange={e => setStepsStr(e.target.value)}
          disabled={running} rows={2}
          style={{ ...s.input, flex: 'none', width: '100%', boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit' }} />
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#7c2d12', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run NL Bar</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Return-mapping…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Bar Results</span></div>
          <table style={s.table}><tbody>
            {result.max_stress != null && <ResultRow label="Max stress" value={fmtMPa(result.max_stress)} />}
            {result.max_plastic_strain != null && <ResultRow label="Max plastic strain" value={fmtSci(result.max_plastic_strain)} />}
            {result.steps_converged != null && <ResultRow label="Steps converged" value={String(result.steps_converged)} />}
          </tbody></table>
          {stressHist.length > 0 && strainHist.length > 0 && (
            <HysteresisPlot stress={stressHist} strain={strainHist} />
          )}
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

function HysteresisPlot({ stress, strain }) {
  const W = 200, H = 60
  if (!stress.length || !strain.length) return null
  const maxS  = Math.max(...stress.map(Math.abs)) || 1
  const maxEp = Math.max(...strain.map(Math.abs)) || 1
  const pts   = stress.map((sig, i) => {
    const x = ((strain[i] || 0) / maxEp) * (W / 2) + W / 2
    const y = H / 2 - (sig / maxS) * (H * 0.42)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return (
    <div aria-label="Stress-strain hysteresis">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>σ–ε hysteresis</div>
      <svg width={W} height={H} style={{ display: 'block', background: '#1f2937', borderRadius: 4 }}>
        <line x1={W / 2} y1="0" x2={W / 2} y2={H} stroke="#374151" strokeWidth="1" />
        <line x1="0" y1={H / 2} x2={W} y2={H / 2} stroke="#374151" strokeWidth="1" />
        <polyline points={pts} fill="none" stroke="#f97316" strokeWidth="1.5" />
      </svg>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// EXPLICIT DYNAMICS  — fem_explicit_dynamics
// ══════════════════════════════════════════════════════════════════════════════

function ExplicitDynamicsCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [mat, setMat]         = useState('steel')
  const [tEnd, setTEnd]       = useState('0.001')
  const [dtScale, setDtScale] = useState('0.9')
  const [loadMag, setLoadMag] = useState('1e6')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    const m = MATERIALS[mat]
    run({
      analysis_type: 'explicit_dynamics',
      material_props: { E: m.E, nu: m.nu, rho: m.rho, yield_strength: m.yield_strength },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: parseFloat(loadMag) || 1e6 }],
      mesh_size: 0.02,
      solver: 'fenicsx',
      // explicit dynamics params
      t_end: parseFloat(tEnd) || 0.001,
      dt_scale: parseFloat(dtScale) || 0.9,
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="explicit-dynamics-card">
      <SectionHeader icon={Zap} label="Explicit Transient Dynamics" color="#ef4444" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Material</label>
          <select value={mat} onChange={e => setMat(e.target.value)} style={s.select} disabled={running}>
            {Object.entries(MATERIALS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>t_end (s)</label>
          <input type="number" value={tEnd} step="0.0001" min="1e-6" onChange={e => setTEnd(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>CFL scale factor</label>
          <input type="number" value={dtScale} step="0.05" min="0.1" max="1.0" onChange={e => setDtScale(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Load magnitude (N)</label>
          <input type="number" value={loadMag} onChange={e => setLoadMag(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#7f1d1d', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Explicit</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Central-difference steps…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Explicit Results</span></div>
          <table style={s.table}><tbody>
            {result.max_vonmises_stress != null && <ResultRow label="Peak von Mises" value={fmtMPa(result.max_vonmises_stress)} />}
            {result.max_displacement != null && <ResultRow label="Peak disp." value={fmtMm(result.max_displacement)} />}
            {result.time_steps != null && <ResultRow label="Time steps" value={String(result.time_steps)} />}
            {result.kinetic_energy != null && <ResultRow label="Peak KE (J)" value={fmtSci(result.kinetic_energy)} />}
            {result.strain_energy != null && <ResultRow label="Peak SE (J)" value={fmtSci(result.strain_energy)} />}
          </tbody></table>
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// THERMAL  — analysis_type: thermal_steady / thermal_transient
// ══════════════════════════════════════════════════════════════════════════════

function ThermalCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [steady, setSteady]         = useState(true)
  const [k, setK]                   = useState('45')       // W/(m·K) — steel
  const [heatFlux, setHeatFlux]     = useState('5e4')
  const [tAmbient, setTAmbient]     = useState('20')
  const [hConv, setHConv]           = useState('25')
  const [tEnd, setTEnd]             = useState('100')
  const [heatFace, setHeatFace]     = useState('2')
  const [convFace, setConvFace]     = useState('3')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    run({
      analysis_type: steady ? 'thermal_steady' : 'thermal_transient',
      thermal_conductivity: parseFloat(k) || 45,
      heat_flux: parseFloat(heatFlux) || 5e4,
      heat_flux_face: parseInt(heatFace, 10) || 2,
      convection: {
        face_tag: parseInt(convFace, 10) || 3,
        h: parseFloat(hConv) || 25,
        T_ambient: parseFloat(tAmbient) || 20,
      },
      t_end: steady ? undefined : parseFloat(tEnd) || 100,
      // generic fields for job queue
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'pressure', face_tags: [parseInt(heatFace, 10) || 2], value: parseFloat(heatFlux) || 5e4 }],
      mesh_size: 0.02,
      solver: 'fenicsx',
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="thermal-card">
      <SectionHeader icon={Thermometer} label="Thermal Analysis (CalculiX *HEAT TRANSFER)" color="#f59e0b" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Mode</label>
          <select value={steady ? 'steady' : 'transient'} onChange={e => setSteady(e.target.value === 'steady')} style={s.select} disabled={running}>
            <option value="steady">Steady-state</option>
            <option value="transient">Transient</option>
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>k W/(m·K)</label>
          <input type="number" value={k} onChange={e => setK(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Heat flux (W/m²)</label>
          <input type="number" value={heatFlux} onChange={e => setHeatFlux(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Heat face tag</label>
          <input type="number" value={heatFace} min="0" onChange={e => setHeatFace(e.target.value)} style={{ ...s.input, flex: '0 0 50px' }} disabled={running} />
          <label style={{ ...s.label, width: 60 }}>Conv face</label>
          <input type="number" value={convFace} min="0" onChange={e => setConvFace(e.target.value)} style={{ ...s.input, flex: '0 0 50px' }} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>h (W/m²K)</label>
          <input type="number" value={hConv} onChange={e => setHConv(e.target.value)} style={s.input} disabled={running} />
          <label style={{ ...s.label, width: 60 }}>T_amb (°C)</label>
          <input type="number" value={tAmbient} onChange={e => setTAmbient(e.target.value)} style={{ ...s.input, flex: '0 0 55px' }} disabled={running} />
        </div>
        {!steady && (
          <div style={s.row}>
            <label style={s.label}>t_end (s)</label>
            <input type="number" value={tEnd} onChange={e => setTEnd(e.target.value)} style={s.input} disabled={running} />
          </div>
        )}
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#78350f', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Thermal</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Solving heat transfer…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Thermal Results</span></div>
          <table style={s.table}><tbody>
            {result.max_temperature != null && <ResultRow label="T_max (°C)" value={Number(result.max_temperature).toFixed(2)} />}
            {result.min_temperature != null && <ResultRow label="T_min (°C)" value={Number(result.min_temperature).toFixed(2)} />}
            {result.max_heat_flux != null && <ResultRow label="Max heat flux" value={fmtSci(result.max_heat_flux, 'W/m²')} />}
            {result.convergence_residual != null && <ResultRow label="Residual" value={fmtSci(result.convergence_residual)} />}
          </tbody></table>
          {result.max_temperature != null && result.min_temperature != null && (
            <ThermalGradientBar tMin={result.min_temperature} tMax={result.max_temperature} />
          )}
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

function ThermalGradientBar({ tMin, tMax }) {
  const range = (tMax - tMin) || 1
  const steps = 20
  return (
    <div aria-label="Thermal gradient bar">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>Temperature gradient</div>
      <div style={{ display: 'flex', height: 14, borderRadius: 3, overflow: 'hidden' }}>
        {Array.from({ length: steps }, (_, i) => {
          const t = i / (steps - 1)
          const r = Math.round(t * 230 + 25)
          const b = Math.round((1 - t) * 230 + 25)
          return <div key={i} style={{ flex: 1, background: `rgb(${r},80,${b})` }} />
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginTop: 2 }}>
        <span>{Number(tMin).toFixed(1)}°C</span>
        <span>{Number(tMax).toFixed(1)}°C</span>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// ACOUSTICS  — fem_acoustics
// ══════════════════════════════════════════════════════════════════════════════

function AcousticsCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [fMin, setFMin]         = useState('20')
  const [fMax, setFMax]         = useState('2000')
  const [nModes, setNModes]     = useState('6')
  const [c, setC]               = useState('343')
  const [rho, setRho]           = useState('1.21')
  const [mode, setMode]         = useState('cavity_modes')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    run({
      analysis_type: 'acoustics',
      acoustics_mode: mode,
      c_sound: parseFloat(c) || 343,
      rho_fluid: parseFloat(rho) || 1.21,
      n_modes: parseInt(nModes, 10) || 6,
      freq_range: { f_min: parseFloat(fMin) || 20, f_max: parseFloat(fMax) || 2000 },
      // generic fallback
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [],
      mesh_size: 0.05,
      solver: 'fenicsx',
    })
  }

  const freqs = Array.isArray(result?.cavity_modes) ? result.cavity_modes
    : Array.isArray(result?.frequencies) ? result.frequencies : []

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="acoustics-card">
      <SectionHeader icon={Waves} label="Acoustics FEM / BEM" color="#818cf8" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Mode</label>
          <select value={mode} onChange={e => setMode(e.target.value)} style={s.select} disabled={running}>
            <option value="cavity_modes">Cavity modes (FEM)</option>
            <option value="bem_radiation">BEM radiation</option>
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>c (m/s)</label>
          <input type="number" value={c} onChange={e => setC(e.target.value)} style={s.input} disabled={running} />
          <label style={{ ...s.label, width: 40 }}>ρ (kg/m³)</label>
          <input type="number" value={rho} step="0.01" onChange={e => setRho(e.target.value)} style={{ ...s.input, flex: '0 0 55px' }} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Modes to extract</label>
          <input type="number" value={nModes} min="1" max="20" onChange={e => setNModes(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>f_min (Hz)</label>
          <input type="number" value={fMin} onChange={e => setFMin(e.target.value)} style={s.input} disabled={running} />
          <label style={{ ...s.label, width: 50 }}>f_max</label>
          <input type="number" value={fMax} onChange={e => setFMax(e.target.value)} style={{ ...s.input, flex: '0 0 70px' }} disabled={running} />
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#3730a3', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Acoustics</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Helmholtz eigensolve…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Acoustic Modes</span></div>
          <table style={s.table}>
            <thead><tr>
              <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>Mode</td>
              <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>Freq (Hz)</td>
              <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>λ (m)</td>
            </tr></thead>
            <tbody>{freqs.map((f, i) => (
              <tr key={i}>
                <td style={s.td}>{i + 1}</td>
                <td style={{ ...s.td, ...s.mono }}>{Number(f).toFixed(1)}</td>
                <td style={{ ...s.td, ...s.mono }}>{(343 / Number(f)).toFixed(3)}</td>
              </tr>
            ))}</tbody>
          </table>
          {result.spl_dB != null && <ResultRow label="SPL (dB)" value={String(Number(result.spl_dB).toFixed(1))} />}
          {result.radiation_efficiency != null && <ResultRow label="Radiation η" value={fmtSci(result.radiation_efficiency)} />}
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// ELECTROSTATICS  — fem_electrostatics
// ══════════════════════════════════════════════════════════════════════════════

function ElectrostaticsCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [eps, setEps]     = useState('8.854e-12')
  const [v0, setV0]       = useState('100')
  const [v1, setV1]       = useState('0')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    run({
      analysis_type: 'electrostatics',
      permittivity: parseFloat(eps) || 8.854e-12,
      voltage_bcs: [
        { face_tag: 1, value: parseFloat(v0) || 100 },
        { face_tag: 2, value: parseFloat(v1) || 0 },
      ],
      // generic fallback
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'pressure', face_tags: [2], value: 0 }],
      mesh_size: 0.02,
      solver: 'fenicsx',
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="electrostatics-card">
      <SectionHeader icon={Zap} label="Electrostatics (Poisson / Laplace)" color="#fde68a" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>ε (F/m)</label>
          <input type="text" value={eps} onChange={e => setEps(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>V on face 1 (V)</label>
          <input type="number" value={v0} onChange={e => setV0(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>V on face 2 (V)</label>
          <input type="number" value={v1} onChange={e => setV1(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#713f12', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Electrostatics</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Solving Laplace…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>E-field Results</span></div>
          <table style={s.table}><tbody>
            {result.max_electric_field != null && <ResultRow label="Max |E| (V/m)" value={fmtSci(result.max_electric_field)} />}
            {result.capacitance != null && <ResultRow label="Capacitance (F)" value={fmtSci(result.capacitance)} />}
            {result.energy != null && <ResultRow label="Stored energy (J)" value={fmtSci(result.energy)} />}
          </tbody></table>
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// MAGNETOSTATICS  — fem_magnetostatics
// ══════════════════════════════════════════════════════════════════════════════

function MagnetostaticsCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [mu, setMu]           = useState('1.2566e-6')
  const [jCurr, setJCurr]     = useState('1e6')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    run({
      analysis_type: 'magnetostatics',
      permeability: parseFloat(mu) || 1.2566e-6,
      current_density: parseFloat(jCurr) || 1e6,
      // generic fallback
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: 0 }],
      mesh_size: 0.02,
      solver: 'fenicsx',
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="magnetostatics-card">
      <SectionHeader icon={Zap} label="Magnetostatics (∇×A formulation)" color="#c084fc" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>μ (H/m)</label>
          <input type="text" value={mu} onChange={e => setMu(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>J (A/m²)</label>
          <input type="text" value={jCurr} onChange={e => setJCurr(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#4c1d95', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Magnetostatics</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Solving vector-potential…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>B-field Results</span></div>
          <table style={s.table}><tbody>
            {result.max_b_field != null && <ResultRow label="Max |B| (T)" value={fmtSci(result.max_b_field)} />}
            {result.inductance != null && <ResultRow label="Inductance (H)" value={fmtSci(result.inductance)} />}
            {result.magnetic_energy != null && <ResultRow label="Stored energy (J)" value={fmtSci(result.magnetic_energy)} />}
          </tbody></table>
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// HIGH-FREQUENCY EM  — fem_em_highfreq
// ══════════════════════════════════════════════════════════════════════════════

function EMHighFreqCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [mode, setMode]       = useState('waveguide')
  const [fMin, setFMin]       = useState('1e9')
  const [fMax, setFMax]       = useState('10e9')
  const [nFreqs, setNFreqs]   = useState('50')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    run({
      analysis_type: 'em_highfreq',
      em_mode: mode,
      freq_range: {
        f_min: parseFloat(fMin) || 1e9,
        f_max: parseFloat(fMax) || 10e9,
        n_pts: parseInt(nFreqs, 10) || 50,
      },
      // generic fallback
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [],
      mesh_size: 0.005,
      solver: 'fenicsx',
    })
  }

  const sparams = result?.s_params || result?.sparams
  const cutoffs = Array.isArray(result?.cutoff_frequencies) ? result.cutoff_frequencies : []

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="em-highfreq-card">
      <SectionHeader icon={Activity} label="High-Frequency EM (waveguide / S-params / FDTD)" color="#22d3ee" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Mode</label>
          <select value={mode} onChange={e => setMode(e.target.value)} style={s.select} disabled={running}>
            <option value="waveguide">Waveguide modes</option>
            <option value="s_params">S-parameters</option>
            <option value="fdtd">FDTD transient</option>
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>f_min (Hz)</label>
          <input type="text" value={fMin} onChange={e => setFMin(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>f_max (Hz)</label>
          <input type="text" value={fMax} onChange={e => setFMax(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Freq pts</label>
          <input type="number" value={nFreqs} min="2" max="500" onChange={e => setNFreqs(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#164e63', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run EM HF</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Maxwell eigensolve…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>EM Results</span></div>
          {cutoffs.length > 0 && (
            <table style={s.table}>
              <thead><tr>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>Mode</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>f_c (GHz)</td>
              </tr></thead>
              <tbody>{cutoffs.map((fc, i) => (
                <tr key={i}>
                  <td style={s.td}>TE{i + 1}0</td>
                  <td style={{ ...s.td, ...s.mono }}>{(Number(fc) / 1e9).toFixed(3)}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
          {sparams && (
            <table style={s.table}><tbody>
              {Object.entries(sparams).map(([k, v]) => (
                <ResultRow key={k} label={k} value={typeof v === 'number' ? fmtSci(v, 'dB') : String(v)} />
              ))}
            </tbody></table>
          )}
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// CFD NAVIER-STOKES  — cfd_navier_stokes_steady
// ══════════════════════════════════════════════════════════════════════════════

function CFDNavierStokesCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [nu, setNu]           = useState('1.5e-5')   // kinematic viscosity (air)
  const [uInlet, setUInlet]   = useState('1.0')
  const [nIter, setNIter]     = useState('100')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    run({
      analysis_type: 'cfd_navier_stokes_steady',
      kinematic_viscosity: parseFloat(nu) || 1.5e-5,
      inlet_velocity: parseFloat(uInlet) || 1.0,
      max_iterations: parseInt(nIter, 10) || 100,
      // generic fallback
      material_props: { E: 1e5, nu: 0.3, rho: 1.21, yield_strength: 1e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'pressure', face_tags: [2], value: 0 }],
      mesh_size: 0.05,
      solver: 'fenicsx',
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="cfd-ns-card">
      <SectionHeader icon={Wind} label="CFD — 2D Navier-Stokes (projection)" color="#34d399" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>ν (m²/s)</label>
          <input type="text" value={nu} onChange={e => setNu(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>U_inlet (m/s)</label>
          <input type="number" value={uInlet} step="0.1" onChange={e => setUInlet(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Max iterations</label>
          <input type="number" value={nIter} min="10" onChange={e => setNIter(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#065f46', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run N-S</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Fractional-step projection…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>CFD Results</span></div>
          <table style={s.table}><tbody>
            {result.max_velocity != null && <ResultRow label="U_max (m/s)" value={Number(result.max_velocity).toFixed(4)} />}
            {result.reynolds_number != null && <ResultRow label="Re" value={fmtSci(result.reynolds_number)} />}
            {result.pressure_drop != null && <ResultRow label="ΔP (Pa)" value={Number(result.pressure_drop).toFixed(2)} />}
            {result.iterations != null && <ResultRow label="Iterations" value={String(result.iterations)} />}
          </tbody></table>
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// CFD POTENTIAL  — cfd_potential_cylinder
// ══════════════════════════════════════════════════════════════════════════════

function CFDPotentialCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [uInf, setUInf]   = useState('1.0')
  const [R, setR]         = useState('0.5')
  const [nPts, setNPts]   = useState('100')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status
  const cpArray   = Array.isArray(result?.cp) ? result.cp : []

  function handleRun() {
    run({
      analysis_type: 'cfd_potential_cylinder',
      u_inf: parseFloat(uInf) || 1.0,
      radius: parseFloat(R) || 0.5,
      n_pts: parseInt(nPts, 10) || 100,
      // generic fallback
      material_props: { E: 1e5, nu: 0.3, rho: 1.21, yield_strength: 1e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [],
      mesh_size: 0.05,
      solver: 'fenicsx',
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="cfd-potential-card">
      <SectionHeader icon={Wind} label="Potential Flow — Cylinder" color="#6ee7b7" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>U_∞ (m/s)</label>
          <input type="number" value={uInf} step="0.1" onChange={e => setUInf(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Radius (m)</label>
          <input type="number" value={R} step="0.05" onChange={e => setR(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Surface pts</label>
          <input type="number" value={nPts} min="10" max="500" onChange={e => setNPts(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#134e4a', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Potential Flow</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Solving Laplace ∇²φ=0…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Potential Flow Results</span></div>
          <table style={s.table}><tbody>
            {result.max_velocity != null && <ResultRow label="U_max (m/s)" value={Number(result.max_velocity).toFixed(4)} />}
            {result.stagnation_pressure != null && <ResultRow label="P_stag (Pa)" value={Number(result.stagnation_pressure).toFixed(2)} />}
            {result.drag_coefficient != null && <ResultRow label="C_D" value={Number(result.drag_coefficient).toFixed(4)} />}
          </tbody></table>
          {cpArray.length > 0 && <CpPlot cp={cpArray} />}
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

function CpPlot({ cp }) {
  const W = 200, H = 60
  if (!cp.length) return null
  const minCp = Math.min(...cp)
  const maxCp = Math.max(...cp)
  const range = (maxCp - minCp) || 1
  const step = W / (cp.length - 1 || 1)
  const pts = cp.map((v, i) => `${(i * step).toFixed(1)},${(H - 4 - ((v - minCp) / range) * (H - 8)).toFixed(1)}`).join(' ')
  return (
    <div aria-label="Pressure coefficient plot">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>Cp around cylinder</div>
      <svg width={W} height={H} style={{ display: 'block', background: '#1f2937', borderRadius: 4 }}>
        <polyline points={pts} fill="none" stroke="#6ee7b7" strokeWidth="1.5" />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginTop: 2 }}>
        <span>0°</span><span>Cp (max {maxCp.toFixed(2)})</span><span>360°</span>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// PLATE / SHELL  — fem_plate_static_solve (MITC4)
// ══════════════════════════════════════════════════════════════════════════════

function PlateStaticCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [E, setE]           = useState('200e9')
  const [nu, setNu]         = useState('0.3')
  const [t, setT]           = useState('0.01')
  const [q, setQ]           = useState('1e4')
  const [Lx, setLx]         = useState('1.0')
  const [Ly, setLy]         = useState('1.0')
  const [bc, setBc]         = useState('simply_supported')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    run({
      analysis_type: 'plate_static',
      plate: {
        E: parseFloat(E) || 200e9,
        nu: parseFloat(nu) || 0.3,
        thickness: parseFloat(t) || 0.01,
        Lx: parseFloat(Lx) || 1.0,
        Ly: parseFloat(Ly) || 1.0,
      },
      load: { uniform_pressure: parseFloat(q) || 1e4 },
      boundary_condition: bc,
      // generic fallback
      material_props: { E: parseFloat(E) || 200e9, nu: parseFloat(nu) || 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'pressure', face_tags: [2], value: parseFloat(q) || 1e4 }],
      mesh_size: 0.05,
      solver: 'fenicsx',
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="plate-static-card">
      <SectionHeader icon={Layers} label="Plate / Shell Static (MITC4)" color="#a78bfa" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>BC type</label>
          <select value={bc} onChange={e => setBc(e.target.value)} style={s.select} disabled={running}>
            <option value="simply_supported">Simply supported</option>
            <option value="clamped">Clamped all edges</option>
            <option value="cantilever">Cantilever (one edge)</option>
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>E (Pa)</label>
          <input type="text" value={E} onChange={e => setE(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>ν</label>
          <input type="number" value={nu} step="0.01" min="0" max="0.5" onChange={e => setNu(e.target.value)} style={s.input} disabled={running} />
          <label style={{ ...s.label, width: 50 }}>t (m)</label>
          <input type="number" value={t} step="0.001" min="0.001" onChange={e => setT(e.target.value)} style={{ ...s.input, flex: '0 0 70px' }} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Lx (m)</label>
          <input type="number" value={Lx} step="0.1" onChange={e => setLx(e.target.value)} style={s.input} disabled={running} />
          <label style={{ ...s.label, width: 40 }}>Ly</label>
          <input type="number" value={Ly} step="0.1" onChange={e => setLy(e.target.value)} style={{ ...s.input, flex: '0 0 60px' }} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Pressure q (Pa)</label>
          <input type="text" value={q} onChange={e => setQ(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#4c1d95', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Plate</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="MITC4 assembly…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Plate Results</span></div>
          <table style={s.table}><tbody>
            {result.max_deflection != null && <ResultRow label="Max deflection (m)" value={fmtSci(result.max_deflection)} />}
            {result.max_moment_x != null && <ResultRow label="Mx_max (N·m/m)" value={fmtSci(result.max_moment_x)} />}
            {result.max_moment_y != null && <ResultRow label="My_max (N·m/m)" value={fmtSci(result.max_moment_y)} />}
            {result.first_natural_freq != null && <ResultRow label="f_1 (Hz)" value={Number(result.first_natural_freq).toFixed(2)} />}
          </tbody></table>
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// UNCERTAINTY PROPAGATION  — fem_propagate_uncertainty
// ══════════════════════════════════════════════════════════════════════════════

function UncertaintyCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [nSamples, setNSamples]   = useState('200')
  const [eSigma, setESigma]       = useState('5e9')
  const [fSigma, setFSigma]       = useState('5000')
  const [method, setMethod]       = useState('lhs')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    run({
      analysis_type: 'probabilistic',
      n_samples: parseInt(nSamples, 10) || 200,
      method,
      uncertain_params: [
        { name: 'E', nominal: 200e9, sigma: parseFloat(eSigma) || 5e9, distribution: 'normal' },
        { name: 'F', nominal: 100000, sigma: parseFloat(fSigma) || 5000, distribution: 'normal' },
      ],
      base_analysis: 'linear_static',
      // generic fallback
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: 100000 }],
      mesh_size: 0.02,
      solver: 'fenicsx',
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="uncertainty-card">
      <SectionHeader icon={Cpu} label="Probabilistic FEA (LHS + Karhunen-Loève)" color="#e879f9" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Sampling method</label>
          <select value={method} onChange={e => setMethod(e.target.value)} style={s.select} disabled={running}>
            <option value="lhs">Latin Hypercube (LHS)</option>
            <option value="mc">Monte Carlo</option>
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>N samples</label>
          <input type="number" value={nSamples} min="10" max="5000" onChange={e => setNSamples(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>σ_E (Pa)</label>
          <input type="text" value={eSigma} onChange={e => setESigma(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>σ_F (N)</label>
          <input type="text" value={fSigma} onChange={e => setFSigma(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#701a75', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Uncertainty</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Monte-Carlo / LHS sweep…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Probabilistic Results</span></div>
          <table style={s.table}><tbody>
            {result.mean_max_stress != null && <ResultRow label="μ(σ_max) (MPa)" value={(result.mean_max_stress / 1e6).toFixed(2)} />}
            {result.std_max_stress != null && <ResultRow label="σ(σ_max) (MPa)" value={(result.std_max_stress / 1e6).toFixed(2)} />}
            {result.pf_yield != null && <ResultRow label="P(failure)" value={fmtSci(result.pf_yield)} />}
            {result.cov != null && <ResultRow label="CoV" value={Number(result.cov).toFixed(4)} />}
            {result.samples_run != null && <ResultRow label="Samples" value={String(result.samples_run)} />}
          </tbody></table>
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TRUSS PLASTIC  — fem_truss_plastic
// ══════════════════════════════════════════════════════════════════════════════

function TrussPlasticCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [E, setE]         = useState('200e9')
  const [A, setA]         = useState('1e-4')
  const [sigY, setSigY]   = useState('275e6')
  const [H, setH]         = useState('2e9')
  const [loadMag, setLoadMag] = useState('5e4')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    // 3-bar truss example: nodes at (0,0), (0.5,0.5), (1,0) — simple arch
    const nodes = [[0, 0], [0.5, 0.5], [1, 0]]
    const elements = [[0, 1], [1, 2]]
    run({
      analysis_type: 'truss_plastic',
      nodes,
      elements,
      E: parseFloat(E) || 200e9,
      area: parseFloat(A) || 1e-4,
      sigma_y0: parseFloat(sigY) || 275e6,
      H: parseFloat(H) || 2e9,
      load_steps: [
        { forces: { '1': [0, -(parseFloat(loadMag) || 5e4)] }, fixed_dofs: [0, 1, 4, 5] },
        { forces: { '1': [0, -(parseFloat(loadMag) * 1.5 || 7.5e4)] }, fixed_dofs: [0, 1, 4, 5] },
      ],
      // generic fallback
      material_props: { E: parseFloat(E) || 200e9, nu: 0.3, rho: 7850, yield_strength: parseFloat(sigY) || 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: parseFloat(loadMag) || 5e4 }],
      mesh_size: 0.1,
      solver: 'fenicsx',
    })
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }} data-testid="truss-plastic-card">
      <SectionHeader icon={Square} label="2D Truss Plasticity (NR global)" color="#fdba74" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>E (Pa)</label>
          <input type="text" value={E} onChange={e => setE(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Area (m²)</label>
          <input type="text" value={A} onChange={e => setA(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>σ_y0 (Pa)</label>
          <input type="text" value={sigY} onChange={e => setSigY(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>H (Pa)</label>
          <input type="text" value={H} onChange={e => setH(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Load (N)</label>
          <input type="number" value={loadMag} onChange={e => setLoadMag(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={{ fontSize: 10, color: '#6b7280' }}>
          Topology: 3-node 2-bar arch — nodes at (0,0), (0.5,0.5), (1,0)
        </div>
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#7c2d12', ...(running ? s.buttonDisabled : {}) }}>
        {running ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</> : <><Play size={13} /> Run Truss</>}
      </button>
      <StatusArea jobStatus={jobStatus} error={error} runningMsg="Newton-Raphson assembly…" />
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Truss Results</span></div>
          <table style={s.table}><tbody>
            {result.max_stress != null && <ResultRow label="Max element stress" value={fmtMPa(result.max_stress)} />}
            {result.max_displacement != null && <ResultRow label="Max node disp. (m)" value={fmtSci(result.max_displacement)} />}
            {result.plastic_elements != null && <ResultRow label="Plastic elements" value={String(result.plastic_elements)} />}
          </tbody></table>
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TOP-LEVEL PANEL
// ══════════════════════════════════════════════════════════════════════════════

const SECTIONS = [
  { id: 'nonlinear',  label: 'Nonlinear & Dynamic', color: '#fb923c', icon: Activity },
  { id: 'thermal',    label: 'Thermal',              color: '#f59e0b', icon: Thermometer },
  { id: 'acousem',    label: 'Acoustics & EM',       color: '#818cf8', icon: Zap },
  { id: 'cfd',        label: 'CFD',                  color: '#34d399', icon: Wind },
  { id: 'plate_misc', label: 'Plate & Uncertainty',  color: '#a78bfa', icon: Layers },
]

/**
 * FEMSolverPanel — extended FEM panel wiring 20+ backend tools.
 *
 * Organised in 5 sections. Each section lazy-mounts its cards only when
 * the tab is active. Props: { projectId, fileId }
 */
export default function FEMSolverPanel({ projectId, fileId }) {
  const [activeSection, setActiveSection] = useState('nonlinear')

  return (
    <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 13 }}>
      {/* Section strip */}
      <div
        style={{
          display: 'flex',
          gap: 0,
          borderBottom: '1px solid #1f2937',
          background: '#0f172a',
          overflowX: 'auto',
        }}
        role="tablist"
        aria-label="FEM solver sections"
      >
        {SECTIONS.map(sec => {
          const active = activeSection === sec.id
          return (
            <button
              key={sec.id}
              role="tab"
              aria-selected={active}
              aria-controls={`fem-panel-${sec.id}`}
              id={`fem-tab-${sec.id}`}
              onClick={() => setActiveSection(sec.id)}
              style={{
                padding: '8px 12px',
                background: 'none',
                border: 'none',
                borderBottom: active ? `2px solid ${sec.color}` : '2px solid transparent',
                color: active ? sec.color : '#6b7280',
                cursor: 'pointer',
                fontSize: 11,
                fontWeight: active ? 700 : 400,
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                whiteSpace: 'nowrap',
                fontFamily: 'inherit',
                transition: 'color 0.15s',
                display: 'flex',
                alignItems: 'center',
                gap: 5,
              }}
            >
              <sec.icon size={11} />
              {sec.label}
            </button>
          )
        })}
      </div>

      {/* Panel body */}
      <div style={{ padding: '12px 0 0 0', display: 'flex', flexDirection: 'column', gap: 16 }}>

        {activeSection === 'nonlinear' && (
          <div role="tabpanel" id="fem-panel-nonlinear" aria-labelledby="fem-tab-nonlinear"
            style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <NonlinearStaticCard projectId={projectId} fileId={fileId} />
            <NonlinearBarCard    projectId={projectId} fileId={fileId} />
            <TrussPlasticCard    projectId={projectId} fileId={fileId} />
            <ExplicitDynamicsCard projectId={projectId} fileId={fileId} />
          </div>
        )}

        {activeSection === 'thermal' && (
          <div role="tabpanel" id="fem-panel-thermal" aria-labelledby="fem-tab-thermal">
            <ThermalCard projectId={projectId} fileId={fileId} />
          </div>
        )}

        {activeSection === 'acousem' && (
          <div role="tabpanel" id="fem-panel-acousem" aria-labelledby="fem-tab-acousem"
            style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <AcousticsCard      projectId={projectId} fileId={fileId} />
            <ElectrostaticsCard projectId={projectId} fileId={fileId} />
            <MagnetostaticsCard projectId={projectId} fileId={fileId} />
            <EMHighFreqCard     projectId={projectId} fileId={fileId} />
          </div>
        )}

        {activeSection === 'cfd' && (
          <div role="tabpanel" id="fem-panel-cfd" aria-labelledby="fem-tab-cfd"
            style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <CFDNavierStokesCard projectId={projectId} fileId={fileId} />
            <CFDPotentialCard    projectId={projectId} fileId={fileId} />
          </div>
        )}

        {activeSection === 'plate_misc' && (
          <div role="tabpanel" id="fem-panel-plate_misc" aria-labelledby="fem-tab-plate_misc"
            style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <PlateStaticCard  projectId={projectId} fileId={fileId} />
            <UncertaintyCard  projectId={projectId} fileId={fileId} />
          </div>
        )}

      </div>
    </div>
  )
}
