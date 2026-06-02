// DrawingPanel.jsx — 2D engineering drawing UI.
//
// Wires 8 drawing backend tools into a tabbed UI.
// Tabs: Views | Dimensions | Annotations | Sheet Layout | Export
//
// Backend tools: drawing_auto_views, drawing_auto_dimension_iso,
//   drawing_measurement_chain, drawing_inspection_report,
//   drawing_silhouette_projection, drawing_oblique_projection,
//   drawing_validate_iso, drawing_compile_pdf (if present)
//
// All tools dispatch POST /api/tools/call with { tool: "<name>", args: {...} }.
// Results are rendered inline (numbers, tables, or SVG previews).
//
// Props: none (standalone panel — operates without a project file)

import { useState, useCallback } from 'react'
import {
  FileText, Ruler, LayoutDashboard, Download, StickyNote,
  AlertTriangle, CheckCircle, Loader2, Play,
  ChevronDown, ChevronUp, RefreshCw, Layers, SplitSquareHorizontal,
  AlignCenter, Scan, FileSearch,
} from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Styles — matching fea/BucklingPanel + OpticsDesignPanel pattern
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
  buttonDisabled: { opacity: 0.5, cursor: 'not-allowed' },
  errorBox:     { display: 'flex', alignItems: 'flex-start', gap: 6, background: '#450a0a', borderRadius: 5, padding: '8px', color: '#fca5a5', marginTop: 8 },
  infoBox:      { display: 'flex', alignItems: 'center', gap: 6, background: '#1e3a5f', borderRadius: 5, padding: '8px', color: '#93c5fd', marginTop: 8 },
  successBox:   { display: 'flex', alignItems: 'flex-start', gap: 6, background: '#052e16', borderRadius: 5, padding: '8px', color: '#86efac', marginTop: 8 },
  resultBox:    { background: '#0f172a', borderRadius: 4, padding: '8px', marginTop: 6, fontFamily: 'monospace', fontSize: 11 },
  table:        { width: '100%', borderCollapse: 'collapse', marginTop: 4 },
  td:           { padding: '3px 6px', borderBottom: '1px solid #1f2937' },
  mono:         { fontFamily: 'monospace' },
  subhead:      { color: '#60a5fa', fontWeight: 600, marginBottom: 4, fontSize: 11 },
  divider:      { borderTop: '1px solid #374151', margin: '8px 0' },
  badge:        { padding: '2px 6px', borderRadius: 3, fontSize: 10, fontWeight: 600 },
  svgBox:       { background: '#0f172a', borderRadius: 4, padding: '8px', marginTop: 6, overflowX: 'auto' },
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
    return Math.abs(v) > 1e4 || (Math.abs(v) < 1e-3 && v !== 0)
      ? v.toExponential(3)
      : v.toFixed(decimals)
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
      <div
        style={{ ...s.sectionTitle, justifyContent: 'space-between', cursor: 'pointer' }}
        onClick={() => setOpen(o => !o)}
      >
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
              <AlertTriangle size={12} style={{ flexShrink: 0, marginTop: 2 }} />
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
              <ResultTable data={result} skip={['svg', 'pdf_base64', 'dxf', 'svg_data']} />
            </div>
          )}
        </>
      )}
    </div>
  )
}

function RunBtn({ onClick, running, disabled, label = 'Run' }) {
  return (
    <button
      onClick={onClick}
      disabled={running || disabled}
      style={{
        ...s.button, background: '#1e40af', marginTop: 6,
        ...(running || disabled ? s.buttonDisabled : {}),
      }}
    >
      {running
        ? <><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> Computing…</>
        : <><Play size={12} /> {label}</>}
    </button>
  )
}

function SelRow({ label, value, onChange, options, disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)} style={s.select} disabled={disabled}>
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
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

function TextRow({ label, value, onChange, placeholder, disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        style={s.input}
      />
    </div>
  )
}

function CheckRow({ label, value, onChange, disabled }) {
  return (
    <div style={{ ...s.row, cursor: 'pointer' }} onClick={() => !disabled && onChange(!value)}>
      <label style={{ ...s.label, cursor: 'pointer' }}>{label}</label>
      <div style={{
        width: 32, height: 18, borderRadius: 9, background: value ? '#2563eb' : '#374151',
        display: 'flex', alignItems: 'center', padding: '0 2px', transition: 'background 0.2s',
        cursor: disabled ? 'not-allowed' : 'pointer', flexShrink: 0,
      }}>
        <div style={{
          width: 14, height: 14, borderRadius: 7, background: '#fff',
          transform: value ? 'translateX(14px)' : 'translateX(0)',
          transition: 'transform 0.2s',
        }} />
      </div>
    </div>
  )
}

