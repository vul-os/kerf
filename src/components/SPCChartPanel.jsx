// SPCChartPanel — Statistical Process Control chart results viewer.
//
// Renders the output of the spc_xbar_r_chart, spc_xbar_s_chart,
// spc_cusum_chart, spc_ewma_chart, and spc_run_rules LLM tools.
//
// File format (.spc — JSON produced by an spc_* tool call):
//   { "tool": "spc_xbar_r_chart"|"spc_cusum_chart"|...,  "result": { ...tool output } }
//
// The panel auto-detects which chart type is present from the stored keys
// and renders accordingly.
//
// Pure display — no live API calls. All data comes from parsedContent.
//
// Exported pure helpers (no DOM) for vitest:
//   parseSPCFile(content)    → { kind, result, tool, error? }
//   fmtSigma(n)              → "+N.NN σ" string
//   flagColor(isOoc)         → CSS colour string
//   oocCount(oocArray)       → integer count

import { useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw file content string into a usable SPC result object.
 * Returns { kind: 'ok'|'empty'|'invalid', tool, result, error? }
 */
export function parseSPCFile(content) {
  const raw = typeof content === 'string' ? content : ''
  if (!raw.trim()) return { kind: 'empty', tool: null, result: null }
  let doc
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    return { kind: 'invalid', error: e.message }
  }
  if (!doc || typeof doc !== 'object') return { kind: 'invalid', error: 'Expected JSON object' }

  // Accept both { tool, result } wrapper and direct tool-output objects
  const tool   = doc.tool || null
  const result = doc.result || doc
  if (!result || typeof result !== 'object') return { kind: 'invalid', error: 'No result field' }
  if (result.ok === false)
    return { kind: 'invalid', error: result.reason || 'Tool returned ok:false' }
  return { kind: 'ok', tool, result }
}

/**
 * Format a number as a sigma string like "+1.50 σ" or "–2.03 σ".
 * Returns "—" for null/undefined/NaN.
 */
export function fmtSigma(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  const sign = n >= 0 ? '+' : '−'
  return `${sign}${Math.abs(n).toFixed(2)} σ`
}

/**
 * Return a CSS colour string for out-of-control (OOC) flag.
 */
export function flagColor(isOoc) {
  return isOoc ? '#f87171' : '#34d399'
}

/**
 * Count total OOC signals from an array of OOC point indices or
 * an object of rule→indices.
 */
