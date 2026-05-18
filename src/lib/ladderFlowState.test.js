// ladderFlowState.test.js — pure-logic vitest suite for ladderFlowState.js.
//
// No DOM, no React, no WASM.  All tests exercise buildPowerFlow and
// emptyPowerFlow directly.
//
// Coverage areas:
//   1.  Module shape — named exports present
//   2.  emptyPowerFlow — zero-tick blank flow for various rung structures
//   3.  buildPowerFlow — null simResult → blank flow
//   4.  buildPowerFlow — variables forwarded verbatim
//   5.  buildPowerFlow — tick forwarded
//   6.  buildPowerFlow — rung energization from rung_results
//   7.  buildPowerFlow — rung defaults to energized=false when rung_results sparse
//   8.  buildPowerFlow — normally-open contact logic
//   9.  buildPowerFlow — normally-closed contact logic
//  10.  buildPowerFlow — coil state follows rung energization
//  11.  buildPowerFlow — coil state overridden by variable when present
//  12.  buildPowerFlow — rungs with no id are skipped
//  13.  buildPowerFlow — rung_results correlated by rung_index (not array position)
//  14.  buildPowerFlow — malformed simResult fields are handled gracefully
//  15.  buildPowerFlow — empty rung array produces empty rungs map

import { describe, it, expect } from 'vitest'
import { buildPowerFlow, emptyPowerFlow } from './ladderFlowState.js'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRung(id, contacts = [], coils = []) {
  return { id, contacts, coils }
}
function makeContact(name, nc = false) {
  return { name, nc }
}
function makeCo(name) {
  return { name }
}

function makeSimResult({ variables = {}, rung_results = [], tick = 1, error } = {}) {
  const result = { variables, rung_results, tick }
  if (error !== undefined) result.error = error
  return result
}

// ---------------------------------------------------------------------------
// 1. Module shape
// ---------------------------------------------------------------------------

describe('ladderFlowState module shape', () => {
  it('exports buildPowerFlow as a function', () => {
    expect(typeof buildPowerFlow).toBe('function')
  })

  it('exports emptyPowerFlow as a function', () => {
    expect(typeof emptyPowerFlow).toBe('function')
  })
})

// ---------------------------------------------------------------------------
// 2. emptyPowerFlow
// ---------------------------------------------------------------------------

describe('emptyPowerFlow — no rungs', () => {
  it('returns tick 0 when no rungs given', () => {
    const pf = emptyPowerFlow([])
    expect(pf.tick).toBe(0)
  })

  it('returns empty rungs map when no rungs given', () => {
    const pf = emptyPowerFlow([])
    expect(pf.rungs).toEqual({})
  })

  it('returns empty variables map when no rungs given', () => {
    const pf = emptyPowerFlow([])
    expect(pf.variables).toEqual({})
  })
})

