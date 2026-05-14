import { describe, it, expect } from 'vitest'
import {
  subdToBufferGeometryArgs,
  meshDocToBufferGeometryArgs,
  subdToBufferGeometry,
  meshDocToBufferGeometry,
} from './subdToBufferGeometry.js'
import { cubeMesh, subdivide, defaultSubD } from './subd.js'

// ── fixtures ───────────────────────────────────────────────────────────────────

function makeCubeSubdDoc(level = 1) {
  return {
    version: 1,
    control_mesh: cubeMesh(),
    subdivision_level: level,
    display_mesh: null,
  }
}

function makeSimpleMeshDoc(withNormals = false) {
  // A single tetrahedron — 4 vertices, 4 triangular faces.
  const vertices = [
    [0, 0, 0],
    [1, 0, 0],
    [0.5, 1, 0],
    [0.5, 0.5, 1],
  ]
  const indices = [0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3]
  const normals = withNormals
    ? vertices.map(() => [0, 0, 1])   // dummy normals — just for testing presence
    : undefined
  return withNormals ? { vertices, indices, normals } : { vertices, indices }
}

// ── subdToBufferGeometryArgs ───────────────────────────────────────────────────

describe('subdToBufferGeometryArgs', () => {
  it('returns Float32Array for positions', () => {
    const doc = makeCubeSubdDoc(1)
    const { positions } = subdToBufferGeometryArgs(doc)
    expect(positions).toBeInstanceOf(Float32Array)
  })

  it('returns Uint32Array for indices', () => {
    const doc = makeCubeSubdDoc(1)
    const { indices } = subdToBufferGeometryArgs(doc)
    expect(indices).toBeInstanceOf(Uint32Array)
  })

  it('positions length is 3 × vertex count', () => {
    const doc = makeCubeSubdDoc(1)
    const subdivided = subdivide(doc)
    const vCount = subdivided.display_mesh.vertices.length
    const { positions } = subdToBufferGeometryArgs(subdivided)
    expect(positions.length).toBe(vCount * 3)
  })

  it('indices length matches display_mesh.indices length', () => {
    const doc = makeCubeSubdDoc(1)
    const subdivided = subdivide(doc)
    const { indices } = subdToBufferGeometryArgs(subdivided)
    expect(indices.length).toBe(subdivided.display_mesh.indices.length)
  })

  it('calls subdivide() automatically when display_mesh is absent', () => {
    const doc = makeCubeSubdDoc(1)
    // display_mesh is null — should not throw
    expect(() => subdToBufferGeometryArgs(doc)).not.toThrow()
    const { positions, indices } = subdToBufferGeometryArgs(doc)
    expect(positions.length).toBeGreaterThan(0)
    expect(indices.length).toBeGreaterThan(0)
  })

  it('index values are in bounds of positions vertex count', () => {
    const doc = makeCubeSubdDoc(1)
    const { positions, indices } = subdToBufferGeometryArgs(doc)
    const vCount = positions.length / 3
    for (const idx of indices) {
      expect(idx).toBeGreaterThanOrEqual(0)
      expect(idx).toBeLessThan(vCount)
    }
  })

  it('triangle count is a multiple of 3', () => {
    const doc = makeCubeSubdDoc(2)
    const { indices } = subdToBufferGeometryArgs(doc)
    expect(indices.length % 3).toBe(0)
  })
})

// ── meshDocToBufferGeometryArgs ────────────────────────────────────────────────

