// CMMInspectionPanel — CMM inspection / metrology results viewer.
//
// Renders the output of cmm_fit_geometry, cmm_align_datum, cmm_eval_gdt,
// cmm_eval_position, cmm_eval_profile, cmm_gum_uncertainty, cmm_probe_compensate,
// cmm_recommend_samples, cmm_gauge_rr, and cmm_process_capability LLM tools.
//
// File format (.cmm — JSON produced by a cmm_* tool call):
//   { "tool": "cmm_fit_geometry"|"cmm_eval_gdt"|..., "result": { ...tool output } }
//
// Pure display — no live API calls. All data comes from parsedContent.
//
// Exported pure helpers (no DOM) for vitest:
//   parseCMMFile(content)    → { kind, tool, result, error? }
//   fmtMm(n, digits?)        → "N.NNmm" string
//   inTolerance(value, tol)  → boolean
//   detectCMMTool(tool, r)   → string

import { AlertTriangle, CheckCircle2, Crosshair } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw CMM file content.
 * Returns { kind: 'ok'|'empty'|'invalid', tool, result, error? }
 */
export function parseCMMFile(content) {
  const raw = typeof content === 'string' ? content : ''
  if (!raw.trim()) return { kind: 'empty', tool: null, result: null }
  let doc
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    return { kind: 'invalid', error: e.message }
  }
  if (!doc || typeof doc !== 'object') return { kind: 'invalid', error: 'Expected JSON object' }
  const tool   = doc.tool || null
  const result = doc.result || doc
  if (!result || typeof result !== 'object') return { kind: 'invalid', error: 'No result field' }
  if (result.ok === false) return { kind: 'invalid', error: result.reason || 'Tool returned ok:false' }
  return { kind: 'ok', tool, result }
}

/**
 * Format a number as a mm dimension string.
 * Returns "—" for non-finite values.
 */
export function fmtMm(n, digits = 4) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(digits) + ' mm'
}

/**
 * Return true if the measured value is within ±tolerance.
 * When tolerance is null/undefined, returns null (unknown).
 */
export function inTolerance(value, tol) {
  if (tol == null || value == null) return null
  return Math.abs(value) <= Math.abs(tol)
}

/**
 * Detect which CMM tool produced the result from the tool name and keys.
 */
