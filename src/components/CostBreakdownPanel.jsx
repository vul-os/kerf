// CostBreakdownPanel — Manufacturing should-cost breakdown viewer.
//
// Renders the output of costing_cnc, costing_casting, costing_injection,
// costing_sheet_metal, costing_printing, costing_assembly, costing_rollup,
// costing_batch_curve, costing_learning_curve, and costing_make_vs_buy LLM tools.
//
// File format (.cost_report — JSON produced by a costing_* tool call):
//   { "tool": "costing_cnc"|"costing_rollup"|..., "result": { ...tool output } }
//
// Pure display — no live API calls. All data comes from parsedContent.
//
// References
// ----------
// Boothroyd, Dewhurst & Knight, "Product Design for Manufacture and Assembly"
// Wright, T.P. (1936), "Factors Affecting the Cost of Airplanes"
//
// Exported pure helpers (no DOM) for vitest:
//   parseCostFile(content)   → { kind, tool, result, error? }
//   fmtCurrency(n)           → "$N.NN" string
//   pctBar(n, total)         → 0–100 percentage number
//   detectCostTool(tool, r)  → string

import { AlertTriangle, DollarSign } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw cost file content.
 * Returns { kind: 'ok'|'empty'|'invalid', tool, result, error? }
 */
export function parseCostFile(content) {
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
 * Format a number as a currency string (2 decimal places).
 * Returns "—" for non-finite values.
 */
export function fmtCurrency(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return '$' + n.toFixed(2)
}

/**
 * Compute percentage of n relative to total. Returns 0 for edge cases.
 */
export function pctBar(n, total) {
  if (!n || !total || total === 0) return 0
  return Math.min(100, Math.max(0, (n / total) * 100))
}

/**
 * Detect which costing tool produced the result.
 */
export function detectCostTool(tool, r) {
  if (tool) {
    if (tool.includes('batch_curve'))    return 'batch_curve'
    if (tool.includes('learning_curve')) return 'learning_curve'
    if (tool.includes('make_vs_buy'))    return 'make_vs_buy'
    if (tool.includes('rollup'))         return 'rollup'
    if (tool.includes('assembly'))       return 'assembly'
    if (tool.includes('printing'))       return 'printing'
    if (tool.includes('sheet_metal'))    return 'sheet_metal'
    if (tool.includes('injection'))      return 'injection'
    if (tool.includes('casting'))        return 'casting'
    if (tool.includes('cnc'))            return 'cnc'
  }
  if (!r) return 'unknown'
  if ('breakpoints' in r)          return 'batch_curve'
  if ('unit_cost_at_n' in r)       return 'learning_curve'
  if ('break_even_volume' in r)    return 'make_vs_buy'
  if ('unit_price' in r)           return 'rollup'
  if ('operations' in r)           return 'assembly'
  if ('machine_cost' in r && 'cycle_time_hr' in r) return 'cnc'
  if ('material_cost_per_kg' in r) return 'casting'
  return 'unknown'
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Cost metric card */
function CostCard({ label, value, highlight, mono }) {
  return (
    <div style={styles.metricCard}>
      <div style={styles.metricLabel}>{label}</div>
      <div style={{ ...styles.metricValue, ...(mono ? styles.mono : {}), color: highlight || styles.metricValue.color }}>
        {typeof value === 'number' ? fmtCurrency(value) : (value ?? '—')}
      </div>
    </div>
  )
}

/** Horizontal percentage bar for cost breakdown visualisation */
function PercentBar({ label, value, total, color = '#818cf8' }) {
  const pct = pctBar(value, total)
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
        <span style={{ fontSize: 11, color: '#9ca3af' }}>{label}</span>
        <span style={{ fontSize: 11, color: '#d1d5db', fontFamily: 'monospace' }}>
          {fmtCurrency(value)} ({pct.toFixed(0)}%)
        </span>
      </div>
      <div style={{ background: '#1f2937', borderRadius: 3, height: 6, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, background: color, height: '100%', borderRadius: 3, transition: 'width 0.2s' }} />
      </div>
    </div>
  )
}

function WarningsBox({ warnings }) {
  if (!warnings || warnings.length === 0) return null
  return (
    <div style={styles.warningBox}>
      <AlertTriangle size={11} style={{ flexShrink: 0, marginRight: 5, color: '#fbbf24' }} />
      <div>{warnings.join(' · ')}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool-specific result renderers
// ---------------------------------------------------------------------------

/** CNC Machining breakdown */
function CNCResult({ r }) {
  const total = r.unit_cost || r.total || 0
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={styles.metricsGrid}>
        <CostCard label="Unit cost" value={total} highlight="#34d399" />
        {r.material  != null && <CostCard label="Material"  value={r.material}  mono />}
        {r.cycle_cost != null && <CostCard label="Cycle"    value={r.cycle_cost} mono />}
        {r.setup_cost_per_unit != null && <CostCard label="Setup/unit" value={r.setup_cost_per_unit} mono />}
        {r.tooling_amortisation != null && <CostCard label="Tooling"   value={r.tooling_amortisation} mono />}
        {r.overhead != null && <CostCard label="Overhead" value={r.overhead} mono />}
      </div>
      {total > 0 && (
        <div style={{ marginTop: 4 }}>
          {r.material != null && <PercentBar label="Material"  value={r.material} total={total} color="#818cf8" />}
          {r.cycle_cost != null && <PercentBar label="Cycle"   value={r.cycle_cost} total={total} color="#34d399" />}
          {r.overhead != null && <PercentBar label="Overhead"  value={r.overhead} total={total} color="#f472b6" />}
        </div>
      )}
      <WarningsBox warnings={r.warnings} />
    </div>
  )
}

/** Rollup waterfall breakdown */
function RollupResult({ r }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={styles.metricsGrid}>
        <CostCard label="Unit price"    value={r.unit_price}    highlight="#34d399" />
        <CostCard label="Full cost"     value={r.full_cost}     mono />
        <CostCard label="Mfg cost"      value={r.manufacturing_cost} mono />
        <CostCard label="Direct cost"   value={r.direct_cost}   mono />
        <CostCard label="Gross margin"  value={r.gross_margin_rate != null ? `${(r.gross_margin_rate * 100).toFixed(0)}%` : undefined} />
      </div>
      {r.unit_price > 0 && (
        <div style={{ marginTop: 4 }}>
          {r.direct_material != null && <PercentBar label="Material"  value={r.direct_material} total={r.unit_price} color="#818cf8" />}
          {r.direct_labour  != null && <PercentBar label="Labour"    value={r.direct_labour}  total={r.unit_price} color="#34d399" />}
          {r.machine_cost   != null && <PercentBar label="Machine"   value={r.machine_cost}   total={r.unit_price} color="#f472b6" />}
          {r.overhead       != null && <PercentBar label="Overhead"  value={r.overhead}       total={r.unit_price} color="#fbbf24" />}
        </div>
      )}
      <WarningsBox warnings={r.warnings} />
    </div>
  )
}

/** Generic process result (casting / injection / sheet metal / printing / assembly) */
function GenericProcessResult({ r }) {
  const unit = r.unit_cost || r.unit_cost_per_good_part || r.total_labour_cost || r.total || 0
  const breakdown = Object.entries(r)
    .filter(([k, v]) => typeof v === 'number' && k !== 'ok' && !k.includes('rate') && !k.includes('fraction') && !k.includes('pct'))
    .sort((a, b) => b[1] - a[1])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={styles.metricsGrid}>
        <CostCard label="Unit cost" value={unit} highlight="#34d399" />
        {breakdown.filter(([k]) => k !== 'unit_cost' && k !== 'unit_cost_per_good_part' && k !== 'total' && k !== 'total_labour_cost').slice(0, 5).map(([k, v]) => (
          <CostCard key={k} label={k.replace(/_/g, ' ')} value={v} mono />
        ))}
      </div>
      <WarningsBox warnings={r.warnings} />
    </div>
  )
}

