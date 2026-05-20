// assemblyLoader.js — Lazy-load + frustum-cull manager for large assemblies.
//
// Strategy
// --------
// For assemblies with > LOD_THRESHOLD_COUNT components, loading and
// tessellating every part upfront is prohibitively expensive.  This module
// implements a two-stage loading strategy:
//
//   1. **Frustum cull**: only components whose bounding box intersects the
//      camera frustum are candidates for loading.
//
//   2. **Pre-fetch window**: maintain a ring of `prefetchWindow` components
//      ahead of the currently-visible set so that parts just outside the
//      frustum are warm when the camera moves.
//
// Components are modelled as plain objects with a minimal shape — the loader
// is pure-JS and can be unit-tested without WebGL (Three.js is used only for
// frustum/box maths; the test suite mocks it).
//
// Public API
// ----------
//   AssemblyLoader(components, options) — constructor
//   loader.update(camera)               — call each frame (or on camera change)
//   loader.getVisibleIds()              — loaded + in-frustum component ids
//   loader.getPrefetchIds()             — ids currently warming up
//   loader.getStatus(id)                — 'loaded' | 'prefetch' | 'unloaded'
//   loader.markLoaded(id)               — called by the mesh-fetch pipeline
//   loader.unload(id)                   — evict from cache
//
// Component shape expected by this loader
// ----------------------------------------
//   {
//     id:        string,
//     bbox:      { min: [x,y,z], max: [x,y,z] } | null,
//     transform: number[16] | null,   // row-major 4×4; used to position bbox
//   }
//
// If `bbox` is null the component is treated as always-visible (pass-through)
// so parts without known bounds are never silently dropped.

import * as THREE from 'three'

// Default options.
export const DEFAULT_PREFETCH_WINDOW = 20
export const DEFAULT_MAX_LOADED = 1000    // evict oldest once above this

// Status constants.
export const STATUS_LOADED   = 'loaded'
export const STATUS_PREFETCH = 'prefetch'
export const STATUS_UNLOADED = 'unloaded'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const _frustum = new THREE.Frustum()
const _projScreen = new THREE.Matrix4()
const _box = new THREE.Box3()
const _min = new THREE.Vector3()
const _max = new THREE.Vector3()

/**
 * Test whether a component's world-space bbox intersects the camera frustum.
 *
 * @param {{ min: number[], max: number[] } | null} bbox
 * @param {number[] | null} transform  Row-major 4×4
 * @param {THREE.Frustum} frustum
 * @returns {boolean}
 */
function _inFrustum(bbox, transform, frustum) {
  if (!bbox) return true  // unknown bbox → assume visible

  _min.set(bbox.min[0], bbox.min[1], bbox.min[2])
  _max.set(bbox.max[0], bbox.max[1], bbox.max[2])
  _box.set(_min, _max)

  if (transform && transform.length === 16) {
    // Apply the row-major 4×4 transform.
    // THREE.Matrix4.set takes row-major arguments.
    const m = new THREE.Matrix4()
    m.set(
      transform[0],  transform[1],  transform[2],  transform[3],
      transform[4],  transform[5],  transform[6],  transform[7],
      transform[8],  transform[9],  transform[10], transform[11],
      transform[12], transform[13], transform[14], transform[15],
    )
    _box.applyMatrix4(m)
  }

  return frustum.intersectsBox(_box)
}

// ---------------------------------------------------------------------------
// AssemblyLoader
// ---------------------------------------------------------------------------

/**
 * Manages lazy-loading for a large assembly.
 *
 * @param {Array<{ id: string, bbox: object|null, transform: number[]|null }>} components
 * @param {object} [opts]
 * @param {number} [opts.prefetchWindow=20]   Number of extra components to warm.
 * @param {number} [opts.maxLoaded=1000]      Max loaded components before eviction.
 */
export class AssemblyLoader {
  constructor(components, opts = {}) {
    this._components = Array.isArray(components) ? components : []
    this._prefetchWindow = opts.prefetchWindow ?? DEFAULT_PREFETCH_WINDOW
    this._maxLoaded = opts.maxLoaded ?? DEFAULT_MAX_LOADED

    // id → STATUS_*
    this._status = new Map()

    // Ordered list of loaded ids (for LRU eviction).
    this._loadOrder = []

    // Last computed visible and prefetch sets.
    this._visibleIds  = new Set()
    this._prefetchIds = new Set()
  }

  // ---- Public query API ----------------------------------------------------

  /** Return ids of components that are in-frustum AND marked loaded. */
  getVisibleIds() { return new Set(this._visibleIds) }

  /** Return ids of components currently being pre-fetched. */
  getPrefetchIds() { return new Set(this._prefetchIds) }

  /**
   * Return the load status of a component by id.
   * @param {string} id
   * @returns {'loaded'|'prefetch'|'unloaded'}
   */
  getStatus(id) { return this._status.get(id) ?? STATUS_UNLOADED }

