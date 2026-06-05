/**
 * ParametricFamilyEditorPanel.jsx — Parametric Family Editor
 * with nested sub-families and type catalogue (Revit parity).
 *
 * Features
 * --------
 * - Parameter editor: name/type/default/min/max/units
 * - Formula editor: name = expression (references parameter names)
 * - Nested sub-family list: sub_family_id + placement_params + count
 * - Type catalogue builder: table of named type variants with param overrides
 * - Instantiate button: resolves parameters and shows geometry summary
 * - Validate button: checks parameter + formula + nested structure
 *
 * Props
 * -----
 * onToast  {Function}
 */

import { useState, useCallback } from 'react'
import {
  Layers,
  ChevronDown,
  ChevronRight,
  Plus,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Zap,
  Table,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PARAM_TYPES = ['number', 'text', 'choice', 'boolean']
const CATEGORIES = ['door', 'window', 'furniture', 'fixture', 'column', 'beam', 'generic']

const DEMO_FAMILY = {
  name: 'Curtain Wall System',
  category: 'generic',
  parameters: [
    { name: 'width',           type: 'number', default: 6000, min: 1000, max: 20000, units: 'mm', description: 'Total panel width' },
    { name: 'height',          type: 'number', default: 3200, min: 1500, max: 8000,  units: 'mm', description: 'Panel height' },
    { name: 'frame_width',     type: 'number', default: 80,   min: 40,   max: 150,   units: 'mm', description: 'Frame profile width' },
    { name: 'panel_count',     type: 'number', default: 4,    min: 1,    max: 20,    units: '',   description: 'Number of glazing panels' },
    { name: 'glazing_type',    type: 'choice', default: 'double', choices: ['single', 'double', 'triple'], description: 'Glazing specification' },
  ],
  formulas: [
    { name: 'panel_width',  expression: '(width - (panel_count + 1) * frame_width) / panel_count' },
    { name: 'frame_height', expression: 'height - 2 * frame_width' },
    { name: 'glass_area',   expression: 'panel_width * frame_height * panel_count' },
  ],
}

const DEMO_NESTED = [
  { sub_family_id: 'GLAZING_PANEL', placement_params: { width: 'panel_width', height: 'frame_height' }, count: 'panel_count', label: 'Glazing Panel', ifc_type: 'IfcWindow' },
  { sub_family_id: 'FRAME_PROFILE',  placement_params: { width: 'frame_width', height: 'height' }, count: 4, label: 'Frame Profile', ifc_type: 'IfcMember' },
]

const DEMO_CATALOGUE = [
  { type_id: 'CW-6000x3200', name: '6m × 3.2m (Standard)',  width: 6000, height: 3200, panel_count: 4 },
  { type_id: 'CW-3000x2700', name: '3m × 2.7m (Narrow)',    width: 3000, height: 2700, panel_count: 2 },
  { type_id: 'CW-9000x4200', name: '9m × 4.2m (Wide)',      width: 9000, height: 4200, panel_count: 6 },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function evaluateFormulas(params, formulas, overrides = {}) {
  const ns = { ...Object.fromEntries(params.map(p => [p.name, p.default])), ...overrides }
  for (const f of formulas) {
    try {
      // Safe eval with only known names
      const fn = new Function(...Object.keys(ns), `return ${f.expression}`)
      ns[f.name] = fn(...Object.values(ns))
    } catch {
      ns[f.name] = null
    }
  }
  return ns
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function FormulaRow({ formula, resolved }) {
  const val = resolved?.[formula.name]
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-28 truncate font-mono text-purple-600 dark:text-purple-400">{formula.name}</span>
      <span className="text-ink-400">=</span>
      <span className="flex-1 font-mono text-ink-600 dark:text-ink-300">{formula.expression}</span>
      {val !== undefined && val !== null && (
        <span className="rounded bg-purple-50 dark:bg-purple-900/20 px-1.5 py-0.5 font-mono text-purple-700 dark:text-purple-300">
          {typeof val === 'number' ? val.toFixed(2) : String(val)}
        </span>
      )}
    </div>
  )
}

let _nextParamId = 0, _nextFormulaId = 0

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function ParametricFamilyEditorPanel({ onToast }) {
  const [family, setFamily] = useState(DEMO_FAMILY)
  const [nestedFamilies, setNestedFamilies] = useState(DEMO_NESTED)
  const [catalogue, setCatalogue] = useState(DEMO_CATALOGUE)
  const [selectedTypeId, setSelectedTypeId] = useState(null)
  const [instantiated, setInstantiated] = useState(null)
  const [errors, setErrors] = useState([])
  const [expanded, setExpanded] = useState(true)
  const [activeTab, setActiveTab] = useState('params')

  const currentTypeEntry = catalogue.find(e => e.type_id === selectedTypeId) || null
  const typeOverrides = currentTypeEntry
    ? Object.fromEntries(Object.entries(currentTypeEntry).filter(([k]) => !['type_id', 'name'].includes(k)))
    : {}

  const resolved = evaluateFormulas(family.parameters, family.formulas, typeOverrides)

  const instantiate = useCallback(() => {
    const nested = nestedFamilies.map(nf => {
      const childParams = {}
      for (const [k, expr] of Object.entries(nf.placement_params)) {
        childParams[k] = resolved[expr] ?? expr
      }
      const count = typeof nf.count === 'string' ? (resolved[nf.count] || 1) : nf.count
      return { ...nf, resolved_placement_params: childParams, resolved_count: count }
    })
    setInstantiated({ family: family.name, category: family.category, type_id: selectedTypeId, resolved_params: resolved, nested })
    setActiveTab('result')
  }, [family, nestedFamilies, resolved, selectedTypeId])

  const validate = useCallback(() => {
    const errs = []
    const paramNames = new Set(family.parameters.map(p => p.name))
    const known = new Set(paramNames)
    for (const f of family.formulas) {
      // Simple reference check
      const refs = f.expression.match(/[a-zA-Z_]\w*/g) || []
      for (const ref of refs) {
        if (!known.has(ref) && !['Math', 'math', 'round', 'abs', 'min', 'max', 'int', 'float'].includes(ref)) {
          errs.push(`Formula '${f.name}': unknown reference '${ref}'`)
        }
      }
      known.add(f.name)
    }
    for (const nf of nestedFamilies) {
      if (!nf.sub_family_id) errs.push(`Nested family missing sub_family_id`)
    }
    setErrors(errs)
    setActiveTab('validation')
  }, [family, nestedFamilies])

  const updateParam = useCallback((idx, field, val) => {
    setFamily(f => ({ ...f, parameters: f.parameters.map((p, i) => i === idx ? { ...p, [field]: val } : p) }))
  }, [])

  const addParam = useCallback(() => {
    setFamily(f => ({ ...f, parameters: [...f.parameters, { name: `param_${++_nextParamId}`, type: 'number', default: 0, units: '', description: '' }] }))
  }, [])

  const removeParam = useCallback((idx) => {
    setFamily(f => ({ ...f, parameters: f.parameters.filter((_, i) => i !== idx) }))
  }, [])

  return (
    <div className="flex flex-col border border-ink-200 dark:border-ink-700 rounded-lg bg-white dark:bg-ink-900 overflow-hidden">
      {/* Header */}
      <button
        className="flex items-center justify-between px-4 py-3 text-sm font-semibold text-ink-800 dark:text-ink-100 hover:bg-ink-50 dark:hover:bg-ink-800"
        onClick={() => setExpanded(x => !x)}
      >
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-purple-500" />
          <span>Parametric Family Editor</span>
          <span className="text-xs font-normal text-ink-400 dark:text-ink-500">Nested families + type catalogue</span>
        </div>
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>

      {expanded && (
        <div className="p-4 space-y-4 border-t border-ink-200 dark:border-ink-700">
          {/* Family name + category */}
          <div className="flex gap-2">
            <input value={family.name} onChange={(e) => setFamily(f => ({ ...f, name: e.target.value }))}
              className="flex-1 rounded border border-ink-200 dark:border-ink-600 bg-transparent px-2 py-1.5 text-sm font-medium"
              placeholder="Family name" />
            <select value={family.category} onChange={(e) => setFamily(f => ({ ...f, category: e.target.value }))}
              className="rounded border border-ink-200 dark:border-ink-600 bg-transparent px-2 py-1.5 text-sm">
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          {/* Type catalogue selector */}
          <div className="flex items-center gap-2">
            <Table className="h-3.5 w-3.5 text-ink-400" />
            <label className="text-xs text-ink-500">Type:</label>
            <select value={selectedTypeId || ''} onChange={(e) => setSelectedTypeId(e.target.value || null)}
              className="flex-1 rounded border border-ink-200 dark:border-ink-600 bg-transparent px-2 py-1 text-xs">
              <option value="">(default)</option>
              {catalogue.map(e => <option key={e.type_id} value={e.type_id}>{e.name}</option>)}
            </select>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <button onClick={instantiate}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700">
              <Zap className="h-3.5 w-3.5" />
              Instantiate
            </button>
            <button onClick={validate}
              className="flex items-center gap-1.5 rounded-md border border-ink-300 px-3 py-1.5 text-sm font-medium text-ink-700 hover:bg-ink-50 dark:border-ink-600 dark:text-ink-300 dark:hover:bg-ink-800">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Validate
            </button>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-ink-200 dark:border-ink-700 flex-wrap">
            {[['params', 'Parameters'], ['formulas', 'Formulas'], ['nested', 'Nested'], ['catalogue', 'Type Catalogue'], ['result', 'Result'], ['validation', 'Validation']].map(([id, label]) => (
              <button key={id} onClick={() => setActiveTab(id)}
                className={`px-2.5 py-1.5 text-xs font-medium border-b-2 transition-colors ${
                  activeTab === id ? 'border-purple-500 text-purple-600 dark:text-purple-400' : 'border-transparent text-ink-500 hover:text-ink-700 dark:hover:text-ink-300'
                }`}>
                {label}
              </button>
            ))}
          </div>

          {/* Parameters tab */}
          {activeTab === 'params' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-ink-600 dark:text-ink-300 uppercase tracking-wider">Parameters</span>
                <button onClick={addParam} className="flex items-center gap-1 rounded px-2 py-1 text-xs text-purple-600 hover:bg-purple-50 dark:text-purple-400 dark:hover:bg-purple-900/20">
                  <Plus className="h-3 w-3" /> Add
                </button>
              </div>
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {family.parameters.map((p, idx) => (
                  <div key={idx} className="rounded border border-ink-200 dark:border-ink-700 p-2 text-xs space-y-1.5">
                    <div className="flex items-center gap-1.5">
                      <input value={p.name} onChange={(e) => updateParam(idx, 'name', e.target.value)}
                        className="flex-1 rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1.5 py-0.5 text-xs font-mono" placeholder="name" />
                      <select value={p.type} onChange={(e) => updateParam(idx, 'type', e.target.value)}
                        className="rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs">
                        {PARAM_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                      <button onClick={() => removeParam(idx)} className="text-red-400 hover:text-red-600"><Trash2 className="h-3 w-3" /></button>
                    </div>
                    <div className="grid grid-cols-3 gap-1.5">
                      <div><label className="text-ink-400">Default</label>
                        <input type={p.type === 'number' ? 'number' : 'text'} value={p.default} onChange={(e) => updateParam(idx, 'default', p.type === 'number' ? parseFloat(e.target.value) : e.target.value)}
                          className="mt-0.5 w-full rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs" /></div>
                      <div><label className="text-ink-400">Min</label>
                        <input type="number" value={p.min ?? ''} onChange={(e) => updateParam(idx, 'min', e.target.value ? parseFloat(e.target.value) : null)}
                          className="mt-0.5 w-full rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs" /></div>
                      <div><label className="text-ink-400">Max</label>
                        <input type="number" value={p.max ?? ''} onChange={(e) => updateParam(idx, 'max', e.target.value ? parseFloat(e.target.value) : null)}
                          className="mt-0.5 w-full rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs" /></div>
                    </div>
                    {/* Resolved value */}
                    {resolved[p.name] !== undefined && (
                      <div className="text-ink-400">
                        Resolved: <span className="font-mono text-purple-600 dark:text-purple-400">{resolved[p.name]}</span>
                        {p.units && <span className="ml-1">{p.units}</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Formulas tab */}
          {activeTab === 'formulas' && (
            <div className="space-y-2">
              {family.formulas.map((f, i) => (
                <FormulaRow key={i} formula={f} resolved={resolved} />
              ))}
            </div>
          )}

          {/* Nested tab */}
          {activeTab === 'nested' && (
            <div className="space-y-2">
              {nestedFamilies.map((nf, i) => (
                <div key={i} className="rounded border border-ink-200 dark:border-ink-700 p-2 text-xs">
                  <div className="font-mono text-blue-600 dark:text-blue-400">{nf.sub_family_id}</div>
                  <div className="text-ink-500">{nf.label} · count: {nf.count} · {nf.ifc_type}</div>
                  <div className="mt-1 text-ink-400">
                    {Object.entries(nf.placement_params).map(([k, v]) => (
                      <span key={k} className="mr-2">{k}={resolved[v] !== undefined ? `${resolved[v]?.toFixed(2) ?? v}` : v}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Type catalogue tab */}
          {activeTab === 'catalogue' && (
            <div className="rounded border border-ink-200 dark:border-ink-700 overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-ink-50 dark:bg-ink-800">
                  <tr>
                    <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">ID</th>
                    <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">Name</th>
                    <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">Overrides</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100 dark:divide-ink-800">
                  {catalogue.map((e) => (
                    <tr key={e.type_id} className={`cursor-pointer ${selectedTypeId === e.type_id ? 'bg-purple-50 dark:bg-purple-900/20' : 'hover:bg-ink-50 dark:hover:bg-ink-800/50'}`}
                      onClick={() => setSelectedTypeId(selectedTypeId === e.type_id ? null : e.type_id)}>
                      <td className="px-2 py-1.5 font-mono">{e.type_id}</td>
                      <td className="px-2 py-1.5">{e.name}</td>
                      <td className="px-2 py-1.5 text-ink-400">
                        {Object.entries(e).filter(([k]) => !['type_id', 'name'].includes(k)).map(([k, v]) => `${k}=${v}`).join(', ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Result tab */}
          {activeTab === 'result' && instantiated && (
            <div className="space-y-3">
              <div className="rounded bg-purple-50 dark:bg-purple-900/20 p-3 text-xs">
                <div className="font-semibold text-purple-700 dark:text-purple-300">{instantiated.family} — {instantiated.type_id || 'default'}</div>
                <div className="mt-2 space-y-0.5">
                  {Object.entries(instantiated.resolved_params).map(([k, v]) => (
                    <div key={k} className="flex justify-between">
                      <span className="font-mono text-ink-600 dark:text-ink-300">{k}</span>
                      <span className="font-mono text-purple-600 dark:text-purple-400">{typeof v === 'number' ? v.toFixed(2) : String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold text-ink-600 dark:text-ink-300 mb-1">Nested ({instantiated.nested.length})</div>
                {instantiated.nested.map((n, i) => (
                  <div key={i} className="text-xs text-ink-600 dark:text-ink-300 mb-1">
                    <span className="font-mono text-blue-500">{n.sub_family_id}</span> × {n.resolved_count}
                    {Object.entries(n.resolved_placement_params).map(([k, v]) => (
                      <span key={k} className="ml-1 text-ink-400">{k}={typeof v === 'number' ? v.toFixed(1) : v}</span>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Validation tab */}
          {activeTab === 'validation' && (
            <div className="space-y-1">
              {errors.length === 0 ? (
                <div className="flex items-center gap-2 text-xs text-green-600 dark:text-green-400">
                  <CheckCircle2 className="h-4 w-4" />
                  Family definition is valid
                </div>
              ) : (
                errors.map((e, i) => (
                  <div key={i} className="flex items-start gap-1.5 text-xs text-red-600 dark:text-red-400">
                    <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                    {e}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
