// topology.test.js — coverage for the JSCAD-side topology derivation +
// the Map-shaped lazy wrapper + the small feature-snap helpers.
//
// We hand-build minimal Geom3-shaped polygon soup as plain JS objects and
// feed it through the public API:
//   * getTopology(part)       — clusters polygons by plane → faces; walks
//     edges → BREP edges; collects vertices on real edges.
//   * getTopologyLazy(parts)  — Map-shaped wrapper that defers per-part
//     topology derivation until a `.get()`/iteration reaches it.
//   * findFeature(top, kind, id)
//   * featureSnapPoint(kind, feature) — face → centroid, edge → midpoint,
//     vertex → position.
//
// We deliberately stay on the JSCAD path (plain `{ polygons }` objects). The
// BufferGeometry path uses three's EdgesGeometry which is exercised
// implicitly elsewhere; what we want to lock in here is the pure plane-key
// clustering / edge-classification logic.

import * as doubles from '../test-support/threeDoubles.js'
import { describe, it, expect } from 'vitest'
import {
  getTopology,
  getTopologyLazy,
  findFeature,
  featureSnapPoint,
} from '../lib/topology.js'

// -- helpers ---------------------------------------------------------------

// Build a Geom3 with one polygon per `verts` entry. Via the shared factory so
// the result carries `transforms` — a bare {polygons} literal is not a Geom3,
// it is one that throws the first time anything transforms it.
const makeGeom = (polys: number[][][]) => doubles.geom3FromTriangles(polys)

// Unit cube centred at the origin. Six quad faces, axis-aligned. We use this
// as the canonical "real solid" — it should yield 6 face clusters, 12 edges,
// 8 vertices.
function unitCube() {
  // 8 corners
  const v = [
    [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], // bottom (z=0)
    [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1], // top    (z=1)
  ]
  return makeGeom([
    // bottom (-Z)
    [v[0], v[3], v[2], v[1]],
    // top    (+Z)
    [v[4], v[5], v[6], v[7]],
    // front  (-Y)
    [v[0], v[1], v[5], v[4]],
    // back   (+Y)
    [v[3], v[7], v[6], v[2]],
    // left   (-X)
    [v[0], v[4], v[7], v[3]],
    // right  (+X)
    [v[1], v[2], v[6], v[5]],
  ])
}

// -- getTopology: empty / degenerate --------------------------------------

describe('getTopology — defensive cases', () => {
  it('returns empty topology for null / missing geom', () => {
    expect(getTopology(null)).toEqual({ faces: [], edges: [], vertices: [] })
    // Intentionally missing `geom` to exercise the defensive branch.
    expect(getTopology({} as any)).toEqual({ faces: [], edges: [], vertices: [] })
  })

  it('skips polygons with fewer than 3 vertices', () => {
    const t = getTopology({ geom: makeGeom([[[0, 0, 0], [1, 0, 0]]]) })
    expect(t.faces).toEqual([])
    expect(t.edges).toEqual([])
    expect(t.vertices).toEqual([])
  })
})

// -- getTopology: cube ----------------------------------------------------

describe('getTopology — unit cube', () => {
  const part = { geom: unitCube() }
  const top = getTopology(part)

  it('clusters into 6 planar faces (one per cube side)', () => {
    expect(top.faces).toHaveLength(6)
  })

  it('every face has a non-zero area near 1 (unit cube)', () => {
    for (const f of top.faces) {
      expect(f.area).toBeGreaterThan(0.9)
      expect(f.area).toBeLessThan(1.1)
    }
  })

  it('every face has a centroid inside the unit cube bounds', () => {
    for (const f of top.faces) {
      const [x, y, z] = f.centroid
      expect(x).toBeGreaterThanOrEqual(-1e-6)
      expect(x).toBeLessThanOrEqual(1 + 1e-6)
      expect(y).toBeGreaterThanOrEqual(-1e-6)
      expect(y).toBeLessThanOrEqual(1 + 1e-6)
      expect(z).toBeGreaterThanOrEqual(-1e-6)
      expect(z).toBeLessThanOrEqual(1 + 1e-6)
    }
  })

  it('has 12 BREP edges (one per cube edge), each unit-length', () => {
    expect(top.edges).toHaveLength(12)
    for (const e of top.edges) {
      expect(e.length).toBeCloseTo(1, 5)
      // Cube edges sit between two distinct face clusters.
      expect(e.faceA).toBeTruthy()
      expect(e.faceB).toBeTruthy()
      expect(e.faceA).not.toBe(e.faceB)
    }
  })

  it('has 8 unique vertices, each touching ≥3 faces', () => {
    expect(top.vertices).toHaveLength(8)
    for (const v of top.vertices) {
      expect(v.faces.length).toBeGreaterThanOrEqual(3)
    }
  })

  it('returns the same topology object on a second call (WeakMap cache)', () => {
    const top2 = getTopology(part)
    expect(top2).toBe(top)
  })
})

