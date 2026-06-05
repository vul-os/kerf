/**
 * AMProcessSimPanel.jsx — Additive Manufacturing Process Simulation result viewer.
 *
 * Renders the output of the `am_process_simulate` LLM tool:
 *   - Distortion field visualised as a color-coded bar (gradient from 0 → max deviation)
 *   - Max deviation and residual von-Mises stress readouts
 *   - Layer-by-layer distortion growth sparkline
 *   - Recoater interference and support-region flags
 *   - Warning list
 *
 * Input (parsedContent JSON from tool output):
 *   {
 *     "ok": true,
 *     "n_layers": 4,
 *     "n_nodes": 45,
 *     "n_elems": 80,
 *     "max_deviation_mm": 0.312,
 *     "max_von_mises_mpa": 287.4,
 *     "layer_max_disp_mm": [0.0, 0.04, 0.12, 0.31],
 *     "recoater_interference": false,
 *     "support_elem_count": 10,
 *     "distortion_field": [[...], ...],      // (N, 3) in metres
 *     "residual_stress_mpa": [[...], ...],   // (M, 6) in MPa
 *     "warnings": ["..."],
 *     "disclaimer": "..."
 *   }
 *
 * Pure display — no live API calls.
 *
 * Exported pure helpers (no DOM) for vitest:
 *   parseAMResult(content)   → { kind, data, error? }
 *   deviationColor(frac)     → CSS colour string (0=blue, 1=red)
 *   stressLabel(mpa)         → risk label string
 *   fmtMm(mm, digits)        → formatted string
 *
 * References:
 *   Mercelis P. & Kruth J.-P. (2006). Residual stresses in selective laser
 *     sintering and selective laser melting. Rapid Prototyping Journal 12(5).
 *   Liang X. et al. (2019). Inherent strain homogenisation for AM.
 *     Manufacturing Letters 20.
 */

import { AlertTriangle, CheckCircle2, Layers, Activity, Zap, BarChart2 } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw AM simulation result JSON.
 * Returns { kind: 'ok'|'empty'|'invalid', data, error? }
 */
export function parseAMResult(content) {
  const raw = typeof content === 'string' ? content : ''
  if (!raw.trim()) return { kind: 'empty', data: null }
  let doc
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    return { kind: 'invalid', error: e.message }
  }
  if (!doc || typeof doc !== 'object') {
    return { kind: 'invalid', error: 'Expected JSON object' }
  }
  const data = doc.result && typeof doc.result === 'object' ? doc.result : doc
  if (data.ok === false) {
    return { kind: 'invalid', error: data.reason || data.error || 'Simulation returned ok:false' }
  }
  if (typeof data.max_deviation_mm !== 'number') {
    return { kind: 'invalid', error: 'Missing max_deviation_mm field' }
  }
  return { kind: 'ok', data }
}

/**
 * Map a distortion fraction [0..1] to a heat-map CSS colour (blue→cyan→green→yellow→red).
 */
export function deviationColor(frac) {
  const f = Math.max(0, Math.min(1, frac))
  // 5-stop gradient: 0=blue, 0.25=cyan, 0.5=green, 0.75=yellow, 1=red
  const stops = [
    [0,   [  0,  80, 255]],
    [0.25,[  0, 200, 220]],
    [0.5, [  0, 200,   0]],
    [0.75,[255, 200,   0]],
    [1.0, [255,  30,  30]],
  ]
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, c0] = stops[i]
    const [t1, c1] = stops[i + 1]
    if (f <= t1) {
      const t = (f - t0) / (t1 - t0)
      const r = Math.round(c0[0] + t * (c1[0] - c0[0]))
      const g = Math.round(c0[1] + t * (c1[1] - c0[1]))
      const b = Math.round(c0[2] + t * (c1[2] - c0[2]))
      return `rgb(${r},${g},${b})`
    }
  }
  return 'rgb(255,30,30)'
}

/**
 * Classify residual von-Mises stress magnitude.
 */
export function stressLabel(mpa) {
  if (mpa < 50)  return 'Low'
  if (mpa < 200) return 'Moderate'
  if (mpa < 500) return 'High'
  return 'Very High'
}

/**
 * Format mm values with fallback.
 */
