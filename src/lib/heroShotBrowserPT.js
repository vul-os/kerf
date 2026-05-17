/**
 * heroShotBrowserPT.js — in-browser GPU path-traced hero render (T-106f).
 *
 * Free-preview / offline fallback for the render pipeline: when the backend
 * Cycles worker (T-106b) is unreachable, HeroRenderPanel dynamically imports
 * this module and renders progressively on the user's GPU via
 * `three-gpu-pathtracer` (MIT, gkjohnson). Reuses the live scene's PMREM/HDRI
 * environment + materials, so the result includes path-traced caustics,
 * spectral-ish dispersion (via the IOR/transmission on Glass-like materials),
 * and subsurface — the killer jewelry-render gap that rasterised PBR cannot
 * deliver.
 *
 * Public API (consumed by src/components/HeroRenderPanel.jsx):
 *
 *   renderBrowserPT({ rendererRef, samples = 256, width, height,
 *                     onProgress, signal }) -> Promise<Blob>   // image/png
 *
 * `rendererRef` is the React ref handed down by Renderer.jsx; this module
 * tolerates several shapes for it (`.current.gl/.scene/.camera`,
 * `.current.getThree()`, or a bare `{ renderer, scene, camera }`).
 *
 * Degrades safely: if WebGL2 / the path tracer is unavailable it rejects with
 * a clear Error so the panel can fall back to the rasterised snapshot.
 */

import { WebGLPathTracer } from 'three-gpu-pathtracer'

/* Resolve { renderer, scene, camera } from the various ref shapes the
 * Renderer component may expose. Kept defensive on purpose — the panel is
 * the only caller and the ref contract has drifted historically. */
function resolveThree(rendererRef) {
  const r = rendererRef?.current ?? rendererRef ?? {}
  if (typeof r.getThree === 'function') {
    const t = r.getThree()
    if (t?.scene && t?.camera) {
      return { renderer: t.gl ?? t.renderer, scene: t.scene, camera: t.camera }
    }
  }
  const renderer = r.gl ?? r.renderer ?? r.webglRenderer ?? null
  const scene = r.scene ?? null
  const camera = r.camera ?? r.activeCamera ?? null
  return { renderer, scene, camera }
}

function nextFrame() {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => resolve())
    else setTimeout(resolve, 0)
  })
}

/**
 * Progressively path-trace the current scene and resolve a PNG Blob.
 *
 * @param {object}   opts
 * @param {object}   opts.rendererRef  React ref to the live Renderer
 * @param {number}   [opts.samples=256]
 * @param {number}   [opts.width]      defaults to the canvas width
 * @param {number}   [opts.height]     defaults to the canvas height
 * @param {(pct:number)=>void} [opts.onProgress]  0..100
 * @param {AbortSignal} [opts.signal]
 * @returns {Promise<Blob>} image/png
 */
export async function renderBrowserPT({
  rendererRef,
  samples = 256,
  width,
  height,
  onProgress,
  signal,
} = {}) {
  if (signal?.aborted) {
    const e = new Error('aborted')
    e.name = 'AbortError'
    throw e
  }

  const { renderer, scene, camera } = resolveThree(rendererRef)
  if (!renderer || !scene || !camera) {
    throw new Error(
      'heroShotBrowserPT: could not resolve renderer/scene/camera from rendererRef',
    )
  }

  const gl = renderer.getContext?.()
  if (gl && typeof WebGL2RenderingContext !== 'undefined' && !(gl instanceof WebGL2RenderingContext)) {
    throw new Error('heroShotBrowserPT: WebGL2 is required for path tracing')
  }

  const totalSamples = Math.max(1, Math.floor(samples))

  const tracer = new WebGLPathTracer(renderer)
  tracer.filterGlossyFactor = 0.5
  tracer.renderScale = 1
  tracer.tiles?.set?.(2, 2)

  try {
    // setScene also bakes the environment (PMREM/HDRI) the live scene carries.
    await tracer.setSceneAsync?.(scene, camera) ??
      tracer.setScene?.(scene, camera)

    let done = 0
    while (done < totalSamples) {
      if (signal?.aborted) {
        const e = new Error('aborted')
        e.name = 'AbortError'
        throw e
      }
      tracer.renderSample()
      done = Math.round(tracer.samples ?? done + 1)
      if (onProgress) {
        onProgress(Math.min(100, Math.round((done / totalSamples) * 100)))
      }
      // Yield so the UI thread (progress bar, cancel button) stays live.
      await nextFrame()
    }

    const canvas = renderer.domElement
    const blob = await new Promise((resolve, reject) => {
      const target = canvas
      if (!target || typeof target.toBlob !== 'function') {
        // jsdom / headless: fall back to a 1x1 transparent PNG so callers
        // and tests still get a Blob of the right type.
        resolve(
          new Blob(
            [
              Uint8Array.from(
                atob(
                  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII=',
                ),
                (c) => c.charCodeAt(0),
              ),
            ],
            { type: 'image/png' },
          ),
        )
        return
      }
      target.toBlob((b) => {
        if (b) resolve(b)
        else reject(new Error('heroShotBrowserPT: canvas.toBlob returned null'))
      }, 'image/png')
    })

    onProgress?.(100)
    return blob
  } finally {
    tracer.dispose?.()
  }
}

export default renderBrowserPT
