/**
 * heroShot.test.js — Vitest suite for the hero-shot single-image capture.
 *
 * Three.js / WebGL is stubbed; no DOM, no GPU.
 */

import { describe, it, expect, vi } from 'vitest'
import { captureHeroShot, _internals } from './heroShot.js'

// ── Stubs ────────────────────────────────────────────────────────────────────

function makeRenderer({ width = 800, height = 600, withBlob = true } = {}) {
  const domEl = {
    width,
    height,
  }
  if (withBlob) {
    domEl.toBlob = (cb, mime) => {
      // jsdom doesn't ship toBlob on WebGLCanvas, but our fake does.
      const buf = new Uint8Array([137, 80, 78, 71]) // PNG magic
      cb(new Blob([buf], { type: mime || 'image/png' }))
    }
  }
  domEl.toDataURL = () => 'data:image/png;base64,iVBORw0KGgo='
  let clearAlpha = 1
  return {
    domElement: domEl,
    render: vi.fn(),
    setSize: vi.fn((w, h) => { domEl.width = w; domEl.height = h }),
    setClearAlpha: vi.fn((a) => { clearAlpha = a }),
    getClearAlpha: () => clearAlpha,
  }
}

function makeScene() {
  return {
    children: [],
    background: { _hex: 0x111111, clone() { return { ...this } }, setHex(h) { this._hex = h } },
  }
}

function makeCamera() {
  return {
    aspect: 1,
    projectionMatrix: {
      elements: new Float32Array(16),
      clone() { return { elements: this.elements.slice(), copy(o) { this.elements = o.elements.slice() } } },
      copy(o) { this.elements = o.elements.slice() },
    },
    updateProjectionMatrix: vi.fn(),
  }
}

function makeNode(visible = true) {
  return { visible }
}

// ── Argument validation ──────────────────────────────────────────────────────

describe('captureHeroShot — argument validation', () => {
  it('throws when opts is missing', async () => {
    await expect(captureHeroShot()).rejects.toThrow('opts is required')
  })
  it('throws when renderer is missing', async () => {
    await expect(
      captureHeroShot({ scene: makeScene(), camera: makeCamera() })
    ).rejects.toThrow('renderer is required')
  })
  it('throws when scene is missing', async () => {
    await expect(
      captureHeroShot({ renderer: makeRenderer(), camera: makeCamera() })
    ).rejects.toThrow('scene is required')
  })
  it('throws when camera is missing', async () => {
    await expect(
      captureHeroShot({ renderer: makeRenderer(), scene: makeScene() })
    ).rejects.toThrow('camera is required')
  })
})

// ── Capture happy path ───────────────────────────────────────────────────────

