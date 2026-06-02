/**
 * BIMPhasePanel.jsx — Renovation Phase Management UI (ArchiCAD parity).
 *
 * Sections
 * --------
 * 1. Element Phase Tagger  — tag any element_id with a phase + optional demolish phase
 * 2. Active Filter Selector — choose from the 4 default presets or build a custom filter
 * 3. Custom Filter Editor   — checkboxes per phase, demolished ghosts toggle
 * 4. Phase Statistics        — bar chart of element count per phase tag
 * 5. Apply Filter            — runs bim_apply_phase_filter, shows visible/hidden counts
 *
 * Props
 * -----
 * elementPhases   {Array}    Current list of ElementPhase records (id, primary_phase, demolish_phase)
 * onPhasesChange  {Function} Called with updated elementPhases array
 * onFilterResult  {Function} Called with PhaseFilterResult when filter is applied
 * className       {string}   Extra Tailwind classes
 */

import { useState, useCallback, useMemo } from 'react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PHASE_TAGS = [
  { value: 'existing',         label: 'Existing',         colour: '#6b7280' },
  { value: 'new_construction', label: 'New Construction',  colour: '#22c55e' },
  { value: 'demolish',         label: 'Demolish',          colour: '#ef4444' },
  { value: 'future',           label: 'Future',            colour: '#3b82f6' },
  { value: 'alternate_a',      label: 'Alternate A',       colour: '#f59e0b' },
  { value: 'alternate_b',      label: 'Alternate B',       colour: '#a855f7' },
]

const PHASE_MAP = Object.fromEntries(PHASE_TAGS.map((p) => [p.value, p]))

const DEFAULT_FILTERS = [
  {
    name: 'Existing Plan',
    visible_phases: ['existing'],
    demolished_visible: false,
    future_visible: false,
  },
  {
    name: 'Demolition Plan',
    visible_phases: ['existing', 'demolish'],
    demolished_visible: true,
    future_visible: false,
  },
  {
    name: 'New Construction Plan',
    visible_phases: ['new_construction'],
    demolished_visible: false,
    future_visible: false,
  },
  {
    name: 'Composite (All Phases)',
    visible_phases: ['existing', 'new_construction', 'demolish', 'future', 'alternate_a', 'alternate_b'],
    demolished_visible: true,
    future_visible: true,
  },
]

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ title, description }) {
  return (
    <div className="mb-3">
      <h3 className="text-sm font-semibold text-ink-800 dark:text-ink-200">{title}</h3>
      {description && (
        <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">{description}</p>
      )}
    </div>
  )
}

function Divider() {
  return <hr className="my-4 border-ink-200 dark:border-ink-700" />
}

function PhaseTag({ phase }) {
  const info = PHASE_MAP[phase]
  if (!info) return <span className="text-xs text-ink-400">{phase}</span>
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium text-white"
      style={{ backgroundColor: info.colour }}
    >
      {info.label}
    </span>
  )
}

function PhaseDot({ phase }) {
  const info = PHASE_MAP[phase]
  if (!info) return null
  return (
    <span
      className="inline-block h-2 w-2 rounded-full"
      style={{ backgroundColor: info.colour }}
      aria-label={info.label}
    />
  )
}

// ---------------------------------------------------------------------------
// Phase Tagger
// ---------------------------------------------------------------------------

