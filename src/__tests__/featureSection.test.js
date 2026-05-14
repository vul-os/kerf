// featureSection.test.js — coverage for Slicing v0.2 (plane cross-section).
//
// No WASM required. The suite verifies:
//
//   1. Source wiring (occtWorker.js): both dispatch tables contain 'section';
//      opSection is defined; the BRepAlgoAPI_Section binding probe / gate
//      comment is present.
//   2. opSection inline mock: binding gate fast-fail; missing target_solid_ref
//      error; plane validation errors; successful dispatch to the algo.
//   3. FeatureView inspector: FEATURE_KINDS contains a 'section' entry;
//      it is in the Modify category; defaults and fields match spec.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// ── 0. Source-level wiring checks ────────────────────────────────────────────

describe('occtWorker.js section wiring', () => {
  const workerSrc = readFileSync(
    path.resolve(__dirname, '../lib/occtWorker.js'),
    'utf8',
  )

  it("evaluateTree dispatch table contains 'section' case", () => {
    const etIdx  = workerSrc.indexOf('function evaluateTree(')
    const etfIdx = workerSrc.indexOf('async function evaluateToFinalShape(')
    const firstSection = workerSrc.indexOf("case 'section'")
    expect(firstSection).toBeGreaterThan(etIdx)
    expect(firstSection).toBeLessThan(etfIdx)
  })

  it("evaluateToFinalShape dispatch table also contains 'section' case", () => {
    const etfIdx = workerSrc.indexOf('async function evaluateToFinalShape(')
    const sectionAfterEtf = workerSrc.indexOf("case 'section'", etfIdx)
    expect(sectionAfterEtf).toBeGreaterThan(etfIdx)
  })

  it("evaluateTree still contains 'boolean' and 'to_solid' cases (no regressions)", () => {
    const etIdx  = workerSrc.indexOf('function evaluateTree(')
    const etfIdx = workerSrc.indexOf('async function evaluateToFinalShape(')
    const firstBoolean  = workerSrc.indexOf("case 'boolean'",  etIdx)
    const firstToSolid  = workerSrc.indexOf("case 'to_solid'", etIdx)
    expect(firstBoolean).toBeGreaterThan(etIdx)
    expect(firstBoolean).toBeLessThan(etfIdx)
    expect(firstToSolid).toBeGreaterThan(etIdx)
    expect(firstToSolid).toBeLessThan(etfIdx)
  })

  it('opSection function is defined', () => {
    expect(workerSrc).toContain('function opSection(')
  })

  it('BRepAlgoAPI_Section binding gate is present in opSection', () => {
    const opIdx = workerSrc.indexOf('function opSection(')
    const opBlock = workerSrc.slice(opIdx, opIdx + 3000)
    expect(opBlock).toContain('BRepAlgoAPI_Section')
    expect(opBlock).toContain('wasm binding missing')
  })

  it('opSection validates target_solid_ref', () => {
    const opIdx = workerSrc.indexOf('function opSection(')
    const opBlock = workerSrc.slice(opIdx, opIdx + 3000)
    expect(opBlock).toContain('target_solid_ref')
    expect(opBlock).toContain('not found in evaluated tree')
  })

  it('opSection uses gp_Pln and gp_Dir to build the cutting plane', () => {
    const opIdx = workerSrc.indexOf('function opSection(')
    const opBlock = workerSrc.slice(opIdx, opIdx + 3000)
    expect(opBlock).toContain('gp_Pln')
    expect(opBlock).toContain('gp_Dir')
  })

  it('opSection checks zero-magnitude normal', () => {
    const opIdx = workerSrc.indexOf('function opSection(')
    const opBlock = workerSrc.slice(opIdx, opIdx + 3000)
    expect(opBlock).toContain('zero magnitude')
  })

  it('NURBS_PHASE4_C1_BINDINGS includes BRepAlgoAPI_Section', () => {
    expect(workerSrc).toContain("'BRepAlgoAPI_Section'")
  })
})

// ── 1. opSection inline mock ──────────────────────────────────────────────────
//
// We inline the opSection logic so we can drive it with mock oc + bodyMap.
// Source-level checks above confirm the real code matches the tested contract.

function track(_tracker, obj) { return obj }

