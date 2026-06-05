/**
 * AshbyChartPanel.test.jsx
 *
 * Vitest tests for AshbyChartPanel — log-log Ashby material chart.
 * Uses renderToStaticMarkup (react-dom/server).
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import AshbyChartPanel from './AshbyChartPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const POINTS = [
  { name: 'AISI_4140_QT',   x: 207,  y: 655,  family: 'steel' },
  { name: 'Al_7075_T6',     x: 71.7, y: 503,  family: 'aluminium' },
  { name: 'Ti_6Al4V',       x: 113,  y: 880,  family: 'titanium' },
  { name: 'CFRP_UD_0deg',   x: 135,  y: 1500, family: 'composite' },
  { name: 'PC',             x: 2.38, y: 62,   family: 'polymer' },
]

const PARETO = [
  { name: 'CFRP_UD_0deg', x: 135, y: 1500 },
  { name: 'Ti_6Al4V',     x: 113, y: 880 },
]

const INDEX_LINES = [
  { slope: 1,   label: 'E/ρ = const' },
  { slope: 0.5, label: 'E^0.5/ρ = const' },
]

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AshbyChartPanel', () => {
  it('renders without crashing with standard data', () => {
    expect(() =>
      renderToStaticMarkup(
        <AshbyChartPanel points={POINTS} pareto={PARETO} xLabel="E (GPa)" yLabel="σy (MPa)" />
      )
    ).not.toThrow()
  })

  it('renders an SVG element', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} />)
    expect(html).toMatch(/<svg\b/)
  })

  it('renders role="img"', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} />)
    expect(html).toMatch(/role="img"/)
  })

  it('includes the chart title', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} title="My Ashby Chart" />)
    expect(html).toContain('My Ashby Chart')
  })

  it('uses default title when not supplied', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} />)
    expect(html).toContain('Ashby Material Chart')
  })

  it('renders xLabel on the chart', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} xLabel="E (GPa)" />)
    expect(html).toContain('E (GPa)')
  })

  it('renders yLabel on the chart', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} yLabel="σy (MPa)" />)
    expect(html).toContain('σy (MPa)')
  })

  it('renders scatter circles for each point', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} />)
    const circleMatches = html.match(/<circle\b/g) || []
    expect(circleMatches.length).toBeGreaterThanOrEqual(POINTS.length)
  })

  it('renders Pareto front polyline when pareto is provided', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} pareto={PARETO} />)
    expect(html).toMatch(/<polyline\b/)
  })

  it('renders Pareto legend entry', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} pareto={PARETO} />)
    expect(html).toContain('Pareto front')
  })

  it('renders index guide lines when provided', () => {
    const html = renderToStaticMarkup(
      <AshbyChartPanel points={POINTS} indexLines={INDEX_LINES} />
    )
    expect(html).toContain('E/ρ = const')
  })

  it('renders width and height on SVG', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} width={700} height={500} />)
    expect(html).toMatch(/width="700"/)
    expect(html).toMatch(/height="500"/)
  })

  it('defaults to 560 x 460', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} />)
    expect(html).toMatch(/width="560"/)
    expect(html).toMatch(/height="460"/)
  })

  it('renders empty state when points is empty', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={[]} />)
    expect(html).toContain('No material data')
    expect(html).not.toMatch(/<svg\b/)
  })

  it('renders material count at the bottom', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} pareto={PARETO} />)
    // Should contain count e.g. "5 materials"
    expect(html).toMatch(/\d+ materials/)
  })

  it('renders Pareto count in summary', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} pareto={PARETO} />)
    expect(html).toContain('Pareto front')
  })

  it('accepts a custom className', () => {
    const html = renderToStaticMarkup(<AshbyChartPanel points={POINTS} className="test-cls" />)
    expect(html).toContain('test-cls')
  })

  it('renders without pareto or indexLines (minimal props)', () => {
    expect(() =>
      renderToStaticMarkup(<AshbyChartPanel points={POINTS} />)
    ).not.toThrow()
  })
})
