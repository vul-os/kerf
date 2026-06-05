// DrawingSheetPanel.jsx — Full 2D drawing sheet editor.
//
// Covers the capability gap: section views (cutting plane + hatch),
// detail views (magnified crop), and title block.
//
// Backend tools (all via POST /api/tools/call):
//   drawing_auto_views         — 6-view orthographic drawing
//   drawing_section_view       — section cut + ISO 128-50 hatch
//   drawing_detail_view        — magnified circular crop
//   drawing_title_block        — ISO 7200:2004 title block
//
// The panel has four tabs:
//   Sheet       — six-view auto-layout (third/first angle, A0–A4)
//   Section     — cutting-plane section view with hatch
//   Detail      — zoomed detail view
//   Title Block — ISO 7200:2004 title block fields
//
// All results include an inline SVG preview where the tool returns one.

import { useState, useCallback } from 'react'
import {
  FileText, Scissors, ZoomIn, LayoutDashboard,
  AlertTriangle, CheckCircle, Loader2, Play,
  ChevronDown, ChevronUp,
} from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Shared style tokens
// ---------------------------------------------------------------------------

const s = {
  root:        { background: '#111827', padding: '12px', fontSize: 12, color: '#e5e7eb', minHeight: 200 },
  header:      { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 },
  title:       { fontWeight: 600, fontSize: 13, color: '#f9fafb' },
  tabs:        { display: 'flex', gap: 2, marginBottom: 10, flexWrap: 'wrap' },
  tab:         { padding: '4px 10px', borderRadius: 4, border: '1px solid #374151', background: '#1f2937', color: '#9ca3af', cursor: 'pointer', fontSize: 11 },
  tabActive:   { background: '#1d4ed8', borderColor: '#3b82f6', color: '#fff' },
  section:     { background: '#1f2937', borderRadius: 6, padding: '10px', marginBottom: 8 },
  sTitle:      { display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600, marginBottom: 8, color: '#d1d5db', fontSize: 11 },
  row:         { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 },
  label:       { color: '#9ca3af', width: 140, flexShrink: 0, fontSize: 11 },
  input:       { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12, minWidth: 0 },
  select:      { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12 },
  btn:         { display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 5, border: 'none', color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 500, background: '#1e40af', marginTop: 6 },
  btnDis:      { opacity: 0.5, cursor: 'not-allowed' },
  errorBox:    { display: 'flex', alignItems: 'flex-start', gap: 6, background: '#450a0a', borderRadius: 5, padding: '8px', color: '#fca5a5', marginTop: 8 },
  infoBox:     { display: 'flex', alignItems: 'center', gap: 6, background: '#1e3a5f', borderRadius: 5, padding: '8px', color: '#93c5fd', marginTop: 8 },
  resultBox:   { background: '#0f172a', borderRadius: 4, padding: '8px', marginTop: 6, fontFamily: 'monospace', fontSize: 11 },
  subhead:     { color: '#60a5fa', fontWeight: 600, marginBottom: 4, fontSize: 11 },
  svgBox:      { background: '#0f172a', borderRadius: 4, padding: '8px', marginTop: 6, overflowX: 'auto' },
  table:       { width: '100%', borderCollapse: 'collapse', marginTop: 4 },
  td:          { padding: '3px 6px', borderBottom: '1px solid #1f2937' },
  mono:        { fontFamily: 'monospace' },
  divider:     { borderTop: '1px solid #374151', margin: '8px 0' },
  badge:       { padding: '2px 6px', borderRadius: 3, fontSize: 10, fontWeight: 600 },
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
    return Math.abs(v) > 1e4 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(3) : v.toFixed(d)
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
        style={{ ...s.sTitle, justifyContent: 'space-between', cursor: 'pointer' }}
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
              <ResultTable data={result} skip={['views', 'visible_edges', 'hidden_edges', 'hatch_lines',
                'contour_edges', 'clipped_visible', 'clipped_hidden', 'fields', 'title_block',
                'cutting_plane_marker', 'detail_circle', 'detail_label_annotation']} />
            </div>
          )}
        </>
      )}
    </div>
  )
}

