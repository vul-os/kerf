// ManufacturingPanel.jsx — Injection-Mold + Electronics manufacturing-prep panel.
//
// Wires 39 backend tools (21 mold + 18 electronics) into a tabbed UI.
// Top tabs:  Mold (Injection) | Electronics (PCB/EMC)
// Mold sub-sections:   Material Flow | Cooling | Ejection | Quality
// Elec sub-sections:   Power | Signal Integrity | Thermal & Protection | RF
//
// All tools dispatch POST /api/tools/call { tool, args }.
// Pattern follows GeometryInspector.jsx (data-driven ToolCard + Section).
//
// Props: none — standalone panel

import { useState } from 'react'
import {
  Factory, CircuitBoard, Settings, Zap,
  Layers, Thermometer, Shield, Activity,
  ChevronDown, ChevronRight,
  Play, Loader2, AlertTriangle, CheckCircle,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const API_URL = typeof import.meta !== 'undefined' && import.meta.env
  ? (import.meta.env.VITE_API_URL || '')
  : ''

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  const data = await res.json()
  if (typeof data.result === 'string') {
    try { return JSON.parse(data.result) } catch { return data.result }
  }
  return data
}

function fmt(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v, null, 2)
  return String(v)
}

// ---------------------------------------------------------------------------
// Styles (dark mono palette)
// ---------------------------------------------------------------------------

const s = {
  root: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 13,
    color: '#e5e7eb',
    background: '#0d1117',
    minHeight: '100vh',
    padding: '24px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
  },
  pageHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    paddingBottom: 16,
    borderBottom: '1px solid #1f2937',
  },
  pageTitle: { fontSize: 18, fontWeight: 700, color: '#f3f4f6' },
  pageSub: { fontSize: 11, color: '#6b7280', marginTop: 2 },
  // top-level tabs
  tabs: { display: 'flex', gap: 4, marginBottom: 4, flexWrap: 'wrap' },
  tab: {
    padding: '6px 16px',
    borderRadius: 5,
    border: '1px solid #374151',
    background: '#161b26',
    color: '#9ca3af',
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 500,
    display: 'flex',
    alignItems: 'center',
    gap: 5,
  },
  tabActive: {
    background: '#0e4f8f',
    borderColor: '#2563eb',
    color: '#fff',
  },
  // collapsible section
  section: {
    background: '#111827',
    borderRadius: 8,
    border: '1px solid #1f2937',
    overflow: 'hidden',
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 14px',
    cursor: 'pointer',
    background: '#161b26',
    userSelect: 'none',
  },
  sectionTitle: {
    fontWeight: 600,
    fontSize: 12,
    color: '#f3f4f6',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    flex: 1,
  },
  sectionCount: { fontSize: 10, color: '#6b7280', fontWeight: 400 },
  cardGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
    gap: 12,
    padding: 12,
  },
  card: {
    background: '#0d1117',
    border: '1px solid #1f2937',
    borderRadius: 6,
    padding: 12,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  cardHeader: { display: 'flex', alignItems: 'center', gap: 6 },
  cardTitle: { fontWeight: 600, fontSize: 12, color: '#f3f4f6', flex: 1 },
  cardDesc: { fontSize: 11, color: '#6b7280', lineHeight: 1.5 },
  fields: { display: 'flex', flexDirection: 'column', gap: 5 },
  row: { display: 'flex', alignItems: 'center', gap: 6 },
  label: { fontSize: 11, color: '#9ca3af', width: 110, flexShrink: 0 },
  input: {
    flex: 1,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '3px 6px',
    fontSize: 11,
    outline: 'none',
    fontFamily: 'inherit',
  },
  select: {
    flex: 1,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '3px 6px',
    fontSize: 11,
    outline: 'none',
    fontFamily: 'inherit',
  },
  runBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    padding: '4px 10px',
    background: '#0e7490',
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    alignSelf: 'flex-start',
  },
  runBtnDisabled: { opacity: 0.45, cursor: 'not-allowed' },
  result: {
    background: '#0a0f1a',
    border: '1px solid #1f2937',
    borderRadius: 4,
    padding: '6px 8px',
    fontSize: 11,
    color: '#a3e635',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
    maxHeight: 200,
    overflowY: 'auto',
  },
  errorBox: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 5,
    background: '#1f0707',
    border: '1px solid #7f1d1d',
    borderRadius: 4,
    padding: '5px 8px',
    color: '#fca5a5',
    fontSize: 11,
  },
  successBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 10,
    fontWeight: 600,
    background: '#14532d22',
    border: '1px solid #16a34a55',
    color: '#4ade80',
    borderRadius: 9999,
    padding: '1px 7px',
  },
}

// ---------------------------------------------------------------------------
// ToolCard — generic data-driven tool card
// ---------------------------------------------------------------------------

