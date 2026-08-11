import { useEffect, useState } from 'react'
import { Copy, Trash2, Link as LinkIcon, Check, Loader2 } from 'lucide-react'
import { api } from '../lib/api.js'
import Modal from './Modal.jsx'
import type { ShareLink, ShareLinkRole } from '@/types'

const LINK_ROLES: ShareLinkRole[] = ['viewer', 'editor']


interface LinksTabProps {
  projectId: string
}

// The API's list endpoint returns every share_links column (`SELECT *`),
// including `revoked_at`, which src/types/api.ts's ShareLink doesn't model.
type ShareLinkRow = ShareLink & { revoked_at?: string | null }

function LinksTab({ projectId }: LinksTabProps) {
  const [links, setLinks] = useState<ShareLinkRow[] | null>(null)
  const [role, setRole] = useState<ShareLinkRole>('viewer')
  const [expiresIn, setExpiresIn] = useState('never')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [freshTokens, setFreshTokens] = useState<Record<string, string | undefined>>({}) // tokens only available at creation time
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    api.listShareLinks(projectId)
      .then((ls) => { if (!cancelled) setLinks((ls as ShareLinkRow[]) || []) })
      .catch((e) => { if (!cancelled) setErr(e?.message || String(e)) })
    return () => { cancelled = true }
  }, [projectId, reloadKey])

  const reload = () => setReloadKey((k) => k + 1)

  async function create() {
    setBusy(true); setErr('')
    try {
      let expires_at: string | null = null
      if (expiresIn !== 'never') {
        const days = parseInt(expiresIn, 10)
        expires_at = new Date(Date.now() + days * 86400_000).toISOString()
      }
      const link = await api.createShareLink(projectId, { role, expires_at })
      if (link?.token) setFreshTokens((t) => ({ ...t, [link.id]: link.token }))
      reload()
    } catch (ex) {
      setErr((ex as Error)?.message || 'Failed to create link')
    } finally {
      setBusy(false)
    }
  }

  async function revoke(id: string) {
    if (!confirm('Revoke this link?')) return
    try {
      await api.revokeShareLink(projectId, id)
      reload()
    } catch (e) {
      setErr((e as Error)?.message || String(e))
    }
  }

  function copy(id: string, token: string) {
    if (!token) return
    const url = `${window.location.origin}/share/${token}`
    navigator.clipboard.writeText(url).then(() => {
      setCopiedId(id)
      setTimeout(() => setCopiedId((c) => (c === id ? null : c)), 1500)
    })
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-ink-400">Role</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as ShareLinkRole)}
            className="bg-ink-850 border border-ink-700 rounded-md px-2 py-1.5 text-sm text-ink-100 outline-none focus:border-kerf-300/60"
          >
            {LINK_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-ink-400">Expires</label>
          <select
            value={expiresIn}
            onChange={(e) => setExpiresIn(e.target.value)}
            className="bg-ink-850 border border-ink-700 rounded-md px-2 py-1.5 text-sm text-ink-100 outline-none focus:border-kerf-300/60"
          >
            <option value="never">Never</option>
            <option value="1">1 day</option>
            <option value="7">7 days</option>
            <option value="30">30 days</option>
          </select>
        </div>
        <button
          type="button"
          onClick={create}
          disabled={busy}
          className="ml-auto inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-kerf-300 text-ink-950 text-sm font-medium hover:bg-kerf-200 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70 focus-visible:ring-offset-1 focus-visible:ring-offset-ink-900"
        >
          {busy ? <Loader2 size={13} className="animate-spin" /> : <LinkIcon size={13} />}
          Create link
        </button>
      </div>
      {err && <div className="text-xs text-red-400">{err}</div>}
      <div className="flex flex-col gap-1">
        {links === null ? (
          <div className="text-xs text-ink-400 py-4 text-center">Loading links…</div>
        ) : links.length === 0 ? (
          <div className="text-xs text-ink-400 py-4 text-center">No share links yet.</div>
        ) : links.map((l) => {
          const token = l.token || freshTokens[l.id]
          const url = token ? `${window.location.origin}/share/${token}` : '(token hidden — copy at creation)'
          return (
            <div key={l.id} className="flex items-center gap-2 py-2 px-2 rounded hover:bg-ink-800">
              <LinkIcon size={13} className="text-ink-400 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-mono text-ink-100 truncate">{url}</div>
                <div className="text-[10px] text-ink-400 mt-0.5">
                  {l.role} · {l.uses ?? 0} uses
                  {l.expires_at && ` · expires ${new Date(l.expires_at).toLocaleDateString()}`}
                  {l.revoked_at && ' · revoked'}
                </div>
              </div>
              {token && (
                <button
                  type="button"
                  onClick={() => copy(l.id, token)}
                  className="p-1 rounded text-ink-400 hover:text-kerf-300 hover:bg-ink-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
                  title="Copy link"
                  aria-label="Copy share link"
                >
                  {copiedId === l.id ? <Check size={13} className="text-kerf-300" /> : <Copy size={13} />}
                </button>
              )}
              {!l.revoked_at && (
                <button
                  type="button"
                  onClick={() => revoke(l.id)}
                  className="p-1 rounded text-ink-400 hover:text-red-400 hover:bg-ink-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/70"
                  title="Revoke"
                  aria-label="Revoke share link"
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export interface ShareModalProps {
  projectId: string
  onClose: () => void
}

export default function ShareModal({ projectId, onClose }: ShareModalProps) {
  // A Members tab used to sit beside this one, adding people to the project by
  // email. There is nobody to add — a node has one owner — and the endpoint
  // behind it could only ever find that owner, so inviting anyone else wrote
  // nothing and reported success. Sharing a project means handing out a link.
  return (
    <Modal
      open
      onClose={onClose}
      title="Share project"
      widthClass="max-w-lg"
    >
      <div className="-mx-5 -mt-5">
        <div className="p-4 overflow-auto max-h-[60vh]">
          <LinksTab projectId={projectId} />
        </div>
      </div>
    </Modal>
  )
}
