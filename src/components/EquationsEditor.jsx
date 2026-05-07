// EquationsEditor — full-bleed table editor for `.equations` JSON files.
//
// File shape (mirrors backend/internal/llm/docs/equations.md):
//
//   { "version": 1, "params": [
//     { "name": "wall", "expr": "2",     "unit": "mm", "comment": "Default" },
//     { "name": "h",    "expr": "wall*5", "unit": "mm" }
//   ]}
//
// All edits flow through `useWorkspace.updateEquations(patch)` (or, if that
// action isn't present in this build, a direct content patch on the workspace
// store) so the existing revision recorder picks them up — Cmd+Z works
// without any extra wiring.
//
// Live evaluation: every keystroke re-runs the entire sheet through
// `evaluateEquations(parsed)`, which walks rows in declaration order and
// returns `{values, errors}`. Per-row errors render inline (red expression
// input + tooltip); the header status badge summarizes "All resolved" /
// "N errors".

import { useEffect, useMemo, useState } from 'react'
import { Plus, Trash2, RefreshCw, AlertTriangle, CheckCircle2, Variable } from 'lucide-react'
import { useWorkspace } from '../store/workspace.js'
import {
  parseEquations, serializeEquations, evaluateEquations, validIdent,
} from '../lib/equations.js'

