// ladderFlowState.js — pure helper that converts a PLC simulator step result
// into the powerFlow map consumed by LadderPowerFlowOverlay.
//
// This module has NO React or DOM dependencies — it is safe to unit-test in a
// plain Node/vitest environment.
//
// Concepts
// --------
// A "sim step result" is the JSON object returned by POST /plc/sim/step:
//   {
//     variables: { [name: string]: boolean | number },
//     rung_results: [
//       { rung_index: number, energized: boolean, coils: string[] },
//       …
//     ],
//     tick: number,
//     error?: string
//   }
//
// A "rung structure" is the in-memory representation of the ladder network:
//   [
//     { id: string, contacts: [{ name: string, nc: boolean }], coils: [{ name: string }] },
//     …
//   ]
//
// The "powerFlow" map is what LadderPowerFlowOverlay consumes:
//   {
//     rungs: {
//       [rungId: string]: {
//         energized: boolean,
//         contacts: { [name: string]: boolean },   // true = contact passing power
//         coils:    { [name: string]: boolean },   // true = coil energized
//       }
//     },
//     variables: { [name: string]: boolean | number },
//     tick: number
//   }
//
// Design decisions
// ----------------
// • Pure function — no side effects; the caller (LadderEditorWithFlow) owns
//   the polling loop and calls buildPowerFlow on each tick.
// • Defensive: missing fields in simResult never throw; they produce
//   `energized: false` defaults.
// • Rung matching: rung_results are correlated to rung structures by
//   rung_index. If rung_results is missing or sparse, the rung defaults to
//   not-energized but still appears in the map so the overlay can render a
//   consistent skeleton.

/**
 * Build the powerFlow map from a simulator step result and the current rung
 * structure.
 *
 * @param {object|null} simResult   — response from POST /plc/sim/step (may be null)
 * @param {Array}       rungs       — ladder rung definitions (may be empty)
 * @returns {{ rungs: object, variables: object, tick: number }}
 */
export function buildPowerFlow(simResult, rungs = []) {
  const variables = (simResult && typeof simResult.variables === 'object' && simResult.variables !== null)
    ? simResult.variables
    : {}

  const tick = (simResult && typeof simResult.tick === 'number') ? simResult.tick : 0

  // Index rung_results by rung_index for O(1) lookup.
  const rungResultByIndex = new Map()
  if (simResult && Array.isArray(simResult.rung_results)) {
    for (const rr of simResult.rung_results) {
      if (rr && typeof rr.rung_index === 'number') {
        rungResultByIndex.set(rr.rung_index, rr)
      }
    }
  }

  const rungsMap = {}
  for (let i = 0; i < rungs.length; i++) {
    const rung = rungs[i]
    if (!rung || typeof rung.id !== 'string') continue

    const rr = rungResultByIndex.get(i)
    const energized = rr ? Boolean(rr.energized) : false

    // Contacts: resolve each contact's logical state from the variable table.
    // A normally-open (nc=false) contact passes power when its variable is truthy.
    // A normally-closed (nc=true)  contact passes power when its variable is falsy.
    const contacts = {}
    if (Array.isArray(rung.contacts)) {
      for (const c of rung.contacts) {
        if (!c || typeof c.name !== 'string') continue
        const rawVal = variables[c.name]
        const varOn = Boolean(rawVal)
        contacts[c.name] = c.nc ? !varOn : varOn
      }
    }

    // Coils: energized when the rung is energized.
    const coils = {}
    if (Array.isArray(rung.coils)) {
      for (const co of rung.coils) {
        if (!co || typeof co.name !== 'string') continue
        // A coil is energized when the rung itself is energized, unless the
        // sim has overridden the variable directly (e.g. SET/RESET coils).
        // We fall back to variable state when the sim provides it.
        const varOverride = typeof variables[co.name] !== 'undefined'
          ? Boolean(variables[co.name])
          : energized
        coils[co.name] = varOverride
      }
    }

    rungsMap[rung.id] = { energized, contacts, coils }
  }

  return { rungs: rungsMap, variables, tick }
}

/**
 * Return a blank / zero-tick powerFlow for the given rung structure.
 * Useful as initial state before the first simulator tick arrives.
 *
 * @param {Array} rungs
 * @returns {{ rungs: object, variables: object, tick: number }}
 */
export function emptyPowerFlow(rungs = []) {
  return buildPowerFlow(null, rungs)
}
