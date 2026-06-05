// ApparelGradingPanel — display panel for apparel_grade_bodice /
// apparel_apply_grading / textiles_pattern_grade tool results.
//
// Renders a size-run table with bust girth, bounding-box dimensions,
// area, and grade deltas.  Colour-codes each row by size.
//
// Props
// ─────
//   result      {Object|string|null}  — parsed output from apparel grading tool
//   className   {string}              — extra CSS classes on root
//
// Supports two result shapes:
//   apparel_grade_bodice  → { base_size, sizes: { S: {bust_girth_cm,...}, ... } }
//   textiles_pattern_grade → { ok, block, base_size, spec, sizes: {...} }
//   apparel_apply_grading  → { block, from_size, to_size, ..., from_bbox_cm, to_bbox_cm }
//
// Exported pure helpers for vitest:
//   parseGradingResult(raw)            → { kind, type, data, error? }
//   formatGradeDelta(dx_mm, dy_mm)     → "+W×+H mm" string
//   sizeColor(size)                    → Tailwind colour class name

import { useMemo } from 'react'
import { Ruler, TrendingUp } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw grading tool result into a display-ready object.
 * Returns { kind: 'ok'|'empty'|'invalid', type, data, error? }
 *
 * type is 'size_run' (grade_bodice / pattern_grade) or 'single' (apply_grading).
 */
export function parseGradingResult(raw) {
  if (raw == null) return { kind: 'empty' }
  const obj = typeof raw === 'string'
    ? (() => { try { return JSON.parse(raw) } catch { return null } })()
    : raw
  if (!obj || typeof obj !== 'object') return { kind: 'invalid', error: 'Expected JSON object' }
  if (obj.error) return { kind: 'invalid', error: obj.error }

  // apparel_apply_grading single-grade result
  if ('from_size' in obj && 'to_size' in obj && 'from_bbox_cm' in obj) {
    return {
      kind: 'ok',
      type: 'single',
      data: {
        block:        obj.block,
        from_size:    obj.from_size,
        to_size:      obj.to_size,
        spec:         obj.spec,
        grade_dx_mm:  obj.grade_dx_mm ?? 0,
        grade_dy_mm:  obj.grade_dy_mm ?? 0,
        from_bbox_cm: obj.from_bbox_cm,
        to_bbox_cm:   obj.to_bbox_cm,
        from_area_cm2:obj.from_area_cm2,
        to_area_cm2:  obj.to_area_cm2,
      },
    }
  }

  // apparel_grade_bodice / textiles_pattern_grade size-run
  if (obj.sizes && typeof obj.sizes === 'object') {
    return {
      kind: 'ok',
      type: 'size_run',
      data: {
        block:     obj.block || null,
        base_size: obj.base_size || null,
        spec:      obj.spec || null,
        sizes:     obj.sizes,
      },
    }
  }

  return { kind: 'invalid', error: 'Unrecognised grading result shape' }
}

/**
 * Format grade deltas as a compact string.
 */
export function formatGradeDelta(dx_mm, dy_mm) {
  if (dx_mm == null && dy_mm == null) return '—'
  const fmt = (n) => {
    if (n == null || !Number.isFinite(n)) return '—'
    const sign = n >= 0 ? '+' : '−'
    return `${sign}${Math.abs(n).toFixed(1)}`
  }
  return `${fmt(dx_mm)} × ${fmt(dy_mm)} mm`
}

/**
 * Return a Tailwind text-colour class for a size label.
 * Maps standard alpha sizes to a spectrum.
 */
