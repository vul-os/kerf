/**
 * HeroRenderPanel.jsx — "Hero Render" drawer panel for the viewport.
 *
 * Responsibilities:
 *   - Quality picker: Draft / Standard / Hero / Cinema with sample counts.
 *   - Submit button: POST to /api/render/job; on success polls /api/render/job/:id
 *     every second until the job reaches a terminal state.
 *   - Progress area: percentage bar + running sample count.
 *   - Downloads: PNG and multi-pass EXR when the job completes.
 *   - Gallery tab: lists past renders for the current project (GET
 *     /api/render/jobs?project_id=...).
 *   - Offline / 503 fallback: when the backend is unreachable, dynamically
 *     imports heroShotBrowserPT.js (written by T-106f) and runs a local
 *     browser path-trace with a "rendering in browser (free preview)" banner.
 *     Gracefully degrades if that module is not yet available.
 *
 * Styling: Tailwind v4 dark ink-* + kerf-* yellow palette, consistent with
 * the rest of the Renderer chrome.
 */

import { useState, useEffect, useRef, useCallback } from 'react'

// ── Quality presets ────────────────────────────────────────────────────────────

export const QUALITY_PRESETS = [
  { id: 'draft',    label: 'Draft',    samples: 256,   creditHint: '~0.5 cr' },
  { id: 'standard', label: 'Standard', samples: 1024,  creditHint: '~2 cr'   },
  { id: 'hero',     label: 'Hero',     samples: 4096,  creditHint: '~10 cr'  },
  { id: 'cinema',   label: 'Cinema',   samples: 16384, creditHint: '~60 cr'  },
]

// ── Poll interval (ms) ─────────────────────────────────────────────────────────
const POLL_INTERVAL_MS = 1000

// ── Tab identifiers ────────────────────────────────────────────────────────────
const TAB_RENDER  = 'render'
const TAB_GALLERY = 'gallery'

// ── Job states ─────────────────────────────────────────────────────────────────
const JOB_TERMINAL = new Set(['done', 'failed', 'cancelled'])

// ── Helpers ────────────────────────────────────────────────────────────────────

