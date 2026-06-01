// StructuralPanel.jsx — Architectural / Structural engineering solver panel.
//
// Wires 24 arch_* LLM backend tools into a tabbed UI.
// Tabs: Beam & Slab | Lateral Loads (Wind) | Connections | Walls & Footings | Stairs & Misc
//
// All tools dispatch POST /api/tools/call with { tool: "<name>", args: {...} }.
// Results are rendered inline (numbers, tables, status badges).
//
// Props: none (standalone panel — operates without a project file)

import { useState, useCallback } from 'react'
import {
  Building2, Wind, Wrench, Layers, AlertTriangle, CheckCircle,
  Loader2, Play, ChevronDown, ChevronUp, Construction,
} from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Styles (matching OpticsDesignPanel.jsx / BucklingPanel.jsx pattern)
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
  label:        { color: '#9ca3af', width: 160, flexShrink: 0, fontSize: 11 },
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
  passChip:     { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700, background: '#064e3b', color: '#34d399' },
  failChip:     { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700, background: '#450a0a', color: '#f87171' },
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

function fmt(v, decimals = 3) {
  if (v == null) return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v)
    return Math.abs(v) > 1e4 || (Math.abs(v) < 1e-2 && v !== 0)
      ? v.toExponential(3)
      : v.toFixed(decimals)
  }
  return String(v)
}

function StatusChip({ ok }) {
  return ok
    ? <span style={s.passChip}>PASS</span>
    : <span style={s.failChip}>FAIL</span>
}

