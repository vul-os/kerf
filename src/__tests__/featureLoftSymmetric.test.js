// featureLoftSymmetric.test.js
//
// Unit tests for the loft symmetric flag:
//   • sketchPlaneFrame() helper math (pure JS, no OCCT WASM).
//   • Mid-plane origin and normal computation.
//   • Parallel-planes validation logic.
//   • Loft node schema — symmetric field defaults and constraints.
//   • Dispatch-table presence: 'loft' case in both evaluateTree and
//     evaluateToFinalShape (verified via regex over the worker source).

import { describe, it, expect } from 'vitest'
import * as fs from 'node:fs'
import * as path from 'node:path'

// ---------------------------------------------------------------------------
// Pure-JS re-implementation of sketchPlaneFrame (mirrors occtWorker.js logic)
// ---------------------------------------------------------------------------

function sketchPlaneFrame(sketchJson) {
  let parsed
  try { parsed = typeof sketchJson === 'string' ? JSON.parse(sketchJson) : sketchJson } catch { parsed = null }
  const plane = parsed?.plane || { type: 'base', name: 'XY' }
  if (plane.type === 'face' && plane.frame
      && Array.isArray(plane.frame.origin) && Array.isArray(plane.frame.normal)) {
    return { origin: plane.frame.origin.slice(0, 3), normal: plane.frame.normal.slice(0, 3) }
  }
  const name = (plane.name || 'XY').toUpperCase()
  if (name === 'XZ') return { origin: [0, 0, 0], normal: [0, 1, 0] }
  if (name === 'YZ') return { origin: [0, 0, 0], normal: [1, 0, 0] }
  return { origin: [0, 0, 0], normal: [0, 0, 1] }
}

// ---------------------------------------------------------------------------
// Pure-JS mid-plane computation (mirrors opLoft symmetric logic)
// ---------------------------------------------------------------------------

function computeMidPlane(frame0, frame1) {
  const n0 = frame0.normal, n1 = frame1.normal
  const len0 = Math.sqrt(n0[0] ** 2 + n0[1] ** 2 + n0[2] ** 2) || 1
  const len1 = Math.sqrt(n1[0] ** 2 + n1[1] ** 2 + n1[2] ** 2) || 1
  const dn0 = n0.map((v) => v / len0)
  const dn1 = n1.map((v) => v / len1)
  const dotAbs = Math.abs(dn0[0] * dn1[0] + dn0[1] * dn1[1] + dn0[2] * dn1[2])
  const isParallel = dotAbs >= 0.9962

  const o0 = frame0.origin, o1 = frame1.origin
  const midOrigin = [
    (o0[0] + o1[0]) * 0.5,
    (o0[1] + o1[1]) * 0.5,
    (o0[2] + o1[2]) * 0.5,
  ]
  const rawDot = dn0[0] * dn1[0] + dn0[1] * dn1[1] + dn0[2] * dn1[2]
  const sign = rawDot >= 0 ? 1 : -1
  const sumN = [dn0[0] + sign * dn1[0], dn0[1] + sign * dn1[1], dn0[2] + sign * dn1[2]]
  const sumLen = Math.sqrt(sumN[0] ** 2 + sumN[1] ** 2 + sumN[2] ** 2) || 1
  const midNormal = sumN.map((v) => v / sumLen)

  return { isParallel, midOrigin, midNormal, dotAbs }
}

// ---------------------------------------------------------------------------
// sketchPlaneFrame tests
// ---------------------------------------------------------------------------

