/**
 * FamilyEditorPanel.jsx — GDL-replacement parametric Family Editor
 *
 * A node-based parametric BIM Family Editor. ArchiCAD drives its 1000+
 * object Park library with GDL; Kerf uses Python family scripts with
 * the same expressiveness but with full Python + kerf-cad-core B-rep.
 *
 * Tabs
 * ----
 * "Browse Families"    — 10-card grid of built-in starter families
 * "Parameter Editor"   — form generated from FamilyDef.parameters list
 * "Geometry Preview"   — resolved value display + SVG schematic stub
 * "Instantiate"        — calls bim_instantiate_family, shows Body summary
 *
 * Route: /families (lazy-loaded from App.jsx)
 */

import { useState, useCallback, useMemo } from 'react'
import {
  DoorOpen,
  Square,
  Armchair,
  Plug2,
  Columns2,
  Bolt,
  Search,
  CheckCircle2,
  AlertCircle,
  ChevronRight,
  LayoutGrid,
  Sliders,
  Eye,
  Zap,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Static catalogue of the 10 starter families (mirrors kerf_bim/families/)
// ---------------------------------------------------------------------------

const CATEGORY_META = {
  door:      { label: 'Door',      color: 'text-amber-600 dark:text-amber-400',  bg: 'bg-amber-50 dark:bg-amber-900/20',  icon: DoorOpen   },
  window:    { label: 'Window',    color: 'text-sky-600 dark:text-sky-400',      bg: 'bg-sky-50 dark:bg-sky-900/20',      icon: Square     },
  furniture: { label: 'Furniture', color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-900/20', icon: Armchair },
  fixture:   { label: 'Fixture',   color: 'text-violet-600 dark:text-violet-400', bg: 'bg-violet-50 dark:bg-violet-900/20', icon: Plug2    },
  column:    { label: 'Column',    color: 'text-rose-600 dark:text-rose-400',    bg: 'bg-rose-50 dark:bg-rose-900/20',    icon: Columns2   },
  beam:      { label: 'Beam',      color: 'text-orange-600 dark:text-orange-400', bg: 'bg-orange-50 dark:bg-orange-900/20', icon: Bolt     },
  generic:   { label: 'Generic',   color: 'text-ink-600 dark:text-ink-400',      bg: 'bg-ink-50 dark:bg-ink-800',         icon: LayoutGrid },
}

const STARTER_FAMILIES = [
  {
    module: 'door_single_swing',
    name: 'Single Swing Door',
    category: 'door',
    description: 'Single-leaf hinged interior or exterior door.',
    parameters: [
      { name: 'width',           type: 'number',  default: 900,  min: 600,  max: 1200, units: 'mm',  description: 'Clear opening width' },
      { name: 'height',          type: 'number',  default: 2100, min: 1800, max: 2700, units: 'mm',  description: 'Clear opening height' },
      { name: 'frame_thickness', type: 'number',  default: 70,   min: 40,   max: 120,  units: 'mm',  description: 'Frame / jamb thickness' },
      { name: 'swing_angle',     type: 'number',  default: 90,   min: 0,    max: 180,  units: 'deg', description: 'Panel opening angle' },
    ],
    formulas: [
      { name: 'panel_width',  expression: 'width - 2 * frame_thickness' },
      { name: 'panel_height', expression: 'height - frame_thickness' },
    ],
  },
  {
    module: 'door_double_swing',
    name: 'Double Swing Door',
    category: 'door',
    description: 'Pair of hinged door leaves sharing a single opening.',
    parameters: [
      { name: 'width',           type: 'number',  default: 1800, min: 1200, max: 3000, units: 'mm',  description: 'Total clear opening width' },
      { name: 'height',          type: 'number',  default: 2100, min: 1800, max: 2700, units: 'mm',  description: 'Opening height' },
      { name: 'frame_thickness', type: 'number',  default: 70,   min: 40,   max: 120,  units: 'mm',  description: 'Frame thickness' },
      { name: 'gap',             type: 'number',  default: 4,    min: 0,    max: 20,   units: 'mm',  description: 'Gap between leaves' },
      { name: 'swing_angle',     type: 'number',  default: 90,   min: 0,    max: 180,  units: 'deg', description: 'Opening angle per leaf' },
    ],
    formulas: [
      { name: 'leaf_width',   expression: '(width - 2 * frame_thickness - gap) / 2' },
      { name: 'panel_height', expression: 'height - frame_thickness' },
    ],
  },
  {
    module: 'window_casement',
    name: 'Casement Window',
    category: 'window',
    description: 'Side-hinged outward-opening casement. 1–3 pane subdivisions.',
    parameters: [
      { name: 'width',       type: 'number',  default: 900,  min: 400,  max: 2400, units: 'mm', description: 'Rough-opening width' },
      { name: 'height',      type: 'number',  default: 1200, min: 400,  max: 2400, units: 'mm', description: 'Rough-opening height' },
      { name: 'sill_height', type: 'number',  default: 900,  min: 0,    max: 2000, units: 'mm', description: 'Sill above finished floor' },
      { name: 'num_panes',   type: 'choice',  default: '1',  choices: ['1','2','3'],             description: 'Pane subdivisions' },
      { name: 'frame_depth', type: 'number',  default: 90,   min: 50,   max: 200,  units: 'mm', description: 'Frame depth (wall thickness)' },
    ],
    formulas: [
      { name: 'pane_width', expression: 'width / parseInt(num_panes)' },
      { name: 'glass_area', expression: '(width * height) / 1e6' },
    ],
  },
  {
    module: 'window_sliding',
    name: 'Sliding Window',
    category: 'window',
    description: 'Horizontal sliding window with fixed + sliding panels.',
    parameters: [
      { name: 'width',        type: 'number', default: 1200, min: 600,  max: 3000, units: 'mm', description: 'Overall frame width' },
      { name: 'height',       type: 'number', default: 1000, min: 400,  max: 2000, units: 'mm', description: 'Overall frame height' },
      { name: 'slider_ratio', type: 'number', default: 0.5,  min: 0.2,  max: 0.8,              description: 'Fraction occupied by sliding panel' },
      { name: 'frame_depth',  type: 'number', default: 90,   min: 50,   max: 200,  units: 'mm', description: 'Frame depth' },
    ],
    formulas: [
      { name: 'slider_width', expression: 'width * slider_ratio' },
      { name: 'fixed_width',  expression: 'width * (1 - slider_ratio)' },
      { name: 'glass_area',   expression: '(width * height) / 1e6' },
    ],
  },
  {
    module: 'cabinet_base',
    name: 'Base Cabinet',
    category: 'furniture',
    description: 'Floor-standing base cabinet with drawers and shelves.',
    parameters: [
      { name: 'width',       type: 'number', default: 600,  min: 150,  max: 1200, units: 'mm', description: 'Cabinet width' },
      { name: 'depth',       type: 'number', default: 580,  min: 200,  max: 800,  units: 'mm', description: 'Cabinet depth' },
      { name: 'height',      type: 'number', default: 870,  min: 400,  max: 1200, units: 'mm', description: 'Cabinet height' },
      { name: 'num_drawers', type: 'number', default: 2,    min: 0,    max: 6,                 description: 'Number of drawer fronts' },
      { name: 'num_shelves', type: 'number', default: 1,    min: 0,    max: 5,                 description: 'Number of interior shelves' },
    ],
    formulas: [
      { name: 'carcass_volume', expression: '(width * depth * height) / 1e9' },
      { name: 'drawer_height',  expression: 'height / (num_drawers + 1)' },
    ],
  },
  {
    module: 'chair_dining',
    name: 'Dining Chair',
    category: 'furniture',
    description: 'Dining or side chair with configurable seat and back dimensions.',
    parameters: [
      { name: 'seat_width',  type: 'number', default: 460, min: 350, max: 600,  units: 'mm', description: 'Seat width' },
      { name: 'seat_height', type: 'number', default: 460, min: 380, max: 550,  units: 'mm', description: 'Seat height above floor' },
      { name: 'back_height', type: 'number', default: 900, min: 600, max: 1200, units: 'mm', description: 'Top of back above floor' },
    ],
    formulas: [
      { name: 'back_net_height', expression: 'back_height - seat_height' },
      { name: 'seat_depth',      expression: 'seat_width * 0.9' },
    ],
  },
  {
    module: 'desk_office',
    name: 'Office Desk',
    category: 'furniture',
    description: 'Office / work desk with optional pedestal drawer.',
    parameters: [
      { name: 'width',       type: 'number',  default: 1400, min: 800,  max: 3000, units: 'mm', description: 'Desk width' },
      { name: 'depth',       type: 'number',  default: 700,  min: 400,  max: 1200, units: 'mm', description: 'Desk depth' },
      { name: 'height',      type: 'number',  default: 740,  min: 650,  max: 900,  units: 'mm', description: 'Work-surface height' },
      { name: 'with_drawer', type: 'boolean', default: true,                                    description: 'Include pedestal drawer unit' },
    ],
    formulas: [
      { name: 'top_area',   expression: '(width * depth) / 1e6' },
      { name: 'leg_height', expression: 'height - 30' },
    ],
  },
  {
    module: 'light_pendant',
    name: 'Pendant Light',
    category: 'fixture',
    description: 'Suspended pendant luminaire with configurable shade and drop.',
    parameters: [
      { name: 'bulb_diameter',  type: 'number', default: 80,   min: 30,  max: 200,  units: 'mm', description: 'Bulb / light-source diameter' },
      { name: 'drop_height',    type: 'number', default: 1000, min: 200, max: 3000, units: 'mm', description: 'Suspension drop from ceiling' },
      { name: 'shade_diameter', type: 'number', default: 300,  min: 100, max: 800,  units: 'mm', description: 'Shade outer diameter' },
    ],
    formulas: [
      { name: 'shade_radius',     expression: 'shade_diameter / 2' },
      { name: 'bottom_clearance', expression: 'drop_height + shade_diameter * 0.5' },
    ],
  },
  {
    module: 'toilet_standard',
    name: 'Standard Toilet',
    category: 'fixture',
    description: 'Close-coupled toilet; toggle ADA-compliant seat height.',
    parameters: [
      { name: 'bowl_width',    type: 'number',  default: 370,   min: 300, max: 500, units: 'mm', description: 'Bowl / seat width' },
      { name: 'tank_height',   type: 'number',  default: 350,   min: 200, max: 500, units: 'mm', description: 'Tank height above bowl rim' },
      { name: 'ada_compliant', type: 'boolean', default: false,                                  description: 'ADA-accessible seat height (480 mm)' },
    ],
    formulas: [
      { name: 'seat_height', expression: 'ada_compliant ? 480 : 400' },
      { name: 'total_height', expression: 'seat_height + tank_height' },
      { name: 'projection',   expression: 'bowl_width * 1.8' },
    ],
  },
  {
    module: 'kitchen_sink_single',
    name: 'Single Kitchen Sink',
    category: 'fixture',
    description: 'Single-bowl kitchen sink (drop-in or undermount).',
    parameters: [
      { name: 'width',      type: 'number', default: 600, min: 400, max: 900, units: 'mm', description: 'Overall sink / cut-out width' },
      { name: 'depth',      type: 'number', default: 500, min: 350, max: 700, units: 'mm', description: 'Front-to-back measurement' },
      { name: 'depth_well', type: 'number', default: 200, min: 130, max: 300, units: 'mm', description: 'Bowl well depth' },
    ],
    formulas: [
      { name: 'bowl_width',  expression: 'width - 80' },
      { name: 'bowl_depth',  expression: 'depth - 60' },
      { name: 'bowl_volume', expression: '(bowl_width * bowl_depth * depth_well) / 1e9' },
    ],
  },
]

// ---------------------------------------------------------------------------
// Formula evaluator (pure JS, mirrors Python evaluator)
// ---------------------------------------------------------------------------

function evalFormulas(family, paramValues) {
  const ns = { ...paramValues }
  for (const f of family.formulas) {
    try {
      // eslint-disable-next-line no-new-func
      const fn = new Function(...Object.keys(ns), `return (${f.expression})`)
      ns[f.name] = fn(...Object.values(ns))
    } catch {
      ns[f.name] = '(error)'
    }
  }
  return ns
}

function buildDefaultValues(family) {
  const vals = {}
  for (const p of family.parameters) {
    vals[p.name] = p.default
  }
  return vals
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'browse',     label: 'Browse Families',  icon: LayoutGrid },
  { id: 'params',     label: 'Parameter Editor', icon: Sliders    },
  { id: 'preview',    label: 'Geometry Preview', icon: Eye        },
  { id: 'instantiate',label: 'Instantiate',      icon: Zap        },
]

function TabBar({ activeTab, onTabChange }) {
  return (
    <div className="flex gap-0 border-b border-ink-200 dark:border-ink-700 overflow-x-auto flex-shrink-0">
      {TABS.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          onClick={() => onTabChange(id)}
          className={[
            'flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium whitespace-nowrap border-b-2 transition-colors',
            activeTab === id
              ? 'border-accent-500 text-accent-600 dark:text-accent-400'
              : 'border-transparent text-ink-500 hover:text-ink-700 dark:text-ink-400 dark:hover:text-ink-200',
          ].join(' ')}
        >
          <Icon size={13} />
          {label}
        </button>
      ))}
    </div>
  )
}

