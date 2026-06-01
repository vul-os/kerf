// GeometryInspector.jsx — B-rep heal / check / analyze inspector panel.
//
// Surfaces 28 brep_* LLM tools across four sections:
//   • Healing       — brep_heal, brep_non_manifold_repair, brep_recover_continuity, ...
//   • Validation    — brep_validate_body, brep_is_manifold, brep_inspect_connectivity, ...
//   • Feature Recog — brep_feature_recognition, brep_recognize_holes, brep_parting_line, ...
//   • Analysis      — brep_analyze_wall_thickness, brep_check_moldability, brep_assembly_interference, ...
//
// All tools dispatch via POST /api/tools/call (routes_tools.py).
// Props: { projectId?: string }

import { useState, useCallback, useRef } from 'react'
import {
  Wrench, Shield, Search, BarChart2, ChevronDown, ChevronRight,
  Play, Loader2, AlertTriangle, CheckCircle, Info, X,
  Layers, Scissors, Cpu, Activity, Eye, Sliders,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Styles — dark mono palette matching feaStyles.js
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
  pageTitle: {
    fontSize: 18,
    fontWeight: 700,
    color: '#f3f4f6',
  },
  pageSub: {
    fontSize: 11,
    color: '#6b7280',
    marginTop: 2,
  },
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
  sectionCount: {
    fontSize: 10,
    color: '#6b7280',
    fontWeight: 400,
  },
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
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  cardTitle: {
    fontWeight: 600,
    fontSize: 12,
    color: '#f3f4f6',
    flex: 1,
  },
  cardDesc: {
    fontSize: 11,
    color: '#6b7280',
    lineHeight: 1.5,
  },
  fields: {
    display: 'flex',
    flexDirection: 'column',
    gap: 5,
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  label: {
    fontSize: 11,
    color: '#9ca3af',
    width: 100,
    flexShrink: 0,
  },
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
  runBtnDisabled: {
    opacity: 0.45,
    cursor: 'not-allowed',
  },
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
    maxHeight: 180,
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
// Shared helpers
// ---------------------------------------------------------------------------

const API_URL = typeof import.meta !== 'undefined' && import.meta.env
  ? (import.meta.env.VITE_API_URL || '')
  : ''

async function callTool(toolName, args, projectId) {
  const body = { tool: toolName, args }
  if (projectId) body.project_id = projectId

  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const txt = await res.text()
    throw new Error(`${res.status}: ${txt}`)
  }
  const data = await res.json()
  // Unwrap if the tool returned a JSON string
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
// ToolCard — a single collapsible tool card
// ---------------------------------------------------------------------------

function ToolCard({ name, icon: Icon, color, desc, fields, buildArgs, projectId }) {
  const [values, setValues] = useState(() =>
    Object.fromEntries(fields.map((f) => [f.key, f.default ?? '']))
  )
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  function set(key, val) {
    setValues((v) => ({ ...v, [key]: val }))
  }

  async function run() {
    setRunning(true)
    setResult(null)
    setError(null)
    try {
      const args = buildArgs ? buildArgs(values) : values
      const res = await callTool(name, args, projectId)
      setResult(res)
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
                <select
                  value={values[f.key]}
                  onChange={(e) => set(f.key, e.target.value)}
                  style={s.select}
                  disabled={running}
                >
                  {f.options.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              ) : f.type === 'textarea' ? (
                <textarea
                  value={values[f.key]}
                  onChange={(e) => set(f.key, e.target.value)}
                  style={{ ...s.input, height: 48, resize: 'vertical' }}
                  disabled={running}
                  placeholder={f.placeholder || ''}
                />
              ) : (
                <input
                  type={f.type || 'text'}
                  value={values[f.key]}
                  onChange={(e) => set(f.key, e.target.value)}
                  style={s.input}
                  disabled={running}
                  placeholder={f.placeholder || ''}
                />
              )}
            </div>
          ))}
        </div>
      )}

      <button
        onClick={run}
        disabled={running}
        style={{ ...s.runBtn, ...(running ? s.runBtnDisabled : {}) }}
      >
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
// Section — collapsible section header + card grid
// ---------------------------------------------------------------------------

