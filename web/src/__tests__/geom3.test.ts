// geom3.test.js — coverage for the JSCAD Geom3 → Three.BufferGeometry
// converter and its companions (applyMatrixToGeom, combinedBoundingBox).
//
// All math is done in-process; we hand-build minimal Geom3-shaped polygon
// soup as plain JS objects (`{ polygons: [{ vertices: [[x,y,z], ...] }] }`).

import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import {
  geom3ToBufferGeometry,
  applyMatrixToGeom,
  combinedBoundingBox,
} from '../lib/geom3.js'
import type { Geom3 } from '@/types'

// A unit-square polygon on z=0 winding CCW (normal +Z).
// Minimal Geom3-shaped polygon soup — only `polygons` is exercised.
const unitSquareXY = {
  polygons: [
    {
      vertices: [
        [0, 0, 0],
        [1, 0, 0],
        [1, 1, 0],
        [0, 1, 0],
      ],
    },
  ],
} as unknown as Geom3

describe('geom3ToBufferGeometry', () => {
  it('returns a BufferGeometry with position+normal attributes', () => {
    const g = geom3ToBufferGeometry(unitSquareXY)
    expect(g.isBufferGeometry).toBe(true)
    expect(g.getAttribute('position')).toBeTruthy()
    expect(g.getAttribute('normal')).toBeTruthy()
  })

  it('fan-triangulates a quad into 2 triangles (6 vertices)', () => {
    const g = geom3ToBufferGeometry(unitSquareXY)
    const pos = g.getAttribute('position')
    expect(pos.count).toBe(6)
  })

  it('emits per-face flat normals pointing +Z for a CCW square in the XY plane', () => {
    const g = geom3ToBufferGeometry(unitSquareXY)
    const n = g.getAttribute('normal')
    // All 6 vertices share the same flat normal.
    for (let i = 0; i < n.count; i++) {
      expect(n.getX(i)).toBeCloseTo(0, 10)
      expect(n.getY(i)).toBeCloseTo(0, 10)
      expect(n.getZ(i)).toBeCloseTo(1, 10)
    }
  })

  it('skips degenerate polygons (<3 vertices)', () => {
    const degenerate = {
      polygons: [
        { vertices: [[0, 0, 0], [1, 0, 0]] }, // only 2 verts
        { vertices: [[0, 0, 0], [1, 0, 0], [1, 1, 0]] }, // proper triangle
      ],
    } as unknown as Geom3
    const g = geom3ToBufferGeometry(degenerate)
    expect(g.getAttribute('position').count).toBe(3)
  })

  it('handles empty/missing polygons array safely', () => {
    expect(geom3ToBufferGeometry(null).getAttribute('position').count).toBe(0)
    expect(geom3ToBufferGeometry({} as unknown as Geom3).getAttribute('position').count).toBe(0)
    expect(geom3ToBufferGeometry({ polygons: [] } as unknown as Geom3).getAttribute('position').count).toBe(0)
  })

  it('computes a bounding box that hugs the input', () => {
    const g = geom3ToBufferGeometry(unitSquareXY)
    expect(g.boundingBox.min.x).toBe(0)
    expect(g.boundingBox.min.y).toBe(0)
    expect(g.boundingBox.max.x).toBe(1)
    expect(g.boundingBox.max.y).toBe(1)
  })
})

describe('applyMatrixToGeom', () => {
  it('returns null for null input', () => {
    expect(applyMatrixToGeom(null, new THREE.Matrix4())).toBeNull()
  })

  it('clones a BufferGeometry input rather than mutating it', () => {
    const src = geom3ToBufferGeometry(unitSquareXY)
    const m = new THREE.Matrix4().makeTranslation(10, 0, 0)
    const out = applyMatrixToGeom(src, m)
    expect(out).not.toBe(src)
    // Source untouched.
    expect(src.boundingBox.max.x).toBe(1)
    // Output translated.
    expect(out.boundingBox.max.x).toBeCloseTo(11, 10)
  })

  it('converts Geom3 input to BufferGeometry and applies the transform', () => {
    const m = new THREE.Matrix4().makeTranslation(5, 5, 0)
    const out = applyMatrixToGeom(unitSquareXY, m)
    expect(out.isBufferGeometry).toBe(true)
    expect(out.boundingBox.min.x).toBeCloseTo(5, 10)
    expect(out.boundingBox.max.y).toBeCloseTo(6, 10)
  })

  it('skips the matrix step when the matrix is identity', () => {
    const out = applyMatrixToGeom(unitSquareXY, new THREE.Matrix4())
    // Identity → output positions match input positions exactly.
    expect(out.boundingBox.min.x).toBe(0)
    expect(out.boundingBox.max.x).toBe(1)
  })
})

describe('combinedBoundingBox', () => {
  it('returns null when the entries list is empty or all geometries have no box', () => {
    expect(combinedBoundingBox([])).toBeNull()
    expect(combinedBoundingBox([{ id: 'x', geometry: null }])).toBeNull()
  })

  it('unions multiple boxes correctly', () => {
    const a = geom3ToBufferGeometry(unitSquareXY)
    const b = applyMatrixToGeom(unitSquareXY, new THREE.Matrix4().makeTranslation(10, 0, 0))
    const box = combinedBoundingBox([
      { id: 'a', geometry: a },
      { id: 'b', geometry: b },
    ])
    expect(box).not.toBeNull()
    expect(box.min.x).toBe(0)
    expect(box.max.x).toBeCloseTo(11, 10)
  })

  it('ignores entries with null geometry', () => {
    const a = geom3ToBufferGeometry(unitSquareXY)
    const box = combinedBoundingBox([
      { id: 'null', geometry: null },
      { id: 'a', geometry: a },
    ])
    expect(box.max.x).toBe(1)
  })
})
