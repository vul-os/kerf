// AcousticsResultPanel.jsx — Engineering acoustics analysis panel.
//
// Wires acoustics LLM tools into a tabbed UI.
// Tabs: Outdoor (ISO 9613-2) | Room (RT60 / NC / NR) | Transmission Loss | Weighting
//
// All tools dispatch POST /api/tools/call with { tool: "<name>", args: {...} }.
// Results are rendered inline (numbers, tables).
//
// Props: none (standalone panel — operates without a project file)

import { useState, useCallback } from 'react'
import {
  Volume2, Wind, Home, Shield, Sliders, AlertTriangle, CheckCircle,
  Loader2, Play, ChevronDown, ChevronUp
} from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Styles
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
  label:        { color: '#9ca3af', width: 155, flexShrink: 0, fontSize: 11 },
  input:        { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12, minWidth: 0 },
  select:       { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12 },
  button:       { display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 5, border: 'none', color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 500 },
  buttonDisabled: { opacity: 0.5, cursor: 'not-allowed' },
  errorBox:     { display: 'flex', alignItems: 'flex-start', gap: 6, background: '#450a0a', borderRadius: 5, padding: '8px', color: '#fca5a5', marginTop: 8 },
  infoBox:      { display: 'flex', alignItems: 'center', gap: 6, background: '#1e3a5f', borderRadius: 5, padding: '8px', color: '#93c5fd', marginTop: 8 },
  resultBox:    { background: '#0f172a', borderRadius: 4, padding: '8px', marginTop: 6, fontFamily: 'monospace', fontSize: 11 },
  table:        { width: '100%', borderCollapse: 'collapse', marginTop: 4 },
  td:           { padding: '3px 6px', borderBottom: '1px solid #1f2937' },
  mono:         { fontFamily: 'monospace' },
  subhead:      { color: '#60a5fa', fontWeight: 600, marginBottom: 4, fontSize: 11 },
  badge:        { padding: '2px 6px', borderRadius: 3, fontSize: 10, fontWeight: 600 },
  note:         { color: '#6b7280', fontSize: 10, marginBottom: 4 },
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

function fmt(v, decimals = 2) {
  if (v == null) return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v)
    return v.toFixed(decimals)
  }
  return String(v)
}

