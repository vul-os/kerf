// CommitDiffViewer.test.jsx — unit tests for CommitDiffViewer component.
//
// @testing-library/react is not installed; DOM render tests are omitted.
// We verify:
//   1. The module default-exports a function (the component).
//   2. Source-text contracts: open/onClose/projectId/sha props present,
//      Esc handler wired, backdrop click closes, status badges rendered.
//   3. git.commitDiff is called (source-text check).
//   4. StatusBadge receives status prop (source-text check).
//
// For fetch/state behaviour testing: mock window.fetch in a jsdom env
// when @testing-library/react is available.

import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const _root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const _src = (p) => readFileSync(join(_root, p), 'utf8')

// ── Source-text contracts ─────────────────────────────────────────────────────

describe('CommitDiffViewer.jsx — source contracts', () => {
  const src = _src('cloud/CommitDiffViewer.jsx')

  it('default-exports a function named CommitDiffViewer', () => {
    expect(src).toContain('export default function CommitDiffViewer(')
  })

  it('accepts open, onClose, projectId, sha props', () => {
    expect(src).toContain('open')
    expect(src).toContain('onClose')
    expect(src).toContain('projectId')
    expect(src).toContain('sha')
  })

  it('calls git.commitDiff to fetch data', () => {
    expect(src).toContain('git.commitDiff')
  })

  it('renders StatusBadge with status prop', () => {
    expect(src).toContain('<StatusBadge')
    expect(src).toContain('status={file.status')
  })

  it('renders additions and deletions counts', () => {
    expect(src).toContain('additions')
    expect(src).toContain('deletions')
  })

  it('handles Esc key to close', () => {
    expect(src).toContain("e.key === 'Escape'")
    expect(src).toContain('onClose?.()')
  })

  it('closes on backdrop mousedown', () => {
    expect(src).toContain('e.target === e.currentTarget')
    expect(src).toContain('onClose?.()')
  })

  it('uses role=dialog and aria-modal for a11y', () => {
    expect(src).toContain('role="dialog"')
    expect(src).toContain('aria-modal="true"')
  })

  it('renders a DiffBlock component for per-file hunks', () => {
    expect(src).toContain('function DiffBlock(')
  })

  it('shows "Diff preview unavailable" when hunks is null/empty', () => {
    expect(src).toContain('Diff preview unavailable')
  })

  it('renders binary file indicator', () => {
    expect(src).toContain('binary')
  })

  it('early-returns null when open is false', () => {
    // The component guards on `if (!open) return null`
    expect(src).toContain('if (!open) return null')
  })
})

// ── StatusBadge colour mapping ────────────────────────────────────────────────

describe('CommitDiffViewer.jsx — StatusBadge colour coverage', () => {
  const src = _src('cloud/CommitDiffViewer.jsx')

  it('maps "added" status to an emerald colour class', () => {
    expect(src).toContain('added:')
    expect(src).toContain('emerald')
  })

  it('maps "modified" status to a sky/blue colour class', () => {
    expect(src).toContain('modified:')
    expect(src).toContain('sky')
  })

  it('maps "deleted" status to a red colour class', () => {
    expect(src).toContain('deleted:')
    expect(src).toContain('red-')
  })
})

// ── API wiring ────────────────────────────────────────────────────────────────

describe('CommitDiffViewer.jsx — API endpoint', () => {
  const apiSrc = _src('cloud/api.js')

  it('git.commitDiff is defined in api.js', () => {
    expect(apiSrc).toContain('commitDiff:')
  })

  it('commitDiff calls the /git/commits/:sha/diff endpoint', () => {
    expect(apiSrc).toContain('/git/commits/')
    expect(apiSrc).toContain('/diff')
  })
})

// ── GitPanel integration ──────────────────────────────────────────────────────

describe('GitPanel.jsx — CommitDiffViewer integration', () => {
  const panelSrc = _src('cloud/GitPanel.jsx')

  it('imports CommitDiffViewer', () => {
    expect(panelSrc).toContain("import CommitDiffViewer from './CommitDiffViewer.jsx'")
  })

  it('renders <CommitDiffViewer', () => {
    expect(panelSrc).toContain('<CommitDiffViewer')
  })

  it('passes open, sha, projectId, onClose props to CommitDiffViewer', () => {
    expect(panelSrc).toContain('open={!!diffSha}')
    expect(panelSrc).toContain('sha={diffSha}')
    expect(panelSrc).toContain('projectId={projectId}')
    expect(panelSrc).toContain('onClose={() => setDiffSha(null)}')
  })
})