// -- getTopology: triangulated face (interior edges should be dropped) ----

describe('getTopology — fan-triangulated planar face', () => {
  // Two co-planar triangles forming a quad on z=0. They share one edge that
  // is interior to the same face cluster — it must be dropped from the
  // BREP edge list (no chord across a flat face).
  it('drops interior tessellation edges shared by polygons in the same plane', () => {
    const geom = makeGeom([
      [[0, 0, 0], [2, 0, 0], [2, 2, 0]],
      [[0, 0, 0], [2, 2, 0], [0, 2, 0]],
    ])
    const top = getTopology({ geom })
    // One planar face cluster (both triangles coplanar with z=0).
    expect(top.faces).toHaveLength(1)
    // 4 boundary edges of the quad. The shared diagonal between the two
    // triangles should NOT appear — it's interior to the face cluster.
    // Open mesh so all four are boundary edges with faceB=null.
    expect(top.edges).toHaveLength(4)
    for (const e of top.edges) {
      expect(e.faceB).toBeNull()
    }
  })
})

// -- getTopologyLazy ------------------------------------------------------

describe('getTopologyLazy', () => {
  const partA = { id: 'A', geom: unitCube() }
  const partB = { id: 'B', geom: unitCube() }

  it('exposes Map-shaped get/has/size for the given parts', () => {
    const m = getTopologyLazy([partA, partB])
    expect(m.size).toBe(2)
    expect(m.has('A')).toBe(true)
    expect(m.has('B')).toBe(true)
    expect(m.has('C')).toBe(false)
  })

  it('lazily computes per-part topology on first .get and memoizes it', () => {
    const m = getTopologyLazy([partA])
    const t1 = m.get('A')
    const t2 = m.get('A')
    expect(t1).toBeTruthy()
    expect(t1.faces).toHaveLength(6)
    expect(t2).toBe(t1)
  })

  it('returns null for an unknown part id (no entry in the parts map)', () => {
    const m = getTopologyLazy([partA])
    expect(m.get('does-not-exist')).toBeNull()
  })

  it('is iterable via entries() — yields [id, topology] pairs', () => {
    const m = getTopologyLazy([partA, partB])
    const ids = []
    for (const [id, top] of m) {
      ids.push(id)
      expect(top.faces).toHaveLength(6)
    }
    expect(ids.sort()).toEqual(['A', 'B'])
  })

  it('skips parts that lack an id at construction', () => {
    const m = getTopologyLazy([partA, { geom: unitCube() }, null])
    expect(m.size).toBe(1)
    expect(m.has('A')).toBe(true)
  })
})

// -- findFeature / featureSnapPoint ---------------------------------------

describe('findFeature + featureSnapPoint', () => {
  const top = getTopology({ geom: unitCube() })

  it('findFeature returns null for an unknown topology', () => {
    expect(findFeature(null, 'face', 'face-0')).toBeNull()
  })

  it('findFeature locates a face by id', () => {
    const f = findFeature(top, 'face', top.faces[0].id)
    expect(f).toBe(top.faces[0])
  })

  it('findFeature returns null for an id that does not match', () => {
    expect(findFeature(top, 'edge', 'no-such-edge')).toBeNull()
  })

  it('findFeature returns null for an unknown kind', () => {
    // Intentionally invalid kind to exercise the runtime fallback.
    expect(findFeature(top, 'nonsense' as any, 'whatever')).toBeNull()
  })

  it('featureSnapPoint returns the centroid for a face', () => {
    const f = top.faces[0]
    expect(featureSnapPoint('face', f)).toBe(f.centroid)
  })

  it('featureSnapPoint returns the midpoint for an edge', () => {
    // Build an edge with known endpoints (avoid index churn).
    // Minimal edge fixture (a/b only); TopologyEdge's full type (id, faceA,
    // faceB, length) is beside the point for this midpoint calculation.
    const edge = { a: [0, 0, 0], b: [2, 0, 0] }
    expect(featureSnapPoint('edge', edge as any)).toEqual([1, 0, 0])
  })

  it('featureSnapPoint returns the position for a vertex', () => {
    // Minimal vertex fixture (position only); see edge fixture note above.
    const v = { position: [3, 4, 5] }
    expect(featureSnapPoint('vertex', v as any)).toEqual([3, 4, 5])
  })

  it('featureSnapPoint returns null for a missing feature or unknown kind', () => {
    expect(featureSnapPoint('face', null)).toBeNull()
    // Intentionally invalid kind to exercise the runtime fallback.
    expect(featureSnapPoint('mystery' as any, { whatever: true } as any)).toBeNull()
  })
})
