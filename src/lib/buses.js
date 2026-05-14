// buses.js — KiCad-style buses and differential pairs for CircuitJSON boards.
//
// CircuitJSON extensions (on the board element):
//   board.bus_definitions: [{ name, member_nets: [...] }]
//     member_nets entries can be plain strings ("DATA0") or
//     KiCad-style bus slice notation "DATA[7..0]" which expandBus() decodes.
//
//   board.differential_pairs: [{
//     name, net_p_id, net_n_id,
//     target_impedance_ohms?, skew_max_mm?
//   }]

// ── Internal helpers ──────────────────────────────────────────────────────────

function getBoard(circuit_json) {
  if (!circuit_json || typeof circuit_json !== 'object') return null
  if (Array.isArray(circuit_json)) {
    return circuit_json.find(el => el && el.type === 'pcb_board') ?? null
  }
  if (circuit_json.type === 'pcb_board') return circuit_json
  return null
}

function cloneCircuit(circuit_json) {
  return JSON.parse(JSON.stringify(circuit_json))
}

function ensureBoardKeys(board) {
  if (!Array.isArray(board.bus_definitions)) board.bus_definitions = []
  if (!Array.isArray(board.differential_pairs)) board.differential_pairs = []
  return board
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Parse a KiCad-style bus slice such as "DATA[7..0]" into an array of net
 * names like ["DATA7", "DATA6", ..., "DATA0"].
 *
 * Supports:
 *   - "NAME[7..0]"   → descending (DATA7 … DATA0)
 *   - "NAME[0..7]"   → ascending  (DATA0 … DATA7)
 *   - "NAME[3..3]"   → single     (NAME3)
 *   - plain strings  → ["NAME"] (pass-through)
 *
 * @param {string} spec — e.g. "DATA[7..0]" or "RX"
 * @returns {string[]} — individual net names; empty array on parse failure
 */
export function expandBus(spec) {
  if (!spec || typeof spec !== 'string') return []

  const hasBrackets = spec.includes('[')
  const sliceMatch = spec.match(/^(.+)\[(\d+)\.\.(\d+)\]$/)
  if (!sliceMatch) {
    return hasBrackets ? [] : [spec]
  }

  const [, prefix, rawA, rawB] = sliceMatch
  const a = parseInt(rawA, 10)
  const b = parseInt(rawB, 10)

  if (isNaN(a) || isNaN(b)) return hasBrackets ? [] : [spec]
  if (a === b) return [`${prefix}${a}`]

  const step = a < b ? 1 : -1
  const nets = []
  for (let i = a; step > 0 ? i <= b : i >= b; i += step) {
    nets.push(`${prefix}${i}`)
  }
  return nets
}

/**
 * Validate a bus definition object.
 *
 * @param {{ name: string, member_nets: string[] } | null | undefined} bus_def
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateBus(bus_def) {
  const errors = []

  if (!bus_def || typeof bus_def !== 'object') {
    return { ok: false, errors: ['bus_def must be a non-null object'] }
  }

  if (!bus_def.name || typeof bus_def.name !== 'string') {
    errors.push('bus_def.name is required and must be a string')
  }

  if (!Array.isArray(bus_def.member_nets)) {
    errors.push('bus_def.member_nets must be an array')
  } else if (bus_def.member_nets.length === 0) {
    errors.push('bus_def.member_nets must not be empty')
  } else {
    for (const net of bus_def.member_nets) {
      if (typeof net !== 'string' || !net.trim()) {
        errors.push(`Invalid bus member: ${JSON.stringify(net)} — must be a non-empty string`)
        break
      }
      if (net.includes('[') && !/^\w+\[\d+\.\.\d+\]$/.test(net)) {
        errors.push(`Bus member "${net}" uses invalid slice syntax (expected NAME[7..0])`)
        break
      }
      const expanded = expandBus(net)
      if (expanded.length === 0) {
        errors.push(`Bus member "${net}" failed to expand`)
        break
      }
    }
  }

  return { ok: errors.length === 0, errors }
}

/**
 * Add or update a bus definition on the board.
 *
 * @param {any} circuit_json
 * @param {{ name: string, member_nets: string[] }} busDef
 *   member_nets entries can use "DATA[7..0]" slice notation.
 * @returns {any} — new circuit_json object (original is not mutated)
 */
export function defineBus(circuit_json, busDef) {
  const validation = validateBus(busDef)
  if (!validation.ok) {
    throw new Error(`Invalid bus definition: ${validation.errors.join('; ')}`)
  }

  const cloned = cloneCircuit(circuit_json)
  const board = getBoard(cloned)
  if (!board) throw new Error('No pcb_board element found in circuit_json')

  ensureBoardKeys(board)

  const entry = {
    name: busDef.name,
    member_nets: [...busDef.member_nets],
  }

  const idx = board.bus_definitions.findIndex(b => b.name === busDef.name)
  if (idx >= 0) {
    board.bus_definitions[idx] = entry
  } else {
    board.bus_definitions.push(entry)
  }

  return cloned
}

/**
 * Add or update a differential pair definition on the board.
 *
 * @param {any} circuit_json
 * @param {{ name: string, net_p: string, net_n: string,
 *           target_impedance_ohms?: number, skew_max_mm?: number }} dpDef
 * @returns {any}
 */
export function defineDifferentialPair(circuit_json, dpDef) {
  if (!dpDef || !dpDef.name || typeof dpDef.name !== 'string') {
    throw new Error('dpDef.name is required and must be a string')
  }
  if (!dpDef.net_p || typeof dpDef.net_p !== 'string') {
    throw new Error('dpDef.net_p is required and must be a string')
  }
  if (!dpDef.net_n || typeof dpDef.net_n !== 'string') {
    throw new Error('dpDef.net_n is required and must be a string')
  }
  if (dpDef.net_p === dpDef.net_n) {
    throw new Error('net_p and net_n must be different nets')
  }
  if (dpDef.target_impedance_ohms !== undefined &&
      typeof dpDef.target_impedance_ohms !== 'number') {
    throw new Error('dpDef.target_impedance_ohms must be a number if provided')
  }
  if (dpDef.skew_max_mm !== undefined &&
      typeof dpDef.skew_max_mm !== 'number') {
    throw new Error('dpDef.skew_max_mm must be a number if provided')
  }

  const cloned = cloneCircuit(circuit_json)
  const board = getBoard(cloned)
  if (!board) throw new Error('No pcb_board element found in circuit_json')

  ensureBoardKeys(board)

  const entry = {
    name: dpDef.name,
    net_p_id: dpDef.net_p,
    net_n_id: dpDef.net_n,
  }
  if (typeof dpDef.target_impedance_ohms === 'number') {
    entry.target_impedance_ohms = dpDef.target_impedance_ohms
  }
  if (typeof dpDef.skew_max_mm === 'number') {
    entry.skew_max_mm = dpDef.skew_max_mm
  }

  const idx = board.differential_pairs.findIndex(d => d.name === dpDef.name)
  if (idx >= 0) {
    board.differential_pairs[idx] = entry
  } else {
    board.differential_pairs.push(entry)
  }

  return cloned
}

/**
 * Look up a differential pair by either of its net IDs.
 *
 * @param {any} circuit_json
 * @param {string} net_id
 * @returns {{ name: string, net_p_id: string, net_n_id: string,
 *             target_impedance_ohms?: number, skew_max_mm?: number } | null}
 */
export function getDifferentialPair(circuit_json, net_id) {
  if (!net_id) return null

  const board = getBoard(circuit_json)
  if (!board || !Array.isArray(board.differential_pairs)) return null

  return board.differential_pairs.find(
    d => d.net_p_id === net_id || d.net_n_id === net_id
  ) ?? null
}

/**
 * Return the full list of differential pairs defined on the board.
 *
 * @param {any} circuit_json
 * @returns {{ name: string, net_p_id: string, net_n_id: string,
 *             target_impedance_ohms?: number, skew_max_mm?: number }[]}
 */
export function listDifferentialPairs(circuit_json) {
  const board = getBoard(circuit_json)
  if (!board || !Array.isArray(board.differential_pairs)) return []
  return board.differential_pairs.map(d => ({ ...d }))
}

/**
 * Return the full list of bus definitions on the board.
 *
 * @param {any} circuit_json
 * @returns {{ name: string, member_nets: string[] }[]}
 */
export function listBuses(circuit_json) {
  const board = getBoard(circuit_json)
  if (!board || !Array.isArray(board.bus_definitions)) return []
  return board.bus_definitions.map(b => ({ name: b.name, member_nets: [...b.member_nets] }))
}
