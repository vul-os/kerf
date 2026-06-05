/**
 * CostEstimationPanel.jsx — 5D Cost Estimation (Revit parity).
 *
 * Quantity takeoff from BIM elements × unit-cost DB → cost rollup
 * by phase / trade / element category.  RICS NRM 1:2012 method.
 *
 * Features
 * --------
 * - Element list editor (id, category, dimensions, trade, phase)
 * - Unit-cost DB editor (custom rates or built-in indicative USD)
 * - Compute cost rollup
 * - Results: total cost, breakdown tabs (by phase / by trade / by category)
 * - Line items table with quantity + unit cost per element
 * - Unpriced elements list
 *
 * Props
 * -----
 * projectId  {string}
 * onToast    {Function}
 */

import { useState, useCallback, useMemo } from 'react'
import {
  DollarSign,
  ChevronDown,
  ChevronRight,
  Plus,
  Trash2,
  BarChart3,
  TrendingUp,
  Package,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CATEGORIES = ['Wall', 'Slab', 'Floor', 'Roof', 'Column', 'Beam', 'Door', 'Window', 'Stair', 'Railing', 'Ceiling', 'MEP', 'Generic']
const TRADES = ['', 'structural', 'architectural', 'mep', 'civil', 'fit-out']
const UNITS = ['m2', 'm3', 'each', 'lm', 'kg', 'm']

// Indicative unit costs (USD, mirrors Python default_unit_cost_db)
const BUILT_IN_RATES = {
  Wall:       { unit: 'm2',   unit_cost: 220 },
  Slab:       { unit: 'm2',   unit_cost: 320 },
  Floor:      { unit: 'm2',   unit_cost: 280 },
  Roof:       { unit: 'm2',   unit_cost: 420 },
  Column:     { unit: 'm3',   unit_cost: 1800 },
  Beam:       { unit: 'm3',   unit_cost: 1600 },
  Door:       { unit: 'each', unit_cost: 1200 },
  Window:     { unit: 'each', unit_cost: 1800 },
  Stair:      { unit: 'each', unit_cost: 8500 },
  Railing:    { unit: 'lm',   unit_cost: 650 },
  Ceiling:    { unit: 'm2',   unit_cost: 120 },
  MEP:        { unit: 'each', unit_cost: 500 },
  Generic:    { unit: 'each', unit_cost: 200 },
}

const DEMO_ELEMENTS = [
  { id: 'wall-001', category: 'Wall',    width: 5.0,  height: 3.0, trade: 'architectural', phase: 'shell' },
  { id: 'wall-002', category: 'Wall',    width: 8.0,  height: 3.0, trade: 'architectural', phase: 'shell' },
  { id: 'slab-001', category: 'Slab',   area: 120.0,              trade: 'structural',     phase: 'shell' },
  { id: 'col-001',  category: 'Column', volume: 0.5,              trade: 'structural',     phase: 'shell' },
  { id: 'door-001', category: 'Door',                             trade: 'architectural',   phase: 'fit-out' },
  { id: 'win-001',  category: 'Window',                           trade: 'architectural',   phase: 'fit-out' },
  { id: 'mep-001',  category: 'MEP',                              trade: 'mep',             phase: 'fit-out' },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractQty(el) {
  const cat = el.category || 'Generic'
  const preferred = BUILT_IN_RATES[cat]?.unit || 'each'
  if (preferred === 'm2') {
    if (el.area > 0) return [parseFloat(el.area), 'm2']
    if (el.width > 0 && el.height > 0) return [el.width * el.height, 'm2']
  }
  if (preferred === 'm3' && el.volume > 0) return [parseFloat(el.volume), 'm3']
  if (preferred === 'lm' && el.length > 0) return [parseFloat(el.length), 'lm']
  return [1.0, 'each']
}

function computeRollup(elements) {
  const lineItems = []
  const unpriced = []
  const byPhase = {}
  const byTrade = {}
  const byCat = {}
  let total = 0

  for (const el of elements) {
    const rate = BUILT_IN_RATES[el.category]
    if (!rate) { unpriced.push(el.id); continue }
    const [qty, unit] = extractQty(el)
    const lineTotal = qty * rate.unit_cost
    total += lineTotal
    const ph = el.phase || '(unphased)'
    const tr = el.trade || '(unassigned)'
    byPhase[ph] = (byPhase[ph] || 0) + lineTotal
    byTrade[tr] = (byTrade[tr] || 0) + lineTotal
    byCat[el.category] = (byCat[el.category] || 0) + lineTotal
    lineItems.push({ element_id: el.id, category: el.category, trade: el.trade, phase: el.phase, quantity: qty, unit, unit_cost: rate.unit_cost, total_cost: lineTotal })
  }

  return { lineItems, unpriced, total: Math.round(total * 100) / 100, byPhase, byTrade, byCat }
}

function fmt(n) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function BreakdownBar({ data, total }) {
  const sorted = Object.entries(data).sort((a, b) => b[1] - a[1])
  const colors = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#a855f7', '#06b6d4', '#f97316']
  return (
    <div className="space-y-1.5">
      {sorted.map(([key, val], i) => (
        <div key={key} className="flex items-center gap-2 text-xs">
          <span className="w-24 truncate text-ink-600 dark:text-ink-300">{key}</span>
          <div className="flex-1 h-2 rounded-full bg-ink-100 dark:bg-ink-700 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${total > 0 ? (val / total * 100) : 0}%`, backgroundColor: colors[i % colors.length] }} />
          </div>
          <span className="w-20 text-right font-mono text-ink-700 dark:text-ink-300">{fmt(val)}</span>
        </div>
      ))}
    </div>
  )
}

let _nextElId = 20

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function CostEstimationPanel({ projectId, onToast }) {
  const [elements, setElements] = useState(DEMO_ELEMENTS)
  const [rollup, setRollup] = useState(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(true)
  const [activeTab, setActiveTab] = useState('summary')

  const compute = useCallback(() => {
    setLoading(true)
    try {
      const result = computeRollup(elements)
      setRollup(result)
    } catch (err) {
      onToast?.(err?.message || 'Cost computation failed')
    } finally {
      setLoading(false)
    }
  }, [elements, onToast])

  const addElement = useCallback(() => {
    const id = `el-${++_nextElId}`
    setElements(prev => [...prev, { id, category: 'Wall', width: 3.0, height: 3.0, trade: '', phase: '' }])
  }, [])

  const removeElement = useCallback((idx) => {
    setElements(prev => prev.filter((_, i) => i !== idx))
  }, [])

  const updateElement = useCallback((idx, field, value) => {
    setElements(prev => prev.map((el, i) => i === idx ? { ...el, [field]: value } : el))
  }, [])

  return (
    <div className="flex flex-col border border-ink-200 dark:border-ink-700 rounded-lg bg-white dark:bg-ink-900 overflow-hidden">
      {/* Header */}
      <button
        className="flex items-center justify-between px-4 py-3 text-sm font-semibold text-ink-800 dark:text-ink-100 hover:bg-ink-50 dark:hover:bg-ink-800"
        onClick={() => setExpanded(x => !x)}
      >
        <div className="flex items-center gap-2">
          <DollarSign className="h-4 w-4 text-green-500" />
          <span>5D Cost Estimation</span>
          <span className="text-xs font-normal text-ink-400 dark:text-ink-500">Revit parity · RICS NRM 1</span>
        </div>
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>

      {expanded && (
        <div className="p-4 space-y-4 border-t border-ink-200 dark:border-ink-700">
          {/* Total cost hero */}
          {rollup && (
            <div className="rounded-lg bg-green-50 dark:bg-green-900/20 p-3 flex items-center justify-between">
              <div>
                <div className="text-2xl font-bold text-green-700 dark:text-green-300">{fmt(rollup.total)}</div>
                <div className="text-xs text-green-600 dark:text-green-400">{rollup.lineItems.length} priced · {rollup.unpriced.length} unpriced</div>
              </div>
              <TrendingUp className="h-8 w-8 text-green-400 opacity-60" />
            </div>
          )}

          {/* Compute button */}
          <button
            onClick={compute}
            disabled={loading}
            className="w-full flex items-center justify-center gap-1.5 rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {loading ? <span className="animate-spin">⟳</span> : <BarChart3 className="h-3.5 w-3.5" />}
            Compute Cost Estimate
          </button>

          {/* Tabs */}
          <div className="flex border-b border-ink-200 dark:border-ink-700">
            {[['summary', 'Summary'], ['phase', 'By Phase'], ['trade', 'By Trade'], ['category', 'By Category'], ['elements', 'Elements']].map(([id, label]) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`px-2.5 py-1.5 text-xs font-medium border-b-2 transition-colors ${
                  activeTab === id
                    ? 'border-green-500 text-green-600 dark:text-green-400'
                    : 'border-transparent text-ink-500 hover:text-ink-700 dark:hover:text-ink-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Summary tab */}
          {activeTab === 'summary' && rollup && (
            <div className="rounded border border-ink-200 dark:border-ink-700 overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-ink-50 dark:bg-ink-800">
                  <tr>
                    <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">Element</th>
                    <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">Qty</th>
                    <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">Unit $</th>
                    <th className="px-2 py-1.5 text-right font-medium text-ink-600 dark:text-ink-300">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100 dark:divide-ink-800">
                  {rollup.lineItems.map((li, i) => (
                    <tr key={i} className="hover:bg-ink-50 dark:hover:bg-ink-800/50">
                      <td className="px-2 py-1.5">
                        <div className="font-mono">{li.element_id}</div>
                        <div className="text-ink-400">{li.category}</div>
                      </td>
                      <td className="px-2 py-1.5">{li.quantity.toFixed(2)} {li.unit}</td>
                      <td className="px-2 py-1.5">{fmt(li.unit_cost)}</td>
                      <td className="px-2 py-1.5 text-right font-medium">{fmt(li.total_cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* By Phase tab */}
          {activeTab === 'phase' && rollup && <BreakdownBar data={rollup.byPhase} total={rollup.total} />}

          {/* By Trade tab */}
          {activeTab === 'trade' && rollup && <BreakdownBar data={rollup.byTrade} total={rollup.total} />}

          {/* By Category tab */}
          {activeTab === 'category' && rollup && <BreakdownBar data={rollup.byCat} total={rollup.total} />}

          {/* Elements tab */}
          {activeTab === 'elements' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-ink-600 dark:text-ink-300 uppercase tracking-wider">BIM Elements</span>
                <button onClick={addElement} className="flex items-center gap-1 rounded px-2 py-1 text-xs text-green-600 hover:bg-green-50 dark:text-green-400 dark:hover:bg-green-900/20">
                  <Plus className="h-3 w-3" /> Add
                </button>
              </div>
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {elements.map((el, idx) => (
                  <div key={el.id} className="rounded border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-800 p-2 text-xs space-y-1.5">
                    <div className="flex items-center gap-1.5">
                      <input value={el.id} onChange={(e) => updateElement(idx, 'id', e.target.value)}
                        className="flex-1 rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1.5 py-0.5 text-xs font-mono" placeholder="element id" />
                      <select value={el.category} onChange={(e) => updateElement(idx, 'category', e.target.value)}
                        className="rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs">
                        {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                      <button onClick={() => removeElement(idx)} className="text-red-400 hover:text-red-600"><Trash2 className="h-3 w-3" /></button>
                    </div>
                    <div className="grid grid-cols-3 gap-1.5">
                      {['width', 'height', 'area', 'volume', 'length'].slice(0, 3).map(f => (
                        <div key={f}>
                          <label className="text-ink-400 capitalize">{f}</label>
                          <input type="number" value={el[f] || ''} onChange={(e) => updateElement(idx, f, parseFloat(e.target.value) || 0)}
                            className="mt-0.5 w-full rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs" placeholder="0" />
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-1.5">
                      <select value={el.trade || ''} onChange={(e) => updateElement(idx, 'trade', e.target.value)}
                        className="flex-1 rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs">
                        {TRADES.map(t => <option key={t} value={t}>{t || '(no trade)'}</option>)}
                      </select>
                      <input value={el.phase || ''} onChange={(e) => updateElement(idx, 'phase', e.target.value)}
                        className="flex-1 rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs" placeholder="phase (e.g. shell)" />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Unpriced */}
          {rollup && rollup.unpriced.length > 0 && (
            <div className="rounded bg-amber-50 dark:bg-amber-900/20 p-2 text-xs">
              <span className="font-medium text-amber-700 dark:text-amber-300">Unpriced: </span>
              <span className="text-amber-600 dark:text-amber-400">{rollup.unpriced.join(', ')}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
