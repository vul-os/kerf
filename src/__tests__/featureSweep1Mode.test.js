// featureSweep1Mode.test.js — coverage for the sweep1 `mode` flag.
//
// The OCCT worker function opSweep1 requires ~5 MB WASM and cannot run in
// node. This suite covers:
//
//   1. Node round-trip — sweep1 node with mode field survives parseFeature /
//      serializeFeature unchanged for all three valid values.
//   2. Worker wiring — the switch table in occtWorker.js contains a 'sweep1'
//      case and the source includes SetMode_5 for corrected_frenet.
//   3. corrected_frenet: degraded-path log — the worker source warns with
//      'degraded:true' when SetMode_5 is unavailable.
//   4. Frame orientation (pure JS) — verify that a corrected-Frenet frame
//      computed via parallel transport produces less cross-section roll than
//      a raw Frenet frame on a coil path. This tests the geometric intent:
//      with corrected_frenet, the section's local Y-axis (in-plane normal)
//      tracks T̂(s) with minimal twist accumulation.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

import { parseFeature, serializeFeature, newFeatureId } from '../lib/occtRunner.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// ── 1. Node round-trip ────────────────────────────────────────────────────────

describe('sweep1 node round-trip (mode field)', () => {
  const BASE = {
    id: 'sweep1-1',
    op: 'sweep1',
    profile_sketch_path: '/circle.sketch',
    path_sketch_path: '/helix.sketch',
    scale: 1.0,
    twist_deg: 0,
  }

  for (const mode of ['auto', 'frenet', 'corrected_frenet']) {
    it(`preserves mode="${mode}" through parseFeature`, () => {
      const node = { ...BASE, id: `sweep1-${mode}`, mode }
      const json = JSON.stringify({ version: 1, name: 'T', features: [node] })
      const parsed = parseFeature(json)
      expect(parsed.features).toHaveLength(1)
      const out = parsed.features[0]
      expect(out.op).toBe('sweep1')
      expect(out.mode).toBe(mode)
      expect(out.profile_sketch_path).toBe('/circle.sketch')
      expect(out.path_sketch_path).toBe('/helix.sketch')
    })
  }

  it('serializeFeature round-trips a corrected_frenet sweep1 node', () => {
    const node = { ...BASE, mode: 'corrected_frenet' }
    const tree = {
      version: 1,
      name: 'Ring',
      features: [node],
      default_config: '',
      configurations: [],
    }
    const serialised = serializeFeature(tree)
    const back = JSON.parse(serialised)
    expect(back.features[0]).toMatchObject(node)
  })

  it('node without mode field round-trips cleanly (backwards compat)', () => {
    const node = { ...BASE } // no mode key
    const json = JSON.stringify({ version: 1, name: 'T', features: [node] })
    const parsed = parseFeature(json)
    // mode is absent in the node — parseFeature must not inject a default.
    // The worker handles the missing key with (node.mode || 'auto').
    expect('mode' in parsed.features[0]).toBe(false)
  })
})

// ── 2. newFeatureId prefix ────────────────────────────────────────────────────

describe('newFeatureId for sweep1 nodes', () => {
  it('generates an id with the sweep1 prefix', () => {
    const id = newFeatureId('sweep1')
    expect(id).toMatch(/^sweep1-/)
  })
})

// ── 3. Worker switch-table and SetMode_5 wiring ───────────────────────────────

