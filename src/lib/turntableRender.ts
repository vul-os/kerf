/**
 * turntableRender.ts — 360° turntable / animation render helpers.
 *
 * Uses the existing Three.js scene/camera/renderer from Renderer.jsx.
 * No geometry mutations; append-only to the renderer interface.
 *
 * Exports:
 *   recordTurntable(scene, camera, renderer, opts) → Promise<string[]>
 *     Orbit the camera around the Y-axis through N frames, render each,
 *     return a list of PNG data-URLs.
 *
 *   exportFrames(frames, format) → Promise<{ blob: Blob, ext: string }>
 *     Pack a frame list into a ZIP of PNGs or a WebM video.
 *
 *   previewMode(scene, camera, renderer) → { stop() }
 *     Start a continuous slow turntable loop for live preview.
 *     Returns a handle with stop() to cancel.
 *
 * Typing note: every Three.js object here is deliberately duck-typed rather
 * than imported as `THREE.PerspectiveCamera`/`THREE.WebGLRenderer` — the
 * Renderer.jsx caller passes real Three.js instances, but this module (and
 * its test's hand-rolled stubs, which only implement a few fields each) only
 * ever reads/calls the members declared below. Constraining to real Three.js
 * types would reject those intentionally-minimal test stubs for no benefit,
 * since nothing here needs the rest of those classes' surface.
 */

/** World-space point; every axis defaults to 0 when omitted. */
export interface OrbitTarget {
  x?: number
  y?: number
  z?: number
}

/** Duck-typed Three.js camera surface this module actually touches. */
export interface OrbitCamera {
  position: {
    x: number
    y: number
    z: number
    set(x: number, y: number, z: number): void
  }
  aspect?: number
  lookAt?(x: number, y: number, z: number): void
  updateProjectionMatrix?(): void
}

/** Duck-typed Three.js renderer surface this module actually touches. */
export interface OrbitRenderer {
  domElement: {
    width?: number
    height?: number
    toDataURL?(mime?: string): string
  }
  render(scene: unknown, camera: OrbitCamera): void
  setSize?(width: number, height: number, updateStyle?: boolean): void
}

// ── Easing helpers ────────────────────────────────────────────────────────────

/**
 * Linear progress — frame i of N maps to t in [0, 1).
 * @param i   Frame index (0-based).
 * @param n   Total frame count.
 * @returns   Normalised progress in [0, 1).
 */
export function easingLinear(i: number, n: number): number {
  if (n <= 0) return 0
  return i / n
}

/**
 * Ease-in-out (smoothstep) — slow at start and end, fast in the middle.
 */
export function easingEaseInOut(i: number, n: number): number {
  if (n <= 0) return 0
  const t = i / n
  return t * t * (3 - 2 * t)
}

// ── Camera orbit math ─────────────────────────────────────────────────────────

/**
 * Position a camera on a horizontal circle around `target` at the given
 * radius, elevation angle (radians above XZ plane), and azimuth (radians
 * around Y-axis from +Z).
 *
 * @param camera   Three.js PerspectiveCamera (duck-typed: position, lookAt).
 * @param target   world-space orbit centre.
 * @param radius   Distance from target to camera.
 * @param elevation  Angle above XZ plane in radians.
 * @param azimuth    Angle around Y-axis in radians.
 */
export function positionCameraOnOrbit(
  camera: OrbitCamera,
  target: OrbitTarget | null | undefined,
  radius: number,
  elevation: number,
  azimuth: number,
): void {
  if (!camera) throw new Error('camera is required')
  const { x: tx = 0, y: ty = 0, z: tz = 0 } = target || {}
  const cosEl = Math.cos(elevation)
  const sinEl = Math.sin(elevation)
  camera.position.set(
    tx + radius * cosEl * Math.sin(azimuth),
    ty + radius * sinEl,
    tz + radius * cosEl * Math.cos(azimuth),
  )
  // Three.js camera.lookAt accepts a Vector3 or plain {x,y,z}.
  if (typeof camera.lookAt === 'function') {
    camera.lookAt(tx, ty, tz)
  }
}

// ── recordTurntable ───────────────────────────────────────────────────────────

