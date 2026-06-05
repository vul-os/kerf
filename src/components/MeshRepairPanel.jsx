// MeshRepairPanel.jsx — Mesh repair & ShrinkWrap panel.
//
// Wires four kerf-cad-core tools:
//   mesh_repair_run      — weld + fill-holes + manifold check (existing)
//   mesh_diagnostics     — genus, holes, watertight (existing)
//   mesh_boolean_run     — union/intersect/subtract (existing)
//   mesh_shrinkwrap_run  — shrinkwrap src mesh onto target surface (NEW — GK-P15)
//
// Pattern: dark mono palette, collapsible ToolCards, callTool helper.

import { useState, useCallback } from 'react'
import {
  Triangle,
  Box,
  Scan,
  Wrench,
  Play,
  Loader2,
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Info,
  Activity,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const API_URL =
  typeof import.meta !== 'undefined' && import.meta.env
    ? import.meta.env.VITE_API_URL || ''
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
// Styles
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
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    paddingBottom: 16,
    borderBottom: '1px solid #1f2937',
  },
  title: { fontSize: 18, fontWeight: 700, color: '#f3f4f6' },
  sub: { fontSize: 11, color: '#6b7280', marginTop: 2 },
  tabs: { display: 'flex', gap: 4, marginBottom: 4, flexWrap: 'wrap' },
  tab: {
    padding: '6px 16px',
    borderRadius: 6,
    border: '1px solid #374151',
    background: '#161b22',
    color: '#9ca3af',
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: 'inherit',
  },
  tabActive: {
    background: '#1a3d1f',
    color: '#4ade80',
    borderColor: '#166534',
  },
  card: {
    background: '#161b22',
    borderRadius: 8,
    border: '1px solid #21262d',
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  cardTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: '#c9d1d9',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    cursor: 'pointer',
    userSelect: 'none',
  },
  cardDesc: { fontSize: 11, color: '#8b949e', lineHeight: 1.5 },
  label: { fontSize: 11, color: '#8b949e', marginBottom: 3 },
  input: {
    width: '100%',
    padding: '6px 10px',
    borderRadius: 5,
    border: '1px solid #30363d',
    background: '#0d1117',
    color: '#e5e7eb',
    fontFamily: 'inherit',
    fontSize: 12,
    boxSizing: 'border-box',
  },
  select: {
    width: '100%',
    padding: '6px 10px',
    borderRadius: 5,
    border: '1px solid #30363d',
    background: '#0d1117',
    color: '#e5e7eb',
    fontFamily: 'inherit',
    fontSize: 12,
    boxSizing: 'border-box',
  },
  textarea: {
    width: '100%',
    padding: '6px 10px',
    borderRadius: 5,
    border: '1px solid #30363d',
    background: '#0d1117',
    color: '#e5e7eb',
    fontFamily: 'inherit',
    fontSize: 11,
    boxSizing: 'border-box',
    minHeight: 70,
    resize: 'vertical',
  },
  button: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '7px 16px',
    borderRadius: 6,
    border: 'none',
    background: '#1a3d1f',
    color: '#d1fae5',
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: 'inherit',
    fontWeight: 600,
  },
  resultBox: {
    marginTop: 4,
    padding: 10,
    borderRadius: 5,
    background: '#0a0e14',
    border: '1px solid #21262d',
    fontSize: 11,
    color: '#a3e635',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
    maxHeight: 240,
    overflowY: 'auto',
  },
  errBox: {
    marginTop: 4,
    padding: 10,
    borderRadius: 5,
    background: '#2a0a0a',
    border: '1px solid #5a1515',
    fontSize: 11,
    color: '#fca5a5',
    whiteSpace: 'pre-wrap',
  },
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '2px 8px',
    borderRadius: 12,
    fontSize: 10,
    fontWeight: 600,
  },
  badgeGreen: { background: '#14532d', color: '#86efac' },
  badgeAmber: { background: '#451a03', color: '#fbbf24' },
  infoBox: {
    padding: '8px 12px',
    borderRadius: 5,
    background: '#0a1e0e',
    border: '1px solid #166534',
    fontSize: 11,
    color: '#86efac',
    lineHeight: 1.5,
  },
  row: { display: 'flex', gap: 12 },
}