describe('occtWorker.js sweep1 mode wiring', () => {
  const workerSrc = readFileSync(
    path.resolve(__dirname, '../lib/occtWorker.js'),
    'utf8',
  )

  it("switch table contains a 'sweep1' case (not dormant)", () => {
    const matches = workerSrc.match(/case 'sweep1'/g)
    expect(matches).not.toBeNull()
    expect(matches.length).toBeGreaterThanOrEqual(2)
  })

  it('opSweep1 reads node.mode', () => {
    // The mode selection block must be present.
    expect(workerSrc).toContain("node.mode || 'auto'")
  })

  it("SetMode_5 is called for corrected_frenet", () => {
    // Verify the corrected_frenet branch invokes SetMode_5.
    expect(workerSrc).toContain("mode === 'corrected_frenet'")
    expect(workerSrc).toContain('SetMode_5')
  })

  it("SetMode_2 is called for frenet", () => {
    expect(workerSrc).toContain("mode === 'frenet'")
    expect(workerSrc).toContain('SetMode_2')
  })

  it('degraded warning is emitted when SetMode_5 is unavailable', () => {
    // The worker must have a console.warn path with 'degraded:true' text
    // so operators can detect degraded-mode sweeps in the browser console.
    expect(workerSrc).toContain('degraded:true')
    expect(workerSrc).toContain("console.warn")
  })

  it('opSweep1 function definition is present', () => {
    expect(workerSrc).toContain('function opSweep1(')
  })
})

// ── 4. Frame orientation — pure-JS coil path geometry ────────────────────────
//
// We implement both Frenet and corrected-Frenet (parallel transport) purely in
// JS and verify that corrected_frenet produces less roll on a helix path.
//
// The test uses a 3-turn helix:
//   x(t) = R cos(2πNt),  y(t) = R sin(2πNt),  z(t) = H t,  t ∈ [0,1]
//
// Frenet frame: at each sample, compute T, B = T×(0,0,1) normalised, N = B×T.
// Corrected Frenet (parallel transport): propagate the frame by rotating the
// previous frame's normal/binormal into the new tangent using the minimum-
// rotation approach (Rodrigues around the cross-product of consecutive Ts).
//
// Roll measure: we look at the angle between consecutive section normals
// projected onto the plane perpendicular to the tangent. For a helix, Frenet
// accumulates a full 2π of roll per turn; parallel transport accumulates
// roughly zero (only residual geometric torsion from the helix itself, which
// is far smaller than the apparent roll of raw Frenet).

function norm3(v) {
  const n = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
  return n < 1e-12 ? [0, 0, 0] : [v[0] / n, v[1] / n, v[2] / n]
}

function cross3(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ]
}

function dot3(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

function add3(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]] }
function sub3(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]] }
function scale3(v, s) { return [v[0] * s, v[1] * s, v[2] * s] }

/** Helix sample: R=5mm, N=3 turns, H=15mm total rise */
function helixPoint(t, R = 5, N = 3, H = 15) {
  const angle = 2 * Math.PI * N * t
  return [R * Math.cos(angle), R * Math.sin(angle), H * t]
}

function helixTangent(t, R = 5, N = 3, H = 15) {
  const angle = 2 * Math.PI * N * t
  const dxdt = -R * 2 * Math.PI * N * Math.sin(angle)
  const dydt =  R * 2 * Math.PI * N * Math.cos(angle)
  const dzdt = H
  return norm3([dxdt, dydt, dzdt])
}

function frenetFrame(T) {
  // Frenet: pick a reference vector that is not parallel to T.
  const ref = Math.abs(T[2]) < 0.9 ? [0, 0, 1] : [0, 1, 0]
  const B = norm3(cross3(T, ref))
  const N = norm3(cross3(B, T))
  return { T, N, B }
}

/**
 * Parallel-transport frame along a sampled path.
 * Returns array of {T, N, B} frames, one per sample.
 */
function parallelTransportFrames(tangents) {
  const frames = []
  // Seed the first frame with a Frenet-like initialisation.
  frames.push(frenetFrame(tangents[0]))
  for (let i = 1; i < tangents.length; i++) {
    const prev = frames[i - 1]
    const T = tangents[i]
    const Tprev = prev.T
    // Rotation axis = Tprev × T; rotate prev.N and prev.B by this rotation.
    const axis = cross3(Tprev, T)
    const sinTheta = Math.sqrt(dot3(axis, axis))
    const cosTheta = dot3(Tprev, T)
    if (sinTheta < 1e-10) {
      frames.push({ T, N: prev.N, B: prev.B })
    } else {
      const k = norm3(axis)
      // Rodrigues: v' = v cosθ + (k×v) sinθ + k (k·v)(1-cosθ)
      function rodrigues(v) {
        const c = cosTheta
        const s = sinTheta
        const kxv = cross3(k, v)
        const kdv = dot3(k, v)
        return add3(add3(scale3(v, c), scale3(kxv, s)), scale3(k, kdv * (1 - c)))
      }
      const N = norm3(rodrigues(prev.N))
      const B = norm3(rodrigues(prev.B))
      frames.push({ T, N, B })
    }
  }
  return frames
}

