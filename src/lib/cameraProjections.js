/**
 * cameraProjections.js — camera-projection utilities for the Kerf viewport.
 *
 * Provides:
 *   - CAMERA_PROJECTIONS  – ordered list of supported projection kinds
 *   - SENSOR_SIZES        – common imaging-sensor widths in mm
 *   - focalToFov / fovToFocal – pure-math focal↔fov conversions
 *   - createCamera        – factory: returns a THREE.Camera (or {camera, postProcessor} for
 *                           fisheye / panoramic-360)
 *   - swapCameraProjection – switch projection while preserving orbit target + distance
 */

import * as THREE from 'three'

// ── Public constants ──────────────────────────────────────────────────────────

/** Ordered list of every projection kind this module understands. */
export const CAMERA_PROJECTIONS = [
  'perspective',
  'orthographic',
  'two-point',
  'fisheye',
  'panoramic-360',
]

/**
 * Common sensor widths (horizontal, in mm).
 * Used together with a focal length to derive a field-of-view angle.
 */
export const SENSOR_SIZES = {
  'full-frame': 36,
  'aps-c':      23.6,
  'cinema-35':  24.89,
  'micro-4-3':  17.3,
}

// ── FOV / focal conversions ───────────────────────────────────────────────────

/**
 * Convert a focal length to a horizontal field-of-view angle.
 *
 * @param {number} focal_mm   Focal length in millimetres (e.g. 50).
 * @param {number} sensor_mm  Sensor horizontal width in millimetres (e.g. 36).
 * @returns {number}          FOV in radians.
 */
export function focalToFov(focal_mm, sensor_mm) {
  return 2 * Math.atan(sensor_mm / (2 * focal_mm))
}

/**
 * Convert a horizontal FOV angle back to a focal length.
 * This is the exact inverse of focalToFov.
 *
 * @param {number} fov_rad    Field of view in radians.
 * @param {number} sensor_mm  Sensor horizontal width in millimetres.
 * @returns {number}          Focal length in millimetres.
 */
export function fovToFocal(fov_rad, sensor_mm) {
  return sensor_mm / (2 * Math.tan(fov_rad / 2))
}

// ── Internal helpers ──────────────────────────────────────────────────────────

/**
 * Resolve sensor_mm from a string key or a raw number.
 * Falls back to full-frame (36 mm) for unknown keys.
 */
function resolveSensorMm(sensor) {
  if (typeof sensor === 'number') return sensor
  return SENSOR_SIZES[sensor] ?? SENSOR_SIZES['full-frame']
}

/**
 * Build the shader-projection post-processor descriptor for fisheye and
 * panoramic-360 modes.
 *
 * In a real integration this would be wired to a THREE.WebGLRenderTarget +
 * a full-screen shader pass (cube-map capture → equirectangular for
 * panoramic-360; cube-map → stereographic fisheye for fisheye). The object
 * returned here is a plain descriptor so the post-processing pass can be
 * constructed by the caller without this module depending on EffectComposer
 * or a specific render pipeline.
 *
 * @param {'fisheye'|'panoramic-360'} kind
 * @returns {{ type: string, uniforms: object }}
 */
function buildPostProcessor(kind) {
  if (kind === 'panoramic-360') {
    return {
      type: 'equirectangular',
      uniforms: {
        // Horizontal FOV for the equirectangular unwrap (full 360°).
        hFov: { value: 2 * Math.PI },
        // Vertical FOV for the equirectangular unwrap (full 180°).
        vFov: { value: Math.PI },
      },
    }
  }
  // fisheye — stereographic projection
  return {
    type: 'fisheye-stereographic',
    uniforms: {
      // Capture FOV for the cube-map faces (180° = hemisphere).
      captureFov: { value: Math.PI },
    },
  }
}

// ── createCamera ──────────────────────────────────────────────────────────────

/**
 * Create a THREE.Camera (or a {camera, postProcessor} pair) for the
 * requested projection kind.
 *
 * @param {'perspective'|'orthographic'|'two-point'|'fisheye'|'panoramic-360'} kind
 * @param {{ aspect?: number, focal_mm?: number, sensor?: string|number }} options
 *   aspect    – viewport width/height ratio (default 16/9)
 *   focal_mm  – focal length in mm for FOV derivation (default 50)
 *   sensor    – sensor size key or raw mm value (default 'full-frame')
 * @returns {THREE.Camera | { camera: THREE.Camera, postProcessor: object }}
 */
