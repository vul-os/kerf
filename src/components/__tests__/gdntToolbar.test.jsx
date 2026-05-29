// gdntToolbar.test.jsx — GD&T toolbar and FCF data-layer tests.
//
// Three test surfaces:
//   1. gdntAnnotations.js — pure data-layer (addFcf, addDatumLabel, etc.)
//   2. GdntToolbar (React component) — rendered via renderToStaticMarkup
//   3. FcfPlacementModal (React component) — rendered via renderToStaticMarkup
//
// No @testing-library/react. Uses renderToStaticMarkup from react-dom/server
// (same pattern as SectorCommandList.test.jsx, LayoutViewer.test.jsx, etc.)

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// ---------------------------------------------------------------------------
// 1. Pure data-layer tests (no React)
// ---------------------------------------------------------------------------

import {
  GDT_SYMBOLS,
  GDT_SYMBOL_MAP,
  DATUM_LABELS,
  renderFcf,
  addFcf,
  addDatumLabel,
  listFcfs,
  listDatumLabels,
} from '../../lib/gdntAnnotations.js'

function flatDrawing() {
  return {
    frame: { size: 'A3', orientation: 'landscape' },
    annotations: [],
    dimensions: [],
  }
}

function multiSheetDrawing() {
  return {
    currentSheet: 0,
    sheets: [
      {
        id: 'sheet-1',
        frame: { size: 'A3', orientation: 'landscape' },
        annotations: [],
        dimensions: [],
      },
    ],
  }
}

describe('GDT_SYMBOLS catalogue', () => {
  it('exports a non-empty array', () => {
    expect(Array.isArray(GDT_SYMBOLS)).toBe(true)
    expect(GDT_SYMBOLS.length).toBeGreaterThanOrEqual(10)
  })

  it('every symbol has code, unicode, name, category', () => {
    for (const s of GDT_SYMBOLS) {
      expect(typeof s.code).toBe('string')
      expect(typeof s.unicode).toBe('string')
      expect(typeof s.name).toBe('string')
      expect(['form', 'profile', 'orientation', 'location', 'runout']).toContain(s.category)
    }
  })

  it('position is present in the map', () => {
    expect(GDT_SYMBOL_MAP['position']).toBeDefined()
    expect(GDT_SYMBOL_MAP['position'].unicode).toBe('⌖')
  })

  it('perpendicularity is present', () => {
    expect(GDT_SYMBOL_MAP['perpendicularity']).toBeDefined()
  })

  it('flatness, circularity, straightness, parallelism, runout codes exist', () => {
    for (const code of ['flatness', 'circularity', 'straightness', 'parallelism', 'circular_runout', 'total_runout']) {
      expect(GDT_SYMBOL_MAP[code], `missing ${code}`).toBeDefined()
    }
  })

  it('profile_line and profile_surface exist', () => {
    expect(GDT_SYMBOL_MAP['profile_line']).toBeDefined()
    expect(GDT_SYMBOL_MAP['profile_surface']).toBeDefined()
  })
})

describe('renderFcf', () => {
  it('renders basic perpendicularity frame', () => {
    const text = renderFcf({
      symbol_code: 'perpendicularity',
      tolerance_value: 0.1,
      diameter_zone: false,
      tolerance_modifier: null,
      datum_refs: [{ label: 'A' }],
    })
    expect(text).toContain('⟂')
    expect(text).toContain('0.1')
    expect(text).toContain('A')
  })

  it('includes ⌀ prefix when diameter_zone is true', () => {
    const text = renderFcf({
      symbol_code: 'position',
      tolerance_value: 0.5,
      diameter_zone: true,
      datum_refs: [],
    })
    expect(text).toContain('⌀')
    expect(text).toContain('0.5')
  })

  it('includes modifier when set', () => {
    const text = renderFcf({
      symbol_code: 'position',
      tolerance_value: 0.2,
      tolerance_modifier: 'M',
      datum_refs: [],
    })
    expect(text).toContain('Ⓜ')
  })

  it('handles multiple datum refs', () => {
    const text = renderFcf({
      symbol_code: 'position',
      tolerance_value: 0.1,
      datum_refs: [{ label: 'A' }, { label: 'B' }, { label: 'C' }],
    })
    expect(text).toContain('A')
    expect(text).toContain('B')
    expect(text).toContain('C')
  })
})

