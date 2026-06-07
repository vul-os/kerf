/**
 * DentalAutoDesignPanel — Algorithmic automated crown/restoration design.
 *
 * ALGORITHMIC/heuristic automated design (anatomical-template fitting +
 * margin/contact/clearance rules), NOT a trained ML/AI model.
 *
 * Backend tools:
 *   dental_auto_design_crown  — full automated crown from prep context
 *   dental_detect_margin      — curvature-based margin line detection
 *   dental_insertion_axis     — insertion axis + undercut detection
 *
 * References:
 *   Taubin 1995 (curvature estimation); Rusinkiewicz 2004 (mesh curvature);
 *   Gilboe 1983 (insertion axis / undercut); Neff 1949 (proximal contacts);
 *   ISO 6872:2015 (ceramic min thickness); Guess 2010 (zirconia clinical guide).
 */

import { useState } from 'react'
import { useAuth } from '../../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// Tooth presets (universal → FDI label, anatomy dimensions in mm)
const TOOTH_PRESETS = [
  { label: 'UR1 (11) — Central incisor', universal: 8,  md: 8.5, bl: 7.0,  h: 10.5, type: 'incisor' },
  { label: 'UR3 (13) — Canine',          universal: 6,  md: 7.5, bl: 8.0,  h: 10.0, type: 'canine'  },
  { label: 'UR4 (14) — 1st premolar',    universal: 5,  md: 7.0, bl: 9.0,  h: 8.5,  type: 'premolar'},
  { label: 'UR6 (16) — 1st molar',       universal: 3,  md: 10,  bl: 11.5, h: 7.5,  type: 'molar'   },
  { label: 'LL6 (36) — 1st molar',       universal: 19, md: 11,  bl: 10.5, h: 7.5,  type: 'molar'   },
  { label: 'LR4 (44) — 1st premolar',    universal: 28, md: 7.0, bl: 8.0,  h: 8.5,  type: 'premolar'},
]

const MATERIALS = [
  { key: 'zirconia',           label: 'Zirconia (≥0.5 mm wall, ≥0.5 mm clearance)' },
  { key: 'lithium_disilicate', label: 'Lithium disilicate e.max (≥0.8 mm)' },
  { key: 'metal_ceramic',      label: 'Metal-ceramic (≥0.3 mm metal)' },
  { key: 'pmma',               label: 'PMMA interim (≥1.5 mm)' },
]

const STATUS_COLOR = {
  ok: '#22c55e',
  fail: '#ef4444',
  warn: '#f59e0b',
  neutral: '#6b7280',
}

function CheckBadge({ ok, label, value }) {
  const color = ok ? STATUS_COLOR.ok : STATUS_COLOR.fail
  const icon = ok ? '✓' : '✗'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0' }}>
      <span style={{ color, fontWeight: 700, fontSize: 14, minWidth: 16 }}>{icon}</span>
      <span style={{ fontSize: 13, color: '#d1d5db' }}>{label}</span>
      {value !== undefined && (
        <span style={{ fontSize: 12, color: color, marginLeft: 'auto', fontFamily: 'monospace' }}>
          {value}
        </span>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase',
                    letterSpacing: '0.05em', marginBottom: 8 }}>
        {title}
      </div>
      {children}
    </div>
  )
}

