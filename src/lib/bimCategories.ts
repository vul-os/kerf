/**
 * bimCategories.js — BIM element categories and hosted-element relationships.
 *
 * Pure JS — no external dependencies.
 * Consumed by LLM tools (bim_categories.py) and eventually by BIMView / families / schedules.
 */

// ── Constants ──────────────────────────────────────────────────────────────────

export const CATEGORIES = [
  'Wall',
  'Floor',
  'Roof',
  'Door',
  'Window',
  'Room',
  'Column',
  'Beam',
  'Stair',
  'Railing',
  'Casework',
  'Site',
  'Generic',
  'MEP_Duct',
  'MEP_Pipe',
  'MEP_Conduit',
]

/**
 * HOST_RULES[hostedCategory] = array of valid host categories.
 * Empty array means the category cannot be hosted on anything.
 */
export const HOST_RULES = {
  Door:        ['Wall'],
  Window:      ['Wall'],
  Casework:    ['Floor', 'Wall'],
  MEP_Duct:    [],
  MEP_Pipe:    [],
  MEP_Conduit: [],
}

// ── Validation helpers ─────────────────────────────────────────────────────────

/**
 * Returns true if `category` is a member of the CATEGORIES enum.
 * @param {string} category
 * @returns {boolean}
 */
export function validateCategory(category) {
  return CATEGORIES.includes(category)
}

/**
 * Returns true if `hostedCategory` is allowed to be hosted on `hostCategory`.
 *
 * Rules:
 *  - If hostedCategory has no entry in HOST_RULES, any host is allowed
 *    (the category is unconstrained).
 *  - If the entry exists but is empty ([]), no host is allowed.
 *  - Otherwise the hostCategory must appear in the list.
 *
 * @param {string} hostedCategory
 * @param {string} hostCategory
 * @returns {boolean}
 */
export function validateHostRef(hostedCategory, hostCategory) {
  if (!(hostedCategory in HOST_RULES)) {
    // Unconstrained — any host is valid
    return true
  }
  const allowed = HOST_RULES[hostedCategory]
  if (allowed.length === 0) {
    // Explicitly forbidden from hosting
    return false
  }
  return allowed.includes(hostCategory)
}

// ── Doc-level helpers ──────────────────────────────────────────────────────────

/**
 * Collect every element object across all array-typed fields of bim_doc.
 * Returns [{element, arrayKey, index}, ...].
 */
function _allElements(bim_doc) {
  const results = []
  for (const [key, val] of Object.entries(bim_doc)) {
    if (Array.isArray(val)) {
      val.forEach((el, i) => {
        if (el && typeof el === 'object') {
          results.push({ element: el, arrayKey: key, index: i })
        }
      })
    }
  }
  return results
}

/**
 * Find all element ids that are directly hosted on host_id.
 *
 * @param {object} bim_doc
 * @param {string} host_id
 * @returns {string[]} array of element ids
 */
export function findHostedElements(bim_doc, host_id) {
  return _allElements(bim_doc)
    .filter(({ element }) => element.host_ref === host_id && element.id != null)
    .map(({ element }) => element.id)
}

/**
 * Collect all element ids transitively hosted on host_id (depth-first).
 */
function _descendantIds(bim_doc, host_id) {
  const direct = findHostedElements(bim_doc, host_id)
  const all = []
  for (const id of direct) {
    all.push(id)
    all.push(..._descendantIds(bim_doc, id))
  }
  return all
}

/**
 * Apply a translation delta to a single element's position.
 * Handles elements with `position: [x,y,z]` or `from`/`to` 2-D coordinates.
 */
function _translateElement(element, delta) {
  const [dx, dy, dz = 0] = delta
  const el = { ...element }

  if (Array.isArray(el.position)) {
    const [x = 0, y = 0, z = 0] = el.position
    el.position = [x + dx, y + dy, z + dz]
  }

  if (Array.isArray(el.from)) {
    const [fx = 0, fy = 0, fz = 0] = el.from
    el.from = el.from.length === 3 ? [fx + dx, fy + dy, fz + dz] : [fx + dx, fy + dy]
  }

  if (Array.isArray(el.to)) {
    const [tx = 0, ty = 0, tz = 0] = el.to
    el.to = el.to.length === 3 ? [tx + dx, ty + dy, tz + dz] : [tx + dx, ty + dy]
  }

  return el
}

/**
 * Translate the element with `host_id` AND all its transitively hosted
 * descendants by `delta = [dx, dy, dz]`.
 *
 * Returns a new bim_doc (the original is not mutated).
 *
 * @param {object} bim_doc
 * @param {string} host_id  — id of the element being moved
 * @param {number[]} delta  — [dx, dy, dz] in millimetres
 * @returns {object} new bim_doc
 */
export function cascadeTransform(bim_doc, host_id, delta) {
  // Collect all ids to move: the host itself + all descendants
  const toMove = new Set([host_id, ..._descendantIds(bim_doc, host_id)])

  const newDoc = { ...bim_doc }
  for (const [key, val] of Object.entries(bim_doc)) {
    if (!Array.isArray(val)) continue
    newDoc[key] = val.map((el) => {
      if (el && typeof el === 'object' && toMove.has(el.id)) {
        return _translateElement(el, delta)
      }
      return el
    })
  }
  return newDoc
}

/**
 * Remove element with `element_id` and all elements transitively hosted on it.
 *
 * If any elements outside the removed set reference a removed element via
 * `host_ref`, a console.warn is emitted listing those orphan ids.
 *
 * Returns a new bim_doc (the original is not mutated).
 *
 * @param {object} bim_doc
 * @param {string} element_id
 * @returns {object} new bim_doc
 */
export function removeWithHosted(bim_doc, element_id) {
  const toRemove = new Set([element_id, ..._descendantIds(bim_doc, element_id)])

  const newDoc = { ...bim_doc }
  for (const [key, val] of Object.entries(bim_doc)) {
    if (!Array.isArray(val)) continue
    newDoc[key] = val.filter((el) => {
      if (el && typeof el === 'object' && el.id != null) {
        return !toRemove.has(el.id)
      }
      return true
    })
  }

  // Orphan check: remaining elements whose host_ref points at a removed id
  const orphans = _allElements(newDoc)
    .filter(({ element }) => element.host_ref != null && toRemove.has(element.host_ref))
    .map(({ element }) => element.id)

  if (orphans.length > 0) {
    console.warn(
      `removeWithHosted: ${orphans.length} element(s) now have a dangling host_ref after removing "${element_id}": ${orphans.join(', ')}`
    )
  }

  return newDoc
}
