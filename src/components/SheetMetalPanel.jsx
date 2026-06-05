// SheetMetalPanel.jsx — Sheet metal tools panel.
//
// Wires three kerf-cad-core tools:
//   sheetmetal_flat_pattern         — flat pattern unfolding + DXF export
//   sheetmetal_compute_corner_relief — corner-relief geometry (GK-P17, NEW)
//   sheetmetal_multi_flange         — multi-flange sequences
//
// Corner relief types (Suchy §7 / DIN 6935 §6):
//   square  — punch w×d = (r+t/2)×(r+t/2)
//   round   — radius rr = max(t/2, r/2), circular punch
//   lance   — L-shaped slot w=t, d=r+t
//
// Pattern: dark mono palette, lucide-react icons, no external deps.

import { useState, useCallback } from 'react'
import {
  Square,
  Circle,
  Scissors,
  Grid3X3,
  Play,
  Loader2,
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Info,
  FileDown,
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

const ACCENT = '#fbbf24'

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
    background: '#2d1f00',
    color: ACCENT,
    borderColor: '#92400e',
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
    background: '#2d1f00',
    color: '#fef3c7',
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
    maxHeight: 300,
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
  badgeBlue: { background: '#1c1c40', color: '#a5b4fc' },
  infoBox: {
    padding: '8px 12px',
    borderRadius: 5,
    background: '#1a1206',
    border: '1px solid #92400e',
    fontSize: 11,
    color: '#fde68a',
    lineHeight: 1.5,
  },
  row: { display: 'flex', gap: 12 },
  reliefDiagram: {
    padding: '10px 14px',
    borderRadius: 5,
    background: '#0a0e14',
    border: '1px solid #21262d',
    fontSize: 11,
    color: '#8b949e',
    lineHeight: 1.6,
  },
}

// ---------------------------------------------------------------------------
// Reusable ToolCard
// ---------------------------------------------------------------------------

