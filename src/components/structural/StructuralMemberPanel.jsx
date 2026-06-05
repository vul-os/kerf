// StructuralMemberPanel.jsx — AISC 360-22 + ACI 318-19 Member Design Panel
//
// Wires four AISC 360-22 LLM backend tools (aisc_compression, aisc_flexure,
// aisc_combined, aisc_member_check) and two ACI 318-19 tools (structural_rc_beam,
// structural_rebar) into a tabbed results UI.
//
// Tabs:
//   Steel Member  — Ch E compression + Ch F flexure + Ch H combined (H1-1a/b)
//   RC Beam       — ACI 318-19 singly-reinforced beam design (As, ρ, limits)
//   Rebar         — ACI 318-19 §25 development + lap-splice lengths
//
// All tools dispatch POST /api/tools/call with { tool: "<name>", args: {...} }.
// Units shown are US customary (kips, inches, ksi, kip-ft) per AISC 360-22.
//
// Props: none — standalone panel.

import { useState, useCallback } from 'react'
import {
  Cpu, Layers, Ruler, AlertTriangle, CheckCircle,
  Loader2, Play, ChevronDown, ChevronUp, TrendingDown,
} from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------

const s = {
  root:          { background: '#111827', padding: '12px', fontSize: 12, color: '#e5e7eb', minHeight: 200 },
  header:        { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 },
  title:         { fontWeight: 600, fontSize: 14, color: '#f9fafb' },
  subtitle:      { color: '#6b7280', fontSize: 11, marginLeft: 4 },
  tabs:          { display: 'flex', gap: 2, marginBottom: 10, flexWrap: 'wrap' },
  tab:           { padding: '4px 10px', borderRadius: 4, border: '1px solid #374151', background: '#1f2937', color: '#9ca3af', cursor: 'pointer', fontSize: 11 },
  tabActive:     { background: '#1d4ed8', borderColor: '#3b82f6', color: '#fff' },
  section:       { background: '#1f2937', borderRadius: 6, padding: '10px', marginBottom: 8 },
  sectionTitle:  { display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600, marginBottom: 8, color: '#d1d5db', fontSize: 11 },
  row:           { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 },
  label:         { color: '#9ca3af', width: 180, flexShrink: 0, fontSize: 11 },
  input:         { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12, minWidth: 0 },
  select:        { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12 },
  button:        { display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 5, border: 'none', color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 500 },
  buttonDisabled:{ opacity: 0.5, cursor: 'not-allowed' },
  errorBox:      { display: 'flex', alignItems: 'flex-start', gap: 6, background: '#450a0a', borderRadius: 5, padding: '8px', color: '#fca5a5', marginTop: 8 },
  infoBox:       { display: 'flex', alignItems: 'center', gap: 6, background: '#1e3a5f', borderRadius: 5, padding: '8px', color: '#93c5fd', marginTop: 8 },
  resultBox:     { background: '#0f172a', borderRadius: 4, padding: '8px', marginTop: 6, fontFamily: 'monospace', fontSize: 11 },
  table:         { width: '100%', borderCollapse: 'collapse', marginTop: 4 },
  td:            { padding: '3px 6px', borderBottom: '1px solid #1f2937' },
  mono:          { fontFamily: 'monospace' },
  subhead:       { color: '#60a5fa', fontWeight: 600, marginBottom: 4, fontSize: 11 },
  divider:       { borderTop: '1px solid #374151', margin: '8px 0' },
  passChip:      { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700, background: '#064e3b', color: '#34d399' },
  failChip:      { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700, background: '#450a0a', color: '#f87171' },
  warnChip:      { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700, background: '#451a03', color: '#fb923c' },
  interactionBar:{ height: 8, borderRadius: 4, background: '#374151', overflow: 'hidden', marginTop: 4 },
  interactionFill:{ height: '100%', borderRadius: 4, transition: 'width 0.3s' },
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

function StatusChip({ ok, label }) {
  if (ok == null) return null
  return ok
    ? <span style={s.passChip}>{label || 'PASS'}</span>
    : <span style={s.failChip}>{label || 'FAIL'}</span>
}

function InteractionRatio({ ratio }) {
  if (ratio == null) return null
  const pct = Math.min(ratio * 100, 100)
  const color = ratio <= 0.85 ? '#22c55e' : ratio <= 1.0 ? '#f59e0b' : '#ef4444'
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#9ca3af', marginBottom: 2 }}>
        <span>H1 interaction ratio</span>
        <span style={{ color, fontWeight: 700 }}>{ratio.toFixed(3)}</span>
      </div>
      <div style={s.interactionBar}>
        <div style={{ ...s.interactionFill, width: `${pct}%`, background: color }} />
      </div>
      {ratio <= 1.0
        ? <div style={{ color: '#34d399', fontSize: 10, marginTop: 2 }}>Adequate (ratio ≤ 1.0) — AISC 360-22 §H1</div>
        : <div style={{ color: '#f87171', fontSize: 10, marginTop: 2 }}>Overstressed (ratio &gt; 1.0) — member inadequate</div>
      }
    </div>
  )
}

