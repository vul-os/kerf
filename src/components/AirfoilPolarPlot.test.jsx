/**
 * AirfoilPolarPlot.test.jsx
 *
 * Vitest tests for the AirfoilPolarPlot SVG component.
 *
 * Uses renderToStaticMarkup (react-dom/server, already a project dep) so
 * no @testing-library/react or jsdom is needed.  Structural assertions via
 * substring / regex matches are sufficient to verify correctness.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import AirfoilPolarPlot from './AirfoilPolarPlot.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const NACA0012_POLAR = {
  airfoil: 'naca0012',
  alpha: [-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10],
  CL: [-1.1, -0.88, -0.66, -0.44, -0.22, 0.0, 0.22, 0.44, 0.66, 0.88, 1.1],
  CD: [0.025, 0.018, 0.012, 0.008, 0.006, 0.005, 0.006, 0.008, 0.012, 0.018, 0.025],
}

const MINIMAL_POLAR = {
  airfoil: 'e387',
  alpha: [0, 5],
  CL: [0.4, 0.9],
  CD: [0.01, 0.015],
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AirfoilPolarPlot', () => {
  it('renders without crashing with standard polar data', () => {
    expect(() => renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)).not.toThrow()
  })

  it('renders an SVG element', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    expect(html).toMatch(/<svg\b/)
  })

  it('renders an SVG with role="img"', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    expect(html).toMatch(/role="img"/)
  })

  it('includes aria-label containing the airfoil name', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    expect(html).toMatch(/aria-label="[^"]*naca0012[^"]*"/)
  })

  it('renders the airfoil name in the chart title', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    expect(html).toContain('naca0012')
  })

  it('includes CL vs α in the title or label', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    expect(html).toMatch(/CL/)
    expect(html).toMatch(/α|alpha/i)
  })

  it('renders at least one polyline (the CL curve)', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    expect(html).toMatch(/<polyline\b/)
  })

  it('renders the polyline with points attribute', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    expect(html).toMatch(/points="[^"]+"/i)
  })

  it('uses the supplied width and height', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} width={640} height={400} />)
    expect(html).toMatch(/width="640"/)
    expect(html).toMatch(/height="400"/)
  })

  it('defaults to 480 x 300', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    expect(html).toMatch(/width="480"/)
    expect(html).toMatch(/height="300"/)
  })

  it('renders an empty state when polar is null', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={null} />)
    expect(html).toContain('No polar data')
    expect(html).not.toMatch(/<svg\b/)
  })

  it('renders an empty state when alpha array is empty', () => {
    const empty = { airfoil: 'naca0012', alpha: [], CL: [], CD: [] }
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={empty} />)
    expect(html).toContain('No polar data')
  })

  it('renders axis labels for α and CL', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    expect(html).toContain('CL')
    expect(html).toMatch(/α|alpha/i)
  })

  it('renders tick text for alpha values', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    // Should have numeric tick labels
    expect(html).toMatch(/-10|10/)
  })

  it('does not show CD line when showCD is false (default)', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} />)
    // CD×10 label only appears when showCD=true
    expect(html).not.toContain('CD×10')
  })

  it('shows CD line when showCD is true', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} showCD />)
    expect(html).toContain('CD×10')
  })

  it('renders a second polyline when showCD is true', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={NACA0012_POLAR} showCD />)
    const matches = html.match(/<polyline\b/g) || []
    expect(matches.length).toBeGreaterThanOrEqual(2)
  })

  it('works with minimal 2-point polar', () => {
    expect(() =>
      renderToStaticMarkup(<AirfoilPolarPlot polar={MINIMAL_POLAR} />)
    ).not.toThrow()
  })

  it('accepts a custom className', () => {
    const html = renderToStaticMarkup(
      <AirfoilPolarPlot polar={NACA0012_POLAR} className="my-custom-chart" />
    )
    expect(html).toContain('my-custom-chart')
  })

  it('renders with different airfoil name in title', () => {
    const html = renderToStaticMarkup(<AirfoilPolarPlot polar={MINIMAL_POLAR} />)
    expect(html).toContain('e387')
  })
})