function ToolCard({ name, icon: Icon, color, desc, fields, buildArgs }) {
  const [values, setValues] = useState(() =>
    Object.fromEntries(fields.map((f) => [f.key, f.default ?? '']))
  )
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  function set(key, val) { setValues((v) => ({ ...v, [key]: val })) }

  async function run() {
    setRunning(true); setResult(null); setError(null)
    try {
      const args = buildArgs ? buildArgs(values) : Object.fromEntries(
        fields.map((f) => [f.key, f.coerce ? f.coerce(values[f.key]) : values[f.key]])
      )
      setResult(await callTool(name, args))
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div style={s.card} data-testid={`tool-card-${name}`}>
      <div style={s.cardHeader}>
        {Icon && <Icon size={13} style={{ color: color || '#22d3ee', flexShrink: 0 }} />}
        <span style={s.cardTitle}>{name}</span>
        {result && !error && (
          <span style={s.successBadge}><CheckCircle size={9} /> done</span>
        )}
      </div>
      {desc && <div style={s.cardDesc}>{desc}</div>}

      {fields.length > 0 && (
        <div style={s.fields}>
          {fields.map((f) => (
            <div key={f.key} style={s.row}>
              <label style={s.label}>{f.label}</label>
              {f.type === 'select' ? (
                <select value={values[f.key]} onChange={(e) => set(f.key, e.target.value)}
                  style={s.select} disabled={running}>
                  {f.options.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              ) : f.type === 'textarea' ? (
                <textarea value={values[f.key]}
                  onChange={(e) => set(f.key, e.target.value)}
                  style={{ ...s.input, height: 52, resize: 'vertical' }}
                  disabled={running} placeholder={f.placeholder || ''} />
              ) : (
                <input type={f.type || 'text'} value={values[f.key]}
                  onChange={(e) => set(f.key, e.target.value)}
                  style={s.input} disabled={running}
                  placeholder={f.placeholder || ''} />
              )}
            </div>
          ))}
        </div>
      )}

      <button onClick={run} disabled={running}
        style={{ ...s.runBtn, ...(running ? s.runBtnDisabled : {}) }}>
        {running
          ? <><Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} /> Running…</>
          : <><Play size={11} /> Run</>}
      </button>

      {error && (
        <div style={s.errorBox} role="alert">
          <AlertTriangle size={11} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      )}
      {result && !error && (
        <div style={s.result}>
          {typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result)}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section — collapsible header + card grid
// ---------------------------------------------------------------------------

function Section({ title, icon: Icon, color, cards, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={s.section}>
      <div style={s.sectionHeader} onClick={() => setOpen((v) => !v)}>
        <Icon size={14} style={{ color }} />
        <span style={s.sectionTitle}>{title}</span>
        <span style={s.sectionCount}>{cards.length} tools</span>
        {open
          ? <ChevronDown size={13} style={{ color: '#6b7280' }} />
          : <ChevronRight size={13} style={{ color: '#6b7280' }} />}
      </div>
      {open && (
        <div style={s.cardGrid}>
          {cards.map((card) => <ToolCard key={card.name} {...card} />)}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers for building args
// ---------------------------------------------------------------------------

function num(v) { return v === '' || v == null ? undefined : Number(v) }
function int(v) { return v === '' || v == null ? undefined : parseInt(v, 10) }
function tryJSON(v, fallback) {
  if (!v) return fallback
  try { return JSON.parse(v) } catch { return v }
}

// ---------------------------------------------------------------------------
// MOLD TOOL DEFINITIONS
// ---------------------------------------------------------------------------

// ── Section 1: Material Flow ─────────────────────────────────────────────────

const MOLD_MATERIAL_FLOW = [
  {
    name: 'mold_check_moldability',
    icon: Factory,
    color: '#f59e0b',
    desc: 'Draft-angle + wall-uniformity + parting-surface continuity check (Beaumont 2007 §3).',
    fields: [
      { key: 'parting_line_points', label: 'Parting pts JSON', type: 'textarea',
        placeholder: '[[0,0,0],[1,0,0],[1,1,0],[0,1,0]]', default: '[[0,0,0],[10,0,0],[10,10,0],[0,10,0]]' },
      { key: 'pull_direction', label: 'Pull dir JSON', type: 'text',
        placeholder: '[0,0,1]', default: '[0,0,1]' },
      { key: 'min_draft_deg', label: 'Min draft (°)', type: 'number', default: '1.0' },
    ],
    buildArgs: (v) => ({
      parting_line_points: tryJSON(v.parting_line_points, [[0,0,0],[10,0,0],[10,10,0],[0,10,0]]),
      pull_direction: tryJSON(v.pull_direction, [0,0,1]),
      ...(v.min_draft_deg !== '' ? { min_draft_deg: num(v.min_draft_deg) } : {}),
    }),
  },
  {
    name: 'mold_check_runner_balance',
    icon: Settings,
    color: '#f59e0b',
    desc: 'Hagen-Poiseuille flow balance across runner tree (Beaumont 2007 §6.6).',
    fields: [
      { key: 'segments', label: 'Segments JSON', type: 'textarea',
        placeholder: '[{"id":"S1","length_mm":50,"diameter_mm":6}]',
        default: '[{"id":"S1","length_mm":50,"diameter_mm":6,"parent_id":null},{"id":"S2","length_mm":30,"diameter_mm":4,"parent_id":"S1"},{"id":"S3","length_mm":30,"diameter_mm":4,"parent_id":"S1"}]' },
      { key: 'cavity_gate_ids', label: 'Gate IDs JSON', type: 'text',
        placeholder: '["S2","S3"]', default: '["S2","S3"]' },
    ],
    buildArgs: (v) => ({
      segments: tryJSON(v.segments, []),
      cavity_gate_ids: tryJSON(v.cavity_gate_ids, []),
    }),
  },
  {
    name: 'mold_check_runner_diameter',
    icon: Settings,
    color: '#f59e0b',
    desc: 'Beaumont power-law runner diameter D = (W^0.25 × √L) / 3.7 for target fill pressure.',
    fields: [
      { key: 'part_weight_g', label: 'Part weight (g)', type: 'number', default: '15' },
      { key: 'runner_length_mm', label: 'Runner length (mm)', type: 'number', default: '80' },
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS (medium)' },
          { value: 'PP-homopolymer', label: 'PP homopolymer' },
          { value: 'PC-high', label: 'PC (high visc)' },
          { value: 'PA6-dry', label: 'PA6 dry' },
          { value: 'HDPE-medium', label: 'HDPE medium' },
        ]},
    ],
    buildArgs: (v) => ({
      part_weight_g: num(v.part_weight_g),
      runner_length_mm: num(v.runner_length_mm),
      polymer_grade: v.polymer_grade,
    }),
  },
  {
    name: 'mold_check_melt_flow_ratio',
    icon: Factory,
    color: '#f59e0b',
    desc: 'ASTM D1238 MFR injection-speed envelope — avoids jetting and gate freeze-off (Beaumont §4).',
    fields: [
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS (medium)' },
          { value: 'PP-homopolymer', label: 'PP homopolymer' },
          { value: 'PC-high', label: 'PC (high visc)' },
          { value: 'PA6-dry', label: 'PA6 dry' },
        ]},
      { key: 'flow_length_mm', label: 'Flow length (mm)', type: 'number', default: '120' },
      { key: 'wall_thickness_mm', label: 'Wall thickness (mm)', type: 'number', default: '2.5' },
      { key: 'gate_diameter_mm', label: 'Gate diam (mm)', type: 'number', default: '1.0' },
      { key: 'injection_speed_mm_per_s', label: 'Injection speed (mm/s)', type: 'number', default: '50' },
    ],
    buildArgs: (v) => ({
      polymer_grade: v.polymer_grade,
      flow_length_mm: num(v.flow_length_mm),
      wall_thickness_mm: num(v.wall_thickness_mm),
      gate_diameter_mm: num(v.gate_diameter_mm),
      injection_speed_mm_per_s: num(v.injection_speed_mm_per_s),
    }),
  },
  {
    name: 'mold_check_gate_vestige',
    icon: Settings,
    color: '#f59e0b',
    desc: 'Gate vestige height prediction and cosmetic risk (Beaumont 2007 §7.6 Table 7.4).',
    fields: [
      { key: 'gate_type', label: 'Gate type', type: 'select', default: 'edge',
        options: [
          { value: 'edge', label: 'Edge gate' },
          { value: 'tab', label: 'Tab gate' },
          { value: 'fan', label: 'Fan gate' },
          { value: 'submarine', label: 'Submarine gate' },
          { value: 'pin-point', label: 'Pin-point gate' },
        ]},
      { key: 'gate_thickness_mm', label: 'Gate thickness (mm)', type: 'number', default: '0.8' },
      { key: 'gate_width_mm', label: 'Gate width (mm)', type: 'number', default: '3.0' },
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS' },
          { value: 'PP-homopolymer', label: 'PP' },
          { value: 'PA6-dry', label: 'PA6' },
        ]},
    ],
    buildArgs: (v) => ({
      gate_type: v.gate_type,
      gate_thickness_mm: num(v.gate_thickness_mm),
      gate_width_mm: num(v.gate_width_mm),
      polymer_grade: v.polymer_grade,
    }),
  },
  {
    name: 'mold_check_sprue_bushing_match',
    icon: Settings,
    color: '#f59e0b',
    desc: 'Verify sprue bushing seat radius and orifice match nozzle (Beaumont 2007 §6.4 + DME catalogue).',
    fields: [
      { key: 'sb_radius_mm', label: 'Bushing radius (mm)', type: 'number', default: '19' },
      { key: 'sb_orifice_mm', label: 'Bushing orifice (mm)', type: 'number', default: '3.5' },
      { key: 'sb_taper_deg', label: 'Bushing taper (°)', type: 'number', default: '2.0' },
      { key: 'sb_length_mm', label: 'Bushing length (mm)', type: 'number', default: '80' },
      { key: 'nozzle_radius_mm', label: 'Nozzle radius (mm)', type: 'number', default: '18' },
      { key: 'nozzle_orifice_mm', label: 'Nozzle orifice (mm)', type: 'number', default: '3.0' },
    ],
    buildArgs: (v) => ({
      sprue_bushing: {
        seat_radius_mm: num(v.sb_radius_mm),
        orifice_diameter_mm: num(v.sb_orifice_mm),
        taper_angle_deg: num(v.sb_taper_deg),
        length_mm: num(v.sb_length_mm),
      },
      machine_nozzle: {
        tip_radius_mm: num(v.nozzle_radius_mm),
        orifice_diameter_mm: num(v.nozzle_orifice_mm),
      },
    }),
  },
  {
    name: 'mold_detect_undercuts',
    icon: Factory,
    color: '#f59e0b',
    desc: 'Detect faces that cannot be released in the pull direction (B-rep DFM undercut check).',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea',
        placeholder: '{"type":"Body","faces":[...]}', default: '' },
      { key: 'pull_direction', label: 'Pull dir JSON', type: 'text',
        placeholder: '[0,0,1]', default: '[0,0,1]' },
    ],
    buildArgs: (v) => ({
      ...(v.body_json ? { body_json: tryJSON(v.body_json, v.body_json) } : {}),
      pull_direction: tryJSON(v.pull_direction, [0,0,1]),
    }),
  },
  {
    name: 'mold_compute_warpage_index',
    icon: Activity,
    color: '#f59e0b',
    desc: 'Heuristic 0–100 warpage risk index from wall uniformity, polymer, gate location (Beaumont §10).',
    fields: [
      { key: 'wall_thicknesses_mm', label: 'Wall t CSV (mm)', type: 'text',
        placeholder: '2,2,3,4,2', default: '2,2,3,4,2' },
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'PP-homopolymer',
        options: [
          { value: 'ABS-medium', label: 'ABS' },
          { value: 'PP-homopolymer', label: 'PP' },
          { value: 'PA6-dry', label: 'PA6' },
          { value: 'PC-high', label: 'PC' },
          { value: 'POM-copolymer', label: 'POM' },
        ]},
      { key: 'gate_location', label: 'Gate location', type: 'select', default: 'center',
        options: [
          { value: 'center', label: 'Center' },
          { value: 'edge', label: 'Edge' },
          { value: 'corner', label: 'Corner' },
          { value: 'multiple', label: 'Multiple' },
        ]},
      { key: 'post_ejection_cooling_s', label: 'Post-ejection cooling (s)', type: 'number', default: '15' },
      { key: 'mold_temp_C', label: 'Mold temp (°C)', type: 'number', default: '40' },
    ],
    buildArgs: (v) => ({
      wall_thicknesses_mm: v.wall_thicknesses_mm.split(',').map(Number).filter(Boolean),
      polymer_grade: v.polymer_grade,
      gate_location: v.gate_location,
      post_ejection_cooling_s: num(v.post_ejection_cooling_s),
      mold_temp_C: num(v.mold_temp_C),
    }),
  },
  {
    name: 'mold_design_tunnel_gate',
    icon: Settings,
    color: '#f59e0b',
    desc: 'Tunnel/submarine gate diameter, break-off force, shear rate, freeze time (Beaumont §7.4).',
    fields: [
      { key: 'shot_weight_g', label: 'Shot weight (g)', type: 'number', default: '20' },
      { key: 'wall_thickness_mm', label: 'Wall thickness (mm)', type: 'number', default: '2.5' },
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS' },
          { value: 'PP-homopolymer', label: 'PP' },
          { value: 'PA6-dry', label: 'PA6' },
        ]},
      { key: 'fill_time_s', label: 'Fill time (s)', type: 'number', default: '1.5' },
      { key: 'melt_temp_C', label: 'Melt temp (°C)', type: 'number', default: '230' },
    ],
    buildArgs: (v) => ({
      shot_weight_g: num(v.shot_weight_g),
      wall_thickness_mm: num(v.wall_thickness_mm),
      polymer_grade: v.polymer_grade,
      fill_time_s: num(v.fill_time_s),
      melt_temp_C: num(v.melt_temp_C),
    }),
  },
  {
    name: 'mold_check_surface_finish',
    icon: Layers,
    color: '#f59e0b',
    desc: 'SPI mold finish A1–D3 compatibility check: resin + steel + HRC minimum (SPI 2017 + Menges §11).',
    fields: [
      { key: 'requested_finish', label: 'Requested finish', type: 'select', default: 'B2',
        options: [
          { value: 'A1', label: 'A1 (mirror)' }, { value: 'A2', label: 'A2' }, { value: 'A3', label: 'A3' },
          { value: 'B1', label: 'B1' }, { value: 'B2', label: 'B2' }, { value: 'B3', label: 'B3' },
          { value: 'C1', label: 'C1' }, { value: 'C2', label: 'C2' }, { value: 'C3', label: 'C3' },
          { value: 'D1', label: 'D1' }, { value: 'D2', label: 'D2' }, { value: 'D3', label: 'D3 (EDM)' },
        ]},
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS' }, { value: 'PP-homopolymer', label: 'PP' },
          { value: 'PC-high', label: 'PC' }, { value: 'PA6-dry', label: 'PA6 (glass-filled)' },
        ]},
      { key: 'steel_grade', label: 'Steel grade', type: 'select', default: 'P20',
        options: [
          { value: 'P20', label: 'P20 (pre-hardened)' }, { value: 'H13', label: 'H13 tool' },
          { value: 'S7', label: 'S7 shock' }, { value: '420SS', label: '420 SS stainless' },
        ]},
      { key: 'steel_hardness_HRC', label: 'Steel HRC', type: 'number', default: '30' },
    ],
    buildArgs: (v) => ({
      requested_finish: v.requested_finish,
      polymer_grade: v.polymer_grade,
      steel_grade: v.steel_grade,
      steel_hardness_HRC: num(v.steel_hardness_HRC),
    }),
  },
  {
    name: 'mold_compute_color_concentrate_ratio',
    icon: Settings,
    color: '#f59e0b',
    desc: 'Masterbatch let-down ratio LDR, MB mass/shot, streaking risk (SPI CC Handbook 3rd ed.).',
    fields: [
      { key: 'target_color_pct', label: 'Target colour (%)', type: 'number', default: '2.0' },
      { key: 'masterbatch_strength_pct', label: 'MB strength (%)', type: 'number', default: '40' },
      { key: 'polymer_grade', label: 'Base polymer', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS' }, { value: 'PP-homopolymer', label: 'PP' },
          { value: 'PA6-dry', label: 'PA6' },
        ]},
      { key: 'shot_weight_g', label: 'Shot weight (g)', type: 'number', default: '20' },
      { key: 'L_D_ratio', label: 'Screw L/D', type: 'number', default: '24' },
      { key: 'residence_time_s', label: 'Residence time (s)', type: 'number', default: '30' },
      { key: 'barrel_temp_C', label: 'Barrel temp (°C)', type: 'number', default: '230' },
    ],
    buildArgs: (v) => ({
      target_color_pct: num(v.target_color_pct),
      masterbatch_strength_pct: num(v.masterbatch_strength_pct),
      polymer_grade: v.polymer_grade,
      shot_weight_g: num(v.shot_weight_g),
      L_D_ratio: num(v.L_D_ratio),
      residence_time_s: num(v.residence_time_s),
      barrel_temp_C: num(v.barrel_temp_C),
    }),
  },
  {
    name: 'mold_optimize_runner_diameter',
    icon: Settings,
    color: '#f59e0b',
    desc: 'Optimal runner diameter minimising pressure × runner volume (Beaumont §6.5 + Menges §6.5).',
    fields: [
      { key: 'part_weight_g', label: 'Part weight (g)', type: 'number', default: '15' },
      { key: 'runner_length_mm', label: 'Runner length (mm)', type: 'number', default: '80' },
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS' }, { value: 'PP-homopolymer', label: 'PP' },
          { value: 'PC-high', label: 'PC' },
        ]},
      { key: 'n_cavities', label: 'No. of cavities', type: 'number', default: '4' },
    ],
    buildArgs: (v) => ({
      part_weight_g: num(v.part_weight_g),
      runner_length_mm: num(v.runner_length_mm),
      polymer_grade: v.polymer_grade,
      ...(v.n_cavities ? { n_cavities: int(v.n_cavities) } : {}),
    }),
  },
]

