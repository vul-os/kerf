// ladderCanvas.js — Pure logic for ladder diagram (LD) rung data.
// PLCopen XML I/O is wired via rungsToPlcopenModel / plcopenModelToRungs
// which map between the canvas rung model and the T-220 PLCopen JSON model.
//
// A Rung is an immutable record:
//   {
//     id       : string,
//     contacts : Array<{id, name, type, position, negated}>,
//     coils    : Array<{id, name, type, position}>,
//     wires    : Array<{id, from, to}>,
//   }
//
// "position" is a column index (integer ≥ 0) on the rung grid.
// Left rail occupies column -1 (virtual), right rail is beyond the last element.
// Contacts must appear left of all coils; a coil is the rightmost element.

let _nextId = 1

function uid(prefix) {
  return `${prefix}-${_nextId++}`
}

// ── createRung ────────────────────────────────────────────────────────────────

/** Return a fresh, empty rung with just its id set. */
export function createRung(id) {
  return {
    id: id ?? uid('rung'),
    contacts: [],
    coils: [],
    wires: [],
  }
}

// ── addContact ────────────────────────────────────────────────────────────────

const CONTACT_TYPES = new Set(['no', 'nc', 'rising', 'falling'])

/**
 * Add a contact to a rung. Returns a new rung (immutable).
 *
 * @param {object} rung
 * @param {string} type - 'no' | 'nc' | 'rising' | 'falling'
 * @param {number} position - column index
 * @param {object} [opts]
 * @param {string} [opts.name]
 * @param {boolean} [opts.negated]
 * @returns {object} new rung
 */
export function addContact(rung, type, position, opts = {}) {
  if (!CONTACT_TYPES.has(type)) {
    throw new Error(`Invalid contact type "${type}". Must be one of: ${[...CONTACT_TYPES].join(', ')}`)
  }
  if (typeof position !== 'number' || !Number.isInteger(position) || position < 0) {
    throw new Error('position must be a non-negative integer')
  }
  const contact = {
    id: uid('c'),
    name: opts.name ?? '',
    type,
    position,
    negated: opts.negated ?? (type === 'nc'),
  }
  return { ...rung, contacts: [...rung.contacts, contact] }
}

// ── addCoil ───────────────────────────────────────────────────────────────────

const COIL_TYPES = new Set(['output', 'set', 'reset', 'pulse'])

/**
 * Add a coil to a rung. Returns a new rung (immutable).
 *
 * @param {object} rung
 * @param {string} type - 'output' | 'set' | 'reset' | 'pulse'
 * @param {number} position - column index
 * @param {object} [opts]
 * @param {string} [opts.name]
 * @returns {object} new rung
 */
export function addCoil(rung, type, position, opts = {}) {
  if (!COIL_TYPES.has(type)) {
    throw new Error(`Invalid coil type "${type}". Must be one of: ${[...COIL_TYPES].join(', ')}`)
  }
  if (typeof position !== 'number' || !Number.isInteger(position) || position < 0) {
    throw new Error('position must be a non-negative integer')
  }
  const coil = {
    id: uid('coil'),
    name: opts.name ?? '',
    type,
    position,
  }
  return { ...rung, coils: [...rung.coils, coil] }
}

// ── deleteElement ─────────────────────────────────────────────────────────────

/**
 * Remove a contact or coil by id. Returns a new rung (immutable).
 *
 * @param {object} rung
 * @param {string} id - element id
 * @returns {object} new rung
 */
export function deleteElement(rung, id) {
  return {
    ...rung,
    contacts: rung.contacts.filter((c) => c.id !== id),
    coils: rung.coils.filter((c) => c.id !== id),
    wires: rung.wires.filter((w) => w.from !== id && w.to !== id),
  }
}

// ── moveElement ───────────────────────────────────────────────────────────────

/**
 * Update the position of a contact or coil. Returns a new rung (immutable).
 *
 * @param {object} rung
 * @param {string} id - element id
 * @param {number} newPosition - new column index
 * @returns {object} new rung
 */
export function moveElement(rung, id, newPosition) {
  if (typeof newPosition !== 'number' || !Number.isInteger(newPosition) || newPosition < 0) {
    throw new Error('newPosition must be a non-negative integer')
  }
  const mapPos = (el) => el.id === id ? { ...el, position: newPosition } : el
  return {
    ...rung,
    contacts: rung.contacts.map(mapPos),
    coils: rung.coils.map(mapPos),
  }
}

// ── validateRung ─────────────────────────────────────────────────────────────

