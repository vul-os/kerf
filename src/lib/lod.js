// lod.js — LOD pipeline for the Kerf 3D viewport.
//
// Two responsibilities:
//
//   1. Proxy generation (decimation):
//      `buildLODProxy(geometry)` — given a Three.js BufferGeometry, produce a
//      coarse-mesh proxy at ~10 % of the original triangle budget using a pure-JS
//      quadric-edge-collapse decimation.  Returns a new BufferGeometry.
//
//   2. LOD selection (angular-size threshold):
//      `selectLOD(worldBBox, camera, options)` — given a part's world-space
//      bounding box and the active camera, return `'full'` or `'proxy'` based on
//      the part's angular size in the current view.
//
// Design goals:
//   - No WebGL context required: all heavy maths is pure-JS (or Three math).
//   - Stable public API with named constants so callers can adjust the knobs.
//   - Unit-testable without a canvas / DOM (mock Three.js in tests).
//
// Constants
// ---------
//   LOD_ANGULAR_THRESHOLD  (radians) — parts whose angular size is below this
//     value are rendered as proxy meshes.  Default: 0.02 rad (~1.15°).
//   LOD_PROXY_RATIO        — target fraction of original triangles kept in the
//     proxy.  Default: 0.10 (10 %).
//   LOD_THRESHOLD_COUNT    — fallback: above this many visible components, all
//     subsequent ones are forced to proxy regardless of angular size.  Matches
//     assembly.js LOD_THRESHOLD.

import * as THREE from 'three'

// ---------------------------------------------------------------------------
// Public constants
// ---------------------------------------------------------------------------

/** Angular-size threshold in radians below which a proxy mesh is shown. */
export const LOD_ANGULAR_THRESHOLD = 0.02   // ~1.15°

/** Target triangle fraction for the proxy mesh (10 % of original). */
export const LOD_PROXY_RATIO = 0.10

/**
 * Fallback count threshold: any component at visible index >= this value is
 * forced to proxy regardless of angular size.  Must stay in sync with
 * assembly.js LOD_THRESHOLD.
 */
export const LOD_THRESHOLD_COUNT = 500

// ---------------------------------------------------------------------------
// Decimation helpers (quadric-edge-collapse, pure JS)
// ---------------------------------------------------------------------------

/**
 * Compute a 4×4 quadric error matrix (as a flat 10-element symmetric tensor
 * stored as [a,b,c,d, e,f,g, h,i, j] = upper triangle of the 4×4 outer
 * product p·pᵀ of the plane equation p=[A,B,C,D]).
 *
 * @private
 */
function _planeQuadric(A, B, C, D) {
  return [
    A*A, A*B, A*C, A*D,
         B*B, B*C, B*D,
              C*C, C*D,
                   D*D,
  ]
}

function _qAdd(q1, q2) {
  return q1.map((v, i) => v + q2[i])
}

/**
 * QEM error for vertex position [x,y,z] against quadric q.
 * vᵀ Q v  (simplified for symmetric 4×4).
 * @private
 */
function _qError(q, x, y, z) {
  // Quadric stored as upper-triangle of 4x4:
  // [ q[0] q[1] q[2] q[3] ]
  // [ q[1] q[4] q[5] q[6] ]
  // [ q[2] q[5] q[7] q[8] ]
  // [ q[3] q[6] q[8] q[9] ]
  const v = [x, y, z, 1]
  // Qv
  const Qv = [
    q[0]*v[0] + q[1]*v[1] + q[2]*v[2] + q[3]*v[3],
    q[1]*v[0] + q[4]*v[1] + q[5]*v[2] + q[6]*v[3],
    q[2]*v[0] + q[5]*v[1] + q[7]*v[2] + q[8]*v[3],
    q[3]*v[0] + q[6]*v[1] + q[8]*v[2] + q[9]*v[3],
  ]
  return v[0]*Qv[0] + v[1]*Qv[1] + v[2]*Qv[2] + v[3]*Qv[3]
}

/**
 * Optimal collapse point: midpoint of the two vertices (simplified; a full
 * solution requires a 3×3 linear solve which is overkill for the LOD proxy).
 * @private
 */
function _collapsePoint(verts, a, b) {
  return [
    (verts[3*a]   + verts[3*b])   * 0.5,
    (verts[3*a+1] + verts[3*b+1]) * 0.5,
    (verts[3*a+2] + verts[3*b+2]) * 0.5,
  ]
}

