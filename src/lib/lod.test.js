/**
 * lod.test.js — Vitest unit tests for src/lib/lod.js
 *
 * Tests are headless (no WebGL).  Three.js is mocked to provide minimal
 * geometry / camera / frustum primitives backed by pure-JS math.
 *
 * Coverage:
 *   - decimateBufferGeometry: reduces triangle count to ~10%; bounding box preserved
 *   - buildLODProxy: wraps decimation and returns a new BufferGeometry
 *   - angularSize: correct formula (2·atan(r/d))
 *   - selectLOD: proxy triggered by angular-size threshold
 *   - selectLOD: proxy triggered by count threshold (visibleIndex >= LOD_THRESHOLD_COUNT)
 *   - selectLOD: 'full' when large angular size + below count threshold
 */

import { describe, it, expect, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Three.js mock — must use vi.hoisted so classes are available when vi.mock
// factory is called (vi.mock is hoisted above imports).
// ---------------------------------------------------------------------------

const {
  MockVector3,
  MockSphere,
  MockBox3,
  MockMatrix4,
  MockFrustum,
  MockBufferAttribute,
  MockBufferGeometry,
} = vi.hoisted(() => {
  class MockVector3 {
    constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; return this }
    clone() { return new MockVector3(this.x, this.y, this.z) }
    copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this }
    distanceTo(v) {
      return Math.sqrt((this.x-v.x)**2 + (this.y-v.y)**2 + (this.z-v.z)**2)
    }
    addScaledVector(v, s) {
      this.x += v.x*s; this.y += v.y*s; this.z += v.z*s; return this
    }
    sub(v) { this.x -= v.x; this.y -= v.y; this.z -= v.z; return this }
    multiplyScalar(s) { this.x *= s; this.y *= s; this.z *= s; return this }
    length() { return Math.sqrt(this.x**2 + this.y**2 + this.z**2) }
  }

  class MockSphere {
    constructor() {
      this.center = new MockVector3()
      this.radius = 0
    }
  }

  class MockBox3 {
    constructor() {
      this.min = new MockVector3(Infinity, Infinity, Infinity)
      this.max = new MockVector3(-Infinity, -Infinity, -Infinity)
      this._empty = true
    }
    set(min, max) {
      this.min.copy(min); this.max.copy(max)
      this._empty = false; return this
    }
    isEmpty() { return this._empty }
    getBoundingSphere(target) {
      const cx = (this.min.x + this.max.x) / 2
      const cy = (this.min.y + this.max.y) / 2
      const cz = (this.min.z + this.max.z) / 2
      target.center.set(cx, cy, cz)
      target.radius = Math.sqrt(
        (this.max.x-cx)**2 + (this.max.y-cy)**2 + (this.max.z-cz)**2
      )
      return target
    }
    applyMatrix4(m) {
      const corners = [
        [this.min.x, this.min.y, this.min.z],
        [this.max.x, this.min.y, this.min.z],
        [this.min.x, this.max.y, this.min.z],
        [this.max.x, this.max.y, this.min.z],
        [this.min.x, this.min.y, this.max.z],
        [this.max.x, this.min.y, this.max.z],
        [this.min.x, this.max.y, this.max.z],
        [this.max.x, this.max.y, this.max.z],
      ]
      const e = m.elements
      let minX=Infinity,minY=Infinity,minZ=Infinity
      let maxX=-Infinity,maxY=-Infinity,maxZ=-Infinity
      for (const [x,y,z] of corners) {
        const tx = e[0]*x + e[4]*y + e[8]*z  + e[12]
        const ty = e[1]*x + e[5]*y + e[9]*z  + e[13]
        const tz = e[2]*x + e[6]*y + e[10]*z + e[14]
        if (tx<minX) minX=tx; if (tx>maxX) maxX=tx
        if (ty<minY) minY=ty; if (ty>maxY) maxY=ty
        if (tz<minZ) minZ=tz; if (tz>maxZ) maxZ=tz
      }
      this.min.set(minX, minY, minZ)
      this.max.set(maxX, maxY, maxZ)
      this._empty = false
      return this
    }
  }

  class MockMatrix4 {
    constructor() {
      this.elements = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
    }
    set(n11,n12,n13,n14, n21,n22,n23,n24, n31,n32,n33,n34, n41,n42,n43,n44) {
      const e = this.elements
      e[0]=n11; e[4]=n12; e[8]=n13;  e[12]=n14
      e[1]=n21; e[5]=n22; e[9]=n23;  e[13]=n24
      e[2]=n31; e[6]=n32; e[10]=n33; e[14]=n34
      e[3]=n41; e[7]=n42; e[11]=n43; e[15]=n44
      return this
    }
    multiplyMatrices(a, b) { return this }
  }

  class MockFrustum {
    constructor() {}
    setFromProjectionMatrix() { return this }
    intersectsBox() { return true }
  }

  class MockBufferAttribute {
    constructor(array, itemSize) {
      this.array = array
      this.itemSize = itemSize
      this.count = array.length / itemSize
    }
  }

  class MockBufferGeometry {
    constructor() { this._attrs = {}; this._index = null }
    setAttribute(name, attr) { this._attrs[name] = attr; return this }
    getAttribute(name) { return this._attrs[name] ?? null }
    setIndex(attr) { this._index = attr; return this }
    getIndex() { return this._index }
    computeBoundingBox() { this.boundingBox = new MockBox3() }
    computeBoundingSphere() { this.boundingSphere = new MockSphere() }
    clone() {
      const g = new MockBufferGeometry()
      for (const [k, v] of Object.entries(this._attrs)) g._attrs[k] = v
      g._index = this._index
      return g
    }
  }

  return { MockVector3, MockSphere, MockBox3, MockMatrix4, MockFrustum, MockBufferAttribute, MockBufferGeometry }
})