/** Build a synthetic crown-prep mesh (tapered cylinder) for a given tooth geometry. */
function buildPrepMesh(mdMm, blMm, heightMm, nRing = 16) {
  const verts = []
  const tris = []
  const N = nRing

  for (let i = 0; i < N; i++) {
    const a = (2 * Math.PI * i) / N
    verts.push([Math.cos(a) * mdMm / 2, Math.sin(a) * blMm / 2, 0])
  }
  const scale = 0.7
  for (let i = 0; i < N; i++) {
    const a = (2 * Math.PI * i) / N
    verts.push([Math.cos(a) * mdMm / 2 * scale, Math.sin(a) * blMm / 2 * scale, heightMm * 0.8])
  }
  verts.push([0, 0, heightMm])     // apex
  verts.push([0, 0, 0])            // base

  for (let i = 0; i < N; i++) {
    const mi = i, mi1 = (i + 1) % N
    const ui = N + i, ui1 = N + (i + 1) % N
    tris.push([mi, mi1, ui1], [mi, ui1, ui])
  }
  for (let i = 0; i < N; i++) {
    tris.push([2 * N, N + (i + 1) % N, N + i])
  }
  for (let i = 0; i < N; i++) {
    tris.push([2 * N + 1, i, (i + 1) % N])
  }
  return { vertices: verts, triangles: tris }
}

/** Build a simple elliptical neighbour mesh at a given x-offset. */
function buildNeighbourMesh(xOffset, n = 10) {
  const verts = []
  for (let i = 0; i < n; i++) {
    const a = (2 * Math.PI * i) / n
    verts.push([xOffset + 5 * Math.cos(a), 5 * Math.sin(a), 4])
  }
  return verts
}

/** Build antagonist mesh (flat ring above the crown). */
function buildAntagonistMesh(zOffset, n = 10) {
  const verts = []
  for (let i = 0; i < n; i++) {
    const a = (2 * Math.PI * i) / n
    verts.push([5 * Math.cos(a), 5 * Math.sin(a), zOffset])
  }
  return verts
}

