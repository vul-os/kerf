// SurfacingPanel.jsx — NURBS surfacing panel: Gordon/network surface,
// skinning loft, loft with guide rails, blend surface.
//
// Wires three kerf-cad-core tools:
//   nurbs_gordon_network_surface  — True Gordon/Coons-Gordon interpolating both curve families
//   nurbs_skinning_loft           — Skinning loft through profiles
//   nurbs_loft_with_guides        — Guide-rail loft (Gordon fallback)
//
// Pattern follows ManufacturingPanel.jsx: dark mono palette, callTool helper,
// tab + section structure, no external deps beyond lucide-react.
//
// Props: none — standalone panel

import { useState, useCallback } from 'react'
import {
  Layers,
  GitBranch,
  Sliders,
  Play,
  Loader2,
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Info,
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
    try {
      return JSON.parse(data.result)
    } catch {
      return data.result
    }
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
    background: '#1f4d7a',
    color: '#60a5fa',
    borderColor: '#1d4ed8',
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
    minHeight: 80,
    resize: 'vertical',
  },
  button: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '7px 16px',
    borderRadius: 6,
    border: 'none',
    background: '#1f4d7a',
    color: '#eff6ff',
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
    background: '#0a1628',
    border: '1px solid #1e3a5f',
    fontSize: 11,
    color: '#93c5fd',
    lineHeight: 1.5,
  },
}

// ---------------------------------------------------------------------------
// Example curve JSON for the input fields
// ---------------------------------------------------------------------------

const EXAMPLE_LINE_CURVE = JSON.stringify({
  control_points: [[0, 0, 0], [1, 0, 0]],
  knots: [0, 0, 1, 1],
  degree: 1,
}, null, 2)

const EXAMPLE_U_CURVES = JSON.stringify([
  { control_points: [[0, 0, 0], [1, 0, 0]], knots: [0, 0, 1, 1], degree: 1 },
  { control_points: [[0, 1, 0], [1, 1, 0]], knots: [0, 0, 1, 1], degree: 1 },
], null, 2)

const EXAMPLE_V_CURVES = JSON.stringify([
  { control_points: [[0, 0, 0], [0, 1, 0]], knots: [0, 0, 1, 1], degree: 1 },
  { control_points: [[1, 0, 0], [1, 1, 0]], knots: [0, 0, 1, 1], degree: 1 },
], null, 2)

// ---------------------------------------------------------------------------
// Reusable ToolCard
// ---------------------------------------------------------------------------