vi.mock('three', () => ({
  Vector3:         MockVector3,
  Sphere:          MockSphere,
  Box3:            MockBox3,
  Matrix4:         MockMatrix4,
  Frustum:         MockFrustum,
  BufferGeometry:  MockBufferGeometry,
  BufferAttribute: MockBufferAttribute,
}))

// Import AFTER mock registration.
import {
  decimateBufferGeometry,
  buildLODProxy,
  angularSize,
  selectLOD,
  LOD_ANGULAR_THRESHOLD,
  LOD_PROXY_RATIO,
  LOD_THRESHOLD_COUNT,
} from './lod.js'

// ---------------------------------------------------------------------------
// Test mesh builder — icosphere subdivisions=2 → 320 tris
// ---------------------------------------------------------------------------

function makeIcosphere(subdivisions = 2) {
  const t = (1 + Math.sqrt(5)) / 2
  const rawV = [
    [-1,t,0],[1,t,0],[-1,-t,0],[1,-t,0],
    [0,-1,t],[0,1,t],[0,-1,-t],[0,1,-t],
    [t,0,-1],[t,0,1],[-t,0,-1],[-t,0,1],
  ]
  const verts = rawV.map(v => {
    const n = Math.sqrt(v[0]**2+v[1]**2+v[2]**2)
    return [v[0]/n, v[1]/n, v[2]/n]
  })
  let faces = [
    [0,11,5],[0,5,1],[0,1,7],[0,7,10],[0,10,11],
    [1,5,9],[5,11,4],[11,10,2],[10,7,6],[7,1,8],
    [3,9,4],[3,4,2],[3,2,6],[3,6,8],[3,8,9],
    [4,9,5],[2,4,11],[6,2,10],[8,6,7],[9,8,1],
  ]
  for (let s = 0; s < subdivisions; s++) {
    const newFaces = []
    const mid = {}
    const midpoint = (a, b) => {
      const k = a < b ? `${a}_${b}` : `${b}_${a}`
      if (!mid[k]) {
        const va = verts[a], vb = verts[b]
        const mx=(va[0]+vb[0])/2, my=(va[1]+vb[1])/2, mz=(va[2]+vb[2])/2
        const nn = Math.sqrt(mx**2+my**2+mz**2)
        mid[k] = verts.length
        verts.push([mx/nn, my/nn, mz/nn])
      }
      return mid[k]
    }
    for (const [a,b,c] of faces) {
      const ab=midpoint(a,b), bc=midpoint(b,c), ca=midpoint(c,a)
      newFaces.push([a,ab,ca],[b,bc,ab],[c,ca,bc],[ab,bc,ca])
    }
    faces = newFaces
  }
  const posArr = new Float32Array(verts.flatMap(v => v))
  const idxArr = new Uint32Array(faces.flatMap(f => f))
  return { posArr, idxArr, faceCount: faces.length }
}

