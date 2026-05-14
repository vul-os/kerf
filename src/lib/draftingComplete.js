// draftingComplete.js — drafting completeness helpers.
//
// Pure data-layer functions that return new drawing objects (no mutation).
// These are intentionally framework-agnostic: they accept a `drawing`
// document and return an updated one, following the same immutable pattern
// used throughout the lib/ folder.

// ---------------------------------------------------------------------------
// HATCH_PATTERNS — named fill patterns available in the hatch picker.
// Mirrors the seed/hatch_library/ JSON files in minimal form.

export const HATCH_PATTERNS = [
  { id: 'ansi31', name: 'ANSI 31 – General (45°)', angle: 45, spacing: 2.5 },
  { id: 'ansi32', name: 'ANSI 32 – Steel', angle: 45, spacing: 1.5 },
  { id: 'ansi33', name: 'ANSI 33 – Brass/Bronze', angle: 45, spacing: 1.5 },
  { id: 'ansi34', name: 'ANSI 34 – Plastic', angle: 45, spacing: 1.5 },
  { id: 'ansi35', name: 'ANSI 35 – Rubber', angle: 45, spacing: 1.5 },
  { id: 'ansi36', name: 'ANSI 36 – Aluminium', angle: 45, spacing: 1.5 },
  { id: 'ansi37', name: 'ANSI 37 – Cast Iron', angle: 45, spacing: 2.0 },
  { id: 'ansi38', name: 'ANSI 38 – Titanium', angle: 45, spacing: 1.2 },
  { id: 'iso07w100', name: 'ISO 07W100 – Cross hatch', angle: 45, spacing: 2.5 },
  { id: 'earth', name: 'Earth / Soil', angle: 45, spacing: 3.0 },
  { id: 'wood', name: 'Wood grain', angle: 0, spacing: 2.0 },
  { id: 'water', name: 'Water', angle: 30, spacing: 2.5 },
]

// ---------------------------------------------------------------------------
// patternToSvgFill — convert a HATCH_PATTERNS entry (+ optional overrides)
// into a minimal SVG <pattern> descriptor that DrawingView can render inline.
//
//   patternToSvgFill(pattern, scale?, angle?)
//   → { id, width, height, patternUnits, patternTransform, line }

export function patternToSvgFill(pattern, scale = 1, angle = null) {
  const pat = typeof pattern === 'string'
    ? (HATCH_PATTERNS.find((p) => p.id === pattern) || HATCH_PATTERNS[0])
    : pattern
  const spacing = (pat.spacing || 2.5) * scale
  const deg = angle != null ? angle : (pat.angle ?? 45)
  const id = `hatch-${pat.id}-s${scale}-a${deg}`
  return {
    id,
    width: spacing,
    height: spacing,
    patternUnits: 'userSpaceOnUse',
    patternTransform: `rotate(${deg})`,
    line: { x1: 0, y1: 0, x2: spacing, y2: 0, stroke: '#1a1f2a', strokeWidth: 0.2 },
  }
}

// ---------------------------------------------------------------------------
// addHatch — add a hatch annotation to the drawing.
//
//   addHatch(drawing, polygon, patternId, scale?, angle?)
//   polygon: [{x, y}, ...] closed polygon in page-mm coords.
//   Returns a new drawing with the hatch appended to the active sheet's
//   annotations array.

