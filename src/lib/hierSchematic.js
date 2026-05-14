// hierSchematic.js — KiCad-style hierarchical schematics for CircuitJSON.
//
// CircuitJSON extensions (on the board element):
//
//   board.sub_sheets: [{
//     id, name, file_id, position: [x, y],
//     pins: [{ name, type, net_id }]
//   }]
//   board.global_labels: [{ name, net_id }]
//   board.hierarchical_labels: [{ name, net_id, sheet_id }]
//
// Global labels propagate across ALL sheets (GND, VCC, etc.).
// Hierarchical labels propagate ONLY through the matching sheet-symbol pin.

// ── Internal helpers ──────────────────────────────────────────────────────────

function getBoard(circuit_json) {
  if (!circuit_json || typeof circuit_json !== 'object') return null
  if (Array.isArray(circuit_json)) {
    return circuit_json.find(el => el && el.type === 'pcb_board') ?? null
  }
  if (circuit_json.type === 'pcb_board') return circuit_json
  return null
}

function clone(v) {
  return JSON.parse(JSON.stringify(v))
}

function ensureKeys(board) {
  if (!Array.isArray(board.sub_sheets)) board.sub_sheets = []
  if (!Array.isArray(board.global_labels)) board.global_labels = []
  if (!Array.isArray(board.hierarchical_labels)) board.hierarchical_labels = []
}

// ── Union-Find ────────────────────────────────────────────────────────────────

class UnionFind {
  constructor() {
    this._parent = {}
  }

  _key(sheet_path, net_id) {
    return `${sheet_path}::${net_id}`
  }

  find(sheet_path, net_id) {
    const k = this._key(sheet_path, net_id)
    if (!(k in this._parent)) this._parent[k] = k
    if (this._parent[k] !== k) {
      this._parent[k] = this._find_by_key(this._parent[k])
    }
    return this._parent[k]
  }

  _find_by_key(k) {
    if (!(k in this._parent)) this._parent[k] = k
    if (this._parent[k] !== k) {
      this._parent[k] = this._find_by_key(this._parent[k])
    }
    return this._parent[k]
  }

  union(sp1, n1, sp2, n2) {
    const r1 = this.find(sp1, n1)
    const r2 = this.find(sp2, n2)
    if (r1 !== r2) this._parent[r1] = r2
  }

  groups() {
    const map = {}
    for (const k of Object.keys(this._parent)) {
      const root = this._find_by_key(k)
      if (!map[root]) map[root] = []
      map[root].push(k)
    }
    return Object.values(map)
  }
}

// ── addSubSheet ───────────────────────────────────────────────────────────────

/**
 * Add a sub-sheet symbol to a parent circuit.
 *
 * @param {object} circuit_json — The parent CircuitJSON board.
 * @param {{ name: string, file_id: string, position: [number, number], pins?: Array }} opts
 * @returns {object} Updated circuit_json.
 */
export function addSubSheet(circuit_json, { name, file_id, position = [0, 0], pins = [] } = {}) {
  if (!name || typeof name !== 'string') throw new Error('name is required')
  if (!file_id || typeof file_id !== 'string') throw new Error('file_id is required')

  const cloned = clone(circuit_json)
  const board = getBoard(cloned)
  if (!board) throw new Error('No pcb_board element found in circuit_json')
  ensureKeys(board)

  const id = crypto.randomUUID()
  board.sub_sheets.push({ id, name, file_id, position, pins: pins.map(p => ({ ...p })) })
  return cloned
}

// ── removeSubSheet ────────────────────────────────────────────────────────────

/**
 * Remove a sub-sheet by its id. Also removes dangling hierarchical_labels
 * that referenced that sheet.
 *
 * @param {object} circuit_json
 * @param {string} sub_sheet_id
 * @returns {object} Updated circuit_json.
 */
export function removeSubSheet(circuit_json, sub_sheet_id) {
  if (!sub_sheet_id) throw new Error('sub_sheet_id is required')

  const cloned = clone(circuit_json)
  const board = getBoard(cloned)
  if (!board) throw new Error('No pcb_board element found in circuit_json')
  ensureKeys(board)

  board.sub_sheets = board.sub_sheets.filter(s => s.id !== sub_sheet_id)
  board.hierarchical_labels = board.hierarchical_labels.filter(l => l.sheet_id !== sub_sheet_id)
  return cloned
}

