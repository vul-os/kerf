// CommitDiffViewer — modal showing per-file changes for a clicked commit.
//
// Props: { open, onClose, projectId, sha }
//
// Fetches GET /api/projects/:pid/git/commits/:sha/diff on open.
// Renders a file-by-file list with per-file expandable diffs.
// Backdrop click and Esc close the modal.

import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, GitCommit, Loader2, X } from 'lucide-react'
import { ApiError } from '../lib/api.js'
import { git } from './api.js'

// ─── status badge ─────────────────────────────────────────────────────────────

const STATUS_STYLE = {
  added:    'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  modified: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  deleted:  'bg-red-500/15 text-red-300 border-red-500/30',
  renamed:  'bg-amber-500/15 text-amber-300 border-amber-500/30',
}

function StatusBadge({ status }) {
  const cls = STATUS_STYLE[status] || STATUS_STYLE.modified
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider border ${cls}`}>
      {status || 'modified'}
    </span>
  )
}

// ─── diff line colorizer ──────────────────────────────────────────────────────

function classifyLine(line) {
  if (line.startsWith('+++') || line.startsWith('---')) return 'header'
  if (line.startsWith('@@')) return 'hunk'
  if (line.startsWith('diff ')) return 'file'
  if (line.startsWith('+')) return 'add'
  if (line.startsWith('-')) return 'del'
  return 'ctx'
}

const LINE_CLASSES = {
  header: 'text-ink-400',
  hunk:   'text-kerf-300 bg-kerf-300/5',
  file:   'text-ink-300 bg-ink-850 font-semibold',
  add:    'text-emerald-200 bg-emerald-500/10',
  del:    'text-red-200 bg-red-500/10',
  ctx:    'text-ink-300',
}

function DiffBlock({ text }) {
  if (!text) {
    return (
      <div className="px-3 py-2 text-[11px] text-ink-500 italic">
        Diff preview unavailable.
      </div>
    )
  }
  const lines = text.split('\n').map((l, i) => ({ i, kind: classifyLine(l), text: l }))
  return (
    <pre className="text-[11px] font-mono leading-[1.55] whitespace-pre overflow-x-auto bg-ink-950">
      {lines.map((l) => (
        <div key={l.i} className={'px-3 ' + (LINE_CLASSES[l.kind] || LINE_CLASSES.ctx)}>
          {l.text || ' '}
        </div>
      ))}
    </pre>
  )
}

// ─── single file row ──────────────────────────────────────────────────────────

function FileRow({ file }) {
  const [expanded, setExpanded] = useState(false)
  const additions = file.additions ?? 0
  const deletions = file.deletions ?? 0

  // Derive additions/deletions from hunks if not provided directly
  const effectiveAdditions = additions || (file.hunks ? file.hunks.split('\n').filter(l => l.startsWith('+') && !l.startsWith('+++')).length : 0)
  const effectiveDeletions = deletions || (file.hunks ? file.hunks.split('\n').filter(l => l.startsWith('-') && !l.startsWith('---')).length : 0)

  // Support both 'text_diff' (workspace endpoint) and 'hunks' (project endpoint)
  const diffText = file.hunks || file.text_diff || null
  const hasDiff = !!diffText && !file.binary

  return (
    <div className="border-b border-ink-850 last:border-0">
      <button
        type="button"
        onClick={() => hasDiff && setExpanded((v) => !v)}
        className={
          'w-full flex items-center gap-2 px-3 py-2 text-left ' +
          (hasDiff ? 'hover:bg-ink-850/60 cursor-pointer' : 'cursor-default')
        }
      >
        {hasDiff ? (
          expanded
            ? <ChevronDown size={12} className="text-ink-400 shrink-0" />
            : <ChevronRight size={12} className="text-ink-400 shrink-0" />
        ) : (
          <span className="w-3 shrink-0" />
        )}

        <span className="font-mono text-[11px] text-ink-100 flex-1 truncate min-w-0">
          {file.path}
        </span>

        <StatusBadge status={file.status || file.change} />

        {!file.binary && (effectiveAdditions > 0 || effectiveDeletions > 0) && (
          <span className="flex items-center gap-1 text-[10px] shrink-0">
            {effectiveAdditions > 0 && (
              <span className="text-emerald-400">+{effectiveAdditions}</span>
            )}
            {effectiveDeletions > 0 && (
              <span className="text-red-400">−{effectiveDeletions}</span>
            )}
          </span>
        )}

        {file.binary && (
          <span className="text-[10px] text-ink-500 shrink-0">binary</span>
        )}
      </button>

      {hasDiff && expanded && (
        <div className="border-t border-ink-850">
          <DiffBlock text={diffText} />
        </div>
      )}
    </div>
  )
}

// ─── public component ─────────────────────────────────────────────────────────

export default function CommitDiffViewer({ open, onClose, projectId, sha }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const closeBtnRef = useRef(null)

  // Fetch on open
  useEffect(() => {
    if (!open || !sha || !projectId) return
    let cancelled = false
    setData(null); setError(null); setLoading(true)
    git.commitDiff(projectId, sha)
      .then((res) => { if (!cancelled) { setData(res); setLoading(false) } })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Could not load diff.')
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [open, sha, projectId])

  // Focus close button on open
  useEffect(() => {
    if (open) closeBtnRef.current?.focus()
  }, [open])

  // Esc to close
  useEffect(() => {
    if (!open) return
    const handle = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [open, onClose])

  if (!open) return null

  const shortHash = (sha || '').slice(0, 12)
  const files = data?.files || []

  const totalAdd = files.reduce((s, f) => s + (f.additions || 0), 0)
  const totalDel = files.reduce((s, f) => s + (f.deletions || 0), 0)

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-ink-950/70 backdrop-blur-sm p-4 md:p-6"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }}
      role="dialog"
      aria-modal="true"
      aria-label={`Commit diff ${shortHash}`}
    >
      <div className="w-[860px] max-w-full max-h-[88vh] bg-ink-900 border border-ink-800 rounded-xl shadow-2xl flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-4 h-11 border-b border-ink-800 flex-shrink-0">
          <div className="flex items-center gap-2 text-sm font-medium text-ink-100 min-w-0">
            <GitCommit size={14} className="text-kerf-300 shrink-0" />
            <span className="truncate">Commit</span>
            <span className="font-mono text-[11px] text-ink-400">{shortHash}</span>
            {!loading && !error && data && (
              <span className="ml-2 text-[11px] flex items-center gap-2 shrink-0">
                <span className="text-ink-500">{files.length} file{files.length !== 1 ? 's' : ''}</span>
                {totalAdd > 0 && <span className="text-emerald-300">+{totalAdd}</span>}
                {totalDel > 0 && <span className="text-red-300">−{totalDel}</span>}
              </span>
            )}
          </div>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            className="p-1 rounded text-ink-400 hover:text-ink-100 hover:bg-ink-800"
            aria-label="Close diff viewer"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading ? (
            <div className="p-6 flex items-center gap-2 text-xs text-ink-400">
              <Loader2 size={14} className="animate-spin" /> Loading diff…
            </div>
          ) : error ? (
            <div className="p-6 text-xs text-red-300">{error}</div>
          ) : files.length === 0 ? (
            <div className="p-6 text-xs text-ink-500">No changes in this commit.</div>
          ) : (
            <div className="divide-y divide-ink-850">
              {files.map((f, i) => (
                <FileRow key={`${f.path}-${i}`} file={f} />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end px-4 h-11 border-t border-ink-800 flex-shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="h-7 px-3 rounded-md text-xs text-ink-300 hover:bg-ink-800 hover:text-ink-100"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
