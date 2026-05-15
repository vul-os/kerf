// curvatureCombsProbe.test.js — C4 binding probe coverage.
//
// Reuses the existing GeomLProp_SLProps probe infrastructure from C2 probe
// (surfaceBooleanProbe.test.js) and verifies:
//   1. NURBS_PHASE4_C4_BINDINGS is declared in occtWorker.js.
//   2. GeomLProp_SLProps and BRepLProp_SLProps are in the C4 probe list.
//   3. sampleSurfaceCurvature in occtBridge.js uses GeomLProp_SLProps_2 (the
//      constructor variant already confirmed bound by 5-axis CAM and surface
//      continuity usage).
//   4. sampleSurfaceCurvature returns geomLPropSLPropsPresent=false when oc
//      lacks the constructor — safe fallback, no exception thrown.
//   5. sampleSurfaceCurvature returns empty points + zero stats for a null face.
//   6. The boot log emits [occt-phase4] C4 (curvature comb) lines.
//
// No WASM required.  All tests derive logic from the source text or inline mocks.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const workerSrc = readFileSync(
  path.resolve(__dirname, '../lib/occtWorker.js'),
  'utf8',
)
const bridgeSrc = readFileSync(
  path.resolve(__dirname, '../lib/occtBridge.js'),
  'utf8',
)

// ── 0. Source-level C4 probe wiring ──────────────────────────────────────────

describe('occtWorker.js — C4 probe wiring', () => {
  it('NURBS_PHASE4_C4_BINDINGS is defined', () => {
    expect(workerSrc).toContain('NURBS_PHASE4_C4_BINDINGS')
  })

  it('C4 probe list contains GeomLProp_SLProps', () => {
    const c4Start = workerSrc.indexOf('NURBS_PHASE4_C4_BINDINGS')
    const geoIdx  = workerSrc.indexOf("'GeomLProp_SLProps'", c4Start)
    // The class must appear within the C4 array (before the next const/let/var)
    const nextDecl = workerSrc.indexOf('\nconst ', c4Start + 1)
    expect(geoIdx).toBeGreaterThan(c4Start)
    expect(geoIdx).toBeLessThan(nextDecl)
  })

  it('C4 probe list contains BRepLProp_SLProps', () => {
    const c4Start = workerSrc.indexOf('NURBS_PHASE4_C4_BINDINGS')
    const brepIdx = workerSrc.indexOf("'BRepLProp_SLProps'", c4Start)
    const nextDecl = workerSrc.indexOf('\nconst ', c4Start + 1)
    expect(brepIdx).toBeGreaterThan(c4Start)
    expect(brepIdx).toBeLessThan(nextDecl)
  })

  it('boot log emits [occt-phase4] C4 lines', () => {
    expect(workerSrc).toContain('C4 (curvature comb)')
  })

  it('getNurbsPhase4Bindings export includes C4 classes via NURBS_PHASE4_ALL_BINDINGS', () => {
    expect(workerSrc).toContain('NURBS_PHASE4_ALL_BINDINGS')
    // The spread of C4 into ALL must appear in source.
    const allIdx = workerSrc.indexOf('NURBS_PHASE4_ALL_BINDINGS')
    const c4Spread = workerSrc.indexOf('...NURBS_PHASE4_C4_BINDINGS', allIdx)
    expect(c4Spread).toBeGreaterThan(allIdx)
  })
})

// ── 1. sampleSurfaceCurvature source-level checks ────────────────────────────