function ResultTable({ data, skip = [] }) {
  if (!data || typeof data !== 'object') return null
  const entries = Object.entries(data).filter(
    ([k, v]) => !skip.includes(k) && typeof v !== 'object' && !Array.isArray(v)
  )
  if (!entries.length) return null
  return (
    <table style={s.table}>
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <td style={{ ...s.td, color: '#9ca3af', width: '55%' }}>{k}</td>
            <td style={{ ...s.td, ...s.mono }}>{fmt(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ToolWidget({ title, icon: Icon, color = '#2563eb', children, result, error, running, passKey }) {
  const [open, setOpen] = useState(true)
  const ok = result && passKey ? Boolean(result[passKey]) : undefined

  return (
    <div style={{ ...s.section, borderLeft: `3px solid ${color}` }}>
      <div
        style={{ ...s.sectionTitle, justifyContent: 'space-between', cursor: 'pointer' }}
        onClick={() => setOpen(o => !o)}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {Icon && <Icon size={12} style={{ color }} />}
          {title}
          {result && passKey && !running && (
            <span style={{ marginLeft: 4 }}>
              <StatusChip ok={ok} />
            </span>
          )}
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
              <ResultTable data={result} skip={['honest_caveat', 'code_section']} />
              {result.honest_caveat && (
                <div style={{ color: '#6b7280', fontSize: 10, marginTop: 4, fontFamily: 'sans-serif' }}>
                  {result.honest_caveat.slice(0, 200)}{result.honest_caveat.length > 200 ? '…' : ''}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function RunBtn({ onClick, running, label = 'Run' }) {
  return (
    <button
      onClick={onClick}
      disabled={running}
      style={{ ...s.button, background: '#1e40af', marginTop: 6, ...(running ? s.buttonDisabled : {}) }}
    >
      {running
        ? <><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> Computing…</>
        : <><Play size={12} /> {label}</>}
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

function SelRow({ label, value, onChange, options, disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        disabled={disabled}
        style={s.select}
      >
        {options.map(o =>
          typeof o === 'string'
            ? <option key={o} value={o}>{o}</option>
            : <option key={o.value} value={o.value}>{o.label}</option>
        )}
      </select>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 1: Beam & Slab
// ---------------------------------------------------------------------------

function TabBeamSlab() {
  // ── arch_compute_beam_deflection ──
  const [bd, setBd] = useState({ length_mm: '6000', E_MPa: '200000', I_mm4: '270000000', support_type: 'simply_supported', load_type: 'udl', load_value: '5' })
  const [bdR, setBdR] = useState(null); const [bdE, setBdE] = useState(null); const [bdRun, setBdRun] = useState(false)
  const runBeam = useCallback(async () => {
    setBdRun(true); setBdE(null); setBdR(null)
    try {
      const r = await callTool('arch_compute_beam_deflection', {
        length_mm: +bd.length_mm, E_MPa: +bd.E_MPa, I_mm4: +bd.I_mm4,
        support_type: bd.support_type, load_type: bd.load_type, load_value: +bd.load_value,
      })
      setBdR(r)
    } catch (e) { setBdE(e.message) } finally { setBdRun(false) }
  }, [bd])

  // ── arch_compute_slab_deflection ──
  const [sd, setSd] = useState({ length_a_mm: '5000', width_b_mm: '4000', thickness_h_mm: '200', udl_kPa: '5', edge_condition: 'simply_supported' })
  const [sdR, setSdR] = useState(null); const [sdE, setSdE] = useState(null); const [sdRun, setSdRun] = useState(false)
  const runSlab = useCallback(async () => {
    setSdRun(true); setSdE(null); setSdR(null)
    try {
      const r = await callTool('arch_compute_slab_deflection', {
        length_a_mm: +sd.length_a_mm, width_b_mm: +sd.width_b_mm,
        thickness_h_mm: +sd.thickness_h_mm, udl_kPa: +sd.udl_kPa,
        edge_condition: sd.edge_condition,
      })
      setSdR(r)
    } catch (e) { setSdE(e.message) } finally { setSdRun(false) }
  }, [sd])

  // ── arch_check_punching_shear ──
  const [ps, setPs] = useState({ column_size_mm: '400', slab_thickness_mm: '250', fc_MPa: '30', effective_depth_d_mm: '210', column_shape: 'square', V_applied_kN: '500' })
  const [psR, setPsR] = useState(null); const [psE, setPsE] = useState(null); const [psRun, setPsRun] = useState(false)
  const runPunch = useCallback(async () => {
    setPsRun(true); setPsE(null); setPsR(null)
    try {
      const r = await callTool('arch_check_punching_shear', {
        column_size_mm: +ps.column_size_mm, slab_thickness_mm: +ps.slab_thickness_mm,
        fc_MPa: +ps.fc_MPa, effective_depth_d_mm: +ps.effective_depth_d_mm,
        column_shape: ps.column_shape, V_applied_kN: +ps.V_applied_kN,
      })
      setPsR(r)
    } catch (e) { setPsE(e.message) } finally { setPsRun(false) }
  }, [ps])

  // ── arch_check_slab_on_grade ──
  const [sog, setSog] = useState({ slab_thickness_mm: '150', fc_MPa: '25', subgrade_modulus_k_MPa_per_m: '27.2', point_load_kN: '50', contact_radius_mm: '80', slab_long_dimension_m: '6' })
  const [sogR, setSogR] = useState(null); const [sogE, setSogE] = useState(null); const [sogRun, setSogRun] = useState(false)
  const runSog = useCallback(async () => {
    setSogRun(true); setSogE(null); setSogR(null)
    try {
      const r = await callTool('arch_check_slab_on_grade', {
        slab_thickness_mm: +sog.slab_thickness_mm, fc_MPa: +sog.fc_MPa,
        subgrade_modulus_k_MPa_per_m: +sog.subgrade_modulus_k_MPa_per_m,
        point_load_kN: +sog.point_load_kN, contact_radius_mm: +sog.contact_radius_mm,
        slab_long_dimension_m: +sog.slab_long_dimension_m,
      })
      setSogR(r)
    } catch (e) { setSogE(e.message) } finally { setSogRun(false) }
  }, [sog])

  return (
    <div>
      <ToolWidget title="Beam Deflection (Roark 9e §8 + AISC 3-23)" icon={Building2} color="#3b82f6" result={bdR} error={bdE} running={bdRun}>
        <NumRow label="Span length (mm)" value={bd.length_mm} onChange={v => setBd(p => ({ ...p, length_mm: v }))} disabled={bdRun} />
        <NumRow label="E modulus (MPa)" value={bd.E_MPa} onChange={v => setBd(p => ({ ...p, E_MPa: v }))} disabled={bdRun} />
        <NumRow label="I moment of area (mm⁴)" value={bd.I_mm4} onChange={v => setBd(p => ({ ...p, I_mm4: v }))} disabled={bdRun} />
        <SelRow label="Support type" value={bd.support_type} onChange={v => setBd(p => ({ ...p, support_type: v }))}
          options={['simply_supported', 'cantilever', 'fixed_fixed']} disabled={bdRun} />
        <SelRow label="Load type" value={bd.load_type} onChange={v => setBd(p => ({ ...p, load_type: v }))}
          options={['udl', 'point_center']} disabled={bdRun} />
        <NumRow label="Load value (N or N/mm)" value={bd.load_value} onChange={v => setBd(p => ({ ...p, load_value: v }))} disabled={bdRun} />
        <RunBtn onClick={runBeam} running={bdRun} />
      </ToolWidget>

      <ToolWidget title="Two-Way Slab Deflection (Timoshenko §44 / Roark 9e Table 11.4)" icon={Layers} color="#8b5cf6" result={sdR} error={sdE} running={sdRun}>
        <NumRow label="Length a (mm)" value={sd.length_a_mm} onChange={v => setSd(p => ({ ...p, length_a_mm: v }))} disabled={sdRun} />
        <NumRow label="Width b (mm)" value={sd.width_b_mm} onChange={v => setSd(p => ({ ...p, width_b_mm: v }))} disabled={sdRun} />
        <NumRow label="Thickness h (mm)" value={sd.thickness_h_mm} onChange={v => setSd(p => ({ ...p, thickness_h_mm: v }))} disabled={sdRun} />
        <NumRow label="UDL (kPa)" value={sd.udl_kPa} onChange={v => setSd(p => ({ ...p, udl_kPa: v }))} disabled={sdRun} />
        <SelRow label="Edge condition" value={sd.edge_condition} onChange={v => setSd(p => ({ ...p, edge_condition: v }))}
          options={['simply_supported', 'fixed_fixed']} disabled={sdRun} />
        <RunBtn onClick={runSlab} running={sdRun} />
      </ToolWidget>

      <ToolWidget title="Punching Shear (ACI 318-19 §22.6)" icon={Layers} color="#ef4444" result={psR} error={psE} running={psRun} passKey="adequate">
        <NumRow label="Column size (mm)" value={ps.column_size_mm} onChange={v => setPs(p => ({ ...p, column_size_mm: v }))} disabled={psRun} />
        <NumRow label="Slab thickness (mm)" value={ps.slab_thickness_mm} onChange={v => setPs(p => ({ ...p, slab_thickness_mm: v }))} disabled={psRun} />
        <NumRow label="f'c concrete (MPa)" value={ps.fc_MPa} onChange={v => setPs(p => ({ ...p, fc_MPa: v }))} disabled={psRun} />
        <NumRow label="Effective depth d (mm)" value={ps.effective_depth_d_mm} onChange={v => setPs(p => ({ ...p, effective_depth_d_mm: v }))} disabled={psRun} />
        <SelRow label="Column shape" value={ps.column_shape} onChange={v => setPs(p => ({ ...p, column_shape: v }))}
          options={['square', 'circular', 'rectangular']} disabled={psRun} />
        <NumRow label="Applied shear V (kN)" value={ps.V_applied_kN} onChange={v => setPs(p => ({ ...p, V_applied_kN: v }))} disabled={psRun} />
        <RunBtn onClick={runPunch} running={psRun} />
      </ToolWidget>

      <ToolWidget title="Slab on Grade (ACI 360R-10 + Westergaard 1948)" icon={Layers} color="#f59e0b" result={sogR} error={sogE} running={sogRun} passKey="adequate">
        <NumRow label="Slab thickness (mm)" value={sog.slab_thickness_mm} onChange={v => setSog(p => ({ ...p, slab_thickness_mm: v }))} disabled={sogRun} />
        <NumRow label="f'c concrete (MPa)" value={sog.fc_MPa} onChange={v => setSog(p => ({ ...p, fc_MPa: v }))} disabled={sogRun} />
        <NumRow label="Subgrade k (MPa/m)" value={sog.subgrade_modulus_k_MPa_per_m} onChange={v => setSog(p => ({ ...p, subgrade_modulus_k_MPa_per_m: v }))} disabled={sogRun} />
        <NumRow label="Point load P (kN)" value={sog.point_load_kN} onChange={v => setSog(p => ({ ...p, point_load_kN: v }))} disabled={sogRun} />
        <NumRow label="Contact radius (mm)" value={sog.contact_radius_mm} onChange={v => setSog(p => ({ ...p, contact_radius_mm: v }))} disabled={sogRun} />
        <NumRow label="Slab dimension (m)" value={sog.slab_long_dimension_m} onChange={v => setSog(p => ({ ...p, slab_long_dimension_m: v }))} disabled={sogRun} />
        <RunBtn onClick={runSog} running={sogRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 2: Lateral Loads (Wind)
// ---------------------------------------------------------------------------

function TabWindLoads() {
  // ── arch_compute_wind_load ──
  const [wl, setWl] = useState({ V_basic_mph: '115', exposure_category: 'C', mean_height_h_ft: '40', length_ft: '100', width_ft: '60' })
  const [wlR, setWlR] = useState(null); const [wlE, setWlE] = useState(null); const [wlRun, setWlRun] = useState(false)
  const runWind = useCallback(async () => {
    setWlRun(true); setWlE(null); setWlR(null)
    try {
      const r = await callTool('arch_compute_wind_load', {
        V_basic_mph: +wl.V_basic_mph, exposure_category: wl.exposure_category,
        mean_height_h_ft: +wl.mean_height_h_ft, length_ft: +wl.length_ft, width_ft: +wl.width_ft,
      })
      setWlR(r)
    } catch (e) { setWlE(e.message) } finally { setWlRun(false) }
  }, [wl])

  // ── arch_compute_wind_cc_pressure ──
  const [cc, setCc] = useState({ V_basic_mph: '115', exposure_category: 'C', mean_height_h_ft: '40', length_ft: '100', width_ft: '60', area_ft2: '100', zone: '1', component_type: 'wall' })
  const [ccR, setCcR] = useState(null); const [ccE, setCcE] = useState(null); const [ccRun, setCcRun] = useState(false)
  const runWcc = useCallback(async () => {
    setCcRun(true); setCcE(null); setCcR(null)
    try {
      const r = await callTool('arch_compute_wind_cc_pressure', {
        V_basic_mph: +cc.V_basic_mph, exposure_category: cc.exposure_category,
        mean_height_h_ft: +cc.mean_height_h_ft, length_ft: +cc.length_ft,
        width_ft: +cc.width_ft, area_ft2: +cc.area_ft2,
        zone: cc.zone, component_type: cc.component_type,
      })
      setCcR(r)
    } catch (e) { setCcE(e.message) } finally { setCcRun(false) }
  }, [cc])

  // ── arch_check_lateral_bracing ──
  const [lb, setLb] = useState({ section_label: 'W14x90', S_x_mm3: '2330000', Z_x_mm3: '2620000', r_y_mm: '65', J_mm4: '3710000', h_o_mm: '360', L_b_mm: '3000' })
  const [lbR, setLbR] = useState(null); const [lbE, setLbE] = useState(null); const [lbRun, setLbRun] = useState(false)
  const runLB = useCallback(async () => {
    setLbRun(true); setLbE(null); setLbR(null)
    try {
      const r = await callTool('arch_check_lateral_bracing', {
        section_label: lb.section_label, S_x_mm3: +lb.S_x_mm3, Z_x_mm3: +lb.Z_x_mm3,
        r_y_mm: +lb.r_y_mm, J_mm4: +lb.J_mm4, h_o_mm: +lb.h_o_mm, L_b_mm: +lb.L_b_mm,
      })
      setLbR(r)
    } catch (e) { setLbE(e.message) } finally { setLbRun(false) }
  }, [lb])

  // ── arch_check_diaphragm_shear ──
  const [dsh, setDsh] = useState({ length_along_load_mm: '12192', width_perp_to_load_mm: '9144', sheathing_type: 'plywood_15_32', nail_spacing_mm: '152', blocked: 'true', framing_species: 'DF_L', V_lateral_lbs: '20000' })
  const [dshR, setDshR] = useState(null); const [dshE, setDshE] = useState(null); const [dshRun, setDshRun] = useState(false)
  const runDsh = useCallback(async () => {
    setDshRun(true); setDshE(null); setDshR(null)
    try {
      const r = await callTool('arch_check_diaphragm_shear', {
        length_along_load_mm: +dsh.length_along_load_mm,
        width_perp_to_load_mm: +dsh.width_perp_to_load_mm,
        sheathing_type: dsh.sheathing_type,
        nail_spacing_mm: +dsh.nail_spacing_mm,
        blocked: dsh.blocked === 'true',
        framing_species: dsh.framing_species,
        V_lateral_lbs: +dsh.V_lateral_lbs,
      })
      setDshR(r)
    } catch (e) { setDshE(e.message) } finally { setDshRun(false) }
  }, [dsh])

  return (
    <div>
      <ToolWidget title="Wind Load MWFRS (ASCE 7-22 §26–27)" icon={Wind} color="#06b6d4" result={wlR} error={wlE} running={wlRun}>
        <NumRow label="Basic wind speed (mph)" value={wl.V_basic_mph} onChange={v => setWl(p => ({ ...p, V_basic_mph: v }))} disabled={wlRun} />
        <SelRow label="Exposure category" value={wl.exposure_category} onChange={v => setWl(p => ({ ...p, exposure_category: v }))}
          options={['B', 'C', 'D']} disabled={wlRun} />
        <NumRow label="Mean roof height (ft)" value={wl.mean_height_h_ft} onChange={v => setWl(p => ({ ...p, mean_height_h_ft: v }))} disabled={wlRun} />
        <NumRow label="Building length (ft)" value={wl.length_ft} onChange={v => setWl(p => ({ ...p, length_ft: v }))} disabled={wlRun} />
        <NumRow label="Building width (ft)" value={wl.width_ft} onChange={v => setWl(p => ({ ...p, width_ft: v }))} disabled={wlRun} />
        <RunBtn onClick={runWind} running={wlRun} />
        {wlR && !wlRun && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Pressures</div>
            <div style={{ ...s.mono, fontSize: 11 }}>
              Windward: {fmt(wlR.p_windward_psf)} psf &nbsp;|&nbsp; Leeward: {fmt(wlR.p_leeward_psf)} psf &nbsp;|&nbsp; Net: {fmt(wlR.total_drag_psf)} psf
            </div>
            <div style={{ color: '#6b7280', fontSize: 10, marginTop: 3 }}>{wlR.code_section}</div>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Wind C&C Pressure (ASCE 7-22 §30 Components & Cladding)" icon={Wind} color="#0ea5e9" result={ccR} error={ccE} running={ccRun}>
        <NumRow label="Basic wind speed (mph)" value={cc.V_basic_mph} onChange={v => setCc(p => ({ ...p, V_basic_mph: v }))} disabled={ccRun} />
        <SelRow label="Exposure category" value={cc.exposure_category} onChange={v => setCc(p => ({ ...p, exposure_category: v }))}
          options={['B', 'C', 'D']} disabled={ccRun} />
        <NumRow label="Mean roof height (ft)" value={cc.mean_height_h_ft} onChange={v => setCc(p => ({ ...p, mean_height_h_ft: v }))} disabled={ccRun} />
        <NumRow label="Building length (ft)" value={cc.length_ft} onChange={v => setCc(p => ({ ...p, length_ft: v }))} disabled={ccRun} />
        <NumRow label="Building width (ft)" value={cc.width_ft} onChange={v => setCc(p => ({ ...p, width_ft: v }))} disabled={ccRun} />
        <NumRow label="Component area (ft²)" value={cc.area_ft2} onChange={v => setCc(p => ({ ...p, area_ft2: v }))} disabled={ccRun} />
        <SelRow label="Pressure zone" value={cc.zone} onChange={v => setCc(p => ({ ...p, zone: v }))}
          options={['1', '2', '3', '4', '5']} disabled={ccRun} />
        <SelRow label="Component type" value={cc.component_type} onChange={v => setCc(p => ({ ...p, component_type: v }))}
          options={['wall', 'roof', 'parapet', 'overhang']} disabled={ccRun} />
        <RunBtn onClick={runWcc} running={ccRun} />
      </ToolWidget>

      <ToolWidget title="Lateral Bracing Check (AISC 360-22 §F2 LRFD + ASD)" icon={Building2} color="#a78bfa" result={lbR} error={lbE} running={lbRun} passKey="adequate">
        <div style={s.row}>
          <label style={s.label}>Section label</label>
          <input value={lb.section_label} onChange={e => setLb(p => ({ ...p, section_label: e.target.value }))} disabled={lbRun} style={s.input} />
        </div>
        <NumRow label="S_x (mm³)" value={lb.S_x_mm3} onChange={v => setLb(p => ({ ...p, S_x_mm3: v }))} disabled={lbRun} />
        <NumRow label="Z_x (mm³)" value={lb.Z_x_mm3} onChange={v => setLb(p => ({ ...p, Z_x_mm3: v }))} disabled={lbRun} />
        <NumRow label="r_y (mm)" value={lb.r_y_mm} onChange={v => setLb(p => ({ ...p, r_y_mm: v }))} disabled={lbRun} />
        <NumRow label="J torsional const (mm⁴)" value={lb.J_mm4} onChange={v => setLb(p => ({ ...p, J_mm4: v }))} disabled={lbRun} />
        <NumRow label="h_o flange distance (mm)" value={lb.h_o_mm} onChange={v => setLb(p => ({ ...p, h_o_mm: v }))} disabled={lbRun} />
        <NumRow label="L_b unbraced length (mm)" value={lb.L_b_mm} onChange={v => setLb(p => ({ ...p, L_b_mm: v }))} disabled={lbRun} />
        <RunBtn onClick={runLB} running={lbRun} />
      </ToolWidget>

      <ToolWidget title="Diaphragm Shear (SDPWS-2021 §4.2 + SDI DDM04)" icon={Layers} color="#f97316" result={dshR} error={dshE} running={dshRun} passKey="adequate">
        <NumRow label="Length along load (mm)" value={dsh.length_along_load_mm} onChange={v => setDsh(p => ({ ...p, length_along_load_mm: v }))} disabled={dshRun} />
        <NumRow label="Width perp to load (mm)" value={dsh.width_perp_to_load_mm} onChange={v => setDsh(p => ({ ...p, width_perp_to_load_mm: v }))} disabled={dshRun} />
        <SelRow label="Sheathing type" value={dsh.sheathing_type} onChange={v => setDsh(p => ({ ...p, sheathing_type: v }))}
          options={['plywood_15_32', 'plywood_19_32', 'osb_15_32', 'metal_deck_22ga', 'metal_deck_18ga']} disabled={dshRun} />
        <NumRow label="Nail spacing (mm)" value={dsh.nail_spacing_mm} onChange={v => setDsh(p => ({ ...p, nail_spacing_mm: v }))} disabled={dshRun} />
        <SelRow label="Blocked?" value={dsh.blocked} onChange={v => setDsh(p => ({ ...p, blocked: v }))}
          options={[{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]} disabled={dshRun} />
        <SelRow label="Framing species" value={dsh.framing_species} onChange={v => setDsh(p => ({ ...p, framing_species: v }))}
          options={['DF_L', 'SP', 'HF', 'SPF']} disabled={dshRun} />
        <NumRow label="Lateral shear V (lbs)" value={dsh.V_lateral_lbs} onChange={v => setDsh(p => ({ ...p, V_lateral_lbs: v }))} disabled={dshRun} />
        <RunBtn onClick={runDsh} running={dshRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 3: Connections
// ---------------------------------------------------------------------------

function TabConnections() {
  // ── arch_design_base_plate ──
  const [bp, setBp] = useState({ column_d_mm: '357', column_bf_mm: '268', axial_load_kN: '1000', fc_MPa: '30', support_width_B_mm: '600', support_length_L_mm: '600' })
  const [bpR, setBpR] = useState(null); const [bpE, setBpE] = useState(null); const [bpRun, setBpRun] = useState(false)
  const runBP = useCallback(async () => {
    setBpRun(true); setBpE(null); setBpR(null)
    try {
      const r = await callTool('arch_design_base_plate', {
        column_d_mm: +bp.column_d_mm, column_bf_mm: +bp.column_bf_mm,
        axial_load_kN: +bp.axial_load_kN, fc_MPa: +bp.fc_MPa,
        support_width_B_mm: +bp.support_width_B_mm, support_length_L_mm: +bp.support_length_L_mm,
      })
      setBpR(r)
    } catch (e) { setBpE(e.message) } finally { setBpRun(false) }
  }, [bp])

  // ── arch_check_bolt_shear ──
  const [bsh, setBsh] = useState({ grade: 'A325-N', diameter_in: '0.75', num_bolts: '4', plate_thickness_in: '0.375', end_distance_in: '1.25' })
  const [bshR, setBshR] = useState(null); const [bshE, setBshE] = useState(null); const [bshRun, setBshRun] = useState(false)
  const runBSh = useCallback(async () => {
    setBshRun(true); setBshE(null); setBshR(null)
    try {
      const r = await callTool('arch_check_bolt_shear', {
        grade: bsh.grade, diameter_in: +bsh.diameter_in,
        num_bolts: +bsh.num_bolts, plate_thickness_in: +bsh.plate_thickness_in,
        end_distance_in: +bsh.end_distance_in,
      })
      setBshR(r)
    } catch (e) { setBshE(e.message) } finally { setBshRun(false) }
  }, [bsh])

  // ── arch_check_anchor_pullout ──
  const [anc, setAnc] = useState({ bolt_diameter_mm: '16', embedment_depth_hef_mm: '200', edge_distance_min_mm: '300', anchor_spacing_min_mm: '200', fc_MPa: '25', fy_steel_MPa: '420', head_bearing_area_mm2: '400', N_factored_kN: '15' })
  const [ancR, setAncR] = useState(null); const [ancE, setAncE] = useState(null); const [ancRun, setAncRun] = useState(false)
  const runAnc = useCallback(async () => {
    setAncRun(true); setAncE(null); setAncR(null)
    try {
      const r = await callTool('arch_check_anchor_pullout', {
        bolt_diameter_mm: +anc.bolt_diameter_mm, embedment_depth_hef_mm: +anc.embedment_depth_hef_mm,
        edge_distance_min_mm: +anc.edge_distance_min_mm, anchor_spacing_min_mm: +anc.anchor_spacing_min_mm,
        fc_MPa: +anc.fc_MPa, fy_steel_MPa: +anc.fy_steel_MPa,
        head_bearing_area_mm2: +anc.head_bearing_area_mm2, N_factored_kN: +anc.N_factored_kN,
      })
      setAncR(r)
    } catch (e) { setAncE(e.message) } finally { setAncRun(false) }
  }, [anc])

  // ── arch_design_lintel ──
  const [ln, setLn] = useState({ opening_span_mm: '1800', wall_thickness_mm: '200', material: 'reinforced_masonry', lintel_depth_mm: '200', lintel_width_mm: '200', fc_or_fy_MPa: '20', dead_load_kN_per_m: '10', live_load_kN_per_m: '6', masonry_above_height_mm: '1200' })
  const [lnR, setLnR] = useState(null); const [lnE, setLnE] = useState(null); const [lnRun, setLnRun] = useState(false)
  const runLn = useCallback(async () => {
    setLnRun(true); setLnE(null); setLnR(null)
    try {
      const r = await callTool('arch_design_lintel', {
        opening_span_mm: +ln.opening_span_mm, wall_thickness_mm: +ln.wall_thickness_mm,
        material: ln.material, lintel_depth_mm: +ln.lintel_depth_mm,
        lintel_width_mm: +ln.lintel_width_mm, fc_or_fy_MPa: +ln.fc_or_fy_MPa,
        dead_load_kN_per_m: +ln.dead_load_kN_per_m, live_load_kN_per_m: +ln.live_load_kN_per_m,
        masonry_above_height_mm: +ln.masonry_above_height_mm,
      })
      setLnR(r)
    } catch (e) { setLnE(e.message) } finally { setLnRun(false) }
  }, [ln])

  // ── arch_check_opening_in_wall ──
  const [ow, setOw] = useState({ wall_height_m: '3', wall_thickness_m: '0.2', opening_width_m: '1.2', opening_height_m: '2.1', header_above_opening_height_m: '0.2', lintel_depth_m: '0.2', jamb_width_m: '0.4', material: 'masonry', f_prime_or_fy_MPa: '20', applied_axial_kN_per_m: '50', applied_lateral_kN_per_m2: '1.5' })
  const [owR, setOwR] = useState(null); const [owE, setOwE] = useState(null); const [owRun, setOwRun] = useState(false)
  const runOw = useCallback(async () => {
    setOwRun(true); setOwE(null); setOwR(null)
    try {
      const r = await callTool('arch_check_opening_in_wall', {
        wall_height_m: +ow.wall_height_m, wall_thickness_m: +ow.wall_thickness_m,
        opening_width_m: +ow.opening_width_m, opening_height_m: +ow.opening_height_m,
        header_above_opening_height_m: +ow.header_above_opening_height_m,
        lintel_depth_m: +ow.lintel_depth_m, jamb_width_m: +ow.jamb_width_m,
        material: ow.material, f_prime_or_fy_MPa: +ow.f_prime_or_fy_MPa,
        applied_axial_kN_per_m: +ow.applied_axial_kN_per_m,
        applied_lateral_kN_per_m2: +ow.applied_lateral_kN_per_m2,
      })
      setOwR(r)
    } catch (e) { setOwE(e.message) } finally { setOwRun(false) }
  }, [ow])

  return (
    <div>
      <ToolWidget title="Base Plate Design (AISC DG-1 §3.1 + AISC 360-22 §J8)" icon={Wrench} color="#f59e0b" result={bpR} error={bpE} running={bpRun} passKey="adequate">
        <NumRow label="Column depth d (mm)" value={bp.column_d_mm} onChange={v => setBp(p => ({ ...p, column_d_mm: v }))} disabled={bpRun} />
        <NumRow label="Column flange b_f (mm)" value={bp.column_bf_mm} onChange={v => setBp(p => ({ ...p, column_bf_mm: v }))} disabled={bpRun} />
        <NumRow label="Axial load P_u (kN)" value={bp.axial_load_kN} onChange={v => setBp(p => ({ ...p, axial_load_kN: v }))} disabled={bpRun} />
        <NumRow label="f'c concrete (MPa)" value={bp.fc_MPa} onChange={v => setBp(p => ({ ...p, fc_MPa: v }))} disabled={bpRun} />
        <NumRow label="Pedestal width B (mm)" value={bp.support_width_B_mm} onChange={v => setBp(p => ({ ...p, support_width_B_mm: v }))} disabled={bpRun} />
        <NumRow label="Pedestal length L (mm)" value={bp.support_length_L_mm} onChange={v => setBp(p => ({ ...p, support_length_L_mm: v }))} disabled={bpRun} />
        <RunBtn onClick={runBP} running={bpRun} />
      </ToolWidget>

      <ToolWidget title="Bolt Shear (AISC 360-22 §J3.6 LRFD)" icon={Wrench} color="#10b981" result={bshR} error={bshE} running={bshRun} passKey="adequate">
        <SelRow label="Bolt grade" value={bsh.grade} onChange={v => setBsh(p => ({ ...p, grade: v }))}
          options={['A325-N', 'A325-X', 'A490-N', 'A490-X', 'A307']} disabled={bshRun} />
        <NumRow label="Bolt diameter (in)" value={bsh.diameter_in} onChange={v => setBsh(p => ({ ...p, diameter_in: v }))} disabled={bshRun} />
        <NumRow label="Number of bolts" value={bsh.num_bolts} onChange={v => setBsh(p => ({ ...p, num_bolts: v }))} step="1" disabled={bshRun} />
        <NumRow label="Plate thickness (in)" value={bsh.plate_thickness_in} onChange={v => setBsh(p => ({ ...p, plate_thickness_in: v }))} disabled={bshRun} />
        <NumRow label="End distance (in)" value={bsh.end_distance_in} onChange={v => setBsh(p => ({ ...p, end_distance_in: v }))} disabled={bshRun} />
        <RunBtn onClick={runBSh} running={bshRun} />
      </ToolWidget>

      <ToolWidget title="Anchor Pullout (ACI 318-19 §17.6 + ACI 355.2)" icon={Wrench} color="#ef4444" result={ancR} error={ancE} running={ancRun} passKey="adequate">
        <NumRow label="Bolt diameter (mm)" value={anc.bolt_diameter_mm} onChange={v => setAnc(p => ({ ...p, bolt_diameter_mm: v }))} disabled={ancRun} />
        <NumRow label="Embedment depth hef (mm)" value={anc.embedment_depth_hef_mm} onChange={v => setAnc(p => ({ ...p, embedment_depth_hef_mm: v }))} disabled={ancRun} />
        <NumRow label="Min edge distance (mm)" value={anc.edge_distance_min_mm} onChange={v => setAnc(p => ({ ...p, edge_distance_min_mm: v }))} disabled={ancRun} />
        <NumRow label="Anchor spacing (mm)" value={anc.anchor_spacing_min_mm} onChange={v => setAnc(p => ({ ...p, anchor_spacing_min_mm: v }))} disabled={ancRun} />
        <NumRow label="f'c concrete (MPa)" value={anc.fc_MPa} onChange={v => setAnc(p => ({ ...p, fc_MPa: v }))} disabled={ancRun} />
        <NumRow label="f_y steel (MPa)" value={anc.fy_steel_MPa} onChange={v => setAnc(p => ({ ...p, fy_steel_MPa: v }))} disabled={ancRun} />
        <NumRow label="Head bearing area (mm²)" value={anc.head_bearing_area_mm2} onChange={v => setAnc(p => ({ ...p, head_bearing_area_mm2: v }))} disabled={ancRun} />
        <NumRow label="Factored tension N (kN)" value={anc.N_factored_kN} onChange={v => setAnc(p => ({ ...p, N_factored_kN: v }))} disabled={ancRun} />
        <RunBtn onClick={runAnc} running={ancRun} />
      </ToolWidget>

      <ToolWidget title="Lintel Design (TMS 402 / ACI 318 / AISC)" icon={Building2} color="#8b5cf6" result={lnR} error={lnE} running={lnRun} passKey="adequate">
        <NumRow label="Opening span (mm)" value={ln.opening_span_mm} onChange={v => setLn(p => ({ ...p, opening_span_mm: v }))} disabled={lnRun} />
        <NumRow label="Wall thickness (mm)" value={ln.wall_thickness_mm} onChange={v => setLn(p => ({ ...p, wall_thickness_mm: v }))} disabled={lnRun} />
        <SelRow label="Material" value={ln.material} onChange={v => setLn(p => ({ ...p, material: v }))}
          options={['reinforced_masonry', 'reinforced_concrete', 'steel']} disabled={lnRun} />
        <NumRow label="Lintel depth (mm)" value={ln.lintel_depth_mm} onChange={v => setLn(p => ({ ...p, lintel_depth_mm: v }))} disabled={lnRun} />
        <NumRow label="Lintel width (mm)" value={ln.lintel_width_mm} onChange={v => setLn(p => ({ ...p, lintel_width_mm: v }))} disabled={lnRun} />
        <NumRow label="f'c or f_y (MPa)" value={ln.fc_or_fy_MPa} onChange={v => setLn(p => ({ ...p, fc_or_fy_MPa: v }))} disabled={lnRun} />
        <NumRow label="Dead load (kN/m)" value={ln.dead_load_kN_per_m} onChange={v => setLn(p => ({ ...p, dead_load_kN_per_m: v }))} disabled={lnRun} />
        <NumRow label="Live load (kN/m)" value={ln.live_load_kN_per_m} onChange={v => setLn(p => ({ ...p, live_load_kN_per_m: v }))} disabled={lnRun} />
        <NumRow label="Masonry above (mm)" value={ln.masonry_above_height_mm} onChange={v => setLn(p => ({ ...p, masonry_above_height_mm: v }))} disabled={lnRun} />
        <RunBtn onClick={runLn} running={lnRun} />
      </ToolWidget>

      <ToolWidget title="Opening in Wall Check (TMS 402 / ACI 318)" icon={Building2} color="#0ea5e9" result={owR} error={owE} running={owRun} passKey="adequate">
        <NumRow label="Wall height (m)" value={ow.wall_height_m} onChange={v => setOw(p => ({ ...p, wall_height_m: v }))} disabled={owRun} />
        <NumRow label="Wall thickness (m)" value={ow.wall_thickness_m} onChange={v => setOw(p => ({ ...p, wall_thickness_m: v }))} disabled={owRun} />
        <NumRow label="Opening width (m)" value={ow.opening_width_m} onChange={v => setOw(p => ({ ...p, opening_width_m: v }))} disabled={owRun} />
        <NumRow label="Opening height (m)" value={ow.opening_height_m} onChange={v => setOw(p => ({ ...p, opening_height_m: v }))} disabled={owRun} />
        <NumRow label="Header height (m)" value={ow.header_above_opening_height_m} onChange={v => setOw(p => ({ ...p, header_above_opening_height_m: v }))} disabled={owRun} />
        <NumRow label="Lintel depth (m)" value={ow.lintel_depth_m} onChange={v => setOw(p => ({ ...p, lintel_depth_m: v }))} disabled={owRun} />
        <NumRow label="Jamb width (m)" value={ow.jamb_width_m} onChange={v => setOw(p => ({ ...p, jamb_width_m: v }))} disabled={owRun} />
        <SelRow label="Material" value={ow.material} onChange={v => setOw(p => ({ ...p, material: v }))}
          options={['masonry', 'concrete', 'wood_frame']} disabled={owRun} />
        <NumRow label="f'c or f_y (MPa)" value={ow.f_prime_or_fy_MPa} onChange={v => setOw(p => ({ ...p, f_prime_or_fy_MPa: v }))} disabled={owRun} />
        <NumRow label="Axial load (kN/m)" value={ow.applied_axial_kN_per_m} onChange={v => setOw(p => ({ ...p, applied_axial_kN_per_m: v }))} disabled={owRun} />
        <NumRow label="Lateral load (kN/m²)" value={ow.applied_lateral_kN_per_m2} onChange={v => setOw(p => ({ ...p, applied_lateral_kN_per_m2: v }))} disabled={owRun} />
        <RunBtn onClick={runOw} running={owRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 4: Walls & Footings
// ---------------------------------------------------------------------------

function TabWallsFootings() {
  // ── arch_compute_bearing_capacity ──
  const [bc, setBc] = useState({ length_B_m: '2', width_L_m: '2', depth_Df_m: '1', shape: 'square', cohesion_c_kPa: '0', friction_angle_phi_deg: '30', unit_weight_kN_m3: '18' })
  const [bcR, setBcR] = useState(null); const [bcE, setBcE] = useState(null); const [bcRun, setBcRun] = useState(false)
  const runBC = useCallback(async () => {
    setBcRun(true); setBcE(null); setBcR(null)
    try {
      const r = await callTool('arch_compute_bearing_capacity', {
        length_B_m: +bc.length_B_m, width_L_m: +bc.width_L_m, depth_Df_m: +bc.depth_Df_m,
        shape: bc.shape, cohesion_c_kPa: +bc.cohesion_c_kPa,
        friction_angle_phi_deg: +bc.friction_angle_phi_deg, unit_weight_kN_m3: +bc.unit_weight_kN_m3,
      })
      setBcR(r)
    } catch (e) { setBcE(e.message) } finally { setBcRun(false) }
  }, [bc])

  // ── arch_check_retaining_wall_stability ──
  const [rw, setRw] = useState({ wall_height_H_m: '4', stem_thickness_t_m: '0.4', base_width_B_m: '2.8', base_thickness_h_m: '0.5', heel_length_m: '1.8', toe_length_m: '0.6', soil_unit_weight_kN_m3: '18', friction_angle_phi_deg: '30', base_friction_delta_deg: '20', allowable_bearing_q_a_kPa: '150' })
  const [rwR, setRwR] = useState(null); const [rwE, setRwE] = useState(null); const [rwRun, setRwRun] = useState(false)
  const runRW = useCallback(async () => {
    setRwRun(true); setRwE(null); setRwR(null)
    try {
      const r = await callTool('arch_check_retaining_wall_stability', {
        wall_height_H_m: +rw.wall_height_H_m, stem_thickness_t_m: +rw.stem_thickness_t_m,
        base_width_B_m: +rw.base_width_B_m, base_thickness_h_m: +rw.base_thickness_h_m,
        heel_length_m: +rw.heel_length_m, toe_length_m: +rw.toe_length_m,
        soil_unit_weight_kN_m3: +rw.soil_unit_weight_kN_m3,
        friction_angle_phi_deg: +rw.friction_angle_phi_deg,
        base_friction_delta_deg: +rw.base_friction_delta_deg,
        allowable_bearing_q_a_kPa: +rw.allowable_bearing_q_a_kPa,
      })
      setRwR(r)
    } catch (e) { setRwE(e.message) } finally { setRwRun(false) }
  }, [rw])

  // ── arch_check_pier_axial ──
  const [pier, setPier] = useState({ pier_width_mm: '400', pier_thickness_mm: '200', height_h_mm: '2400', material: 'reinforced_concrete', f_prime_MPa: '25', end_conditions: 'fixed_fixed', P_factored_kN: '200' })
  const [pierR, setPierR] = useState(null); const [pierE, setPierE] = useState(null); const [pierRun, setPierRun] = useState(false)
  const runPier = useCallback(async () => {
    setPierRun(true); setPierE(null); setPierR(null)
    try {
      const r = await callTool('arch_check_pier_axial', {
        pier_width_mm: +pier.pier_width_mm, pier_thickness_mm: +pier.pier_thickness_mm,
        height_h_mm: +pier.height_h_mm, material: pier.material,
        f_prime_MPa: +pier.f_prime_MPa, end_conditions: pier.end_conditions,
        P_factored_kN: +pier.P_factored_kN,
      })
      setPierR(r)
    } catch (e) { setPierE(e.message) } finally { setPierRun(false) }
  }, [pier])

  // ── arch_check_bearing_wall_axial ──
  const [bwa, setBwa] = useState({ wall_thickness_t_mm: '200', wall_height_h_mm: '3000', wall_length_lw_m: '5', material: 'reinforced_concrete', f_prime_MPa: '25', P_factored_kN_per_m: '150' })
  const [bwaR, setBwaR] = useState(null); const [bwaE, setBwaE] = useState(null); const [bwaRun, setBwaRun] = useState(false)
  const runBWA = useCallback(async () => {
    setBwaRun(true); setBwaE(null); setBwaR(null)
    try {
      const r = await callTool('arch_check_bearing_wall_axial', {
        wall_thickness_t_mm: +bwa.wall_thickness_t_mm, wall_height_h_mm: +bwa.wall_height_h_mm,
        wall_length_lw_m: +bwa.wall_length_lw_m, material: bwa.material,
        f_prime_MPa: +bwa.f_prime_MPa, P_factored_kN_per_m: +bwa.P_factored_kN_per_m,
      })
      setBwaR(r)
    } catch (e) { setBwaE(e.message) } finally { setBwaRun(false) }
  }, [bwa])

  // ── arch_check_shear_wall_oop ──
  const [sw, setSw] = useState({ wall_thickness_t_mm: '200', wall_height_h_mm: '3000', wall_length_lw_mm: '5000', fc_MPa: '25', fy_MPa: '420', As_each_face_mm2_per_m: '300', axial_load_Pu_kN_per_m: '100', oop_moment_Mu_kNm_per_m: '30' })
  const [swR, setSwR] = useState(null); const [swE, setSwE] = useState(null); const [swRun, setSwRun] = useState(false)
  const runSW = useCallback(async () => {
    setSwRun(true); setSwE(null); setSwR(null)
    try {
      const r = await callTool('arch_check_shear_wall_oop', {
        wall_thickness_t_mm: +sw.wall_thickness_t_mm, wall_height_h_mm: +sw.wall_height_h_mm,
        wall_length_lw_mm: +sw.wall_length_lw_mm, fc_MPa: +sw.fc_MPa,
        fy_MPa: +sw.fy_MPa, As_each_face_mm2_per_m: +sw.As_each_face_mm2_per_m,
        axial_load_Pu_kN_per_m: +sw.axial_load_Pu_kN_per_m,
        oop_moment_Mu_kNm_per_m: +sw.oop_moment_Mu_kNm_per_m,
      })
      setSwR(r)
    } catch (e) { setSwE(e.message) } finally { setSwRun(false) }
  }, [sw])

  return (
    <div>
      <ToolWidget title="Bearing Capacity (Meyerhof 1963 / Bowles 5e §4)" icon={Layers} color="#16a34a" result={bcR} error={bcE} running={bcRun}>
        <NumRow label="Footing width B (m)" value={bc.length_B_m} onChange={v => setBc(p => ({ ...p, length_B_m: v }))} disabled={bcRun} />
        <NumRow label="Footing length L (m)" value={bc.width_L_m} onChange={v => setBc(p => ({ ...p, width_L_m: v }))} disabled={bcRun} />
        <NumRow label="Embedment depth Df (m)" value={bc.depth_Df_m} onChange={v => setBc(p => ({ ...p, depth_Df_m: v }))} disabled={bcRun} />
        <SelRow label="Footing shape" value={bc.shape} onChange={v => setBc(p => ({ ...p, shape: v }))}
          options={['square', 'strip', 'circular', 'rectangular']} disabled={bcRun} />
        <NumRow label="Cohesion c (kPa)" value={bc.cohesion_c_kPa} onChange={v => setBc(p => ({ ...p, cohesion_c_kPa: v }))} disabled={bcRun} />
        <NumRow label="Friction angle φ (°)" value={bc.friction_angle_phi_deg} onChange={v => setBc(p => ({ ...p, friction_angle_phi_deg: v }))} disabled={bcRun} />
        <NumRow label="Unit weight γ (kN/m³)" value={bc.unit_weight_kN_m3} onChange={v => setBc(p => ({ ...p, unit_weight_kN_m3: v }))} disabled={bcRun} />
        <RunBtn onClick={runBC} running={bcRun} />
        {bcR && !bcRun && (
          <div style={s.resultBox}>
            <div style={{ ...s.mono, fontSize: 11 }}>
              q_ult: {fmt(bcR.q_ult_kPa)} kPa &nbsp;|&nbsp; q_allow: {fmt(bcR.q_allow_kPa)} kPa &nbsp;|&nbsp; FS: {fmt(bcR.FS, 1)}
            </div>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Retaining Wall Stability (ASCE 7 + Bowles 5e §11)" icon={Building2} color="#dc2626" result={rwR} error={rwE} running={rwRun} passKey="stable">
        <NumRow label="Wall height H (m)" value={rw.wall_height_H_m} onChange={v => setRw(p => ({ ...p, wall_height_H_m: v }))} disabled={rwRun} />
        <NumRow label="Stem thickness (m)" value={rw.stem_thickness_t_m} onChange={v => setRw(p => ({ ...p, stem_thickness_t_m: v }))} disabled={rwRun} />
        <NumRow label="Base width B (m)" value={rw.base_width_B_m} onChange={v => setRw(p => ({ ...p, base_width_B_m: v }))} disabled={rwRun} />
        <NumRow label="Base thickness (m)" value={rw.base_thickness_h_m} onChange={v => setRw(p => ({ ...p, base_thickness_h_m: v }))} disabled={rwRun} />
        <NumRow label="Heel length (m)" value={rw.heel_length_m} onChange={v => setRw(p => ({ ...p, heel_length_m: v }))} disabled={rwRun} />
        <NumRow label="Toe length (m)" value={rw.toe_length_m} onChange={v => setRw(p => ({ ...p, toe_length_m: v }))} disabled={rwRun} />
        <NumRow label="Soil γ (kN/m³)" value={rw.soil_unit_weight_kN_m3} onChange={v => setRw(p => ({ ...p, soil_unit_weight_kN_m3: v }))} disabled={rwRun} />
        <NumRow label="Friction angle φ (°)" value={rw.friction_angle_phi_deg} onChange={v => setRw(p => ({ ...p, friction_angle_phi_deg: v }))} disabled={rwRun} />
        <NumRow label="Base friction δ (°)" value={rw.base_friction_delta_deg} onChange={v => setRw(p => ({ ...p, base_friction_delta_deg: v }))} disabled={rwRun} />
        <NumRow label="Allowable bearing (kPa)" value={rw.allowable_bearing_q_a_kPa} onChange={v => setRw(p => ({ ...p, allowable_bearing_q_a_kPa: v }))} disabled={rwRun} />
        <RunBtn onClick={runRW} running={rwRun} />
      </ToolWidget>

      <ToolWidget title="Pier Axial Capacity (TMS 402-22 §8.3 / ACI 318-19 §22.4)" icon={Building2} color="#7c3aed" result={pierR} error={pierE} running={pierRun} passKey="adequate">
        <NumRow label="Pier width (mm)" value={pier.pier_width_mm} onChange={v => setPier(p => ({ ...p, pier_width_mm: v }))} disabled={pierRun} />
        <NumRow label="Pier thickness (mm)" value={pier.pier_thickness_mm} onChange={v => setPier(p => ({ ...p, pier_thickness_mm: v }))} disabled={pierRun} />
        <NumRow label="Clear height (mm)" value={pier.height_h_mm} onChange={v => setPier(p => ({ ...p, height_h_mm: v }))} disabled={pierRun} />
        <SelRow label="Material" value={pier.material} onChange={v => setPier(p => ({ ...p, material: v }))}
          options={['clay_masonry', 'concrete_masonry', 'reinforced_concrete']} disabled={pierRun} />
        <NumRow label="f' or f'c (MPa)" value={pier.f_prime_MPa} onChange={v => setPier(p => ({ ...p, f_prime_MPa: v }))} disabled={pierRun} />
        <SelRow label="End conditions" value={pier.end_conditions} onChange={v => setPier(p => ({ ...p, end_conditions: v }))}
          options={['fixed_fixed', 'pin_pin', 'fixed_pin', 'cantilever']} disabled={pierRun} />
        <NumRow label="Factored axial P (kN)" value={pier.P_factored_kN} onChange={v => setPier(p => ({ ...p, P_factored_kN: v }))} disabled={pierRun} />
        <RunBtn onClick={runPier} running={pierRun} />
      </ToolWidget>

      <ToolWidget title="Bearing Wall Axial (ACI §11.5 / TMS 402-22 §8.3)" icon={Building2} color="#0369a1" result={bwaR} error={bwaE} running={bwaRun} passKey="adequate">
        <NumRow label="Thickness t (mm)" value={bwa.wall_thickness_t_mm} onChange={v => setBwa(p => ({ ...p, wall_thickness_t_mm: v }))} disabled={bwaRun} />
        <NumRow label="Height h (mm)" value={bwa.wall_height_h_mm} onChange={v => setBwa(p => ({ ...p, wall_height_h_mm: v }))} disabled={bwaRun} />
        <NumRow label="Wall length lw (m)" value={bwa.wall_length_lw_m} onChange={v => setBwa(p => ({ ...p, wall_length_lw_m: v }))} disabled={bwaRun} />
        <SelRow label="Material" value={bwa.material} onChange={v => setBwa(p => ({ ...p, material: v }))}
          options={['concrete', 'reinforced_concrete', 'clay_masonry', 'concrete_masonry']} disabled={bwaRun} />
        <NumRow label="f' (MPa)" value={bwa.f_prime_MPa} onChange={v => setBwa(p => ({ ...p, f_prime_MPa: v }))} disabled={bwaRun} />
        <NumRow label="Axial P_u (kN/m)" value={bwa.P_factored_kN_per_m} onChange={v => setBwa(p => ({ ...p, P_factored_kN_per_m: v }))} disabled={bwaRun} />
        <RunBtn onClick={runBWA} running={bwaRun} />
      </ToolWidget>

      <ToolWidget title="Shear Wall Out-of-Plane (ACI 318-19 §11.8)" icon={Building2} color="#b45309" result={swR} error={swE} running={swRun} passKey="adequate">
        <NumRow label="Thickness t (mm)" value={sw.wall_thickness_t_mm} onChange={v => setSw(p => ({ ...p, wall_thickness_t_mm: v }))} disabled={swRun} />
        <NumRow label="Height h (mm)" value={sw.wall_height_h_mm} onChange={v => setSw(p => ({ ...p, wall_height_h_mm: v }))} disabled={swRun} />
        <NumRow label="Length lw (mm)" value={sw.wall_length_lw_mm} onChange={v => setSw(p => ({ ...p, wall_length_lw_mm: v }))} disabled={swRun} />
        <NumRow label="f'c (MPa)" value={sw.fc_MPa} onChange={v => setSw(p => ({ ...p, fc_MPa: v }))} disabled={swRun} />
        <NumRow label="f_y steel (MPa)" value={sw.fy_MPa} onChange={v => setSw(p => ({ ...p, fy_MPa: v }))} disabled={swRun} />
        <NumRow label="As each face (mm²/m)" value={sw.As_each_face_mm2_per_m} onChange={v => setSw(p => ({ ...p, As_each_face_mm2_per_m: v }))} disabled={swRun} />
        <NumRow label="P_u axial (kN/m)" value={sw.axial_load_Pu_kN_per_m} onChange={v => setSw(p => ({ ...p, axial_load_Pu_kN_per_m: v }))} disabled={swRun} />
        <NumRow label="M_u OOP (kNm/m)" value={sw.oop_moment_Mu_kNm_per_m} onChange={v => setSw(p => ({ ...p, oop_moment_Mu_kNm_per_m: v }))} disabled={swRun} />
        <RunBtn onClick={runSW} running={swRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 5: Stairs & Misc
// ---------------------------------------------------------------------------

function TabStairsMisc() {
  // ── arch_design_stair_stringer ──
  const [ss, setSs] = useState({ num_treads: '8', riser_height_in: '7', tread_depth_in: '11', stair_width_in: '48', material: 'sawn-DF-No2' })
  const [ssR, setSsR] = useState(null); const [ssE, setSsE] = useState(null); const [ssRun, setSsRun] = useState(false)
  const runSS = useCallback(async () => {
    setSsRun(true); setSsE(null); setSsR(null)
    try {
      const r = await callTool('arch_design_stair_stringer', {
        num_treads: +ss.num_treads, riser_height_in: +ss.riser_height_in,
        tread_depth_in: +ss.tread_depth_in, stair_width_in: +ss.stair_width_in,
        material: ss.material,
      })
      setSsR(r)
    } catch (e) { setSsE(e.message) } finally { setSsRun(false) }
  }, [ss])

  // ── arch_check_bearing_capacity via footing ── (repeat with different defaults)
  // Instead wire arch_check_column_load as the 2nd misc tool
  const [cl, setCl] = useState({ column_type: 'steel_wide_flange', P_demand_kN: '800' })
  const [clR, setClR] = useState(null); const [clE, setClE] = useState(null); const [clRun, setClRun] = useState(false)
  const runCL = useCallback(async () => {
    setClRun(true); setClE(null); setClR(null)
    try {
      const r = await callTool('arch_check_column_load', {
        column_type: cl.column_type, P_demand_kN: +cl.P_demand_kN,
      })
      setClR(r)
    } catch (e) { setClE(e.message) } finally { setClRun(false) }
  }, [cl])

  return (
    <div>
      <ToolWidget title="Stair Stringer (IBC 2021 §1011 + AWC NDS-2018 / AISC 360-22)" icon={Construction} color="#f97316" result={ssR} error={ssE} running={ssRun} passKey="ok">
        <NumRow label="Number of treads" value={ss.num_treads} onChange={v => setSs(p => ({ ...p, num_treads: v }))} step="1" disabled={ssRun} />
        <NumRow label="Riser height (in)" value={ss.riser_height_in} onChange={v => setSs(p => ({ ...p, riser_height_in: v }))} disabled={ssRun} />
        <NumRow label="Tread depth (in)" value={ss.tread_depth_in} onChange={v => setSs(p => ({ ...p, tread_depth_in: v }))} disabled={ssRun} />
        <NumRow label="Stair width (in)" value={ss.stair_width_in} onChange={v => setSs(p => ({ ...p, stair_width_in: v }))} disabled={ssRun} />
        <SelRow label="Material" value={ss.material} onChange={v => setSs(p => ({ ...p, material: v }))}
          options={[
            { value: 'sawn-DF-No2', label: 'Sawn DF-Larch No.2' },
            { value: 'sawn-SP-No1', label: 'Sawn S.Pine No.1' },
            { value: 'steel-C10x15.3', label: 'Steel C10×15.3 (A36)' },
            { value: 'steel-HSS6x4x1/4', label: 'Steel HSS6×4×1/4 (A500 GrB)' },
          ]} disabled={ssRun} />
        <RunBtn onClick={runSS} running={ssRun} />
        {ssR && !ssRun && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
              <span style={{ color: '#9ca3af' }}>IBC geometry:</span>
              <StatusChip ok={ssR.ibc_geometry_ok} />
              <span style={{ color: '#9ca3af', marginLeft: 8 }}>Bending:</span>
              <StatusChip ok={ssR.bending_ok} />
              <span style={{ color: '#9ca3af', marginLeft: 8 }}>Deflection:</span>
              <StatusChip ok={ssR.deflection_ok} />
            </div>
            <ResultTable data={ssR} skip={['honest_caveat', 'ibc_geometry_ok', 'bending_ok', 'deflection_ok', 'ok', 'status']} />
            {ssR.ibc_fail_reason && (
              <div style={{ color: '#fca5a5', fontSize: 10, marginTop: 3 }}>{ssR.ibc_fail_reason}</div>
            )}
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Column Load Check (AISC 360-22 §E3 / ACI 318-19 §22.4)" icon={Building2} color="#3b82f6" result={clR} error={clE} running={clRun} passKey="adequate">
        <div style={s.row}>
          <label style={s.label}>Column type</label>
          <input value={cl.column_type} onChange={e => setCl(p => ({ ...p, column_type: e.target.value }))} disabled={clRun} style={s.input} />
        </div>
        <NumRow label="P demand (kN)" value={cl.P_demand_kN} onChange={v => setCl(p => ({ ...p, P_demand_kN: v }))} disabled={clRun} />
        <RunBtn onClick={runCL} running={clRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'beam',        label: 'Beam & Slab',         icon: Building2 },
  { id: 'wind',        label: 'Lateral Loads (Wind)', icon: Wind },
  { id: 'connections', label: 'Connections',          icon: Wrench },
  { id: 'walls',       label: 'Walls & Footings',     icon: Layers },
  { id: 'stairs',      label: 'Stairs & Misc',        icon: Construction },
]

export default function StructuralPanel() {
  const [tab, setTab] = useState('beam')

  return (
    <div style={s.root} data-testid="structural-panel">
      <div style={s.header}>
        <Building2 size={16} style={{ color: '#60a5fa' }} />
        <span style={s.title}>Structural Engineering</span>
        <span style={s.subtitle}>24 arch_* tools — ASCE 7-22, ACI 318-19, AISC 360-22, TMS 402-22</span>
      </div>

      <div style={s.tabs}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{ ...s.tab, ...(tab === t.id ? s.tabActive : {}) }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'beam'        && <TabBeamSlab />}
      {tab === 'wind'        && <TabWindLoads />}
      {tab === 'connections' && <TabConnections />}
      {tab === 'walls'       && <TabWallsFootings />}
      {tab === 'stairs'      && <TabStairsMisc />}
    </div>
  )
}
