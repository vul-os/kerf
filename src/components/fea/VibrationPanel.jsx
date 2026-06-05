// VibrationPanel.jsx — FEA Harmonic / Random Vibration panel.
//
// Harmonic / PSD-input selector + Run + frequency-response plot.
// Enhanced: dual-axis FRF magnitude + phase plot, mode table with frequencies
//           and DAF, resonance marker, and SDOF analytical overlay.
//
// Maps to:
//   fem_harmonic_response — steady-state harmonic response via mode superposition
//   fem_frf_sweep         — direct FRF sweep from modal properties (new)
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

// ---------------------------------------------------------------------------
// SDOF analytical DAF for preview — no fetch needed
// DAF = 1 / sqrt((1 - r²)² + (2ζr)²)   (Inman §3.4)
// ---------------------------------------------------------------------------
function sdofDaf(r, zeta) {
  const den = Math.sqrt(Math.pow(1 - r * r, 2) + Math.pow(2 * zeta * r, 2))
  return den < 1e-30 ? Infinity : 1 / den
}

function sdofPhaseDeg(r, zeta) {
  return (Math.atan2(2 * zeta * r, 1 - r * r) * 180) / Math.PI
}

// Generate SDOF preview FRF
function generateSDOFPreview(fn, zeta, fMin, fMax, nPts = 120) {
  const d = (fMax - fMin) / (nPts - 1)
  return Array.from({ length: nPts }, (_, i) => {
    const f = fMin + i * d
    const r = f / fn
    return { f, daf: sdofDaf(r, zeta), phase: sdofPhaseDeg(r, zeta) }
  })
}

