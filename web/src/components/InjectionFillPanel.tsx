/**
 * InjectionFillPanel.jsx — Injection fill simulation result viewer.
 *
 * Renders the output of the mold_injection_fill_simulate LLM tool.
 * Displays fill time, pressure drop, weld-line count, air-trap locations,
 * and short-shot risk from a 1.5D Hele-Shaw fill simulation
 * (Hieber-Shen 1980; Cross-WLF viscosity model).
 *
 * Input format (parsedContent JSON from tool output):
 *   {
 *     "fill_time_s": 1.5,
 *     "max_pressure_drop_mpa": 42.3,
 *     "weld_line_count": 2,
 *     "weld_lines": [[{"x":50,"y":30},...], ...],
 *     "air_trap_count": 1,
 *     "air_traps": [{"x":70,"y":80}],
 *     "last_to_fill_count": 5,
 *     "last_to_fill_locations": [{"x":95,"y":90},...],
 *     "short_shot_risk_pct": 0.0,
 *     "polymer": "ABS_Cycolac_T",
 *     "honest_caveat": "SIMPLIFIED 1.5D model..."
 *   }
 *
 * Pure display — no live API calls.
 *
 * Exported pure helpers (no DOM) for vitest:
 *   parseFillResult(content)   → { kind, data, error? }
 *   riskColor(pct)             → CSS colour string
 *   fmtNum(n, digits)          → formatted string or "—"
 *   shortShotLabel(pct)        → "Low"|"Moderate"|"High"|"Critical"
 *
 * References:
 *   Hieber, C.A., Shen, S.F. (1980). J. Non-Newtonian Fluid Mech. 7, 1–32.
 *   Cross, M.M. (1965). J. Colloid Sci. 20, 417–437.
 *   Autodesk Moldflow Insight User Guide (public documentation).
 */

