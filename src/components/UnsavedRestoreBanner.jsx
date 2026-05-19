/**
 * UnsavedRestoreBanner — Crash-recovery prompt for the editor.
 *
 * Rendered at the top of the Editor body ONLY when `unsavedEntries.length > 0`.
 * Prompts the user to Restore or Discard unflushed IDB entries from a previous
 * session (e.g. browser crash / forced tab close before the autosave flush).
 *
 * This is SEPARATE from ConflictBanner (T-302), which handles live OCC conflicts
 * (409 from PATCH while the editor is open). This banner is for crash-recovery
 * only.
 *
 * Props:
 *   useWorkspace {function}  — Zustand hook (injected for testability).
 *   className    {string}    — extra CSS classes for the root element.
 */

import { useCallback } from 'react'
import { useWorkspace as _useWorkspace } from '../store/workspace.js'

const MAX_FILES_SHOWN = 3

function formatTime(ts) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

export default function UnsavedRestoreBanner({ useWorkspace = _useWorkspace, className = '' }) {
  const unsavedEntries = useWorkspace((s) => s.unsavedEntries)
  const restoreUnsavedEntries = useWorkspace((s) => s.restoreUnsavedEntries)
  const discardUnsavedEntries = useWorkspace((s) => s.discardUnsavedEntries)

  const handleRestore = useCallback(() => {
    restoreUnsavedEntries()
  }, [restoreUnsavedEntries])

  const handleDiscard = useCallback(() => {
    discardUnsavedEntries()
  }, [discardUnsavedEntries])

  if (!unsavedEntries || unsavedEntries.length === 0) return null

  const n = unsavedEntries.length
  const shown = unsavedEntries.slice(0, MAX_FILES_SHOWN)
  const overflow = n - MAX_FILES_SHOWN

  // Use the oldest stash timestamp as the session time reference.
  const sessionTime = unsavedEntries[0]?.stashed_at
    ? formatTime(unsavedEntries[0].stashed_at)
    : ''

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="unsaved-restore-banner"
      className={['unsaved-restore-banner', className].filter(Boolean).join(' ')}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        padding: '8px 14px',
        background: 'var(--restore-banner-bg, #1a2233)',
        borderLeft: '3px solid var(--restore-banner-accent, #4f8ef7)',
        borderRadius: '4px',
        fontSize: '13px',
        color: 'var(--restore-banner-text, #c8d8f0)',
        boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <span style={{ flex: 1 }}>
          You have{' '}
          <strong style={{ color: 'var(--restore-banner-highlight, #7db4ff)' }}>
            {n} unsaved {n === 1 ? 'change' : 'changes'}
          </strong>
          {' '}from a previous session
          {sessionTime ? ` (${sessionTime})` : ''}.
        </span>

        {/* Restore (primary) */}
        <button
          onClick={handleRestore}
          data-testid="unsaved-restore-btn"
          style={{
            padding: '4px 12px',
            background: 'var(--kerf-300, #4f8ef7)',
            color: '#fff',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: '12px',
            whiteSpace: 'nowrap',
          }}
        >
          Restore
        </button>

        {/* Discard (ghost) */}
        <button
          onClick={handleDiscard}
          data-testid="unsaved-discard-btn"
          style={{
            padding: '4px 10px',
            background: 'none',
            color: 'var(--ink-400, #8899aa)',
            border: '1px solid var(--ink-400, #8899aa)',
            borderRadius: '4px',
            cursor: 'pointer',
            fontWeight: 500,
            fontSize: '12px',
            whiteSpace: 'nowrap',
          }}
        >
          Discard
        </button>
      </div>

      {/* File list */}
      <ul
        data-testid="unsaved-file-list"
        style={{
          margin: 0,
          padding: '0 0 0 4px',
          listStyle: 'none',
          display: 'flex',
          flexDirection: 'column',
          gap: '2px',
        }}
      >
        {shown.map((entry) => (
          <li key={entry.path} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                fontSize: '11px',
                fontFamily: 'monospace',
                color: 'var(--restore-banner-path, #a0c0e0)',
              }}
            >
              {entry.path}
            </span>
            {entry._error && (
              <span
                data-testid={`restore-error-${entry.path}`}
                style={{
                  fontSize: '11px',
                  color: 'var(--conflict-banner-accent, #e05252)',
                  marginLeft: '4px',
                }}
              >
                — {entry._error}
              </span>
            )}
          </li>
        ))}
        {overflow > 0 && (
          <li
            data-testid="unsaved-overflow"
            style={{ fontSize: '11px', color: 'var(--ink-400, #8899aa)' }}
          >
            + {overflow} more file{overflow !== 1 ? 's' : ''}
          </li>
        )}
      </ul>
    </div>
  )
}
