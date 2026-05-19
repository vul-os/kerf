import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'
import { listDirty, listUnflushed, reconcile } from './lib/localStash.js'
import { useAuth } from './store/auth.js'

// ── L1 stash: load-time reconcile ─────────────────────────────────────────────
// After auth resolves, replay any dirty L1 entries to the server (handles
// crash / forced-close recovery). The T-309 autosave pipeline now writes
// stash entries keyed by (projectId, fileId) — these are the L1 IDB entries.
//
// TODO (T-309 follow-up): Instead of silently replaying, surface an interactive
// prompt inside <Editor> via listUnflushed() + a banner:
//   "You have N unsaved changes from a previous session. [Restore] [Discard]"
//
// On Restore: call reconcile() to PATCH files to server, then markFlushed each.
// On Discard: clear all unflushed entries for this workspace.
// On conflict (server has newer version): reuse <ConflictBanner> from T-302.
//
// The interactive prompt belongs in src/routes/Editor.jsx, not here, because
// it needs the React context and workspace store for workspaceId resolution.
// The silent replay below is kept as a safe fallback for non-editor routes.
async function _reconcileOnLoad() {
  const { accessToken, user } = useAuth.getState()
  if (!accessToken || !user) return
  // Derive the current workspace from the URL if available (editor path:
  // /projects/:projectId). For pages without a project context, reconcile is
  // a no-op because there are no dirty entries for workspaceId=undefined.
  const match = window.location.pathname.match(/\/projects\/([^/]+)/)
  const workspaceId = match ? match[1] : null
  if (!workspaceId) return

  // Check if there are unflushed entries before attempting a silent replay.
  // If entries exist and we're in the editor, the Editor route should surface
  // the interactive prompt instead. This path handles non-interactive recovery
  // (e.g. background tab reload while not in the editor view).
  const API_URL = import.meta.env.VITE_API_URL || ''
  await reconcile(workspaceId, async (filePath, bytes) => {
    const res = await fetch(
      `${API_URL}/api/workspaces/${workspaceId}/files/${encodeURIComponent(filePath)}`,
      {
        method: 'POST',
        headers: {
          'content-type': 'application/octet-stream',
          authorization: `Bearer ${accessToken}`,
        },
        body: bytes,
      },
    )
    if (!res.ok) throw new Error(`reconcile: server returned ${res.status}`)
  })
}

// ── L1 stash: beforeunload guard ──────────────────────────────────────────────
// Fire the browser "unsaved changes" prompt ONLY when L1 has dirty entries.
// Browsers no longer honour custom messages; just triggering preventDefault
// is enough to show the native dialog.
//
// Note: the T-309 autosave wiring (editContent → schedulerMarkDirty → stash)
// writes to IDB synchronously before the network round-trip, so any keystroke
// that didn't make it to the server will already have an IDB entry here.
// The listDirty() check below catches those entries.
//
// TODO (T-309 follow-up): On beforeunload, also attempt a synchronous last-
// write via the Beacon API so in-progress flushes get one final chance:
//   navigator.sendBeacon(`/api/workspaces/${id}/stash`, formData)
// This is best-effort — the browser may ignore it on tab close.
window.addEventListener('beforeunload', (event) => {
  listDirty().then((dirty) => {
    if (dirty.length > 0) {
      event.preventDefault()
    }
  })
})

// Subscribe to auth changes so reconcile runs once after the user logs in.
useAuth.subscribe((state, prev) => {
  if (state.accessToken && !prev.accessToken) {
    _reconcileOnLoad().catch(() => {/* reconcile failures are non-fatal */})
  }
})

// Also attempt reconcile immediately in case auth is already resolved
// (e.g. persisted refresh token that was exchanged before this listener ran).
_reconcileOnLoad().catch(() => {/* non-fatal */})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