function RunBtn({ onClick, running, disabled, label = 'Run' }) {
  return (
    <button onClick={onClick} disabled={running || disabled}
      style={{ ...s.btn, ...(running || disabled ? s.btnDis : {}) }}>
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
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

function NumRow({ label, value, onChange, step = 'any', disabled, placeholder }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <input type="number" value={value} onChange={e => onChange(e.target.value)}
        step={step} disabled={disabled} placeholder={placeholder} style={s.input} />
    </div>
  )
}

function TextRow({ label, value, onChange, placeholder, disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <input type="text" value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder} disabled={disabled} style={s.input} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Minimal SVG preview: builds an SVG from polylines
// ---------------------------------------------------------------------------

function PolylineSvg({ visible = [], hidden = [], hatch = [], contour = [], maxPx = 300 }) {
  // Gather all points to compute bounding box
  const allPts = [
    ...visible.flat(), ...hidden.flat(), ...hatch.flat(), ...contour.flat(),
  ]
  if (!allPts.length) return <div style={{ color: '#6b7280', fontSize: 11, marginTop: 6 }}>No geometry</div>

  const xs = allPts.map(p => p[0])
  const ys = allPts.map(p => p[1])
  const xmin = Math.min(...xs), xmax = Math.max(...xs)
  const ymin = Math.min(...ys), ymax = Math.max(...ys)
  const W = xmax - xmin || 1
  const H = ymax - ymin || 1
  const scale = maxPx / Math.max(W, H)
  const pad = 4

  const tx = p => ((p[0] - xmin) * scale + pad).toFixed(2)
  const ty = p => ((ymax - p[1]) * scale + pad).toFixed(2)

  const polyPts = (seg) => seg.map(p => `${tx(p)},${ty(p)}`).join(' ')
  const svgW = W * scale + pad * 2
  const svgH = H * scale + pad * 2

  return (
    <div style={s.svgBox}>
      <div style={s.subhead}>Preview</div>
      <svg width={svgW} height={svgH} style={{ display: 'block', maxWidth: '100%' }}>
        {visible.map((seg, i) => (
          <polyline key={`v${i}`} points={polyPts(seg)}
            stroke="#e5e7eb" strokeWidth="0.8" fill="none" strokeLinecap="round" />
        ))}
        {hidden.map((seg, i) => (
          <polyline key={`h${i}`} points={polyPts(seg)}
            stroke="#6b7280" strokeWidth="0.5" fill="none" strokeDasharray="2,1" />
        ))}
        {contour.map((seg, i) => (
          <polyline key={`c${i}`} points={polyPts(seg)}
            stroke="#60a5fa" strokeWidth="1" fill="none" />
        ))}
        {hatch.map((seg, i) => (
          <polyline key={`ht${i}`} points={polyPts(seg)}
            stroke="#f59e0b" strokeWidth="0.4" fill="none" />
        ))}
      </svg>
      <div style={{ fontSize: 10, color: '#4b5563', marginTop: 2 }}>
        <span style={{ color: '#e5e7eb' }}>— visible</span>
        {hidden.length > 0 && <span style={{ color: '#6b7280', marginLeft: 8 }}>-- hidden</span>}
        {contour.length > 0 && <span style={{ color: '#60a5fa', marginLeft: 8 }}>— contour</span>}
        {hatch.length > 0 && <span style={{ color: '#f59e0b', marginLeft: 8 }}>— hatch</span>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Default mesh JSON (a simple box)
// ---------------------------------------------------------------------------

const DEFAULT_MESH_JSON = JSON.stringify({
  vertices: [
    [-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],
    [-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1],
  ],
  triangles: [
    [0,2,1],[0,3,2],[4,5,6],[4,6,7],
    [0,1,5],[0,5,4],[1,2,6],[1,6,5],
    [2,3,7],[2,7,6],[3,0,4],[3,4,7],
  ],
}, null, 2)

// ---------------------------------------------------------------------------
// TAB: Sheet (6-view drawing)
// ---------------------------------------------------------------------------

function TabSheet() {
  const [mesh, setMesh] = useState(DEFAULT_MESH_JSON)
  const [projType, setProjType] = useState('third_angle')
  const [includeIso, setIncludeIso] = useState(true)
  const [sheet, setSheet] = useState('A3')
  const [scale, setScale] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)

  const run = useCallback(async () => {
    setRunning(true); setError(null); setResult(null)
    try {
      const meshObj = JSON.parse(mesh)
      const args = {
        mesh: meshObj,
        projection_type: projType,
        include_iso: includeIso,
        sheet,
      }
      if (scale) args.scale = parseFloat(scale)
      const r = await callTool('drawing_auto_views', args)
      setResult(r)
    } catch (e) { setError(e.message) } finally { setRunning(false) }
  }, [mesh, projType, includeIso, sheet, scale])

  return (
    <ToolWidget title="6-View Drawing Sheet (ISO 128-30)" icon={LayoutDashboard}
      color="#3b82f6" result={result} error={error} running={running}>
      <div style={s.row}>
        <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Mesh (JSON)</label>
        <textarea value={mesh} onChange={e => setMesh(e.target.value)} disabled={running}
          rows={6} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
      </div>
      <SelRow label="Projection type" value={projType} onChange={setProjType} disabled={running}
        options={[
          { value: 'third_angle', label: 'Third angle (ANSI/ASME Y14.3)' },
          { value: 'first_angle', label: 'First angle (ISO/DIN)' },
        ]} />
      <div style={s.row}>
        <label style={{ ...s.label, cursor: 'pointer' }} onClick={() => setIncludeIso(v => !v)}>
          Include isometric
        </label>
        <div style={{ width: 32, height: 18, borderRadius: 9, background: includeIso ? '#2563eb' : '#374151',
          display: 'flex', alignItems: 'center', padding: '0 2px', cursor: 'pointer' }}
          onClick={() => setIncludeIso(v => !v)}>
          <div style={{ width: 14, height: 14, borderRadius: 7, background: '#fff',
            transform: includeIso ? 'translateX(14px)' : 'none', transition: 'transform 0.2s' }} />
        </div>
      </div>
      <SelRow label="Sheet size" value={sheet} onChange={setSheet} disabled={running}
        options={['A0','A1','A2','A3','A4','LETTER'].map(s => ({ value: s, label: s }))} />
      <NumRow label="Scale (blank = auto)" value={scale} onChange={setScale} disabled={running} />
      <RunBtn onClick={run} running={running} />
      {result && !running && !error && (
        <div style={{ ...s.resultBox, marginTop: 8 }}>
          <div style={s.subhead}>Generated views</div>
          {result.views && Object.entries(result.views).map(([vname, vdata]) => (
            <div key={vname} style={{ ...s.mono, fontSize: 11, marginBottom: 2 }}>
              {vname}: {vdata.visible?.length ?? 0} vis, {vdata.hidden?.length ?? 0} hid segs
            </div>
          ))}
          {result.scale && <div style={{ color: '#a3a3a3', fontSize: 10, marginTop: 4 }}>
            Scale: {result.scale} | ID: {result.drawing_id}
          </div>}
        </div>
      )}
    </ToolWidget>
  )
}

// ---------------------------------------------------------------------------
// TAB: Section view
// ---------------------------------------------------------------------------

const DEFAULT_PLANE_JSON = JSON.stringify(
  { normal: [0, 1, 0], point: [0, 0, 0] }, null, 2
)

function TabSection() {
  const [mesh, setMesh] = useState(DEFAULT_MESH_JSON)
  const [plane, setPlane] = useState(DEFAULT_PLANE_JSON)
  const [viewDir, setViewDir] = useState('')
  const [hatchAngle, setHatchAngle] = useState('45')
  const [hatchSpacing, setHatchSpacing] = useState('3')
  const [label, setLabel] = useState('A')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)

  const run = useCallback(async () => {
    setRunning(true); setError(null); setResult(null)
    try {
      const meshObj = JSON.parse(mesh)
      const planeObj = (() => {
        try { return JSON.parse(plane) } catch { return plane }
      })()
      const args = {
        vertices: meshObj.vertices,
        triangles: meshObj.triangles,
        plane: planeObj,
        hatch_angle_deg: parseFloat(hatchAngle) || 45,
        hatch_spacing_mm: parseFloat(hatchSpacing) || 3,
        label: label || 'A',
      }
      if (viewDir.trim()) {
        try { args.view_direction = JSON.parse(viewDir) } catch { /**/ }
      }
      const r = await callTool('drawing_section_view', args)
      setResult(r)
    } catch (e) { setError(e.message) } finally { setRunning(false) }
  }, [mesh, plane, viewDir, hatchAngle, hatchSpacing, label])

  return (
    <ToolWidget title="Section View — Cutting Plane + Hatch (ISO 128-50)" icon={Scissors}
      color="#10b981" result={result} error={error} running={running}>

      <div style={{ ...s.section, background: '#0f172a', padding: '6px 8px', marginBottom: 6 }}>
        <div style={{ fontSize: 10, color: '#6b7280', lineHeight: 1.4 }}>
          Cuts the mesh with a plane (Sutherland-Hodgman 1974). The rear half is rendered with
          ISO 128-50 §3.2 hatch (default 45°, 3 mm spacing = ANSI 31 "general metal").
          Cutting plane marker A–A is generated for placement on the parent view.
        </div>
      </div>

      <div style={s.row}>
        <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Mesh (JSON)</label>
        <textarea value={mesh} onChange={e => setMesh(e.target.value)} disabled={running}
          rows={6} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
      </div>

      <div style={s.row}>
        <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>
          Cutting plane (JSON or string like "xz@y=0")
        </label>
        <textarea value={plane} onChange={e => setPlane(e.target.value)} disabled={running}
          rows={3} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
      </div>

      <TextRow label='View dir [dx,dy,dz] (opt)' value={viewDir} onChange={setViewDir}
        placeholder='e.g. [0,1,0]' disabled={running} />
      <NumRow label="Hatch angle (°)" value={hatchAngle} onChange={setHatchAngle}
        step="1" disabled={running} />
      <NumRow label="Hatch spacing (mm)" value={hatchSpacing} onChange={setHatchSpacing}
        step="0.5" disabled={running} />
      <TextRow label="Section label" value={label} onChange={setLabel}
        placeholder="A" disabled={running} />

      <RunBtn onClick={run} running={running} />

      {result && !running && !error && (
        <>
          <div style={s.resultBox}>
            <div style={s.subhead}>Section result</div>
            <div style={s.mono}>
              <div>Visible edges: {result.n_visible_edges}</div>
              <div>Hatch lines: {result.n_hatch_lines}</div>
              <div>Contour edges: {result.n_contour_edges}</div>
              <div>Hatch pattern: {result.hatch_pattern}</div>
              {result.cutting_plane_marker?.label_left && (
                <div>Section: {result.cutting_plane_marker.label_left}–{result.cutting_plane_marker.label_right}</div>
              )}
            </div>
          </div>
          <PolylineSvg
            visible={result.visible_edges || []}
            hatch={result.hatch_lines || []}
            contour={result.contour_edges || []}
          />
        </>
      )}
    </ToolWidget>
  )
}

// ---------------------------------------------------------------------------
// TAB: Detail view
// ---------------------------------------------------------------------------

const DEFAULT_VISIBLE_JSON = JSON.stringify([
  [[0,0],[10,0]],[[10,0],[10,10]],[[10,10],[0,10]],[[0,10],[0,0]],
  [[2,4],[8,4]],[[5,0],[5,10]],
], null, 2)

function TabDetail() {
  const [visibleEdges, setVisibleEdges] = useState(DEFAULT_VISIBLE_JSON)
  const [hiddenEdges, setHiddenEdges] = useState('[]')
  const [cx, setCx] = useState('5')
  const [cy, setCy] = useState('5')
  const [radius, setRadius] = useState('4')
  const [magnification, setMagnification] = useState('2')
  const [label, setLabel] = useState('A')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)

  const run = useCallback(async () => {
    setRunning(true); setError(null); setResult(null)
    try {
      const visible = JSON.parse(visibleEdges)
      const hidden = JSON.parse(hiddenEdges)
      const r = await callTool('drawing_detail_view', {
        visible_edges: visible,
        hidden_edges: hidden,
        centre: [parseFloat(cx), parseFloat(cy)],
        radius: parseFloat(radius),
        magnification: parseFloat(magnification) || 2,
        label: label || 'A',
      })
      setResult(r)
    } catch (e) { setError(e.message) } finally { setRunning(false) }
  }, [visibleEdges, hiddenEdges, cx, cy, radius, magnification, label])

  return (
    <ToolWidget title="Detail View — Magnified Circular Crop (ISO 128-30 §10)" icon={ZoomIn}
      color="#8b5cf6" result={result} error={error} running={running}>

      <div style={{ ...s.section, background: '#0f172a', padding: '6px 8px', marginBottom: 6 }}>
        <div style={{ fontSize: 10, color: '#6b7280', lineHeight: 1.4 }}>
          Clips the parent view's edges to a circle, scales by the magnification factor,
          and returns the detail-view geometry plus a thin-circle annotation for the parent
          view (ISO 128-30 §10.2).
        </div>
      </div>

      <div style={s.row}>
        <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Visible edges (JSON)</label>
        <textarea value={visibleEdges} onChange={e => setVisibleEdges(e.target.value)} disabled={running}
          rows={6} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
      </div>
      <div style={s.row}>
        <label style={{ ...s.label, alignSelf: 'flex-start', paddingTop: 3 }}>Hidden edges (JSON)</label>
        <textarea value={hiddenEdges} onChange={e => setHiddenEdges(e.target.value)} disabled={running}
          rows={2} style={{ ...s.input, fontFamily: 'monospace', fontSize: 11, resize: 'vertical' }} />
      </div>

      <NumRow label="Circle centre X (mm)" value={cx} onChange={setCx} step="0.5" disabled={running} />
      <NumRow label="Circle centre Y (mm)" value={cy} onChange={setCy} step="0.5" disabled={running} />
      <NumRow label="Circle radius (mm)" value={radius} onChange={setRadius} step="0.5" disabled={running} />
      <NumRow label="Magnification (×)" value={magnification} onChange={setMagnification} step="0.5" disabled={running} />
      <TextRow label="Detail label" value={label} onChange={setLabel} placeholder="A" disabled={running} />

      <RunBtn onClick={run} running={running} />

      {result && !running && !error && (
        <>
          <div style={s.resultBox}>
            <div style={s.subhead}>Detail result</div>
            <div style={s.mono}>
              <div>Clipped visible: {result.n_clipped_visible}</div>
              <div>Clipped hidden: {result.n_clipped_hidden}</div>
              <div>Magnification: {result.magnification}×</div>
              <div>Label: DETAIL {result.label}</div>
              {result.detail_label_annotation?.scale_note && (
                <div>{result.detail_label_annotation.scale_note}</div>
              )}
            </div>
          </div>
          {result.detail_circle && (
            <div style={{ ...s.resultBox, marginTop: 4 }}>
              <div style={s.subhead}>Parent-view annotation</div>
              <div style={s.mono}>
                Circle: cx={result.detail_circle.cx}, cy={result.detail_circle.cy}, r={result.detail_circle.r}
              </div>
            </div>
          )}
          <PolylineSvg
            visible={result.clipped_visible || []}
            hidden={result.clipped_hidden || []}
          />
        </>
      )}
    </ToolWidget>
  )
}

// ---------------------------------------------------------------------------
// TAB: Title block
// ---------------------------------------------------------------------------

function TabTitleBlock() {
  const [fields, setFields] = useState({
    title: 'Bracket Assembly',
    document_number: 'DWG-001',
    organisation: 'ACME Engineering',
    scale: '1:1',
    sheet: '1/1',
    revision: 'A',
    date: '',
    drawn_by: '',
    approved_by: '',
    material: 'Mild Steel',
    weight_kg: '',
    project: '',
  })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)

  const set = (key, val) => setFields(f => ({ ...f, [key]: val }))

  const run = useCallback(async () => {
    setRunning(true); setError(null); setResult(null)
    try {
      const args = { ...fields }
      if (args.weight_kg === '' || args.weight_kg == null) delete args.weight_kg
      else args.weight_kg = parseFloat(args.weight_kg)
      if (!args.date) delete args.date
      const r = await callTool('drawing_title_block', args)
      setResult(r)
    } catch (e) { setError(e.message) } finally { setRunning(false) }
  }, [fields])

  return (
    <ToolWidget title="Title Block (ISO 7200:2004 §5)" icon={FileText}
      color="#f59e0b" result={result} error={error} running={running}>

      <div style={{ ...s.section, background: '#0f172a', padding: '6px 8px', marginBottom: 6 }}>
        <div style={{ fontSize: 10, color: '#6b7280', lineHeight: 1.4 }}>
          Generates an ISO 7200:2004 §5 compliant title block. All fields optional.
          Returns structured JSON + ordered field list for DXF/SVG rendering.
        </div>
      </div>

      <TextRow label="Title" value={fields.title} onChange={v => set('title', v)} disabled={running} />
      <TextRow label="Document No." value={fields.document_number} onChange={v => set('document_number', v)}
        placeholder="auto-generated" disabled={running} />
      <TextRow label="Organisation" value={fields.organisation} onChange={v => set('organisation', v)} disabled={running} />
      <SelRow label="Scale" value={fields.scale} onChange={v => set('scale', v)} disabled={running}
        options={['1:100','1:50','1:20','1:10','1:5','1:2','1:1','2:1','5:1','10:1'].map(s => ({ value: s, label: s }))} />
      <TextRow label="Sheet" value={fields.sheet} onChange={v => set('sheet', v)}
        placeholder="1/1" disabled={running} />
      <SelRow label="Revision" value={fields.revision} onChange={v => set('revision', v)} disabled={running}
        options={['A','B','C','D','E','F'].map(s => ({ value: s, label: s }))} />
      <TextRow label="Date (ISO 8601)" value={fields.date} onChange={v => set('date', v)}
        placeholder="blank = today" disabled={running} />
      <TextRow label="Drawn by" value={fields.drawn_by} onChange={v => set('drawn_by', v)} disabled={running} />
      <TextRow label="Approved by" value={fields.approved_by} onChange={v => set('approved_by', v)} disabled={running} />
      <TextRow label="Material" value={fields.material} onChange={v => set('material', v)} disabled={running} />
      <NumRow label="Weight (kg)" value={fields.weight_kg} onChange={v => set('weight_kg', v)}
        step="0.001" placeholder="optional" disabled={running} />
      <TextRow label="Project" value={fields.project} onChange={v => set('project', v)} disabled={running} />

      <RunBtn onClick={run} running={running} label="Generate Title Block" />

      {result && !running && !error && (
        <div style={s.resultBox}>
          <div style={s.subhead}>ISO 7200:2004 Title Block</div>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={{ ...s.td, color: '#60a5fa', textAlign: 'left' }}>Field (ISO §5)</th>
                <th style={{ ...s.td, color: '#60a5fa', textAlign: 'left' }}>Value</th>
              </tr>
            </thead>
            <tbody>
              {(result.fields || []).map((f, i) => (
                <tr key={i}>
                  <td style={{ ...s.td, color: '#9ca3af' }}>{f.label}</td>
                  <td style={{ ...s.td, ...s.mono, color: '#f9fafb' }}>{f.value || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.title_block?.drawing_id && (
            <div style={{ color: '#4b5563', fontSize: 10, marginTop: 4 }}>
              Drawing ID: {result.title_block.drawing_id} · {result.title_block.standard}
            </div>
          )}
        </div>
      )}
    </ToolWidget>
  )
}

// ---------------------------------------------------------------------------
// Root panel
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'sheet',    label: 'Sheet',       Icon: LayoutDashboard },
  { id: 'section',  label: 'Section',     Icon: Scissors },
  { id: 'detail',   label: 'Detail',      Icon: ZoomIn },
  { id: 'titleblock', label: 'Title Block', Icon: FileText },
]

export default function DrawingSheetPanel() {
  const [tab, setTab] = useState('sheet')

  return (
    <div style={s.root}>
      <div style={s.header}>
        <LayoutDashboard size={16} style={{ color: '#3b82f6' }} />
        <span style={s.title}>2D Drawing Sheet</span>
        <span style={{ fontSize: 10, color: '#6b7280', marginLeft: 4 }}>
          ISO 128-30 / ISO 128-50 / ISO 7200:2004
        </span>
      </div>

      <div style={s.tabs}>
        {TABS.map(({ id, label, Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            style={{ ...s.tab, ...(tab === id ? s.tabActive : {}) }}>
            <Icon size={11} style={{ marginRight: 4 }} />{label}
          </button>
        ))}
      </div>

      {tab === 'sheet'      && <TabSheet />}
      {tab === 'section'    && <TabSection />}
      {tab === 'detail'     && <TabDetail />}
      {tab === 'titleblock' && <TabTitleBlock />}
    </div>
  )
}
