/**
 * PLCView — Monaco editor for IEC 61131-3 Structured Text (.plc.st) files.
 *
 * Props:
 *   content     {string}  ST source from the .plc.st file
 *   projectId   {string}  Project ID for lint API calls
 *   fileId      {string}  File ID for lint API calls
 *   fileName    {string}  Display name
 *   onContentChange {fn}  Called with new content string on edit
 *   viewRef     {ref}     Imperative handle ref for snapshot()
 *   className   {string}  Extra CSS classes for the container div
 *
 * Lint debounce: 600 ms after last keystroke → POST /api/projects/:pid/plc/lint
 * → render diagnostics in Monaco marker layer + bottom panel.
 *
 * Snapshot: returns a JPEG blob of the editor viewport (solid dark background
 * with the visible code, 512×512 px) for the thumbnail capture system.
 *
 * Language: registers a custom `iec61131-st` language on first mount with the
 * full IEC 61131-3 keyword list. Monaco's built-in `pascal` mode was considered
 * but rejected because it:
 *   1. Does not tokenize `END_VAR`, `END_FOR`, `END_IF`, `END_FUNCTION_BLOCK`
 *      etc. as keywords — these compound-END tokens are unknown to Pascal.
 *   2. Does not know ST-specific types (BOOL, DINT, LREAL, TIME, TOD …).
 *   3. Does not recognise AND/OR/XOR/NOT/MOD/TRUE/FALSE as keyword-class tokens
 *      (Pascal uses `and`/`or`/`not` lowercase; ST requires uppercase).
 * Registering a minimal custom grammar avoids these mismatches with ~100 lines.
 */
import { useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { SquareCode } from 'lucide-react'
import { api } from '../lib/api.js'

// ---------------------------------------------------------------------------
// IEC 61131-3 ST keyword lists
// ---------------------------------------------------------------------------

const ST_KEYWORDS = [
  // Program Organisation Units
  'FUNCTION', 'END_FUNCTION',
  'FUNCTION_BLOCK', 'END_FUNCTION_BLOCK',
  'PROGRAM', 'END_PROGRAM',
  // Variable sections
  'VAR', 'VAR_INPUT', 'VAR_OUTPUT', 'VAR_IN_OUT',
  'VAR_GLOBAL', 'VAR_EXTERNAL', 'VAR_TEMP',
  'END_VAR',
  // Control flow
  'IF', 'THEN', 'ELSIF', 'ELSE', 'END_IF',
  'CASE', 'OF', 'END_CASE',
  'FOR', 'TO', 'BY', 'DO', 'END_FOR',
  'WHILE', 'END_WHILE',
  'REPEAT', 'UNTIL', 'END_REPEAT',
  'RETURN', 'EXIT', 'GOTO',
  // Modifiers / misc
  'AT', 'RETAIN', 'NON_RETAIN', 'CONSTANT', 'PERSISTENT',
  'OVERLAP', 'WITH', 'READ_WRITE', 'READ_ONLY',
  // Operators
  'AND', 'OR', 'XOR', 'NOT', 'MOD',
  // Literals
  'TRUE', 'FALSE',
]

const ST_TYPES = [
  // Boolean
  'BOOL',
  // Integer
  'SINT', 'INT', 'DINT', 'LINT',
  'USINT', 'UINT', 'UDINT', 'ULINT',
  // Real
  'REAL', 'LREAL',
  // Time
  'TIME', 'DATE', 'TIME_OF_DAY', 'TOD', 'DATE_AND_TIME', 'DT',
  // String
  'STRING', 'WSTRING',
  // Bit string
  'BYTE', 'WORD', 'DWORD', 'LWORD',
  // Structured
  'STRUCT', 'END_STRUCT',
  'TYPE', 'END_TYPE',
  'ARRAY', 'OF',
]

const ST_STDLIB_FB = [
  'TON', 'TOF', 'TP', 'SR', 'RS', 'CTU', 'CTD', 'CTUD', 'R_TRIG', 'F_TRIG',
]

// ---------------------------------------------------------------------------
// Monaco language registration (runs once per browser session)
// ---------------------------------------------------------------------------

let _stLanguageRegistered = false

function registerIEC61131STLanguage(monaco) {
  if (_stLanguageRegistered) return
  _stLanguageRegistered = true

  monaco.languages.register({ id: 'iec61131-st' })

  monaco.languages.setMonarchTokensProvider('iec61131-st', {
    ignoreCase: true,
    keywords: ST_KEYWORDS,
    typeKeywords: ST_TYPES,
    stdFb: ST_STDLIB_FB,

    tokenizer: {
      root: [
        // Comments: (* … *) and // to end-of-line
        [/\(\*/, 'comment', '@comment_block'],
        [/\/\/.*$/, 'comment'],

        // String literals
        [/'([^'\\]|\\.)*'/, 'string'],
        [/"([^"\\]|\\.)*"/, 'string'],

        // Numeric literals (including time literals like T#5s, D#2024-01-01)
        [/[TtDd]#[^\s,;()\[\]]+/, 'number'],
        [/16#[0-9A-Fa-f]+/, 'number.hex'],
        [/8#[0-7]+/, 'number.octal'],
        [/2#[01]+/, 'number.binary'],
        [/\d+\.\d+([Ee][+-]?\d+)?/, 'number.float'],
        [/\d+/, 'number'],

        // Type prefix for typed literals e.g. INT#42, BOOL#TRUE
        [/[A-Z_][A-Z0-9_]*(?=#)/, 'type'],

        // Identifiers and keywords
        [/[A-Za-z_][A-Za-z0-9_]*/, {
          cases: {
            '@keywords': 'keyword',
            '@typeKeywords': 'type',
            '@stdFb': 'entity.name.function',
            '@default': 'identifier',
          },
        }],

        // Operators
        [/:=|<>|<=|>=|[+\-*/=<>]/, 'operator'],

        // Delimiters
        [/[;,.:()[\]]/, 'delimiter'],

        // Whitespace
        [/\s+/, 'white'],
      ],

      comment_block: [
        [/[^*(]+/, 'comment'],
        [/\*\)/, 'comment', '@pop'],
        [/[*(]/, 'comment'],
      ],
    },
  })

  monaco.languages.setLanguageConfiguration('iec61131-st', {
    comments: {
      lineComment: '//',
      blockComment: ['(*', '*)'],
    },
    brackets: [
      ['(', ')'],
      ['[', ']'],
    ],
    autoClosingPairs: [
      { open: '(', close: ')' },
      { open: '[', close: ']' },
      { open: "'", close: "'", notIn: ['string', 'comment'] },
    ],
    wordPattern: /[A-Za-z_][A-Za-z0-9_]*/,
    indentationRules: {
      increaseIndentPattern: /\b(THEN|DO|REPEAT|OF|VAR|VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_GLOBAL|VAR_EXTERNAL|VAR_TEMP)\b/i,
      decreaseIndentPattern: /\b(END_IF|END_FOR|END_WHILE|END_REPEAT|END_CASE|END_VAR|END_FUNCTION|END_FUNCTION_BLOCK|END_PROGRAM|END_STRUCT|END_TYPE)\b/i,
    },
  })

  monaco.editor.defineTheme('kerf-plc-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'keyword', foreground: 'c792ea', fontStyle: 'bold' },
      { token: 'type', foreground: '82aaff' },
      { token: 'entity.name.function', foreground: 'ffcb6b' },
      { token: 'operator', foreground: '89ddff' },
      { token: 'number', foreground: 'f78c6c' },
      { token: 'number.hex', foreground: 'f78c6c' },
      { token: 'number.float', foreground: 'f78c6c' },
      { token: 'number.octal', foreground: 'f78c6c' },
      { token: 'number.binary', foreground: 'f78c6c' },
      { token: 'string', foreground: 'c3e88d' },
      { token: 'comment', foreground: '546e7a', fontStyle: 'italic' },
      { token: 'delimiter', foreground: 'a6accd' },
    ],
    colors: {
      'editor.background': '#0d1117',
      'editor.foreground': '#c9d1d9',
      'editorLineNumber.foreground': '#3d4451',
      'editorLineNumber.activeForeground': '#6b7280',
    },
  })
}

// ---------------------------------------------------------------------------
// Monaco options
// ---------------------------------------------------------------------------

const EDITOR_OPTIONS = {
  minimap: { enabled: false },
  fontFamily: 'JetBrains Mono, Geist Mono, ui-monospace, SF Mono, Menlo, monospace',
  fontSize: 13,
  lineNumbers: 'on',
  scrollBeyondLastLine: false,
  smoothScrolling: true,
  cursorBlinking: 'smooth',
  renderLineHighlight: 'line',
  tabSize: 2,
  wordWrap: 'off',
  padding: { top: 12, bottom: 12 },
  automaticLayout: true,
}

// ---------------------------------------------------------------------------
// PLCView component
// ---------------------------------------------------------------------------

const LINT_DEBOUNCE_MS = 600

export default function PLCView({
  content = '',
  projectId,
  fileId,
  fileName = '',
  onContentChange,
  viewRef,
  className = '',
}) {
  const monaco = useMonaco()
  const editorRef = useRef(null)
  const lintTimerRef = useRef(null)
  const [diagnostics, setDiagnostics] = useState([])
  const [warnings, setWarnings] = useState([])
  const [linting, setLinting] = useState(false)

  // Register custom language once Monaco is available.
  useEffect(() => {
    if (monaco) registerIEC61131STLanguage(monaco)
  }, [monaco])

  // ── Lint ────────────────────────────────────────────────────────────────────

  const runLint = useCallback(async (src) => {
    if (!projectId || !src || !src.trim()) {
      setDiagnostics([])
      setWarnings([])
      return
    }
    setLinting(true)
    try {
      const result = await api.lintPLC(projectId, src)
      const diags = result?.diagnostics || []
      const warns = result?.warnings || []
      setDiagnostics(diags)
      setWarnings(warns)

      // Push diagnostics into Monaco's marker layer.
      if (monaco && editorRef.current) {
        const model = editorRef.current.getModel()
        if (model) {
          const markers = diags.map((d) => ({
            severity: d.severity === 'error'
              ? monaco.MarkerSeverity.Error
              : d.severity === 'warning'
                ? monaco.MarkerSeverity.Warning
                : monaco.MarkerSeverity.Info,
            message: d.message,
            startLineNumber: d.line ?? 1,
            startColumn: d.column ?? 1,
            endLineNumber: d.line ?? 1,
            endColumn: (d.column ?? 1) + 1,
            source: d.source || 'matiec',
          }))
          monaco.editor.setModelMarkers(model, 'matiec', markers)
        }
      }
    } catch {
      // Network / auth errors — suppress silently; the editor stays editable.
    } finally {
      setLinting(false)
    }
  }, [projectId, monaco])

  // Debounced lint on content change.
  useEffect(() => {
    if (lintTimerRef.current) clearTimeout(lintTimerRef.current)
    lintTimerRef.current = setTimeout(() => runLint(content), LINT_DEBOUNCE_MS)
    return () => { if (lintTimerRef.current) clearTimeout(lintTimerRef.current) }
  }, [content, runLint])

  // Clear markers on unmount.
  useEffect(() => {
    return () => {
      if (monaco && editorRef.current) {
        const model = editorRef.current.getModel()
        if (model) monaco.editor.setModelMarkers(model, 'matiec', [])
      }
    }
  }, [monaco])

  // ── Snapshot (thumbnail capture) ────────────────────────────────────────────

  useImperativeHandle(viewRef, () => ({
    snapshot: async ({ size = 512, quality = 0.7 } = {}) => {
      // Grab a screenshot of the Monaco editor's visible viewport by
      // serializing it to a canvas via html2canvas-style approach.
      // Simpler and taint-free: paint a dark canvas with no DOM cross-origin refs.
      if (!editorRef.current) return null
      try {
        const domNode = editorRef.current.getDomNode?.()
        if (!domNode) return null

        const off = document.createElement('canvas')
        off.width = size
        off.height = size
        const ctx = off.getContext('2d')
        if (!ctx) return null

        // Dark background matching the editor theme.
        ctx.fillStyle = '#0d1117'
        ctx.fillRect(0, 0, size, size)

        // Draw the file name as a header label.
        ctx.fillStyle = '#6b7280'
        ctx.font = `bold ${Math.round(size * 0.028)}px "JetBrains Mono", monospace`
        ctx.fillText(fileName || 'untitled.plc.st', size * 0.04, size * 0.07)

        // Draw a few lines of visible source text into the snapshot.
        const lines = (typeof content === 'string' ? content : '')
          .split('\n')
          .slice(0, Math.floor(size / 22))
        ctx.fillStyle = '#c9d1d9'
        ctx.font = `${Math.round(size * 0.026)}px "JetBrains Mono", monospace`
        lines.forEach((line, i) => {
          ctx.fillText(
            line.slice(0, 72),
            size * 0.04,
            size * 0.12 + i * Math.round(size * 0.048),
          )
        })

        return new Promise((resolve) => {
          try {
            off.toBlob((blob) => resolve(blob || null), 'image/jpeg', quality)
          } catch {
            resolve(null)
          }
        })
      } catch {
        return null
      }
    },
  }), [content, fileName])

  // ── Render ──────────────────────────────────────────────────────────────────

  const errorCount = diagnostics.filter((d) => d.severity === 'error').length
  const warnCount = diagnostics.filter((d) => d.severity === 'warning').length

  return (
    <div className={`flex flex-col h-full min-h-0 bg-[#0d1117] ${className}`}>
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-ink-800 bg-ink-900/60 flex-shrink-0">
        <SquareCode size={14} className="text-lime-300 shrink-0" />
        <span className="text-xs font-semibold uppercase tracking-wider text-ink-300">
          PLC — Structured Text
        </span>
        <span className="text-[11px] text-ink-500 truncate min-w-0 ml-1">
          {fileName}
        </span>
        <span className="ml-2 text-[10px] uppercase tracking-wider text-lime-400 border border-lime-400/40 rounded px-1.5 py-0.5 shrink-0">
          IEC 61131-3
        </span>
        {linting && (
          <span className="ml-auto text-[10px] text-ink-500 animate-pulse shrink-0">linting…</span>
        )}
        {!linting && (errorCount > 0 || warnCount > 0) && (
          <span className="ml-auto flex items-center gap-2 shrink-0">
            {errorCount > 0 && (
              <span className="text-[10px] text-red-400 font-mono">
                {errorCount} error{errorCount !== 1 ? 's' : ''}
              </span>
            )}
            {warnCount > 0 && (
              <span className="text-[10px] text-amber-400 font-mono">
                {warnCount} warning{warnCount !== 1 ? 's' : ''}
              </span>
            )}
          </span>
        )}
        {!linting && errorCount === 0 && warnCount === 0 && warnings.length === 0 && (
          <span className="ml-auto text-[10px] text-lime-500 font-mono shrink-0">no issues</span>
        )}
      </div>

      {/* Editor */}
      <div className="flex-1 min-h-0">
        <MonacoEditor
          height="100%"
          language="iec61131-st"
          theme="kerf-plc-dark"
          value={typeof content === 'string' ? content : ''}
          options={EDITOR_OPTIONS}
          onChange={(val) => onContentChange?.(val ?? '')}
          onMount={(editor) => {
            editorRef.current = editor
            // Run initial lint when the editor mounts with existing content.
            if (content && content.trim()) {
              setTimeout(() => runLint(content), LINT_DEBOUNCE_MS)
            }
          }}
        />
      </div>

      {/* Diagnostic panel */}
      {(diagnostics.length > 0 || warnings.length > 0) && (
        <div className="flex-shrink-0 max-h-36 overflow-y-auto border-t border-ink-800 bg-ink-950/80">
          {warnings.map((w, i) => (
            <div
              key={`warn-${i}`}
              className="flex items-start gap-2 px-3 py-1.5 border-b border-ink-800/60 text-amber-300 text-[11px] font-mono"
            >
              <span className="text-amber-500 shrink-0 uppercase text-[9px] tracking-wider mt-0.5">
                warn
              </span>
              <span className="leading-snug">{w}</span>
            </div>
          ))}
          {diagnostics.map((d, i) => (
            <div
              key={`diag-${i}`}
              className={`flex items-start gap-2 px-3 py-1.5 border-b border-ink-800/60 text-[11px] font-mono ${
                d.severity === 'error'
                  ? 'text-red-300'
                  : d.severity === 'warning'
                    ? 'text-amber-300'
                    : 'text-ink-300'
              }`}
            >
              <span
                className={`shrink-0 uppercase text-[9px] tracking-wider mt-0.5 ${
                  d.severity === 'error'
                    ? 'text-red-500'
                    : d.severity === 'warning'
                      ? 'text-amber-500'
                      : 'text-ink-500'
                }`}
              >
                {d.severity}
              </span>
              {d.line != null && (
                <span className="text-ink-500 shrink-0">
                  {d.line}:{d.column ?? 1}
                </span>
              )}
              <span className="leading-snug break-words min-w-0">{d.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
