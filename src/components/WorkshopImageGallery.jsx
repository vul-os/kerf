// WorkshopImageGallery — drag-to-reorder image strip for a project's
// Workshop cover-art gallery.
//
// Drop-in: <WorkshopImageGallery projectId="…" /> renders the full UI.
// It manages its own list state via api.workshopImages.* — callers
// don't need to wire up persistence.
//
// Caps (mirror the backend in routes.py):
//   * 10 images per project
//   * 5 MB per image
//   * JPEG / PNG / WebP only
//
// Drag/drop: stock HTML5 — no external deps. We reorder optimistically
// in local state, then PATCH `sort_order` on every involved row so the
// server sees a flat sequence (0..N-1) afterwards.

import { useCallback, useEffect, useRef, useState } from 'react'
import { GripVertical, Plus, Trash2, Loader2, AlertCircle, Image as ImageIcon } from 'lucide-react'
import { api, ApiError } from '../lib/api.js'

const MAX_IMAGES = 10
const MAX_BYTES = 5 * 1024 * 1024
const ALLOWED_MIME = new Set(['image/jpeg', 'image/png', 'image/webp'])

function bytesHuman(n) {
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export default function WorkshopImageGallery({ projectId, readOnly = false }) {
  const [images, setImages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [dragId, setDragId] = useState(null)
  const fileInputRef = useRef(null)

  const refresh = useCallback(async () => {
    if (!projectId) return
    try {
      const resp = await api.workshopImages.list(projectId)
      setImages(resp.images || [])
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load images.')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { refresh() }, [refresh])

  const onPickFile = () => {
    if (readOnly || uploading || images.length >= MAX_IMAGES) return
    fileInputRef.current?.click()
  }

  const onFileChosen = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!ALLOWED_MIME.has(file.type)) {
      setError('Image must be JPEG, PNG, or WebP.')
      return
    }
    if (file.size > MAX_BYTES) {
      setError(`Image is too large (max ${bytesHuman(MAX_BYTES)}).`)
      return
    }
    setUploading(true)
    setError(null)
    try {
      const row = await api.workshopImages.upload(projectId, file)
      setImages((prev) => [...prev, row])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  const onCaptionBlur = async (image, nextCaption) => {
    if (readOnly) return
    if ((image.caption || '') === (nextCaption || '')) return
    try {
      const row = await api.workshopImages.update(projectId, image.id, { caption: nextCaption })
      setImages((prev) => prev.map((x) => (x.id === image.id ? row : x)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not update caption.')
    }
  }

  const onDelete = async (image) => {
    if (readOnly) return
    if (!window.confirm('Delete this image from the gallery?')) return
    try {
      await api.workshopImages.remove(projectId, image.id)
      setImages((prev) => prev.filter((x) => x.id !== image.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed.')
    }
  }

  // ----- Drag/drop reorder -----
  const onDragStart = (id) => setDragId(id)
  const onDragEnd = () => setDragId(null)
  const onDragOver = (e) => { e.preventDefault() }
  const onDrop = async (targetId) => {
    if (!dragId || dragId === targetId) { setDragId(null); return }
    const fromIdx = images.findIndex((x) => x.id === dragId)
    const toIdx = images.findIndex((x) => x.id === targetId)
    if (fromIdx < 0 || toIdx < 0) { setDragId(null); return }

    const next = images.slice()
    const [moved] = next.splice(fromIdx, 1)
    next.splice(toIdx, 0, moved)
    setImages(next)
    setDragId(null)

    // Persist sort_order on every row whose index shifted. Fire in
    // parallel — order doesn't matter, we just need them all to land.
    try {
      await Promise.all(
        next.map((row, i) =>
          row.sort_order !== i
            ? api.workshopImages.update(projectId, row.id, { sort_order: i })
            : null,
        ),
      )
    } catch (err) {
      // If a single PATCH fails, refresh to recover canonical order.
      console.warn('[WorkshopImageGallery] reorder failed, reloading', err)
      refresh()
    }
  }

  // ----- Render -----
  if (loading) {
    return (
      <div className="flex items-center justify-center py-6 text-ink-400">
        <Loader2 size={16} className="animate-spin" />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-widest font-mono text-ink-400">
          Gallery ({images.length}/{MAX_IMAGES})
        </div>
        {!readOnly && (
          <button
            type="button"
            onClick={onPickFile}
            disabled={uploading || images.length >= MAX_IMAGES}
            className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded bg-kerf-300/10 border border-kerf-300/30 text-kerf-200 hover:bg-kerf-300/20 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {uploading ? (
              <><Loader2 size={12} className="animate-spin" /> Uploading…</>
            ) : (
              <><Plus size={12} /> Add image</>
            )}
          </button>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="hidden"
          onChange={onFileChosen}
        />
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          <AlertCircle size={13} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {images.length === 0 ? (
        <div className="grid place-items-center py-8 rounded-lg border border-dashed border-ink-700 bg-ink-900/30 text-ink-500">
          <ImageIcon size={22} className="opacity-50" />
          <p className="mt-2 text-xs">No gallery images yet.</p>
          {!readOnly && (
            <p className="mt-1 text-[10px] font-mono opacity-60">
              JPEG, PNG, or WebP · up to {bytesHuman(MAX_BYTES)} each
            </p>
          )}
        </div>
      ) : (
        <ul className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {images.map((img) => (
            <li
              key={img.id}
              draggable={!readOnly}
              onDragStart={() => onDragStart(img.id)}
              onDragEnd={onDragEnd}
              onDragOver={onDragOver}
              onDrop={() => onDrop(img.id)}
              className={[
                'group relative rounded-lg overflow-hidden border bg-ink-900',
                dragId === img.id ? 'border-kerf-300/60 opacity-60' : 'border-ink-700',
                readOnly ? '' : 'cursor-grab',
              ].join(' ')}
            >
              <div className="aspect-square bg-ink-800">
                <img
                  src={img.url}
                  alt={img.caption || ''}
                  className="w-full h-full object-cover"
                  draggable={false}
                />
              </div>
              {!readOnly && (
                <>
                  <div className="absolute top-1.5 left-1.5 px-1 py-0.5 rounded bg-ink-950/80 text-ink-300 opacity-0 group-hover:opacity-100 transition-opacity">
                    <GripVertical size={12} />
                  </div>
                  <button
                    type="button"
                    onClick={() => onDelete(img)}
                    aria-label="Delete image"
                    className="absolute top-1.5 right-1.5 p-1 rounded bg-ink-950/80 text-red-300 hover:text-red-200 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <Trash2 size={12} />
                  </button>
                </>
              )}
              <input
                type="text"
                defaultValue={img.caption || ''}
                placeholder={readOnly ? '' : 'Caption'}
                disabled={readOnly}
                onBlur={(e) => onCaptionBlur(img, e.target.value)}
                className="w-full px-2 py-1.5 text-[11px] bg-ink-950/60 text-ink-100 placeholder:text-ink-500 outline-none border-t border-ink-800 disabled:bg-ink-900/40"
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
