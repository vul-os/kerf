// GitPanel — right-side drawer surfacing a project's local git repo.
// Mounted in src/routes/Editor.jsx as a core MIT node capability (no longer
// gated behind useCloudConfig().cloudEnabled — see decisions.md's
// 2026-07-17 "local git only; no OAuth" addendum).
//
// Drives the local git API directly (src/cloud/api.js `git`): init if not
// initialized, status/branch/dirty, commit with a message, a flat commit
// log, a remotes manager (add/remove name+URL — any git remote, no OAuth),
// and push/pull with remote + branch pickers. There is no branch
// switching/merge/per-commit-diff UI here: the local git contract this
// wave rewires onto (GET/POST /api/git/:project_id/...) doesn't expose
// branch listing, merge, or diff endpoints — those were part of the old
// hosted-git product and are gone with it. `file_revisions` (fine-grained
// local undo, surfaced below as the revision-history badge + purge modal)
// is a separate, unrelated system that coexists with git commits and is
// untouched by this rewire.

import { useCallback, useEffect, useState } from 'react'
import {
  AlertCircle, ArrowDownToLine, ArrowUpFromLine, GitBranch, GitCommit,
  Link2, Loader2, RefreshCw, X,
} from 'lucide-react'
import Button from '../components/Button.jsx'
import PurgeRevisionsModal from '../components/PurgeRevisionsModal.jsx'
import { api, ApiError } from '../lib/api.js'
import { git } from './api.js'
import RemotesManager from './RemotesManager.jsx'

function shortSha(s) {
  return (s || '').slice(0, 7)
}