// ── Section 2: Cooling ─────────────────────────────────────────────────────

const MOLD_COOLING = [
  {
    name: 'mold_compute_cooling_time_chen_chiang',
    icon: Thermometer,
    color: '#06b6d4',
    desc: 'Chen-Chiang 1985 cooling time from wall thickness, polymer α, T_melt, T_ejection (Beaumont §10.4).',
    fields: [
      { key: 'wall_thickness_mm', label: 'Wall thickness (mm)', type: 'number', default: '2.5' },
      { key: 'material_name', label: 'Material', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS (medium)' },
          { value: 'PP-homopolymer', label: 'PP homopolymer' },
          { value: 'PC-high', label: 'PC (high visc)' },
          { value: 'PA6-dry', label: 'PA6 dry' },
          { value: 'POM-copolymer', label: 'POM copolymer' },
          { value: 'HDPE-medium', label: 'HDPE medium' },
        ]},
      { key: 'mold_temp_C', label: 'Mold temp (°C)', type: 'number', default: '40' },
    ],
    buildArgs: (v) => ({
      wall_thickness_mm: num(v.wall_thickness_mm),
      material_name: v.material_name,
      mold_temp_C: num(v.mold_temp_C),
    }),
  },
  {
    name: 'mold_compute_cooling_pressure_drop',
    icon: Thermometer,
    color: '#06b6d4',
    desc: 'Darcy-Weisbach pressure drop through cooling-channel circuit (Beaumont §11.2 + White §6.7).',
    fields: [
      { key: 'segments', label: 'Segments JSON', type: 'textarea',
        placeholder: '[{"length_mm":200,"diameter_mm":8,"segment_type":"straight"}]',
        default: '[{"length_mm":200,"diameter_mm":8,"segment_type":"straight"},{"length_mm":50,"diameter_mm":8,"segment_type":"elbow_90"}]' },
      { key: 'flow_rate_L_per_min', label: 'Flow rate (L/min)', type: 'number', default: '4' },
      { key: 'coolant_temp_C', label: 'Coolant temp (°C)', type: 'number', default: '25' },
      { key: 'coolant_type', label: 'Coolant', type: 'select', default: 'water',
        options: [
          { value: 'water', label: 'Water' },
          { value: 'ethylene_glycol_50', label: '50% EG mix' },
        ]},
    ],
    buildArgs: (v) => ({
      segments: tryJSON(v.segments, []),
      flow_rate_L_per_min: num(v.flow_rate_L_per_min),
      coolant_temp_C: num(v.coolant_temp_C),
      coolant_type: v.coolant_type,
    }),
  },
  {
    name: 'mold_check_turbulent_re',
    icon: Activity,
    color: '#06b6d4',
    desc: 'Verify Re > 10 000 for fully turbulent cooling flow + Dittus-Boelter applicability (Beaumont §11).',
    fields: [
      { key: 'channel_diameter_mm', label: 'Channel diam (mm)', type: 'number', default: '8' },
      { key: 'flow_rate_L_per_min', label: 'Flow rate (L/min)', type: 'number', default: '4' },
      { key: 'coolant_temp_C', label: 'Coolant temp (°C)', type: 'number', default: '25' },
      { key: 'coolant_kinematic_visc_cSt', label: 'Kinematic visc (cSt)', type: 'number', default: '0.89' },
    ],
    buildArgs: (v) => ({
      channel_diameter_mm: num(v.channel_diameter_mm),
      flow_rate_L_per_min: num(v.flow_rate_L_per_min),
      coolant_temp_C: num(v.coolant_temp_C),
      ...(v.coolant_kinematic_visc_cSt ? { coolant_kinematic_visc_cSt: num(v.coolant_kinematic_visc_cSt) } : {}),
    }),
  },
  {
    name: 'mold_design_core_pin_cooling',
    icon: Thermometer,
    color: '#06b6d4',
    desc: 'Baffle/bubbler cooling for tall core pins: Re, Dittus-Boelter HTC, tip temperature (Menges §7.5).',
    fields: [
      { key: 'pin_diameter_mm', label: 'Pin diam (mm)', type: 'number', default: '12' },
      { key: 'pin_height_mm', label: 'Pin height (mm)', type: 'number', default: '60' },
      { key: 'method', label: 'Cooling method', type: 'select', default: 'baffle',
        options: [
          { value: 'baffle', label: 'Baffle' },
          { value: 'bubbler', label: 'Bubbler' },
        ]},
      { key: 'coolant_flow_rate_L_per_min', label: 'Flow rate (L/min)', type: 'number', default: '1.5' },
      { key: 'coolant_temp_in_C', label: 'Coolant in (°C)', type: 'number', default: '20' },
      { key: 'melt_temp_C', label: 'Melt temp (°C)', type: 'number', default: '230' },
      { key: 'steel_conductivity_W_per_mK', label: 'Steel λ (W/m·K)', type: 'number', default: '29' },
    ],
    buildArgs: (v) => ({
      pin_diameter_mm: num(v.pin_diameter_mm),
      pin_height_mm: num(v.pin_height_mm),
      method: v.method,
      coolant_flow_rate_L_per_min: num(v.coolant_flow_rate_L_per_min),
      coolant_temp_in_C: num(v.coolant_temp_in_C),
      melt_temp_C: num(v.melt_temp_C),
      steel_conductivity_W_per_mK: num(v.steel_conductivity_W_per_mK),
    }),
  },
  {
    name: 'mold_generate_vent_slot_layout',
    icon: Activity,
    color: '#06b6d4',
    desc: 'Vent slot spacing, width, and depth layout for parting line venting (Beaumont §8.5 + Table 8.4).',
    fields: [
      { key: 'parting_perimeter_mm', label: 'Parting perimeter (mm)', type: 'number', default: '400' },
      { key: 'vent_depth_mm', label: 'Vent depth (mm)', type: 'number', default: '0.025' },
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS' }, { value: 'PP-homopolymer', label: 'PP' },
          { value: 'PA6-dry', label: 'PA6 (GF)' },
        ]},
      { key: 'vent_land_length_mm', label: 'Vent land (mm)', type: 'number', default: '3' },
    ],
    buildArgs: (v) => ({
      parting_perimeter_mm: num(v.parting_perimeter_mm),
      vent_depth_mm: num(v.vent_depth_mm),
      polymer_grade: v.polymer_grade,
      vent_land_length_mm: num(v.vent_land_length_mm),
    }),
  },
  {
    name: 'mold_check_vent_depth',
    icon: Activity,
    color: '#06b6d4',
    desc: 'Check proposed vent depth against polymer flash limit and flow front (Beaumont §8.3 Table 8.2).',
    fields: [
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS' }, { value: 'PP-homopolymer', label: 'PP' },
          { value: 'PA6-dry', label: 'PA6' }, { value: 'PC-high', label: 'PC' },
        ]},
      { key: 'proposed_depth_mm', label: 'Proposed depth (mm)', type: 'number', default: '0.025' },
      { key: 'vent_width_mm', label: 'Vent width (mm)', type: 'number', default: '6' },
    ],
    buildArgs: (v) => ({
      polymer_grade: v.polymer_grade,
      proposed_depth_mm: num(v.proposed_depth_mm),
      vent_width_mm: num(v.vent_width_mm),
    }),
  },
  {
    name: 'mold_check_cold_slug_design',
    icon: Activity,
    color: '#06b6d4',
    desc: 'Cold-slug well sizing at runner junctions (Beaumont §6.7 + Menges §6.5).',
    fields: [
      { key: 'junctions', label: 'Junctions JSON', type: 'textarea',
        placeholder: '[{"id":"J1","runner_diameter_mm":6,"cold_slug_depth_mm":6,"cold_slug_diameter_mm":6}]',
        default: '[{"id":"J1","runner_diameter_mm":6,"cold_slug_depth_mm":6,"cold_slug_diameter_mm":6,"has_puller_pin":true}]' },
    ],
    buildArgs: (v) => ({ junctions: tryJSON(v.junctions, []) }),
  },
]

