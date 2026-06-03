/**
 * ConfiguratorPanel.jsx — PLM Variant BOM Configurator.
 *
 * Exposes the `plm_resolve_variant_bom` backend tool via a UI that lets the
 * user configure a product variant (region / color / market_segment / options)
 * and see which BOM entries are active for that variant.
 *
 * Tool spec (POST /api/llm-tools/plm_resolve_variant_bom):
 *   {
 *     base_bom:       [[part_number, qty], ...],
 *     variant_rules:  [{part_number, variant_attribute_key,
 *                       variant_attribute_value, condition}, ...],
 *     variant:        {variant_id, attributes: {key: value, ...}},
 *   }
 *
 * Response rows: {part_number, qty, included, reason}
 */

import { useState, useCallback } from 'react'
import { Plus, Trash2, Layers, RefreshCw, CheckCircle, XCircle } from 'lucide-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ATTR_KEYS = ['region', 'color', 'market_segment', 'options', 'grade', 'language']

const ATTR_VALUES = {
  region:         ['GLOBAL', 'EU', 'US', 'APAC', 'LATAM', 'MEA'],
  color:          ['black', 'white', 'silver', 'red', 'blue', 'green'],
  market_segment: ['consumer', 'enterprise', 'oem', 'aftermarket'],
  options:        ['standard', 'premium', 'sport', 'eco'],
  grade:          ['A', 'B', 'C'],
  language:       ['en', 'de', 'fr', 'zh', 'ja'],
}

const PLACEHOLDER_BOM = [
  ['P-001', 1],
  ['P-002', 2],
  ['P-003', 1],
  ['P-004', 4],
  ['P-005', 1],
]

const PLACEHOLDER_RULES = [
  { id: 1, part_number: 'P-002', variant_attribute_key: 'color',   variant_attribute_value: 'red',     condition: 'exclude' },
  { id: 2, part_number: 'P-004', variant_attribute_key: 'region',  variant_attribute_value: 'EU',      condition: 'include' },
  { id: 3, part_number: 'P-005', variant_attribute_key: 'options', variant_attribute_value: 'premium', condition: 'include' },
]

let _nextRuleId = PLACEHOLDER_RULES.length + 1

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function AttrRow({ row, onChange, onDelete }) {
  const vals = ATTR_VALUES[row.key] ?? []
  return (
    <div className="flex items-center gap-2">
      <select
        value={row.key}
        onChange={(e) => onChange({ key: e.target.value, value: (ATTR_VALUES[e.target.value] ?? [])[0] ?? '' })}
        className="flex-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
        aria-label="Attribute key"
      >
        {ATTR_KEYS.map((k) => (
          <option key={k} value={k}>{k}</option>
        ))}
      </select>
      <select
        value={row.value}
        onChange={(e) => onChange({ value: e.target.value })}
        className="flex-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
        aria-label="Attribute value"
      >
        {vals.map((v) => (
          <option key={v} value={v}>{v}</option>
        ))}
      </select>
      <button
        onClick={onDelete}
        className="rounded p-1 text-gray-400 hover:text-red-500 focus:outline-none focus:ring-1 focus:ring-red-400"
        aria-label="Remove attribute"
        title="Remove"
      >
        <Trash2 size={13} />
      </button>
    </div>
  )
}


