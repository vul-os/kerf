// frustumCull.js — S1 frustum culling helper for the Kerf 3D viewport.
//
// `cullByFrustum(meshes, camera, options)` returns the subset of meshes whose
// world-space AABB intersects the camera frustum. It also toggles
// `mesh.visible` so Three.js's per-draw-call path skips invisible geometry
// without any extra book-keeping at the call site.
//
// Design goals:
//   - O(N) per frame: one Frustum.intersectsBox call per mesh.
//   - Reuses bounding box computed on first call; recomputes only when
//     `mesh.matrixWorldNeedsUpdate` is set (object moved / transformed).
//   - Does NOT replace Three.js's built-in `mesh.frustumCulled` path — just
//     sets `mesh.visible` so the per-mesh cull is augmented for objects whose
//     geometries live inside groups (where Three's default path can miss the
//     real world-space AABB).

import * as THREE from 'three'

// Cache key on each mesh so we don't reconstruct Box3 objects every frame.
const _WORLD_BOX_CACHE = Symbol('_kerf_worldBox')
const _MATRIX_CACHE    = Symbol('_kerf_matrixCache')

const _frustum = new THREE.Frustum()
const _projScreenMatrix = new THREE.Matrix4()

/**
 * Compute (or return cached) world-space bounding box for a mesh.
 * Recomputes whenever `mesh.matrixWorldNeedsUpdate` is true or the
 * cached matrix differs from the current `matrixWorld`.
 *
 * @param {THREE.Mesh} mesh
 * @returns {THREE.Box3 | null}
 */
function worldBoundingBox(mesh) {
  const geom = mesh.geometry
  if (!geom) return null

  // Ensure geometry-local bounding box exists.
  if (!geom.boundingBox) {
    geom.computeBoundingBox()
  }
  if (!geom.boundingBox) return null

  // Check if we need to recompute the world box.
  // We store the Box3 and the matrixWorld elements as a Float32Array for comparison.
  const cachedBox    = mesh[_WORLD_BOX_CACHE]
  const cachedMatrix = mesh[_MATRIX_CACHE]

  // matrixWorldNeedsUpdate alone isn't enough — Three updates the matrix
  // inside `renderer.render()`, so by the time we call this it may already
  // be fresh. Instead compare the 16 elements directly.
  mesh.updateWorldMatrix(true, false)
  const currentEls = mesh.matrixWorld.elements

  let dirty = !cachedBox || !cachedMatrix
  if (!dirty) {
    for (let i = 0; i < 16; i++) {
      if (cachedMatrix[i] !== currentEls[i]) { dirty = true; break }
    }
  }

  if (dirty) {
    const box = new THREE.Box3()
    box.copy(geom.boundingBox).applyMatrix4(mesh.matrixWorld)
    mesh[_WORLD_BOX_CACHE] = box
    mesh[_MATRIX_CACHE]    = Float32Array.from(currentEls)
    return box
  }

  return cachedBox
}

/**
 * Cull `meshes` against the camera frustum.
 *
 * For each mesh:
 *   - If its world-space AABB intersects the frustum → set `mesh.visible = true`.
 *   - Otherwise → set `mesh.visible = false`.
 *
 * Meshes that were already hidden by the caller (e.g. hiddenIds toggle) are
 * left with `visible = false` but do NOT get forced visible. We detect this by
 * checking an optional `_kerf_userVisible` property which Renderer writes when
 * it applies the hiddenIds toggle. If that property is absent we assume
 * user-visible = true (safe default: anything the caller passed in is
 * intended to be shown if in frustum).
 *
 * @param {THREE.Mesh[]} meshes
 * @param {THREE.Camera} camera
 * @param {{ enabled?: boolean }} [options]
 * @returns {THREE.Mesh[]} subset that are inside the frustum
 */
export function cullByFrustum(meshes, camera, options = {}) {
  const enabled = options.enabled !== false // default true

  // Build frustum from camera.
  _projScreenMatrix.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse)
  _frustum.setFromProjectionMatrix(_projScreenMatrix)

  const visible = []

  for (const mesh of meshes) {
    // Respect explicit user-hide (hiddenIds) — never un-hide.
    const userVisible = mesh._kerf_userVisible !== false

    if (!enabled) {
      // Feature flag off: let everything through (restore user-visible state).
      if (userVisible) mesh.visible = true
      if (userVisible) visible.push(mesh)
      continue
    }

    if (!userVisible) {
      mesh.visible = false
      continue
    }

    const box = worldBoundingBox(mesh)
    if (!box) {
      // No geometry bounding box — pass through (safe fallback).
      mesh.visible = true
      visible.push(mesh)
      continue
    }

    const inFrustum = _frustum.intersectsBox(box)
    mesh.visible = inFrustum
    if (inFrustum) visible.push(mesh)
  }

  return visible
}

/**
 * Mark a mesh's user-visibility intent. Called by Renderer when applying
 * hiddenIds so `cullByFrustum` can distinguish "hidden by user" from
 * "hidden by frustum" and never accidentally un-hides user-hidden geometry.
 *
 * @param {THREE.Mesh} mesh
 * @param {boolean} userVisible
 */
export function setUserVisible(mesh, userVisible) {
  mesh._kerf_userVisible = userVisible
  mesh.visible = userVisible
}

/**
 * Read the KERF_FRUSTUM_CULL localStorage flag.
 * Default: ON (returns true if absent).
 *
 * @returns {boolean}
 */
export function frustumCullEnabled() {
  try {
    const v = window.localStorage.getItem('KERF_FRUSTUM_CULL')
    if (v === null) return true   // default ON
    return v !== '0'
  } catch {
    return true
  }
}
