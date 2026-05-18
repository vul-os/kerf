/**
 * studioLighting.js — Studio-lighting preset library.
 *
 * Each preset builder returns a `doc.lights[]`-shaped array using the
 * same light object schema as `presetThreePointLighting` in render.js.
 *
 * All coordinates are in millimetres. No DOM/browser dependencies.
 */

import { presetThreePointLighting } from './render.js'

// ── Preset registry ────────────────────────────────────────────────────────────

export const STUDIO_PRESETS = [
  'three-point',
  'four-point',
  'butterfly',
  'rembrandt',
  'ring-light',
  'softbox',
]

// ── three-point ────────────────────────────────────────────────────────────────

/**
 * Classic 3-point rig: key + fill + back.
 * Re-uses presetThreePointLighting from render.js so the output is
 * byte-identical to the existing function.
 *
 * @param {number[]} target - Scene centre [x, y, z] in mm.
 * @returns {object[]}
 */
export function buildThreePointPreset(target) {
  return presetThreePointLighting(target)
}

// ── four-point ─────────────────────────────────────────────────────────────────

/**
 * 4-point rig: 3-point base + kicker (low rear-side rim to accentuate
 * silhouette separation from the background).
 *
 * @param {number[]} target - Scene centre [x, y, z] in mm.
 * @returns {object[]}
 */
export function buildFourPointPreset(target) {
  const [tx, ty, tz] = target
  return [
    ...presetThreePointLighting(target),
    {
      id: 'kicker',
      kind: 'sun',
      direction: [0.8, -0.5, 0.3],
      intensity: 1.5,
      color: '#ffe8d0',
    },
  ]
}

// ── butterfly ──────────────────────────────────────────────────────────────────

/**
 * Butterfly / beauty rig: overhead key casts a small shadow under the nose;
 * low frontal fill lifts the shadow contrast.
 *
 * @param {number[]} target - Scene centre [x, y, z] in mm.
 * @returns {object[]}
 */
export function buildButterflyPreset(target) {
  const [tx, ty, tz] = target
  return [
    {
      id: 'butterfly-key',
      kind: 'sun',
      direction: [0, -0.4, -1],
      intensity: 6,
      color: '#ffffff',
    },
    {
      id: 'butterfly-fill',
      kind: 'area',
      position: [tx, ty - 2000, tz - 500],
      size_mm: 800,
      intensity: 1.5,
      color: '#e8f0ff',
    },
  ]
}

// ── rembrandt ──────────────────────────────────────────────────────────────────

/**
 * Rembrandt rig: 45° key from one side creates the characteristic triangle of
 * light under the eye; low opposing fill keeps shadow detail visible.
 *
 * @param {number[]} target - Scene centre [x, y, z] in mm.
 * @returns {object[]}
 */
export function buildRembrandtPreset(target) {
  const [tx, ty, tz] = target
  return [
    {
      id: 'rembrandt-key',
      kind: 'sun',
      // 45° horizontal + 45° elevation from subject's left
      direction: [-1, -1, -1],
      intensity: 5,
      color: '#fff5e0',
    },
    {
      id: 'rembrandt-fill',
      kind: 'area',
      // Low, opposite side
      position: [tx + 2500, ty - 1000, tz - 200],
      size_mm: 600,
      intensity: 0.8,
      color: '#d0e0ff',
    },
  ]
}

// ── ring-light ─────────────────────────────────────────────────────────────────

/**
 * Ring-light rig: 8 small sun lights evenly distributed around the camera
 * axis at constant elevation, mimicking a circular ring flash.
 *
 * @param {number[]} target - Scene centre [x, y, z] in mm.
 * @returns {object[]}
 */
export function buildRingLightPreset(target) {
  const COUNT = 8
  const RADIUS_MM = 1500   // ring radius in scene space (used for direction)
  const ELEVATION_DEG = 10 // degrees above the horizon
  const el = (ELEVATION_DEG * Math.PI) / 180

  return Array.from({ length: COUNT }, (_, i) => {
    const angle = (2 * Math.PI * i) / COUNT
    // Direction vector points FROM the ring position TOWARD the target
    const dx = -Math.cos(el) * Math.cos(angle)
    const dy = -Math.cos(el) * Math.sin(angle)
    const dz = -Math.sin(el)
    return {
      id: `ring-${i}`,
      kind: 'sun',
      direction: [dx, dy, dz],
      intensity: 1.5,
      color: '#ffffff',
    }
  })
}

// ── softbox ────────────────────────────────────────────────────────────────────

/**
 * Softbox rig: single large area light overhead-front at ~45° — the
 * workhorse of product photography.
 *
 * @param {number[]} target - Scene centre [x, y, z] in mm.
 * @returns {object[]}
 */
export function buildSoftboxPreset(target) {
  const [tx, ty, tz] = target
  return [
    {
      id: 'softbox',
      kind: 'area',
      // 45° overhead-front position
      position: [tx, ty - 2500, tz + 2500],
      size_mm: 1500,
      intensity: 8,
      color: '#fff8f0',
    },
  ]
}

// ── applyStudioPreset ─────────────────────────────────────────────────────────

const BUILDERS = {
  'three-point': buildThreePointPreset,
  'four-point': buildFourPointPreset,
  'butterfly': buildButterflyPreset,
  'rembrandt': buildRembrandtPreset,
  'ring-light': buildRingLightPreset,
  'softbox': buildSoftboxPreset,
}

/**
 * Return a new render doc with `lights` cleared and repopulated by the
 * named preset.
 *
 * @param {object} doc - Render document (not mutated).
 * @param {string} presetName - One of STUDIO_PRESETS.
 * @param {number[]} [target=[0,0,500]] - Scene centre in mm.
 * @returns {object} New render document.
 */
export function applyStudioPreset(doc, presetName, target = [0, 0, 500]) {
  const builder = BUILDERS[presetName]
  if (!builder) {
    throw new Error(`Unknown studio preset: "${presetName}". Valid: ${STUDIO_PRESETS.join(', ')}`)
  }
  return {
    ...doc,
    lights: builder(target),
  }
}