function Section({ title, icon: Icon, color, cards, projectId, defaultOpen = true }) {
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
          {cards.map((card) => (
            <ToolCard key={card.name} {...card} projectId={projectId} />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool definitions — 28 tools across 4 sections
// ---------------------------------------------------------------------------

function buildBodyArg(values) {
  // Most heal/validate tools accept body_json as JSON text in the field.
  // Try to parse it; fall back to passing as-is (string).
  try {
    return { body_json: JSON.parse(values.body_json), tol: parseFloat(values.tol) || undefined }
  } catch {
    return { body_json: values.body_json, tol: parseFloat(values.tol) || undefined }
  }
}

function buildFacesArg(values) {
  try {
    return { faces: JSON.parse(values.faces_json) }
  } catch {
    return { faces: values.faces_json }
  }
}

function buildTopologyArg(values) {
  try {
    return { topology: JSON.parse(values.topology_json) }
  } catch {
    return { topology: values.topology_json }
  }
}

const HEALING_CARDS = [
  {
    name: 'brep_heal',
    icon: Wrench,
    color: '#f59e0b',
    desc: 'Full industrial heal pass: merge vertices, stitch cracks, fix non-manifold edges, fill holes, unify normals (Weiler 1985).',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body","faces":[...]}', default: '' },
      { key: 'tol', label: 'Tolerance', type: 'number', placeholder: '1e-5', default: '1e-5' },
    ],
    buildArgs: (v) => {
      const args = {}
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      if (v.tol) args.tol = parseFloat(v.tol)
      return args
    },
  },
  {
    name: 'brep_non_manifold_repair',
    icon: Wrench,
    color: '#f59e0b',
    desc: 'Detect and repair non-manifold edges (T-junctions, fan-edges) by topological split.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
    ],
    buildArgs: (v) => {
      try { return { body_json: JSON.parse(v.body_json) } } catch { return { body_json: v.body_json } }
    },
  },
  {
    name: 'brep_recover_continuity',
    icon: Wrench,
    color: '#f59e0b',
    desc: 'Recover G1/G2 surface continuity across shared edges after STEP import or Boolean operations.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'target_continuity', label: 'Target', type: 'select', default: 'G1', options: [
        { value: 'G0', label: 'G0 (positional)' },
        { value: 'G1', label: 'G1 (tangent)' },
        { value: 'G2', label: 'G2 (curvature)' },
      ]},
    ],
    buildArgs: (v) => {
      const args = { target_continuity: v.target_continuity }
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      return args
    },
  },
  {
    name: 'brep_make_hollow',
    icon: Layers,
    color: '#f59e0b',
    desc: 'Shell a solid body to a given wall thickness (offset shell body).',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'thickness', label: 'Thickness (mm)', type: 'number', placeholder: '2.0', default: '2.0' },
    ],
    buildArgs: (v) => {
      const args = { thickness: parseFloat(v.thickness) || 2.0 }
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      return args
    },
  },
  {
    name: 'brep_make_faces_compatible',
    icon: Wrench,
    color: '#f59e0b',
    desc: 'Re-parametrize adjacent face pairs so shared edge curves are within tolerance.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'tol', label: 'Tolerance', type: 'number', placeholder: '1e-4', default: '1e-4' },
    ],
    buildArgs: (v) => {
      const args = {}
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      if (v.tol) args.tol = parseFloat(v.tol)
      return args
    },
  },
  {
    name: 'brep_detect_and_flip_face_normals',
    icon: Eye,
    color: '#f59e0b',
    desc: 'BFS-propagate face orientations; flip inconsistently-oriented faces so normals point outward.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
    ],
    buildArgs: (v) => {
      try { return { body_json: JSON.parse(v.body_json) } } catch { return { body_json: v.body_json } }
    },
  },
]