/**
 * Pure-JS quadric edge-collapse decimation.
 *
 * Input/output use Three.js BufferGeometry conventions:
 *   - `position` attribute as flat Float32Array [x0,y0,z0, x1,y1,z1, ...]
 *   - `index` attribute (or non-indexed) as flat Uint32Array triangle list
 *
 * For performance, this is an O(N·k) greedy implementation (rebuild candidates
 * each iteration) suitable for meshes up to ~50 k triangles.  The QEM error is
 * a proxy; accuracy is acceptable for LOD proxies which are shown at low angular
 * sizes and never in close-up.
 *
 * @param {Float32Array} posArr  Flat [x,y,z,...] position buffer.
 * @param {Uint32Array}  idxArr  Flat [a,b,c,...] index buffer (triangle list).
 * @param {number}       targetRatio  Target fraction of triangles to keep.
 * @returns {{ positions: Float32Array, indices: Uint32Array, originalCount: number, finalCount: number }}
 */
export function decimateBufferGeometry(posArr, idxArr, targetRatio = LOD_PROXY_RATIO) {
  const originalCount = idxArr.length / 3

  // Copy to mutable arrays.
  const verts = Float32Array.from(posArr)      // [x,y,z,...]
  const faces = Array.from({ length: originalCount }, (_, i) => [
    idxArr[3*i], idxArr[3*i+1], idxArr[3*i+2],
  ])
  const nVerts = verts.length / 3
  const activeVerts = new Uint8Array(nVerts).fill(1)
  const activeFaces = new Uint8Array(originalCount).fill(1)

  const targetFaces = Math.max(1, Math.round(originalCount * targetRatio))

  if (originalCount <= targetFaces) {
    return { positions: posArr, indices: idxArr, originalCount, finalCount: originalCount }
  }

  // Build per-vertex quadrics from face planes.
  const Q = Array.from({ length: nVerts }, () => new Array(10).fill(0))
  for (let fi = 0; fi < originalCount; fi++) {
    const [ia, ib, ic] = faces[fi]
    const ax = verts[3*ia], ay = verts[3*ia+1], az = verts[3*ia+2]
    const bx = verts[3*ib], by = verts[3*ib+1], bz = verts[3*ib+2]
    const cx = verts[3*ic], cy = verts[3*ic+1], cz = verts[3*ic+2]
    // Face normal via cross product.
    const ex = bx-ax, ey = by-ay, ez = bz-az
    const fx = cx-ax, fy = cy-ay, fz = cz-az
    const nx = ey*fz - ez*fy
    const ny = ez*fx - ex*fz
    const nz = ex*fy - ey*fx
    const len = Math.sqrt(nx*nx + ny*ny + nz*nz)
    if (len < 1e-12) continue
    const A = nx/len, B = ny/len, C = nz/len
    const D = -(A*ax + B*ay + C*az)
    const q = _planeQuadric(A, B, C, D)
    Q[ia] = _qAdd(Q[ia], q)
    Q[ib] = _qAdd(Q[ib], q)
    Q[ic] = _qAdd(Q[ic], q)
  }

  // Build vert → face adjacency.
  const vertFaces = Array.from({ length: nVerts }, () => new Set())
  for (let fi = 0; fi < originalCount; fi++) {
    for (const vi of faces[fi]) vertFaces[vi].add(fi)
  }

  let nActive = originalCount

  // Greedy collapse loop.
  const MAX_ITERS = (originalCount - targetFaces) * 4
  for (let iter = 0; iter < MAX_ITERS && nActive > targetFaces; iter++) {
    // Find cheapest edge.
    let bestErr = Infinity, bestA = -1, bestB = -1

    // Collect unique edges from active faces.
    const seenEdges = new Set()
    for (let fi = 0; fi < originalCount; fi++) {
      if (!activeFaces[fi]) continue
      const [a, b, c] = faces[fi]
      for (const [u, v] of [[a, b], [b, c], [c, a]]) {
        const key = u < v ? (u * 1_000_000 + v) : (v * 1_000_000 + u)
        if (seenEdges.has(key)) continue
        seenEdges.add(key)
        const Qc = _qAdd(Q[u], Q[v])
        const [mx, my, mz] = _collapsePoint(verts, u, v)
        const err = _qError(Qc, mx, my, mz)
        if (err < bestErr) { bestErr = err; bestA = u; bestB = v }
      }
    }

    if (bestA < 0) break

    // Collapse bestB into bestA.
    const Qc = _qAdd(Q[bestA], Q[bestB])
    const [mx, my, mz] = _collapsePoint(verts, bestA, bestB)
    verts[3*bestA]   = mx; verts[3*bestA+1] = my; verts[3*bestA+2] = mz
    Q[bestA] = Qc
    activeVerts[bestB] = 0

    for (const fi of Array.from(vertFaces[bestB])) {
      if (!activeFaces[fi]) continue
      const f = faces[fi]
      const newF = f.map(v => v === bestB ? bestA : v)
      if (new Set(newF).size < 3) {
        activeFaces[fi] = 0
        nActive--
        for (const vi of f) vertFaces[vi].delete(fi)
      } else {
        faces[fi] = newF
        vertFaces[bestA].add(fi)
        vertFaces[bestB].delete(fi)
        for (const vi of newF) vertFaces[vi].add(fi)
      }
    }
  }

  // Compact vertices.
  const remap = new Int32Array(nVerts).fill(-1)
  const newVerts = []
  let nextIdx = 0
  for (let i = 0; i < nVerts; i++) {
    if (!activeVerts[i]) continue
    remap[i] = nextIdx++
    newVerts.push(verts[3*i], verts[3*i+1], verts[3*i+2])
  }

  // Compact faces.
  const newIndices = []
  let finalCount = 0
  for (let fi = 0; fi < originalCount; fi++) {
    if (!activeFaces[fi]) continue
    const f = faces[fi]
    const ia = remap[f[0]], ib = remap[f[1]], ic = remap[f[2]]
    if (ia < 0 || ib < 0 || ic < 0) continue
    newIndices.push(ia, ib, ic)
    finalCount++
  }

  return {
    positions: new Float32Array(newVerts),
    indices:   new Uint32Array(newIndices),
    originalCount,
    finalCount,
  }
}