/** Batch curve: unit cost vs. batch size */
function BatchCurveResult({ r }) {
  const pts = r.breakpoints || []
  if (pts.length === 0) return <div style={styles.empty}>No batch curve data.</div>

  const maxCost = Math.max(...pts.map((p) => p.unit_cost || 0)) || 1

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={styles.metricsGrid}>
        {r.min_unit_cost != null && <CostCard label="Min unit cost" value={r.min_unit_cost} highlight="#34d399" />}
        {r.max_unit_cost != null && <CostCard label="Max unit cost" value={r.max_unit_cost} mono />}
      </div>
      <div style={{ marginTop: 4 }}>
        <div style={styles.metricLabel}>Unit cost by batch size</div>
        {pts.map((p, i) => (
          <PercentBar
            key={i}
            label={`n = ${p.batch_size}`}
            value={p.unit_cost}
            total={maxCost}
            color={i === 0 ? '#f87171' : i === pts.length - 1 ? '#34d399' : '#818cf8'}
          />
        ))}
      </div>
    </div>
  )
}

/** Make vs. buy comparison */
function MakeVsBuyResult({ r }) {
  const preferred = r.preferred
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {preferred && (
        <div style={{ ...styles.badge,
          background: preferred === 'buy' ? '#1e3a5f44' : '#14532d44',
          color: preferred === 'buy' ? '#38bdf8' : '#34d399',
          borderColor: preferred === 'buy' ? '#1e40af66' : '#15803d66',
          display: 'inline-flex', alignItems: 'center', gap: 4, padding: '3px 12px', fontSize: 12,
        }}>
          Preferred: <strong style={{ marginLeft: 3, textTransform: 'uppercase' }}>{preferred}</strong>
        </div>
      )}
      <div style={styles.metricsGrid}>
        {r.make_annual_total  != null && <CostCard label="Make (annual)"  value={r.make_annual_total} mono />}
        {r.buy_annual_total   != null && <CostCard label="Buy (annual)"   value={r.buy_annual_total} mono />}
        {r.break_even_volume  != null && <CostCard label="Break-even vol" value={`${r.break_even_volume} units`} />}
        {r.make_unit_cost     != null && <CostCard label="Make unit cost" value={r.make_unit_cost} mono />}
        {r.buy_unit_price     != null && <CostCard label="Buy unit price" value={r.buy_unit_price} mono />}
        {r.annual_volume      != null && <CostCard label="Annual volume"  value={`${r.annual_volume} units`} />}
      </div>
    </div>
  )
}