export default function DentalAutoDesignPanel({ projectId, content }) {
  const { accessToken } = useAuth()

  const [toothPreset, setToothPreset] = useState(TOOTH_PRESETS[4])   // LL6 default
  const [material, setMaterial]       = useState('zirconia')
  const [withNeighbours, setWithNeighbours] = useState(true)
  const [withAntagonist, setWithAntagonist] = useState(true)
  const [prepHeight, setPrepHeight]   = useState(8.0)

  const [running, setRunning]         = useState(false)
  const [result, setResult]           = useState(null)
  const [marginResult, setMarginResult] = useState(null)
  const [axisResult, setAxisResult]   = useState(null)
  const [error, setError]             = useState(null)

  async function callTool(tool, args) {
    const resp = await fetch(`${API_URL}/api/tool`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify({ tool, args }),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const payload = await resp.json()
    if (payload.error) throw new Error(payload.error)
    return payload
  }

  async function handleAutoDesign() {
    setRunning(true)
    setResult(null)
    setMarginResult(null)
    setAxisResult(null)
    setError(null)

    try {
      const { vertices: prepV, triangles: prepT } = buildPrepMesh(
        toothPreset.md, toothPreset.bl, prepHeight
      )

      // 1. Detect margin
      const mResult = await callTool('dental_detect_margin', {
        prep_vertices: prepV,
        prep_triangles: prepT,
        n_margin_pts: 16,
        margin_type: 'chamfer',
        margin_width_mm: 0.8,
      })
      setMarginResult(mResult)

      // 2. Insertion axis
      const aResult = await callTool('dental_insertion_axis', {
        prep_vertices: prepV,
        prep_triangles: prepT,
        n_candidates: 25,
      })
      setAxisResult(aResult)

      // 3. Full auto crown design
      const crownArgs = {
        prep_vertices: prepV,
        prep_triangles: prepT,
        universal_tooth_number: toothPreset.universal,
        material,
      }
      if (withNeighbours) {
        const halfMd = toothPreset.md / 2
        crownArgs.mesial_vertices = buildNeighbourMesh(-(halfMd + 0.05 + 4.5))
        crownArgs.distal_vertices = buildNeighbourMesh(halfMd + 0.05 + 4.5)
      }
      if (withAntagonist) {
        crownArgs.antagonist_vertices = buildAntagonistMesh(prepHeight + 2.0)
      }

      const dResult = await callTool('dental_auto_design_crown', crownArgs)
      setResult(dResult)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div style={{ fontFamily: 'sans-serif', padding: 20, maxWidth: 520,
                  background: '#111827', color: '#f9fafb', minHeight: '100vh' }}>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: '0 0 4px', fontSize: 18, fontWeight: 700 }}>
          Algorithmic Auto Crown Design
        </h2>
        <div style={{ fontSize: 11, color: '#9ca3af', lineHeight: 1.5 }}>
          ALGORITHMIC/heuristic automated design — anatomical-template fitting +
          margin/contact/clearance rules. NOT a trained ML/AI model.
          NOT FDA-cleared. Requires clinical review.
        </div>
      </div>

      {/* Inputs */}
      <Section title="Tooth & Material">
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, color: '#9ca3af', display: 'block', marginBottom: 4 }}>
            Tooth (FDI position)
          </label>
          <select
            value={toothPreset.universal}
            onChange={e => setToothPreset(TOOTH_PRESETS.find(p => p.universal === +e.target.value))}
            style={{ width: '100%', background: '#1f2937', color: '#f9fafb', border: '1px solid #374151',
                     borderRadius: 6, padding: '6px 8px', fontSize: 13 }}
          >
            {TOOTH_PRESETS.map(p => (
              <option key={p.universal} value={p.universal}>{p.label}</option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, color: '#9ca3af', display: 'block', marginBottom: 4 }}>
            Material
          </label>
          <select
            value={material}
            onChange={e => setMaterial(e.target.value)}
            style={{ width: '100%', background: '#1f2937', color: '#f9fafb', border: '1px solid #374151',
                     borderRadius: 6, padding: '6px 8px', fontSize: 13 }}
          >
            {MATERIALS.map(m => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: 12, color: '#9ca3af', display: 'block', marginBottom: 4 }}>
            Prep height (mm): <strong style={{ color: '#f9fafb' }}>{prepHeight.toFixed(1)}</strong>
          </label>
          <input type="range" min={4} max={14} step={0.5} value={prepHeight}
            onChange={e => setPrepHeight(+e.target.value)}
            style={{ width: '100%' }} />
        </div>

        <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
          <label style={{ fontSize: 12, color: '#9ca3af', display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={withNeighbours}
              onChange={e => setWithNeighbours(e.target.checked)} />
            Include neighbours
          </label>
          <label style={{ fontSize: 12, color: '#9ca3af', display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={withAntagonist}
              onChange={e => setWithAntagonist(e.target.checked)} />
            Include antagonist
          </label>
        </div>
      </Section>

      {/* Run button */}
      <button
        onClick={handleAutoDesign}
        disabled={running}
        style={{
          width: '100%', padding: '10px 0', borderRadius: 8, border: 'none',
          background: running ? '#374151' : '#2563eb', color: '#fff',
          fontSize: 14, fontWeight: 600, cursor: running ? 'not-allowed' : 'pointer',
          marginBottom: 20,
        }}
      >
        {running ? 'Running pipeline…' : '⚙ Auto-Design Crown'}
      </button>

      {error && (
        <div style={{ background: '#450a0a', border: '1px solid #b91c1c', borderRadius: 8,
                      padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#fca5a5' }}>
          {error}
        </div>
      )}

      {/* Margin detection result */}
      {marginResult && (
        <Section title="Step 1 — Margin Detection (curvature-based)">
          <div style={{ background: '#1f2937', borderRadius: 8, padding: '10px 14px', fontSize: 12 }}>
            <div style={{ color: '#9ca3af', marginBottom: 4 }}>
              Method: principal-curvature PCA (Taubin 1995)
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
              <span style={{ color: '#d1d5db' }}>Margin points:</span>
              <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>
                {marginResult.margin_points?.length ?? '—'}
              </span>
              <span style={{ color: '#d1d5db' }}>Perimeter:</span>
              <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>
                {marginResult.margin_perimeter_mm?.toFixed(2) ?? '—'} mm
              </span>
              <span style={{ color: '#d1d5db' }}>Mean curvature:</span>
              <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>
                {marginResult.mean_curvature_at_margin?.toFixed(4) ?? '—'}
              </span>
              <span style={{ color: '#d1d5db' }}>Margin type:</span>
              <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>
                {marginResult.margin_type ?? '—'}
              </span>
            </div>
          </div>
        </Section>
      )}

      {/* Insertion axis result */}
      {axisResult && (
        <Section title="Step 2 — Insertion Axis + Undercut (Gilboe 1983)">
          <div style={{ background: '#1f2937', borderRadius: 8, padding: '10px 14px', fontSize: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
              <span style={{ color: '#d1d5db' }}>Axis:</span>
              <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>
                [{axisResult.insertion_axis?.map(v => v.toFixed(3)).join(', ') ?? '—'}]
              </span>
              <span style={{ color: '#d1d5db' }}>Undercut fraction:</span>
              <span style={{
                color: axisResult.undercut_fraction < 0.1 ? STATUS_COLOR.ok : STATUS_COLOR.warn,
                fontFamily: 'monospace',
              }}>
                {((axisResult.undercut_fraction ?? 0) * 100).toFixed(1)}%
              </span>
              <span style={{ color: '#d1d5db' }}>Max undercut:</span>
              <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>
                {axisResult.max_undercut_depth_mm?.toFixed(2) ?? '—'} mm
              </span>
              <span style={{ color: '#d1d5db' }}>Candidates tested:</span>
              <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>
                {axisResult.candidate_axes_tested ?? '—'}
              </span>
            </div>
          </div>
        </Section>
      )}

      {/* Crown quality checks */}
      {result && (
        <>
          <Section title="Step 3 — Crown Quality Checks">
            <div style={{ background: '#1f2937', borderRadius: 8, padding: '10px 14px' }}>
              <div style={{ fontSize: 12, color: '#9ca3af', marginBottom: 8 }}>
                FDI {result.tooth_fdi} — {result.tooth_type} —
                template: <em style={{ color: '#d1d5db' }}>{result.fdi_template_used}</em>
              </div>

              <CheckBadge
                ok={result.wall_thickness_ok}
                label="Min wall thickness"
                value={`${result.wall_thickness_min_mm?.toFixed(2)} mm`}
              />
              <CheckBadge
                ok={result.proximal_contacts_ok}
                label="Proximal contacts"
                value={
                  result.proximal_contact_mesial_mm !== null
                    ? `M:${result.proximal_contact_mesial_mm?.toFixed(2)} D:${result.proximal_contact_distal_mm?.toFixed(2)} mm`
                    : 'no neighbours'
                }
              />
              <CheckBadge
                ok={result.occlusal_clearance_ok}
                label="Occlusal clearance"
                value={`${result.occlusal_clearance_mm?.toFixed(2)} mm`}
              />
              <CheckBadge
                ok={result.margin_fit_um <= 100}
                label="Margin fit"
                value={`${result.margin_fit_um?.toFixed(0)} µm`}
              />

              <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid #374151',
                            display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  color: result.passes_all_checks ? STATUS_COLOR.ok : STATUS_COLOR.fail,
                  fontWeight: 700, fontSize: 14,
                }}>
                  {result.passes_all_checks ? '✓ PASSES ALL CHECKS' : '✗ CHECKS FAILED'}
                </span>
              </div>

              <div style={{ marginTop: 8, fontSize: 11, color: '#6b7280', lineHeight: 1.5 }}>
                Vertices: {result.crown_outer_vertices} / Triangles: {result.crown_outer_triangles}
              </div>
            </div>
          </Section>

          <Section title="Honest Disclosure">
            <div style={{ background: '#1c1917', border: '1px solid #44403c',
                          borderRadius: 8, padding: '8px 12px', fontSize: 11,
                          color: '#a8a29e', lineHeight: 1.6 }}>
              {result.honest_caveat}
            </div>
          </Section>
        </>
      )}
    </div>
  )
}