export default function EquationsEditor() {
  const currentFile = useWorkspace((s) => s.currentFile)
  const currentFileContent = useWorkspace((s) => s.currentFileContent)
  const editContent = useWorkspace((s) => s.editContent)
  const refreshEquationsCache = useWorkspace((s) => s.refreshEquationsCache)

  // Local copy of the parsed doc. We keep the editor state derived from the
  // store's `currentFileContent` so external changes (revision restore, LLM
  // tool edits) propagate, but we also let the user type freely without
  // round-tripping through JSON.parse on every keystroke.
  const [doc, setDoc] = useState(() => parseEquations(currentFileContent || ''))

  // External content change → reset local doc.
  useEffect(() => {
    setDoc(parseEquations(currentFileContent || ''))
  }, [currentFileContent])

  // Push a fresh parsed doc into the workspace store (which serializes,
  // marks dirty, and lets the autosave loop persist).
  function commit(next) {
    setDoc(next)
    if (typeof editContent === 'function') {
      editContent(serializeEquations(next))
    }
  }

  const evaluated = useMemo(() => evaluateEquations(doc), [doc])
  const errorByIndex = useMemo(() => {
    const m = new Map()
    for (const e of evaluated.errors) m.set(e.paramIndex, e)
    return m
  }, [evaluated.errors])

  function updateRow(i, patch) {
    const next = { ...doc, params: doc.params.map((p, j) => j === i ? { ...p, ...patch } : p) }
    commit(next)
  }
  function removeRow(i) {
    commit({ ...doc, params: doc.params.filter((_, j) => j !== i) })
  }
  function addRow() {
    const used = new Set(doc.params.map((p) => p.name))
    let candidate = 'param'
    let n = 1
    while (used.has(candidate)) {
      candidate = `param${n++}`
    }
    commit({ ...doc, params: [...doc.params, { name: candidate, expr: '0', unit: '', comment: '' }] })
  }

  const errorCount = evaluated.errors.length
  const allResolved = errorCount === 0 && doc.params.length > 0

  return (
    <div className="h-full flex flex-col bg-ink-950 text-ink-100 min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-ink-800 bg-ink-900/40">
        <div className="flex items-center gap-2 min-w-0">
          <Variable size={14} className="text-kerf-300 shrink-0" />
          <span className="text-sm font-medium truncate">{currentFile?.name || 'equations'}</span>
          <span className="text-[11px] text-ink-500 shrink-0">
            {doc.params.length} param{doc.params.length === 1 ? '' : 's'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge errors={errorCount} resolved={allResolved} />
          <button
            type="button"
            onClick={() => {
              setDoc(parseEquations(currentFileContent || ''))
              try { refreshEquationsCache?.() } catch { /* tolerate */ }
            }}
            className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-ink-900/60 border border-ink-700 text-ink-300 hover:bg-ink-800 text-xs"
            title="Re-parse and re-evaluate"
          >
            <RefreshCw size={11} />
            Re-evaluate
          </button>
        </div>
      </div>

      {/* Top-level parse error (malformed JSON) */}
      {doc.errors && doc.errors.length > 0 && (
        <div className="px-4 py-2 bg-red-950/40 border-b border-red-900/60 text-xs text-red-300 flex items-center gap-2">
          <AlertTriangle size={12} />
          <span>{doc.errors[0].message}</span>
        </div>
      )}

      {/* Table */}
      <div className="flex-1 min-h-0 overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-ink-900/95 backdrop-blur border-b border-ink-800 z-10">
            <tr className="text-ink-400 text-left">
              <th className="px-3 py-2 font-medium w-10">#</th>
              <th className="px-3 py-2 font-medium w-44">Name</th>
              <th className="px-3 py-2 font-medium">Expression</th>
              <th className="px-3 py-2 font-medium w-28 text-right">Value</th>
              <th className="px-3 py-2 font-medium w-20">Unit</th>
              <th className="px-3 py-2 font-medium">Comment</th>
              <th className="px-3 py-2 font-medium w-10"></th>
            </tr>
          </thead>
          <tbody>
            {doc.params.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-ink-500 italic">
                  No parameters yet. Click <span className="text-kerf-300">+ Add row</span> to start
                  defining shared dimensions for your project.
                </td>
              </tr>
            )}
            {doc.params.map((row, i) => {
              const err = errorByIndex.get(i)
              const value = evaluated.values[row.name]
              const nameValid = validIdent(row.name)
              return (
                <tr key={i} className="border-b border-ink-800/60 hover:bg-ink-900/20">
                  <td className="px-3 py-1.5 text-ink-500 text-[11px] font-mono">{i + 1}</td>
                  <td className="px-3 py-1.5">
                    <input
                      type="text"
                      value={row.name}
                      onChange={(e) => updateRow(i, { name: e.target.value })}
                      placeholder="name"
                      className={
                        'w-full bg-ink-900/60 border rounded px-2 py-1 text-ink-100 font-mono text-[12px] outline-none ' +
                        (!nameValid && row.name
                          ? 'border-red-700/70 focus:border-red-500'
                          : 'border-ink-700 focus:border-kerf-300/60')
                      }
                      title={!nameValid && row.name ? 'name must be a valid identifier' : ''}
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      type="text"
                      value={row.expr}
                      onChange={(e) => updateRow(i, { expr: e.target.value })}
                      placeholder="2 + wall * 5"
                      className={
                        'w-full bg-ink-900/60 border rounded px-2 py-1 text-ink-100 font-mono text-[12px] outline-none ' +
                        (err
                          ? 'border-red-700/70 focus:border-red-500 text-red-300'
                          : 'border-ink-700 focus:border-kerf-300/60')
                      }
                      title={err?.message || ''}
                    />
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-[12px]">
                    {err ? (
                      <span className="text-red-400" title={err.message}>err</span>
                    ) : Number.isFinite(value) ? (
                      <span className="text-kerf-300">{formatValue(value)}</span>
                    ) : (
                      <span className="text-ink-600">—</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      type="text"
                      value={row.unit || ''}
                      onChange={(e) => updateRow(i, { unit: e.target.value })}
                      placeholder="mm"
                      className="w-full bg-ink-900/60 border border-ink-700 focus:border-kerf-300/60 rounded px-2 py-1 text-ink-200 text-[12px] outline-none"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      type="text"
                      value={row.comment || ''}
                      onChange={(e) => updateRow(i, { comment: e.target.value })}
                      placeholder="optional comment"
                      className="w-full bg-ink-900/60 border border-ink-700 focus:border-kerf-300/60 rounded px-2 py-1 text-ink-300 text-[12px] outline-none"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <button
                      type="button"
                      onClick={() => removeRow(i)}
                      className="p-1 rounded hover:bg-red-950/40 text-ink-500 hover:text-red-400"
                      title="Delete row"
                    >
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              )
            })}
            <tr>
              <td colSpan={7} className="px-3 py-2">
                <button
                  type="button"
                  onClick={addRow}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 text-xs"
                >
                  <Plus size={11} />
                  Add row
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Footer help */}
      <div className="border-t border-ink-800 px-4 py-2 text-[11px] text-ink-500 flex items-center justify-between gap-3">
        <span>
          Reference earlier params by name in expressions. Reference these values from JSCAD via{' '}
          <code className="text-kerf-300">params.&lt;name&gt;</code> or from{' '}
          <code className="text-kerf-300">.feature</code> /{' '}
          <code className="text-kerf-300">.sketch</code> via{' '}
          <code className="text-kerf-300">{'${name}'}</code> placeholders.
        </span>
      </div>
    </div>
  )
}

function StatusBadge({ errors, resolved }) {
  if (errors > 0) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-red-950/40 border border-red-900/60 text-red-300 text-[11px]">
        <AlertTriangle size={10} />
        {errors} error{errors === 1 ? '' : 's'}
      </span>
    )
  }
  if (resolved) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-emerald-950/40 border border-emerald-900/60 text-emerald-300 text-[11px]">
        <CheckCircle2 size={10} />
        All resolved
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-ink-900/60 border border-ink-700 text-ink-400 text-[11px]">
      Empty
    </span>
  )
}

function formatValue(n) {
  if (!Number.isFinite(n)) return '—'
  // Trim trailing zeros for readability while keeping enough precision for
  // typical CAD dimensions (a few decimals on mm).
  const abs = Math.abs(n)
  if (abs === 0) return '0'
  if (abs < 1e-4 || abs >= 1e9) return n.toExponential(4)
  const s = n.toFixed(6)
  return s.replace(/\.?0+$/, '')
}
