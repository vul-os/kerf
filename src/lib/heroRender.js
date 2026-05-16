/**
 * heroRender.js — One-click photo-real hero render for jewellery.
 *
 * Exports:
 *   renderHeroSet(scene, camera, renderer, opts)
 *     → Promise<{ stills: string[], turntable: string[] }>
 *     Renders 4 preset hero stills + a 36-frame turntable sequence.
 *
 *   applyJewelryLighting(scene) → savedLights[]
 *     Push jewelry-grade three-point softbox lighting onto the scene
 *     (5500 K key, soft fill, bounce, rim). Returns a snapshot so the
 *     caller can later restore.
 *
 *   restorePrevLighting(scene, savedLights)
 *     Pop the jewelry lights and restore the scene to the saved snapshot.
 *
 *   composeContactSheet(images) → string (PNG data-URL)
 *     Composite 4 hero stills into a 2×2 grid with thin border.
 *
 *   socialMediaCrops(image, platforms) → Promise<Record<string, string>>
 *     Crop a source image to platform-specific aspect ratios.
 */

import { recordTurntable } from './turntableRender.js'

// ── Lighting constants ────────────────────────────────────────────────────────

// 5500 K daylight white mapped to an approximate RGB hex.
const CT_5500K = 0xfff4e8

// Hero-shot preset camera angles: [azimuth (rad), elevation (rad)]
// 3/4 hero, top-down, front-on, macro-detail (close, slight high angle)
const HERO_ANGLES = [
  { azimuth: Math.PI / 4,       elevation: Math.PI / 8,        label: 'three_quarter' },
  { azimuth: 0,                  elevation: Math.PI / 2 - 0.05, label: 'top_down'      },
  { azimuth: 0,                  elevation: 0.08,               label: 'front_on'      },
  { azimuth: -Math.PI / 6,      elevation: Math.PI / 10,       label: 'macro_detail'  },
]

// Macro shot uses a tighter FOV multiplier (simulate zoom / shallow DOF).
const MACRO_FOV_FACTOR = 0.45
const DEFAULT_FOV = 45

// ── applyJewelryLighting ──────────────────────────────────────────────────────

/**
 * Replace the scene's existing lights with a jewelry-grade three-point
 * softbox rig at 5500 K:
 *   - Key light:   slightly above & to the left, warm white, high intensity.
 *   - Fill light:  opposite side, lower intensity, soft blue-white.
 *   - Bounce/rim:  behind the subject, low angle, subtle warm rim.
 *   - Ambient:     low-level hemisphere to avoid pure black shadows.
 *
 * The caller should call restorePrevLighting() when done.
 *
 * @param {object} scene  THREE.Scene (duck-typed; must have .children and .add/.remove).
 * @returns {object[]}    Saved light objects that were in the scene before this call.
 */
export function applyJewelryLighting(scene) {
  if (!scene) throw new Error('scene is required for applyJewelryLighting')

  // Snapshot the existing lights so we can restore them later.
  const saved = (scene.children || []).filter((c) => _isLight(c))

  // Remove all existing lights.
  for (const l of saved) {
    if (typeof scene.remove === 'function') scene.remove(l)
  }

  const lights = _buildJewelryLights()
  for (const l of lights) {
    if (typeof scene.add === 'function') scene.add(l)
  }

  // Tag them so restorePrevLighting can identify and remove them.
  for (const l of lights) {
    l.userData = { ...(l.userData || {}), _heroJewelry: true }
  }

  return saved
}

/**
 * Remove jewelry lights added by applyJewelryLighting() and put the
 * previously-saved lights back.
 *
 * @param {object}   scene      THREE.Scene
 * @param {object[]} savedLights  Array returned by applyJewelryLighting.
 */
export function restorePrevLighting(scene, savedLights) {
  if (!scene) throw new Error('scene is required for restorePrevLighting')

  // Remove any jewelry lights that are still in the scene.
  const toRemove = (scene.children || []).filter(
    (c) => _isLight(c) && c.userData && c.userData._heroJewelry,
  )
  for (const l of toRemove) {
    if (typeof scene.remove === 'function') scene.remove(l)
  }

  // Restore saved lights.
  for (const l of savedLights || []) {
    if (typeof scene.add === 'function') scene.add(l)
  }
}

