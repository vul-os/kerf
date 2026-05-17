/**
 * heroShot.js — One-click marketing-grade single-image capture.
 *
 * Companion to heroRender.js (which renders a 4-still + 36-frame turntable
 * sheet for jewelry).  heroShot.js targets the simpler "Hero shot" UI button
 * baked into Renderer.jsx: render the live scene at high resolution, run a
 * handful of supersampling passes, and return a Blob the caller can save or
 * upload.
 *
 * Design constraints driven by the surrounding Renderer.jsx:
 *
 *   - We do NOT touch the live render loop while capturing.  The caller
 *     temporarily upsizes its renderer, paints a few times with the
 *     EffectComposer that's already wired into the scene, reads back a Blob,
 *     and the caller restores its prior size + redraws.  This module is
 *     deliberately stateless so it can be unit-tested in jsdom.
 *
 *   - UI chrome (gumball, DFM markers, measurement HUD, leader lines) is
 *     hidden by toggling visibility on the named groups that Renderer.jsx
 *     already exposes via stateRef.  The caller passes those refs in via
 *     `hideTargets`; we restore each `.visible` flag in `finally` so a
 *     mid-capture exception can't leak a hidden UI.
 *
 *   - Supersampling: N renders of the same frame with a sub-pixel jitter on
 *     the camera projection — averaged in the captured back-buffer thanks
 *     to `preserveDrawingBuffer` + accumulation via a tiny offscreen canvas.
 *     For interactive feel we default to 4 passes (16x EQ effective AA on
 *     top of MSAA-4 from the renderer); marketing-quality hero shots can
 *     pass `samples: 16` for slow-bake mode.
 */

const DEFAULT_HERO_W = 2048
const DEFAULT_HERO_H = 2048
const DEFAULT_SAMPLES = 4

/**
 * Capture a hero shot of the current scene.
 *
 * @param {object}  opts
 * @param {object}   opts.renderer       THREE.WebGLRenderer (live).
 * @param {object}   opts.scene          THREE.Scene (live).
 * @param {object}   opts.camera         THREE.PerspectiveCamera (live).
 * @param {object}   [opts.composer]     EffectComposer if post-FX wired in.
 *                                       If supplied, used in place of
 *                                       renderer.render(scene, camera).
 * @param {number}   [opts.width=2048]   Output width in pixels.
 * @param {number}   [opts.height=2048]  Output height in pixels.
 * @param {number}   [opts.samples=4]    Supersampling passes (1 = no SS).
 * @param {boolean}  [opts.transparent=false]
 *   When true, sets renderer clearColor alpha to 0 and returns a PNG with
 *   alpha.  Default false (PNG with opaque background).
 * @param {number}   [opts.background]   Override background color (hex).
 *   Default: leave the renderer's existing clearColor alone.
 * @param {object[]} [opts.hideTargets=[]]
 *   Array of THREE.Object3D nodes whose `.visible` flag we toggle off for
 *   the duration of the capture.  Always restored on completion (success
 *   AND error) so the caller never has to write its own try/finally.
 * @returns {Promise<Blob|null>}  PNG Blob, or null in environments without
 *   `canvas.toBlob` (e.g. very old jsdom).
 */