function ToolCard({ icon: Icon, title, description, children }) {
  const [open, setOpen] = useState(true)
  return (
    <div style={s.card}>
      <div
        style={{ ...s.cardTitle, cursor: 'pointer', userSelect: 'none' }}
        onClick={() => setOpen(v => !v)}
      >
        {Icon && <Icon size={14} />}
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

// ---------------------------------------------------------------------------
// GordonNetworkTool
// ---------------------------------------------------------------------------

function GordonNetworkTool() {
  const [uCurves, setUCurves] = useState(EXAMPLE_U_CURVES)
  const [vCurves, setVCurves] = useState(EXAMPLE_V_CURVES)
  const [tol, setTol] = useState('1e-4')
  const [gridN, setGridN] = useState('20')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      let uc, vc
      try { uc = JSON.parse(uCurves) } catch { throw new Error('u_curves: invalid JSON') }
      try { vc = JSON.parse(vCurves) } catch { throw new Error('v_curves: invalid JSON') }
      const res = await callTool('nurbs_gordon_network_surface', {
        u_curves: uc,
        v_curves: vc,
        tol: parseFloat(tol) || 1e-4,
        grid_n: parseInt(gridN, 10) || 20,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [uCurves, vCurves, tol, gridN])

  return (
    <ToolCard
      icon={GitBranch}
      title="Gordon / Coons-Gordon Network Surface"
      description={
        'Interpolates both u-direction AND v-direction curve families exactly. ' +
        'Gordon formula: G(u,v) = Σ L_i(v)·c_i(u) + Σ M_j(u)·d_j(v) − Σ L_i(v)·M_j(u)·P_ij. ' +
        'Ref: W. J. Gordon (1969), Piegl & Tiller §12.4.'
      }
    >
      <div style={s.infoBox}>
        <Info size={11} style={{ display: 'inline', marginRight: 4 }} />
        Intersection check: every u-curve must cross every v-curve within <code>tol</code>.
        Use evenly-spaced lines in opposite directions for a valid test case.
      </div>
      <div>
        <div style={s.label}>u_curves (JSON array of curve objects)</div>
        <textarea
          style={s.textarea}
          value={uCurves}
          onChange={e => setUCurves(e.target.value)}
          rows={5}
        />
      </div>
      <div>
        <div style={s.label}>v_curves (JSON array of curve objects)</div>
        <textarea
          style={s.textarea}
          value={vCurves}
          onChange={e => setVCurves(e.target.value)}
          rows={5}
        />
      </div>
      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={s.label}>Tolerance (tol)</div>
          <input style={s.input} value={tol} onChange={e => setTol(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={s.label}>Grid N</div>
          <input style={s.input} value={gridN} onChange={e => setGridN(e.target.value)} />
        </div>
      </div>
      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Compute Gordon Surface
      </button>
      {result && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            {result.ok !== false
              ? <span style={{ ...s.badge, ...s.badgeGreen }}><CheckCircle size={10} /> OK</span>
              : <span style={{ ...s.badge, ...s.badgeAmber }}><AlertTriangle size={10} /> Failed</span>}
          </div>
          {result.surface && (
            <div style={{ fontSize: 11, color: '#8b949e' }}>
              Degree: {result.surface.degree_u}×{result.surface.degree_v} ·
              Control net: {result.surface.num_control_points_u}×{result.surface.num_control_points_v}
            </div>
          )}
          <div style={s.resultBox}>{fmt(result)}</div>
        </div>
      )}
      {error && <div style={s.errBox}><AlertTriangle size={11} /> {error}</div>}
    </ToolCard>
  )
}

// ---------------------------------------------------------------------------
// SkinningLoftTool
// ---------------------------------------------------------------------------

function SkinningLoftTool() {
  const [profiles, setProfiles] = useState(EXAMPLE_U_CURVES)
  const [degreeU, setDegreeU] = useState('3')
  const [ruled, setRuled] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      let profs
      try { profs = JSON.parse(profiles) } catch { throw new Error('profiles: invalid JSON') }
      const res = await callTool('nurbs_skinning_loft', {
        profiles: profs,
        degree_u: parseInt(degreeU, 10) || 3,
        ruled,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [profiles, degreeU, ruled])

  return (
    <ToolCard
      icon={Layers}
      title="Skinning Loft"
      description={
        'Skin (loft) through an ordered sequence of cross-section profiles. ' +
        'B-spline global interpolation (Piegl & Tiller §10.4). ' +
        'Ruled=true gives linear connections between profiles.'
      }
    >
      <div>
        <div style={s.label}>profiles (JSON array)</div>
        <textarea
          style={s.textarea}
          value={profiles}
          onChange={e => setProfiles(e.target.value)}
          rows={5}
        />
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <div style={s.label}>degree_u</div>
          <input style={s.input} value={degreeU} onChange={e => setDegreeU(e.target.value)} />
        </div>
        <label style={{ fontSize: 12, color: '#9ca3af', display: 'flex', alignItems: 'center', gap: 5, paddingBottom: 1 }}>
          <input type="checkbox" checked={ruled} onChange={e => setRuled(e.target.checked)} />
          Ruled (linear)
        </label>
      </div>
      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Loft Profiles
      </button>
      {result && (
        <div>
          {result.surface && (
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>
              Degree: {result.surface.degree_u}×{result.surface.degree_v} ·
              Control net: {result.surface.num_control_points_u}×{result.surface.num_control_points_v}
            </div>
          )}
          <div style={s.resultBox}>{fmt(result)}</div>
        </div>
      )}
      {error && <div style={s.errBox}><AlertTriangle size={11} /> {error}</div>}
    </ToolCard>
  )
}

// ---------------------------------------------------------------------------
// LoftWithGuidesTool
// ---------------------------------------------------------------------------

function LoftWithGuidesTool() {
  const [profiles, setProfiles] = useState(EXAMPLE_U_CURVES)
  const [guides, setGuides] = useState(EXAMPLE_V_CURVES)
  const [degreeU, setDegreeU] = useState('3')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      let profs, gcs
      try { profs = JSON.parse(profiles) } catch { throw new Error('profiles: invalid JSON') }
      try { gcs = JSON.parse(guides) } catch { throw new Error('guide_curves: invalid JSON') }
      const res = await callTool('nurbs_loft_with_guides', {
        profiles: profs,
        guide_curves: gcs,
        degree_u: parseInt(degreeU, 10) || 3,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [profiles, guides, degreeU])

  return (
    <ToolCard
      icon={Sliders}
      title="Loft with Guide Rails"
      description={
        'Loft through profiles constrained by guide-rail curves (Gordon surface). ' +
        'Guide rails must intersect every profile.  Falls back to skinning loft ' +
        'with a warning when intersection tolerance is not met.'
      }
    >
      <div>
        <div style={s.label}>profiles (JSON array)</div>
        <textarea
          style={s.textarea}
          value={profiles}
          onChange={e => setProfiles(e.target.value)}
          rows={4}
        />
      </div>
      <div>
        <div style={s.label}>guide_curves (JSON array)</div>
        <textarea
          style={s.textarea}
          value={guides}
          onChange={e => setGuides(e.target.value)}
          rows={4}
        />
      </div>
      <div>
        <div style={s.label}>degree_u</div>
        <input
          style={{ ...s.input, maxWidth: 120 }}
          value={degreeU}
          onChange={e => setDegreeU(e.target.value)}
        />
      </div>
      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Loft with Guides
      </button>
      {result && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
            {result.ok !== false
              ? <span style={{ ...s.badge, ...s.badgeGreen }}><CheckCircle size={10} /> OK</span>
              : <span style={{ ...s.badge, ...s.badgeAmber }}><AlertTriangle size={10} /> Failed</span>}
            {result.used_gordon === true && (
              <span style={{ ...s.badge, ...s.badgeGreen }}>Gordon</span>
            )}
            {result.used_gordon === false && (
              <span style={{ ...s.badge, ...s.badgeAmber }}>Skinning fallback</span>
            )}
          </div>
          {result.surface && (
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>
              Degree: {result.surface.degree_u}×{result.surface.degree_v} ·
              Control net: {result.surface.num_control_points_u}×{result.surface.num_control_points_v}
            </div>
          )}
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

const TABS = ['Gordon', 'Skinning', 'Guide Rails']

export default function SurfacingPanel() {
  const [tab, setTab] = useState('Gordon')

  return (
    <div style={s.root}>
      <div style={s.header}>
        <GitBranch size={20} color="#60a5fa" />
        <div>
          <div style={s.title}>NURBS Surfacing</div>
          <div style={s.sub}>
            Gordon/Coons-Gordon · Skinning loft · Guide-rail loft
            (Piegl &amp; Tiller §10.4 / §12.4)
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

      {tab === 'Gordon' && <GordonNetworkTool />}
      {tab === 'Skinning' && <SkinningLoftTool />}
      {tab === 'Guide Rails' && <LoftWithGuidesTool />}
    </div>
  )
}
