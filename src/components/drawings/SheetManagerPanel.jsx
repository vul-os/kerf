/**
 * SheetManagerPanel.jsx — ArchiCAD Layout Book equivalent.
 *
 * A self-contained panel that manages a construction document drawing set:
 *   - Sheet list table (AIA NCS sheet number, title, discipline, size, scale)
 *   - Add / remove sheet rows
 *   - Auto-number button (assigns A-101, S-201, etc.)
 *   - Validate button (duplicate numbers, missing titles, orphaned refs)
 *   - Cross-reference table
 *
 * The component is pure-frontend: it owns a local `sheets` list in state and
 * exposes an `onChange(sheets)` callback so the caller can persist.  No fetch
 * calls are made — the parent is responsible for seeding `initialSheets` and
 * saving on change.
 */

import { useState, useCallback, useId } from 'react'
import { Plus, Trash2, Hash, CheckCircle, AlertTriangle, ArrowRight } from 'lucide-react'

// ── constants ──────────────────────────────────────────────────────────────────

const DISCIPLINES = [
  { value: 'architectural', label: 'Architectural' },
  { value: 'structural',    label: 'Structural'    },
  { value: 'mep',           label: 'MEP'           },
  { value: 'civil',         label: 'Civil'         },
  { value: 'interior',      label: 'Interior'      },
  { value: 'general',       label: 'General'       },
]

const SHEET_SIZES = ['A0', 'A1', 'A2', 'A3', 'A4', 'ANSI-A', 'ANSI-B', 'ANSI-C', 'ANSI-D', 'ANSI-E']

// AIA NCS prefixes and series start numbers.
const AIA_PREFIX  = { architectural: 'A', structural: 'S', mep: 'M', civil: 'C', interior: 'I', general: 'G' }
const AIA_BASE    = { architectural: 100, structural: 200, mep: 300, civil: 600, interior: 700, general: 0 }

// Detail marker pattern: "<n>/<LETTER>-<digits>"
const DETAIL_MARKER_RE = /\b(\d+)\/([A-Z]-\d{3})\b/g

let _uid = 0
function nextId() { return `sheet-${++_uid}` }

function makeBlankSheet() {
  return {
    _id:          nextId(),
    sheet_number: '',
    title:        '',
    discipline:   'architectural',
    sheet_size:   'A1',
    scale:        '1:100',
    viewports:    [],
  }
}

// ── auto-numbering (mirrors drawing_list.py logic) ────────────────────────────

function autoNumberSheets(sheets) {
  const counters = {}
  return sheets.map((s) => {
    const disc   = s.discipline
    const prefix = AIA_PREFIX[disc] ?? 'X'
    const base   = AIA_BASE[disc]   ?? 0
    const idx    = counters[disc] ?? 0
    counters[disc] = idx + 1
    return { ...s, sheet_number: `${prefix}-${String(base + idx + 1).padStart(3, '0')}` }
  })
}

// ── validation (mirrors drawing_list.py logic) ─────────────────────────────────

function validateSheets(sheets) {
  const errors = []
  const seen = {}

  sheets.forEach((s, i) => {
    const label = s.sheet_number || `sheets[${i}]`
    if (!s.sheet_number) errors.push(`Sheet ${i + 1} "${s.title}" has no sheet number`)
    if (!s.title)        errors.push(`Sheet ${label} has no title`)
    if (s.sheet_number) {
      if (seen[s.sheet_number] != null) {
        errors.push(`Duplicate sheet number ${s.sheet_number} (rows ${seen[s.sheet_number] + 1} and ${i + 1})`)
      } else {
        seen[s.sheet_number] = i
      }
    }
  })

  const validNums = new Set(sheets.map((s) => s.sheet_number).filter(Boolean))
  sheets.forEach((s) => {
    for (const vp of s.viewports || []) {
      const ref = vp.view_ref || ''
      for (const m of ref.matchAll(DETAIL_MARKER_RE)) {
        const target = m[2]
        if (!validNums.has(target)) {
          errors.push(`Sheet ${s.sheet_number}: ref "${ref}" targets missing sheet ${target}`)
        }
      }
    }
  })

  return errors
}

