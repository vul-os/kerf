// buses.ts — KiCad-style buses and differential pairs for CircuitJSON boards.
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
//
// Typing note: `bus_definitions`/`differential_pairs` are Kerf-specific
// extensions to the Circuit JSON `pcb_board` element — circuit-json's real
// `PcbBoard` interface has no such fields (and requires pcb_board_id/
// thickness/num_layers/center/material that this file's own test fixtures
// don't carry). So this module works over a local `BoardLike` shape rather
// than importing `CircuitElement`/`PcbBoard` from `@/types` and fighting the
// mismatch at every access — the alias seam in `src/types/circuit.ts` is for
// genuine Circuit JSON elements, and forcing it here would misdescribe what
// this file actually reads and writes.

/** One bus definition attached to a board. */
export interface BusDefinition {
  name: string
  member_nets: string[]
}

/** One differential-pair definition attached to a board. */
export interface DifferentialPair {
  name: string
  net_p_id: string
  net_n_id: string
  target_impedance_ohms?: number
  skew_max_mm?: number
}

/**
 * Input to `defineDifferentialPair` — the net ids use `net_p`/`net_n`
 * (caller-facing) rather than the `net_p_id`/`net_n_id` the stored
 * `DifferentialPair` entry uses.
 */
export interface DifferentialPairDef {
  name: string
  net_p: string
  net_n: string
  target_impedance_ohms?: number
  skew_max_mm?: number
}

/**
 * The board-like object this module reads/writes. `getBoard()` accepts
 * either a flat Circuit JSON array (finds the `pcb_board` element) or a
 * bare board object directly — both call shapes are exercised by
 * buses.test.ts's `makeCircuit()` fixture (a single object, not wrapped in
 * an array). The index signature keeps this honestly loose: callers pass
 * whatever board-shaped object they have, not a schema-complete PcbBoard.
 */
export interface BoardLike {
  type?: string
  bus_definitions?: BusDefinition[]
  differential_pairs?: DifferentialPair[]
  [key: string]: unknown
}