const VALIDATION_CARDS = [
  {
    name: 'brep_validate_body',
    icon: Shield,
    color: '#22d3ee',
    desc: 'Full topology + geometry validation: Euler formula, edge-pair closure, face normals, degenerate edges.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
    ],
    buildArgs: (v) => {
      try { return { body_json: JSON.parse(v.body_json) } } catch { return { body_json: v.body_json } }
    },
  },
  {
    name: 'brep_is_manifold',
    icon: Shield,
    color: '#22d3ee',
    desc: 'Boolean check: is the shell a closed 2-manifold (no boundary/non-manifold edges, single component)?',
    fields: [
      { key: 'faces_json', label: 'Faces JSON', type: 'textarea', placeholder: '[{"face_id":0,"edges":[...]}]', default: '' },
    ],
    buildArgs: buildFacesArg,
  },
  {
    name: 'brep_inspect_connectivity',
    icon: Shield,
    color: '#22d3ee',
    desc: 'Classify every edge by radial valence (Weiler 1985): dangling / boundary / manifold / non-manifold. Euler–Poincaré V-E+F.',
    fields: [
      { key: 'faces_json', label: 'Faces JSON', type: 'textarea', placeholder: '[{"face_id":0,"edges":[...]}]', default: '' },
    ],
    buildArgs: buildFacesArg,
  },
  {
    name: 'brep_verify_euler_topology',
    icon: Shield,
    color: '#22d3ee',
    desc: 'Verify the Euler–Poincaré characteristic (V-E+F=2 for a sphere-topology solid).',
    fields: [
      { key: 'faces_json', label: 'Faces JSON', type: 'textarea', placeholder: '[{"face_id":0,"edges":[...]}]', default: '' },
    ],
    buildArgs: buildFacesArg,
  },
  {
    name: 'brep_check_wire_closed',
    icon: Shield,
    color: '#22d3ee',
    desc: 'Verify every face wire (outer + inner loops) is topologically closed.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
    ],
    buildArgs: (v) => {
      try { return { body_json: JSON.parse(v.body_json) } } catch { return { body_json: v.body_json } }
    },
  },
  {
    name: 'brep_check_vertex_degrees',
    icon: Shield,
    color: '#22d3ee',
    desc: 'Report vertex valence histogram; flag vertices with unusual edge counts.',
    fields: [
      { key: 'faces_json', label: 'Faces JSON', type: 'textarea', placeholder: '[{"face_id":0,"edges":[...]}]', default: '' },
    ],
    buildArgs: buildFacesArg,
  },
  {
    name: 'brep_non_manifold_check',
    icon: Shield,
    color: '#22d3ee',
    desc: 'Lightweight non-manifold check: returns list of non-manifold edge IDs and their valence counts.',
    fields: [
      { key: 'faces_json', label: 'Faces JSON', type: 'textarea', placeholder: '[{"face_id":0,"edges":[...]}]', default: '' },
    ],
    buildArgs: buildFacesArg,
  },
]

const FEATURE_RECOG_CARDS = [
  {
    name: 'brep_feature_recognition',
    icon: Search,
    color: '#a78bfa',
    desc: 'ISO 10303-224 / Han-Pratt-Regli 2000 feature recognition: holes, slots, pockets, fillets, chamfers, bosses, ribs, steps.',
    fields: [
      { key: 'topology_json', label: 'Topology JSON', type: 'textarea', placeholder: '{"faces":[{"id":0,"type":"planar",...}]}', default: '' },
    ],
    buildArgs: buildTopologyArg,
  },
  {
    name: 'brep_recognize_holes',
    icon: Search,
    color: '#a78bfa',
    desc: 'Tang-Pratt thread/hole detection: through-holes, blind holes, counterbores, countersinks, threaded bore classification.',
    fields: [
      { key: 'topology_json', label: 'Topology JSON', type: 'textarea', placeholder: '{"faces":[...]}', default: '' },
    ],
    buildArgs: buildTopologyArg,
  },
  {
    name: 'brep_parting_line',
    icon: Scissors,
    color: '#a78bfa',
    desc: 'Compute the optimal mold parting line for injection-mold tool split, given a pull direction.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'pull_dir', label: 'Pull direction', type: 'text', placeholder: '[0,0,1]', default: '[0,0,1]' },
    ],
    buildArgs: (v) => {
      const args = {}
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      try { args.pull_direction = JSON.parse(v.pull_dir) } catch { args.pull_direction = v.pull_dir }
      return args
    },
  },
  {
    name: 'brep_detect_undercuts',
    icon: Search,
    color: '#a78bfa',
    desc: 'Detect undercut faces that cannot be released in the given pull direction (mold-design DFM).',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'pull_dir', label: 'Pull direction', type: 'text', placeholder: '[0,0,1]', default: '[0,0,1]' },
    ],
    buildArgs: (v) => {
      const args = {}
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      try { args.pull_direction = JSON.parse(v.pull_dir) } catch { args.pull_direction = v.pull_dir }
      return args
    },
  },
  {
    name: 'brep_optimal_pull_direction',
    icon: Search,
    color: '#a78bfa',
    desc: 'Search for the pull direction that minimises undercut area for injection moulding.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'n_candidates', label: 'Candidates', type: 'number', placeholder: '36', default: '36' },
    ],
    buildArgs: (v) => {
      const args = { n_candidates: parseInt(v.n_candidates, 10) || 36 }
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      return args
    },
  },
  {
    name: 'brep_classify_edges',
    icon: Cpu,
    color: '#a78bfa',
    desc: 'Classify every edge as convex / concave / tangent based on the dihedral angle between adjacent faces.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
    ],
    buildArgs: (v) => {
      try { return { body_json: JSON.parse(v.body_json) } } catch { return { body_json: v.body_json } }
    },
  },
  {
    name: 'brep_face_neighbors',
    icon: Search,
    color: '#a78bfa',
    desc: 'Return adjacency list: for each face_id, the set of neighboring face_ids sharing an edge.',
    fields: [
      { key: 'faces_json', label: 'Faces JSON', type: 'textarea', placeholder: '[{"face_id":0,"edges":[...]}]', default: '' },
    ],
    buildArgs: buildFacesArg,
  },
]

