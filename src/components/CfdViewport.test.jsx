/**
 * CfdViewport.test.jsx
 *
 * Uses react-dom/server renderToStaticMarkup (same pattern as Loader.test.jsx)
 * since @testing-library/react is not installed.  All useEffect/useRef hooks
 * are no-ops during SSR so canvas rendering is not exercised — we test the
 * React tree structure and prop handling.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CfdViewport from './CfdViewport.jsx'

// ── Minimal field fixtures ────────────────────────────────────────────────────

function makeField({ nx = 5, ny = 5 } = {}) {
  const u = Array.from({ length: ny }, () => Array(nx).fill(1))
  const v = Array.from({ length: ny }, () => Array(nx).fill(0))
  const p = Array.from({ length: ny }, (_, row) =>
    Array.from({ length: nx }, (_, col) => col + row)
  )
  return { x0: 0, y0: 0, dx: 1, dy: 1, nx, ny, u, v, p }
}

function makeCellsField({ nx = 4, ny = 4 } = {}) {
  const cells = []
  for (let row = 0; row < ny; row++)
    for (let col = 0; col < nx; col++)
      cells.push({ x: col, y: row, Ux: 1, Uy: 0, p: col + row })
  return { cells }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('CfdViewport — render without crash', () => {
  it('renders with no vectorField (empty state)', () => {
    const html = renderToStaticMarkup(<CfdViewport />)
    expect(html).toContain('canvas')
    expect(html).toContain('No CFD data')
  })

  it('renders with a grid vectorField without throwing', () => {
    const field = makeField()
    const html = renderToStaticMarkup(<CfdViewport vectorField={field} />)
    expect(html).toContain('canvas')
    // Placeholder message should NOT appear when field is provided
    expect(html).not.toContain('No CFD data')
  })

  it('renders with a cells-shape vectorField without throwing', () => {
    const field = makeCellsField()
    const html = renderToStaticMarkup(<CfdViewport vectorField={field} />)
    expect(html).toContain('canvas')
    expect(html).not.toContain('No CFD data')
  })

  it('renders with all layers disabled without throwing', () => {
    const field = makeField()
    const html = renderToStaticMarkup(
      <CfdViewport
        vectorField={field}
        showStreamlines={false}
        showArrows={false}
        showPressure={false}
      />
    )
    expect(html).toContain('canvas')
  })
})

describe('CfdViewport — layer legend chips', () => {
  it('shows Streamlines chip when showStreamlines=true', () => {
    const field = makeField()
    const html = renderToStaticMarkup(<CfdViewport vectorField={field} showStreamlines />)
    expect(html).toContain('Streamlines')
  })

  it('hides Streamlines chip when showStreamlines=false', () => {
    const field = makeField()
    const html = renderToStaticMarkup(
      <CfdViewport vectorField={field} showStreamlines={false} />
    )
    expect(html).not.toContain('Streamlines')
  })

  it('shows Velocity chip when showArrows=true', () => {
    const field = makeField()
    const html = renderToStaticMarkup(<CfdViewport vectorField={field} showArrows />)
    expect(html).toContain('Velocity')
  })

  it('hides Velocity chip when showArrows=false', () => {
    const field = makeField()
    const html = renderToStaticMarkup(
      <CfdViewport vectorField={field} showArrows={false} />
    )
    expect(html).not.toContain('Velocity')
  })

  it('shows Pressure chip when showPressure=true', () => {
    const field = makeField()
    const html = renderToStaticMarkup(<CfdViewport vectorField={field} showPressure />)
    expect(html).toContain('Pressure')
  })

  it('hides Pressure chip when showPressure=false', () => {
    const field = makeField()
    const html = renderToStaticMarkup(
      <CfdViewport vectorField={field} showPressure={false} />
    )
    expect(html).not.toContain('Pressure')
  })
})

describe('CfdViewport — colour bar', () => {
  it('shows pressure colour bar when showPressure=true and field is provided', () => {
    const field = makeField()
    const html = renderToStaticMarkup(<CfdViewport vectorField={field} showPressure />)
    // Color bar shows "Pa"
    expect(html).toContain('Pa')
  })

  it('hides colour bar when showPressure=false', () => {
    const field = makeField()
    const html = renderToStaticMarkup(
      <CfdViewport vectorField={field} showPressure={false} />
    )
    expect(html).not.toContain('Pa')
  })

  it('hides colour bar when no field provided', () => {
    const html = renderToStaticMarkup(<CfdViewport />)
    expect(html).not.toContain('Pa')
  })
})

describe('CfdViewport — canvas dimensions', () => {
  it('applies default width/height attributes', () => {
    const html = renderToStaticMarkup(<CfdViewport />)
    expect(html).toMatch(/width="520"/)
    expect(html).toMatch(/height="340"/)
  })

  it('respects custom width and height props', () => {
    const html = renderToStaticMarkup(<CfdViewport width={800} height={600} />)
    expect(html).toMatch(/width="800"/)
    expect(html).toMatch(/height="600"/)
  })
})

describe('CfdViewport — edge cases', () => {
  it('renders with vectorField=null without throwing', () => {
    expect(() => renderToStaticMarkup(<CfdViewport vectorField={null} />)).not.toThrow()
  })

  it('renders with an empty cells array without throwing', () => {
    expect(() =>
      renderToStaticMarkup(<CfdViewport vectorField={{ cells: [] }} />)
    ).not.toThrow()
  })

  it('renders with a separate pressureField without throwing', () => {
    const vf = makeField()
    const pf = makeField()  // also has .p
    expect(() =>
      renderToStaticMarkup(<CfdViewport vectorField={vf} pressureField={pf} />)
    ).not.toThrow()
  })

  it('renders with custom seeds prop without throwing', () => {
    const field = makeField()
    const seeds = [{ x: 0.5, y: 0.5 }, { x: 0.5, y: 2.5 }]
    expect(() =>
      renderToStaticMarkup(<CfdViewport vectorField={field} seeds={seeds} />)
    ).not.toThrow()
  })
})
