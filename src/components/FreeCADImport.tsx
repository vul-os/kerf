// FreeCADImport.jsx — Import FreeCAD .FCStd files into a Kerf project.
//
// Three integration points:
//   1. <FreeCADImportButton> — standalone trigger (used in Projects.jsx toolbar
//      and FileTree CreateMenu). Clicking opens <FreeCADImportDialog>.
//   2. <FreeCADImportDialog> — modal: file picker + upload + import flow.
//      Upload fires immediately on file pick via uploadAsset. The import call
//      (api.importFreecadProject) is currently stubbed with a T7-pending error;
//      the progress card surfaces the message honestly. T7 swaps the stub with
//      the real endpoint in api.js — a one-line change.
//   3. isFCStdFile(file) — predicate used by FileTree drag-drop to recognise
//      .FCStd extensions.

import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  Box,
  CheckCircle2,
  FileBox,
  Loader2,
  Upload,
  X,
} from 'lucide-react'
import { api, ApiError } from '../lib/api.js'

// ---- Helpers ----------------------------------------------------------------

/** Returns true when a File or filename string ends with .FCStd (case-insensitive). */
export function isFCStdFile(fileOrName) {
  const name = typeof fileOrName === 'string' ? fileOrName : fileOrName?.name || ''
  return name.toLowerCase().endsWith('.fcstd')
}

// ---- Progress card ----------------------------------------------------------

/**
 * Inline card shown while the import is running (or after it settles).
 *
 * Props:
 *   filename  — display name of the source .FCStd file
 *   status    — 'uploading' | 'importing' | 'done' | 'error'
 *   progress  — 0–100 upload progress pct (only meaningful during 'uploading')
 *   error     — error message string (only when status === 'error')
 *   onDismiss — called when the user clicks the X on a terminal state
 */
export function FreeCADImportProgress({ filename, status, progress = 0, error, onDismiss }) {
  const isTerminal = status === 'done' || status === 'error'
  const isError = status === 'error'
  const isDone = status === 'done'

  return (
    <div
      className={[
        'rounded-lg border px-3 py-2.5 text-[11px]',
        isError
          ? 'border-red-600/50 bg-red-950/30 text-red-200'
          : isDone
          ? 'border-emerald-600/40 bg-emerald-950/20 text-emerald-200'
          : 'border-kerf-300/30 bg-ink-850 text-ink-200',
      ].join(' ')}
    >
      <div className="flex items-center gap-2">
        {isDone ? (
          <CheckCircle2 size={13} className="shrink-0 text-emerald-400" />
        ) : isError ? (
          <AlertCircle size={13} className="shrink-0 text-red-400" />
        ) : (
          <Loader2 size={13} className="shrink-0 animate-spin text-kerf-300" />
        )}
        <span className="flex-1 truncate font-mono" title={filename}>{filename}</span>
        {status === 'uploading' && (
          <span className="shrink-0 tabular-nums">{progress}%</span>
        )}
        {isTerminal && onDismiss && (
          <button
            type="button"
            aria-label="Dismiss"
            onClick={onDismiss}
            className="p-0.5 rounded hover:bg-ink-700 text-current opacity-60 hover:opacity-100"
          >
            <X size={11} />
          </button>
        )}
      </div>

      {/* Upload progress bar */}
      {status === 'uploading' && (
        <div className="mt-1.5 h-1 rounded bg-ink-800 overflow-hidden">
          <div
            className="h-full bg-kerf-300 transition-all duration-200"
            style={{ width: `${Math.max(2, progress)}%` }}
          />
        </div>
      )}

      {/* Status label */}
      <div className="mt-1 text-[10px] opacity-70">
        {status === 'uploading' && 'Uploading .FCStd archive…'}
        {status === 'importing' && 'Importing FreeCAD project…'}
        {status === 'done' && 'Import complete — project created.'}
        {isError && (
          <span className="text-red-300">{error}</span>
        )}
      </div>
    </div>
  )
}

// ---- Dialog -----------------------------------------------------------------

/**
 * Modal dialog with a .FCStd file picker, upload, and import flow.
 *
 * Props:
 *   projectId  — UUID of the target Kerf project to import into.
 *                If null, a new project should be created first (Projects.jsx
 *                handles that before opening this dialog).
 *   open       — boolean
 *   onClose    — called when dialog should close
 *   onImported — called with the import API response on success
 */