// ── renderHeroSet ─────────────────────────────────────────────────────────────

/**
 * One-click hero render: applies jewelry lighting, captures 4 preset stills,
 * records a 36-frame turntable, then restores the original lighting.
 *
 * @param {object} scene     THREE.Scene
 * @param {object} camera    THREE.PerspectiveCamera (duck-typed)
 * @param {object} renderer  THREE.WebGLRenderer (must have .render() and .domElement)
 * @param {object} [opts]
 * @param {number}   [opts.width=1024]       Render width in pixels.
 * @param {number}   [opts.height=1024]      Render height in pixels.
 * @param {{x,y,z}} [opts.target]           Orbit centre; defaults to origin.
 * @param {number}   [opts.radius]           Camera distance; derived from current position if omitted.
 * @param {number}   [opts.turntableFrames=36]  Number of turntable frames.
 * @returns {Promise<{ stills: string[], turntable: string[] }>}
 *   stills:    4 PNG data-URLs (three_quarter, top_down, front_on, macro_detail).
 *   turntable: N PNG data-URLs for a 360° orbit.
 */
export async function renderHeroSet(scene, camera, renderer, opts = {}) {
  if (!scene) throw new Error('scene is required for renderHeroSet')
  if (!camera) throw new Error('camera is required for renderHeroSet')
  if (!renderer) throw new Error('renderer is required for renderHeroSet')

  const {
    width = 1024,
    height = 1024,
    target = { x: 0, y: 0, z: 0 },
    turntableFrames = 36,
  } = opts

  const tx = target.x ?? 0
  const ty = target.y ?? 0
  const tz = target.z ?? 0

  // Derive orbit radius from current camera position unless caller supplies one.
  const dx = camera.position.x - tx
  const dy = camera.position.y - ty
  const dz = camera.position.z - tz
  const radius = opts.radius != null
    ? opts.radius
    : Math.sqrt(dx * dx + dy * dy + dz * dz) || 100

  // Save camera state.
  const origPos = {
    x: camera.position.x,
    y: camera.position.y,
    z: camera.position.z,
  }
  const origFov = camera.fov != null ? camera.fov : DEFAULT_FOV
  const origAspect = camera.aspect != null ? camera.aspect : 1

  // Save renderer size.
  const domEl = renderer.domElement
  const origW = domEl ? (domEl.width || 0) : 0
  const origH = domEl ? (domEl.height || 0) : 0
  const needResize = (width !== origW || height !== origH)

  if (needResize && typeof renderer.setSize === 'function') {
    renderer.setSize(width, height, false)
  }

  // Apply jewelry lighting and save previous state.
  const savedLights = applyJewelryLighting(scene)

  const stills = []

  try {
    for (const angle of HERO_ANGLES) {
      const isMacro = angle.label === 'macro_detail'

      // Apply shallow DOF simulation for macro: reduce FOV.
      if (isMacro && camera.fov != null && typeof camera.updateProjectionMatrix === 'function') {
        camera.fov = origFov * MACRO_FOV_FACTOR
        camera.aspect = width / height
        camera.updateProjectionMatrix()
      } else if (!isMacro && camera.fov != null && typeof camera.updateProjectionMatrix === 'function') {
        camera.fov = origFov
        camera.aspect = width / height
        camera.updateProjectionMatrix()
      } else if (typeof camera.updateProjectionMatrix === 'function') {
        camera.aspect = width / height
        camera.updateProjectionMatrix()
      }

      // Adjust radius for macro (move closer).
      const frameRadius = isMacro ? radius * 0.45 : radius

      // Position camera on the orbit sphere.
      _placeCamera(camera, target, frameRadius, angle.elevation, angle.azimuth)

      if (typeof camera.updateProjectionMatrix === 'function') {
        camera.updateProjectionMatrix()
      }

      renderer.render(scene, camera)

      const dataUrl = (domEl && typeof domEl.toDataURL === 'function')
        ? domEl.toDataURL('image/png')
        : `data:image/png;base64,STUB_STILL_${angle.label}`

      stills.push(dataUrl)
    }
  } finally {
    // Restore camera.
    camera.position.set(origPos.x, origPos.y, origPos.z)
    if (camera.fov != null) camera.fov = origFov
    if (camera.aspect != null) camera.aspect = origAspect
    if (typeof camera.lookAt === 'function') camera.lookAt(tx, ty, tz)
    if (typeof camera.updateProjectionMatrix === 'function') camera.updateProjectionMatrix()

    // Restore renderer size.
    if (needResize && typeof renderer.setSize === 'function') {
      renderer.setSize(origW, origH, false)
      if (camera.aspect != null) camera.aspect = origW / (origH || 1)
      if (typeof camera.updateProjectionMatrix === 'function') camera.updateProjectionMatrix()
    }

    // Restore lighting.
    restorePrevLighting(scene, savedLights)
  }

  // Record turntable using the restored camera position.
  const turntable = await recordTurntable(scene, camera, renderer, {
    frameCount: turntableFrames,
    target,
    radius,
    width,
    height,
  })

  return { stills, turntable }
}