describe('addFcf', () => {
  it('adds an FCF annotation to a flat drawing', () => {
    const d = addFcf(flatDrawing(), {
      x: 50, y: 30,
      symbol_code: 'flatness',
      tolerance_value: 0.05,
    })
    expect(d.annotations).toHaveLength(1)
    expect(d.annotations[0].kind).toBe('fcf')
  })

  it('adds an FCF annotation to a multi-sheet drawing', () => {
    const d = addFcf(multiSheetDrawing(), {
      x: 50, y: 30,
      symbol_code: 'perpendicularity',
      tolerance_value: 0.1,
      datum_refs: [{ label: 'A' }],
    })
    expect(d.sheets[0].annotations).toHaveLength(1)
    expect(d.sheets[0].annotations[0].kind).toBe('fcf')
  })

  it('stored FCF carries rendered text', () => {
    const d = addFcf(flatDrawing(), {
      x: 10, y: 10,
      symbol_code: 'position',
      tolerance_value: 0.5,
      diameter_zone: true,
      datum_refs: [{ label: 'A' }, { label: 'B' }],
    })
    const ann = d.annotations[0]
    expect(typeof ann.rendered).toBe('string')
    expect(ann.rendered).toContain('⌖')
    expect(ann.rendered).toContain('⌀')
    expect(ann.rendered).toContain('A')
  })

  it('throws when symbol_code is unknown', () => {
    expect(() => addFcf(flatDrawing(), {
      x: 0, y: 0,
      symbol_code: 'not_a_symbol',
      tolerance_value: 0.1,
    })).toThrow()
  })

  it('throws when tolerance_value is missing', () => {
    expect(() => addFcf(flatDrawing(), {
      x: 0, y: 0,
      symbol_code: 'flatness',
      tolerance_value: null,
    })).toThrow()
  })

  it('does not mutate the original drawing', () => {
    const orig = flatDrawing()
    addFcf(orig, { x: 0, y: 0, symbol_code: 'flatness', tolerance_value: 0.1 })
    expect(orig.annotations).toHaveLength(0)
  })

  it('stores target_id when provided', () => {
    const d = addFcf(flatDrawing(), {
      x: 10, y: 10,
      symbol_code: 'circularity',
      tolerance_value: 0.02,
      target_id: 'face-42',
    })
    expect(d.annotations[0].target_id).toBe('face-42')
  })

  it('stores leader_from when provided', () => {
    const d = addFcf(flatDrawing(), {
      x: 50, y: 30,
      symbol_code: 'parallelism',
      tolerance_value: 0.1,
      datum_refs: [{ label: 'A' }],
      leader_from: { x: 20, y: 15 },
    })
    expect(d.annotations[0].leader_from).toEqual({ x: 20, y: 15 })
  })
})

describe('addDatumLabel', () => {
  it('adds a datum label annotation', () => {
    const d = addDatumLabel(flatDrawing(), { x: 20, y: 20, label: 'A' })
    expect(d.annotations).toHaveLength(1)
    expect(d.annotations[0].kind).toBe('gdt_datum')
    expect(d.annotations[0].label).toBe('A')
  })

  it('upper-cases the label', () => {
    const d = addDatumLabel(flatDrawing(), { x: 0, y: 0, label: 'b' })
    expect(d.annotations[0].label).toBe('B')
  })

  it('throws when label is missing', () => {
    expect(() => addDatumLabel(flatDrawing(), { x: 0, y: 0, label: '' })).toThrow()
  })

  it('does not mutate the original drawing', () => {
    const orig = flatDrawing()
    addDatumLabel(orig, { x: 0, y: 0, label: 'A' })
    expect(orig.annotations).toHaveLength(0)
  })
})

describe('listFcfs / listDatumLabels', () => {
  it('returns only FCF annotations', () => {
    let d = addFcf(flatDrawing(), { x: 0, y: 0, symbol_code: 'flatness', tolerance_value: 0.1 })
    d = addDatumLabel(d, { x: 5, y: 5, label: 'A' })
    expect(listFcfs(d)).toHaveLength(1)
    expect(listDatumLabels(d)).toHaveLength(1)
  })

  it('returns empty arrays when no annotations', () => {
    const d = flatDrawing()
    expect(listFcfs(d)).toHaveLength(0)
    expect(listDatumLabels(d)).toHaveLength(0)
  })
})

describe('addFcf end-to-end placement round-trip', () => {
  it('persists FCF with all fields from a full FCF opts object', () => {
    const opts = {
      x: 50,
      y: 30,
      symbol_code: 'perpendicularity',
      tolerance_value: 0.05,
      diameter_zone: false,
      tolerance_modifier: null,
      datum_refs: [{ label: 'A' }],
    }
    const d = addFcf(flatDrawing(), opts)
    expect(listFcfs(d)).toHaveLength(1)
    const fcf = listFcfs(d)[0]
    expect(fcf.symbol_code).toBe('perpendicularity')
    expect(fcf.tolerance_value).toBe(0.05)
    expect(fcf.datum_refs[0].label).toBe('A')
    expect(fcf.rendered).toContain('⟂')
  })
})

