// FamilyEditor.jsx — Editor for .family.json parametric component templates.

import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { validateFamily } from '../lib/family.js'

const CATEGORIES = [
  'Wall', 'Floor', 'Roof', 'Door', 'Window', 'Column', 'Beam',
  'Stair', 'Railing', 'Ceiling', 'Furniture', 'Generic',
]
const PARAM_TYPES = ['number', 'string', 'boolean', 'enum']
const DEBOUNCE_MS = 250

function parse(content) {
  try { return JSON.parse(content || '{}') } catch { return {} }
}

export default function FamilyEditor({ content, fileName, onContentChange }) {
  const [family, setFamily] = useState(() => parse(content))
  const lastEmittedRef = useRef(content)
  const timerRef = useRef(null)

  // Resync if external content changes (LLM write / undo).
  useEffect(() => {
    if (content !== lastEmittedRef.current) {
      setFamily(parse(content))
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
    setFamily((f) => {
      const next = { ...f, ...delta }
      emit(next)
      return next
    })
  }

  // ── Params ──────────────────────────────────────────────────────────────────

  function addParam() {
    setFamily((f) => {
      const params = [...(f.params || []), { name: '', type: 'number', default: 0 }]
      const next = { ...f, params }
      emit(next)
      return next
    })
  }

  function removeParam(idx) {
    setFamily((f) => {
      const params = (f.params || []).filter((_, i) => i !== idx)
      const next = { ...f, params }
      emit(next)
      return next
    })
  }

  function patchParam(idx, delta) {
    setFamily((f) => {
      const params = (f.params || []).map((p, i) => i === idx ? { ...p, ...delta } : p)
      const next = { ...f, params }
      emit(next)
      return next
    })
  }

  // ── Types ───────────────────────────────────────────────────────────────────

  function addType() {
    setFamily((f) => {
      const id = `type-${Date.now()}`
      const types = [...(f.types || []), { id, name: '', params: {} }]
      const next = { ...f, types }
      emit(next)
      return next
    })
  }

  function removeType(idx) {
    setFamily((f) => {
      const types = (f.types || []).filter((_, i) => i !== idx)
      const next = { ...f, types }
      emit(next)
      return next
    })
  }

  function patchType(idx, delta) {
    setFamily((f) => {
      const types = (f.types || []).map((t, i) => i === idx ? { ...t, ...delta } : t)
      const next = { ...f, types }
      emit(next)
      return next
    })
  }

  const { errors } = validateFamily(family)
  const params = family.params || []
  const types = family.types || []

  return (
    <div className="h-full flex flex-col bg-ink-950 text-ink-100 overflow-auto">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-ink-800 flex-shrink-0">
        <input
          type="text"
          value={family.name || ''}
          onChange={(e) => patch({ name: e.target.value })}
          placeholder="Family name"
          className="flex-1 bg-ink-900 border border-ink-800 rounded px-2 py-1 text-sm text-ink-100 outline-none focus:border-kerf-300/60"
        />
        <select
          value={family.category || 'Generic'}
          onChange={(e) => patch({ category: e.target.value })}
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
        {/* Params table */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold">Parameters</span>
            <button
              type="button"
              onClick={addParam}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px]"
            >
              <Plus size={11} /> Add param
            </button>
          </div>

          {params.length === 0 ? (
            <p className="text-[11px] text-ink-500 italic">No parameters defined.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-ink-500 text-[10px] uppercase tracking-wider border-b border-ink-800">
                    <th className="text-left pb-1.5 pr-2 font-medium">Name</th>
                    <th className="text-left pb-1.5 pr-2 font-medium">Type</th>
                    <th className="text-left pb-1.5 pr-2 font-medium">Default</th>
                    <th className="text-left pb-1.5 pr-2 font-medium">Min</th>
                    <th className="text-left pb-1.5 pr-2 font-medium">Max</th>
                    <th className="text-left pb-1.5 pr-2 font-medium">Unit</th>
                    <th className="pb-1.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-900">
                  {params.map((p, idx) => (
                    <tr key={idx}>
                      <td className="py-1 pr-2">
                        <input
                          value={p.name || ''}
                          onChange={(e) => patchParam(idx, { name: e.target.value })}
                          placeholder="name"
                          className="w-full bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-ink-100 outline-none focus:border-kerf-300/60 font-mono"
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <select
                          value={p.type || 'number'}
                          onChange={(e) => patchParam(idx, { type: e.target.value })}
                          className="bg-ink-900 border border-ink-800 rounded px-1 py-0.5 text-ink-100 outline-none focus:border-kerf-300/60"
                        >
                          {PARAM_TYPES.map((t) => <option key={t}>{t}</option>)}
                        </select>
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          value={p.default !== undefined ? String(p.default) : ''}
                          onChange={(e) => {
                            const v = p.type === 'number' ? Number(e.target.value) : e.target.value
                            patchParam(idx, { default: v })
                          }}
                          placeholder="—"
                          className="w-20 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-ink-100 outline-none focus:border-kerf-300/60 font-mono"
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          type="number"
                          value={p.min !== undefined ? p.min : ''}
                          onChange={(e) => patchParam(idx, { min: e.target.value === '' ? undefined : Number(e.target.value) })}
                          placeholder="—"
                          disabled={p.type !== 'number'}
                          className="w-16 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-ink-100 outline-none focus:border-kerf-300/60 font-mono disabled:opacity-30"
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          type="number"
                          value={p.max !== undefined ? p.max : ''}
                          onChange={(e) => patchParam(idx, { max: e.target.value === '' ? undefined : Number(e.target.value) })}
                          placeholder="—"
                          disabled={p.type !== 'number'}
                          className="w-16 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-ink-100 outline-none focus:border-kerf-300/60 font-mono disabled:opacity-30"
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          value={p.unit || ''}
                          onChange={(e) => patchParam(idx, { unit: e.target.value })}
                          placeholder="mm"
                          className="w-14 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-ink-100 outline-none focus:border-kerf-300/60"
                        />
                      </td>
                      <td className="py-1">
                        <button
                          type="button"
                          onClick={() => removeParam(idx)}
                          className="p-1 rounded hover:bg-red-900/30 text-ink-500 hover:text-red-300"
                          title="Remove param"
                        >
                          <Trash2 size={11} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Types panel */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold">Types (param presets)</span>
            <button
              type="button"
              onClick={addType}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px]"
            >
              <Plus size={11} /> Add type
            </button>
          </div>

          {types.length === 0 ? (
            <p className="text-[11px] text-ink-500 italic">No types defined.</p>
          ) : (
            <ul className="space-y-2">
              {types.map((t, idx) => (
                <li key={idx} className="flex items-center gap-2 bg-ink-900 border border-ink-800 rounded px-3 py-2">
                  <input
                    value={t.id || ''}
                    onChange={(e) => patchType(idx, { id: e.target.value })}
                    placeholder="id"
                    className="w-28 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60"
                  />
                  <input
                    value={t.name || ''}
                    onChange={(e) => patchType(idx, { name: e.target.value })}
                    placeholder="display name"
                    className="flex-1 bg-ink-950 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] text-ink-100 outline-none focus:border-kerf-300/60"
                  />
                  <button
                    type="button"
                    onClick={() => removeType(idx)}
                    className="p-1 rounded hover:bg-red-900/30 text-ink-500 hover:text-red-300"
                    title="Delete type"
                  >
                    <Trash2 size={11} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