export function oocCount(ooc) {
  if (!ooc) return 0
  if (Array.isArray(ooc)) return ooc.length
  if (typeof ooc === 'object') {
    return Object.values(ooc).reduce((s, v) => s + (Array.isArray(v) ? v.length : 0), 0)
  }
  return 0
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Small metric card */
function MetricCard({ label, value, mono, highlight }) {
  return (
    <div style={styles.metricCard}>
      <div style={styles.metricLabel}>{label}</div>
      <div style={{
        ...styles.metricValue,
        ...(mono ? styles.mono : {}),
        color: highlight || styles.metricValue.color,
      }}>{value ?? '—'}</div>
    </div>
  )
}

/** Horizontal sparkline for a numeric series (UCL/LCL/CL bands optional) */
function MiniChart({ data, ucl, lcl, cl, label, height = 70, color = '#818cf8' }) {
  if (!data || data.length < 2) return null
  const n    = data.length
  const mins = [Math.min(...data), ucl, lcl, cl].filter((v) => v != null)
  const maxs = [Math.max(...data), ucl, lcl, cl].filter((v) => v != null)
  const minY = Math.min(...mins)
  const maxY = Math.max(...maxs)
  const rangeY = maxY - minY || 1
  const W = 600
  const H = height
  const pad = 4

  function yPos(v) { return H - pad - ((v - minY) / rangeY) * (H - pad * 2) }
  function xPos(i) { return pad + (i / (n - 1)) * (W - pad * 2) }

  const pts = data.map((v, i) => `${xPos(i).toFixed(1)},${yPos(v).toFixed(1)}`).join(' ')

  return (
    <div style={{ marginBottom: 8 }}>
      {label && <div style={styles.chartLabel}>{label}</div>}
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" style={{ borderRadius: 4, background: '#0d1117' }}>
        {/* Control limit bands */}
        {ucl != null && lcl != null && (
          <rect x={pad} y={yPos(ucl)} width={W - pad * 2} height={Math.max(1, yPos(lcl) - yPos(ucl))} fill="#1e3a5f44" />
        )}
        {/* Center line */}
        {cl != null && (
          <line x1={pad} y1={yPos(cl)} x2={W - pad} y2={yPos(cl)} stroke="#4b5563" strokeWidth="1" strokeDasharray="4,3" />
        )}
        {/* UCL / LCL lines */}
        {ucl != null && (
          <line x1={pad} y1={yPos(ucl)} x2={W - pad} y2={yPos(ucl)} stroke="#6366f1" strokeWidth="1" strokeDasharray="3,2" />
        )}
        {lcl != null && (
          <line x1={pad} y1={yPos(lcl)} x2={W - pad} y2={yPos(lcl)} stroke="#6366f1" strokeWidth="1" strokeDasharray="3,2" />
        )}
        {/* Data polyline */}
        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
        {/* Data dots */}
        {data.map((v, i) => {
          const ooc = (ucl != null && v > ucl) || (lcl != null && v < lcl)
          return (
            <circle
              key={i}
              cx={xPos(i)}
              cy={yPos(v)}
              r="3"
              fill={ooc ? '#f87171' : color}
              opacity={0.9}
            />
          )
        })}
      </svg>
    </div>
  )
}

/** Collapsible run-rules violations section */
function RunRulesSection({ violations, anyViolation }) {
  const [open, setOpen] = useState(false)
  if (!violations) return null
  const rules = Object.entries(violations).filter(([, v]) => Array.isArray(v) && v.length > 0)

  return (
    <div style={{ marginTop: 8 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={styles.collapseBtn}
      >
        {anyViolation
          ? <AlertTriangle size={12} style={{ color: '#fbbf24', flexShrink: 0 }} />
          : <CheckCircle2 size={12} style={{ color: '#34d399', flexShrink: 0 }} />
        }
        <span>Run rules: {anyViolation ? `${rules.length} violation(s)` : 'all clear'}</span>
        {open ? <ChevronUp size={11} style={{ marginLeft: 'auto' }} /> : <ChevronDown size={11} style={{ marginLeft: 'auto' }} />}
      </button>
      {open && (
        <div style={{ marginTop: 4, paddingLeft: 8 }}>
          {rules.length === 0
            ? <div style={{ fontSize: 11, color: '#6b7280' }}>No rule violations detected.</div>
            : rules.map(([rule, pts]) => (
              <div key={rule} style={{ fontSize: 11, color: '#fca5a5', marginBottom: 2 }}>
                {rule}: points {pts.join(', ')}
              </div>
            ))
          }
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Chart-type renderers
// ---------------------------------------------------------------------------

function XBarRChart({ result }) {
  const xbar = result.subgroup_means || []
  const r    = result.subgroup_ranges || []
  const totalOoc = (result.ooc_xbar?.length || 0) + (result.ooc_r?.length || 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={styles.metricsGrid}>
        <MetricCard label="Grand mean (x̄̄)" value={result.grand_mean?.toFixed(4)} mono />
        <MetricCard label="Avg range (R̄)"   value={result.r_bar?.toFixed(4)} mono />
        <MetricCard label="UCL (x̄)"         value={result.ucl_xbar?.toFixed(4)} mono />
        <MetricCard label="LCL (x̄)"         value={result.lcl_xbar?.toFixed(4)} mono />
        <MetricCard label="Estimated σ"      value={result.sigma?.toFixed(4)} mono />
        <MetricCard label="OOC points"       value={totalOoc}
          highlight={totalOoc > 0 ? '#f87171' : '#34d399'} />
      </div>
      <MiniChart data={xbar} ucl={result.ucl_xbar} lcl={result.lcl_xbar} cl={result.grand_mean} label="X̄ chart" color="#818cf8" />
      <MiniChart data={r}    ucl={result.ucl_r}    lcl={result.lcl_r}    cl={result.r_bar}      label="R chart" color="#34d399" />
    </div>
  )
}

function XBarSChart({ result }) {
  const xbar = result.subgroup_means || []
  const s    = result.subgroup_stdevs || []
  const totalOoc = (result.ooc_xbar?.length || 0) + (result.ooc_s?.length || 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={styles.metricsGrid}>
        <MetricCard label="Grand mean (x̄̄)" value={result.grand_mean?.toFixed(4)} mono />
        <MetricCard label="Avg StDev (S̄)"   value={result.s_bar?.toFixed(4)} mono />
        <MetricCard label="UCL (x̄)"         value={result.ucl_xbar?.toFixed(4)} mono />
        <MetricCard label="LCL (x̄)"         value={result.lcl_xbar?.toFixed(4)} mono />
        <MetricCard label="Estimated σ"      value={result.sigma?.toFixed(4)} mono />
        <MetricCard label="OOC points"       value={totalOoc}
          highlight={totalOoc > 0 ? '#f87171' : '#34d399'} />
      </div>
      <MiniChart data={xbar} ucl={result.ucl_xbar} lcl={result.lcl_xbar} cl={result.grand_mean} label="X̄ chart" color="#818cf8" />
      <MiniChart data={s}    ucl={result.ucl_s}    lcl={result.lcl_s}    cl={result.s_bar}      label="S chart" color="#34d399" />
    </div>
  )
}

function CusumChart({ result }) {
  const cPos = result.c_pos || []
  const cNeg = result.c_neg || []
  const ooc  = (result.ooc_pos?.length || 0) + (result.ooc_neg?.length || 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={styles.metricsGrid}>
        <MetricCard label="Target (μ₀)"  value={result.target?.toFixed(4)} mono />
        <MetricCard label="Sigma (σ)"    value={result.sigma?.toFixed(4)} mono />
        <MetricCard label="K (allowance)" value={result.K?.toFixed(4)} mono />
        <MetricCard label="H (decision)" value={result.H?.toFixed(4)} mono />
        <MetricCard label="OOC signals"  value={ooc} highlight={ooc > 0 ? '#f87171' : '#34d399'} />
      </div>
      <MiniChart data={cPos} ucl={result.H} lcl={0} cl={0} label="C⁺ (upper CUSUM)" color="#818cf8" />
      <MiniChart data={cNeg} ucl={0} lcl={result.H != null ? -result.H : undefined} cl={0} label="C⁻ (lower CUSUM)" color="#f472b6" />
    </div>
  )
}

function EwmaChart({ result }) {
  const ewma = result.ewma || []
  const ucl  = Array.isArray(result.ucl) ? result.ucl[result.ucl.length - 1] : result.ucl
  const lcl  = Array.isArray(result.lcl) ? result.lcl[result.lcl.length - 1] : result.lcl
  const ooc  = result.ooc?.length || 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={styles.metricsGrid}>
        <MetricCard label="Target (μ₀)"   value={result.target?.toFixed(4)} mono />
        <MetricCard label="Sigma (σ)"     value={result.sigma?.toFixed(4)} mono />
        <MetricCard label="Lambda (λ)"    value={result.lam?.toFixed(3)} mono />
        <MetricCard label="UCL"           value={typeof ucl === 'number' ? ucl.toFixed(4) : '—'} mono />
        <MetricCard label="LCL"           value={typeof lcl === 'number' ? lcl.toFixed(4) : '—'} mono />
        <MetricCard label="OOC points"    value={ooc} highlight={ooc > 0 ? '#f87171' : '#34d399'} />
      </div>
      <MiniChart
        data={ewma}
        ucl={typeof ucl === 'number' ? ucl : undefined}
        lcl={typeof lcl === 'number' ? lcl : undefined}
        cl={result.target}
        label="EWMA"
        color="#818cf8"
      />
    </div>
  )
}

function RunRulesResult({ result }) {
  const anyViolation = result.any_violation === true
  const totalViolations = oocCount(result.violations)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={styles.metricsGrid}>
        <MetricCard
          label="Status"
          value={anyViolation ? 'Special causes detected' : 'In statistical control'}
          highlight={anyViolation ? '#f87171' : '#34d399'}
        />
        <MetricCard label="Total violations" value={totalViolations}
          highlight={totalViolations > 0 ? '#fbbf24' : '#34d399'} />
        <MetricCard label="Center" value={result.center?.toFixed(4)} mono />
        <MetricCard label="Sigma"  value={result.sigma?.toFixed(4)} mono />
      </div>
      <RunRulesSection violations={result.violations} anyViolation={anyViolation} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Detect chart type from result keys
// ---------------------------------------------------------------------------

function detectChartType(tool, result) {
  if (tool) {
    if (tool.includes('xbar_r'))   return 'xbar_r'
    if (tool.includes('xbar_s'))   return 'xbar_s'
    if (tool.includes('cusum'))    return 'cusum'
    if (tool.includes('ewma'))     return 'ewma'
    if (tool.includes('run_rules')) return 'run_rules'
  }
  if (result.subgroup_ranges !== undefined) return 'xbar_r'
  if (result.subgroup_stdevs !== undefined) return 'xbar_s'
  if (result.c_pos !== undefined)           return 'cusum'
  if (result.ewma !== undefined)            return 'ewma'
  if (result.violations !== undefined)      return 'run_rules'
  return 'unknown'
}

const CHART_TYPE_LABELS = {
  xbar_r:    'X̄-R Shewhart Chart',
  xbar_s:    'X̄-S Shewhart Chart',
  cusum:     'Tabular CUSUM Chart',
  ewma:      'EWMA Chart',
  run_rules: 'Run Rules Analysis',
  unknown:   'SPC Results',
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * SPCChartPanel
 *
 * Props:
 *   parsedContent — already-parsed JSON of a `.spc` file, or null.
 *   rawContent    — raw string content (used when parsedContent is absent).
 *   fileName      — display name.
 */
export default function SPCChartPanel({ parsedContent, rawContent, fileName }) {
  const source = parsedContent ?? (rawContent ? (() => {
    try { return JSON.parse(rawContent) } catch { return null }
  })() : null)

  const parsed = source ? parseSPCFile(JSON.stringify(source)) : parseSPCFile(rawContent || '')

  if (parsed.kind === 'empty') {
    return (
      <div style={styles.root}>
        <Header fileName={fileName} title="SPC Chart" chartTypeLabel="" />
        <div style={styles.empty}>No SPC data yet. Run an <code style={{ color: '#a78bfa' }}>spc_*</code> tool to generate chart data.</div>
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div style={styles.root}>
        <Header fileName={fileName} title="SPC Chart" chartTypeLabel="" />
        <div style={styles.errorBox}>
          <AlertTriangle size={13} style={{ flexShrink: 0 }} />
          <span style={{ marginLeft: 6 }}>{parsed.error || 'Invalid SPC file'}</span>
        </div>
      </div>
    )
  }

  const { tool, result } = parsed
  const chartType = detectChartType(tool, result)
  const title = CHART_TYPE_LABELS[chartType] || 'SPC Results'

  return (
    <div style={styles.root}>
      <Header fileName={fileName} title={title} chartTypeLabel={chartType !== 'unknown' ? chartType : ''} />
      <div style={{ padding: '0 2px' }}>
        {chartType === 'xbar_r'    && <XBarRChart result={result} />}
        {chartType === 'xbar_s'    && <XBarSChart result={result} />}
        {chartType === 'cusum'     && <CusumChart result={result} />}
        {chartType === 'ewma'      && <EwmaChart  result={result} />}
        {chartType === 'run_rules' && <RunRulesResult result={result} />}
        {chartType === 'unknown'   && (
          <pre style={{ fontSize: 10, color: '#9ca3af', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function Header({ fileName, title, chartTypeLabel }) {
  return (
    <div style={styles.header}>
      <Activity size={14} style={{ color: '#818cf8', flexShrink: 0 }} />
      <span style={styles.title}>{title}</span>
      {chartTypeLabel && (
        <span style={styles.typePill}>{chartTypeLabel.toUpperCase()}</span>
      )}
      {fileName && (
        <span style={styles.fileName}>{fileName}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  root: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 13,
    color: '#e5e7eb',
    background: '#111827',
    borderRadius: 8,
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    minWidth: 0,
    width: '100%',
    height: '100%',
    overflowY: 'auto',
    boxSizing: 'border-box',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    borderBottom: '1px solid #1f2937',
    paddingBottom: 10,
    flexWrap: 'wrap',
  },
  title: { fontWeight: 600, fontSize: 14, color: '#f3f4f6' },
  typePill: {
    padding: '1px 7px',
    borderRadius: 9999,
    fontSize: 10,
    fontWeight: 700,
    background: '#1e1b4b',
    color: '#a5b4fc',
    border: '1px solid #3730a3',
    letterSpacing: '0.05em',
  },
  fileName: { fontSize: 11, color: '#6b7280', marginLeft: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  metricsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))',
    gap: 8,
  },
  metricCard: {
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 6,
    padding: '6px 10px',
  },
  metricLabel: { fontSize: 10, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' },
  metricValue: { fontSize: 13, color: '#e5e7eb', fontWeight: 600, marginTop: 2 },
  mono: { fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace', color: '#a78bfa' },
  chartLabel: { fontSize: 10, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 },
  collapseBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 5,
    color: '#d1d5db',
    fontSize: 11,
    padding: '4px 10px',
    cursor: 'pointer',
    width: '100%',
    textAlign: 'left',
  },
  empty: { color: '#6b7280', fontSize: 12, padding: '12px 0' },
  errorBox: {
    display: 'flex',
    alignItems: 'center',
    background: '#1f0707',
    border: '1px solid #7f1d1d',
    borderRadius: 5,
    padding: '6px 10px',
    color: '#fca5a5',
    fontSize: 12,
    gap: 4,
  },
}
