/**
 * CompareFeatureMatrix.test.jsx — unit tests for the structured feature matrix.
 *
 * Uses renderToStaticMarkup (react-dom/server) — consistent with the
 * project's CompareCardGrid.test.jsx pattern. No @testing-library/react needed.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CompareFeatureMatrix from './CompareFeatureMatrix.jsx'

function render(ui) {
  return renderToStaticMarkup(ui)
}

/* -------------------------------------------------------------------------- */
/* Fixtures                                                                    */
/* -------------------------------------------------------------------------- */

const SAMPLE_FEATURES = [
  {
    domain: 'D1',
    feature: 'Constraint sketcher (geo + dim)',
    competitor: { status: 'yes', note: 'Full parametric sketcher' },
    kerf: { status: 'yes', note: 'PlaneGCS WASM', evidence: 'packages/kerf-sketcher' },
  },
  {
    domain: 'D1',
    feature: 'Loft',
    competitor: { status: 'yes', note: 'Guide rails supported' },
    kerf: { status: 'partial', note: 'no guide-rail overload' },
  },
  {
    domain: 'D6',
    feature: 'PCB layout',
    competitor: { status: 'yes', note: 'Native MCAD/ECAD link' },
    kerf: { status: 'yes', note: 'Viewer wired' },
  },
  {
    domain: 'D7',
    feature: '3-axis CAM',
    competitor: { status: 'no', note: 'Not included' },
    kerf: { status: 'yes', note: 'CAMView wired' },
  },
]

/* -------------------------------------------------------------------------- */
/* Tests                                                                       */
/* -------------------------------------------------------------------------- */

describe('CompareFeatureMatrix', () => {
  it('returns empty string (null component) when features is undefined', () => {
    const html = render(<CompareFeatureMatrix features={undefined} competitor="Fusion 360" />)
    expect(html).toBe('')
  })

  it('returns empty string (null component) when features is an empty array', () => {
    const html = render(<CompareFeatureMatrix features={[]} competitor="Fusion 360" />)
    expect(html).toBe('')
  })

  it('renders the "Full feature matrix" section header when features are present', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    expect(html).toContain('Full feature matrix')
  })

  it('renders the data-testid compare-feature-matrix container', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    expect(html).toContain('data-testid="compare-feature-matrix"')
  })

  it('groups features by domain — D1 section present', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    expect(html).toContain('data-testid="domain-section-D1"')
  })

  it('groups features by domain — D6 section present', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    expect(html).toContain('data-testid="domain-section-D6"')
  })

  it('groups features by domain — D7 section present', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    expect(html).toContain('data-testid="domain-section-D7"')
  })

  it('does NOT render a D2 section when no D2 features exist', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    expect(html).not.toContain('data-testid="domain-section-D2"')
  })

  it('renders feature names inside their domain section', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    expect(html).toContain('Constraint sketcher')
    expect(html).toContain('Loft')
    expect(html).toContain('PCB layout')
    expect(html).toContain('3-axis CAM')
  })

  it('status pill renders the correct symbol for "yes" status', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    // STATUS_META.yes.symbol = '✓'
    expect(html).toContain('✓')
    expect(html).toContain('data-testid="status-pill-yes"')
  })

  it('status pill renders the correct symbol for "partial" status', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    // STATUS_META.partial.symbol = '~'
    expect(html).toContain('~')
    expect(html).toContain('data-testid="status-pill-partial"')
  })

  it('status pill renders the correct symbol for "no" status', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    // STATUS_META.no.symbol = '✗'
    expect(html).toContain('✗')
    expect(html).toContain('data-testid="status-pill-no"')
  })

  it('shows "X of Y matched" count in D1 section header', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    // D1: 2 rows; sketcher=both yes (matched), loft=kerf partial (not matched) → 1 of 2
    expect(html).toContain('1 of 2 matched')
  })

  it('renders the Kerf column header', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    expect(html).toContain('data-testid="matrix-kerf-header"')
  })

  it('renders domain sections using <details> elements (collapsible)', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    // Should have exactly 3 <details> (D1, D6, D7)
    const detailsCount = (html.match(/<details/g) || []).length
    expect(detailsCount).toBe(3)
  })

  it('renders feature row count correctly for D1 (2 features)', () => {
    const html = render(<CompareFeatureMatrix features={SAMPLE_FEATURES} competitor="Fusion 360" />)
    // The D1 summary says "2 of 2" or "1 of 2" — either way contains "2"
    // The domain section shows 2 feature rows
    const d1Section = html.match(/domain-section-D1[\s\S]*?domain-section-D6/)?.[0] ?? ''
    const rowCount = (d1Section.match(/data-testid="feature-row"/g) || []).length
    expect(rowCount).toBe(2)
  })

  it('single-feature list renders correctly', () => {
    const single = [SAMPLE_FEATURES[0]]
    const html = render(<CompareFeatureMatrix features={single} competitor="Fusion 360" />)
    expect(html).toContain('data-testid="compare-feature-matrix"')
    expect(html).toContain('Constraint sketcher')
  })
})