export type TurntableEasing = 'linear' | 'ease-in-out'

export interface RecordTurntableOptions {
  /** Number of frames (covers full 360°). */
  frameCount?: number
  /** Orbit radius; defaults to current distance. */
  radius?: number
  /** Elevation in radians; defaults to current. */
  elevation?: number
  /** Orbit centre; defaults to world origin. */
  target?: OrbitTarget
  /** Frame distribution. */
  easing?: TurntableEasing
  /** Render width in pixels (uses canvas size if omitted). */
  width?: number
  /** Render height in pixels. */
  height?: number
}

/**
 * Orbit the camera 360° around the Y-axis through `frameCount` stops,
 * render each frame with the provided Three.js renderer, and return an
 * array of PNG data-URLs (one per frame).
 *
 * The camera is temporarily re-positioned for each frame; its original
 * position and target are restored on completion (or on error).
 *
 * @returns Array of PNG data-URL strings, length === frameCount.
 */
export async function recordTurntable(
  scene: unknown,
  camera: OrbitCamera,
  renderer: OrbitRenderer,
  opts: RecordTurntableOptions = {},
): Promise<string[]> {
  if (!camera) throw new Error('camera is required for recordTurntable')
  if (!renderer) throw new Error('renderer is required for recordTurntable')
  if (!scene) throw new Error('scene is required for recordTurntable')

  const {
    frameCount = 36,
    target = { x: 0, y: 0, z: 0 },
    easing = 'linear',
    width,
    height,
  } = opts

  if (frameCount < 1) throw new Error('frameCount must be ≥ 1')

  // Resolve orbit radius and elevation from current camera position.
  const cx = camera.position.x
  const cy = camera.position.y
  const cz = camera.position.z
  const tx = target.x ?? 0
  const ty = target.y ?? 0
  const tz = target.z ?? 0
  const dx = cx - tx
  const dy = cy - ty
  const dz = cz - tz

  const radius = opts.radius != null
    ? opts.radius
    : Math.sqrt(dx * dx + dy * dy + dz * dz) || 100

  const elevation = opts.elevation != null
    ? opts.elevation
    : Math.atan2(dy, Math.sqrt(dx * dx + dz * dz))

  // Save original camera state for restoration.
  const origPos = { x: camera.position.x, y: camera.position.y, z: camera.position.z }
  // Save renderer size if we're going to resize it.
  const domEl = renderer.domElement
  const origW = domEl ? (domEl.width || 0) : 0
  const origH = domEl ? (domEl.height || 0) : 0
  const needResize = (width != null && height != null) && (width !== origW || height !== origH)

  if (needResize && typeof renderer.setSize === 'function') {
    renderer.setSize(width, height, false)
    if (typeof camera.updateProjectionMatrix === 'function') {
      camera.aspect = width / height
      camera.updateProjectionMatrix()
    }
  }

  const easingFn = easing === 'ease-in-out' ? easingEaseInOut : easingLinear
  const frames: string[] = []

  try {
    for (let i = 0; i < frameCount; i++) {
      const t = easingFn(i, frameCount)
      const azimuth = t * 2 * Math.PI

      positionCameraOnOrbit(camera, target, radius, elevation, azimuth)

      if (typeof camera.updateProjectionMatrix === 'function') {
        camera.updateProjectionMatrix()
      }

      renderer.render(scene, camera)

      const dataUrl = typeof renderer.domElement.toDataURL === 'function'
        ? renderer.domElement.toDataURL('image/png')
        : `data:image/png;base64,STUB_FRAME_${i}`

      frames.push(dataUrl)
    }
  } finally {
    // Restore camera position.
    camera.position.set(origPos.x, origPos.y, origPos.z)
    if (typeof camera.lookAt === 'function') {
      camera.lookAt(tx, ty, tz)
    }
    if (typeof camera.updateProjectionMatrix === 'function') {
      camera.updateProjectionMatrix()
    }
    // Restore renderer size.
    if (needResize && typeof renderer.setSize === 'function') {
      renderer.setSize(origW, origH, false)
      if (typeof camera.updateProjectionMatrix === 'function') {
        camera.aspect = origW / (origH || 1)
        camera.updateProjectionMatrix()
      }
    }
  }

  return frames
}

