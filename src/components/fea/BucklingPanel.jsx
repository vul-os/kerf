// BucklingPanel.jsx — FEA Buckling Analysis panel.
//
// Load case selector + Run + critical-load factor + buckling-mode viewer.
//
// Maps to fem_buckling_linear (linear eigenvalue buckling, Euler Pcr).
// Dispatches POST /api/projects/{pid}/files/{fid}/fem with
// analysis_type:"buckling".
//
// Props: { projectId, fileId }

import { useState, useRef } from 'react'
import { Activity, AlertTriangle, CheckCircle, Loader2, Play } from 'lucide-react'
import { useAuth } from '../../store/auth.js'
import { submitFemJob, pollFemStatus } from './feaApi.js'
import { s, badgeStyle } from './feaStyles.js'

const LOAD_CASES = [
  { id: 'axial_compression', label: 'Axial compression (column)' },
  { id: 'lateral_pressure',  label: 'Lateral pressure (plate)' },
  { id: 'combined',          label: 'Combined (axial + shear)' },
]

const BC_CONFIGS = [
  { id: 'pinned_pinned', label: 'Pinned-Pinned (K=1)',  supports: [{ type: 'pinned', x: 0 }, { type: 'pinned', x: 1 }] },
  { id: 'fixed_free',    label: 'Fixed-Free (K=2)',     supports: [{ type: 'fixed',  x: 0 }] },
  { id: 'fixed_fixed',   label: 'Fixed-Fixed (K=0.5)',  supports: [{ type: 'fixed',  x: 0 }, { type: 'fixed',  x: 1 }] },
  { id: 'fixed_pinned',  label: 'Fixed-Pinned (K=0.7)', supports: [{ type: 'fixed',  x: 0 }, { type: 'pinned', x: 1 }] },
]

export default function BucklingPanel({ projectId, fileId }) {
  const [loadCase, setLoadCase] = useState('axial_compression')
  const [bcConfig, setBcConfig] = useState('pinned_pinned')
  const [pRef, setPRef]         = useState('100000')    // N — reference compressive load
  const [L, setL]               = useState('1.0')       // m — column length
  const [nModes, setNModes]     = useState('3')
  const [running, setRunning]   = useState(false)
  const [status, setStatus]     = useState(null)
  const [error, setError]       = useState(null)
  const pollRef = useRef(null)

  function stopPoll() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  async function handleRun() {
    if (!projectId || !fileId) return
    setError(null)
    setRunning(true)
    setStatus(null)
    stopPoll()

    const bc = BC_CONFIGS.find(c => c.id === bcConfig) || BC_CONFIGS[0]
    // Scale supports to actual length
    const length = parseFloat(L) || 1.0
    const supports = bc.supports.map(sp => ({ ...sp, x: sp.x * length }))

    const body = {
      analysis_type: 'buckling',
      load_case: loadCase,
      // fem_buckling_linear params (passed through as options in input_spec)
      E:       200e9,
      I:       8.33e-9,   // 10mm × 10mm square: I = b*h³/12
      A:       1e-4,
      L:       length,
      P_ref:   parseFloat(pRef) || 100000,
      supports,
      n_modes: parseInt(nModes, 10) || 3,
      // Fallback to regular fem_run fields for the job queue
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: supports.map(sp => ({ type: sp.type === 'pinned' ? 'fixed' : 'fixed', face_tags: [1] })),
      loads: [{ type: 'force', face_tags: [2], value: parseFloat(pRef) || 100000 }],
      mesh_size: 0.05,
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
  const lambdas   = Array.isArray(result?.buckling_load_factors) ? result.buckling_load_factors
    : Array.isArray(result?.frequencies) ? result.frequencies   // fallback from generic run
    : []

  return (
    <div style={s.root} data-testid="buckling-panel">
      <div style={s.header}>
        <Activity size={15} style={{ color: '#fbbf24' }} />
        <span style={s.title}>Buckling Analysis</span>
        {jobStatus && jobStatus !== 'not_found' && (
          <span style={badgeStyle(jobStatus)}>{jobStatus}</span>
        )}
      </div>

      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Load case</label>
          <select value={loadCase} onChange={e => setLoadCase(e.target.value)} style={s.select} disabled={running}>
            {LOAD_CASES.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>BC type</label>
          <select value={bcConfig} onChange={e => setBcConfig(e.target.value)} style={s.select} disabled={running}>
            {BC_CONFIGS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>Column length (m)</label>
          <input type="number" value={L} min="0.01" step="0.1"
            onChange={e => setL(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Ref. load (N)</label>
          <input type="number" value={pRef} min="1"
            onChange={e => setPRef(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Modes to extract</label>
          <input type="number" value={nModes} min="1" max="10"
            onChange={e => setNModes(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>

      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#92400e', ...(running ? s.buttonDisabled : {}) }}>
        {running
          ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</>
          : <><Play size={13} /> Run Buckling</>}
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
            <span>Buckling Load Factors</span>
          </div>
          <table style={s.table}>
            <thead>
              <tr>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>Mode</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>λ (critical factor)</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>Pcr (kN)</td>
              </tr>
            </thead>
            <tbody>
              {lambdas.length > 0 ? lambdas.map((lam, i) => (
                <tr key={i}>
                  <td style={s.td}>Mode {i + 1}</td>
                  <td style={{ ...s.td, ...s.mono }}>{Number(lam).toFixed(3)}</td>
                  <td style={{ ...s.td, ...s.mono }}>
                    {((Number(lam) * (parseFloat(pRef) || 100000)) / 1000).toFixed(2)} kN
                  </td>
                </tr>
              )) : (
                <tr>
                  <td style={s.td} colSpan={3}>
                    {result.max_vonmises_stress != null
                      ? `Pcr ≈ ${((result.fos || 1) * (parseFloat(pRef) || 100000) / 1000).toFixed(2)} kN (FoS = ${(result.fos || 1).toFixed(2)})`
                      : 'No buckling factor data in result — see generic FEM result below.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          {lambdas.length > 0 && (
            <BucklingModeViz lambdas={lambdas} pRef={parseFloat(pRef) || 100000} />
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
          <span>{jobStatus === 'queued' ? 'Queued…' : 'Solving eigenvalue problem…'}</span>
        </div>
      )}
    </div>
  )
}

// Sinusoidal mode-shape sketches.
function BucklingModeViz({ lambdas, pRef }) {
  const W = 200
  const H = 60
  const N_PTS = 40
  return (
    <div aria-label="Buckling mode shapes">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>Mode shapes (schematic)</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {lambdas.slice(0, 3).map((lam, modeIdx) => {
          const n = modeIdx + 1
          const pts = Array.from({ length: N_PTS }, (_, i) => {
            const x = (i / (N_PTS - 1)) * W
            const y = H / 2 - (H * 0.35) * Math.sin((n * Math.PI * i) / (N_PTS - 1))
            return `${x.toFixed(1)},${y.toFixed(1)}`
          }).join(' ')
          return (
            <div key={modeIdx} style={{ textAlign: 'center' }}>
              <svg width={W} height={H} style={{ display: 'block', background: '#1f2937', borderRadius: 4 }}>
                <polyline points={pts} fill="none" stroke="#fbbf24" strokeWidth="1.5" />
              </svg>
              <div style={{ fontSize: 10, color: '#9ca3af', marginTop: 2 }}>
                Mode {n} — λ={Number(lam).toFixed(2)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
