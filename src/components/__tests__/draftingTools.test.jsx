// draftingTools.test.jsx — Pure data-layer tests for draftingComplete.js
//
// No React DOM rendering. Tests assert that addHatch / addLeader / addRichText
// / addDimensionChain return drawings with correctly-shaped new entities.

import { describe, it, expect } from 'vitest'
import {
  HATCH_PATTERNS,
  addHatch,
  addLeader,
  addRichText,
  addDimensionChain,
  patternToSvgFill,
} from '../../lib/draftingComplete.js'

// ---------------------------------------------------------------------------
// Minimal drawing fixtures — flat (legacy) + multi-sheet.

function flatDrawing(annOverride = [], dimOverride = []) {
  return {
    frame: { size: 'A3', orientation: 'landscape' },
    annotations: [...annOverride],
    dimensions: [...dimOverride],
  }
}

function multiSheetDrawing(annOverride = [], dimOverride = []) {
  return {
    currentSheet: 0,
    sheets: [
      {
        id: 'sheet-1',
        frame: { size: 'A3', orientation: 'landscape' },
        annotations: [...annOverride],
        dimensions: [...dimOverride],
      },
    ],
  }
}

const TRIANGLE = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 5, y: 10 }]
const FROM = { x: 5, y: 5 }
const TO = { x: 30, y: 20 }
const PICKS = [{ x: 10, y: 10 }, { x: 30, y: 10 }, { x: 50, y: 10 }]

// ── 1. HATCH_PATTERNS ────────────────────────────────────────────────────────

describe('HATCH_PATTERNS', () => {
  it('exports a non-empty array', () => {
    expect(Array.isArray(HATCH_PATTERNS)).toBe(true)
    expect(HATCH_PATTERNS.length).toBeGreaterThan(0)
  })

  it('every pattern has id, name, angle, spacing', () => {
    for (const p of HATCH_PATTERNS) {
      expect(typeof p.id).toBe('string')
      expect(typeof p.name).toBe('string')
      expect(typeof p.angle).toBe('number')
      expect(typeof p.spacing).toBe('number')
    }
  })

  it('ansi31 is the first pattern', () => {
    expect(HATCH_PATTERNS[0].id).toBe('ansi31')
  })
})

// ── 2. patternToSvgFill ───────────────────────────────────────────────────────

describe('patternToSvgFill', () => {
  it('returns an object with id, width, height, patternUnits, patternTransform, line', () => {
    const fill = patternToSvgFill(HATCH_PATTERNS[0])
    expect(fill).toHaveProperty('id')
    expect(fill).toHaveProperty('width')
    expect(fill).toHaveProperty('height')
    expect(fill).toHaveProperty('patternUnits')
    expect(fill).toHaveProperty('patternTransform')
    expect(fill).toHaveProperty('line')
  })

  it('scale factor multiplies spacing into width/height', () => {
    const base = patternToSvgFill(HATCH_PATTERNS[0], 1)
    const scaled = patternToSvgFill(HATCH_PATTERNS[0], 2)
    expect(scaled.width).toBeCloseTo(base.width * 2)
    expect(scaled.height).toBeCloseTo(base.height * 2)
  })

  it('angle override is reflected in patternTransform', () => {
    const fill = patternToSvgFill(HATCH_PATTERNS[0], 1, 30)
    expect(fill.patternTransform).toContain('30')
  })

  it('accepts a pattern id string as first arg', () => {
    const fill = patternToSvgFill('ansi31')
    expect(fill.id).toMatch(/ansi31/)
  })
})

// ── 3. addHatch ───────────────────────────────────────────────────────────────

describe('addHatch', () => {
  it('appends a hatch annotation — flat drawing', () => {
    const d = addHatch(flatDrawing(), TRIANGLE, 'ansi31')
    expect(d.annotations).toHaveLength(1)
  })

  it('appends a hatch annotation — multi-sheet drawing', () => {
    const d = addHatch(multiSheetDrawing(), TRIANGLE, 'ansi31')
    expect(d.sheets[0].annotations).toHaveLength(1)
  })

  it('hatch annotation has kind=hatch and a polygon', () => {
    const d = addHatch(flatDrawing(), TRIANGLE, 'ansi31')
    const ann = d.annotations[0]
    expect(ann.kind).toBe('hatch')
    expect(Array.isArray(ann.polygon)).toBe(true)
    expect(ann.polygon).toHaveLength(3)
  })

  it('hatch annotation carries patternDef with an id', () => {
    const d = addHatch(flatDrawing(), TRIANGLE, 'ansi32', 1.5, 30)
    const ann = d.annotations[0]
    expect(ann.patternDef).toBeDefined()
    expect(typeof ann.patternDef.id).toBe('string')
  })

  it('does not mutate the original drawing', () => {
    const orig = flatDrawing()
    addHatch(orig, TRIANGLE, 'ansi31')
    expect(orig.annotations).toHaveLength(0)
  })

  it('throws when polygon has fewer than 3 points', () => {
    expect(() => addHatch(flatDrawing(), [{ x: 0, y: 0 }])).toThrow()
  })
})