export function sizeColor(size) {
  const map = {
    XS: 'text-sky-400',
    S:  'text-teal-400',
    M:  'text-emerald-400',
    L:  'text-yellow-400',
    XL: 'text-orange-400',
    XXL:'text-red-400',
  }
  return map[String(size).toUpperCase()] ?? 'text-ink-300'
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SizeRunTable({ sizes, baseSize }) {
  const rows = Object.entries(sizes)
  if (rows.length === 0) return <p className="text-xs text-ink-500 mt-2">No sizes found.</p>
  return (
    <div className="overflow-x-auto mt-2" data-testid="grading-size-run-table">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-ink-800">
            <th className="py-1.5 pr-3 text-left font-mono text-[10px] uppercase tracking-wider text-ink-500">Size</th>
            {rows[0]?.[1]?.bust_girth_cm !== undefined && (
              <th className="py-1.5 pr-3 text-right font-mono text-[10px] uppercase tracking-wider text-ink-500">Bust (cm)</th>
            )}
            <th className="py-1.5 pr-3 text-right font-mono text-[10px] uppercase tracking-wider text-ink-500">W (cm)</th>
            <th className="py-1.5 pr-3 text-right font-mono text-[10px] uppercase tracking-wider text-ink-500">H (cm)</th>
            <th className="py-1.5 pr-3 text-right font-mono text-[10px] uppercase tracking-wider text-ink-500">Area (cm²)</th>
            <th className="py-1.5 text-right font-mono text-[10px] uppercase tracking-wider text-ink-500">Grade</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([size, s]) => (
            <tr
              key={size}
              className={`border-b border-ink-800/40 ${size === baseSize ? 'bg-cyan-edge/5' : ''}`}
            >
              <td className={`py-1.5 pr-3 font-semibold ${sizeColor(size)}`}>
                {size}
                {size === baseSize && (
                  <span className="ml-1 text-[9px] font-mono text-cyan-edge opacity-70">base</span>
                )}
              </td>
              {s.bust_girth_cm !== undefined && (
                <td className="py-1.5 pr-3 text-right font-mono text-ink-200">
                  {Number.isFinite(s.bust_girth_cm) ? s.bust_girth_cm.toFixed(1) : '—'}
                </td>
              )}
              <td className="py-1.5 pr-3 text-right font-mono text-ink-300">
                {Number.isFinite(s.width_cm) ? s.width_cm.toFixed(1) : '—'}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono text-ink-300">
                {Number.isFinite(s.height_cm) ? s.height_cm.toFixed(1) : '—'}
              </td>
              <td className="py-1.5 pr-3 text-right font-mono text-ink-300">
                {Number.isFinite(s.area_cm2) ? s.area_cm2.toFixed(0) : '—'}
              </td>
              <td className="py-1.5 text-right font-mono text-ink-400 text-[10px]">
                {formatGradeDelta(s.grade_dx_mm, s.grade_dy_mm)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SingleGradeView({ data }) {
  const { block, from_size, to_size, spec, grade_dx_mm, grade_dy_mm,
          from_bbox_cm, to_bbox_cm, from_area_cm2, to_area_cm2 } = data
  return (
    <div data-testid="grading-single-view">
      <div className="flex flex-wrap gap-2 text-xs mb-3">
        {block && (
          <span className="rounded-md border border-ink-800 bg-ink-900/60 px-2 py-0.5 font-mono text-ink-300">
            {block}
          </span>
        )}
        {spec && (
          <span className="rounded-md border border-ink-800 bg-ink-900/60 px-2 py-0.5 font-mono text-ink-400">
            {spec}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg border border-ink-800 bg-ink-950/50 px-3 py-2">
          <p className={`font-semibold ${sizeColor(from_size)}`}>{from_size}</p>
          <p className="font-mono text-ink-400 mt-0.5">
            {from_bbox_cm?.width?.toFixed(1)} × {from_bbox_cm?.height?.toFixed(1)} cm
          </p>
          {from_area_cm2 != null && (
            <p className="font-mono text-ink-500 text-[10px]">{from_area_cm2.toFixed(0)} cm²</p>
          )}
        </div>
        <div className="rounded-lg border border-cyan-edge/20 bg-cyan-edge/5 px-3 py-2">
          <p className={`font-semibold ${sizeColor(to_size)}`}>{to_size}</p>
          <p className="font-mono text-ink-300 mt-0.5">
            {to_bbox_cm?.width?.toFixed(1)} × {to_bbox_cm?.height?.toFixed(1)} cm
          </p>
          {to_area_cm2 != null && (
            <p className="font-mono text-ink-400 text-[10px]">{to_area_cm2.toFixed(0)} cm²</p>
          )}
        </div>
      </div>

      <div className="mt-2 flex items-center gap-2 text-xs text-ink-400">
        <span className="font-mono">Grade delta:</span>
        <span className="font-mono text-ink-200">{formatGradeDelta(grade_dx_mm, grade_dy_mm)}</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * ApparelGradingPanel — renders pattern grading results.
 *
 * @param {Object} props
 * @param {Object|string|null} props.result  — grading tool output
 * @param {string} [props.className]
 */
export default function ApparelGradingPanel({ result = null, content, className = '' }) {
  // content prop (from panelRegistry) is a JSON string; parse and use as result
  const effectiveResult = useMemo(() => {
    if (content != null) {
      try { return { ...JSON.parse(content), ...((result != null && typeof result === 'object') ? result : {}) } } catch { return result }
    }
    return result
  }, [result, content])
  const parsed = useMemo(() => parseGradingResult(effectiveResult), [effectiveResult])

  if (parsed.kind === 'empty') {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 py-10 text-ink-500 ${className}`}
        data-testid="grading-panel-empty"
      >
        <Ruler size={28} className="opacity-40" />
        <p className="text-sm">No grading result yet.</p>
        <p className="text-xs opacity-60">
          Ask Kerf to grade a bodice, sleeve, or trouser block across sizes.
        </p>
      </div>
    )
  }

  if (parsed.kind === 'invalid') {
    return (
      <div
        className={`rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400 ${className}`}
        data-testid="grading-panel-error"
      >
        Error: {parsed.error}
      </div>
    )
  }

  const { type, data } = parsed

  return (
    <div className={`flex flex-col gap-0 ${className}`} data-testid="apparel-grading-panel">
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <span className="grid place-items-center w-5 h-5 rounded bg-cyan-edge/10 border border-cyan-edge/20 text-cyan-edge">
          <TrendingUp size={11} />
        </span>
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink-400">
          Pattern grading
        </span>
        {data.block && (
          <span
            className="ml-auto rounded-md border border-ink-700 bg-ink-900/60 px-2 py-0.5 font-mono text-[11px] text-ink-300"
            data-testid="grading-block-label"
          >
            {data.block}
          </span>
        )}
      </div>

      {type === 'size_run'
        ? <SizeRunTable sizes={data.sizes} baseSize={data.base_size} />
        : <SingleGradeView data={data} />
      }
    </div>
  )
}
