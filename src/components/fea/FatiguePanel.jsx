// FatiguePanel.jsx — FEA Fatigue & Durability panel.
//
// Material S-N curve picker + load-history input + Run + life contour viewer.
//
// Maps to fem_fatigue (S-N, ε-N, rainflow, Goodman/Gerber/SWT, Miner's rule).
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

export default function FatiguePanel({ projectId, fileId }) {
  const [preset, setPreset]         = useState('steel_1045')
  const [correction, setCorrection] = useState('goodman')
  const [damageParam, setDamageParam] = useState('von_mises')
  const [targetLife, setTargetLife] = useState('1e6')
  const [loadHistory, setLoadHistory] = useState(DEFAULT_HISTORY)
  const [running, setRunning]       = useState(false)
  const [status, setStatus]         = useState(null)
  const [error, setError]           = useState(null)
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

  return (
    <div style={s.root} data-testid="fatigue-panel">
      <div style={s.header}>
        <Activity size={15} style={{ color: '#f472b6' }} />
        <span style={s.title}>Fatigue &amp; Durability</span>
        {jobStatus && jobStatus !== 'not_found' && (
          <span style={badgeStyle(jobStatus)}>{jobStatus}</span>
        )}
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
          <div style={{ fontSize: 10, color: '#6b7280' }}>
            {parseHistory().length} values — min/max: {Math.min(...parseHistory()).toFixed(0)} / {Math.max(...parseHistory()).toFixed(0)} N
          </div>
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
                  <td style={{ ...s.td, ...s.mono }}>{Number(safetyFactor).toFixed(2)}</td>
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

          {(dmgMap.length > 0 || lifeMap.length > 0) && (
            <LifeContourBar data={lifeMap.length > 0 ? lifeMap : dmgMap} isLife={lifeMap.length > 0} />
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

// Horizontal bar showing life or damage distribution across nodes.
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
          // For life: higher = greener (longer life). For damage: higher = redder.
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

// Simple load history plot.
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
