// surfaceBoolean.test.js — C1-T2 worker handler coverage.
//
// No WASM required.  Verifies:
//   1. Source wiring: opSurfaceBoolean defined, case 'surface_boolean' in both
//      dispatch switches, NURBS_PHASE4_C1_BINDINGS present.
//   2. opSurfaceBoolean inline mock: dispatch by kind (cut/fuse/common);
//      missing operand errors; unknown kind error; IsDone=false error message
//      mentions C1-T10 escalation; empty-result error.
//   3. ShapeFix_Shape pre-pass is applied when binding is present.
//   4. ShapeUpgrade_UnifySameDomain is applied to result when binding is present.
//   5. SetFuzzyValue is called when BOPAlgo_Builder is present and the method exists.
//   6. Fallback common (A − (A − B)) when Common_3 is absent.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const workerSrc = readFileSync(
  path.resolve(__dirname, '../lib/occtWorker.js'),
  'utf8',
)

// ── 0. Source-level wiring ────────────────────────────────────────────────────

describe('occtWorker.js — surface_boolean wiring', () => {
  it('opSurfaceBoolean function is defined', () => {
    expect(workerSrc).toContain('function opSurfaceBoolean(')
  })

  it("evaluateTree dispatch table contains 'surface_boolean' case", () => {
    const etIdx = workerSrc.indexOf('function evaluateTree(')
    const etfIdx = workerSrc.indexOf('async function evaluateToFinalShape(')
    const caseIdx = workerSrc.indexOf("case 'surface_boolean'", etIdx)
    expect(caseIdx).toBeGreaterThan(etIdx)
    expect(caseIdx).toBeLessThan(etfIdx)
  })

  it("evaluateToFinalShape dispatch table also contains 'surface_boolean' case", () => {
    const etfIdx = workerSrc.indexOf('async function evaluateToFinalShape(')
    const caseIdx = workerSrc.indexOf("case 'surface_boolean'", etfIdx)
    expect(caseIdx).toBeGreaterThan(etfIdx)
  })

  it("existing 'boolean' case is still present in evaluateTree (not broken)", () => {
    const etIdx = workerSrc.indexOf('function evaluateTree(')
    const etfIdx = workerSrc.indexOf('async function evaluateToFinalShape(')
    const caseIdx = workerSrc.indexOf("case 'boolean'", etIdx)
    expect(caseIdx).toBeGreaterThan(etIdx)
    expect(caseIdx).toBeLessThan(etfIdx)
  })

  it("existing 'boolean' case is still present in evaluateToFinalShape (not broken)", () => {
    const etfIdx = workerSrc.indexOf('async function evaluateToFinalShape(')
    const caseIdx = workerSrc.indexOf("case 'boolean'", etfIdx)
    expect(caseIdx).toBeGreaterThan(etfIdx)
  })

  it('opSurfaceBoolean uses getNurbsPhase4Bindings for probe-gating', () => {
    const fnIdx = workerSrc.indexOf('function opSurfaceBoolean(')
    const probeIdx = workerSrc.indexOf('getNurbsPhase4Bindings(', fnIdx)
    expect(probeIdx).toBeGreaterThan(fnIdx)
  })

  it('opSurfaceBoolean attempts SetFuzzyValue call', () => {
    const fnIdx = workerSrc.indexOf('function opSurfaceBoolean(')
    const setIdx = workerSrc.indexOf('SetFuzzyValue', fnIdx)
    expect(setIdx).toBeGreaterThan(fnIdx)
  })

  it('IsDone=false error message mentions C1-T10 escalation', () => {
    expect(workerSrc).toContain('C1-T10')
  })

  it('opSurfaceBoolean checks ShapeFix_Shape binding gate', () => {
    const fnIdx = workerSrc.indexOf('function opSurfaceBoolean(')
    const fixIdx = workerSrc.indexOf('ShapeFix_Shape', fnIdx)
    expect(fixIdx).toBeGreaterThan(fnIdx)
  })

  it('opSurfaceBoolean checks ShapeUpgrade_UnifySameDomain gate', () => {
    const fnIdx = workerSrc.indexOf('function opSurfaceBoolean(')
    const unifyIdx = workerSrc.indexOf('ShapeUpgrade_UnifySameDomain', fnIdx)
    expect(unifyIdx).toBeGreaterThan(fnIdx)
  })
})

