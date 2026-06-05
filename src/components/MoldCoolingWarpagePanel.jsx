/**
 * MoldCoolingWarpagePanel.jsx — Cooling analysis, runner balance, and warpage result viewer.
 *
 * Renders the output of three mold LLM tools:
 *   mold_cooling_analysis     — Dittus-Boelter HTC, cooling time, coolant temp rise
 *   mold_check_runner_balance — Hagen-Poiseuille path resistance, imbalance %
 *   mold_compute_warpage_index — Heuristic 0–100 warpage risk index
 *
 * References:
 *   Beaumont J.P. (2007). Runner and Gating Design Handbook, 2nd ed., Hanser.
 *     §6.6 (runner balance), §10 (warpage), §11 (cooling channel analysis).
 *   Menges G., Michaeli W., Mohren P. (2001). How to Make Injection Molds, 3rd ed.
 *     §6.6.4, §7.3.3, §7.5, §8.
 *   Incropera & DeWitt (2007). Fundamentals of Heat & Mass Transfer, eq. 8.60
 *     (Dittus-Boelter Nu correlation).
 *
 * Exported pure helpers for vitest:
 *   parseMoldResult(content)  → { kind, tool, data, error? }
 *   detectTool(data)          → 'cooling'|'runner_balance'|'warpage'|'unknown'
 *   warpageColor(index)       → CSS colour string
 *   balanceColor(pct)         → CSS colour string
 *   fmtVal(n, digits, unit)   → formatted string
 */

import { AlertTriangle, CheckCircle2, Thermometer, Activity, Zap } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw mold tool result JSON content.
 * Returns { kind: 'ok'|'empty'|'invalid', tool, data, error? }
 */
export function parseMoldResult(content) {
  const raw = typeof content === 'string' ? content : ''
  if (!raw.trim()) return { kind: 'empty', tool: null, data: null }
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
    return { kind: 'invalid', error: data.reason || data.error || 'Tool returned ok:false' }
  }
  const tool = detectTool(data)
  if (tool === 'unknown') {
    return { kind: 'invalid', error: 'Unrecognised mold tool output format' }
  }
  return { kind: 'ok', tool, data }
}

/**
 * Detect which mold tool produced this result.
 */
export function detectTool(data) {
  if (!data || typeof data !== 'object') return 'unknown'
  // Cooling analysis: has htc_w_m2_k or cooling_time_s and reynolds
  if ('htc_w_m2_k' in data || ('cooling_time_s' in data && 'reynolds' in data)) return 'cooling'
  // Runner balance: has balanced + cavity_paths
  if ('balanced' in data && 'cavity_paths' in data) return 'runner_balance'
  // Warpage: has warpage_index + risk_level
  if ('warpage_index' in data && 'risk_level' in data) return 'warpage'
  return 'unknown'
}

/**
 * Return CSS colour for a warpage index (0–100).
 * 0–25: green (low); 25–50: amber (moderate); 50–75: orange (high); >75: red (severe)
 */
export function warpageColor(index) {
  if (index == null || !Number.isFinite(index)) return '#9ca3af'
  if (index <= 25) return '#34d399'
  if (index <= 50) return '#fbbf24'
  if (index <= 75) return '#f97316'
  return '#f87171'
}

/**
 * Return CSS colour for a runner imbalance percentage.
 * <5 %: green; 5–15 %: amber; >15 %: red
 */
export function balanceColor(pct) {
  if (pct == null || !Number.isFinite(pct)) return '#9ca3af'
  if (pct < 5)  return '#34d399'
  if (pct < 15) return '#fbbf24'
  return '#f87171'
}

/**
 * Format a numeric value, optionally appending a unit.
 * Returns "—" for null/non-finite.
 */
