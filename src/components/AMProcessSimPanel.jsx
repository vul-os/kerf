/**
 * AMProcessSimPanel.jsx — Additive Manufacturing Process Simulation result viewer.
 *
 * Renders output from BOTH AM simulation tools:
 *   1. `am_process_simulate`          — inherent-strain quasi-static ISM
 *   2. `am_thermomechanical_simulate` — coupled transient thermo-mechanical
 *
 * Auto-detects which tool produced the result from the presence of
 * `layer_peak_temp_k` (thermo-mechanical) vs its absence (ISM).
 *
 * ISM fields (am_process_simulate):
 *   { ok, n_layers, n_nodes, n_elems, max_deviation_mm, max_von_mises_mpa,
 *     layer_max_disp_mm, recoater_interference, support_elem_count,
 *     distortion_field, residual_stress_mpa, warnings, disclaimer }
 *
 * Thermo-mechanical fields (am_thermomechanical_simulate) — superset of ISM:
 *   + layer_peak_temp_k      : list[float] — peak temperature per layer [K]
 *   + melt_pool_depth_mm     : list[float] — melt-pool depth per layer [mm]
 *   + melt_pool_width_mm     : list[float] — melt-pool width per layer [mm]
 *   + melt_pool_reached      : list[bool]  — did layer reach T_melt?
 *   + energy_input_j         : float — total energy deposited [J]
 *   + energy_balance_ok      : bool
 *
 * Pure display — no live API calls.
 *
 * Exported pure helpers (no DOM) for vitest:
 *   parseAMResult(content)      → { kind, data, error? }
 *   deviationColor(frac)        → CSS colour string (0=blue, 1=red)
 *   stressLabel(mpa)            → risk label string
 *   fmtMm(mm, digits)           → formatted string
 *   tempColor(T_k, T_melt_k)    → CSS colour for temperature (blue → red)
 *   isThermoMech(data)          → true if data is from thermo-mechanical tool
 *
 * References:
 *   Goldak J. et al. (1984). A new FE model for welding heat sources.
 *     Metallurgical Transactions B 15:299–305.
 *   Mercelis P. & Kruth J.-P. (2006). Residual stresses in SLS/SLM.
 *     Rapid Prototyping Journal 12(5).
 *   Vastola G. et al. (2016). Controlling residual stress in Ti6Al4V AM.
 *     Additive Manufacturing 12.
 */

import { AlertTriangle, CheckCircle2, Layers, Activity, Zap, BarChart2, Thermometer, Droplets } from 'lucide-react'

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

/**
 * Map a temperature [K] to a heat-map CSS colour (blue=cold, red=hot).
 * T_melt_k is used to set the 1.0 anchor (above melt = full red).
 */
export function tempColor(T_k, T_melt_k = 1878) {
  const T_ref = 298.15
  const frac = Math.max(0, Math.min(1, (T_k - T_ref) / Math.max(T_melt_k - T_ref, 1)))
  return deviationColor(frac)
}

/**
 * True if the data payload includes thermal fields from am_thermomechanical_simulate.
 */