// ---------------------------------------------------------------------------
// Example mesh JSON
// ---------------------------------------------------------------------------

// Two-triangle flat plane (no holes, watertight quad split)
const EXAMPLE_SIMPLE_MESH = JSON.stringify({
  vertices: [[0,0,0],[1,0,0],[1,1,0],[0,1,0]],
  faces: [[0,1,2],[0,2,3]],
}, null, 2)

// Single quad mesh as shrinkwrap target
const EXAMPLE_TARGET_MESH = JSON.stringify({
  vertices: [[0,0,0],[2,0,0],[2,2,0],[0,2,0]],
  faces: [[0,1,2],[0,2,3]],
}, null, 2)

// ---------------------------------------------------------------------------
// Reusable ToolCard
// ---------------------------------------------------------------------------

function ToolCard({ icon: Icon, title, description, accentColor = '#4ade80', children }) {
  const [open, setOpen] = useState(true)
  return (
    <div style={s.card}>
      <div style={s.cardTitle} onClick={() => setOpen(v => !v)}>
        {Icon && <Icon size={14} color={accentColor} />}
        {title}
        <span style={{ marginLeft: 'auto' }}>
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
      </div>
      {open && (
        <>
          {description && <div style={s.cardDesc}>{description}</div>}
          {children}
        </>
      )}
    </div>
  )
}

function StatusBadge({ ok }) {
  return ok !== false
    ? <span style={{ ...s.badge, ...s.badgeGreen }}><CheckCircle size={10} /> OK</span>
    : <span style={{ ...s.badge, ...s.badgeAmber }}><AlertTriangle size={10} /> Failed</span>
}

// ---------------------------------------------------------------------------
// MeshRepairTool
// ---------------------------------------------------------------------------

function MeshRepairTool() {
  const [mesh, setMesh] = useState(EXAMPLE_SIMPLE_MESH)
  const [weldTol, setWeldTol] = useState('1e-6')
  const [maxHoleEdges, setMaxHoleEdges] = useState('20')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      let m
      try { m = JSON.parse(mesh) } catch { throw new Error('mesh: invalid JSON') }
      const res = await callTool('mesh_repair_run', {
        vertices: m.vertices,
        faces: m.faces,
        weld_tol: parseFloat(weldTol) || 1e-6,
        max_hole_edges: parseInt(maxHoleEdges, 10) || 20,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [mesh, weldTol, maxHoleEdges])

  return (
    <ToolCard
      icon={Wrench}
      title="Mesh Repair"
      description={
        'Weld duplicate vertices → unify normals → fill small holes → verify manifold. ' +
        'Returns repaired mesh + diagnostics.'
      }
    >
      <div>
        <div style={s.label}>mesh (JSON {'{vertices, faces}'})</div>
        <textarea style={s.textarea} value={mesh} onChange={e => setMesh(e.target.value)} />
      </div>
      <div style={s.row}>
        <div style={{ flex: 1 }}>
          <div style={s.label}>weld_tol</div>
          <input style={s.input} value={weldTol} onChange={e => setWeldTol(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={s.label}>max_hole_edges</div>
          <input style={s.input} value={maxHoleEdges} onChange={e => setMaxHoleEdges(e.target.value)} />
        </div>
      </div>
      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Repair Mesh
      </button>
      {result && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4, flexWrap: 'wrap', fontSize: 11 }}>
            <StatusBadge ok={result.ok} />
            {result.is_manifold != null && (
              result.is_manifold
                ? <span style={{ ...s.badge, ...s.badgeGreen }}>Manifold</span>
                : <span style={{ ...s.badge, ...s.badgeAmber }}>Non-manifold</span>
            )}
            {result.is_closed != null && (
              result.is_closed
                ? <span style={{ ...s.badge, ...s.badgeGreen }}>Closed</span>
                : <span style={{ ...s.badge, ...s.badgeAmber }}>Open</span>
            )}
            {result.holes_filled != null && (
              <span style={{ ...s.badge, background: '#1c1c40', color: '#a5b4fc' }}>
                {result.holes_filled} holes filled
              </span>
            )}
          </div>
          <div style={s.resultBox}>{fmt(result)}</div>
        </div>
      )}
      {error && <div style={s.errBox}><AlertTriangle size={11} /> {error}</div>}
    </ToolCard>
  )
}