// ── Section 3: Ejection ────────────────────────────────────────────────────

const MOLD_EJECTION = [
  {
    name: 'mold_compute_demold_force',
    icon: Settings,
    color: '#8b5cf6',
    desc: 'Ejection / demolding force from interference fit, friction, draft angle (Beaumont §9.3).',
    fields: [
      { key: 'polymer_grade', label: 'Polymer grade', type: 'select', default: 'ABS-medium',
        options: [
          { value: 'ABS-medium', label: 'ABS' }, { value: 'PP-homopolymer', label: 'PP' },
          { value: 'PA6-dry', label: 'PA6' }, { value: 'PC-high', label: 'PC' },
        ]},
      { key: 'projected_area_mm2', label: 'Projected area (mm²)', type: 'number', default: '5000' },
      { key: 'draft_angle_deg', label: 'Draft angle (°)', type: 'number', default: '1.5' },
      { key: 'mold_temp_C', label: 'Mold temp (°C)', type: 'number', default: '40' },
      { key: 'surface_texture', label: 'Surface texture', type: 'select', default: 'polished',
        options: [
          { value: 'polished', label: 'Polished (A/B)' },
          { value: 'textured', label: 'Textured (C/D)' },
          { value: 'edm', label: 'EDM' },
        ]},
    ],
    buildArgs: (v) => ({
      polymer_grade: v.polymer_grade,
      projected_area_mm2: num(v.projected_area_mm2),
      draft_angle_deg: num(v.draft_angle_deg),
      mold_temp_C: num(v.mold_temp_C),
      surface_texture: v.surface_texture,
    }),
  },
  {
    name: 'mold_compute_ejector_pin_push',
    icon: Settings,
    color: '#8b5cf6',
    desc: 'Euler critical buckling load for ejector pins F_cr = π²EI/(KL)² (SPI/ANSI B151.1 + Roark §15.2).',
    fields: [
      { key: 'required_force_N', label: 'Required force (N)', type: 'number', default: '300' },
      { key: 'pin_length_mm', label: 'Pin length (mm)', type: 'number', default: '100' },
      { key: 'pin_diameter_mm', label: 'Pin diam (mm)', type: 'number', default: '3' },
      { key: 'end_condition', label: 'End condition', type: 'select', default: 'pinned_pinned',
        options: [
          { value: 'pinned_pinned', label: 'Pinned-pinned (K=1.0)' },
          { value: 'fixed_fixed', label: 'Fixed-fixed (K=0.5)' },
          { value: 'cantilever', label: 'Cantilever (K=2.0)' },
        ]},
      { key: 'steel_grade', label: 'Steel grade', type: 'select', default: 'M2',
        options: [
          { value: 'M2', label: 'M2 HSS' }, { value: 'H13', label: 'H13' },
          { value: 'S7', label: 'S7' }, { value: 'D2', label: 'D2' },
        ]},
    ],
    buildArgs: (v) => ({
      required_force_N: num(v.required_force_N),
      pin_length_mm: num(v.pin_length_mm),
      pin_diameter_mm: num(v.pin_diameter_mm),
      end_condition: v.end_condition,
      steel_grade: v.steel_grade,
    }),
  },
]