function ResultTable({ data, skip = [], highlight = [] }) {
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
            <td style={{ ...s.td, ...s.mono, color: highlight.includes(k) ? '#fbbf24' : '#f9fafb' }}>
              {fmt(v)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ToolWidget({ title, icon: Icon, color = '#2563eb', children, result, error, running, passKey }) {
  const [open, setOpen] = useState(true)
  const ok = result && passKey != null
    ? (passKey === '__ok__' ? Boolean(result.ok) : Boolean(result[passKey]))
    : undefined

  return (
    <div style={{ ...s.section, borderLeft: `3px solid ${color}` }}>
      <div
        style={{ ...s.sectionTitle, justifyContent: 'space-between', cursor: 'pointer' }}
        onClick={() => setOpen(o => !o)}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {Icon && <Icon size={12} style={{ color }} />}
          {title}
          {result && passKey != null && !running && (
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
              {children.__result ? null : null}
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

function NumRow({ label, value, onChange, step = 'any', disabled, unit }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}{unit ? <span style={{ color: '#6b7280', marginLeft: 3 }}>({unit})</span> : null}</label>
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
// Tab 1 — Steel Member Design (AISC 360-22 Ch E + F + H)
// ---------------------------------------------------------------------------

const W_SHAPES = [
  'W8X31','W10X33','W12X40','W12X50','W14X48','W14X82','W14X90',
  'W16X36','W16X50','W18X35','W18X50','W18X76','W21X50','W21X68',
  'W24X55','W24X76','W27X84','W30X90','W33X130','W36X135',
]
const HSS_RECT = [
  'HSS4X4X1/4','HSS4X4X3/8','HSS5X5X1/4','HSS5X5X5/16',
  'HSS6X4X3/16','HSS6X6X1/4','HSS6X6X3/8','HSS8X6X5/16',
  'HSS8X8X3/8','HSS10X8X3/8',
]
const HSS_ROUND = [
  'HSS3.500X0.216','HSS4.000X0.237','HSS4.500X0.237','HSS5.000X0.250','HSS6.000X0.250',
]
const PIPES = ['PIPE2STD','PIPE3STD','PIPE4STD','PIPE4XS','PIPE6STD']
const CHANNELS = ['C6X10.5','C8X11.5','C10X20','C12X20.7','C15X33.9']
const ANGLES = ['L3X3X1/4','L3X3X3/8','L4X4X1/4','L4X4X1/2','L6X4X3/8']

function sectionOptions(type) {
  switch (type) {
    case 'W': return W_SHAPES
    case 'C': return CHANNELS
    case 'HSS_rect': return HSS_RECT
    case 'HSS_round': return HSS_ROUND
    case 'Pipe': return PIPES
    case 'Angle': return ANGLES
    default: return []
  }
}

function TabSteelMember() {
  // Full member check (E + F + H)
  const [mc, setMc] = useState({
    section_type: 'W', designation: 'W14X90',
    Lc_ft: '12', Lcy_ft: '12', Lb_ft: '10',
    Pu: '200', Mux_kip_ft: '80', Muy_kip_ft: '0',
    Cb: '1.0', Fy: '50',
  })
  const [mcR, setMcR] = useState(null)
  const [mcE, setMcE] = useState(null)
  const [mcRun, setMcRun] = useState(false)

  // Compression only (Chapter E)
  const [comp, setComp] = useState({
    section_type: 'W', designation: 'W14X90',
    Lc_ft: '12', Lcy_ft: '0', Fy: '50',
  })
  const [compR, setCompR] = useState(null)
  const [compE, setCompE] = useState(null)
  const [compRun, setCompRun] = useState(false)

  // Flexure only (Chapter F)
  const [flex, setFlex] = useState({
    section_type: 'W', designation: 'W18X50',
    Lb_ft: '10', Cb: '1.0', Fy: '50', axis: 'x',
  })
  const [flexR, setFlexR] = useState(null)
  const [flexE, setFlexE] = useState(null)
  const [flexRun, setFlexRun] = useState(false)

  const runMC = useCallback(async () => {
    setMcRun(true); setMcE(null); setMcR(null)
    try {
      const r = await callTool('aisc_member_check', {
        designation: mc.designation, section_type: mc.section_type,
        Lc_ft: +mc.Lc_ft, Lcy_ft: +mc.Lcy_ft, Lb_ft: +mc.Lb_ft,
        Pu: +mc.Pu, Mux_kip_ft: +mc.Mux_kip_ft, Muy_kip_ft: +mc.Muy_kip_ft,
        Cb: +mc.Cb, Fy: +mc.Fy,
      })
      setMcR(r)
    } catch (e) { setMcE(e.message) } finally { setMcRun(false) }
  }, [mc])

  const runComp = useCallback(async () => {
    setCompRun(true); setCompE(null); setCompR(null)
    try {
      const r = await callTool('aisc_compression', {
        designation: comp.designation, section_type: comp.section_type,
        Lc_ft: +comp.Lc_ft, Lcy_ft: +comp.Lcy_ft, Fy: +comp.Fy,
      })
      setCompR(r)
    } catch (e) { setCompE(e.message) } finally { setCompRun(false) }
  }, [comp])

  const runFlex = useCallback(async () => {
    setFlexRun(true); setFlexE(null); setFlexR(null)
    try {
      const r = await callTool('aisc_flexure', {
        designation: flex.designation, section_type: flex.section_type,
        Lb_ft: +flex.Lb_ft, Cb: +flex.Cb, Fy: +flex.Fy, axis: flex.axis,
      })
      setFlexR(r)
    } catch (e) { setFlexE(e.message) } finally { setFlexRun(false) }
  }, [flex])

  const updateMcType = v => setMc(p => ({ ...p, section_type: v, designation: sectionOptions(v)[0] }))
  const updateCompType = v => setComp(p => ({ ...p, section_type: v, designation: sectionOptions(v)[0] }))
  const updateFlexType = v => setFlex(p => ({ ...p, section_type: v, designation: sectionOptions(v)[0] }))

  return (
    <div>
      {/* ── Full Member Check: Chapters E + F + H ── */}
      <div style={{ ...s.section, borderLeft: '3px solid #3b82f6' }}>
        <div style={s.sectionTitle}>
          <Cpu size={12} style={{ color: '#3b82f6' }} />
          Full Member Check — AISC 360-22 Ch E + F + H (H1-1a/b interaction)
          {mcR && !mcRun && (
            <span style={{ marginLeft: 6 }}>
              <StatusChip ok={mcR.interaction_ok} label={mcR.interaction_ok ? 'ADEQUATE' : 'OVERSTRESSED'} />
            </span>
          )}
        </div>

        <div style={{ ...s.row, alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>SECTION</div>
            <SelRow label="Section type" value={mc.section_type} onChange={updateMcType}
              options={['W','C','HSS_rect','HSS_round','Pipe','Angle']} />
            <SelRow label="Designation" value={mc.designation}
              onChange={v => setMc(p => ({ ...p, designation: v }))}
              options={sectionOptions(mc.section_type)} />
            <NumRow label="Fy (ksi)" value={mc.Fy} onChange={v => setMc(p => ({ ...p, Fy: v }))} />
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>LENGTHS</div>
            <NumRow label="KL strong axis" value={mc.Lc_ft} onChange={v => setMc(p => ({ ...p, Lc_ft: v }))} unit="ft" />
            <NumRow label="KL weak axis" value={mc.Lcy_ft} onChange={v => setMc(p => ({ ...p, Lcy_ft: v }))} unit="ft" />
            <NumRow label="LTB unbraced Lb" value={mc.Lb_ft} onChange={v => setMc(p => ({ ...p, Lb_ft: v }))} unit="ft" />
            <NumRow label="Cb (LTB factor)" value={mc.Cb} onChange={v => setMc(p => ({ ...p, Cb: v }))} />
          </div>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>DEMANDS (LRFD)</div>
            <NumRow label="Pu axial compression" value={mc.Pu} onChange={v => setMc(p => ({ ...p, Pu: v }))} unit="kips" />
            <NumRow label="Mux strong-axis" value={mc.Mux_kip_ft} onChange={v => setMc(p => ({ ...p, Mux_kip_ft: v }))} unit="kip-ft" />
            <NumRow label="Muy weak-axis" value={mc.Muy_kip_ft} onChange={v => setMc(p => ({ ...p, Muy_kip_ft: v }))} unit="kip-ft" />
          </div>
        </div>

        <RunBtn onClick={runMC} running={mcRun} label="Run Full Member Check" />

        {mcE && <div style={s.errorBox}><AlertTriangle size={12} /><span>{mcE}</span></div>}
        {mcRun && <div style={s.infoBox}><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /><span>Computing AISC 360-22 Ch E + F + H…</span></div>}

        {mcR && !mcRun && !mcE && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>
                {mc.designation} — H1 ratio: {fmt(mcR.ratio_H1, 3)} [{mcR.interaction_ok ? 'ADEQUATE' : 'OVERSTRESSED'}]
              </span>
            </div>
            <InteractionRatio ratio={mcR.ratio_H1} />
            <div style={{ ...s.divider, marginTop: 8 }} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 4 }}>
              <div>
                <div style={s.subhead}>Compression (Ch E)</div>
                <table style={s.table}><tbody>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>φcPn</td><td style={{ ...s.td, ...s.mono }}>{fmt(mcR.phi_Pn_kips)} kips</td></tr>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>KL/r</td><td style={{ ...s.td, ...s.mono }}>{fmt(mcR.KL_r)}</td></tr>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>Fcr</td><td style={{ ...s.td, ...s.mono }}>{fmt(mcR.Fcr_ksi)} ksi</td></tr>
                </tbody></table>
              </div>
              <div>
                <div style={s.subhead}>Flexure (Ch F)</div>
                <table style={s.table}><tbody>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>φbMnx</td><td style={{ ...s.td, ...s.mono }}>{fmt(mcR.phi_Mnx_kip_ft)} k-ft</td></tr>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>φbMny</td><td style={{ ...s.td, ...s.mono }}>{fmt(mcR.phi_Mny_kip_ft)} k-ft</td></tr>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>LTB zone</td><td style={{ ...s.td, ...s.mono }}>{mcR.ltb_zone}</td></tr>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>Flange λ</td><td style={{ ...s.td, ...s.mono }}>{mcR.flange_slenderness}</td></tr>
                </tbody></table>
              </div>
              <div>
                <div style={s.subhead}>Combined (Ch H)</div>
                <table style={s.table}><tbody>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>H1 ratio</td>
                    <td style={{ ...s.td, ...s.mono, color: mcR.interaction_ok ? '#34d399' : '#f87171', fontWeight: 700 }}>
                      {fmt(mcR.ratio_H1, 3)}
                    </td>
                  </tr>
                  <tr><td style={{ ...s.td, color: '#9ca3af' }}>Governing</td><td style={{ ...s.td, ...s.mono }}>{mcR.governing}</td></tr>
                </tbody></table>
              </div>
            </div>
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 6 }}>
              Ref: AISC 360-22 §E3 (compression), §F2/F3/F6/F7/F8/F10 (flexure), §H1.1 (combined). LRFD φc=0.90, φb=0.90.
            </div>
          </div>
        )}
      </div>

      {/* ── Chapter E — Compression Only ── */}
      <div style={{ ...s.section, borderLeft: '3px solid #8b5cf6' }}>
        <div style={s.sectionTitle}>
          <TrendingDown size={12} style={{ color: '#8b5cf6' }} />
          Chapter E — Axial Compression Capacity
          {compR && !compRun && <span style={{ marginLeft: 6 }}><StatusChip ok={compR.ok} /></span>}
        </div>
        <SelRow label="Section type" value={comp.section_type} onChange={updateCompType}
          options={['W','C','HSS_rect','HSS_round','Pipe','Angle']} />
        <SelRow label="Designation" value={comp.designation}
          onChange={v => setComp(p => ({ ...p, designation: v }))}
          options={sectionOptions(comp.section_type)} />
        <NumRow label="KL strong axis" value={comp.Lc_ft} onChange={v => setComp(p => ({ ...p, Lc_ft: v }))} unit="ft" />
        <NumRow label="KL weak axis (0=same)" value={comp.Lcy_ft} onChange={v => setComp(p => ({ ...p, Lcy_ft: v }))} unit="ft" />
        <NumRow label="Fy" value={comp.Fy} onChange={v => setComp(p => ({ ...p, Fy: v }))} unit="ksi" />
        <RunBtn onClick={runComp} running={compRun} label="Run Ch E Compression" />
        {compE && <div style={s.errorBox}><AlertTriangle size={12} /><span>{compE}</span></div>}
        {compRun && <div style={s.infoBox}><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /><span>Computing…</span></div>}
        {compR && !compRun && !compE && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 4 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>φcPn = {fmt(compR.phi_Pn_kips, 1)} kips</span>
            </div>
            <ResultTable data={compR} skip={['ok']}
              highlight={['phi_Pn_kips','Fcr_ksi']} />
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 4 }}>
              Ref: AISC 360-22 §E3 (KL/r ≤ 4.71√(E/QFy) → inelastic, else §E3-3 elastic). Slender-element Q per §E7.
            </div>
          </div>
        )}
      </div>

      {/* ── Chapter F — Flexure Only ── */}
      <div style={{ ...s.section, borderLeft: '3px solid #06b6d4' }}>
        <div style={s.sectionTitle}>
          <Layers size={12} style={{ color: '#06b6d4' }} />
          Chapter F — Flexural Capacity (LTB + local buckling)
          {flexR && !flexRun && <span style={{ marginLeft: 6 }}><StatusChip ok={flexR.ok} /></span>}
        </div>
        <SelRow label="Section type" value={flex.section_type} onChange={updateFlexType}
          options={['W','C','HSS_rect','HSS_round','Pipe','Angle']} />
        <SelRow label="Designation" value={flex.designation}
          onChange={v => setFlex(p => ({ ...p, designation: v }))}
          options={sectionOptions(flex.section_type)} />
        <NumRow label="Lb unbraced length" value={flex.Lb_ft} onChange={v => setFlex(p => ({ ...p, Lb_ft: v }))} unit="ft" />
        <NumRow label="Cb (LTB factor)" value={flex.Cb} onChange={v => setFlex(p => ({ ...p, Cb: v }))} />
        <NumRow label="Fy" value={flex.Fy} onChange={v => setFlex(p => ({ ...p, Fy: v }))} unit="ksi" />
        <SelRow label="Bending axis" value={flex.axis} onChange={v => setFlex(p => ({ ...p, axis: v }))}
          options={[{ value: 'x', label: 'Strong (x)' }, { value: 'y', label: 'Weak (y)' }]} />
        <RunBtn onClick={runFlex} running={flexRun} label="Run Ch F Flexure" />
        {flexE && <div style={s.errorBox}><AlertTriangle size={12} /><span>{flexE}</span></div>}
        {flexRun && <div style={s.infoBox}><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /><span>Computing…</span></div>}
        {flexR && !flexRun && !flexE && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 4 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>φbMn = {fmt(flexR.phi_Mn_kip_ft, 1)} kip-ft</span>
              <span style={{ marginLeft: 8, color: '#fbbf24', fontWeight: 600, fontSize: 10 }}>{flexR.ltb_zone?.toUpperCase()} LTB</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 4 }}>
              <table style={s.table}><tbody>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>φbMn</td><td style={{ ...s.td, ...s.mono, color: '#60a5fa', fontWeight: 700 }}>{fmt(flexR.phi_Mn_kip_ft, 2)} kip-ft</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Mp</td><td style={{ ...s.td, ...s.mono }}>{fmt(flexR.Mp_kip_in ? flexR.Mp_kip_in / 12 : null, 2)} kip-ft</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Lp</td><td style={{ ...s.td, ...s.mono }}>{fmt(flexR.Lp_ft, 2)} ft</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Lr</td><td style={{ ...s.td, ...s.mono }}>{fmt(flexR.Lr_ft, 2)} ft</td></tr>
              </tbody></table>
              <table style={s.table}><tbody>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>LTB zone</td><td style={{ ...s.td, ...s.mono, color: '#fbbf24' }}>{flexR.ltb_zone}</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Flange λ</td><td style={{ ...s.td, ...s.mono }}>{flexR.flange_slenderness}</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Web λ</td><td style={{ ...s.td, ...s.mono }}>{flexR.web_slenderness}</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Mn/Ωb</td><td style={{ ...s.td, ...s.mono }}>{fmt(flexR.Mn_over_Omega_kip_ft, 2)} kip-ft (ASD)</td></tr>
              </tbody></table>
            </div>
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 4 }}>
              Ref: AISC 360-22 §F2 (W plastic/inelastic/elastic LTB), §F3 (FLB), §F7 (HSS rect), §F8 (round), §F10 (angle). φb=0.90.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 2 — ACI 318-19 RC Beam Design
