// scriptEditorCopy.test.js — the script-file panel must not lie about
// being "read-only" (Monaco is readOnly:false and onChange persists),
// and must tell the user how to get the 3D viewport back (selecting a
// script swaps the main pane by file kind — the model isn't lost).

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(
  path.resolve(__dirname, '../components/ScriptEditor.jsx'), 'utf8',
)

describe('ScriptEditor copy', () => {
  it('does not falsely claim in-app editing is read-only', () => {
    expect(src).not.toMatch(/read-only stub/i)
    expect(src).not.toMatch(/script editing is read-only/i)
  })

  it('states it is editable and saved', () => {
    expect(src).toMatch(/Editable here/i)
  })

  it('notes the 3D model renders in the viewport above (split layout)', () => {
    expect(src).toMatch(/3D model renders in the viewport above/i)
  })

  it('keeps the Monaco editor writable', () => {
    expect(src).toContain('readOnly: false')
  })
})
