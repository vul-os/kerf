// ModalPanel.jsx — FEA Modal Analysis panel.
//
// N-modes selector + Run + modes table (frequency, modal participation) +
// mode-shape viewer.
//
// Dispatches POST /api/projects/{pid}/files/{fid}/fem with
// analysis_type:"modal".
//
// Props: { projectId, fileId }

import { useState, useRef } from 'react'
import { Activity, AlertTriangle, CheckCircle, Loader2, Play } from 'lucide-react'
import { useAuth } from '../../store/auth.js'
import { submitFemJob, pollFemStatus } from './feaApi.js'
import { s, badgeStyle } from './feaStyles.js'

const MATERIAL_PRESETS = {
  steel:     { label: 'Steel (S275)',       E: 200e9, nu: 0.3,   rho: 7850, yield_strength: 275e6 },
  aluminium: { label: 'Aluminium 6061-T6',  E: 68.9e9, nu: 0.33, rho: 2700, yield_strength: 276e6 },
  titanium:  { label: 'Titanium Ti-6Al-4V', E: 113.8e9, nu: 0.342, rho: 4430, yield_strength: 880e6 },
}

export default function ModalPanel({ projectId, fileId }) {
  const [preset, setPreset]   = useState('steel')
  const [nModes, setNModes]   = useState('6')
  const [faceTag, setFaceTag] = useState('1')   // fixed BC face
  const [running, setRunning] = useState(false)
  const [status, setStatus]   = useState(null)
  const [error, setError]     = useState(null)
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
      analysis_type: 'modal',
      n_modes: parseInt(nModes, 10) || 6,
      material_props: { E: mat.E, nu: mat.nu, rho: mat.rho, yield_strength: mat.yield_strength },
      boundary_conditions: [{ type: 'fixed', face_tags: [parseInt(faceTag, 10) || 1] }],
      loads: [],           // modal analysis — no static loads needed
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
  const freqs     = Array.isArray(result?.frequencies) ? result.frequencies : []
  const shapes    = Array.isArray(result?.mode_shapes)  ? result.mode_shapes  : []

  return (
    <div style={s.root} data-testid="modal-panel">
      <div style={s.header}>
        <Activity size={15} style={{ color: '#a78bfa' }} />
        <span style={s.title}>Modal Analysis</span>
        {jobStatus && jobStatus !== 'not_found' && (
          <span style={badgeStyle(jobStatus)}>{jobStatus}</span>
        )}
      </div>

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
          <label style={s.label}>Number of modes</label>
          <input type="number" value={nModes} min="1" max="20"
            onChange={e => setNModes(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Fixed BC face tag</label>
          <input type="number" value={faceTag} min="0"
            onChange={e => setFaceTag(e.target.value)} style={s.input} disabled={running} />
        </div>
      </div>

      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#5b21b6', ...(running ? s.buttonDisabled : {}) }}>
        {running
          ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</>
          : <><Play size={13} /> Run Modal</>}
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
            <span>Mode Table</span>
          </div>
          <table style={s.table}>
            <thead>
              <tr>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>Mode</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>Frequency (Hz)</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>Modal Participation</td>
              </tr>
            </thead>
            <tbody>
              {freqs.map((f, i) => {
                const shape = shapes[i]
                const participation = shape
                  ? Math.sqrt(shape.reduce((acc, v) => {
                      const mag = Array.isArray(v) ? Math.sqrt(v.reduce((a, x) => a + x * x, 0)) : Math.abs(Number(v) || 0)
                      return acc + mag * mag
                    }, 0)).toExponential(2)
                  : '—'
                return (
                  <tr key={i}>
                    <td style={s.td}>Mode {i + 1}</td>
                    <td style={{ ...s.td, ...s.mono }}>{Number(f).toFixed(2)} Hz</td>
                    <td style={{ ...s.td, ...s.mono }}>{participation}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {freqs.length > 0 && (
            <ModeShapeBar freqs={freqs} />
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
          <span>{jobStatus === 'queued' ? 'Queued…' : 'Extracting modes…'}</span>
        </div>
      )}
    </div>
  )
}

// Simple frequency spectrum bar chart.
function ModeShapeBar({ freqs }) {
  const max = Math.max(...freqs) || 1
  return (
    <div aria-label="Mode frequency spectrum">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>Frequency spectrum</div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 40 }}>
        {freqs.map((f, i) => (
          <div key={i} style={{
            flex: 1,
            height: `${Math.max(4, (f / max) * 100)}%`,
            background: '#a78bfa',
            borderRadius: '2px 2px 0 0',
            title: `Mode ${i + 1}: ${f.toFixed(1)} Hz`,
          }} />
        ))}
      </div>
    </div>
  )
}
