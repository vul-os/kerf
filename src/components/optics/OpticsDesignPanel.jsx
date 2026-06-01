// OpticsDesignPanel.jsx — Geometric optics & lens design solver panel.
//
// Wires 42 optics LLM backend tools into a tabbed UI.
// Tabs: Lens Design | Aberrations | MTF / PSF | Pupils & Field | Utilities
//
// All tools dispatch POST /api/tools/call with { tool: "<name>", args: {...} }.
// Results are rendered inline (numbers, tables, or SVG previews).
//
// Props: none (standalone panel — operates without a project file)

import { useState, useCallback } from 'react'
import {
  Eye, Circle, Zap, Sun, Aperture, AlertTriangle, CheckCircle,
  Loader2, Play, ChevronDown, ChevronUp, RefreshCw
} from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Styles (inline, matching fea/BucklingPanel.jsx pattern)
// ---------------------------------------------------------------------------

const s = {
  root:         { background: '#111827', padding: '12px', fontSize: 12, color: '#e5e7eb', minHeight: 200 },
  header:       { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 },
  title:        { fontWeight: 600, fontSize: 13, color: '#f9fafb' },
  tabs:         { display: 'flex', gap: 2, marginBottom: 10, flexWrap: 'wrap' },
  tab:          { padding: '4px 10px', borderRadius: 4, border: '1px solid #374151', background: '#1f2937', color: '#9ca3af', cursor: 'pointer', fontSize: 11 },
  tabActive:    { background: '#1d4ed8', borderColor: '#3b82f6', color: '#fff' },
  section:      { background: '#1f2937', borderRadius: 6, padding: '10px', marginBottom: 8 },
  sectionTitle: { display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600, marginBottom: 8, color: '#d1d5db', fontSize: 11 },
  row:          { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 },
  label:        { color: '#9ca3af', width: 140, flexShrink: 0, fontSize: 11 },
  input:        { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12, minWidth: 0 },
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
  badge:        { padding: '2px 6px', borderRadius: 3, fontSize: 10, fontWeight: 600 },
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

function fmt(v, decimals = 4) {
  if (v == null) return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v)
    return v.toExponential(2).replace(/e\+?0$/, '') === v.toFixed(decimals)
      ? v.toFixed(decimals)
      : Math.abs(v) > 1e4 || (Math.abs(v) < 1e-3 && v !== 0)
        ? v.toExponential(3)
        : v.toFixed(decimals)
  }
  return String(v)
}