/** `BoardLike` after `ensureBoardKeys` has guaranteed both list fields exist. */
interface BoardWithLists extends BoardLike {
  bus_definitions: BusDefinition[]
  differential_pairs: DifferentialPair[]
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function getBoard(circuit_json: unknown): BoardLike | null {
  if (!circuit_json || typeof circuit_json !== 'object') return null
  if (Array.isArray(circuit_json)) {
    const found = (circuit_json as unknown[]).find(
      (el): el is BoardLike => !!el && typeof el === 'object' && (el as BoardLike).type === 'pcb_board'
    )
    return found ?? null
  }
  if ((circuit_json as BoardLike).type === 'pcb_board') return circuit_json as BoardLike
  return null
}

function cloneCircuit<T>(circuit_json: T): T {
  return JSON.parse(JSON.stringify(circuit_json))
}

function ensureBoardKeys(board: BoardLike): BoardWithLists {
  if (!Array.isArray(board.bus_definitions)) board.bus_definitions = []
  if (!Array.isArray(board.differential_pairs)) board.differential_pairs = []
  return board as BoardWithLists
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
 * @param spec — e.g. "DATA[7..0]" or "RX"; empty array on parse failure.
 */
export function expandBus(spec: unknown): string[] {
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
  const nets: string[] = []
  for (let i = a; step > 0 ? i <= b : i >= b; i += step) {
    nets.push(`${prefix}${i}`)
  }
  return nets
}

/** Validate a bus definition object. */
export function validateBus(bus_def: unknown): { ok: boolean; errors: string[] } {
  const errors: string[] = []

  if (!bus_def || typeof bus_def !== 'object') {
    return { ok: false, errors: ['bus_def must be a non-null object'] }
  }

  const bd = bus_def as Partial<BusDefinition>

  if (!bd.name || typeof bd.name !== 'string') {
    errors.push('bus_def.name is required and must be a string')
  }

  if (!Array.isArray(bd.member_nets)) {
    errors.push('bus_def.member_nets must be an array')
  } else if (bd.member_nets.length === 0) {
    errors.push('bus_def.member_nets must not be empty')
  } else {
    for (const net of bd.member_nets) {
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
 * `member_nets` entries can use "DATA[7..0]" slice notation.
 * Returns a new circuit_json object (original is not mutated).
 */
export function defineBus(circuit_json: BoardLike, busDef: unknown): BoardWithLists
export function defineBus(circuit_json: BoardLike[], busDef: unknown): BoardLike[]
export function defineBus(circuit_json: unknown, busDef: unknown): unknown {
  const validation = validateBus(busDef)
  if (!validation.ok) {
    throw new Error(`Invalid bus definition: ${validation.errors.join('; ')}`)
  }
  const validated = busDef as BusDefinition

  const cloned = cloneCircuit(circuit_json)
  const board = getBoard(cloned)
  if (!board) throw new Error('No pcb_board element found in circuit_json')

  const b = ensureBoardKeys(board)

  const entry: BusDefinition = {
    name: validated.name,
    member_nets: [...validated.member_nets],
  }

  const idx = b.bus_definitions.findIndex((x) => x.name === validated.name)
  if (idx >= 0) {
    b.bus_definitions[idx] = entry
  } else {
    b.bus_definitions.push(entry)
  }

  return cloned
}

/** Add or update a differential pair definition on the board. */
export function defineDifferentialPair(circuit_json: BoardLike, dpDef: unknown): BoardWithLists
export function defineDifferentialPair(circuit_json: BoardLike[], dpDef: unknown): BoardLike[]
export function defineDifferentialPair(circuit_json: unknown, dpDef: unknown): unknown {
  const dd = (dpDef && typeof dpDef === 'object' ? dpDef : {}) as Partial<DifferentialPairDef>

  if (!dd.name || typeof dd.name !== 'string') {
    throw new Error('dpDef.name is required and must be a string')
  }
  if (!dd.net_p || typeof dd.net_p !== 'string') {
    throw new Error('dpDef.net_p is required and must be a string')
  }
  if (!dd.net_n || typeof dd.net_n !== 'string') {
    throw new Error('dpDef.net_n is required and must be a string')
  }
  if (dd.net_p === dd.net_n) {
    throw new Error('net_p and net_n must be different nets')
  }
  if (dd.target_impedance_ohms !== undefined && typeof dd.target_impedance_ohms !== 'number') {
    throw new Error('dpDef.target_impedance_ohms must be a number if provided')
  }
  if (dd.skew_max_mm !== undefined && typeof dd.skew_max_mm !== 'number') {
    throw new Error('dpDef.skew_max_mm must be a number if provided')
  }

  const cloned = cloneCircuit(circuit_json)
  const board = getBoard(cloned)
  if (!board) throw new Error('No pcb_board element found in circuit_json')

  const b = ensureBoardKeys(board)

  const entry: DifferentialPair = {
    name: dd.name,
    net_p_id: dd.net_p,
    net_n_id: dd.net_n,
  }
  if (typeof dd.target_impedance_ohms === 'number') {
    entry.target_impedance_ohms = dd.target_impedance_ohms
  }
  if (typeof dd.skew_max_mm === 'number') {
    entry.skew_max_mm = dd.skew_max_mm
  }

  const idx = b.differential_pairs.findIndex((d) => d.name === dd.name)
  if (idx >= 0) {
    b.differential_pairs[idx] = entry
  } else {
    b.differential_pairs.push(entry)
  }

  return cloned
}

/** Look up a differential pair by either of its net IDs. */
export function getDifferentialPair(circuit_json: unknown, net_id: unknown): DifferentialPair | null {
  if (!net_id || typeof net_id !== 'string') return null

  const board = getBoard(circuit_json)
  if (!board || !Array.isArray(board.differential_pairs)) return null

  return (
    board.differential_pairs.find((d) => d.net_p_id === net_id || d.net_n_id === net_id) ?? null
  )
}

/** Return the full list of differential pairs defined on the board. */
export function listDifferentialPairs(circuit_json: unknown): DifferentialPair[] {
  const board = getBoard(circuit_json)
  if (!board || !Array.isArray(board.differential_pairs)) return []
  return board.differential_pairs.map((d) => ({ ...d }))
}

/** Return the full list of bus definitions on the board. */
export function listBuses(circuit_json: unknown): BusDefinition[] {
  const board = getBoard(circuit_json)
  if (!board || !Array.isArray(board.bus_definitions)) return []
  return board.bus_definitions.map((b) => ({ name: b.name, member_nets: [...b.member_nets] }))
}
