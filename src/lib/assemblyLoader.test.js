/**
 * assemblyLoader.test.js — Vitest unit tests for src/lib/assemblyLoader.js
 *
 * Tests are headless (no WebGL).  Three.js is mocked with minimal stubs.
 *
 * Coverage:
 *   - Components OUTSIDE frustum are NOT in the visible set
 *   - Components INSIDE frustum are in the visible set
 *   - Pre-fetch window loads components beyond the visible set
 *   - Components outside frustum + outside prefetch window are NOT loaded
 *   - markLoaded / getStatus lifecycle
 *   - LRU eviction when maxLoaded is exceeded
 *   - createAssemblyLoader factory helper
 */

import { describe, it, expect, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Three.js mock — must use vi.hoisted so classes are available when vi.mock
// factory is called (vi.mock is hoisted above imports).
// ---------------------------------------------------------------------------

const {
  MockVector3,
  MockBox3,
  MockMatrix4,
  MockFrustum,
  _frustumIntersects,
} = vi.hoisted(() => {
  // Mutable flag: tests can set this to control whether the Frustum
  // mock accepts or rejects box intersections.
  const _frustumIntersects = { value: true }

  class MockVector3 {
    constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this }
    clone() { return new MockVector3(this.x, this.y, this.z) }
    copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this }
  }

  class MockBox3 {
    constructor() {
      this.min = new MockVector3()
      this.max = new MockVector3()
    }
    set(min, max) { this.min.copy(min); this.max.copy(max); return this }
    applyMatrix4(m) { return this }
  }

  class MockMatrix4 {
    constructor() {
      this.elements = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
    }
    set(...args) { return this }
    multiplyMatrices(a, b) { return this }
  }

  class MockFrustum {
    constructor() {}
    setFromProjectionMatrix() { return this }
    intersectsBox() { return _frustumIntersects.value }
  }

  return { MockVector3, MockBox3, MockMatrix4, MockFrustum, _frustumIntersects }
})

vi.mock('three', () => ({
  Vector3: MockVector3,
  Box3:    MockBox3,
  Matrix4: MockMatrix4,
  Frustum: MockFrustum,
}))

// Import AFTER mock registration.
import {
  AssemblyLoader,
  createAssemblyLoader,
  STATUS_LOADED,
  STATUS_PREFETCH,
  STATUS_UNLOADED,
  DEFAULT_PREFETCH_WINDOW,
} from './assemblyLoader.js'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCamera() {
  return {
    projectionMatrix:    { elements: new Array(16).fill(0) },
    matrixWorldInverse:  { elements: new Array(16).fill(0) },
  }
}

function makeComponents(n, withBbox = false) {
  return Array.from({ length: n }, (_, i) => ({
    id:        `c-${i}`,
    bbox:      withBbox ? { min: [i, 0, 0], max: [i+1, 1, 1] } : null,
    transform: null,
  }))
}

// ---------------------------------------------------------------------------
// Tests: basic load lifecycle
// ---------------------------------------------------------------------------

describe('AssemblyLoader — basic lifecycle', () => {
  it('initially all components are STATUS_UNLOADED', () => {
    const loader = new AssemblyLoader(makeComponents(5))
    for (let i = 0; i < 5; i++) {
      expect(loader.getStatus(`c-${i}`)).toBe(STATUS_UNLOADED)
    }
  })

  it('markLoaded upgrades status to STATUS_LOADED', () => {
    const loader = new AssemblyLoader(makeComponents(3))
    loader.markLoaded('c-1')
    expect(loader.getStatus('c-1')).toBe(STATUS_LOADED)
  })

  it('unload removes a component from the cache', () => {
    const loader = new AssemblyLoader(makeComponents(3))
    loader.markLoaded('c-0')
    loader.unload('c-0')
    expect(loader.getStatus('c-0')).toBe(STATUS_UNLOADED)
  })

  it('unknown id returns STATUS_UNLOADED', () => {
    const loader = new AssemblyLoader(makeComponents(2))
    expect(loader.getStatus('not-a-real-id')).toBe(STATUS_UNLOADED)
  })
})

