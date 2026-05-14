// sheet.js — Pure helpers for .sheet.json (Revit-parity print-ready layouts).
//
// A sheet is a print-ready layout: paper size, title block, and one or more
// viewports that each reference a .view.json file.

const uuidv4 = () => crypto.randomUUID()

// ── Constants ─────────────────────────────────────────────────────────────────

/** Paper sizes in mm [width, height] (portrait orientation base). */
export const SHEET_SIZES_MM = {
  A0:     [841,  1189],
  A1:     [594,   841],
  A2:     [420,   594],
  A3:     [297,   420],
  A4:     [210,   297],
  ANSI_A: [216,   279],
  ANSI_B: [279,   432],
  ANSI_C: [432,   559],
  ANSI_D: [559,   864],
  ANSI_E: [864,  1118],
}

export const VALID_SIZES = Object.keys(SHEET_SIZES_MM)
export const VALID_ORIENTATIONS = ['landscape', 'portrait']

// ── defaultSheet ──────────────────────────────────────────────────────────────

/**
 * Return a minimal valid sheet document.
 * @param {string} name
 * @param {string} sheetNumber
 * @param {string} size  — e.g. 'A1'
 * @returns {object}
 */
export function defaultSheet(name, sheetNumber, size = 'A1') {
  return {
    version: 1,
    id: uuidv4(),
    name: name ?? '',
    sheet_number: sheetNumber ?? '',
    size,
    orientation: 'landscape',
    titleblock: {
      project_name: '',
      issue_date: '',
      revision: '',
      drawn_by: '',
    },
    viewports: [],
    revision_clouds: [],
  }
}

// ── validateSheet ─────────────────────────────────────────────────────────────

/**
 * Validate a sheet document.
 * @param {object} sheet
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function validateSheet(sheet) {
  const errors = []

  if (!sheet || typeof sheet !== 'object') {
    return { ok: false, errors: ['sheet must be an object'] }
  }
  if (sheet.version !== 1) errors.push('version must be 1')
  if (!sheet.name || typeof sheet.name !== 'string') errors.push('name is required')
  if (!sheet.sheet_number || typeof sheet.sheet_number !== 'string') {
    errors.push('sheet_number is required')
  }
  if (!VALID_SIZES.includes(sheet.size)) {
    errors.push(`size must be one of ${VALID_SIZES.join(', ')}`)
  }
  if (!VALID_ORIENTATIONS.includes(sheet.orientation)) {
    errors.push(`orientation must be one of ${VALID_ORIENTATIONS.join(', ')}`)
  }
  if (!Array.isArray(sheet.viewports)) errors.push('viewports must be an array')
  if (!Array.isArray(sheet.revision_clouds)) errors.push('revision_clouds must be an array')

  if (sheet.viewports) {
    sheet.viewports.forEach((vp, i) => {
      if (!vp.view_file_id) errors.push(`viewports[${i}]: view_file_id is required`)
      if (!Array.isArray(vp.position) || vp.position.length < 2) {
        errors.push(`viewports[${i}]: position must be a [x,y] array`)
      }
      if (typeof vp.scale !== 'number' || vp.scale <= 0) {
        errors.push(`viewports[${i}]: scale must be a positive number`)
      }
    })
  }

  return { ok: errors.length === 0, errors }
}

// ── Viewport helpers ──────────────────────────────────────────────────────────

/**
 * Add a viewport to the sheet.
 * @param {object} sheet
 * @param {string} view_file_id
 * @param {[number, number]} position  — [x, y] in mm from sheet origin
 * @param {number} scale               — e.g. 0.02 for 1:50
 * @param {string} [title]
 * @returns {object}
 */
export function addViewport(sheet, view_file_id, position, scale, title = '') {
  if (!view_file_id) throw new Error('view_file_id is required')
  if (!Array.isArray(position) || position.length < 2) {
    throw new Error('position must be a [x, y] array')
  }
  if (typeof scale !== 'number' || scale <= 0) {
    throw new Error('scale must be a positive number')
  }
  const vp = { id: uuidv4(), view_file_id, position, scale, title }
  return { ...sheet, viewports: [...(sheet.viewports ?? []), vp] }
}

/**
 * Remove a viewport by id.
 * @param {object} sheet
 * @param {string} viewport_id
 * @returns {object}
 */
export function removeViewport(sheet, viewport_id) {
  return {
    ...sheet,
    viewports: (sheet.viewports ?? []).filter(vp => vp.id !== viewport_id),
  }
}

/**
 * Move a viewport to a new position.
 * @param {object} sheet
 * @param {string} viewport_id
 * @param {[number, number]} position
 * @returns {object}
 */
export function moveViewport(sheet, viewport_id, position) {
  if (!Array.isArray(position) || position.length < 2) {
    throw new Error('position must be a [x, y] array')
  }
  return {
    ...sheet,
    viewports: (sheet.viewports ?? []).map(vp =>
      vp.id === viewport_id ? { ...vp, position } : vp
    ),
  }
}

// ── Revision cloud helpers ────────────────────────────────────────────────────

/**
 * Add a revision cloud.
 * @param {object} sheet
 * @param {Array<[number, number]>} polygon  — list of [x,y] points
 * @param {string} revision                  — e.g. 'A'
 * @param {string} [note]
 * @returns {object}
 */
export function addRevisionCloud(sheet, polygon, revision, note = '') {
  if (!Array.isArray(polygon) || polygon.length < 3) {
    throw new Error('polygon must be an array of at least 3 [x,y] points')
  }
  if (!revision) throw new Error('revision is required')
  const cloud = { id: uuidv4(), polygon, revision, note }
  return { ...sheet, revision_clouds: [...(sheet.revision_clouds ?? []), cloud] }
}