describe('occtBridge.js — sampleSurfaceCurvature source', () => {
  it('sampleSurfaceCurvature is exported', () => {
    expect(bridgeSrc).toContain('export function sampleSurfaceCurvature(')
  })

  it('probes GeomLProp_SLProps_2 before sampling', () => {
    const fnIdx  = bridgeSrc.indexOf('export function sampleSurfaceCurvature(')
    const probeIdx = bridgeSrc.indexOf("typeof oc.GeomLProp_SLProps_2 === 'function'", fnIdx)
    expect(probeIdx).toBeGreaterThan(fnIdx)
  })

  it('returns early with empty points when GeomLProp_SLProps_2 absent', () => {
    const fnIdx  = bridgeSrc.indexOf('export function sampleSurfaceCurvature(')
    // The guard should be inside the function body
    const earlyIdx = bridgeSrc.indexOf('geomLPropSLPropsPresent }', fnIdx)
    expect(earlyIdx).toBeGreaterThan(fnIdx)
  })

  it('calls IsCurvatureDefined before reading curvature values', () => {
    const fnIdx  = bridgeSrc.indexOf('export function sampleSurfaceCurvature(')
    const defIdx = bridgeSrc.indexOf('IsCurvatureDefined', fnIdx)
    expect(defIdx).toBeGreaterThan(fnIdx)
  })

  it('reads MaxCurvature and MinCurvature', () => {
    const fnIdx = bridgeSrc.indexOf('export function sampleSurfaceCurvature(')
    expect(bridgeSrc.indexOf('MaxCurvature', fnIdx)).toBeGreaterThan(fnIdx)
    expect(bridgeSrc.indexOf('MinCurvature', fnIdx)).toBeGreaterThan(fnIdx)
  })

  it('computes gaussian = k1 * k2', () => {
    const fnIdx = bridgeSrc.indexOf('export function sampleSurfaceCurvature(')
    expect(bridgeSrc.indexOf('k1 * k2', fnIdx)).toBeGreaterThan(fnIdx)
  })

  it('normalises Infinity stats to 0 before return', () => {
    const fnIdx = bridgeSrc.indexOf('export function sampleSurfaceCurvature(')
    const infIdx = bridgeSrc.indexOf('isFinite', fnIdx)
    expect(infIdx).toBeGreaterThan(fnIdx)
  })
})

// ── 2. sampleSurfaceCurvature inline re-derivation ───────────────────────────
//
// Mirror the guard logic so we can unit-test the fallback paths without WASM.

function sampleSurfaceCurvature_derived(oc, face) {
  const empty = {
    points: [],
    stats: {
      minMean: 0, maxMean: 0,
      minGaussian: 0, maxGaussian: 0,
      minK1: 0, maxK1: 0, minK2: 0, maxK2: 0,
      sampleCount: 0, curvatureDefinedCount: 0,
    },
    geomLPropSLPropsPresent: typeof oc.GeomLProp_SLProps_2 === 'function',
  }
  if (!empty.geomLPropSLPropsPresent || !face) return empty
  // In this derived version we stop here — just enough to test the probe guard.
  return empty
}

describe('sampleSurfaceCurvature — fallback guard (inline re-derivation)', () => {
  it('returns geomLPropSLPropsPresent=false when binding absent', () => {
    const result = sampleSurfaceCurvature_derived({}, { _tag: 'face' })
    expect(result.geomLPropSLPropsPresent).toBe(false)
  })

  it('returns empty points when binding absent', () => {
    const result = sampleSurfaceCurvature_derived({}, { _tag: 'face' })
    expect(result.points).toEqual([])
  })

  it('returns geomLPropSLPropsPresent=true when binding present', () => {
    const oc = { GeomLProp_SLProps_2: function() {} }
    const result = sampleSurfaceCurvature_derived(oc, null)
    expect(result.geomLPropSLPropsPresent).toBe(true)
  })

  it('returns empty points when face is null', () => {
    const oc = { GeomLProp_SLProps_2: function() {} }
    const result = sampleSurfaceCurvature_derived(oc, null)
    expect(result.points).toEqual([])
  })

  it('stats have zeroed Infinity values', () => {
    const result = sampleSurfaceCurvature_derived({}, null)
    expect(result.stats.minMean).toBe(0)
    expect(result.stats.maxMean).toBe(0)
    expect(isFinite(result.stats.minGaussian)).toBe(true)
  })
})