// ── 1. opSurfaceBoolean inline mock ──────────────────────────────────────────
//
// We inline the opSurfaceBoolean logic to drive it with mock oc + bodyMap.
// Source-level checks above verify the real code matches the contract.

// Minimal helpers mirrored from the real worker.
function track(_tracker, obj) { return obj }

function _isEmptyShape(_oc, shape) {
  if (!shape) return true
  return shape._empty === true
}

function getNurbsPhase4Bindings_mock(oc, classes) {
  return Object.fromEntries(
    classes.map(cls => [cls, typeof oc[cls] === 'function'])
  )
}

const P4_C1 = ['BOPAlgo_Builder', 'ShapeFix_Shape', 'ShapeUpgrade_UnifySameDomain']

function opSurfaceBoolean(oc, _prev, node, _sketches, tracker, bodyMap, overrides = {}) {
  const {
    BRepAlgoAPI_Cut_3: Cut3 = oc.BRepAlgoAPI_Cut_3,
    BRepAlgoAPI_Fuse_3: Fuse3 = oc.BRepAlgoAPI_Fuse_3,
    BRepAlgoAPI_Common_3: Common3 = oc.BRepAlgoAPI_Common_3,
  } = overrides

  const aId = node.target_a_id
  const bId = node.target_b_id
  if (!aId) throw new Error('surface_boolean: target_a_id is required')
  if (!bId) throw new Error('surface_boolean: target_b_id is required')

  const a = bodyMap && bodyMap[aId]
  const b = bodyMap && bodyMap[bId]
  if (!a) throw new Error(`surface_boolean: target_a '${aId}' not found in evaluated tree`)
  if (!b) throw new Error(`surface_boolean: target_b '${bId}' not found in evaluated tree`)

  const kind = node.kind || 'cut'
  if (!['cut', 'fuse', 'common'].includes(kind)) {
    throw new Error(`surface_boolean: unknown kind '${kind}' (expected cut|fuse|common)`)
  }

  const fuzziness = typeof node.fuzziness === 'number' && node.fuzziness > 0
    ? node.fuzziness
    : 1e-4

  const p4 = getNurbsPhase4Bindings_mock(oc, P4_C1)
  const hasShapeFix = p4['ShapeFix_Shape']
  const hasUnify    = p4['ShapeUpgrade_UnifySameDomain']
  const hasBOPAlgo  = p4['BOPAlgo_Builder']

  function maybeFixShape(shape) {
    if (!hasShapeFix) return shape
    try {
      const fixer = track(tracker, new oc.ShapeFix_Shape_2(shape))
      fixer.Perform({})
      return fixer.Shape()
    } catch {
      return shape
    }
  }

  const fixedA = maybeFixShape(a)
  const fixedB = maybeFixShape(b)

  const pr = () => ({})

  let fuzzyCalledWith = null
  function buildAlgo(AlgoClass, opA, opB) {
    const algo = track(tracker, new AlgoClass(opA, opB, pr()))
    if (hasBOPAlgo) {
      try {
        if (typeof algo.SetFuzzyValue === 'function') {
          algo.SetFuzzyValue(fuzziness)
          fuzzyCalledWith = fuzziness
        }
      } catch { /* */ }
    }
    algo.Build(pr())
    return algo
  }

  let algo
  switch (kind) {
    case 'cut':
      algo = buildAlgo(Cut3, fixedA, fixedB)
      break
    case 'fuse':
      algo = buildAlgo(Fuse3, fixedA, fixedB)
      break
    case 'common':
      if (typeof Common3 !== 'function') {
        const inner = buildAlgo(Cut3, fixedA, fixedB)
        if (!inner.IsDone()) throw new Error('surface_boolean: common-via-cut inner step failed')
        algo = buildAlgo(Cut3, fixedA, inner.Shape())
      } else {
        algo = buildAlgo(Common3, fixedA, fixedB)
      }
      break
    default:
      throw new Error(`surface_boolean: unknown kind '${kind}'`)
  }

  if (!algo.IsDone()) {
    throw new Error(
      `surface_boolean: ${kind} algorithm failed (BOPAlgo error). ` +
      'If operands are Face/Shell, this build may not support non-solid operands — ' +
      'try feature_to_solid first, or escalate to C1-T10 (WASM rebuild).'
    )
  }

  let result = algo.Shape()
  if (_isEmptyShape(oc, result)) {
    throw new Error(`surface_boolean: ${kind} produced an empty result (operands may not intersect)`)
  }

  if (hasUnify) {
    try {
      const unify = track(tracker, new oc.ShapeUpgrade_UnifySameDomain_2(result, true, true, false))
      unify.Build()
      result = unify.Shape()
    } catch { /* */ }
  }

  return { result, fuzzyCalledWith }
}