function ToolCard({ icon: Icon, title, description, children }) {
  const [open, setOpen] = useState(true)
  return (
    <div style={s.card}>
      <div style={s.cardTitle} onClick={() => setOpen(v => !v)}>
        {Icon && <Icon size={14} color={ACCENT} />}
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
// FlatPatternTool
// ---------------------------------------------------------------------------

const EXAMPLE_FLANGES = JSON.stringify([
  { length_mm: 50, bend_radius_mm: 2, angle_deg: 90, k_factor: 0.33 },
  { length_mm: 30, bend_radius_mm: 2, angle_deg: 90, k_factor: 0.33 },
], null, 2)

function FlatPatternTool() {
  const [thickness, setThickness] = useState('1.5')
  const [flanges, setFlanges] = useState(EXAMPLE_FLANGES)
  const [material, setMaterial] = useState('mild_steel')
  const [exportDxf, setExportDxf] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      let fl
      try { fl = JSON.parse(flanges) } catch { throw new Error('flanges: invalid JSON') }
      const res = await callTool('sheetmetal_flat_pattern', {
        thickness_mm: parseFloat(thickness) || 1.5,
        flanges: fl,
        material,
        export_dxf: exportDxf,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [thickness, flanges, material, exportDxf])

  return (
    <ToolCard
      icon={FileDown}
      title="Flat Pattern Unfolding"
      description={
        'Unfold a bend sequence to flat blank. Bend allowance from K-factor (DIN 6935 §3 / Suchy §3): ' +
        'BA = (π/180)·θ·(r + K·t). Returns flat_length_mm and per-bend breakdown.'
      }
    >
      <div style={s.row}>
        <div style={{ flex: 1 }}>
          <div style={s.label}>Thickness (mm)</div>
          <input style={s.input} value={thickness} onChange={e => setThickness(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={s.label}>Material</div>
          <select style={s.select} value={material} onChange={e => setMaterial(e.target.value)}>
            <option value="mild_steel">Mild steel</option>
            <option value="stainless">Stainless (304)</option>
            <option value="aluminium">Aluminium (6061)</option>
            <option value="copper">Copper</option>
          </select>
        </div>
      </div>
      <div>
        <div style={s.label}>flanges (JSON array — each has length_mm, bend_radius_mm, angle_deg, k_factor)</div>
        <textarea style={s.textarea} value={flanges} onChange={e => setFlanges(e.target.value)} />
      </div>
      <label style={{ fontSize: 12, color: '#9ca3af', display: 'flex', alignItems: 'center', gap: 5 }}>
        <input type="checkbox" checked={exportDxf} onChange={e => setExportDxf(e.target.checked)} />
        Export DXF
      </label>
      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Compute Flat Pattern
      </button>
      {result && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
            <StatusBadge ok={result.ok} />
            {result.flat_length_mm != null && (
              <span style={{ ...s.badge, ...s.badgeBlue }}>
                Flat = {result.flat_length_mm?.toFixed(3)} mm
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
// CornerReliefTool — GK-P17 (NEW)
// ---------------------------------------------------------------------------

const RELIEF_DIAGRAMS = {
  square: `Square punch (Suchy §7.4 / DIN 6935 §6.2):
  width  = r + t/2
  depth  = r + t/2
  min punch radius = t/2
  ┌──────┐
  │      │  ← square notch centred on corner
  └──────┘`,
  round: `Round punch (Suchy §7.4):
  relief_radius = max(t/2, r/2)
  width = depth = 2·rr
  ○  ← circular punch centred on corner`,
  lance: `Lance / L-slot (Suchy §7.5):
  width = t
  depth = r + t
  ┐    ← L-shaped slot cuts only one leg`,
}

function CornerReliefTool() {
  const [reliefType, setReliefType] = useState('square')
  const [bendRadius, setBendRadius] = useState('2.0')
  const [thickness, setThickness] = useState('1.5')
  const [angle, setAngle] = useState('90.0')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      const res = await callTool('sheetmetal_compute_corner_relief', {
        relief_type: reliefType,
        bend_radius_mm: parseFloat(bendRadius) || 2.0,
        thickness_mm: parseFloat(thickness) || 1.5,
        bend_angle_deg: parseFloat(angle) || 90.0,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [reliefType, bendRadius, thickness, angle])

  return (
    <ToolCard
      icon={Scissors}
      title="Corner Relief Geometry"
      description={
        'Compute corner-relief punch dimensions and outline polygon. ' +
        'Refs: Suchy "Handbook of Die Design" §7 + DIN 6935 §6. ' +
        'Three types: square, round, lance (L-slot).'
      }
    >
      <div style={s.infoBox}>
        <Info size={11} style={{ display: 'inline', marginRight: 4 }} />
        Corner relief prevents material distortion / cracking where two bend lines meet.
        Choose type per tooling availability.
      </div>

      <div style={s.row}>
        <div style={{ flex: 1 }}>
          <div style={s.label}>Relief type</div>
          <select style={s.select} value={reliefType} onChange={e => setReliefType(e.target.value)}>
            <option value="square">Square punch</option>
            <option value="round">Round punch</option>
            <option value="lance">Lance / L-slot</option>
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <div style={s.label}>Bend angle (°)</div>
          <input style={s.input} value={angle} onChange={e => setAngle(e.target.value)} />
        </div>
      </div>
      <div style={s.row}>
        <div style={{ flex: 1 }}>
          <div style={s.label}>Bend radius (mm)</div>
          <input style={s.input} value={bendRadius} onChange={e => setBendRadius(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={s.label}>Thickness (mm)</div>
          <input style={s.input} value={thickness} onChange={e => setThickness(e.target.value)} />
        </div>
      </div>

      <div style={s.reliefDiagram}>{RELIEF_DIAGRAMS[reliefType]}</div>

      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Compute Corner Relief
      </button>
      {result && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
            <StatusBadge ok={result.ok} />
            {result.width_mm != null && (
              <span style={{ ...s.badge, ...s.badgeBlue }}>
                w = {result.width_mm?.toFixed(3)} mm
              </span>
            )}
            {result.depth_mm != null && (
              <span style={{ ...s.badge, ...s.badgeBlue }}>
                d = {result.depth_mm?.toFixed(3)} mm
              </span>
            )}
            {result.relief_radius_mm != null && (
              <span style={{ ...s.badge, ...s.badgeBlue }}>
                rr = {result.relief_radius_mm?.toFixed(3)} mm
              </span>
            )}
            {result.area_mm2 != null && (
              <span style={{ ...s.badge, background: '#1f2d1f', color: '#86efac' }}>
                A = {result.area_mm2?.toFixed(4)} mm²
              </span>
            )}
          </div>
          {result.caveat && (
            <div style={{ ...s.infoBox, marginBottom: 6 }}>
              <Info size={11} style={{ display: 'inline', marginRight: 4 }} />
              {result.caveat}
            </div>
          )}
          {result.outline_mm && result.outline_mm.length > 0 && (
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>
              Outline: {result.outline_mm.length} vertices
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
// MultiFlangeCalc — informational sub-tool to chain multiple flanges
// ---------------------------------------------------------------------------

const EXAMPLE_MF = JSON.stringify([
  { flange_type: 'bend', length_mm: 40, angle_deg: 90, bend_radius_mm: 2 },
  { flange_type: 'bend', length_mm: 20, angle_deg: -45, bend_radius_mm: 2 },
], null, 2)

function MultiFlangeCalc() {
  const [thickness, setThickness] = useState('1.5')
  const [kFactor, setKFactor] = useState('0.33')
  const [flanges, setFlanges] = useState(EXAMPLE_MF)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = useCallback(async () => {
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      let fl
      try { fl = JSON.parse(flanges) } catch { throw new Error('flanges: invalid JSON') }
      const res = await callTool('sheetmetal_multi_flange', {
        thickness_mm: parseFloat(thickness) || 1.5,
        k_factor: parseFloat(kFactor) || 0.33,
        flanges: fl,
      })
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [thickness, kFactor, flanges])

  return (
    <ToolCard
      icon={Grid3X3}
      title="Multi-Flange Sequence"
      description="Compute cumulative bend allowances and flat length for a multi-flange sequence."
    >
      <div style={s.row}>
        <div style={{ flex: 1 }}>
          <div style={s.label}>Thickness (mm)</div>
          <input style={s.input} value={thickness} onChange={e => setThickness(e.target.value)} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={s.label}>K-factor</div>
          <input style={s.input} value={kFactor} onChange={e => setKFactor(e.target.value)} />
        </div>
      </div>
      <div>
        <div style={s.label}>flanges (JSON)</div>
        <textarea style={s.textarea} value={flanges} onChange={e => setFlanges(e.target.value)} />
      </div>
      <button style={s.button} onClick={run} disabled={loading}>
        {loading ? <Loader2 size={13} /> : <Play size={13} />}
        Compute
      </button>
      {result && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
            <StatusBadge ok={result.ok} />
            {result.total_flat_length_mm != null && (
              <span style={{ ...s.badge, ...s.badgeBlue }}>
                Total = {result.total_flat_length_mm?.toFixed(3)} mm
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
// Main panel
// ---------------------------------------------------------------------------

const TABS = ['Flat Pattern', 'Corner Relief', 'Multi-Flange']

export default function SheetMetalPanel({ content } = {}) {
  // content prop: JSON string optionally carrying persisted tab selection.
  const _parsed = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()
  const [tab, setTab] = useState(_parsed.tab || 'Flat Pattern')

  return (
    <div style={s.root}>
      <div style={s.header}>
        <Square size={20} color={ACCENT} />
        <div>
          <div style={s.title}>Sheet Metal</div>
          <div style={s.sub}>
            Flat pattern · corner relief (GK-P17) · multi-flange · DXF export
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

      {tab === 'Flat Pattern' && <FlatPatternTool />}
      {tab === 'Corner Relief' && <CornerReliefCalc />}
      {tab === 'Multi-Flange' && <MultiFlangeCalc />}
    </div>
  )
}

// alias so the tab label maps cleanly
const CornerReliefCalc = CornerReliefTool
