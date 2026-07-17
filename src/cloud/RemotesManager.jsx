// RemotesManager — full-panel overlay for managing a project's local git
// remotes. Rendered inside GitPanel (covers the panel while open, same
// pattern the old GitProviderSettings used) so nothing behind it unmounts.
//
// Per decisions.md's 2026-07-17 "local git only; no OAuth" addendum: a kerf
// project is a plain local git repo, and collaboration is git push/pull to
// any remote the user configures — a teammate's node, a homelab box,
// GitHub, Gitea. There is no hosted-git product and no kerf-run OAuth app.

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, Link2, Loader2, Plus, Trash2, X } from 'lucide-react'
import Button from '../components/Button.jsx'
import Input from '../components/Input.jsx'
import { ApiError } from '../lib/api.js'
import { git } from './api.js'

export default function RemotesManager({ projectId, onClose, onChanged }) {
  const [remotes, setRemotes] = useState(null) // null = loading
  const [loadError, setLoadError] = useState(null)
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState(null)
  const [removing, setRemoving] = useState(null)

  const load = useCallback(async () => {
    if (!projectId) return
    setLoadError(null)
    try {
      const list = await git.listRemotes(projectId)
      setRemotes(Array.isArray(list) ? list : [])
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : 'Could not load remotes.')
      setRemotes([])
    }
  }, [projectId])

  useEffect(() => { load() }, [load])

  const onAdd = useCallback(async (e) => {
    e?.preventDefault?.()
    if (!name.trim() || !url.trim()) {
      setAddError('Name and URL are both required.')
      return
    }
    setAdding(true)
    setAddError(null)
    try {
      await git.addRemote(projectId, name.trim(), url.trim())
      setName('')
      setUrl('')
      await load()
      onChanged?.()
    } catch (err) {
      setAddError(err instanceof ApiError ? err.message : 'Could not add remote.')
    } finally {
      setAdding(false)
    }
  }, [projectId, name, url, load, onChanged])

  const onRemove = useCallback(async (remoteName) => {
    if (typeof window !== 'undefined' && !window.confirm(
      `Remove remote "${remoteName}"? This only forgets it locally — nothing changes on the remote itself.`,
    )) return
    setRemoving(remoteName)
    try {
      await git.removeRemote(projectId, remoteName)
      await load()
      onChanged?.()
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : 'Could not remove remote.')
    } finally {
      setRemoving(null)
    }
  }, [projectId, load, onChanged])

  const loading = remotes === null

  return (
    <div className="flex flex-col h-full bg-ink-900">
      <div className="flex items-center justify-between h-10 px-3 border-b border-ink-800 flex-shrink-0">
        <div className="flex items-center gap-2 text-xs font-medium text-ink-200 uppercase tracking-wider">
          <Link2 size={12} className="text-kerf-300" />
          Remotes
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded text-ink-400 hover:text-ink-100 hover:bg-ink-800"
          title="Back to Git panel"
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0 p-3 space-y-4">
        <div className="rounded-md border border-kerf-400/25 bg-kerf-300/5 px-3 py-2.5 text-[11px] text-kerf-200/90 leading-relaxed">
          Use any git remote — a teammate&apos;s node, your homelab, GitHub or
          Gitea. Authentication uses your own SSH key or token; kerf never
          stores credentials.
        </div>

        {loading && (
          <div className="flex items-center gap-2 text-xs text-ink-400 py-2">
            <Loader2 size={13} className="animate-spin" />
            Loading…
          </div>
        )}

        {loadError && (
          <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-2.5 py-2 text-[11px] text-red-200">
            <AlertCircle size={12} className="mt-0.5 shrink-0" />
            <span>{loadError}</span>
          </div>
        )}

        {!loading && remotes.length === 0 && !loadError && (
          <p className="text-[11px] text-ink-500" data-testid="remotes-empty">
            No remotes configured yet. Add one below to push and pull.
          </p>
        )}

        {!loading && remotes.length > 0 && (
          <ul className="space-y-1.5" data-testid="remotes-list">
            {remotes.map((r) => (
              <li
                key={r.name}
                className="flex items-center gap-2 rounded-md border border-ink-800 bg-ink-850/30 px-2.5 py-2 text-xs"
              >
                <span className="font-mono text-ink-100 shrink-0">{r.name}</span>
                <span className="font-mono text-ink-400 truncate flex-1">{r.url}</span>
                <button
                  type="button"
                  onClick={() => onRemove(r.name)}
                  disabled={removing === r.name}
                  className="p-1 rounded text-red-300 hover:bg-red-500/10 disabled:opacity-40"
                  title={`Remove ${r.name}`}
                >
                  {removing === r.name
                    ? <Loader2 size={12} className="animate-spin" />
                    : <Trash2 size={12} />}
                </button>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={onAdd} className="space-y-2 pt-2 border-t border-ink-800">
          <h4 className="text-[10px] uppercase tracking-wider text-ink-400">Add remote</h4>
          <div className="grid grid-cols-2 gap-2">
            <Input
              label="Name"
              placeholder="origin"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Input
              label="URL"
              placeholder="git@github.com:you/repo.git"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </div>
          {addError && <p className="text-[11px] text-red-300">{addError}</p>}
          <Button type="submit" size="sm" variant="secondary" disabled={adding} className="w-full">
            {adding
              ? <><Loader2 size={12} className="animate-spin" /> Adding…</>
              : <><Plus size={12} /> Add remote</>}
          </Button>
        </form>
      </div>
    </div>
  )
}
