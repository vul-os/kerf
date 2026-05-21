/**
 * Renderer.webgl-fallback.test.jsx — T-C4
 *
 * Verifies that Renderer renders the WebGL-unavailable fallback panel when
 * detectWebGL returns false.  Uses react-dom/server (renderToStaticMarkup)
 * so no real DOM, GPU, or canvas is required.
 *
 * Strategy:
 *  - mock `../lib/detectWebGL` to return false
 *  - mock all Three.js / heavy deps (never instantiated because the effect
 *    bails before creating a WebGLRenderer when webGLUnavailable=true)
 *  - render Renderer via renderToStaticMarkup and assert the fallback markup
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'

// ── Mock detectWebGL to return false ─────────────────────────────────────────
vi.mock('../lib/detectWebGL.js', () => ({
  detectWebGL: () => false,
}))

// ── Stub lucide-react ─────────────────────────────────────────────────────────
vi.mock('lucide-react', () => {
  const make = (name) => ({ size, className }) =>
    React.createElement('svg', { 'data-icon': name, width: size, className: className ?? '' })
  return {
    Sun: make('sun'),
    SlidersHorizontal: make('sliders'),
    Check: make('check'),
    ChevronDown: make('chevron-down'),
    MonitorX: make('monitor-x'),
  }
})

// ── Stub three (all usages guarded by early return, but module must resolve) ──
vi.mock('three', () => {
  const noop = () => {}
  class Fake { constructor() {} set() { return this } dispose() {} }
  return {
    WebGLRenderer: class extends Fake { constructor(o) { super(); this.setPixelRatio = noop; this.setClearColor = noop; this.setSize = noop; this.render = noop; this.domElement = (typeof document !== 'undefined' ? document.createElement('canvas') : {}) } },
    Scene: Fake,
    PerspectiveCamera: Fake,
    AmbientLight: Fake,
    DirectionalLight: Fake,
    PMREMGenerator: Fake,
    Color: Fake,
    GridHelper: Fake,
    AxesHelper: Fake,
    Vector2: Fake,
    Vector3: Fake,
    BufferGeometry: Fake,
    BufferAttribute: Fake,
    Raycaster: Fake,
    Mesh: Fake,
    MeshStandardMaterial: Fake,
    InstancedMesh: Fake,
    PlaneGeometry: Fake,
    ShadowMaterial: Fake,
    ACESFilmicToneMapping: 5,
    SRGBColorSpace: 'srgb',
    PCFSoftShadowMap: 2,
    TOUCH: { ROTATE: 0, DOLLY_PAN: 1 },
    CanvasTexture: Fake,
    SphereGeometry: Fake,
    MeshBasicMaterial: Fake,
    DataTexture: Fake,
    RGBAFormat: 1023,
    FloatType: 1015,
    LinearFilter: 1006,
    Group: Fake,
  }
})

// ── Stub three jsm helpers ────────────────────────────────────────────────────
vi.mock('three/examples/jsm/controls/OrbitControls.js', () => ({ OrbitControls: class { constructor() {} dispose() {} update() {} } }))
vi.mock('three/examples/jsm/lines/Line2.js', () => ({ Line2: class { constructor() {} } }))
vi.mock('three/examples/jsm/lines/LineGeometry.js', () => ({ LineGeometry: class { constructor() {} setPositions() {} dispose() {} } }))
vi.mock('three/examples/jsm/lines/LineMaterial.js', () => ({ LineMaterial: class { constructor() {} dispose() {} } }))
vi.mock('three/examples/jsm/postprocessing/EffectComposer.js', () => ({ EffectComposer: class { constructor() {} addPass() {} setSize() {} setPixelRatio() {} render() {} dispose() {} } }))
vi.mock('three/examples/jsm/postprocessing/RenderPass.js', () => ({ RenderPass: class { constructor() {} dispose() {} } }))
vi.mock('three/examples/jsm/postprocessing/UnrealBloomPass.js', () => ({ UnrealBloomPass: class { constructor() { this.resolution = { set: () => {} }; this.enabled = true } dispose() {} } }))
vi.mock('three/examples/jsm/loaders/RGBELoader.js', () => ({ RGBELoader: class { constructor() {} load() {} } }))
vi.mock('three/examples/jsm/environments/RoomEnvironment.js', () => ({ RoomEnvironment: class { constructor() {} dispose() {} } }))

// ── Stub internal lib deps ────────────────────────────────────────────────────
vi.mock('../lib/geom3.js', () => ({ geom3ToBufferGeometry: () => null, combinedBoundingBox: () => null }))
vi.mock('../lib/topology.js', () => ({ getTopologyLazy: () => new Map() }))
vi.mock('../lib/measure.js', () => ({ distance: () => 0, formatDistance: () => '' }))
vi.mock('../lib/frustumCull.js', () => ({ cullByFrustum: () => {}, setUserVisible: () => {}, frustumCullEnabled: () => false }))
vi.mock('../lib/instancingPlan.js', () => ({ planInstances: () => ({ groups: [] }), instancingEnabled: () => false }))
vi.mock('../lib/zebraMaterial.js', () => ({ createZebraMaterial: () => ({}) }))
vi.mock('../lib/turntableRender.js', () => ({ recordTurntable: async () => {} }))
vi.mock('../lib/dfmOverlay.js', () => ({ attachDfmOverlay: () => {}, detachDfmOverlay: () => {}, refreshDfm: () => {} }))
vi.mock('../lib/heroRender.js', () => ({ renderHeroSet: async () => {} }))
vi.mock('../lib/heroShot.js', () => ({ captureHeroShot: async () => {} }))
vi.mock('../lib/applyDocLightsToScene.js', () => ({ applyDocLightsToScene: () => {} }))
vi.mock('./HeroRenderPanel.jsx', () => ({ default: () => null }))

// ── Import after mocks are registered ────────────────────────────────────────
import RendererRaw from './Renderer.jsx'

// forwardRef component; wrap it so SSR render works without a ref prop.
const Renderer = React.forwardRef ? RendererRaw : RendererRaw

describe('Renderer — WebGL fallback (T-C4)', () => {
  it('renders the fallback panel when detectWebGL returns false', () => {
    const html = renderToStaticMarkup(
      React.createElement(Renderer, { parts: [] }),
    )
    // The fallback div carries this test id.
    expect(html).toContain('data-testid="renderer-webgl-fallback"')
  })

  it('fallback panel has role=status', () => {
    const html = renderToStaticMarkup(
      React.createElement(Renderer, { parts: [] }),
    )
    expect(html).toContain('role="status"')
  })

  it('fallback panel has aria-live=polite', () => {
    const html = renderToStaticMarkup(
      React.createElement(Renderer, { parts: [] }),
    )
    expect(html).toContain('aria-live="polite"')
  })

  it('fallback panel contains the MonitorX icon', () => {
    const html = renderToStaticMarkup(
      React.createElement(Renderer, { parts: [] }),
    )
    expect(html).toContain('data-icon="monitor-x"')
  })

  it('does NOT render the normal canvas mount div when WebGL is unavailable', () => {
    const html = renderToStaticMarkup(
      React.createElement(Renderer, { parts: [] }),
    )
    // The normal viewport mounts here; it should be absent in the fallback path.
    expect(html).not.toContain('absolute inset-0 overflow-hidden')
  })
})