function ResultTable({ data, skip = [] }) {
  if (!data || typeof data !== 'object') return null
  const entries = Object.entries(data).filter(
    ([k]) => !skip.includes(k) && !Array.isArray(data[k]) && typeof data[k] !== 'object'
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
              <ResultTable data={result} skip={['ok', 'per_band', 'per_field', 'results', 'modes',
                                                  'band_exceedance', 'octave_band_spls', 'weighted_bands',
                                                  'edc_db', 'il_by_band_db', 'total_il_db']} />
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

function SelectRow({ label, value, onChange, options, disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)} disabled={disabled} style={s.select}>
        {options.map(o => <option key={o.value || o} value={o.value || o}>{o.label || o}</option>)}
      </select>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 1: Outdoor Propagation (ISO 9613-2)
// ---------------------------------------------------------------------------

function TabOutdoor() {
  // ── Single band ──
  const [sb, setSb] = useState({
    Lw: '90', source_h: '0.5', receiver_h: '1.5',
    horizontal_dist: '100', Q: '2', ground_type: 'hard',
    barrier_h: '0', barrier_dist_source: '30', freq_hz: '500',
  })
  const [sbR, setSbR] = useState(null)
  const [sbE, setSbE] = useState(null)
  const [sbRun, setSbRun] = useState(false)

  const runSingleBand = useCallback(async () => {
    setSbRun(true); setSbE(null); setSbR(null)
    try {
      const args = {
        Lw: +sb.Lw, source_h: +sb.source_h, receiver_h: +sb.receiver_h,
        horizontal_dist: +sb.horizontal_dist, Q: +sb.Q,
        ground_type: sb.ground_type, freq_hz: +sb.freq_hz,
      }
      if (+sb.barrier_h > 0) {
        args.barrier_h = +sb.barrier_h
        args.barrier_dist_source = +sb.barrier_dist_source
      }
      const r = await callTool('acoustics_iso9613_outdoor', args)
      setSbR(r)
    } catch (e) { setSbE(e.message) } finally { setSbRun(false) }
  }, [sb])

  // ── Octave bands ──
  const [ob, setOb] = useState({
    lw_bands: JSON.stringify({ '63': 85, '125': 88, '250': 90, '500': 90, '1000': 87, '2000': 84, '4000': 79, '8000': 73 }),
    source_h: '0.5', receiver_h: '1.5',
    horizontal_dist: '100', Q: '2', ground_type: 'soft',
    barrier_h: '0', barrier_dist_source: '30',
  })
  const [obR, setObR] = useState(null)
  const [obE, setObE] = useState(null)
  const [obRun, setObRun] = useState(false)

  const runOctaveBands = useCallback(async () => {
    setObRun(true); setObE(null); setObR(null)
    try {
      const Lw_bands = JSON.parse(ob.lw_bands)
      const args = {
        Lw_bands, source_h: +ob.source_h, receiver_h: +ob.receiver_h,
        horizontal_dist: +ob.horizontal_dist, Q: +ob.Q,
        ground_type: ob.ground_type,
      }
      if (+ob.barrier_h > 0) {
        args.barrier_h = +ob.barrier_h
        args.barrier_dist_source = +ob.barrier_dist_source
      }
      const r = await callTool('acoustics_iso9613_octave_bands', args)
      setObR(r)
    } catch (e) { setObE(e.message) } finally { setObRun(false) }
  }, [ob])

  const GROUND_OPTIONS = [
    { value: 'hard', label: 'Hard (concrete, asphalt, water) G=0' },
    { value: 'soft', label: 'Soft (grass, soil, forest) G=1' },
  ]

  return (
    <div>
      <div style={s.note}>
        ISO 9613-2:1996 — Geometric divergence + atmospheric absorption (ISO 9613-1) + ground effect + Maekawa barrier diffraction.
      </div>

      <ToolWidget title="Single-Band Outdoor Propagation" icon={Wind} color="#3b82f6" result={sbR} error={sbE} running={sbRun}>
        <NumRow label="Lw (dB re 1 pW)" value={sb.Lw} onChange={v => setSb(p => ({ ...p, Lw: v }))} disabled={sbRun} />
        <NumRow label="Source height (m)" value={sb.source_h} onChange={v => setSb(p => ({ ...p, source_h: v }))} disabled={sbRun} />
        <NumRow label="Receiver height (m)" value={sb.receiver_h} onChange={v => setSb(p => ({ ...p, receiver_h: v }))} disabled={sbRun} />
        <NumRow label="Horizontal dist (m)" value={sb.horizontal_dist} onChange={v => setSb(p => ({ ...p, horizontal_dist: v }))} disabled={sbRun} />
        <NumRow label="Q directivity" value={sb.Q} onChange={v => setSb(p => ({ ...p, Q: v }))} disabled={sbRun} />
        <SelectRow label="Ground type" value={sb.ground_type} onChange={v => setSb(p => ({ ...p, ground_type: v }))} options={GROUND_OPTIONS} disabled={sbRun} />
        <NumRow label="Frequency (Hz)" value={sb.freq_hz} onChange={v => setSb(p => ({ ...p, freq_hz: v }))} disabled={sbRun} />
        <NumRow label="Barrier height (m, 0=none)" value={sb.barrier_h} onChange={v => setSb(p => ({ ...p, barrier_h: v }))} disabled={sbRun} />
        {+sb.barrier_h > 0 && (
          <NumRow label="Barrier dist from src (m)" value={sb.barrier_dist_source} onChange={v => setSb(p => ({ ...p, barrier_dist_source: v }))} disabled={sbRun} />
        )}
        <RunBtn onClick={runSingleBand} running={sbRun} />
        {sbR && !sbRun && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Attenuation breakdown</div>
            <table style={s.table}>
              <tbody>
                {[
                  ['Lp at receiver', `${fmt(sbR.lp_db)} dB`],
                  ['A_div (spreading)', `${fmt(sbR.A_div_db)} dB`],
                  ['A_atm (atmosphere)', `${fmt(sbR.A_atm_db)} dB`],
                  ['A_gr (ground)', `${fmt(sbR.A_gr_db)} dB`],
                  ['A_bar (barrier)', `${fmt(sbR.A_bar_db)} dB`],
                  ['A_total', `${fmt(sbR.A_total_db)} dB`],
                  ['Slant distance', `${fmt(sbR.slant_dist_m)} m`],
                ].map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ ...s.td, color: '#9ca3af', width: '60%' }}>{k}</td>
                    <td style={{ ...s.td, ...s.mono }}>{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Octave-Band Outdoor Propagation (dB + dBA)" icon={Wind} color="#8b5cf6" result={obR} error={obE} running={obRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Lw_bands (JSON)</label>
          <textarea
            value={ob.lw_bands}
            onChange={e => setOb(p => ({ ...p, lw_bands: e.target.value }))}
            disabled={obRun}
            rows={4}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <div style={s.note}>Format: {'{'}freq_hz: Lw_dB{'}'} — standard bands 63–8000 Hz</div>
        <NumRow label="Source height (m)" value={ob.source_h} onChange={v => setOb(p => ({ ...p, source_h: v }))} disabled={obRun} />
        <NumRow label="Receiver height (m)" value={ob.receiver_h} onChange={v => setOb(p => ({ ...p, receiver_h: v }))} disabled={obRun} />
        <NumRow label="Horizontal dist (m)" value={ob.horizontal_dist} onChange={v => setOb(p => ({ ...p, horizontal_dist: v }))} disabled={obRun} />
        <NumRow label="Q directivity" value={ob.Q} onChange={v => setOb(p => ({ ...p, Q: v }))} disabled={obRun} />
        <SelectRow label="Ground type" value={ob.ground_type} onChange={v => setOb(p => ({ ...p, ground_type: v }))} options={GROUND_OPTIONS} disabled={obRun} />
        <NumRow label="Barrier height (m, 0=none)" value={ob.barrier_h} onChange={v => setOb(p => ({ ...p, barrier_h: v }))} disabled={obRun} />
        {+ob.barrier_h > 0 && (
          <NumRow label="Barrier dist from src (m)" value={ob.barrier_dist_source} onChange={v => setOb(p => ({ ...p, barrier_dist_source: v }))} disabled={obRun} />
        )}
        <RunBtn onClick={runOctaveBands} running={obRun} />
        {obR && !obRun && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Overall levels</div>
            <div style={s.mono}>Lp total: {fmt(obR.Lp_total_db)} dB &nbsp;|&nbsp; Lp(A): {fmt(obR.LpA_total_db)} dB(A)</div>
            {Array.isArray(obR.per_band) && (
              <>
                <div style={{ ...s.subhead, marginTop: 8 }}>Per-band Lp</div>
                <table style={s.table}>
                  <thead><tr>
                    <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>Freq (Hz)</td>
                    <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>Lp (dB)</td>
                    <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>A_div</td>
                    <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>A_bar</td>
                  </tr></thead>
                  <tbody>
                    {obR.per_band.map((b, i) => (
                      <tr key={i}>
                        <td style={s.td}>{b.freq_hz_input ?? b.freq_hz}</td>
                        <td style={{ ...s.td, ...s.mono }}>{fmt(b.lp_db)}</td>
                        <td style={{ ...s.td, ...s.mono }}>{fmt(b.A_div_db)}</td>
                        <td style={{ ...s.td, ...s.mono }}>{fmt(b.A_bar_db)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 2: Room Acoustics (RT60 / Noise Rating)
// ---------------------------------------------------------------------------

function TabRoom() {
  // ── Sabine RT60 ──
  const [sab, setSab] = useState({ volume_m3: '500', total_absorption_m2: '80' })
  const [sabR, setSabR] = useState(null); const [sabE, setSabE] = useState(null); const [sabRun, setSabRun] = useState(false)
  const runSabine = useCallback(async () => {
    setSabRun(true); setSabE(null); setSabR(null)
    try { const r = await callTool('acoustics_sabine_rt60', { volume_m3: +sab.volume_m3, total_absorption_m2: +sab.total_absorption_m2 }); setSabR(r) }
    catch (e) { setSabE(e.message) } finally { setSabRun(false) }
  }, [sab])

  // ── Eyring RT60 ──
  const [eyr, setEyr] = useState({ volume_m3: '500', S_m2: '400', alpha_avg: '0.2' })
  const [eyrR, setEyrR] = useState(null); const [eyrE, setEyrE] = useState(null); const [eyrRun, setEyrRun] = useState(false)
  const runEyring = useCallback(async () => {
    setEyrRun(true); setEyrE(null); setEyrR(null)
    try { const r = await callTool('acoustics_eyring_rt60', { volume_m3: +eyr.volume_m3, S_m2: +eyr.S_m2, alpha_avg: +eyr.alpha_avg }); setEyrR(r) }
    catch (e) { setEyrE(e.message) } finally { setEyrRun(false) }
  }, [eyr])

  // ── Room constant ──
  const [rc, setRc] = useState({ S_m2: '400', alpha_avg: '0.15' })
  const [rcR, setRcR] = useState(null); const [rcE, setRcE] = useState(null); const [rcRun, setRcRun] = useState(false)
  const runRoomConst = useCallback(async () => {
    setRcRun(true); setRcE(null); setRcR(null)
    try { const r = await callTool('acoustics_room_constant', { S_m2: +rc.S_m2, alpha_avg: +rc.alpha_avg }); setRcR(r) }
    catch (e) { setRcE(e.message) } finally { setRcRun(false) }
  }, [rc])

  // ── NC Rating ──
  const [nc, setNc] = useState({ octave_band_spls: JSON.stringify({ '63': 54, '125': 44, '250': 37, '500': 31, '1000': 27, '2000': 24, '4000': 22, '8000': 21 }) })
  const [ncR, setNcR] = useState(null); const [ncE, setNcE] = useState(null); const [ncRun, setNcRun] = useState(false)
  const runNc = useCallback(async () => {
    setNcRun(true); setNcE(null); setNcR(null)
    try { const r = await callTool('acoustics_nc_rating', { octave_band_spls: JSON.parse(nc.octave_band_spls) }); setNcR(r) }
    catch (e) { setNcE(e.message) } finally { setNcRun(false) }
  }, [nc])

  // ── NR Rating ──
  const [nr, setNr] = useState({ octave_band_spls: JSON.stringify({ '63': 55, '125': 47, '250': 40, '500': 35, '1000': 31, '2000': 28, '4000': 27, '8000': 26 }) })
  const [nrR, setNrR] = useState(null); const [nrE, setNrE] = useState(null); const [nrRun, setNrRun] = useState(false)
  const runNr = useCallback(async () => {
    setNrRun(true); setNrE(null); setNrR(null)
    try { const r = await callTool('acoustics_nr_rating', { octave_band_spls: JSON.parse(nr.octave_band_spls) }); setNrR(r) }
    catch (e) { setNrE(e.message) } finally { setNrRun(false) }
  }, [nr])

  // ── Room Modes ──
  const [modes, setModes] = useState({ L: '8', W: '5', H: '3', f_max: '200' })
  const [modesR, setModesR] = useState(null); const [modesE, setModesE] = useState(null); const [modesRun, setModesRun] = useState(false)
  const runModes = useCallback(async () => {
    setModesRun(true); setModesE(null); setModesR(null)
    try { const r = await callTool('wave_room_modes', { L: +modes.L, W: +modes.W, H: +modes.H, f_max: +modes.f_max }); setModesR(r) }
    catch (e) { setModesE(e.message) } finally { setModesRun(false) }
  }, [modes])

  return (
    <div>
      <ToolWidget title="Sabine RT60 (low absorption)" icon={Home} color="#3b82f6" result={sabR} error={sabE} running={sabRun}>
        <div style={s.note}>Valid when average α &lt; ~0.2 (diffuse field).</div>
        <NumRow label="Volume (m³)" value={sab.volume_m3} onChange={v => setSab(p => ({ ...p, volume_m3: v }))} disabled={sabRun} />
        <NumRow label="Total absorption (m²)" value={sab.total_absorption_m2} onChange={v => setSab(p => ({ ...p, total_absorption_m2: v }))} disabled={sabRun} />
        <RunBtn onClick={runSabine} running={sabRun} />
      </ToolWidget>

      <ToolWidget title="Eyring RT60 (higher absorption)" icon={Home} color="#10b981" result={eyrR} error={eyrE} running={eyrRun}>
        <div style={s.note}>More accurate than Sabine when α_avg &gt; 0.2.</div>
        <NumRow label="Volume (m³)" value={eyr.volume_m3} onChange={v => setEyr(p => ({ ...p, volume_m3: v }))} disabled={eyrRun} />
        <NumRow label="Surface area (m²)" value={eyr.S_m2} onChange={v => setEyr(p => ({ ...p, S_m2: v }))} disabled={eyrRun} />
        <NumRow label="α_avg (0–1)" value={eyr.alpha_avg} onChange={v => setEyr(p => ({ ...p, alpha_avg: v }))} disabled={eyrRun} />
        <RunBtn onClick={runEyring} running={eyrRun} />
      </ToolWidget>

      <ToolWidget title="Room Constant R" icon={Home} color="#f59e0b" result={rcR} error={rcE} running={rcRun}>
        <NumRow label="Surface area (m²)" value={rc.S_m2} onChange={v => setRc(p => ({ ...p, S_m2: v }))} disabled={rcRun} />
        <NumRow label="α_avg (0–1)" value={rc.alpha_avg} onChange={v => setRc(p => ({ ...p, alpha_avg: v }))} disabled={rcRun} />
        <RunBtn onClick={runRoomConst} running={rcRun} />
      </ToolWidget>

      <ToolWidget title="NC Rating (Noise Criteria)" icon={Volume2} color="#dc2626" result={ncR} error={ncE} running={ncRun}>
        <div style={s.note}>NC-25 to NC-35: private offices. NC-35 to NC-45: open offices.</div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Octave SPLs (JSON)</label>
          <textarea value={nc.octave_band_spls} onChange={e => setNc(p => ({ ...p, octave_band_spls: e.target.value }))} disabled={ncRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <RunBtn onClick={runNc} running={ncRun} />
        {ncR && !ncRun && (
          <div style={s.resultBox}>
            <div style={s.mono}>NC Rating: <strong>{ncR.nc_rating ?? '>70'}</strong>
              {ncR.exceeds_nc70 && <span style={{ color: '#fca5a5' }}> (exceeds NC-70!)</span>}
            </div>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="NR Rating (ISO 1996-1 Noise Rating)" icon={Volume2} color="#7c3aed" result={nrR} error={nrE} running={nrRun}>
        <div style={s.note}>NR-15 to NR-20: concert halls. NR-35 to NR-45: offices.</div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Octave SPLs (JSON)</label>
          <textarea value={nr.octave_band_spls} onChange={e => setNr(p => ({ ...p, octave_band_spls: e.target.value }))} disabled={nrRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <RunBtn onClick={runNr} running={nrRun} />
        {nrR && !nrRun && (
          <div style={s.resultBox}>
            <div style={s.mono}>NR Rating: <strong>{nrR.nr_rating ?? '>75'}</strong>
              {nrR.exceeds_nr75 && <span style={{ color: '#fca5a5' }}> (exceeds NR-75!)</span>}
            </div>
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="Room Modes (axial/tangential/oblique)" icon={Home} color="#0891b2" result={null} error={modesE} running={modesRun}>
        <div style={s.note}>f = (c/2)·√((nx/L)²+(ny/W)²+(nz/H)²)</div>
        <NumRow label="L length (m)" value={modes.L} onChange={v => setModes(p => ({ ...p, L: v }))} disabled={modesRun} />
        <NumRow label="W width (m)" value={modes.W} onChange={v => setModes(p => ({ ...p, W: v }))} disabled={modesRun} />
        <NumRow label="H height (m)" value={modes.H} onChange={v => setModes(p => ({ ...p, H: v }))} disabled={modesRun} />
        <NumRow label="f_max (Hz)" value={modes.f_max} onChange={v => setModes(p => ({ ...p, f_max: v }))} step="1" disabled={modesRun} />
        <RunBtn onClick={runModes} running={modesRun} />
        {modesR && !modesRun && (
          <div style={s.resultBox}>
            <div style={s.mono}>{modesR.modes?.length ?? 0} modes below {modes.f_max} Hz</div>
            {Array.isArray(modesR.modes) && modesR.modes.slice(0, 15).map((m, i) => (
              <div key={i} style={{ ...s.mono, fontSize: 10, color: '#d1d5db' }}>
                {fmt(m.f_hz, 1)} Hz — {m.type} ({m.nx},{m.ny},{m.nz})
              </div>
            ))}
            {modesR.modes?.length > 15 && (
              <div style={{ color: '#6b7280', fontSize: 10 }}>…and {modesR.modes.length - 15} more</div>
            )}
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 3: Transmission Loss
// ---------------------------------------------------------------------------

function TabTL() {
  // ── Mass-law TL ──
  const [ml, setMl] = useState({ surface_density_kg_m2: '10', freq_hz: '500' })
  const [mlR, setMlR] = useState(null); const [mlE, setMlE] = useState(null); const [mlRun, setMlRun] = useState(false)
  const runMassLaw = useCallback(async () => {
    setMlRun(true); setMlE(null); setMlR(null)
    try { const r = await callTool('acoustics_mass_law_tl', { surface_density_kg_m2: +ml.surface_density_kg_m2, freq_hz: +ml.freq_hz }); setMlR(r) }
    catch (e) { setMlE(e.message) } finally { setMlRun(false) }
  }, [ml])

  // ── Composite TL ──
  const [ct, setCt] = useState({
    elements: JSON.stringify([
      { area_m2: 12, tl_db: 40 },
      { area_m2: 2.5, tl_db: 25 },
    ])
  })
  const [ctR, setCtR] = useState(null); const [ctE, setCtE] = useState(null); const [ctRun, setCtRun] = useState(false)
  const runCompTL = useCallback(async () => {
    setCtRun(true); setCtE(null); setCtR(null)
    try {
      const elements = JSON.parse(ct.elements)
      const r = await callTool('acoustics_composite_tl', { elements })
      setCtR(r)
    } catch (e) { setCtE(e.message) } finally { setCtRun(false) }
  }, [ct])

  // ── SPL transmitted ──
  const [tr, setTr] = useState({ spl_source: '75', tl_db: '40' })
  const [trR, setTrR] = useState(null); const [trE, setTrE] = useState(null); const [trRun, setTrRun] = useState(false)
  const runTransmit = useCallback(async () => {
    setTrRun(true); setTrE(null); setTrR(null)
    try { const r = await callTool('acoustics_spl_transmitted', { spl_source: +tr.spl_source, tl_db: +tr.tl_db }); setTrR(r) }
    catch (e) { setTrE(e.message) } finally { setTrRun(false) }
  }, [tr])

  // ── SEA Two-Room ──
  const [sea, setSea] = useState({ loss_factor_1: '0.05', loss_factor_2: '0.05', coupling: '0.01', modal_density: '1.0', freq_bands: '125,250,500,1000,2000' })
  const [seaR, setSeaR] = useState(null); const [seaE, setSeaE] = useState(null); const [seaRun, setSeaRun] = useState(false)
  const runSEA = useCallback(async () => {
    setSeaRun(true); setSeaE(null); setSeaR(null)
    try {
      const freq_bands = sea.freq_bands.split(',').map(Number)
      const r = await callTool('wave_sea_two_rooms_tl', {
        loss_factor_1: +sea.loss_factor_1, loss_factor_2: +sea.loss_factor_2,
        coupling: +sea.coupling, modal_density: +sea.modal_density, freq_bands,
      })
      setSeaR(r)
    } catch (e) { setSeaE(e.message) } finally { setSeaRun(false) }
  }, [sea])

  return (
    <div>
      <ToolWidget title="Mass-Law TL (ISO 140-3, single-leaf partition)" icon={Shield} color="#3b82f6" result={mlR} error={mlE} running={mlRun}>
        <div style={s.note}>TL = 20·log₁₀(m·f) − 47  (field-incidence, valid below coincidence).</div>
        <NumRow label="Surface density (kg/m²)" value={ml.surface_density_kg_m2} onChange={v => setMl(p => ({ ...p, surface_density_kg_m2: v }))} disabled={mlRun} />
        <NumRow label="Frequency (Hz)" value={ml.freq_hz} onChange={v => setMl(p => ({ ...p, freq_hz: v }))} disabled={mlRun} />
        <RunBtn onClick={runMassLaw} running={mlRun} />
      </ToolWidget>

      <ToolWidget title="Composite Partition TL (wall + window/door)" icon={Shield} color="#f59e0b" result={ctR} error={ctE} running={ctRun}>
        <div style={s.note}>τ_avg = Σ(Sᵢτᵢ)/ΣSᵢ — a weak element dominates.</div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Elements (JSON)</label>
          <textarea value={ct.elements} onChange={e => setCt(p => ({ ...p, elements: e.target.value }))} disabled={ctRun}
            rows={4} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <div style={s.note}>Each: {'{'}area_m2, tl_db{'}'}</div>
        <RunBtn onClick={runCompTL} running={ctRun} />
      </ToolWidget>

      <ToolWidget title="SPL Transmitted Through Barrier" icon={Shield} color="#10b981" result={trR} error={trE} running={trRun}>
        <NumRow label="Source SPL (dB)" value={tr.spl_source} onChange={v => setTr(p => ({ ...p, spl_source: v }))} disabled={trRun} />
        <NumRow label="TL (dB)" value={tr.tl_db} onChange={v => setTr(p => ({ ...p, tl_db: v }))} disabled={trRun} />
        <RunBtn onClick={runTransmit} running={trRun} />
      </ToolWidget>

      <ToolWidget title="SEA Two-Room TL (Statistical Energy Analysis)" icon={Shield} color="#7c3aed" result={null} error={seaE} running={seaRun}>
        <div style={s.note}>Solves 2×2 energy balance per band: TL = 10·log₁₀(E₁/E₂).</div>
        <NumRow label="η₁ loss factor room 1" value={sea.loss_factor_1} onChange={v => setSea(p => ({ ...p, loss_factor_1: v }))} disabled={seaRun} />
        <NumRow label="η₂ loss factor room 2" value={sea.loss_factor_2} onChange={v => setSea(p => ({ ...p, loss_factor_2: v }))} disabled={seaRun} />
        <NumRow label="coupling coefficient" value={sea.coupling} onChange={v => setSea(p => ({ ...p, coupling: v }))} disabled={seaRun} />
        <NumRow label="modal density (modes/Hz)" value={sea.modal_density} onChange={v => setSea(p => ({ ...p, modal_density: v }))} disabled={seaRun} />
        <div style={s.row}>
          <label style={s.label}>Freq bands (Hz, CSV)</label>
          <input value={sea.freq_bands} onChange={e => setSea(p => ({ ...p, freq_bands: e.target.value }))} disabled={seaRun} style={s.input} />
        </div>
        <RunBtn onClick={runSEA} running={seaRun} />
        {seaR?.results && !seaRun && (
          <div style={s.resultBox}>
            <table style={s.table}>
              <thead><tr>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>Freq (Hz)</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 10 }}>TL (dB)</td>
              </tr></thead>
              <tbody>
                {seaR.results.map((b, i) => (
                  <tr key={i}>
                    <td style={s.td}>{b.freq_hz}</td>
                    <td style={{ ...s.td, ...s.mono }}>{b.tl_db != null ? fmt(b.tl_db) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 4: Weighting & SPL Arithmetic
// ---------------------------------------------------------------------------

function TabWeighting() {
  // ── A-weighting ──
  const [aw, setAw] = useState({ freq_hz: '1000' })
  const [awR, setAwR] = useState(null); const [awE, setAwE] = useState(null); const [awRun, setAwRun] = useState(false)
  const runAW = useCallback(async () => {
    setAwRun(true); setAwE(null); setAwR(null)
    try { const r = await callTool('acoustics_a_weighting', { freq_hz: +aw.freq_hz }); setAwR(r) }
    catch (e) { setAwE(e.message) } finally { setAwRun(false) }
  }, [aw])

  // ── Apply weighting ──
  const [apw, setApw] = useState({
    octave_band_spls: JSON.stringify({ '63': 70, '125': 68, '250': 65, '500': 62, '1000': 60, '2000': 58, '4000': 55, '8000': 52 }),
    weighting: 'A',
  })
  const [apwR, setApwR] = useState(null); const [apwE, setApwE] = useState(null); const [apwRun, setApwRun] = useState(false)
  const runApplyW = useCallback(async () => {
    setApwRun(true); setApwE(null); setApwR(null)
    try {
      const r = await callTool('acoustics_apply_weighting', {
        octave_band_spls: JSON.parse(apw.octave_band_spls),
        weighting: apw.weighting,
      })
      setApwR(r)
    } catch (e) { setApwE(e.message) } finally { setApwRun(false) }
  }, [apw])

  // ── SPL sum ──
  const [sum, setSum] = useState({ levels: '70,70,65' })
  const [sumR, setSumR] = useState(null); const [sumE, setSumE] = useState(null); const [sumRun, setSumRun] = useState(false)
  const runSum = useCallback(async () => {
    setSumRun(true); setSumE(null); setSumR(null)
    try { const r = await callTool('acoustics_spl_sum', { levels_db: sum.levels.split(',').map(Number) }); setSumR(r) }
    catch (e) { setSumE(e.message) } finally { setSumRun(false) }
  }, [sum])

  // ── Point source ──
  const [ps, setPs] = useState({ Lw: '90', r: '10', Q: '2' })
  const [psR, setPsR] = useState(null); const [psE, setPsE] = useState(null); const [psRun, setPsRun] = useState(false)
  const runPS = useCallback(async () => {
    setPsRun(true); setPsE(null); setPsR(null)
    try { const r = await callTool('acoustics_point_source', { Lw: +ps.Lw, r: +ps.r, Q: +ps.Q }); setPsR(r) }
    catch (e) { setPsE(e.message) } finally { setPsRun(false) }
  }, [ps])

  return (
    <div>
      <ToolWidget title="A-Weighting Correction (IEC 61672-1)" icon={Sliders} color="#3b82f6" result={awR} error={awE} running={awRun}>
        <NumRow label="Frequency (Hz)" value={aw.freq_hz} onChange={v => setAw(p => ({ ...p, freq_hz: v }))} disabled={awRun} />
        <RunBtn onClick={runAW} running={awRun} />
      </ToolWidget>

      <ToolWidget title="Apply A/C Weighting to Octave Bands" icon={Sliders} color="#8b5cf6" result={null} error={apwE} running={apwRun}>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Octave SPLs (JSON)</label>
          <textarea value={apw.octave_band_spls} onChange={e => setApw(p => ({ ...p, octave_band_spls: e.target.value }))} disabled={apwRun}
            rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
        </div>
        <SelectRow label="Weighting" value={apw.weighting} onChange={v => setApw(p => ({ ...p, weighting: v }))}
          options={[{ value: 'A', label: 'A — speech intelligibility' }, { value: 'C', label: 'C — peak levels / low frequency' }]}
          disabled={apwRun} />
        <RunBtn onClick={runApplyW} running={apwRun} />
        {apwR && !apwRun && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Weighted SPLs (dB{apwR.weighting})</div>
            {apwR.weighted_bands && Object.entries(apwR.weighted_bands).map(([f, v]) => (
              <div key={f} style={{ ...s.mono, fontSize: 10, color: '#d1d5db' }}>{f} Hz: {fmt(v)} dB</div>
            ))}
          </div>
        )}
      </ToolWidget>

      <ToolWidget title="SPL Sum (logarithmic energy addition)" icon={Volume2} color="#10b981" result={sumR} error={sumE} running={sumRun}>
        <div style={s.row}>
          <label style={s.label}>Levels (dB, CSV)</label>
          <input value={sum.levels} onChange={e => setSum(p => ({ ...p, levels: e.target.value }))} disabled={sumRun} style={s.input} />
        </div>
        <RunBtn onClick={runSum} running={sumRun} />
      </ToolWidget>

      <ToolWidget title="Point Source SPL at Distance" icon={Volume2} color="#f97316" result={psR} error={psE} running={psRun}>
        <div style={s.note}>Lp = Lw + 10·log₁₀(Q / (4πr²))  — simple free-field model.</div>
        <NumRow label="Lw (dB re 1 pW)" value={ps.Lw} onChange={v => setPs(p => ({ ...p, Lw: v }))} disabled={psRun} />
        <NumRow label="r distance (m)" value={ps.r} onChange={v => setPs(p => ({ ...p, r: v }))} disabled={psRun} />
        <NumRow label="Q directivity" value={ps.Q} onChange={v => setPs(p => ({ ...p, Q: v }))} disabled={psRun} />
        <RunBtn onClick={runPS} running={psRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'outdoor', label: 'Outdoor (ISO 9613-2)', icon: Wind },
  { id: 'room',    label: 'Room Acoustics',       icon: Home },
  { id: 'tl',      label: 'Transmission Loss',    icon: Shield },
  { id: 'weight',  label: 'Weighting / SPL',      icon: Sliders },
]

export default function AcousticsResultPanel() {
  const [activeTab, setActiveTab] = useState('outdoor')

  return (
    <div style={s.root} data-testid="acoustics-result-panel">
      <div style={s.header}>
        <Volume2 size={15} style={{ color: '#34d399' }} />
        <span style={s.title}>Acoustics</span>
        <span style={{ ...s.badge, background: '#065f46', color: '#6ee7b7' }}>ISO 9613-2 + RT60 + SEA</span>
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

      {activeTab === 'outdoor' && <TabOutdoor />}
      {activeTab === 'room'    && <TabRoom />}
      {activeTab === 'tl'      && <TabTL />}
      {activeTab === 'weight'  && <TabWeighting />}
    </div>
  )
}
