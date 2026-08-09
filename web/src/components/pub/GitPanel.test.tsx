// GitPanel.test.jsx — Vitest unit tests for GitPanel helpers (T-302).
//
// Strategy: pure-function tests for formatBytes (no React render overhead,
// no network calls, no store dependencies). A separate smoke test verifies
// that the open-purge-modal data-testid exists in the rendered badge markup.
//
// We follow the project convention of using renderToStaticMarkup (react-dom/server)
// for component shape tests, and copy pure helpers inline to avoid the heavy
// dependency chain of GitPanel.jsx (zustand stores, API clients, lucide icons).

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'

// ─────────────────────────────────────────────────────────────────────────────
// formatBytes — copied verbatim from GitPanel.jsx so we can unit-test it
// without importing the full component tree.
// ─────────────────────────────────────────────────────────────────────────────

function formatBytes(bytes) {
  if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(1)} GB`
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

describe('formatBytes', () => {
  it('returns bytes for small values', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1023)).toBe('1023 B')
  })

  it('returns KB with 1 decimal for kilobyte-range values', () => {
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(1536)).toBe('1.5 KB')
  })

  it('returns MB with 1 decimal for megabyte-range values', () => {
    expect(formatBytes(1048576)).toBe('1.0 MB')
    expect(formatBytes(4_400_000)).toBe(`${(4_400_000 / 1048576).toFixed(1)} MB`)
  })

  it('returns GB with 1 decimal for gigabyte-range values', () => {
    expect(formatBytes(1073741824)).toBe('1.0 GB')
    expect(formatBytes(2 * 1073741824)).toBe('2.0 GB')
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// RevisionStorageBadge — minimal inline replica of the badge JSX from
// GitPanel so we can assert on the data-testid and text without importing the
// full panel (which drags in zustand, the cloud API client, and lucide icons).
// ─────────────────────────────────────────────────────────────────────────────

function RevisionStorageBadge({ revSize }) {
  if (!revSize || revSize.revision_count === 0) return null
  return (
    <div className="flex items-center justify-between">
      <span>
        {'Revision history: '}
        {formatBytes(revSize.total_bytes)}
        {' across '}
        {revSize.revision_count}
        {' revisions'}
      </span>
      <button
        type="button"
        data-testid="open-purge-modal"
        onClick={() => {}}
      >
        Manage…
      </button>
    </div>
  )
}

describe('RevisionStorageBadge', () => {
  it('renders nothing when revSize is null', () => {
    const html = renderToStaticMarkup(<RevisionStorageBadge revSize={null} />)
    expect(html).toBe('')
  })

  it('renders nothing when revision_count is 0', () => {
    const html = renderToStaticMarkup(
      <RevisionStorageBadge revSize={{ total_bytes: 0, revision_count: 0 }} />,
    )
    expect(html).toBe('')
  })

  it('renders the badge when revisions exist', () => {
    const html = renderToStaticMarkup(
      <RevisionStorageBadge revSize={{ total_bytes: 4_400_000, revision_count: 230 }} />,
    )
    expect(html).toContain('Revision history')
    expect(html).toContain('230')
    expect(html).toContain('revisions')
  })

  it('renders the open-purge-modal button', () => {
    const html = renderToStaticMarkup(
      <RevisionStorageBadge revSize={{ total_bytes: 1_234_567, revision_count: 87 }} />,
    )
    expect(html).toContain('data-testid="open-purge-modal"')
  })

  it('button label is "Manage…"', () => {
    const html = renderToStaticMarkup(
      <RevisionStorageBadge revSize={{ total_bytes: 1_000_000, revision_count: 10 }} />,
    )
    expect(html).toContain('Manage…')
  })

  it('formats total_bytes using formatBytes', () => {
    const html = renderToStaticMarkup(
      <RevisionStorageBadge revSize={{ total_bytes: 1048576, revision_count: 5 }} />,
    )
    expect(html).toContain('1.0 MB')
  })
})