export function addHatch(drawing, polygon, patternId = 'ansi31', scale = 1, angle = null) {
  if (!polygon || polygon.length < 3) throw new Error('addHatch: polygon must have ≥ 3 points')
  const pat = HATCH_PATTERNS.find((p) => p.id === patternId) || HATCH_PATTERNS[0]
  const fill = patternToSvgFill(pat, scale, angle)
  const id = `hatch-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  const annotation = {
    id,
    kind: 'hatch',
    polygon: polygon.map((p) => ({ x: p.x, y: p.y })),
    patternId: fill.id,
    patternDef: fill,
    scale,
    angle: angle ?? pat.angle,
  }
  return _appendAnnotation(drawing, annotation)
}

// ---------------------------------------------------------------------------
// addLeader — add a leader annotation (arrow + label) to the drawing.
//
//   addLeader(drawing, from, to, text, opts?)
//   from, to: {x, y} in page-mm.
//   Returns a new drawing with the leader appended.

export function addLeader(drawing, from, to, text = '', opts = {}) {
  if (!from || !to) throw new Error('addLeader: from and to are required')
  const id = `leader-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  const annotation = {
    id,
    kind: 'leader',
    from: { x: from.x, y: from.y },
    to: { x: to.x, y: to.y },
    text: String(text),
    fontSize: opts.fontSize ?? 3.5,
    view_id: opts.view_id ?? undefined,
  }
  return _appendAnnotation(drawing, annotation)
}

// ---------------------------------------------------------------------------
// addRichText — add a rich-text annotation (multi-line, styled) to the drawing.
//
//   addRichText(drawing, x, y, text, opts?)
//   opts: { bold?, italic?, fontSize?, color?, view_id? }
//   Returns a new drawing with the rich-text annotation appended.

export function addRichText(drawing, x, y, text = '', opts = {}) {
  const id = `richtext-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  const annotation = {
    id,
    kind: 'rich_text',
    x,
    y,
    text: String(text),
    bold: opts.bold ?? false,
    italic: opts.italic ?? false,
    fontSize: opts.fontSize ?? 3.5,
    color: opts.color ?? '#1a1f2a',
    view_id: opts.view_id ?? undefined,
  }
  return _appendAnnotation(drawing, annotation)
}

// ---------------------------------------------------------------------------
// addDimensionChain — add a multi-point chain dimension to the drawing.
//
//   addDimensionChain(drawing, picks, viewId, opts?)
//   picks: [{x, y}, ...] at least 2 points in page-mm.
//   opts: { offset? } perpendicular offset in mm.
//   Returns a new drawing with the chain dimension appended.

export function addDimensionChain(drawing, picks, viewId, opts = {}) {
  if (!picks || picks.length < 2) throw new Error('addDimensionChain: need ≥ 2 picks')
  const id = `chain-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  const dimension = {
    id,
    kind: 'chain',
    view_id: viewId ?? undefined,
    picks: picks.map((p) => ({ x: p.x, y: p.y })),
    offset: opts.offset ?? 8,
  }
  return _appendDimension(drawing, dimension)
}

// ---------------------------------------------------------------------------
// Internal helpers — immutable append to the active sheet.

function _getActiveSheet(drawing) {
  if (drawing.sheets && drawing.sheets.length > 0) {
    const idx = Math.min(drawing.currentSheet ?? 0, drawing.sheets.length - 1)
    return { sheets: true, idx, sheet: drawing.sheets[idx] }
  }
  // Legacy flat drawing.
  return { sheets: false, idx: 0, sheet: drawing }
}

function _appendAnnotation(drawing, annotation) {
  const { sheets, idx, sheet } = _getActiveSheet(drawing)
  const nextSheet = {
    ...sheet,
    annotations: [...(sheet.annotations || []), annotation],
  }
  if (!sheets) return { ...nextSheet }
  const nextSheets = drawing.sheets.map((s, i) => (i === idx ? nextSheet : s))
  return { ...drawing, sheets: nextSheets }
}

function _appendDimension(drawing, dimension) {
  const { sheets, idx, sheet } = _getActiveSheet(drawing)
  const nextSheet = {
    ...sheet,
    dimensions: [...(sheet.dimensions || []), dimension],
  }
  if (!sheets) return { ...nextSheet }
  const nextSheets = drawing.sheets.map((s, i) => (i === idx ? nextSheet : s))
  return { ...drawing, sheets: nextSheets }
}
