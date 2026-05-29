// VibrationPanel.jsx — FEA Harmonic / Random Vibration panel.
//
// Harmonic / PSD-input selector + Run + frequency-response plot.
//
// Maps to:
//   fem_harmonic_response — steady-state harmonic response via mode superposition
//   fem_random_vibration_psd — random vibration RMS response to shaped PSD
//
// Dispatches POST /api/projects/{pid}/files/{fid}/fem with
// analysis_type:"harmonic" or "random_vibration".
//
// Props: { projectId, fileId }

import { useState, useRef } from 'react'
import { Activity, AlertTriangle, CheckCircle, Loader2, Play } from 'lucide-react'
import { useAuth } from '../../store/auth.js'
import { submitFemJob, pollFemStatus } from './feaApi.js'
import { s, badgeStyle } from './feaStyles.js'

const ANALYSIS_MODES = [
  { id: 'harmonic',         label: 'Harmonic (FRF / mode-superposition)' },
  { id: 'random_vibration', label: 'Random Vibration (PSD / Miles)' },
]

const PSD_PROFILES = [
  { id: 'mil_std_810g',  label: 'MIL-STD-810G (transportation)',
    table: [[10,0.04],[40,0.04],[500,0.0158],[2000,0.0158]] },
  { id: 'flat_0.04',     label: 'Flat 0.04 g²/Hz (10–2000 Hz)',
    table: [[10,0.04],[2000,0.04]] },
  { id: 'nasa_gsfc_7000', label: 'NASA GSFC-STD-7000 (random vibe)',
    table: [[20,0.026],[50,0.16],[800,0.16],[2000,0.026]] },
]

