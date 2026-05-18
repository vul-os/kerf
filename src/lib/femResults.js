/**
 * Helpers for parsing and working with the unified FEM Result JSON shape
 * as returned by the kerf-fem worker (FEMResult.to_dict()).
 *
 * The canonical result shape is:
 * {
 *   max_vonmises_stress: number,      // Pa
 *   max_displacement:    number,      // m
 *   displacement: {
 *     node_displacements: [{ux,uy,uz,mag?}, ...],
 *     stresses:           [number, ...]           // per-cell DG0 von Mises [Pa]
 *   },
 *   fos:           number,
 *   frequencies:   [number, ...],     // Hz (modal)
 *   mode_shapes:   [...],             // per-mode node displacements
 *   temperatures:  [number, ...],     // per-node [K] (thermal)
 *   warnings:      [string, ...],
 *   errors:        [string, ...],
 * }
 *
 * This module provides:
 *   parseFEMResult(raw)           — validate + normalise the raw JSON
 *   availableFields(result)       — list of displayable field names
 *   pickColorConfig(result, field) — colour scale + normalisation config
 *   fieldLabel(field)             — human-readable label
 *   fieldUnit(field)              — SI unit string
 */

// ── field constants ───────────────────────────────────────────────────────────

export const FIELD_DISPLACEMENT = 'displacement'
export const FIELD_VONMISES     = 'vonmises'
export const FIELD_TEMPERATURE  = 'temperature'
export const FIELD_MODAL        = 'modal'

// Default colour-scale assignment per field
const FIELD_DEFAULT_SCALE = {
  [FIELD_DISPLACEMENT]: 'viridis',
  [FIELD_VONMISES]:     'plasma',
  [FIELD_TEMPERATURE]:  'coolwarm',
  [FIELD_MODAL]:        'jet',
}

// ── parsing ───────────────────────────────────────────────────────────────────

/**
 * Validate and normalise a raw result object returned by the FEM backend.
 *
 * Returns a normalised result object with guaranteed keys and sensible
 * defaults for missing fields.  Throws a TypeError for obviously invalid input.
 *
 * @param {object} raw  Raw JSON-parsed result from the API
 * @returns {NormalisedFEMResult}
 */
export function parseFEMResult(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new TypeError('parseFEMResult: expected a plain object')
  }

  const displacement = raw.displacement || {}
  const nodeDisplacements = Array.isArray(displacement.node_displacements)
    ? displacement.node_displacements.map(normaliseNodeDisplacement)
    : []
  const stresses = Array.isArray(displacement.stresses) ? displacement.stresses : []

  const temperatures = Array.isArray(raw.temperatures) ? raw.temperatures : []
  const frequencies = Array.isArray(raw.frequencies) ? raw.frequencies : []
  const modeShapes = Array.isArray(raw.mode_shapes) ? raw.mode_shapes : []

  const maxVonmises = typeof raw.max_vonmises_stress === 'number' ? raw.max_vonmises_stress : null
  const maxDisp = typeof raw.max_displacement === 'number' ? raw.max_displacement : null

  // Derive maxes from data when backend didn't report them
  const computedMaxDisp = maxDisp !== null
    ? maxDisp
    : nodeDisplacements.reduce((m, d) => Math.max(m, d.mag), 0)

  const computedMaxVonmises = maxVonmises !== null
    ? maxVonmises
    : stresses.reduce((m, s) => Math.max(m, s), 0)

  const computedMaxTemp = temperatures.reduce((m, t) => Math.max(m, t), 0)
  const computedMinTemp = temperatures.reduce((m, t) => Math.min(m, t), Infinity)

  return {
    nodeDisplacements,
    stresses,
    temperatures,
    frequencies,
    modeShapes,
    maxDisplacement: computedMaxDisp,
    maxVonmises: computedMaxVonmises,
    maxTemperature: computedMaxTemp,
    minTemperature: computedMinTemp === Infinity ? 0 : computedMinTemp,
    fos: typeof raw.fos === 'number' ? raw.fos : null,
    warnings: Array.isArray(raw.warnings) ? raw.warnings : [],
    errors: Array.isArray(raw.errors) ? raw.errors : [],
  }
}

/**
 * Ensure a node-displacement entry has ux, uy, uz, and mag.
 */
function normaliseNodeDisplacement(d) {
  if (!d || typeof d !== 'object') return { ux: 0, uy: 0, uz: 0, mag: 0 }
  const ux = typeof d.ux === 'number' ? d.ux : 0
  const uy = typeof d.uy === 'number' ? d.uy : 0
  const uz = typeof d.uz === 'number' ? d.uz : 0
  const mag = typeof d.mag === 'number' ? d.mag : Math.sqrt(ux * ux + uy * uy + uz * uz)
  return { ux, uy, uz, mag }
}

// ── available fields ──────────────────────────────────────────────────────────