// ── Section 4: Quality ─────────────────────────────────────────────────────

const MOLD_QUALITY = [] // runner_balance already in flow; additional checks below

// ---------------------------------------------------------------------------
// ELECTRONICS TOOL DEFINITIONS
// ---------------------------------------------------------------------------

// ── Section 1: Power ──────────────────────────────────────────────────────

const ELEC_POWER = [
  {
    name: 'electronics_check_voltage_drop',
    icon: Zap,
    color: '#f59e0b',
    desc: 'NEC 2023 Art. 210.19(A) voltage drop check for AC/DC conductor runs.',
    fields: [
      { key: 'awg_size', label: 'AWG size', type: 'number', default: '12' },
      { key: 'material', label: 'Material', type: 'select', default: 'copper',
        options: [{ value: 'copper', label: 'Copper' }, { value: 'aluminum', label: 'Aluminum' }] },
      { key: 'length_one_way_m', label: 'Length one-way (m)', type: 'number', default: '20' },
      { key: 'voltage_V', label: 'Voltage (V)', type: 'number', default: '120' },
      { key: 'current_A', label: 'Current (A)', type: 'number', default: '15' },
      { key: 'phase', label: 'Phase', type: 'select', default: 'single',
        options: [{ value: 'single', label: 'Single-phase' }, { value: 'three', label: 'Three-phase' }, { value: 'dc', label: 'DC' }] },
    ],
    buildArgs: (v) => ({
      awg_size: int(v.awg_size), material: v.material,
      length_one_way_m: num(v.length_one_way_m), voltage_V: num(v.voltage_V),
      current_A: num(v.current_A), phase: v.phase,
    }),
  },
  {
    name: 'electronics_compute_derated_ampacity',
    icon: Zap,
    color: '#f59e0b',
    desc: 'NEC 2023 Art. 310 wire ampacity derating for ambient temperature + conductor bundling.',
    fields: [
      { key: 'awg_size', label: 'AWG size', type: 'number', default: '12' },
      { key: 'material', label: 'Material', type: 'select', default: 'copper',
        options: [{ value: 'copper', label: 'Copper' }, { value: 'aluminum', label: 'Aluminum' }] },
      { key: 'insulation_class', label: 'Insulation', type: 'select', default: 'THWN',
        options: [
          { value: 'THWN', label: 'THWN (75°C)' }, { value: 'THHN', label: 'THHN (90°C)' },
          { value: 'XHHW', label: 'XHHW (90°C)' },
        ]},
      { key: 'base_ampacity_A', label: 'Base ampacity (A)', type: 'number', default: '20' },
      { key: 'ambient_temp_C', label: 'Ambient temp (°C)', type: 'number', default: '30' },
    ],
    buildArgs: (v) => ({
      awg_size: int(v.awg_size), material: v.material,
      insulation_class: v.insulation_class,
      base_ampacity_A: num(v.base_ampacity_A),
      ambient_temp_C: num(v.ambient_temp_C),
    }),
  },
  {
    name: 'electronics_compute_pcb_trace_current',
    icon: CircuitBoard,
    color: '#f59e0b',
    desc: 'IPC-2221B PCB trace max current from width, copper oz, temperature rise.',
    fields: [
      { key: 'trace_width_mils', label: 'Trace width (mil)', type: 'number', default: '20' },
      { key: 'copper_oz', label: 'Copper (oz)', type: 'number', default: '1' },
      { key: 'delta_T_C', label: 'ΔT allowed (°C)', type: 'number', default: '10' },
      { key: 'location', label: 'Location', type: 'select', default: 'external',
        options: [{ value: 'external', label: 'External' }, { value: 'internal', label: 'Internal' }] },
    ],
    buildArgs: (v) => ({
      trace_width_mils: num(v.trace_width_mils),
      copper_oz: num(v.copper_oz),
      ...(v.delta_T_C ? { delta_T_C: num(v.delta_T_C) } : {}),
      ...(v.location ? { location: v.location } : {}),
    }),
  },
  {
    name: 'electronics_compute_buck_ripple',
    icon: Zap,
    color: '#f59e0b',
    desc: 'Buck DC-DC CCM output voltage ripple: ΔiL, ΔV_cap, ΔV_ESR, total ΔV_out (Erickson 3e §2.4).',
    fields: [
      { key: 'V_in_V', label: 'V_in (V)', type: 'number', default: '12' },
      { key: 'V_out_V', label: 'V_out (V)', type: 'number', default: '5' },
      { key: 'I_load_A', label: 'I_load (A)', type: 'number', default: '2' },
      { key: 'switching_freq_Hz', label: 'Freq (Hz)', type: 'number', default: '400000' },
      { key: 'L_uH', label: 'L (µH)', type: 'number', default: '10' },
      { key: 'C_out_uF', label: 'C_out (µF)', type: 'number', default: '100' },
      { key: 'C_ESR_mOhm', label: 'C ESR (mΩ)', type: 'number', default: '20' },
    ],
    buildArgs: (v) => ({
      V_in_V: num(v.V_in_V), V_out_V: num(v.V_out_V),
      I_load_A: num(v.I_load_A), switching_freq_Hz: num(v.switching_freq_Hz),
      L_uH: num(v.L_uH), C_out_uF: num(v.C_out_uF), C_ESR_mOhm: num(v.C_ESR_mOhm),
    }),
  },
  {
    name: 'electronics_check_ldo_dropout',
    icon: Thermometer,
    color: '#f59e0b',
    desc: 'LDO dropout headroom, power dissipation, T_j, thermal compliance (TI Power Ref §3).',
    fields: [
      { key: 'V_out_V', label: 'V_out (V)', type: 'number', default: '3.3' },
      { key: 'V_in_min_V', label: 'V_in min (V)', type: 'number', default: '4.5' },
      { key: 'V_in_max_V', label: 'V_in max (V)', type: 'number', default: '5.5' },
      { key: 'I_load_A', label: 'I_load (A)', type: 'number', default: '0.5' },
      { key: 'dropout_voltage_at_max_load_mV', label: 'Dropout @ max load (mV)', type: 'number', default: '300' },
      { key: 'junction_to_ambient_thermal_resistance_K_per_W', label: 'θJA (°C/W)', type: 'number', default: '80' },
    ],
    buildArgs: (v) => ({
      V_out_V: num(v.V_out_V), V_in_min_V: num(v.V_in_min_V),
      V_in_max_V: num(v.V_in_max_V), I_load_A: num(v.I_load_A),
      dropout_voltage_at_max_load_mV: num(v.dropout_voltage_at_max_load_mV),
      junction_to_ambient_thermal_resistance_K_per_W: num(v.junction_to_ambient_thermal_resistance_K_per_W),
    }),
  },
  {
    name: 'electronics_compute_pcb_via_current',
    icon: CircuitBoard,
    color: '#f59e0b',
    desc: 'IPC-2152 §6.3 PCB via current capacity: drill, plating, length, ΔT.',
    fields: [
      { key: 'drill_diameter_mm', label: 'Drill diam (mm)', type: 'number', default: '0.3' },
      { key: 'plating_thickness_um', label: 'Plating (µm)', type: 'number', default: '25' },
      { key: 'via_length_mm', label: 'Via length (mm)', type: 'number', default: '1.6' },
      { key: 'temp_rise_C', label: 'ΔT (°C)', type: 'number', default: '10' },
      { key: 'target_current_A', label: 'Target current (A)', type: 'number', default: '1' },
    ],
    buildArgs: (v) => ({
      drill_diameter_mm: num(v.drill_diameter_mm),
      plating_thickness_um: num(v.plating_thickness_um),
      via_length_mm: num(v.via_length_mm),
      ...(v.temp_rise_C ? { temp_rise_C: num(v.temp_rise_C) } : {}),
      ...(v.target_current_A ? { target_current_A: num(v.target_current_A) } : {}),
    }),
  },
]