// ── addGlobalLabel ────────────────────────────────────────────────────────────

/**
 * Add or update a global label (propagates across all sheets).
 * If a label with the same name already exists it is updated in-place.
 *
 * @param {object} circuit_json
 * @param {string} name
 * @param {string} net_id
 * @returns {object} Updated circuit_json.
 */
export function addGlobalLabel(circuit_json, name, net_id) {
  if (!name || typeof name !== 'string') throw new Error('name is required')
  if (!net_id || typeof net_id !== 'string') throw new Error('net_id is required')

  const cloned = clone(circuit_json)
  const board = getBoard(cloned)
  if (!board) throw new Error('No pcb_board element found in circuit_json')
  ensureKeys(board)

  const idx = board.global_labels.findIndex(l => l.name === name)
  if (idx >= 0) {
    board.global_labels[idx] = { name, net_id }
  } else {
    board.global_labels.push({ name, net_id })
  }
  return cloned
}

// ── addHierLabel ──────────────────────────────────────────────────────────────

/**
 * Add or update a hierarchical label on a child sheet.
 * Hierarchical labels are scoped to a specific sheet_id.
 *
 * @param {object} circuit_json
 * @param {string} name   — must match a pin.name on the parent's sub_sheet.
 * @param {string} net_id — the child sheet's local net.
 * @param {string} sheet_id — the sub_sheet.id in the parent that owns this label.
 * @returns {object} Updated circuit_json.
 */
export function addHierLabel(circuit_json, name, net_id, sheet_id) {
  if (!name || typeof name !== 'string') throw new Error('name is required')
  if (!net_id || typeof net_id !== 'string') throw new Error('net_id is required')
  if (!sheet_id || typeof sheet_id !== 'string') throw new Error('sheet_id is required')

  const cloned = clone(circuit_json)
  const board = getBoard(cloned)
  if (!board) throw new Error('No pcb_board element found in circuit_json')
  ensureKeys(board)

  const idx = board.hierarchical_labels.findIndex(l => l.name === name && l.sheet_id === sheet_id)
  if (idx >= 0) {
    board.hierarchical_labels[idx] = { name, net_id, sheet_id }
  } else {
    board.hierarchical_labels.push({ name, net_id, sheet_id })
  }
  return cloned
}

// ── resolveSheetPin ───────────────────────────────────────────────────────────

/**
 * Resolve a single pin binding between parent and child.
 *
 * @param {object} parent_circuit
 * @param {string} sub_sheet_id
 * @param {string} pin_name
 * @param {object} child_circuit
 * @returns {{ parent_net_id: string, child_net_id: string } | null}
 */
export function resolveSheetPin(parent_circuit, sub_sheet_id, pin_name, child_circuit) {
  const parentBoard = getBoard(parent_circuit)
  const childBoard = getBoard(child_circuit)
  if (!parentBoard || !childBoard) return null

  ensureKeys(parentBoard)
  ensureKeys(childBoard)

  const sheet = parentBoard.sub_sheets.find(s => s.id === sub_sheet_id)
  if (!sheet) return null

  const pin = (sheet.pins || []).find(p => p.name === pin_name)
  if (!pin) return null

  const hierLabel = childBoard.hierarchical_labels.find(
    l => l.name === pin_name && l.sheet_id === sub_sheet_id
  )
  if (!hierLabel) return null

  return { parent_net_id: pin.net_id, child_net_id: hierLabel.net_id }
}

// ── flattenHierarchy ──────────────────────────────────────────────────────────

/**
 * Flatten a hierarchy of circuits into a single net equivalence list.
 *
 * Uses union-find over (sheet_path, net_id) tuples.
 *  - Global labels across all sheets are unioned together by label name.
 *  - Sub-sheet pins are unioned with the matching child hierarchical_label.
 *
 * @param {object} top_circuit
 * @param {Object.<string, object>} children_circuits_by_file_id — { file_id: circuit_json }
 * @returns {{ net_groups: string[][] }} Each group is a list of "sheet_path::net_id" keys
 *   that are electrically equivalent.
 */