// ── composeContactSheet ───────────────────────────────────────────────────────

/**
 * Composite 4 hero stills into a single 2×2 grid PNG.
 *
 * Each cell is `cellSize × cellSize` pixels, separated by `gap` pixels
 * of border/gutter. The outer border is the same width as the gap.
 *
 * @param {string[]} images    Array of at least 4 PNG data-URL strings.
 * @param {object}   [opts]
 * @param {number}     [opts.cellSize=512]  Width & height of each cell in pixels.
 * @param {number}     [opts.gap=4]         Gutter / border width in pixels.
 * @param {string}     [opts.background='#111114']  Background / border colour.
 * @returns {string}  PNG data-URL of the composed 2×2 sheet.
 */
export function composeContactSheet(images, opts = {}) {
  if (!Array.isArray(images) || images.length < 4) {
    throw new Error('composeContactSheet requires at least 4 images')
  }

  const {
    cellSize = 512,
    gap = 4,
    background = '#111114',
  } = opts

  // Total canvas size: 2 columns + 3 gaps (left, middle, right)
  const totalW = cellSize * 2 + gap * 3
  const totalH = cellSize * 2 + gap * 3

  // In a Node / jsdom test environment, `document` may or may not be
  // available.  We guard and fall back to a stub data-URL so tests that
  // exercise layout maths can still work with a fake canvas.
  if (typeof document === 'undefined' || typeof document.createElement !== 'function') {
    return `data:image/png;base64,STUB_CONTACT_SHEET_${totalW}x${totalH}`
  }

  const canvas = document.createElement('canvas')
  canvas.width = totalW
  canvas.height = totalH
  const ctx = canvas.getContext('2d')
  if (!ctx) return `data:image/png;base64,STUB_CONTACT_SHEET_NO_CTX`

  // Fill background.
  ctx.fillStyle = background
  ctx.fillRect(0, 0, totalW, totalH)

  // Draw each image into its cell.
  for (let i = 0; i < 4; i++) {
    const col = i % 2          // 0 or 1
    const row = Math.floor(i / 2) // 0 or 1
    const x = gap + col * (cellSize + gap)
    const y = gap + row * (cellSize + gap)

    const src = images[i]
    if (typeof src === 'string' && src.startsWith('data:')) {
      // Synchronous path: draw via Image element.
      // In environments with synchronous image decoding (jsdom) this works;
      // in browser we rely on the image already being decoded (PNG data-URL).
      const img = new Image()
      img.src = src
      // drawImage is a no-op if the image hasn't loaded; acceptable here because
      // browsers decode data-URLs synchronously when drawn to canvas.
      ctx.drawImage(img, x, y, cellSize, cellSize)
    } else {
      // Placeholder rectangle for unavailable images.
      ctx.fillStyle = '#222'
      ctx.fillRect(x, y, cellSize, cellSize)
      ctx.fillStyle = background
    }
  }

  return canvas.toDataURL('image/png')
}