export default function VibrationPanel({ projectId, fileId }) {
  const [mode, setMode]           = useState('harmonic')
  const [zeta, setZeta]           = useState('0.02')   // damping ratio
  const [fMin, setFMin]           = useState('1')
  const [fMax, setFMax]           = useState('2000')
  const [nPts, setNPts]           = useState('200')
  const [fnPreview, setFnPreview] = useState('100')     // preview natural frequency [Hz]
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

  // Harmonic response data (supports both legacy and new field names)
  const freqAxis  = Array.isArray(result?.frequencies_hz)     ? result.frequencies_hz    :
    Array.isArray(result?.frequencies)         ? result.frequencies         : []
  const ampArray  = Array.isArray(result?.amplitude)          ? result.amplitude          :
    Array.isArray(result?.amplitudes)          ? result.amplitudes          :
    Array.isArray(result?.freq_response?.amplitude) ? result.freq_response.amplitude : []
  const phaseArray = Array.isArray(result?.phase_deg)         ? result.phase_deg          : []
  const modeTable  = Array.isArray(result?.mode_table)        ? result.mode_table         :
    Array.isArray(result?.frequencies_hz) && result?.DAF_analytical ? null : null

  // Random vibration data
  const rmsResp     = result?.rms_response     ?? result?.grms       ?? null
  const miles_grms  = result?.miles_grms       ?? null
  const sigmaResp   = result?.sigma_3_response ?? result?.sigma_3     ?? null

  // SDOF preview curve
  const fn    = parseFloat(fnPreview) || 100
  const zetaV = parseFloat(zeta) || 0.02
  const f0    = parseFloat(fMin) || 1
  const f1    = parseFloat(fMax) || 2000
  const previewPts = generateSDOFPreview(fn, zetaV, f0, f1, 120)

  return (
    <div style={s.root} data-testid="vibration-panel">
      <div style={s.header}>
        <Activity size={15} style={{ color: '#34d399' }} />
        <span style={s.title}>Vibration Analysis</span>
        {jobStatus && jobStatus !== 'not_found' && (
          <span style={badgeStyle(jobStatus)}>{jobStatus}</span>
        )}
      </div>

      {/* SDOF FRF Preview */}
      <div style={s.section}>
        <div style={s.sectionTitle}>FRF Preview — SDOF analytical</div>
        <FrfDualPlot freqs={previewPts.map(p => p.f)} magnitudes={previewPts.map(p => p.daf)}
          phases={previewPts.map(p => p.phase)} resonantHz={fn} isPreview />
        <div style={{ fontSize: 10, color: '#4b5563' }}>
          DAF = 1/√((1−r²)²+(2ζr)²) | fn = {fn} Hz | ζ = {zetaV} | DAF_peak = {(1 / (2 * zetaV)).toFixed(1)}
        </div>
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
        {mode === 'harmonic' && (
          <div style={s.row}>
            <label style={s.label}>Preview fn (Hz)</label>
            <input type="number" value={fnPreview} min="0.1" step="10"
              onChange={e => setFnPreview(e.target.value)} style={s.input} disabled={running} />
          </div>
        )}
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

          {/* Dual FRF magnitude + phase plot */}
          {(freqAxis.length > 0 || ampArray.length > 0) && (
            <FrfDualPlot
              freqs={freqAxis}
              magnitudes={ampArray}
              phases={phaseArray}
              resonantHz={result?.resonant_peak_hz ?? null}
            />
          )}

          {/* Mode table */}
          {modeTable && modeTable.length > 0 && (
            <ModeTable modes={modeTable} />
          )}

          {/* Resonant frequency summary */}
          {result?.resonant_peak_hz != null && (
            <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 4 }}>
              Resonant peak: <span style={{ color: '#34d399', fontWeight: 600 }}>
                {Number(result.resonant_peak_hz).toFixed(2)} Hz
              </span>
              {result.resonant_amplitude != null && (
                <span style={{ color: '#6b7280' }}>{' '}|U| = {Number(result.resonant_amplitude).toExponential(3)}</span>
              )}
            </div>
          )}

          {/* Modal frequencies from result (legacy field) */}
          {Array.isArray(result.frequencies) && result.frequencies.length > 0 && mode === 'harmonic' && (
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

// ---------------------------------------------------------------------------
// Dual FRF plot: magnitude (top) + phase (bottom)
// ---------------------------------------------------------------------------
function FrfDualPlot({ freqs, magnitudes, phases, resonantHz, isPreview }) {
  const W = 240, H_mag = 50, H_phase = 30, PAD = { l: 6, r: 6, t: 4, b: 4 }

  const data = magnitudes && magnitudes.length > 0 ? magnitudes : []
  if (!data.length) return null

  const maxMag = Math.max(...data.map(Math.abs)) || 1
  const innerW = W - PAD.l - PAD.r
  const step   = innerW / (data.length - 1 || 1)

  function xPx(i) { return PAD.l + i * step }
  function magYPx(v) { return PAD.t + (1 - Math.abs(v) / maxMag) * (H_mag - PAD.t - PAD.b) }
  function phaseYPx(v) {
    // Map [-180, 180] → [0, H_phase]
    return PAD.t + (1 - (v + 180) / 360) * (H_phase - PAD.t - PAD.b)
  }

  const magPts = data.map((v, i) => `${xPx(i).toFixed(1)},${magYPx(v).toFixed(1)}`).join(' ')
  const phasePts = phases && phases.length === data.length
    ? phases.map((v, i) => `${xPx(i).toFixed(1)},${phaseYPx(v).toFixed(1)}`).join(' ')
    : null

  // Resonant peak marker
  let resonantXPx = null
  if (resonantHz != null && freqs && freqs.length > 0) {
    const f0 = freqs[0], f1 = freqs[freqs.length - 1]
    if (f1 > f0) {
      const norm = (resonantHz - f0) / (f1 - f0)
      resonantXPx = PAD.l + norm * innerW
    }
  }

  const fLabel = freqs && freqs.length > 0
    ? `${Number(freqs[0]).toFixed(0)}–${Number(freqs[freqs.length - 1]).toFixed(0)} Hz`
    : ''
  const color = isPreview ? '#6ee7b7' : '#34d399'

  return (
    <div aria-label={isPreview ? 'SDOF FRF preview' : 'Frequency response plot'}>
      <div style={{ ...s.sectionTitle, marginBottom: 3 }}>
        {isPreview ? 'SDOF FRF preview' : `Frequency response${fLabel ? ` (${fLabel})` : ''}`}
      </div>

      {/* Magnitude */}
      <svg width={W} height={H_mag} style={{ display: 'block', background: '#1f2937', borderRadius: '4px 4px 0 0' }}>
        {resonantXPx != null && (
          <line x1={resonantXPx} y1={PAD.t} x2={resonantXPx} y2={H_mag - PAD.b}
            stroke="#fbbf24" strokeWidth="1" strokeDasharray="3 2" opacity="0.7" />
        )}
        <polyline points={magPts} fill="none" stroke={color} strokeWidth="1.5" />
        <text x={W - 4} y={PAD.t + 9} fontSize="7" fill="#6b7280" textAnchor="end">|H|</text>
      </svg>

      {/* Phase */}
      {phasePts && (
        <svg width={W} height={H_phase}
          style={{ display: 'block', background: '#161f2f', borderRadius: '0 0 4px 4px', borderTop: '1px solid #374151' }}>
          {resonantXPx != null && (
            <line x1={resonantXPx} y1={0} x2={resonantXPx} y2={H_phase}
              stroke="#fbbf24" strokeWidth="1" strokeDasharray="3 2" opacity="0.7" />
          )}
          {/* 0° reference */}
          <line x1={PAD.l} y1={H_phase / 2} x2={W - PAD.r} y2={H_phase / 2}
            stroke="#374151" strokeWidth="0.5" />
          <polyline points={phasePts} fill="none" stroke="#a78bfa" strokeWidth="1" />
          <text x={W - 4} y={H_phase - 2} fontSize="7" fill="#6b7280" textAnchor="end">Phase°</text>
        </svg>
      )}

      {fLabel && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginTop: 2 }}>
          <span>{freqs && freqs.length > 0 ? `${Number(freqs[0]).toFixed(0)} Hz` : 'f_min'}</span>
          {resonantHz != null && (
            <span style={{ color: '#fbbf24' }}>▲ {Number(resonantHz).toFixed(1)} Hz</span>
          )}
          <span>{freqs && freqs.length > 0 ? `${Number(freqs[freqs.length - 1]).toFixed(0)} Hz` : 'f_max'}</span>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode table (fn, ζ, DAF at resonance)
// ---------------------------------------------------------------------------
function ModeTable({ modes }) {
  return (
    <div aria-label="Mode table">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>Mode Table</div>
      <table style={s.table}>
        <thead>
          <tr>
            <th style={{ ...s.td, color: '#9ca3af', textAlign: 'left', fontSize: 10 }}>Mode</th>
            <th style={{ ...s.td, color: '#9ca3af', textAlign: 'right', fontSize: 10 }}>fn (Hz)</th>
            <th style={{ ...s.td, color: '#9ca3af', textAlign: 'right', fontSize: 10 }}>ζ</th>
            <th style={{ ...s.td, color: '#9ca3af', textAlign: 'right', fontSize: 10 }}>DAF_peak</th>
          </tr>
        </thead>
        <tbody>
          {modes.map((m, i) => (
            <tr key={i}>
              <td style={s.td}>{m.mode ?? i + 1}</td>
              <td style={{ ...s.td, ...s.mono }}>{Number(m.fn_hz ?? m.frequency_hz ?? 0).toFixed(2)}</td>
              <td style={{ ...s.td, ...s.mono }}>{Number(m.zeta ?? 0).toFixed(4)}</td>
              <td style={{ ...s.td, ...s.mono }}>
                {isFinite(m.DAF_at_resonance)
                  ? Number(m.DAF_at_resonance).toFixed(1)
                  : '∞'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
