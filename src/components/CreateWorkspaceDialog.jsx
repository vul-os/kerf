import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Building2, X, AlertCircle, Loader2, Upload } from 'lucide-react'
import clsx from 'clsx'
import { useWorkspaces } from '../store/workspaces.js'
import { api, ApiError } from '../lib/api.js'

function slugify(s) {
  return (s || '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32)
}

function isValidSlug(s) {
  return /^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$/.test(s) || /^[a-z0-9]{1,3}$/.test(s)
}

export default function CreateWorkspaceDialog({ open, onClose, onCreated }) {
  const create = useWorkspaces((s) => s.create)
  const loadAll = useWorkspaces((s) => s.loadAll)

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugDirty, setSlugDirty] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [warning, setWarning] = useState(null)
  const [avatarFile, setAvatarFile] = useState(null)
  const [avatarPreview, setAvatarPreview] = useState(null)
  const nameRef = useRef(null)
  const fileRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setName('')
    setSlug('')
    setSlugDirty(false)
    setSubmitting(false)
    setError(null)
    setWarning(null)
    setAvatarFile(null)
    setAvatarPreview(null)
    const t = setTimeout(() => nameRef.current?.focus(), 30)
    return () => clearTimeout(t)
  }, [open])

  // Revoke any object URL when it changes / dialog closes to avoid leaks.
  useEffect(() => {
    return () => {
      if (avatarPreview) URL.revokeObjectURL(avatarPreview)
    }
  }, [avatarPreview])

  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const effectiveSlug = useMemo(() => {
    if (slugDirty) return slug
    return slugify(name)
  }, [slug, slugDirty, name])

  const slugValid = !effectiveSlug || isValidSlug(effectiveSlug)

  const onPickAvatar = (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('Pick an image file (PNG or JPEG).')
      return
    }
    if (avatarPreview) URL.revokeObjectURL(avatarPreview)
    setAvatarFile(file)
    setAvatarPreview(URL.createObjectURL(file))
    setError(null)
  }

  const clearAvatar = () => {
    if (avatarPreview) URL.revokeObjectURL(avatarPreview)
    setAvatarFile(null)
    setAvatarPreview(null)
  }

  const submit = async (e) => {
    e?.preventDefault?.()
    if (submitting) return
    if (!name.trim()) { setError('Give your workspace a name.'); return }
    if (effectiveSlug && !isValidSlug(effectiveSlug)) {
      setError('Slug must be 3–32 chars, lowercase, alphanumeric or hyphens.')
      return
    }
    setSubmitting(true); setError(null); setWarning(null)
    let created
    try {
      created = await create({ name: name.trim(), slug: effectiveSlug || undefined })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : (err?.message || 'Could not create workspace.'))
      setSubmitting(false)
      return
    }
    // Workspace is created. Try to attach the avatar (non-blocking on error).
    if (avatarFile) {
      try {
        await api.uploadWorkspaceAvatar(created.slug, avatarFile)
        await loadAll()
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : (err?.message || 'unknown error')
        setWarning(`Workspace created, but avatar upload failed: ${msg}`)
        // Keep the dialog open briefly so the user sees the warning, then continue.
        setSubmitting(false)
        // Still notify parent so navigation can proceed if it wants to.
        onCreated?.(created)
        return
      }
    }
    onCreated?.(created)
    onClose()
  }

  if (!open) return null
  // Portal at body level so any ancestor `transform`/`filter`/`will-change` (e.g.
  // a `backdrop-blur` header) can't trap our `position: fixed`.
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
              <Building2 size={15} />
            </span>
            <h2 className="font-display text-base font-semibold tracking-tight text-ink-100">
              Create workspace
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
          {warning && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span>{warning}</span>
            </div>
          )}

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={submitting}
              title={avatarPreview ? 'Replace image' : 'Upload image'}
              className={clsx(
                'relative grid place-items-center w-24 h-24 rounded-2xl overflow-hidden',
                'border border-ink-700 hover:border-kerf-300/60 transition-colors',
                avatarPreview ? 'bg-ink-800' : 'bg-kerf-300/10',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/40',
              )}
            >
              {avatarPreview ? (
                <img src={avatarPreview} alt="" className="w-full h-full object-cover" />
              ) : (
                <div className="grid place-items-center text-kerf-300/80">
                  <Upload size={20} />
                  <span className="text-[10px] font-mono uppercase tracking-wider mt-1">avatar</span>
                </div>
              )}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={onPickAvatar}
            />
            <div className="flex-1 flex flex-col gap-1.5">
              <p className="text-[11px] font-medium text-ink-300 uppercase tracking-wider">
                Avatar (optional)
              </p>
              <p className="text-[11px] text-ink-500 leading-snug">
                PNG or JPEG, square preferred. You can change it later.
              </p>
              {avatarPreview && (
                <button
                  type="button"
                  onClick={clearAvatar}
                  disabled={submitting}
                  className="self-start inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] text-ink-300 hover:text-ink-100 hover:bg-ink-800 transition-colors"
                >
                  <X size={11} />
                  Remove
                </button>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-medium text-ink-300 uppercase tracking-wider">
              Name
            </label>
            <input
              ref={nameRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Acme Robotics"
              className="bg-ink-950 border border-ink-700 rounded-lg px-3 py-2 text-sm text-ink-100 placeholder:text-ink-600 outline-none focus:border-kerf-300/60"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-medium text-ink-300 uppercase tracking-wider">
              URL slug
            </label>
            <div className="flex items-stretch rounded-lg border border-ink-700 bg-ink-950 overflow-hidden focus-within:border-kerf-300/60 transition-colors">
              <span className="grid place-items-center px-3 text-[12px] font-mono text-ink-500 bg-ink-900 border-r border-ink-800">
                /w/
              </span>
              <input
                type="text"
                value={effectiveSlug}
                onChange={(e) => { setSlug(slugify(e.target.value)); setSlugDirty(true) }}
                placeholder="acme-robotics"
                className="flex-1 bg-transparent px-2 py-2 text-sm font-mono text-ink-100 placeholder:text-ink-600 outline-none"
              />
            </div>
            <p className={clsx(
              'text-[11px] leading-tight',
              effectiveSlug && !slugValid ? 'text-red-300' : 'text-ink-500',
            )}>
              {effectiveSlug && !slugValid
                ? 'Slug must be 3–32 chars, lowercase, alphanumeric or hyphens.'
                : effectiveSlug
                  ? <>Workspace will live at <span className="font-mono text-ink-300">/w/{effectiveSlug}</span>.</>
                  : 'Auto-generated from the name; click to customize.'}
            </p>
          </div>

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-3 py-1.5 rounded-md text-sm text-ink-300 hover:bg-ink-800 transition-colors disabled:opacity-40"
            >
              {warning ? 'Close' : 'Cancel'}
            </button>
            {!warning && (
              <button
                type="submit"
                disabled={submitting || !name.trim() || !slugValid}
                className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-md bg-kerf-300 text-ink-950 text-sm font-semibold hover:bg-kerf-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {submitting && <Loader2 size={13} className="animate-spin" />}
                {submitting ? 'Creating…' : 'Create workspace'}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  ), document.body)
}
