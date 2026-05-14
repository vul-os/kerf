/**
 * subdToBufferGeometry.js — Convert .subd and .mesh documents to
 * THREE.BufferGeometry for the 3D viewport.
 *
 * Exports two layers:
 *  - Pure helpers (subdToBufferGeometryArgs, meshDocToBufferGeometryArgs):
 *    no Three.js dependency — unit-testable in Node/Vitest without a WebGL
 *    context, and usable as adapters when only typed arrays are needed.
 *  - Geometry builders (subdToBufferGeometry, meshDocToBufferGeometry):
 *    import THREE and return a ready-to-use BufferGeometry.
 */

import * as THREE from 'three'
import { subdivide } from './subd.js'

// ── Pure helpers (no THREE dep; THREE is imported at the top but not used
//   in these functions — they return plain typed arrays) ────────────────────────

/**
 * Convert a subd document into flat typed arrays suitable for BufferGeometry
 * attributes.  Calls `subdivide()` if `doc.display_mesh` is not yet populated.
 *
 * @param {object} doc - Subd document (may or may not have display_mesh).
 * @returns {{ positions: Float32Array, indices: Uint32Array }}
 */
export function subdToBufferGeometryArgs(doc) {
  const resolved = doc.display_mesh ? doc : subdivide(doc)
  const dm = resolved.display_mesh

  const verts = dm.vertices   // [[x,y,z], ...]
  const idxArr = dm.indices   // [i0, i1, i2, ...]

  const positions = new Float32Array(verts.length * 3)
  for (let i = 0; i < verts.length; i++) {
    positions[i * 3]     = verts[i][0]
    positions[i * 3 + 1] = verts[i][1]
    positions[i * 3 + 2] = verts[i][2]
  }

  const indices = new Uint32Array(idxArr.length)
  for (let i = 0; i < idxArr.length; i++) indices[i] = idxArr[i]

  return { positions, indices }
}

/**
 * Convert a .mesh document into flat typed arrays for BufferGeometry.
 *
 * @param {object} meshDoc
 * @param {Array<[number,number,number]>} meshDoc.vertices
 * @param {number[]} meshDoc.indices
 * @param {Array<[number,number,number]>} [meshDoc.normals]
 * @returns {{ positions: Float32Array, indices: Uint32Array, normals?: Float32Array }}
 */
export function meshDocToBufferGeometryArgs(meshDoc) {
  const { vertices, indices: idxArr, normals: normalsIn } = meshDoc

  const positions = new Float32Array(vertices.length * 3)
  for (let i = 0; i < vertices.length; i++) {
    positions[i * 3]     = vertices[i][0]
    positions[i * 3 + 1] = vertices[i][1]
    positions[i * 3 + 2] = vertices[i][2]
  }

  const indices = new Uint32Array(idxArr.length)
  for (let i = 0; i < idxArr.length; i++) indices[i] = idxArr[i]

  let normals
  if (normalsIn && normalsIn.length === vertices.length) {
    normals = new Float32Array(normalsIn.length * 3)
    for (let i = 0; i < normalsIn.length; i++) {
      normals[i * 3]     = normalsIn[i][0]
      normals[i * 3 + 1] = normalsIn[i][1]
      normals[i * 3 + 2] = normalsIn[i][2]
    }
  }

  return normals ? { positions, indices, normals } : { positions, indices }
}

// ── Three.js geometry builders ─────────────────────────────────────────────────

/**
 * Build a THREE.BufferGeometry from a .subd document.
 * Uses subdToBufferGeometryArgs internally; normals are computed by Three.js.
 *
 * @param {object} subdDoc
 * @returns {THREE.BufferGeometry}
 */
export function subdToBufferGeometry(subdDoc) {
  const { positions, indices } = subdToBufferGeometryArgs(subdDoc)
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  g.setIndex(new THREE.BufferAttribute(indices, 1))
  g.computeVertexNormals()
  g.computeBoundingBox()
  g.computeBoundingSphere()
  return g
}

/**
 * Build a THREE.BufferGeometry from a .mesh document.
 * Uses provided normals when present; falls back to computeVertexNormals().
 *
 * @param {object} meshDoc
 * @returns {THREE.BufferGeometry}
 */
export function meshDocToBufferGeometry(meshDoc) {
  const { positions, indices, normals } = meshDocToBufferGeometryArgs(meshDoc)
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  g.setIndex(new THREE.BufferAttribute(indices, 1))
  if (normals) {
    g.setAttribute('normal', new THREE.BufferAttribute(normals, 3))
  } else {
    g.computeVertexNormals()
  }
  g.computeBoundingBox()
  g.computeBoundingSphere()
  return g
}
