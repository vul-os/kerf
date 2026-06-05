// SeismicRSAPanel.jsx — ASCE 7-22 Response-Spectrum Analysis (RSA) Panel
//
// Wires four seismic LLM backend tools into a tabbed UI:
//   seismic_build_asce7_spectrum  — ASCE 7-22 §11.4.5 design spectrum
//   seismic_rsa_sdof              — SDOF peak response (Sa, Sd, force)
//   seismic_rsa_mdof              — Multi-mode RSA (SRSS/CQC) per ASCE 7 §12.9
//   seismic_newmark_sdof          — Newmark-β SDOF time-history integration
//
// Tabs:
//   Spectrum   — Build ASCE 7-22 design response spectrum
//   SDOF       — Single-degree-of-freedom spectral response
//   MDOF/RSA   — Multi-mode RSA: input ω/ϕ/Γ, get combined displacements + base shear
//   Newmark    — Direct time-history integration (simple harmonic input)
//
// Units: SI throughout (m, kg, N, rad/s, s).  Sa displayed in g.
//
// Props: none — standalone panel.

import { useState, useCallback } from 'react'
import {
  Activity, BarChart2, AlertTriangle, CheckCircle,
  Loader2, Play, ChevronDown, ChevronUp, Zap,
} from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------

const s = {
  root:         { background: '#111827', padding: '12px', fontSize: 12, color: '#e5e7eb', minHeight: 200 },
  header:       { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 },
  title:        { fontWeight: 600, fontSize: 14, color: '#f9fafb' },
  subtitle:     { color: '#6b7280', fontSize: 11, marginLeft: 4 },
  tabs:         { display: 'flex', gap: 2, marginBottom: 10, flexWrap: 'wrap' },
  tab:          { padding: '4px 10px', borderRadius: 4, border: '1px solid #374151', background: '#1f2937', color: '#9ca3af', cursor: 'pointer', fontSize: 11 },
  tabActive:    { background: '#1d4ed8', borderColor: '#3b82f6', color: '#fff' },
  section:      { background: '#1f2937', borderRadius: 6, padding: '10px', marginBottom: 8 },
  sectionTitle: { display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600, marginBottom: 8, color: '#d1d5db', fontSize: 11 },
  row:          { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 },
  label:        { color: '#9ca3af', width: 190, flexShrink: 0, fontSize: 11 },
  input:        { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12, minWidth: 0 },
  textarea:     { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '5px 7px', color: '#f9fafb', fontSize: 11, fontFamily: 'monospace', minWidth: 0, resize: 'vertical' },
  select:       { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12 },
  button:       { display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 5, border: 'none', color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 500 },
  buttonDisabled:{ opacity: 0.5, cursor: 'not-allowed' },
  errorBox:     { display: 'flex', alignItems: 'flex-start', gap: 6, background: '#450a0a', borderRadius: 5, padding: '8px', color: '#fca5a5', marginTop: 8 },
  infoBox:      { display: 'flex', alignItems: 'center', gap: 6, background: '#1e3a5f', borderRadius: 5, padding: '8px', color: '#93c5fd', marginTop: 8 },
  resultBox:    { background: '#0f172a', borderRadius: 4, padding: '8px', marginTop: 6, fontFamily: 'monospace', fontSize: 11 },
  table:        { width: '100%', borderCollapse: 'collapse', marginTop: 4 },
  td:           { padding: '3px 6px', borderBottom: '1px solid #1f2937' },
  mono:         { fontFamily: 'monospace' },
  subhead:      { color: '#60a5fa', fontWeight: 600, marginBottom: 4, fontSize: 11 },
  divider:      { borderTop: '1px solid #374151', margin: '8px 0' },
  passChip:     { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700, background: '#064e3b', color: '#34d399' },
  warnChip:     { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700, background: '#451a03', color: '#fb923c' },
  spectrumGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(70px, 1fr))', gap: 2, maxHeight: 120, overflowY: 'auto', marginTop: 4 },
  spectrumCell: { padding: '2px 4px', fontSize: 10, background: '#1e293b', borderRadius: 2, textAlign: 'right', color: '#94a3b8' },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  return res.json()
}

function fmt(v, d = 4) {
  if (v == null) return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v)
    return Math.abs(v) > 1e4 || (Math.abs(v) < 1e-3 && v !== 0)
      ? v.toExponential(3)
      : v.toFixed(d)
  }
  return String(v)
}

