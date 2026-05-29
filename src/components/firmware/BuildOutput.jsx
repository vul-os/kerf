/**
 * BuildOutput.jsx — streaming compiler output panel.
 *
 * Tails the build job's stdout by calling POST /firmware/build (via
 * firmwareBridge.buildFirmware) and rendering the build_log that comes back.
 * For future streaming (SSE), the parent can pass lines directly via the
 * `lines` prop. When `lines` is provided the component is fully controlled;
 * otherwise it renders from internal state driven by the build result.
 *
 * Props:
 *   lines     {string[]}  — controlled: pre-split log lines to display
 *   running   {boolean}   — show the spinner when true
 *   error     {string|null} — error message to highlight at the top
 *   onClear   {function}  — callback when the user hits Clear
 *
 * The panel autoscrolls to the bottom as lines arrive (same pattern as
 * SerialMonitor). A "Clear" button and autoscroll toggle are provided.
 */

import { useEffect, useRef, useState } from 'react'
import { Terminal, X, ChevronsDown } from 'lucide-react'

export default function BuildOutput({
  lines = [],
  running = false,
  error = null,
  onClear = null,
}) {
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef(null)

  // Autoscroll whenever lines change and autoscroll is enabled.
  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [lines, autoScroll])

  return (
    <div
      className="flex flex-col h-full min-h-0 bg-ink-950 border border-ink-800 rounded-md overflow-hidden"
      data-testid="build-output"
    >
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-ink-800 bg-ink-900/60 flex-shrink-0">
        <Terminal size={12} className="text-kerf-300 flex-shrink-0" />
        <span className="text-[11px] text-ink-300 font-medium flex-1">Build output</span>
        {running && (
          <span className="text-[10px] text-kerf-300 font-mono animate-pulse">compiling…</span>
        )}
        <button
          type="button"
          title={autoScroll ? 'Disable autoscroll' : 'Enable autoscroll'}
          onClick={() => setAutoScroll((v) => !v)}
          className={`p-0.5 rounded transition-colors ${
            autoScroll
              ? 'text-kerf-300 bg-kerf-300/10'
              : 'text-ink-500 hover:text-ink-300'
          }`}
        >
          <ChevronsDown size={12} />
        </button>
        {onClear && (
          <button
            type="button"
            title="Clear output"
            onClick={onClear}
            className="p-0.5 rounded text-ink-500 hover:text-ink-300 transition-colors"
          >
            <X size={12} />
          </button>
        )}
      </div>

      {/* Log area */}
      <div className="flex-1 min-h-0 overflow-y-auto font-mono text-[11px] leading-relaxed p-2 space-y-0.5">
        {error && (
          <div className="mb-2 rounded bg-red-950/60 border border-red-700/40 px-2 py-1 text-red-300">
            {error}
          </div>
        )}
        {lines.length === 0 && !running && !error && (
          <span className="text-ink-600 italic">No output yet. Click Build to compile.</span>
        )}
        {lines.map((line, i) => {
          // Colour-code common compiler output patterns.
          let cls = 'text-ink-300'
          if (/\berror\b/i.test(line)) cls = 'text-red-300'
          else if (/\bwarning\b/i.test(line)) cls = 'text-amber-300'
          else if (/\bsuccess\b|\bDone\b|\bBuilding\b/i.test(line)) cls = 'text-emerald-300'
          return (
            <div key={i} className={cls}>
              {line || <span className="text-ink-700">&nbsp;</span>}
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
