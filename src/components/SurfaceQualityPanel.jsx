// SurfaceQualityPanel.jsx — Class-A NURBS surface-quality inspection panel.
//
// Wires the kerf-cad-core Class-A surfacing tools:
//   surface_class_a_analyze       — G0/G1/G2/G3 continuity + zebra + isophote grade
//   surface_gaussian_mean_curvature — Gaussian / mean curvature map
//   feature_zebra_analysis (ref)  — zebra-stripe overlay (viewport feature)
//
// Renders the continuity report (per-edge G0/G1/G2/G3 pass/fail with measured
// residuals), the highest achieved grade, and zebra / isophote classification.
//
// Pattern mirrors SurfacingPanel.jsx (dark mono palette, callTool helper).
// Props: none — standalone analysis panel.

import { useState, useCallback } from 'react'
import {
  Activity,
  Eye,
  Gauge,
  Play,
  Loader2,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Info,
} from 'lucide-react'

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

function fmtNum(v, digits = 6) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  if (typeof v !== 'number') return String(v)
  if (v !== 0 && (Math.abs(v) < 1e-3 || Math.abs(v) >= 1e5)) return v.toExponential(2)
  return v.toFixed(digits)
}

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
  card: {
    background: '#161b22',
    border: '1px solid #1f2937',
    borderRadius: 8,
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  cardTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: '#d1d5db',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  btn: {
    padding: '8px 16px',
    borderRadius: 6,
    border: '1px solid #2563eb',
    background: '#1d4ed8',
    color: '#fff',
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: 'inherit',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    width: 'fit-content',
  },
  gateRow: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
  },
  gate: (ok) => ({
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 12px',
    borderRadius: 6,
    border: `1px solid ${ok ? '#15803d' : '#7f1d1d'}`,
    background: ok ? '#0f2a18' : '#2a1010',
    color: ok ? '#86efac' : '#fca5a5',
    fontSize: 12,
  }),
  grade: (g) => ({
    fontSize: 22,
    fontWeight: 800,
    color:
      g === 'G3' ? '#86efac'
      : g === 'G2' ? '#a7f3d0'
      : g === 'G1' ? '#fde68a'
      : g === 'G0' ? '#fdba74'
      : '#fca5a5',
  }),
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 12 },
  th: { textAlign: 'left', padding: '6px 8px', color: '#9ca3af', borderBottom: '1px solid #1f2937' },
  td: { padding: '6px 8px', borderBottom: '1px solid #11161d' },
  err: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 12px',
    borderRadius: 6,
    border: '1px solid #7f1d1d',
    background: '#2a1010',
    color: '#fca5a5',
    fontSize: 12,
  },
  note: {
    display: 'flex',
    gap: 8,
    padding: '10px 12px',
    borderRadius: 6,
    border: '1px solid #1f2937',
    background: '#0f141b',
    color: '#9ca3af',
    fontSize: 11,
    lineHeight: 1.5,
  },
}

/**
 * Surface-quality / Class-A continuity inspection panel.
 *
 * Optionally accepts `surfA`, `surfB`, and `sharedEdge` props (NURBS surface
 * JSON + edge polyline).  When present, the "Analyze" button calls
 * `surface_class_a_analyze` and renders the G0/G1/G2/G3 gate report, the
 * highest achieved grade, and the zebra / isophote continuity classification.
 */
export default function SurfaceQualityPanel({ surfA, surfB, sharedEdge }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [report, setReport] = useState(null)

  const analyze = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await callTool('surface_class_a_analyze', {
        surf_a: surfA,
        surf_b: surfB,
        shared_edge_pts: sharedEdge,
        num_samples: 20,
        n_stripes: 8,
      })
      if (res && res.ok === false) {
        throw new Error(res.reason || 'analysis failed')
      }
      setReport(res)
    } catch (e) {
      setError(e.message || String(e))
    } finally {
      setBusy(false)
    }
  }, [surfA, surfB, sharedEdge])

  const gates = report?.gates || {}
  const cont = report?.continuity || {}

  const GATES = [
    { key: 'G0_ok', label: 'G0 position', metric: cont.G0_max, unit: 'mm' },
    { key: 'G1_ok', label: 'G1 tangent', metric: cont.G1_max_deg, unit: '°' },
    { key: 'G2_ok', label: 'G2 curvature', metric: cont.G2_max, unit: 'ΔH' },
    { key: 'G3_ok', label: 'G3 curv-rate', metric: cont.G3_max, unit: 'dκ/ds' },
  ]

  return (
    <div style={s.root}>
      <div style={s.header}>
        <Gauge size={22} color="#60a5fa" />
        <div>
          <div style={s.title}>Surface Quality — Class-A Inspection</div>
          <div style={s.sub}>
            Curvature-continuous (G0/G1/G2/G3) join analysis · zebra · isophote ·
            analytic NURBS derivatives
          </div>
        </div>
      </div>

      <div style={s.card}>
        <div style={s.cardTitle}>
          <Activity size={16} /> Continuity report
        </div>
        <button style={s.btn} onClick={analyze} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
          {busy ? 'Analyzing…' : 'Analyze join'}
        </button>

        {error && (
          <div style={s.err}>
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {report && (
          <>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
              <span style={{ color: '#9ca3af', fontSize: 12 }}>Highest grade:</span>
              <span style={s.grade(report.highest_grade)}>
                {report.highest_grade || '—'}
              </span>
            </div>

            <div style={s.gateRow}>
              {GATES.map((g) => (
                <div key={g.key} style={s.gate(gates[g.key])}>
                  {gates[g.key] ? <CheckCircle size={13} /> : <XCircle size={13} />}
                  {g.label}
                </div>
              ))}
            </div>

            <table style={s.table}>
              <thead>
                <tr>
                  <th style={s.th}>Gate</th>
                  <th style={s.th}>Max residual</th>
                  <th style={s.th}>Unit</th>
                  <th style={s.th}>Pass</th>
                </tr>
              </thead>
              <tbody>
                {GATES.map((g) => (
                  <tr key={g.key}>
                    <td style={s.td}>{g.label}</td>
                    <td style={s.td}>{fmtNum(g.metric)}</td>
                    <td style={s.td}>{g.unit}</td>
                    <td style={s.td}>{gates[g.key] ? '✓' : '✗'}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div style={s.gateRow}>
              <div style={{ ...s.gate(true), borderColor: '#374151', background: '#11161d', color: '#cbd5e1' }}>
                <Eye size={13} /> Zebra: {report.zebra_grade || '—'}
              </div>
              <div style={{ ...s.gate(true), borderColor: '#374151', background: '#11161d', color: '#cbd5e1' }}>
                <Eye size={13} /> Isophote: {report.isophote_grade || '—'}
              </div>
            </div>
          </>
        )}
      </div>

      <div style={s.note}>
        <Info size={14} style={{ flexShrink: 0, marginTop: 1 }} />
        <span>
          Continuity is measured with exact analytic surface derivatives (Piegl &
          Tiller A3.6/A4.4) — no finite differences. G2 = matching normal
          curvature across the seam; G3 = matching curvature rate (dκ/ds). The
          zebra and isophote rows are independent reflection-line classifiers used
          for automotive Class-A inspection. To construct a curvature-continuous
          join, use the <code>surface_match_g2</code> tool; to fill a curve loop,
          use <code>surface_network_fill</code>.
        </span>
      </div>
    </div>
  )
}
