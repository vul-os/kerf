// derivedCacheOverlay.test.js
//
// Tests for the compile-on-demand cache integration:
//   1. Cache hit → compile (recompile fn) is short-circuited.
//   2. Cache miss → result is stored after recompile.
//   3. onStats callback receives correct event on hit and miss.
//   4. addDerivedCacheListener fires for hits and misses and can be unsubscribed.
//
// These tests focus on the compile-on-demand glue (onStats + event bus) that
// wires the dev overlay. The core hit/miss/store mechanics are covered by
// the deeper suite in assembly.test.js.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../lib/geom3.js', () => ({
  applyMatrixToGeom: (geom) => geom,
}))

import {
  loadExternalParts,
  addDerivedCacheListener,
  derivedKindForRefKind,
} from '../lib/assembly.js'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const REF = {
  project_id: 'proj-cache-test',
  file_id: 'file-cache-test',
  kind: 'board_3d',
  pin: 'tracking_latest',
}

// Helper: drain the microtask queue so fire-and-forget store calls complete.
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

// ---------------------------------------------------------------------------
// 1. Cache hit → recompile is short-circuited
// ---------------------------------------------------------------------------

describe('compile-on-demand: cache hit skips recompile', () => {
  it('returns cached parts without calling recompile', async () => {
    const cachedParts = [{ id: '__board__', geom: { tag: 'cached' } }]
    const lookup = vi.fn(async () => ({
      cached: true,
      derivedKind: 'circuit_board_3d',
      payload: new Uint8Array([1, 2, 3]),
    }))
    const decodePayload = vi.fn(async () => cachedParts)
    const recompile = vi.fn(async () => { throw new Error('recompile must not be called on hit') })

    const out = await loadExternalParts({ ref: REF, recompile, lookup, decodePayload })

    expect(out).toBe(cachedParts)
    expect(recompile).not.toHaveBeenCalled()
    expect(lookup).toHaveBeenCalledOnce()
    expect(decodePayload).toHaveBeenCalledOnce()
  })

  it('onStats receives { hit:true } with derivedKind on a cache hit', async () => {
    const cachedParts = [{ id: 'r', geom: {} }]
    const lookup = vi.fn(async () => ({
      cached: true,
      derivedKind: 'circuit_board_3d',
      payload: new Uint8Array([9, 8, 7]),
    }))
    const decodePayload = vi.fn(async () => cachedParts)
    const recompile = vi.fn()
    const onStats = vi.fn()

    await loadExternalParts({ ref: REF, recompile, lookup, decodePayload, onStats })

    expect(onStats).toHaveBeenCalledOnce()
    const evt = onStats.mock.calls[0][0]
    expect(evt.hit).toBe(true)
    expect(evt.derivedKind).toBe('circuit_board_3d')
    expect(evt.projectId).toBe(REF.project_id)
    expect(evt.fileId).toBe(REF.file_id)
    expect(typeof evt.timestamp).toBe('number')
    // payload size: 3 bytes from the Uint8Array above
    expect(evt.payloadSize).toBe(3)
  })
})

// ---------------------------------------------------------------------------
// 2. Cache miss → recompile runs and result is stored
// ---------------------------------------------------------------------------

describe('compile-on-demand: cache miss triggers recompile + store', () => {
  it('calls recompile on miss and fire-and-forgets store afterward', async () => {
    const recompiled = [{ id: '__fresh__', geom: { tag: 'fresh' } }]
    const encoded = new Uint8Array([0xde, 0xad])

    const lookup = vi.fn(async () => ({
      cached: false,
      derivedKind: 'circuit_board_3d',
      payload: null,
      error: 'compile-on-demand-not-yet-wired',
    }))
    const recompile = vi.fn(async () => recompiled)
    const encodePayload = vi.fn(async (kind, parts) => {
      expect(kind).toBe('circuit_board_3d')
      expect(parts).toBe(recompiled)
      return encoded
    })
    const store = vi.fn(async ({ projectId, fileId, derivedKind, payload }) => {
      expect(projectId).toBe(REF.project_id)
      expect(fileId).toBe(REF.file_id)
      expect(derivedKind).toBe('circuit_board_3d')
      expect(payload).toBe(encoded)
      return { stored: true, payloadSize: encoded.length }
    })

    const out = await loadExternalParts({
      ref: REF, recompile, lookup, encodePayload, store,
    })

    // Returned parts are from recompile, not the (absent) cache.
    expect(out).toBe(recompiled)
    expect(recompile).toHaveBeenCalledOnce()

    // The store call is fire-and-forget; flush the microtask queue.
    await flush()
    expect(encodePayload).toHaveBeenCalledOnce()
    expect(store).toHaveBeenCalledOnce()
  })

  it('onStats receives { hit:false } on a cache miss', async () => {
    const recompiled = [{ id: 'r', geom: {} }]
    const lookup = vi.fn(async () => ({
      cached: false,
      derivedKind: 'circuit_board_3d',
      payload: null,
    }))
    const recompile = vi.fn(async () => recompiled)
    const onStats = vi.fn()

    await loadExternalParts({ ref: REF, recompile, lookup, onStats })

    expect(onStats).toHaveBeenCalledOnce()
    const evt = onStats.mock.calls[0][0]
    expect(evt.hit).toBe(false)
    expect(evt.derivedKind).toBe('circuit_board_3d')
    expect(evt.payloadSize).toBeNull()
    expect(evt.projectId).toBe(REF.project_id)
    expect(typeof evt.timestamp).toBe('number')
  })

  it('store failure does not alter returned parts (strict fire-and-forget)', async () => {
    const recompiled = [{ id: 'r', geom: {} }]
    const lookup = vi.fn(async () => ({ cached: false, derivedKind: 'circuit_board_3d', payload: null }))
    const recompile = vi.fn(async () => recompiled)
    const encodePayload = vi.fn(async () => new Uint8Array([1]))
    const store = vi.fn(async () => { throw new Error('server 500') })

    const out = await loadExternalParts({ ref: REF, recompile, lookup, encodePayload, store })
    expect(out).toBe(recompiled)
    await flush()
    expect(store).toHaveBeenCalledOnce()
  })
})

