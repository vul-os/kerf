// FileEditor.jsx — editable plain-text / code view for common file extensions.
//
// Wraps @monaco-editor/react with the Monaco language ID resolved from the
// file's extension via src/lib/editorModes.js.  No WASM, no LSP — Monaco's
// built-in regex-based tokenizers provide "good enough" syntax colouring for
// T-116 (proper per-language intelligence is a later task).
//
// Props:
//   content    {string}             Current file text.
//   fileName   {string}             File name (used to resolve the language ID).
//   onChange   {(string) => void}   Called on every edit (round-trips through
//                                   the existing workspace save path).

import { useCallback } from 'react'
import MonacoEditor from '@monaco-editor/react'
import type { OnMount } from '@monaco-editor/react'
import type { editor as MonacoEditorNs } from 'monaco-editor'
import { useWorkspace } from '../store/workspace.js'
import { getEditorMode } from '../lib/editorModes.js'

const OPTIONS: MonacoEditorNs.IStandaloneEditorConstructionOptions = {
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

export interface FileEditorProps {
  /** Current file text. */
  content?: string
  /** File name (used to resolve the language ID). */
  fileName?: string
  /** Called on every edit (round-trips through the existing workspace save path). */
  onChange?: (value: string) => void
}

export default function FileEditor({ content, fileName, onChange }: FileEditorProps) {
  const language = getEditorMode(fileName || '') || 'plaintext'

  // Track Monaco focus on the workspace store so the global Cmd+Z handler
  // yields to Monaco's buffer-undo while the editor has focus.
  const handleMount: OnMount = useCallback((editor) => {
    const set = (focused: boolean) => useWorkspace.getState().setEditorFocused(focused)
    editor.onDidFocusEditorText(() => set(true))
    editor.onDidBlurEditorText(() => set(false))
  }, [])

  return (
    <div className="flex flex-col h-full bg-ink-900">
      <MonacoEditor
        height="100%"
        theme="vs-dark"
        language={language}
        value={content ?? ''}
        onChange={(v) => onChange?.(v ?? '')}
        options={OPTIONS}
        onMount={handleMount}
      />
    </div>
  )
}
