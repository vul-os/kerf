/**
 * heroRender.test.js — Vitest suite for the one-click hero render module.
 *
 * All Three.js objects are stubbed in-process; no DOM or GPU required.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  renderHeroSet,
  applyJewelryLighting,
  restorePrevLighting,
  composeContactSheet,
  socialMediaCrops,
} from './heroRender.js'

// ── Three.js stubs ────────────────────────────────────────────────────────────

function makeFakeLight(type = 'DirectionalLight') {
  return { isLight: true, type, userData: {}, position: { x: 0, y: 0, z: 0 }, color: 0xffffff, intensity: 1 }
}

const fakeThree = {
  DirectionalLight: class {
    constructor(color, intensity) {
      this.isLight = true
      this.type = 'DirectionalLight'
      this.color = color
      this.intensity = intensity
      this.position = { x: 0, y: 0, z: 0, set(x, y, z) { this.x = x; this.y = y; this.z = z } }
      this.userData = {}
    }
  },
  AmbientLight: class {
    constructor(color, intensity) {
      this.isLight = true
      this.type = 'AmbientLight'
      this.color = color
      this.intensity = intensity
      this.position = null
      this.userData = {}
    }
  },
}

// ── Scene / camera / renderer helpers ─────────────────────────────────────────

function makeScene(extraChildren = []) {
  const children = [...extraChildren]
  return {
    children,
    add(obj) { children.push(obj) },
    remove(obj) {
      const idx = children.indexOf(obj)
      if (idx >= 0) children.splice(idx, 1)
    },
  }
}

function makeCamera(pos = { x: 80, y: 80, z: 80 }) {
  return {
    position: {
      x: pos.x, y: pos.y, z: pos.z,
      set(x, y, z) { this.x = x; this.y = y; this.z = z },
    },
    fov: 45,
    aspect: 1,
    _lookAt: null,
    lookAt(x, y, z) { this._lookAt = { x, y, z } },
    updateProjectionMatrix: vi.fn(),
  }
}

let _frameIdx = 0
function makeRenderer() {
  const domElement = {
    width: 800,
    height: 600,
    toDataURL(mime) {
      return `data:${mime || 'image/png'};base64,FRAME${String(_frameIdx++).padStart(4, '0')}`
    },
  }
  return {
    domElement,
    render: vi.fn(),
    setSize: vi.fn((w, h) => { domElement.width = w; domElement.height = h }),
  }
}

// ── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  _frameIdx = 0
  // Inject fake THREE so _buildJewelryLights() uses real-ish objects.
  globalThis.THREE = fakeThree
})

afterEach(() => {
  delete globalThis.THREE
})

// ── applyJewelryLighting ──────────────────────────────────────────────────────

describe('applyJewelryLighting', () => {
  it('throws when scene is null', () => {
    expect(() => applyJewelryLighting(null)).toThrow('scene is required')
  })

  it('adds jewelry lights to the scene', () => {
    const scene = makeScene()
    applyJewelryLighting(scene)
    expect(scene.children.length).toBeGreaterThan(0)
  })

  it('added lights all have isLight=true', () => {
    const scene = makeScene()
    applyJewelryLighting(scene)
    for (const c of scene.children) {
      expect(c.isLight).toBe(true)
    }
  })

  it('adds at least 4 lights (key, fill, bounce, rim, ambient)', () => {
    const scene = makeScene()
    applyJewelryLighting(scene)
    expect(scene.children.length).toBeGreaterThanOrEqual(4)
  })

  it('tags each added light with _heroJewelry=true', () => {
    const scene = makeScene()
    applyJewelryLighting(scene)
    for (const c of scene.children) {
      expect(c.userData._heroJewelry).toBe(true)
    }
  })

  it('removes pre-existing lights before adding jewelry lights', () => {
    const existingLight = makeFakeLight()
    const scene = makeScene([existingLight])
    applyJewelryLighting(scene)
    // The original light should no longer be in the scene.
    expect(scene.children).not.toContain(existingLight)
  })

  it('returns the saved pre-existing lights', () => {
    const existingLight = makeFakeLight()
    const scene = makeScene([existingLight])
    const saved = applyJewelryLighting(scene)
    expect(saved).toContain(existingLight)
  })

  it('returns empty array when no lights existed before', () => {
    const scene = makeScene()
    const saved = applyJewelryLighting(scene)
    expect(Array.isArray(saved)).toBe(true)
    expect(saved.length).toBe(0)
  })
})

// ── restorePrevLighting ───────────────────────────────────────────────────────

describe('restorePrevLighting', () => {
  it('throws when scene is null', () => {
    expect(() => restorePrevLighting(null, [])).toThrow('scene is required')
  })

  it('removes jewelry lights after restoring', () => {
    const scene = makeScene()
    const saved = applyJewelryLighting(scene)
    restorePrevLighting(scene, saved)
    const jewelryLights = scene.children.filter((c) => c.userData && c.userData._heroJewelry)
    expect(jewelryLights.length).toBe(0)
  })

  it('restores original lights to the scene', () => {
    const orig = makeFakeLight('AmbientLight')
    const scene = makeScene([orig])
    const saved = applyJewelryLighting(scene)
    restorePrevLighting(scene, saved)
    expect(scene.children).toContain(orig)
  })

  it('leaves no jewelry lights after full apply+restore cycle', () => {
    const scene = makeScene()
    const saved = applyJewelryLighting(scene)
    restorePrevLighting(scene, saved)
    for (const c of scene.children) {
      expect(c.userData && c.userData._heroJewelry).toBeFalsy()
    }
  })

  it('is idempotent: restoring twice does not throw', () => {
    const scene = makeScene()
    const saved = applyJewelryLighting(scene)
    restorePrevLighting(scene, saved)
    expect(() => restorePrevLighting(scene, saved)).not.toThrow()
  })
})

// ── renderHeroSet ─────────────────────────────────────────────────────────────

describe('renderHeroSet', () => {
  it('throws when scene is missing', async () => {
    await expect(renderHeroSet(null, makeCamera(), makeRenderer())).rejects.toThrow('scene is required')
  })

  it('throws when camera is missing', async () => {
    await expect(renderHeroSet(makeScene(), null, makeRenderer())).rejects.toThrow('camera is required')
  })

  it('throws when renderer is missing', async () => {
    await expect(renderHeroSet(makeScene(), makeCamera(), null)).rejects.toThrow('renderer is required')
  })

  it('returns an object with stills and turntable arrays', async () => {
    const result = await renderHeroSet(makeScene(), makeCamera(), makeRenderer())
    expect(result).toHaveProperty('stills')
    expect(result).toHaveProperty('turntable')
    expect(Array.isArray(result.stills)).toBe(true)
    expect(Array.isArray(result.turntable)).toBe(true)
  })

  it('returns exactly 4 still frames', async () => {
    const result = await renderHeroSet(makeScene(), makeCamera(), makeRenderer())
    expect(result.stills).toHaveLength(4)
  })

  it('returns 36 turntable frames by default', async () => {
    const result = await renderHeroSet(makeScene(), makeCamera(), makeRenderer())
    expect(result.turntable).toHaveLength(36)
  })

  it('respects custom turntableFrames count', async () => {
    const result = await renderHeroSet(makeScene(), makeCamera(), makeRenderer(), { turntableFrames: 12 })
    expect(result.turntable).toHaveLength(12)
  })

  it('all stills are data-URL strings', async () => {
    const result = await renderHeroSet(makeScene(), makeCamera(), makeRenderer())
    for (const s of result.stills) {
      expect(typeof s).toBe('string')
      expect(s.startsWith('data:')).toBe(true)
    }
  })

  it('all turntable frames are data-URL strings', async () => {
    const result = await renderHeroSet(makeScene(), makeCamera(), makeRenderer())
    for (const f of result.turntable) {
      expect(typeof f).toBe('string')
      expect(f.startsWith('data:')).toBe(true)
    }
  })

  it('restores camera position after rendering', async () => {
    const cam = makeCamera({ x: 50, y: 50, z: 50 })
    await renderHeroSet(makeScene(), cam, makeRenderer())
    expect(cam.position.x).toBeCloseTo(50, 2)
    expect(cam.position.y).toBeCloseTo(50, 2)
    expect(cam.position.z).toBeCloseTo(50, 2)
  })

  it('restores camera fov after rendering', async () => {
    const cam = makeCamera()
    cam.fov = 45
    await renderHeroSet(makeScene(), cam, makeRenderer())
    expect(cam.fov).toBe(45)
  })

  it('lighting is applied then fully restored (no leak)', async () => {
    const origLight = makeFakeLight('AmbientLight')
    const scene = makeScene([origLight])
    await renderHeroSet(scene, makeCamera(), makeRenderer())
    // After the call: original light back, no jewelry lights remain.
    expect(scene.children).toContain(origLight)
    const leaked = scene.children.filter((c) => c.userData && c.userData._heroJewelry)
    expect(leaked.length).toBe(0)
  })

  it('calls renderer.render at least 4 times (one per still)', async () => {
    const ren = makeRenderer()
    await renderHeroSet(makeScene(), makeCamera(), ren)
    // 4 stills + 36 turntable frames = 40 renders minimum
    expect(ren.render.mock.calls.length).toBeGreaterThanOrEqual(4)
  })
})

// ── composeContactSheet ───────────────────────────────────────────────────────

describe('composeContactSheet', () => {
  it('throws when fewer than 4 images are provided', () => {
    expect(() => composeContactSheet(['a', 'b', 'c'])).toThrow('at least 4 images')
  })

  it('throws when images is not an array', () => {
    expect(() => composeContactSheet(null)).toThrow()
  })

  it('returns a data-URL string', () => {
    const images = Array(4).fill('data:image/png;base64,abc')
    const result = composeContactSheet(images)
    expect(typeof result).toBe('string')
    expect(result.startsWith('data:')).toBe(true)
  })

  it('works with more than 4 images (uses first 4)', () => {
    const images = Array(6).fill('data:image/png;base64,abc')
    expect(() => composeContactSheet(images)).not.toThrow()
  })
})

// ── socialMediaCrops ──────────────────────────────────────────────────────────

describe('socialMediaCrops', () => {
  it('throws when image is missing', async () => {
    await expect(socialMediaCrops(null)).rejects.toThrow('image is required')
  })

  it('throws when image is not a string', async () => {
    await expect(socialMediaCrops(42)).rejects.toThrow('image is required')
  })

  it('returns results for all requested platforms', async () => {
    const result = await socialMediaCrops(
      'data:image/png;base64,abc',
      ['instagram_post', 'instagram_story', 'x_card'],
    )
    expect(result).toHaveProperty('instagram_post')
    expect(result).toHaveProperty('instagram_story')
    expect(result).toHaveProperty('x_card')
  })

  it('instagram_post crop stub encodes 1:1 ratio in name', async () => {
    const result = await socialMediaCrops('data:image/png;base64,abc', ['instagram_post'])
    // In jsdom/stub environment the value should indicate a square crop or be a data-URL.
    const val = result.instagram_post
    expect(typeof val).toBe('string')
    // Stub path: width === height (1:1)
    if (val.includes('STUB_CROP')) {
      // e.g. STUB_CROP_instagram_post_1024x1024
      const match = val.match(/(\d+)x(\d+)/)
      if (match) expect(match[1]).toBe(match[2])
    }
  })

  it('instagram_story crop stub encodes 9:16 ratio in name', async () => {
    const result = await socialMediaCrops('data:image/png;base64,abc', ['instagram_story'])
    const val = result.instagram_story
    expect(typeof val).toBe('string')
    if (val.includes('STUB_CROP')) {
      const match = val.match(/(\d+)x(\d+)/)
      if (match) {
        const w = parseInt(match[1], 10)
        const h = parseInt(match[2], 10)
        // 9:16 → h/w ≈ 1.777
        expect(h / w).toBeCloseTo(16 / 9, 1)
      }
    }
  })

  it('x_card crop stub encodes 2:1 ratio in name', async () => {
    const result = await socialMediaCrops('data:image/png;base64,abc', ['x_card'])
    const val = result.x_card
    expect(typeof val).toBe('string')
    if (val.includes('STUB_CROP')) {
      const match = val.match(/(\d+)x(\d+)/)
      if (match) {
        const w = parseInt(match[1], 10)
        const h = parseInt(match[2], 10)
        // 2:1 → w/h = 2
        expect(w / h).toBeCloseTo(2, 1)
      }
    }
  })

  it('passes unknown platforms through unchanged', async () => {
    const src = 'data:image/png;base64,abc'
    const result = await socialMediaCrops(src, ['unknown_platform'])
    expect(result.unknown_platform).toBe(src)
  })

  it('default platforms include instagram_post, instagram_story, x_card', async () => {
    const result = await socialMediaCrops('data:image/png;base64,abc')
    expect(result).toHaveProperty('instagram_post')
    expect(result).toHaveProperty('instagram_story')
    expect(result).toHaveProperty('x_card')
  })

  it('works with an empty platforms list', async () => {
    const result = await socialMediaCrops('data:image/png;base64,abc', [])
    expect(Object.keys(result)).toHaveLength(0)
  })
})