/** Learning curve */
function LearningCurveResult({ r }) {
  return (
    <div style={styles.metricsGrid}>
      <CostCard label="Unit cost at n" value={r.unit_cost_at_n}    highlight="#34d399" />
      <CostCard label="T₁ (first unit)" value={r.t1}              mono />
      <CostCard label="Volume (n)"     value={`${r.cumulative_volume} units`} />
      <CostCard label="Learning rate"  value={r.learning_rate != null ? `${(r.learning_rate * 100).toFixed(0)}%` : undefined} />
      <CostCard label="b (exponent)"   value={r.b?.toFixed(4)}     mono />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const TOOL_LABELS = {
  cnc:           'CNC Machining Should-Cost',
  casting:       'Casting Should-Cost',
  injection:     'Injection Moulding Should-Cost',
  sheet_metal:   'Sheet Metal Should-Cost',
  printing:      '3D Printing Should-Cost',
  assembly:      'Assembly Labour Cost',
  rollup:        'Manufacturing Cost Roll-Up',
  batch_curve:   'Batch-Size Cost Curve',
  learning_curve:'Wright Learning Curve',
  make_vs_buy:   'Make vs. Buy Analysis',
  unknown:       'Cost Analysis',
}

/**
 * CostBreakdownPanel
 *
 * Props:
 *   parsedContent — already-parsed JSON of a `.cost_report` file, or null.
 *   rawContent    — raw string content (used when parsedContent is absent).
 *   fileName      — display name.
 */
export default function CostBreakdownPanel({ parsedContent, rawContent, fileName }) {
  const source = parsedContent ?? (rawContent ? (() => {
    try { return JSON.parse(rawContent) } catch { return null }
  })() : null)

  const parsed = source ? parseCostFile(JSON.stringify(source)) : parseCostFile(rawContent || '')

  if (parsed.kind === 'empty') {
    return (
      <div style={styles.root}>
        <Header fileName={fileName} title="Cost Analysis" />
        <div style={styles.empty}>No cost data yet. Run a <code style={{ color: '#a78bfa' }}>costing_*</code> tool to generate a cost estimate.</div>
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div style={styles.root}>
        <Header fileName={fileName} title="Cost Analysis" />
        <div style={styles.errorBox}>
          <AlertTriangle size={13} style={{ flexShrink: 0 }} />
          <span style={{ marginLeft: 6 }}>{parsed.error || 'Invalid cost file'}</span>
        </div>
      </div>
    )
  }

  const { tool, result } = parsed
  const toolType = detectCostTool(tool, result)
  const title = TOOL_LABELS[toolType] || 'Cost Analysis'

  return (
    <div style={styles.root}>
      <Header fileName={fileName} title={title} />
      <div style={{ padding: '0 2px' }}>
        {toolType === 'cnc'           && <CNCResult r={result} />}
        {toolType === 'rollup'        && <RollupResult r={result} />}
        {toolType === 'batch_curve'   && <BatchCurveResult r={result} />}
        {toolType === 'learning_curve'&& <LearningCurveResult r={result} />}
        {toolType === 'make_vs_buy'   && <MakeVsBuyResult r={result} />}
        {(toolType === 'casting' || toolType === 'injection' ||
          toolType === 'sheet_metal' || toolType === 'printing' ||
          toolType === 'assembly' || toolType === 'unknown') && <GenericProcessResult r={result} />}
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
      <DollarSign size={14} style={{ color: '#34d399', flexShrink: 0 }} />
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
    gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
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
  badge: {
    border: '1px solid',
    borderRadius: 9999,
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.03em',
  },
  warningBox: {
    display: 'flex',
    alignItems: 'flex-start',
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