// ── Section 2: Signal Integrity ────────────────────────────────────────────

const ELEC_SIGNAL = [
  {
    name: 'electronics_check_diffpair_skew',
    icon: CircuitBoard,
    color: '#22d3ee',
    desc: 'Intra-pair skew check vs UI budget (Johnson §12.4 + IPC-2141A §6).',
    fields: [
      { key: 'signal_name', label: 'Signal name', type: 'text', default: 'CLK_DP', placeholder: 'CLK_DP' },
      { key: 'pos_length_mm', label: 'D+ length (mm)', type: 'number', default: '80.5' },
      { key: 'neg_length_mm', label: 'D− length (mm)', type: 'number', default: '81.0' },
      { key: 'data_rate_Mbps', label: 'Data rate (Mbps)', type: 'number', default: '1000' },
    ],
    buildArgs: (v) => ({
      signal_name: v.signal_name,
      pos_length_mm: num(v.pos_length_mm),
      neg_length_mm: num(v.neg_length_mm),
      ...(v.data_rate_Mbps ? { data_rate_Mbps: num(v.data_rate_Mbps) } : {}),
    }),
  },
  {
    name: 'electronics_compute_crystal_load_caps',
    icon: CircuitBoard,
    color: '#22d3ee',
    desc: 'Pierce oscillator CL = (C1·C2)/(C1+C2) + C_stray (NXP AN-2867 §3 + AVR ATmega §28.5).',
    fields: [
      { key: 'frequency_MHz', label: 'Freq (MHz)', type: 'number', default: '16' },
      { key: 'load_capacitance_CL_pF', label: 'CL (pF)', type: 'number', default: '12' },
      { key: 'esr_max_ohms', label: 'ESR max (Ω)', type: 'number', default: '40' },
      { key: 'stray_capacitance_pF', label: 'C_stray (pF)', type: 'number', default: '3' },
    ],
    buildArgs: (v) => ({
      frequency_MHz: num(v.frequency_MHz),
      load_capacitance_CL_pF: num(v.load_capacitance_CL_pF),
      esr_max_ohms: num(v.esr_max_ohms),
      ...(v.stray_capacitance_pF ? { stray_capacitance_pF: num(v.stray_capacitance_pF) } : {}),
    }),
  },
  {
    name: 'electronics_design_emi_filter',
    icon: Shield,
    color: '#22d3ee',
    desc: 'Passive LC/RC power-line EMI filter: corner freq, L, C, attenuation (Ott §15.3 + CISPR 22).',
    fields: [
      { key: 'dc_voltage_V', label: 'Voltage (V)', type: 'number', default: '12' },
      { key: 'dc_current_A', label: 'Current (A)', type: 'number', default: '2' },
      { key: 'target_attenuation_dB', label: 'Attenuation (dB)', type: 'number', default: '40' },
      { key: 'noise_frequency_MHz', label: 'Noise freq (MHz)', type: 'number', default: '10' },
    ],
    buildArgs: (v) => ({
      dc_voltage_V: num(v.dc_voltage_V),
      dc_current_A: num(v.dc_current_A),
      target_attenuation_dB: num(v.target_attenuation_dB),
      noise_frequency_MHz: num(v.noise_frequency_MHz),
    }),
  },
  {
    name: 'elec_analyze_optocoupler',
    icon: CircuitBoard,
    color: '#22d3ee',
    desc: 'Optocoupler isolation circuit: IC_min/typ/max, saturation margin, rise/fall time (Vishay AN-38).',
    fields: [
      { key: 'IF_mA', label: 'I_F (mA)', type: 'number', default: '10' },
      { key: 'CTR_min_percent', label: 'CTR min (%)', type: 'number', default: '100' },
      { key: 'CTR_typ_percent', label: 'CTR typ (%)', type: 'number', default: '150' },
      { key: 'CTR_max_percent', label: 'CTR max (%)', type: 'number', default: '300' },
      { key: 'IF_max_mA', label: 'IF max (mA)', type: 'number', default: '50' },
      { key: 'Vcc_out_V', label: 'Vcc out (V)', type: 'number', default: '5' },
      { key: 'R_pullup_ohm', label: 'R_pullup (Ω)', type: 'number', default: '4700' },
    ],
    buildArgs: (v) => ({
      IF_mA: num(v.IF_mA),
      CTR_min_percent: num(v.CTR_min_percent),
      CTR_typ_percent: num(v.CTR_typ_percent),
      CTR_max_percent: num(v.CTR_max_percent),
      IF_max_mA: num(v.IF_max_mA),
      Vcc_out_V: num(v.Vcc_out_V),
      R_pullup_ohm: num(v.R_pullup_ohm),
    }),
  },
  {
    name: 'elec_compute_zener_drift',
    icon: Zap,
    color: '#22d3ee',
    desc: 'Zener Vz(T) = Vz_nom + TC×(T−T_test); zero-TC crossing ≈ 5.6 V (Sze §4.5 + Vishay AN-2014-3).',
    fields: [
      { key: 'Vz_nominal_V', label: 'Vz nominal (V)', type: 'number', default: '5.6' },
      { key: 'TC_mV_per_C', label: 'TC (mV/°C)', type: 'number', default: '2' },
      { key: 'test_current_mA', label: 'Test current (mA)', type: 'number', default: '5' },
      { key: 'T_min_C', label: 'T min (°C)', type: 'number', default: '-40' },
      { key: 'T_max_C', label: 'T max (°C)', type: 'number', default: '85' },
    ],
    buildArgs: (v) => ({
      Vz_nominal_V: num(v.Vz_nominal_V),
      TC_mV_per_C: num(v.TC_mV_per_C),
      test_current_mA: num(v.test_current_mA),
      T_min_C: num(v.T_min_C),
      T_max_C: num(v.T_max_C),
    }),
  },
]