export function flattenHierarchy(top_circuit, children_circuits_by_file_id = {}) {
  const uf = new UnionFind()

  // Recursive helper; sheet_path identifies uniquely each instantiated sheet.
  function processSheet(circuit, sheet_path) {
    const board = getBoard(circuit)
    if (!board) return
    ensureKeys(board)

    // Register every net referenced by global labels under the global "GBL" namespace,
    // merging matching label names across all sheets.
    for (const gl of board.global_labels) {
      uf.union(sheet_path, gl.net_id, `__global__`, gl.name)
    }

    // Process each sub-sheet
    for (const sheet of board.sub_sheets) {
      const child_circuit = children_circuits_by_file_id[sheet.file_id]
      if (!child_circuit) continue

      const child_path = `${sheet_path}/${sheet.id}`

      // Union each parent pin net with the child hierarchical label net
      for (const pin of (sheet.pins || [])) {
        const childBoard = getBoard(child_circuit)
        if (!childBoard) continue
        ensureKeys(childBoard)
        const hierLabel = childBoard.hierarchical_labels.find(
          l => l.name === pin.name && l.sheet_id === sheet.id
        )
        if (hierLabel) {
          uf.union(sheet_path, pin.net_id, child_path, hierLabel.net_id)
        }
      }

      // Recurse into child sheet
      processSheet(child_circuit, child_path)
    }
  }

  processSheet(top_circuit, 'top')

  const net_groups = uf.groups()
  return { net_groups }
}

// ── validateHierarchy ─────────────────────────────────────────────────────────

/**
 * Validate a circuit hierarchy.
 *
 * Checks:
 *  1. Every sub_sheet references a known file_id in children_circuits_by_file_id.
 *  2. Every sub_sheet pin has a matching hierarchical_label in the child.
 *  3. No global label name collisions (same name → different net_id on same sheet).
 *  4. No orphaned hierarchical_labels (label exists but no matching pin on parent sheet).
 *
 * @param {object} top_circuit
 * @param {Object.<string, object>} children_circuits_by_file_id
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateHierarchy(top_circuit, children_circuits_by_file_id = {}) {
  const errors = []

  function validateSheet(circuit, sheet_path) {
    const board = getBoard(circuit)
    if (!board) {
      errors.push(`${sheet_path}: not a valid pcb_board`)
      return
    }
    ensureKeys(board)

    // Check for global label name collisions on this sheet
    const globalNameToNet = {}
    for (const gl of board.global_labels) {
      if (gl.name in globalNameToNet && globalNameToNet[gl.name] !== gl.net_id) {
        errors.push(`${sheet_path}: global label "${gl.name}" has conflicting net_ids: "${globalNameToNet[gl.name]}" vs "${gl.net_id}"`)
      }
      globalNameToNet[gl.name] = gl.net_id
    }

    for (const sheet of board.sub_sheets) {
      const child_circuit = children_circuits_by_file_id[sheet.file_id]
      const child_path = `${sheet_path}/${sheet.id}(${sheet.name})`

      // Check 1: child must exist
      if (!child_circuit) {
        errors.push(`${child_path}: referenced file_id "${sheet.file_id}" not found in children`)
        continue
      }

      const childBoard = getBoard(child_circuit)
      if (!childBoard) {
        errors.push(`${child_path}: child circuit is not a valid pcb_board`)
        continue
      }
      ensureKeys(childBoard)

      // Check 2: every pin must have a matching hierarchical_label in child
      for (const pin of (sheet.pins || [])) {
        const hierLabel = childBoard.hierarchical_labels.find(
          l => l.name === pin.name && l.sheet_id === sheet.id
        )
        if (!hierLabel) {
          errors.push(`${child_path}: pin "${pin.name}" has no matching hierarchical_label in child circuit`)
        }
      }

      // Check 4: orphaned hierarchical_labels (in child but no matching pin in parent)
      for (const hl of childBoard.hierarchical_labels) {
        if (hl.sheet_id === sheet.id) {
          const pin = (sheet.pins || []).find(p => p.name === hl.name)
          if (!pin) {
            errors.push(`${child_path}: hierarchical_label "${hl.name}" has no matching pin on parent sheet symbol`)
          }
        }
      }

      // Recurse
      validateSheet(child_circuit, `${sheet_path}/${sheet.id}`)
    }
  }

  validateSheet(top_circuit, 'top')

  return { ok: errors.length === 0, errors }
}
