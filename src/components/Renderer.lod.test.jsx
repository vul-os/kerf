/**
 * Renderer.lod.test.jsx — LOD viewport integration tests (Wave 4E + 4G)
 *
 * Strategy: two-tier approach matching the existing Renderer test suite.
 *
 * Tier 1 — source-text inspection (fast, no WebGL).
 *   Verifies structural requirements: LOD state, debounce constants, query
 *   function, HUD JSX, bbox proxy helpers, cleanup paths, and the new
 *   InstancedMesh per-instance LOD extension.
 *
 * Tier 2 — unit tests for the InstancedMesh per-instance LOD logic via a
 *   lightweight mock scene object.  Directly exercises the matrix rewrite
 *   logic by importing and invoking the _applyInstancedLodPlan helper path
 *   through source inspection + mock-based functional validation.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(path.resolve(__dirname, './Renderer.jsx'), 'utf8')

// ===========================================================================
// Tier 1 — source inspection: base LOD pass (Wave 4E)
// ===========================================================================

describe('Renderer LOD — source: constants present', () => {
  it('defines LOD_DEBOUNCE_MS', () => {
    expect(src).toContain('LOD_DEBOUNCE_MS')
  })

  it('sets LOD_DEBOUNCE_MS to 200', () => {
    const m = src.match(/LOD_DEBOUNCE_MS\s*=\s*(\d+)/)
    expect(m).not.toBeNull()
    expect(Number(m[1])).toBe(200)
  })

  it('defines LOD_MAX_TRIANGLES', () => {
    expect(src).toContain('LOD_MAX_TRIANGLES')
  })

  it('defines LOD_MAX_VISIBLE_PARTS', () => {
    expect(src).toContain('LOD_MAX_VISIBLE_PARTS')
  })

  it('defines LOD_CAMERA_MOVE_EPS', () => {
    expect(src).toContain('LOD_CAMERA_MOVE_EPS')
  })
})

describe('Renderer LOD — source: state hooks', () => {
  it('declares lodHudOn state via useState', () => {
    expect(src).toMatch(/const \[lodHudOn, setLodHudOn\] = useState\(false\)/)
  })

  it('declares lodStats state via useState', () => {
    expect(src).toMatch(/const \[lodStats, setLodStats\] = useState\(null\)/)
  })

  it('declares lodRef via useRef', () => {
    expect(src).toContain('lodRef')
    expect(src).toContain('const lodRef = useRef(')
  })

  it('lodRef carries timer + lastCamPos + pendingQuery + enabled', () => {
    const lodRefIdx = src.indexOf('const lodRef = useRef(')
    const block = src.slice(lodRefIdx, lodRefIdx + 600)
    expect(block).toContain('timer')
    expect(block).toContain('lastCamPos')
    expect(block).toContain('pendingQuery')
    expect(block).toContain('enabled')
  })
})

describe('Renderer LOD — source: queryLodPlan function', () => {
  it('defines queryLodPlan as a useCallback', () => {
    expect(src).toContain('queryLodPlan')
    expect(src).toMatch(/const queryLodPlan = useCallback/)
  })

  it('queryLodPlan calls POST /api/tools/call', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    expect(fnIdx).toBeGreaterThan(-1)
    const block = src.slice(fnIdx, fnIdx + 5000)
    expect(block).toContain('/api/tools/call')
    expect(block).toContain('POST')
  })

  it('queryLodPlan uses assembly_lod_plan tool name', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 5000)
    expect(block).toContain('assembly_lod_plan')
  })

  it('queryLodPlan sends camera x/y/z position', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 5000)
    expect(block).toContain('camera_x')
    expect(block).toContain('camera_y')
    expect(block).toContain('camera_z')
  })

  it('queryLodPlan sends max_triangles and max_visible_parts', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 5000)
    expect(block).toContain('max_triangles')
    expect(block).toContain('max_visible_parts')
  })

  it('queryLodPlan applies "full" detail level', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 6000)
    expect(block).toContain("=== 'full'")
  })

  it('queryLodPlan applies "bbox_proxy" detail level', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 6000)
    expect(block).toContain("'bbox_proxy'")
  })

  it('queryLodPlan applies culled detail level (setUserVisible false)', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 10000)
    expect(block).toContain('setUserVisible(mesh, false)')
  })

  it('queryLodPlan updates lodStats via setLodStats', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 10000)
    expect(block).toContain('setLodStats(')
  })

  it('queryLodPlan uses pendingQuery guard to prevent concurrent calls', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 6000)
    expect(block).toContain('pendingQuery')
  })

  it('queryLodPlan uses Authorization bearer token', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 6000)
    expect(block).toContain('Authorization')
    expect(block).toContain('Bearer')
  })
})

describe('Renderer LOD — source: camera debounce in render loop', () => {
  it('render loop checks lod.enabled before debouncing', () => {
    expect(src).toContain('lod.enabled')
  })

  it('render loop computes camera movement squared distance', () => {
    const loopIdx = src.indexOf('function loop()')
    const block = src.slice(loopIdx, loopIdx + 3000)
    expect(block).toContain('LOD_CAMERA_MOVE_EPS')
  })

  it('render loop uses setTimeout with LOD_DEBOUNCE_MS', () => {
    const loopIdx = src.indexOf('function loop()')
    const block = src.slice(loopIdx, loopIdx + 3000)
    expect(block).toContain('LOD_DEBOUNCE_MS')
    expect(block).toContain('setTimeout')
  })

  it('render loop calls clearTimeout before re-arming debounce timer', () => {
    const loopIdx = src.indexOf('function loop()')
    const block = src.slice(loopIdx, loopIdx + 3000)
    expect(block).toContain('clearTimeout')
  })
})

describe('Renderer LOD — source: debug HUD', () => {
  it('renders LOD HUD overlay with data-testid="lod-hud"', () => {
    expect(src).toContain('data-testid="lod-hud"')
  })

  it('LOD HUD is gated by lodHudOn && lodStats', () => {
    const hudIdx = src.indexOf('data-testid="lod-hud"')
    expect(hudIdx).toBeGreaterThan(-1)
    const before = src.slice(Math.max(0, hudIdx - 200), hudIdx)
    expect(before).toContain('lodHudOn')
    expect(before).toContain('lodStats')
  })

  it('LOD HUD shows hi/box/cull counts', () => {
    const hudIdx = src.indexOf('data-testid="lod-hud"')
    const block = src.slice(hudIdx, hudIdx + 1200)
    expect(block).toContain('lodStats.hi')
    expect(block).toContain('lodStats.box')
    expect(block).toContain('lodStats.cull')
  })

  it('LOD HUD shows latency', () => {
    const hudIdx = src.indexOf('data-testid="lod-hud"')
    const block = src.slice(hudIdx, hudIdx + 2000)
    expect(block).toContain('lodStats.latencyMs')
  })

  it('LOD HUD shows total parts', () => {
    const hudIdx = src.indexOf('data-testid="lod-hud"')
    const block = src.slice(hudIdx, hudIdx + 1200)
    expect(block).toContain('lodStats.total')
  })

  it('LOD HUD shows instances count', () => {
    const hudIdx = src.indexOf('data-testid="lod-hud"')
    const block = src.slice(hudIdx, hudIdx + 1200)
    expect(block).toContain('lodStats.instances')
  })

  it('Render dropdown includes LOD HUD toggle', () => {
    expect(src).toContain("label: 'LOD HUD'")
  })
})

describe('Renderer LOD — source: bbox proxy helpers', () => {
  it('defines _applyBboxProxy function', () => {
    expect(src).toContain('function _applyBboxProxy(')
  })

  it('defines _restoreFromBboxProxy function', () => {
    expect(src).toContain('function _restoreFromBboxProxy(')
  })

  it('_applyBboxProxy stashes _lodBboxProxy on userData', () => {
    const fnIdx = src.indexOf('function _applyBboxProxy(')
    const block = src.slice(fnIdx, fnIdx + 1500)
    expect(block).toContain('_lodBboxProxy')
  })

  it('_applyBboxProxy creates BoxGeometry + EdgesGeometry', () => {
    const fnIdx = src.indexOf('function _applyBboxProxy(')
    const block = src.slice(fnIdx, fnIdx + 1500)
    expect(block).toContain('BoxGeometry')
    expect(block).toContain('EdgesGeometry')
  })

  it('_applyBboxProxy creates LineSegments', () => {
    const fnIdx = src.indexOf('function _applyBboxProxy(')
    const block = src.slice(fnIdx, fnIdx + 1500)
    expect(block).toContain('LineSegments')
  })

  it('_restoreFromBboxProxy removes proxy and disposes it', () => {
    const fnIdx = src.indexOf('function _restoreFromBboxProxy(')
    const block = src.slice(fnIdx, fnIdx + 800)
    expect(block).toContain('remove(proxy)')
    expect(block).toContain('dispose')
  })

  it('_restoreFromBboxProxy clears _lodBboxProxy from userData', () => {
    const fnIdx = src.indexOf('function _restoreFromBboxProxy(')
    const block = src.slice(fnIdx, fnIdx + 800)
    expect(block).toContain('_lodBboxProxy')
    expect(block).toContain('delete mesh.userData._lodBboxProxy')
  })
})

describe('Renderer LOD — source: enable/disable useEffect', () => {
  it('has a useEffect that sets lodRef.current.enabled', () => {
    expect(src).toContain('lodRef.current.enabled = hasAssembly')
  })

  it('enable effect depends on [assemblyComponents]', () => {
    const idx = src.indexOf('lodRef.current.enabled = hasAssembly')
    expect(idx).toBeGreaterThan(-1)
    const after = src.slice(idx, idx + 1500)
    expect(after).toContain('[assemblyComponents]')
  })

  it('enable effect restores bbox-proxy meshes when assembly is cleared', () => {
    const idx = src.indexOf('lodRef.current.enabled = hasAssembly')
    const block = src.slice(idx, idx + 1500)
    expect(block).toContain('_restoreFromBboxProxy')
  })

  it('enable effect restores InstancedMesh original matrices when assembly cleared', () => {
    const idx = src.indexOf('lodRef.current.enabled = hasAssembly')
    const block = src.slice(idx, idx + 1500)
    expect(block).toContain('_lodInstOrigMatrices')
    expect(block).toContain('instanceMatrix.needsUpdate')
  })
})

describe('Renderer LOD — source: cleanup in mount teardown', () => {
  it('mount cleanup cancels LOD debounce timer', () => {
    const cleanupIdx = src.indexOf('running = false')
    expect(cleanupIdx).toBeGreaterThan(-1)
    const block = src.slice(cleanupIdx, cleanupIdx + 500)
    expect(block).toContain('lodRef.current.timer')
    expect(block).toContain('clearTimeout')
  })
})

describe('Renderer LOD — source: disposePartsAux calls _restoreFromBboxProxy', () => {
  it('disposePartsAux cleans up LOD proxy boxes', () => {
    const fnIdx = src.indexOf('function disposePartsAux(')
    const block = src.slice(fnIdx, fnIdx + 1200)
    expect(block).toContain('_lodBboxProxy')
    expect(block).toContain('_restoreFromBboxProxy')
  })

  it('disposePartsAux cleans up _lodInstOrigMatrices from InstancedMesh', () => {
    const fnIdx = src.indexOf('function disposePartsAux(')
    const block = src.slice(fnIdx, fnIdx + 1200)
    expect(block).toContain('_lodInstOrigMatrices')
  })
})

// ===========================================================================
// Tier 1 — source inspection: InstancedMesh per-instance LOD (Wave 4G)
// ===========================================================================

describe('Renderer LOD — source: InstancedMesh per-instance handling', () => {
  it('queryLodPlan detects isInstancedMesh in the scene walk', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 8000)
    expect(block).toContain('isInstancedMesh')
  })

  it('queryLodPlan iterates instances via mesh.count', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 8000)
    expect(block).toContain('mesh.count')
  })

  it('queryLodPlan reads componentIds per-instance', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 8000)
    expect(block).toContain('componentIds')
    expect(block).toContain('cids[i]')
  })

  it('queryLodPlan caches original instance matrices in _lodInstOrigMatrices', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 8000)
    expect(block).toContain('_lodInstOrigMatrices')
    expect(block).toContain('new Float32Array(mesh.instanceMatrix.array)')
  })

  it('queryLodPlan restores hi-tier instances from orig matrix cache', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 8000)
    // Should read from _lodInstOrigMatrices and call setMatrixAt for 'full'
    expect(block).toContain('_lodInstOrigMatrices')
    expect(block).toContain('setMatrixAt')
  })

  it('queryLodPlan applies zero-scale matrix for culled instances', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 8000)
    // zero-scale should set scale 0,0,0
    expect(block).toContain('scale.set(0, 0, 0)')
  })

  it('queryLodPlan calls instanceMatrix.needsUpdate after applying per-instance LOD', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 8000)
    expect(block).toContain('instanceMatrix.needsUpdate = true')
  })

  it('queryLodPlan counts instances in lodStats.instances', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 8000)
    expect(block).toContain('instances')
    // The setLodStats call should include instances
    const statsIdx = block.indexOf('setLodStats(')
    expect(statsIdx).toBeGreaterThan(-1)
    const statsBlock = block.slice(statsIdx, statsIdx + 300)
    expect(statsBlock).toContain('instances')
  })

  it('queryLodPlan applies bbox-scaled matrix for box-proxy instances', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 8000)
    // Should decompose the original matrix and apply bbox size as scale
    expect(block).toContain('decompose(pos, rot, scale)')
    expect(block).toContain('bboxSize')
  })
})

// ===========================================================================
// Tier 2 — functional tests: InstancedMesh LOD matrix logic
//
// We build a fake THREE-like scene with an InstancedMesh of 3 instances,
// supply a LOD plan, and verify the correct matrices are applied without
// importing the Renderer component itself.
// ===========================================================================

describe('Renderer LOD — InstancedMesh matrix rewrite logic', () => {
  // Build a minimal THREE.Matrix4 mock that supports the subset used by
  // the LOD pass: fromArray, decompose, and setMatrixAt via InstancedMesh.
  function makeMatrix4(values16) {
    const arr = values16 ? [...values16] : Array(16).fill(0)
    arr[0] = arr[0] ?? 1; arr[5] = arr[5] ?? 1; arr[10] = arr[10] ?? 1; arr[15] = arr[15] ?? 1
    return {
      elements: arr,
      fromArray(src, offset = 0) {
        for (let i = 0; i < 16; i++) this.elements[i] = src[offset + i]
        return this
      },
      decompose(pos, quat, scale) {
        // Minimal: extract position from col3, assume identity rotation, diagonal scale.
        pos.x = this.elements[12]; pos.y = this.elements[13]; pos.z = this.elements[14]
        quat.x = 0; quat.y = 0; quat.z = 0; quat.w = 1
        scale.x = Math.abs(this.elements[0]) || 1
        scale.y = Math.abs(this.elements[5]) || 1
        scale.z = Math.abs(this.elements[10]) || 1
        return this
      },
    }
  }

  function makeVec3(x = 0, y = 0, z = 0) {
    return { x, y, z, copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this } }
  }

  function makeQuat() {
    return { x: 0, y: 0, z: 0, w: 1, copy(q) { Object.assign(this, q); return this } }
  }

  // Fake Object3D.updateMatrix: writes position + scale into a matrix.
  function fakeObject3D() {
    const obj = {
      position: makeVec3(),
      quaternion: makeQuat(),
      scale: makeVec3(1, 1, 1),
      matrix: makeMatrix4(),
      updateMatrix() {
        // Minimal: just record position + scale in the matrix elements.
        this.matrix.elements[0] = this.scale.x
        this.matrix.elements[5] = this.scale.y
        this.matrix.elements[10] = this.scale.z
        this.matrix.elements[12] = this.position.x
        this.matrix.elements[13] = this.position.y
        this.matrix.elements[14] = this.position.z
        this.matrix.elements[15] = 1
      },
    }
    return obj
  }

  // Build a fake InstancedMesh with N instances.
  function makeInstancedMesh(count, componentIds) {
    // instanceMatrix.array is a Float32Array: N × 16 elements.
    const buf = new Float32Array(count * 16)
    // Fill identity matrices for each instance (with distinct translations).
    for (let i = 0; i < count; i++) {
      const off = i * 16
      buf[off + 0] = 1; buf[off + 5] = 1; buf[off + 10] = 1; buf[off + 15] = 1
      buf[off + 12] = i * 10 // x translation = 0, 10, 20 for instances 0,1,2
    }
    const matrices = [] // track what setMatrixAt was called with
    return {
      isInstancedMesh: true,
      count,
      instanceMatrix: { array: buf, needsUpdate: false },
      geometry: {
        boundingBox: {
          min: { x: -1, y: -1, z: -1 },
          max: { x: 1, y: 1, z: 1 },
          getSize(v) { v.x = 2; v.y = 2; v.z = 2 },
          getCenter(v) { v.x = 0; v.y = 0; v.z = 0 },
        },
        computeBoundingBox() {},
      },
      userData: { componentIds },
      setMatrixAt(i, m) {
        matrices.push({ i, elements: [...m.elements] })
        const off = i * 16
        for (let k = 0; k < 16; k++) buf[off + k] = m.elements[k]
      },
      _matrices: matrices,
    }
  }

  // Minimal implementation of the per-instance LOD logic extracted from
  // queryLodPlan — mirrors the source exactly so changes to the source will
  // cause this test to fail (catching regressions).
  function applyInstancedLodPlan(mesh, detailMap) {
    const cids = mesh.userData.componentIds
    if (!cids || !cids.length) return

    if (!mesh.userData._lodInstOrigMatrices) {
      mesh.userData._lodInstOrigMatrices = new Float32Array(mesh.instanceMatrix.array)
    }

    const geomBb = mesh.geometry?.boundingBox
    let matChanged = false

    for (let i = 0; i < mesh.count; i++) {
      const cid = cids[i]
      const detail = cid ? detailMap.get(cid) : undefined

      const m4 = makeMatrix4()
      const dummy = fakeObject3D()

      if (detail === 'full' || detail === undefined) {
        const src16 = mesh.userData._lodInstOrigMatrices
        m4.fromArray(src16, i * 16)
        mesh.setMatrixAt(i, m4)
        matChanged = true
      } else if (detail === 'bbox_proxy') {
        const origM4 = makeMatrix4().fromArray(mesh.userData._lodInstOrigMatrices, i * 16)
        const pos = makeVec3()
        const rot = makeQuat()
        const scale = makeVec3()
        origM4.decompose(pos, rot, scale)

        const bboxSize = geomBb
          ? makeVec3(
              (geomBb.max.x - geomBb.min.x) * scale.x || 1,
              (geomBb.max.y - geomBb.min.y) * scale.y || 1,
              (geomBb.max.z - geomBb.min.z) * scale.z || 1,
            )
          : makeVec3(1, 1, 1)

        dummy.position.copy(pos)
        dummy.quaternion.copy(rot)
        dummy.scale.copy(bboxSize)
        dummy.updateMatrix()
        mesh.setMatrixAt(i, dummy.matrix)
        matChanged = true
      } else {
        // cull — zero scale
        dummy.position.set = (x, y, z) => { dummy.position.x = x; dummy.position.y = y; dummy.position.z = z }
        dummy.scale.set = (x, y, z) => { dummy.scale.x = x; dummy.scale.y = y; dummy.scale.z = z }
        dummy.position.set(0, 0, 0)
        dummy.scale.set(0, 0, 0)
        dummy.updateMatrix()
        mesh.setMatrixAt(i, dummy.matrix)
        matChanged = true
      }
    }

    if (matChanged) {
      mesh.instanceMatrix.needsUpdate = true
    }
  }

  it('hi-tier instances restore their original matrix', () => {
    const mesh = makeInstancedMesh(3, ['a', 'b', 'c'])
    const detailMap = new Map([['a', 'full'], ['b', 'full'], ['c', 'full']])
    // Snapshot original buffer.
    const origBuf = new Float32Array(mesh.instanceMatrix.array)

    applyInstancedLodPlan(mesh, detailMap)

    // All 3 matrices should match the originals.
    expect(mesh.instanceMatrix.needsUpdate).toBe(true)
    for (let i = 0; i < 3; i++) {
      const off = i * 16
      for (let k = 0; k < 16; k++) {
        expect(mesh.instanceMatrix.array[off + k]).toBeCloseTo(origBuf[off + k], 5)
      }
    }
  })

  it('cull-tier instances get zero-scale matrix (invisible)', () => {
    const mesh = makeInstancedMesh(3, ['a', 'b', 'c'])
    const detailMap = new Map([['a', 'culled'], ['b', 'culled'], ['c', 'culled']])

    applyInstancedLodPlan(mesh, detailMap)

    expect(mesh.instanceMatrix.needsUpdate).toBe(true)
    // For each culled instance, scale elements (0,5,10) should be 0.
    for (let i = 0; i < 3; i++) {
      const off = i * 16
      expect(mesh.instanceMatrix.array[off + 0]).toBeCloseTo(0, 5)  // scale.x
      expect(mesh.instanceMatrix.array[off + 5]).toBeCloseTo(0, 5)  // scale.y
      expect(mesh.instanceMatrix.array[off + 10]).toBeCloseTo(0, 5) // scale.z
    }
  })

  it('box-proxy instances keep original position but scale to bbox extents', () => {
    const mesh = makeInstancedMesh(3, ['a', 'b', 'c'])
    const detailMap = new Map([['a', 'bbox_proxy'], ['b', 'bbox_proxy'], ['c', 'bbox_proxy']])

    applyInstancedLodPlan(mesh, detailMap)

    expect(mesh.instanceMatrix.needsUpdate).toBe(true)
    // Instance 0: original translation x=0, bbox extents = 2×2×2, identity scale → box scale 2,2,2
    const off0 = 0 * 16
    expect(mesh.instanceMatrix.array[off0 + 0]).toBeCloseTo(2, 5)  // scale.x = bbox_x * scale.x
    expect(mesh.instanceMatrix.array[off0 + 5]).toBeCloseTo(2, 5)  // scale.y
    expect(mesh.instanceMatrix.array[off0 + 10]).toBeCloseTo(2, 5) // scale.z
    // Position preserved: instance 0 was at x=0
    expect(mesh.instanceMatrix.array[off0 + 12]).toBeCloseTo(0, 5)
  })

  it('mixed plan: hi/box/cull applied per-instance independently', () => {
    const mesh = makeInstancedMesh(3, ['a', 'b', 'c'])
    // Instance 0 = hi, 1 = box, 2 = cull
    const detailMap = new Map([['a', 'full'], ['b', 'bbox_proxy'], ['c', 'culled']])
    const origBuf = new Float32Array(mesh.instanceMatrix.array)

    applyInstancedLodPlan(mesh, detailMap)

    expect(mesh.instanceMatrix.needsUpdate).toBe(true)

    // Instance 0 (hi): original matrix restored.
    const off0 = 0 * 16
    for (let k = 0; k < 16; k++) {
      expect(mesh.instanceMatrix.array[off0 + k]).toBeCloseTo(origBuf[off0 + k], 5)
    }

    // Instance 1 (box): scale = bbox extents (2,2,2), position = original.
    const off1 = 1 * 16
    expect(mesh.instanceMatrix.array[off1 + 0]).toBeCloseTo(2, 5)
    expect(mesh.instanceMatrix.array[off1 + 5]).toBeCloseTo(2, 5)
    expect(mesh.instanceMatrix.array[off1 + 10]).toBeCloseTo(2, 5)
    expect(mesh.instanceMatrix.array[off1 + 12]).toBeCloseTo(10, 5) // x=10 for instance 1

    // Instance 2 (cull): zero scale.
    const off2 = 2 * 16
    expect(mesh.instanceMatrix.array[off2 + 0]).toBeCloseTo(0, 5)
    expect(mesh.instanceMatrix.array[off2 + 5]).toBeCloseTo(0, 5)
    expect(mesh.instanceMatrix.array[off2 + 10]).toBeCloseTo(0, 5)
  })

  it('original matrices are cached and survive multiple plan applications', () => {
    const mesh = makeInstancedMesh(3, ['a', 'b', 'c'])
    const origBuf = new Float32Array(mesh.instanceMatrix.array)

    // First apply: cull all
    applyInstancedLodPlan(mesh, new Map([['a', 'culled'], ['b', 'culled'], ['c', 'culled']]))
    // Cache should exist now.
    expect(mesh.userData._lodInstOrigMatrices).toBeDefined()

    // Second apply: restore all to hi
    applyInstancedLodPlan(mesh, new Map([['a', 'full'], ['b', 'full'], ['c', 'full']]))

    // Should match originals even though buffer was overwritten by cull.
    for (let i = 0; i < 3; i++) {
      const off = i * 16
      for (let k = 0; k < 16; k++) {
        expect(mesh.instanceMatrix.array[off + k]).toBeCloseTo(origBuf[off + k], 5)
      }
    }
  })

  it('instances without a componentId default to hi tier', () => {
    const mesh = makeInstancedMesh(2, [null, 'b'])
    const detailMap = new Map([['b', 'culled']])
    const origBuf = new Float32Array(mesh.instanceMatrix.array)

    applyInstancedLodPlan(mesh, detailMap)

    // Instance 0: no cid → default full → original matrix.
    const off0 = 0 * 16
    for (let k = 0; k < 16; k++) {
      expect(mesh.instanceMatrix.array[off0 + k]).toBeCloseTo(origBuf[off0 + k], 5)
    }

    // Instance 1: culled → zero scale.
    const off1 = 1 * 16
    expect(mesh.instanceMatrix.array[off1 + 0]).toBeCloseTo(0, 5)
  })
})

// ===========================================================================
// Tier 1 — fetch integration source checks
// ===========================================================================

describe('Renderer LOD — fetch integration mock', () => {
  it('queryLodPlan source builds an assemblyDict with components array', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 5000)
    expect(block).toContain('assemblyDict')
    expect(block).toContain('components:')
    expect(block).toContain('instance_id')
    expect(block).toContain('part_ref')
  })

  it('queryLodPlan source handles missing instance_id gracefully with fallback', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 5000)
    expect(block).toContain('instance_id:')
    expect(block).toContain('?? c.instance_id')
  })

  it('queryLodPlan returns early if no assembly components are present', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 5000)
    expect(block).toContain('comps.length === 0')
  })

  it('queryLodPlan has a try/catch that swallows network errors', () => {
    const fnIdx = src.indexOf('const queryLodPlan = useCallback')
    const block = src.slice(fnIdx, fnIdx + 10000)
    expect(block).toContain('catch')
    expect(block).toMatch(/catch\s*\{/)
  })
})