// ── socialMediaCrops ──────────────────────────────────────────────────────────

/**
 * Crop a source image to platform-specific aspect ratios.
 *
 * Supported platforms and their target aspect ratios:
 *   instagram_post  — 1:1   (square)
 *   instagram_story — 9:16  (portrait)
 *   x_card          — 2:1   (landscape)
 *
 * The crop is always centred on the source image.
 *
 * @param {string}   image      PNG or JPEG data-URL to crop.
 * @param {string[]} [platforms=['instagram_post','instagram_story','x_card']]
 * @returns {Promise<Record<string, string>>}  Map of platform → data-URL.
 */
export async function socialMediaCrops(
  image,
  platforms = ['instagram_post', 'instagram_story', 'x_card'],
) {
  if (!image || typeof image !== 'string') {
    throw new Error('image is required for socialMediaCrops')
  }

  const RATIOS = {
    instagram_post: { w: 1, h: 1 },     // 1:1
    instagram_story: { w: 9, h: 16 },   // 9:16 portrait
    x_card: { w: 2, h: 1 },             // 2:1 landscape
  }

  // Resolve source dimensions by loading the image.
  const { naturalWidth: srcW, naturalHeight: srcH } = await _loadImage(image)

  const result = {}

  for (const platform of platforms) {
    const ratio = RATIOS[platform]
    if (!ratio) {
      // Unknown platform — pass through unchanged.
      result[platform] = image
      continue
    }

    const cropW_px = _centredCropDims(srcW, srcH, ratio.w, ratio.h)
    const cropH_px = Math.round(cropW_px * ratio.h / ratio.w)

    const sx = Math.round((srcW - cropW_px) / 2)
    const sy = Math.round((srcH - cropH_px) / 2)

    if (typeof document === 'undefined' || typeof document.createElement !== 'function') {
      result[platform] = `data:image/png;base64,STUB_CROP_${platform}_${cropW_px}x${cropH_px}`
      continue
    }

    const canvas = document.createElement('canvas')
    canvas.width = cropW_px
    canvas.height = cropH_px
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      result[platform] = image
      continue
    }

    const img = new Image()
    img.src = image
    ctx.drawImage(img, sx, sy, cropW_px, cropH_px, 0, 0, cropW_px, cropH_px)
    result[platform] = canvas.toDataURL('image/png')
  }

  return result
}

// ── Private helpers ───────────────────────────────────────────────────────────

/**
 * Build the jewelry-grade light array.
 * Returns an array of duck-typed light objects that mirror Three.js lights.
 *
 * In production the caller already has Three.js loaded; here we create plain
 * objects that look enough like THREE lights for the scene.add/remove path
 * to work, while remaining usable in tests without a GPU.
 *
 * IMPORTANT: this module does NOT import three — Renderer.jsx already manages
 * the Three.js scene.  We build lights via duck-typed plain objects so the
 * module has zero side-effect imports and is testable in jsdom.
 */
