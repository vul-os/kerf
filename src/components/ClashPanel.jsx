/**
 * ClashPanel — Assembly clash-detection side panel.
 *
 * Renders a collapsible panel inside the AssemblyEditor that lets the user
 * run OBB-SAT + BVH clash detection on the current assembly and inspect the
 * results.
 *
 * Props
 * -----
 * projectId         string           — current project id
 * assemblyFileId    string           — id of the .assembly file
 * onHighlight       (componentId) => void
 *                   — called when the user clicks "Jump to"; the parent should
 *                     pass this down to the Renderer as selectedComponentId or
 *                     call rendererRef.highlightFaces([id]).
 * onToast           (msg) => void    — surface errors as toasts
 *
 * Result columns
 * --------------
 * Part A | Part B | Severity (depth mm or clash type) | Action (Jump to)
 */

import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, Loader2, ShieldAlert, ZapOff } from 'lucide-react'
import { api } from '../lib/api.js'

// Badge colour per clash type.
const CLASH_TYPE_CLASS = {
  hard: 'bg-red-500/20 text-red-300 border border-red-500/30',
  clearance: 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
  coincident: 'bg-purple-500/20 text-purple-300 border border-purple-500/30',
}

function ClashTypeBadge({ type }) {
  const cls = CLASH_TYPE_CLASS[type] || 'bg-ink-800 text-ink-300'
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono ${cls}`}>
      {type}
    </span>
  )
}

export default function ClashPanel({ projectId, assemblyFileId, onHighlight, onToast }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null) // { clashes, clash_count, errors }
  const [highlighted, setHighlighted] = useState(null)

  async function runCheck() {
    if (!projectId || !assemblyFileId) {
      onToast?.('No assembly file selected')
      return
    }
    setLoading(true)
    setResult(null)
    try {
      const data = await api.runClashDetect(projectId, assemblyFileId)
      setResult(data)
    } catch (err) {
      onToast?.(err?.message || 'Clash detection failed')
    } finally {
      setLoading(false)
    }
  }

  function jumpTo(componentId) {
    setHighlighted(componentId)
    onHighlight?.(componentId)
  }

  const clashCount = result?.clash_count ?? 0
  const hasClashes = clashCount > 0

  return (
    <div className="border-t border-ink-800 flex-shrink-0" data-testid="clash-panel">
      {/* Header row */}
      <div className="flex items-center px-3 py-1.5 gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 text-[11px] text-ink-400 hover:text-kerf-300 flex-1 min-w-0"
          aria-expanded={open}
          aria-controls="clash-panel-body"
          data-testid="clash-panel-toggle"
        >
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          <ShieldAlert size={12} className={hasClashes ? 'text-red-400' : 'text-ink-500'} />
          <span className="font-medium">Clashes</span>
          {result !== null && (
            <span className={`ml-1 px-1.5 py-0.5 rounded text-[10px] font-mono ${
              hasClashes ? 'bg-red-500/20 text-red-300' : 'bg-ink-800 text-ink-500'
            }`}>
              {clashCount}
            </span>
          )}
        </button>

        <button
          type="button"
          disabled={loading || !projectId || !assemblyFileId}
          onClick={runCheck}
          className="inline-flex items-center gap-1 px-2 py-1 rounded bg-ink-800 hover:bg-ink-700 text-[11px] text-ink-200 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70 flex-shrink-0"
          title="Run clash detection on this assembly"
          data-testid="clash-check-button"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <ZapOff size={11} />}
          Check Clashes
        </button>
      </div>

      {/* Body */}
      {open && (
        <div
          id="clash-panel-body"
          className="px-3 pb-3"
          data-testid="clash-panel-body"
        >
          {loading && (
            <div className="flex items-center gap-2 py-4 justify-center text-xs text-ink-400">
              <Loader2 size={14} className="animate-spin" />
              Detecting clashes…
            </div>
          )}

          {!loading && result === null && (
            <p className="text-[11px] text-ink-500 py-2">
              Click <strong className="text-ink-300">Check Clashes</strong> to run interference detection.
            </p>
          )}

          {!loading && result !== null && clashCount === 0 && (
            <div className="flex items-center gap-2 py-2 text-[11px] text-emerald-400">
              <ShieldAlert size={12} />
              No clashes found
            </div>
          )}

          {!loading && result !== null && clashCount > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]" data-testid="clash-table">
                <thead>
                  <tr className="text-ink-500 text-[10px] uppercase tracking-wider border-b border-ink-800">
                    <th className="text-left pb-1 pr-2 font-medium">Part A</th>
                    <th className="text-left pb-1 pr-2 font-medium">Part B</th>
                    <th className="text-left pb-1 pr-2 font-medium">Severity</th>
                    <th className="text-left pb-1 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {result.clashes.map((clash, i) => {
                    const isHighlighted = highlighted === clash.a || highlighted === clash.b
                    return (
                      <tr
                        key={`${clash.a}-${clash.b}-${i}`}
                        className={`border-b border-ink-900 ${isHighlighted ? 'bg-kerf-300/5' : ''}`}
                        data-testid="clash-row"
                      >
                        <td className="py-1 pr-2 font-mono text-ink-200 truncate max-w-[100px]" title={clash.a}>
                          {clash.a}
                        </td>
                        <td className="py-1 pr-2 font-mono text-ink-200 truncate max-w-[100px]" title={clash.b}>
                          {clash.b}
                        </td>
                        <td className="py-1 pr-2">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <ClashTypeBadge type={clash.type} />
                            {clash.type === 'hard' && (
                              <span className="text-[10px] text-red-300/70 font-mono">
                                {Math.abs(clash.depth).toFixed(2)} mm
                              </span>
                            )}
                            {clash.type === 'clearance' && (
                              <span className="text-[10px] text-amber-300/70 font-mono">
                                gap {clash.depth.toFixed(2)} mm
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-1">
                          <button
                            type="button"
                            onClick={() => jumpTo(clash.a)}
                            className="text-[10px] text-kerf-300 hover:underline mr-2 focus-visible:outline-none"
                            title={`Highlight ${clash.a} in viewport`}
                            data-testid="clash-jump-btn"
                          >
                            Jump to
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Non-fatal backend errors */}
          {result?.errors?.length > 0 && (
            <div className="mt-2 space-y-0.5">
              {result.errors.map((e, i) => (
                <div key={i} className="flex items-start gap-1 text-[10px] text-amber-400/80">
                  <AlertTriangle size={10} className="mt-0.5 flex-shrink-0" />
                  {e}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