const ANALYSIS_CARDS = [
  {
    name: 'brep_analyze_wall_thickness',
    icon: BarChart2,
    color: '#34d399',
    desc: 'Analyse wall thickness by inward-ray casting. Returns per-face min, global min/max, injection-moulding guideline.',
    fields: [
      { key: 'shape', label: 'Primitive', type: 'select', default: 'box', options: [
        { value: 'box',      label: 'Box' },
        { value: 'sphere',   label: 'Sphere' },
        { value: 'cylinder', label: 'Cylinder' },
      ]},
      { key: 'size', label: 'Size [mm]', type: 'text', placeholder: '[50,30,20]', default: '[50,30,20]' },
      { key: 'material', label: 'Material', type: 'select', default: 'abs', options: [
        { value: 'abs',         label: 'ABS' },
        { value: 'polypropylene', label: 'Polypropylene' },
        { value: 'nylon',       label: 'Nylon' },
        { value: 'pom',         label: 'POM (Delrin)' },
      ]},
    ],
    buildArgs: (v) => {
      const args = { shape: v.shape, material: v.material }
      try { args.size = JSON.parse(v.size) } catch { args.size = v.size }
      return args
    },
  },
  {
    name: 'brep_check_moldability',
    icon: BarChart2,
    color: '#34d399',
    desc: 'Draft-angle + undercut check for injection moulding. Returns face draft angles and pass/fail per face.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'pull_dir', label: 'Pull direction', type: 'text', placeholder: '[0,0,1]', default: '[0,0,1]' },
      { key: 'min_draft_deg', label: 'Min draft (°)', type: 'number', placeholder: '1.0', default: '1.0' },
    ],
    buildArgs: (v) => {
      const args = { min_draft_deg: parseFloat(v.min_draft_deg) || 1.0 }
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      try { args.pull_direction = JSON.parse(v.pull_dir) } catch { args.pull_direction = v.pull_dir }
      return args
    },
  },
  {
    name: 'brep_assembly_interference',
    icon: Activity,
    color: '#34d399',
    desc: 'Möller-Trumbore + AABB BVH assembly interference check. Returns clash pairs and penetration depth.',
    fields: [
      { key: 'file_id', label: 'File ID', type: 'text', placeholder: 'uuid', default: '' },
      { key: 'method', label: 'Method', type: 'select', default: 'boolean', options: [
        { value: 'boolean',      label: 'Boolean (exact)' },
        { value: 'monte_carlo',  label: 'Monte Carlo' },
        { value: 'voxel',        label: 'Voxel' },
      ]},
    ],
    buildArgs: (v) => ({
      file_id: v.file_id,
      method: v.method,
    }),
  },
  {
    name: 'brep_general_boolean',
    icon: BarChart2,
    color: '#34d399',
    desc: 'GK-P09 planar polyhedra boolean: union / intersection / difference on two closed bodies.',
    fields: [
      { key: 'body_a', label: 'Body A JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'body_b', label: 'Body B JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'operation', label: 'Operation', type: 'select', default: 'union', options: [
        { value: 'union',        label: 'Union' },
        { value: 'intersection', label: 'Intersection' },
        { value: 'difference',   label: 'Difference' },
      ]},
    ],
    buildArgs: (v) => {
      const args = { operation: v.operation }
      try { args.body_a = JSON.parse(v.body_a) } catch { args.body_a = v.body_a }
      try { args.body_b = JSON.parse(v.body_b) } catch { args.body_b = v.body_b }
      return args
    },
  },
  {
    name: 'brep_compute_inertia',
    icon: Sliders,
    color: '#34d399',
    desc: 'Mass properties: volume, surface area, centroid, inertia tensor (Eberly 1999 divergence theorem).',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'quad_order', label: 'Quad order', type: 'number', placeholder: '20', default: '20' },
    ],
    buildArgs: (v) => {
      const args = { quad_order: parseInt(v.quad_order, 10) || 20 }
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      return args
    },
  },
  {
    name: 'brep_volume_above_plane',
    icon: BarChart2,
    color: '#34d399',
    desc: 'Compute the volume of a solid body above a given cutting plane.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'plane_point', label: 'Plane point', type: 'text', placeholder: '[0,0,0]', default: '[0,0,0]' },
      { key: 'plane_normal', label: 'Plane normal', type: 'text', placeholder: '[0,0,1]', default: '[0,0,1]' },
    ],
    buildArgs: (v) => {
      const args = {}
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      try { args.plane_point = JSON.parse(v.plane_point) } catch { args.plane_point = v.plane_point }
      try { args.plane_normal = JSON.parse(v.plane_normal) } catch { args.plane_normal = v.plane_normal }
      return args
    },
  },
  {
    name: 'brep_multi_plane_section',
    icon: Scissors,
    color: '#34d399',
    desc: 'Generate cross-section contours at multiple parallel planes (serial section analysis).',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'axis', label: 'Section axis', type: 'select', default: 'z', options: [
        { value: 'x', label: 'X axis' },
        { value: 'y', label: 'Y axis' },
        { value: 'z', label: 'Z axis' },
      ]},
      { key: 'n_sections', label: 'Sections', type: 'number', placeholder: '10', default: '10' },
    ],
    buildArgs: (v) => {
      const args = { axis: v.axis, n_sections: parseInt(v.n_sections, 10) || 10 }
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      return args
    },
  },
  {
    name: 'brep_solid_contains_point',
    icon: Search,
    color: '#34d399',
    desc: 'Ray-parity inside/outside test: is a 3D point inside the closed solid?',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'point', label: 'Point [x,y,z]', type: 'text', placeholder: '[0,0,0]', default: '[0,0,0]' },
    ],
    buildArgs: (v) => {
      const args = {}
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      try { args.point = JSON.parse(v.point) } catch { args.point = v.point }
      return args
    },
  },
  {
    name: 'brep_check_face_planarity',
    icon: Shield,
    color: '#34d399',
    desc: 'Report planarity deviation (max distance from best-fit plane) for each face.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'tol', label: 'Flatness tol', type: 'number', placeholder: '1e-4', default: '1e-4' },
    ],
    buildArgs: (v) => {
      const args = {}
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      if (v.tol) args.tol = parseFloat(v.tol)
      return args
    },
  },
  {
    name: 'brep_total_edge_length',
    icon: BarChart2,
    color: '#34d399',
    desc: 'Sum total edge length in the B-rep; break down by convex / concave / tangent edge kind.',
    fields: [
      { key: 'faces_json', label: 'Faces JSON', type: 'textarea', placeholder: '[{"face_id":0,"edges":[{"edge_id":0,"start":0,"end":1,"length":1.0}]}]', default: '' },
    ],
    buildArgs: buildFacesArg,
  },
  {
    name: 'brep_edge_length_by_kind',
    icon: BarChart2,
    color: '#34d399',
    desc: 'Total edge length broken down by type: linear, arc, B-spline, composite.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
    ],
    buildArgs: (v) => {
      try { return { body_json: JSON.parse(v.body_json) } } catch { return { body_json: v.body_json } }
    },
  },
  {
    name: 'brep_uv_unwrap',
    icon: Layers,
    color: '#34d399',
    desc: 'UV-atlas unwrap for B-rep faces; returns per-face UV coordinates and distortion estimate.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'method', label: 'Method', type: 'select', default: 'conformal', options: [
        { value: 'conformal', label: 'Conformal (LSCM)' },
        { value: 'angle',     label: 'Angle-based' },
      ]},
    ],
    buildArgs: (v) => {
      const args = { method: v.method }
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      return args
    },
  },
  {
    name: 'brep_uv_distortion_report',
    icon: BarChart2,
    color: '#34d399',
    desc: 'Report UV distortion metrics (area, angle, stretch) for an existing UV unwrap.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
    ],
    buildArgs: (v) => {
      try { return { body_json: JSON.parse(v.body_json) } } catch { return { body_json: v.body_json } }
    },
  },
  {
    name: 'brep_check_clearance',
    icon: Activity,
    color: '#34d399',
    desc: 'Minimum clearance check between two bodies — returns closest approach distance.',
    fields: [
      { key: 'body_a', label: 'Body A JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'body_b', label: 'Body B JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'min_clearance', label: 'Min clearance', type: 'number', placeholder: '0.5', default: '0.5' },
    ],
    buildArgs: (v) => {
      const args = { min_clearance: parseFloat(v.min_clearance) || 0.5 }
      try { args.body_a = JSON.parse(v.body_a) } catch { args.body_a = v.body_a }
      try { args.body_b = JSON.parse(v.body_b) } catch { args.body_b = v.body_b }
      return args
    },
  },
  {
    name: 'brep_check_shell_walls',
    icon: Shield,
    color: '#34d399',
    desc: 'Detect shell walls below minimum printable or mouldable thickness.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'min_wall_mm', label: 'Min wall (mm)', type: 'number', placeholder: '1.0', default: '1.0' },
    ],
    buildArgs: (v) => {
      const args = { min_wall_mm: parseFloat(v.min_wall_mm) || 1.0 }
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      return args
    },
  },
  {
    name: 'brep_centroid_density_field',
    icon: BarChart2,
    color: '#34d399',
    desc: 'Compute a per-voxel density field from a mesh centroid distribution for topology pre-processing.',
    fields: [
      { key: 'body_json', label: 'Body JSON', type: 'textarea', placeholder: '{"type":"Body",...}', default: '' },
      { key: 'resolution', label: 'Grid resolution', type: 'number', placeholder: '32', default: '32' },
    ],
    buildArgs: (v) => {
      const args = { resolution: parseInt(v.resolution, 10) || 32 }
      try { args.body_json = JSON.parse(v.body_json) } catch { args.body_json = v.body_json }
      return args
    },
  },
]