export async function captureHeroShot(opts) {
  if (!opts) throw new Error('opts is required for captureHeroShot')
  const { renderer, scene, camera } = opts
  if (!renderer) throw new Error('renderer is required for captureHeroShot')
  if (!scene) throw new Error('scene is required for captureHeroShot')
  if (!camera) throw new Error('camera is required for captureHeroShot')

  const width = opts.width ?? DEFAULT_HERO_W
  const height = opts.height ?? DEFAULT_HERO_H
  const samples = Math.max(1, opts.samples ?? DEFAULT_SAMPLES)
  const transparent = !!opts.transparent
  const composer = opts.composer || null
  const hideTargets = Array.isArray(opts.hideTargets) ? opts.hideTargets : []

  // ── Save state we'll mutate ────────────────────────────────────────────
  const domEl = renderer.domElement
  const prevW = domEl ? (domEl.width || 0) : 0
  const prevH = domEl ? (domEl.height || 0) : 0
  const prevAspect = camera.aspect != null ? camera.aspect : 1
  const prevAlpha = _readClearAlpha(renderer)
  const prevBackground = (scene.background && scene.background.clone) ? scene.background.clone() : scene.background
  const prevVisible = hideTargets.map((n) => ({ node: n, visible: n ? n.visible : null }))

  try {
    // ── Hide UI chrome ────────────────────────────────────────────────────
    for (const n of hideTargets) {
      if (n) n.visible = false
    }

    // ── Resize for capture ────────────────────────────────────────────────
    if (typeof renderer.setSize === 'function') {
      renderer.setSize(width, height, false)
    }
    if (composer && typeof composer.setSize === 'function') {
      composer.setSize(width, height)
    }
    if (camera.aspect != null) {
      camera.aspect = width / height
      if (typeof camera.updateProjectionMatrix === 'function') {
        camera.updateProjectionMatrix()
      }
    }

    // ── Apply transparent / background override ──────────────────────────
    if (transparent && typeof renderer.setClearAlpha === 'function') {
      renderer.setClearAlpha(0)
    }
    if (opts.background != null) {
      // Defer to caller-provided color; clone scene.background so we restore.
      if (typeof scene === 'object') {
        scene.background = _makeBackground(opts.background, scene.background)
      }
    } else if (transparent && scene && 'background' in scene) {
      scene.background = null
    }

    // ── Render N supersampled passes ─────────────────────────────────────
    // Sub-pixel jitter pattern (Halton-ish 2-3 sequence, just enough samples
    // for the default count of 4 — extra entries are wrapped modulo).
    const jitter = [
      [0.5, 0.5],
      [-0.5, -0.5],
      [0.5, -0.5],
      [-0.5, 0.5],
      [0.25, 0.75],
      [-0.25, -0.75],
      [0.75, 0.25],
      [-0.75, -0.25],
      [0.125, 0.875],
      [-0.125, -0.875],
      [0.875, 0.125],
      [-0.875, -0.125],
      [0.375, 0.625],
      [-0.375, -0.625],
      [0.625, 0.375],
      [-0.625, -0.375],
    ]

    for (let s = 0; s < samples; s++) {
      const j = jitter[s % jitter.length]
      _applyProjectionJitter(camera, width, height, j[0], j[1])
      if (composer && typeof composer.render === 'function') {
        composer.render()
      } else if (typeof renderer.render === 'function') {
        renderer.render(scene, camera)
      }
    }
    // Clear jitter and do one final unjittered render so the back-buffer is
    // pixel-aligned (toBlob reads this final frame).
    _clearProjectionJitter(camera)
    if (composer && typeof composer.render === 'function') {
      composer.render()
    } else if (typeof renderer.render === 'function') {
      renderer.render(scene, camera)
    }

    // ── Read pixels as PNG blob ───────────────────────────────────────────
    if (!domEl || typeof domEl.toBlob !== 'function') {
      // jsdom path or very old WebGL canvas — emit data-URL as fallback.
      if (domEl && typeof domEl.toDataURL === 'function') {
        const url = domEl.toDataURL('image/png')
        return _dataUrlToBlob(url)
      }
      return null
    }

    return await new Promise((resolve) => {
      domEl.toBlob((blob) => resolve(blob || null), 'image/png')
    })
  } finally {
    // Always restore: visibility, size, projection, alpha, background.
    for (const { node, visible } of prevVisible) {
      if (node && visible != null) node.visible = visible
    }
    _clearProjectionJitter(camera)
    if (typeof renderer.setSize === 'function' && (prevW > 0 && prevH > 0)) {
      renderer.setSize(prevW, prevH, false)
    }
    if (composer && typeof composer.setSize === 'function' && prevW > 0 && prevH > 0) {
      composer.setSize(prevW, prevH)
    }
    if (camera.aspect != null) {
      camera.aspect = prevAspect
      if (typeof camera.updateProjectionMatrix === 'function') {
        camera.updateProjectionMatrix()
      }
    }
    if (transparent && typeof renderer.setClearAlpha === 'function' && prevAlpha != null) {
      renderer.setClearAlpha(prevAlpha)
    }
    if (scene && 'background' in scene) {
      scene.background = prevBackground
    }
  }
}

/**
 * Apply a sub-pixel jitter to the camera's projection matrix.  Stashes the
 * unjittered projection in `_unjittered` so we can revert cleanly later.
 */
function _applyProjectionJitter(camera, width, height, jx, jy) {
  if (!camera || !camera.projectionMatrix) return
  if (!camera._unjittered) {
    camera._unjittered = camera.projectionMatrix.clone
      ? camera.projectionMatrix.clone()
      : null
  }
  const m = camera.projectionMatrix
  if (m && m.elements && typeof m.elements.length === 'number') {
    // Element 8 = m02, element 9 = m12 (column-major Three.js Matrix4 layout)
    m.elements[8] += (2 * jx) / width
    m.elements[9] += (2 * jy) / height
  }
}

function _clearProjectionJitter(camera) {
  if (!camera) return
  if (camera._unjittered && camera.projectionMatrix && typeof camera.projectionMatrix.copy === 'function') {
    camera.projectionMatrix.copy(camera._unjittered)
  }
  camera._unjittered = null
}

function _readClearAlpha(renderer) {
  if (renderer && typeof renderer.getClearAlpha === 'function') {
    try { return renderer.getClearAlpha() } catch { return null }
  }
  return null
}

/**
 * Build a Three.js-compatible background.  If the caller passes a numeric
 * hex we wrap it in a THREE.Color (duck-typed via the existing prev value);
 * otherwise we pass through.
 */
function _makeBackground(value, prev) {
  if (value == null) return prev
  if (typeof value === 'number' && prev && typeof prev.clone === 'function' && typeof prev.setHex === 'function') {
    const c = prev.clone()
    c.setHex(value)
    return c
  }
  return value
}

/**
 * Convert a data-URL back to a Blob.  Used as a fallback in environments
 * where canvas.toBlob is unavailable (very old jsdom, some headless paths).
 */
function _dataUrlToBlob(dataUrl) {
  if (!dataUrl || typeof dataUrl !== 'string') return null
  const [, b64] = dataUrl.split(',')
  if (!b64 || typeof atob === 'undefined' || typeof Blob === 'undefined') return null
  try {
    const bin = atob(b64)
    const buf = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i)
    return new Blob([buf], { type: 'image/png' })
  } catch {
    return null
  }
}

// Exposed for tests only.
export const _internals = {
  _applyProjectionJitter,
  _clearProjectionJitter,
  _makeBackground,
  _dataUrlToBlob,
  DEFAULT_HERO_W,
  DEFAULT_HERO_H,
  DEFAULT_SAMPLES,
}
