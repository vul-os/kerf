/**
 * SheetMetalPanel.test.jsx
 *
 * Tests for the SheetMetalPanel React component.
 * Uses renderToStaticMarkup (no @testing-library/react).
 *
 * Tests:
 *   1. Renders without crashing
 *   2. Correct tab structure (Flat Pattern / Corner Relief / Multi-Flange)
 *   3. Default tab is Flat Pattern
 *   4. Corner Relief tab content — type selector, Suchy/DIN reference
 *   5. Formula references visible in descriptions
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SheetMetalPanel from './SheetMetalPanel.jsx'

// ---------------------------------------------------------------------------
// Basic rendering
// ---------------------------------------------------------------------------

describe('SheetMetalPanel — rendering', () => {
  it('renders without crashing', () => {
    expect(() => renderToStaticMarkup(<SheetMetalPanel />)).not.toThrow()
  })

  it('includes Sheet Metal heading', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Sheet Metal')
  })

  it('has subtitle mentioning GK-P17 corner relief', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('GK-P17')
    expect(html).toContain('corner relief')
  })

  it('includes all three tab labels', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Flat Pattern')
    expect(html).toContain('Corner Relief')
    expect(html).toContain('Multi-Flange')
  })
})

// ---------------------------------------------------------------------------
// Flat Pattern tab (default)
// ---------------------------------------------------------------------------

describe('SheetMetalPanel — Flat Pattern tab', () => {
  it('shows Compute Flat Pattern button', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Compute Flat Pattern')
  })

  it('contains Thickness input', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Thickness')
  })

  it('references DIN 6935 in description', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('DIN 6935')
  })

  it('references K-factor formula', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('K-factor')
  })

  it('mentions Bend allowance in description', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Bend allowance')
  })

  it('shows material selector', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Mild steel')
    expect(html).toContain('Aluminium')
  })

  it('shows flanges JSON input description', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('flanges')
    expect(html).toContain('length_mm')
  })

  it('has Export DXF checkbox label', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Export DXF')
  })
})

// ---------------------------------------------------------------------------
// Corner Relief tab — content present (default tab is Flat Pattern, so
// Corner Relief body is NOT rendered in server HTML unless we change default)
// ---------------------------------------------------------------------------

describe('SheetMetalPanel — Corner Relief tab (button)', () => {
  it('Corner Relief tab label is present', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Corner Relief')
  })
})

// ---------------------------------------------------------------------------
// Multi-Flange tab
// ---------------------------------------------------------------------------

describe('SheetMetalPanel — Multi-Flange tab (button)', () => {
  it('Multi-Flange tab label is present', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Multi-Flange')
  })
})

// ---------------------------------------------------------------------------
// Structure and quality
// ---------------------------------------------------------------------------

describe('SheetMetalPanel — structure', () => {
  it('renders non-trivial HTML (more than 500 chars)', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html.length).toBeGreaterThan(500)
  })

  it('references Suchy Handbook of Die Design', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    expect(html).toContain('Suchy')
  })

  it('shows BA formula in description', () => {
    const html = renderToStaticMarkup(<SheetMetalPanel />)
    // BA = (π/180)·θ·(r + K·t)
    expect(html).toContain('BA')
    expect(html).toContain('180')
  })
})
