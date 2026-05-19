/**
 * PurgeRevisionsModal.jsx — Loud confirmation modal for purging per-keystroke
 * revision history from a project.
 *
 * Props:
 *   open          {boolean}  Whether the modal is visible.
 *   onClose       {fn}       Called when the modal is dismissed (cancel or success).
 *   projectId     {string}   The project whose revisions will be purged.
 *   currentSize   {object}   Result of api.getRevisionsSize — {total_bytes, revision_count}.
 *                            May be null while loading.
 *
 * Behaviour:
 *   - The destructive "Purge" button is disabled until the safety checkbox
 *     is checked.
 *   - On success: closes modal, fires a toast via the ToastBus.
 *   - On failure: renders an inline error message inside the modal.
 */

import { useState } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import Button from './Button.jsx'
import { toast } from './ToastBus.jsx'
import { api } from '../lib/api.js'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format bytes to a human-readable string (e.g. "4.2 MB"). */
function fmtBytes(bytes) {
  if (bytes == null || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PurgeRevisionsModal({
  open,
  onClose,
  projectId,
  currentSize,
}) {
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (!open) return null

  const totalBytes = currentSize?.total_bytes ?? null
  const revisionCount = currentSize?.revision_count ?? null

  const handlePurge = async () => {
    if (!confirmed || busy) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.purgeRevisions(projectId, { keepLast: 5 })
      const freed = fmtBytes(result.freed_bytes)
      toast.success(`Freed ${freed}. Git commits are unaffected.`)
      onClose()
    } catch (err) {
      setError(err?.message || 'Purge failed. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const handleCancel = () => {
    if (busy) return
    onClose()
  }

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="purge-modal-title"
    >
      {/* Panel */}
      <div className="relative w-full max-w-md mx-4 rounded-xl bg-ink-900 border border-ink-700 shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-4 border-b border-ink-800">
          <div className="flex items-center gap-3">
            <div className="grid place-items-center w-9 h-9 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 shrink-0">
              <AlertTriangle size={18} />
            </div>
            <h2 id="purge-modal-title" className="text-sm font-semibold text-ink-100 leading-tight">
              Purge revision history
            </h2>
          </div>
          <button
            type="button"
            onClick={handleCancel}
            className="p-1 rounded text-ink-400 hover:text-ink-100 hover:bg-ink-800"
            aria-label="Close dialog"
            data-testid="purge-modal-cancel-x"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {/* Explanation */}
          <p className="text-[13px] text-ink-300 leading-relaxed">
            This will permanently delete per-keystroke revision history for this
            project. The{' '}
            <span className="font-medium text-ink-100">5 most recent revisions</span>{' '}
            per file are kept as a safety net.
          </p>
          <p className="text-[13px] text-ink-300 leading-relaxed">
            <span className="font-medium text-green-400">Git commits are not affected.</span>{' '}
            Everything you have committed to git will remain intact. This only
            frees the fine-grained keystroke history stored in the database.
          </p>

          {/* Size stats */}
          {currentSize != null && (
            <div className="rounded-lg bg-ink-850 border border-ink-700 px-4 py-3 text-[12px] text-ink-300">
              <span className="font-medium text-red-300">{fmtBytes(totalBytes)}</span>
              {' '}across{' '}
              <span className="font-medium text-ink-100">
                {revisionCount != null ? revisionCount.toLocaleString() : '—'} revision{revisionCount !== 1 ? 's' : ''}
              </span>
              {' '}will be freed.
            </div>
          )}

          {/* Safety checkbox */}
          <label className="flex items-start gap-3 cursor-pointer select-none group">
            <input
              type="checkbox"
              className="mt-0.5 w-4 h-4 rounded border border-ink-600 bg-ink-800 accent-red-500 cursor-pointer"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              data-testid="purge-modal-confirm-checkbox"
            />
            <span className="text-[13px] text-ink-200 leading-snug group-hover:text-ink-100 transition-colors">
              I have committed everything I want to keep to git
            </span>
          </label>

          {/* Inline error */}
          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-200"
            >
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 pb-5">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleCancel}
            disabled={busy}
            data-testid="purge-modal-cancel"
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            onClick={handlePurge}
            disabled={!confirmed || busy}
            data-testid="purge-modal-confirm"
          >
            {busy ? 'Purging…' : 'Purge revision history'}
          </Button>
        </div>
      </div>
    </div>
  )
}