export default function VibrationPanel({ projectId, fileId }) {
  const [mode, setMode]           = useState('harmonic')
  const [zeta, setZeta]           = useState('0.02')   // damping ratio
  const [fMin, setFMin]           = useState('1')
  const [fMax, setFMax]           = useState('2000')
  const [nPts, setNPts]           = useState('200')
  const [psdProfile, setPsdProfile] = useState('mil_std_810g')
  const [running, setRunning]     = useState(false)
  const [status, setStatus]       = useState(null)
  const [error, setError]         = useState(null)
  const pollRef = useRef(null)

  function stopPoll() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  function buildBody() {
    const psd = PSD_PROFILES.find(p => p.id === psdProfile) || PSD_PROFILES[0]
    const base = {
      analysis_type: mode,
      modal_damping: parseFloat(zeta) || 0.02,
      freq_range: {
        f_min: parseFloat(fMin) || 1,
        f_max: parseFloat(fMax) || 2000,
        n_pts: parseInt(nPts, 10) || 200,
      },
      // Generic fem_run fields so the job queue accepts it
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: 1.0 }],  // unit harmonic force
      mesh_size: 0.01,
      solver: 'fenicsx',
    }
    if (mode === 'random_vibration') {
      base.psd_table = psd.table
      base.psd_profile = psdProfile
    }
    return base
  }

  async function handleRun() {
    if (!projectId || !fileId) return
    setError(null)
    setRunning(true)
    setStatus(null)
    stopPoll()

    try {
      const token = useAuth.getState().accessToken
      const ctx = { pid: projectId, fid: fileId, token }
      const queued = await submitFemJob(ctx, buildBody())
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

  // Harmonic response data
  const freqAxis  = Array.isArray(result?.frequencies)       ? result.frequencies       : []
  const ampArray  = Array.isArray(result?.amplitudes)        ? result.amplitudes         :
    Array.isArray(result?.freq_response?.amplitude) ? result.freq_response.amplitude : []

  // Random vibration data
  const rmsResp     = result?.rms_response     ?? result?.grms       ?? null
  const miles_grms  = result?.miles_grms       ?? null
  const sigmaResp   = result?.sigma_3_response ?? result?.sigma_3     ?? null

  return (
    <div style={s.root} data-testid="vibration-panel">
      <div style={s.header}>
        <Activity size={15} style={{ color: '#34d399' }} />
        <span style={s.title}>Vibration Analysis</span>
        {jobStatus && jobStatus !== 'not_found' && (
          <span style={badgeStyle(jobStatus)}>{jobStatus}</span>
        )}
      </div>

      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Analysis type</label>
          <select value={mode} onChange={e => setMode(e.target.value)} style={s.select} disabled={running}>
            {ANALYSIS_MODES.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>Damping ratio ζ</label>
          <input type="number" value={zeta} step="0.005" min="0.001" max="0.5"
            onChange={e => setZeta(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>f_min (Hz)</label>
          <input type="number" value={fMin} min="0.01"
            onChange={e => setFMin(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>f_max (Hz)</label>
          <input type="number" value={fMax} min="1"
            onChange={e => setFMax(e.target.value)} style={s.input} disabled={running} />
        </div>
        {mode === 'harmonic' && (
          <div style={s.row}>
            <label style={s.label}>Sweep points</label>
            <input type="number" value={nPts} min="10" max="2000"
              onChange={e => setNPts(e.target.value)} style={s.input} disabled={running} />
          </div>
        )}
        {mode === 'random_vibration' && (
          <div style={s.row}>
            <label style={s.label}>PSD profile</label>
            <select value={psdProfile} onChange={e => setPsdProfile(e.target.value)} style={s.select} disabled={running}>
              {PSD_PROFILES.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </div>
        )}
      </div>

      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#065f46', ...(running ? s.buttonDisabled : {}) }}>
        {running
          ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Running…</>
          : <><Play size={13} /> Run {mode === 'harmonic' ? 'Harmonic' : 'PSD'}</>}
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
            <span>{mode === 'harmonic' ? 'Frequency Response' : 'Random Vibration Results'}</span>
          </div>

          {mode === 'random_vibration' && (
            <table style={s.table}>
              <tbody>
                {rmsResp != null && (
                  <tr>
                    <td style={s.td}>RMS response (1σ)</td>
                    <td style={{ ...s.td, ...s.mono }}>{Number(rmsResp).toExponential(3)}</td>
                  </tr>
                )}
                {sigmaResp != null && (
                  <tr>
                    <td style={s.td}>3σ response</td>
                    <td style={{ ...s.td, ...s.mono }}>{Number(sigmaResp).toExponential(3)}</td>
                  </tr>
                )}
                {miles_grms != null && (
                  <tr>
                    <td style={s.td}>Miles' GRMS</td>
                    <td style={{ ...s.td, ...s.mono }}>{Number(miles_grms).toFixed(3)} g</td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          {/* FRF / frequency sweep plot */}
          {(freqAxis.length > 0 || ampArray.length > 0) && (
            <FrfPlot freqs={freqAxis} amplitudes={ampArray} />
          )}

          {/* Modal frequencies in result */}
          {Array.isArray(result.frequencies) && result.frequencies.length > 0 &&
            mode === 'harmonic' && (
            <div style={{ marginTop: 8 }}>
              <div style={s.sectionTitle}>Natural Frequencies</div>
              <table style={s.table}>
                <tbody>
                  {result.frequencies.map((f, i) => (
                    <tr key={i}>
                      <td style={s.td}>Mode {i + 1}</td>
                      <td style={{ ...s.td, ...s.mono }}>{Number(f).toFixed(2)} Hz</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
          <span>{jobStatus === 'queued' ? 'Queued…' : 'Sweeping frequencies…'}</span>
        </div>
      )}
    </div>
  )
}

// SVG frequency response plot.
function FrfPlot({ freqs, amplitudes }) {
  const W = 240, H = 60

  // Use amplitudes array if available; otherwise use freqs as a spectrum proxy
  const data = amplitudes.length > 0 ? amplitudes : freqs
  if (!data.length) return null

  const maxA  = Math.max(...data.map(Math.abs)) || 1
  const step  = W / (data.length - 1 || 1)
  const pts   = data.map((v, i) =>
    `${(i * step).toFixed(1)},${(H - 4 - (Math.abs(v) / maxA) * (H - 8)).toFixed(1)}`
  ).join(' ')

  const fLabel = freqs.length > 0
    ? `${Number(freqs[0]).toFixed(0)}–${Number(freqs[freqs.length - 1]).toFixed(0)} Hz`
    : ''

  return (
    <div aria-label="Frequency response plot">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>
        Frequency response{fLabel ? ` (${fLabel})` : ''}
      </div>
      <svg width={W} height={H} style={{ display: 'block', background: '#1f2937', borderRadius: 4 }}>
        <polyline points={pts} fill="none" stroke="#34d399" strokeWidth="1.5" />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginTop: 2 }}>
        <span>f_min</span>
        <span>Amplitude</span>
        <span>f_max</span>
      </div>
    </div>
  )
}