export function detectCMMTool(tool, r) {
  if (tool) {
    if (tool.includes('fit_geometry'))      return 'fit_geometry'
    if (tool.includes('align_datum'))       return 'align_datum'
    if (tool.includes('eval_gdt'))          return 'eval_gdt'
    if (tool.includes('eval_position'))     return 'eval_position'
    if (tool.includes('eval_profile'))      return 'eval_profile'
    if (tool.includes('gum_uncertainty'))   return 'gum_uncertainty'
    if (tool.includes('probe_compensate'))  return 'probe_compensate'
    if (tool.includes('recommend_samples')) return 'recommend_samples'
    if (tool.includes('gauge_rr'))          return 'gauge_rr'
    if (tool.includes('process_capability'))return 'process_capability'
  }
  if (!r) return 'unknown'
  if ('form_error' in r && 'shape' in r)          return 'fit_geometry'
  if ('transform' in r)                            return 'align_datum'
  if ('zone_width' in r && 'characteristic' in r)  return 'eval_gdt'
  if ('positional_deviation' in r)                 return 'eval_position'
  if ('profile_value' in r)                        return 'eval_profile'
  if ('expanded_uncertainty' in r)                 return 'gum_uncertainty'
  if ('compensated_pts' in r)                      return 'probe_compensate'
  if ('n_recommended' in r)                        return 'recommend_samples'
  if ('grr' in r || 'GRR' in r)                    return 'gauge_rr'
  if ('cpk' in r && 'ppk' in r)                    return 'process_capability'
  return 'unknown'
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricCard({ label, value, mono, highlight, unit }) {
  const displayVal = unit ? `${value ?? '—'} ${unit}` : (value ?? '—')
  return (
    <div style={styles.metricCard}>
      <div style={styles.metricLabel}>{label}</div>
      <div style={{ ...styles.metricValue, ...(mono ? styles.mono : {}), color: highlight || styles.metricValue.color }}>
        {displayVal}
      </div>
    </div>
  )
}

function PassFailBadge({ pass, label }) {
  if (pass == null) return null
  return (
    <span style={{ ...styles.badge, background: pass ? '#14532d44' : '#7f1d1d44', color: pass ? '#34d399' : '#f87171', borderColor: pass ? '#15803d66' : '#b91c1c66' }}>
      {pass
        ? <><CheckCircle2 size={10} style={{ display: 'inline', marginRight: 3 }} />{label || 'PASS'}</>
        : <><AlertTriangle size={10} style={{ display: 'inline', marginRight: 3 }} />{label || 'FAIL'}</>
      }
    </span>
  )
}

function SectionTitle({ children }) {
  return <div style={styles.sectionTitle}>{children}</div>
}

// ---------------------------------------------------------------------------
// Tool-specific result renderers
// ---------------------------------------------------------------------------

function FitGeometryResult({ r }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={styles.metricsGrid}>
        <MetricCard label="Shape" value={r.shape || '—'} />
        <MetricCard label="Form error" value={r.form_error != null ? fmtMm(r.form_error) : '—'} mono />
        {r.radius   != null && <MetricCard label="Radius"  value={fmtMm(r.radius)} mono />}
        {r.rms != null      && <MetricCard label="RMS res" value={fmtMm(r.rms)} mono />}
      </div>
      {r.centroid && (
        <>
          <SectionTitle>Centroid</SectionTitle>
          <div style={styles.metricsGrid}>
            {(['x','y','z']).map((ax) => r.centroid[ax] != null && (
              <MetricCard key={ax} label={ax.toUpperCase()} value={fmtMm(r.centroid[ax])} mono />
            ))}
          </div>
        </>
      )}
      {r.centre && (
        <>
          <SectionTitle>Centre</SectionTitle>
          <div style={styles.metricsGrid}>
            {r.centre.map((v, i) => (
              <MetricCard key={i} label={['X','Y','Z'][i] || `C${i}`} value={fmtMm(v)} mono />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function EvalGDTResult({ r }) {
  const pass = r.in_tolerance != null ? r.in_tolerance : inTolerance(r.zone_width, r.tolerance)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>{r.characteristic || 'GD&T'}</span>
        <PassFailBadge pass={pass} />
      </div>
      <div style={styles.metricsGrid}>
        <MetricCard label="Zone width" value={r.zone_width != null ? fmtMm(r.zone_width) : '—'} mono />
        {r.tolerance != null && <MetricCard label="Tolerance" value={fmtMm(r.tolerance)} mono />}
        {r.mean_deviation != null && <MetricCard label="Mean dev" value={fmtMm(r.mean_deviation)} mono />}
        {r.max_deviation  != null && <MetricCard label="Max dev"  value={fmtMm(r.max_deviation)} mono />}
      </div>
      {r.warnings?.length > 0 && (
        <div style={styles.warningBox}>
          {r.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}
    </div>
  )
}

function EvalPositionResult({ r }) {
  const pass = r.in_tolerance != null ? r.in_tolerance : inTolerance(r.positional_deviation, r.effective_tolerance)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>True Position (ASME Y14.5)</span>
        <PassFailBadge pass={pass} />
      </div>
      <div style={styles.metricsGrid}>
        <MetricCard label="Deviation" value={r.positional_deviation != null ? fmtMm(r.positional_deviation) : '—'} mono />
        <MetricCard label="Tolerance" value={r.tolerance != null ? fmtMm(r.tolerance) : '—'} mono />
        {r.bonus_tolerance != null && <MetricCard label="MMC bonus" value={fmtMm(r.bonus_tolerance)} mono />}
        {r.effective_tolerance != null && <MetricCard label="Effective tol" value={fmtMm(r.effective_tolerance)} mono />}
      </div>
    </div>
  )
}

function ProcessCapabilityResult({ r }) {
  const capable = r.cpk != null ? r.cpk >= 1.33 : null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>Process Capability (Cpk/Ppk)</span>
        <PassFailBadge pass={capable} label={capable ? 'CAPABLE' : 'NOT CAPABLE'} />
      </div>
      <div style={styles.metricsGrid}>
        <MetricCard label="Cpk (short-term)"  value={r.cpk?.toFixed(3)} mono
          highlight={r.cpk != null ? (r.cpk >= 1.33 ? '#34d399' : r.cpk >= 1.0 ? '#fbbf24' : '#f87171') : undefined} />
        <MetricCard label="Ppk (long-term)"   value={r.ppk?.toFixed(3)} mono
          highlight={r.ppk != null ? (r.ppk >= 1.33 ? '#34d399' : r.ppk >= 1.0 ? '#fbbf24' : '#f87171') : undefined} />
        <MetricCard label="Mean"   value={r.mean?.toFixed(4)}  mono />
        <MetricCard label="Sigma"  value={r.sigma?.toFixed(4)} mono />
        <MetricCard label="USL"    value={r.usl?.toFixed(4)}   mono />
        <MetricCard label="LSL"    value={r.lsl?.toFixed(4)}   mono />
        {r.defect_ppm != null && <MetricCard label="Defect PPM" value={r.defect_ppm?.toFixed(1)} highlight={r.defect_ppm > 6210 ? '#f87171' : '#34d399'} />}
        {r.yield_pct  != null && <MetricCard label="Yield %"   value={r.yield_pct?.toFixed(2) + '%'} />}
      </div>
      {r.warnings?.length > 0 && (
        <div style={styles.warningBox}>
          {r.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}
    </div>
  )
}

function GaugeRRResult({ r }) {
  const capable = r.pct_study_var != null ? r.pct_study_var <= 10 : null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: '#9ca3af' }}>Gauge R&R (AIAG MSA)</span>
        <PassFailBadge pass={capable} label={capable ? 'CAPABLE' : capable === false ? 'POOR' : undefined} />
      </div>
      <div style={styles.metricsGrid}>
        <MetricCard label="GRR"         value={r.grr?.toFixed(4) ?? r.GRR?.toFixed(4)} mono />
        <MetricCard label="EV (repeat)" value={r.ev?.toFixed(4) ?? r.EV?.toFixed(4)} mono />
        <MetricCard label="AV (reprod)" value={r.av?.toFixed(4) ?? r.AV?.toFixed(4)} mono />
        <MetricCard label="PV (part)"   value={r.pv?.toFixed(4) ?? r.PV?.toFixed(4)} mono />
        <MetricCard label="TV (total)"  value={r.tv?.toFixed(4) ?? r.TV?.toFixed(4)} mono />
        {r.pct_study_var != null && (
          <MetricCard label="GRR % study" value={r.pct_study_var?.toFixed(1) + '%'}
            highlight={r.pct_study_var <= 10 ? '#34d399' : r.pct_study_var <= 30 ? '#fbbf24' : '#f87171'} />
        )}
        {r.ndc != null && <MetricCard label="NDC" value={r.ndc} highlight={r.ndc >= 5 ? '#34d399' : '#fbbf24'} />}
      </div>
    </div>
  )
}

function GumUncertaintyResult({ r }) {
  return (
    <div style={styles.metricsGrid}>
      <MetricCard label="Combined uc"      value={r.uc?.toFixed(6)}        mono />
      <MetricCard label="Expanded U (k×uc)" value={r.U?.toFixed(6)}         mono />
      <MetricCard label="Coverage factor k" value={r.coverage_factor?.toFixed(1)} mono />
    </div>
  )
}

function RecommendSamplesResult({ r }) {
  return (
    <div style={styles.metricsGrid}>
      <MetricCard label="Recommended N"   value={r.n_recommended} />
      <MetricCard label="Nyquist minimum" value={r.n_nyquist} />
      <MetricCard label="Safety factor"   value={r.safety_factor?.toFixed(2)} mono />
      <MetricCard label="Harmonics"       value={r.expected_harmonics} />
    </div>
  )
}

function GenericResult({ r }) {
  return (
    <pre style={{ fontSize: 10, color: '#9ca3af', whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0 }}>
      {JSON.stringify(r, null, 2)}
    </pre>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const TOOL_LABELS = {
  fit_geometry:      'CMM Geometry Fit',
  align_datum:       'CMM Datum Alignment',
  eval_gdt:          'GD&T Evaluation',
  eval_position:     'True-Position Evaluation',
  eval_profile:      'Surface Profile Evaluation',
  gum_uncertainty:   'GUM Measurement Uncertainty',
  probe_compensate:  'Probe Radius Compensation',
  recommend_samples: 'Sample Recommendation',
  gauge_rr:          'Gauge R&R Study',
  process_capability:'CMM Process Capability',
  unknown:           'CMM Inspection Results',
}

/**
 * CMMInspectionPanel
 *
 * Props:
 *   parsedContent — already-parsed JSON of a `.cmm` file, or null.
 *   rawContent    — raw string content (used when parsedContent is absent).
 *   fileName      — display name.
 */
export default function CMMInspectionPanel({ parsedContent, rawContent, fileName }) {
  const source = parsedContent ?? (rawContent ? (() => {
    try { return JSON.parse(rawContent) } catch { return null }
  })() : null)

  const parsed = source ? parseCMMFile(JSON.stringify(source)) : parseCMMFile(rawContent || '')

  if (parsed.kind === 'empty') {
    return (
      <div style={styles.root}>
        <Header fileName={fileName} title="CMM Inspection" />
        <div style={styles.empty}>No CMM data yet. Run a <code style={{ color: '#a78bfa' }}>cmm_*</code> tool to generate inspection data.</div>
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div style={styles.root}>
        <Header fileName={fileName} title="CMM Inspection" />
        <div style={styles.errorBox}>
          <AlertTriangle size={13} style={{ flexShrink: 0 }} />
          <span style={{ marginLeft: 6 }}>{parsed.error || 'Invalid CMM file'}</span>
        </div>
      </div>
    )
  }

  const { tool, result } = parsed
  const toolType = detectCMMTool(tool, result)
  const title = TOOL_LABELS[toolType] || 'CMM Inspection Results'

  return (
    <div style={styles.root}>
      <Header fileName={fileName} title={title} />
      <div style={{ padding: '0 2px' }}>
        {toolType === 'fit_geometry'       && <FitGeometryResult r={result} />}
        {toolType === 'eval_gdt'           && <EvalGDTResult r={result} />}
        {toolType === 'eval_position'      && <EvalPositionResult r={result} />}
        {toolType === 'process_capability' && <ProcessCapabilityResult r={result} />}
        {toolType === 'gauge_rr'           && <GaugeRRResult r={result} />}
        {toolType === 'gum_uncertainty'    && <GumUncertaintyResult r={result} />}
        {toolType === 'recommend_samples'  && <RecommendSamplesResult r={result} />}
        {(toolType === 'align_datum' || toolType === 'eval_profile' ||
          toolType === 'probe_compensate' || toolType === 'unknown') && <GenericResult r={result} />}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function Header({ fileName, title }) {
  return (
    <div style={styles.header}>
      <Crosshair size={14} style={{ color: '#34d399', flexShrink: 0 }} />
      <span style={styles.titleText}>{title}</span>
      {fileName && <span style={styles.fileName}>{fileName}</span>}
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
  titleText: { fontWeight: 600, fontSize: 14, color: '#f3f4f6' },
  fileName: { fontSize: 11, color: '#6b7280', marginLeft: 4 },
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
  sectionTitle: { fontSize: 10, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' },
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '1px 8px',
    borderRadius: 9999,
    fontSize: 10,
    fontWeight: 700,
    border: '1px solid',
    letterSpacing: '0.05em',
  },
  warningBox: {
    background: '#1c1408',
    border: '1px solid #92400e',
    borderRadius: 5,
    padding: '5px 10px',
    color: '#fbbf24',
    fontSize: 11,
    lineHeight: 1.6,
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
