// RebarDetailPanel.jsx — 3D RC Rebar Detailing + Bending Schedule + Shop Drawing
//
// Wires three backend tools:
//   rebar_detail_member    — 3D bar placement (BS 8666) in a concrete section
//   rebar_bending_schedule — bar-bending schedule from member detail
//   shop_drawing_generate  — fabrication shop drawing (section + elevation + BBS)
//
// Panels:
//   Detail  — member inputs → longitudinal bars + stirrups + 3D section/elevation SVG
//   Schedule — bending schedule table (mark, shape, size, length, count, mass)
//   Drawing  — shop drawing sheet preview (SVG canvas)
//
// Props: none — standalone panel.

import { useState, useCallback, useMemo } from 'react'
import { Layers, Grid3x3, FileText, AlertTriangle, CheckCircle, Loader2, Play } from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------
const s = {
  root:         { background: '#111827', padding: 12, fontSize: 12, color: '#e5e7eb', minHeight: 200 },
  header:       { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 },
  title:        { fontWeight: 600, fontSize: 14, color: '#f9fafb' },
  tabs:         { display: 'flex', gap: 2, marginBottom: 10, flexWrap: 'wrap' },
  tab:          { padding: '4px 10px', borderRadius: 4, border: '1px solid #374151', background: '#1f2937', color: '#9ca3af', cursor: 'pointer', fontSize: 11 },
  tabActive:    { background: '#1d4ed8', borderColor: '#3b82f6', color: '#fff' },
  section:      { background: '#1f2937', borderRadius: 6, padding: 10, marginBottom: 8 },
  sectionTitle: { display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600, marginBottom: 8, color: '#d1d5db', fontSize: 11 },
  row:          { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 },
  label:        { color: '#9ca3af', width: 180, flexShrink: 0, fontSize: 11 },
  input:        { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12, minWidth: 0 },
  select:       { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12 },
  button:       { display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 5, border: 'none', color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 500, background: '#1d4ed8' },
  errorBox:     { display: 'flex', alignItems: 'flex-start', gap: 6, background: '#450a0a', borderRadius: 5, padding: 8, color: '#fca5a5', marginTop: 8 },
  resultBox:    { background: '#0f172a', borderRadius: 4, padding: 8, marginTop: 6, fontFamily: 'monospace', fontSize: 11 },
  table:        { width: '100%', borderCollapse: 'collapse', marginTop: 4 },
  th:           { padding: '4px 6px', background: '#1e3a5f', color: '#93c5fd', fontWeight: 600, fontSize: 10, textAlign: 'left', borderBottom: '1px solid #374151' },
  td:           { padding: '3px 6px', borderBottom: '1px solid #1f2937', fontSize: 11 },
  chip:         { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700 },
  svg:          { border: '1px solid #374151', borderRadius: 4, background: '#0f172a', width: '100%' },
  mono:         { fontFamily: 'monospace' },
  divider:      { borderTop: '1px solid #374151', margin: '8px 0' },
}