  // ---- Lifecycle -----------------------------------------------------------

  /**
   * Mark a component as fully loaded (mesh data available).
   * @param {string} id
   */
  markLoaded(id) {
    this._status.set(id, STATUS_LOADED)
    // Track load order for LRU eviction.
    const pos = this._loadOrder.indexOf(id)
    if (pos >= 0) this._loadOrder.splice(pos, 1)
    this._loadOrder.push(id)
    this._evictIfNeeded()
  }

  /**
   * Evict a component from the cache (free GPU/memory).
   * @param {string} id
   */
  unload(id) {
    this._status.delete(id)
    const pos = this._loadOrder.indexOf(id)
    if (pos >= 0) this._loadOrder.splice(pos, 1)
    this._visibleIds.delete(id)
    this._prefetchIds.delete(id)
  }

  // ---- Per-frame update ----------------------------------------------------

  /**
   * Compute the current visible set and prefetch window for the given camera.
   * Should be called each frame (or whenever the camera moves significantly).
   *
   * Returns { toLoad: string[], toEvict: string[], visibleIds: Set<string> }
   *   `toLoad`  — ids the caller should now start fetching (not yet loaded).
   *   `toEvict` — ids the caller may unload (well outside frustum + window).
   *   `visibleIds` — currently in-frustum loaded ids.
   *
   * @param {THREE.Camera} camera
   * @returns {{ toLoad: string[], toEvict: string[], visibleIds: Set<string> }}
   */
  update(camera) {
    // Rebuild frustum.
    _projScreen.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse)
    _frustum.setFromProjectionMatrix(_projScreen)

    // Classify each component as in-frustum or out-of-frustum.
    const inFrustumIndices = []
    for (let i = 0; i < this._components.length; i++) {
      const comp = this._components[i]
      if (_inFrustum(comp.bbox, comp.transform, _frustum)) {
        inFrustumIndices.push(i)
      }
    }

    // Build visible + prefetch index sets.
    const visibleSet  = new Set()
    const prefetchSet = new Set()

    // Compute the range of component indices to include in the prefetch window.
    // The prefetch window extends `_prefetchWindow` indices beyond the visible set
    // in document order (components are assumed ordered by spatial locality or
    // document order — the pre-fetch is a simple ring, not a spatial KD-tree).
    const visibleIdxSet = new Set(inFrustumIndices)
    let prefetchCount = 0
    let i = 0
    while (i < this._components.length && prefetchCount < this._prefetchWindow) {
      if (!visibleIdxSet.has(i)) {
        prefetchSet.add(this._components[i].id)
        prefetchCount++
      }
      i++
    }

    // Build visible id set.
    for (const idx of inFrustumIndices) {
      visibleSet.add(this._components[idx].id)
    }

    this._visibleIds  = visibleSet
    this._prefetchIds = prefetchSet

    // Determine what needs to be loaded.
    const wantLoaded = new Set([...visibleSet, ...prefetchSet])
    const toLoad = []
    for (const id of wantLoaded) {
      const s = this._status.get(id)
      if (s !== STATUS_LOADED) {
        // Mark as prefetch (will be upgraded to loaded by markLoaded).
        if (s !== STATUS_PREFETCH) {
          this._status.set(id, STATUS_PREFETCH)
        }
        toLoad.push(id)
      }
    }

    // Determine what can be evicted: loaded but neither visible nor prefetch.
    const toEvict = []
    for (const id of this._loadOrder) {
      if (!wantLoaded.has(id)) {
        toEvict.push(id)
      }
    }

    return { toLoad, toEvict, visibleIds: new Set(visibleSet) }
  }

  // ---- Private helpers -----------------------------------------------------

  _evictIfNeeded() {
    while (this._loadOrder.length > this._maxLoaded) {
      const id = this._loadOrder.shift()
      this._status.delete(id)
      this._visibleIds.delete(id)
      this._prefetchIds.delete(id)
    }
  }
}

// ---------------------------------------------------------------------------
// Factory helper
// ---------------------------------------------------------------------------

/**
 * Create an AssemblyLoader from a parsed assembly (the shape returned by
 * `parseAssembly` in assembly.js) and an optional bounding-box map.
 *
 * @param {{ components: Array }} assembly  Parsed assembly object.
 * @param {Map<string, { min: number[], max: number[] }>} [bboxMap]
 *   Optional map from component.id → world-space bbox.  If omitted, all
 *   components are treated as always-visible.
 * @param {object} [opts]  Forwarded to AssemblyLoader constructor.
 * @returns {AssemblyLoader}
 */
export function createAssemblyLoader(assembly, bboxMap = new Map(), opts = {}) {
  const comps = (assembly?.components ?? []).map(comp => ({
    id:        comp.id,
    bbox:      bboxMap.get(comp.id) ?? null,
    transform: Array.isArray(comp.transform) ? comp.transform : null,
  }))
  return new AssemblyLoader(comps, opts)
}