// ---------------------------------------------------------------------------
// Tests: frustum culling
// ---------------------------------------------------------------------------

describe('AssemblyLoader — frustum cull', () => {
  it('all null-bbox components appear in visibleIds (always-visible pass-through)', () => {
    _frustumIntersects.value = true
    const loader = new AssemblyLoader(makeComponents(5))
    const { visibleIds } = loader.update(makeCamera())
    expect(visibleIds.size).toBe(5)
    for (let i = 0; i < 5; i++) expect(visibleIds.has(`c-${i}`)).toBe(true)
  })

  it('components with bbox that frustum rejects are not visible', () => {
    _frustumIntersects.value = false  // Frustum rejects everything
    const comps = makeComponents(5, true)  // has bbox
    const loader = new AssemblyLoader(comps)
    const { visibleIds } = loader.update(makeCamera())
    // All have bboxes → frustum rejects all → none visible.
    expect(visibleIds.size).toBe(0)
    _frustumIntersects.value = true  // restore
  })

  it('components with bbox that frustum accepts are visible', () => {
    _frustumIntersects.value = true
    const comps = makeComponents(3, true)
    const loader = new AssemblyLoader(comps)
    const { visibleIds } = loader.update(makeCamera())
    expect(visibleIds.size).toBe(3)
  })

  it('null-bbox components are always visible regardless of frustum flag', () => {
    _frustumIntersects.value = false  // frustum rejects bbox components
    const comps = [
      { id: 'null-bbox',  bbox: null, transform: null },  // always visible
      { id: 'has-bbox',   bbox: { min: [0,0,0], max: [1,1,1] }, transform: null },
    ]
    const loader = new AssemblyLoader(comps)
    const { visibleIds } = loader.update(makeCamera())
    expect(visibleIds.has('null-bbox')).toBe(true)
    expect(visibleIds.has('has-bbox')).toBe(false)
    _frustumIntersects.value = true  // restore
  })
})

// ---------------------------------------------------------------------------
// Tests: prefetch window
// ---------------------------------------------------------------------------

describe('AssemblyLoader — prefetch window', () => {
  it('default prefetchWindow matches DEFAULT_PREFETCH_WINDOW', () => {
    const loader = new AssemblyLoader(makeComponents(5))
    expect(loader._prefetchWindow).toBe(DEFAULT_PREFETCH_WINDOW)
  })

  it('custom prefetchWindow option is respected', () => {
    const loader = new AssemblyLoader(makeComponents(50), { prefetchWindow: 7 })
    expect(loader._prefetchWindow).toBe(7)
  })

  it('prefetch includes non-visible components up to window size', () => {
    _frustumIntersects.value = false  // nothing visible (all have bbox)
    const comps = makeComponents(10, true)
    const loader = new AssemblyLoader(comps, { prefetchWindow: 3 })
    const { toLoad } = loader.update(makeCamera())
    // No visible components → prefetch first 3.
    expect(toLoad.length).toBe(3)
    expect(toLoad).toContain('c-0')
    expect(toLoad).toContain('c-1')
    expect(toLoad).toContain('c-2')
    // c-3 and beyond NOT in toLoad.
    expect(toLoad).not.toContain('c-3')
    _frustumIntersects.value = true  // restore
  })

  it('components outside frustum AND outside prefetch window are not in toLoad', () => {
    _frustumIntersects.value = false
    const comps = makeComponents(10, true)
    const loader = new AssemblyLoader(comps, { prefetchWindow: 2 })
    const { toLoad } = loader.update(makeCamera())
    // Only c-0 and c-1 prefetched; c-2..c-9 not loaded.
    for (let i = 2; i < 10; i++) {
      expect(toLoad).not.toContain(`c-${i}`)
    }
    _frustumIntersects.value = true
  })
})

// ---------------------------------------------------------------------------
// Tests: toEvict
// ---------------------------------------------------------------------------