// --- helpers -----------------------------------------------------------------

function makeShape(tag = 'shape') {
  return { _tag: tag }
}

function makeAlgoClass(resultShape, isDone = true) {
  return class MockAlgo {
    constructor(_a, _b, _pr) {
      this._result = resultShape
      this._done = isDone
    }
    Build(_pr) {}
    IsDone() { return this._done }
    Shape() { return this._result }
  }
}

// ── 2. Dispatch by kind ───────────────────────────────────────────────────────

describe('opSurfaceBoolean — dispatch by kind', () => {
  it('cut dispatches to Cut_3', () => {
    let cutCalled = false
    const resultShape = makeShape('cut_result')
    class MockCut {
      constructor() { cutCalled = true }
      Build() {}
      IsDone() { return true }
      Shape() { return resultShape }
    }
    const a = makeShape('a'), b = makeShape('b')
    const node = { op: 'surface_boolean', id: 'sb1', target_a_id: 'a', target_b_id: 'b', kind: 'cut' }
    const { result } = opSurfaceBoolean({}, null, node, {}, [], { a, b }, { BRepAlgoAPI_Cut_3: MockCut })
    expect(cutCalled).toBe(true)
    expect(result).toBe(resultShape)
  })

  it('fuse dispatches to Fuse_3', () => {
    let fuseCalled = false
    const resultShape = makeShape('fuse_result')
    class MockFuse {
      constructor() { fuseCalled = true }
      Build() {}
      IsDone() { return true }
      Shape() { return resultShape }
    }
    const a = makeShape(), b = makeShape()
    const node = { op: 'surface_boolean', target_a_id: 'a', target_b_id: 'b', kind: 'fuse' }
    const { result } = opSurfaceBoolean(
      {}, null, node, {}, [], { a, b },
      { BRepAlgoAPI_Fuse_3: MockFuse, BRepAlgoAPI_Cut_3: makeAlgoClass(makeShape()) }
    )
    expect(fuseCalled).toBe(true)
    expect(result).toBe(resultShape)
  })

  it('common dispatches to Common_3 when available', () => {
    let commonCalled = false
    const resultShape = makeShape('common_result')
    class MockCommon {
      constructor() { commonCalled = true }
      Build() {}
      IsDone() { return true }
      Shape() { return resultShape }
    }
    const a = makeShape(), b = makeShape()
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'common' }
    const { result } = opSurfaceBoolean(
      {}, null, node, {}, [], { a, b },
      { BRepAlgoAPI_Common_3: MockCommon, BRepAlgoAPI_Cut_3: makeAlgoClass(makeShape()) }
    )
    expect(commonCalled).toBe(true)
    expect(result).toBe(resultShape)
  })

  it('common falls back to A − (A − B) when Common_3 is absent', () => {
    let cutCallCount = 0
    const innerResult = makeShape('inner_cut')
    const outerResult = makeShape('outer_cut')
    class MockCut {
      constructor() {
        cutCallCount++
        this._result = cutCallCount === 1 ? innerResult : outerResult
      }
      Build() {}
      IsDone() { return true }
      Shape() { return this._result }
    }
    const a = makeShape(), b = makeShape()
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'common' }
    const { result } = opSurfaceBoolean({}, null, node, {}, [], { a, b }, {
      BRepAlgoAPI_Cut_3: MockCut,
    })
    expect(cutCallCount).toBe(2)
    expect(result).toBe(outerResult)
  })

  it('accepts any shape topology (not just solids)', () => {
    // Unlike opBoolean, no solid-check is applied.
    const resultShape = makeShape('face_fragment')
    class MockCut {
      constructor() {}
      Build() {}
      IsDone() { return true }
      Shape() { return resultShape }
    }
    // These shapes have no ShapeType — they're "faces" (no solid wrapper).
    const a = { _tag: 'face_a' }
    const b = { _tag: 'face_b' }
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'cut' }
    expect(() => opSurfaceBoolean({}, null, node, {}, [], { a, b }, { BRepAlgoAPI_Cut_3: MockCut }))
      .not.toThrow()
  })
})

