// FatiguePanel.jsx — FEA Fatigue & Durability panel.
//
// Material S-N curve picker + load-history input + Run + life contour viewer.
// Enhanced: S-N curve (Wöhler) SVG visualization, Haigh diagram, and
//           damage/life contour with mean-stress correction display.
//
// Maps to fem_fatigue (S-N, ε-N, rainflow, Goodman/Gerber/SWT, Miner's rule),
//         fem_sn_curve (Basquin S-N curve data),
//         fem_haigh_diagram (Goodman/Gerber/SWT/Langer boundaries).
// Dispatches POST /api/projects/{pid}/files/{fid}/fem with
// analysis_type:"fatigue".
//
// Props: { projectId, fileId }

import { useState, useRef } from 'react'
import { Activity, AlertTriangle, CheckCircle, Loader2, Play } from 'lucide-react'
import { useAuth } from '../../store/auth.js'
import { submitFemJob, pollFemStatus } from './feaApi.js'
import { s, badgeStyle } from './feaStyles.js'

// S-N curve presets — (Su, Se, b, c) from Shigley / Juvinall
const SN_PRESETS = {
  steel_1045:  { label: 'Steel 1045 (Machined)',       Su: 690e6, Sy: 580e6, Se: 241.5e6, b: -0.085, c: -0.600, E: 207e9 },
  steel_4340:  { label: 'Steel 4340 (Q&T 600°F)',      Su: 1480e6, Sy: 1380e6, Se: 620e6, b: -0.073, c: -0.660, E: 207e9 },
  al_6061_t6:  { label: 'Aluminium 6061-T6',           Su: 310e6, Sy: 276e6, Se: 97e6,   b: -0.110, c: -0.664, E: 68.9e9 },
  al_7075_t6:  { label: 'Aluminium 7075-T6',           Su: 572e6, Sy: 503e6, Se: 159e6,  b: -0.097, c: -0.650, E: 72e9 },
  titanium:    { label: 'Titanium Ti-6Al-4V',          Su: 950e6, Sy: 880e6, Se: 510e6,  b: -0.100, c: -0.680, E: 114e9 },
}

const CORRECTION_METHODS = [
  { id: 'goodman', label: 'Goodman (conservative)' },
  { id: 'gerber',  label: 'Gerber (less conservative)' },
  { id: 'swt',     label: 'Smith-Watson-Topper (SWT)' },
]

const DAMAGE_PARAMS = [
  { id: 'von_mises',     label: 'von Mises (signed)' },
  { id: 'max_principal', label: 'Max principal stress' },
]

const DEFAULT_HISTORY = '-200,400,-200,350,-100,300,0,300,-100,200'

// ---------------------------------------------------------------------------
// S-N curve generator (pure JS, Basquin equation — no fetch required)
// σ_a = sf_prime · (2N)^b  (Shigley §6-7)
// ---------------------------------------------------------------------------
function generateSNCurve(mat, nPoints = 40) {
  const { sf_prime, b, Se, Su } = mat
  const sfp = sf_prime || 1.5 * Su
  const logMin = 2, logMax = 8
  const pts = []
  for (let i = 0; i < nPoints; i++) {
    const logN = logMin + (i / (nPoints - 1)) * (logMax - logMin)
    const N = Math.pow(10, logN)
    const sigma_a = sfp * Math.pow(2 * N, b)
    pts.push({ N, sigma_a_mpa: sigma_a / 1e6 })
  }
  return pts
}

// Goodman boundary at endurance limit: σ_a / Se + σ_m / Su = 1
function generateHaighGoodman(mat, nPts = 40) {
  const { Su, Se } = mat
  const pts = []
  for (let i = 0; i < nPts; i++) {
    const sigma_m = (i / (nPts - 1)) * Su
    const sigma_a = Math.max(Se * (1 - sigma_m / Su), 0)
    pts.push({ sigma_m_mpa: sigma_m / 1e6, sigma_a_mpa: sigma_a / 1e6 })
  }
  return pts
}