function downloadBlob(blob, filename) {
  if (typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') return
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function downloadUrl(url, filename) {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

// ── Small UI pieces ────────────────────────────────────────────────────────────

function PresetButton({ preset, active, onClick }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={`${preset.label} quality — ${preset.samples.toLocaleString()} samples`}
      onClick={() => onClick(preset.id)}
      className={[
        'flex flex-col items-center gap-0.5 px-3 py-2 rounded text-[11px] font-mono border transition-colors',
        active
          ? 'bg-kerf-300 text-ink-950 border-kerf-300'
          : 'bg-ink-900/80 text-ink-300 border-ink-700 hover:text-kerf-300 hover:border-kerf-300/50 backdrop-blur',
      ].join(' ')}
    >
      <span className="font-semibold">{preset.label}</span>
      <span className={`text-[9px] ${active ? 'text-ink-800' : 'text-ink-500'}`}>
        {preset.samples.toLocaleString()} spp
      </span>
      <span className={`text-[9px] ${active ? 'text-ink-800' : 'text-ink-500'}`}>
        {preset.creditHint}
      </span>
    </button>
  )
}

function ProgressBar({ percent }) {
  const clamped = Math.min(100, Math.max(0, percent ?? 0))
  return (
    <div
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Render progress"
      className="w-full h-2 rounded-full bg-ink-800 overflow-hidden"
    >
      <div
        className="h-full rounded-full bg-kerf-300 transition-all duration-300"
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}

function GalleryItem({ job, onDownloadPng, onDownloadExr }) {
  const ts = job.created_at ? new Date(job.created_at).toLocaleString() : '—'
  const preset = QUALITY_PRESETS.find((p) => p.id === job.quality) ?? { label: job.quality ?? '—' }
  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded bg-ink-800/60 border border-ink-700 text-[11px] font-mono">
      {job.thumbnail_url ? (
        <img
          src={job.thumbnail_url}
          alt="Render thumbnail"
          className="w-10 h-10 rounded object-cover border border-ink-700"
        />
      ) : (
        <div className="w-10 h-10 rounded bg-ink-800 border border-ink-700 flex items-center justify-center text-ink-500 text-[9px]">
          {job.status === 'done' ? '✓' : job.status ?? '?'}
        </div>
      )}
      <div className="flex flex-col gap-0.5 flex-1 min-w-0">
        <span className="text-ink-200 truncate">{preset.label} · {ts}</span>
        <span className={`text-[9px] ${job.status === 'done' ? 'text-kerf-300' : 'text-ink-500'}`}>
          {job.status ?? 'unknown'}
        </span>
      </div>
      {job.status === 'done' && (
        <div className="flex gap-1 shrink-0">
          {job.png_url && (
            <button
              type="button"
              aria-label="Download PNG"
              onClick={() => onDownloadPng(job)}
              className="px-2 py-0.5 rounded bg-ink-700 text-ink-300 border border-ink-600 hover:text-kerf-300 hover:border-kerf-300/50 text-[9px]"
            >
              PNG
            </button>
          )}
          {job.exr_url && (
            <button
              type="button"
              aria-label="Download EXR"
              onClick={() => onDownloadExr(job)}
              className="px-2 py-0.5 rounded bg-ink-700 text-ink-300 border border-ink-600 hover:text-kerf-300 hover:border-kerf-300/50 text-[9px]"
            >
              EXR
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

/**
 * HeroRenderPanel
 *
 * @param {object}   props
 * @param {function} props.onClose       Called when the user dismisses the panel.
 * @param {string}   [props.projectId]   Current project ID, passed to gallery + job submit.
 * @param {object}   [props.rendererRef] Optional forwarded ref to Renderer; used if the
 *                                       browser-PT fallback needs the live scene.
 */
export default function HeroRenderPanel({ onClose, projectId, rendererRef }) {
  const [tab, setTab]               = useState(TAB_RENDER)
  const [quality, setQuality]       = useState('hero')
  const [job, setJob]               = useState(null)       // current in-flight or last job
  const [progress, setProgress]     = useState(0)          // 0..100
  const [samplesRendered, setSamplesRendered] = useState(0)
  const [status, setStatus]         = useState('idle')     // idle | submitting | polling | done | failed | browser
  const [errorMsg, setErrorMsg]     = useState(null)
  const [browserMode, setBrowserMode] = useState(false)    // T-106f fallback active
  const [gallery, setGallery]       = useState([])
  const [galleryLoading, setGalleryLoading] = useState(false)
  // ── In-process CPU path tracer ("production render") ──────────────────────
  const [productionMode, setProductionMode] = useState(false) // path-traced GI
  const [ptImage, setPtImage]       = useState(null)          // data URL of result
  const [ptStats, setPtStats]       = useState(null)          // {samples, triangles, ...}

  const pollRef     = useRef(null)
  const cancelledRef = useRef(false)

  // ── Cleanup on unmount ───────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      cancelledRef.current = true
      if (pollRef.current) clearTimeout(pollRef.current)
    }
  }, [])

  // ── Load gallery when tab is switched ────────────────────────────────────────
  useEffect(() => {
    if (tab !== TAB_GALLERY) return
    if (!projectId) return
    let alive = true
    setGalleryLoading(true)
    fetch(`/api/render/jobs?project_id=${encodeURIComponent(projectId)}`)
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then((data) => { if (alive) { setGallery(Array.isArray(data) ? data : (data.jobs ?? [])); setGalleryLoading(false) } })
      .catch(() => { if (alive) setGalleryLoading(false) })
    return () => { alive = false }
  }, [tab, projectId])

  // ── Polling loop ─────────────────────────────────────────────────────────────
  const pollJob = useCallback((jobId) => {
    if (cancelledRef.current) return
    fetch(`/api/render/job/${jobId}`)
      .then((r) => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then((data) => {
        if (cancelledRef.current) return
        setJob(data)
        const pct = typeof data.progress_pct === 'number'
          ? data.progress_pct
          : (typeof data.samples_done === 'number' && data.samples_total > 0
              ? Math.round((data.samples_done / data.samples_total) * 100)
              : progress)
        setProgress(pct)
        if (typeof data.samples_done === 'number') setSamplesRendered(data.samples_done)

        if (JOB_TERMINAL.has(data.status)) {
          setStatus(data.status === 'done' ? 'done' : 'failed')
          if (data.status !== 'done') setErrorMsg(data.error ?? 'Render failed')
        } else {
          pollRef.current = setTimeout(() => pollJob(jobId), POLL_INTERVAL_MS)
        }
      })
      .catch(() => {
        if (!cancelledRef.current) {
          setStatus('failed')
          setErrorMsg('Lost contact with render server during polling')
        }
      })
  }, [progress])

  // ── Browser-PT fallback ───────────────────────────────────────────────────────
  async function runBrowserFallback() {
    setBrowserMode(true)
    setStatus('browser')
    setProgress(0)
    setErrorMsg(null)

    try {
      // Dynamically import the browser path-tracer module; gracefully
      // degrade if absent. @vite-ignore so the bundler does not hard-fail
      // when the optional module is not present at build time.
      const mod = await import('../lib/heroShotBrowserPT.js')
      if (typeof mod.renderBrowserPT !== 'function') throw new Error('renderBrowserPT not exported')

      const preset = QUALITY_PRESETS.find((p) => p.id === quality) ?? QUALITY_PRESETS[2]
      const blob = await mod.renderBrowserPT({
        rendererRef,
        samples: preset.samples,
        onProgress: (pct) => { if (!cancelledRef.current) setProgress(pct) },
      })
      if (cancelledRef.current) return

      setProgress(100)
      setStatus('done')
      setJob({ status: 'done', _browserBlob: blob })
    } catch (err) {
      if (!cancelledRef.current) {
        setStatus('failed')
        setErrorMsg(`Browser render failed: ${err.message ?? err}`)
      }
    }
  }

  // ── Production render: in-process CPU path tracer ─────────────────────────────
  // Calls the render worker's /render/pathtrace endpoint (genuine multi-bounce
  // Monte-Carlo GI: BVH, GGX/dielectric BSDFs, NEE). Returns a base64 PNG plus
  // convergence stats. Progressive: we poll in escalating sample chunks so the
  // image visibly refines and the sample count climbs.
  async function runProductionRender() {
    if (pollRef.current) clearTimeout(pollRef.current)
    cancelledRef.current = false
    setStatus('polling')
    setProgress(0)
    setSamplesRendered(0)
    setErrorMsg(null)
    setBrowserMode(false)
    setPtImage(null)
    setPtStats(null)

    const preset = QUALITY_PRESETS.find((p) => p.id === quality) ?? QUALITY_PRESETS[2]
    // Cap synchronous CPU path-trace samples; map quality presets down.
    const target = Math.min(256, Math.max(16, Math.round(preset.samples / 16)))
    // Escalating accumulation: render at increasing spp so the user sees it converge.
    const chunks = [16, 32, 64, 128, 256].filter((s) => s <= target)
    if (chunks[chunks.length - 1] !== target) chunks.push(target)

    try {
      for (let i = 0; i < chunks.length; i++) {
        if (cancelledRef.current) return
        const spp = chunks[i]
        const res = await fetch('/api/render/pathtrace', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            preset: 'cornell',
            width: 192,
            height: 192,
            samples: spp,
            max_depth: 8,
            seed: i,
          }),
        })
        if (!res.ok) {
          const isOffline = res.status === 503 || res.status === 0 || res.status === 404
          if (isOffline) { await runBrowserFallback(); return }
          throw new Error(`HTTP ${res.status}`)
        }
        const data = await res.json()
        if (cancelledRef.current) return
        if (data.image_b64) setPtImage(`data:image/png;base64,${data.image_b64}`)
        setPtStats(data)
        setSamplesRendered(data.samples ?? spp)
        setProgress(Math.round(((i + 1) / chunks.length) * 100))
      }
      if (cancelledRef.current) return
      setProgress(100)
      setStatus('done')
      setJob({ status: 'done' })
    } catch (err) {
      if (err instanceof TypeError) { await runBrowserFallback(); return }
      if (!cancelledRef.current) {
        setStatus('failed')
        setErrorMsg(`Path-traced render failed: ${err.message ?? err}`)
      }
    }
  }

  // ── Submit job ────────────────────────────────────────────────────────────────
  async function handleSubmit() {
    if (productionMode) { await runProductionRender(); return }
    if (pollRef.current) clearTimeout(pollRef.current)
    cancelledRef.current = false
    setStatus('submitting')
    setProgress(0)
    setSamplesRendered(0)
    setJob(null)
    setErrorMsg(null)
    setBrowserMode(false)

    const preset = QUALITY_PRESETS.find((p) => p.id === quality) ?? QUALITY_PRESETS[2]

    try {
      const res = await fetch('/api/render/job', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          quality,
          samples: preset.samples,
        }),
      })

      if (!res.ok) {
        const isOffline = res.status === 503 || res.status === 0
        if (isOffline) {
          await runBrowserFallback()
          return
        }
        const text = await res.text().catch(() => '')
        throw new Error(`HTTP ${res.status}: ${text}`)
      }

      const data = await res.json()
      setJob(data)
      setStatus('polling')
      pollJob(data.id ?? data.job_id)
    } catch (err) {
      // Network error → treat as offline, fall back to browser PT
      if (
        err instanceof TypeError ||
        (err.message && (err.message.includes('fetch') || err.message.includes('network') || err.message.includes('Failed to fetch')))
      ) {
        await runBrowserFallback()
        return
      }
      setStatus('failed')
      setErrorMsg(err.message ?? String(err))
    }
  }

  // ── Download helpers ──────────────────────────────────────────────────────────
  function handleDownloadPng(j = job) {
    if (!j) return
    if (j._browserBlob) { downloadBlob(j._browserBlob, `kerf-hero-${Date.now()}.png`); return }
    if (j.png_url) downloadUrl(j.png_url, `kerf-hero-${j.id ?? Date.now()}.png`)
  }

  function handleDownloadExr(j = job) {
    if (!j) return
    if (j.exr_url) downloadUrl(j.exr_url, `kerf-hero-${j.id ?? Date.now()}.exr`)
  }

  // ── Derived state ─────────────────────────────────────────────────────────────
  const busy           = status === 'submitting' || status === 'polling' || status === 'browser'
  const activePreset   = QUALITY_PRESETS.find((p) => p.id === quality) ?? QUALITY_PRESETS[2]
  const hasPng         = status === 'done' && (job?._browserBlob || job?.png_url)
  const hasExr         = status === 'done' && !job?._browserBlob && job?.exr_url

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div
      role="dialog"
      aria-label="Hero Render"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-ink-950/70 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.() }}
    >
      <div className="w-full sm:w-[480px] max-h-[90vh] flex flex-col rounded-t-xl sm:rounded-xl bg-ink-900 border border-ink-700 shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-ink-700">
          <span className="text-sm font-semibold text-ink-100 font-mono">Hero Render</span>
          <button
            type="button"
            aria-label="Close Hero Render panel"
            onClick={onClose}
            className="p-1 rounded text-ink-400 hover:text-ink-100 hover:bg-ink-800 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-ink-700">
          {[TAB_RENDER, TAB_GALLERY].map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={[
                'flex-1 py-2 text-[11px] font-mono capitalize transition-colors',
                tab === t
                  ? 'text-kerf-300 border-b-2 border-kerf-300 -mb-px'
                  : 'text-ink-400 hover:text-ink-200',
              ].join(' ')}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Tab: Render */}
        {tab === TAB_RENDER && (
          <div className="flex flex-col gap-4 p-4 overflow-y-auto">

            {/* Browser fallback banner */}
            {browserMode && (
              <div
                role="status"
                aria-label="Rendering in browser (free preview)"
                className="px-3 py-2 rounded bg-kerf-300/10 border border-kerf-300/40 text-[11px] font-mono text-kerf-300"
              >
                Rendering in browser (free preview) — backend offline
              </div>
            )}

            {/* Quality presets */}
            <fieldset>
              <legend className="text-[10px] font-mono text-ink-500 uppercase tracking-wider mb-2">
                Quality
              </legend>
              <div className="grid grid-cols-4 gap-1.5">
                {QUALITY_PRESETS.map((p) => (
                  <PresetButton
                    key={p.id}
                    preset={p}
                    active={quality === p.id}
                    onClick={setQuality}
                  />
                ))}
              </div>
            </fieldset>

            {/* Production render (path-traced GI) toggle */}
            <label className="flex items-center justify-between gap-3 px-3 py-2 rounded bg-ink-800/60 border border-ink-700 cursor-pointer">
              <span className="flex flex-col">
                <span className="text-[11px] font-mono text-ink-200">Production render</span>
                <span className="text-[9px] font-mono text-ink-500">
                  CPU path tracer — multi-bounce global illumination
                </span>
              </span>
              <input
                type="checkbox"
                role="switch"
                aria-label="Production render (path-traced global illumination)"
                aria-checked={productionMode}
                checked={productionMode}
                onChange={(e) => setProductionMode(e.target.checked)}
                className="accent-kerf-300 w-4 h-4"
              />
            </label>

            {/* Submit */}
            <button
              type="button"
              aria-label="Start Hero Render"
              disabled={busy}
              onClick={handleSubmit}
              className={[
                'w-full py-2 rounded text-[12px] font-mono font-semibold border transition-colors',
                busy
                  ? 'bg-ink-800 text-ink-500 border-ink-700 cursor-wait'
                  : 'bg-kerf-300 text-ink-950 border-kerf-300 hover:bg-kerf-400',
              ].join(' ')}
            >
              {status === 'submitting' ? 'Submitting…'
                : status === 'polling'    ? 'Rendering…'
                : status === 'browser'    ? 'Rendering in browser…'
                : status === 'done'       ? 'Render again'
                : 'Start render'}
            </button>

            {/* Accumulating path-traced image preview */}
            {productionMode && ptImage && (
              <figure className="flex flex-col gap-1">
                <img
                  src={ptImage}
                  alt="Path-traced render preview"
                  aria-label="Path-traced render preview"
                  className="w-full rounded border border-ink-700 bg-ink-950"
                  style={{ imageRendering: 'auto' }}
                />
                <figcaption className="text-[9px] font-mono text-ink-500 flex justify-between">
                  <span>{ptStats?.engine ?? 'kerf-cpu-pathtracer'}</span>
                  <span>
                    {ptStats?.samples != null ? `${ptStats.samples} spp` : ''}
                    {ptStats?.triangles != null ? ` · ${ptStats.triangles} tris` : ''}
                  </span>
                </figcaption>
              </figure>
            )}

            {/* Progress area */}
            {(busy || status === 'done') && (
              <div className="flex flex-col gap-2">
                <ProgressBar percent={progress} />
                <div className="flex justify-between text-[10px] font-mono text-ink-400">
                  <span>
                    {productionMode
                      ? (samplesRendered > 0 ? `${samplesRendered.toLocaleString()} spp (path-traced)` : 'path-traced')
                      : (samplesRendered > 0
                        ? `${samplesRendered.toLocaleString()} / ${activePreset.samples.toLocaleString()} spp`
                        : `${activePreset.samples.toLocaleString()} spp`)}
                  </span>
                  <span>{progress}%</span>
                </div>
              </div>
            )}

            {/* Error */}
            {status === 'failed' && errorMsg && (
              <div
                role="alert"
                className="px-3 py-2 rounded bg-red-900/30 border border-red-700/40 text-[11px] font-mono text-red-300"
              >
                {errorMsg}
              </div>
            )}

            {/* Download buttons */}
            {status === 'done' && (
              <div className="flex gap-2">
                {hasPng && (
                  <button
                    type="button"
                    aria-label="Download PNG"
                    onClick={() => handleDownloadPng()}
                    className="flex-1 py-2 rounded text-[11px] font-mono border bg-ink-800 text-ink-200 border-ink-600 hover:text-kerf-300 hover:border-kerf-300/50 transition-colors"
                  >
                    Download PNG
                  </button>
                )}
                {hasExr && (
                  <button
                    type="button"
                    aria-label="Download EXR"
                    onClick={() => handleDownloadExr()}
                    className="flex-1 py-2 rounded text-[11px] font-mono border bg-ink-800 text-ink-200 border-ink-600 hover:text-kerf-300 hover:border-kerf-300/50 transition-colors"
                  >
                    Download EXR
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {/* Tab: Gallery */}
        {tab === TAB_GALLERY && (
          <div className="flex flex-col gap-2 p-4 overflow-y-auto">
            {!projectId && (
              <p className="text-[11px] font-mono text-ink-500">No project selected.</p>
            )}
            {projectId && galleryLoading && (
              <p className="text-[11px] font-mono text-ink-500">Loading gallery…</p>
            )}
            {projectId && !galleryLoading && gallery.length === 0 && (
              <p className="text-[11px] font-mono text-ink-500">No renders yet for this project.</p>
            )}
            {gallery.map((j) => (
              <GalleryItem
                key={j.id ?? j.job_id}
                job={j}
                onDownloadPng={handleDownloadPng}
                onDownloadExr={handleDownloadExr}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Exported helpers for tests ─────────────────────────────────────────────────
export { POLL_INTERVAL_MS, JOB_TERMINAL }