function opSection(oc, _prev, node, _sketches, tracker, bodyMap) {
  // Binding gate
  if (typeof oc.BRepAlgoAPI_Section !== 'function') {
    throw new Error(
      'section: wasm binding missing — BRepAlgoAPI_Section not present in this OCCT build ' +
      '(C1 binding probe reported MISSING at boot)',
    )
  }

  // Resolve target
  const solidId = node.target_solid_ref
  if (!solidId) throw new Error('section: target_solid_ref is required')
  const targetShape = bodyMap && bodyMap[solidId]
  if (!targetShape) throw new Error(`section: target_solid_ref '${solidId}' not found in evaluated tree`)

  // Validate plane
  const planeSpec = node.plane
  if (!planeSpec) throw new Error('section: plane is required')
  const pt  = planeSpec.point  || [0, 0, 0]
  const nrm = planeSpec.normal || [0, 0, 1]

  if (!Array.isArray(pt)  || pt.length < 3)  throw new Error('section: plane.point must be [x,y,z]')
  if (!Array.isArray(nrm) || nrm.length < 3) throw new Error('section: plane.normal must be [x,y,z]')

  const [nx, ny, nz] = nrm.map(Number)
  const mag = Math.sqrt(nx * nx + ny * ny + nz * nz)
  if (mag < 1e-10) throw new Error('section: plane.normal has zero magnitude')

  const [px, py, pz] = pt.map(Number)
  const origin = track(tracker, new oc.gp_Pnt_3(px, py, pz))
  const axis   = track(tracker, new oc.gp_Dir_4(nx / mag, ny / mag, nz / mag))
  const plane  = track(tracker, new oc.gp_Pln_2(origin, axis))

  const pr = () => ({ _tag: 'pr' })
  let algo
  if (typeof oc.BRepAlgoAPI_Section_3 === 'function') {
    algo = track(tracker, new oc.BRepAlgoAPI_Section_3(targetShape, plane, pr()))
  } else {
    algo = track(tracker, new oc.BRepAlgoAPI_Section(targetShape, plane, true))
  }

  if (typeof algo.Build === 'function') algo.Build(pr())

  if (typeof algo.IsDone === 'function' && !algo.IsDone()) {
    throw new Error('section: BRepAlgoAPI_Section.IsDone() returned false — section may be degenerate or parallel to solid')
  }

  const result = algo.Shape()
  if (!result) throw new Error('section: BRepAlgoAPI_Section returned null shape')
  return result
}

// Build a fake compound (edge result shape).
function makeCompound(tag = 'compound') {
  return { _tag: tag, ShapeType: () => 0 /* COMPOUND */ }
}

// Build a fake solid shape.
function makeSolid(tag = 'solid') {
  return { _tag: tag, ShapeType: () => 2 /* SOLID */ }
}

// Build a mock BRepAlgoAPI_Section class factory.
function makeSectionClass(resultShape = null, isDone = true) {
  return class MockSection {
    constructor() {
      this._result = resultShape || makeCompound('section_result')
      this._done = isDone
    }
    Build(_pr) {}
    IsDone() { return this._done }
    Shape() { return this._result }
  }
}

// Build a mock oc object with the required geometry constructors.
function makeOc({ hasSection = true, SectionClass = null } = {}) {
  const resultShape = makeCompound()
  const SClass = SectionClass || makeSectionClass(resultShape)
  return {
    BRepAlgoAPI_Section:   hasSection ? SClass : undefined,
    BRepAlgoAPI_Section_3: undefined,  // prefer plain overload in tests
    gp_Pnt_3:  class { constructor(x, y, z) { this.x = x; this.y = y; this.z = z } },
    gp_Dir_4:  class { constructor(x, y, z) { this.x = x; this.y = y; this.z = z } },
    gp_Pln_2:  class { constructor(origin, axis) { this.origin = origin; this.axis = axis } },
    Message_ProgressRange_1: class { constructor() {} },
    _resultShape: resultShape,
  }
}

describe('opSection — binding gate', () => {
  it('throws wasm binding missing when BRepAlgoAPI_Section is absent', () => {
    const oc = makeOc({ hasSection: false })
    const node = { target_solid_ref: 'pad-1', plane: { point: [0,0,0], normal: [0,0,1] } }
    expect(() => opSection(oc, null, node, {}, [], { 'pad-1': makeSolid() }))
      .toThrow(/wasm binding missing/)
  })
})

describe('opSection — target resolution', () => {
  it('throws when target_solid_ref is missing', () => {
    const oc = makeOc()
    const node = { plane: { point: [0,0,0], normal: [0,0,1] } }
    expect(() => opSection(oc, null, node, {}, [], {}))
      .toThrow(/target_solid_ref is required/)
  })

  it('throws when target not in bodyMap', () => {
    const oc = makeOc()
    const node = { target_solid_ref: 'missing', plane: { point: [0,0,0], normal: [0,0,1] } }
    expect(() => opSection(oc, null, node, {}, [], {}))
      .toThrow(/not found in evaluated tree/)
  })
})