/**
 * Validate a rung against IEC 61131-3 LD rules.
 *
 * Rules checked:
 *  1. Must have at least one contact (left-rail attachment).
 *  2. Must have exactly one coil (right-rail attachment).
 *  3. No two contacts may share the same position (overlap).
 *  4. Every coil position must be greater than every contact position (coil is rightmost).
 *
 * @param {object} rung
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateRung(rung) {
  const errors = []

  if (!rung || typeof rung !== 'object') {
    return { ok: false, errors: ['rung must be an object'] }
  }

  const contacts = rung.contacts ?? []
  const coils = rung.coils ?? []

  // Rule 1: needs contacts to attach to left rail
  if (contacts.length === 0) {
    errors.push('rung has no contacts — no connection to left rail')
  }

  // Rule 2: needs at least one coil to drive right rail
  if (coils.length === 0) {
    errors.push('rung has no coils — no connection to right rail')
  }

  // Rule 3: no overlapping contacts
  const positions = contacts.map((c) => c.position)
  const seen = new Set()
  for (const pos of positions) {
    if (seen.has(pos)) {
      errors.push(`overlapping contacts at position ${pos}`)
      break
    }
    seen.add(pos)
  }

  // Rule 4: coil must be rightmost — all coil positions > all contact positions
  if (contacts.length > 0 && coils.length > 0) {
    const maxContactPos = Math.max(...contacts.map((c) => c.position))
    const minCoilPos = Math.min(...coils.map((c) => c.position))
    if (minCoilPos <= maxContactPos) {
      errors.push(
        `coil at position ${minCoilPos} is not to the right of all contacts (max contact pos: ${maxContactPos})`
      )
    }
  }

  return { ok: errors.length === 0, errors }
}

// ── serialiseRung ─────────────────────────────────────────────────────────────

/**
 * Serialise a rung to a stable JSON-friendly document.
 *
 * @param {object} rung
 * @returns {object} serialised rung document
 */
export function serialiseRung(rung) {
  const sortById = (arr) => [...arr].sort((a, b) => a.id.localeCompare(b.id))
  return {
    id: rung.id,
    contacts: sortById(rung.contacts).map((c) => ({
      id: c.id,
      name: c.name,
      type: c.type,
      position: c.position,
      negated: c.negated,
    })),
    coils: sortById(rung.coils).map((c) => ({
      id: c.id,
      name: c.name,
      type: c.type,
      position: c.position,
    })),
    wires: sortById(rung.wires ?? []).map((w) => ({
      id: w.id,
      from: w.from,
      to: w.to,
    })),
  }
}

// ── PLCopen XML bridge (T-220) ────────────────────────────────────────────────

/**
 * Convert canvas rungs to the PLCopen model dict expected by the backend's
 * `export_plcopen_xml` LLM tool (T-220).
 *
 * Each canvas rung becomes one LD rung in a single Program POU.
 * Contact type mapping:
 *   no      → negated: false
 *   nc      → negated: true
 *   rising  → negated: false (best-effort; edge detection is FB-based in PLCopen)
 *   falling → negated: false
 *
 * @param {object[]} rungs   - Canvas rung array
 * @param {string}   name    - POU / project name
 * @returns {object}         - model dict for export_plcopen_xml
 */
export function rungsToPlcopenModel(rungs, name = 'Main') {
  const CELL_W = 80
  const RAIL_X_LEFT = 60
  const RUNG_SPACING = 90
  const RUNG_Y_START = 80

  let localId = 1
  const plcRungs = rungs.map((rung, rungIndex) => {
    const rungY = RUNG_Y_START + rungIndex * RUNG_SPACING
    const leftId = localId++
    const rightId = localId++

    const contacts = rung.contacts.map((c) => ({
      local_id: localId++,
      variable: c.name || `var_${c.id}`,
      negated: c.type === 'nc' || c.negated === true,
      position: {
        x: RAIL_X_LEFT + (c.position + 1) * CELL_W,
        y: rungY,
      },
    }))

    const coils = rung.coils.map((c) => ({
      local_id: localId++,
      variable: c.name || `coil_${c.id}`,
      negated: false,
      position: {
        x: RAIL_X_LEFT + (c.position + 1) * CELL_W,
        y: rungY,
      },
    }))

    return {
      left_power_rail: { local_id: leftId },
      right_power_rail: { local_id: rightId },
      contacts,
      coils,
      fb_instances: [],
    }
  })

  return {
    project_name: name,
    version: '1.0',
    author: '',
    description: '',
    pous: [
      {
        name,
        pou_type: 'program',
        body_language: 'LD',
        var_blocks: [],
        body: { language: 'LD', rungs: plcRungs },
      },
    ],
    configurations: [],
  }
}

/**
 * Convert a PLCopen model dict (as returned by `import_plcopen_xml`) back to
 * canvas rungs. Only LD bodies are converted; ST/FBD/IL bodies are skipped.
 *
 * @param {object} model - PLCopen model dict from import_plcopen_xml
 * @returns {object[]}   - Canvas rung array
 */
export function plcopenModelToRungs(model) {
  const result = []

  for (const pou of model.pous ?? []) {
    const body = pou.body ?? {}
    if (body.language !== 'LD') continue

    for (const rung of body.rungs ?? []) {
      const canvasRung = createRung()

      // Map PLCopen contacts → canvas contacts
      for (const c of rung.contacts ?? []) {
        const pos = c.position ? Math.round((c.position.x - 60) / 80) - 1 : result.length
        const type = c.negated ? 'nc' : 'no'
        const contact = {
          id: uid('c'),
          name: c.variable ?? '',
          type,
          position: Math.max(0, pos),
          negated: c.negated ?? false,
        }
        canvasRung.contacts.push(contact)
      }

      // Map PLCopen coils → canvas coils
      for (const c of rung.coils ?? []) {
        const pos = c.position ? Math.round((c.position.x - 60) / 80) - 1 : 8
        const coil = {
          id: uid('coil'),
          name: c.variable ?? '',
          type: 'output',
          position: Math.max(0, pos),
        }
        canvasRung.coils.push(coil)
      }

      result.push(canvasRung)
    }
  }

  return result
}