// ---------------------------------------------------------------------------
// GeometryInspector — main page component
// ---------------------------------------------------------------------------

export default function GeometryInspector({ projectId }) {
  const totalTools =
    HEALING_CARDS.length +
    VALIDATION_CARDS.length +
    FEATURE_RECOG_CARDS.length +
    ANALYSIS_CARDS.length

  return (
    <div style={s.root} data-testid="geometry-inspector">
      {/* Page header */}
      <div style={s.pageHeader}>
        <Wrench size={20} style={{ color: '#22d3ee', flexShrink: 0 }} />
        <div>
          <div style={s.pageTitle}>Geometry Inspector</div>
          <div style={s.pageSub}>
            B-rep heal · validate · feature recognition · analysis — {totalTools} tools wired
            {projectId && <> · project <code style={{ color: '#6b7280' }}>{projectId.slice(0, 8)}…</code></>}
          </div>
        </div>
      </div>

      {/* Sections */}
      <Section
        title="Healing"
        icon={Wrench}
        color="#f59e0b"
        cards={HEALING_CARDS}
        projectId={projectId}
        defaultOpen
      />

      <Section
        title="Validation"
        icon={Shield}
        color="#22d3ee"
        cards={VALIDATION_CARDS}
        projectId={projectId}
        defaultOpen
      />

      <Section
        title="Feature Recognition"
        icon={Search}
        color="#a78bfa"
        cards={FEATURE_RECOG_CARDS}
        projectId={projectId}
        defaultOpen={false}
      />

      <Section
        title="Analysis"
        icon={BarChart2}
        color="#34d399"
        cards={ANALYSIS_CARDS}
        projectId={projectId}
        defaultOpen={false}
      />
    </div>
  )
}