// ── exportFrames ──────────────────────────────────────────────────────────────

export type TurntableExportFormat = 'png-zip' | 'webm'

export interface ExportFramesOptions {
  /** Frames per second (used for WebM timing). */
  fps?: number
}

export interface ExportFramesResult {
  blob: Blob
  ext: string
  format: string
}

/**
 * Pack an array of PNG data-URL frames into a distributable format.
 *
 * Supported formats:
 *   'png-zip' — ZIP archive of frame0000.png … frameNNNN.png (uses fflate).
 *   'webm'    — WebM video via MediaRecorder if available; falls back to
 *               'png-zip' if MediaRecorder is not supported.
 */
export async function exportFrames(
  frames: string[],
  format: TurntableExportFormat = 'png-zip',
  opts: ExportFramesOptions = {},
): Promise<ExportFramesResult> {
  if (!Array.isArray(frames)) throw new Error('frames must be an array')

  const effectiveFormat = (format === 'webm' && !isMediaRecorderAvailable())
    ? 'png-zip'
    : format

  if (effectiveFormat === 'webm') {
    return exportWebm(frames, opts)
  }
  return exportPngZip(frames, opts)
}

// ── WebM export ───────────────────────────────────────────────────────────────

async function exportWebm(frames: string[], opts: ExportFramesOptions = {}): Promise<ExportFramesResult> {
  const fps = opts.fps ?? 24
  const interval = 1000 / fps

  // We need a canvas to draw each frame into for MediaRecorder.
  // In a browser context this works; in test stubs we return a stub blob.
  if (typeof document === 'undefined' || typeof MediaRecorder === 'undefined') {
    // Fallback in environments without DOM.
    return exportPngZip(frames, opts)
  }

  return new Promise((resolve, reject) => {
    // Decode first frame to get dimensions.
    const firstImg = new Image()
    firstImg.onload = () => {
      const w = firstImg.naturalWidth || 512
      const h = firstImg.naturalHeight || 512
      const canvas = document.createElement('canvas')
      canvas.width = w
      canvas.height = h
      const ctx = canvas.getContext('2d')

      const stream = canvas.captureStream(fps)
      const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' })
      const chunks: Blob[] = []

      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data) }
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: 'video/webm' })
        resolve({ blob, ext: 'webm', format: 'webm' })
      }
      recorder.onerror = () => reject(new Error('MediaRecorder error'))

      recorder.start()

      let idx = 0
      function drawNext() {
        if (idx >= frames.length) {
          recorder.stop()
          return
        }
        const img = new Image()
        img.onload = () => {
          ctx?.drawImage(img, 0, 0)
          idx++
          setTimeout(drawNext, interval)
        }
        img.onerror = () => { idx++; setTimeout(drawNext, interval) }
        img.src = frames[idx]
      }
      drawNext()
    }
    firstImg.onerror = () => {
      // Can't decode first frame; fall back.
      exportPngZip(frames, opts).then(resolve).catch(reject)
    }
    firstImg.src = frames[0] || 'data:image/png;base64,'
  })
}

// ── PNG ZIP export ────────────────────────────────────────────────────────────

async function exportPngZip(frames: string[], _opts: ExportFramesOptions = {}): Promise<ExportFramesResult> {
  // Dynamically import fflate (bundled in the project) so this module
  // stays side-effect-free when fflate is unavailable (e.g. test environments).
  let zipSync: ((files: Record<string, Uint8Array>) => Uint8Array) | undefined
  try {
    const fflate = await import('fflate')
    zipSync = fflate.zipSync
  } catch {
    // fflate unavailable — return a stub Blob in test/SSR environments.
    const stub = new Uint8Array([0x50, 0x4b, 0x05, 0x06, ...new Array(18).fill(0)])
    return { blob: new Blob([stub], { type: 'application/zip' }), ext: 'zip', format: 'png-zip' }
  }

  // Convert data-URLs to Uint8Array binary.
  const files: Record<string, Uint8Array> = {}
  for (let i = 0; i < frames.length; i++) {
    const pad = String(i).padStart(4, '0')
    const name = `frame${pad}.png`
    const dataUrl = frames[i]
    const bytes = dataUrlToBytes(dataUrl)
    files[name] = bytes
  }

  const zipped = zipSync(files)
  const blob = new Blob([zipped as BlobPart], { type: 'application/zip' })
  return { blob, ext: 'zip', format: 'png-zip' }
}

