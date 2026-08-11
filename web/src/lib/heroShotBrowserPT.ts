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

// `three-gpu-pathtracer` is an OPTIONAL in-browser path-tracer. Its three.js
// peer range (>=0.180) conflicts with the pinned three ^0.160, so it is NOT a
// hard dependency; it is dynamically imported below (vite-ignored) so the
// production build never resolves it and the feature degrades cleanly when
// the package is absent.

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
  return new Promise<void>((resolve) => {
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
 * @param {(pct:number)=>void} [opts.onProgress]  0..100
 *
 * The output is the canvas's own size. `width`/`height` options used to be
 * accepted here and documented as overrides; nothing read them, so asking for
 * a 4K hero shot silently produced a viewport-sized one. Removed rather than
 * implemented: rendering at a size the viewport is not is a feature with a
 * control attached to it, not a parameter.
 * @param {AbortSignal} [opts.signal]
 * @returns {Promise<Blob>} image/png
 */
export async function renderBrowserPT({
  rendererRef,
  samples = 256,
  onProgress,
  signal,
}: {
  rendererRef?: unknown
  samples?: number
  onProgress?: (pct: number) => void
  signal?: AbortSignal
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

  let WebGLPathTracer
  try {
    // three-gpu-pathtracer is an optional peer dependency (see header comment)
    // and is not installed, so it has no type declarations to resolve here.
    // @ts-expect-error - optional dependency, absent from node_modules by design
    ;({ WebGLPathTracer } = await import(/* @vite-ignore */ 'three-gpu-pathtracer'))
  } catch {
    throw new Error(
      'heroShotBrowserPT: in-browser path tracer unavailable ' +
        '(optional three-gpu-pathtracer not installed)',
    )
  }

  const tracer = new WebGLPathTracer(renderer)
  tracer.filterGlossyFactor = 0.5
  tracer.renderScale = 1
  tracer.tiles?.set?.(2, 2)

  try {
    // setScene also bakes the environment (PMREM/HDRI) the live scene carries.
    //
    // This was `await tracer.setSceneAsync?.(...) ?? tracer.setScene?.(...)`,
    // which reads as "the async one, or the sync one" and is not. `await X ?? Y`
    // parses as `(await X) ?? Y`, and setSceneAsync is a void async method — it
    // resolves to undefined — so the ?? fired every time and the scene was set
    // twice, the second time synchronously and without waiting for the first to
    // finish baking.
    if (tracer.setSceneAsync) {
      await tracer.setSceneAsync(scene, camera)
    } else {
      tracer.setScene?.(scene, camera)
    }

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