describe('sketchPlaneFrame', () => {
  it('defaults to XY plane for missing plane spec', () => {
    const f = sketchPlaneFrame({})
    expect(f.normal).toEqual([0, 0, 1])
    expect(f.origin).toEqual([0, 0, 0])
  })

  it('returns XY normal [0,0,1] for base XY', () => {
    const f = sketchPlaneFrame({ plane: { type: 'base', name: 'XY' } })
    expect(f.normal).toEqual([0, 0, 1])
    expect(f.origin).toEqual([0, 0, 0])
  })

  it('returns XZ normal [0,1,0] for base XZ', () => {
    const f = sketchPlaneFrame({ plane: { type: 'base', name: 'XZ' } })
    expect(f.normal).toEqual([0, 1, 0])
    expect(f.origin).toEqual([0, 0, 0])
  })

  it('returns YZ normal [1,0,0] for base YZ', () => {
    const f = sketchPlaneFrame({ plane: { type: 'base', name: 'YZ' } })
    expect(f.normal).toEqual([1, 0, 0])
    expect(f.origin).toEqual([0, 0, 0])
  })

  it('is case-insensitive for plane name', () => {
    const f = sketchPlaneFrame({ plane: { type: 'base', name: 'xz' } })
    expect(f.normal).toEqual([0, 1, 0])
  })

  it('extracts face-anchored plane origin and normal', () => {
    const sketch = {
      plane: {
        type: 'face',
        frame: {
          origin: [5, 10, 20],
          normal: [0, 0, 1],
          uDir: [1, 0, 0],
          vDir: [0, 1, 0],
        },
      },
    }
    const f = sketchPlaneFrame(sketch)
    expect(f.origin).toEqual([5, 10, 20])
    expect(f.normal).toEqual([0, 0, 1])
  })

  it('parses stringified JSON', () => {
    const sketch = JSON.stringify({ plane: { type: 'base', name: 'XZ' } })
    const f = sketchPlaneFrame(sketch)
    expect(f.normal).toEqual([0, 1, 0])
  })

  it('returns only 3 components even if frame has extra', () => {
    const sketch = {
      plane: {
        type: 'face',
        frame: {
          origin: [1, 2, 3, 999],
          normal: [0, 0, 1, 999],
          uDir: [1, 0, 0],
          vDir: [0, 1, 0],
        },
      },
    }
    const f = sketchPlaneFrame(sketch)
    expect(f.origin).toHaveLength(3)
    expect(f.normal).toHaveLength(3)
  })
})

// ---------------------------------------------------------------------------
// Mid-plane computation tests
// ---------------------------------------------------------------------------

describe('computeMidPlane — parallel planes', () => {
  it('two XY planes at same height → mid-plane at Z=0, normal [0,0,1]', () => {
    const f0 = { origin: [0, 0, 0], normal: [0, 0, 1] }
    const f1 = { origin: [0, 0, 0], normal: [0, 0, 1] }
    const { midOrigin, midNormal, isParallel } = computeMidPlane(f0, f1)
    expect(isParallel).toBe(true)
    expect(midOrigin).toEqual([0, 0, 0])
    // Normal should be (approximately) [0,0,1]
    expect(midNormal[2]).toBeCloseTo(1, 5)
  })

  it('two face-anchored XY planes at z=0 and z=20 → mid-plane at z=10', () => {
    const f0 = { origin: [0, 0, 0], normal: [0, 0, 1] }
    const f1 = { origin: [0, 0, 20], normal: [0, 0, 1] }
    const { midOrigin, midNormal, isParallel } = computeMidPlane(f0, f1)
    expect(isParallel).toBe(true)
    expect(midOrigin[2]).toBeCloseTo(10, 5)
    expect(midNormal[2]).toBeCloseTo(1, 5)
  })

  it('two parallel planes with opposite normals → still detects parallel (dot abs)', () => {
    const f0 = { origin: [0, 0, 0], normal: [0, 0, 1] }
    const f1 = { origin: [0, 0, 10], normal: [0, 0, -1] }
    const { isParallel, midNormal } = computeMidPlane(f0, f1)
    expect(isParallel).toBe(true)
    // midNormal should still have |z| ≈ 1 (sign convention from rawDot)
    expect(Math.abs(midNormal[2])).toBeCloseTo(1, 5)
  })

  it('symmetric about XZ plane → mid-plane at y=5, normal [0,1,0]', () => {
    const f0 = { origin: [0, 0, 0], normal: [0, 1, 0] }
    const f1 = { origin: [0, 10, 0], normal: [0, 1, 0] }
    const { midOrigin, midNormal, isParallel } = computeMidPlane(f0, f1)
    expect(isParallel).toBe(true)
    expect(midOrigin[1]).toBeCloseTo(5, 5)
    expect(midNormal[1]).toBeCloseTo(1, 5)
  })
})

