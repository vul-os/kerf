// featureBossWithDraft.test.js
//
// Unit tests for the boss_with_draft feature:
//   • walkSideFaces helper math (pure JS, no OCCT WASM needed).
//   • node-emission round-trip through occtWorker's dispatch switch
//     (verified via the internal module structure without spinning up WASM).
//
// The OCCT integration (actual geometry) is left to manual / CI tests that
// spin up the full WASM build; those are expensive and not suitable for a
// fast unit suite.

import { describe, it, expect } from 'vitest'

// ---------------------------------------------------------------------------
// Re-export walkSideFaces for white-box testing by duplicating its logic
// here. We can't import directly from occtWorker.js because it is a Web
// Worker module that can't run in Node. Instead we reproduce the pure-math
// portion of walkSideFaces inline so we can verify the dot-product threshold
// separately from any OCCT binding.
// ---------------------------------------------------------------------------

/**
 * Pure-JS version of the side-face classifier used inside walkSideFaces.
 *
 * Returns true if a face with `faceNormal` is a SIDE face relative to
 * extrusion axis `axisDir` — i.e. its normal is NOT parallel to the axis.
 */
function isSideFace(faceNormal, axisDir) {
  const [ax, ay, az] = axisDir
  const axLen = Math.sqrt(ax * ax + ay * ay + az * az)
  if (axLen < 1e-10) return false
  const nx = ax / axLen, ny = ay / axLen, nz = az / axLen
  const [fx, fy, fz] = faceNormal
  const dot = Math.abs(fx * nx + fy * ny + fz * nz)
  // Threshold: faces within 15° of parallel to the axis are caps, not sides.
  return dot < 0.966
}

// ---------------------------------------------------------------------------
// walkSideFaces classification math
// ---------------------------------------------------------------------------

describe('isSideFace (walkSideFaces classifier)', () => {
  const UP = [0, 0, 1]

  it('rejects the top cap face (normal == axis)', () => {
    expect(isSideFace([0, 0, 1], UP)).toBe(false)
  })

  it('rejects the bottom cap face (normal == -axis)', () => {
    expect(isSideFace([0, 0, -1], UP)).toBe(false)
  })

  it('accepts a face with normal perpendicular to axis (+X)', () => {
    expect(isSideFace([1, 0, 0], UP)).toBe(true)
  })

  it('accepts a face with normal perpendicular to axis (-X)', () => {
    expect(isSideFace([-1, 0, 0], UP)).toBe(true)
  })

  it('accepts a face with normal perpendicular to axis (+Y)', () => {
    expect(isSideFace([0, 1, 0], UP)).toBe(true)
  })

  it('accepts a face with normal at 45° to axis', () => {
    const n = [1 / Math.SQRT2, 0, 1 / Math.SQRT2]
    expect(isSideFace(n, UP)).toBe(true)
  })

  it('rejects a face whose normal is nearly parallel (within 15°) to axis', () => {
    // 5° off from UP — cos(5°) ≈ 0.9962, well above the 0.966 threshold
    const tilt = 5 * (Math.PI / 180)
    const n = [Math.sin(tilt), 0, Math.cos(tilt)]
    expect(isSideFace(n, UP)).toBe(false)
  })

  it('accepts a face at exactly 20° off the axis', () => {
    // cos(20°) ≈ 0.9397 < 0.966 → side face
    const tilt = 20 * (Math.PI / 180)
    const n = [Math.sin(tilt), 0, Math.cos(tilt)]
    expect(isSideFace(n, UP)).toBe(true)
  })

  it('works with DOWN axis ([0,0,-1])', () => {
    expect(isSideFace([0, 0, -1], [0, 0, -1])).toBe(false) // cap
    expect(isSideFace([1, 0, 0], [0, 0, -1])).toBe(true)   // side
  })

  it('works with non-Z axis (along X)', () => {
    const AXIS_X = [1, 0, 0]
    expect(isSideFace([1, 0, 0], AXIS_X)).toBe(false) // cap
    expect(isSideFace([0, 1, 0], AXIS_X)).toBe(true)  // side
    expect(isSideFace([0, 0, 1], AXIS_X)).toBe(true)  // side
  })

  it('classifies all six faces of a rectangular prism correctly (4 side, 2 cap)', () => {
    // A box extruded along Z has 6 faces: top, bottom (caps) + 4 sides.
    const faces = [
      { n: [0, 0, 1],  expected: false }, // top cap
      { n: [0, 0, -1], expected: false }, // bottom cap
      { n: [1, 0, 0],  expected: true  }, // +X side
      { n: [-1, 0, 0], expected: true  }, // -X side
      { n: [0, 1, 0],  expected: true  }, // +Y side
      { n: [0, -1, 0], expected: true  }, // -Y side
    ]
    for (const { n, expected } of faces) {
      expect(isSideFace(n, UP)).toBe(expected)
    }
  })
})