function RuleRow({ rule, onChange, onDelete }) {
  return (
    <tr className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50">
      <td className="px-2 py-1.5">
        <input
          type="text"
          value={rule.part_number}
          onChange={(e) => onChange({ part_number: e.target.value })}
          placeholder="P-001"
          className="w-full rounded border border-gray-300 dark:border-gray-600 bg-transparent px-2 py-0.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label="Part number"
        />
      </td>
      <td className="px-2 py-1.5">
        <select
          value={rule.variant_attribute_key}
          onChange={(e) => onChange({ variant_attribute_key: e.target.value })}
          className="w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-2 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label="Attribute key"
        >
          {ATTR_KEYS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </td>
      <td className="px-2 py-1.5">
        <input
          type="text"
          value={rule.variant_attribute_value}
          onChange={(e) => onChange({ variant_attribute_value: e.target.value })}
          placeholder="red"
          className="w-full rounded border border-gray-300 dark:border-gray-600 bg-transparent px-2 py-0.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label="Attribute value"
        />
      </td>
      <td className="px-2 py-1.5">
        <select
          value={rule.condition}
          onChange={(e) => onChange({ condition: e.target.value })}
          className="w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-2 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label="Condition"
        >
          <option value="include">include</option>
          <option value="exclude">exclude</option>
        </select>
      </td>
      <td className="px-2 py-1.5 text-center">
        <button
          onClick={onDelete}
          className="rounded p-1 text-gray-400 hover:text-red-500 focus:outline-none focus:ring-1 focus:ring-red-400"
          aria-label="Remove rule"
          title="Remove rule"
        >
          <Trash2 size={13} />
        </button>
      </td>
    </tr>
  )
}


function ResultTable({ rows }) {
  const total    = rows.length
  const included = rows.filter((r) => r.included).length
  const excluded = total - included

  return (
    <div className="flex flex-col gap-3">
      {/* Stats */}
      <div className="flex flex-wrap gap-3">
        {[
          { label: 'Total',    value: total,    color: 'text-gray-700 dark:text-gray-300' },
          { label: 'Included', value: included, color: 'text-green-700 dark:text-green-400' },
          { label: 'Excluded', value: excluded, color: 'text-red-600 dark:text-red-400' },
        ].map(({ label, value, color }) => (
          <div key={label} className="flex items-center gap-1.5 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-1.5">
            <span className={`text-lg font-bold tabular-nums ${color}`}>{value}</span>
            <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
              <th className="px-3 py-2 font-medium">Part Number</th>
              <th className="px-3 py-2 font-medium">Qty</th>
              <th className="px-3 py-2 font-medium">Included?</th>
              <th className="px-3 py-2 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={i}
                className={`border-b border-gray-100 dark:border-gray-800 ${
                  row.included
                    ? 'hover:bg-green-50 dark:hover:bg-green-950/20'
                    : 'hover:bg-red-50 dark:hover:bg-red-950/20 opacity-60'
                }`}
              >
                <td className="px-3 py-1.5 font-mono">{row.part_number}</td>
                <td className="px-3 py-1.5 tabular-nums">{row.qty ?? 1}</td>
                <td className="px-3 py-1.5">
                  {row.included
                    ? <span className="flex items-center gap-1 text-green-700 dark:text-green-400"><CheckCircle size={12} /> Yes</span>
                    : <span className="flex items-center gap-1 text-red-600 dark:text-red-400"><XCircle size={12} /> No</span>
                  }
                </td>
                <td className="px-3 py-1.5 text-gray-500 dark:text-gray-400">{row.reason ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ConfiguratorPanel
// ---------------------------------------------------------------------------

/**
 * ConfiguratorPanel — PLM variant BOM configurator.
 *
 * Props
 * -----
 * parentPn     {string}    Pre-filled parent part number.
 * className    {string}    Extra Tailwind classes.
 */
export default function ConfiguratorPanel({ parentPn: initialPn = '', className = '' }) {
  const [parentPn,    setParentPn]    = useState(initialPn || 'ASSY-001')
  const [variantId,   setVariantId]   = useState('MY_VARIANT')
  const [attrRows,    setAttrRows]    = useState([
    { id: 1, key: 'region', value: 'EU' },
    { id: 2, key: 'color',  value: 'red' },
  ])
  const [nextAttrId,  setNextAttrId]  = useState(3)
  const [rules,       setRules]       = useState(PLACEHOLDER_RULES)
  const [resultRows,  setResultRows]  = useState(null)
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState(null)

  // ── Attr handlers ─────────────────────────────────────────────────────────

  const handleAddAttr = useCallback(() => {
    setAttrRows((prev) => [...prev, { id: nextAttrId, key: ATTR_KEYS[0], value: (ATTR_VALUES[ATTR_KEYS[0]] ?? [])[0] ?? '' }])
    setNextAttrId((n) => n + 1)
  }, [nextAttrId])

  const handleAttrChange = useCallback((id, delta) => {
    setAttrRows((prev) => prev.map((r) => r.id === id ? { ...r, ...delta } : r))
  }, [])

  const handleAttrDelete = useCallback((id) => {
    setAttrRows((prev) => prev.filter((r) => r.id !== id))
  }, [])

  // ── Rule handlers ─────────────────────────────────────────────────────────

  const handleAddRule = useCallback(() => {
    setRules((prev) => [
      ...prev,
      { id: _nextRuleId++, part_number: '', variant_attribute_key: 'color', variant_attribute_value: '', condition: 'exclude' },
    ])
  }, [])

  const handleRuleChange = useCallback((id, delta) => {
    setRules((prev) => prev.map((r) => r.id === id ? { ...r, ...delta } : r))
  }, [])

  const handleRuleDelete = useCallback((id) => {
    setRules((prev) => prev.filter((r) => r.id !== id))
  }, [])

  // ── Resolve ───────────────────────────────────────────────────────────────

  const handleResolve = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResultRows(null)

    const attributes = Object.fromEntries(attrRows.map((r) => [r.key, r.value]))
    const payload = {
      base_bom:      PLACEHOLDER_BOM,
      variant_rules: rules.map(({ part_number, variant_attribute_key, variant_attribute_value, condition }) => ({
        part_number,
        variant_attribute_key,
        variant_attribute_value,
        condition,
      })),
      variant: {
        variant_id: variantId || 'UNNAMED',
        attributes,
      },
    }

    try {
      const res = await fetch('/api/llm-tools/plm_resolve_variant_bom', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      // Backend returns {ok, resolved_bom: [{part_number, qty, included, reason}]}
      const resolved = data.resolved_bom ?? data.result?.resolved_bom ?? []
      if (resolved.length === 0 && data.ok !== true) {
        // Fallback: demo mode — simulate response from rules + BOM
        const demoRows = PLACEHOLDER_BOM.map(([pn, qty]) => {
          const matchedRule = payload.variant_rules.find(
            (rule) =>
              rule.part_number === pn &&
              attributes[rule.variant_attribute_key] === rule.variant_attribute_value
          )
          const included = matchedRule ? matchedRule.condition === 'include' : true
          const reason = matchedRule
            ? `Rule: ${matchedRule.variant_attribute_key}=${matchedRule.variant_attribute_value} → ${matchedRule.condition}`
            : 'Default: included (no matching rule)'
          return { part_number: pn, qty, included, reason }
        })
        setResultRows(demoRows)
      } else {
        setResultRows(resolved)
      }
    } catch {
      // Demo / offline fallback
      const demoRows = PLACEHOLDER_BOM.map(([pn, qty]) => {
        const matchedRule = payload.variant_rules.find(
          (rule) =>
            rule.part_number === pn &&
            attributes[rule.variant_attribute_key] === rule.variant_attribute_value
        )
        const included = matchedRule ? matchedRule.condition === 'include' : true
        const reason = matchedRule
          ? `Rule: ${matchedRule.variant_attribute_key}=${matchedRule.variant_attribute_value} → ${matchedRule.condition}`
          : 'Default: included (no matching rule)'
        return { part_number: pn, qty, included, reason }
      })
      setResultRows(demoRows)
    } finally {
      setLoading(false)
    }
  }, [attrRows, rules, variantId])

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={`flex flex-col gap-6 ${className}`}>
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          PLM Variant Configurator
        </h2>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
          Configure product variant attributes and resolve the active BOM (PTC Windchill / ISO 10303-44 §6).
        </p>
      </div>

      {/* Parent PN + Variant ID */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
            Parent assembly (PN)
          </label>
          <input
            type="text"
            value={parentPn}
            onChange={(e) => setParentPn(e.target.value)}
            placeholder="ASSY-001"
            className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Parent assembly part number"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700 dark:text-gray-300">
            Variant ID
          </label>
          <input
            type="text"
            value={variantId}
            onChange={(e) => setVariantId(e.target.value)}
            placeholder="RED_EU"
            className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Variant identifier"
          />
        </div>
      </div>

      {/* Variant attribute editor */}
      <section aria-labelledby="attrs-label">
        <div className="flex items-center justify-between mb-2">
          <label id="attrs-label" className="text-xs font-medium text-gray-700 dark:text-gray-300">
            Variant attributes ({attrRows.length})
          </label>
          <button
            onClick={handleAddAttr}
            className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/30 focus:outline-none focus:ring-1 focus:ring-blue-500"
            aria-label="Add attribute"
          >
            <Plus size={12} /> Add
          </button>
        </div>
        <div className="flex flex-col gap-2">
          {attrRows.length === 0 ? (
            <p className="text-xs text-gray-400 dark:text-gray-500 italic">
              No attributes — click &ldquo;Add&rdquo; to define variant dimensions.
            </p>
          ) : (
            attrRows.map((row) => (
              <AttrRow
                key={row.id}
                row={row}
                onChange={(delta) => handleAttrChange(row.id, delta)}
                onDelete={() => handleAttrDelete(row.id)}
              />
            ))
          )}
        </div>
      </section>

      {/* Variant rules table */}
      <section aria-labelledby="rules-label">
        <div className="flex items-center justify-between mb-2">
          <label id="rules-label" className="text-xs font-medium text-gray-700 dark:text-gray-300">
            Variant rules ({rules.length})
          </label>
          <button
            onClick={handleAddRule}
            className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/30 focus:outline-none focus:ring-1 focus:ring-blue-500"
            aria-label="Add variant rule"
          >
            <Plus size={12} /> Add rule
          </button>
        </div>
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="w-full min-w-[540px] text-left text-xs">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
                <th className="px-2 py-2 font-medium">Part No.</th>
                <th className="px-2 py-2 font-medium">Attr key</th>
                <th className="px-2 py-2 font-medium">Attr value</th>
                <th className="px-2 py-2 font-medium">Condition</th>
                <th className="px-2 py-2 w-8" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rules.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-gray-400 dark:text-gray-500 italic">
                    No rules — all parts will be included by default.
                  </td>
                </tr>
              ) : (
                rules.map((rule) => (
                  <RuleRow
                    key={rule.id}
                    rule={rule}
                    onChange={(delta) => handleRuleChange(rule.id, delta)}
                    onDelete={() => handleRuleDelete(rule.id)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
          First-match wins per part (ISO 10303-44 §6.2). No matching rule → included.
        </p>
      </section>

      {/* Error */}
      {error && (
        <p className="text-xs text-red-600 dark:text-red-400" role="alert">{error}</p>
      )}

      {/* Resolve button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleResolve}
          disabled={loading}
          className="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
          aria-label="Resolve variant BOM"
        >
          {loading
            ? <><RefreshCw size={14} className="animate-spin" /> Resolving…</>
            : <><Layers size={14} /> Resolve BOM</>
          }
        </button>
        {resultRows !== null && !loading && (
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {resultRows.filter((r) => r.included).length} / {resultRows.length} parts active
          </span>
        )}
      </div>

      {/* Results */}
      {resultRows !== null && (
        <section aria-labelledby="result-label">
          <label id="result-label" className="mb-2 block text-xs font-medium text-gray-700 dark:text-gray-300">
            Resolved BOM — variant &ldquo;{variantId}&rdquo;
          </label>
          <ResultTable rows={resultRows} />
        </section>
      )}
    </div>
  )
}