// ── 4. addLeader ──────────────────────────────────────────────────────────────

describe('addLeader', () => {
  it('appends a leader annotation', () => {
    const d = addLeader(flatDrawing(), FROM, TO, 'M6 thread')
    expect(d.annotations).toHaveLength(1)
  })

  it('leader annotation has kind=leader, from, to, text', () => {
    const d = addLeader(flatDrawing(), FROM, TO, 'R3.2')
    const ann = d.annotations[0]
    expect(ann.kind).toBe('leader')
    expect(ann.from).toEqual(FROM)
    expect(ann.to).toEqual(TO)
    expect(ann.text).toBe('R3.2')
  })

  it('appends to multi-sheet drawing correctly', () => {
    const d = addLeader(multiSheetDrawing(), FROM, TO, 'note')
    expect(d.sheets[0].annotations).toHaveLength(1)
  })

  it('does not mutate the original drawing', () => {
    const orig = flatDrawing()
    addLeader(orig, FROM, TO, 'x')
    expect(orig.annotations).toHaveLength(0)
  })

  it('throws when from or to is missing', () => {
    expect(() => addLeader(flatDrawing(), null, TO, 'x')).toThrow()
    expect(() => addLeader(flatDrawing(), FROM, null, 'x')).toThrow()
  })
})

// ── 5. addRichText ────────────────────────────────────────────────────────────

describe('addRichText', () => {
  it('appends a rich_text annotation', () => {
    const d = addRichText(flatDrawing(), 20, 30, 'TOLERANCE: ±0.05')
    expect(d.annotations).toHaveLength(1)
  })

  it('annotation has kind=rich_text, x, y, text', () => {
    const d = addRichText(flatDrawing(), 20, 30, 'NOTE 1')
    const ann = d.annotations[0]
    expect(ann.kind).toBe('rich_text')
    expect(ann.x).toBe(20)
    expect(ann.y).toBe(30)
    expect(ann.text).toBe('NOTE 1')
  })

  it('opts bold/italic/fontSize are set on the entity', () => {
    const d = addRichText(flatDrawing(), 0, 0, 'TITLE', { bold: true, italic: true, fontSize: 5 })
    const ann = d.annotations[0]
    expect(ann.bold).toBe(true)
    expect(ann.italic).toBe(true)
    expect(ann.fontSize).toBe(5)
  })

  it('appends to multi-sheet drawing correctly', () => {
    const d = addRichText(multiSheetDrawing(), 10, 10, 'text')
    expect(d.sheets[0].annotations).toHaveLength(1)
  })

  it('does not mutate the original drawing', () => {
    const orig = flatDrawing()
    addRichText(orig, 0, 0, 'x')
    expect(orig.annotations).toHaveLength(0)
  })
})

// ── 6. addDimensionChain ──────────────────────────────────────────────────────

describe('addDimensionChain', () => {
  it('appends a chain dimension', () => {
    const d = addDimensionChain(flatDrawing(), PICKS, 'view-1')
    expect(d.dimensions).toHaveLength(1)
  })

  it('dimension has kind=chain and the supplied picks', () => {
    const d = addDimensionChain(flatDrawing(), PICKS, 'view-1')
    const dim = d.dimensions[0]
    expect(dim.kind).toBe('chain')
    expect(dim.picks).toHaveLength(3)
    expect(dim.picks[0]).toEqual(PICKS[0])
  })

  it('view_id is stored on the dimension', () => {
    const d = addDimensionChain(flatDrawing(), PICKS, 'view-abc')
    expect(d.dimensions[0].view_id).toBe('view-abc')
  })

  it('appends to multi-sheet drawing correctly', () => {
    const d = addDimensionChain(multiSheetDrawing(), PICKS, 'v1')
    expect(d.sheets[0].dimensions).toHaveLength(1)
  })

  it('opts.offset is forwarded', () => {
    const d = addDimensionChain(flatDrawing(), PICKS, 'v', { offset: 12 })
    expect(d.dimensions[0].offset).toBe(12)
  })

  it('does not mutate the original drawing', () => {
    const orig = flatDrawing()
    addDimensionChain(orig, PICKS, 'v')
    expect(orig.dimensions).toHaveLength(0)
  })

  it('throws when fewer than 2 picks are supplied', () => {
    expect(() => addDimensionChain(flatDrawing(), [{ x: 0, y: 0 }], 'v')).toThrow()
  })
})
