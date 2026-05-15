// PublishButton — toolbar drop-in for the editor.
//
// T-44: updated publish flow:
//   - README preview / edit with "Regenerate with AI" action.
//   - Gallery upload is now OPTIONAL (not required to publish).
//   - On publish, the backend AI-generates a README by default; the author
//     can view and edit the draft before submitting.
//
// Caller hands us a `project` (id + name + visibility, at minimum). On
// click, we open a modal collecting title, description, and an optional
// README override, then POST to /api/workshop/publish. If the project is
// already listed, the button shows "Unpublish" instead.

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  BookOpen,
  ChevronDown,
  ChevronUp,
  Globe,
  Loader2,
  RefreshCw,
  RotateCcw,
  Sparkles,
  X,
} from 'lucide-react'
import Button from '../components/Button.jsx'
import Input, { Textarea } from '../components/Input.jsx'
import WorkshopImageGallery from '../components/WorkshopImageGallery.jsx'
import { api, ApiError } from '../lib/api.js'
import { workshop } from './api.js'

// PublishModal — collect title/description/readme, then POST /workshop/publish.
// captureSnapshot: optional async () => Blob|null (from Editor currentViewRef).
function PublishModal({ open, onClose, project, onPublished, captureSnapshot }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [readmeDraft, setReadmeDraft] = useState(null)   // null = use AI default
  const [readmeEditing, setReadmeEditing] = useState(false)
  const [readmeExpanded, setReadmeExpanded] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [thumbRefreshing, setThumbRefreshing] = useState(false)
  const [thumbToast, setThumbToast] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState(null)
  const toastTimerRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setTitle(project?.name || '')
    setDescription(project?.description || '')
    setReadmeDraft(null)
    setReadmeEditing(false)
    setReadmeExpanded(false)
    setError(null)
    setGenerateError(null)
    setSubmitting(false)
    setThumbToast(null)
  }, [open, project?.id, project?.name, project?.description])

  const onRefreshThumbnail = async () => {
    if (!captureSnapshot || thumbRefreshing || !project?.id) return
    setThumbRefreshing(true)
    try {
      const blob = await captureSnapshot({ size: 512, quality: 0.7 })
      if (blob) {
        await api.uploadProjectThumbnail(project.id, blob)
        if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
        setThumbToast('Thumbnail updated')
        toastTimerRef.current = setTimeout(() => setThumbToast(null), 3000)
      }
    } catch (err) {
      console.warn('[PublishModal] thumbnail refresh failed', err)
    } finally {
      setThumbRefreshing(false)
    }
  }

  // Fetch an AI-generated README preview before final publish.
  // We call /workshop/regenerate-readme on the project — this requires the
  // project to already exist (it always does by the time Publish is clicked).
  // The pre-generated draft is stored locally in readmeDraft; on submit it is
  // sent as the explicit readme= override so the backend doesn't regenerate.
  const onPreviewReadme = async () => {
    if (!project?.id || generating) return
    setGenerating(true)
    setGenerateError(null)
    try {
      const res = await workshop.regenerateReadme(project.id)
      setReadmeDraft(res.readme || '')
      setReadmeExpanded(true)
    } catch (err) {
      setGenerateError(err instanceof ApiError ? err.message : 'Could not generate README.')
    } finally {
      setGenerating(false)
    }
  }

  if (!open) return null

  const onSubmit = async (e) => {
    e?.preventDefault?.()
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await workshop.publish({
        projectId: project.id,
        title: title.trim() || project?.name || '',
        description: description.trim(),
        // If the user edited or previewed the README, send it explicitly so the
        // backend skips re-generation. Otherwise let the backend AI-generate it.
        ...(readmeDraft != null ? { readme: readmeDraft, generateReadme: false } : {}),
      })
      onPublished(res)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Publish failed.')
      setSubmitting(false)
    }
  }

  const willBePrivate = project?.visibility === 'private'
  const hasReadmeDraft = readmeDraft != null

  return (
    <div className="fixed inset-0 z-50 grid place-items-center px-4">
      <div className="absolute inset-0 bg-ink-950/80 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div className="relative w-full max-w-2xl bg-ink-900 border border-ink-800 rounded-2xl shadow-2xl shadow-black/50 max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-ink-800 flex-shrink-0">
          <h2 className="font-display text-lg font-semibold tracking-tight">Publish to workshop</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-ink-400 hover:text-ink-100"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <form onSubmit={onSubmit} className="p-5 flex flex-col gap-4 overflow-y-auto">
          <p className="text-sm text-ink-300">
            Anyone will be able to browse this listing, like it, and fork their
            own copy. You stay the owner of the original project.
          </p>
          {willBePrivate && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span>
                This project is private. Set its visibility to{' '}
                <span className="font-mono">unlisted</span> or{' '}
                <span className="font-mono">public</span> before publishing.
              </span>
            </div>
          )}
          <Input
            label="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={project?.name || 'Cool bracket'}
            required
          />
          <Textarea
            label="Description"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What is it? Who's it for?"
          />

          {/* ---- README section ---- */}
          <div className="flex flex-col gap-2 rounded-lg border border-ink-800 bg-ink-950/40 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-medium text-ink-200">
                <BookOpen size={13} className="text-kerf-300" />
                README
                <span className="font-mono text-[10px] text-kerf-300 bg-kerf-300/10 border border-kerf-300/20 rounded px-1.5 py-0.5">
                  AI-generated on publish
                </span>
              </div>
              <div className="flex items-center gap-2">
                {hasReadmeDraft && (
                  <button
                    type="button"
                    onClick={() => setReadmeEditing((v) => !v)}
                    className="text-xs text-ink-400 hover:text-ink-200 flex items-center gap-1"
                  >
                    {readmeEditing ? 'Done editing' : 'Edit'}
                  </button>
                )}
                <button
                  type="button"
                  onClick={onPreviewReadme}
                  disabled={generating}
                  className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded bg-ink-800 border border-ink-700 text-ink-200 hover:bg-ink-700 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {generating
                    ? <><Loader2 size={11} className="animate-spin" /> Generating…</>
                    : hasReadmeDraft
                      ? <><RefreshCw size={11} /> Regenerate</>
                      : <><Sparkles size={11} /> Preview README</>}
                </button>
                {hasReadmeDraft && (
                  <button
                    type="button"
                    onClick={() => setReadmeExpanded((v) => !v)}
                    className="text-ink-400 hover:text-ink-200"
                    aria-label={readmeExpanded ? 'Collapse README' : 'Expand README'}
                  >
                    {readmeExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                )}
              </div>
            </div>

            {generateError && (
              <div className="flex items-start gap-2 rounded border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-200">
                <AlertCircle size={12} className="mt-0.5 shrink-0" />
                <span>{generateError}</span>
              </div>
            )}

            {!hasReadmeDraft && (
              <p className="text-[11px] text-ink-500">
                A README will be auto-generated from your project parameters, BOM, and parts on publish.
                Click &ldquo;Preview README&rdquo; to see and edit the draft first.
              </p>
            )}

            {hasReadmeDraft && readmeExpanded && (
              readmeEditing ? (
                <Textarea
                  rows={12}
                  value={readmeDraft}
                  onChange={(e) => setReadmeDraft(e.target.value)}
                  className="font-mono text-xs"
                  aria-label="README editor"
                />
              ) : (
                <div className="max-h-48 overflow-y-auto rounded bg-ink-900 border border-ink-800 p-3">
                  <pre className="text-[11px] text-ink-300 whitespace-pre-wrap font-mono leading-relaxed">
                    {readmeDraft}
                  </pre>
                </div>
              )
            )}
          </div>

          {/* ---- Thumbnail & gallery (gallery is optional) ---- */}
          {project?.id && (
            <div className="pt-1 flex flex-col gap-3">
              {captureSnapshot && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={onRefreshThumbnail}
                    disabled={thumbRefreshing}
                    className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded bg-ink-800 border border-ink-700 text-ink-200 hover:bg-ink-700 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {thumbRefreshing
                      ? <><Loader2 size={12} className="animate-spin" /> Refreshing…</>
                      : <><RotateCcw size={12} /> Refresh thumbnail</>}
                  </button>
                  {thumbToast && (
                    <span className="text-xs text-emerald-400 font-mono">{thumbToast}</span>
                  )}
                </div>
              )}
              {/* Gallery is optional — no "required" label or validation */}
              <div>
                <p className="text-xs text-ink-400 mb-2">
                  Gallery images <span className="text-ink-600">(optional)</span>
                </p>
                <WorkshopImageGallery projectId={project.id} />
              </div>
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
          <button type="submit" className="hidden" />
        </form>
        <div className="px-5 py-4 border-t border-ink-800 flex justify-end gap-2">
          <Button variant="ghost" size="md" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={onSubmit}
            disabled={submitting || willBePrivate}
          >
            {submitting ? (
              <>
                <Loader2 size={14} className="animate-spin" /> Publishing…
              </>
            ) : (
              <>
                <Globe size={14} /> Publish
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}

// captureSnapshot: optional async () => Blob|null, forwarded from the Editor's
// currentViewRef.snapshot(). When absent, the "Refresh thumbnail" affordance
// in the modal is hidden.
export function PublishButton({ project, existingSlug, onChange, size = 'sm', variant = 'ghost', captureSnapshot }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [slug, setSlug] = useState(existingSlug || null)
  const [working, setWorking] = useState(false)

  useEffect(() => {
    setSlug(existingSlug || null)
  }, [existingSlug])

  if (!project?.id) return null

  const onPublished = (res) => {
    const newSlug = res.slug || res.project_id
    setSlug(newSlug)
    setOpen(false)
    onChange?.({ slug: newSlug, listed: true })
    navigate(`/workshop/${newSlug}`)
  }

  const onUnpublish = async () => {
    if (!slug || working) return
    if (!window.confirm('Remove this listing from the workshop?')) return
    setWorking(true)
    try {
      await workshop.unpublish(slug)
      setSlug(null)
      onChange?.({ slug: null, listed: false })
    } catch (err) {
      console.error('[PublishButton] unpublish failed', err)
      window.alert(err instanceof ApiError ? err.message : 'Unpublish failed.')
    } finally {
      setWorking(false)
    }
  }

  if (slug) {
    return (
      <Button variant={variant} size={size} onClick={onUnpublish} disabled={working}>
        {working ? <Loader2 size={14} className="animate-spin" /> : <Globe size={14} />}
        Unpublish
      </Button>
    )
  }

  return (
    <>
      <Button variant={variant} size={size} onClick={() => setOpen(true)}>
        <Globe size={14} /> Publish
      </Button>
      <PublishModal
        open={open}
        onClose={() => setOpen(false)}
        project={project}
        onPublished={onPublished}
        captureSnapshot={captureSnapshot}
      />
    </>
  )
}

export default PublishButton