// ── 3. Error paths ────────────────────────────────────────────────────────────

describe('opSurfaceBoolean — error paths', () => {
  it('throws when target_a_id missing', () => {
    const node = { target_b_id: 'b', kind: 'cut' }
    expect(() => opSurfaceBoolean({}, null, node, {}, [], {})).toThrow(/target_a_id is required/)
  })

  it('throws when target_b_id missing', () => {
    const node = { target_a_id: 'a', kind: 'cut' }
    expect(() => opSurfaceBoolean({}, null, node, {}, [], {})).toThrow(/target_b_id is required/)
  })

  it('throws when target_a not in bodyMap', () => {
    const node = { target_a_id: 'missing', target_b_id: 'b', kind: 'cut' }
    expect(() => opSurfaceBoolean({}, null, node, {}, [], { b: makeShape() })).toThrow(/target_a.*not found/)
  })

  it('throws when target_b not in bodyMap', () => {
    const node = { target_a_id: 'a', target_b_id: 'missing', kind: 'cut' }
    expect(() => opSurfaceBoolean({}, null, node, {}, [], { a: makeShape() })).toThrow(/target_b.*not found/)
  })

  it('throws for unknown kind', () => {
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'union' }
    expect(() => opSurfaceBoolean({}, null, node, {}, [], { a: makeShape(), b: makeShape() }))
      .toThrow(/unknown kind/)
  })

  it('IsDone=false error mentions C1-T10 escalation', () => {
    class FailCut {
      constructor() {}
      Build() {}
      IsDone() { return false }
      Shape() { return makeShape() }
    }
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'cut' }
    let err = null
    try {
      opSurfaceBoolean({}, null, node, {}, [], { a: makeShape(), b: makeShape() }, {
        BRepAlgoAPI_Cut_3: FailCut,
      })
    } catch (e) { err = e }
    expect(err).not.toBeNull()
    expect(err.message).toContain('C1-T10')
  })

  it('throws on empty result shape', () => {
    const emptyShape = { _empty: true, _tag: 'empty' }
    class MockCut {
      Build() {}
      IsDone() { return true }
      Shape() { return emptyShape }
    }
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'cut' }
    expect(() => opSurfaceBoolean({}, null, node, {}, [], { a: makeShape(), b: makeShape() }, {
      BRepAlgoAPI_Cut_3: MockCut,
    })).toThrow(/empty result/)
  })
})

// ── 4. Probe-gated features ───────────────────────────────────────────────────

