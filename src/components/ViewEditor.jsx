// ViewEditor.jsx — Editor for .view.json saved view files.

import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { VALID_KINDS, validateView, addAnnotation, removeAnnotation } from '../lib/view.js'

// viewFilters.js is declared but not yet shipped.
// Inline stub: accept any non-empty expression; full validation lands when the
// module is available and can be wired in here.
function validateFilterExpr(expr) {
  if (!expr || !expr.trim()) return { ok: false, errors: ['expression is empty'] }
  return { ok: true, errors: [] }
}

const DEBOUNCE_MS = 250

function parse(content) {
  try { return JSON.parse(content || '{}') } catch { return {} }
}

// Simple numeric input with label.
function NumField({ label, value, onChange, placeholder = '0' }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-ink-500 uppercase tracking-wider w-24 flex-shrink-0">{label}</span>
      <input
        type="number"
        value={value !== null && value !== undefined ? value : ''}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        placeholder={placeholder}
        className="w-28 bg-ink-900 border border-ink-800 rounded px-2 py-1 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60"
      />
    </div>
  )
}

export default function ViewEditor({ content, fileName, onContentChange }) {
  const [view, setView] = useState(() => parse(content))
  const [filterDraft, setFilterDraft] = useState('')
  const [filterErr, setFilterErr] = useState(null)
  const lastEmittedRef = useRef(content)
  const timerRef = useRef(null)

  useEffect(() => {
    if (content !== lastEmittedRef.current) {
      setView(parse(content))
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
    setView((v) => {
      const next = { ...v, ...delta }
      emit(next)
      return next
    })
  }

  function patchCropBox(axis, minmax, val) {
    setView((v) => {
      const box = v.crop_box
        ? { min: [...(v.crop_box.min || [0,0,0])], max: [...(v.crop_box.max || [0,0,0])] }
        : { min: [0,0,0], max: [0,0,0] }
      box[minmax][axis] = val
      const next = { ...v, crop_box: box }
      emit(next)
      return next
    })
  }

  function clearCropBox() {
    patch({ crop_box: null })
  }

  // Filter expr validation
  function validateExpr(expr) {
    if (!expr.trim()) { setFilterErr(null); return }
    const res = validateFilterExpr(expr)
    setFilterErr(res?.ok === false ? (res.errors?.[0] || 'Invalid') : null)
  }

  function addFilterExpr() {
    if (!filterDraft.trim()) return
    const filters = [...(view.filters || []), { expr: filterDraft.trim() }]
    patch({ filters })
    setFilterDraft('')
    setFilterErr(null)
  }

  function removeFilter(idx) {
    patch({ filters: (view.filters || []).filter((_, i) => i !== idx) })
  }

  function handleAddAnnotation() {
    const next = addAnnotation(view, { kind: 'tag', label: '' })
    emit(next)
    setView(next)
  }

  function handleRemoveAnnotation(id) {
    const next = removeAnnotation(view, id)
    emit(next)
    setView(next)
  }

  const { errors } = validateView(view)
  const filters = view.filters || []
  const annotations = view.annotations || []
  const cropBox = view.crop_box

  return (
    <div className="h-full flex flex-col bg-ink-950 text-ink-100 overflow-auto">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-ink-800 flex-shrink-0">
        <input
          type="text"
          value={view.name || ''}
          onChange={(e) => patch({ name: e.target.value })}
          placeholder="View name"
          className="flex-1 bg-ink-900 border border-ink-800 rounded px-2 py-1 text-sm text-ink-100 outline-none focus:border-kerf-300/60"
        />
        <select
          value={view.kind || 'plan'}
          onChange={(e) => patch({ kind: e.target.value })}
          className="bg-ink-900 border border-ink-800 rounded px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60"
        >
          {VALID_KINDS.map((k) => <option key={k}>{k}</option>)}
        </select>
        <span className="text-[10px] text-ink-500 font-mono truncate max-w-[140px]">{fileName}</span>
      </div>

      {errors.length > 0 && (
        <div className="px-4 py-2 text-[11px] text-amber-400 border-b border-amber-900/40 bg-amber-950/20">
          {errors[0]}
        </div>
      )}

      <div className="flex-1 overflow-auto px-4 py-4 space-y-6">
        {/* Cut plane / crop box */}
        <section className="space-y-2">
          <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold block">Cut plane &amp; crop box</span>

          {view.kind === 'plan' && (
            <NumField
              label="Cut plane Z (mm)"
              value={view.cut_plane_z_mm}
              onChange={(v) => patch({ cut_plane_z_mm: v })}
              placeholder="1200"
            />
          )}

          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-ink-500 uppercase tracking-wider w-24 flex-shrink-0">Crop box</span>
              {cropBox ? (
                <button
                  type="button"
                  onClick={clearCropBox}
                  className="text-[10px] text-ink-400 hover:text-kerf-300"
                >
                  Clear
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => patch({ crop_box: { min: [0,0,0], max: [1000,1000,3000] } })}
                  className="text-[10px] text-kerf-300 hover:text-kerf-200"
                >
                  Enable
                </button>
              )}
            </div>
            {cropBox && (
              <div className="ml-6 space-y-1">
                {(['min', 'max']).map((mm) => (
                  <div key={mm} className="flex items-center gap-1.5">
                    <span className="text-[10px] text-ink-500 w-8">{mm}</span>
                    {[0,1,2].map((axis) => (
                      <input
                        key={axis}
                        type="number"
                        value={cropBox[mm]?.[axis] ?? 0}
                        onChange={(e) => patchCropBox(axis, mm, Number(e.target.value))}
                        className="w-20 bg-ink-900 border border-ink-800 rounded px-1.5 py-0.5 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60"
                      />
                    ))}
                    <span className="text-[10px] text-ink-500">x y z</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Filters */}
        <section>
          <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold block mb-2">Element filters</span>
          <div className="flex items-center gap-2 mb-2">
            <input
              value={filterDraft}
              onChange={(e) => { setFilterDraft(e.target.value); validateExpr(e.target.value) }}
              onKeyDown={(e) => { if (e.key === 'Enter') addFilterExpr() }}
              placeholder="category=='Wall' AND level>'0'"
              className={`flex-1 bg-ink-900 border rounded px-2 py-1 text-[11px] font-mono text-ink-100 outline-none focus:border-kerf-300/60 ${filterErr ? 'border-red-600' : 'border-ink-800'}`}
            />
            <button
              type="button"
              onClick={addFilterExpr}
              disabled={!filterDraft.trim() || !!filterErr}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px] disabled:opacity-40"
            >
              <Plus size={11} /> Add
            </button>
          </div>
          {filterErr && <p className="text-[10px] text-red-400 mb-1">{filterErr}</p>}
          {filters.length === 0 ? (
            <p className="text-[11px] text-ink-500 italic">No filters — all elements visible.</p>
          ) : (
            <ul className="space-y-1">
              {filters.map((f, idx) => (
                <li key={idx} className="flex items-center gap-2 bg-ink-900 border border-ink-800 rounded px-2 py-1">
                  <code className="flex-1 text-[11px] text-ink-200">{typeof f === 'string' ? f : f.expr}</code>
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

        {/* Annotations */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-ink-400 uppercase tracking-wider font-semibold">Annotations</span>
            <button
              type="button"
              onClick={handleAddAnnotation}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-[11px]"
            >
              <Plus size={11} /> Add
            </button>
          </div>
          {annotations.length === 0 ? (
            <p className="text-[11px] text-ink-500 italic">No annotations.</p>
          ) : (
            <ul className="space-y-1">
              {annotations.map((a) => (
                <li key={a.id} className="flex items-center gap-2 bg-ink-900 border border-ink-800 rounded px-2 py-1">
                  <span className="text-[10px] text-ink-500 font-mono">{a.kind || 'tag'}</span>
                  <span className="flex-1 text-[11px] text-ink-300 truncate">{a.label || a.id}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveAnnotation(a.id)}
                    className="p-1 rounded hover:bg-red-900/30 text-ink-500 hover:text-red-300"
                    title="Remove annotation"
                  >
                    <Trash2 size={11} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Renderer deferred */}
        <section className="rounded border border-ink-800 bg-ink-900/40 px-3 py-3 text-[11px] text-ink-500 italic">
          Will render against linked .bim when Renderer wiring lands.
        </section>
      </div>
    </div>
  )
}