// ── cross-reference computation ───────────────────────────────────────────────

function computeCrossRefs(sheets) {
  const validNums = new Set(sheets.map((s) => s.sheet_number).filter(Boolean))
  const refs = []
  sheets.forEach((s) => {
    for (const vp of s.viewports || []) {
      const ref = vp.view_ref || ''
      for (const m of ref.matchAll(DETAIL_MARKER_RE)) {
        const marker = m[0]
        const target = m[2]
        if (validNums.has(target)) {
          refs.push({ from: s.sheet_number, to: target, marker })
        }
      }
    }
  })
  return refs
}

// ── sub-components ─────────────────────────────────────────────────────────────

function ValidationBanner({ errors }) {
  if (errors === null) return null
  if (errors.length === 0) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded bg-green-900/30 border border-green-700/50 text-green-300 text-xs">
        <CheckCircle size={13} className="shrink-0" aria-hidden="true" />
        Drawing set is valid — no errors found.
      </div>
    )
  }
  return (
    <div className="rounded border border-amber-600/50 bg-amber-900/20 p-3 space-y-1">
      <div className="flex items-center gap-2 text-amber-300 text-xs font-semibold">
        <AlertTriangle size={13} className="shrink-0" aria-hidden="true" />
        {errors.length} validation {errors.length === 1 ? 'error' : 'errors'}
      </div>
      <ul className="ml-5 list-disc space-y-0.5">
        {errors.map((e, i) => (
          <li key={i} className="text-[11px] text-amber-200">{e}</li>
        ))}
      </ul>
    </div>
  )
}

