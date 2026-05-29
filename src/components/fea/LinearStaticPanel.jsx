// LinearStaticPanel.jsx — FEA Linear Static solve panel.
//
// Load editor (force/pressure/distributed) + boundary-condition editor
// (fixed/roller/symmetry) + Run button + von Mises contour viewer.
//
// Dispatches POST /api/projects/{pid}/files/{fid}/fem with
// analysis_type:"linear_static" and polls until done.
//
// Props: { projectId, fileId }

import { useState, useRef } from 'react'
import { Activity, AlertTriangle, CheckCircle, Loader2, Play, Plus, Trash2 } from 'lucide-react'
import { useAuth } from '../../store/auth.js'
import { submitFemJob, pollFemStatus } from './feaApi.js'
import { s, badgeStyle } from './feaStyles.js'

const MATERIAL_PRESETS = {
  steel:     { label: 'Steel (S275)',         E: 200e9, nu: 0.3,   rho: 7850, yield_strength: 275e6 },
  aluminium: { label: 'Aluminium 6061-T6',    E: 68.9e9, nu: 0.33, rho: 2700, yield_strength: 276e6 },
  titanium:  { label: 'Titanium Ti-6Al-4V',   E: 113.8e9, nu: 0.342, rho: 4430, yield_strength: 880e6 },
  pla:       { label: 'PLA (3D-print)',        E: 3.5e9, nu: 0.36, rho: 1250, yield_strength: 50e6 },
}

const BC_TYPES   = ['fixed', 'roller', 'symmetry']
const LOAD_TYPES = ['force', 'pressure', 'distributed']

function fmtMPa(pa) {
  if (pa == null || !isFinite(pa)) return '—'
  return (pa / 1e6).toFixed(2) + ' MPa'
}
function fmtMm(m) {
  if (m == null || !isFinite(m)) return '—'
  return (m * 1000).toFixed(4) + ' mm'
}