/**
 * Return the list of field identifiers that can actually be displayed
 * for this result (i.e. have non-empty data).
 *
 * @param {NormalisedFEMResult} result
 * @returns {string[]}
 */
export function availableFields(result) {
  if (!result) return []
  const fields = []
  if (result.nodeDisplacements.length > 0) fields.push(FIELD_DISPLACEMENT)
  if (result.stresses.length > 0) fields.push(FIELD_VONMISES)
  if (result.temperatures.length > 0) fields.push(FIELD_TEMPERATURE)
  if (result.modeShapes.length > 0) fields.push(FIELD_MODAL)
  return fields
}

// ── colour config ─────────────────────────────────────────────────────────────

/**
 * Return a colour configuration object for use with FEMDeformedShape / colour
 * bar rendering.
 *
 * @param {NormalisedFEMResult} result
 * @param {string} field  One of the FIELD_* constants
 * @param {string} [scaleName]  Override palette (default chosen per field)
 * @returns {{
 *   scaleName: string,
 *   minValue: number,
 *   maxValue: number,
 *   label: string,
 *   unit: string,
 *   colorMode: string,   // matches FEMDeformedShape colorMode prop
 * }}
 */
export function pickColorConfig(result, field, scaleName) {
  const palette = scaleName || FIELD_DEFAULT_SCALE[field] || 'viridis'

  switch (field) {
    case FIELD_VONMISES:
      return {
        scaleName: palette,
        minValue: 0,
        maxValue: result.maxVonmises,
        label: fieldLabel(field),
        unit: fieldUnit(field),
        colorMode: 'vonmises',
      }

    case FIELD_TEMPERATURE:
      return {
        scaleName: palette,
        minValue: result.minTemperature,
        maxValue: result.maxTemperature,
        label: fieldLabel(field),
        unit: fieldUnit(field),
        colorMode: 'temperature',
      }

    case FIELD_MODAL:
      return {
        scaleName: palette,
        minValue: 0,
        maxValue: 1,
        label: fieldLabel(field),
        unit: fieldUnit(field),
        colorMode: 'modal',
      }

    case FIELD_DISPLACEMENT:
    default:
      return {
        scaleName: palette,
        minValue: 0,
        maxValue: result.maxDisplacement,
        label: fieldLabel(field),
        unit: fieldUnit(field),
        colorMode: 'displacement',
      }
  }
}

// ── labels / units ────────────────────────────────────────────────────────────

const FIELD_LABELS = {
  [FIELD_DISPLACEMENT]: 'Displacement |u|',
  [FIELD_VONMISES]:     'von Mises σ',
  [FIELD_TEMPERATURE]:  'Temperature T',
  [FIELD_MODAL]:        'Mode shape (norm.)',
}

const FIELD_UNITS = {
  [FIELD_DISPLACEMENT]: 'mm',
  [FIELD_VONMISES]:     'MPa',
  [FIELD_TEMPERATURE]:  'K',
  [FIELD_MODAL]:        '—',
}

/**
 * Human-readable label for a result field.
 * @param {string} field
 * @returns {string}
 */
export function fieldLabel(field) {
  return FIELD_LABELS[field] || field
}

/**
 * SI unit string for a result field.
 * @param {string} field
 * @returns {string}
 */
export function fieldUnit(field) {
  return FIELD_UNITS[field] || ''
}

// ── scalar extraction helpers ─────────────────────────────────────────────────

/**
 * Extract the per-node scalar array for the given field.
 * Returns a plain Array (not Float32Array) of numbers.
 *
 * @param {NormalisedFEMResult} result
 * @param {string} field
 * @param {number} [modeIndex=0]  Which mode to extract for FIELD_MODAL
 * @returns {number[]}
 */
export function extractScalars(result, field, modeIndex = 0) {
  switch (field) {
    case FIELD_VONMISES:
      return result.stresses.slice()

    case FIELD_TEMPERATURE:
      return result.temperatures.slice()

    case FIELD_MODAL: {
      const shape = result.modeShapes[modeIndex]
      if (!Array.isArray(shape)) return []
      return shape.map(d => {
        if (typeof d === 'number') return d
        if (d && typeof d === 'object') {
          const ux = d.ux || 0
          const uy = d.uy || 0
          const uz = d.uz || 0
          return Math.sqrt(ux * ux + uy * uy + uz * uz)
        }
        return 0
      })
    }

    case FIELD_DISPLACEMENT:
    default:
      return result.nodeDisplacements.map(d => d.mag)
  }
}

/**
 * Normalise a scalar array to [0, 1] using min/max from pickColorConfig.
 *
 * @param {number[]} scalars
 * @param {number} minValue
 * @param {number} maxValue
 * @returns {number[]}
 */
export function normaliseScalars(scalars, minValue, maxValue) {
  const range = maxValue - minValue
  if (range === 0) return scalars.map(() => 0)
  return scalars.map(v => Math.max(0, Math.min(1, (v - minValue) / range)))
}
