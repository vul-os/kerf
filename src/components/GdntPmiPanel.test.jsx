// GdntPmiPanel.test.jsx — component tests for the GD&T PMI placement panel.
//
// Uses renderToStaticMarkup (react-dom/server) — no browser DOM, no fetch,
// mirrors the pattern in gdntToolbar.test.jsx and LayoutViewer.test.jsx.

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import GdntPmiPanel from './GdntPmiPanel.jsx'
import { addFcf, addDatumLabel } from '../lib/gdntAnnotations.js'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function emptyDrawing() {
  return {
    frame: { size: 'A3', orientation: 'landscape' },
    annotations: [],
    dimensions: [],
  }
}

function drawingWithFcf() {
  return addFcf(emptyDrawing(), {
    x: 50, y: 30,
    symbol_code: 'perpendicularity',
    tolerance_value: 0.1,
    datum_refs: [{ label: 'A' }],
  })
}

function drawingWithDatum() {
  return addDatumLabel(emptyDrawing(), { x: 20, y: 20, label: 'A' })
}

function drawingWithBoth() {
  let d = addFcf(emptyDrawing(), {
    x: 50, y: 30,
    symbol_code: 'position',
    tolerance_value: 0.5,
    diameter_zone: true,
    datum_refs: [{ label: 'A' }, { label: 'B' }],
  })
  d = addDatumLabel(d, { x: 20, y: 20, label: 'A' })
  d = addDatumLabel(d, { x: 40, y: 20, label: 'B' })
  return d
}

// ---------------------------------------------------------------------------
// Panel smoke tests
// ---------------------------------------------------------------------------

describe('GdntPmiPanel — basic render', () => {
  it('mounts without error with null drawing', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={null} tool="" onTool={() => {}} />
    )
    expect(html.length).toBeGreaterThan(0)
  })

  it('has data-testid="gdnt-pmi-panel"', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={null} tool="" onTool={() => {}} />
    )
    expect(html).toContain('data-testid="gdnt-pmi-panel"')
  })

  it('shows GD&T / PMI header', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={null} tool="" onTool={() => {}} />
    )
    expect(html).toContain('GD&amp;T / PMI')
  })

  it('shows "0 placed" when drawing has no annotations', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={emptyDrawing()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('0 placed')
  })
})

// ---------------------------------------------------------------------------
// Panel with FCF annotations
// ---------------------------------------------------------------------------

describe('GdntPmiPanel — FCF annotations', () => {
  it('shows "1 placed" count when one FCF is placed', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithFcf()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('1 placed')
  })

  it('renders an FCF list entry with testid', () => {
    const d = drawingWithFcf()
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={d} tool="" onTool={() => {}} />
    )
    // The entry testid includes the annotation id
    expect(html).toContain('data-testid="pmi-fcf-entry-')
  })

  it('shows the FCF rendered text (contains tolerance value)', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithFcf()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('0.1')
  })

  it('shows perpendicularity unicode symbol ⟂', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithFcf()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('⟂')
  })

  it('renders Placed FCFs section', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithFcf()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('Placed FCFs')
  })
})

// ---------------------------------------------------------------------------
// Panel with datum labels
// ---------------------------------------------------------------------------

describe('GdntPmiPanel — datum annotations', () => {
  it('shows "1 placed" count for a single datum', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithDatum()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('1 placed')
  })

  it('renders datum entry with testid', () => {
    const d = drawingWithDatum()
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={d} tool="" onTool={() => {}} />
    )
    expect(html).toContain('data-testid="pmi-datum-entry-')
  })

  it('shows the datum letter A', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithDatum()} tool="" onTool={() => {}} />
    )
    // The label 'A' should appear in the datum entry
    expect(html).toContain('>A<')
  })

  it('renders Placed Datums section', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithDatum()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('Placed Datums')
  })
})

// ---------------------------------------------------------------------------
// Panel with mixed annotations
// ---------------------------------------------------------------------------

describe('GdntPmiPanel — mixed annotations', () => {
  it('shows "3 placed" for 1 FCF + 2 datums', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithBoth()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('3 placed')
  })

  it('shows Placed FCFs (1) header', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithBoth()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('Placed FCFs (1)')
  })

  it('shows Placed Datums (2) header', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithBoth()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('Placed Datums (2)')
  })

  it('position symbol ⌖ appears from the FCF', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={drawingWithBoth()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('⌖')
  })
})

// ---------------------------------------------------------------------------
// Tool state reflected in GdntToolbar
// ---------------------------------------------------------------------------

describe('GdntPmiPanel — tool state', () => {
  it('passes active tool to embedded GdntToolbar', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={emptyDrawing()} tool="gdt:fcf:flatness" onTool={() => {}} />
    )
    // GdntToolbar uses aria-pressed="true" for the active tool
    expect(html).toContain('aria-pressed="true"')
  })

  it('no tool active → all buttons have aria-pressed="false"', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={emptyDrawing()} tool="" onTool={() => {}} />
    )
    expect(html).not.toContain('aria-pressed="true"')
  })
})

// ---------------------------------------------------------------------------
// Auto-callout button (optional prop)
// ---------------------------------------------------------------------------

describe('GdntPmiPanel — auto-callout', () => {
  it('does not render auto-callout section heading when prop is absent', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={emptyDrawing()} tool="" onTool={() => {}} />
    )
    expect(html).not.toContain('Auto-Propose GD')
  })

  it('renders auto-callout section heading when onAutoCallout is provided', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel
        drawing={emptyDrawing()}
        tool=""
        onTool={() => {}}
        onAutoCallout={() => {}}
      />
    )
    // Section header is always rendered even when collapsed
    expect(html).toContain('Auto-Propose GD')
  })
})

// ---------------------------------------------------------------------------
// Quick validate panel
// ---------------------------------------------------------------------------

describe('GdntPmiPanel — quick validate section', () => {
  it('renders the quick-validate section heading', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={emptyDrawing()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('Validate Frame (Y14.5)')
  })

  it('renders the validate button text (section open by default)', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={emptyDrawing()} tool="" onTool={() => {}} />
    )
    // QuickValidatePanel is open by default — button text should be present
    expect(html).toContain('gdt_validate_frame')
  })

  it('renders pmi-quick-validate testid (section open by default)', () => {
    const html = renderToStaticMarkup(
      <GdntPmiPanel drawing={emptyDrawing()} tool="" onTool={() => {}} />
    )
    expect(html).toContain('data-testid="pmi-quick-validate"')
  })
})