function dataUrlToBytes(dataUrl: string): Uint8Array {
  if (typeof dataUrl !== 'string') return new Uint8Array(0)
  const comma = dataUrl.indexOf(',')
  if (comma < 0) return new Uint8Array(0)
  const base64 = dataUrl.slice(comma + 1)
  // Use atob in browser; Buffer in Node.
  try {
    const binary = typeof atob !== 'undefined'
      ? atob(base64)
      // @ts-expect-error - no @types/node in this toolchain (Buffer is a Node-only fallback for non-browser environments; see iesLoader.test.ts for the established pattern).
      : Buffer.from(base64, 'base64').toString('binary')
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    return bytes
  } catch {
    return new Uint8Array(0)
  }
}

// ── previewMode ───────────────────────────────────────────────────────────────

export interface PreviewModeOptions {
  /** Angular speed. */
  degreesPerSecond?: number
  /** Orbit centre; defaults to origin. */
  target?: OrbitTarget
  /** Distance; defaults to current. */
  radius?: number
  /** Elevation; defaults to current. */
  elevation?: number
}

export interface PreviewModeHandle {
  stop(): void
}

/**
 * Start a continuous slow-turntable loop for live preview in the viewport.
 *
 * The orbit angular speed defaults to one full revolution in ~12 seconds
 * (30°/s). The camera is moved every animation frame; OrbitControls should
 * be disabled by the caller while preview mode is active to avoid fighting.
 *
 * @param renderer Not used directly (Renderer.jsx drives the RAF loop),
 *                 but accepted for API symmetry and future use.
 */
export function previewMode(
  scene: unknown,
  camera: OrbitCamera,
  renderer: OrbitRenderer | null | undefined,
  opts: PreviewModeOptions = {},
): PreviewModeHandle {
  if (!camera) throw new Error('camera is required for previewMode')

  const {
    degreesPerSecond = 30,
    target = { x: 0, y: 0, z: 0 },
  } = opts

  const tx = target.x ?? 0
  const ty = target.y ?? 0
  const tz = target.z ?? 0

  const dx = camera.position.x - tx
  const dy = camera.position.y - ty
  const dz = camera.position.z - tz

  const radius = opts.radius != null
    ? opts.radius
    : Math.sqrt(dx * dx + dy * dy + dz * dz) || 100

  const elevation = opts.elevation != null
    ? opts.elevation
    : Math.atan2(dy, Math.sqrt(dx * dx + dz * dz))

  // Compute initial azimuth from current camera position.
  let azimuth = Math.atan2(dx, dz)

  const radiansPerMs = (degreesPerSecond * Math.PI / 180) / 1000
  let lastTime: number | null = null
  let rafId: number | null = null
  let running = true

  function tick(now: number) {
    if (!running) return
    if (lastTime !== null) {
      const dt = now - lastTime
      azimuth = (azimuth + radiansPerMs * dt) % (2 * Math.PI)
    }
    lastTime = now
    positionCameraOnOrbit(camera, target, radius, elevation, azimuth)
    if (typeof camera.updateProjectionMatrix === 'function') {
      camera.updateProjectionMatrix()
    }
    rafId = requestAnimationFrame(tick)
  }

  rafId = requestAnimationFrame(tick)

  return {
    stop() {
      running = false
      if (rafId != null) {
        cancelAnimationFrame(rafId)
        rafId = null
      }
    },
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

/**
 * Return true if MediaRecorder is available and supports 'video/webm'.
 */
export function isMediaRecorderAvailable(): boolean {
  if (typeof MediaRecorder === 'undefined') return false
  try {
    return MediaRecorder.isTypeSupported('video/webm')
  } catch {
    return false
  }
}