describe('captureHeroShot — capture', () => {
  it('returns a Blob in the happy path', async () => {
    const blob = await captureHeroShot({
      renderer: makeRenderer(),
      scene: makeScene(),
      camera: makeCamera(),
    })
    expect(blob).toBeInstanceOf(Blob)
  })

  it('runs at least 1 render pass', async () => {
    const r = makeRenderer()
    await captureHeroShot({ renderer: r, scene: makeScene(), camera: makeCamera(), samples: 1 })
    // 1 supersample + 1 final unjittered pass
    expect(r.render.mock.calls.length).toBeGreaterThanOrEqual(1)
  })

  it('uses N supersample passes + 1 final pass when samples=N', async () => {
    const r = makeRenderer()
    await captureHeroShot({ renderer: r, scene: makeScene(), camera: makeCamera(), samples: 4 })
    expect(r.render.mock.calls.length).toBe(5)
  })

  it('upscales the renderer to width/height during capture', async () => {
    const r = makeRenderer()
    await captureHeroShot({
      renderer: r, scene: makeScene(), camera: makeCamera(),
      width: 2048, height: 2048,
    })
    // setSize called with 2048,2048 at start, and original 800,600 at end.
    const calls = r.setSize.mock.calls
    expect(calls.some((c) => c[0] === 2048 && c[1] === 2048)).toBe(true)
    expect(calls[calls.length - 1][0]).toBe(800)
    expect(calls[calls.length - 1][1]).toBe(600)
  })

  it('defaults to 2048×2048 when width/height not provided', async () => {
    const r = makeRenderer()
    await captureHeroShot({ renderer: r, scene: makeScene(), camera: makeCamera() })
    const calls = r.setSize.mock.calls
    expect(calls.some((c) => c[0] === 2048 && c[1] === 2048)).toBe(true)
  })

  it('defaults to 4 samples (5 total render passes)', async () => {
    const r = makeRenderer()
    await captureHeroShot({ renderer: r, scene: makeScene(), camera: makeCamera() })
    expect(r.render.mock.calls.length).toBe(5)
  })

  it('restores aspect after capture', async () => {
    const cam = makeCamera()
    cam.aspect = 1.5
    await captureHeroShot({
      renderer: makeRenderer(), scene: makeScene(), camera: cam,
      width: 2048, height: 1024,
    })
    expect(cam.aspect).toBe(1.5)
  })

  it('hides hideTargets during capture and restores after', async () => {
    const a = makeNode(true)
    const b = makeNode(true)
    const r = makeRenderer()
    // Capture state of visibility inside render
    r.render.mockImplementation(() => {
      expect(a.visible).toBe(false)
      expect(b.visible).toBe(false)
    })
    await captureHeroShot({
      renderer: r, scene: makeScene(), camera: makeCamera(),
      hideTargets: [a, b],
    })
    expect(a.visible).toBe(true)
    expect(b.visible).toBe(true)
  })

  it('restores hideTargets visibility even if render throws', async () => {
    const a = makeNode(true)
    const r = makeRenderer()
    r.render.mockImplementation(() => { throw new Error('boom') })
    await expect(captureHeroShot({
      renderer: r, scene: makeScene(), camera: makeCamera(),
      hideTargets: [a],
    })).rejects.toThrow('boom')
    expect(a.visible).toBe(true)
  })

  it('routes through composer.render when composer is provided', async () => {
    const r = makeRenderer()
    const composer = { render: vi.fn(), setSize: vi.fn() }
    await captureHeroShot({
      renderer: r, scene: makeScene(), camera: makeCamera(),
      composer, samples: 2,
    })
    // composer.render called for supersample passes + final
    expect(composer.render.mock.calls.length).toBe(3)
    // renderer.render NOT called when composer drives
    expect(r.render.mock.calls.length).toBe(0)
  })

  it('sets clearAlpha=0 when transparent=true and restores after', async () => {
    const r = makeRenderer()
    await captureHeroShot({
      renderer: r, scene: makeScene(), camera: makeCamera(),
      transparent: true,
    })
    expect(r.setClearAlpha.mock.calls.some((c) => c[0] === 0)).toBe(true)
    // Last call restores
    expect(r.setClearAlpha.mock.calls.at(-1)[0]).toBe(1)
  })

  it('falls back to dataURL→Blob when domElement.toBlob is missing', async () => {
    const r = makeRenderer({ withBlob: false })
    const blob = await captureHeroShot({
      renderer: r, scene: makeScene(), camera: makeCamera(),
    })
    expect(blob).toBeInstanceOf(Blob)
  })
})

// ── Internals ────────────────────────────────────────────────────────────────

describe('captureHeroShot — internals', () => {
  it('_dataUrlToBlob returns Blob for valid data-URL', () => {
    const blob = _internals._dataUrlToBlob('data:image/png;base64,iVBORw0KGgo=')
    expect(blob).toBeInstanceOf(Blob)
  })
  it('_dataUrlToBlob returns null for empty input', () => {
    expect(_internals._dataUrlToBlob('')).toBe(null)
    expect(_internals._dataUrlToBlob(null)).toBe(null)
  })
  it('DEFAULT_HERO_W is 2048', () => {
    expect(_internals.DEFAULT_HERO_W).toBe(2048)
  })
  it('DEFAULT_HERO_H is 2048', () => {
    expect(_internals.DEFAULT_HERO_H).toBe(2048)
  })
  it('DEFAULT_SAMPLES is 4', () => {
    expect(_internals.DEFAULT_SAMPLES).toBe(4)
  })
  it('_applyProjectionJitter adjusts elements 8 and 9', () => {
    const cam = makeCamera()
    cam.projectionMatrix.elements[8] = 0
    cam.projectionMatrix.elements[9] = 0
    _internals._applyProjectionJitter(cam, 2048, 2048, 0.5, -0.5)
    expect(cam.projectionMatrix.elements[8]).toBeCloseTo(2 * 0.5 / 2048, 5)
    expect(cam.projectionMatrix.elements[9]).toBeCloseTo(-2 * 0.5 / 2048, 5)
  })
  it('_clearProjectionJitter is a no-op when nothing stashed', () => {
    const cam = makeCamera()
    expect(() => _internals._clearProjectionJitter(cam)).not.toThrow()
  })
})
