/**
 * studioLighting.ts — Studio-lighting preset library.
 *
 * Each preset builder returns a `doc.lights[]`-shaped array using the
 * same light object schema as `presetThreePointLighting` in render.js.
 *
 * All coordinates are in millimetres. No DOM/browser dependencies.
 */

import { presetThreePointLighting } from './render.js'
import type { Vec3 } from '@/types'

// ── Light shapes ─────────────────────────────────────────────────────────────
//
// render.js/render.ts export no types (JSDoc-only, loosely `object[]`), so the
// light shapes used here are modeled locally from how presetThreePointLighting
// and the preset builders below actually construct them.

export interface SunLight {
  id: string
  kind: 'sun'
  direction: Vec3
  intensity: number
  color: string
}

export interface AreaLight {
  id: string
  kind: 'area'
  position: Vec3
  size_mm: number
  intensity: number
  color: string
}

export type StudioLight = SunLight | AreaLight

/** Minimal render-document shape `applyStudioPreset` needs — it only reads/writes `lights`. */
export interface StudioLightingDoc {
  lights: StudioLight[]
  [key: string]: unknown
}

export type StudioPresetName =
  | 'three-point'
  | 'four-point'
  | 'butterfly'
  | 'rembrandt'
  | 'ring-light'
  | 'softbox'

// ── Preset registry ────────────────────────────────────────────────────────────

export const STUDIO_PRESETS: StudioPresetName[] = [
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
 * @param target - Scene centre [x, y, z] in mm.
 */
export function buildThreePointPreset(target: Vec3): StudioLight[] {
  // render.ts (T-502) carries no return-type annotation, so its object-literal `kind` /
  // `direction` / `position` fields infer as widened `string` / `number[]`. The runtime
  // shape is exactly StudioLight; this cast documents that boundary.
  return presetThreePointLighting(target) as StudioLight[]
}

// ── four-point ─────────────────────────────────────────────────────────────────

/**
 * 4-point rig: 3-point base + kicker (low rear-side rim to accentuate
 * silhouette separation from the background).
 *
 * @param target - Scene centre [x, y, z] in mm.
 */
export function buildFourPointPreset(target: Vec3): StudioLight[] {
  const kicker: SunLight = {
    id: 'kicker',
    kind: 'sun',
    direction: [0.8, -0.5, 0.3],
    intensity: 1.5,
    color: '#ffe8d0',
  }
  return [...(presetThreePointLighting(target) as StudioLight[]), kicker]
}

// ── butterfly ──────────────────────────────────────────────────────────────────

/**
 * Butterfly / beauty rig: overhead key casts a small shadow under the nose;
 * low frontal fill lifts the shadow contrast.
 *
 * @param target - Scene centre [x, y, z] in mm.
 */
export function buildButterflyPreset(target: Vec3): StudioLight[] {
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
 * @param target - Scene centre [x, y, z] in mm.
 */
export function buildRembrandtPreset(target: Vec3): StudioLight[] {
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
 * @param _target - Scene centre [x, y, z] in mm. Unused: every ring light is a directional
 *   (`sun`) light, and a direction vector is translation- and radius-invariant, so neither the
 *   rig's target centre nor its nominal radius affects the output. Pre-existing in the source
 *   .js (both `target` and the `RADIUS_MM` local below were already dead); kept and merely
 *   underscore-prefixed here to satisfy the TS lint rule without changing behaviour.
 */
export function buildRingLightPreset(_target: Vec3): SunLight[] {
  const COUNT = 8
  const _RADIUS_MM = 1500  // ring radius in scene space — see note above; not used
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
      kind: 'sun' as const,
      direction: [dx, dy, dz] as Vec3,
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
 * @param target - Scene centre [x, y, z] in mm.
 */
export function buildSoftboxPreset(target: Vec3): AreaLight[] {
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

const BUILDERS: Record<StudioPresetName, (target: Vec3) => StudioLight[]> = {
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
 * @param doc - Render document (not mutated).
 * @param presetName - One of STUDIO_PRESETS.
 * @param target - Scene centre in mm.
 */
export function applyStudioPreset<T extends StudioLightingDoc>(
  doc: T,
  presetName: StudioPresetName,
  target: Vec3 = [0, 0, 500],
): T {
  const builder = BUILDERS[presetName]
  if (!builder) {
    throw new Error(`Unknown studio preset: "${presetName}". Valid: ${STUDIO_PRESETS.join(', ')}`)
  }
  return {
    ...doc,
    lights: builder(target),
  }
}