// ---------------------------------------------------------------------------
// decimateBufferGeometry tests
// ---------------------------------------------------------------------------

describe('decimateBufferGeometry', () => {
  it('reduces triangle count to approximately 10%', () => {
    const { posArr, idxArr, faceCount } = makeIcosphere(2) // 320 tris
    const { finalCount, originalCount } = decimateBufferGeometry(posArr, idxArr, 0.10)
    expect(originalCount).toBe(faceCount)
    const ratio = finalCount / originalCount
    expect(ratio).toBeLessThan(0.25)
    expect(ratio).toBeGreaterThan(0)
  })

  it('output indices reference valid vertex positions', () => {
    const { posArr, idxArr } = makeIcosphere(1) // 80 tris
    const { positions, indices } = decimateBufferGeometry(posArr, idxArr, 0.10)
    const nVerts = positions.length / 3
    for (let i = 0; i < indices.length; i++) {
      expect(indices[i]).toBeGreaterThanOrEqual(0)
      expect(indices[i]).toBeLessThan(nVerts)
    }
  })

  it('preserves bounding box within 10% of diagonal', () => {
    const { posArr, idxArr } = makeIcosphere(2)
    const { positions } = decimateBufferGeometry(posArr, idxArr, 0.10)

    let origMinX = Infinity, origMaxX = -Infinity
    for (let i = 0; i < posArr.length; i += 3) {
      if (posArr[i] < origMinX) origMinX = posArr[i]
      if (posArr[i] > origMaxX) origMaxX = posArr[i]
    }
    let outMinX = Infinity, outMaxX = -Infinity
    for (let i = 0; i < positions.length; i += 3) {
      if (positions[i] < outMinX) outMinX = positions[i]
      if (positions[i] > outMaxX) outMaxX = positions[i]
    }

    const diagApprox = 2.0
    const tol = diagApprox * 0.10
    expect(Math.abs(outMinX - origMinX)).toBeLessThan(tol)
    expect(Math.abs(outMaxX - origMaxX)).toBeLessThan(tol)
  })

  it('handles mesh already at or below target face count', () => {
    const posArr = new Float32Array([0,0,0, 1,0,0, 0,1,0])
    const idxArr = new Uint32Array([0,1,2])
    const { finalCount, originalCount } = decimateBufferGeometry(posArr, idxArr, 0.10)
    expect(originalCount).toBe(1)
    expect(finalCount).toBe(1)
  })
})

// ---------------------------------------------------------------------------
// buildLODProxy tests
// ---------------------------------------------------------------------------

describe('buildLODProxy', () => {
  it('returns a BufferGeometry with fewer triangles', () => {
    const { posArr, idxArr, faceCount } = makeIcosphere(2)
    const geom = new MockBufferGeometry()
    geom.setAttribute('position', new MockBufferAttribute(posArr, 3))
    geom.setIndex(new MockBufferAttribute(idxArr, 1))

    const proxy = buildLODProxy(geom, 0.10)
    const proxyIdx = proxy.getIndex()
    const proxyFaceCount = proxyIdx ? proxyIdx.count / 3 : 0
    expect(proxyFaceCount).toBeLessThan(faceCount)
    expect(proxyFaceCount).toBeGreaterThan(0)
  })

  it('returns a clone when geometry has no position attribute', () => {
    const geom = new MockBufferGeometry()
    const proxy = buildLODProxy(geom)
    expect(proxy).toBeInstanceOf(MockBufferGeometry)
  })
})

