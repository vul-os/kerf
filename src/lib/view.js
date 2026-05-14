// view.js — Pure helpers for .view.json (Revit-parity saved views).
//
// A view captures what you're looking at: plan, section, elevation, or 3d.
// It stores the BIM file reference, cut plane, crop box, per-element display
// overrides, and attached annotations (tags, dimensions, leaders).

const uuidv4 = () => crypto.randomUUID()

// ── Constants ─────────────────────────────────────────────────────────────────

export const VALID_KINDS = ['plan', 'section', 'elevation', '3d']

// ── defaultView ───────────────────────────────────────────────────────────────

/**
 * Return a minimal valid view document.
 * @param {'plan'|'section'|'elevation'|'3d'} kind
 * @param {string} bim_file_id
 * @returns {object}
 */
export function defaultView(kind, bim_file_id) {
  return {
    version: 1,
    id: uuidv4(),
    name: '',
    kind,
    bim_file_id: bim_file_id ?? '',
    level_id: null,
    cut_plane_z_mm: null,
    section_origin: null,
    section_direction: null,
    crop_box: null,
    filters: [],
    display_overrides: { by_category: {} },
    annotations: [],
  }
}

// ── validateView ──────────────────────────────────────────────────────────────

/**
 * Validate a view document.
 * @param {object} view
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateView(view) {
  const errors = []

  if (!view || typeof view !== 'object') {
    return { ok: false, errors: ['view must be an object'] }
  }
  if (view.version !== 1) errors.push('version must be 1')
  if (!VALID_KINDS.includes(view.kind)) {
    errors.push(`kind must be one of ${VALID_KINDS.join(', ')}`)
  }
  if (!view.bim_file_id || typeof view.bim_file_id !== 'string') {
    errors.push('bim_file_id is required')
  }
  if (view.kind === 'plan' && view.cut_plane_z_mm != null && typeof view.cut_plane_z_mm !== 'number') {
    errors.push('cut_plane_z_mm must be a number')
  }
  if (['section', 'elevation'].includes(view.kind)) {
    if (view.section_origin != null && !_isVec3(view.section_origin)) {
      errors.push('section_origin must be a [x,y,z] array')
    }
    if (view.section_direction != null && !_isVec3(view.section_direction)) {
      errors.push('section_direction must be a [x,y,z] array')
    }
  }
  if (view.crop_box != null) {
    if (!_isVec3(view.crop_box.min) || !_isVec3(view.crop_box.max)) {
      errors.push('crop_box must have min and max as [x,y,z] arrays')
    }
  }
  if (!Array.isArray(view.filters)) {
    errors.push('filters must be an array')
  }
  if (!Array.isArray(view.annotations)) {
    errors.push('annotations must be an array')
  }

  return { ok: errors.length === 0, errors }
}

// ── Filter evaluation ─────────────────────────────────────────────────────────

// Simple expression evaluator: supports field=='value', field>value,
// field<value, field>='value', field<='value', AND, OR.
// Returns a boolean.

function _evalExpr(expr, element) {
  if (!expr || typeof expr !== 'string') return true
  const upper = expr.trim()

  // OR splits on outermost OR
  const orParts = _splitTopLevel(upper, ' OR ')
  if (orParts.length > 1) {
    return orParts.some(p => _evalExpr(p, element))
  }

  // AND splits on outermost AND
  const andParts = _splitTopLevel(upper, ' AND ')
  if (andParts.length > 1) {
    return andParts.every(p => _evalExpr(p, element))
  }

  // single comparison: field OP value (value may be 'quoted' or unquoted number)
  const cmpMatch = upper.match(/^(\w+)\s*(>=|<=|!=|>|<|==)\s*('([^']*)'|(\S+))$/)
  if (!cmpMatch) return true // unparseable → pass through
  const [, field, op, , quotedVal, rawVal] = cmpMatch
  const rhs = quotedVal !== undefined ? quotedVal : rawVal
  const lhs = element[field]
  if (lhs === undefined) return false
  const lhsStr = String(lhs)
  const lhsNum = parseFloat(lhs)
  const rhsNum = parseFloat(rhs)

  switch (op) {
    case '==': return lhsStr === rhs
    case '!=': return lhsStr !== rhs
    case '>':  return !isNaN(lhsNum) && !isNaN(rhsNum) ? lhsNum > rhsNum : lhsStr > rhs
    case '<':  return !isNaN(lhsNum) && !isNaN(rhsNum) ? lhsNum < rhsNum : lhsStr < rhs
    case '>=': return !isNaN(lhsNum) && !isNaN(rhsNum) ? lhsNum >= rhsNum : lhsStr >= rhs
    case '<=': return !isNaN(lhsNum) && !isNaN(rhsNum) ? lhsNum <= rhsNum : lhsStr <= rhs
    default:   return true
  }
}

function _splitTopLevel(expr, sep) {
  // naive split (no paren nesting needed for current grammar)
  const parts = expr.split(sep)
  return parts.length > 1 ? parts : [expr]
}

/**
 * Apply the view's filter list to a BIM document and return the visible elements.
 * @param {object} view
 * @param {{ elements: object[] }} bim_doc
 * @returns {object[]}
 */
export function applyFilters(view, bim_doc) {
  if (!bim_doc || !Array.isArray(bim_doc.elements)) return []
  const filters = view?.filters ?? []
  if (filters.length === 0) return [...bim_doc.elements]

  return bim_doc.elements.filter(el =>
    filters.every(f => {
      const expr = typeof f === 'string' ? f : f.expr
      return _evalExpr(expr, el)
    })
  )
}

// ── Annotation helpers ────────────────────────────────────────────────────────

/**
 * Add an annotation to the view, assigning a uuid id if not provided.
 * Returns a new view (immutable style).
 * @param {object} view
 * @param {object} annotation
 * @returns {object}
 */
export function addAnnotation(view, annotation) {
  if (!annotation || typeof annotation !== 'object') {
    throw new Error('annotation must be an object')
  }
  const ann = { id: uuidv4(), ...annotation }
  return { ...view, annotations: [...(view.annotations ?? []), ann] }
}

/**
 * Remove an annotation by id.
 * @param {object} view
 * @param {string} annotation_id
 * @returns {object}
 */
export function removeAnnotation(view, annotation_id) {
  return {
    ...view,
    annotations: (view.annotations ?? []).filter(a => a.id !== annotation_id),
  }
}

// ── Crop box helpers ──────────────────────────────────────────────────────────

/**
 * Set (or replace) the crop box.
 * @param {object} view
 * @param {[number,number,number]} min
 * @param {[number,number,number]} max
 * @returns {object}
 */
export function setCropBox(view, min, max) {
  if (!_isVec3(min) || !_isVec3(max)) {
    throw new Error('min and max must be [x,y,z] arrays')
  }
  return { ...view, crop_box: { min, max } }
}

/**
 * Remove the crop box.
 * @param {object} view
 * @returns {object}
 */
export function clearCropBox(view) {
  return { ...view, crop_box: null }
}

// ── Internal helpers ──────────────────────────────────────────────────────────

function _isVec3(v) {
  return Array.isArray(v) && v.length === 3 && v.every(n => typeof n === 'number')
}