// ── Section 3: Thermal & Protection ───────────────────────────────────────

const ELEC_THERMAL = [
  {
    name: 'electronics_check_fet_soa',
    icon: Thermometer,
    color: '#ef4444',
    desc: 'MOSFET Safe Operating Area check: within_soa, P_diss, T_J, soa_violation_modes (IRF HDM §5).',
    fields: [
      { key: 'V_DSS_max_V', label: 'VDS max (V)', type: 'number', default: '100' },
      { key: 'I_D_continuous_A', label: 'ID cont (A)', type: 'number', default: '10' },
      { key: 'I_D_pulsed_A', label: 'ID pulse (A)', type: 'number', default: '40' },
      { key: 'R_DS_on_mOhm', label: 'RDS(on) (mΩ)', type: 'number', default: '50' },
      { key: 'R_theta_JA_K_per_W', label: 'θJA (°C/W)', type: 'number', default: '60' },
      { key: 'P_D_max_W', label: 'PD max (W)', type: 'number', default: '2.5' },
      { key: 'V_DS_op_V', label: 'VDS operating (V)', type: 'number', default: '48' },
      { key: 'I_D_op_A', label: 'ID operating (A)', type: 'number', default: '3' },
    ],
    buildArgs: (v) => ({
      V_DSS_max_V: num(v.V_DSS_max_V),
      I_D_continuous_A: num(v.I_D_continuous_A),
      I_D_pulsed_A: num(v.I_D_pulsed_A),
      R_DS_on_mOhm: num(v.R_DS_on_mOhm),
      R_theta_JA_K_per_W: num(v.R_theta_JA_K_per_W),
      P_D_max_W: num(v.P_D_max_W),
      V_DS_op_V: num(v.V_DS_op_V),
      I_D_op_A: num(v.I_D_op_A),
    }),
  },
  {
    name: 'electronics_check_inductor_saturation',
    icon: Thermometer,
    color: '#ef4444',
    desc: 'Inductor core saturation: B_peak vs B_sat, margin %, ferrite temp derating (Erickson §15).',
    fields: [
      { key: 'A_e_mm2', label: 'Core area A_e (mm²)', type: 'number', default: '45' },
      { key: 'l_e_mm', label: 'Mean path l_e (mm)', type: 'number', default: '67' },
      { key: 'B_sat_mT', label: 'B_sat (mT)', type: 'number', default: '380' },
      { key: 'mu_r', label: 'μ_r', type: 'number', default: '2200' },
      { key: 'turns_N', label: 'Turns N', type: 'number', default: '30' },
      { key: 'I_dc_A', label: 'I_DC (A)', type: 'number', default: '1.5' },
      { key: 'I_peak_A', label: 'I_peak (A)', type: 'number', default: '2.0' },
    ],
    buildArgs: (v) => ({
      A_e_mm2: num(v.A_e_mm2), l_e_mm: num(v.l_e_mm), B_sat_mT: num(v.B_sat_mT),
      mu_r: num(v.mu_r), turns_N: int(v.turns_N), I_dc_A: num(v.I_dc_A),
      ...(v.I_peak_A ? { I_peak_A: num(v.I_peak_A) } : {}),
    }),
  },
  {
    name: 'electronics_compute_op_amp_drift',
    icon: Activity,
    color: '#ef4444',
    desc: 'Op-amp Vos(T) + temperature drift, worst-case output error (TI SLOA069 §3 + ADI AN-580).',
    fields: [
      { key: 'Vos_typ_uV', label: 'Vos typ (µV)', type: 'number', default: '200' },
      { key: 'Vos_drift_uV_per_C', label: 'TC (µV/°C)', type: 'number', default: '2' },
      { key: 'T_ambient_min_C', label: 'T min (°C)', type: 'number', default: '-40' },
      { key: 'T_ambient_max_C', label: 'T max (°C)', type: 'number', default: '85' },
      { key: 'gain_VV', label: 'Gain (V/V)', type: 'number', default: '100' },
      { key: 'signal_full_scale_V', label: 'Full scale (V)', type: 'number', default: '5' },
    ],
    buildArgs: (v) => ({
      Vos_typ_uV: num(v.Vos_typ_uV),
      Vos_drift_uV_per_C: num(v.Vos_drift_uV_per_C),
      T_ambient_min_C: num(v.T_ambient_min_C),
      T_ambient_max_C: num(v.T_ambient_max_C),
      gain_VV: num(v.gain_VV),
      signal_full_scale_V: num(v.signal_full_scale_V),
    }),
  },
  {
    name: 'electronics_design_zener_clamp',
    icon: Shield,
    color: '#ef4444',
    desc: 'Zener clamp R_series, power rating, recommended E12 value (H&H §2.2.4 + Vishay AN-2014-3).',
    fields: [
      { key: 'V_in_min_V', label: 'V_in min (V)', type: 'number', default: '5' },
      { key: 'V_in_max_V', label: 'V_in max (V)', type: 'number', default: '15' },
      { key: 'V_zener_V', label: 'V_zener (V)', type: 'number', default: '5.1' },
      { key: 'I_load_max_mA', label: 'I_load max (mA)', type: 'number', default: '20' },
    ],
    buildArgs: (v) => ({
      V_in_min_V: num(v.V_in_min_V), V_in_max_V: num(v.V_in_max_V),
      V_zener_V: num(v.V_zener_V),
      ...(v.I_load_max_mA ? { I_load_max_mA: num(v.I_load_max_mA) } : {}),
    }),
  },
  {
    name: 'electronics_check_fuse_i2t',
    icon: Shield,
    color: '#ef4444',
    desc: 'Fuse I²t melting energy check — clears_safely, breaking capacity (IEC 60269 + Cooper Bussmann).',
    fields: [
      { key: 'nominal_current_A', label: 'Nominal current (A)', type: 'number', default: '5' },
      { key: 'voltage_rating_V', label: 'Voltage rating (V)', type: 'number', default: '250' },
      { key: 'I_squared_t_pre_arc_A2_s', label: 'I²t pre-arc (A²s)', type: 'number', default: '100' },
      { key: 'breaking_capacity_kA', label: 'Breaking cap (kA)', type: 'number', default: '10' },
      { key: 'fuse_class', label: 'Fuse class', type: 'select', default: 'gG',
        options: [
          { value: 'gG', label: 'gG (IEC 60269)' }, { value: 'aM', label: 'aM (motor)' },
          { value: 'gL', label: 'gL (cable)' }, { value: 'RK5', label: 'RK5 (UL)' },
        ]},
      { key: 'peak_current_A', label: 'Peak current (A)', type: 'number', default: '30' },
      { key: 'duration_ms', label: 'Duration (ms)', type: 'number', default: '100' },
      { key: 'available_short_circuit_current_kA', label: 'ASCC (kA)', type: 'number', default: '1' },
    ],
    buildArgs: (v) => ({
      nominal_current_A: num(v.nominal_current_A),
      voltage_rating_V: num(v.voltage_rating_V),
      I_squared_t_pre_arc_A2_s: num(v.I_squared_t_pre_arc_A2_s),
      breaking_capacity_kA: num(v.breaking_capacity_kA),
      fuse_class: v.fuse_class,
      peak_current_A: num(v.peak_current_A),
      duration_ms: num(v.duration_ms),
      available_short_circuit_current_kA: num(v.available_short_circuit_current_kA),
    }),
  },
]