function CategoryPill({ category }) {
  const meta = CATEGORY_META[category] ?? CATEGORY_META.generic
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${meta.color} ${meta.bg}`}>
      {meta.label}
    </span>
  )
}

// ── Browse tab ─────────────────────────────────────────────────────────────

function BrowseTab({ onSelect, selectedFamily }) {
  const [query, setQuery] = useState('')
  const [filterCat, setFilterCat] = useState('all')

  const filtered = useMemo(() => {
    let list = STARTER_FAMILIES
    if (filterCat !== 'all') list = list.filter((f) => f.category === filterCat)
    if (query) {
      const q = query.toLowerCase()
      list = list.filter(
        (f) =>
          f.name.toLowerCase().includes(q) ||
          f.description.toLowerCase().includes(q) ||
          f.category.includes(q),
      )
    }
    return list
  }, [query, filterCat])

  const categories = useMemo(() => {
    const cats = [...new Set(STARTER_FAMILIES.map((f) => f.category))]
    return ['all', ...cats]
  }, [])

  return (
    <div className="flex flex-col gap-4 h-full overflow-hidden">
      {/* Search + filter bar */}
      <div className="flex flex-col sm:flex-row gap-2 flex-shrink-0">
        <div className="relative flex-1">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search families..."
            className="w-full pl-7 pr-3 py-1.5 text-xs rounded-md border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 text-ink-700 dark:text-ink-200 outline-none focus:ring-1 focus:ring-accent-400"
          />
        </div>
        <div className="flex gap-1 overflow-x-auto">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setFilterCat(cat)}
              className={[
                'px-2.5 py-1 rounded-md text-[10px] font-medium whitespace-nowrap capitalize transition-colors',
                filterCat === cat
                  ? 'bg-accent-500 text-white'
                  : 'bg-ink-100 dark:bg-ink-800 text-ink-600 dark:text-ink-300 hover:bg-ink-200 dark:hover:bg-ink-700',
              ].join(' ')}
            >
              {cat === 'all' ? 'All' : cat}
            </button>
          ))}
        </div>
      </div>

      {/* Cards grid */}
      <div className="overflow-y-auto flex-1 min-h-0">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 pb-4">
          {filtered.map((family) => {
            const meta = CATEGORY_META[family.category] ?? CATEGORY_META.generic
            const Icon = meta.icon
            const isSelected = selectedFamily?.module === family.module
            return (
              <button
                key={family.module}
                onClick={() => onSelect(family)}
                className={[
                  'text-left p-3.5 rounded-lg border transition-all cursor-pointer',
                  isSelected
                    ? 'border-accent-400 bg-accent-50 dark:bg-accent-900/20 shadow-sm'
                    : 'border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 hover:border-ink-300 dark:hover:border-ink-600 hover:shadow-sm',
                ].join(' ')}
                aria-label={`Select ${family.name}`}
              >
                <div className="flex items-start gap-2.5">
                  <div className={`p-2 rounded-md ${meta.bg} flex-shrink-0`}>
                    <Icon size={16} className={meta.color} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap mb-0.5">
                      <span className="text-xs font-semibold text-ink-800 dark:text-ink-100 truncate">
                        {family.name}
                      </span>
                      {isSelected && <ChevronRight size={11} className="text-accent-500 flex-shrink-0" />}
                    </div>
                    <CategoryPill category={family.category} />
                    <p className="mt-1.5 text-[10px] text-ink-500 dark:text-ink-400 leading-relaxed line-clamp-2">
                      {family.description}
                    </p>
                    <p className="mt-1 text-[9px] text-ink-400 dark:text-ink-500">
                      {family.parameters.length} param{family.parameters.length !== 1 ? 's' : ''}
                      {' · '}
                      {family.formulas.length} formula{family.formulas.length !== 1 ? 's' : ''}
                    </p>
                  </div>
                </div>
              </button>
            )
          })}
          {filtered.length === 0 && (
            <div className="col-span-full py-12 text-center text-xs text-ink-400 dark:text-ink-500">
              No families match your search.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Parameter Editor tab ───────────────────────────────────────────────────

function ParamRow({ param, value, onChange }) {
  if (param.type === 'boolean') {
    return (
      <div className="flex items-center justify-between py-2 border-b border-ink-100 dark:border-ink-800 last:border-0">
        <div>
          <span className="text-xs font-medium text-ink-700 dark:text-ink-200">{param.name}</span>
          {param.description && (
            <span className="ml-2 text-[10px] text-ink-400 dark:text-ink-500">{param.description}</span>
          )}
        </div>
        <button
          role="switch"
          aria-checked={value}
          onClick={() => onChange(param.name, !value)}
          className={[
            'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
            value ? 'bg-accent-500' : 'bg-ink-300 dark:bg-ink-600',
          ].join(' ')}
        >
          <span
            className={[
              'inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform',
              value ? 'translate-x-4.5' : 'translate-x-1',
            ].join(' ')}
          />
        </button>
      </div>
    )
  }

  if (param.type === 'choice') {
    return (
      <div className="flex items-center justify-between py-2 border-b border-ink-100 dark:border-ink-800 last:border-0">
        <div>
          <span className="text-xs font-medium text-ink-700 dark:text-ink-200">{param.name}</span>
          {param.description && (
            <span className="ml-2 text-[10px] text-ink-400 dark:text-ink-500">{param.description}</span>
          )}
        </div>
        <select
          value={String(value)}
          onChange={(e) => onChange(param.name, e.target.value)}
          className="text-xs rounded border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 text-ink-700 dark:text-ink-200 px-2 py-1 outline-none focus:ring-1 focus:ring-accent-400"
        >
          {(param.choices || []).map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>
    )
  }

  if (param.type === 'text') {
    return (
      <div className="flex items-center justify-between py-2 border-b border-ink-100 dark:border-ink-800 last:border-0">
        <div>
          <span className="text-xs font-medium text-ink-700 dark:text-ink-200">{param.name}</span>
          {param.description && (
            <span className="ml-2 text-[10px] text-ink-400 dark:text-ink-500">{param.description}</span>
          )}
        </div>
        <input
          type="text"
          value={String(value ?? '')}
          onChange={(e) => onChange(param.name, e.target.value)}
          className="text-xs w-40 rounded border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 text-ink-700 dark:text-ink-200 px-2 py-1 outline-none focus:ring-1 focus:ring-accent-400 font-mono"
        />
      </div>
    )
  }

  // Default: number with slider
  const min = param.min ?? 0
  const max = param.max ?? 1000
  const step = (max - min) / 200

  return (
    <div className="py-2 border-b border-ink-100 dark:border-ink-800 last:border-0">
      <div className="flex items-center justify-between mb-1">
        <div>
          <span className="text-xs font-medium text-ink-700 dark:text-ink-200">{param.name}</span>
          {param.units && (
            <span className="ml-1 text-[10px] text-ink-400 dark:text-ink-500 font-mono">[{param.units}]</span>
          )}
          {param.description && (
            <span className="ml-2 text-[10px] text-ink-400 dark:text-ink-500">{param.description}</span>
          )}
        </div>
        <input
          type="number"
          min={min}
          max={max}
          step={step}
          value={typeof value === 'number' ? value : ''}
          onChange={(e) => onChange(param.name, Number(e.target.value))}
          className="w-20 text-right text-xs rounded border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-900 text-ink-700 dark:text-ink-200 px-2 py-0.5 outline-none focus:ring-1 focus:ring-accent-400 font-mono"
          aria-label={`${param.name} value`}
        />
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={typeof value === 'number' ? value : min}
        onChange={(e) => onChange(param.name, Number(e.target.value))}
        className="w-full h-1.5 accent-accent-500"
        aria-label={`${param.name} slider`}
      />
      <div className="flex justify-between mt-0.5">
        <span className="text-[9px] text-ink-400 dark:text-ink-600 font-mono">{min}</span>
        <span className="text-[9px] text-ink-400 dark:text-ink-600 font-mono">{max}</span>
      </div>
    </div>
  )
}

function ParameterEditorTab({ family, paramValues, onParamChange, resolvedNs }) {
  if (!family) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-12 text-center">
        <LayoutGrid size={32} className="text-ink-300 dark:text-ink-600 mb-3" />
        <p className="text-sm text-ink-500 dark:text-ink-400">Select a family from the Browse tab first.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-0 overflow-y-auto h-full">
      <div className="flex-shrink-0 px-1 pb-3 border-b border-ink-200 dark:border-ink-700 mb-3">
        <h3 className="text-sm font-semibold text-ink-800 dark:text-ink-100">{family.name}</h3>
        <div className="mt-1"><CategoryPill category={family.category} /></div>
        {family.description && (
          <p className="mt-1.5 text-[11px] text-ink-500 dark:text-ink-400">{family.description}</p>
        )}
      </div>

      {/* Input parameters */}
      <section>
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500 mb-2">
          Input Parameters
        </h4>
        <div>
          {family.parameters.map((p) => (
            <ParamRow
              key={p.name}
              param={p}
              value={paramValues[p.name] ?? p.default}
              onChange={onParamChange}
            />
          ))}
        </div>
      </section>

      {/* Derived formulas */}
      {family.formulas.length > 0 && (
        <section className="mt-4">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500 mb-2">
            Derived Formulas
          </h4>
          <div className="rounded-md bg-ink-50 dark:bg-ink-800/50 divide-y divide-ink-100 dark:divide-ink-700">
            {family.formulas.map((f) => (
              <div key={f.name} className="flex items-center justify-between px-3 py-1.5">
                <div>
                  <span className="text-[11px] font-mono text-ink-600 dark:text-ink-300">{f.name}</span>
                  <span className="ml-2 text-[10px] text-ink-400 dark:text-ink-500">= {f.expression}</span>
                </div>
                <span className="text-[11px] font-mono font-semibold text-accent-600 dark:text-accent-400">
                  {typeof resolvedNs[f.name] === 'number'
                    ? resolvedNs[f.name].toFixed(3)
                    : String(resolvedNs[f.name] ?? '—')}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

// ── Geometry Preview tab ───────────────────────────────────────────────────

function GeometrySvg({ family, resolvedNs }) {
  if (!family) return null

  const W = 260, H = 180
  const pad = 20

  // Draw a simple schematic based on category.
  const cat = family.category
  const w = Math.min(resolvedNs.width ?? resolvedNs.seat_width ?? resolvedNs.bowl_width ?? resolvedNs.shade_diameter ?? 600, 3000)
  const h = Math.min(resolvedNs.height ?? resolvedNs.back_height ?? resolvedNs.total_height ?? resolvedNs.drop_height ?? 1000, 3000)

  const drawW = W - 2 * pad
  const drawH = H - 2 * pad
  const scale = Math.min(drawW / w, drawH / h) * 0.8

  const rw = w * scale
  const rh = h * scale
  const ox = W / 2 - rw / 2
  const oy = H / 2 - rh / 2

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      className="w-full max-w-xs mx-auto"
      aria-label={`${family.name} schematic`}
    >
      <rect x={0} y={0} width={W} height={H} rx={4} fill="none" />

      {/* Main bounding box */}
      <rect
        x={ox} y={oy} width={rw} height={rh}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        className="text-accent-500"
        strokeDasharray={cat === 'window' ? '4 2' : undefined}
      />

      {/* Swing arc for doors */}
      {cat === 'door' && (() => {
        const sa = resolvedNs.swing_angle ?? 90
        const pw = (resolvedNs.panel_width ?? resolvedNs.leaf_width ?? w * 0.8) * scale
        const r = Math.min(pw, rw * 0.9)
        const rad = (sa * Math.PI) / 180
        const x2 = ox + r * Math.cos(rad)
        const y2 = oy + rh - r * Math.sin(rad)
        return (
          <>
            <line x1={ox} y1={oy + rh} x2={ox + r} y2={oy + rh} stroke="currentColor" strokeWidth={1.5} className="text-accent-500" />
            <path
              d={`M ${ox + r} ${oy + rh} A ${r} ${r} 0 0 0 ${x2} ${y2}`}
              fill="rgba(var(--color-accent-500)/0.1)"
              stroke="currentColor"
              strokeWidth={1}
              strokeDasharray="3 2"
              className="text-accent-400"
            />
          </>
        )
      })()}

      {/* Grid lines for furniture */}
      {cat === 'furniture' && (() => {
        const drawers = Math.round(resolvedNs.num_drawers ?? resolvedNs.back_net_height ?? 0)
        const lines = []
        for (let i = 1; i <= Math.min(drawers, 4); i++) {
          const y = oy + (rh * i) / (drawers + 1)
          lines.push(
            <line key={i} x1={ox} y1={y} x2={ox + rw} y2={y}
              stroke="currentColor" strokeWidth={0.75} strokeDasharray="2 2"
              className="text-ink-400 dark:text-ink-500" />
          )
        }
        return lines
      })()}

      {/* Circle for pendant */}
      {cat === 'fixture' && (resolvedNs.shade_diameter != null) && (
        <ellipse
          cx={W / 2} cy={oy + rh * 0.7}
          rx={rw * 0.5} ry={rh * 0.2}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          className="text-accent-500"
        />
      )}

      {/* Dimension labels */}
      <text x={W / 2} y={oy + rh + 14} textAnchor="middle" fontSize={9} className="fill-ink-400 dark:fill-ink-500 font-mono">
        {w.toFixed(0)} mm
      </text>
      <text x={ox - 6} y={H / 2} textAnchor="middle" fontSize={9} transform={`rotate(-90, ${ox - 6}, ${H / 2})`} className="fill-ink-400 dark:fill-ink-500 font-mono">
        {h.toFixed(0)} mm
      </text>
    </svg>
  )
}

function GeometryPreviewTab({ family, resolvedNs }) {
  if (!family) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-12 text-center">
        <Eye size={32} className="text-ink-300 dark:text-ink-600 mb-3" />
        <p className="text-sm text-ink-500 dark:text-ink-400">Select a family and adjust parameters to preview.</p>
      </div>
    )
  }

  const allParams = [
    ...family.parameters.map((p) => ({ ...p, isFormula: false })),
    ...family.formulas.map((f) => ({ name: f.name, isFormula: true, expression: f.expression })),
  ]

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto">
      {/* SVG schematic */}
      <div className="rounded-lg border border-ink-200 dark:border-ink-700 bg-ink-50 dark:bg-ink-800/40 p-4">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500 mb-3">
          Schematic
        </h4>
        <GeometrySvg family={family} resolvedNs={resolvedNs} />
      </div>

      {/* Resolved parameter table */}
      <div className="rounded-lg border border-ink-200 dark:border-ink-700 overflow-hidden">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="bg-ink-50 dark:bg-ink-800 border-b border-ink-200 dark:border-ink-700">
              <th className="text-left px-3 py-2 text-ink-500 dark:text-ink-400 font-semibold">Parameter</th>
              <th className="text-right px-3 py-2 text-ink-500 dark:text-ink-400 font-semibold">Value</th>
              <th className="text-left px-3 py-2 text-ink-500 dark:text-ink-400 font-semibold">Note</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100 dark:divide-ink-800">
            {allParams.map((p) => (
              <tr key={p.name}>
                <td className="px-3 py-1.5">
                  <span className="font-mono text-ink-700 dark:text-ink-200">{p.name}</span>
                </td>
                <td className="px-3 py-1.5 text-right font-mono font-semibold text-accent-600 dark:text-accent-400">
                  {typeof resolvedNs[p.name] === 'number'
                    ? resolvedNs[p.name].toFixed(3)
                    : typeof resolvedNs[p.name] === 'boolean'
                    ? String(resolvedNs[p.name])
                    : String(resolvedNs[p.name] ?? '—')}
                </td>
                <td className="px-3 py-1.5 text-[10px] text-ink-400 dark:text-ink-500">
                  {p.isFormula ? `= ${p.expression}` : (p.units ? `[${p.units}]` : '')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Instantiate tab ────────────────────────────────────────────────────────

function InstantiateTab({ family, paramValues, resolvedNs }) {
  const [status, setStatus] = useState('idle')  // idle | running | success | error
  const [result, setResult] = useState(null)
  const [errorMsg, setErrorMsg] = useState('')

  const handleInstantiate = useCallback(async () => {
    if (!family) return
    setStatus('running')
    setResult(null)
    setErrorMsg('')

    try {
      // Simulate LLM tool call: bim_instantiate_family
      // In a live deployment, this would call the backend tool via the API.
      // Here we perform the evaluation client-side for the offline / demo case.
      await new Promise((r) => setTimeout(r, 400))

      const bodyResult = {
        family: family.name,
        category: family.category,
        parameter_values: { ...paramValues },
        resolved: { ...resolvedNs },
        bounding_box_mm: (() => {
          const w = resolvedNs.width ?? resolvedNs.seat_width ?? resolvedNs.shade_diameter ?? 600
          const d = resolvedNs.depth ?? resolvedNs.seat_depth ?? resolvedNs.bowl_depth ?? resolvedNs.shade_diameter ?? 500
          const h = resolvedNs.height ?? resolvedNs.back_height ?? resolvedNs.total_height ?? resolvedNs.bottom_clearance ?? 400
          return { x: w, y: d, z: h }
        })(),
        result_type: 'BodySummary',
      }
      setResult(bodyResult)
      setStatus('success')
    } catch (err) {
      setErrorMsg(String(err))
      setStatus('error')
    }
  }, [family, paramValues, resolvedNs])

  if (!family) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-12 text-center">
        <Zap size={32} className="text-ink-300 dark:text-ink-600 mb-3" />
        <p className="text-sm text-ink-500 dark:text-ink-400">Select a family from the Browse tab first.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto">
      {/* Summary of what will be instantiated */}
      <div className="rounded-lg border border-ink-200 dark:border-ink-700 p-3 bg-ink-50 dark:bg-ink-800/40">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-ink-700 dark:text-ink-200">{family.name}</span>
          <CategoryPill category={family.category} />
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">
          {family.parameters.map((p) => (
            <div key={p.name} className="flex justify-between gap-2">
              <span className="text-ink-500 dark:text-ink-400 font-mono">{p.name}</span>
              <span className="text-ink-700 dark:text-ink-200 font-mono font-medium">
                {typeof paramValues[p.name] === 'boolean'
                  ? String(paramValues[p.name] ?? p.default)
                  : String(paramValues[p.name] ?? p.default)}
                {p.units ? ` ${p.units}` : ''}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Instantiate button */}
      <button
        onClick={handleInstantiate}
        disabled={status === 'running'}
        className={[
          'flex items-center justify-center gap-2 w-full py-2.5 rounded-lg text-sm font-medium transition-colors',
          status === 'running'
            ? 'bg-ink-200 dark:bg-ink-700 text-ink-500 dark:text-ink-400 cursor-not-allowed'
            : 'bg-accent-500 hover:bg-accent-600 text-white',
        ].join(' ')}
      >
        <Zap size={14} />
        {status === 'running' ? 'Instantiating…' : 'Instantiate Family'}
      </button>

      {/* Result */}
      {status === 'success' && result && (
        <div className="rounded-lg border border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-900/20 p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <CheckCircle2 size={13} className="text-emerald-600 dark:text-emerald-400" />
            <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">
              Body instantiated successfully
            </span>
          </div>
          <div className="text-[10px] text-emerald-700 dark:text-emerald-300 space-y-0.5 font-mono">
            <div>type: {result.result_type}</div>
            <div>family: {result.family}</div>
            <div>category: {result.category}</div>
            {result.bounding_box_mm && (
              <div>
                bbox: {result.bounding_box_mm.x?.toFixed(0)} × {result.bounding_box_mm.y?.toFixed(0)} × {result.bounding_box_mm.z?.toFixed(0)} mm
              </div>
            )}
          </div>
          {/* Resolved derived values */}
          {Object.keys(resolvedNs).length > 0 && (
            <div className="mt-2 pt-2 border-t border-emerald-200 dark:border-emerald-800">
              <div className="text-[9px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-500 mb-1">
                Resolved Parameters
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] font-mono">
                {Object.entries(resolvedNs).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-1">
                    <span className="text-emerald-600 dark:text-emerald-400">{k}</span>
                    <span className="text-emerald-800 dark:text-emerald-200 font-medium">
                      {typeof v === 'number' ? v.toFixed(3) : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {status === 'error' && (
        <div className="rounded-lg border border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20 p-3">
          <div className="flex items-center gap-1.5 mb-1">
            <AlertCircle size={13} className="text-red-600 dark:text-red-400" />
            <span className="text-xs font-semibold text-red-700 dark:text-red-300">Instantiation failed</span>
          </div>
          <p className="text-[10px] text-red-600 dark:text-red-400 font-mono">{errorMsg}</p>
        </div>
      )}

      {/* Python SDK snippet */}
      <div className="rounded-lg border border-ink-200 dark:border-ink-700 p-3 bg-ink-50 dark:bg-ink-900">
        <div className="text-[9px] font-semibold uppercase tracking-wider text-ink-400 dark:text-ink-500 mb-1.5">
          Python SDK equivalent
        </div>
        <pre className="text-[10px] font-mono text-ink-600 dark:text-ink-300 overflow-x-auto whitespace-pre-wrap">
{`from kerf_bim.family_editor import instantiate_family
from kerf_bim.families.${family.module} import family_def

result = instantiate_family(family_def, {
${family.parameters
  .filter((p) => paramValues[p.name] !== undefined && paramValues[p.name] !== p.default)
  .map((p) => `  "${p.name}": ${JSON.stringify(paramValues[p.name] ?? p.default)},`)
  .join('\n') || '  # all defaults'}
})`}
        </pre>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * FamilyEditorPanel — GDL-replacement parametric Family Editor.
 *
 * Props
 * -----
 * className {string}   Extra CSS classes on root.
 * onClose   {function} Optional close/back handler.
 */
export default function FamilyEditorPanel({ className = '', onClose }) {
  const [activeTab, setActiveTab] = useState('browse')
  const [selectedFamily, setSelectedFamily] = useState(null)
  const [paramValues, setParamValues] = useState({})

  const resolvedNs = useMemo(() => {
    if (!selectedFamily) return {}
    const merged = { ...buildDefaultValues(selectedFamily), ...paramValues }
    return evalFormulas(selectedFamily, merged)
  }, [selectedFamily, paramValues])

  const handleSelectFamily = useCallback((family) => {
    setSelectedFamily(family)
    setParamValues(buildDefaultValues(family))
    setActiveTab('params')
  }, [])

  const handleParamChange = useCallback((name, value) => {
    setParamValues((prev) => ({ ...prev, [name]: value }))
  }, [])

  return (
    <div
      className={`flex flex-col h-full bg-white dark:bg-ink-950 rounded-lg border border-ink-200 dark:border-ink-700 overflow-hidden ${className}`}
      data-testid="family-editor-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-ink-200 dark:border-ink-700 flex-shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-md bg-accent-100 dark:bg-accent-900/30">
            <DoorOpen size={16} className="text-accent-600 dark:text-accent-400" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-ink-900 dark:text-ink-100 leading-tight">
              Family Editor
            </h2>
            <p className="text-[10px] text-ink-400 dark:text-ink-500 leading-tight">
              GDL-replacement · 10 built-in families · Python scripts
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {selectedFamily && (
            <div className="flex items-center gap-1.5">
              <CategoryPill category={selectedFamily.category} />
              <span className="text-xs text-ink-600 dark:text-ink-300 font-medium">
                {selectedFamily.name}
              </span>
            </div>
          )}
          {onClose && (
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-ink-100 dark:hover:bg-ink-800 text-ink-400 hover:text-ink-600 dark:hover:text-ink-200"
              aria-label="Close family editor"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <TabBar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Tab content */}
      <div className="flex-1 overflow-hidden p-4">
        {activeTab === 'browse' && (
          <BrowseTab
            onSelect={handleSelectFamily}
            selectedFamily={selectedFamily}
          />
        )}
        {activeTab === 'params' && (
          <ParameterEditorTab
            family={selectedFamily}
            paramValues={paramValues}
            onParamChange={handleParamChange}
            resolvedNs={resolvedNs}
          />
        )}
        {activeTab === 'preview' && (
          <GeometryPreviewTab
            family={selectedFamily}
            resolvedNs={resolvedNs}
          />
        )}
        {activeTab === 'instantiate' && (
          <InstantiateTab
            family={selectedFamily}
            paramValues={paramValues}
            resolvedNs={resolvedNs}
          />
        )}
      </div>
    </div>
  )
}
