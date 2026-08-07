import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useParams } from 'react-router-dom'
import { AlertCircle, Loader2, Plus, Users, X, Copy, Check } from 'lucide-react'
import Layout from '../components/Layout.jsx'
import Card from '../components/Card.jsx'
import Button from '../components/Button.jsx'
import { api, ApiError } from '../lib/api.js'
import { useAuth } from '../store/auth.js'
import { useWorkspaces } from '../store/workspaces.js'

function initials(name = '', email = '') {
  const src = (name || email || '?').trim()
  if (!src) return '?'
  const parts = src.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return src.slice(0, 2).toUpperCase()
}

function MemberAvatar({ member, size = 32 }) {
  const px = `${size}px`
  const u = member?.user || {}
  if (u.avatar_url) {
    return (
      <img
        src={u.avatar_url}
        alt=""
        style={{ width: px, height: px }}
        className="rounded-md object-cover bg-ink-800"
      />
    )
  }
  return (
    <span
      style={{ width: px, height: px, fontSize: Math.max(10, size * 0.38) }}
      className="grid place-items-center rounded-md bg-kerf-300/15 border border-kerf-300/30 text-kerf-300 font-semibold tracking-tight"
    >
      {initials(u.name, u.email)}
    </span>
  )
}

function InviteModal({ open, onClose, onInvited, slug }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('member')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [inviteLink, setInviteLink] = useState(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open) return
    setEmail('')
    setRole('member')
    setSubmitting(false)
    setError(null)
    setInviteLink(null)
    setCopied(false)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const submit = async (e) => {
    e?.preventDefault?.()
    if (submitting) return
    const trimmed = email.trim().toLowerCase()
    if (!trimmed || !trimmed.includes('@')) { setError('Enter a valid email.'); return }
    setSubmitting(true); setError(null); setInviteLink(null); setCopied(false)
    try {
      const resp = await api.inviteWorkspaceMember(slug, trimmed, role)
      if (resp?.added) {
        // Existing user — added immediately.
        onInvited?.()
        onClose()
      } else if (resp?.invite?.token) {
        // No account — show the invite link to copy.
        const url = `${window.location.origin}/signup?invite=${encodeURIComponent(resp.invite.token)}`
        setInviteLink(url)
        onInvited?.()
      } else {
        // Defensive — backend didn't return either branch.
        onInvited?.()
        onClose()
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err?.message || 'Could not invite member.'))
    } finally {
      setSubmitting(false)
    }
  }

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(inviteLink)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Fall back to selecting the text — best effort.
    }
  }

  return createPortal((
    <div className="fixed inset-0 z-[100] flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-ink-950/80 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        className="relative w-full max-w-md bg-ink-900 border border-ink-800 rounded-2xl shadow-2xl shadow-black/60"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-ink-800">
          <div className="flex items-center gap-2.5">
            <span className="grid place-items-center w-8 h-8 rounded-lg bg-kerf-300/15 border border-kerf-300/30 text-kerf-300">
              <Plus size={15} />
            </span>
            <h2 className="font-display text-base font-semibold tracking-tight text-ink-100">
              Invite member
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-ink-400 hover:text-ink-100 transition-colors"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <form className="p-5 flex flex-col gap-4" onSubmit={submit}>
          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-medium text-ink-300 uppercase tracking-wider">
              Email
            </label>
            <input
              type="email"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="teammate@example.com"
              className="bg-ink-950 border border-ink-700 rounded-lg px-3 py-2 text-sm text-ink-100 placeholder:text-ink-600 outline-none focus:border-kerf-300/60"
              disabled={submitting || !!inviteLink}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-medium text-ink-300 uppercase tracking-wider">
              Role
            </label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              disabled={submitting || !!inviteLink}
              className="bg-ink-950 border border-ink-700 rounded-lg px-3 py-2 text-sm text-ink-100 outline-none focus:border-kerf-300/60"
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
            <p className="text-[11px] text-ink-500 leading-tight">
              Owners can be promoted post-join. Admins manage members and avatar; members can edit projects.
            </p>
          </div>

          {inviteLink && (
            <div className="flex flex-col gap-1.5 rounded-lg border border-kerf-300/30 bg-kerf-300/5 p-3">
              <p className="text-[11px] font-medium text-kerf-300 uppercase tracking-wider">
                Invite link
              </p>
              <p className="text-[11px] text-ink-400 leading-tight">
                No account exists for that email yet. Copy and share this link so they can sign up and join.
              </p>
              <div className="flex items-stretch gap-2 mt-1">
                <input
                  type="text"
                  readOnly
                  value={inviteLink}
                  className="flex-1 bg-ink-950 border border-ink-700 rounded-lg px-2 py-1.5 text-xs font-mono text-ink-200 outline-none"
                  onFocus={(e) => e.target.select()}
                />
                <Button type="button" variant="ghost" size="sm" onClick={onCopy}>
                  {copied ? <Check size={12} /> : <Copy size={12} />}
                  {copied ? 'Copied' : 'Copy'}
                </Button>
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-3 py-1.5 rounded-md text-sm text-ink-300 hover:bg-ink-800 transition-colors disabled:opacity-40"
            >
              {inviteLink ? 'Done' : 'Cancel'}
            </button>
            {!inviteLink && (
              <button
                type="submit"
                disabled={submitting || !email.trim()}
                className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-md bg-kerf-300 text-ink-950 text-sm font-semibold hover:bg-kerf-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {submitting && <Loader2 size={13} className="animate-spin" />}
                {submitting ? 'Inviting…' : 'Invite'}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  ), document.body)
}

export default function WorkspaceMembers() {
  const { workspaceSlug } = useParams()
  const meId = useAuth((s) => s.user?.id)
  const loadAll = useWorkspaces((s) => s.loadAll)

  const [ws, setWs] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [busyUser, setBusyUser] = useState(null)
  const [inviteOpen, setInviteOpen] = useState(false)

  const refresh = async () => {
    try {
      const data = await api.getWorkspace(workspaceSlug)
      setWs(data)
      setErr(null)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not load members.')
    }
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.getWorkspace(workspaceSlug)
      .then((data) => {
        if (cancelled) return
        setWs(data); setErr(null)
      })
      .catch((e) => { if (!cancelled) setErr(e instanceof ApiError ? e.message : 'Could not load members.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [workspaceSlug])

  const myRole = ws?.my_role || ''
  const canManage = myRole === 'owner' || myRole === 'admin'
  const ownerCount = useMemo(() => (ws?.members || []).filter((m) => m.role === 'owner').length, [ws])

  const onChangeRole = async (member, role) => {
    if (busyUser) return
    setBusyUser(member.user_id)
    try {
      await api.changeWorkspaceMemberRole(workspaceSlug, member.user_id, role)
      await refresh()
      await loadAll()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not change role.')
    } finally {
      setBusyUser(null)
    }
  }

  const onRemove = async (member) => {
    if (busyUser) return
    const target = member.user?.name || member.user?.email || 'member'
    if (!window.confirm(`Remove ${target} from this workspace?`)) return
    setBusyUser(member.user_id)
    try {
      await api.removeWorkspaceMember(workspaceSlug, member.user_id)
      await refresh()
      await loadAll()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not remove member.')
    } finally {
      setBusyUser(null)
    }
  }

  if (loading && !ws) {
    return (
      <Layout>
        <div className="max-w-2xl mx-auto py-12 text-center text-ink-400">
          <Loader2 size={16} className="animate-spin inline-block mr-2" /> Loading…
        </div>
      </Layout>
    )
  }

  const members = ws?.members || []

  return (
    <Layout>
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <span className="grid place-items-center w-10 h-10 rounded-xl bg-kerf-300/15 border border-kerf-300/30 text-kerf-300">
            <Users size={18} />
          </span>
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-kerf-300">Workspace</p>
            <h1 className="font-display text-2xl font-semibold tracking-tight">{ws?.name || workspaceSlug}</h1>
          </div>
        </div>

        <Card className="overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-ink-800">
            <div>
              <h2 className="font-display text-base font-semibold tracking-tight text-ink-100">
                Members
              </h2>
              <p className="text-[11px] text-ink-500 leading-tight mt-0.5">
                {members.length} {members.length === 1 ? 'person' : 'people'} can access this workspace.
              </p>
            </div>
            {canManage && (
              <Button variant="primary" size="sm" onClick={() => setInviteOpen(true)}>
                <Plus size={12} />
                Invite member
              </Button>
            )}
          </div>

          {err && (
            <div role="alert" aria-live="assertive" className="mx-5 mt-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
              <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>{err}</span>
            </div>
          )}

          <ul className="divide-y divide-ink-800">
            {members.map((m) => {
              const isOnlyOwner = m.role === 'owner' && ownerCount <= 1
              const isMe = m.user_id === meId
              const isBusy = busyUser === m.user_id
              return (
                <li key={m.user_id} className="flex items-center gap-3 px-5 py-3">
                  <MemberAvatar member={m} size={36} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-ink-100 truncate flex items-center gap-2">
                      <span className="truncate">{m.user?.name || m.user?.email || m.user_id}</span>
                      {isMe && (
                        <span className="text-[10px] font-mono uppercase tracking-wider text-ink-500">
                          you
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] font-mono text-ink-500 truncate">
                      {m.user?.email || ''}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {canManage && !isOnlyOwner ? (
                      <select
                        value={m.role}
                        disabled={isBusy}
                        onChange={(e) => onChangeRole(m, e.target.value)}
                        className="bg-ink-950 border border-ink-700 rounded-md px-2 py-1 text-xs text-ink-100 outline-none focus:border-kerf-300/60 disabled:opacity-50"
                      >
                        <option value="owner">Owner</option>
                        <option value="admin">Admin</option>
                        <option value="member">Member</option>
                      </select>
                    ) : (
                      <span className="text-[11px] font-mono uppercase tracking-wider text-ink-400 px-2">
                        {m.role}
                      </span>
                    )}
                    {canManage && !isOnlyOwner && (
                      <button
                        type="button"
                        onClick={() => onRemove(m)}
                        disabled={isBusy}
                        title="Remove from workspace"
                        className="grid place-items-center w-7 h-7 rounded-md text-ink-400 hover:text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-40"
                      >
                        {isBusy ? <Loader2 size={13} className="animate-spin" /> : <X size={13} />}
                      </button>
                    )}
                  </div>
                </li>
              )
            })}
            {members.length === 0 && (
              <li className="px-5 py-8 text-center text-sm text-ink-500">
                No members yet.
              </li>
            )}
          </ul>
        </Card>
      </div>

      <InviteModal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        onInvited={() => { refresh(); loadAll() }}
        slug={workspaceSlug}
      />
    </Layout>
  )
}