/**
 * Build an LOD proxy BufferGeometry from an existing Three.js BufferGeometry.
 *
 * Returns a new BufferGeometry with ~10 % of the original triangle budget.
 * The geometry's bounding box is computed immediately so callers can use it
 * for angular-size queries.
 *
 * @param {THREE.BufferGeometry} geometry  Source geometry (must have position + index).
 * @param {number} [ratio=LOD_PROXY_RATIO]  Target face retention fraction.
 * @returns {THREE.BufferGeometry}          Decimated proxy geometry.
 */
export function buildLODProxy(geometry, ratio = LOD_PROXY_RATIO) {
  const posAttr = geometry.getAttribute('position')
  const idxAttr = geometry.getIndex()

  if (!posAttr) {
    // Nothing to decimate; return a clone.
    return geometry.clone()
  }

  // Ensure we have an index buffer.
  let idxArr
  if (idxAttr) {
    idxArr = new Uint32Array(idxAttr.array)
  } else {
    // Non-indexed: generate sequential indices.
    const n = posAttr.count
    idxArr = new Uint32Array(n)
    for (let i = 0; i < n; i++) idxArr[i] = i
  }

  const posArr = new Float32Array(posAttr.array)
  const { positions, indices } = decimateBufferGeometry(posArr, idxArr, ratio)

  const proxyGeom = new THREE.BufferGeometry()
  proxyGeom.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  proxyGeom.setIndex(new THREE.BufferAttribute(indices, 1))
  proxyGeom.computeBoundingBox()
  proxyGeom.computeBoundingSphere()

  return proxyGeom
}

// ---------------------------------------------------------------------------
// Angular-size LOD selection
// ---------------------------------------------------------------------------

const _tmpSphere  = new THREE.Sphere()
const _tmpVec     = new THREE.Vector3()

/**
 * Compute the angular size (radians) of a world-space bounding box from the
 * camera's current position.
 *
 * The angular size is 2·atan(r / d) where r is the bounding sphere radius and
 * d is the distance from the camera to the sphere centre.
 *
 * @param {THREE.Box3}    worldBBox  World-space AABB of the part.
 * @param {THREE.Camera}  camera     Active camera.
 * @returns {number}                 Angular size in radians.
 */
export function angularSize(worldBBox, camera) {
  if (!worldBBox || worldBBox.isEmpty()) return 0

  worldBBox.getBoundingSphere(_tmpSphere)
  const r = _tmpSphere.radius
  const d = camera.position.distanceTo(_tmpSphere.center)

  if (d <= 0) return Math.PI
  return 2 * Math.atan(r / Math.max(d, 1e-9))
}

/**
 * Decide whether to render a part at full quality or as a proxy.
 *
 * Two independent criteria — proxy is chosen if either triggers:
 *   1. The part's angular size < LOD_ANGULAR_THRESHOLD (too small to see detail).
 *   2. visibleIndex >= LOD_THRESHOLD_COUNT (budget exceeded; late components get proxy).
 *
 * @param {THREE.Box3}   worldBBox      World-space AABB of the part.
 * @param {THREE.Camera} camera         Active camera.
 * @param {object}       [opts]
 * @param {number}       [opts.visibleIndex=0]         0-based position in visible list.
 * @param {number}       [opts.angularThreshold=LOD_ANGULAR_THRESHOLD]
 * @param {number}       [opts.countThreshold=LOD_THRESHOLD_COUNT]
 * @returns {'full'|'proxy'}
 */
export function selectLOD(worldBBox, camera, opts = {}) {
  const {
    visibleIndex      = 0,
    angularThreshold  = LOD_ANGULAR_THRESHOLD,
    countThreshold    = LOD_THRESHOLD_COUNT,
  } = opts

  // Count threshold: always proxy above budget.
  if (visibleIndex >= countThreshold) return 'proxy'

  // Angular-size threshold: proxy for distant/small parts.
  const ang = angularSize(worldBBox, camera)
  if (ang < angularThreshold) return 'proxy'

  return 'full'
}