function ResultTable({ data, skip = [] }) {
  if (!data || typeof data !== 'object') return null
  const entries = Object.entries(data).filter(([k]) => !skip.includes(k) && !Array.isArray(data[k]) && typeof data[k] !== 'object')
  if (!entries.length) return null
  return (
    <table style={s.table}>
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <td style={{ ...s.td, color: '#9ca3af', width: '50%' }}>{k}</td>
            <td style={{ ...s.td, ...s.mono }}>{fmt(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ToolWidget({ title, icon: Icon, color = '#2563eb', children, result, error, running }) {
  const [open, setOpen] = useState(true)
  return (
    <div style={{ ...s.section, borderLeft: `3px solid ${color}` }}>
      <div style={{ ...s.sectionTitle, justifyContent: 'space-between', cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {Icon && <Icon size={12} style={{ color }} />}
          {title}
        </span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </div>
      {open && (
        <>
          {children}
          {error && (
            <div style={s.errorBox}>
              <AlertTriangle size={12} />
              <span>{error}</span>
            </div>
          )}
          {running && (
            <div style={s.infoBox}>
              <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
              <span>Computing…</span>
            </div>
          )}
          {result && !running && !error && (
            <div style={s.resultBox}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
                <CheckCircle size={11} style={{ color: '#34d399' }} />
                <span style={{ color: '#34d399', fontWeight: 600 }}>Result</span>
              </div>
              <ResultTable data={result} />
            </div>
          )}
        </>
      )}
    </div>
  )
}

function RunBtn({ onClick, running, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={running || disabled}
      style={{ ...s.button, background: '#1e40af', marginTop: 6, ...(running || disabled ? s.buttonDisabled : {}) }}
    >
      {running
        ? <><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> Computing…</>
        : <><Play size={12} /> Run</>}
    </button>
  )
}

function NumRow({ label, value, onChange, step = 'any', disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <input
        type="number"
        value={value}
        onChange={e => onChange(e.target.value)}
        step={step}
        disabled={disabled}
        style={s.input}
      />
    </div>
  )
}

// Default BK7 biconvex singlet surfaces (used as a reference in multiple tools)
const BK7_SURFACES_DEFAULT = JSON.stringify([
  { c: 0.02, t: 5, n: 1.5168, k: 0 },
  { c: -0.02, t: 0, n: 1.0, k: 0 },
])

// ---------------------------------------------------------------------------
// TAB 1: Lens Design
// ---------------------------------------------------------------------------

function TabLensDesign() {
  // ── optics_lensmaker ──
  const [lm, setLm] = useState({ R1: '0.05', R2: '-0.05', n: '1.5168', d: '0.005' })
  const [lmR, setLmR] = useState(null); const [lmE, setLmE] = useState(null); const [lmRun, setLmRun] = useState(false)
  const runLensmaker = useCallback(async () => {
    setLmRun(true); setLmE(null); setLmR(null)
    try {
      const r = await callTool('optics_lensmaker', { R1: +lm.R1, R2: +lm.R2, n: +lm.n, d: +lm.d })
      setLmR(r)
    } catch (e) { setLmE(e.message) } finally { setLmRun(false) }
  }, [lm])

  // ── optics_thin_lens_imaging ──
  const [tli, setTli] = useState({ f: '0.05', s_o: '0.3' })
  const [tliR, setTliR] = useState(null); const [tliE, setTliE] = useState(null); const [tliRun, setTliRun] = useState(false)
  const runThinLens = useCallback(async () => {
    setTliRun(true); setTliE(null); setTliR(null)
    try { const r = await callTool('optics_thin_lens_imaging', { f: +tli.f, s_o: +tli.s_o }); setTliR(r) }
    catch (e) { setTliE(e.message) } finally { setTliRun(false) }
  }, [tli])

  // ── optics_two_lens_system ──
  const [tls, setTls] = useState({ f1: '0.05', f2: '0.08', d: '0.03' })
  const [tlsR, setTlsR] = useState(null); const [tlsE, setTlsE] = useState(null); const [tlsRun, setTlsRun] = useState(false)
  const runTwoLens = useCallback(async () => {
    setTlsRun(true); setTlsE(null); setTlsR(null)
    try { const r = await callTool('optics_two_lens_system', { f1: +tls.f1, f2: +tls.f2, d: +tls.d }); setTlsR(r) }
    catch (e) { setTlsE(e.message) } finally { setTlsRun(false) }
  }, [tls])

  // ── optics_achromat_powers ──
  const [ach, setAch] = useState({ f_total: '0.1', V1: '64.2', V2: '36.4' })
  const [achR, setAchR] = useState(null); const [achE, setAchE] = useState(null); const [achRun, setAchRun] = useState(false)
  const runAchromat = useCallback(async () => {
    setAchRun(true); setAchE(null); setAchR(null)
    try { const r = await callTool('optics_achromat_powers', { f_total: +ach.f_total, V1: +ach.V1, V2: +ach.V2 }); setAchR(r) }
    catch (e) { setAchE(e.message) } finally { setAchRun(false) }
  }, [ach])

  // ── optics_fnumber ──
  const [fn, setFn] = useState({ f: '0.1', D: '0.025' })
  const [fnR, setFnR] = useState(null); const [fnE, setFnE] = useState(null); const [fnRun, setFnRun] = useState(false)
  const runFnumber = useCallback(async () => {
    setFnRun(true); setFnE(null); setFnR(null)
    try { const r = await callTool('optics_fnumber', { f: +fn.f, D: +fn.D }); setFnR(r) }
    catch (e) { setFnE(e.message) } finally { setFnRun(false) }
  }, [fn])

  // ── optics_numerical_aperture ──
  const [na, setNa] = useState({ n: '1.0', half_angle_rad: '0.25' })
  const [naR, setNaR] = useState(null); const [naE, setNaE] = useState(null); const [naRun, setNaRun] = useState(false)
  const runNA = useCallback(async () => {
    setNaRun(true); setNaE(null); setNaR(null)
    try { const r = await callTool('optics_numerical_aperture', { n: +na.n, half_angle_rad: +na.half_angle_rad }); setNaR(r) }
    catch (e) { setNaE(e.message) } finally { setNaRun(false) }
  }, [na])

  // ── optics_depth_of_field ──
  const [dof, setDof] = useState({ f: '0.05', N: '5.6', c: '0.000025', s_o: '3.0' })
  const [dofR, setDofR] = useState(null); const [dofE, setDofE] = useState(null); const [dofRun, setDofRun] = useState(false)
  const runDof = useCallback(async () => {
    setDofRun(true); setDofE(null); setDofR(null)
    try { const r = await callTool('optics_depth_of_field', { f: +dof.f, N: +dof.N, c: +dof.c, s_o: +dof.s_o }); setDofR(r) }
    catch (e) { setDofE(e.message) } finally { setDofRun(false) }
  }, [dof])

  // ── optics_ray_trace_lens_stack ──
  const [rts, setRts] = useState({ surfaces: BK7_SURFACES_DEFAULT, ray_h: '1.0', ray_u: '0.0' })
  const [rtsR, setRtsR] = useState(null); const [rtsE, setRtsE] = useState(null); const [rtsRun, setRtsRun] = useState(false)
  const runRayTrace = useCallback(async () => {
    setRtsRun(true); setRtsE(null); setRtsR(null)
    try {
      const surfaces = JSON.parse(rts.surfaces)
      const r = await callTool('optics_ray_trace_lens_stack', { surfaces, ray_h: +rts.ray_h, ray_u: +rts.ray_u })
      setRtsR(r)
    } catch (e) { setRtsE(e.message) } finally { setRtsRun(false) }
  }, [rts])

  return (
    <div>
      <ToolWidget title="Lensmaker's Equation" icon={Circle} color="#3b82f6" result={lmR} error={lmE} running={lmRun}>
        <NumRow label="R1 (m)" value={lm.R1} onChange={v => setLm(p => ({ ...p, R1: v }))} disabled={lmRun} />
        <NumRow label="R2 (m)" value={lm.R2} onChange={v => setLm(p => ({ ...p, R2: v }))} disabled={lmRun} />
        <NumRow label="n (refractive index)" value={lm.n} onChange={v => setLm(p => ({ ...p, n: v }))} disabled={lmRun} />
        <NumRow label="d thickness (m)" value={lm.d} onChange={v => setLm(p => ({ ...p, d: v }))} disabled={lmRun} />
        <RunBtn onClick={runLensmaker} running={lmRun} />
      </ToolWidget>

      <ToolWidget title="Thin-Lens Imaging" icon={Eye} color="#8b5cf6" result={tliR} error={tliE} running={tliRun}>
        <NumRow label="f focal length (m)" value={tli.f} onChange={v => setTli(p => ({ ...p, f: v }))} disabled={tliRun} />
        <NumRow label="s_o object dist (m)" value={tli.s_o} onChange={v => setTli(p => ({ ...p, s_o: v }))} disabled={tliRun} />
        <RunBtn onClick={runThinLens} running={tliRun} />
      </ToolWidget>

      <ToolWidget title="Two-Lens System" icon={Circle} color="#10b981" result={tlsR} error={tlsE} running={tlsRun}>
        <NumRow label="f1 (m)" value={tls.f1} onChange={v => setTls(p => ({ ...p, f1: v }))} disabled={tlsRun} />
        <NumRow label="f2 (m)" value={tls.f2} onChange={v => setTls(p => ({ ...p, f2: v }))} disabled={tlsRun} />
        <NumRow label="d separation (m)" value={tls.d} onChange={v => setTls(p => ({ ...p, d: v }))} disabled={tlsRun} />
        <RunBtn onClick={runTwoLens} running={tlsRun} />
      </ToolWidget>

      <ToolWidget title="Achromatic Doublet Powers (Smith MOE §6.4)" icon={Sun} color="#f59e0b" result={achR} error={achE} running={achRun}>
        <NumRow label="f_total (m)" value={ach.f_total} onChange={v => setAch(p => ({ ...p, f_total: v }))} disabled={achRun} />
        <NumRow label="V1 crown Abbe#" value={ach.V1} onChange={v => setAch(p => ({ ...p, V1: v }))} disabled={achRun} />
        <NumRow label="V2 flint Abbe#" value={ach.V2} onChange={v => setAch(p => ({ ...p, V2: v }))} disabled={achRun} />
        <RunBtn onClick={runAchromat} running={achRun} />
      </ToolWidget>

      <ToolWidget title="F-number" icon={Aperture} color="#6366f1" result={fnR} error={fnE} running={fnRun}>
        <NumRow label="f focal length (m)" value={fn.f} onChange={v => setFn(p => ({ ...p, f: v }))} disabled={fnRun} />
        <NumRow label="D aperture diam (m)" value={fn.D} onChange={v => setFn(p => ({ ...p, D: v }))} disabled={fnRun} />
        <RunBtn onClick={runFnumber} running={fnRun} />
      </ToolWidget>

      <ToolWidget title="Numerical Aperture" icon={Aperture} color="#ec4899" result={naR} error={naE} running={naRun}>
        <NumRow label="n refractive index" value={na.n} onChange={v => setNa(p => ({ ...p, n: v }))} disabled={naRun} />
        <NumRow label="half-angle (rad)" value={na.half_angle_rad} onChange={v => setNa(p => ({ ...p, half_angle_rad: v }))} disabled={naRun} />
        <RunBtn onClick={runNA} running={naRun} />
      </ToolWidget>

      <ToolWidget title="Depth of Field" icon={Eye} color="#0ea5e9" result={dofR} error={dofE} running={dofRun}>
        <NumRow label="f focal length (m)" value={dof.f} onChange={v => setDof(p => ({ ...p, f: v }))} disabled={dofRun} />
        <NumRow label="N F-number" value={dof.N} onChange={v => setDof(p => ({ ...p, N: v }))} disabled={dofRun} />
        <NumRow label="c CoC diam (m)" value={dof.c} onChange={v => setDof(p => ({ ...p, c: v }))} disabled={dofRun} />
        <NumRow label="s_o subject dist (m)" value={dof.s_o} onChange={v => setDof(p => ({ ...p, s_o: v }))} disabled={dofRun} />
        <RunBtn onClick={runDof} running={dofRun} />
      </ToolWidget>

      <ToolWidget title="Ray Trace Lens Stack (paraxial + meridional)" icon={Sun} color="#f97316" result={rtsR} error={rtsE} running={rtsRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
          <textarea
            value={rts.surfaces}
            onChange={e => setRts(p => ({ ...p, surfaces: e.target.value }))}
            disabled={rtsRun}
            rows={4}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <NumRow label="ray_h at first surf (mm)" value={rts.ray_h} onChange={v => setRts(p => ({ ...p, ray_h: v }))} disabled={rtsRun} />
        <NumRow label="ray_u angle (rad)" value={rts.ray_u} onChange={v => setRts(p => ({ ...p, ray_u: v }))} disabled={rtsRun} />
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>
          Each surface: {'{'}c (mm⁻¹), t (mm), n, k{'}'} — e.g. BK7 biconvex R=50mm: c=0.02
        </div>
        <RunBtn onClick={runRayTrace} running={rtsRun} />
        {rtsR && !rtsRun && (
          <div style={s.resultBox}>
            <div style={s.subhead}>System properties</div>
            <div style={{ ...s.mono, fontSize: 11 }}>
              EFL: {fmt(rtsR.EFL_mm)} mm &nbsp;|&nbsp; BFL: {fmt(rtsR.BFL_mm)} mm &nbsp;|&nbsp; FFL: {fmt(rtsR.FFL_mm)} mm
            </div>
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 2: Aberrations
// ---------------------------------------------------------------------------

function TabAberrations() {
  // ── optics_seidel_aberrations ──
  const [sa, setSa] = useState({ surfaces: BK7_SURFACES_DEFAULT, aperture: '1.0', field_angle_deg: '5.0' })
  const [saR, setSaR] = useState(null); const [saE, setSaE] = useState(null); const [saRun, setSaRun] = useState(false)
  const runSeidel = useCallback(async () => {
    setSaRun(true); setSaE(null); setSaR(null)
    try {
      const surfaces = JSON.parse(sa.surfaces)
      const r = await callTool('optics_seidel_aberrations', { surfaces, aperture: +sa.aperture, field_angle_deg: +sa.field_angle_deg })
      setSaR(r)
    } catch (e) { setSaE(e.message) } finally { setSaRun(false) }
  }, [sa])

  // ── optics_compute_coma ──
  const [coma, setComa] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angles: '0,5,10,14', aperture_radius_mm: '5.0' })
  const [comaR, setComaR] = useState(null); const [comaE, setComaE] = useState(null); const [comaRun, setComaRun] = useState(false)
  const runComa = useCallback(async () => {
    setComaRun(true); setComaE(null); setComaR(null)
    try {
      const surfaces = JSON.parse(coma.surfaces)
      const field_angles_deg = coma.field_angles.split(',').map(Number)
      const r = await callTool('optics_compute_coma', { surfaces, field_angles_deg, aperture_radius_mm: +coma.aperture_radius_mm })
      setComaR(r)
    } catch (e) { setComaE(e.message) } finally { setComaRun(false) }
  }, [coma])

  // ── optics_compute_seidel_coma ──
  const [sc, setSc] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_height_mm: '5.0', aperture_radius_mm: '1.0' })
  const [scR, setScR] = useState(null); const [scE, setScE] = useState(null); const [scRun, setScRun] = useState(false)
  const runSeidelComa = useCallback(async () => {
    setScRun(true); setScE(null); setScR(null)
    try {
      const surfaces = JSON.parse(sc.surfaces)
      const r = await callTool('optics_compute_seidel_coma', { surfaces, field_height_mm: +sc.field_height_mm, aperture_radius_mm: +sc.aperture_radius_mm })
      setScR(r)
    } catch (e) { setScE(e.message) } finally { setScRun(false) }
  }, [sc])

  // ── optics_chromatic_aberration ──
  const [ca, setCa] = useState({ f: '0.1', V: '64.2' })
  const [caR, setCaR] = useState(null); const [caE, setCaE] = useState(null); const [caRun, setCaRun] = useState(false)
  const runChromatic = useCallback(async () => {
    setCaRun(true); setCaE(null); setCaR(null)
    try { const r = await callTool('optics_chromatic_aberration', { f: +ca.f, V: +ca.V }); setCaR(r) }
    catch (e) { setCaE(e.message) } finally { setCaRun(false) }
  }, [ca])

  // ── optics_compute_chromatic_focus ──
  const [cf, setCf] = useState({
    stack: JSON.stringify([{ glass: 'BK7', R1: 50, R2: -50, separation_mm: 0 }]),
    wavelengths_nm: '486,587,656'
  })
  const [cfR, setCfR] = useState(null); const [cfE, setCfE] = useState(null); const [cfRun, setCfRun] = useState(false)
  const runChromaticFocus = useCallback(async () => {
    setCfRun(true); setCfE(null); setCfR(null)
    try {
      const stack = JSON.parse(cf.stack)
      const wavelengths_nm = cf.wavelengths_nm.split(',').map(Number)
      const r = await callTool('optics_compute_chromatic_focus', { stack, wavelengths_nm })
      setCfR(r)
    } catch (e) { setCfE(e.message) } finally { setCfRun(false) }
  }, [cf])

  // ── optics_compute_petzval_curvature ──
  const [petz, setPetz] = useState({
    surfaces: JSON.stringify([
      { radius_mm: 50, n_index_before: 1.0, n_index_after: 1.5168 },
      { radius_mm: -50, n_index_before: 1.5168, n_index_after: 1.0 },
    ])
  })
  const [petzR, setPetzR] = useState(null); const [petzE, setPetzE] = useState(null); const [petzRun, setPetzRun] = useState(false)
  const runPetzval = useCallback(async () => {
    setPetzRun(true); setPetzE(null); setPetzR(null)
    try {
      const surfaces = JSON.parse(petz.surfaces)
      const r = await callTool('optics_compute_petzval_curvature', { surfaces })
      setPetzR(r)
    } catch (e) { setPetzE(e.message) } finally { setPetzRun(false) }
  }, [petz])

  // ── optics_distortion_map ──
  const [dm, setDm] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angles: '0,5,10,15,20' })
  const [dmR, setDmR] = useState(null); const [dmE, setDmE] = useState(null); const [dmRun, setDmRun] = useState(false)
  const runDistortion = useCallback(async () => {
    setDmRun(true); setDmE(null); setDmR(null)
    try {
      const surfaces = JSON.parse(dm.surfaces)
      const field_angles_deg = dm.field_angles.split(',').map(Number)
      const r = await callTool('optics_distortion_map', { surfaces, field_angles_deg })
      setDmR(r)
    } catch (e) { setDmE(e.message) } finally { setDmRun(false) }
  }, [dm])

  // ── optics_compute_abbe_number ──
  const [abbe, setAbbe] = useState({ glass_name: 'BK7' })
  const [abbeR, setAbbeR] = useState(null); const [abbeE, setAbbeE] = useState(null); const [abbeRun, setAbbeRun] = useState(false)
  const runAbbe = useCallback(async () => {
    setAbbeRun(true); setAbbeE(null); setAbbeR(null)
    try { const r = await callTool('optics_compute_abbe_number', { glass_name: abbe.glass_name }); setAbbeR(r) }
    catch (e) { setAbbeE(e.message) } finally { setAbbeRun(false) }
  }, [abbe])

  return (
    <div>
      <ToolWidget title="Seidel Aberrations S_I–S_V" icon={RefreshCw} color="#dc2626" result={saR} error={saE} running={saRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
          <textarea value={sa.surfaces} onChange={e => setSa(p => ({ ...p, surfaces: e.target.value }))} disabled={saRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <NumRow label="aperture (mm)" value={sa.aperture} onChange={v => setSa(p => ({ ...p, aperture: v }))} disabled={saRun} />
        <NumRow label="field_angle (deg)" value={sa.field_angle_deg} onChange={v => setSa(p => ({ ...p, field_angle_deg: v }))} disabled={saRun} />
        <RunBtn onClick={runSeidel} running={saRun} />
        {saR && !saRun && (
          <div style={s.resultBox}>
            <table style={s.table}>
              <tbody>
                {['S_I','S_II','S_III','S_IV','S_V'].map(k => (
                  <tr key={k}><td style={{ ...s.td, color: '#9ca3af', width: '40%' }}>{k}</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(saR[k])}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Coma (finite ray, per field angle)" icon={Eye} color="#f59e0b" result={comaR} error={comaE} running={comaRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
          <textarea value={coma.surfaces} onChange={e => setComa(p => ({ ...p, surfaces: e.target.value }))} disabled={comaRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Field angles (deg, CSV)</label>
          <input value={coma.field_angles} onChange={e => setComa(p => ({ ...p, field_angles: e.target.value }))}
            disabled={comaRun} style={s.input} />
        </div>
        <NumRow label="aperture radius (mm)" value={coma.aperture_radius_mm} onChange={v => setComa(p => ({ ...p, aperture_radius_mm: v }))} disabled={comaRun} />
        <RunBtn onClick={runComa} running={comaRun} />
        {comaR?.per_field && !comaRun && (
          <div style={s.resultBox}>
            <table style={s.table}>
              <thead><tr>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>Field°</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>Total coma (mm)</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>Seidel pred (mm)</td>
              </tr></thead>
              <tbody>
                {comaR.per_field.map((f, i) => (
                  <tr key={i}>
                    <td style={s.td}>{fmt(f.field_angle_deg, 1)}</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(f.total_coma_mm)}</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(f.seidel_prediction_mm)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Seidel Coma S_II (closed-form)" icon={Eye} color="#9333ea" result={scR} error={scE} running={scRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
          <textarea value={sc.surfaces} onChange={e => setSc(p => ({ ...p, surfaces: e.target.value }))} disabled={scRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <NumRow label="field_height (mm)" value={sc.field_height_mm} onChange={v => setSc(p => ({ ...p, field_height_mm: v }))} disabled={scRun} />
        <NumRow label="aperture radius (mm)" value={sc.aperture_radius_mm} onChange={v => setSc(p => ({ ...p, aperture_radius_mm: v }))} disabled={scRun} />
        <RunBtn onClick={runSeidelComa} running={scRun} />
      </ToolWidget>

      <ToolWidget title="Longitudinal Chromatic Aberration (Abbe)" icon={Sun} color="#ef4444" result={caR} error={caE} running={caRun}>
        <NumRow label="f focal length (m)" value={ca.f} onChange={v => setCa(p => ({ ...p, f: v }))} disabled={caRun} />
        <NumRow label="V Abbe number" value={ca.V} onChange={v => setCa(p => ({ ...p, V: v }))} disabled={caRun} />
        <RunBtn onClick={runChromatic} running={caRun} />
      </ToolWidget>

      <ToolWidget title="Chromatic Focus (Sellmeier dispersion)" icon={Sun} color="#f97316" result={cfR} error={cfE} running={cfRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Stack (JSON)</label>
          <textarea value={cf.stack} onChange={e => setCf(p => ({ ...p, stack: e.target.value }))} disabled={cfRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Wavelengths (nm CSV)</label>
          <input value={cf.wavelengths_nm} onChange={e => setCf(p => ({ ...p, wavelengths_nm: e.target.value }))}
            disabled={cfRun} style={s.input} />
        </div>
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>Glasses: BK7, F2, SF6, K5, SF11, BK10</div>
        <RunBtn onClick={runChromaticFocus} running={cfRun} />
      </ToolWidget>

      <ToolWidget title="Petzval Field Curvature" icon={RefreshCw} color="#22d3ee" result={petzR} error={petzE} running={petzRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
          <textarea value={petz.surfaces} onChange={e => setPetz(p => ({ ...p, surfaces: e.target.value }))} disabled={petzRun}
            rows={4} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>Each: {'{'} radius_mm, n_index_before, n_index_after {'}'}</div>
        <RunBtn onClick={runPetzval} running={petzRun} />
      </ToolWidget>

      <ToolWidget title="Distortion Map (barrel/pincushion)" icon={RefreshCw} color="#16a34a" result={dmR} error={dmE} running={dmRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
          <textarea value={dm.surfaces} onChange={e => setDm(p => ({ ...p, surfaces: e.target.value }))} disabled={dmRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Field angles (deg, CSV)</label>
          <input value={dm.field_angles} onChange={e => setDm(p => ({ ...p, field_angles: e.target.value }))}
            disabled={dmRun} style={s.input} />
        </div>
        <RunBtn onClick={runDistortion} running={dmRun} />
        {dmR?.distortion_percent && !dmRun && (
          <div style={s.resultBox}>
            <div style={{ ...s.mono, fontSize: 11 }}>Max: {fmt(dmR.max_distortion_pct, 2)}% — {dmR.kind}</div>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Abbe Number (glass properties)" icon={Zap} color="#a78bfa" result={abbeR} error={abbeE} running={abbeRun}>
        <div style={s.row}>
          <label style={s.label}>Glass name</label>
          <select value={abbe.glass_name} onChange={e => setAbbe({ glass_name: e.target.value })} style={s.select} disabled={abbeRun}>
            {['BK7','F2','SF6','K5','SF11','BK10'].map(g => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>
        <RunBtn onClick={runAbbe} running={abbeRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 3: MTF / PSF
// ---------------------------------------------------------------------------

function TabMtfPsf() {
  // ── optics_compute_diffraction_mtf ──
  const [dm, setDm] = useState({ wavelength_nm: '550', f_number: '4' })
  const [dmR, setDmR] = useState(null); const [dmE, setDmE] = useState(null); const [dmRun, setDmRun] = useState(false)
  const runDiffrMtf = useCallback(async () => {
    setDmRun(true); setDmE(null); setDmR(null)
    try { const r = await callTool('optics_compute_diffraction_mtf', { wavelength_nm: +dm.wavelength_nm, f_number: +dm.f_number }); setDmR(r) }
    catch (e) { setDmE(e.message) } finally { setDmRun(false) }
  }, [dm])

  // ── optics_mtf_across_field ──
  const [maf, setMaf] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angles: '0,5,10,14', aperture_radius_mm: '10' })
  const [mafR, setMafR] = useState(null); const [mafE, setMafE] = useState(null); const [mafRun, setMafRun] = useState(false)
  const runMtfField = useCallback(async () => {
    setMafRun(true); setMafE(null); setMafR(null)
    try {
      const surfaces = JSON.parse(maf.surfaces)
      const field_angles_deg = maf.field_angles.split(',').map(Number)
      const r = await callTool('optics_mtf_across_field', { surfaces, field_angles_deg, aperture_radius_mm: +maf.aperture_radius_mm })
      setMafR(r)
    } catch (e) { setMafE(e.message) } finally { setMafRun(false) }
  }, [maf])

  // ── optics_compute_spot_diagram ──
  const [spd, setSpd] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angles: '0,5,10', aperture_radius_mm: '5' })
  const [spdR, setSpdR] = useState(null); const [spdE, setSpdE] = useState(null); const [spdRun, setSpdRun] = useState(false)
  const runSpotDiagram = useCallback(async () => {
    setSpdRun(true); setSpdE(null); setSpdR(null)
    try {
      const surfaces = JSON.parse(spd.surfaces)
      const field_angles_deg = spd.field_angles.split(',').map(Number)
      const r = await callTool('optics_compute_spot_diagram', { surfaces, field_angles_deg, aperture_radius_mm: +spd.aperture_radius_mm })
      setSpdR(r)
    } catch (e) { setSpdE(e.message) } finally { setSpdRun(false) }
  }, [spd])

  // ── optics_compute_diffraction_psf ──
  const [psf, setPsf] = useState({ wavelength_nm: '550', f_number: '4', grid_size: '64', defocus_waves: '0' })
  const [psfR, setPsfR] = useState(null); const [psfE, setPsfE] = useState(null); const [psfRun, setPsfRun] = useState(false)
  const runDiffrPsf = useCallback(async () => {
    setPsfRun(true); setPsfE(null); setPsfR(null)
    try {
      const r = await callTool('optics_compute_diffraction_psf', {
        wavelength_nm: +psf.wavelength_nm, f_number: +psf.f_number,
        grid_size: +psf.grid_size, defocus_waves: +psf.defocus_waves
      })
      setPsfR(r)
    } catch (e) { setPsfE(e.message) } finally { setPsfRun(false) }
  }, [psf])

  // ── optics_compute_pixel_mtf ──
  const [pmtf, setPmtf] = useState({ pixel_pitch_um: '4.64', fill_factor: '1.0', wavelength_nm: '550', f_number: '2.8' })
  const [pmtfR, setPmtfR] = useState(null); const [pmtfE, setPmtfE] = useState(null); const [pmtfRun, setPmtfRun] = useState(false)
  const runPixelMtf = useCallback(async () => {
    setPmtfRun(true); setPmtfE(null); setPmtfR(null)
    try {
      const r = await callTool('optics_compute_pixel_mtf', {
        pixel_pitch_um: +pmtf.pixel_pitch_um, fill_factor: +pmtf.fill_factor,
        wavelength_nm: +pmtf.wavelength_nm, f_number: +pmtf.f_number
      })
      setPmtfR(r)
    } catch (e) { setPmtfE(e.message) } finally { setPmtfRun(false) }
  }, [pmtf])

  // ── optics_airy_spot ──
  const [airy, setAiry] = useState({ wavelength: '550e-9', N: '4' })
  const [airyR, setAiryR] = useState(null); const [airyE, setAiryE] = useState(null); const [airyRun, setAiryRun] = useState(false)
  const runAiry = useCallback(async () => {
    setAiryRun(true); setAiryE(null); setAiryR(null)
    try { const r = await callTool('optics_airy_spot', { wavelength: +airy.wavelength, N: +airy.N }); setAiryR(r) }
    catch (e) { setAiryE(e.message) } finally { setAiryRun(false) }
  }, [airy])

  // ── optics_defocus_curve ──
  const [dc, setDc] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angle_deg: '0', defocus_range_mm: '0.5' })
  const [dcR, setDcR] = useState(null); const [dcE, setDcE] = useState(null); const [dcRun, setDcRun] = useState(false)
  const runDefocus = useCallback(async () => {
    setDcRun(true); setDcE(null); setDcR(null)
    try {
      const surfaces = JSON.parse(dc.surfaces)
      const r = await callTool('optics_defocus_curve', { surfaces, field_angle_deg: +dc.field_angle_deg, defocus_range_mm: +dc.defocus_range_mm })
      setDcR(r)
    } catch (e) { setDcE(e.message) } finally { setDcRun(false) }
  }, [dc])

  return (
    <div>
      <ToolWidget title="Diffraction MTF (analytic, aberration-free)" icon={Zap} color="#3b82f6" result={dmR} error={dmE} running={dmRun}>
        <NumRow label="wavelength (nm)" value={dm.wavelength_nm} onChange={v => setDm(p => ({ ...p, wavelength_nm: v }))} disabled={dmRun} />
        <NumRow label="F-number" value={dm.f_number} onChange={v => setDm(p => ({ ...p, f_number: v }))} disabled={dmRun} />
        <RunBtn onClick={runDiffrMtf} running={dmRun} />
        {dmR && !dmRun && (
          <div style={s.resultBox}>
            <div style={{ ...s.mono, fontSize: 11 }}>
              Cutoff: {fmt(dmR.cutoff_freq_cyc_per_mm, 1)} lp/mm &nbsp;|&nbsp;
              50% MTF @ {fmt(dmR.mtf_at_50_percent, 1)} lp/mm
            </div>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="MTF Across Field Angles (ray trace)" icon={Eye} color="#8b5cf6" result={null} error={mafE} running={mafRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
          <textarea value={maf.surfaces} onChange={e => setMaf(p => ({ ...p, surfaces: e.target.value }))} disabled={mafRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Field angles (deg, CSV)</label>
          <input value={maf.field_angles} onChange={e => setMaf(p => ({ ...p, field_angles: e.target.value }))} disabled={mafRun} style={s.input} />
        </div>
        <NumRow label="aperture radius (mm)" value={maf.aperture_radius_mm} onChange={v => setMaf(p => ({ ...p, aperture_radius_mm: v }))} disabled={mafRun} />
        <RunBtn onClick={runMtfField} running={mafRun} />
        {mafR && !mafRun && (
          <div style={s.resultBox}>
            {mafE && <div style={{ color: '#fca5a5' }}>{mafE}</div>}
            <div style={{ ...s.mono, fontSize: 11, color: '#34d399' }}>MTF results received ({Array.isArray(mafR) ? mafR.length : 'n/a'} field angles)</div>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Spot Diagram (fan-of-rays, RMS + EE80)" icon={Aperture} color="#10b981" result={null} error={spdE} running={spdRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
          <textarea value={spd.surfaces} onChange={e => setSpd(p => ({ ...p, surfaces: e.target.value }))} disabled={spdRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Field angles (deg, CSV)</label>
          <input value={spd.field_angles} onChange={e => setSpd(p => ({ ...p, field_angles: e.target.value }))} disabled={spdRun} style={s.input} />
        </div>
        <NumRow label="aperture radius (mm)" value={spd.aperture_radius_mm} onChange={v => setSpd(p => ({ ...p, aperture_radius_mm: v }))} disabled={spdRun} />
        <RunBtn onClick={runSpotDiagram} running={spdRun} />
        {spdR && !spdRun && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Spot sizes (RMS, mm)</div>
            {Array.isArray(spdR.rms_spot_size_per_field) && spdR.rms_spot_size_per_field.map((v, i) => (
              <div key={i} style={{ ...s.mono, fontSize: 11 }}>Field {i}: {fmt(v)} mm</div>
            ))}
            {spdR.svg && (
              <div style={{ marginTop: 6 }}
                dangerouslySetInnerHTML={{ __html: spdR.svg }} />
            )}
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Diffraction PSF" icon={Sun} color="#f59e0b" result={psfR} error={psfE} running={psfRun}>
        <NumRow label="wavelength (nm)" value={psf.wavelength_nm} onChange={v => setPsf(p => ({ ...p, wavelength_nm: v }))} disabled={psfRun} />
        <NumRow label="F-number" value={psf.f_number} onChange={v => setPsf(p => ({ ...p, f_number: v }))} disabled={psfRun} />
        <NumRow label="grid size" value={psf.grid_size} onChange={v => setPsf(p => ({ ...p, grid_size: v }))} step="1" disabled={psfRun} />
        <NumRow label="defocus (waves)" value={psf.defocus_waves} onChange={v => setPsf(p => ({ ...p, defocus_waves: v }))} disabled={psfRun} />
        <RunBtn onClick={runDiffrPsf} running={psfRun} />
      </ToolWidget>

      <ToolWidget title="Pixel MTF (combined lens+sensor)" icon={Zap} color="#06b6d4" result={pmtfR} error={pmtfE} running={pmtfRun}>
        <NumRow label="pixel pitch (µm)" value={pmtf.pixel_pitch_um} onChange={v => setPmtf(p => ({ ...p, pixel_pitch_um: v }))} disabled={pmtfRun} />
        <NumRow label="fill factor" value={pmtf.fill_factor} onChange={v => setPmtf(p => ({ ...p, fill_factor: v }))} disabled={pmtfRun} />
        <NumRow label="wavelength (nm)" value={pmtf.wavelength_nm} onChange={v => setPmtf(p => ({ ...p, wavelength_nm: v }))} disabled={pmtfRun} />
        <NumRow label="F-number" value={pmtf.f_number} onChange={v => setPmtf(p => ({ ...p, f_number: v }))} disabled={pmtfRun} />
        <RunBtn onClick={runPixelMtf} running={pmtfRun} />
      </ToolWidget>

      <ToolWidget title="Airy Disk Radius" icon={Circle} color="#a78bfa" result={airyR} error={airyE} running={airyRun}>
        <NumRow label="wavelength (m)" value={airy.wavelength} onChange={v => setAiry(p => ({ ...p, wavelength: v }))} disabled={airyRun} />
        <NumRow label="F-number" value={airy.N} onChange={v => setAiry(p => ({ ...p, N: v }))} disabled={airyRun} />
        <RunBtn onClick={runAiry} running={airyRun} />
      </ToolWidget>

      <ToolWidget title="Defocus Curve (through-focus RMS spot size)" icon={RefreshCw} color="#f43f5e" result={dcR} error={dcE} running={dcRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
          <textarea value={dc.surfaces} onChange={e => setDc(p => ({ ...p, surfaces: e.target.value }))} disabled={dcRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <NumRow label="field angle (deg)" value={dc.field_angle_deg} onChange={v => setDc(p => ({ ...p, field_angle_deg: v }))} disabled={dcRun} />
        <NumRow label="defocus range (mm)" value={dc.defocus_range_mm} onChange={v => setDc(p => ({ ...p, defocus_range_mm: v }))} disabled={dcRun} />
        <RunBtn onClick={runDefocus} running={dcRun} />
        {dcR && !dcRun && (
          <div style={s.resultBox}>
            <div style={{ ...s.mono, fontSize: 11 }}>
              Best focus shift: {fmt(dcR.best_focus_shift_mm)} mm &nbsp;|&nbsp;
              Min RMS: {fmt(dcR.min_rms_mm)} mm
            </div>
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 4: Pupils & Field
// ---------------------------------------------------------------------------

function TabPupilsField() {
  // ── optics_pupil_diagram ──
  const [pd, setPd] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angles: '0,5,14', aperture_radius_mm: '10' })
  const [pdR, setPdR] = useState(null); const [pdE, setPdE] = useState(null); const [pdRun, setPdRun] = useState(false)
  const runPupilDiagram = useCallback(async () => {
    setPdRun(true); setPdE(null); setPdR(null)
    try {
      const surfaces = JSON.parse(pd.surfaces)
      const field_angles_deg = pd.field_angles.split(',').map(Number)
      const r = await callTool('optics_pupil_diagram', { surfaces, field_angles_deg, aperture_radius_mm: +pd.aperture_radius_mm })
      setPdR(r)
    } catch (e) { setPdE(e.message) } finally { setPdRun(false) }
  }, [pd])

  // ── optics_compute_vignetting ──
  const [vig, setVig] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angles: '0,5,10,14', aperture_radius_mm: '10' })
  const [vigR, setVigR] = useState(null); const [vigE, setVigE] = useState(null); const [vigRun, setVigRun] = useState(false)
  const runVignetting = useCallback(async () => {
    setVigRun(true); setVigE(null); setVigR(null)
    try {
      const surfaces = JSON.parse(vig.surfaces)
      const field_angles_deg = vig.field_angles.split(',').map(Number)
      const r = await callTool('optics_compute_vignetting', { surfaces, field_angles_deg, aperture_radius_mm: +vig.aperture_radius_mm })
      setVigR(r)
    } catch (e) { setVigE(e.message) } finally { setVigRun(false) }
  }, [vig])

  // ── optics_compute_entrance_pupil ──
  const [ep, setEp] = useState({ surfaces: BK7_SURFACES_DEFAULT, stop_diameter_mm: '20' })
  const [epR, setEpR] = useState(null); const [epE, setEpE] = useState(null); const [epRun, setEpRun] = useState(false)
  const runEntrance = useCallback(async () => {
    setEpRun(true); setEpE(null); setEpR(null)
    try {
      const surfaces = JSON.parse(ep.surfaces)
      const r = await callTool('optics_compute_entrance_pupil', { surfaces, stop_diameter_mm: +ep.stop_diameter_mm })
      setEpR(r)
    } catch (e) { setEpE(e.message) } finally { setEpRun(false) }
  }, [ep])

  // ── optics_compute_exit_pupil ──
  const [xp, setXp] = useState({ surfaces: BK7_SURFACES_DEFAULT, stop_diameter_mm: '20' })
  const [xpR, setXpR] = useState(null); const [xpE, setXpE] = useState(null); const [xpRun, setXpRun] = useState(false)
  const runExit = useCallback(async () => {
    setXpRun(true); setXpE(null); setXpR(null)
    try {
      const surfaces = JSON.parse(xp.surfaces)
      const r = await callTool('optics_compute_exit_pupil', { surfaces, stop_diameter_mm: +xp.stop_diameter_mm })
      setXpR(r)
    } catch (e) { setXpE(e.message) } finally { setXpRun(false) }
  }, [xp])

  // ── optics_compute_relative_illum_map ──
  const [ri, setRi] = useState({ surfaces: BK7_SURFACES_DEFAULT, sensor_half_height_mm: '15', aperture_radius_mm: '10' })
  const [riR, setRiR] = useState(null); const [riE, setRiE] = useState(null); const [riRun, setRiRun] = useState(false)
  const runRelIllum = useCallback(async () => {
    setRiRun(true); setRiE(null); setRiR(null)
    try {
      const surfaces = JSON.parse(ri.surfaces)
      const r = await callTool('optics_compute_relative_illum_map', { surfaces, sensor_half_height_mm: +ri.sensor_half_height_mm, aperture_radius_mm: +ri.aperture_radius_mm })
      setRiR(r)
    } catch (e) { setRiE(e.message) } finally { setRiRun(false) }
  }, [ri])

  // ── optics_compute_vignetting_check ──
  const [vc, setVc] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angles: '0,5,10,14' })
  const [vcR, setVcR] = useState(null); const [vcE, setVcE] = useState(null); const [vcRun, setVcRun] = useState(false)
  const runVigCheck = useCallback(async () => {
    setVcRun(true); setVcE(null); setVcR(null)
    try {
      const surfaces = JSON.parse(vc.surfaces)
      const field_angles_deg = vc.field_angles.split(',').map(Number)
      const r = await callTool('optics_compute_vignetting_check', { surfaces, field_angles_deg })
      setVcR(r)
    } catch (e) { setVcE(e.message) } finally { setVcRun(false) }
  }, [vc])

  // ── optics_compute_telecentricity ──
  const [tc, setTc] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angles: '0,5,10,14' })
  const [tcR, setTcR] = useState(null); const [tcE, setTcE] = useState(null); const [tcRun, setTcRun] = useState(false)
  const runTelecentric = useCallback(async () => {
    setTcRun(true); setTcE(null); setTcR(null)
    try {
      const surfaces = JSON.parse(tc.surfaces)
      const field_angles_deg = tc.field_angles.split(',').map(Number)
      const r = await callTool('optics_compute_telecentricity', { surfaces, field_angles_deg })
      setTcR(r)
    } catch (e) { setTcE(e.message) } finally { setTcRun(false) }
  }, [tc])

  function PupilSummary({ data }) {
    if (!data || !data.rms_spot_size_per_field) return null
    return (
      <div style={s.resultBox}>
        <div style={s.subhead}>RMS spot radius per field (mm)</div>
        {data.rms_spot_size_per_field.map((v, i) => (
          <div key={i} style={{ ...s.mono, fontSize: 11 }}>
            Field {i}: {fmt(v)} mm
          </div>
        ))}
      </div>
    )
  }

  const surfacesInput = (val, setter, disabled) => (
    <div style={s.row}>
      <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
      <textarea value={val} onChange={e => setter(p => ({ ...p, surfaces: e.target.value }))} disabled={disabled}
        rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
    </div>
  )

  return (
    <div>
      <ToolWidget title="Pupil Diagram (spot intercepts + exit-pupil map)" icon={Aperture} color="#3b82f6" result={null} error={pdE} running={pdRun}>
        {surfacesInput(pd.surfaces, setPd, pdRun)}
        <div style={s.row}>
          <label style={s.label}>Field angles (deg, CSV)</label>
          <input value={pd.field_angles} onChange={e => setPd(p => ({ ...p, field_angles: e.target.value }))} disabled={pdRun} style={s.input} />
        </div>
        <NumRow label="aperture radius (mm)" value={pd.aperture_radius_mm} onChange={v => setPd(p => ({ ...p, aperture_radius_mm: v }))} disabled={pdRun} />
        <RunBtn onClick={runPupilDiagram} running={pdRun} />
        {pdR && <PupilSummary data={pdR} />}
      </ToolWidget>

      <ToolWidget title="Vignetting (relative illumination)" icon={Eye} color="#f59e0b" result={null} error={vigE} running={vigRun}>
        {surfacesInput(vig.surfaces, setVig, vigRun)}
        <div style={s.row}>
          <label style={s.label}>Field angles (deg, CSV)</label>
          <input value={vig.field_angles} onChange={e => setVig(p => ({ ...p, field_angles: e.target.value }))} disabled={vigRun} style={s.input} />
        </div>
        <NumRow label="aperture radius (mm)" value={vig.aperture_radius_mm} onChange={v => setVig(p => ({ ...p, aperture_radius_mm: v }))} disabled={vigRun} />
        <RunBtn onClick={runVignetting} running={vigRun} />
        {vigR && !vigRun && (
          <div style={s.resultBox}>
            <table style={s.table}>
              <thead><tr>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>Field°</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>Rel. illum.</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>cos⁴ baseline</td>
              </tr></thead>
              <tbody>
                {(Array.isArray(vigR) ? vigR : vigR.per_field || []).map((f, i) => (
                  <tr key={i}>
                    <td style={s.td}>{fmt(f.field_angle_deg ?? i, 1)}</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(f.relative_illumination ?? f.ri, 3)}</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmt(f.cos4_baseline, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Entrance Pupil (position + size)" icon={Circle} color="#10b981" result={epR} error={epE} running={epRun}>
        {surfacesInput(ep.surfaces, setEp, epRun)}
        <NumRow label="stop diameter (mm)" value={ep.stop_diameter_mm} onChange={v => setEp(p => ({ ...p, stop_diameter_mm: v }))} disabled={epRun} />
        <RunBtn onClick={runEntrance} running={epRun} />
      </ToolWidget>

      <ToolWidget title="Exit Pupil (Ramsden disk)" icon={Circle} color="#6366f1" result={xpR} error={xpE} running={xpRun}>
        {surfacesInput(xp.surfaces, setXp, xpRun)}
        <NumRow label="stop diameter (mm)" value={xp.stop_diameter_mm} onChange={v => setXp(p => ({ ...p, stop_diameter_mm: v }))} disabled={xpRun} />
        <RunBtn onClick={runExit} running={xpRun} />
      </ToolWidget>

      <ToolWidget title="Relative Illumination Map (2-D)" icon={Sun} color="#dc2626" result={riR} error={riE} running={riRun}>
        {surfacesInput(ri.surfaces, setRi, riRun)}
        <NumRow label="sensor half-height (mm)" value={ri.sensor_half_height_mm} onChange={v => setRi(p => ({ ...p, sensor_half_height_mm: v }))} disabled={riRun} />
        <NumRow label="aperture radius (mm)" value={ri.aperture_radius_mm} onChange={v => setRi(p => ({ ...p, aperture_radius_mm: v }))} disabled={riRun} />
        <RunBtn onClick={runRelIllum} running={riRun} />
        {riR && !riRun && (
          <div style={s.resultBox}>
            <div style={{ ...s.mono, fontSize: 11 }}>
              Corner RI: {fmt(riR.corner_ri, 3)} &nbsp;|&nbsp; cos⁴: {fmt(riR.corner_cos4, 3)} &nbsp;|&nbsp; Max field: {fmt(riR.max_field_angle, 1)}°
            </div>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Vignetting Check (chief-ray + stop)" icon={AlertTriangle} color="#ea580c" result={vcR} error={vcE} running={vcRun}>
        {surfacesInput(vc.surfaces, setVc, vcRun)}
        <div style={s.row}>
          <label style={s.label}>Field angles (deg, CSV)</label>
          <input value={vc.field_angles} onChange={e => setVc(p => ({ ...p, field_angles: e.target.value }))} disabled={vcRun} style={s.input} />
        </div>
        <RunBtn onClick={runVigCheck} running={vcRun} />
      </ToolWidget>

      <ToolWidget title="Telecentricity Check" icon={Eye} color="#7c3aed" result={tcR} error={tcE} running={tcRun}>
        {surfacesInput(tc.surfaces, setTc, tcRun)}
        <div style={s.row}>
          <label style={s.label}>Field angles (deg, CSV)</label>
          <input value={tc.field_angles} onChange={e => setTc(p => ({ ...p, field_angles: e.target.value }))} disabled={tcRun} style={s.input} />
        </div>
        <RunBtn onClick={runTelecentric} running={tcRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 5: Utilities (Wavefront, Rays, Other)
// ---------------------------------------------------------------------------

function TabUtilities() {
  // ── optics_fit_zernike_wavefront ──
  const [zern, setZern] = useState({
    samples: JSON.stringify([
      [0.0, 0.0, 0.0], [0.5, 0.0, 0.1], [1.0, 0.0, 0.3],
      [0.5, 1.57, -0.05], [1.0, 1.57, -0.1]
    ]),
    num_terms: '15'
  })
  const [zernR, setZernR] = useState(null); const [zernE, setZernE] = useState(null); const [zernRun, setZernRun] = useState(false)
  const runZernike = useCallback(async () => {
    setZernRun(true); setZernE(null); setZernR(null)
    try {
      const samples = JSON.parse(zern.samples)
      const r = await callTool('optics_fit_zernike_wavefront', { samples, num_terms: +zern.num_terms })
      setZernR(r)
    } catch (e) { setZernE(e.message) } finally { setZernRun(false) }
  }, [zern])

  // ── optics_analyze_wavefront_alignment ──
  const [wa, setWa] = useState({
    samples: JSON.stringify([
      [0.0, 0.0, 0.05], [0.5, 0.0, 0.08], [1.0, 0.0, 0.20],
      [0.7, 1.57, 0.12], [0.3, 3.14, 0.02]
    ])
  })
  const [waR, setWaR] = useState(null); const [waE, setWaE] = useState(null); const [waRun, setWaRun] = useState(false)
  const runWfAlign = useCallback(async () => {
    setWaRun(true); setWaE(null); setWaR(null)
    try {
      const samples = JSON.parse(wa.samples)
      const r = await callTool('optics_analyze_wavefront_alignment', { samples })
      setWaR(r)
    } catch (e) { setWaE(e.message) } finally { setWaRun(false) }
  }, [wa])

  // ── optics_snell ──
  const [snell, setSnell] = useState({ n1: '1.0', theta1_rad: '0.3', n2: '1.5168' })
  const [snellR, setSnellR] = useState(null); const [snellE, setSnellE] = useState(null); const [snellRun, setSnellRun] = useState(false)
  const runSnell = useCallback(async () => {
    setSnellRun(true); setSnellE(null); setSnellR(null)
    try { const r = await callTool('optics_snell', { n1: +snell.n1, theta1_rad: +snell.theta1_rad, n2: +snell.n2 }); setSnellR(r) }
    catch (e) { setSnellE(e.message) } finally { setSnellRun(false) }
  }, [snell])

  // ── optics_critical_angle ──
  const [cang, setCang] = useState({ n1: '1.5168', n2: '1.0' })
  const [cangR, setCangR] = useState(null); const [cangE, setCangE] = useState(null); const [cangRun, setCangRun] = useState(false)
  const runCritAngle = useCallback(async () => {
    setCangRun(true); setCangE(null); setCangR(null)
    try { const r = await callTool('optics_critical_angle', { n1: +cang.n1, n2: +cang.n2 }); setCangR(r) }
    catch (e) { setCangE(e.message) } finally { setCangRun(false) }
  }, [cang])

  // ── optics_brewster_angle ──
  const [brew, setBrew] = useState({ n1: '1.0', n2: '1.5168' })
  const [brewR, setBrewR] = useState(null); const [brewE, setBrewE] = useState(null); const [brewRun, setBrewRun] = useState(false)
  const runBrewster = useCallback(async () => {
    setBrewRun(true); setBrewE(null); setBrewR(null)
    try { const r = await callTool('optics_brewster_angle', { n1: +brew.n1, n2: +brew.n2 }); setBrewR(r) }
    catch (e) { setBrewE(e.message) } finally { setBrewRun(false) }
  }, [brew])

  // ── optics_prism_deviation ──
  const [prism, setPrism] = useState({ n: '1.5168', apex_rad: '0.5236', theta_i_rad: '0.5236' })
  const [prismR, setPrismR] = useState(null); const [prismE, setPrismE] = useState(null); const [prismRun, setPrismRun] = useState(false)
  const runPrism = useCallback(async () => {
    setPrismRun(true); setPrismE(null); setPrismR(null)
    try { const r = await callTool('optics_prism_deviation', { n: +prism.n, apex_rad: +prism.apex_rad, theta_i_rad: +prism.theta_i_rad }); setPrismR(r) }
    catch (e) { setPrismE(e.message) } finally { setPrismRun(false) }
  }, [prism])

  // ── optics_mirror_imaging ──
  const [mirr, setMirr] = useState({ R: '-0.2', s_o: '0.5' })
  const [mirrR, setMirrR] = useState(null); const [mirrE, setMirrE] = useState(null); const [mirrRun, setMirrRun] = useState(false)
  const runMirror = useCallback(async () => {
    setMirrRun(true); setMirrE(null); setMirrR(null)
    try { const r = await callTool('optics_mirror_imaging', { R: +mirr.R, s_o: +mirr.s_o }); setMirrR(r) }
    catch (e) { setMirrE(e.message) } finally { setMirrRun(false) }
  }, [mirr])

  // ── optics_design_schmidt_corrector ──
  const [schmidt, setSchmidt] = useState({ D_mm: '300', R_mm: '2400', n: '1.5168' })
  const [schmidtR, setSchmidtR] = useState(null); const [schmidtE, setSchmidtE] = useState(null); const [schmidtRun, setSchmidtRun] = useState(false)
  const runSchmidt = useCallback(async () => {
    setSchmidtRun(true); setSchmidtE(null); setSchmidtR(null)
    try {
      const r = await callTool('optics_design_schmidt_corrector', { D_mm: +schmidt.D_mm, R_mm: +schmidt.R_mm, n: +schmidt.n })
      setSchmidtR(r)
    } catch (e) { setSchmidtE(e.message) } finally { setSchmidtRun(false) }
  }, [schmidt])

  // ── optics_compute_working_fno ──
  const [wfno, setWfno] = useState({ f_number: '4', magnification: '0.1' })
  const [wfnoR, setWfnoR] = useState(null); const [wfnoE, setWfnoE] = useState(null); const [wfnoRun, setWfnoRun] = useState(false)
  const runWorkingFno = useCallback(async () => {
    setWfnoRun(true); setWfnoE(null); setWfnoR(null)
    try { const r = await callTool('optics_compute_working_fno', { f_number: +wfno.f_number, magnification: +wfno.magnification }); setWfnoR(r) }
    catch (e) { setWfnoE(e.message) } finally { setWfnoRun(false) }
  }, [wfno])

  // ── optics_compute_lens_volume ──
  const [lv, setLv] = useState({ surfaces: BK7_SURFACES_DEFAULT, aperture_radius_mm: '25' })
  const [lvR, setLvR] = useState(null); const [lvE, setLvE] = useState(null); const [lvRun, setLvRun] = useState(false)
  const runLensVolume = useCallback(async () => {
    setLvRun(true); setLvE(null); setLvR(null)
    try {
      const surfaces = JSON.parse(lv.surfaces)
      const r = await callTool('optics_compute_lens_volume', { surfaces, aperture_radius_mm: +lv.aperture_radius_mm })
      setLvR(r)
    } catch (e) { setLvE(e.message) } finally { setLvRun(false) }
  }, [lv])

  // ── optics_compute_iris_diameter_map ──
  const [iris, setIris] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angles: '0,5,10,14', aperture_radius_mm: '10' })
  const [irisR, setIrisR] = useState(null); const [irisE, setIrisE] = useState(null); const [irisRun, setIrisRun] = useState(false)
  const runIris = useCallback(async () => {
    setIrisRun(true); setIrisE(null); setIrisR(null)
    try {
      const surfaces = JSON.parse(iris.surfaces)
      const field_angles_deg = iris.field_angles.split(',').map(Number)
      const r = await callTool('optics_compute_iris_diameter_map', { surfaces, field_angles_deg, aperture_radius_mm: +iris.aperture_radius_mm })
      setIrisR(r)
    } catch (e) { setIrisE(e.message) } finally { setIrisRun(false) }
  }, [iris])

  // ── optics_compute_sagitta_arrow_chart ──
  const [sag, setSag] = useState({ surfaces: BK7_SURFACES_DEFAULT })
  const [sagR, setSagR] = useState(null); const [sagE, setSagE] = useState(null); const [sagRun, setSagRun] = useState(false)
  const runSagitta = useCallback(async () => {
    setSagRun(true); setSagE(null); setSagR(null)
    try {
      const surfaces = JSON.parse(sag.surfaces)
      const r = await callTool('optics_compute_sagitta_arrow_chart', { surfaces })
      setSagR(r)
    } catch (e) { setSagE(e.message) } finally { setSagRun(false) }
  }, [sag])

  // ── optics_compute_depth_of_field (extended) ──
  const [edof, setEdof] = useState({ surfaces: BK7_SURFACES_DEFAULT, aperture_radius_mm: '5', rms_threshold_mm: '0.01' })
  const [edofR, setEdofR] = useState(null); const [edofE, setEdofE] = useState(null); const [edofRun, setEdofRun] = useState(false)
  const runExtDof = useCallback(async () => {
    setEdofRun(true); setEdofE(null); setEdofR(null)
    try {
      const surfaces = JSON.parse(edof.surfaces)
      const r = await callTool('optics_compute_depth_of_field', { surfaces, aperture_radius_mm: +edof.aperture_radius_mm, rms_threshold_mm: +edof.rms_threshold_mm })
      setEdofR(r)
    } catch (e) { setEdofE(e.message) } finally { setEdofRun(false) }
  }, [edof])

  // ── optics_trace_chief_ray ──
  const [cr, setCr] = useState({ surfaces: BK7_SURFACES_DEFAULT, field_angle_deg: '10' })
  const [crR, setCrR] = useState(null); const [crE, setCrE] = useState(null); const [crRun, setCrRun] = useState(false)
  const runChiefRay = useCallback(async () => {
    setCrRun(true); setCrE(null); setCrR(null)
    try {
      const surfaces = JSON.parse(cr.surfaces)
      const r = await callTool('optics_trace_chief_ray', { surfaces, field_angle_deg: +cr.field_angle_deg })
      setCrR(r)
    } catch (e) { setCrE(e.message) } finally { setCrRun(false) }
  }, [cr])

  // ── optics_abcd_system ──
  const [abcd, setAbcd] = useState({
    elements: JSON.stringify([
      { type: 'free_space', d: 0.05 },
      { type: 'thin_lens', f: 0.1 },
      { type: 'free_space', d: 0.1 }
    ])
  })
  const [abcdR, setAbcdR] = useState(null); const [abcdE, setAbcdE] = useState(null); const [abcdRun, setAbcdRun] = useState(false)
  const runAbcd = useCallback(async () => {
    setAbcdRun(true); setAbcdE(null); setAbcdR(null)
    try {
      const elements = JSON.parse(abcd.elements)
      const r = await callTool('optics_abcd_system', { elements })
      setAbcdR(r)
    } catch (e) { setAbcdE(e.message) } finally { setAbcdRun(false) }
  }, [abcd])

  const surfacesInput = (val, setter, disabled) => (
    <div style={s.row}>
      <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Surfaces (JSON)</label>
      <textarea value={val} onChange={e => setter(p => ({ ...p, surfaces: e.target.value }))} disabled={disabled}
        rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
    </div>
  )

  return (
    <div>
      <ToolWidget title="Schmidt Corrector Design (aspheric profile)" icon={Sun} color="#f59e0b" result={schmidtR} error={schmidtE} running={schmidtRun}>
        <NumRow label="D aperture (mm)" value={schmidt.D_mm} onChange={v => setSchmidt(p => ({ ...p, D_mm: v }))} disabled={schmidtRun} />
        <NumRow label="R mirror radius (mm)" value={schmidt.R_mm} onChange={v => setSchmidt(p => ({ ...p, R_mm: v }))} disabled={schmidtRun} />
        <NumRow label="n glass index" value={schmidt.n} onChange={v => setSchmidt(p => ({ ...p, n: v }))} disabled={schmidtRun} />
        <RunBtn onClick={runSchmidt} running={schmidtRun} />
      </ToolWidget>

      <ToolWidget title="Zernike Wavefront Fit (Noll j=1..15)" icon={RefreshCw} color="#3b82f6" result={null} error={zernE} running={zernRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Samples [ρ,θ,W] (JSON)</label>
          <textarea value={zern.samples} onChange={e => setZern(p => ({ ...p, samples: e.target.value }))} disabled={zernRun}
            rows={4} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <NumRow label="num_terms (1–15)" value={zern.num_terms} onChange={v => setZern(p => ({ ...p, num_terms: v }))} step="1" disabled={zernRun} />
        <RunBtn onClick={runZernike} running={zernRun} />
        {zernR && !zernRun && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Dominant aberration: {zernR.dominant_aberration}</div>
            <div style={{ ...s.mono, fontSize: 11 }}>RMS residual: {fmt(zernR.rms_residual_waves)} waves</div>
            {Array.isArray(zernR.coefficients) && zernR.coefficient_names && (
              <table style={{ ...s.table, marginTop: 6 }}>
                <tbody>
                  {zernR.coefficients.map((c, i) => (
                    <tr key={i}>
                      <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>j={i+1} {zernR.coefficient_names[i]}</td>
                      <td style={{ ...s.td, ...s.mono, fontSize: 11 }}>{fmt(c)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Wavefront Alignment (piston/tip/tilt)" icon={Eye} color="#8b5cf6" result={waR} error={waE} running={waRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Samples [ρ,θ,W] (JSON)</label>
          <textarea value={wa.samples} onChange={e => setWa(p => ({ ...p, samples: e.target.value }))} disabled={waRun}
            rows={4} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <RunBtn onClick={runWfAlign} running={waRun} />
      </ToolWidget>

      <ToolWidget title="Snell's Law" icon={Zap} color="#10b981" result={snellR} error={snellE} running={snellRun}>
        <NumRow label="n1" value={snell.n1} onChange={v => setSnell(p => ({ ...p, n1: v }))} disabled={snellRun} />
        <NumRow label="θ1 (rad)" value={snell.theta1_rad} onChange={v => setSnell(p => ({ ...p, theta1_rad: v }))} disabled={snellRun} />
        <NumRow label="n2" value={snell.n2} onChange={v => setSnell(p => ({ ...p, n2: v }))} disabled={snellRun} />
        <RunBtn onClick={runSnell} running={snellRun} />
      </ToolWidget>

      <ToolWidget title="Critical Angle (TIR)" icon={Zap} color="#ef4444" result={cangR} error={cangE} running={cangRun}>
        <NumRow label="n1 (denser)" value={cang.n1} onChange={v => setCang(p => ({ ...p, n1: v }))} disabled={cangRun} />
        <NumRow label="n2 (less dense)" value={cang.n2} onChange={v => setCang(p => ({ ...p, n2: v }))} disabled={cangRun} />
        <RunBtn onClick={runCritAngle} running={cangRun} />
      </ToolWidget>

      <ToolWidget title="Brewster's Angle (polarisation)" icon={Zap} color="#06b6d4" result={brewR} error={brewE} running={brewRun}>
        <NumRow label="n1 incident" value={brew.n1} onChange={v => setBrew(p => ({ ...p, n1: v }))} disabled={brewRun} />
        <NumRow label="n2 transmitted" value={brew.n2} onChange={v => setBrew(p => ({ ...p, n2: v }))} disabled={brewRun} />
        <RunBtn onClick={runBrewster} running={brewRun} />
      </ToolWidget>

      <ToolWidget title="Prism Deviation" icon={Circle} color="#a78bfa" result={prismR} error={prismE} running={prismRun}>
        <NumRow label="n glass" value={prism.n} onChange={v => setPrism(p => ({ ...p, n: v }))} disabled={prismRun} />
        <NumRow label="apex angle (rad)" value={prism.apex_rad} onChange={v => setPrism(p => ({ ...p, apex_rad: v }))} disabled={prismRun} />
        <NumRow label="θ incidence (rad)" value={prism.theta_i_rad} onChange={v => setPrism(p => ({ ...p, theta_i_rad: v }))} disabled={prismRun} />
        <RunBtn onClick={runPrism} running={prismRun} />
      </ToolWidget>

      <ToolWidget title="Spherical Mirror Imaging" icon={Circle} color="#f97316" result={mirrR} error={mirrE} running={mirrRun}>
        <NumRow label="R radius (m)" value={mirr.R} onChange={v => setMirr(p => ({ ...p, R: v }))} disabled={mirrRun} />
        <NumRow label="s_o object dist (m)" value={mirr.s_o} onChange={v => setMirr(p => ({ ...p, s_o: v }))} disabled={mirrRun} />
        <RunBtn onClick={runMirror} running={mirrRun} />
      </ToolWidget>

      <ToolWidget title="Working F-number (magnified system)" icon={Aperture} color="#7c3aed" result={wfnoR} error={wfnoE} running={wfnoRun}>
        <NumRow label="F-number (infinity)" value={wfno.f_number} onChange={v => setWfno(p => ({ ...p, f_number: v }))} disabled={wfnoRun} />
        <NumRow label="magnification" value={wfno.magnification} onChange={v => setWfno(p => ({ ...p, magnification: v }))} disabled={wfnoRun} />
        <RunBtn onClick={runWorkingFno} running={wfnoRun} />
      </ToolWidget>

      <ToolWidget title="Lens Volume (glass mass estimate)" icon={Circle} color="#0d9488" result={lvR} error={lvE} running={lvRun}>
        {surfacesInput(lv.surfaces, setLv, lvRun)}
        <NumRow label="aperture radius (mm)" value={lv.aperture_radius_mm} onChange={v => setLv(p => ({ ...p, aperture_radius_mm: v }))} disabled={lvRun} />
        <RunBtn onClick={runLensVolume} running={lvRun} />
      </ToolWidget>

      <ToolWidget title="Iris Diameter Map" icon={Aperture} color="#c026d3" result={irisR} error={irisE} running={irisRun}>
        {surfacesInput(iris.surfaces, setIris, irisRun)}
        <div style={s.row}>
          <label style={s.label}>Field angles (deg, CSV)</label>
          <input value={iris.field_angles} onChange={e => setIris(p => ({ ...p, field_angles: e.target.value }))} disabled={irisRun} style={s.input} />
        </div>
        <NumRow label="aperture radius (mm)" value={iris.aperture_radius_mm} onChange={v => setIris(p => ({ ...p, aperture_radius_mm: v }))} disabled={irisRun} />
        <RunBtn onClick={runIris} running={irisRun} />
      </ToolWidget>

      <ToolWidget title="Sagitta Arrow Chart" icon={RefreshCw} color="#7c3aed" result={sagR} error={sagE} running={sagRun}>
        {surfacesInput(sag.surfaces, setSag, sagRun)}
        <RunBtn onClick={runSagitta} running={sagRun} />
      </ToolWidget>

      <ToolWidget title="Extended Depth of Field (system DOF via ray trace)" icon={Eye} color="#dc2626" result={edofR} error={edofE} running={edofRun}>
        {surfacesInput(edof.surfaces, setEdof, edofRun)}
        <NumRow label="aperture radius (mm)" value={edof.aperture_radius_mm} onChange={v => setEdof(p => ({ ...p, aperture_radius_mm: v }))} disabled={edofRun} />
        <NumRow label="RMS threshold (mm)" value={edof.rms_threshold_mm} onChange={v => setEdof(p => ({ ...p, rms_threshold_mm: v }))} disabled={edofRun} />
        <RunBtn onClick={runExtDof} running={edofRun} />
      </ToolWidget>

      <ToolWidget title="Chief Ray Trace" icon={Sun} color="#f59e0b" result={crR} error={crE} running={crRun}>
        {surfacesInput(cr.surfaces, setCr, crRun)}
        <NumRow label="field angle (deg)" value={cr.field_angle_deg} onChange={v => setCr(p => ({ ...p, field_angle_deg: v }))} disabled={crRun} />
        <RunBtn onClick={runChiefRay} running={crRun} />
      </ToolWidget>

      <ToolWidget title="ABCD Matrix System" icon={Zap} color="#3b82f6" result={abcdR} error={abcdE} running={abcdRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Elements (JSON)</label>
          <textarea value={abcd.elements} onChange={e => setAbcd(p => ({ ...p, elements: e.target.value }))} disabled={abcdRun}
            rows={4} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>Types: free_space (d), thin_lens (f), mirror (R), refraction (n1,n2,R)</div>
        <RunBtn onClick={runAbcd} running={abcdRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'lens',       label: 'Lens Design',      icon: Circle  },
  { id: 'aberr',      label: 'Aberrations',       icon: Eye     },
  { id: 'mtf',        label: 'MTF / PSF',         icon: Zap     },
  { id: 'pupils',     label: 'Pupils & Field',    icon: Aperture},
  { id: 'utils',      label: 'Utilities',         icon: Sun     },
]

export default function OpticsDesignPanel() {
  const [activeTab, setActiveTab] = useState('lens')

  return (
    <div style={s.root} data-testid="optics-design-panel">
      <div style={s.header}>
        <Eye size={15} style={{ color: '#60a5fa' }} />
        <span style={s.title}>Optics Design</span>
        <span style={{ ...s.badge, background: '#1d4ed8', color: '#bfdbfe' }}>42 tools</span>
      </div>

      <div style={s.tabs}>
        {TABS.map(t => (
          <button
            key={t.id}
            style={{ ...s.tab, ...(activeTab === t.id ? s.tabActive : {}) }}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === 'lens'    && <TabLensDesign />}
      {activeTab === 'aberr'   && <TabAberrations />}
      {activeTab === 'mtf'     && <TabMtfPsf />}
      {activeTab === 'pupils'  && <TabPupilsField />}
      {activeTab === 'utils'   && <TabUtilities />}
    </div>
  )
}