function formatBytes(bytes) {
  if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(1)} GB`
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

function relativeTime(iso) {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const sec = Math.round((Date.now() - t) / 1000)
  if (sec < 45) return 'just now'
  const min = Math.round(sec / 60); if (min < 60) return `${min}m`
  const hr = Math.round(min / 60); if (hr < 24) return `${hr}h`
  const day = Math.round(hr / 24); if (day < 30) return `${day}d`
  const mo = Math.round(day / 30); if (mo < 12) return `${mo}mo`
  return `${Math.round(mo / 12)}y`
}

export function ErrorBanner({ message, onDismiss }) {
  if (!message) return null
  return (
    <div
      className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-2.5 py-1.5 text-[11px] text-red-200"
      role="alert"
    >
      <AlertCircle size={12} className="mt-0.5 shrink-0" />
      <span className="flex-1 break-words">{message}</span>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="text-red-200 hover:text-white">
          <X size={11} />
        </button>
      )}
    </div>
  )
}

// TransferPanel — shared inline form for Push and Pull. Both actions need a
// remote + branch pair; the contract is POST {remote, branch} for each.
export function TransferPanel({ mode, remotes, defaultBranch, busy, onSubmit, onCancel }) {
  const [remote, setRemote] = useState(remotes[0]?.name || '')
  const [branch, setBranch] = useState(defaultBranch || '')

  const label = mode === 'push' ? 'Push' : 'Pull'
  const Icon = mode === 'push' ? ArrowUpFromLine : ArrowDownToLine

  return (
    <div className="p-2.5 border-t border-ink-800 bg-ink-850/40 flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-wider text-ink-400">Remote</span>
          <select
            value={remote}
            onChange={(e) => setRemote(e.target.value)}
            className="h-7 rounded-md bg-ink-800 border border-ink-700 px-1.5 text-[11px] text-ink-100 focus:outline-none focus:border-kerf-300"
          >
            {remotes.map((r) => (
              <option key={r.name} value={r.name}>{r.name}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[9px] uppercase tracking-wider text-ink-400">Branch</span>
          <input
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            placeholder="main"
            className="h-7 rounded-md bg-ink-800 border border-ink-700 px-1.5 text-[11px] font-mono text-ink-100 placeholder:text-ink-600 focus:outline-none focus:border-kerf-300"
          />
        </label>
      </div>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          className="flex-1"
          disabled={busy || !remote || !branch.trim()}
          onClick={() => onSubmit(remote, branch.trim())}
        >
          {busy
            ? <Loader2 size={12} className="animate-spin" />
            : <Icon size={12} />}
          {label} to {remote || '…'}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

export function CommitLog({ commits, loading }) {
  if (loading && commits.length === 0) {
    return (
      <div className="p-4 flex items-center gap-2 text-xs text-ink-400">
        <Loader2 size={14} className="animate-spin" /> Loading commits…
      </div>
    )
  }
  if (commits.length === 0) {
    return (
      <div className="p-6 text-center text-xs text-ink-500">
        No commits yet — make the first one.
      </div>
    )
  }
  return (
    <ul className="py-1">
      {commits.map((c, i) => {
        const title = (c.message || '').split('\n', 1)[0] || '(no message)'
        return (
          <li
            key={c.sha || i}
            className="flex items-stretch text-left px-3 py-2 border-b border-ink-850/80 last:border-b-0"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-[11px] text-ink-100 truncate flex-1">{title}</span>
                <span className="font-mono text-[10px] text-ink-500 shrink-0">{shortSha(c.sha)}</span>
              </div>
              <div className="mt-0.5 flex items-center gap-2 text-[10px] text-ink-500 truncate">
                <span className="truncate">{c.author || ''}</span>
                {c.ts && <span>· {relativeTime(c.ts)}</span>}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export function EmptyState({ busy, onInit }) {
  return (
    <div className="p-4 flex flex-col gap-3">
      <div className="rounded-lg border border-ink-800 bg-ink-850/40 p-4">
        <div className="grid place-items-center w-9 h-9 rounded-lg bg-kerf-300/10 border border-kerf-300/30 text-kerf-300">
          <GitBranch size={16} />
        </div>
        <h3 className="mt-3 text-sm font-semibold text-ink-100 tracking-tight">Version control</h3>
        <p className="mt-1 text-[11px] text-ink-400 leading-relaxed">
          Track changes to your project files with a plain local git repo.
          Push to any remote you configure when you&apos;re ready to share —
          a teammate&apos;s node, your homelab, GitHub, or Gitea.
        </p>
        <div className="mt-3">
          <Button size="sm" variant="primary" onClick={onInit} disabled={busy}>
            {busy === 'init'
              ? <><Loader2 size={13} className="animate-spin" /> Initializing…</>
              : <><GitBranch size={13} /> Initialize git</>}
          </Button>
        </div>
        <a
          href="/docs/saving-your-work"
          className="mt-4 inline-flex items-center gap-1 text-[10px] text-kerf-300/70 hover:text-kerf-300 underline-offset-2 hover:underline"
        >
          How saving works — L1 · L2 · L3
        </a>
      </div>
    </div>
  )
}

export function GitPanel({ projectId, onClose }) {
  const [status, setStatus] = useState(null) // null = loading; {initialized, branch, dirty, ahead, behind, remotes}
  const [log, setLog] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState('')
  const [committing, setCommitting] = useState(false)
  const [busy, setBusy] = useState(null) // 'init' | 'push' | 'pull' | null
  const [transfer, setTransfer] = useState(null) // null | 'push' | 'pull'
  const [showRemotes, setShowRemotes] = useState(false)
  const [showPurge, setShowPurge] = useState(false)
  const [revSize, setRevSize] = useState(null)

  const loadRevSize = useCallback(async () => {
    if (!projectId) return
    try {
      const data = await api.getRevisionsSize(projectId)
      setRevSize(data)
    } catch {
      // non-critical — badge simply won't render
    }
  }, [projectId])

  const refreshLog = useCallback(async () => {
    if (!projectId) return
    try {
      const rows = await git.log(projectId, 50)
      setLog(Array.isArray(rows) ? rows : [])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load commit log.')
    }
  }, [projectId])

  const refreshStatus = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const s = await git.status(projectId)
      setStatus(s)
      setError(null)
      if (s?.initialized) await refreshLog()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load git status.')
    } finally {
      setLoading(false)
    }
  }, [projectId, refreshLog])

  useEffect(() => {
    if (projectId) {
      refreshStatus()
      loadRevSize()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const onInit = useCallback(async () => {
    setBusy('init')
    setError(null)
    try {
      await git.init(projectId)
      await refreshStatus()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Init failed.')
    } finally {
      setBusy(null)
    }
  }, [projectId, refreshStatus])

  const onCommit = useCallback(async (e) => {
    e?.preventDefault?.()
    const msg = message.trim()
    if (!msg || committing) return
    setCommitting(true)
    setError(null)
    try {
      await git.commit(projectId, msg)
      setMessage('')
      await refreshStatus()
      await loadRevSize()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Commit failed.')
    } finally {
      setCommitting(false)
    }
  }, [projectId, message, committing, refreshStatus, loadRevSize])

  const onTransfer = useCallback(async (mode, remote, branch) => {
    setBusy(mode)
    setError(null)
    try {
      if (mode === 'push') await git.push(projectId, remote, branch)
      else await git.pull(projectId, remote, branch)
      setTransfer(null)
      await refreshStatus()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `${mode === 'push' ? 'Push' : 'Pull'} failed.`)
    } finally {
      setBusy(null)
    }
  }, [projectId, refreshStatus])

  const onKey = useCallback((e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') onCommit(e)
  }, [onCommit])

  if (showRemotes) {
    return (
      <RemotesManager
        projectId={projectId}
        onClose={() => setShowRemotes(false)}
        onChanged={refreshStatus}
      />
    )
  }

  const initialized = !!status?.initialized
  const remotes = status?.remotes || []
  const dirty = !!status?.dirty

  return (
    <div className="h-full bg-ink-900 flex flex-col">
      {/* Action bar */}
      <div className="flex items-center justify-end h-8 px-3 border-b border-ink-800 flex-shrink-0">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => refreshStatus()}
            disabled={loading}
            className="p-1 rounded text-ink-400 hover:text-ink-100 hover:bg-ink-800 disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
          {initialized && (
            <button
              type="button"
              onClick={() => setShowRemotes(true)}
              className="p-1 rounded text-ink-400 hover:text-ink-100 hover:bg-ink-800"
              title="Manage remotes"
            >
              <Link2 size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Sub-header: branch + dirty indicator */}
      {initialized && status && (
        <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-ink-800">
          <span className="flex items-center gap-1.5 h-7 px-2 rounded-md bg-ink-800 border border-ink-700 text-xs text-ink-100">
            <GitBranch size={12} className="text-kerf-300" />
            <span className="font-mono truncate max-w-[140px]">{status.branch || '—'}</span>
          </span>
          <span
            className={
              'text-[10px] font-mono px-1.5 py-0.5 rounded ' +
              (dirty
                ? 'bg-amber-500/15 text-amber-300 border border-amber-500/25'
                : 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/25')
            }
          >
            {dirty ? 'dirty' : 'clean'}
          </span>
        </div>
      )}

      {/* Revision-history badge (T-302) + purge entry (T-303) — unrelated
          file_revisions system, kept as-is. */}
      {initialized && revSize && revSize.revision_count > 0 && (
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-ink-800 bg-ink-850/40">
          <span className="text-[10px] text-ink-400">
            Revision history:{' '}
            <span className="text-ink-300">{formatBytes(revSize.total_bytes)}</span>
            {' '}across{' '}
            <span className="text-ink-300">{revSize.revision_count}</span>
            {' '}revisions
          </span>
          <button
            type="button"
            data-testid="open-purge-modal"
            onClick={() => setShowPurge(true)}
            className="text-[10px] text-kerf-300/70 hover:text-kerf-300 underline underline-offset-2 shrink-0 ml-2"
          >
            Manage…
          </button>
        </div>
      )}

      {/* Commit box */}
      {initialized && (
        <form onSubmit={onCommit} className="flex flex-col gap-1.5 p-2 border-b border-ink-800">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={onKey}
            placeholder="Commit message…"
            rows={2}
            className="w-full resize-none rounded-md bg-ink-800 border border-ink-700 px-2 py-1.5 text-[11px] text-ink-100 placeholder:text-ink-500 focus:outline-none focus:border-kerf-300 focus:ring-2 focus:ring-kerf-300/20"
          />
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={committing || !message.trim() || !dirty}
            className="w-full"
          >
            {committing
              ? <><Loader2 size={12} className="animate-spin" /> Committing…</>
              : <><GitCommit size={12} /> {dirty ? 'Commit changes' : 'Working tree clean'}</>}
          </Button>
        </form>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {error && (
          <div className="p-2"><ErrorBanner message={error} onDismiss={() => setError(null)} /></div>
        )}
        {status === null && !error ? (
          <div className="p-4 flex items-center gap-2 text-xs text-ink-400">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        ) : !initialized ? (
          <EmptyState busy={busy} onInit={onInit} />
        ) : (
          <CommitLog commits={log} loading={loading} />
        )}
      </div>

      {/* Footer / push-pull */}
      {initialized && (
        <div className="flex-shrink-0">
          {transfer && (
            <TransferPanel
              mode={transfer}
              remotes={remotes}
              defaultBranch={status?.branch || ''}
              busy={busy === transfer}
              onSubmit={(remote, branch) => onTransfer(transfer, remote, branch)}
              onCancel={() => setTransfer(null)}
            />
          )}
          <div className="flex items-center gap-1 px-2 py-2 border-t border-ink-800">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setTransfer(transfer === 'pull' ? null : 'pull')}
              disabled={remotes.length === 0}
              title={remotes.length === 0 ? 'Add a remote first' : 'Pull from remote'}
              className="flex items-center gap-1"
            >
              <ArrowDownToLine size={13} />
              {status?.behind > 0 && (
                <span className="text-[9px] font-mono text-amber-300">{status.behind}↓</span>
              )}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setTransfer(transfer === 'push' ? null : 'push')}
              disabled={remotes.length === 0}
              title={remotes.length === 0 ? 'Add a remote first' : 'Push to remote'}
              className="flex items-center gap-1"
            >
              <ArrowUpFromLine size={13} />
              {status?.ahead > 0 && (
                <span className="text-[9px] font-mono text-kerf-300">{status.ahead}↑</span>
              )}
            </Button>
            {remotes.length === 0 && (
              <button
                type="button"
                onClick={() => setShowRemotes(true)}
                className="ml-1 text-[10px] text-kerf-300/70 hover:text-kerf-300 underline underline-offset-2"
              >
                Add a remote…
              </button>
            )}
          </div>
        </div>
      )}

      {showPurge && (
        <PurgeRevisionsModal
          open={showPurge}
          onClose={() => {
            setShowPurge(false)
            loadRevSize()
          }}
          projectId={projectId}
          currentSize={revSize}
        />
      )}
    </div>
  )
}

export default GitPanel