export function fmtMm(mm, digits = 3) {
  if (mm == null || !isFinite(mm)) return '—'
  return mm.toFixed(digits)
}

// ---------------------------------------------------------------------------
// Layer sparkline (pure SVG, no d3)
// ---------------------------------------------------------------------------

function LayerSparkline({ values, width = 280, height = 50 }) {
  if (!values || values.length === 0) return null
  const max = Math.max(...values, 1e-12)
  const pts = values.map((v, i) => {
    const x = (i / Math.max(values.length - 1, 1)) * width
    const y = height - (v / max) * (height - 4)
    return `${x},${y}`
  })
  const polyline = pts.join(' ')
  return (
    <svg
      width={width}
      height={height}
      style={{ display: 'block', overflow: 'visible' }}
      aria-label="Layer distortion growth"
    >
      <polyline
        points={polyline}
        fill="none"
        stroke="#3b82f6"
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
      {values.map((v, i) => {
        const x = (i / Math.max(values.length - 1, 1)) * width
        const y = height - (v / max) * (height - 4)
        return <circle key={i} cx={x} cy={y} r={2} fill="#3b82f6" />
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Distortion color bar
// ---------------------------------------------------------------------------

function DeviationColorBar({ maxMm }) {
  const stops = [0, 0.25, 0.5, 0.75, 1.0]
  const gradient = stops.map(s => `${deviationColor(s)} ${s * 100}%`).join(', ')
  return (
    <div style={{ marginTop: 6 }}>
      <div
        style={{
          height: 14,
          borderRadius: 4,
          background: `linear-gradient(to right, ${gradient})`,
          width: '100%',
        }}
        aria-label="Distortion color scale"
      />
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#888', marginTop: 2 }}>
        <span>0 mm</span>
        <span style={{ fontWeight: 600, color: '#dc2626' }}>{fmtMm(maxMm)} mm</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel component
// ---------------------------------------------------------------------------

export default function AMProcessSimPanel({ parsedContent }) {
  const parsed = parseAMResult(parsedContent)

  if (parsed.kind === 'empty') {
    return (
      <div style={styles.empty}>
        No AM simulation result loaded. Run <code>am_process_simulate</code> to generate a result.
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div style={styles.errorBox}>
        <AlertTriangle size={14} style={{ marginRight: 6 }} />
        <strong>Parse error:</strong> {parsed.error}
      </div>
    )
  }

  const d = parsed.data
  const layerMm = Array.isArray(d.layer_max_disp_mm) ? d.layer_max_disp_mm : []
  const warnings = Array.isArray(d.warnings) ? d.warnings : []
  const stressLbl = stressLabel(d.max_von_mises_mpa ?? 0)

  return (
    <div style={styles.root}>
      {/* Header */}
      <div style={styles.header}>
        <Layers size={16} style={{ marginRight: 6, color: '#3b82f6' }} />
        <span style={styles.title}>AM Process Simulation</span>
        <span style={styles.badge}>Inherent-Strain Method</span>
      </div>

      {/* Mesh summary */}
      <div style={styles.metaRow}>
        <span style={styles.metaItem}><strong>{d.n_layers ?? '—'}</strong> layers</span>
        <span style={styles.metaDivider}>/</span>
        <span style={styles.metaItem}><strong>{d.n_nodes ?? '—'}</strong> nodes</span>
        <span style={styles.metaDivider}>/</span>
        <span style={styles.metaItem}><strong>{d.n_elems ?? '—'}</strong> elements</span>
      </div>

      {/* Key results */}
      <div style={styles.statsGrid}>
        <StatCard
          icon={<Activity size={14} />}
          label="Max Distortion"
          value={`${fmtMm(d.max_deviation_mm)} mm`}
          color={d.max_deviation_mm > 1.0 ? '#dc2626' : d.max_deviation_mm > 0.5 ? '#f59e0b' : '#16a34a'}
        />
        <StatCard
          icon={<Zap size={14} />}
          label="Residual von-Mises"
          value={`${(d.max_von_mises_mpa ?? 0).toFixed(1)} MPa`}
          sub={stressLbl}
          color={stressLbl === 'Very High' ? '#dc2626' : stressLbl === 'High' ? '#f59e0b' : '#16a34a'}
        />
        <StatCard
          icon={<BarChart2 size={14} />}
          label="Support Elements"
          value={String(d.support_elem_count ?? '—')}
          color="#6b7280"
        />
        <StatCard
          icon={d.recoater_interference
            ? <AlertTriangle size={14} />
            : <CheckCircle2 size={14} />
          }
          label="Recoater Risk"
          value={d.recoater_interference ? 'Interference Risk' : 'Clear'}
          color={d.recoater_interference ? '#dc2626' : '#16a34a'}
        />
      </div>

      {/* Distortion color bar */}
      <div style={styles.section}>
        <div style={styles.sectionTitle}>Distortion Scale</div>
        <DeviationColorBar maxMm={d.max_deviation_mm ?? 0} />
      </div>

      {/* Layer distortion sparkline */}
      {layerMm.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Distortion Growth per Layer</div>
          <LayerSparkline values={layerMm} />
          <div style={styles.sparklineLabels}>
            <span>Layer 1</span>
            <span>Layer {layerMm.length}</span>
          </div>
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Warnings</div>
          {warnings.map((w, i) => (
            <div key={i} style={styles.warning}>
              <AlertTriangle size={12} style={{ marginRight: 5, flexShrink: 0, color: '#f59e0b' }} />
              {w}
            </div>
          ))}
        </div>
      )}

      {/* Disclaimer */}
      {d.disclaimer && (
        <div style={styles.disclaimer}>{d.disclaimer}</div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({ icon, label, value, sub, color }) {
  return (
    <div style={styles.statCard}>
      <div style={{ ...styles.statIcon, color }}>{icon}</div>
      <div style={styles.statLabel}>{label}</div>
      <div style={{ ...styles.statValue, color }}>{value}</div>
      {sub && <div style={styles.statSub}>{sub}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  root: {
    fontFamily: 'system-ui, sans-serif',
    fontSize: 13,
    color: '#1f2937',
    padding: '12px 14px',
    maxWidth: 640,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    marginBottom: 10,
  },
  title: {
    fontWeight: 700,
    fontSize: 15,
    marginRight: 8,
  },
  badge: {
    background: '#eff6ff',
    color: '#1d4ed8',
    border: '1px solid #bfdbfe',
    borderRadius: 4,
    fontSize: 10,
    padding: '1px 6px',
    fontWeight: 600,
    letterSpacing: 0.3,
  },
  metaRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    color: '#6b7280',
    marginBottom: 10,
    fontSize: 12,
  },
  metaItem: {},
  metaDivider: { color: '#d1d5db' },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: 8,
    marginBottom: 12,
  },
  statCard: {
    background: '#f9fafb',
    border: '1px solid #e5e7eb',
    borderRadius: 6,
    padding: '8px 10px',
  },
  statIcon: {
    marginBottom: 2,
  },
  statLabel: {
    fontSize: 10,
    color: '#9ca3af',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 2,
  },
  statValue: {
    fontWeight: 700,
    fontSize: 14,
  },
  statSub: {
    fontSize: 10,
    color: '#6b7280',
    marginTop: 1,
  },
  section: {
    marginBottom: 12,
  },
  sectionTitle: {
    fontWeight: 600,
    fontSize: 11,
    color: '#6b7280',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 5,
  },
  sparklineLabels: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 10,
    color: '#9ca3af',
    marginTop: 2,
  },
  warning: {
    display: 'flex',
    alignItems: 'flex-start',
    background: '#fffbeb',
    border: '1px solid #fde68a',
    borderRadius: 4,
    padding: '5px 8px',
    marginBottom: 4,
    fontSize: 12,
    color: '#92400e',
  },
  disclaimer: {
    fontSize: 10,
    color: '#9ca3af',
    borderTop: '1px solid #f3f4f6',
    paddingTop: 6,
    marginTop: 4,
    lineHeight: 1.4,
    fontStyle: 'italic',
  },
  empty: {
    color: '#9ca3af',
    padding: '20px 12px',
    textAlign: 'center',
    fontSize: 13,
  },
  errorBox: {
    display: 'flex',
    alignItems: 'center',
    background: '#fef2f2',
    border: '1px solid #fca5a5',
    borderRadius: 5,
    padding: '8px 10px',
    color: '#dc2626',
    fontSize: 12,
  },
}