// SVG preview helper — renders inline if data is a string starting with <svg
function SvgPreview({ data }) {
  if (!data || typeof data !== 'string') return null
  const isSvg = data.trimStart().startsWith('<svg') || data.trimStart().startsWith('<?xml')
  if (!isSvg) return null
  return (
    <div style={s.svgBox}>
      <div style={s.subhead}>Preview</div>
      <div
        style={{ maxWidth: '100%', overflow: 'auto' }}
        dangerouslySetInnerHTML={{ __html: data }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Default body spec (JSON string, used as placeholder)
// ---------------------------------------------------------------------------
const DEFAULT_BODY = JSON.stringify({
  name: 'bracket',
  bbox: { length: 100, width: 50, height: 30 },
  holes: [{ x: 15, y: 15, diameter: 8, depth: 30 }],
}, null, 2)

// ---------------------------------------------------------------------------
// TAB 1: Views
// ---------------------------------------------------------------------------

function TabViews() {
  // ── drawing_auto_views ──────────────────────────────────────────────────
  const [av, setAv] = useState({
    body: DEFAULT_BODY,
    projection_type: 'third_angle',
    include_iso: true,
    sheet: 'A3',
    scale: '',
  })
  const [avR, setAvR] = useState(null)
  const [avE, setAvE] = useState(null)
  const [avRun, setAvRun] = useState(false)

  const runAutoViews = useCallback(async () => {
    setAvRun(true); setAvE(null); setAvR(null)
    try {
      const body = JSON.parse(av.body)
      const args = {
        body,
        projection_type: av.projection_type,
        include_iso: av.include_iso,
        sheet: av.sheet,
      }
      if (av.scale) args.scale = parseFloat(av.scale)
      const r = await callTool('drawing_auto_views', args)
      setAvR(r)
    } catch (e) { setAvE(e.message) } finally { setAvRun(false) }
  }, [av])

  // ── drawing_silhouette_projection ───────────────────────────────────────
  const [sp, setSp] = useState({
    body: DEFAULT_BODY,
    direction: 'front',
    include_hidden: true,
  })
  const [spR, setSpR] = useState(null)
  const [spE, setSpE] = useState(null)
  const [spRun, setSpRun] = useState(false)

  const runSilhouette = useCallback(async () => {
    setSpRun(true); setSpE(null); setSpR(null)
    try {
      const body = JSON.parse(sp.body)
      const r = await callTool('drawing_silhouette_projection', {
        body,
        direction: sp.direction,
        include_hidden: sp.include_hidden,
      })
      setSpR(r)
    } catch (e) { setSpE(e.message) } finally { setSpRun(false) }
  }, [sp])

  // ── drawing_oblique_projection ──────────────────────────────────────────
  const [op, setOp] = useState({
    body: DEFAULT_BODY,
    kind: 'cabinet',
    angle_deg: '45',
    scale_depth: '0.5',
  })
  const [opR, setOpR] = useState(null)
  const [opE, setOpE] = useState(null)
  const [opRun, setOpRun] = useState(false)

  const runOblique = useCallback(async () => {
    setOpRun(true); setOpE(null); setOpR(null)
    try {
      const body = JSON.parse(op.body)
      const r = await callTool('drawing_oblique_projection', {
        body,
        kind: op.kind,
        angle_deg: parseFloat(op.angle_deg),
        scale_depth: parseFloat(op.scale_depth),
      })
      setOpR(r)
    } catch (e) { setOpE(e.message) } finally { setOpRun(false) }
  }, [op])

  return (
    <div>
      <ToolWidget
        title="Auto 6-View Drawing (ISO 128-30)"
        icon={Layers}
        color="#3b82f6"
        result={avR}
        error={avE}
        running={avRun}
      >
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Body (JSON)</label>
          <textarea
            value={av.body}
            onChange={e => setAv(p => ({ ...p, body: e.target.value }))}
            disabled={avRun}
            rows={5}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <SelRow
          label="Projection type"
          value={av.projection_type}
          onChange={v => setAv(p => ({ ...p, projection_type: v }))}
          disabled={avRun}
          options={[
            { value: 'third_angle', label: 'Third angle (ANSI/ASME Y14.3)' },
            { value: 'first_angle', label: 'First angle (ISO/DIN)' },
          ]}
        />
        <CheckRow
          label="Include isometric view"
          value={av.include_iso}
          onChange={v => setAv(p => ({ ...p, include_iso: v }))}
          disabled={avRun}
        />
        <SelRow
          label="Sheet size"
          value={av.sheet}
          onChange={v => setAv(p => ({ ...p, sheet: v }))}
          disabled={avRun}
          options={[
            { value: 'A0', label: 'A0 (841×1189 mm)' },
            { value: 'A1', label: 'A1 (594×841 mm)' },
            { value: 'A2', label: 'A2 (420×594 mm)' },
            { value: 'A3', label: 'A3 (297×420 mm)' },
            { value: 'A4', label: 'A4 (210×297 mm)' },
            { value: 'LETTER', label: 'ANSI A / Letter' },
            { value: 'TABLOID', label: 'ANSI B / Tabloid' },
            { value: 'C', label: 'ANSI C' },
            { value: 'D', label: 'ANSI D' },
            { value: 'E', label: 'ANSI E' },
          ]}
        />
        <NumRow
          label="Scale (blank = auto)"
          value={av.scale}
          onChange={v => setAv(p => ({ ...p, scale: v }))}
          disabled={avRun}
        />
        <RunBtn onClick={runAutoViews} running={avRun} />
        {avR && !avRun && !avE && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Generated views</div>
            {Array.isArray(avR.views) && avR.views.map((v, i) => (
              <div key={i} style={{ ...s.mono, fontSize: 11, marginBottom: 2 }}>
                {v.name}: {v.visible_edges?.length ?? 0} visible edges, {v.hidden_edges?.length ?? 0} hidden
              </div>
            ))}
            {avR.svg && <SvgPreview data={avR.svg} />}
            {avR.svg_data && <SvgPreview data={avR.svg_data} />}
          </div>
        )}
      </ToolWidget>

      <ToolWidget
        title="Silhouette + Visible Edge Projection"
        icon={Scan}
        color="#8b5cf6"
        result={spR}
        error={spE}
        running={spRun}
      >
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Body (JSON)</label>
          <textarea
            value={sp.body}
            onChange={e => setSp(p => ({ ...p, body: e.target.value }))}
            disabled={spRun}
            rows={5}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <SelRow
          label="View direction"
          value={sp.direction}
          onChange={v => setSp(p => ({ ...p, direction: v }))}
          disabled={spRun}
          options={[
            { value: 'front',  label: 'Front (−Y)' },
            { value: 'back',   label: 'Back (+Y)' },
            { value: 'top',    label: 'Top (+Z)' },
            { value: 'bottom', label: 'Bottom (−Z)' },
            { value: 'left',   label: 'Left (−X)' },
            { value: 'right',  label: 'Right (+X)' },
            { value: 'iso',    label: 'Isometric' },
          ]}
        />
        <CheckRow
          label="Include hidden lines"
          value={sp.include_hidden}
          onChange={v => setSp(p => ({ ...p, include_hidden: v }))}
          disabled={spRun}
        />
        <RunBtn onClick={runSilhouette} running={spRun} />
        {spR && !spRun && !spE && (
          <div style={s.resultBox}>
            <ResultTable data={spR} skip={['svg', 'svg_data', 'edges', 'silhouette_edges', 'hidden_edges']} />
            {spR.svg && <SvgPreview data={spR.svg} />}
            {spR.svg_data && <SvgPreview data={spR.svg_data} />}
          </div>
        )}
      </ToolWidget>

      <ToolWidget
        title="Oblique Projection (Cabinet / Cavalier)"
        icon={SplitSquareHorizontal}
        color="#10b981"
        result={opR}
        error={opE}
        running={opRun}
      >
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Body (JSON)</label>
          <textarea
            value={op.body}
            onChange={e => setOp(p => ({ ...p, body: e.target.value }))}
            disabled={opRun}
            rows={5}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <SelRow
          label="Projection kind"
          value={op.kind}
          onChange={v => setOp(p => ({ ...p, kind: v }))}
          disabled={opRun}
          options={[
            { value: 'cabinet',   label: 'Cabinet (depth scale 0.5, Bertoline §11.5)' },
            { value: 'cavalier',  label: 'Cavalier (depth scale 1.0, Bertoline §11.5)' },
            { value: 'general',   label: 'General (custom depth scale)' },
          ]}
        />
        <NumRow
          label="Angle (deg)"
          value={op.angle_deg}
          onChange={v => setOp(p => ({ ...p, angle_deg: v }))}
          disabled={opRun}
        />
        <NumRow
          label="Depth scale"
          value={op.scale_depth}
          onChange={v => setOp(p => ({ ...p, scale_depth: v }))}
          disabled={opRun}
        />
        <RunBtn onClick={runOblique} running={opRun} />
        {opR && !opRun && !opE && (
          <div style={s.resultBox}>
            <ResultTable data={opR} skip={['svg', 'svg_data', 'edges', 'polylines']} />
            {opR.svg && <SvgPreview data={opR.svg} />}
            {opR.svg_data && <SvgPreview data={opR.svg_data} />}
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 2: Dimensions
// ---------------------------------------------------------------------------

function TabDimensions() {
  // ── drawing_auto_dimension_iso ──────────────────────────────────────────
  const [ad, setAd] = useState({
    view: JSON.stringify({
      name: 'front',
      edges: [
        { id: 'e1', start: [0, 0], end: [100, 0] },
        { id: 'e2', start: [100, 0], end: [100, 50] },
        { id: 'e3', start: [100, 50], end: [0, 50] },
        { id: 'e4', start: [0, 50], end: [0, 0] },
      ],
    }, null, 2),
    mode: 'chain',
  })
  const [adR, setAdR] = useState(null)
  const [adE, setAdE] = useState(null)
  const [adRun, setAdRun] = useState(false)

  const runAutoDim = useCallback(async () => {
    setAdRun(true); setAdE(null); setAdR(null)
    try {
      const view = JSON.parse(ad.view)
      const r = await callTool('drawing_auto_dimension_iso', { view, mode: ad.mode })
      setAdR(r)
    } catch (e) { setAdE(e.message) } finally { setAdRun(false) }
  }, [ad])

  // ── drawing_measurement_chain ───────────────────────────────────────────
  const [mc, setMc] = useState({
    body: DEFAULT_BODY,
  })
  const [mcR, setMcR] = useState(null)
  const [mcE, setMcE] = useState(null)
  const [mcRun, setMcRun] = useState(false)

  const runMeasChain = useCallback(async () => {
    setMcRun(true); setMcE(null); setMcR(null)
    try {
      const body = JSON.parse(mc.body)
      const r = await callTool('drawing_measurement_chain', { body })
      setMcR(r)
    } catch (e) { setMcE(e.message) } finally { setMcRun(false) }
  }, [mc])

  // ── drawing_validate_iso ────────────────────────────────────────────────
  const [vi, setVi] = useState({
    view: JSON.stringify({
      name: 'front',
      dimensions: [
        { id: 'd1', kind: 'linear', value: 100, extension_gap: 2, overshoot: 2, spacing: 10 },
      ],
    }, null, 2),
  })
  const [viR, setViR] = useState(null)
  const [viE, setViE] = useState(null)
  const [viRun, setViRun] = useState(false)

  const runValidate = useCallback(async () => {
    setViRun(true); setViE(null); setViR(null)
    try {
      const view = JSON.parse(vi.view)
      const r = await callTool('drawing_validate_iso', { view })
      setViR(r)
    } catch (e) { setViE(e.message) } finally { setViRun(false) }
  }, [vi])

  return (
    <div>
      <ToolWidget
        title="ISO 129-1:2018 Auto-Dimension"
        icon={Ruler}
        color="#3b82f6"
        result={adR}
        error={adE}
        running={adRun}
      >
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 6 }}>
          Chain (§5.1): sequential; Baseline (§5.1): all from datum; Mixed: auto-select.
          Extension gap = 2 mm (§5.4), overshoot = 2 mm, spacing = 10 mm (§5.4).
        </div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>View (JSON)</label>
          <textarea
            value={ad.view}
            onChange={e => setAd(p => ({ ...p, view: e.target.value }))}
            disabled={adRun}
            rows={8}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <SelRow
          label="Dimensioning mode"
          value={ad.mode}
          onChange={v => setAd(p => ({ ...p, mode: v }))}
          disabled={adRun}
          options={[
            { value: 'chain',    label: 'Chain (§5.1)' },
            { value: 'baseline', label: 'Baseline (§5.1)' },
            { value: 'mixed',    label: 'Mixed' },
          ]}
        />
        <RunBtn onClick={runAutoDim} running={adRun} />
        {adR && !adRun && !adE && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Generated dimensions</div>
            {Array.isArray(adR.dimensions) && adR.dimensions.map((d, i) => (
              <div key={i} style={{ ...s.mono, fontSize: 11, marginBottom: 2 }}>
                {d.id ?? `d${i}`}: {d.kind ?? 'linear'} {fmt(d.value, 2)} mm
              </div>
            ))}
            {adR.dimension_count != null && (
              <div style={{ ...s.mono, fontSize: 11, color: '#34d399', marginTop: 4 }}>
                Total: {adR.dimension_count} dimensions
              </div>
            )}
          </div>
        )}
      </ToolWidget>

      <ToolWidget
        title="Inspection Measurement Chain (ASME Y14.5 §3.4 + ISO 129)"
        icon={AlignCenter}
        color="#f59e0b"
        result={mcR}
        error={mcE}
        running={mcRun}
      >
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 6 }}>
          Extracts A/B/C datum-frame, per-feature DOF coverage, and detects redundant dims
          (ISO 129-1 §6 no-closed-chain rule).
        </div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Body (JSON)</label>
          <textarea
            value={mc.body}
            onChange={e => setMc(p => ({ ...p, body: e.target.value }))}
            disabled={mcRun}
            rows={6}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <RunBtn onClick={runMeasChain} running={mcRun} />
        {mcR && !mcRun && !mcE && (
          <div style={s.resultBox}>
            <ResultTable data={mcR} skip={['dimensions', 'chain', 'features', 'datums']} />
            {Array.isArray(mcR.chain) && (
              <>
                <div style={{ ...s.subhead, marginTop: 6 }}>Measurement chain</div>
                {mcR.chain.map((item, i) => (
                  <div key={i} style={{ ...s.mono, fontSize: 11, marginBottom: 2 }}>
                    {item.feature ?? `item ${i}`}: {item.dimension ?? ''} {item.value != null ? fmt(item.value, 3) + ' mm' : ''}
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </ToolWidget>

      <ToolWidget
        title="Validate ISO 129-1:2018 Compliance"
        icon={FileSearch}
        color="#ef4444"
        result={viR}
        error={viE}
        running={viRun}
      >
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 6 }}>
          Checks extension-line lengths, spacing (10 mm minimum), leader angles (preferred 15°/30°/45°/60°),
          and dimension-line orientation per ISO 129-1:2018.
        </div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>View (JSON)</label>
          <textarea
            value={vi.view}
            onChange={e => setVi(p => ({ ...p, view: e.target.value }))}
            disabled={viRun}
            rows={8}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <RunBtn onClick={runValidate} running={viRun} />
        {viR && !viRun && !viE && (
          <div style={s.resultBox}>
            {viR.valid != null && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                {viR.valid
                  ? <CheckCircle size={14} style={{ color: '#34d399' }} />
                  : <AlertTriangle size={14} style={{ color: '#fbbf24' }} />}
                <span style={{ fontWeight: 600, color: viR.valid ? '#34d399' : '#fbbf24' }}>
                  {viR.valid ? 'ISO 129-1:2018 compliant' : 'Compliance issues found'}
                </span>
              </div>
            )}
            <ResultTable data={viR} skip={['violations', 'warnings']} />
            {Array.isArray(viR.violations) && viR.violations.length > 0 && (
              <>
                <div style={{ ...s.subhead, color: '#fca5a5', marginTop: 6 }}>Violations</div>
                {viR.violations.map((v, i) => (
                  <div key={i} style={{ ...s.mono, fontSize: 11, color: '#fca5a5', marginBottom: 2 }}>• {v}</div>
                ))}
              </>
            )}
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 3: Annotations
// ---------------------------------------------------------------------------

function TabAnnotations() {
  // Text notes
  const [note, setNote] = useState({ text: '', x: '20', y: '20', font_size: '3.5' })
  const [noteItems, setNoteItems] = useState([])

  const addNote = useCallback(() => {
    if (!note.text.trim()) return
    setNoteItems(prev => [
      ...prev,
      { text: note.text, x: parseFloat(note.x), y: parseFloat(note.y), font_size: parseFloat(note.font_size) },
    ])
    setNote(p => ({ ...p, text: '' }))
  }, [note])

  // Balloons / leaders
  const [balloon, setBalloon] = useState({ label: '1', x: '60', y: '40', radius: '5' })
  const [balloonItems, setBalloonItems] = useState([])

  const addBalloon = useCallback(() => {
    if (!balloon.label.trim()) return
    setBalloonItems(prev => [
      ...prev,
      { label: balloon.label, x: parseFloat(balloon.x), y: parseFloat(balloon.y), radius: parseFloat(balloon.radius) },
    ])
    setBalloon(p => ({ ...p, label: String(parseInt(balloon.label || '0', 10) + 1) }))
  }, [balloon])

  // Inspection report
  const [ir, setIr] = useState({
    body: DEFAULT_BODY,
    format: 'iso129',
  })
  const [irR, setIrR] = useState(null)
  const [irE, setIrE] = useState(null)
  const [irRun, setIrRun] = useState(false)

  const runInspReport = useCallback(async () => {
    setIrRun(true); setIrE(null); setIrR(null)
    try {
      const body = JSON.parse(ir.body)
      const r = await callTool('drawing_inspection_report', { body, format: ir.format })
      setIrR(r)
    } catch (e) { setIrE(e.message) } finally { setIrRun(false) }
  }, [ir])

  // Simple SVG preview of accumulated annotations
  const annotSvg = (() => {
    const w = 200, h = 120
    const notes = noteItems.map(n =>
      `<text x="${n.x}" y="${n.y}" font-size="${n.font_size}" fill="#60a5fa">${n.text}</text>`
    ).join('')
    const balloons = balloonItems.map(b =>
      `<circle cx="${b.x}" cy="${b.y}" r="${b.radius}" fill="none" stroke="#34d399" stroke-width="0.5"/>` +
      `<text x="${b.x}" y="${parseFloat(b.y) + parseFloat(b.radius) * 0.4}" text-anchor="middle" font-size="${b.radius * 0.8}" fill="#34d399">${b.label}</text>`
    ).join('')
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="background:#0f172a;border-radius:4px">${notes}${balloons}</svg>`
  })()

  return (
    <div>
      {/* Text notes */}
      <div style={{ ...s.section, borderLeft: '3px solid #3b82f6' }}>
        <div style={s.sectionTitle}>
          <StickyNote size={12} style={{ color: '#3b82f6' }} />
          Text Notes
        </div>
        <TextRow
          label="Note text"
          value={note.text}
          onChange={v => setNote(p => ({ ...p, text: v }))}
          placeholder="e.g. ALL DIMS IN MM"
        />
        <NumRow label="X position (mm)" value={note.x} onChange={v => setNote(p => ({ ...p, x: v }))} />
        <NumRow label="Y position (mm)" value={note.y} onChange={v => setNote(p => ({ ...p, y: v }))} />
        <NumRow label="Font size (mm)" value={note.font_size} onChange={v => setNote(p => ({ ...p, font_size: v }))} />
        <button
          onClick={addNote}
          style={{ ...s.button, background: '#1e40af', marginTop: 6 }}
        >
          Add Note
        </button>
        {noteItems.length > 0 && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Queued notes ({noteItems.length})</div>
            {noteItems.map((n, i) => (
              <div key={i} style={{ ...s.mono, fontSize: 11 }}>({n.x}, {n.y}): {n.text}</div>
            ))}
          </div>
        )}
      </div>

      {/* Balloons */}
      <div style={{ ...s.section, borderLeft: '3px solid #10b981' }}>
        <div style={s.sectionTitle}>
          <Layers size={12} style={{ color: '#10b981' }} />
          Balloons / Leaders
        </div>
        <TextRow
          label="Balloon label"
          value={balloon.label}
          onChange={v => setBalloon(p => ({ ...p, label: v }))}
          placeholder="e.g. 1"
        />
        <NumRow label="X position (mm)" value={balloon.x} onChange={v => setBalloon(p => ({ ...p, x: v }))} />
        <NumRow label="Y position (mm)" value={balloon.y} onChange={v => setBalloon(p => ({ ...p, y: v }))} />
        <NumRow label="Radius (mm)" value={balloon.radius} onChange={v => setBalloon(p => ({ ...p, radius: v }))} />
        <button
          onClick={addBalloon}
          style={{ ...s.button, background: '#064e3b', marginTop: 6 }}
        >
          Add Balloon
        </button>
        {balloonItems.length > 0 && (
          <div style={s.resultBox}>
            <div style={s.subhead}>Queued balloons ({balloonItems.length})</div>
            {balloonItems.map((b, i) => (
              <div key={i} style={{ ...s.mono, fontSize: 11 }}>#{b.label} at ({b.x}, {b.y}) r={b.radius}</div>
            ))}
          </div>
        )}
      </div>

      {/* Live SVG preview */}
      {(noteItems.length > 0 || balloonItems.length > 0) && (
        <div style={{ ...s.section, borderLeft: '3px solid #6366f1' }}>
          <div style={s.sectionTitle}>
            <LayoutDashboard size={12} style={{ color: '#6366f1' }} />
            Annotation Preview
          </div>
          <div style={s.svgBox}>
            <div dangerouslySetInnerHTML={{ __html: annotSvg }} />
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button
              onClick={() => setNoteItems([])}
              style={{ ...s.button, background: '#374151', fontSize: 11, padding: '3px 8px' }}
            >
              Clear notes
            </button>
            <button
              onClick={() => setBalloonItems([])}
              style={{ ...s.button, background: '#374151', fontSize: 11, padding: '3px 8px' }}
            >
              Clear balloons
            </button>
          </div>
        </div>
      )}

      {/* Inspection Report */}
      <ToolWidget
        title="Inspection Report (ISO 129-1 / ASME Y14.5)"
        icon={FileText}
        color="#f97316"
        result={irR}
        error={irE}
        running={irRun}
      >
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 6 }}>
          Renders a structured inspection report from a measurement chain. Suitable for QC
          sign-off documentation.
        </div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Body (JSON)</label>
          <textarea
            value={ir.body}
            onChange={e => setIr(p => ({ ...p, body: e.target.value }))}
            disabled={irRun}
            rows={5}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <SelRow
          label="Report format"
          value={ir.format}
          onChange={v => setIr(p => ({ ...p, format: v }))}
          disabled={irRun}
          options={[
            { value: 'iso129',  label: 'ISO 129-1:2018' },
            { value: 'asme145', label: 'ASME Y14.5-2018' },
          ]}
        />
        <RunBtn onClick={runInspReport} running={irRun} label="Generate Report" />
        {irR && !irRun && !irE && (
          <div style={s.resultBox}>
            <ResultTable data={irR} skip={['report', 'text', 'lines']} />
            {typeof irR.report === 'string' && (
              <pre style={{ ...s.mono, fontSize: 10, marginTop: 6, whiteSpace: 'pre-wrap', color: '#d1d5db' }}>
                {irR.report}
              </pre>
            )}
            {typeof irR.text === 'string' && (
              <pre style={{ ...s.mono, fontSize: 10, marginTop: 6, whiteSpace: 'pre-wrap', color: '#d1d5db' }}>
                {irR.text}
              </pre>
            )}
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 4: Sheet Layout
// ---------------------------------------------------------------------------

// Standard sheet sizes (mm)
const SHEET_SIZES = {
  A0: [841, 1189], A1: [594, 841], A2: [420, 594], A3: [297, 420], A4: [210, 297],
  LETTER: [216, 279], TABLOID: [279, 432], C: [432, 559], D: [559, 864], E: [864, 1118],
}

function TabSheetLayout() {
  const [sheet, setSheet] = useState('A3')
  const [landscape, setLandscape] = useState(false)
  const [scale, setScale] = useState('1:1')
  const [titleBlock, setTitleBlock] = useState({
    title: '',
    drawn_by: '',
    date: new Date().toISOString().slice(0, 10),
    revision: 'A',
    material: '',
    finish: '',
    tolerances: 'ISO 2768-m',
    projection: 'third_angle',
    company: '',
    part_number: '',
    sheet_of: '1 of 1',
  })

  const dims = SHEET_SIZES[sheet] ?? [297, 420]
  const [w, h] = landscape ? [dims[1], dims[0]] : dims

  // Mini sheet preview SVG
  const previewScale = 0.35
  const pw = w * previewScale
  const ph = h * previewScale
  // Title block occupies bottom 20 mm
  const tbH = 20 * previewScale
  const tbY = ph - tbH

  const previewSvg = `
<svg xmlns="http://www.w3.org/2000/svg" width="${pw}" height="${ph}" viewBox="0 0 ${pw} ${ph}" style="background:#0f172a;border-radius:4px">
  <!-- Sheet border -->
  <rect x="1" y="1" width="${pw - 2}" height="${ph - 2}" fill="none" stroke="#374151" stroke-width="0.8"/>
  <!-- Title block border -->
  <rect x="1" y="${tbY}" width="${pw - 2}" height="${tbH}" fill="#1f2937" stroke="#374151" stroke-width="0.5"/>
  <!-- Title block fields -->
  <text x="4" y="${tbY + 6}" font-size="4" fill="#9ca3af">${titleBlock.title || 'UNTITLED'}</text>
  <text x="4" y="${tbY + 12}" font-size="3" fill="#6b7280">${titleBlock.part_number || 'P/N:'} | ${titleBlock.material || 'MAT:'} | ${titleBlock.revision || 'REV:'}</text>
  <text x="4" y="${tbY + 17}" font-size="3" fill="#4b5563">${titleBlock.drawn_by || 'DRAWN:'} ${titleBlock.date} | ${titleBlock.tolerances}</text>
  <!-- Scale note -->
  <text x="${pw - 4}" y="${tbY + 6}" font-size="3.5" fill="#6b7280" text-anchor="end">SCALE ${scale}</text>
  <!-- Sheet size tag -->
  <text x="${pw - 4}" y="${tbY + 12}" font-size="3" fill="#4b5563" text-anchor="end">${sheet} ${landscape ? 'L' : 'P'}</text>
</svg>`

  return (
    <div>
      <div style={{ ...s.section, borderLeft: '3px solid #3b82f6' }}>
        <div style={s.sectionTitle}>
          <LayoutDashboard size={12} style={{ color: '#3b82f6' }} />
          Sheet Setup
        </div>
        <SelRow
          label="Sheet size"
          value={sheet}
          onChange={setSheet}
          options={Object.entries(SHEET_SIZES).map(([k, [sw, sh]]) => ({
            value: k, label: `${k} (${sw}×${sh} mm)`,
          }))}
        />
        <CheckRow label="Landscape orientation" value={landscape} onChange={setLandscape} />
        <SelRow
          label="Drawing scale"
          value={scale}
          onChange={setScale}
          options={[
            { value: '1:1', label: '1:1 (full size)' },
            { value: '1:2', label: '1:2' },
            { value: '1:5', label: '1:5' },
            { value: '1:10', label: '1:10' },
            { value: '1:20', label: '1:20' },
            { value: '1:50', label: '1:50' },
            { value: '2:1', label: '2:1 (enlarged)' },
            { value: '5:1', label: '5:1 (enlarged)' },
          ]}
        />
        <div style={{ ...s.mono, fontSize: 10, color: '#6b7280', marginTop: 4, marginBottom: 8 }}>
          Active: {sheet} {landscape ? 'landscape' : 'portrait'} — {w} × {h} mm
        </div>

        {/* Sheet preview */}
        <div style={s.svgBox}>
          <div style={s.subhead}>Sheet preview</div>
          <div dangerouslySetInnerHTML={{ __html: previewSvg }} />
        </div>
      </div>

      <div style={{ ...s.section, borderLeft: '3px solid #f59e0b' }}>
        <div style={s.sectionTitle}>
          <FileText size={12} style={{ color: '#f59e0b' }} />
          Title Block Fields
        </div>
        {[
          ['Drawing title',  'title',       'e.g. Bracket Assembly'],
          ['Part number',    'part_number', 'e.g. BRK-001-A'],
          ['Drawn by',       'drawn_by',    'e.g. J. Smith'],
          ['Date',           'date',        'YYYY-MM-DD'],
          ['Revision',       'revision',    'e.g. A'],
          ['Material',       'material',    'e.g. Al 6061-T6'],
          ['Surface finish', 'finish',      'e.g. Ra 1.6'],
          ['Tolerances',     'tolerances',  'e.g. ISO 2768-m'],
          ['Company',        'company',     'e.g. Acme Corp'],
          ['Sheet',          'sheet_of',    'e.g. 1 of 3'],
        ].map(([label, key, ph]) => (
          <TextRow
            key={key}
            label={label}
            value={titleBlock[key]}
            onChange={v => setTitleBlock(p => ({ ...p, [key]: v }))}
            placeholder={ph}
          />
        ))}
        <SelRow
          label="Projection symbol"
          value={titleBlock.projection}
          onChange={v => setTitleBlock(p => ({ ...p, projection: v }))}
          options={[
            { value: 'third_angle', label: 'Third angle ⊕ (ANSI/ASME)' },
            { value: 'first_angle', label: 'First angle ⊕ (ISO/DIN)' },
          ]}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 5: Export
// ---------------------------------------------------------------------------

function TabExport() {
  // PDF compilation
  const [pdf, setPdf] = useState({
    body: DEFAULT_BODY,
    sheet: 'A3',
    projection_type: 'third_angle',
    include_dimensions: true,
    include_title_block: true,
    title: '',
  })
  const [pdfR, setPdfR] = useState(null)
  const [pdfE, setPdfE] = useState(null)
  const [pdfRun, setPdfRun] = useState(false)

  const runPdf = useCallback(async () => {
    setPdfRun(true); setPdfE(null); setPdfR(null)
    try {
      const body = JSON.parse(pdf.body)
      // drawing_compile_pdf may not exist — degrade gracefully
      const r = await callTool('drawing_compile_pdf', {
        body,
        sheet: pdf.sheet,
        projection_type: pdf.projection_type,
        include_dimensions: pdf.include_dimensions,
        include_title_block: pdf.include_title_block,
        title: pdf.title || undefined,
      })
      setPdfR(r)
    } catch (e) { setPdfE(e.message) } finally { setPdfRun(false) }
  }, [pdf])

  // DXF / SVG export — dispatches drawing_auto_views then signals download
  const [exp, setExp] = useState({
    body: DEFAULT_BODY,
    format: 'svg',
    sheet: 'A3',
    projection_type: 'third_angle',
  })
  const [expR, setExpR] = useState(null)
  const [expE, setExpE] = useState(null)
  const [expRun, setExpRun] = useState(false)

  const runExport = useCallback(async () => {
    setExpRun(true); setExpE(null); setExpR(null)
    try {
      const body = JSON.parse(exp.body)
      const r = await callTool('drawing_auto_views', {
        body,
        sheet: exp.sheet,
        projection_type: exp.projection_type,
        include_iso: true,
        output_format: exp.format,
      })
      setExpR(r)

      // If we got back a downloadable blob, trigger browser download
      const content = r.svg || r.svg_data || r.dxf
      if (content) {
        const mime = exp.format === 'dxf' ? 'application/dxf' : 'image/svg+xml'
        const ext = exp.format === 'dxf' ? 'dxf' : 'svg'
        const blob = new Blob([content], { type: mime })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `drawing.${ext}`; a.click()
        URL.revokeObjectURL(url)
      }
    } catch (e) { setExpE(e.message) } finally { setExpRun(false) }
  }, [exp])

  // Inspection report download
  const [irExp, setIrExp] = useState({
    body: DEFAULT_BODY,
    format: 'iso129',
  })
  const [irExpR, setIrExpR] = useState(null)
  const [irExpE, setIrExpE] = useState(null)
  const [irExpRun, setIrExpRun] = useState(false)

  const runIrExport = useCallback(async () => {
    setIrExpRun(true); setIrExpE(null); setIrExpR(null)
    try {
      const body = JSON.parse(irExp.body)
      const r = await callTool('drawing_inspection_report', { body, format: irExp.format })
      setIrExpR(r)
      const text = r.report || r.text || JSON.stringify(r, null, 2)
      const blob = new Blob([text], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `inspection_report.txt`; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { setIrExpE(e.message) } finally { setIrExpRun(false) }
  }, [irExp])

  return (
    <div>
      {/* PDF */}
      <ToolWidget
        title="Compile to PDF"
        icon={Download}
        color="#3b82f6"
        result={pdfR}
        error={pdfE}
        running={pdfRun}
      >
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 6 }}>
          Calls <code style={s.mono}>drawing_compile_pdf</code> — generates a multi-view
          sheet ready for print. PDF data returned as base64 when the backend supports it.
        </div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Body (JSON)</label>
          <textarea
            value={pdf.body}
            onChange={e => setPdf(p => ({ ...p, body: e.target.value }))}
            disabled={pdfRun}
            rows={5}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <SelRow
          label="Sheet size"
          value={pdf.sheet}
          onChange={v => setPdf(p => ({ ...p, sheet: v }))}
          disabled={pdfRun}
          options={[
            { value: 'A0', label: 'A0' }, { value: 'A1', label: 'A1' },
            { value: 'A2', label: 'A2' }, { value: 'A3', label: 'A3' },
            { value: 'A4', label: 'A4' }, { value: 'LETTER', label: 'Letter' },
          ]}
        />
        <SelRow
          label="Projection type"
          value={pdf.projection_type}
          onChange={v => setPdf(p => ({ ...p, projection_type: v }))}
          disabled={pdfRun}
          options={[
            { value: 'third_angle', label: 'Third angle (ANSI)' },
            { value: 'first_angle', label: 'First angle (ISO)' },
          ]}
        />
        <CheckRow
          label="Include dimensions"
          value={pdf.include_dimensions}
          onChange={v => setPdf(p => ({ ...p, include_dimensions: v }))}
          disabled={pdfRun}
        />
        <CheckRow
          label="Include title block"
          value={pdf.include_title_block}
          onChange={v => setPdf(p => ({ ...p, include_title_block: v }))}
          disabled={pdfRun}
        />
        <TextRow
          label="Drawing title"
          value={pdf.title}
          onChange={v => setPdf(p => ({ ...p, title: v }))}
          placeholder="e.g. Bracket Assembly"
          disabled={pdfRun}
        />
        <RunBtn onClick={runPdf} running={pdfRun} label="Compile PDF" />
        {pdfR && !pdfRun && !pdfE && (
          <div style={s.resultBox}>
            <ResultTable data={pdfR} skip={['pdf_base64', 'pdf', 'svg']} />
            {pdfR.pdf_base64 && (
              <button
                onClick={() => {
                  const a = document.createElement('a')
                  a.href = 'data:application/pdf;base64,' + pdfR.pdf_base64
                  a.download = 'drawing.pdf'; a.click()
                }}
                style={{ ...s.button, background: '#1d4ed8', marginTop: 6 }}
              >
                <Download size={12} /> Download PDF
              </button>
            )}
          </div>
        )}
      </ToolWidget>

      {/* SVG / DXF */}
      <ToolWidget
        title="Export SVG / DXF"
        icon={Download}
        color="#10b981"
        result={expR}
        error={expE}
        running={expRun}
      >
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 6 }}>
          Generates views via <code style={s.mono}>drawing_auto_views</code> and downloads
          the result. DXF output available when the backend returns a <code>dxf</code> key.
        </div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Body (JSON)</label>
          <textarea
            value={exp.body}
            onChange={e => setExp(p => ({ ...p, body: e.target.value }))}
            disabled={expRun}
            rows={5}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <SelRow
          label="Export format"
          value={exp.format}
          onChange={v => setExp(p => ({ ...p, format: v }))}
          disabled={expRun}
          options={[
            { value: 'svg', label: 'SVG (vector, browser-ready)' },
            { value: 'dxf', label: 'DXF (CAD exchange)' },
          ]}
        />
        <SelRow
          label="Sheet size"
          value={exp.sheet}
          onChange={v => setExp(p => ({ ...p, sheet: v }))}
          disabled={expRun}
          options={[
            { value: 'A0', label: 'A0' }, { value: 'A1', label: 'A1' },
            { value: 'A2', label: 'A2' }, { value: 'A3', label: 'A3' },
            { value: 'A4', label: 'A4' }, { value: 'LETTER', label: 'Letter' },
          ]}
        />
        <SelRow
          label="Projection type"
          value={exp.projection_type}
          onChange={v => setExp(p => ({ ...p, projection_type: v }))}
          disabled={expRun}
          options={[
            { value: 'third_angle', label: 'Third angle (ANSI)' },
            { value: 'first_angle', label: 'First angle (ISO)' },
          ]}
        />
        <RunBtn onClick={runExport} running={expRun} label="Export + Download" />
        {expR && !expRun && !expE && (
          <div style={s.successBox}>
            <CheckCircle size={12} style={{ flexShrink: 0, marginTop: 2 }} />
            <span>Export completed — browser download triggered if content was returned.</span>
          </div>
        )}
      </ToolWidget>

      {/* Inspection report download */}
      <ToolWidget
        title="Inspection Report Download"
        icon={FileSearch}
        color="#f59e0b"
        result={irExpR}
        error={irExpE}
        running={irExpRun}
      >
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 6 }}>
          Generate and download an inspection report as a text file for QC / supplier sign-off.
        </div>
        <div style={s.row}>
          <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Body (JSON)</label>
          <textarea
            value={irExp.body}
            onChange={e => setIrExp(p => ({ ...p, body: e.target.value }))}
            disabled={irExpRun}
            rows={5}
            style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }}
          />
        </div>
        <SelRow
          label="Report format"
          value={irExp.format}
          onChange={v => setIrExp(p => ({ ...p, format: v }))}
          disabled={irExpRun}
          options={[
            { value: 'iso129',  label: 'ISO 129-1:2018' },
            { value: 'asme145', label: 'ASME Y14.5-2018' },
          ]}
        />
        <RunBtn onClick={runIrExport} running={irExpRun} label="Generate + Download" />
        {irExpR && !irExpRun && !irExpE && (
          <div style={s.successBox}>
            <CheckCircle size={12} style={{ flexShrink: 0, marginTop: 2 }} />
            <span>Report downloaded as inspection_report.txt.</span>
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root component
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'views',       label: 'Views',        Icon: Layers },
  { id: 'dimensions',  label: 'Dimensions',   Icon: Ruler },
  { id: 'annotations', label: 'Annotations',  Icon: StickyNote },
  { id: 'layout',      label: 'Sheet Layout', Icon: LayoutDashboard },
  { id: 'export',      label: 'Export',       Icon: Download },
]

export default function DrawingPanel() {
  const [activeTab, setActiveTab] = useState('views')

  return (
    <div style={s.root}>
      {/* Header */}
      <div style={s.header}>
        <FileText size={16} style={{ color: '#3b82f6' }} />
        <span style={s.title}>2D Engineering Drawings</span>
        <span style={{
          ...s.badge,
          background: '#1e3a5f',
          color: '#93c5fd',
          marginLeft: 4,
        }}>
          8 tools · ISO 128-30 / ISO 129-1:2018
        </span>
      </div>

      {/* Tab bar */}
      <div style={s.tabs}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            style={{
              ...s.tab,
              ...(activeTab === t.id ? s.tabActive : {}),
              display: 'flex', alignItems: 'center', gap: 4,
            }}
          >
            <t.Icon size={11} />
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'views'       && <TabViews />}
      {activeTab === 'dimensions'  && <TabDimensions />}
      {activeTab === 'annotations' && <TabAnnotations />}
      {activeTab === 'layout'      && <TabSheetLayout />}
      {activeTab === 'export'      && <TabExport />}
    </div>
  )
}