// ---------------------------------------------------------------------------
// API call helper
// ---------------------------------------------------------------------------
async function callTool(tool, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool, args }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Section SVG renderer
// ---------------------------------------------------------------------------
function SectionSVG({ detail }) {
  if (!detail) return null
  const { section, longitudinal_bars, stirrups } = detail
  const { width_mm, depth_mm, cover_mm } = section

  const SVG_W = 200, SVG_H = 280
  const scaleX = (SVG_W - 40) / width_mm
  const scaleY = (SVG_H - 40) / depth_mm
  const sc = Math.min(scaleX, scaleY)

  const ox = 20, oy = 20
  const W = width_mm * sc, H = depth_mm * sc

  // Render bar circles
  const barEls = []
  const allBars = [...(longitudinal_bars || []), ...(stirrups || [])]
  allBars.forEach((bar, bi) => {
    const cl = bar.centreline || []
    if (cl.length === 0) return
    const r = (bar.diameter_mm * sc) / 2
    // For section view: use x, y of first centreline point
    const pt = cl[0]
    if (bar.role === 'stirrup' || bar.role === 'tie') {
      // Draw stirrup as rectangle
      const sw = (section.width_mm - 2 * cover_mm - bar.diameter_mm) * sc
      const sh = (section.depth_mm - 2 * cover_mm - bar.diameter_mm) * sc
      barEls.push(
        <rect key={`stir-${bi}`}
          x={ox + cover_mm * sc} y={oy + cover_mm * sc}
          width={sw} height={sh}
          fill="none" stroke="#60a5fa" strokeWidth={Math.max(0.5, bar.diameter_mm * sc * 0.8)}
        />
      )
    } else {
      // Longitudinal bars: draw each across the section
      const count = bar.count
      const diam = bar.diameter_mm
      const innerW = (width_mm - 2 * cover_mm - 2 * (stirrups[0]?.diameter_mm || 10) - diam) * sc
      const offX = (cover_mm + (stirrups[0]?.diameter_mm || 10) + diam / 2) * sc
      const barY = oy + pt[1] * sc

      for (let i = 0; i < count; i++) {
        const bx = ox + (count === 1 ? W / 2 : offX + i * (innerW / (count - 1)))
        barEls.push(
          <circle key={`bar-${bi}-${i}`}
            cx={bx} cy={barY} r={Math.max(1.5, r)}
            fill="#ef4444" stroke="#fca5a5" strokeWidth={0.5}
          />
        )
      }
    }
  })

  return (
    <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={s.svg}>
      {/* Concrete outline */}
      <rect x={ox} y={oy} width={W} height={H}
        fill="#1e293b" stroke="#94a3b8" strokeWidth={1.5} />
      {/* Cover lines (dashed) */}
      <rect x={ox + cover_mm * sc} y={oy + cover_mm * sc}
        width={W - 2 * cover_mm * sc} height={H - 2 * cover_mm * sc}
        fill="none" stroke="#475569" strokeWidth={0.5} strokeDasharray="3,2" />
      {barEls}
      {/* Labels */}
      <text x={ox + W / 2} y={oy + H + 14} textAnchor="middle"
        fill="#94a3b8" fontSize={8}>
        {width_mm}×{depth_mm} mm (cover {cover_mm} mm)
      </text>
      <text x={ox + W / 2} y={SVG_H - 2} textAnchor="middle"
        fill="#60a5fa" fontSize={7}>SECTION</text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Schedule table
// ---------------------------------------------------------------------------
function ScheduleTable({ schedule }) {
  if (!schedule || !schedule.rows || schedule.rows.length === 0) return null
  return (
    <div>
      <table style={s.table}>
        <thead>
          <tr>
            {['Member', 'Mark', 'Type', 'Dia', 'Shape', 'Length (mm)', 'No.', 'Total L (m)', 'Mass (kg)'].map(h => (
              <th key={h} style={s.th}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {schedule.rows.map((r, i) => (
            <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : '#161d2b' }}>
              <td style={s.td}>{r.member_ref}</td>
              <td style={{ ...s.td, ...s.mono }}>{r.bar_mark}</td>
              <td style={s.td}>{r.bar_type}{r.diameter_mm}</td>
              <td style={s.td}>{r.diameter_mm}</td>
              <td style={{ ...s.td, ...s.mono }}>{r.shape_code}</td>
              <td style={s.td}>{r.cut_length_mm?.toFixed(0)}</td>
              <td style={s.td}>{r.number_of_bars}</td>
              <td style={s.td}>{r.total_length_m?.toFixed(2)}</td>
              <td style={s.td}>{r.mass_kg?.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr style={{ borderTop: '2px solid #374151' }}>
            <td colSpan={8} style={{ ...s.td, fontWeight: 700, color: '#93c5fd' }}>TOTAL</td>
            <td style={{ ...s.td, fontWeight: 700, color: '#34d399' }}>
              {schedule.summary?.total_mass_kg?.toFixed(2)} kg
            </td>
          </tr>
        </tfoot>
      </table>
      <div style={{ marginTop: 6, color: '#6b7280', fontSize: 10 }}>
        {schedule.summary?.total_bars} bars · {schedule.summary?.row_count} schedule rows
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shop drawing sheet preview
// ---------------------------------------------------------------------------
function DrawingSheetPreview({ drawing, sheetIdx = 0 }) {
  if (!drawing || !drawing.sheets || drawing.sheets.length === 0) return null
  const sheet = drawing.sheets[sheetIdx]
  if (!sheet) return null

  const entities = sheet.entities || []
  const SVG_W = 600, SVG_H = 400

  // Find bounding box to auto-scale
  const xs = [], ys = []
  entities.forEach(e => {
    if ('x' in e) { xs.push(e.x); if (e.w) xs.push(e.x + e.w) }
    if ('x1' in e) { xs.push(e.x1, e.x2) }
    if ('cx' in e) { xs.push(e.cx - e.r, e.cx + e.r) }
    if ('y' in e) { ys.push(e.y); if (e.h) ys.push(e.y + e.h) }
    if ('y1' in e) { ys.push(e.y1, e.y2) }
    if ('cy' in e) { ys.push(e.cy - e.r, e.cy + e.r) }
  })

  const xmin = xs.length ? Math.min(...xs) - 5 : 0
  const ymin = ys.length ? Math.min(...ys) - 5 : 0
  const xmax = xs.length ? Math.max(...xs) + 5 : 200
  const ymax = ys.length ? Math.max(...ys) + 5 : 150
  const vw = xmax - xmin, vh = ymax - ymin

  const svgEls = entities.slice(0, 500).map((e, i) => {
    const clr = e.layer === 'rebar' ? '#ef4444'
              : e.layer === 'annotation' ? '#60a5fa'
              : e.layer === 'dimension' ? '#fbbf24'
              : '#94a3b8'
    if (e.type === 'line') return (
      <line key={i} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
        stroke={clr} strokeWidth={0.4}
        strokeDasharray={e.style === 'dashed' ? '3,2' : undefined} />
    )
    if (e.type === 'rect') return (
      <rect key={i} x={e.x} y={e.y} width={e.w} height={e.h}
        fill="none" stroke={clr} strokeWidth={e.layer === 'annotation' ? 0.3 : 0.8} />
    )
    if (e.type === 'circle') return (
      <circle key={i} cx={e.cx} cy={e.cy} r={e.r}
        fill="#7f1d1d" stroke="#ef4444" strokeWidth={0.5} />
    )
    if (e.type === 'text') return (
      <text key={i} x={e.x} y={e.y} fontSize={e.size || 3}
        fill={clr} textAnchor={e.anchor || 'start'}>{e.text}</text>
    )
    if (e.type === 'leader') return (
      <g key={i}>
        <line x1={e.x_tip} y1={e.y_tip} x2={e.x_text} y2={e.y_text}
          stroke="#60a5fa" strokeWidth={0.4} />
        <text x={e.x_text} y={e.y_text - 1} fontSize={2.5} fill="#93c5fd">{e.text}</text>
      </g>
    )
    if (e.type === 'dimension') return (
      <g key={i}>
        <line x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
          stroke="#fbbf24" strokeWidth={0.3} markerEnd="url(#arr)" />
        <text x={e.mid_x} y={e.mid_y - 1} fontSize={2.8} fill="#fbbf24" textAnchor="middle">{e.value}</text>
      </g>
    )
    return null
  }).filter(Boolean)

  return (
    <div>
      <div style={{ marginBottom: 4, color: '#6b7280', fontSize: 10 }}>
        Sheet {sheet.sheet_number}: {sheet.title} · {sheet.entity_count} entities
      </div>
      <svg viewBox={`${xmin} ${ymin} ${vw} ${vh}`} style={{ ...s.svg, height: SVG_H }}>
        <defs>
          <marker id="arr" markerWidth="4" markerHeight="4" refX="2" refY="2" orient="auto">
            <path d="M0,0 L4,2 L0,4 Z" fill="#fbbf24" />
          </marker>
        </defs>
        {svgEls}
      </svg>
      <div style={{ marginTop: 4, color: '#6b7280', fontSize: 10 }}>
        {drawing.title_block?.drawing_number && `Dwg: ${drawing.title_block.drawing_number}`}
        {drawing.title_block?.scale && ` · Scale: ${drawing.title_block.scale}`}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------
export default function RebarDetailPanel() {
  const [tab, setTab] = useState('detail')

  // Form state
  const [form, setForm] = useState({
    member_type: 'beam',
    member_ref: 'B1',
    length_mm: 6000,
    width_mm: 300,
    depth_mm: 600,
    cover_mm: 25,
    long_bar_diameter_mm: 16,
    n_bars_bottom: 3,
    n_bars_top: 2,
    stirrup_diameter_mm: 10,
    stirrup_spacing_mm: 200,
  })

  // Results
  const [detail, setDetail]     = useState(null)
  const [schedule, setSchedule] = useState(null)
  const [drawing, setDrawing]   = useState(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [sheetIdx, setSheetIdx] = useState(0)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const runAll = useCallback(async () => {
    setLoading(true)
    setError('')
    setDetail(null); setSchedule(null); setDrawing(null)

    try {
      // 1) Detail member
      const detailResult = await callTool('rebar_detail_member', {
        member_type: form.member_type,
        length_mm: +form.length_mm,
        width_mm: +form.width_mm,
        depth_mm: +form.depth_mm,
        cover_mm: +form.cover_mm,
        long_bar_diameter_mm: +form.long_bar_diameter_mm,
        n_bars_bottom: +form.n_bars_bottom,
        n_bars_top: +form.n_bars_top,
        stirrup_diameter_mm: +form.stirrup_diameter_mm,
        stirrup_spacing_mm: +form.stirrup_spacing_mm,
      })
      if (!detailResult.ok) throw new Error(detailResult.error || 'Detail failed')
      setDetail(detailResult)

      // 2) Bending schedule
      const schedResult = await callTool('rebar_bending_schedule', {
        members: [{ member_ref: form.member_ref, all_bars: detailResult.all_bars }],
      })
      if (!schedResult.ok) throw new Error(schedResult.error || 'Schedule failed')
      setSchedule(schedResult)

      // 3) Shop drawing
      const drawResult = await callTool('shop_drawing_generate', {
        mode: 'shop',
        member_ref: form.member_ref,
        member_type: form.member_type,
        length_mm: +form.length_mm,
        width_mm: +form.width_mm,
        depth_mm: +form.depth_mm,
        cover_mm: +form.cover_mm,
        long_bar_diameter_mm: +form.long_bar_diameter_mm,
        n_bars_bottom: +form.n_bars_bottom,
        n_bars_top: +form.n_bars_top,
        stirrup_diameter_mm: +form.stirrup_diameter_mm,
        stirrup_spacing_mm: +form.stirrup_spacing_mm,
        title_block: { project_name: 'kerf', scale: '1:50' },
      })
      if (!drawResult.ok) throw new Error(drawResult.error || 'Drawing failed')
      setDrawing(drawResult)
      setSheetIdx(0)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [form])

  const inputRow = (label, key, type = 'number', options = null) => (
    <div style={s.row} key={key}>
      <span style={s.label}>{label}</span>
      {options
        ? <select style={s.select} value={form[key]} onChange={e => set(key, e.target.value)}>
            {options.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        : <input style={s.input} type={type} value={form[key]}
            onChange={e => set(key, type === 'number' ? +e.target.value : e.target.value)} />
      }
    </div>
  )

  const TABS = [
    { id: 'detail',   label: 'Detail & Section' },
    { id: 'schedule', label: 'Bending Schedule' },
    { id: 'drawing',  label: 'Shop Drawing' },
  ]

  return (
    <div style={s.root}>
      {/* Header */}
      <div style={s.header}>
        <Layers size={16} color="#60a5fa" />
        <span style={s.title}>RC Rebar Detailing</span>
        <span style={{ color: '#6b7280', fontSize: 11, marginLeft: 4 }}>
          BS 8666:2020 · 3D Placement · Shop Drawing
        </span>
      </div>

      {/* Tabs */}
      <div style={s.tabs}>
        {TABS.map(t => (
          <button key={t.id} style={{ ...s.tab, ...(tab === t.id ? s.tabActive : {}) }}
            onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>

      {/* Inputs */}
      <div style={s.section}>
        <div style={s.sectionTitle}><Grid3x3 size={12} /> Member Geometry</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
          {inputRow('Member Type', 'member_type', 'text', ['beam', 'column', 'slab'])}
          {inputRow('Member Ref', 'member_ref', 'text')}
          {inputRow('Length (mm)', 'length_mm')}
          {inputRow('Width (mm)', 'width_mm')}
          {inputRow('Depth (mm)', 'depth_mm')}
          {inputRow('Cover (mm)', 'cover_mm')}
          {inputRow('Long. Bar Dia (mm)', 'long_bar_diameter_mm', 'number')}
          {inputRow('Bars Bottom', 'n_bars_bottom')}
          {inputRow('Bars Top', 'n_bars_top')}
          {inputRow('Stirrup Dia (mm)', 'stirrup_diameter_mm')}
          {inputRow('Stirrup Spacing (mm)', 'stirrup_spacing_mm')}
        </div>
        <div style={{ marginTop: 8 }}>
          <button style={{ ...s.button, opacity: loading ? 0.6 : 1 }} onClick={runAll} disabled={loading}>
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            {loading ? 'Computing...' : 'Detail + Schedule + Drawing'}
          </button>
        </div>
        {error && (
          <div style={s.errorBox}><AlertTriangle size={14} />{error}</div>
        )}
      </div>

      {/* Detail tab */}
      {tab === 'detail' && detail && (
        <div>
          <div style={s.section}>
            <div style={s.sectionTitle}><CheckCircle size={12} color="#34d399" /> Placement Summary</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <div>
                <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 2 }}>Section</div>
                <div style={s.mono}>
                  {detail.section.width_mm}×{detail.section.depth_mm}×{detail.section.length_mm} mm
                </div>
                <div style={{ color: '#6b7280', fontSize: 10, marginTop: 4 }}>Cover: {detail.section.cover_mm} mm</div>
              </div>
              <div>
                <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 2 }}>Totals</div>
                <div><span style={{ color: '#34d399', fontWeight: 700 }}>{detail.summary.total_bar_count}</span> bars</div>
                <div><span style={{ color: '#f59e0b', fontWeight: 700 }}>{detail.summary.total_mass_kg?.toFixed(1)}</span> kg</div>
              </div>
            </div>
          </div>

          {/* Section SVG */}
          <div style={s.section}>
            <div style={s.sectionTitle}>Cross-Section View</div>
            <SectionSVG detail={detail} />
          </div>

          {/* Bar list */}
          <div style={s.section}>
            <div style={s.sectionTitle}>Bar Placement List</div>
            <table style={s.table}>
              <thead>
                <tr>
                  {['Mark', 'Role', 'Shape', 'Dia', 'Cut L (mm)', 'Count', 'Mass (kg)'].map(h => (
                    <th key={h} style={s.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {detail.all_bars.map((b, i) => (
                  <tr key={i}>
                    <td style={{ ...s.td, ...s.mono }}>{b.mark}</td>
                    <td style={s.td}>{b.role}</td>
                    <td style={{ ...s.td, ...s.mono }}>{b.shape_code}</td>
                    <td style={s.td}>T{b.diameter_mm}</td>
                    <td style={s.td}>{b.cut_length_mm?.toFixed(0)}</td>
                    <td style={s.td}>{b.count}</td>
                    <td style={s.td}>{b.mass_kg?.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Schedule tab */}
      {tab === 'schedule' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><FileText size={12} /> BS 8666:2020 Bar-Bending Schedule</div>
          {schedule
            ? <ScheduleTable schedule={schedule} />
            : <div style={{ color: '#6b7280', fontSize: 11 }}>Run detailing first to generate schedule.</div>
          }
        </div>
      )}

      {/* Drawing tab */}
      {tab === 'drawing' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><FileText size={12} /> Shop Drawing Preview</div>
          {drawing ? (
            <div>
              <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
                {drawing.sheets.map((sh, i) => (
                  <button key={i}
                    style={{ ...s.tab, ...(sheetIdx === i ? s.tabActive : {}) }}
                    onClick={() => setSheetIdx(i)}>
                    Sheet {sh.sheet_number}: {sh.title}
                  </button>
                ))}
              </div>
              <DrawingSheetPreview drawing={drawing} sheetIdx={sheetIdx} />
              <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                <div><span style={{ color: '#6b7280', fontSize: 10 }}>Sheets</span><div style={{ fontWeight: 600, color: '#f9fafb' }}>{drawing.summary.sheets}</div></div>
                <div><span style={{ color: '#6b7280', fontSize: 10 }}>Total Bars</span><div style={{ fontWeight: 600, color: '#34d399' }}>{drawing.summary.total_bars}</div></div>
                <div><span style={{ color: '#6b7280', fontSize: 10 }}>Total Mass</span><div style={{ fontWeight: 600, color: '#f59e0b' }}>{drawing.summary.total_mass_kg?.toFixed(1)} kg</div></div>
              </div>
            </div>
          ) : (
            <div style={{ color: '#6b7280', fontSize: 11 }}>Run detailing first to generate shop drawing.</div>
          )}
        </div>
      )}

      {!detail && !loading && (
        <div style={{ color: '#6b7280', fontSize: 11, textAlign: 'center', padding: 20 }}>
          Enter member dimensions above and click "Detail + Schedule + Drawing"
        </div>
      )}
    </div>
  )
}