// ---------------------------------------------------------------------------
// angularSize tests
// ---------------------------------------------------------------------------

describe('angularSize', () => {
  it('returns a positive value for a box in front of the camera', () => {
    const box = new MockBox3()
    box.set(new MockVector3(-1,-1,-1), new MockVector3(1,1,1))
    box._empty = false
    const camera = { position: new MockVector3(0, 0, 10) }
    const ang = angularSize(box, camera)
    expect(ang).toBeGreaterThan(0)
    expect(ang).toBeLessThan(Math.PI)
  })

  it('returns PI for camera inside the sphere (distance 0)', () => {
    const box = new MockBox3()
    box.set(new MockVector3(-1,-1,-1), new MockVector3(1,1,1))
    box._empty = false
    const camera = { position: new MockVector3(0, 0, 0) }
    const ang = angularSize(box, camera)
    expect(ang).toBe(Math.PI)
  })

  it('returns 0 for empty bounding box', () => {
    const box = new MockBox3()  // isEmpty() === true
    const camera = { position: new MockVector3(0, 0, 10) }
    expect(angularSize(box, camera)).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// selectLOD tests
// ---------------------------------------------------------------------------

describe('selectLOD', () => {
  function makeLargeBox() {
    const box = new MockBox3()
    box.set(new MockVector3(-100,-100,-100), new MockVector3(100,100,100))
    box._empty = false
    return box
  }
  function makeSmallBox() {
    const box = new MockBox3()
    box.set(new MockVector3(-0.001,-0.001,-0.001), new MockVector3(0.001,0.001,0.001))
    box._empty = false
    return box
  }

  const nearCamera = { position: new MockVector3(0, 0, 1) }
  const farCamera  = { position: new MockVector3(0, 0, 10_000) }

  it("returns 'full' for large close box below count threshold", () => {
    expect(selectLOD(makeLargeBox(), nearCamera, { visibleIndex: 0 })).toBe('full')
  })

  it("returns 'proxy' for tiny distant box (angular size below threshold)", () => {
    expect(selectLOD(makeSmallBox(), farCamera, { visibleIndex: 0 })).toBe('proxy')
  })

  it("returns 'proxy' when visibleIndex >= LOD_THRESHOLD_COUNT regardless of angle", () => {
    expect(selectLOD(makeLargeBox(), nearCamera, {
      visibleIndex: LOD_THRESHOLD_COUNT,
    })).toBe('proxy')
  })

  it("returns 'full' for visibleIndex just below LOD_THRESHOLD_COUNT with large angle", () => {
    expect(selectLOD(makeLargeBox(), nearCamera, {
      visibleIndex: LOD_THRESHOLD_COUNT - 1,
    })).toBe('full')
  })

  it('angularThreshold option overrides the default', () => {
    expect(selectLOD(makeLargeBox(), nearCamera, {
      visibleIndex: 0,
      angularThreshold: Math.PI,  // everything below PI → proxy
    })).toBe('proxy')
  })

  it('countThreshold option overrides the default', () => {
    expect(selectLOD(makeLargeBox(), nearCamera, {
      visibleIndex: 5,
      countThreshold: 5,
    })).toBe('proxy')
  })

  it("returns 'proxy' for empty bbox (angularSize=0 < threshold)", () => {
    const emptyBox = new MockBox3()  // isEmpty = true → angularSize returns 0
    expect(selectLOD(emptyBox, nearCamera, { visibleIndex: 0 })).toBe('proxy')
  })
})