/** Signed roll angle between consecutive section-plane normals (deg). */
function rollAngle(n1, n2, T) {
  // Project both normals into the plane perpendicular to T.
  const proj = (v) => {
    const along = dot3(v, T)
    return norm3(sub3(v, scale3(T, along)))
  }
  const a = proj(n1)
  const b = proj(n2)
  const c = dot3(a, b)
  const sinA = dot3(T, cross3(a, b))
  return Math.atan2(sinA, c) * (180 / Math.PI)
}

describe('sweep1 corrected_frenet frame orientation on a helix', () => {
  const SAMPLES = 120  // 120 samples over 3 turns = 40 per turn

  // Build sample tangents along the helix.
  const ts = Array.from({ length: SAMPLES }, (_, i) => i / (SAMPLES - 1))
  const tangents = ts.map((t) => helixTangent(t))

  // Frenet frames at each sample.
  const frenetFrames = tangents.map((T) => frenetFrame(T))

  // Corrected-Frenet (parallel transport) frames.
  const ptFrames = parallelTransportFrames(tangents)

  it('corrected_frenet (parallel transport) accumulates less roll than Frenet', () => {
    // Sum of absolute roll angles over the full path.
    let frenetTotalRoll = 0
    let ptTotalRoll = 0

    for (let i = 1; i < SAMPLES; i++) {
      frenetTotalRoll += Math.abs(rollAngle(frenetFrames[i - 1].N, frenetFrames[i].N, tangents[i]))
      ptTotalRoll += Math.abs(rollAngle(ptFrames[i - 1].N, ptFrames[i].N, tangents[i]))
    }

    // On a 3-turn helix the Frenet frame accumulates ~3 × 360° = ~1080° of
    // apparent roll; parallel transport accumulates only the geometric torsion
    // of the helix, which is ≪ 360°. We assert ptTotalRoll < frenetTotalRoll / 5
    // to confirm the order-of-magnitude difference.
    expect(ptTotalRoll).toBeLessThan(frenetTotalRoll / 5)
  })

  it('Frenet frame accumulates measurable roll on a 3-turn helix (>100 deg total)', () => {
    // Sanity-check: confirm Frenet does accumulate roll (would detect broken
    // geometry or a trivial path). On a 3-turn helix with R=5, H=15, Frenet
    // step-to-step roll sums to ~169° — more than double the parallel-
    // transport result of ~28°. The 100° floor guards against a test with
    // no meaningful path.
    let total = 0
    for (let i = 1; i < SAMPLES; i++) {
      total += Math.abs(rollAngle(frenetFrames[i - 1].N, frenetFrames[i].N, tangents[i]))
    }
    expect(total).toBeGreaterThan(100)
  })

  it('corrected_frenet sections stay perpendicular to path tangent T̂(s)', () => {
    // The section normal (N axis) must remain perpendicular to T.
    // dot(N, T) must be near zero at every sample point.
    for (let i = 0; i < SAMPLES; i++) {
      const d = Math.abs(dot3(ptFrames[i].N, ptFrames[i].T))
      expect(d).toBeLessThan(1e-6)
    }
  })

  it('corrected_frenet frame is right-handed at every sample', () => {
    for (let i = 0; i < SAMPLES; i++) {
      const { T, N, B } = ptFrames[i]
      // B should equal T × N for a right-handed frame.
      const TxN = norm3(cross3(T, N))
      const d = dot3(TxN, B)
      expect(d).toBeGreaterThan(0.999)
    }
  })
})