describe('opSection — plane validation', () => {
  it('throws when plane is missing', () => {
    const oc = makeOc()
    const node = { target_solid_ref: 'pad-1' }
    expect(() => opSection(oc, null, node, {}, [], { 'pad-1': makeSolid() }))
      .toThrow(/plane is required/)
  })

  it('throws when plane.point has wrong length', () => {
    const oc = makeOc()
    const node = { target_solid_ref: 'pad-1', plane: { point: [0, 0], normal: [0,0,1] } }
    expect(() => opSection(oc, null, node, {}, [], { 'pad-1': makeSolid() }))
      .toThrow(/plane\.point/)
  })

  it('throws when plane.normal has wrong length', () => {
    const oc = makeOc()
    const node = { target_solid_ref: 'pad-1', plane: { point: [0,0,0], normal: [1, 0] } }
    expect(() => opSection(oc, null, node, {}, [], { 'pad-1': makeSolid() }))
      .toThrow(/plane\.normal/)
  })

  it('throws when normal is zero vector', () => {
    const oc = makeOc()
    const node = { target_solid_ref: 'pad-1', plane: { point: [0,0,0], normal: [0,0,0] } }
    expect(() => opSection(oc, null, node, {}, [], { 'pad-1': makeSolid() }))
      .toThrow(/zero magnitude/)
  })
})

describe('opSection — dispatch and result', () => {
  it('calls BRepAlgoAPI_Section with target shape and plane', () => {
    let sectionCalled = false
    const resultShape = makeCompound('cut_result')
    class MockSection {
      constructor(_shape, _plane, _build) { sectionCalled = true }
      Build() {}
      IsDone() { return true }
      Shape() { return resultShape }
    }
    const oc = makeOc({ SectionClass: MockSection })
    const solid = makeSolid()
    const node = { target_solid_ref: 's', plane: { point: [0,0,5], normal: [0,0,1] } }
    const result = opSection(oc, null, node, {}, [], { s: solid })
    expect(sectionCalled).toBe(true)
    expect(result).toBe(resultShape)
  })

  it('throws when IsDone() is false', () => {
    const oc = makeOc({ SectionClass: makeSectionClass(makeCompound(), false) })
    const node = { target_solid_ref: 's', plane: { point: [0,0,0], normal: [0,0,1] } }
    expect(() => opSection(oc, null, node, {}, [], { s: makeSolid() }))
      .toThrow(/IsDone.*false/)
  })

  it('uses non-unit normal (normalises internally)', () => {
    let capturedAxis = null
    class MockDir { constructor(x, y, z) { capturedAxis = [x, y, z] } }
    const oc = makeOc()
    oc.gp_Dir_4 = MockDir
    const node = { target_solid_ref: 's', plane: { point: [0,0,0], normal: [0, 0, 3] } }
    opSection(oc, null, node, {}, [], { s: makeSolid() })
    // Normal [0,0,3] should be normalised to [0,0,1].
    expect(capturedAxis[2]).toBeCloseTo(1, 5)
  })
})

// ── 2. FeatureView inspector checks ──────────────────────────────────────────

describe('FeatureView.jsx section inspector entry', () => {
  const viewSrc = readFileSync(
    path.resolve(__dirname, '../components/FeatureView.jsx'),
    'utf8',
  )

  it("FEATURE_KINDS contains op: 'section'", () => {
    expect(viewSrc).toContain("op: 'section'")
  })

  it("Modify category contains 'section'", () => {
    const modifyIdx = viewSrc.indexOf("id: 'modify'")
    expect(modifyIdx).toBeGreaterThan(-1)
    const modifyLine = viewSrc.slice(modifyIdx, viewSrc.indexOf('\n', modifyIdx + 1) + 300)
    expect(modifyLine).toContain('section')
  })

  it("section entry has target_solid_ref as feature_picker field", () => {
    const secIdx = viewSrc.indexOf("op: 'section'")
    const secBlock = viewSrc.slice(secIdx, secIdx + 800)
    expect(secBlock).toContain("'target_solid_ref'")
    expect(secBlock).toContain("'feature_picker'")
  })

  it("section entry default plane normal is [0,0,1]", () => {
    const secIdx = viewSrc.indexOf("op: 'section'")
    const secBlock = viewSrc.slice(secIdx, secIdx + 600)
    expect(secBlock).toContain('normal')
    // Default normal should reference 1 in the Z slot.
    expect(secBlock).toContain('[0, 0, 1]')
  })

  it("Scissors icon is imported from lucide-react", () => {
    const importBlock = viewSrc.slice(0, viewSrc.indexOf("import FeatureRenderer"))
    expect(importBlock).toContain('Scissors')
  })
})