describe('meshDocToBufferGeometryArgs', () => {
  it('positions is Float32Array with correct length', () => {
    const meshDoc = makeSimpleMeshDoc()
    const { positions } = meshDocToBufferGeometryArgs(meshDoc)
    expect(positions).toBeInstanceOf(Float32Array)
    expect(positions.length).toBe(meshDoc.vertices.length * 3)
  })

  it('indices is Uint32Array with correct length', () => {
    const meshDoc = makeSimpleMeshDoc()
    const { indices } = meshDocToBufferGeometryArgs(meshDoc)
    expect(indices).toBeInstanceOf(Uint32Array)
    expect(indices.length).toBe(meshDoc.indices.length)
  })

  it('normals absent when meshDoc has no normals', () => {
    const meshDoc = makeSimpleMeshDoc(false)
    const result = meshDocToBufferGeometryArgs(meshDoc)
    expect(result.normals).toBeUndefined()
  })

  it('normals present and correct length when meshDoc provides them', () => {
    const meshDoc = makeSimpleMeshDoc(true)
    const { normals } = meshDocToBufferGeometryArgs(meshDoc)
    expect(normals).toBeInstanceOf(Float32Array)
    expect(normals.length).toBe(meshDoc.vertices.length * 3)
  })

  it('index values are in range', () => {
    const meshDoc = makeSimpleMeshDoc()
    const { indices } = meshDocToBufferGeometryArgs(meshDoc)
    const vCount = meshDoc.vertices.length
    for (const i of indices) {
      expect(i).toBeGreaterThanOrEqual(0)
      expect(i).toBeLessThan(vCount)
    }
  })

  it('position values match input vertices', () => {
    const meshDoc = makeSimpleMeshDoc()
    const { positions } = meshDocToBufferGeometryArgs(meshDoc)
    for (let i = 0; i < meshDoc.vertices.length; i++) {
      expect(positions[i * 3]).toBeCloseTo(meshDoc.vertices[i][0])
      expect(positions[i * 3 + 1]).toBeCloseTo(meshDoc.vertices[i][1])
      expect(positions[i * 3 + 2]).toBeCloseTo(meshDoc.vertices[i][2])
    }
  })
})

// ── subdToBufferGeometry (THREE.js) ───────────────────────────────────────────

describe('subdToBufferGeometry', () => {
  it('returns an object with isBufferGeometry=true', () => {
    const doc = makeCubeSubdDoc(1)
    const g = subdToBufferGeometry(doc)
    expect(g.isBufferGeometry).toBe(true)
  })

  it('has a position attribute', () => {
    const doc = makeCubeSubdDoc(1)
    const g = subdToBufferGeometry(doc)
    expect(g.getAttribute('position')).toBeTruthy()
  })

  it('has a normal attribute (computed)', () => {
    const doc = makeCubeSubdDoc(1)
    const g = subdToBufferGeometry(doc)
    expect(g.getAttribute('normal')).toBeTruthy()
  })

  it('has a boundingBox after build', () => {
    const doc = makeCubeSubdDoc(1)
    const g = subdToBufferGeometry(doc)
    expect(g.boundingBox).not.toBeNull()
  })
})

// ── meshDocToBufferGeometry (THREE.js) ────────────────────────────────────────

describe('meshDocToBufferGeometry', () => {
  it('returns an object with isBufferGeometry=true', () => {
    const meshDoc = makeSimpleMeshDoc()
    const g = meshDocToBufferGeometry(meshDoc)
    expect(g.isBufferGeometry).toBe(true)
  })

  it('has position attribute with correct item count', () => {
    const meshDoc = makeSimpleMeshDoc()
    const g = meshDocToBufferGeometry(meshDoc)
    const pos = g.getAttribute('position')
    expect(pos.count).toBe(meshDoc.vertices.length)
  })

  it('uses provided normals when present', () => {
    const meshDoc = makeSimpleMeshDoc(true)
    const g = meshDocToBufferGeometry(meshDoc)
    const nrm = g.getAttribute('normal')
    expect(nrm).toBeTruthy()
    expect(nrm.count).toBe(meshDoc.vertices.length)
  })

  it('computes normals when meshDoc has none', () => {
    const meshDoc = makeSimpleMeshDoc(false)
    const g = meshDocToBufferGeometry(meshDoc)
    // computeVertexNormals() was called — normal attribute must exist
    expect(g.getAttribute('normal')).toBeTruthy()
  })

  it('has a valid boundingBox', () => {
    const meshDoc = makeSimpleMeshDoc()
    const g = meshDocToBufferGeometry(meshDoc)
    expect(g.boundingBox).not.toBeNull()
    expect(isFinite(g.boundingBox.min.x)).toBe(true)
  })
})