export default function FatiguePanel({ projectId, fileId }) {
  const [preset, setPreset]         = useState('steel_1045')
  const [correction, setCorrection] = useState('goodman')
  const [damageParam, setDamageParam] = useState('von_mises')
  const [targetLife, setTargetLife] = useState('1e6')
  const [loadHistory, setLoadHistory] = useState(DEFAULT_HISTORY)
  const [running, setRunning]       = useState(false)
  const [status, setStatus]         = useState(null)
  const [error, setError]           = useState(null)
  const [showHaigh, setShowHaigh]   = useState(false)
  const pollRef = useRef(null)

  function stopPoll() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  function parseHistory() {
    return loadHistory.split(',')
      .map(v => parseFloat(v.trim()))
      .filter(v => isFinite(v))
  }

  async function handleRun() {
    if (!projectId || !fileId) return
    setError(null)
    setRunning(true)
    setStatus(null)
    stopPoll()

    const mat = SN_PRESETS[preset]
    const history = parseHistory()

    const body = {
      analysis_type: 'fatigue',
      // fem_fatigue params
      material: {
        Su: mat.Su,
        Sy: mat.Sy,
        Se: mat.Se,
        b:  mat.b,
        c:  mat.c,
        E:  mat.E,
        sf_prime: 1.5 * mat.Su,
        ef_prime: 0.59,
      },
      options: {
        correction: correction,
        damage_param: damageParam,
        life_curve: 'basquin',
        target_life: parseFloat(targetLife) || 1e6,
      },
      load_history: history,
      // Generic fem_run fallback fields for job queue
      material_props: { E: mat.E, nu: 0.3, rho: 7850, yield_strength: mat.Sy },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: history.slice(0, 1).map(v => ({ type: 'force', face_tags: [2], value: Math.abs(v) || 1e4 })),
      mesh_size: 0.01,
      solver: 'fenicsx',
    }

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

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  // Extract fatigue-specific fields or fall back to generic FEM result
  const minLifeCycles = result?.min_life_cycles ?? result?.min_life ?? null
  const safetyFactor  = result?.safety_factor   ?? result?.fos      ?? null
  const infiniteLife  = result?.infinite_life    ?? false
  const dmgMap        = result?.damage_map   ? Object.values(result.damage_map) : []
  const lifeMap       = result?.life_map     ? Object.values(result.life_map)   : []

  const mat = SN_PRESETS[preset]
  const snCurvePts = generateSNCurve(mat)
  const haighPts   = generateHaighGoodman(mat)

  return (
    <div style={s.root} data-testid="fatigue-panel">
      <div style={s.header}>
        <Activity size={15} style={{ color: '#f472b6' }} />
        <span style={s.title}>Fatigue &amp; Durability</span>
        {jobStatus && jobStatus !== 'not_found' && (
          <span style={badgeStyle(jobStatus)}>{jobStatus}</span>
        )}
      </div>

      {/* S-N Curve Visualisation */}
      <div style={s.section}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={s.sectionTitle}>S-N Curve (Wöhler) — {mat.label}</div>
          <button
            onClick={() => setShowHaigh(h => !h)}
            style={{
              marginLeft: 'auto', fontSize: 10, background: 'none', border: '1px solid #374151',
              borderRadius: 3, color: '#9ca3af', padding: '1px 6px', cursor: 'pointer',
            }}
          >
            {showHaigh ? 'S-N' : 'Haigh'}
          </button>
        </div>
        {showHaigh
          ? <HaighDiagramPlot pts={haighPts} mat={mat} />
          : <SNcurvePlot pts={snCurvePts} mat={mat} />}
        <div style={{ fontSize: 10, color: '#4b5563', marginTop: 2 }}>
          Basquin: σ_a = σ&#x2019;_f·(2N)^b | b = {mat.b} | Se = {(mat.Se / 1e6).toFixed(0)} MPa | Su = {(mat.Su / 1e6).toFixed(0)} MPa
        </div>
      </div>

      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>S-N material</label>
          <select value={preset} onChange={e => setPreset(e.target.value)} style={s.select} disabled={running}>
            {Object.entries(SN_PRESETS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>Mean-stress corr.</label>
          <select value={correction} onChange={e => setCorrection(e.target.value)} style={s.select} disabled={running}>
            {CORRECTION_METHODS.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>Damage parameter</label>
          <select value={damageParam} onChange={e => setDamageParam(e.target.value)} style={s.select} disabled={running}>
            {DAMAGE_PARAMS.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>Target life (cycles)</label>
          <input type="text" value={targetLife}
            onChange={e => setTargetLife(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.section}>
          <div style={s.sectionTitle}>Load history (N, comma-separated)</div>
          <textarea
            value={loadHistory}
            onChange={e => setLoadHistory(e.target.value)}
            disabled={running}
            rows={3}
            style={{
              ...s.input,
              flex: 'none',
              width: '100%',
              boxSizing: 'border-box',
              resize: 'vertical',
              fontFamily: 'inherit',
            }}
            aria-label="Load history values"
          />
          {parseHistory().length > 0 && (
            <div style={{ fontSize: 10, color: '#6b7280' }}>
              {parseHistory().length} values — min/max: {Math.min(...parseHistory()).toFixed(0)} / {Math.max(...parseHistory()).toFixed(0)} N
            </div>
          )}
        </div>
      </div>

      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#9d174d', ...(running ? s.buttonDisabled : {}) }}>
        {running
          ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</>
          : <><Play size={13} /> Run Fatigue</>}
      </button>

      {error && (
        <div style={s.errorBox} role="alert">
          <AlertTriangle size={13} />
          <span>{error}</span>
        </div>
      )}

      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}>
            <CheckCircle size={12} style={{ color: '#34d399' }} />
            <span>Fatigue Results</span>
          </div>
          {infiniteLife && (
            <div style={{ padding: '4px 8px', background: '#064e3b', borderRadius: 4, fontSize: 12, color: '#6ee7b7' }}>
              Infinite life — all amplitudes below endurance limit
            </div>
          )}
          <table style={s.table}>
            <tbody>
              {minLifeCycles != null && (
                <tr>
                  <td style={s.td}>Min life (critical node)</td>
                  <td style={{ ...s.td, ...s.mono }}>{Number(minLifeCycles).toExponential(2)} cycles</td>
                </tr>
              )}
              {safetyFactor != null && (
                <tr>
                  <td style={s.td}>Safety factor</td>
                  <td style={{ ...s.td, ...s.mono, color: Number(safetyFactor) >= 1 ? '#34d399' : '#f87171' }}>
                    {isFinite(Number(safetyFactor)) ? Number(safetyFactor).toFixed(2) : '∞'}
                  </td>
                </tr>
              )}
              {result.min_life_node != null && (
                <tr>
                  <td style={s.td}>Critical node</td>
                  <td style={{ ...s.td, ...s.mono }}>{result.min_life_node}</td>
                </tr>
              )}
              {result.max_vonmises_stress != null && (
                <tr>
                  <td style={s.td}>Max von Mises (static)</td>
                  <td style={{ ...s.td, ...s.mono }}>{(result.max_vonmises_stress / 1e6).toFixed(2)} MPa</td>
                </tr>
              )}
            </tbody>
          </table>

          {/* Life / damage contour bars */}
          {(dmgMap.length > 0 || lifeMap.length > 0) && (
            <LifeContourBar data={lifeMap.length > 0 ? lifeMap : dmgMap} isLife={lifeMap.length > 0} />
          )}

          {/* Multiaxial proportionality summary */}
          {result.multiaxial_flags && Object.keys(result.multiaxial_flags).length > 0 && (
            <MultiaxialSummary flags={result.multiaxial_flags} />
          )}

          {dmgMap.length === 0 && lifeMap.length === 0 && (
            <LoadHistoryPlot values={parseHistory()} />
          )}
        </div>
      )}

      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert">
          <AlertTriangle size={13} />
          <span>{status.error}</span>
        </div>
      )}
      {(jobStatus === 'queued' || jobStatus === 'running') && !result && (
        <div style={s.infoBox}>
          <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
          <span>{jobStatus === 'queued' ? 'Queued…' : 'Counting cycles (rainflow)…'}</span>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// S-N curve SVG plot (log-log scale)
// ---------------------------------------------------------------------------
function SNcurvePlot({ pts, mat }) {
  const W = 240, H = 70, PAD = { l: 30, r: 8, t: 6, b: 18 }
  const inner = { w: W - PAD.l - PAD.r, h: H - PAD.t - PAD.b }

  if (!pts || pts.length < 2) return null

  const logNMin = Math.log10(pts[0].N)
  const logNMax = Math.log10(pts[pts.length - 1].N)
  const sigmaMin = Math.max(0.1, Math.min(...pts.map(p => p.sigma_a_mpa)))
  const sigmaMax = Math.max(...pts.map(p => p.sigma_a_mpa))
  const logSMin = Math.log10(sigmaMin)
  const logSMax = Math.log10(sigmaMax)

  function xPx(N) {
    return PAD.l + ((Math.log10(N) - logNMin) / (logNMax - logNMin)) * inner.w
  }
  function yPx(sigma_mpa) {
    const logS = Math.log10(Math.max(sigma_mpa, 0.1))
    return PAD.t + (1 - (logS - logSMin) / (logSMax - logSMin)) * inner.h
  }

  const curvePts = pts.map(p => `${xPx(p.N).toFixed(1)},${yPx(p.sigma_a_mpa).toFixed(1)}`).join(' ')

  // Endurance limit line
  const Se_mpa = mat.Se / 1e6
  const seY = yPx(Se_mpa)

  // X-axis tick marks at 10^2, 10^4, 10^6, 10^8
  const xTicks = [2, 4, 6, 8].filter(e => e >= logNMin && e <= logNMax)

  return (
    <svg
      width={W} height={H}
      style={{ display: 'block', background: '#1f2937', borderRadius: 4 }}
      aria-label="S-N curve"
      role="img"
    >
      {/* Grid lines */}
      {xTicks.map(e => {
        const x = xPx(Math.pow(10, e))
        return <line key={e} x1={x} y1={PAD.t} x2={x} y2={H - PAD.b} stroke="#374151" strokeWidth="0.5" />
      })}

      {/* Endurance limit */}
      {Se_mpa > sigmaMin && Se_mpa < sigmaMax && (
        <>
          <line x1={PAD.l} y1={seY} x2={W - PAD.r} y2={seY}
            stroke="#6ee7b7" strokeWidth="1" strokeDasharray="4 2" />
          <text x={W - PAD.r - 2} y={seY - 2} fontSize="8" fill="#6ee7b7" textAnchor="end">Se</text>
        </>
      )}

      {/* S-N curve */}
      <polyline points={curvePts} fill="none" stroke="#f472b6" strokeWidth="1.5" />

      {/* Axis labels */}
      {xTicks.map(e => {
        const x = xPx(Math.pow(10, e))
        return (
          <text key={e} x={x} y={H - 3} fontSize="7" fill="#6b7280" textAnchor="middle">
            10^{e}
          </text>
        )
      })}
      <text x={PAD.l - 2} y={H - PAD.b} fontSize="7" fill="#6b7280" textAnchor="end" transform={`rotate(-90, ${PAD.l - 2}, ${H / 2})`}
        style={{ transformOrigin: `${PAD.l - 2}px ${H / 2}px` }}>
      </text>
      <text x={W / 2} y={H - 2} fontSize="7" fill="#6b7280" textAnchor="middle">N (cycles)</text>
      <text x={PAD.l + 2} y={PAD.t + 8} fontSize="7" fill="#9ca3af">σ_a (MPa)</text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Haigh (Goodman) diagram SVG
// ---------------------------------------------------------------------------
function HaighDiagramPlot({ pts, mat }) {
  const W = 240, H = 70, PAD = { l: 28, r: 8, t: 6, b: 18 }
  const inner = { w: W - PAD.l - PAD.r, h: H - PAD.t - PAD.b }

  if (!pts || pts.length < 2) return null

  const Su_mpa = mat.Su / 1e6
  const Se_mpa = mat.Se / 1e6
  const Sy_mpa = mat.Sy / 1e6

  function xPx(sigma_m) {
    return PAD.l + (sigma_m / Su_mpa) * inner.w
  }
  function yPx(sigma_a) {
    return PAD.t + (1 - sigma_a / Se_mpa) * inner.h
  }

  // Goodman line
  const goodmanPts = pts.map(p => `${xPx(p.sigma_m_mpa).toFixed(1)},${yPx(p.sigma_a_mpa).toFixed(1)}`).join(' ')

  // Gerber parabola: σ_a = Se * (1 - (σ_m/Su)^2)
  const gerberPts = pts.map(p => {
    const r = p.sigma_m_mpa / Su_mpa
    const a = Math.max(Se_mpa * (1 - r * r), 0)
    return `${xPx(p.sigma_m_mpa).toFixed(1)},${yPx(a).toFixed(1)}`
  }).join(' ')

  // Langer yield line: σ_a = Sy - σ_m
  const langerPts = pts
    .filter(p => Sy_mpa - p.sigma_m_mpa >= 0)
    .map(p => `${xPx(p.sigma_m_mpa).toFixed(1)},${yPx(Math.max(Sy_mpa - p.sigma_m_mpa, 0)).toFixed(1)}`)
    .join(' ')

  const xTicks = [0, 0.25, 0.5, 0.75, 1.0]

  return (
    <svg
      width={W} height={H}
      style={{ display: 'block', background: '#1f2937', borderRadius: 4 }}
      aria-label="Haigh diagram"
      role="img"
    >
      {/* Grid */}
      {xTicks.map(r => {
        const x = PAD.l + r * inner.w
        return <line key={r} x1={x} y1={PAD.t} x2={x} y2={H - PAD.b} stroke="#374151" strokeWidth="0.5" />
      })}

      {/* Gerber (less conservative) */}
      <polyline points={gerberPts} fill="none" stroke="#fb923c" strokeWidth="1" strokeDasharray="4 2" />
      {/* Langer yield */}
      <polyline points={langerPts} fill="none" stroke="#a78bfa" strokeWidth="1" strokeDasharray="2 2" />
      {/* Goodman */}
      <polyline points={goodmanPts} fill="none" stroke="#f472b6" strokeWidth="1.5" />

      {/* Legend */}
      <line x1={W - 70} y1={PAD.t + 5} x2={W - 55} y2={PAD.t + 5} stroke="#f472b6" strokeWidth="1.5" />
      <text x={W - 53} y={PAD.t + 8} fontSize="7" fill="#f472b6">Goodman</text>
      <line x1={W - 70} y1={PAD.t + 14} x2={W - 55} y2={PAD.t + 14} stroke="#fb923c" strokeWidth="1" strokeDasharray="4 2" />
      <text x={W - 53} y={PAD.t + 17} fontSize="7" fill="#fb923c">Gerber</text>
      <line x1={W - 70} y1={PAD.t + 23} x2={W - 55} y2={PAD.t + 23} stroke="#a78bfa" strokeWidth="1" strokeDasharray="2 2" />
      <text x={W - 53} y={PAD.t + 26} fontSize="7" fill="#a78bfa">Yield</text>

      {/* Axis labels */}
      {xTicks.slice(1).map(r => {
        const x = PAD.l + r * inner.w
        return (
          <text key={r} x={x} y={H - 3} fontSize="7" fill="#6b7280" textAnchor="middle">
            {(r * Su_mpa).toFixed(0)}
          </text>
        )
      })}
      <text x={W / 2} y={H - 2} fontSize="7" fill="#6b7280" textAnchor="middle">σ_m (MPa)</text>
      <text x={PAD.l + 2} y={PAD.t + 8} fontSize="7" fill="#9ca3af">σ_a</text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Multiaxial proportionality summary badge row
// ---------------------------------------------------------------------------
function MultiaxialSummary({ flags }) {
  const entries = Object.entries(flags)
  const npCount = entries.filter(([, v]) => v === 'non_proportional').length
  const total   = entries.length
  if (total === 0) return null
  return (
    <div style={{ fontSize: 11, color: '#9ca3af', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      <span>Multiaxial:</span>
      <span style={{ color: npCount === 0 ? '#34d399' : '#fbbf24' }}>
        {npCount === 0
          ? 'All proportional'
          : `${npCount}/${total} non-proportional`}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Life / damage contour bar chart
// ---------------------------------------------------------------------------
function LifeContourBar({ data, isLife }) {
  const N = Math.min(data.length, 30)
  const slice = data.slice(0, N)
  const max = Math.max(...slice.map(Math.abs)) || 1
  return (
    <div aria-label={isLife ? 'Life contour' : 'Damage contour'}>
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>
        {isLife ? 'Life contour (node sample)' : 'Damage contour (node sample)'}
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 40 }}>
        {slice.map((v, i) => {
          const norm = Math.abs(v) / max
          const r = isLife ? Math.round((1 - norm) * 200) : Math.round(norm * 220)
          const g = isLife ? Math.round(norm * 200) : Math.round((1 - norm) * 80)
          return (
            <div key={i} style={{
              flex: 1,
              height: `${Math.max(3, norm * 100)}%`,
              background: `rgb(${r},${g},60)`,
              borderRadius: '2px 2px 0 0',
            }} />
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Simple load history plot
// ---------------------------------------------------------------------------
function LoadHistoryPlot({ values }) {
  const W = 240, H = 50
  if (!values.length) return null
  const max = Math.max(...values.map(Math.abs)) || 1
  const step = W / (values.length - 1 || 1)
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(H / 2 - (v / max) * (H * 0.42)).toFixed(1)}`).join(' ')
  return (
    <div aria-label="Load history plot">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>Load history</div>
      <svg width={W} height={H} style={{ display: 'block', background: '#1f2937', borderRadius: 4 }}>
        <line x1="0" y1={H / 2} x2={W} y2={H / 2} stroke="#374151" strokeWidth="1" strokeDasharray="4 2" />
        <polyline points={pts} fill="none" stroke="#f472b6" strokeWidth="1.5" />
      </svg>
    </div>
  )
}
