// QuantitySchedulePanel.jsx — BIM material quantity take-off schedule panel.
//
// Displays the output of the bim_quantity_schedule and bim_material_cost_rollup
// LLM tools as a tabular schedule grouped by element category and material.
//
// This panel addresses the "Material cost / quantity schedules" AEC use case:
// it shows what ArchiCAD calls an "element schedule" — area / volume / count
// per element type — plus direct material cost when cost data is available.
//
// The panel is pure display — no live API calls.
// All data comes from parsedContent (JSON from a bim_quantity_schedule or
// bim_material_cost_rollup tool call result).
//
// File format (.qty_schedule — JSON produced by a bim_quantity_schedule or
//              bim_material_cost_rollup tool call):
//   { "tool": "bim_quantity_schedule"|"bim_material_cost_rollup", "result": { ... } }
//
// Exported pure helpers (no DOM) for vitest:
//   parseScheduleFile(content)  → { kind, result, hasCost, error? }
//   fmtQty(n, unit)             → formatted quantity string
//   fmtCostUsd(n)               → "$N.NN" string

import { AlertTriangle, Table2 } from 'lucide-react'

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

/**
 * Parse raw quantity schedule file content.
 * Returns { kind: 'ok'|'empty'|'invalid', result, hasCost, error? }
 */
export function parseScheduleFile(content) {
  const raw = typeof content === 'string' ? content : ''
  if (!raw.trim()) return { kind: 'empty', result: null, hasCost: false }
  let doc
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    return { kind: 'invalid', result: null, hasCost: false, error: e.message }
  }
  if (!doc || typeof doc !== 'object') {
    return { kind: 'invalid', result: null, hasCost: false, error: 'Expected JSON object' }
  }
  const result = doc.result || doc
  if (!result || typeof result !== 'object') {
    return { kind: 'invalid', result: null, hasCost: false, error: 'No result field' }
  }
  if (result.ok === false) {
    return { kind: 'invalid', result: null, hasCost: false, error: result.reason || 'Tool returned ok:false' }
  }
  const hasCost = typeof result.total_material_cost_usd === 'number'
  return { kind: 'ok', result, hasCost }
}

/**
 * Format a quantity number with an optional unit label.
 * Returns "—" for nulls.
 */
export function fmtQty(n, unit = '') {
  if (n == null || !Number.isFinite(n)) return '—'
  const s = Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/\.?0+$/, '')
  return unit ? `${s} ${unit}` : s
}

/**
 * Format a number as a USD cost string (2 decimal places).
 * Returns "—" for non-finite values.
 */
export function fmtCostUsd(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return '$' + n.toFixed(2)
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-ink-600"
         data-testid="qty-empty-state">
      <Table2 size={32} className="mb-3 opacity-40" />
      <div className="text-[12px] font-medium">No schedule data</div>
      <div className="text-[10px] mt-1 text-ink-700">
        Run bim_quantity_schedule or bim_material_cost_rollup to populate
      </div>
    </div>
  )
}

function ErrorState({ message }) {
  return (
    <div className="flex items-start gap-2 m-3 rounded bg-red-950/40 border border-red-800 px-3 py-2"
         data-testid="qty-error-state">
      <AlertTriangle size={13} className="text-red-400 shrink-0 mt-0.5" />
      <span className="text-[11px] text-red-300">{message}</span>
    </div>
  )
}

function SummaryRow({ label, value, highlight = false }) {
  return (
    <div className={`flex justify-between items-center py-1 px-2 rounded text-[11px] ${
      highlight ? 'bg-kerf-950/40 border border-kerf-800' : ''
    }`}>
      <span className="text-ink-400">{label}</span>
      <span className={`font-mono font-semibold ${highlight ? 'text-kerf-300' : 'text-ink-200'}`}>
        {value}
      </span>
    </div>
  )
}