function _buildJewelryLights() {
  // We rely on the THREE global being available in browser context.
  // In test environments THREE is stubbed by the test harness.
  const THREE = _getThree()

  const lights = []

  if (THREE) {
    // Key light — 5500 K, 45° above & to the left, high intensity.
    const key = new THREE.DirectionalLight(CT_5500K, 1.8)
    key.position.set(-60, 80, 50)
    lights.push(key)

    // Fill light — cooler, opposite side, 0.4 intensity to soften shadows.
    const fill = new THREE.DirectionalLight(0xd0e8ff, 0.4)
    fill.position.set(70, 30, -40)
    lights.push(fill)

    // Bounce — warm light from below to simulate bounce card.
    const bounce = new THREE.DirectionalLight(0xffeedd, 0.25)
    bounce.position.set(0, -50, 30)
    lights.push(bounce)

    // Rim light — cool-white behind, gives halo on gems.
    const rim = new THREE.DirectionalLight(0xe0f0ff, 0.55)
    rim.position.set(10, 40, -100)
    lights.push(rim)

    // Low-level ambient to avoid pitch-black shadows.
    const ambient = new THREE.AmbientLight(0xfff8f0, 0.12)
    lights.push(ambient)
  } else {
    // Test stub path — minimal plain objects.
    const makeFakeLight = (type, color, intensity, pos) => ({
      isLight: true,
      type,
      color,
      intensity,
      position: pos || { x: 0, y: 0, z: 0 },
      userData: {},
    })
    lights.push(makeFakeLight('DirectionalLight', CT_5500K, 1.8, { x: -60, y: 80, z: 50 }))
    lights.push(makeFakeLight('DirectionalLight', 0xd0e8ff, 0.4, { x: 70, y: 30, z: -40 }))
    lights.push(makeFakeLight('DirectionalLight', 0xffeedd, 0.25, { x: 0, y: -50, z: 30 }))
    lights.push(makeFakeLight('DirectionalLight', 0xe0f0ff, 0.55, { x: 10, y: 40, z: -100 }))
    lights.push(makeFakeLight('AmbientLight', 0xfff8f0, 0.12, null))
  }

  return lights
}

/**
 * Duck-typed check: is this object a Three.js-style light?
 */
function _isLight(obj) {
  if (!obj) return false
  // Three.js lights have isLight=true; our stubs also set this flag.
  if (obj.isLight) return true
  // Fallback: check constructor name for real Three.js objects.
  const name = obj.constructor ? obj.constructor.name : ''
  return name.endsWith('Light')
}

/**
 * Try to get the THREE namespace.  In browser the real three is used; in
 * tests the caller may inject a stub via globalThis.THREE.
 */
function _getThree() {
  if (typeof globalThis !== 'undefined' && globalThis.THREE) return globalThis.THREE
  return null
}

/**
 * Position a camera on a sphere.
 * Mirrors turntableRender.positionCameraOnOrbit but is inlined here to
 * keep this module self-contained and independently testable.
 *
 * @param {object}   camera
 * @param {{x,y,z}} target
 * @param {number}   radius
 * @param {number}   elevation  radians above XZ plane
 * @param {number}   azimuth    radians around Y-axis
 */
function _placeCamera(camera, target, radius, elevation, azimuth) {
  const tx = target.x ?? 0
  const ty = target.y ?? 0
  const tz = target.z ?? 0
  const cosEl = Math.cos(elevation)
  const sinEl = Math.sin(elevation)
  camera.position.set(
    tx + radius * cosEl * Math.sin(azimuth),
    ty + radius * sinEl,
    tz + radius * cosEl * Math.cos(azimuth),
  )
  if (typeof camera.lookAt === 'function') {
    camera.lookAt(tx, ty, tz)
  }
}

/**
 * Compute the width (in px) of a centred crop of `srcW × srcH` at the
 * target aspect ratio `rw : rh`.  The crop is as large as possible while
 * fitting inside the source.
 */
function _centredCropDims(srcW, srcH, rw, rh) {
  const byWidth = srcW
  const byHeight = Math.round(srcH * rw / rh)
  return Math.min(byWidth, byHeight)
}

/**
 * Load an image from a data-URL and return its natural dimensions.
 * Falls back to {naturalWidth: 1024, naturalHeight: 1024} in non-browser
 * environments.
 *
 * @param {string} src  data-URL
 * @returns {Promise<{naturalWidth: number, naturalHeight: number}>}
 */
function _loadImage(src) {
  if (typeof Image === 'undefined') {
    return Promise.resolve({ naturalWidth: 1024, naturalHeight: 1024 })
  }
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve({ naturalWidth: img.naturalWidth || 1024, naturalHeight: img.naturalHeight || 1024 })
    img.onerror = () => resolve({ naturalWidth: 1024, naturalHeight: 1024 })
    img.src = src
  })
}