// ── Section 4: RF & Simulation ─────────────────────────────────────────────

const ELEC_RF = [
  {
    name: 'electronics_check_circuit_protection',
    icon: Shield,
    color: '#6366f1',
    desc: 'NEC 2023 Art. 240.4 + Table 310.16 + Art. 215 conductor ampacity + OCPD sizing check.',
    fields: [
      { key: 'awg_size', label: 'AWG size', type: 'number', default: '12' },
      { key: 'material', label: 'Material', type: 'select', default: 'copper',
        options: [{ value: 'copper', label: 'Copper' }, { value: 'aluminum', label: 'Aluminum' }] },
      { key: 'insulation_class', label: 'Insulation', type: 'select', default: 'THWN',
        options: [
          { value: 'THWN', label: 'THWN' }, { value: 'THHN', label: 'THHN' },
          { value: 'XHHW', label: 'XHHW' }, { value: 'RHW', label: 'RHW' },
        ]},
      { key: 'I_continuous_A', label: 'I continuous (A)', type: 'number', default: '12' },
      { key: 'I_non_continuous_A', label: 'I non-cont (A)', type: 'number', default: '2' },
      { key: 'ocpd_rating_A', label: 'OCPD rating (A)', type: 'number', default: '20' },
    ],
    buildArgs: (v) => ({
      conductor: {
        awg_size: int(v.awg_size),
        material: v.material,
        insulation_class: v.insulation_class,
      },
      load: {
        I_continuous_A: num(v.I_continuous_A),
        I_non_continuous_A: num(v.I_non_continuous_A),
      },
      ocpd: { rating_A: num(v.ocpd_rating_A) },
    }),
  },
]

// ---------------------------------------------------------------------------
// Tab content
// ---------------------------------------------------------------------------

function TabMold() {
  const totalMold = MOLD_MATERIAL_FLOW.length + MOLD_COOLING.length + MOLD_EJECTION.length + MOLD_QUALITY.length
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 11, color: '#6b7280' }}>
        {totalMold} mold tools — Material Flow · Cooling · Ejection · Quality
      </div>
      <Section title="Material Flow" icon={Factory} color="#f59e0b"
        cards={MOLD_MATERIAL_FLOW} defaultOpen />
      <Section title="Cooling" icon={Thermometer} color="#06b6d4"
        cards={MOLD_COOLING} defaultOpen />
      <Section title="Ejection" icon={Settings} color="#8b5cf6"
        cards={MOLD_EJECTION} defaultOpen />
    </div>
  )
}

function TabElectronics() {
  const totalElec = ELEC_POWER.length + ELEC_SIGNAL.length + ELEC_THERMAL.length + ELEC_RF.length
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 11, color: '#6b7280' }}>
        {totalElec} electronics tools — Power · Signal Integrity · Thermal & Protection · RF
      </div>
      <Section title="Power" icon={Zap} color="#f59e0b"
        cards={ELEC_POWER} defaultOpen />
      <Section title="Signal Integrity" icon={CircuitBoard} color="#22d3ee"
        cards={ELEC_SIGNAL} defaultOpen />
      <Section title="Thermal & Protection" icon={Thermometer} color="#ef4444"
        cards={ELEC_THERMAL} defaultOpen />
      <Section title="RF / Safety" icon={Shield} color="#6366f1"
        cards={ELEC_RF} defaultOpen={false} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// ManufacturingPanel — main export
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'mold', label: 'Mold (Injection)', icon: Factory },
  { id: 'electronics', label: 'Electronics (PCB/EMC)', icon: CircuitBoard },
]

export default function ManufacturingPanel() {
  const [tab, setTab] = useState('mold')

  const totalMold = MOLD_MATERIAL_FLOW.length + MOLD_COOLING.length + MOLD_EJECTION.length
  const totalElec = ELEC_POWER.length + ELEC_SIGNAL.length + ELEC_THERMAL.length + ELEC_RF.length
  const total = totalMold + totalElec

  return (
    <div style={s.root} data-testid="manufacturing-panel">
      {/* Page header */}
      <div style={s.pageHeader}>
        <Factory size={20} style={{ color: '#f59e0b', flexShrink: 0 }} />
        <div>
          <div style={s.pageTitle}>Manufacturing Panel</div>
          <div style={s.pageSub}>
            Injection-mold DFM · Electronics DFM — {total} tools wired ({totalMold} mold + {totalElec} electronics)
          </div>
        </div>
      </div>

      {/* Top-level tabs */}
      <div style={s.tabs}>
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            style={{ ...s.tab, ...(tab === id ? s.tabActive : {}) }}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'mold' && <TabMold />}
      {tab === 'electronics' && <TabElectronics />}
    </div>
  )
}
