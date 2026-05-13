// ScriptEditor — read-only viewer for `.script.ts` files (the Phase 1 stub
// of the Scripting automation kind).
//
// File shape (mirrors the backend constraint shipped in
// 1746578200000_kind_script.sql): plain TypeScript source. The eventual
// engine (esbuild-wasm bundler in a Web Worker, typed `kerf.*` API, fixed-
// RPC backend ops) is deferred — this v1 only confirms the kind round-trips
// end-to-end so a future engine slice has a stable shape to write to.
//
// Mirrors SimulationView.jsx's "engine pending" pattern: a header strip, a
// monospace body, and an inline banner that names the missing runtime so a
// reader of the editor knows nothing is broken — the runtime just hasn't
// landed yet.
//
// Intentionally NOT wired:
//   - editContent path (read-only stub; bytes flow via the backend only)
//   - any TypeScript parsing beyond Monaco's built-in highlighting
//
// The Monaco binding here is intentionally minimal: read-only, TypeScript
// language, no extraLibs / compiler config. We don't reuse CodeEditor.jsx
// because that wrapper hard-codes `language="javascript"` and is tuned for
// the .jscad runtime; coupling the script viewer to it would force unrelated
// changes in a parallel slice. ~15 extra lines of @monaco-editor/react is
// the lighter contract.

import Editor from '@monaco-editor/react'
import { AlertTriangle, Code } from 'lucide-react'

const MONACO_OPTIONS = {
  readOnly: true,
  domReadOnly: true,
  minimap: { enabled: false },
  fontFamily: 'JetBrains Mono, Geist Mono, ui-monospace, SF Mono, Menlo, monospace',
  fontSize: 12,
  lineNumbers: 'on',
  scrollBeyondLastLine: false,
  renderLineHighlight: 'none',
  tabSize: 2,
  wordWrap: 'on',
  padding: { top: 8, bottom: 8 },
  automaticLayout: true,
}

export default function ScriptEditor({ content, fileName }) {
  const src = typeof content === 'string' ? content : ''

  return (
    <div className="h-full flex flex-col bg-ink-950 text-ink-100 min-h-0">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-ink-800 bg-ink-900/40 flex-shrink-0">
        <Code size={14} className="text-kerf-300 shrink-0" />
        <span className="text-xs font-semibold uppercase tracking-wider text-ink-300">
          Script
        </span>
        <span className="text-[11px] text-ink-500 truncate min-w-0">
          {fileName || ''}
        </span>
        <span className="ml-2 text-[10px] uppercase tracking-wider text-kerf-300 border border-kerf-300/40 rounded px-1.5 py-0.5">
          .script.ts
        </span>
      </div>

      <div className="px-4 py-3 border-b border-ink-800 bg-amber-950/20 flex-shrink-0">
        <div className="flex items-start gap-2 text-[11px] text-amber-200">
          <AlertTriangle size={12} className="text-amber-400 shrink-0 mt-0.5" />
          <div>
            <div className="font-medium text-amber-300">
              Engine pending — esbuild-wasm runtime not yet wired
            </div>
            <div className="text-amber-200/70 mt-0.5">
              The script kind round-trips today but is read-only in the
              editor. Bundler, typed <span className="font-mono">kerf.*</span> API,
              and backend RPC ops land in a follow-up slice.
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          theme="vs-dark"
          language="typescript"
          value={src}
          options={MONACO_OPTIONS}
        />
      </div>
    </div>
  )
}