// ---------------------------------------------------------------------------
// 3. Event bus (addDerivedCacheListener)
// ---------------------------------------------------------------------------

describe('addDerivedCacheListener — module-level event bus', () => {
  let dispose

  afterEach(() => {
    if (dispose) { dispose(); dispose = null }
  })

  it('fires listener with hit:true on a cache hit', async () => {
    const events = []
    dispose = addDerivedCacheListener((evt) => events.push(evt))

    const cachedParts = [{ id: 'r', geom: {} }]
    const lookup = vi.fn(async () => ({
      cached: true,
      derivedKind: 'circuit_board_3d',
      payload: new Uint8Array([5]),
    }))
    const decodePayload = vi.fn(async () => cachedParts)
    const recompile = vi.fn()

    await loadExternalParts({ ref: REF, recompile, lookup, decodePayload })

    expect(events).toHaveLength(1)
    expect(events[0].hit).toBe(true)
    expect(events[0].derivedKind).toBe('circuit_board_3d')
  })

  it('fires listener with hit:false on a cache miss', async () => {
    const events = []
    dispose = addDerivedCacheListener((evt) => events.push(evt))

    const lookup = vi.fn(async () => ({ cached: false, derivedKind: 'circuit_board_3d', payload: null }))
    const recompile = vi.fn(async () => [{ id: 'x', geom: {} }])

    await loadExternalParts({ ref: REF, recompile, lookup })

    expect(events).toHaveLength(1)
    expect(events[0].hit).toBe(false)
  })

  it('disposer removes the listener so no further events arrive', async () => {
    const events = []
    const unsub = addDerivedCacheListener((evt) => events.push(evt))

    // First lookup — listener is active.
    const lookup = vi.fn(async () => ({ cached: false, derivedKind: 'circuit_board_3d', payload: null }))
    const recompile = vi.fn(async () => [{ id: 'x', geom: {} }])
    await loadExternalParts({ ref: REF, recompile, lookup })
    expect(events).toHaveLength(1)

    // Dispose.
    unsub()

    // Second lookup — listener should be silent.
    await loadExternalParts({ ref: REF, recompile, lookup })
    expect(events).toHaveLength(1) // unchanged
  })

  it('multiple listeners all receive the same event', async () => {
    const a = [], b = []
    const d1 = addDerivedCacheListener((e) => a.push(e))
    const d2 = addDerivedCacheListener((e) => b.push(e))

    const lookup = vi.fn(async () => ({ cached: false, derivedKind: 'jscad_mesh', payload: null }))
    const recompile = vi.fn(async () => [{ id: 'q', geom: {} }])
    await loadExternalParts({
      ref: { ...REF, kind: 'mesh' },
      recompile,
      lookup,
    })

    expect(a).toHaveLength(1)
    expect(b).toHaveLength(1)
    expect(a[0]).toBe(b[0]) // same event object

    d1(); d2()
  })

  it('a throwing listener does not propagate errors or silence other listeners', async () => {
    const good = []
    const d1 = addDerivedCacheListener(() => { throw new Error('bad listener') })
    const d2 = addDerivedCacheListener((e) => good.push(e))

    const lookup = vi.fn(async () => ({ cached: false, derivedKind: 'circuit_board_3d', payload: null }))
    const recompile = vi.fn(async () => [{ id: 'x', geom: {} }])

    // Must not throw.
    await expect(
      loadExternalParts({ ref: REF, recompile, lookup }),
    ).resolves.toBeDefined()

    expect(good).toHaveLength(1)
    d1(); d2()
  })
})

// ---------------------------------------------------------------------------
// 4. derivedKindForRefKind helper (belt-and-suspenders for overlay integration)
// ---------------------------------------------------------------------------

describe('derivedKindForRefKind — kind mapping', () => {
  it('maps all three supported kinds', () => {
    expect(derivedKindForRefKind('board_3d')).toBe('circuit_board_3d')
    expect(derivedKindForRefKind('board_outline_2d')).toBe('sketch_geom2')
    expect(derivedKindForRefKind('mesh')).toBe('jscad_mesh')
  })

  it('returns null for unknown or falsy inputs', () => {
    expect(derivedKindForRefKind('rocket-fuel')).toBeNull()
    expect(derivedKindForRefKind('')).toBeNull()
    expect(derivedKindForRefKind(null)).toBeNull()
    expect(derivedKindForRefKind(undefined)).toBeNull()
  })
})
