// gdntAnnotations.js — Pure data-layer helpers for GD&T FCF placement.
//
// These functions accept a `drawing` document and return a new (immutable)
// drawing with GD&T annotations added/updated. They mirror the pattern used
// in draftingComplete.js and are intentionally framework-agnostic so they
// can be tested without any JSX / VDOM overhead.
//
// FCF format (per ISO 1101:2017 / ASME Y14.5-2018):
//   | symbol | ⌀?tol modifier? | datumA | datumB | datumC |
//
// Each stored annotation has kind='fcf' and the fields below.
// Datum annotations have kind='gdt_datum' and carry a label + position.

// ---------------------------------------------------------------------------
// GD&T symbol catalogue — ISO 1101 codes + Unicode + human labels.

export const GDT_SYMBOLS = [
  // Form
  { code: 'straightness',      unicode: '⎯', name: 'Straightness',        category: 'form' },
  { code: 'flatness',          unicode: '▱', name: 'Flatness',            category: 'form' },
  { code: 'circularity',       unicode: '○', name: 'Circularity',         category: 'form' },
  { code: 'cylindricity',      unicode: '⌭', name: 'Cylindricity',        category: 'form' },
  // Profile
  { code: 'profile_line',      unicode: '⌒', name: 'Profile of a Line',   category: 'profile' },
  { code: 'profile_surface',   unicode: '⌓', name: 'Profile of a Surface',category: 'profile' },
  // Orientation
  { code: 'angularity',        unicode: '∠', name: 'Angularity',          category: 'orientation' },
  { code: 'perpendicularity',  unicode: '⟂', name: 'Perpendicularity',    category: 'orientation' },
  { code: 'parallelism',       unicode: '∥', name: 'Parallelism',         category: 'orientation' },
  // Location
  { code: 'position',          unicode: '⌖', name: 'Position',            category: 'location' },
  { code: 'concentricity',     unicode: '◎', name: 'Concentricity',       category: 'location' },
  { code: 'symmetry',          unicode: '⌯', name: 'Symmetry',            category: 'location' },
  // Runout
  { code: 'circular_runout',   unicode: '↗', name: 'Circular Runout',     category: 'runout' },
  { code: 'total_runout',      unicode: '⇈', name: 'Total Runout',        category: 'runout' },
]

export const GDT_SYMBOL_MAP = Object.fromEntries(GDT_SYMBOLS.map((s) => [s.code, s]))

// Datum labels A/B/C (the standard 3-datum reference frame).
export const DATUM_LABELS = ['A', 'B', 'C', 'D', 'E', 'F']

// ---------------------------------------------------------------------------
// FCF rendering helper — produces the canonical text form of a FCF.
//
//   renderFcf({ symbol_code, tolerance_value, diameter_zone,
//               tolerance_modifier, datum_refs }) → string
//
// Example: ⏐⌖⏐∅0.5 Ⓜ⏐A⏐B⏐

export function renderFcf(fcf) {
  const sym = GDT_SYMBOL_MAP[fcf.symbol_code]
  if (!sym) return '?'
  const symChar = sym.unicode
  const diaPrefix = fcf.diameter_zone ? '⌀' : ''
  const tolStr = Number.isFinite(fcf.tolerance_value) ? String(fcf.tolerance_value) : ''
  const modMap = { M: 'Ⓜ', L: 'Ⓛ', S: 'Ⓢ', F: 'Ⓕ', P: 'Ⓟ', T: 'Ⓣ' }
  const modStr = fcf.tolerance_modifier ? ` ${modMap[fcf.tolerance_modifier] || fcf.tolerance_modifier}` : ''
  const tolCompartment = `${diaPrefix}${tolStr}${modStr}`
  const datumParts = (fcf.datum_refs || []).map((dr) => `⏐${dr.label}${dr.modifier ? ` ${modMap[dr.modifier] || dr.modifier}` : ''}`).join('')
  const trailing = (fcf.datum_refs || []).length > 0 ? '⏐' : ''
  return `⏐${symChar}⏐${tolCompartment}${datumParts}${trailing}`
}

// ---------------------------------------------------------------------------
// Internal helper — resolve active sheet annotations from a drawing doc.
// Returns [annotations, sheetUpdater] where sheetUpdater(newAnnotations)
// returns the updated drawing (immutable).

