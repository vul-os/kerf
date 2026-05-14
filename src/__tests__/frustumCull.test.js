// frustumCull.test.js — vitest coverage for the S1 frustum culling helper.
//
// Strategy: we need THREE.Box3, THREE.Frustum, THREE.Matrix4, THREE.Vector3.
// These are pure math classes with no WebGL dependency, so they work fine in
// Node. We mock THREE.Mesh objects as plain objects carrying the properties the
// helper reads.
//
// Cases:
//   1. mesh inside frustum  → returns it, visible stays true
//   2. mesh outside frustum → excluded, visible set false
//   3. mesh straddling frustum (AABB partially overlaps) → included
//   4. empty mesh list  → returns empty array
//   5. missing bounding box → auto-computed; mesh passes through

import { describe, it, expect, beforeEach, vi } from 'vitest'
import * as THREE from 'three'

// --------------------------------------------------------------------------
// We exercise the real frustumCull.js helper.  Because it references
// `window.localStorage` only in `frustumCullEnabled()` (not in the core
// cullByFrustum path), and vitest's jsdom environment exposes window, we can
// import the module directly.
import { cullByFrustum, setUserVisible } from '../lib/frustumCull.js'

// --------------------------------------------------------------------------
// Helpers to build a fake Mesh and an orthographic frustum that exactly
// covers a known AABB.

/**
 * Build a minimal mesh-like object with a BufferGeometry that has a pre-set
 * bounding box, and an identity matrixWorld (so world-space AABB == local AABB).
 *
 * @param {THREE.Box3} bbox  The geometry-local bounding box.
 * @returns {object}  Behaves like THREE.Mesh for the purposes of cullByFrustum.
 */
function makeMesh(bbox) {
  const geom = new THREE.BufferGeometry()
  geom.boundingBox = bbox.clone()

  // Provide the minimal subset of Mesh API that cullByFrustum calls.
  return {
    geometry: geom,
    matrixWorld: new THREE.Matrix4(),      // identity
    _kerf_userVisible: undefined,
    visible: true,
    updateWorldMatrix: () => {},           // no-op; identity stays
  }
}

/**
 * Build a perspective camera frustum that exactly contains the unit cube
 * [-1,1] × [-1,1] × [-1,1] when placed at (0,0,10) looking at the origin.
 * Parts outside that window will be culled.
 */
function makeFrustum() {
  const camera = new THREE.PerspectiveCamera(90, 1, 0.5, 100)
  camera.position.set(0, 0, 10)
  camera.lookAt(0, 0, 0)
  camera.updateMatrixWorld()
  camera.updateProjectionMatrix()
  return camera
}

// --------------------------------------------------------------------------

describe('cullByFrustum', () => {
  let camera

  beforeEach(() => {
    camera = makeFrustum()
  })

  // 1. Mesh clearly inside the frustum.
  it('returns a mesh whose AABB lies inside the camera frustum and keeps it visible', () => {
    // A tiny box right at the origin — well within the frustum.
    const mesh = makeMesh(new THREE.Box3(
      new THREE.Vector3(-0.1, -0.1, -0.1),
      new THREE.Vector3( 0.1,  0.1,  0.1),
    ))
    const result = cullByFrustum([mesh], camera)
    expect(result).toContain(mesh)
    expect(mesh.visible).toBe(true)
  })

  // 2. Mesh clearly outside the frustum (behind the camera).
  it('excludes a mesh whose AABB is completely behind the camera and sets visible=false', () => {
    // Box is at z = +50, far behind the camera which is at z=10 looking toward -z.
    const mesh = makeMesh(new THREE.Box3(
      new THREE.Vector3(-0.5, -0.5, 40),
      new THREE.Vector3( 0.5,  0.5, 50),
    ))
    const result = cullByFrustum([mesh], camera)
    expect(result).not.toContain(mesh)
    expect(mesh.visible).toBe(false)
  })

  // 3. Mesh straddling the frustum boundary.
  it('includes a mesh whose AABB partially overlaps the near frustum plane', () => {
    // Box spans z = [8, 12], camera near plane is at z = 10 - 0.5 = 9.5 (approx).
    // Definitely intersects.
    const mesh = makeMesh(new THREE.Box3(
      new THREE.Vector3(-0.5, -0.5, 8),
      new THREE.Vector3( 0.5,  0.5, 12),
    ))
    const result = cullByFrustum([mesh], camera)
    expect(result).toContain(mesh)
    expect(mesh.visible).toBe(true)
  })

  // 4. Empty mesh list.
  it('returns an empty array for an empty mesh list', () => {
    const result = cullByFrustum([], camera)
    expect(result).toEqual([])
  })

  // 5. Missing bounding box → auto-computed via computeBoundingBox() fallback.
  it('auto-computes a missing bounding box and passes the mesh through', () => {
    // Build a real BufferGeometry with vertex data so computeBoundingBox works.
    const positions = new Float32Array([
      -0.1, -0.1, -0.1,
       0.1, -0.1, -0.1,
       0.0,  0.1, -0.1,
    ])
    const geom = new THREE.BufferGeometry()
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    // Deliberately leave geom.boundingBox null — the helper should call
    // computeBoundingBox() and cache the result.

    const mesh = {
      geometry: geom,
      matrixWorld: new THREE.Matrix4(),
      _kerf_userVisible: undefined,
      visible: true,
      updateWorldMatrix: () => {},
    }

    expect(geom.boundingBox).toBeNull()   // confirm it's absent before call

    const result = cullByFrustum([mesh], camera)

    // After the call the bounding box must be present.
    expect(geom.boundingBox).not.toBeNull()
    // The triangle is at z=-0.1, inside the frustum.
    expect(result).toContain(mesh)
    expect(mesh.visible).toBe(true)
  })

  // Bonus: setUserVisible correctly marks a mesh as hidden by user.
  it('does not un-hide a mesh that is user-hidden via setUserVisible', () => {
    const mesh = makeMesh(new THREE.Box3(
      new THREE.Vector3(-0.1, -0.1, -0.1),
      new THREE.Vector3( 0.1,  0.1,  0.1),
    ))
    setUserVisible(mesh, false)   // user explicitly hid this mesh

    const result = cullByFrustum([mesh], camera)
    expect(result).not.toContain(mesh)
    expect(mesh.visible).toBe(false)
  })
})