export function FreeCADImportDialog({ projectId, open, onClose, onImported }) {
  const fileInputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)
  const [importState, setImportState] = useState(null)
  // importState shape: { filename, status, progress, error }

  // Listen for drag-drop from FileTree (kerf:fcstd-drop event).
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (e.detail?.file && !importState) handleFile(e.detail.file)
    }
    window.addEventListener('kerf:fcstd-drop', handler)
    return () => window.removeEventListener('kerf:fcstd-drop', handler)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, importState])

  if (!open) return null

  function resetState() {
    setImportState(null)
  }

  async function handleFile(file) {
    if (!file) return
    if (!isFCStdFile(file)) {
      setImportState({
        filename: file.name,
        status: 'error',
        error: `Expected a .FCStd file — got "${file.name}".`,
      })
      return
    }
    if (!projectId) {
      setImportState({
        filename: file.name,
        status: 'error',
        error: 'No project selected. Please create or open a project first.',
      })
      return
    }

    // Phase 1: upload the .FCStd blob so the backend has a storage key.
    setImportState({ filename: file.name, status: 'uploading', progress: 0 })
    let assetRecord
    try {
      assetRecord = await api.uploadAssetChunked(projectId, file, {
        kind: 'step', // generic binary blob; T7 will see it by storage key
        onProgress: ({ received, total }) => {
          const pct = total > 0 ? Math.round((received / total) * 100) : 0
          setImportState((s) => ({ ...s, progress: pct }))
        },
      })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : (err.message || 'Upload failed.')
      setImportState({ filename: file.name, status: 'error', error: msg })
      return
    }

    // Phase 2: call the import endpoint (T7 stub until T7 ships).
    setImportState({ filename: file.name, status: 'importing', progress: 100 })
    try {
      const result = await api.importFreecadProject(projectId, assetRecord.id ?? assetRecord.file_id)
      setImportState({ filename: file.name, status: 'done', progress: 100 })
      onImported?.(result)
    } catch (err) {
      const isPending = err.code === 'FREECAD_T7_PENDING'
      const msg = isPending
        ? 'T7 not yet shipped — backend import handler pending. File uploaded; import will run once T7 lands.'
        : (err instanceof ApiError ? err.message : (err.message || 'Import failed.'))
      setImportState({ filename: file.name, status: 'error', error: msg })
    }
  }

  function onInputChange(e) {
    handleFile(e.target.files?.[0])
    e.target.value = ''
  }

  function onDrop(e) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleFile(file)
  }

  const isRunning = importState && (importState.status === 'uploading' || importState.status === 'importing')

  return (
    <div className="fixed inset-0 z-50 grid place-items-center px-4">
      <div
        className="absolute inset-0 bg-ink-950/80 backdrop-blur-sm"
        onClick={!isRunning ? onClose : undefined}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="fcstd-import-title"
        className="relative w-full max-w-md bg-ink-900 border border-ink-800 rounded-2xl shadow-2xl shadow-black/50"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-ink-800">
          <div className="flex items-center gap-2">
            <FileBox size={16} className="text-kerf-300" />
            <h2 id="fcstd-import-title" className="font-display text-base font-semibold tracking-tight">
              Import FreeCAD project
            </h2>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            disabled={isRunning}
            className="text-ink-400 hover:text-ink-100 transition-colors disabled:opacity-40"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 flex flex-col gap-4">
          {/* Description + tooltip text */}
          <p className="text-sm text-ink-300 leading-relaxed">
            Imports FreeCAD 0.19+ files (.FCStd) — features lifted as read-only, BRep solid editable.
          </p>
          <p className="text-xs text-ink-400 leading-relaxed">
            The imported feature tree is read-only metadata. Geometry comes from the
            cached BRep blob — no FreeCAD recompute. You can add fillets, holes, and
            assemblies on top of the imported solid immediately.
          </p>

          {/* Drop zone / pick button (hidden when import is running/done) */}
          {!importState && (
            <div
              className={[
                'relative rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors cursor-pointer',
                dragOver
                  ? 'border-kerf-300/70 bg-kerf-300/5'
                  : 'border-ink-700 hover:border-ink-600 hover:bg-ink-800/40',
              ].join(' ')}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              aria-label="Drop .FCStd file or click to browse"
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click() }}
            >
              <Box size={28} className="mx-auto mb-3 text-ink-500" />
              <p className="text-sm text-ink-200 font-medium">
                Drop a .FCStd file here
              </p>
              <p className="mt-1 text-xs text-ink-400">
                or click to browse
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".FCStd,.fcstd"
                className="hidden"
                onChange={onInputChange}
              />
            </div>
          )}

          {/* Progress card (upload + import phases) */}
          {importState && (
            <FreeCADImportProgress
              filename={importState.filename}
              status={importState.status}
              progress={importState.progress}
              error={importState.error}
              onDismiss={!isRunning ? resetState : undefined}
            />
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-ink-800 flex items-center justify-between gap-2">
          <span className="text-[11px] text-ink-400 font-mono">
            .FCStd · FreeCAD 0.19+
          </span>
          <button
            type="button"
            onClick={onClose}
            disabled={isRunning}
            className="px-3 py-1.5 text-sm rounded-lg border border-ink-700 text-ink-200 hover:bg-ink-800 disabled:opacity-40 transition-colors"
          >
            {importState?.status === 'done' ? 'Done' : 'Cancel'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- Button -----------------------------------------------------------------

/**
 * Small "Import FreeCAD" button that opens <FreeCADImportDialog>.
 * Accepts all props forwarded to the dialog (projectId, onImported).
 */
export function FreeCADImportButton({ projectId, onImported, className = '' }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        type="button"
        title="Imports FreeCAD 0.19+ files (.FCStd) — features lifted as read-only, BRep solid editable"
        onClick={() => setOpen(true)}
        className={[
          'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-medium',
          'border-ink-700 text-ink-200 hover:border-ink-600 hover:bg-ink-800/60 transition-colors',
          className,
        ].join(' ')}
      >
        <Upload size={13} />
        Import FreeCAD
      </button>
      <FreeCADImportDialog
        projectId={projectId}
        open={open}
        onClose={() => setOpen(false)}
        onImported={(result) => {
          setOpen(false)
          onImported?.(result)
        }}
      />
    </>
  )
}