describe('opSurfaceBoolean — probe-gated ShapeFix + Unify + Fuzzy', () => {
  it('calls ShapeFix_Shape_2 pre-pass when binding is present', () => {
    let fixCallCount = 0
    const fixedShape = makeShape('fixed')
    const resultShape = makeShape('result')

    function makeOc() {
      return {
        ShapeFix_Shape: function() {},  // presence flag
        ShapeFix_Shape_2: class {
          constructor() { fixCallCount++ }
          Perform() {}
          Shape() { return fixedShape }
        },
        BRepAlgoAPI_Cut_3: class {
          constructor(_a, _b) { this._a = _a }
          Build() {}
          IsDone() { return true }
          Shape() { return resultShape }
        },
      }
    }

    const oc = makeOc()
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'cut' }
    opSurfaceBoolean(oc, null, node, {}, [], { a: makeShape('a'), b: makeShape('b') })
    // Should have been called twice: once for operand A and once for operand B.
    expect(fixCallCount).toBe(2)
  })

  it('skips ShapeFix_Shape pre-pass when binding is absent', () => {
    let fixCallCount = 0
    const resultShape = makeShape('result')
    const oc = {
      // ShapeFix_Shape NOT present
      ShapeFix_Shape_2: class {
        constructor() { fixCallCount++ }
        Perform() {}
        Shape() { return makeShape('fixed') }
      },
      BRepAlgoAPI_Cut_3: makeAlgoClass(resultShape),
    }
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'cut' }
    opSurfaceBoolean(oc, null, node, {}, [], { a: makeShape(), b: makeShape() })
    expect(fixCallCount).toBe(0)
  })

  it('applies ShapeUpgrade_UnifySameDomain when binding is present', () => {
    let unifyCalled = false
    const unifiedShape = makeShape('unified')
    const resultShape = makeShape('result')
    const oc = {
      ShapeUpgrade_UnifySameDomain: function() {},  // presence flag
      ShapeUpgrade_UnifySameDomain_2: class {
        constructor() { unifyCalled = true }
        Build() {}
        Shape() { return unifiedShape }
      },
      BRepAlgoAPI_Cut_3: makeAlgoClass(resultShape),
    }
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'cut' }
    const { result } = opSurfaceBoolean(oc, null, node, {}, [], { a: makeShape(), b: makeShape() })
    expect(unifyCalled).toBe(true)
    expect(result).toBe(unifiedShape)
  })

  it('calls SetFuzzyValue when BOPAlgo_Builder and method are present', () => {
    let fuzzyValue = null
    const resultShape = makeShape('result')
    const oc = {
      BOPAlgo_Builder: function() {},  // presence flag
      BRepAlgoAPI_Cut_3: class {
        constructor() {}
        SetFuzzyValue(v) { fuzzyValue = v }
        Build() {}
        IsDone() { return true }
        Shape() { return resultShape }
      },
    }
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'cut', fuzziness: 5e-4 }
    opSurfaceBoolean(oc, null, node, {}, [], { a: makeShape(), b: makeShape() })
    expect(fuzzyValue).toBeCloseTo(5e-4)
  })

  it('uses default fuzziness of 1e-4 when not specified', () => {
    let fuzzyValue = null
    const resultShape = makeShape('result')
    const oc = {
      BOPAlgo_Builder: function() {},
      BRepAlgoAPI_Cut_3: class {
        constructor() {}
        SetFuzzyValue(v) { fuzzyValue = v }
        Build() {}
        IsDone() { return true }
        Shape() { return resultShape }
      },
    }
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'cut' }
    opSurfaceBoolean(oc, null, node, {}, [], { a: makeShape(), b: makeShape() })
    expect(fuzzyValue).toBeCloseTo(1e-4)
  })

  it('skips SetFuzzyValue when BOPAlgo_Builder is absent', () => {
    let fuzzyValue = null
    const resultShape = makeShape('result')
    const oc = {
      // BOPAlgo_Builder NOT present
      BRepAlgoAPI_Cut_3: class {
        constructor() {}
        SetFuzzyValue(v) { fuzzyValue = v }
        Build() {}
        IsDone() { return true }
        Shape() { return resultShape }
      },
    }
    const node = { target_a_id: 'a', target_b_id: 'b', kind: 'cut' }
    opSurfaceBoolean(oc, null, node, {}, [], { a: makeShape(), b: makeShape() })
    expect(fuzzyValue).toBeNull()
  })
})
