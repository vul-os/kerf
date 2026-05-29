/**
 * GradingPlanView.test.jsx — SSR smoke tests for the grading plan viewport.
 */
import { describe, it, expect, beforeAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import GradingPlanView from './GradingPlanView.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

// Flat existing surface at z=0
const EXISTING = [
  [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
]

// Proposed with a berm in the middle (fill) and cut at corners
const PROPOSED = [
  [0, 0, -1], [10, 0, -1], [10, 10, -1], [0, 10, -1],
  [5, 5, 2],  // raised centre → fill
]

// Manual triangles for existing (flat square split into 2 triangles)
const EX_TRIS = [[0, 1, 2], [0, 2, 3]]

// ---------------------------------------------------------------------------
// 1. Empty state
// ---------------------------------------------------------------------------

describe('GradingPlanView — empty state', () => {
  it('renders without crashing with no props', () => {
    expect(() => renderToStaticMarkup(<GradingPlanView />)).not.toThrow()
  })

  it('shows fallback text when no data', () => {
    const html = renderToStaticMarkup(<GradingPlanView />)
    expect(html).toContain('No grading data')
  })

  it('renders an SVG root', () => {
    const html = renderToStaticMarkup(<GradingPlanView />)
    expect(html).toMatch(/<svg\b/)
  })

  it('has aria-label on SVG', () => {
    const html = renderToStaticMarkup(<GradingPlanView />)
    expect(html).toContain('aria-label="Grading plan view"')
  })

  it('has data-testid="grading-plan-view"', () => {
    const html = renderToStaticMarkup(<GradingPlanView />)
    expect(html).toContain('data-testid="grading-plan-view"')
  })
})

// ---------------------------------------------------------------------------
// 2. With data
// ---------------------------------------------------------------------------

describe('GradingPlanView — with existing + proposed surfaces', () => {
  let html

  beforeAll(() => {
    html = renderToStaticMarkup(
      <GradingPlanView
        existing={EXISTING}
        proposed={PROPOSED}
        existingTriangles={EX_TRIS}
        contourInterval={0.5}
      />
    )
  })

  it('renders without crashing', () => {
    expect(html).toBeTruthy()
  })

  it('does not show the empty fallback', () => {
    expect(html).not.toContain('No grading data')
  })

  it('renders cut/fill path elements', () => {
    expect(html).toMatch(/<path\b/)
  })

  it('renders legend with Fill and Cut labels', () => {
    expect(html).toContain('Fill')
    expect(html).toContain('Cut')
  })

  it('renders legend with existing/proposed contour entries', () => {
    expect(html).toContain('Existing contour')
    expect(html).toContain('Proposed contour')
  })
})

// ---------------------------------------------------------------------------
// 3. Compute volumes button
// ---------------------------------------------------------------------------

describe('GradingPlanView — compute volumes dispatch', () => {
  it('renders the Compute volumes button', () => {
    const html = renderToStaticMarkup(
      <GradingPlanView existing={EXISTING} proposed={PROPOSED} />
    )
    expect(html).toContain('Compute volumes')
    expect(html).toContain('data-testid="grading-volume-btn"')
  })

  it('renders with onDispatch prop without crashing', () => {
    expect(() => renderToStaticMarkup(
      <GradingPlanView
        existing={EXISTING}
        proposed={PROPOSED}
        onDispatch={() => {}}
      />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 4. Custom dimensions
// ---------------------------------------------------------------------------

describe('GradingPlanView — custom dimensions', () => {
  it('respects width/height', () => {
    const html = renderToStaticMarkup(
      <GradingPlanView existing={EXISTING} proposed={PROPOSED} width={800} height={500} />
    )
    expect(html).toContain('width="800"')
    expect(html).toContain('height="500"')
  })
})