function CategoryTable({ categories, hasCost }) {
  if (!categories || categories.length === 0) return null
  return (
    <div data-testid="qty-category-table">
      <div className="text-[9px] font-semibold text-ink-500 uppercase tracking-wider px-1 mb-1 mt-3">
        By Element Type
      </div>
      <div className="overflow-auto rounded border border-ink-800">
        <table className="w-full text-[10px] text-ink-300">
          <thead>
            <tr className="bg-ink-900/80 text-ink-500 text-[9px] uppercase">
              <th className="text-left px-2 py-1.5 font-medium">Category</th>
              <th className="text-right px-2 py-1.5 font-medium">Count</th>
              <th className="text-right px-2 py-1.5 font-medium">Area m²</th>
              <th className="text-right px-2 py-1.5 font-medium">Vol m³</th>
              {hasCost && (
                <th className="text-right px-2 py-1.5 font-medium">Cost</th>
              )}
            </tr>
          </thead>
          <tbody>
            {categories.map((cat, i) => (
              <tr key={cat.category || i}
                  className="border-t border-ink-800/60 hover:bg-ink-900/30"
                  data-testid={`qty-cat-row-${cat.category}`}>
                <td className="px-2 py-1.5 font-medium text-ink-200">{cat.category}</td>
                <td className="px-2 py-1.5 text-right font-mono">{cat.element_count}</td>
                <td className="px-2 py-1.5 text-right font-mono">
                  {fmtQty(cat.total_area_m2)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono">
                  {fmtQty(cat.total_volume_m3)}
                </td>
                {hasCost && (
                  <td className="px-2 py-1.5 text-right font-mono text-emerald-400">
                    {fmtCostUsd(cat.total_material_cost_usd)}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MaterialTable({ materials, hasCost }) {
  if (!materials || materials.length === 0) return null
  return (
    <div data-testid="qty-material-table">
      <div className="text-[9px] font-semibold text-ink-500 uppercase tracking-wider px-1 mb-1 mt-3">
        By Material
      </div>
      <div className="overflow-auto rounded border border-ink-800">
        <table className="w-full text-[10px] text-ink-300">
          <thead>
            <tr className="bg-ink-900/80 text-ink-500 text-[9px] uppercase">
              <th className="text-left px-2 py-1.5 font-medium">Material</th>
              <th className="text-right px-2 py-1.5 font-medium">Count</th>
              <th className="text-right px-2 py-1.5 font-medium">Vol m³</th>
              {hasCost && (
                <>
                  <th className="text-right px-2 py-1.5 font-medium">Mass kg</th>
                  <th className="text-right px-2 py-1.5 font-medium">Cost</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {materials.map((mat, i) => (
              <tr key={mat.material || i}
                  className="border-t border-ink-800/60 hover:bg-ink-900/30"
                  data-testid={`qty-mat-row-${mat.material}`}>
                <td className="px-2 py-1.5 font-medium text-ink-200">{mat.material}</td>
                <td className="px-2 py-1.5 text-right font-mono">{mat.element_count}</td>
                <td className="px-2 py-1.5 text-right font-mono">
                  {fmtQty(mat.total_volume_m3)}
                </td>
                {hasCost && (
                  <>
                    <td className="px-2 py-1.5 text-right font-mono">
                      {fmtQty(mat.total_gross_mass_kg)}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-emerald-400">
                      {fmtCostUsd(mat.total_material_cost_usd)}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function WarningsList({ warnings }) {
  if (!warnings || warnings.length === 0) return null
  return (
    <div className="mt-2 space-y-0.5" data-testid="qty-warnings">
      {warnings.map((w, i) => (
        <div key={i} className="flex items-start gap-1.5 text-[9px] text-amber-400">
          <AlertTriangle size={9} className="shrink-0 mt-0.5" />
          <span>{w}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

/**
 * QuantitySchedulePanel — display a material quantity take-off schedule.
 *
 * Props:
 *   content   — raw JSON string from a bim_quantity_schedule /
 *               bim_material_cost_rollup tool result (or { result: ... } wrapper)
 *   fileName  — optional file name shown in header
 */
export default function QuantitySchedulePanel({ content = '', fileName = '' }) {
  const { kind, result, hasCost, error } = parseScheduleFile(content)

  const displayName = fileName
    ? fileName.replace(/\.(qty_schedule|json)$/, '')
    : 'Quantity Schedule'

  return (
    <div
      className="flex flex-col h-full overflow-hidden bg-ink-950 text-ink-100"
      data-testid="quantity-schedule-panel"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-ink-800 shrink-0">
        <Table2 size={14} className="text-kerf-400 shrink-0" />
        <span className="text-[13px] font-semibold text-ink-100 truncate flex-1">
          {displayName}
        </span>
        {hasCost && (
          <span className="text-[9px] text-emerald-500 font-mono uppercase tracking-wider">
            with cost
          </span>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto px-3 py-2">
        {kind === 'empty' && <EmptyState />}

        {kind === 'invalid' && <ErrorState message={error || 'Invalid schedule data'} />}

        {kind === 'ok' && result && (
          <>
            {/* Top summary */}
            <div className="space-y-0.5 rounded border border-ink-800 px-2 py-1.5 bg-ink-900/30"
                 data-testid="qty-summary">
              {result.by_category && (
                <SummaryRow
                  label="Element types"
                  value={String(result.by_category.length)}
                />
              )}
              {result.element_lines && (
                <SummaryRow
                  label="Total elements"
                  value={String(result.element_lines.length)}
                />
              )}
              {hasCost && (
                <SummaryRow
                  label="Total material cost"
                  value={fmtCostUsd(result.total_material_cost_usd)}
                  highlight
                />
              )}
            </div>

            <CategoryTable
              categories={result.by_category}
              hasCost={hasCost}
            />

            <MaterialTable
              materials={result.by_material}
              hasCost={hasCost}
            />

            <WarningsList warnings={result.warnings} />
          </>
        )}
      </div>
    </div>
  )
}
