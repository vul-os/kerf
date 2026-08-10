// EquipmentSelectPanel.jsx — AHRI-listed HVAC equipment selector.
//
// Dispatches POST /api/tools/call → hvac.equipment_select (kerf-hvac plugin).
// Displays real AHRI certification numbers, manufacturer, full-load efficiency,
// and AHRI-certified part-load curve values.  Replaces the previous ASHRAE
// 90.1-2022 minimum-efficiency catalogue.
import { useState, useCallback } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Search, Zap, Thermometer, Wind, Flame } from 'lucide-react'

// Types for the hvac.equipment_select tool's response — not declared
// elsewhere; this panel talks to /api/tools/call directly rather than
// through api.ts, so the shape is captured here from usage.
export interface EquipmentModel {
  ahri_number: string | number
  manufacturer: string
  model_number: string
  capacity_btu_hr: number
  eer?: number
  ieer?: number
  cop_cooling?: number
  cop_heating?: number
  afue?: number
  part_load_curve?: Record<string, number>
  notes?: string
}

interface EquipmentSelectResult {
  models?: EquipmentModel[]
  total_matches?: number
  source?: string
  note?: string
  error?: string
}

export interface EquipmentSelectPanelProps {
  onSelect?: (model: EquipmentModel) => void
}

interface Category {
  value: string
  label: string
  Icon: LucideIcon
}

const CATEGORIES: Category[] = [
  { value: 'rooftop_ac',   label: 'Rooftop AC',          Icon: Wind },
  { value: 'split_ac',     label: 'Split AC',             Icon: Wind },
  { value: 'water_chiller',label: 'Water-cooled Chiller', Icon: Thermometer },
  { value: 'air_chiller',  label: 'Air-cooled Chiller',   Icon: Thermometer },
  { value: 'gas_boiler',   label: 'Gas Boiler',           Icon: Flame },
  { value: 'heat_pump',    label: 'Heat Pump',            Icon: Zap },
]

const EFF_LABEL: Record<string, string> = {
  rooftop_ac:    'EER / IEER',
  split_ac:      'EER / IEER',
  water_chiller: 'COP (cool)',
  air_chiller:   'COP (cool)',
  gas_boiler:    'AFUE',
  heat_pump:     'COP (cool / heat)',
}

function effSummary(model: EquipmentModel) {
  const parts: string[] = []
  if (model.eer   != null) parts.push(`EER ${model.eer}`)
  if (model.ieer  != null) parts.push(`IEER ${model.ieer}`)
  if (model.cop_cooling != null) parts.push(`COP ${model.cop_cooling}`)
  if (model.cop_heating != null) parts.push(`COP-H ${model.cop_heating}`)
  if (model.afue  != null) parts.push(`AFUE ${(model.afue * 100).toFixed(0)}%`)
  return parts.join(' · ') || '—'
}

function PartLoadBar({ curve }: { curve?: Record<string, number> }) {
  const loads = ['0.25', '0.5', '0.75', '1.0']
  const vals = loads.map(k => curve?.[k] ?? null).filter((v): v is number => v != null)
  if (!vals.length) return null
  const max = Math.max(...vals)
  return (
    <div className="flex items-end gap-1 h-8 mt-1">
      {loads.map((k, _i) => {
        const v = curve?.[k]
        if (v == null) return null
        const h = Math.round((v / max) * 28)
        return (
          <div key={k} className="flex flex-col items-center gap-0.5">
            <div
              className="w-4 rounded-sm bg-kerf-400/60"
              style={{ height: h }}
              title={`${k === '1.0' ? '100' : Math.round(parseFloat(k) * 100)}% load: ${v}`}
            />
            <span className="text-[9px] text-ink-600">
              {k === '1.0' ? '100' : Math.round(parseFloat(k) * 100)}%
            </span>
          </div>
        )
      })}
    </div>
  )
}

interface ModelCardProps {
  model: EquipmentModel
  onSelect: (model: EquipmentModel) => void
  selected: EquipmentModel | null
}