// ---------------------------------------------------------------------------

function TabRCBeam() {
  // Design (required As)
  const [design, setDesign] = useState({
    b: '12', h: '24', Mu_kip_ft: '150',
    fc: '4000', fy: '60000',
    cover: '1.5', stirrup_dia: '0.375', bar_dia: '0.625',
  })
  const [designR, setDesignR] = useState(null)
  const [designE, setDesignE] = useState(null)
  const [designRun, setDesignRun] = useState(false)

  const runDesign = useCallback(async () => {
    setDesignRun(true); setDesignE(null); setDesignR(null)
    try {
      const r = await callTool('structural_rc_beam', {
        b: +design.b, h: +design.h, Mu_kip_ft: +design.Mu_kip_ft,
        fc: +design.fc, fy: +design.fy,
        cover: +design.cover, stirrup_dia: +design.stirrup_dia, bar_dia: +design.bar_dia,
      })
      setDesignR(r)
    } catch (e) { setDesignE(e.message) } finally { setDesignRun(false) }
  }, [design])

  return (
    <div>
      <div style={{ ...s.section, borderLeft: '3px solid #f59e0b' }}>
        <div style={s.sectionTitle}>
          <Layers size={12} style={{ color: '#f59e0b' }} />
          ACI 318-19 §22.2 + §9.6 Singly-Reinforced RC Beam Design
          {designR && !designRun && <span style={{ marginLeft: 6 }}><StatusChip ok={designR.ok} /></span>}
        </div>
        <div style={{ ...s.row, flexWrap: 'wrap', gap: 8, alignItems: 'flex-start' }}>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>GEOMETRY</div>
            <NumRow label="Width b" value={design.b} onChange={v => setDesign(p => ({ ...p, b: v }))} unit="in" />
            <NumRow label="Total depth h" value={design.h} onChange={v => setDesign(p => ({ ...p, h: v }))} unit="in" />
            <NumRow label="Factored moment Mu" value={design.Mu_kip_ft} onChange={v => setDesign(p => ({ ...p, Mu_kip_ft: v }))} unit="kip-ft" />
          </div>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>MATERIALS</div>
            <NumRow label="f'c concrete" value={design.fc} onChange={v => setDesign(p => ({ ...p, fc: v }))} unit="psi" />
            <NumRow label="fy rebar" value={design.fy} onChange={v => setDesign(p => ({ ...p, fy: v }))} unit="psi" />
          </div>
          <div style={{ flex: 1, minWidth: 180 }}>
            <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 4 }}>COVER + BARS</div>
            <NumRow label="Clear cover" value={design.cover} onChange={v => setDesign(p => ({ ...p, cover: v }))} unit="in" />
            <NumRow label="Stirrup dia" value={design.stirrup_dia} onChange={v => setDesign(p => ({ ...p, stirrup_dia: v }))} unit="in" />
            <NumRow label="Long. bar dia" value={design.bar_dia} onChange={v => setDesign(p => ({ ...p, bar_dia: v }))} unit="in" />
          </div>
        </div>
        <RunBtn onClick={runDesign} running={designRun} label="Design RC Beam" />
        {designE && <div style={s.errorBox}><AlertTriangle size={12} /><span>{designE}</span></div>}
        {designRun && <div style={s.infoBox}><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /><span>Computing ACI 318-19 R-method…</span></div>}
        {designR && !designRun && !designE && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 6 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>
                As_req = {fmt(designR.As_required_in2, 3)} in² &nbsp;|&nbsp; ρ = {fmt(designR.rho, 5)}
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <table style={s.table}><tbody>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Effective depth d</td><td style={{ ...s.td, ...s.mono }}>{fmt(designR.d, 3)} in</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>Rn</td><td style={{ ...s.td, ...s.mono }}>{fmt(designR.Rn_psi, 1)} psi</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>As required</td><td style={{ ...s.td, ...s.mono, color: '#60a5fa', fontWeight: 700 }}>{fmt(designR.As_required_in2, 3)} in²</td></tr>
              </tbody></table>
              <table style={s.table}><tbody>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>ρ required</td><td style={{ ...s.td, ...s.mono }}>{fmt(designR.rho, 5)}</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>ρ_min §9.6.1.2</td><td style={{ ...s.td, ...s.mono }}>{fmt(designR.rho_min, 5)}</td></tr>
                <tr><td style={{ ...s.td, color: '#9ca3af' }}>ρ_max (εt≥0.004)</td><td style={{ ...s.td, ...s.mono }}>{fmt(designR.rho_max, 5)}</td></tr>
              </tbody></table>
            </div>
            {/* Steel ratio bar */}
            {designR.rho != null && designR.rho_max != null && (
              <div style={{ marginTop: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#9ca3af', marginBottom: 2 }}>
                  <span>ρ / ρ_max ratio</span>
                  <span style={{ color: '#fbbf24', fontWeight: 700 }}>{fmt(designR.rho / designR.rho_max, 3)}</span>
                </div>
                <div style={s.interactionBar}>
                  <div style={{ ...s.interactionFill, width: `${Math.min(designR.rho / designR.rho_max * 100, 100)}%`, background: '#f59e0b' }} />
                </div>
              </div>
            )}
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 4 }}>
              Ref: ACI 318-19 §22.2 (USD strength design), §9.3.3 (εt≥0.004 limit), §9.6.1.2 (ρ_min). φ=0.90 (tension-controlled).
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 3 — Rebar Detailing (ACI 318-19 §25)
// ---------------------------------------------------------------------------

function TabRebar() {
  const [rb, setRb] = useState({
    bar_mark: '5', splice_class: 'B',
    fc: '4000', fy: '60000',
    psi_t: '1.0', psi_e: '1.0', cb_Ktr_db: '2.5',
  })
  const [rbR, setRbR] = useState(null)
  const [rbE, setRbE] = useState(null)
  const [rbRun, setRbRun] = useState(false)

  const runRebar = useCallback(async () => {
    setRbRun(true); setRbE(null); setRbR(null)
    try {
      const r = await callTool('structural_rebar', {
        bar_mark: +rb.bar_mark, splice_class: rb.splice_class,
        fc: +rb.fc, fy: +rb.fy,
        psi_t: +rb.psi_t, psi_e: +rb.psi_e, cb_Ktr_db: +rb.cb_Ktr_db,
      })
      setRbR(r)
    } catch (e) { setRbE(e.message) } finally { setRbRun(false) }
  }, [rb])

  return (
    <div>
      <div style={{ ...s.section, borderLeft: '3px solid #10b981' }}>
        <div style={s.sectionTitle}>
          <Ruler size={12} style={{ color: '#10b981' }} />
          ACI 318-19 §25.5 Development + Lap Splice Lengths
        </div>
        <div style={{ ...s.row, flexWrap: 'wrap', gap: 8, alignItems: 'flex-start' }}>
          <div style={{ flex: 1, minWidth: 160 }}>
            <SelRow label="Bar number" value={rb.bar_mark}
              onChange={v => setRb(p => ({ ...p, bar_mark: v }))}
              options={['3','4','5','6','7','8','9','10','11','14','18']} />
            <SelRow label="Splice class" value={rb.splice_class}
              onChange={v => setRb(p => ({ ...p, splice_class: v }))}
              options={[{ value: 'A', label: 'Class A' }, { value: 'B', label: 'Class B' }]} />
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <NumRow label="f'c" value={rb.fc} onChange={v => setRb(p => ({ ...p, fc: v }))} unit="psi" />
            <NumRow label="fy" value={rb.fy} onChange={v => setRb(p => ({ ...p, fy: v }))} unit="psi" />
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <NumRow label="ψt (top bar factor)" value={rb.psi_t} onChange={v => setRb(p => ({ ...p, psi_t: v }))} />
            <NumRow label="ψe (coating factor)" value={rb.psi_e} onChange={v => setRb(p => ({ ...p, psi_e: v }))} />
            <NumRow label="(cb+Ktr)/db ≤ 2.5" value={rb.cb_Ktr_db} onChange={v => setRb(p => ({ ...p, cb_Ktr_db: v }))} />
          </div>
        </div>
        <RunBtn onClick={runRebar} running={rbRun} label="Compute Development Lengths" />
        {rbE && <div style={s.errorBox}><AlertTriangle size={12} /><span>{rbE}</span></div>}
        {rbRun && <div style={s.infoBox}><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /><span>Computing ACI 318-19 §25.5…</span></div>}
        {rbR && !rbRun && !rbE && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 6 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>
                #{ rbR.bar_mark } bar — ld = {fmt(rbR.ld_in, 2)} in &nbsp;|&nbsp; Lap {rbR.splice_class}: {fmt(rbR.lap_length_in, 2)} in
              </span>
            </div>
            <table style={s.table}><tbody>
              <tr><td style={{ ...s.td, color: '#9ca3af' }}>Bar number</td><td style={{ ...s.td, ...s.mono }}>#{rbR.bar_mark}</td></tr>
              <tr><td style={{ ...s.td, color: '#9ca3af' }}>Bar diameter db</td><td style={{ ...s.td, ...s.mono }}>{fmt(rbR.diameter_in, 4)} in</td></tr>
              <tr><td style={{ ...s.td, color: '#9ca3af' }}>Bar area Ab</td><td style={{ ...s.td, ...s.mono }}>{fmt(rbR.area_in2, 4)} in²</td></tr>
              <tr><td style={{ ...s.td, color: '#9ca3af' }}>Development length ld</td><td style={{ ...s.td, ...s.mono, color: '#60a5fa', fontWeight: 700 }}>{fmt(rbR.ld_in, 2)} in ({fmt(rbR.ld_in / 12, 2)} ft)</td></tr>
              <tr><td style={{ ...s.td, color: '#9ca3af' }}>Lap splice Class {rbR.splice_class}</td><td style={{ ...s.td, ...s.mono, color: '#fbbf24', fontWeight: 700 }}>{fmt(rbR.lap_length_in, 2)} in ({fmt(rbR.lap_length_in / 12, 2)} ft)</td></tr>
            </tbody></table>
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 4 }}>
              Ref: ACI 318-19 §25.5.2.1 — ld = (3/40)·(fy/λ√f'c)·(ψt·ψe·ψs/(cb+Ktr)/db)·db, min 12 in.
              Class A = 1.0·ld; Class B = 1.3·ld (§25.5.5.1).
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
  { id: 'steel', label: 'Steel Member (AISC 360-22)', icon: Cpu },
  { id: 'rc',    label: 'RC Beam (ACI 318-19)',        icon: Layers },
  { id: 'rebar', label: 'Rebar Detailing',             icon: Ruler },
]

export default function StructuralMemberPanel() {
  const [tab, setTab] = useState('steel')

  return (
    <div style={s.root}>
      <div style={s.header}>
        <Cpu size={16} style={{ color: '#3b82f6' }} />
        <span style={s.title}>Structural Member Design</span>
        <span style={s.subtitle}>AISC 360-22 Ch E/F/H · ACI 318-19 · LRFD/ASD</span>
      </div>

      <div style={s.tabs}>
        {TABS.map(t => (
          <button
            key={t.id}
            style={{ ...s.tab, ...(tab === t.id ? s.tabActive : {}) }}
            onClick={() => setTab(t.id)}
          >
            {t.icon && <t.icon size={10} style={{ marginRight: 3 }} />}
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'steel' && <TabSteelMember />}
      {tab === 'rc'    && <TabRCBeam />}
      {tab === 'rebar' && <TabRebar />}
    </div>
  )
}