// ---------------------------------------------------------------------------
// DiagnosticsTool
// ---------------------------------------------------------------------------

function DiagnosticsTool() {
  const [mesh, setMesh] = useState(EXAMPLE_SIMPLE_MESH)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      let m
      try { m = JSON.parse(mesh) } catch { throw new Error('mesh: invalid JSON') }
      const res = await callTool('mesh_diagnostics', {
        vertices: m.vertices,
        faces: m.faces,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [mesh])

  return (
    <ToolCard
      icon={Activity}
      title="Mesh Diagnostics"
      description="Genus, boundary edges, hole count, watertight check, non-manifold edges, normal consistency."
    >
      <div>
        <div style={s.label}>mesh (JSON {'{vertices, faces}'})</div>
        <textarea style={s.textarea} value={mesh} onChange={e => setMesh(e.target.value)} />
      </div>
      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Run Diagnostics
      </button>
      {result && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4, flexWrap: 'wrap', fontSize: 11 }}>
            <StatusBadge ok={result.ok} />
            {result.is_watertight === true && <span style={{ ...s.badge, ...s.badgeGreen }}>Watertight</span>}
            {result.is_watertight === false && <span style={{ ...s.badge, ...s.badgeAmber }}>Not watertight</span>}
            {result.genus != null && (
              <span style={{ ...s.badge, background: '#1c1c40', color: '#a5b4fc' }}>
                Genus {result.genus}
              </span>
            )}
            {result.hole_count != null && (
              <span style={{ ...s.badge, background: '#1c1c40', color: '#a5b4fc' }}>
                {result.hole_count} holes
              </span>
            )}
          </div>
          <div style={s.resultBox}>{fmt(result)}</div>
        </div>
      )}
      {error && <div style={s.errBox}><AlertTriangle size={11} /> {error}</div>}
    </ToolCard>
  )
}

// ---------------------------------------------------------------------------
// ShrinkWrapTool — GK-P15: new capability
// ---------------------------------------------------------------------------

function ShrinkWrapTool() {
  const [srcMesh, setSrcMesh] = useState(EXAMPLE_SIMPLE_MESH)
  const [tgtMesh, setTgtMesh] = useState(EXAMPLE_TARGET_MESH)
  const [method, setMethod] = useState('nearest_surface_point')
  const [iterations, setIterations] = useState('1')
  const [snapTol, setSnapTol] = useState('1e-6')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      let src, tgt
      try { src = JSON.parse(srcMesh) } catch { throw new Error('source mesh: invalid JSON') }
      try { tgt = JSON.parse(tgtMesh) } catch { throw new Error('target mesh: invalid JSON') }
      const res = await callTool('mesh_shrinkwrap_run', {
        src_vertices: src.vertices,
        src_faces: src.faces,
        tgt_vertices: tgt.vertices,
        tgt_faces: tgt.faces,
        method,
        iterations: parseInt(iterations, 10) || 1,
        snap_tol: parseFloat(snapTol) || 1e-6,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [srcMesh, tgtMesh, method, iterations, snapTol])

  return (
    <ToolCard
      icon={Scan}
      title="ShrinkWrap"
      description={
        'Project source mesh vertices onto target surface. ' +
        'nearest_surface_point: Christer Ericson barycentric closest-point per triangle. ' +
        'project_normal: Möller–Trumbore ray-triangle intersection along vertex normal.'
      }
    >
      <div style={s.infoBox}>
        <Info size={11} style={{ display: 'inline', marginRight: 4 }} />
        Use <strong>nearest_surface_point</strong> for retopo / organic wrapping.
        Use <strong>project_normal</strong> for conforming remesh along a surface.
      </div>
      <div>
        <div style={s.label}>source mesh (JSON {'{vertices, faces}'})</div>
        <textarea style={s.textarea} value={srcMesh} onChange={e => setSrcMesh(e.target.value)} />
      </div>
      <div>
        <div style={s.label}>target mesh (JSON {'{vertices, faces}'})</div>
        <textarea style={s.textarea} value={tgtMesh} onChange={e => setTgtMesh(e.target.value)} />
      </div>
      <div style={s.row}>
        <div style={{ flex: 2 }}>
          <div style={s.label}>method</div>
          <select style={s.select} value={method} onChange={e => setMethod(e.target.value)}>
            <option value="nearest_surface_point">nearest_surface_point</option>
            <option value="project_normal">project_normal</option>
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <div style={s.label}>iterations</div>
          <input style={s.input} value={iterations} onChange={e => setIterations(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={s.label}>snap_tol</div>
          <input style={s.input} value={snapTol} onChange={e => setSnapTol(e.target.value)} />
        </div>
      </div>
      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Shrinkwrap
      </button>
      {result && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4, flexWrap: 'wrap', fontSize: 11 }}>
            <StatusBadge ok={result.ok} />
            {result.projected_count != null && (
              <span style={{ ...s.badge, background: '#1c1c40', color: '#a5b4fc' }}>
                {result.projected_count} vertices projected
              </span>
            )}
            {result.max_displacement != null && (
              <span style={{ ...s.badge, background: '#1c1c40', color: '#a5b4fc' }}>
                max Δ = {result.max_displacement?.toFixed(6)}
              </span>
            )}
          </div>
          <div style={s.resultBox}>{fmt(result)}</div>
        </div>
      )}
      {error && <div style={s.errBox}><AlertTriangle size={11} /> {error}</div>}
    </ToolCard>
  )
}

