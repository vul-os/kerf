// newFileDialog.test.js — task #207: the FileTree "+ New" long dropdown
// is now a friendly, searchable, responsive DIALOG offering every
// canonical kind + an Import group. Source-level assertions (matches the
// repo's existing FileTree test style) plus a catalog-parity check so a
// kind in KIND_ORDER can never render a blank card.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(
  path.resolve(__dirname, '../components/FileTree.jsx'), 'utf8',
)

describe('New file: dialog (not dropdown)', () => {
  it('renders an accessible modal dialog', () => {
    expect(src).toContain('role="dialog"')
    expect(src).toContain('aria-modal="true"')
    expect(src).toContain('aria-label="New file"')
  })

  it('dropped the old absolute dropdown panel', () => {
    expect(src).not.toContain('absolute right-0 top-full')
    expect(src).not.toContain('function CreateRow')
  })

  it('has a search filter', () => {
    expect(src).toContain('Search file types')
    expect(src).toMatch(/searchRef/)
  })

  it('is responsive + scrollable', () => {
    expect(src).toContain('grid-cols-2 sm:grid-cols-3')
    expect(src).toContain('max-h-[80vh]')
    expect(src).toContain('overflow-y-auto')
  })

  it('closes on Escape and backdrop click', () => {
    expect(src).toMatch(/key === 'Escape'/)
    expect(src).toMatch(/onClick=\{close\}/)
  })
})

describe('New file: full kind catalog', () => {
  const orderMatch = src.match(/const KIND_ORDER = \[([^\]]*)\]/)
  const rowsMatch = src.match(/const KIND_ROWS = \{([\s\S]*?)\n\}/)

  it('KIND_ORDER and KIND_ROWS are present', () => {
    expect(orderMatch).toBeTruthy()
    expect(rowsMatch).toBeTruthy()
  })

  it('every ordered kind has a catalog row (no blank cards)', () => {
    const order = [...orderMatch[1].matchAll(/'([a-z_]+)'/g)].map((m) => m[1])
    const rowKeys = new Set(
      [...rowsMatch[1].matchAll(/^\s*([a-z_]+):\s*\{/gm)].map((m) => m[1]),
    )
    expect(order.length).toBeGreaterThanOrEqual(15)
    const missing = order.filter((k) => !rowKeys.has(k))
    expect(missing, `KIND_ORDER ids with no KIND_ROWS entry: ${missing}`).toEqual([])
  })

  it('offers an Import group (STEP / KiCad / FreeCAD)', () => {
    expect(src).toContain('IMPORT_ROWS')
    for (const id of ['__step', '__kicad', '__freecad']) {
      expect(src).toContain(`'${id}'`)
    }
  })
})
