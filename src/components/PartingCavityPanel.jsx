/**
 * PartingCavityPanel.jsx — Parting-line detection + cavity/core split result viewer.
 *
 * Renders the output of the mold_detect_parting_line and mold_split_cavity_core
 * LLM tools (kerf_mold.parting_cavity_tools).
 *
 * Algorithm basis:
 *   Hayrettin, A. et al. (2003). "Automatic parting line extraction for cast parts."
 *     Computer-Aided Design 35(12), 1109–1122. §3 silhouette detection.
 *   Chen, L.L., Rosen, D.W. (1999). "Parting direction selection in mold design."
 *     J. Manufacturing Science & Engineering 121(1), 73–80. §2–§4.
 *
 * Input format (parsedContent JSON — either parting-line or split-result):
 *   Parting-line:
 *     { ok, segments, total_length_mm, closed_loops, has_undercuts,
 *       undercut_face_ids, draft_deficient_face_ids, honest_caveat }
 *   Cavity/core split:
 *     { ok, parting_surface, cavity_body, core_body, insert_count,
 *       parting_surface_complexity, has_sliders_needed, has_lifters_needed,
 *       honest_caveat }
 *
 * Exported pure helpers for vitest:
 *   parsePartingResult(content)  → { kind, mode, data, error? }
 *   detectMode(data)             → 'parting_line'|'split'|'unknown'
 *   classifyColor(classification) → CSS colour string
 *   fmtMm(n, digits)             → string
 */

import { AlertTriangle, CheckCircle2, Layers, Scissors } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw parting-result JSON content.
 * Returns { kind: 'ok'|'empty'|'invalid', mode, data, error? }
 */
export function parsePartingResult(content) {
  const raw = typeof content === 'string' ? content : ''
  if (!raw.trim()) return { kind: 'empty', mode: null, data: null }
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
  const mode = detectMode(data)
  if (mode === 'unknown') {
    return { kind: 'invalid', error: 'Unrecognised parting tool output format' }
  }
  return { kind: 'ok', mode, data }
}

/**
 * Detect whether the result is from mold_detect_parting_line or mold_split_cavity_core.
 */
export function detectMode(data) {
  if (!data || typeof data !== 'object') return 'unknown'
  if ('segments' in data && 'closed_loops' in data) return 'parting_line'
  if ('parting_surface' in data && 'cavity_body' in data) return 'split'
  return 'unknown'
}

/**
 * Return a CSS colour string for an edge classification.
 */
export function classifyColor(classification) {
  if (classification === 'silhouette')       return '#34d399'
  if (classification === 'undercut_boundary') return '#f87171'
  if (classification === 'sharp_edge')        return '#fbbf24'
  return '#94a3b8'
}

/**
 * Format mm value.
 */