function resolveSheet(drawing) {
  const hasSheets = drawing.sheets && drawing.sheets.length > 0
  if (hasSheets) {
    const idx = Math.min(drawing.currentSheet ?? 0, drawing.sheets.length - 1)
    const sheet = drawing.sheets[idx]
    const updateSheet = (newAnns) => {
      const nextSheets = drawing.sheets.map((s, i) =>
        i === idx ? { ...s, annotations: newAnns } : s,
      )
      return { ...drawing, sheets: nextSheets }
    }
    return [sheet.annotations || [], updateSheet]
  }
  const updateFlat = (newAnns) => ({ ...drawing, annotations: newAnns })
  return [drawing.annotations || [], updateFlat]
}

// ---------------------------------------------------------------------------
// addFcf — place a Feature Control Frame annotation at (x, y) in page-mm.
//
//   addFcf(drawing, {
//     x, y,                     // anchor (leader root or direct position)
//     symbol_code,              // e.g. 'perpendicularity'
//     tolerance_value,          // e.g. 0.1
//     diameter_zone?,           // boolean
//     tolerance_modifier?,      // 'M' | 'L' | ...
//     datum_refs?,              // [{ label: 'A', modifier: null }, ...]
//     view_id?,                 // page view id
//     target_id?,               // face/edge id from the 3D topology
//     leader_from?,             // {x, y} arrow tip (edge mid-point on 2D proj)
//     note?,                    // free-form text
//   })
//   → newDrawing

export function addFcf(drawing, opts) {
  const {
    x, y,
    symbol_code,
    tolerance_value,
    diameter_zone = false,
    tolerance_modifier = null,
    datum_refs = [],
    view_id = null,
    target_id = null,
    leader_from = null,
    note = null,
  } = opts || {}

  if (!symbol_code) throw new Error('addFcf: symbol_code is required')
  if (!GDT_SYMBOL_MAP[symbol_code]) throw new Error(`addFcf: unknown symbol_code ${symbol_code}`)
  if (tolerance_value == null || !Number.isFinite(Number(tolerance_value))) {
    throw new Error('addFcf: tolerance_value must be a finite number')
  }

  const [anns, updateSheet] = resolveSheet(drawing)
  const id = `fcf-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

  const fcf = {
    id,
    kind: 'fcf',
    x: Number(x),
    y: Number(y),
    symbol_code,
    tolerance_value: Number(tolerance_value),
    diameter_zone: Boolean(diameter_zone),
    tolerance_modifier: tolerance_modifier || null,
    datum_refs: datum_refs.map((dr) => ({ label: dr.label, modifier: dr.modifier || null })),
    view_id: view_id || null,
    target_id: target_id || null,
    leader_from: leader_from ? { x: Number(leader_from.x), y: Number(leader_from.y) } : null,
    note: note || null,
    rendered: renderFcf({ symbol_code, tolerance_value, diameter_zone, tolerance_modifier, datum_refs }),
  }

  return updateSheet([...anns, fcf])
}

// ---------------------------------------------------------------------------
// addDatumLabel — place a datum triangle identifier at (x, y).
//
//   addDatumLabel(drawing, { x, y, label, view_id?, target_id? })
//   → newDrawing

export function addDatumLabel(drawing, opts) {
  const { x, y, label, view_id = null, target_id = null } = opts || {}
  if (!label) throw new Error('addDatumLabel: label is required')

  const [anns, updateSheet] = resolveSheet(drawing)
  const id = `datum-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

  const datum = {
    id,
    kind: 'gdt_datum',
    x: Number(x),
    y: Number(y),
    label: String(label).toUpperCase().slice(0, 4),
    view_id: view_id || null,
    target_id: target_id || null,
  }

  return updateSheet([...anns, datum])
}

// ---------------------------------------------------------------------------
// listFcfs — return all FCF annotations on the active sheet.

export function listFcfs(drawing) {
  const [anns] = resolveSheet(drawing)
  return anns.filter((a) => a.kind === 'fcf')
}

// ---------------------------------------------------------------------------
// listDatumLabels — return all datum label annotations on the active sheet.

export function listDatumLabels(drawing) {
  const [anns] = resolveSheet(drawing)
  return anns.filter((a) => a.kind === 'gdt_datum')
}