export function fmtVal(n, digits = 2, unit = '') {
  if (n == null || !Number.isFinite(n)) return '—'
  const s = n.toFixed(digits)
  return unit ? `${s} ${unit}` : s
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const S = {
  container: {
    fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
    fontSize: 12,
    color: '#e2e8f0',
    background: '#0f172a',
    padding: 16,
    borderRadius: 8,
    border: '1px solid #1e293b',
    overflowY: 'auto',
    maxHeight: 560,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 14,
    paddingBottom: 8,
    borderBottom: '1px solid #1e293b',
  },
  title: {
    fontFamily: 'system-ui, sans-serif',
    fontWeight: 700,
    fontSize: 13,
    color: '#f1f5f9',
    letterSpacing: '0.02em',
  },
  metricsGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 8,
    marginBottom: 12,
  },
  metricCard: {
    background: '#1e293b',
    borderRadius: 6,
    padding: '8px 10px',
    border: '1px solid #2d3748',
  },
  metricLabel: {
    color: '#94a3b8',
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    marginBottom: 3,
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  metricValue: {
    color: '#f1f5f9',
    fontSize: 18,
    fontWeight: 700,
    fontVariantNumeric: 'tabular-nums',
  },
  metricUnit: {
    color: '#64748b',
    fontSize: 11,
    marginLeft: 3,
  },
  sectionTitle: {
    color: '#7dd3fc',
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    marginBottom: 6,
    marginTop: 12,
  },
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '2px 7px',
    borderRadius: 9999,
    fontSize: 10,
    fontWeight: 600,
    border: '1px solid',
  },
  row: {
    background: '#1e293b',
    borderRadius: 4,
    padding: '4px 8px',
    marginBottom: 3,
    color: '#cbd5e1',
    fontSize: 11,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  barOuter: {
    height: 6,
    borderRadius: 3,
    background: '#1e293b',
    overflow: 'hidden',
    marginTop: 5,
  },
  mitigation: {
    color: '#94a3b8',
    fontSize: 11,
    padding: '2px 0',
    lineHeight: 1.6,
  },
  caveat: {
    marginTop: 12,
    padding: '8px 10px',
    background: '#1e1208',
    border: '1px solid #78350f44',
    borderRadius: 6,
    color: '#fbbf24',
    fontSize: 10,
    lineHeight: 1.5,
  },
  empty: {
    color: '#475569',
    padding: 20,
    textAlign: 'center',
  },
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricCard({ label, value, unit, accent, icon: Icon }) {
  return (
    <div style={S.metricCard}>
      <div style={S.metricLabel}>
        {Icon && <Icon size={10} />}
        {label}
      </div>
      <div>
        <span style={{ ...S.metricValue, color: accent || S.metricValue.color }}>
          {value ?? '—'}
        </span>
        {unit && <span style={S.metricUnit}>{unit}</span>}
      </div>
    </div>
  )
}

function IndexGauge({ value, color, label }) {
  const clampedPct = Math.min(100, Math.max(0, value ?? 0))
  return (
    <div style={S.metricCard}>
      <div style={S.metricLabel}>{label}</div>
      <span style={{ ...S.metricValue, color }}>{fmtVal(value, 1)}</span>
      <div style={S.barOuter}>
        <div style={{ height: '100%', width: `${clampedPct}%`, background: color, borderRadius: 3 }} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool-specific renderers
// ---------------------------------------------------------------------------

function CoolingView({ data: d }) {
  return (
    <>
      <div style={S.metricsGrid}>
        <MetricCard icon={Thermometer} label="HTC" value={fmtVal(d.htc_w_m2_k, 0)} unit="W/m²K" accent="#7dd3fc" />
        <MetricCard icon={Activity} label="Reynolds" value={fmtVal(d.reynolds, 0)} accent={d.reynolds >= 10000 ? '#34d399' : '#f87171'} />
        <MetricCard label="Cooling time" value={fmtVal(d.cooling_time_s, 3)} unit="s" accent="#a78bfa" />
        <MetricCard label="ΔT coolant" value={fmtVal(d.coolant_temp_rise_c, 2)} unit="°C" accent="#fbbf24" />
      </div>
      {d.flow_regime && (
        <div style={{ marginBottom: 10 }}>
          <span style={{
            ...S.badge,
            background: d.flow_regime === 'turbulent' ? '#14532d44' : '#7f1d1d44',
            color: d.flow_regime === 'turbulent' ? '#34d399' : '#f87171',
            borderColor: d.flow_regime === 'turbulent' ? '#15803d66' : '#b91c1c66',
          }}>
            {d.flow_regime === 'turbulent'
              ? <><CheckCircle2 size={10} style={{ display: 'inline', marginRight: 3 }} />Turbulent (Dittus-Boelter valid)</>
              : <><AlertTriangle size={10} style={{ display: 'inline', marginRight: 3 }} />{d.flow_regime} — HTC correlation unreliable</>
            }
          </span>
        </div>
      )}
    </>
  )
}

function RunnerBalanceView({ data: d }) {
  const paths     = Array.isArray(d.cavity_paths) ? d.cavity_paths : []
  const imbalPct  = d.max_imbalance_pct ?? 0
  const color     = balanceColor(imbalPct)
  const SHOW_MAX  = 10

  return (
    <>
      <div style={S.metricsGrid}>
        <IndexGauge value={imbalPct} color={color} label="Max imbalance %" />
        <MetricCard label="Balanced" value={d.balanced ? 'Yes' : 'No'} accent={d.balanced ? '#34d399' : '#f87171'} />
        <MetricCard label="Cavities" value={paths.length} accent="#a78bfa" />
      </div>

      {paths.length > 0 && (
        <>
          <div style={S.sectionTitle}>Cavity Paths</div>
          {paths.slice(0, SHOW_MAX).map((cp, i) => (
            <div key={i} style={S.row}>
              <span style={{ color: '#94a3b8', minWidth: 70 }}>{cp.cavity_id || `C${i}`}</span>
              <span>fill ratio: </span>
              <span style={{ color: Math.abs((cp.fill_ratio ?? 1) - 1) < 0.05 ? '#34d399' : '#f87171', fontWeight: 600 }}>
                {fmtVal(cp.fill_ratio, 3)}
              </span>
              {cp.total_resistance != null && (
                <span style={{ color: '#64748b', marginLeft: 'auto' }}>
                  R={fmtVal(cp.total_resistance, 2)}
                </span>
              )}
            </div>
          ))}
          {paths.length > SHOW_MAX && (
            <div style={{ color: '#64748b', fontSize: 10 }}>+ {paths.length - SHOW_MAX} more</div>
          )}
        </>
      )}
    </>
  )
}

function WarpageView({ data: d }) {
  const color       = warpageColor(d.warpage_index)
  const mitigations = Array.isArray(d.mitigation_suggestions) ? d.mitigation_suggestions : []
  const subScores   = d.sub_scores && typeof d.sub_scores === 'object' ? d.sub_scores : {}

  return (
    <>
      <div style={S.metricsGrid}>
        <IndexGauge value={d.warpage_index} color={color} label="Warpage index (0–100)" />
        <MetricCard label="Risk level" value={d.risk_level} accent={color} />
        <MetricCard label="Primary driver" value={d.primary_warp_driver} accent="#7dd3fc" />
      </div>

      {Object.keys(subScores).length > 0 && (
        <>
          <div style={S.sectionTitle}>Sub-Scores</div>
          {Object.entries(subScores).map(([k, v]) => (
            <div key={k} style={S.row}>
              <span style={{ color: '#94a3b8', minWidth: 130 }}>{k.replace(/_/g, ' ')}</span>
              <span style={{ fontWeight: 600 }}>{fmtVal(v, 1)}</span>
            </div>
          ))}
        </>
      )}

      {mitigations.length > 0 && (
        <>
          <div style={S.sectionTitle}>Mitigation suggestions</div>
          {mitigations.map((m, i) => (
            <div key={i} style={S.mitigation}>• {m}</div>
          ))}
        </>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * MoldCoolingWarpagePanel renders the output of mold_cooling_analysis,
 * mold_check_runner_balance, or mold_compute_warpage_index.
 *
 * Props:
 *   parsedContent — string | object  (raw tool JSON output)
 */
export default function MoldCoolingWarpagePanel({ parsedContent }) {
  const raw = typeof parsedContent === 'object' && parsedContent !== null
    ? JSON.stringify(parsedContent)
    : (parsedContent ?? '')

  const { kind, tool, data, error } = parseMoldResult(raw)

  if (kind === 'empty') {
    return (
      <div style={S.container}>
        <div style={S.empty}>No mold analysis result loaded.</div>
      </div>
    )
  }

  if (kind === 'invalid') {
    return (
      <div style={S.container}>
        <div style={S.caveat}>
          <AlertTriangle size={12} style={{ display: 'inline', marginRight: 4 }} />
          Could not parse result: {error}
        </div>
      </div>
    )
  }

  const icons = { cooling: Thermometer, runner_balance: Activity, warpage: Zap }
  const titles = {
    cooling: 'Cooling Channel Analysis',
    runner_balance: 'Runner Balance',
    warpage: 'Warpage Index',
  }
  const Icon  = icons[tool] || Activity
  const title = titles[tool] || 'Mold Analysis'

  return (
    <div style={S.container}>
      <div style={S.header}>
        <Icon size={14} color="#7dd3fc" />
        <span style={S.title}>{title}</span>
      </div>

      {tool === 'cooling'         && <CoolingView data={data} />}
      {tool === 'runner_balance'  && <RunnerBalanceView data={data} />}
      {tool === 'warpage'         && <WarpageView data={data} />}

      {data.honest_caveat && (
        <div style={S.caveat}>
          <AlertTriangle size={11} style={{ display: 'inline', marginRight: 4 }} />
          {data.honest_caveat}
        </div>
      )}
    </div>
  )
}