export default function LinearStaticPanel({ projectId, fileId }) {
  const { accessToken } = useAuth()
  const [preset, setPreset]       = useState('steel')
  const [bcs, setBcs]             = useState([{ type: 'fixed', face_tag: '1' }])
  const [loads, setLoads]         = useState([{ type: 'pressure', face_tag: '2', value: '1e6' }])
  const [meshSize, setMeshSize]   = useState('0.01')
  const [running, setRunning]     = useState(false)
  const [status, setStatus]       = useState(null)   // { status, result?, error? }
  const [error, setError]         = useState(null)
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

    const mat = MATERIAL_PRESETS[preset]
    const body = {
      analysis_type: 'linear_static',
      material_props: { E: mat.E, nu: mat.nu, rho: mat.rho, yield_strength: mat.yield_strength },
      boundary_conditions: bcs.map(bc => ({
        type: bc.type === 'roller' || bc.type === 'symmetry' ? 'fixed' : bc.type,
        face_tags: [parseInt(bc.face_tag, 10) || 1],
      })),
      loads: loads.map(l => ({
        type: l.type === 'distributed' ? 'pressure' : l.type,
        face_tags: [parseInt(l.face_tag, 10) || 2],
        value: parseFloat(l.value) || 1e6,
      })),
      mesh_size: parseFloat(meshSize) || 0.01,
      solver: 'fenicsx',
    }

    try {
      const token = useAuth.getState().accessToken
      const ctx = { pid: projectId, fid: fileId, token }
      const queued = await submitFemJob(ctx, body)
      setStatus({ status: 'queued', job_id: queued.job_id })

      pollRef.current = setInterval(async () => {
        const s = await pollFemStatus(ctx)
        setStatus(s)
        if (s.status === 'done' || s.status === 'error') {
          stopPoll()
          setRunning(false)
        }
      }, 3000)
    } catch (e) {
      setError(e.message)
      setRunning(false)
    }
  }

  function addBC()  { setBcs(prev   => [...prev,  { type: 'fixed',    face_tag: '1' }]) }
  function addLoad(){ setLoads(prev  => [...prev,  { type: 'pressure', face_tag: '2', value: '1e6' }]) }
  function removeBC(i)   { setBcs(prev   => prev.filter((_, j) => j !== i)) }
  function removeLoad(i) { setLoads(prev => prev.filter((_, j) => j !== i)) }

  const result   = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  return (
    <div style={s.root} data-testid="linear-static-panel">
      <div style={s.header}>
        <Activity size={15} style={{ color: '#22d3ee' }} />
        <span style={s.title}>Linear Static</span>
        {jobStatus && jobStatus !== 'not_found' && (
          <span style={badgeStyle(jobStatus)}>{jobStatus}</span>
        )}
      </div>

      {/* Material */}
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Material</label>
          <select value={preset} onChange={e => setPreset(e.target.value)} style={s.select} disabled={running}>
            {Object.entries(MATERIAL_PRESETS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>Mesh size (m)</label>
          <input type="number" value={meshSize} onChange={e => setMeshSize(e.target.value)}
            style={s.input} step="0.001" min="0.001" disabled={running} />
        </div>
      </div>

      {/* Boundary conditions */}
      <div style={s.section}>
        <div style={{ ...s.sectionTitle, justifyContent: 'space-between' }}>
          <span>Boundary Conditions</span>
          <button onClick={addBC} disabled={running}
            style={{ background: 'none', border: 'none', color: '#22d3ee', cursor: 'pointer', padding: 0 }}
            title="Add BC" aria-label="Add boundary condition">
            <Plus size={13} />
          </button>
        </div>
        {bcs.map((bc, i) => (
          <div key={i} style={s.row}>
            <select value={bc.type} onChange={e => setBcs(bcs.map((b, j) => j === i ? { ...b, type: e.target.value } : b))}
              style={{ ...s.select, flex: '0 0 90px' }} disabled={running}>
              {BC_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <label style={{ ...s.label, width: 55 }}>face tag</label>
            <input type="number" value={bc.face_tag} min="0"
              onChange={e => setBcs(bcs.map((b, j) => j === i ? { ...b, face_tag: e.target.value } : b))}
              style={{ ...s.input, flex: '0 0 50px' }} disabled={running} />
            <button onClick={() => removeBC(i)} disabled={running || bcs.length <= 1}
              style={{ background: 'none', border: 'none', color: '#6b7280', cursor: 'pointer', padding: 0 }}
              aria-label="Remove boundary condition">
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>

      {/* Loads */}
      <div style={s.section}>
        <div style={{ ...s.sectionTitle, justifyContent: 'space-between' }}>
          <span>Loads</span>
          <button onClick={addLoad} disabled={running}
            style={{ background: 'none', border: 'none', color: '#22d3ee', cursor: 'pointer', padding: 0 }}
            title="Add load" aria-label="Add load">
            <Plus size={13} />
          </button>
        </div>
        {loads.map((l, i) => (
          <div key={i} style={{ ...s.row, flexWrap: 'wrap', gap: 4 }}>
            <select value={l.type} onChange={e => setLoads(loads.map((x, j) => j === i ? { ...x, type: e.target.value } : x))}
              style={{ ...s.select, flex: '0 0 90px' }} disabled={running}>
              {LOAD_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <label style={{ ...s.label, width: 55 }}>face</label>
            <input type="number" value={l.face_tag} min="0"
              onChange={e => setLoads(loads.map((x, j) => j === i ? { ...x, face_tag: e.target.value } : x))}
              style={{ ...s.input, flex: '0 0 44px' }} disabled={running} />
            <label style={{ ...s.label, width: 40 }}>value</label>
            <input type="number" value={l.value}
              onChange={e => setLoads(loads.map((x, j) => j === i ? { ...x, value: e.target.value } : x))}
              style={{ ...s.input, flex: '0 0 80px' }} disabled={running} />
            <button onClick={() => removeLoad(i)} disabled={running || loads.length <= 1}
              style={{ background: 'none', border: 'none', color: '#6b7280', cursor: 'pointer', padding: 0 }}
              aria-label="Remove load">
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>

      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, ...(running ? s.buttonDisabled : {}) }}>
        {running
          ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</>
          : <><Play size={13} /> Run Linear Static</>}
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
            <span>Results — von Mises contour</span>
          </div>
          <table style={s.table}>
            <tbody>
              {result.max_vonmises_stress != null && (
                <tr>
                  <td style={s.td}>Max von Mises</td>
                  <td style={{ ...s.td, ...s.mono }}>{fmtMPa(result.max_vonmises_stress)}</td>
                </tr>
              )}
              {result.max_displacement != null && (
                <tr>
                  <td style={s.td}>Max Displacement</td>
                  <td style={{ ...s.td, ...s.mono }}>{fmtMm(result.max_displacement)}</td>
                </tr>
              )}
              {result.fos != null && result.fos > 0 && (
                <tr>
                  <td style={s.td}>Factor of Safety</td>
                  <td style={{ ...s.td, ...s.mono }}>{Number(result.fos).toFixed(2)}</td>
                </tr>
              )}
            </tbody>
          </table>
          {Array.isArray(result.stresses) && result.stresses.length > 0 && (
            <VonMisesBar stresses={result.stresses} maxStress={result.max_vonmises_stress} />
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
          <span>{jobStatus === 'queued' ? 'Queued…' : 'Solving…'}</span>
        </div>
      )}
    </div>
  )
}

// Compact horizontal colour bar showing the von-Mises stress range.
function VonMisesBar({ stresses, maxStress }) {
  const max = maxStress || Math.max(...stresses) || 1
  // Build 20 buckets
  const N = 20
  const buckets = Array(N).fill(0)
  for (const v of stresses) {
    const idx = Math.min(N - 1, Math.floor((v / max) * N))
    buckets[idx]++
  }
  const peak = Math.max(...buckets) || 1
  return (
    <div aria-label="von Mises stress distribution">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>Stress distribution</div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 40 }}>
        {buckets.map((count, i) => {
          const t = i / (N - 1)  // 0→1 = blue→red
          const r = Math.round(t * 255)
          const b = Math.round((1 - t) * 255)
          return (
            <div key={i} style={{
              flex: 1,
              height: `${Math.max(2, (count / peak) * 100)}%`,
              background: `rgb(${r},80,${b})`,
              borderRadius: '2px 2px 0 0',
            }} />
          )
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginTop: 2 }}>
        <span>0 MPa</span>
        <span>{(max / 1e6).toFixed(1)} MPa</span>
      </div>
    </div>
  )
}