export function fmtMm(n, digits = 2) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(digits) + ' mm'
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
    maxHeight: 540,
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
  },
  metricValue: {
    color: '#f1f5f9',
    fontSize: 18,
    fontWeight: 700,
    fontVariantNumeric: 'tabular-nums',
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
  segRow: {
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
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    flexShrink: 0,
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
  faceList: {
    background: '#1e293b',
    borderRadius: 4,
    padding: '6px 10px',
    marginBottom: 6,
    color: '#f87171',
    fontSize: 11,
    lineHeight: 1.8,
  },
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetricCard({ label, value, accent }) {
  return (
    <div style={S.metricCard}>
      <div style={S.metricLabel}>{label}</div>
      <div style={{ ...S.metricValue, color: accent || S.metricValue.color }}>
        {value ?? '—'}
      </div>
    </div>
  )
}

function StatusBadge({ pass, label }) {
  const color  = pass ? '#34d399' : '#f87171'
  const bg     = pass ? '#14532d44' : '#7f1d1d44'
  const border = pass ? '#15803d66' : '#b91c1c66'
  return (
    <span style={{ ...S.badge, background: bg, color, borderColor: border }}>
      {pass
        ? <><CheckCircle2 size={10} style={{ display: 'inline', marginRight: 3 }} />{label || 'OK'}</>
        : <><AlertTriangle size={10} style={{ display: 'inline', marginRight: 3 }} />{label || 'WARN'}</>
      }
    </span>
  )
}

// ---------------------------------------------------------------------------
// Mode renderers
// ---------------------------------------------------------------------------

function PartingLineView({ data: d }) {
  const segs          = Array.isArray(d.segments) ? d.segments : []
  const silhouettes   = segs.filter(s => s.classification === 'silhouette')
  const undercuts     = segs.filter(s => s.classification === 'undercut_boundary')
  const draftFails    = Array.isArray(d.draft_deficient_face_ids) ? d.draft_deficient_face_ids : []
  const SHOW_MAX = 12

  return (
    <>
      <div style={S.metricsGrid}>
        <MetricCard label="Parting length" value={fmtMm(d.total_length_mm)} accent="#7dd3fc" />
        <MetricCard label="Closed loops" value={d.closed_loops ?? '—'} accent="#a78bfa" />
        <MetricCard label="Silhouette edges" value={silhouettes.length} accent="#34d399" />
        <MetricCard label="Undercut edges" value={undercuts.length} accent={undercuts.length > 0 ? '#f87171' : '#34d399'} />
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <StatusBadge pass={!d.has_undercuts} label={d.has_undercuts ? 'Undercuts detected' : 'No undercuts'} />
        <StatusBadge pass={draftFails.length === 0} label={draftFails.length > 0 ? `${draftFails.length} draft deficient` : 'Draft OK'} />
      </div>

      {segs.length > 0 && (
        <>
          <div style={S.sectionTitle}>Parting-Line Segments ({segs.length} total)</div>
          {segs.slice(0, SHOW_MAX).map((seg, i) => (
            <div key={i} style={S.segRow}>
              <div style={{ ...S.dot, background: classifyColor(seg.classification) }} />
              <span style={{ color: '#94a3b8', minWidth: 55 }}>{seg.edge_id || `E${i}`}</span>
              <span style={{ color: classifyColor(seg.classification), fontWeight: 600 }}>
                {seg.classification}
              </span>
              {seg.length_mm != null && (
                <span style={{ color: '#64748b', marginLeft: 'auto' }}>
                  {fmtMm(seg.length_mm)}
                </span>
              )}
            </div>
          ))}
          {segs.length > SHOW_MAX && (
            <div style={{ color: '#64748b', fontSize: 10, marginTop: 4 }}>
              + {segs.length - SHOW_MAX} more segments
            </div>
          )}
        </>
      )}

      {d.undercut_face_ids && d.undercut_face_ids.length > 0 && (
        <>
          <div style={S.sectionTitle}>Undercut Faces (side-action required)</div>
          <div style={S.faceList}>
            {d.undercut_face_ids.join(', ')}
          </div>
        </>
      )}

      {draftFails.length > 0 && (
        <>
          <div style={S.sectionTitle}>Draft-Deficient Faces</div>
          <div style={{ ...S.faceList, color: '#fbbf24' }}>
            {draftFails.join(', ')}
          </div>
        </>
      )}
    </>
  )
}

function SplitView({ data: d }) {
  const ps = d.parting_surface || {}
  return (
    <>
      <div style={S.metricsGrid}>
        <MetricCard label="Parting surface" value={ps.surface_type || d.parting_surface_complexity || '—'} accent="#7dd3fc" />
        <MetricCard label="Inserts" value={d.insert_count ?? '—'} accent="#a78bfa" />
        <MetricCard label="Sliders" value={d.has_sliders_needed ? 'Needed' : 'None'} accent={d.has_sliders_needed ? '#fbbf24' : '#34d399'} />
        <MetricCard label="Lifters" value={d.has_lifters_needed ? 'Needed' : 'None'} accent={d.has_lifters_needed ? '#fbbf24' : '#34d399'} />
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        <StatusBadge pass={!d.has_sliders_needed} label={d.has_sliders_needed ? 'Sliders required' : 'No sliders'} />
        <StatusBadge pass={!d.has_lifters_needed} label={d.has_lifters_needed ? 'Lifters required' : 'No lifters'} />
      </div>

      {d.cavity_body && (
        <>
          <div style={S.sectionTitle}>Cavity Half (pull side)</div>
          <div style={S.segRow}>
            <div style={{ ...S.dot, background: '#7dd3fc' }} />
            <span>{JSON.stringify(d.cavity_body).slice(0, 80)}…</span>
          </div>
        </>
      )}

      {d.core_body && (
        <>
          <div style={S.sectionTitle}>Core Half (ejection side)</div>
          <div style={S.segRow}>
            <div style={{ ...S.dot, background: '#a78bfa' }} />
            <span>{JSON.stringify(d.core_body).slice(0, 80)}…</span>
          </div>
        </>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * PartingCavityPanel renders the output of mold_detect_parting_line or
 * mold_split_cavity_core.
 *
 * Props:
 *   parsedContent — string | object  (raw tool JSON output)
 */
export default function PartingCavityPanel({ parsedContent }) {
  const raw = typeof parsedContent === 'object' && parsedContent !== null
    ? JSON.stringify(parsedContent)
    : (parsedContent ?? '')

  const { kind, mode, data, error } = parsePartingResult(raw)

  if (kind === 'empty') {
    return (
      <div style={S.container}>
        <div style={S.empty}>No parting-line result loaded.</div>
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

  const Icon  = mode === 'split' ? Scissors : Layers
  const title = mode === 'split' ? 'Cavity / Core Split' : 'Parting-Line Detection'

  return (
    <div style={S.container}>
      {/* Header */}
      <div style={S.header}>
        <Icon size={14} color="#7dd3fc" />
        <span style={S.title}>{title}</span>
      </div>

      {mode === 'parting_line' && <PartingLineView data={data} />}
      {mode === 'split' && <SplitView data={data} />}

      {/* Honest caveat */}
      {data.honest_caveat && (
        <div style={S.caveat}>
          <AlertTriangle size={11} style={{ display: 'inline', marginRight: 4 }} />
          {data.honest_caveat}
        </div>
      )}
    </div>
  )
}