// ---------------------------------------------------------------------------
// BooleanTool
// ---------------------------------------------------------------------------

function BooleanTool() {
  const [meshA, setMeshA] = useState(EXAMPLE_SIMPLE_MESH)
  const [meshB, setMeshB] = useState(EXAMPLE_TARGET_MESH)
  const [operation, setOperation] = useState('union')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      let a, b
      try { a = JSON.parse(meshA) } catch { throw new Error('mesh A: invalid JSON') }
      try { b = JSON.parse(meshB) } catch { throw new Error('mesh B: invalid JSON') }
      const res = await callTool('mesh_boolean_run', {
        mesh_a: { vertices: a.vertices, faces: a.faces },
        mesh_b: { vertices: b.vertices, faces: b.faces },
        operation,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [meshA, meshB, operation])

  return (
    <ToolCard
      icon={Box}
      title="Mesh Boolean"
      description="Union, intersection, or subtraction between two closed mesh bodies."
    >
      <div>
        <div style={s.label}>mesh A</div>
        <textarea style={s.textarea} value={meshA} onChange={e => setMeshA(e.target.value)} />
      </div>
      <div>
        <div style={s.label}>mesh B</div>
        <textarea style={s.textarea} value={meshB} onChange={e => setMeshB(e.target.value)} />
      </div>
      <div>
        <div style={s.label}>operation</div>
        <select style={{ ...s.select, maxWidth: 200 }} value={operation} onChange={e => setOperation(e.target.value)}>
          <option value="union">Union</option>
          <option value="intersect">Intersect</option>
          <option value="subtract">Subtract (A − B)</option>
        </select>
      </div>
      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Run Boolean
      </button>
      {result && (
        <div>
          <StatusBadge ok={result.ok} />
          <div style={s.resultBox}>{fmt(result)}</div>
        </div>
      )}
      {error && <div style={s.errBox}><AlertTriangle size={11} /> {error}</div>}
    </ToolCard>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const TABS = ['Repair', 'Diagnostics', 'ShrinkWrap', 'Boolean']

export default function MeshRepairPanel({ content } = {}) {
  // content prop: JSON string optionally carrying persisted tab selection.
  const _parsed = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()
  const [tab, setTab] = useState(_parsed.tab || 'Repair')

  return (
    <div style={s.root}>
      <div style={s.header}>
        <Triangle size={20} color="#4ade80" />
        <div>
          <div style={s.title}>Mesh Repair &amp; ShrinkWrap</div>
          <div style={s.sub}>
            Weld · fill holes · manifold · shrinkwrap (GK-P15) · boolean
          </div>
        </div>
      </div>

      <div style={s.tabs}>
        {TABS.map(t => (
          <button
            key={t}
            style={{ ...s.tab, ...(tab === t ? s.tabActive : {}) }}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'Repair' && <MeshRepairTool />}
      {tab === 'Diagnostics' && <DiagnosticsTool />}
      {tab === 'ShrinkWrap' && <ShrinkWrapTool />}
      {tab === 'Boolean' && <BooleanTool />}
    </div>
  )
}
