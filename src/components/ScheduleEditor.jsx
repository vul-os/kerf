// ScheduleEditor.jsx — Editor for .schedule.json query DSL files.

import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Trash2, Play } from 'lucide-react'
import { validateSchedule, runSchedule } from '../lib/schedule.js'

const CATEGORIES = ['Wall', 'Door', 'Window', 'Room', 'Slab', 'Space', 'Opening', 'Level', 'Site']
const FILTER_OPS = ['eq', 'ne', 'gt', 'lt', 'gte', 'lte', 'in', 'contains']
const DEBOUNCE_MS = 250

function parse(content) {
  try { return JSON.parse(content || '{}') } catch { return {} }
}

export default function ScheduleEditor({ content, fileName, onContentChange }) {
  const [schedule, setSchedule] = useState(() => parse(content))
  const [bimText, setBimText] = useState('')
  const [result, setResult] = useState(null)
  const lastEmittedRef = useRef(content)
  const timerRef = useRef(null)

  useEffect(() => {
    if (content !== lastEmittedRef.current) {
      setSchedule(parse(content))
    }
  }, [content])

  const emit = useCallback((next) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      const s = JSON.stringify(next, null, 2)
      lastEmittedRef.current = s
      onContentChange?.(s)
    }, DEBOUNCE_MS)
  }, [onContentChange])
  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  function patch(delta) {
    setSchedule((s) => {
      const next = { ...s, ...delta }
      emit(next)
      return next
    })
  }

  // ── Filters ─────────────────────────────────────────────────────────────────

  function addFilter() {
    patch({ filters: [...(schedule.filters || []), { field: '', op: 'eq', value: '' }] })
  }

  function removeFilter(idx) {
    patch({ filters: (schedule.filters || []).filter((_, i) => i !== idx) })
  }

  function patchFilter(idx, delta) {
    const filters = (schedule.filters || []).map((f, i) => i === idx ? { ...f, ...delta } : f)
    patch({ filters })
  }

  // ── Columns ──────────────────────────────────────────────────────────────────

  function addColumn() {
    patch({ columns: [...(schedule.columns || []), { field: '', label: '', format: '' }] })
  }

  function removeColumn(idx) {
    patch({ columns: (schedule.columns || []).filter((_, i) => i !== idx) })
  }

  function patchColumn(idx, delta) {
    const columns = (schedule.columns || []).map((c, i) => i === idx ? { ...c, ...delta } : c)
    patch({ columns })
  }

  // ── Run ──────────────────────────────────────────────────────────────────────

  function handleRun() {
    let bimDoc
    try { bimDoc = JSON.parse(bimText) } catch {
      setResult({ error: 'Invalid BIM JSON' })
      return
    }
    try {
      const r = runSchedule(schedule, bimDoc)
      setResult({ ok: r })
    } catch (err) {
      setResult({ error: err.message || String(err) })
    }
  }

  const { errors } = validateSchedule(schedule)
  const filters = schedule.filters || []
  const columns = schedule.columns || []

  return (
    <div className="h-full flex flex-col bg-ink-950 text-ink-100 overflow-auto">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-ink-800 flex-shrink-0">
        <input
          type="text"
          value={schedule.name || ''}
          onChange={(e) => patch({ name: e.target.value })}
          placeholder="Schedule name"
          className="flex-1 bg-ink-900 border border-ink-800 rounded px-2 py-1 text-sm text-ink-100 outline-none focus:border-kerf-300/60"
        />
        <select
          value={schedule.target_category || 'Wall'}
          onChange={(e) => patch({ target_category: e.target.value })}
          className="bg-ink-900 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60"
        >
          {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
        </select>
        <span className="text-[10px] text-ink-500 font-mono truncate max-w-[140px]">{fileName}</span>
      </div>

      {errors.length > 0 && (
        <div className="px-4 py-2 text-[11px] text-amber-400 border-b border-amber-900/40 bg-amber-950/20">
          {errors[0]}
        </div>
      )}

      <div className="flex-1 overflow-auto px-4 py-4 space-y-6">
        {/* Filters */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold">Filters</span>
            <button
              type="button"
              onClick={addFilter}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px]"
            >
              <Plus size={11} /> Add filter
            </button>
          </div>

          {filters.length === 0 ? (
            <p className="text-[11px] text-ink-500 italic">No filters — all elements included.</p>
          ) : (
            <ul className="space-y-1.5">
              {filters.map((f, idx) => (
                <li key={idx} className="flex items-center gap-2">
                  <input
                    value={f.field || ''}
                    onChange={(e) => patchFilter(idx, { field: e.target.value })}
                    placeholder="field"
                    className="w-32 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60"
                  />
                  <select
                    value={f.op || 'eq'}
                    onChange={(e) => patchFilter(idx, { op: e.target.value })}
                    className="bg-ink-900 border border-ink-800 rounded px-1 py-0.5 text-[11px] text-ink-100 outline-none focus:border-kerf-300/60"
                  >
                    {FILTER_OPS.map((o) => <option key={o}>{o}</option>)}
                  </select>
                  <input
                    value={f.value !== undefined ? String(f.value) : ''}
                    onChange={(e) => patchFilter(idx, { value: e.target.value })}
                    placeholder="value"
                    className="flex-1 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60"
                  />
                  <button
                    type="button"
                    onClick={() => removeFilter(idx)}
                    className="p-1 rounded hover:bg-red-900/30 text-ink-500 hover:text-red-300"
                    title="Remove filter"
                  >
                    <Trash2 size={11} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Columns */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold">Columns</span>
            <button
              type="button"
              onClick={addColumn}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px]"
            >
              <Plus size={11} /> Add column
            </button>
          </div>

          {columns.length === 0 ? (
            <p className="text-[11px] text-ink-500 italic">No columns defined.</p>
          ) : (
            <ul className="space-y-1.5">
              {columns.map((c, idx) => (
                <li key={idx} className="flex items-center gap-2">
                  <input
                    value={c.field || ''}
                    onChange={(e) => patchColumn(idx, { field: e.target.value })}
                    placeholder="field"
                    className="w-32 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60"
                  />
                  <input
                    value={c.label || ''}
                    onChange={(e) => patchColumn(idx, { label: e.target.value })}
                    placeholder="label"
                    className="w-32 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 outline-none focus:border-kerf-300/60"
                  />
                  <input
                    value={c.format || ''}
                    onChange={(e) => patchColumn(idx, { format: e.target.value })}
                    placeholder="format"
                    className="w-24 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 outline-none focus:border-kerf-300/60"
                  />
                  <button
                    type="button"
                    onClick={() => removeColumn(idx)}
                    className="p-1 rounded hover:bg-red-900/30 text-ink-500 hover:text-red-300"
                    title="Remove column"
                  >
                    <Trash2 size={11} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Run / test */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold">Test against BIM</span>
            <button
              type="button"
              onClick={handleRun}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300 text-ink-950 text-[11px] font-medium hover:bg-kerf-200"
            >
              <Play size={11} /> Run
            </button>
          </div>
          <textarea
            value={bimText}
            onChange={(e) => setBimText(e.target.value)}
            placeholder={'Paste .bim JSON here to test\n{"elements":[...]}'}
            rows={5}
            spellCheck={false}
            className="w-full bg-ink-900 border border-ink-800 rounded p-2 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60 resize-none"
          />

          {result?.error && (
            <p className="mt-2 text-[11px] text-red-400">{result.error}</p>
          )}

          {result?.ok && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-[11px] border-collapse">
                <thead>
                  <tr className="border-b border-ink-800">
                    {result.ok.columns.map((col) => (
                      <th key={col.field} className="text-left px-2 py-1 text-[10px] text-ink-400 uppercase tracking-wider font-semibold">
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.ok.rows.flat().map((row, i) => (
                    <tr key={i} className="border-b border-ink-900 hover:bg-ink-900/40">
                      {result.ok.columns.map((col) => (
                        <td key={col.field} className="px-2 py-1 font-mono text-ink-200">
                          {row[col.field] !== null && row[col.field] !== undefined ? String(row[col.field]) : <span className="text-ink-600">—</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {result.ok.rows.flat().length === 0 && (
                    <tr><td colSpan={result.ok.columns.length} className="px-2 py-3 text-center text-ink-500 italic">No results</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