function NumRow({ label, value, onChange, step = 'any', disabled, unit }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}{unit ? <span style={{ color: '#6b7280', marginLeft: 3 }}>({unit})</span> : null}</label>
      <input type="number" value={value} onChange={e => onChange(e.target.value)} step={step} disabled={disabled} style={s.input} />
    </div>
  )
}

function SelRow({ label, value, onChange, options, disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)} disabled={disabled} style={s.select}>
        {options.map(o =>
          typeof o === 'string'
            ? <option key={o} value={o}>{o}</option>
            : <option key={o.value} value={o.value}>{o.label}</option>
        )}
      </select>
    </div>
  )
}

function RunBtn({ onClick, running, label = 'Run' }) {
  return (
    <button onClick={onClick} disabled={running}
      style={{ ...s.button, background: '#1e40af', marginTop: 6, ...(running ? s.buttonDisabled : {}) }}>
      {running
        ? <><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> Computing…</>
        : <><Play size={12} /> {label}</>}
    </button>
  )
}

function Warnings({ warnings }) {
  if (!warnings || !warnings.length) return null
  return (
    <div style={{ ...s.infoBox, background: '#1c1a04', color: '#fde68a', marginTop: 4 }}>
      <AlertTriangle size={11} />
      <span>{warnings.join(' | ')}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mini spectrum ASCII chart
// ---------------------------------------------------------------------------
function SpectrumChart({ spectrum }) {
  if (!spectrum || !spectrum.length) return null
  // Display as a simple table of sampled points (every 10th point up to 20)
  const step = Math.max(1, Math.floor(spectrum.length / 20))
  const samples = spectrum.filter((_, i) => i % step === 0)
  const maxSa = Math.max(...samples.map(p => p[1]))
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ ...s.subhead }}>Spectrum (sampled)</div>
      <div style={s.spectrumGrid}>
        <div style={{ ...s.spectrumCell, color: '#60a5fa' }}>T (s)</div>
        <div style={{ ...s.spectrumCell, color: '#60a5fa' }}>Sa (g)</div>
        {samples.map((pt, i) => (
          <>
            <div key={`t${i}`} style={s.spectrumCell}>{pt[0].toFixed(2)}</div>
            <div key={`sa${i}`} style={{ ...s.spectrumCell, color: pt[1] === maxSa ? '#fbbf24' : '#94a3b8' }}>{pt[1].toFixed(4)}</div>
          </>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 1 — ASCE 7-22 Design Response Spectrum
// ---------------------------------------------------------------------------

function TabSpectrum() {
  const [spec, setSpec] = useState({ SDS: '1.0', SD1: '0.6', TL: '6', n_points: '100' })
  const [specR, setSpecR] = useState(null)
  const [specE, setSpecE] = useState(null)
  const [specRun, setSpecRun] = useState(false)

  const run = useCallback(async () => {
    setSpecRun(true); setSpecE(null); setSpecR(null)
    try {
      const r = await callTool('seismic_build_asce7_spectrum', {
        SDS: +spec.SDS, SD1: +spec.SD1, TL: +spec.TL, n_points: +spec.n_points,
      })
      setSpecR(r)
    } catch (e) { setSpecE(e.message) } finally { setSpecRun(false) }
  }, [spec])

  return (
    <div>
      <div style={{ ...s.section, borderLeft: '3px solid #6366f1' }}>
        <div style={s.sectionTitle}>
          <BarChart2 size={12} style={{ color: '#6366f1' }} />
          ASCE 7-22 §11.4.5 Design Response Spectrum
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>SITE PARAMETERS</div>
            <NumRow label="SDS (short period, g)" value={spec.SDS} onChange={v => setSpec(p => ({ ...p, SDS: v }))} />
            <NumRow label="SD1 (1-second, g)" value={spec.SD1} onChange={v => setSpec(p => ({ ...p, SD1: v }))} />
            <NumRow label="TL (long-period, s)" value={spec.TL} onChange={v => setSpec(p => ({ ...p, TL: v }))} step="1" />
            <NumRow label="n_points" value={spec.n_points} onChange={v => setSpec(p => ({ ...p, n_points: v }))} step="10" />
          </div>
          {specR && !specRun && !specE && (
            <div style={{ flex: 2, minWidth: 240 }}>
              <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>KEY PERIODS</div>
              <table style={{ ...s.table, marginTop: 0 }}><tbody>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>T0 = 0.2·SD1/SDS</td>
                    <td style={{ ...s.td, ...s.mono, color: '#fbbf24' }}>{fmt(specR.T0, 4)} s</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Ts = SD1/SDS</td>
                    <td style={{ ...s.td, ...s.mono, color: '#fbbf24' }}>{fmt(specR.Ts, 4)} s</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>TL (long-period transition)</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(specR.TL, 2)} s</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Peak Sa (SDS)</td>
                    <td style={{ ...s.td, ...s.mono, color: '#34d399', fontWeight: 700 }}>{fmt(specR.SDS, 3)} g</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>n_points returned</td>
                    <td style={{ ...s.td, ...s.mono }}>{specR.spectrum?.length ?? '—'}</td></tr>
              </tbody></table>
            </div>
          )}
        </div>
        <RunBtn onClick={run} running={specRun} label="Build ASCE 7-22 Spectrum" />
        {specE && <div style={s.errorBox}><AlertTriangle size={12} /><span>{specE}</span></div>}
        {specRun && <div style={s.infoBox}><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /><span>Building spectrum…</span></div>}
        {specR && !specRun && !specE && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 4 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>
                Spectrum built — T0={fmt(specR.T0,3)}s, Ts={fmt(specR.Ts,3)}s, SDS={fmt(specR.SDS,3)}g
              </span>
            </div>
            <Warnings warnings={specR.warnings} />
            <SpectrumChart spectrum={specR.spectrum} />
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 4 }}>
              Ref: ASCE 7-22 §11.4.5. Rising region T&lt;T0: Sa=SDS·(0.4+0.6T/T0). Plateau T0–Ts: Sa=SDS.
              Velocity region Ts–TL: Sa=SD1/T. Long-period: Sa=SD1·TL/T².
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 2 — SDOF Response
// ---------------------------------------------------------------------------

function TabSDOF() {
  const [sdof, setSdof] = useState({ omega_n: '3.14', zeta: '0.05', m: '10000', SDS: '1.0', SD1: '0.6', TL: '6' })
  const [sdofR, setSdofR] = useState(null)
  const [sdofE, setSdofE] = useState(null)
  const [sdofRun, setSdofRun] = useState(false)

  const run = useCallback(async () => {
    setSdofRun(true); setSdofE(null); setSdofR(null)
    try {
      // Build a quick ASCE 7-22 spectrum first, then query it
      const specRes = await callTool('seismic_build_asce7_spectrum', {
        SDS: +sdof.SDS, SD1: +sdof.SD1, TL: +sdof.TL,
      })
      if (!specRes.ok) throw new Error(specRes.reason || 'Spectrum build failed')

      const r = await callTool('seismic_rsa_sdof', {
        omega_n: +sdof.omega_n,
        zeta: +sdof.zeta,
        m: +sdof.m,
        spectrum_pts: specRes.spectrum,
      })
      setSdofR({ ...r, T0: specRes.T0, Ts: specRes.Ts })
    } catch (e) { setSdofE(e.message) } finally { setSdofRun(false) }
  }, [sdof])

  return (
    <div>
      <div style={{ ...s.section, borderLeft: '3px solid #22c55e' }}>
        <div style={s.sectionTitle}>
          <Activity size={12} style={{ color: '#22c55e' }} />
          SDOF Spectral Response (ASCE 7-22 §12.9.1 single mode)
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>STRUCTURE</div>
            <NumRow label="ωn (rad/s)" value={sdof.omega_n} onChange={v => setSdof(p => ({ ...p, omega_n: v }))} />
            <NumRow label="ζ damping ratio" value={sdof.zeta} onChange={v => setSdof(p => ({ ...p, zeta: v }))} step="0.01" />
            <NumRow label="Mass m" value={sdof.m} onChange={v => setSdof(p => ({ ...p, m: v }))} unit="kg" />
          </div>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>SPECTRUM (ASCE 7-22)</div>
            <NumRow label="SDS" value={sdof.SDS} onChange={v => setSdof(p => ({ ...p, SDS: v }))} unit="g" />
            <NumRow label="SD1" value={sdof.SD1} onChange={v => setSdof(p => ({ ...p, SD1: v }))} unit="g" />
            <NumRow label="TL" value={sdof.TL} onChange={v => setSdof(p => ({ ...p, TL: v }))} unit="s" />
          </div>
        </div>
        <RunBtn onClick={run} running={sdofRun} label="Run SDOF RSA" />
        {sdofE && <div style={s.errorBox}><AlertTriangle size={12} /><span>{sdofE}</span></div>}
        {sdofRun && <div style={s.infoBox}><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /><span>Computing SDOF response…</span></div>}
        {sdofR && !sdofRun && !sdofE && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 6 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>
                T = {fmt(sdofR.T_n, 3)} s &nbsp;|&nbsp; Sa = {fmt(sdofR.Sa_g, 4)} g &nbsp;|&nbsp; F = {fmt(sdofR.peak_force_N, 0)} N
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <table style={s.table}><tbody>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Natural period Tn</td>
                    <td style={{ ...s.td, ...s.mono, color: '#fbbf24', fontWeight: 700 }}>{fmt(sdofR.T_n, 4)} s</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>ωn</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(sdofR.omega_n, 4)} rad/s</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Spectral accel Sa</td>
                    <td style={{ ...s.td, ...s.mono, color: '#60a5fa', fontWeight: 700 }}>{fmt(sdofR.Sa_g, 5)} g</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Sa (m/s²)</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(sdofR.Sa_ms2, 4)} m/s²</td></tr>
              </tbody></table>
              <table style={s.table}><tbody>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Spectral disp Sd</td>
                    <td style={{ ...s.td, ...s.mono, color: '#34d399', fontWeight: 700 }}>{fmt(sdofR.Sd_m * 1000, 3)} mm</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Peak disp</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(sdofR.peak_disp_m * 1000, 3)} mm</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Peak force</td>
                    <td style={{ ...s.td, ...s.mono, color: '#f87171', fontWeight: 700 }}>{fmt(sdofR.peak_force_N, 0)} N</td></tr>
              </tbody></table>
            </div>
            <Warnings warnings={sdofR.warnings} />
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 4 }}>
              Sa = Sa_g×g; Sd = Sa/(ωn²); F = m×Sa. Ref: ASCE 7-22 §12.9.1, Chopra (2012) §12.8.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 3 — Multi-mode RSA (SRSS / CQC)
// ---------------------------------------------------------------------------

function TabMDOF() {
  // 2-DOF example defaults: 2-story shear frame
  const [mdof, setMdof] = useState({
    // omega_list as comma-separated
    omega_list: '6.28, 18.85',
    // phi_list: mode 1, mode 2 (comma-separated rows separated by |)
    phi_list: '0.707, 1.0 | -1.0, 0.707',
    // gamma_list
    gamma_list: '1.2, 0.3',
    // zeta_list
    zeta_list: '0.05, 0.05',
    // m_list (kg)
    m_list: '50000, 50000',
    // h_list for overturning moment (m)
    h_list: '3.0, 6.0',
    // Spectrum
    SDS: '1.0', SD1: '0.6', TL: '6',
    method: 'CQC',
  })
  const [mdofR, setMdofR] = useState(null)
  const [mdofE, setMdofE] = useState(null)
  const [mdofRun, setMdofRun] = useState(false)

  const parseFV = str => str.split(',').map(Number)

  const run = useCallback(async () => {
    setMdofRun(true); setMdofE(null); setMdofR(null)
    try {
      // Build spectrum
      const specRes = await callTool('seismic_build_asce7_spectrum', {
        SDS: +mdof.SDS, SD1: +mdof.SD1, TL: +mdof.TL,
      })
      if (!specRes.ok) throw new Error(specRes.reason || 'Spectrum build failed')

      const omega_list = parseFV(mdof.omega_list)
      const gamma_list = parseFV(mdof.gamma_list)
      const zeta_list = parseFV(mdof.zeta_list)
      const m_list = parseFV(mdof.m_list)
      const h_list = parseFV(mdof.h_list)

      // phi_list: rows separated by |, values within row by comma
      const phi_list = mdof.phi_list.split('|').map(row => parseFV(row.trim()))

      const r = await callTool('seismic_rsa_mdof', {
        omega_list, phi_list, gamma_list, zeta_list, m_list,
        spectrum_pts: specRes.spectrum,
        method: mdof.method,
        h_list,
      })
      setMdofR(r)
    } catch (e) { setMdofE(e.message) } finally { setMdofRun(false) }
  }, [mdof])

  return (
    <div>
      <div style={{ ...s.section, borderLeft: '3px solid #f59e0b' }}>
        <div style={s.sectionTitle}>
          <Zap size={12} style={{ color: '#f59e0b' }} />
          Multi-Mode RSA — ASCE 7-22 §12.9 (SRSS / CQC)
        </div>

        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 8 }}>
          Enter comma-separated values. Mode shapes (phi_list): rows per mode separated by |. Example 2-DOF, 2-mode: "0.707, 1.0 | -1.0, 0.707"
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>MODAL PROPERTIES</div>
            <div style={s.row}>
              <label style={s.label}>ω_n list (rad/s)</label>
              <input value={mdof.omega_list} onChange={e => setMdof(p => ({ ...p, omega_list: e.target.value }))} style={s.input} placeholder="6.28, 18.85" />
            </div>
            <div style={s.row}>
              <label style={s.label}>φ mode shapes (rows by |)</label>
              <input value={mdof.phi_list} onChange={e => setMdof(p => ({ ...p, phi_list: e.target.value }))} style={s.input} placeholder="0.707, 1.0 | -1.0, 0.707" />
            </div>
            <div style={s.row}>
              <label style={s.label}>Γ participation factors</label>
              <input value={mdof.gamma_list} onChange={e => setMdof(p => ({ ...p, gamma_list: e.target.value }))} style={s.input} />
            </div>
            <div style={s.row}>
              <label style={s.label}>ζ damping ratios</label>
              <input value={mdof.zeta_list} onChange={e => setMdof(p => ({ ...p, zeta_list: e.target.value }))} style={s.input} />
            </div>
            <div style={s.row}>
              <label style={s.label}>Masses m (kg)</label>
              <input value={mdof.m_list} onChange={e => setMdof(p => ({ ...p, m_list: e.target.value }))} style={s.input} />
            </div>
            <div style={s.row}>
              <label style={s.label}>Heights h (m, for OTM)</label>
              <input value={mdof.h_list} onChange={e => setMdof(p => ({ ...p, h_list: e.target.value }))} style={s.input} />
            </div>
          </div>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>SPECTRUM + METHOD</div>
            <NumRow label="SDS (g)" value={mdof.SDS} onChange={v => setMdof(p => ({ ...p, SDS: v }))} />
            <NumRow label="SD1 (g)" value={mdof.SD1} onChange={v => setMdof(p => ({ ...p, SD1: v }))} />
            <NumRow label="TL (s)" value={mdof.TL} onChange={v => setMdof(p => ({ ...p, TL: v }))} step="1" />
            <SelRow label="Combination method" value={mdof.method}
              onChange={v => setMdof(p => ({ ...p, method: v }))}
              options={[{ value: 'CQC', label: 'CQC (Wilson–Penzien)' }, { value: 'SRSS', label: 'SRSS' }]} />
          </div>
        </div>

        <RunBtn onClick={run} running={mdofRun} label="Run Multi-Mode RSA" />
        {mdofE && <div style={s.errorBox}><AlertTriangle size={12} /><span>{mdofE}</span></div>}
        {mdofRun && <div style={s.infoBox}><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /><span>Running RSA ({mdof.method})…</span></div>}

        {mdofR && !mdofRun && !mdofE && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>
                V_base = {fmt(mdofR.base_shear_N, 0)} N &nbsp;|&nbsp; {mdofR.method} &nbsp;|&nbsp; {mdofR.n_modes} modes / {mdofR.n_dofs} DOFs
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <div>
                <div style={s.subhead}>Per-Mode Sa (g)</div>
                <table style={s.table}><tbody>
                  {(mdofR.mode_Sa_g || []).map((sa, i) => (
                    <tr key={i}>
                      <td style={{ ...s.td, color: '#9ca3af' }}>Mode {i + 1}</td>
                      <td style={{ ...s.td, ...s.mono }}>{fmt(sa, 5)} g</td>
                    </tr>
                  ))}
                </tbody></table>

                <div style={{ ...s.subhead, marginTop: 8 }}>Per-Mode Shear (N)</div>
                <table style={s.table}><tbody>
                  {(mdofR.mode_shear_N || []).map((v, i) => (
                    <tr key={i}>
                      <td style={{ ...s.td, color: '#9ca3af' }}>Mode {i + 1}</td>
                      <td style={{ ...s.td, ...s.mono }}>{fmt(v, 0)} N</td>
                    </tr>
                  ))}
                </tbody></table>
              </div>

              <div>
                <div style={s.subhead}>Combined Displacements (mm)</div>
                <table style={s.table}><tbody>
                  {(mdofR.combined_disp_m || []).map((d, i) => (
                    <tr key={i}>
                      <td style={{ ...s.td, color: '#9ca3af' }}>DOF {i + 1}</td>
                      <td style={{ ...s.td, ...s.mono, color: '#60a5fa', fontWeight: 700 }}>{fmt(d * 1000, 3)} mm</td>
                    </tr>
                  ))}
                </tbody></table>

                <div style={{ ...s.subhead, marginTop: 8 }}>Summary</div>
                <table style={s.table}><tbody>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>Base shear</td>
                      <td style={{ ...s.td, ...s.mono, color: '#f87171', fontWeight: 700 }}>{fmt(mdofR.base_shear_N, 0)} N</td></tr>
                  {mdofR.base_moment_Nm != null && (
                    <tr><td style={{ ...s.td, color: '#9ca3af' }}>OTM</td>
                        <td style={{ ...s.td, ...s.mono }}>{fmt(mdofR.base_moment_Nm, 0)} N·m</td></tr>
                  )}
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>Method</td>
                      <td style={{ ...s.td, ...s.mono }}>{mdofR.method}</td></tr>
                </tbody></table>
              </div>
            </div>
            <Warnings warnings={mdofR.warnings} />
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 4 }}>
              Ref: ASCE 7-22 §12.9 RSA. CQC correlation ρ_ij per Wilson–Penzien (1972).
              Per-mode: u = φ·Γ·Sd; f = m·φ·Γ·Sa. Base shear = Σf_i per mode, combined via {mdofR.method}.
              Per ASCE 7-22 §12.9.1.3 verify ≥90% modal mass participation.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 4 — Newmark-β SDOF Time-History
// ---------------------------------------------------------------------------

function TabNewmark() {
  const [nm, setNm] = useState({
    m: '10000', k: '3948803', zeta: '0.05', dt: '0.01',
    cycles: '5', ag_amp: '0.3',
  })
  const [nmR, setNmR] = useState(null)
  const [nmE, setNmE] = useState(null)
  const [nmRun, setNmRun] = useState(false)

  const run = useCallback(async () => {
    setNmRun(true); setNmE(null); setNmR(null)
    try {
      // Build a simple harmonic ground motion: ag = A·sin(2π·t/T)
      // Use a representative period T ≈ 0.5 s, dt=0.01 s, duration = cycles × T
      const dt = +nm.dt
      const T_exc = 0.5  // excitation period in seconds
      const duration = +nm.cycles * T_exc + 2 * T_exc  // a bit extra
      const N = Math.ceil(duration / dt) + 1
      const ag_time = []
      const A = +nm.ag_amp * 9.80665  // convert g to m/s²
      for (let i = 0; i < N; i++) {
        const t = i * dt
        ag_time.push(A * Math.sin(2 * Math.PI * t / T_exc))
      }

      const r = await callTool('seismic_newmark_sdof', {
        m: +nm.m, k: +nm.k, zeta: +nm.zeta,
        ag_time, dt,
      })
      setNmR(r)
    } catch (e) { setNmE(e.message) } finally { setNmRun(false) }
  }, [nm])

  return (
    <div>
      <div style={{ ...s.section, borderLeft: '3px solid #ef4444' }}>
        <div style={s.sectionTitle}>
          <Activity size={12} style={{ color: '#ef4444' }} />
          Newmark-β SDOF Time-History (γ=½, β=¼ constant-average-acceleration)
        </div>
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 8 }}>
          Synthetic harmonic ground motion: ag(t) = A·sin(2π·t/0.5s). Amplitude in g.
          Integration: Chopra (2012) §5.2.3 predictor-corrector.
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>STRUCTURE</div>
            <NumRow label="Mass m" value={nm.m} onChange={v => setNm(p => ({ ...p, m: v }))} unit="kg" />
            <NumRow label="Stiffness k" value={nm.k} onChange={v => setNm(p => ({ ...p, k: v }))} unit="N/m" />
            <NumRow label="ζ damping ratio" value={nm.zeta} onChange={v => setNm(p => ({ ...p, zeta: v }))} step="0.01" />
          </div>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>GROUND MOTION</div>
            <NumRow label="ag amplitude" value={nm.ag_amp} onChange={v => setNm(p => ({ ...p, ag_amp: v }))} unit="g" />
            <NumRow label="Excitation cycles" value={nm.cycles} onChange={v => setNm(p => ({ ...p, cycles: v }))} step="1" />
            <NumRow label="Time step dt" value={nm.dt} onChange={v => setNm(p => ({ ...p, dt: v }))} unit="s" step="0.001" />
          </div>
        </div>
        <RunBtn onClick={run} running={nmRun} label="Run Newmark Integration" />
        {nmE && <div style={s.errorBox}><AlertTriangle size={12} /><span>{nmE}</span></div>}
        {nmRun && <div style={s.infoBox}><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /><span>Integrating Newmark-β…</span></div>}
        {nmR && !nmRun && !nmE && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 6 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>
                Tn = {fmt(nmR.T_n, 3)} s &nbsp;|&nbsp; Peak u = {fmt(nmR.peak_u_m * 1000, 2)} mm
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <table style={s.table}><tbody>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Natural period Tn</td>
                    <td style={{ ...s.td, ...s.mono, color: '#fbbf24', fontWeight: 700 }}>{fmt(nmR.T_n, 4)} s</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>ωn</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(nmR.omega_n, 3)} rad/s</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Peak displacement</td>
                    <td style={{ ...s.td, ...s.mono, color: '#60a5fa', fontWeight: 700 }}>{fmt(nmR.peak_u_m * 1000, 3)} mm</td></tr>
              </tbody></table>
              <table style={s.table}><tbody>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Peak velocity</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(nmR.peak_v_ms * 1000, 3)} mm/s</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Peak acceleration</td>
                    <td style={{ ...s.td, ...s.mono, color: '#f87171', fontWeight: 700 }}>{fmt(nmR.peak_a_ms2, 4)} m/s²</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Steps</td>
                    <td style={{ ...s.td, ...s.mono }}>{nmR.u?.length ?? '—'}</td></tr>
              </tbody></table>
            </div>
            <Warnings warnings={nmR.warnings} />
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 4 }}>
              Ref: Chopra (2012) §5.2.3, Newmark (1959). Constant average acceleration γ=½, β=¼ — unconditionally stable.
              EOM: m·ü + c·u̇ + k·u = −m·ag(t).
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root export
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'spectrum', label: 'ASCE 7-22 Spectrum', icon: BarChart2 },
  { id: 'sdof',     label: 'SDOF Response',       icon: Activity },
  { id: 'mdof',     label: 'Multi-Mode RSA',       icon: Zap },
  { id: 'newmark',  label: 'Newmark Time-History', icon: Activity },
]

export default function SeismicRSAPanel({ content } = {}) {
  // content prop: JSON string optionally carrying persisted tab selection.
  const _parsed = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()

  const [tab, setTab] = useState(_parsed.tab || 'spectrum')

  return (
    <div style={s.root}>
      <div style={s.header}>
        <Activity size={16} style={{ color: '#6366f1' }} />
        <span style={s.title}>Seismic RSA</span>
        <span style={s.subtitle}>ASCE 7-22 §11.4.5 + §12.9 · SRSS/CQC · Newmark-β</span>
      </div>

      <div style={s.tabs}>
        {TABS.map(t => (
          <button key={t.id} style={{ ...s.tab, ...(tab === t.id ? s.tabActive : {}) }} onClick={() => setTab(t.id)}>
            {t.icon && <t.icon size={10} style={{ marginRight: 3 }} />}
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'spectrum' && <TabSpectrum />}
      {tab === 'sdof'     && <TabSDOF />}
      {tab === 'mdof'     && <TabMDOF />}
      {tab === 'newmark'  && <TabNewmark />}
    </div>
  )
}