// ---------------------------------------------------------------------------
// 2. GdntToolbar component tests — renderToStaticMarkup
// ---------------------------------------------------------------------------

import GdntToolbar from '../GdntToolbar.jsx'

describe('GdntToolbar', () => {
  it('mounts without error (renders non-empty HTML)', () => {
    const html = renderToStaticMarkup(<GdntToolbar tool="" onTool={() => {}} />)
    expect(html.length).toBeGreaterThan(0)
  })

  it('contains data-testid for datum A/B/C buttons', () => {
    const html = renderToStaticMarkup(<GdntToolbar tool="" onTool={() => {}} />)
    expect(html).toContain('data-testid="gdnt-tool-gdt:datum:A"')
    expect(html).toContain('data-testid="gdnt-tool-gdt:datum:B"')
    expect(html).toContain('data-testid="gdnt-tool-gdt:datum:C"')
  })

  it('contains data-testid for ISO 1101 characteristic buttons', () => {
    const html = renderToStaticMarkup(<GdntToolbar tool="" onTool={() => {}} />)
    for (const code of ['position', 'perpendicularity', 'flatness', 'circularity', 'straightness', 'profile_line', 'profile_surface', 'parallelism', 'circular_runout', 'total_runout']) {
      expect(html, `missing ${code}`).toContain(`data-testid="gdnt-tool-gdt:fcf:${code}"`)
    }
  })

  it('marks the active tool as aria-pressed=true', () => {
    const html = renderToStaticMarkup(<GdntToolbar tool="gdt:fcf:flatness" onTool={() => {}} />)
    // The active button should have aria-pressed="true"
    expect(html).toContain('aria-pressed="true"')
  })

  it('inactive tools have aria-pressed=false', () => {
    const html = renderToStaticMarkup(<GdntToolbar tool="gdt:fcf:flatness" onTool={() => {}} />)
    expect(html).toContain('aria-pressed="false"')
  })

  it('renders GD&T section header', () => {
    const html = renderToStaticMarkup(<GdntToolbar tool="" onTool={() => {}} />)
    expect(html).toContain('GD&amp;T')
  })

  it('renders Unicode symbols for all characteristics', () => {
    const html = renderToStaticMarkup(<GdntToolbar tool="" onTool={() => {}} />)
    // Spot-check key Unicode characters
    expect(html).toContain('⌖')   // position
    expect(html).toContain('⟂')   // perpendicularity
    expect(html).toContain('▱')   // flatness
    expect(html).toContain('○')   // circularity
    expect(html).toContain('⌒')   // profile of a line
    expect(html).toContain('↗')   // circular runout
  })
})

// ---------------------------------------------------------------------------
// 3. FcfPlacementModal component tests — renderToStaticMarkup
// ---------------------------------------------------------------------------

import { FcfPlacementModal } from '../GdntToolbar.jsx'

describe('FcfPlacementModal', () => {
  it('renders without error', () => {
    const html = renderToStaticMarkup(
      <FcfPlacementModal
        symbolCode="perpendicularity"
        position={{ x: 50, y: 30 }}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(html.length).toBeGreaterThan(0)
  })

  it('shows the symbol name', () => {
    const html = renderToStaticMarkup(
      <FcfPlacementModal
        symbolCode="perpendicularity"
        position={{ x: 50, y: 30 }}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(html).toContain('Perpendicularity')
  })

  it('shows the symbol unicode', () => {
    const html = renderToStaticMarkup(
      <FcfPlacementModal
        symbolCode="flatness"
        position={{ x: 0, y: 0 }}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(html).toContain('▱')
  })

  it('contains Place FCF and Cancel buttons', () => {
    const html = renderToStaticMarkup(
      <FcfPlacementModal
        symbolCode="position"
        position={{ x: 10, y: 10 }}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(html).toContain('Place FCF')
    expect(html).toContain('Cancel')
  })

  it('contains the data-testid for the modal', () => {
    const html = renderToStaticMarkup(
      <FcfPlacementModal
        symbolCode="circularity"
        position={{ x: 5, y: 5 }}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(html).toContain('data-testid="fcf-placement-modal"')
  })

  it('shows the category label', () => {
    const html = renderToStaticMarkup(
      <FcfPlacementModal
        symbolCode="position"
        position={{ x: 0, y: 0 }}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(html).toContain('location')
  })

  it('shows diameter zone toggle button (⌀)', () => {
    const html = renderToStaticMarkup(
      <FcfPlacementModal
        symbolCode="position"
        position={{ x: 0, y: 0 }}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(html).toContain('⌀')
  })

  it('returns null for unknown symbol code', () => {
    const html = renderToStaticMarkup(
      <FcfPlacementModal
        symbolCode="not_real"
        position={{ x: 0, y: 0 }}
        onCommit={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(html).toBe('')
  })
})
