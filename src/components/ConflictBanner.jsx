/**
 * ConflictBanner — OCC (Optimistic Concurrency Control) conflict notification.
 *
 * Rendered when a PATCH /files/:id returns 409 (version mismatch). This
 * handles both multi-tab same-user conflicts AND multi-user same-branch
 * conflicts — the primitive is identical either way: state lives in Postgres,
 * not in memory or Redis.
 *
 * The banner reads `conflictFile` from the workspace store and offers a
 * "Reload" button that calls `loadFileForEditor(file_id)` to pull the
 * server's current version, resetting the local version cursor.
 *
 * Props:
 *   useWorkspace {function}  — the workspace Zustand store hook (injected
 *                              for testability; defaults to the real store).
 *   className    {string}    — extra CSS classes for the root element.
 */

import { useCallback } from 'react'

// Default import of the real store — tests inject a mock via the prop.
import { useWorkspace as _useWorkspace } from '../store/workspace.js'

export default function ConflictBanner({ useWorkspace = _useWorkspace, className = '' }) {
  const conflictFile = useWorkspace((s) => s.conflictFile)
  const loadFileForEditor = useWorkspace((s) => s.loadFileForEditor)

  const handleReload = useCallback(() => {
    const { conflictFile: cf } = useWorkspace.getState()
    if (!cf?.file_id) return
    // Dismiss the banner first, then reload — loadFileForEditor resets dirty
    // and currentFile.version so the next save sends the correct expected_version.
    useWorkspace.setState({ conflictFile: null })
    loadFileForEditor(cf.file_id)
  }, [useWorkspace, loadFileForEditor])

  const handleDismiss = useCallback(() => {
    useWorkspace.setState({ conflictFile: null })
  }, [useWorkspace])

  if (!conflictFile) return null

  return (
    <div
      role="alert"
      aria-live="assertive"
      data-testid="conflict-banner"
      className={['conflict-banner', className].filter(Boolean).join(' ')}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '8px 14px',
        background: 'var(--conflict-banner-bg, #2d1a1a)',
        borderLeft: '3px solid var(--conflict-banner-accent, #e05252)',
        borderRadius: '4px',
        fontSize: '13px',
        color: 'var(--conflict-banner-text, #f0c0c0)',
        boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
      }}
    >
      <span style={{ flex: 1 }}>
        Someone else edited this file.
      </span>

      <button
        onClick={handleReload}
        data-testid="conflict-banner-reload"
        style={{
          padding: '4px 12px',
          background: 'var(--conflict-banner-accent, #e05252)',
          color: '#fff',
          border: 'none',
          borderRadius: '4px',
          cursor: 'pointer',
          fontWeight: 600,
          fontSize: '12px',
          whiteSpace: 'nowrap',
        }}
      >
        Reload
      </button>

      <button
        onClick={handleDismiss}
        aria-label="Dismiss conflict banner"
        data-testid="conflict-banner-dismiss"
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          color: 'var(--conflict-banner-text, #f0c0c0)',
          fontSize: '16px',
          lineHeight: 1,
          padding: '0 2px',
          opacity: 0.6,
        }}
      >
        ×
      </button>
    </div>
  )
}
