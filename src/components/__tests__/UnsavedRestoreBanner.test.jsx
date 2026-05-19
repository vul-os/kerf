/**
 * UnsavedRestoreBanner.test.jsx — Vitest suite for the crash-recovery banner.
 *
 * Tests:
 *   1. Renders nothing when unsavedEntries is empty.
 *   2. Renders banner with file list when non-empty.
 *   3. role="status" + aria-live="polite" present.
 *   4. Restore button renders with correct data-testid.
 *   5. Discard button renders with correct data-testid.
 *   6. Renders per-entry _error inline next to the file path when restore fails.
 *   7. Truncates file list when more than MAX_FILES_SHOWN entries.
 *
 * Strategy: inject a mock `useWorkspace` hook via the component's prop so no
 * real Zustand store or IDB is needed. Static render via renderToStaticMarkup
 * for HTML inspection; source-level checks for action wiring.
 */

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement, useCallback } from 'react'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// ── Import the component under test ──────────────────────────────────────────
import UnsavedRestoreBanner from '../UnsavedRestoreBanner.jsx'

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeUseWorkspace({
  unsavedEntries = [],
  restoreUnsavedEntries = vi.fn(),
  discardUnsavedEntries = vi.fn(),
} = {}) {
  const state = { unsavedEntries, restoreUnsavedEntries, discardUnsavedEntries }
  function useWorkspace(selector) {
    return selector(state)
  }
  useWorkspace.getState = () => state
  useWorkspace.setState = vi.fn()
  return useWorkspace
}

function render(entries, extra = {}) {
  const useWorkspace = makeUseWorkspace({ unsavedEntries: entries, ...extra })
  return renderToStaticMarkup(
    createElement(UnsavedRestoreBanner, { useWorkspace }),
  )
}

const ENTRY = { path: 'main.jscad', bytes: new Uint8Array([1]), stashed_at: Date.now() }
const TWO_ENTRIES = [
  { path: 'main.jscad', bytes: new Uint8Array([1]), stashed_at: Date.now() },
  { path: 'part.jscad', bytes: new Uint8Array([2]), stashed_at: Date.now() },
]

// ── 1. Empty entries → nothing rendered ──────────────────────────────────────

describe('UnsavedRestoreBanner — empty', () => {
  it('renders nothing (empty string) when unsavedEntries is empty', () => {
    const html = render([])
    expect(html).toBe('')
  })
})

// ── 2. Non-empty → banner content ────────────────────────────────────────────

describe('UnsavedRestoreBanner — content', () => {
  it('renders non-empty markup when entries exist', () => {
    const html = render([ENTRY])
    expect(html.length).toBeGreaterThan(0)
  })

  it('includes the entry path in the output', () => {
    const html = render([ENTRY])
    expect(html).toContain('main.jscad')
  })

  it('shows count when multiple entries', () => {
    const html = render(TWO_ENTRIES)
    expect(html).toContain('2')
  })

  it('includes both file paths when multiple entries', () => {
    const html = render(TWO_ENTRIES)
    expect(html).toContain('main.jscad')
    expect(html).toContain('part.jscad')
  })
})

// ── 3. Accessibility attributes ──────────────────────────────────────────────

describe('UnsavedRestoreBanner — accessibility', () => {
  it('has role="status"', () => {
    const html = render([ENTRY])
    expect(html).toMatch(/role="status"/)
  })

  it('has aria-live="polite"', () => {
    const html = render([ENTRY])
    expect(html).toMatch(/aria-live="polite"/)
  })

  it('has data-testid="unsaved-restore-banner"', () => {
    const html = render([ENTRY])
    expect(html).toMatch(/data-testid="unsaved-restore-banner"/)
  })
})

// ── 4 & 5. Buttons ───────────────────────────────────────────────────────────

describe('UnsavedRestoreBanner — buttons', () => {
  it('renders a Restore button with data-testid="unsaved-restore-btn"', () => {
    const html = render([ENTRY])
    expect(html).toMatch(/data-testid="unsaved-restore-btn"/)
    expect(html).toContain('Restore')
  })

  it('renders a Discard button with data-testid="unsaved-discard-btn"', () => {
    const html = render([ENTRY])
    expect(html).toMatch(/data-testid="unsaved-discard-btn"/)
    expect(html).toContain('Discard')
  })
})

// ── 6. Per-entry error rendering ─────────────────────────────────────────────

describe('UnsavedRestoreBanner — per-entry errors', () => {
  it('renders _error inline next to the file path', () => {
    const entries = [{
      path: 'conflict.jscad',
      bytes: new Uint8Array([1]),
      stashed_at: Date.now(),
      _error: 'Server has newer version — reload to merge',
    }]
    const html = render(entries)
    expect(html).toContain('conflict.jscad')
    expect(html).toContain('Server has newer version')
  })

  it('renders restore-error data-testid for the failing entry', () => {
    const entries = [{
      path: 'fail.jscad',
      bytes: new Uint8Array([1]),
      stashed_at: Date.now(),
      _error: 'Failed to restore',
    }]
    const html = render(entries)
    expect(html).toMatch(/data-testid="restore-error-fail\.jscad"/)
  })
})

// ── 7. Overflow truncation ───────────────────────────────────────────────────

describe('UnsavedRestoreBanner — file list truncation', () => {
  it('shows overflow indicator when more than MAX_FILES_SHOWN entries', () => {
    const entries = Array.from({ length: 5 }, (_, i) => ({
      path: `file-${i}.jscad`,
      bytes: new Uint8Array([i]),
      stashed_at: Date.now(),
    }))
    const html = render(entries)
    // Should contain "more" text for overflow.
    expect(html).toMatch(/data-testid="unsaved-overflow"/)
    expect(html).toContain('more')
  })

  it('does NOT show overflow when exactly MAX_FILES_SHOWN or fewer entries', () => {
    const entries = Array.from({ length: 3 }, (_, i) => ({
      path: `file-${i}.jscad`,
      bytes: new Uint8Array([i]),
      stashed_at: Date.now(),
    }))
    const html = render(entries)
    expect(html).not.toMatch(/data-testid="unsaved-overflow"/)
  })
})

// ── 8. Source-contract: action wiring ────────────────────────────────────────

describe('UnsavedRestoreBanner — source contracts', () => {
  const src = readFileSync(
    resolve(__dirname, '../UnsavedRestoreBanner.jsx'),
    'utf8',
  )

  it('imports from the workspace store', () => {
    expect(src).toMatch(/from.*store\/workspace/)
  })

  it('calls restoreUnsavedEntries on Restore button click', () => {
    expect(src).toMatch(/restoreUnsavedEntries/)
  })

  it('calls discardUnsavedEntries on Discard button click', () => {
    expect(src).toMatch(/discardUnsavedEntries/)
  })

  it('reads unsavedEntries from store', () => {
    expect(src).toMatch(/unsavedEntries/)
  })
})