describe('emptyPowerFlow — with rungs', () => {
  const rungs = [makeRung('r0', [makeContact('X0')], [makeCo('Y0')])]

  it('creates a key for each rung id', () => {
    const pf = emptyPowerFlow(rungs)
    expect('r0' in pf.rungs).toBe(true)
  })

  it('rung energized is false in blank flow', () => {
    const pf = emptyPowerFlow(rungs)
    expect(pf.rungs.r0.energized).toBe(false)
  })

  it('contact is false in blank flow', () => {
    const pf = emptyPowerFlow(rungs)
    expect(pf.rungs.r0.contacts.X0).toBe(false)
  })

  it('coil is false in blank flow', () => {
    const pf = emptyPowerFlow(rungs)
    expect(pf.rungs.r0.coils.Y0).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 3. buildPowerFlow — null simResult
// ---------------------------------------------------------------------------

describe('buildPowerFlow — null simResult', () => {
  const rungs = [makeRung('r0', [makeContact('X0')], [makeCo('Y0')])]

  it('returns tick 0 for null simResult', () => {
    expect(buildPowerFlow(null, rungs).tick).toBe(0)
  })

  it('returns empty variables for null simResult', () => {
    expect(buildPowerFlow(null, rungs).variables).toEqual({})
  })

  it('rung energized is false for null simResult', () => {
    expect(buildPowerFlow(null, rungs).rungs.r0.energized).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 4. buildPowerFlow — variables forwarded
// ---------------------------------------------------------------------------

describe('buildPowerFlow — variables forwarding', () => {
  it('forwards all variables verbatim', () => {
    const sim = makeSimResult({ variables: { X0: true, Y0: false, COUNTER: 42 } })
    const pf = buildPowerFlow(sim, [])
    expect(pf.variables).toEqual({ X0: true, Y0: false, COUNTER: 42 })
  })

  it('returns empty object when variables is missing', () => {
    const sim = { rung_results: [], tick: 3 }
    expect(buildPowerFlow(sim, []).variables).toEqual({})
  })
})

// ---------------------------------------------------------------------------
// 5. buildPowerFlow — tick forwarded
// ---------------------------------------------------------------------------

describe('buildPowerFlow — tick forwarding', () => {
  it('forwards the tick value from simResult', () => {
    const sim = makeSimResult({ tick: 99 })
    expect(buildPowerFlow(sim, []).tick).toBe(99)
  })

  it('defaults tick to 0 when field is absent', () => {
    const sim = { variables: {}, rung_results: [] }
    expect(buildPowerFlow(sim, []).tick).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// 6. buildPowerFlow — rung energization
// ---------------------------------------------------------------------------

describe('buildPowerFlow — rung energization from rung_results', () => {
  const rungs = [
    makeRung('rung-a'),
    makeRung('rung-b'),
  ]

  it('marks rung-a energized when rung_results[0].energized=true', () => {
    const sim = makeSimResult({
      rung_results: [
        { rung_index: 0, energized: true, coils: [] },
        { rung_index: 1, energized: false, coils: [] },
      ],
    })
    const pf = buildPowerFlow(sim, rungs)
    expect(pf.rungs['rung-a'].energized).toBe(true)
    expect(pf.rungs['rung-b'].energized).toBe(false)
  })

  it('marks rung-b energized when rung_results[1].energized=true', () => {
    const sim = makeSimResult({
      rung_results: [
        { rung_index: 0, energized: false, coils: [] },
        { rung_index: 1, energized: true, coils: [] },
      ],
    })
    const pf = buildPowerFlow(sim, rungs)
    expect(pf.rungs['rung-a'].energized).toBe(false)
    expect(pf.rungs['rung-b'].energized).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 7. buildPowerFlow — sparse rung_results defaults
// ---------------------------------------------------------------------------

describe('buildPowerFlow — sparse rung_results', () => {
  const rungs = [makeRung('r0'), makeRung('r1'), makeRung('r2')]

  it('rungs missing from rung_results default to energized=false', () => {
    const sim = makeSimResult({
      rung_results: [{ rung_index: 1, energized: true, coils: [] }],
    })
    const pf = buildPowerFlow(sim, rungs)
    expect(pf.rungs.r0.energized).toBe(false)
    expect(pf.rungs.r1.energized).toBe(true)
    expect(pf.rungs.r2.energized).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 8. buildPowerFlow — normally-open contact logic
// ---------------------------------------------------------------------------

describe('buildPowerFlow — normally-open contacts (nc=false)', () => {
  const rung = makeRung('r0', [makeContact('X0', false)], [])
  const rungs = [rung]

  it('contact passes (true) when variable is truthy', () => {
    const sim = makeSimResult({ variables: { X0: true } })
    expect(buildPowerFlow(sim, rungs).rungs.r0.contacts.X0).toBe(true)
  })

  it('contact does not pass (false) when variable is falsy', () => {
    const sim = makeSimResult({ variables: { X0: false } })
    expect(buildPowerFlow(sim, rungs).rungs.r0.contacts.X0).toBe(false)
  })

  it('contact does not pass when variable is absent', () => {
    const sim = makeSimResult({ variables: {} })
    expect(buildPowerFlow(sim, rungs).rungs.r0.contacts.X0).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 9. buildPowerFlow — normally-closed contact logic
// ---------------------------------------------------------------------------

describe('buildPowerFlow — normally-closed contacts (nc=true)', () => {
  const rung = makeRung('r0', [makeContact('X1', true)], [])
  const rungs = [rung]

  it('contact passes (true) when variable is falsy', () => {
    const sim = makeSimResult({ variables: { X1: false } })
    expect(buildPowerFlow(sim, rungs).rungs.r0.contacts.X1).toBe(true)
  })

  it('contact does not pass (false) when variable is truthy', () => {
    const sim = makeSimResult({ variables: { X1: true } })
    expect(buildPowerFlow(sim, rungs).rungs.r0.contacts.X1).toBe(false)
  })

  it('contact passes when variable is absent (defaults to falsy)', () => {
    const sim = makeSimResult({ variables: {} })
    expect(buildPowerFlow(sim, rungs).rungs.r0.contacts.X1).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 10. buildPowerFlow — coil follows rung energization
// ---------------------------------------------------------------------------

describe('buildPowerFlow — coil follows rung energization (no variable override)', () => {
  const rungs = [makeRung('r0', [], [makeCo('Y0')])]

  it('coil is true when rung is energized and no variable override', () => {
    const sim = makeSimResult({
      rung_results: [{ rung_index: 0, energized: true, coils: ['Y0'] }],
      variables: {},
    })
    expect(buildPowerFlow(sim, rungs).rungs.r0.coils.Y0).toBe(true)
  })

  it('coil is false when rung is not energized and no variable override', () => {
    const sim = makeSimResult({
      rung_results: [{ rung_index: 0, energized: false, coils: [] }],
      variables: {},
    })
    expect(buildPowerFlow(sim, rungs).rungs.r0.coils.Y0).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 11. buildPowerFlow — coil overridden by variable
// ---------------------------------------------------------------------------

describe('buildPowerFlow — coil overridden by variable (SET/RESET)', () => {
  const rungs = [makeRung('r0', [], [makeCo('Y1')])]

  it('coil is true when variable is true even if rung not energized', () => {
    const sim = makeSimResult({
      rung_results: [{ rung_index: 0, energized: false, coils: [] }],
      variables: { Y1: true },
    })
    expect(buildPowerFlow(sim, rungs).rungs.r0.coils.Y1).toBe(true)
  })

  it('coil is false when variable is false even if rung energized', () => {
    const sim = makeSimResult({
      rung_results: [{ rung_index: 0, energized: true, coils: ['Y1'] }],
      variables: { Y1: false },
    })
    expect(buildPowerFlow(sim, rungs).rungs.r0.coils.Y1).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 12. buildPowerFlow — rungs without id are skipped
// ---------------------------------------------------------------------------

describe('buildPowerFlow — rungs without id are skipped', () => {
  it('does not add a key for a rung with no id', () => {
    const rungs = [{ contacts: [], coils: [] }, makeRung('r1')]
    const pf = buildPowerFlow(null, rungs)
    expect(Object.keys(pf.rungs)).toEqual(['r1'])
  })
})

// ---------------------------------------------------------------------------
// 13. buildPowerFlow — rung_results correlated by rung_index
// ---------------------------------------------------------------------------

describe('buildPowerFlow — rung_results correlated by rung_index not array position', () => {
  it('uses rung_index to match rungs regardless of array order', () => {
    const rungs = [makeRung('r0'), makeRung('r1'), makeRung('r2')]
    const sim = makeSimResult({
      // rung_results out-of-order: rung 2 first, then rung 0
      rung_results: [
        { rung_index: 2, energized: true, coils: [] },
        { rung_index: 0, energized: false, coils: [] },
      ],
    })
    const pf = buildPowerFlow(sim, rungs)
    expect(pf.rungs.r0.energized).toBe(false)
    expect(pf.rungs.r1.energized).toBe(false)  // missing → default
    expect(pf.rungs.r2.energized).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 14. buildPowerFlow — malformed simResult fields handled gracefully
// ---------------------------------------------------------------------------

describe('buildPowerFlow — malformed simResult fields', () => {
  it('does not throw when variables is null', () => {
    expect(() => buildPowerFlow({ variables: null, rung_results: [], tick: 1 }, [])).not.toThrow()
  })

  it('does not throw when rung_results is null', () => {
    expect(() => buildPowerFlow({ variables: {}, rung_results: null, tick: 1 }, [])).not.toThrow()
  })

  it('does not throw when rung_results contains null entries', () => {
    const rungs = [makeRung('r0')]
    expect(() => buildPowerFlow(
      { variables: {}, rung_results: [null, { rung_index: 0, energized: true, coils: [] }], tick: 1 },
      rungs,
    )).not.toThrow()
  })

  it('does not throw when simResult is completely empty object', () => {
    expect(() => buildPowerFlow({}, [])).not.toThrow()
  })

  it('does not throw when a rung has null contacts/coils', () => {
    const rungs = [{ id: 'r0', contacts: null, coils: null }]
    expect(() => buildPowerFlow(makeSimResult(), rungs)).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 15. buildPowerFlow — empty rung array
// ---------------------------------------------------------------------------

describe('buildPowerFlow — empty rung array', () => {
  it('returns empty rungs map for empty rung array', () => {
    const sim = makeSimResult({ variables: { X0: true }, tick: 5 })
    const pf = buildPowerFlow(sim, [])
    expect(pf.rungs).toEqual({})
  })

  it('still forwards variables and tick with empty rungs', () => {
    const sim = makeSimResult({ variables: { X0: true }, tick: 7 })
    const pf = buildPowerFlow(sim, [])
    expect(pf.variables.X0).toBe(true)
    expect(pf.tick).toBe(7)
  })
})

// ---------------------------------------------------------------------------
// Integration: typical ladder with contacts + coils + sim result
// ---------------------------------------------------------------------------

describe('buildPowerFlow — integration: full rung with contacts and coil', () => {
  //  Rung 0: [X0 NO]--[X1 NC]--( Y0 )
  const rungs = [
    makeRung('rung-0', [makeContact('X0', false), makeContact('X1', true)], [makeCo('Y0')]),
  ]

  it('reports correct contact states when rung is energized', () => {
    const sim = makeSimResult({
      variables: { X0: true, X1: false, Y0: true },
      rung_results: [{ rung_index: 0, energized: true, coils: ['Y0'] }],
      tick: 10,
    })
    const pf = buildPowerFlow(sim, rungs)
    // X0 NO: variable true → passes
    expect(pf.rungs['rung-0'].contacts.X0).toBe(true)
    // X1 NC: variable false → passes (NC inverted)
    expect(pf.rungs['rung-0'].contacts.X1).toBe(true)
    expect(pf.rungs['rung-0'].energized).toBe(true)
    // Y0 variable=true overrides
    expect(pf.rungs['rung-0'].coils.Y0).toBe(true)
    expect(pf.tick).toBe(10)
  })

  it('reports correct contact states when rung is de-energized', () => {
    const sim = makeSimResult({
      variables: { X0: false, X1: true, Y0: false },
      rung_results: [{ rung_index: 0, energized: false, coils: [] }],
      tick: 11,
    })
    const pf = buildPowerFlow(sim, rungs)
    // X0 NO: variable false → blocked
    expect(pf.rungs['rung-0'].contacts.X0).toBe(false)
    // X1 NC: variable true → blocked (NC inverted)
    expect(pf.rungs['rung-0'].contacts.X1).toBe(false)
    expect(pf.rungs['rung-0'].energized).toBe(false)
    expect(pf.rungs['rung-0'].coils.Y0).toBe(false)
  })
})