import type { CSSProperties, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { AlertTriangle, CheckCircle2, Droplets, Wind, Clock, Gauge } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
//
// Domain shape of the mold_injection_fill_simulate tool output. No shared
// type exists for this analysis payload — declared locally.

// A weld-line / air-trap / last-to-fill point — either {x,y} or an [x,y] tuple
// at runtime. The numeric index signature lets `.x`/`.y` and `[0]`/`[1]`
// access both typecheck without adding a runtime discriminator (no
// behaviour change).
interface FillPoint {
  x?: number
  y?: number
  [index: number]: number | undefined
}

interface FillResultData {
  ok?: boolean
  reason?: string
  error?: string
  fill_time_s?: number
  max_pressure_drop_mpa?: number
  weld_line_count?: number
  weld_lines?: FillPoint[][]
  air_trap_count?: number
  air_traps?: FillPoint[]
  last_to_fill_count?: number
  last_to_fill_locations?: FillPoint[]
  short_shot_risk_pct?: number
  polymer?: string
  honest_caveat?: string
  [key: string]: unknown
}

interface FillParseResult {
  kind: 'empty' | 'invalid' | 'ok'
  data?: FillResultData | null
  error?: string
}

export interface InjectionFillPanelProps {
  /** raw tool JSON output — string or already-parsed object */
  parsedContent?: string | FillResultData | null
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw fill-result JSON content.
 * Returns { kind: 'ok'|'empty'|'invalid', data, error? }
 *
 * Exported alongside the component (not moved to a separate module) since
 * this file's tests import them directly; splitting into a separate module
 * is a refactor out of scope for a rename-only migration (T-515).
 */
// eslint-disable-next-line react-refresh/only-export-components -- see comment above.
export function parseFillResult(content: string): FillParseResult {
  const raw = typeof content === 'string' ? content : ''
  if (!raw.trim()) return { kind: 'empty', data: null }
  let doc
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    return { kind: 'invalid', error: (e as Error).message }
  }
  if (!doc || typeof doc !== 'object') {
    return { kind: 'invalid', error: 'Expected JSON object' }
  }
  // Unwrap { result: {...} } wrapper if present
  const data: FillResultData = doc.result && typeof doc.result === 'object' ? doc.result : doc
  if (data.ok === false) {
    return { kind: 'invalid', error: data.reason || data.error || 'Tool returned ok:false' }
  }
  if (!('fill_time_s' in data) && !('max_pressure_drop_mpa' in data)) {
    return { kind: 'invalid', error: 'Missing fill_time_s field' }
  }
  return { kind: 'ok', data }
}

/**
 * Return a CSS colour string for a short-shot risk percentage.
 * 0–5 %: green; 5–20 %: amber; 20–50 %: orange; >50 %: red
 */
// eslint-disable-next-line react-refresh/only-export-components -- see parseFillResult above.
export function riskColor(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return '#9ca3af'
  if (pct <= 5)  return '#34d399'
  if (pct <= 20) return '#fbbf24'
  if (pct <= 50) return '#f97316'
  return '#f87171'
}

/**
 * Format a number to a given number of decimal places.
 * Returns "—" for null / non-finite.
 */
// eslint-disable-next-line react-refresh/only-export-components -- see parseFillResult above.
export function fmtNum(n: number | null | undefined, digits = 3): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

/**
 * Return a human-readable short-shot risk label.
 */
// eslint-disable-next-line react-refresh/only-export-components -- see parseFillResult above.
export function shortShotLabel(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct)) return 'Unknown'
  if (pct <= 5)  return 'Low'
  if (pct <= 20) return 'Moderate'
  if (pct <= 50) return 'High'
  return 'Critical'
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const S: Record<string, CSSProperties> = {
  container: {
    fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
    fontSize: 12,
    color: '#e2e8f0',
    background: '#0f172a',
    padding: 16,
    borderRadius: 8,
    border: '1px solid #1e293b',
    overflowY: 'auto',
    maxHeight: 520,
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
  polymerTag: {
    background: '#312e81',
    color: '#a5b4fc',
    borderRadius: 4,
    padding: '1px 6px',
    fontSize: 10,
    marginLeft: 'auto',
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
  riskBar: {
    height: 6,
    borderRadius: 3,
    marginTop: 5,
    background: '#1e293b',
    overflow: 'hidden',
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
  weldEntry: {
    background: '#1e293b',
    borderRadius: 4,
    padding: '4px 8px',
    marginBottom: 4,
    color: '#cbd5e1',
    fontSize: 11,
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  trapEntry: {
    background: '#1e293b',
    borderRadius: 4,
    padding: '4px 8px',
    marginBottom: 4,
    color: '#fca5a5',
    fontSize: 11,
    display: 'flex',
    alignItems: 'center',
    gap: 6,
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

interface MetricCardProps {
  icon?: LucideIcon
  label: string
  value: ReactNode
  unit?: string
  accent?: string
}

function MetricCard({ icon: Icon, label, value, unit, accent }: MetricCardProps) {
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

function RiskGauge({ pct }: { pct: number | null | undefined }) {
  const label  = shortShotLabel(pct)
  const color  = riskColor(pct)
  const width  = Math.min(100, Math.max(0, pct ?? 0))
  return (
    <div style={S.metricCard}>
      <div style={S.metricLabel}>
        <Gauge size={10} />
        Short-shot risk
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ ...S.metricValue, color }}>{fmtNum(pct, 1)}</span>
        <span style={S.metricUnit}>%</span>
        <span style={{ ...S.badge, background: color + '22', color, borderColor: color + '55', marginLeft: 4 }}>
          {label}
        </span>
      </div>
      <div style={S.riskBar}>
        <div style={{ height: '100%', width: `${width}%`, background: color, borderRadius: 3, transition: 'width 0.4s' }} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * InjectionFillPanel renders the output of mold_injection_fill_simulate.
 *
 * Props:
 *   parsedContent — string | object  (raw tool JSON output)
 */
export default function InjectionFillPanel({ parsedContent }: InjectionFillPanelProps) {
  // TS doesn't carry the negated "typeof === object && !== null" narrowing
  // into the ternary's else branch, so the non-object arm is asserted back
  // to string | null | undefined (parsedContent can only be a string here
  // at runtime once the object branch is excluded).
  const raw = typeof parsedContent === 'object' && parsedContent !== null
    ? JSON.stringify(parsedContent)
    : ((parsedContent as string | null | undefined) ?? '')

  const { kind, data, error } = parseFillResult(raw)

  if (kind === 'empty') {
    return (
      <div style={S.container}>
        <div style={S.empty}>No fill simulation result loaded.</div>
      </div>
    )
  }

  if (kind === 'invalid') {
    return (
      <div style={S.container}>
        <div style={{ ...S.caveat, borderColor: '#f8717144' }}>
          <AlertTriangle size={12} style={{ display: 'inline', marginRight: 4 }} />
          Could not parse fill result: {error}
        </div>
      </div>
    )
  }

  const d = data

  return (
    <div style={S.container}>
      {/* Header */}
      <div style={S.header}>
        <Droplets size={14} color="#7dd3fc" />
        <span style={S.title}>Injection Fill Analysis</span>
        {d.polymer && (
          <span style={S.polymerTag}>{d.polymer}</span>
        )}
      </div>

      {/* Key metrics */}
      <div style={S.metricsGrid}>
        <MetricCard
          icon={Clock}
          label="Fill time"
          value={fmtNum(d.fill_time_s, 3)}
          unit="s"
          accent="#7dd3fc"
        />
        <MetricCard
          icon={Gauge}
          label="Max ΔP"
          value={fmtNum(d.max_pressure_drop_mpa, 2)}
          unit="MPa"
          accent="#a78bfa"
        />
        <MetricCard
          icon={Wind}
          label="Weld lines"
          value={d.weld_line_count ?? 0}
          accent={d.weld_line_count > 0 ? '#fbbf24' : '#34d399'}
        />
        <MetricCard
          icon={AlertTriangle}
          label="Air traps"
          value={d.air_trap_count ?? 0}
          accent={d.air_trap_count > 0 ? '#f87171' : '#34d399'}
        />
      </div>

      {/* Short-shot risk gauge */}
      <RiskGauge pct={d.short_shot_risk_pct} />

      {/* Weld-line detail */}
      {Array.isArray(d.weld_lines) && d.weld_lines.length > 0 && (
        <>
          <div style={S.sectionTitle}>Weld Lines</div>
          {d.weld_lines.map((wl, i) => (
            <div key={i} style={S.weldEntry}>
              <Wind size={10} color="#fbbf24" />
              <span>Line {i + 1} — {Array.isArray(wl) ? wl.length : 0} points</span>
              {Array.isArray(wl) && wl[0] && (
                <span style={{ color: '#64748b', marginLeft: 'auto' }}>
                  origin ({fmtNum(wl[0].x ?? wl[0][0], 1)}, {fmtNum(wl[0].y ?? wl[0][1], 1)})
                </span>
              )}
            </div>
          ))}
        </>
      )}

      {/* Air-trap detail */}
      {Array.isArray(d.air_traps) && d.air_traps.length > 0 && (
        <>
          <div style={S.sectionTitle}>Air Traps</div>
          {d.air_traps.map((trap, i) => (
            <div key={i} style={S.trapEntry}>
              <AlertTriangle size={10} color="#f87171" />
              <span>
                ({fmtNum(trap.x ?? trap[0], 1)}, {fmtNum(trap.y ?? trap[1], 1)})
              </span>
            </div>
          ))}
        </>
      )}

      {/* Last-to-fill */}
      {typeof d.last_to_fill_count === 'number' && d.last_to_fill_count > 0 && (
        <>
          <div style={S.sectionTitle}>Last-to-fill regions</div>
          <div style={S.weldEntry}>
            <CheckCircle2 size={10} color="#94a3b8" />
            <span>{d.last_to_fill_count} cells in the final 5% fill window</span>
          </div>
        </>
      )}

      {/* Honest caveat */}
      {d.honest_caveat && (
        <div style={S.caveat}>
          <AlertTriangle size={11} style={{ display: 'inline', marginRight: 4 }} />
          {d.honest_caveat}
        </div>
      )}
    </div>
  )
}