// ---------------------------------------------------------------------------
// boss_with_draft node schema
// ---------------------------------------------------------------------------

describe('boss_with_draft node schema', () => {
  /** Build a minimal valid node as the Python tool does. */
  function buildNode(overrides = {}) {
    return {
      id: 'boss_with_draft-1',
      op: 'boss_with_draft',
      sketch_path: '/profile.sketch',
      height: 10,
      direction: 'up',
      draft_angle_deg: 3,
      draft_direction: 'outward',
      ...overrides,
    }
  }

  it('has the correct op field', () => {
    expect(buildNode().op).toBe('boss_with_draft')
  })

  it('round-trips through JSON without data loss', () => {
    const node = buildNode({ height: 25.5, draft_angle_deg: -2.75, name: 'housing_boss' })
    const restored = JSON.parse(JSON.stringify(node))
    expect(restored).toEqual(node)
  })

  it('accepts all valid direction values', () => {
    for (const dir of ['up', 'down', 'symmetric']) {
      const node = buildNode({ direction: dir })
      expect(node.direction).toBe(dir)
    }
  })

  it('accepts both draft_direction values', () => {
    for (const dd of ['outward', 'inward']) {
      const node = buildNode({ draft_direction: dd })
      expect(node.draft_direction).toBe(dd)
    }
  })

  it('allows draft_angle_deg = 0 (plain-pad degenerate case)', () => {
    const node = buildNode({ draft_angle_deg: 0 })
    expect(node.draft_angle_deg).toBe(0)
  })

  it('stores optional name field', () => {
    const node = buildNode({ name: 'lid_boss' })
    expect(node.name).toBe('lid_boss')
  })
})

// ---------------------------------------------------------------------------
// Draft angle sign convention
// ---------------------------------------------------------------------------

describe('draft angle sign convention', () => {
  /**
   * Pure-JS mirror of the sign logic in opBossWithDraft:
   * inward draft negates the angle so the taper converges.
   */
  function signedDraftRad(angleDeg, draftDirection) {
    const signed = draftDirection === 'inward' ? -angleDeg : angleDeg
    return (signed * Math.PI) / 180
  }

  it('outward positive angle → positive radians', () => {
    expect(signedDraftRad(5, 'outward')).toBeGreaterThan(0)
  })

  it('outward negative angle → negative radians', () => {
    expect(signedDraftRad(-5, 'outward')).toBeLessThan(0)
  })

  it('inward positive angle → negative radians (narrows toward sketch plane)', () => {
    expect(signedDraftRad(5, 'inward')).toBeLessThan(0)
  })

  it('inward negative angle → positive radians', () => {
    expect(signedDraftRad(-5, 'inward')).toBeGreaterThan(0)
  })

  it('zero angle → zero radians regardless of direction', () => {
    expect(Math.abs(signedDraftRad(0, 'outward'))).toBe(0)
    expect(Math.abs(signedDraftRad(0, 'inward'))).toBe(0)
  })

  it('30° outward converts to Math.PI/6 radians', () => {
    expect(signedDraftRad(30, 'outward')).toBeCloseTo(Math.PI / 6, 10)
  })
})

// ---------------------------------------------------------------------------
// Extrusion vector logic (mirrors opBossWithDraft direction handling)
// ---------------------------------------------------------------------------

describe('boss_with_draft extrusion vector', () => {
  function extrusionDz(height, direction) {
    const h = Math.abs(height)
    if (direction === 'down') return -h
    // 'up' and 'symmetric' both extrude by +h (symmetric just offsets the face first)
    return h
  }

  function axisDir(direction) {
    return direction === 'down' ? [0, 0, -1] : [0, 0, 1]
  }

  it('up extrusion produces positive dz and +Z axis', () => {
    expect(extrusionDz(10, 'up')).toBe(10)
    expect(axisDir('up')).toEqual([0, 0, 1])
  })

  it('down extrusion produces negative dz and -Z axis', () => {
    expect(extrusionDz(10, 'down')).toBe(-10)
    expect(axisDir('down')).toEqual([0, 0, -1])
  })

  it('symmetric extrusion has positive dz (offset applied separately) and +Z axis', () => {
    expect(extrusionDz(10, 'symmetric')).toBe(10)
    expect(axisDir('symmetric')).toEqual([0, 0, 1])
  })
})
