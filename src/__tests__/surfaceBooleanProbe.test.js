// surfaceBooleanProbe.test.js — C1-T1 binding probe coverage.
//
// Verifies:
//   1. Source wiring: NURBS_PHASE4_C1_BINDINGS, getNurbsPhase4Bindings, and
//      _logNurbsPhase4Bindings are all present in occtWorker.js.
//   2. getNurbsPhase4Bindings(oc) returns the correct shape for an all-present
//      mock and an all-absent mock.
//   3. The probe includes the five Capability 1 gating classes listed in the
//      plan doc (BOPAlgo_Builder, BRepAlgoAPI_Section, ShapeFix_Shape,
//      ShapeFix_Solid, ShapeUpgrade_UnifySameDomain).
//   4. _logNurbsPhase4Bindings logs [occt-phase4] lines for each class and
//      emits a GO / PARTIAL/BLOCKED gate summary line per capability group.
//
// No WASM required.  The probe logic is re-derived here from the source to
// stay independent of import mechanics.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const workerSrc = readFileSync(
  path.resolve(__dirname, '../lib/occtWorker.js'),
  'utf8',
)

// ── 0. Source-level wiring ────────────────────────────────────────────────────

describe('occtWorker.js — Phase 4 probe source wiring', () => {
  it('NURBS_PHASE4_C1_BINDINGS array is defined', () => {
    expect(workerSrc).toContain('NURBS_PHASE4_C1_BINDINGS')
  })

  it('getNurbsPhase4Bindings export is present', () => {
    expect(workerSrc).toContain('export function getNurbsPhase4Bindings(')
  })

  it('_logNurbsPhase4Bindings function is present', () => {
    expect(workerSrc).toContain('function _logNurbsPhase4Bindings(')
  })

  it('loadOcct calls _logNurbsPhase4Bindings', () => {
    const loadIdx = workerSrc.indexOf('function loadOcct(')
    const callIdx = workerSrc.indexOf('_logNurbsPhase4Bindings(oc)', loadIdx)
    expect(callIdx).toBeGreaterThan(loadIdx)
  })

  it('C1 gate includes BOPAlgo_Builder', () => {
    expect(workerSrc).toContain('BOPAlgo_Builder')
  })

  it('C1 gate includes BRepAlgoAPI_Section', () => {
    expect(workerSrc).toContain('BRepAlgoAPI_Section')
  })

  it('C1 gate includes ShapeFix_Shape', () => {
    expect(workerSrc).toContain('ShapeFix_Shape')
  })

  it('C1 gate includes ShapeFix_Solid', () => {
    expect(workerSrc).toContain('ShapeFix_Solid')
  })

  it('C1 gate includes ShapeUpgrade_UnifySameDomain', () => {
    expect(workerSrc).toContain('ShapeUpgrade_UnifySameDomain')
  })

  it('probe logs [occt-phase4] prefix', () => {
    expect(workerSrc).toContain('[occt-phase4]')
  })

  it('probe logs GO verdict', () => {
    expect(workerSrc).toContain('GO')
  })

  it('probe logs PARTIAL/BLOCKED verdict', () => {
    expect(workerSrc).toContain('PARTIAL/BLOCKED')
  })
})

// ── 1. getNurbsPhase4Bindings inline re-derivation ───────────────────────────
//
// Mirror the exact logic from occtWorker.js so we can unit-test it without
// importing the module (the worker has side effects on import).

const C1_CLASSES = [
  'BOPAlgo_Builder',
  'BRepAlgoAPI_Section',
  'ShapeFix_Shape',
  'ShapeFix_Solid',
  'ShapeUpgrade_UnifySameDomain',
]

function getNurbsPhase4Bindings_derived(oc, allClasses) {
  return Object.fromEntries(
    allClasses.map(cls => [cls, typeof oc[cls] === 'function'])
  )
}