export function createCamera(kind, { aspect = 16 / 9, focal_mm = 50, sensor = 'full-frame' } = {}) {
  const sensor_mm  = resolveSensorMm(sensor)
  const hFov_rad   = focalToFov(focal_mm, sensor_mm)
  // THREE.PerspectiveCamera takes a *vertical* FOV in degrees.
  const vFov_deg   = (hFov_rad / aspect) * (180 / Math.PI)

  switch (kind) {
    case 'perspective': {
      const cam = new THREE.PerspectiveCamera(vFov_deg, aspect, 0.1, 5000)
      return cam
    }

    case 'two-point': {
      // Two-point perspective: standard PerspectiveCamera with a manually
      // zeroed film offset so verticals stay strictly parallel while
      // horizontals converge. The caller is expected to position the camera
      // at the horizon height and not tilt it vertically.
      const cam = new THREE.PerspectiveCamera(vFov_deg, aspect, 0.1, 5000)
      cam.filmOffset = 0
      cam.userData.twoPoint = true
      return cam
    }

    case 'orthographic': {
      // Scale the orthographic frustum so one unit in world space maps to
      // approximately the same screen area as the perspective view would at
      // the default orbit distance (~100 units).
      const halfH = 50 / aspect // half-height at reference distance
      const halfW = halfH * aspect
      const cam = new THREE.OrthographicCamera(-halfW, halfW, halfH, -halfH, 0.1, 5000)
      cam.zoom = 1
      return cam
    }

    case 'fisheye': {
      // Fisheye is implemented as a cube-map capture camera + a stereographic
      // shader pass. The inner camera sees a full hemisphere (180° FOV).
      const cam = new THREE.PerspectiveCamera(180, aspect, 0.1, 5000)
      cam.userData.kind = 'fisheye'
      return { camera: cam, postProcessor: buildPostProcessor('fisheye') }
    }

    case 'panoramic-360': {
      // Panoramic 360 uses a cube-map capture camera + an equirectangular
      // unwrap pass. The capture camera sees the full sphere.
      const cam = new THREE.PerspectiveCamera(90, 1, 0.1, 5000)
      cam.userData.kind = 'panoramic-360'
      return { camera: cam, postProcessor: buildPostProcessor('panoramic-360') }
    }

    default:
      throw new Error(`createCamera: unknown projection kind "${kind}"`)
  }
}

// ── swapCameraProjection ──────────────────────────────────────────────────────

/**
 * Switch the active camera to a new projection kind, preserving the
 * orbit-target world position and the camera-to-target distance.
 *
 * @param {THREE.Camera} oldCam
 *   The camera currently in use.
 * @param {'perspective'|'orthographic'|'two-point'|'fisheye'|'panoramic-360'} kind
 *   The desired projection.
 * @param {{
 *   aspect?: number,
 *   focal_mm?: number,
 *   sensor?: string|number,
 *   target?: THREE.Vector3,
 *   distance?: number,
 * }} options
 *   target   – the orbit pivot point in world space (default origin).
 *   distance – camera-to-target distance to maintain (default 100).
 *   All other options are forwarded to createCamera.
 * @returns {THREE.Camera | { camera: THREE.Camera, postProcessor: object }}
 */
export function swapCameraProjection(oldCam, kind, options = {}) {
  const {
    target   = new THREE.Vector3(0, 0, 0),
    distance = 100,
    aspect   = 16 / 9,
    focal_mm = 50,
    sensor   = 'full-frame',
  } = options

  // Derive the orbit-target from the old camera when OrbitControls has
  // written its target into userData (convenience hook for callers).
  const orbitTarget = oldCam.userData?.orbitTarget
    ? oldCam.userData.orbitTarget.clone()
    : (target instanceof THREE.Vector3 ? target.clone() : new THREE.Vector3(...target))

  // Compute the view direction from old camera to target so we keep the
  // same look direction after the swap.
  const oldPos = oldCam.position.clone()
  const dir = orbitTarget.clone().sub(oldPos)
  const len = dir.length()
  const unitDir = len > 0 ? dir.divideScalar(len) : new THREE.Vector3(0, 0, -1)

  const result = createCamera(kind, { aspect, focal_mm, sensor })

  // Extract the actual camera object whether we got a plain camera or a tuple.
  const newCam = result?.camera ?? result

  // Place the new camera at the same distance from the target, looking toward it.
  newCam.position.copy(orbitTarget).addScaledVector(unitDir, -distance)

  // Store the orbit target so downstream code can recover it easily.
  newCam.userData.orbitTarget = orbitTarget.clone()

  // Copy the world-up orientation.
  newCam.up.copy(oldCam.up)
  newCam.lookAt(orbitTarget)
  newCam.updateProjectionMatrix()

  return result
}