describe('AssemblyLoader — eviction', () => {
  it('loaded visible components are NOT evicted', () => {
    _frustumIntersects.value = true
    const loader = new AssemblyLoader(makeComponents(3))
    loader.markLoaded('c-0')
    const { toEvict } = loader.update(makeCamera())
    expect(toEvict).not.toContain('c-0')
  })

  it('LRU eviction fires when maxLoaded is exceeded', () => {
    const loader = new AssemblyLoader(makeComponents(10), { maxLoaded: 3 })
    loader.markLoaded('c-0')
    loader.markLoaded('c-1')
    loader.markLoaded('c-2')
    loader.markLoaded('c-3')  // triggers eviction of c-0 (LRU)

    expect(loader.getStatus('c-0')).toBe(STATUS_UNLOADED)
    expect(loader.getStatus('c-3')).toBe(STATUS_LOADED)
  })

  it('eviction removes id from loadOrder', () => {
    const loader = new AssemblyLoader(makeComponents(5), { maxLoaded: 2 })
    loader.markLoaded('c-0')
    loader.markLoaded('c-1')
    loader.markLoaded('c-2')  // evicts c-0
    expect(loader._loadOrder).not.toContain('c-0')
    expect(loader._loadOrder.length).toBe(2)
  })
})

// ---------------------------------------------------------------------------
// Tests: getVisibleIds / getPrefetchIds return copies
// ---------------------------------------------------------------------------

describe('AssemblyLoader — accessors return copies', () => {
  it('mutating returned visibleIds does not affect internal state', () => {
    const loader = new AssemblyLoader(makeComponents(3))
    loader.update(makeCamera())
    const ids = loader.getVisibleIds()
    ids.clear()
    expect(loader.getVisibleIds().size).toBe(3)
  })

  it('mutating returned prefetchIds does not affect internal state', () => {
    _frustumIntersects.value = false
    const loader = new AssemblyLoader(makeComponents(5, true), { prefetchWindow: 3 })
    loader.update(makeCamera())
    const ids = loader.getPrefetchIds()
    ids.clear()
    expect(loader.getPrefetchIds().size).toBe(3)
    _frustumIntersects.value = true
  })
})

// ---------------------------------------------------------------------------
// Tests: createAssemblyLoader factory
// ---------------------------------------------------------------------------

describe('createAssemblyLoader', () => {
  it('creates an AssemblyLoader from a parsed assembly object', () => {
    const assembly = {
      components: [
        { id: 'a', file_id: 'f1', object_id: 'b1', transform: null },
        { id: 'b', file_id: 'f1', object_id: 'b2', transform: null },
      ],
    }
    const loader = createAssemblyLoader(assembly)
    expect(loader).toBeInstanceOf(AssemblyLoader)
    expect(loader._components.length).toBe(2)
    expect(loader._components[0].id).toBe('a')
    expect(loader._components[1].id).toBe('b')
  })

  it('maps bboxes from the provided bboxMap', () => {
    const assembly = {
      components: [{ id: 'x', file_id: 'f1', object_id: 'b1', transform: null }],
    }
    const bboxMap = new Map([['x', { min: [0,0,0], max: [1,1,1] }]])
    const loader = createAssemblyLoader(assembly, bboxMap)
    expect(loader._components[0].bbox).toEqual({ min: [0,0,0], max: [1,1,1] })
  })

  it('uses null bbox for components not in bboxMap', () => {
    const assembly = {
      components: [{ id: 'y', file_id: 'f1', object_id: 'b1', transform: null }],
    }
    const loader = createAssemblyLoader(assembly, new Map())
    expect(loader._components[0].bbox).toBeNull()
  })

  it('handles null / undefined assembly gracefully', () => {
    const loader = createAssemblyLoader(null)
    expect(loader).toBeInstanceOf(AssemblyLoader)
    expect(loader._components.length).toBe(0)
  })

  it('accepts opts forwarded to AssemblyLoader', () => {
    const assembly = { components: [] }
    const loader = createAssemblyLoader(assembly, new Map(), { prefetchWindow: 5 })
    expect(loader._prefetchWindow).toBe(5)
  })
})