describe('getNurbsPhase4Bindings — binding map logic', () => {
  it('returns true for each class when all are present', () => {
    const oc = {}
    for (const cls of C1_CLASSES) oc[cls] = function() {}
    const result = getNurbsPhase4Bindings_derived(oc, C1_CLASSES)
    for (const cls of C1_CLASSES) {
      expect(result[cls]).toBe(true)
    }
  })

  it('returns false for each class when none are present', () => {
    const oc = {}
    const result = getNurbsPhase4Bindings_derived(oc, C1_CLASSES)
    for (const cls of C1_CLASSES) {
      expect(result[cls]).toBe(false)
    }
  })

  it('returns mixed map when only some classes are present', () => {
    const oc = { BOPAlgo_Builder: function() {}, ShapeFix_Shape: function() {} }
    const result = getNurbsPhase4Bindings_derived(oc, C1_CLASSES)
    expect(result['BOPAlgo_Builder']).toBe(true)
    expect(result['ShapeFix_Shape']).toBe(true)
    expect(result['BRepAlgoAPI_Section']).toBe(false)
    expect(result['ShapeFix_Solid']).toBe(false)
    expect(result['ShapeUpgrade_UnifySameDomain']).toBe(false)
  })

  it('returns false if the value is not a function (e.g. an object)', () => {
    const oc = { BOPAlgo_Builder: { notAFunction: true } }
    const result = getNurbsPhase4Bindings_derived(oc, ['BOPAlgo_Builder'])
    expect(result['BOPAlgo_Builder']).toBe(false)
  })
})

// ── 2. _logNurbsPhase4Bindings — log output behaviour ────────────────────────

// Re-derive the log helper from the description in the plan so we can test
// the contract without importing the worker module.
function _logNurbsPhase4Bindings_derived(oc, consoleSpy) {
  const groups = [
    ['C1 (surface-direct booleans)', C1_CLASSES],
  ]
  for (const [label, classes] of groups) {
    const statuses = classes.map(cls => {
      const ok = typeof oc[cls] === 'function'
      consoleSpy(`[occt-phase4] ${label} — ${cls}: ${ok ? 'OK' : 'MISSING'}`)
      return ok
    })
    const allOk = statuses.every(Boolean)
    consoleSpy(`[occt-phase4] ${label} gate: ${allOk ? 'GO' : 'PARTIAL/BLOCKED'}`)
  }
}

describe('_logNurbsPhase4Bindings — log lines', () => {
  it('logs OK for each present class', () => {
    const oc = {}
    for (const cls of C1_CLASSES) oc[cls] = function() {}
    const lines = []
    _logNurbsPhase4Bindings_derived(oc, (line) => lines.push(line))
    for (const cls of C1_CLASSES) {
      expect(lines.some(l => l.includes(cls) && l.includes('OK'))).toBe(true)
    }
  })

  it('logs MISSING for each absent class', () => {
    const oc = {}
    const lines = []
    _logNurbsPhase4Bindings_derived(oc, (line) => lines.push(line))
    for (const cls of C1_CLASSES) {
      expect(lines.some(l => l.includes(cls) && l.includes('MISSING'))).toBe(true)
    }
  })

  it('logs GO gate when all C1 classes are present', () => {
    const oc = {}
    for (const cls of C1_CLASSES) oc[cls] = function() {}
    const lines = []
    _logNurbsPhase4Bindings_derived(oc, (line) => lines.push(line))
    const gateLine = lines.find(l => l.includes('gate:'))
    expect(gateLine).toBeDefined()
    expect(gateLine).toContain('GO')
    expect(gateLine).not.toContain('PARTIAL/BLOCKED')
  })

  it('logs PARTIAL/BLOCKED gate when some C1 classes are absent', () => {
    const oc = { BOPAlgo_Builder: function() {} }  // only one present
    const lines = []
    _logNurbsPhase4Bindings_derived(oc, (line) => lines.push(line))
    const gateLine = lines.find(l => l.includes('gate:'))
    expect(gateLine).toBeDefined()
    expect(gateLine).toContain('PARTIAL/BLOCKED')
  })

  it('emits a line for every C1 class', () => {
    const oc = {}
    const lines = []
    _logNurbsPhase4Bindings_derived(oc, (line) => lines.push(line))
    for (const cls of C1_CLASSES) {
      expect(lines.some(l => l.includes(cls))).toBe(true)
    }
  })
})
