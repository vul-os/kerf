// renderView.test.jsx — Vitest assertions for RenderView data-layer helpers.
//
// Pure data-layer tests (no React DOM rendering). The interesting logic lives
// in render.js, which RenderView wraps. Tests cover: defaultRender shape,
// addLight, removeLight, validateRender, setCameraFromOrbit.

import { describe, it, expect } from 'vitest'
import {
  defaultRender,
  addLight,
  removeLight,
  validateRender,
  setCameraFromOrbit,
  presetThreePointLighting,
} from '../../lib/render.js'

// ── 1. defaultRender ───────────────────────────────────────────────────────────

describe('defaultRender', () => {
  it('returns version 1', () => {
    const r = defaultRender('abc-123')
    expect(r.version).toBe(1)
  })

  it('includes the supplied scene_file_id', () => {
    const r = defaultRender('file-id-xyz')
    expect(r.scene_file_id).toBe('file-id-xyz')
  })

  it('has a camera with position and target arrays of length 3', () => {
    const r = defaultRender('x')
    expect(Array.isArray(r.camera.position)).toBe(true)
    expect(r.camera.position).toHaveLength(3)
    expect(Array.isArray(r.camera.target)).toBe(true)
    expect(r.camera.target).toHaveLength(3)
  })

  it('has render_settings with positive samples', () => {
    const r = defaultRender('x')
    expect(typeof r.render_settings.samples).toBe('number')
    expect(r.render_settings.samples).toBeGreaterThan(0)
  })

  it('accepts a custom name', () => {
    const r = defaultRender('x', 'Hero shot')
    expect(r.name).toBe('Hero shot')
  })

  it('ships with 3 lights from presetThreePointLighting', () => {
    const r = defaultRender('x')
    expect(r.lights).toHaveLength(3)
  })

  it('materials_override wildcard entry exists with a base_color', () => {
    const r = defaultRender('x')
    expect(r.materials_override['*']).toBeDefined()
    expect(typeof r.materials_override['*'].base_color).toBe('string')
  })
})

// ── 2. addLight ────────────────────────────────────────────────────────────────

describe('addLight', () => {
  it('appends a light and increases count by 1', () => {
    const r = defaultRender('x')
    const next = addLight(r, { id: 'extra', kind: 'point', position: [0, 0, 0], intensity: 1, color: '#fff' })
    expect(next.lights).toHaveLength(r.lights.length + 1)
  })

  it('does not mutate the original render doc', () => {
    const r = defaultRender('x')
    const originalLen = r.lights.length
    addLight(r, { id: 'tmp', kind: 'sun', direction: [0, 0, -1], intensity: 1, color: '#fff' })
    expect(r.lights).toHaveLength(originalLen)
  })

  it('appended light is accessible by id', () => {
    const r = defaultRender('x')
    const next = addLight(r, { id: 'new-light', kind: 'area', intensity: 2, color: '#eee' })
    expect(next.lights.find((l) => l.id === 'new-light')).toBeDefined()
  })
})

// ── 3. removeLight ─────────────────────────────────────────────────────────────

describe('removeLight', () => {
  it('removes the targeted light', () => {
    const r = defaultRender('x')
    const idToRemove = r.lights[0].id
    const next = removeLight(r, idToRemove)
    expect(next.lights.find((l) => l.id === idToRemove)).toBeUndefined()
  })

  it('leaves other lights intact', () => {
    const r = defaultRender('x')
    const idToRemove = r.lights[0].id
    const next = removeLight(r, idToRemove)
    expect(next.lights).toHaveLength(r.lights.length - 1)
  })

  it('does not mutate the original', () => {
    const r = defaultRender('x')
    const originalLen = r.lights.length
    removeLight(r, r.lights[0].id)
    expect(r.lights).toHaveLength(originalLen)
  })
})

// ── 4. validateRender ─────────────────────────────────────────────────────────

describe('validateRender', () => {
  it('validates a freshly created defaultRender as ok', () => {
    const { ok, errors } = validateRender(defaultRender('sid'))
    expect(ok).toBe(true)
    expect(errors).toHaveLength(0)
  })

  it('fails when camera.fov_deg is out of range', () => {
    const r = defaultRender('sid')
    r.camera.fov_deg = 0
    const { ok, errors } = validateRender(r)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('fov_deg'))).toBe(true)
  })

  it('fails when camera is missing entirely', () => {
    const r = defaultRender('sid')
    delete r.camera
    const { ok, errors } = validateRender(r)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('camera'))).toBe(true)
  })

  it('fails with unsupported version', () => {
    const r = defaultRender('sid')
    r.version = 99
    const { ok, errors } = validateRender(r)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('version'))).toBe(true)
  })

  it('fails when scene_file_id is absent', () => {
    const r = defaultRender('sid')
    delete r.scene_file_id
    const { ok, errors } = validateRender(r)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('scene_file_id'))).toBe(true)
  })
})

// ── 5. setCameraFromOrbit ─────────────────────────────────────────────────────

describe('setCameraFromOrbit', () => {
  it('produces a position different from the original', () => {
    const r = defaultRender('x')
    const next = setCameraFromOrbit(r, [0, 0, 500], 5000, 45, 30)
    const orig = r.camera.position
    expect(next.camera.position).not.toEqual(orig)
  })

  it('sets camera.target to the supplied target', () => {
    const r = defaultRender('x')
    const target = [100, 200, 300]
    const next = setCameraFromOrbit(r, target, 3000, 0, 0)
    expect(next.camera.target).toEqual(target)
  })

  it('position is the correct distance from target', () => {
    const r = defaultRender('x')
    const target = [0, 0, 0]
    const dist = 1000
    const next = setCameraFromOrbit(r, target, dist, 0, 0)
    const [px, py, pz] = next.camera.position
    const actual = Math.sqrt(px * px + py * py + pz * pz)
    expect(actual).toBeCloseTo(dist, 1)
  })

  it('does not mutate the original render doc', () => {
    const r = defaultRender('x')
    const origPos = [...r.camera.position]
    setCameraFromOrbit(r, [0, 0, 0], 2000, 90, 0)
    expect(r.camera.position).toEqual(origPos)
  })
})

// ── 6. presetThreePointLighting ───────────────────────────────────────────────

describe('presetThreePointLighting', () => {
  it('returns an array of exactly 3 lights', () => {
    const lights = presetThreePointLighting([0, 0, 0])
    expect(lights).toHaveLength(3)
  })

  it('all lights have a kind property', () => {
    const lights = presetThreePointLighting([0, 0, 0])
    lights.forEach((l) => expect(typeof l.kind).toBe('string'))
  })
})