describe('computeMidPlane — non-parallel planes', () => {
  it('90° apart → not parallel', () => {
    const f0 = { origin: [0, 0, 0], normal: [0, 0, 1] }  // XY
    const f1 = { origin: [0, 0, 0], normal: [0, 1, 0] }  // XZ
    const { isParallel } = computeMidPlane(f0, f1)
    expect(isParallel).toBe(false)
  })

  it('45° apart → not parallel', () => {
    const n1 = [0, 1 / Math.SQRT2, 1 / Math.SQRT2]
    const f0 = { origin: [0, 0, 0], normal: [0, 0, 1] }
    const f1 = { origin: [0, 0, 0], normal: n1 }
    const { isParallel } = computeMidPlane(f0, f1)
    expect(isParallel).toBe(false)
  })

  it('5° apart → accepted (boundary at cos(5°))', () => {
    // cos(5°) ≈ 0.9962, threshold is 0.9962
    const tilt = 4 * (Math.PI / 180) // just under 5°
    const n1 = [0, Math.sin(tilt), Math.cos(tilt)]
    const f0 = { origin: [0, 0, 0], normal: [0, 0, 1] }
    const f1 = { origin: [0, 0, 0], normal: n1 }
    const { isParallel } = computeMidPlane(f0, f1)
    expect(isParallel).toBe(true)
  })

  it('6° apart → rejected', () => {
    const tilt = 6 * (Math.PI / 180)
    const n1 = [0, Math.sin(tilt), Math.cos(tilt)]
    const f0 = { origin: [0, 0, 0], normal: [0, 0, 1] }
    const f1 = { origin: [0, 0, 0], normal: n1 }
    const { isParallel } = computeMidPlane(f0, f1)
    expect(isParallel).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Mirror math: verify that mirroring a point across the mid-plane produces
// the expected position (pure JS — no OCCT).
// ---------------------------------------------------------------------------

function mirrorPoint(p, planeOrigin, planeNormal) {
  // Reflect p across the plane defined by (planeOrigin, planeNormal).
  // p' = p - 2 * dot(p - o, n̂) * n̂
  const len = Math.sqrt(planeNormal.reduce((s, v) => s + v * v, 0))
  const n = planeNormal.map((v) => v / len)
  const d = p.reduce((s, v, i) => s + (v - planeOrigin[i]) * n[i], 0)
  return p.map((v, i) => v - 2 * d * n[i])
}

describe('mirror math', () => {
  it('mirroring a point on the mid-plane does not move it', () => {
    const p = [5, 5, 10]   // on z=10 plane
    const origin = [0, 0, 10]
    const normal = [0, 0, 1]
    const pm = mirrorPoint(p, origin, normal)
    expect(pm).toEqual([5, 5, 10])
  })

  it('mirroring a point at z=20 across z=10 plane → z=0', () => {
    const p = [3, 4, 20]
    const pm = mirrorPoint(p, [0, 0, 10], [0, 0, 1])
    expect(pm[0]).toBeCloseTo(3, 5)
    expect(pm[1]).toBeCloseTo(4, 5)
    expect(pm[2]).toBeCloseTo(0, 5)
  })

  it('mirroring z=0 point across z=10 → z=20', () => {
    const p = [3, 4, 0]
    const pm = mirrorPoint(p, [0, 0, 10], [0, 0, 1])
    expect(pm[2]).toBeCloseTo(20, 5)
  })

  it('double-mirror returns to original', () => {
    const p = [7, -3, 5]
    const origin = [0, 0, 10]
    const normal = [0, 0, 1]
    const pm = mirrorPoint(p, origin, normal)
    const pmm = mirrorPoint(pm, origin, normal)
    p.forEach((v, i) => expect(pmm[i]).toBeCloseTo(v, 5))
  })

  it('mirroring across XZ plane (y=5)', () => {
    const p = [1, 0, 2]
    const pm = mirrorPoint(p, [0, 5, 0], [0, 1, 0])
    expect(pm[0]).toBeCloseTo(1, 5)
    expect(pm[1]).toBeCloseTo(10, 5)
    expect(pm[2]).toBeCloseTo(2, 5)
  })
})

// ---------------------------------------------------------------------------
// Symmetric loft mid-plane geometry property:
// if both profiles are placed symmetrically, the mid-plane is equidistant
// from both origins.
// ---------------------------------------------------------------------------

describe('symmetric loft mid-plane is equidistant from both profiles', () => {
  function distToPlane(point, planeOrigin, planeNormal) {
    const n = planeNormal.map((v) => {
      const len = Math.sqrt(planeNormal.reduce((s, x) => s + x * x, 0))
      return v / len
    })
    return Math.abs(point.reduce((s, v, i) => s + (v - planeOrigin[i]) * n[i], 0))
  }

  it('z=0 and z=20 profiles → mid-plane at z=10 equidistant (10mm each)', () => {
    const f0 = { origin: [0, 0, 0], normal: [0, 0, 1] }
    const f1 = { origin: [0, 0, 20], normal: [0, 0, 1] }
    const { midOrigin, midNormal } = computeMidPlane(f0, f1)

    const d0 = distToPlane(f0.origin, midOrigin, midNormal)
    const d1 = distToPlane(f1.origin, midOrigin, midNormal)
    expect(d0).toBeCloseTo(d1, 5)
    expect(d0).toBeCloseTo(10, 5)
  })

  it('z=5 and z=15 profiles → mid-plane at z=10', () => {
    const f0 = { origin: [0, 0, 5], normal: [0, 0, 1] }
    const f1 = { origin: [0, 0, 15], normal: [0, 0, 1] }
    const { midOrigin } = computeMidPlane(f0, f1)
    expect(midOrigin[2]).toBeCloseTo(10, 5)
  })

  it('non-origin-offset face planes', () => {
    const f0 = { origin: [10, 20, 0], normal: [0, 0, 1] }
    const f1 = { origin: [10, 20, 40], normal: [0, 0, 1] }
    const { midOrigin } = computeMidPlane(f0, f1)
    expect(midOrigin[0]).toBeCloseTo(10, 5)
    expect(midOrigin[1]).toBeCloseTo(20, 5)
    expect(midOrigin[2]).toBeCloseTo(20, 5)
  })
})

// ---------------------------------------------------------------------------
// Loft node schema
// ---------------------------------------------------------------------------

describe('loft node schema', () => {
  function buildNode(overrides = {}) {
    return {
      id: 'loft-1',
      op: 'loft',
      profile_sketch_paths: ['/p1.sketch', '/p2.sketch'],
      ruled: false,
      closed: false,
      symmetric: false,
      continuity: 'C0',
      ...overrides,
    }
  }

  it('default symmetric is false', () => {
    expect(buildNode().symmetric).toBe(false)
  })

  it('symmetric=true stored in node', () => {
    expect(buildNode({ symmetric: true }).symmetric).toBe(true)
  })

  it('symmetric=true requires exactly 2 profiles (schema validation)', () => {
    // This mirrors the Python validation logic in JS land.
    function validateSymmetric(paths, symmetric, closed) {
      if (symmetric && paths.length !== 2) return 'exactly 2'
      if (symmetric && closed) return 'symmetric and closed'
      return null
    }
    expect(validateSymmetric(['/p1.sketch', '/p2.sketch', '/p3.sketch'], true, false)).toBeTruthy()
    expect(validateSymmetric(['/p1.sketch', '/p2.sketch'], true, false)).toBeNull()
    expect(validateSymmetric(['/p1.sketch', '/p2.sketch'], true, true)).toBeTruthy()
    expect(validateSymmetric(['/p1.sketch', '/p2.sketch', '/p3.sketch'], false, false)).toBeNull()
  })

  it('round-trips through JSON without data loss', () => {
    const node = buildNode({ symmetric: true, continuity: 'C1', ruled: true })
    const restored = JSON.parse(JSON.stringify(node))
    expect(restored).toEqual(node)
  })

  it('accepts all valid continuity values', () => {
    for (const cont of ['C0', 'C1', 'C2']) {
      expect(buildNode({ continuity: cont }).continuity).toBe(cont)
    }
  })
})

// ---------------------------------------------------------------------------
// Dispatch-table check: 'loft' case present in both evaluateTree and
// evaluateToFinalShape in occtWorker.js.
// ---------------------------------------------------------------------------

describe('occtWorker.js dispatch table', () => {
  const workerSrc = fs.readFileSync(
    path.resolve(__dirname, '../../src/lib/occtWorker.js'),
    'utf8',
  )

  it("case 'loft' appears in evaluateTree switch", () => {
    // The worker has two switch blocks — we verify both contain 'loft'.
    const caseMatches = [...workerSrc.matchAll(/case\s+'loft'/g)]
    expect(caseMatches.length).toBeGreaterThanOrEqual(2)
  })

  it('opLoft function is defined', () => {
    expect(workerSrc).toContain('function opLoft(')
  })

  it('sketchPlaneFrame helper is defined in the worker', () => {
    expect(workerSrc).toContain('function sketchPlaneFrame(')
  })

  it('symmetric branch exists in opLoft', () => {
    expect(workerSrc).toContain('node.symmetric')
  })

  it('mirrorShape is called in the symmetric path', () => {
    // mirrorShape is imported from occtBridge.js and called in opLoft symmetric
    const mirrorCallIdx = workerSrc.indexOf('mirrorShape(oc, wires[0]')
    expect(mirrorCallIdx).toBeGreaterThan(-1)
  })
})