function CrossRefTable({ refs }) {
  if (!refs || refs.length === 0) {
    return (
      <p className="text-[11px] text-ink-500 py-1">
        No resolved cross-references. Add viewport view_refs in the format "1/A-301".
      </p>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] text-ink-200">
        <thead>
          <tr className="border-b border-ink-700">
            <th className="text-left py-1 pr-3 text-ink-400 font-medium">From</th>
            <th className="text-left py-1 pr-3 text-ink-400 font-medium">To</th>
            <th className="text-left py-1 text-ink-400 font-medium">Marker</th>
          </tr>
        </thead>
        <tbody>
          {refs.map((r, i) => (
            <tr key={i} className="border-b border-ink-800 last:border-0">
              <td className="py-1 pr-3 font-mono">{r.from}</td>
              <td className="py-1 pr-3 font-mono flex items-center gap-1">
                <ArrowRight size={10} className="text-ink-500" aria-hidden="true" />
                {r.to}
              </td>
              <td className="py-1 font-mono text-kerf-300">{r.marker}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── main component ─────────────────────────────────────────────────────────────

export default function SheetManagerPanel({ initialSheets = [], onChange }) {
  const [sheets, setSheets]         = useState(() => initialSheets.length ? initialSheets : [makeBlankSheet()])
  const [validErrors, setValidErrors] = useState(null)   // null = not yet run
  const [crossRefs, setCrossRefs]   = useState(null)
  const [activeTab, setActiveTab]   = useState('sheets') // 'sheets' | 'xrefs'

  const labelId = useId()

  const commit = useCallback((next) => {
    setSheets(next)
    onChange?.(next)
    // Clear stale validation results on any edit.
    setValidErrors(null)
    setCrossRefs(null)
  }, [onChange])

  function addSheet() {
    commit([...sheets, makeBlankSheet()])
  }

  function removeSheet(id) {
    commit(sheets.filter((s) => s._id !== id))
  }

  function patchSheet(id, patch) {
    commit(sheets.map((s) => s._id === id ? { ...s, ...patch } : s))
  }

  function handleAutoNumber() {
    const numbered = autoNumberSheets(sheets)
    commit(numbered)
  }

  function handleValidate() {
    const errors = validateSheets(sheets)
    setValidErrors(errors)
  }

  function handleShowCrossRefs() {
    const refs = computeCrossRefs(sheets)
    setCrossRefs(refs)
    setActiveTab('xrefs')
  }

  const disciplineCount = sheets.reduce((acc, s) => {
    acc[s.discipline] = (acc[s.discipline] ?? 0) + 1
    return acc
  }, {})

  return (
    <div className="flex flex-col gap-3 h-full text-ink-100">

      {/* Header row */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h2 id={labelId} className="text-sm font-semibold text-ink-100">Sheet Manager</h2>
          <p className="text-[11px] text-ink-400 mt-0.5">
            {sheets.length} sheet{sheets.length !== 1 ? 's' : ''} · AIA NCS auto-numbering
          </p>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <button
            type="button"
            onClick={handleAutoNumber}
            title="Auto-number sheets per AIA NCS"
            className="flex items-center gap-1 px-2 py-1 rounded bg-ink-800 text-ink-100 text-[11px] hover:bg-ink-700 hover:text-kerf-300 focus-visible:ring-2 focus-visible:ring-kerf-300 focus-visible:outline-none"
          >
            <Hash size={11} aria-hidden="true" />
            Auto-number
          </button>
          <button
            type="button"
            onClick={handleValidate}
            title="Validate drawing set"
            className="flex items-center gap-1 px-2 py-1 rounded bg-ink-800 text-ink-100 text-[11px] hover:bg-ink-700 hover:text-kerf-300 focus-visible:ring-2 focus-visible:ring-kerf-300 focus-visible:outline-none"
          >
            <CheckCircle size={11} aria-hidden="true" />
            Validate
          </button>
          <button
            type="button"
            onClick={addSheet}
            title="Add sheet"
            aria-label="Add sheet"
            className="flex items-center gap-1 px-2 py-1 rounded bg-kerf-300 text-ink-950 text-[11px] font-medium hover:bg-kerf-200 focus-visible:ring-2 focus-visible:ring-ink-950 focus-visible:outline-none"
          >
            <Plus size={11} aria-hidden="true" />
            Add Sheet
          </button>
        </div>
      </div>

      {/* Validation banner */}
      <ValidationBanner errors={validErrors} />

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-ink-700">
        {[
          { key: 'sheets', label: `Sheets (${sheets.length})` },
          { key: 'xrefs',  label: `Cross-refs${crossRefs ? ` (${crossRefs.length})` : ''}` },
        ].map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              if (key === 'xrefs' && crossRefs === null) handleShowCrossRefs()
              else setActiveTab(key)
            }}
            className={[
              'px-3 py-1.5 text-[11px] font-medium border-b-2 -mb-px focus-visible:ring-2 focus-visible:ring-kerf-300 focus-visible:outline-none',
              activeTab === key
                ? 'border-kerf-300 text-kerf-300'
                : 'border-transparent text-ink-400 hover:text-ink-100',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
        <button
          type="button"
          onClick={handleShowCrossRefs}
          className="ml-auto px-2 py-1 text-[10px] text-ink-500 hover:text-ink-200 focus-visible:ring-2 focus-visible:ring-kerf-300 focus-visible:outline-none"
          title="Refresh cross-reference scan"
        >
          Scan refs
        </button>
      </div>

      {/* Content */}
      {activeTab === 'sheets' ? (
        <div className="flex-1 overflow-y-auto min-h-0">

          {/* Discipline summary chips */}
          <div className="flex flex-wrap gap-1.5 mb-3">
            {Object.entries(disciplineCount).map(([disc, cnt]) => (
              <span
                key={disc}
                className="px-2 py-0.5 rounded-full bg-ink-800 text-[10px] text-ink-300"
              >
                {AIA_PREFIX[disc] || '?'} · {disc} · {cnt}
              </span>
            ))}
          </div>

          {/* Sheet table */}
          <div className="overflow-x-auto rounded border border-ink-700">
            <table className="w-full text-[11px]" aria-labelledby={labelId}>
              <thead className="bg-ink-800 sticky top-0">
                <tr>
                  {['#', 'Sheet No.', 'Title', 'Discipline', 'Size', 'Scale', ''].map((h, i) => (
                    <th
                      key={i}
                      className="text-left px-2 py-1.5 text-[10px] uppercase tracking-wider text-ink-400 font-semibold whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sheets.map((sheet, rowIdx) => (
                  <SheetRow
                    key={sheet._id}
                    sheet={sheet}
                    rowIndex={rowIdx + 1}
                    onPatch={(patch) => patchSheet(sheet._id, patch)}
                    onRemove={() => removeSheet(sheet._id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {sheets.length === 0 && (
            <p className="text-center text-[11px] text-ink-500 py-6">
              No sheets yet — click "Add Sheet" to begin.
            </p>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto min-h-0">
          <p className="text-[11px] text-ink-400 mb-2">
            Resolved detail marker cross-references found in viewport view_refs.
          </p>
          <CrossRefTable refs={crossRefs} />
        </div>
      )}
    </div>
  )
}

// ── SheetRow — a single editable table row ────────────────────────────────────

function SheetRow({ sheet, rowIndex, onPatch, onRemove }) {
  return (
    <tr className="border-b border-ink-800 last:border-0 group hover:bg-ink-800/40">
      <td className="px-2 py-1 text-ink-500 tabular-nums">{rowIndex}</td>
      <td className="px-2 py-1">
        <input
          value={sheet.sheet_number}
          onChange={(e) => onPatch({ sheet_number: e.target.value })}
          aria-label="Sheet number"
          placeholder="A-101"
          className="w-20 h-6 bg-transparent border border-ink-700 rounded px-1.5 text-[11px] font-mono text-ink-100 focus-visible:ring-1 focus-visible:ring-kerf-300 focus-visible:outline-none placeholder:text-ink-600"
        />
      </td>
      <td className="px-2 py-1">
        <input
          value={sheet.title}
          onChange={(e) => onPatch({ title: e.target.value })}
          aria-label="Sheet title"
          placeholder="Floor Plans Level 1"
          className="w-40 h-6 bg-transparent border border-ink-700 rounded px-1.5 text-[11px] text-ink-100 focus-visible:ring-1 focus-visible:ring-kerf-300 focus-visible:outline-none placeholder:text-ink-600"
        />
      </td>
      <td className="px-2 py-1">
        <select
          value={sheet.discipline}
          onChange={(e) => onPatch({ discipline: e.target.value })}
          aria-label="Discipline"
          className="h-6 bg-ink-900 border border-ink-700 rounded px-1.5 text-[11px] text-ink-100 focus-visible:ring-1 focus-visible:ring-kerf-300 focus-visible:outline-none"
        >
          {DISCIPLINES.map((d) => (
            <option key={d.value} value={d.value}>{d.label}</option>
          ))}
        </select>
      </td>
      <td className="px-2 py-1">
        <select
          value={sheet.sheet_size}
          onChange={(e) => onPatch({ sheet_size: e.target.value })}
          aria-label="Sheet size"
          className="h-6 bg-ink-900 border border-ink-700 rounded px-1.5 text-[11px] text-ink-100 focus-visible:ring-1 focus-visible:ring-kerf-300 focus-visible:outline-none"
        >
          {SHEET_SIZES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </td>
      <td className="px-2 py-1">
        <input
          value={sheet.scale}
          onChange={(e) => onPatch({ scale: e.target.value })}
          aria-label="Scale"
          placeholder="1:100"
          className="w-16 h-6 bg-transparent border border-ink-700 rounded px-1.5 text-[11px] font-mono text-ink-100 focus-visible:ring-1 focus-visible:ring-kerf-300 focus-visible:outline-none placeholder:text-ink-600"
        />
      </td>
      <td className="px-2 py-1">
        <button
          type="button"
          onClick={onRemove}
          title="Remove sheet"
          aria-label="Remove sheet"
          className="p-0.5 rounded text-ink-600 hover:text-amber-300 opacity-0 group-hover:opacity-100 focus-visible:ring-2 focus-visible:ring-kerf-300 focus-visible:outline-none focus-visible:opacity-100"
        >
          <Trash2 size={11} aria-hidden="true" />
        </button>
      </td>
    </tr>
  )
}