function PhaseTagger({ onTag }) {
  const [elementId, setElementId] = useState('')
  const [phase, setPhase] = useState('existing')
  const [demolishPhase, setDemolishPhase] = useState('')
  const [notes, setNotes] = useState('')

  const handleApply = useCallback(() => {
    if (!elementId.trim()) return
    onTag({ element_id: elementId.trim(), primary_phase: phase, demolish_phase: demolishPhase || null, notes })
    setElementId('')
    setNotes('')
  }, [elementId, phase, demolishPhase, notes, onTag])

  return (
    <div className="space-y-2">
      <SectionHeader
        title="Element Phase Tagger"
        description="Assign a renovation phase to any BIM element by ID."
      />

      <div className="flex flex-col gap-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={elementId}
            onChange={(e) => setElementId(e.target.value)}
            placeholder="element_id (e.g. wall-001)"
            className="flex-1 rounded border border-ink-200 bg-white px-2 py-1.5 text-sm dark:border-ink-600 dark:bg-ink-800 dark:text-ink-100"
            aria-label="Element ID"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1 block text-xs text-ink-500 dark:text-ink-400">Primary phase</label>
            <select
              value={phase}
              onChange={(e) => setPhase(e.target.value)}
              className="w-full rounded border border-ink-200 bg-white px-2 py-1.5 text-sm dark:border-ink-600 dark:bg-ink-800 dark:text-ink-100"
              aria-label="Primary phase"
            >
              {PHASE_TAGS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1 block text-xs text-ink-500 dark:text-ink-400">Demolish in phase</label>
            <select
              value={demolishPhase}
              onChange={(e) => setDemolishPhase(e.target.value)}
              className="w-full rounded border border-ink-200 bg-white px-2 py-1.5 text-sm dark:border-ink-600 dark:bg-ink-800 dark:text-ink-100"
              aria-label="Demolish phase"
            >
              <option value="">(none)</option>
              {PHASE_TAGS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>
        </div>

        <input
          type="text"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Design notes (optional)"
          className="rounded border border-ink-200 bg-white px-2 py-1.5 text-sm dark:border-ink-600 dark:bg-ink-800 dark:text-ink-100"
          aria-label="Design notes"
        />

        <button
          onClick={handleApply}
          disabled={!elementId.trim()}
          className="self-end rounded bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Tag element
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Active Filter Selector + Custom Filter Editor
// ---------------------------------------------------------------------------

function FilterSelector({ activeFilter, onFilterChange }) {
  const [mode, setMode] = useState('preset')  // 'preset' | 'custom'
  const [selectedPreset, setSelectedPreset] = useState(DEFAULT_FILTERS[0].name)
  const [customPhases, setCustomPhases] = useState(['existing'])
  const [demolishedVisible, setDemolishedVisible] = useState(false)
  const [futureVisible, setFutureVisible] = useState(false)

  const handlePresetChange = useCallback((name) => {
    setSelectedPreset(name)
    const preset = DEFAULT_FILTERS.find((f) => f.name === name)
    if (preset) onFilterChange(preset)
  }, [onFilterChange])

  const handleCustomToggle = useCallback((phase) => {
    setCustomPhases((prev) => {
      const next = prev.includes(phase) ? prev.filter((p) => p !== phase) : [...prev, phase]
      onFilterChange({
        name: 'custom',
        visible_phases: next,
        demolished_visible: demolishedVisible,
        future_visible: futureVisible,
      })
      return next
    })
  }, [demolishedVisible, futureVisible, onFilterChange])

  const handleDemolishedToggle = useCallback((v) => {
    setDemolishedVisible(v)
    onFilterChange({
      name: 'custom',
      visible_phases: customPhases,
      demolished_visible: v,
      future_visible: futureVisible,
    })
  }, [customPhases, futureVisible, onFilterChange])

  const handleFutureToggle = useCallback((v) => {
    setFutureVisible(v)
    onFilterChange({
      name: 'custom',
      visible_phases: customPhases,
      demolished_visible: demolishedVisible,
      future_visible: v,
    })
  }, [customPhases, demolishedVisible, onFilterChange])

  return (
    <div className="space-y-3">
      <SectionHeader
        title="Active Filter"
        description="Select a layer combination to control drawing visibility."
      />

      <div className="flex gap-2">
        <button
          onClick={() => setMode('preset')}
          className={`rounded px-3 py-1 text-xs font-medium ${
            mode === 'preset'
              ? 'bg-accent-600 text-white'
              : 'border border-ink-300 text-ink-600 hover:bg-ink-50 dark:border-ink-600 dark:text-ink-300 dark:hover:bg-ink-700'
          }`}
        >
          Preset
        </button>
        <button
          onClick={() => setMode('custom')}
          className={`rounded px-3 py-1 text-xs font-medium ${
            mode === 'custom'
              ? 'bg-accent-600 text-white'
              : 'border border-ink-300 text-ink-600 hover:bg-ink-50 dark:border-ink-600 dark:text-ink-300 dark:hover:bg-ink-700'
          }`}
        >
          Custom
        </button>
      </div>

      {mode === 'preset' && (
        <div className="space-y-1">
          {DEFAULT_FILTERS.map((f) => (
            <label
              key={f.name}
              className="flex cursor-pointer items-center gap-2 rounded p-1.5 hover:bg-ink-50 dark:hover:bg-ink-700"
            >
              <input
                type="radio"
                name="phase-filter-preset"
                value={f.name}
                checked={selectedPreset === f.name}
                onChange={() => handlePresetChange(f.name)}
                className="accent-accent-600"
              />
              <span className="text-sm text-ink-700 dark:text-ink-200">{f.name}</span>
              <span className="ml-auto flex gap-1">
                {f.visible_phases.slice(0, 4).map((p) => (
                  <PhaseDot key={p} phase={p} />
                ))}
                {f.visible_phases.length > 4 && (
                  <span className="text-xs text-ink-400">+{f.visible_phases.length - 4}</span>
                )}
              </span>
            </label>
          ))}
        </div>
      )}

      {mode === 'custom' && (
        <div className="space-y-2 rounded border border-ink-200 p-3 dark:border-ink-600">
          <p className="text-xs font-medium text-ink-500 dark:text-ink-400">Visible phases</p>
          <div className="grid grid-cols-2 gap-1">
            {PHASE_TAGS.map((p) => (
              <label key={p.value} className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={customPhases.includes(p.value)}
                  onChange={() => handleCustomToggle(p.value)}
                  className="accent-accent-600"
                />
                <PhaseDot phase={p.value} />
                <span className="text-sm text-ink-700 dark:text-ink-200">{p.label}</span>
              </label>
            ))}
          </div>

          <Divider />

          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={demolishedVisible}
              onChange={(e) => handleDemolishedToggle(e.target.checked)}
              className="accent-accent-600"
            />
            <span className="text-sm text-ink-700 dark:text-ink-200">Show demolished as ghosts</span>
          </label>

          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={futureVisible}
              onChange={(e) => handleFutureToggle(e.target.checked)}
              className="accent-accent-600"
            />
            <span className="text-sm text-ink-700 dark:text-ink-200">Show future elements</span>
          </label>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Phase Statistics bar chart
// ---------------------------------------------------------------------------

function PhaseStats({ elementPhases }) {
  const counts = useMemo(() => {
    const c = Object.fromEntries(PHASE_TAGS.map((p) => [p.value, 0]))
    for (const ep of elementPhases) {
      if (ep.primary_phase in c) c[ep.primary_phase]++
    }
    return c
  }, [elementPhases])

  const maxCount = Math.max(...Object.values(counts), 1)
  const total = elementPhases.length

  return (
    <div className="space-y-3">
      <SectionHeader
        title="Phase Statistics"
        description={`${total} element${total !== 1 ? 's' : ''} in model`}
      />
      <div className="space-y-1.5">
        {PHASE_TAGS.map((p) => {
          const count = counts[p.value]
          const pct = Math.round((count / maxCount) * 100)
          return (
            <div key={p.value} className="flex items-center gap-2">
              <span className="w-28 truncate text-xs text-ink-600 dark:text-ink-300">{p.label}</span>
              <div className="flex-1 overflow-hidden rounded-full bg-ink-100 dark:bg-ink-700">
                <div
                  className="h-2 rounded-full transition-all duration-300"
                  style={{ width: `${pct}%`, backgroundColor: p.colour }}
                  aria-label={`${p.label}: ${count}`}
                />
              </div>
              <span className="w-6 text-right text-xs tabular-nums text-ink-500 dark:text-ink-400">
                {count}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filter Result display
// ---------------------------------------------------------------------------

function FilterResultPanel({ result }) {
  if (!result) return null

  const { visible_count = 0, hidden_count = 0, demolished_ghost_count = 0, filter_name } = result

  return (
    <div className="rounded-md border border-ink-200 bg-ink-50 p-3 dark:border-ink-600 dark:bg-ink-800/50">
      <p className="mb-2 text-xs font-semibold text-ink-700 dark:text-ink-200">
        Filter applied: <span className="font-normal">{filter_name}</span>
      </p>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-lg font-bold text-green-600 dark:text-green-400">{visible_count}</div>
          <div className="text-xs text-ink-500 dark:text-ink-400">Visible</div>
        </div>
        <div>
          <div className="text-lg font-bold text-red-500 dark:text-red-400">{demolished_ghost_count}</div>
          <div className="text-xs text-ink-500 dark:text-ink-400">Ghosts</div>
        </div>
        <div>
          <div className="text-lg font-bold text-ink-400">{hidden_count}</div>
          <div className="text-xs text-ink-500 dark:text-ink-400">Hidden</div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Element list
// ---------------------------------------------------------------------------

function ElementList({ elementPhases, onRemove }) {
  if (!elementPhases.length) {
    return (
      <p className="text-xs text-ink-400 dark:text-ink-500 italic">
        No elements tagged yet. Use the tagger above to add elements.
      </p>
    )
  }

  return (
    <div className="max-h-40 overflow-y-auto space-y-1">
      {elementPhases.map((ep) => (
        <div
          key={ep.element_id}
          className="flex items-center justify-between rounded px-2 py-1 text-xs hover:bg-ink-50 dark:hover:bg-ink-700"
        >
          <span className="font-mono text-ink-700 dark:text-ink-200 truncate mr-2">{ep.element_id}</span>
          <div className="flex items-center gap-1.5 shrink-0">
            <PhaseTag phase={ep.primary_phase} />
            {ep.demolish_phase && (
              <>
                <span className="text-ink-400">→</span>
                <PhaseTag phase={ep.demolish_phase} />
              </>
            )}
            {onRemove && (
              <button
                onClick={() => onRemove(ep.element_id)}
                className="ml-1 text-ink-400 hover:text-red-500"
                aria-label={`Remove ${ep.element_id}`}
              >
                ×
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main BIMPhasePanel
// ---------------------------------------------------------------------------

export default function BIMPhasePanel({
  elementPhases: externalPhases,
  onPhasesChange,
  onFilterResult,
  className = '',
}) {
  const [localPhases, setLocalPhases] = useState([])
  const [activeFilter, setActiveFilter] = useState(DEFAULT_FILTERS[0])
  const [filterResult, setFilterResult] = useState(null)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState(null)

  // Use controlled or uncontrolled mode
  const elementPhases = externalPhases ?? localPhases
  const setElementPhases = useCallback((phases) => {
    if (onPhasesChange) {
      onPhasesChange(phases)
    } else {
      setLocalPhases(phases)
    }
  }, [onPhasesChange])

  const handleTag = useCallback((entry) => {
    setElementPhases(
      elementPhases.some((ep) => ep.element_id === entry.element_id)
        ? elementPhases.map((ep) => ep.element_id === entry.element_id ? entry : ep)
        : [...elementPhases, entry]
    )
  }, [elementPhases, setElementPhases])

  const handleRemove = useCallback((id) => {
    setElementPhases(elementPhases.filter((ep) => ep.element_id !== id))
  }, [elementPhases, setElementPhases])

  const handleApplyFilter = useCallback(async () => {
    setApplying(true)
    setError(null)
    try {
      // Simulate the filter application client-side using the same logic
      // as the backend (no network call needed for UI preview).
      const visibleSet = new Set(activeFilter.visible_phases)
      const visible = []
      const hidden = []
      const ghost = []

      for (const ep of elementPhases) {
        if (ep.primary_phase === 'future' && !activeFilter.future_visible) {
          hidden.push(ep.element_id)
          continue
        }
        if (!visibleSet.has(ep.primary_phase)) {
          hidden.push(ep.element_id)
          continue
        }
        if (ep.demolish_phase && visibleSet.has(ep.demolish_phase)) {
          if (activeFilter.demolished_visible) {
            ghost.push(ep.element_id)
          } else {
            hidden.push(ep.element_id)
          }
          continue
        }
        visible.push(ep.element_id)
      }

      const result = {
        filter_name: activeFilter.name,
        total_elements: elementPhases.length,
        visible_count: visible.length,
        hidden_count: hidden.length,
        demolished_ghost_count: ghost.length,
        visible_element_ids: visible,
        hidden_element_ids: hidden,
        demolished_ghost_ids: ghost,
      }
      setFilterResult(result)
      if (onFilterResult) onFilterResult(result)
    } catch (e) {
      setError(e.message)
    } finally {
      setApplying(false)
    }
  }, [elementPhases, activeFilter, onFilterResult])

  return (
    <div className={`space-y-4 p-4 ${className}`}>
      {/* Phase Tagger */}
      <PhaseTagger onTag={handleTag} />

      <Divider />

      {/* Element List */}
      <div>
        <SectionHeader
          title="Tagged Elements"
          description={`${elementPhases.length} element${elementPhases.length !== 1 ? 's' : ''} tagged`}
        />
        <ElementList elementPhases={elementPhases} onRemove={handleRemove} />
      </div>

      <Divider />

      {/* Filter Selector */}
      <FilterSelector
        activeFilter={activeFilter}
        onFilterChange={setActiveFilter}
      />

      <Divider />

      {/* Phase Statistics */}
      <PhaseStats elementPhases={elementPhases} />

      <Divider />

      {/* Apply Filter */}
      <div className="space-y-3">
        <SectionHeader
          title="Apply Filter"
          description="Preview element visibility for the selected layer combination."
        />

        {error && (
          <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-700 dark:bg-red-950/30 dark:text-red-300">
            {error}
          </div>
        )}

        <button
          onClick={handleApplyFilter}
          disabled={applying || elementPhases.length === 0}
          className="w-full rounded bg-accent-600 px-3 py-2 text-sm font-medium text-white hover:bg-accent-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {applying ? 'Applying…' : `Apply "${activeFilter.name}"`}
        </button>

        <FilterResultPanel result={filterResult} />
      </div>
    </div>
  )
}