export function isThermoMech(data) {
  return data != null && Array.isArray(data.layer_peak_temp_k) && data.layer_peak_temp_k.length > 0
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
  const isTM = isThermoMech(d)

  return (
    <div style={styles.root}>
      {/* Header */}
      <div style={styles.header}>
        <Layers size={16} style={{ marginRight: 6, color: '#3b82f6' }} />
        <span style={styles.title}>AM Process Simulation</span>
        <span style={isTM ? styles.badgeTM : styles.badge}>
          {isTM ? 'Thermo-Mechanical' : 'Inherent-Strain Method'}
        </span>
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

      {/* Thermo-mechanical: thermal history + melt pool */}
      {isTM && (
        <ThermoMechSection data={d} />
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
// Thermo-mechanical section (rendered only when data is from TM tool)
// ---------------------------------------------------------------------------

function ThermoMechSection({ data: d }) {
  const peakTemps = Array.isArray(d.layer_peak_temp_k) ? d.layer_peak_temp_k : []
  const meltDepths = Array.isArray(d.melt_pool_depth_mm) ? d.melt_pool_depth_mm : []
  const meltWidths = Array.isArray(d.melt_pool_width_mm) ? d.melt_pool_width_mm : []
  const meltReached = Array.isArray(d.melt_pool_reached) ? d.melt_pool_reached : []
  const T_melt = d.T_melt_k ?? 1878
  const maxTemp = peakTemps.length > 0 ? Math.max(...peakTemps) : 0
  const minTemp = peakTemps.length > 0 ? Math.min(...peakTemps) : 0
  const meltCount = meltReached.filter(Boolean).length

  return (
    <>
      {/* Thermal summary stats */}
      <div style={styles.section}>
        <div style={styles.sectionTitle}>
          <Thermometer size={10} style={{ marginRight: 3, verticalAlign: 'middle' }} />
          Thermal History
        </div>
        <div style={styles.statsGrid}>
          <StatCard
            icon={<Thermometer size={14} />}
            label="Peak Temperature"
            value={maxTemp > 0 ? `${Math.round(maxTemp)} K` : '—'}
            sub={maxTemp >= T_melt ? 'Above Melt' : 'Below Melt'}
            color={maxTemp >= T_melt ? '#dc2626' : '#f59e0b'}
          />
          <StatCard
            icon={<Droplets size={14} />}
            label="Melt Pool Layers"
            value={`${meltCount} / ${meltReached.length}`}
            sub={meltCount === 0 ? 'No melting' : meltCount === meltReached.length ? 'All melted' : 'Partial'}
            color={meltCount > 0 ? '#dc2626' : '#6b7280'}
          />
          <StatCard
            icon={<Activity size={14} />}
            label="Avg Melt Depth"
            value={meltDepths.length > 0
              ? `${(meltDepths.reduce((a,b) => a+b, 0) / meltDepths.length).toFixed(3)} mm`
              : '—'}
            color="#7c3aed"
          />
          <StatCard
            icon={<Zap size={14} />}
            label="Energy Input"
            value={d.energy_input_j != null ? `${d.energy_input_j.toFixed(2)} J` : '—'}
            sub={d.energy_balance_ok === false ? 'Balance Warning' : 'OK'}
            color={d.energy_balance_ok === false ? '#f59e0b' : '#16a34a'}
          />
        </div>
      </div>

      {/* Peak temperature sparkline per layer */}
      {peakTemps.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Peak Temperature per Layer [K]</div>
          <TempSparkline values={peakTemps} T_melt={T_melt} />
          <div style={styles.sparklineLabels}>
            <span>Layer 1  ({Math.round(minTemp)} K)</span>
            <span>Max: {Math.round(maxTemp)} K</span>
          </div>
        </div>
      )}

      {/* Melt pool heat map (colour-coded by melt reached) */}
      {meltReached.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Melt Pool Status per Layer</div>
          <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
            {meltReached.map((reached, i) => (
              <div
                key={i}
                title={`Layer ${i + 1}: ${reached ? 'Melted' : 'Not melted'} | Peak ${peakTemps[i] != null ? Math.round(peakTemps[i]) + ' K' : '?'}`}
                style={{
                  width: 18, height: 18,
                  borderRadius: 3,
                  background: reached ? '#dc2626' : '#bfdbfe',
                  border: '1px solid #e5e7eb',
                  cursor: 'default',
                  fontSize: 9, color: '#fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                {i + 1}
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: '#9ca3af', marginTop: 4 }}>
            Red = melted (&ge;{Math.round(T_melt)} K) &nbsp;|&nbsp; Blue = not melted
          </div>
        </div>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Temperature sparkline with T_melt reference line
// ---------------------------------------------------------------------------

function TempSparkline({ values, T_melt, width = 280, height = 60 }) {
  if (!values || values.length === 0) return null
  const max = Math.max(...values, T_melt * 1.05)
  const min = 250   // K floor
  const range = max - min
  const pts = values.map((v, i) => {
    const x = (i / Math.max(values.length - 1, 1)) * width
    const y = height - ((v - min) / range) * (height - 4)
    return `${x},${y}`
  })
  const meltY = height - ((T_melt - min) / range) * (height - 4)
  return (
    <svg width={width} height={height} style={{ display: 'block', overflow: 'visible' }} aria-label="Peak temperature per layer">
      {/* Melt temperature reference line */}
      <line x1={0} y1={meltY} x2={width} y2={meltY}
        stroke="#dc2626" strokeWidth={1} strokeDasharray="4 2" opacity={0.6} />
      <text x={width - 2} y={meltY - 3} fontSize={8} fill="#dc2626" textAnchor="end">T_melt</text>
      {/* Temperature curve */}
      <polyline points={pts.join(' ')} fill="none" stroke="#f97316" strokeWidth={1.5} strokeLinejoin="round" />
      {values.map((v, i) => {
        const x = (i / Math.max(values.length - 1, 1)) * width
        const y = height - ((v - min) / range) * (height - 4)
        return <circle key={i} cx={x} cy={y} r={2} fill={v >= T_melt ? '#dc2626' : '#f97316'} />
      })}
    </svg>
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
  badgeTM: {
    background: '#fff7ed',
    color: '#c2410c',
    border: '1px solid #fed7aa',
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
