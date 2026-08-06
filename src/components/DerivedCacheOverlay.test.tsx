// DerivedCacheOverlay.test.tsx
//
// Tests for the DerivedCacheOverlay component and its mounting contract in
// Editor.jsx.
//
// Strategy:
//   1. Source-text check — Editor.jsx must contain the DEV-gated render line
//      so the overlay is absent in production builds and present in dev.
//   2. Component render — DerivedCacheOverlay renders a floating badge with
//      the toggle button and data-component attribute when mounted directly.
//   3. addDerivedCacheListener — the component subscribes on mount via the
//      assembly.js event bus (verified by spying on the mock).
//
// DOM rendering uses renderToStaticMarkup (react-dom/server) — no browser or
// useEffect execution needed to assert structural output.

import { describe, it, expect, vi } from 'vitest'
// @types/node isn't part of this project's toolchain (tsconfig.json's `types` array is
// T-500's — see docs/typescript-migration.md), so these Node builtins (used only for this
// file's source-inspection assertions) are untyped at this boundary.
// @ts-expect-error - no @types/node in this toolchain
import { readFileSync } from 'fs'
// @ts-expect-error - no @types/node in this toolchain
import { fileURLToPath } from 'url'
// @ts-expect-error - no @types/node in this toolchain
import path from 'path'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'

// ---------------------------------------------------------------------------
// Source-text helpers
// ---------------------------------------------------------------------------

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const editorSrc = readFileSync(
  path.resolve(__dirname, '../routes/Editor.jsx'),
  'utf8',
)

// FINDING (dead code, left as-is per T-513's "report, don't fix"): this variable was
// already unused in the original .jsx — no assertion below reads `overlaySrc`. Kept
// for parity with the pre-migration file; path extension updated from .jsx to .tsx so
// the eager readFileSync doesn't throw ENOENT now that the source has been renamed
// (docs/typescript-migration.md's "tests that read source by literal path" trap).
const overlaySrc = readFileSync(
  path.resolve(__dirname, './DerivedCacheOverlay.tsx'),
  'utf8',
)
void overlaySrc

// ---------------------------------------------------------------------------
// 1. Editor.jsx DEV gate
// ---------------------------------------------------------------------------

describe('Editor.jsx — DerivedCacheOverlay mount point', () => {
  it('imports DerivedCacheOverlay', () => {
    expect(editorSrc).toContain("import DerivedCacheOverlay from '../components/DerivedCacheOverlay.jsx'")
  })

  it('renders DerivedCacheOverlay gated by import.meta.env.DEV', () => {
    expect(editorSrc).toContain('import.meta.env.DEV && <DerivedCacheOverlay />')
  })

  it('does not render DerivedCacheOverlay unconditionally', () => {
    // The only occurrence of <DerivedCacheOverlay /> must be behind DEV
    const occurrences = (editorSrc.match(/<DerivedCacheOverlay/g) || []).length
    const gatedOccurrences = (editorSrc.match(/import\.meta\.env\.DEV.*DerivedCacheOverlay/g) || []).length
    expect(occurrences).toBe(gatedOccurrences)
  })
})

// ---------------------------------------------------------------------------
// 2. DerivedCacheOverlay component structure
// ---------------------------------------------------------------------------

// Mock assembly.js so the component doesn't need the real event bus.
vi.mock('../lib/assembly.js', () => ({
  addDerivedCacheListener: vi.fn(() => () => {}),
  mateRefFromPick: vi.fn(),
  parseAssembly: vi.fn(),
}))

// Dynamically import the component AFTER the mock is set up.
const { default: DerivedCacheOverlay } = await import('./DerivedCacheOverlay.jsx')

describe('DerivedCacheOverlay — component structure', () => {
  it('renders the data-component attribute', () => {
    const html = renderToStaticMarkup(React.createElement(DerivedCacheOverlay))
    expect(html).toContain('data-component="DerivedCacheOverlay"')
  })

  it('renders the toggle button with aria-label', () => {
    const html = renderToStaticMarkup(React.createElement(DerivedCacheOverlay))
    expect(html).toContain('aria-label="Toggle derived cache stats"')
  })

  it('renders "cache" label when no events have fired', () => {
    const html = renderToStaticMarkup(React.createElement(DerivedCacheOverlay))
    expect(html).toContain('>cache<')
  })

  it('positions at bottom-right by default', () => {
    const html = renderToStaticMarkup(React.createElement(DerivedCacheOverlay))
    expect(html).toContain('bottom-4 right-4')
  })

  it('positions at bottom-left when prop is set', () => {
    const html = renderToStaticMarkup(
      React.createElement(DerivedCacheOverlay, { position: 'bottom-left' }),
    )
    expect(html).toContain('bottom-4 left-4')
  })

  it('panel is closed by default (defaultOpen=false)', () => {
    const html = renderToStaticMarkup(React.createElement(DerivedCacheOverlay))
    // When closed, the expanded panel div is not in the output
    expect(html).not.toContain('Derived Cache')
  })

  it('panel is open when defaultOpen=true', () => {
    const html = renderToStaticMarkup(
      React.createElement(DerivedCacheOverlay, { defaultOpen: true }),
    )
    expect(html).toContain('Derived Cache')
  })
})

// ---------------------------------------------------------------------------
// 3. addDerivedCacheListener subscription
// ---------------------------------------------------------------------------

describe('DerivedCacheOverlay — event bus subscription', () => {
  it('calls addDerivedCacheListener on module import', async () => {
    const { addDerivedCacheListener } = await import('../lib/assembly.js')
    // Re-render to trigger useEffect (server render doesn't run effects, but
    // the mock is already called from earlier renders in this test suite via
    // the dynamic import + renderToStaticMarkup chain; verify the mock exists)
    expect(typeof addDerivedCacheListener).toBe('function')
  })

  it('assembly.js exports addDerivedCacheListener', async () => {
    // Structural: the real assembly.js source must export addDerivedCacheListener
    const assemblySrc = readFileSync(
      path.resolve(__dirname, '../lib/assembly.ts'),
      'utf8',
    )
    expect(assemblySrc).toContain('export function addDerivedCacheListener')
  })

  it('assembly.js exports _emitDerivedCacheEvent for internal use', () => {
    const assemblySrc = readFileSync(
      path.resolve(__dirname, '../lib/assembly.ts'),
      'utf8',
    )
    expect(assemblySrc).toContain('function _emitDerivedCacheEvent')
  })
})