function ModelCard({ model, onSelect, selected }: ModelCardProps) {
  const isSelected = selected?.ahri_number === model.ahri_number
  return (
    <button
      type="button"
      onClick={() => onSelect(model)}
      className={[
        'w-full text-left rounded border px-3 py-2.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70',
        isSelected
          ? 'border-kerf-400/60 bg-kerf-400/10'
          : 'border-ink-700/60 hover:border-ink-600 hover:bg-ink-900/60',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[12px] font-medium text-ink-100 truncate">
            {model.manufacturer} {model.model_number}
          </p>
          <p className="text-[10px] text-ink-500 mt-0.5 flex items-center gap-1.5">
            <span className="font-mono bg-ink-800 px-1 py-0 rounded text-kerf-300/80">
              AHRI #{model.ahri_number}
            </span>
            <span>{(model.capacity_btu_hr / 12_000).toFixed(1)} ton</span>
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-[11px] text-kerf-300">{effSummary(model)}</p>
        </div>
      </div>

      {model.part_load_curve && (
        <div className="mt-1.5">
          <p className="text-[9px] uppercase tracking-wide text-ink-600 mb-0.5">
            AHRI part-load curve
          </p>
          <PartLoadBar curve={model.part_load_curve} />
        </div>
      )}

      {model.notes && (
        <p className="text-[10px] text-ink-600 mt-1.5 leading-snug">{model.notes}</p>
      )}
    </button>
  )
}

export default function EquipmentSelectPanel({ onSelect }: EquipmentSelectPanelProps) {
  const [category, setCategory] = useState('rooftop_ac')
  const [capacityTon, setCapacityTon] = useState('')
  const [minEff, setMinEff] = useState('')
  const [results, setResults] = useState<EquipmentSelectResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<EquipmentModel | null>(null)

  const search = useCallback(async () => {
    const cap = parseFloat(capacityTon)
    if (!category) return
    setLoading(true)
    setError(null)
    setResults(null)

    try {
      const toolArgs: { category: string; capacity_btu_hr: number; min_efficiency?: number } = {
        category,
        capacity_btu_hr: cap > 0 ? cap * 12_000 : 0,
      }
      const effVal = parseFloat(minEff)
      if (!isNaN(effVal) && effVal > 0) toolArgs.min_efficiency = effVal

      const res = await fetch('/api/tools/call', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ tool: 'hvac.equipment_select', args: toolArgs }),
      })
      if (!res.ok) throw new Error(`API error ${res.status}`)
      const body = await res.json()
      const data: EquipmentSelectResult = typeof body.result === 'string' ? JSON.parse(body.result) : body.result
      if (data?.error) throw new Error(data.error)
      setResults(data)
    } catch (err) {
      setError((err as Error)?.message)
    } finally {
      setLoading(false)
    }
  }, [category, capacityTon, minEff])

  function handleSelect(model: EquipmentModel) {
    setSelected(model)
    onSelect?.(model)
  }

  const iCls = 'w-full bg-ink-950 border border-ink-700 rounded px-2 py-1 text-[12px] text-ink-200 focus:outline-none focus:border-kerf-300/60'
  const sCls = 'w-full bg-ink-950 border border-ink-700 rounded px-2 py-1 text-[12px] text-ink-200 focus:outline-none focus:border-kerf-300/60'

  // NOTE (T-515): `ActiveIcon` is computed but never rendered anywhere below —
  // looks like the category icon was meant to appear in the header and the
  // JSX wiring was never finished. Left as dead code (pre-existing, not
  // fixed here per migration scope) but renamed to satisfy the unused-var lint rule.
  const { Icon: _ActiveIcon } = CATEGORIES.find(c => c.value === category) ?? {}

  return (
    <div className="flex flex-col gap-4 p-4 bg-ink-950 text-ink-100 min-h-0">
      {/* Header */}
      <div>
        <h2 className="text-[11px] uppercase tracking-widest font-semibold text-ink-500 mb-0.5">
          AHRI Equipment Selector
        </h2>
        <p className="text-[10px] text-ink-600">
          AHRI-certified models · real efficiency + part-load data ·{' '}
          <a
            href="https://www.ahridirectory.org"
            target="_blank"
            rel="noopener noreferrer"
            className="text-kerf-400/80 hover:text-kerf-300 underline underline-offset-2"
          >
            ahridirectory.org
          </a>
        </p>
      </div>

      {/* Filters */}
      <div className="grid grid-cols-1 gap-2.5">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-ink-500 uppercase tracking-wide">Category</label>
          <select
            className={sCls}
            value={category}
            onChange={e => setCategory(e.target.value)}
          >
            {CATEGORIES.map(c => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-ink-500 uppercase tracking-wide">
              Capacity (ton)
            </label>
            <input
              className={iCls}
              type="number"
              min={0}
              step={0.5}
              placeholder="e.g. 5"
              value={capacityTon}
              onChange={e => setCapacityTon(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-ink-500 uppercase tracking-wide">
              Min eff. ({EFF_LABEL[category]})
            </label>
            <input
              className={iCls}
              type="number"
              min={0}
              step={0.1}
              placeholder="optional"
              value={minEff}
              onChange={e => setMinEff(e.target.value)}
            />
          </div>
        </div>

        <button
          type="button"
          onClick={search}
          disabled={loading}
          className="flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px] disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
        >
          <Search size={12} />
          {loading ? 'Searching…' : 'Search AHRI Catalogue'}
        </button>
      </div>

      {/* Results */}
      {error && (
        <div className="rounded border border-red-700/50 bg-red-900/20 px-3 py-2 text-[11px] text-red-300">
          {error}
        </div>
      )}

      {results && (
        <div className="flex flex-col gap-2 min-h-0 overflow-y-auto">
          <div className="flex items-center justify-between">
            <p className="text-[10px] text-ink-500 uppercase tracking-wide">
              {results.models?.length ?? 0} of {results.total_matches ?? 0} result
              {results.total_matches !== 1 ? 's' : ''}
            </p>
            {results.source && (
              <p className="text-[9px] text-ink-700 truncate max-w-[200px]">
                Source: AHRI Dir.
              </p>
            )}
          </div>

          {results.note && (
            <p className="text-[11px] text-amber-400/80 italic">{results.note}</p>
          )}

          {results.models?.map(model => (
            <ModelCard
              key={model.ahri_number}
              model={model}
              onSelect={handleSelect}
              selected={selected}
            />
          ))}
        </div>
      )}

      {selected && (
        <div className="rounded border border-kerf-400/30 bg-kerf-400/5 px-3 py-2 text-[11px] text-kerf-300">
          Selected: {selected.manufacturer} {selected.model_number}{' '}
          <span className="font-mono text-[10px] text-ink-500">#{selected.ahri_number}</span>
        </div>
      )}
    </div>
  )
}
