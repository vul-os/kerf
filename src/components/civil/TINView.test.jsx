/**
 * TINView.test.jsx — SSR smoke tests for the TIN surface viewport.
 *
 * Uses react-dom/server renderToStaticMarkup (same pattern as
 * ThermalNetworkViewer.test.jsx) — no jsdom / @testing-library required.
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import TINView from './TINView.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

// Minimal 4-point hill: centred around (5,5,2), corners at z=0
const POINTS = [
  [0, 0, 0],
  [10, 0, 0],
  [10, 10, 0],
  [0, 10, 0],
  [5, 5, 4],   // peak
]

const TRIANGLES = [
  [0, 1, 4],
  [1, 2, 4],
  [2, 3, 4],
  [3, 0, 4],
]

// ---------------------------------------------------------------------------
// 1. Empty state
// ---------------------------------------------------------------------------

describe('TINView — empty state', () => {
  it('renders without crashing when no props', () => {
    expect(() => renderToStaticMarkup(<TINView />)).not.toThrow()
  })

  it('shows fallback text with no points', () => {
    const html = renderToStaticMarkup(<TINView />)
    expect(html).toContain('No TIN data')
  })

  it('renders an SVG root', () => {
    const html = renderToStaticMarkup(<TINView />)
    expect(html).toMatch(/<svg\b/)
  })

  it('renders aria-label on SVG', () => {
    const html = renderToStaticMarkup(<TINView />)
    expect(html).toContain('aria-label="TIN surface view"')
  })
})

// ---------------------------------------------------------------------------
// 2. With point + triangle data
// ---------------------------------------------------------------------------

describe('TINView — with points and triangles', () => {
  let html

  beforeAll(() => {
    html = renderToStaticMarkup(
      <TINView points={POINTS} triangles={TRIANGLES} contourInterval={1} />
    )
  })

  it('renders without crashing', () => {
    expect(html).toBeTruthy()
  })

  it('renders SVG paths for faces', () => {
    expect(html).toMatch(/<path\b/)
  })

  it('does not render the empty-state fallback', () => {
    expect(html).not.toContain('No TIN data')
  })

  it('renders the run-analysis button', () => {
    expect(html).toContain('Run terrain analysis')
  })

  it('includes data-testid="tin-view"', () => {
    expect(html).toContain('data-testid="tin-view"')
  })

  it('renders the legend gradient', () => {
    expect(html).toMatch(/tinGrad/)
  })
})

// ---------------------------------------------------------------------------
// 3. Points only (auto-triangulation)
// ---------------------------------------------------------------------------

describe('TINView — auto-triangulation (no triangles prop)', () => {
  it('renders without crashing', () => {
    expect(() => renderToStaticMarkup(
      <TINView points={POINTS} />
    )).not.toThrow()
  })

  it('renders SVG path elements (fan triangulation)', () => {
    const html = renderToStaticMarkup(<TINView points={POINTS} />)
    expect(html).toMatch(/<path\b/)
  })
})

// ---------------------------------------------------------------------------
// 4. Wireframe / contour toggles
// ---------------------------------------------------------------------------

describe('TINView — wireframe and contour toggles', () => {
  it('renders with wireframe=false without crashing', () => {
    expect(() => renderToStaticMarkup(
      <TINView points={POINTS} triangles={TRIANGLES} wireframe={false} />
    )).not.toThrow()
  })

  it('renders with showContours=false without crashing', () => {
    expect(() => renderToStaticMarkup(
      <TINView points={POINTS} triangles={TRIANGLES} showContours={false} />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 5. onDispatch callback dispatches civil_tin_terrain
// ---------------------------------------------------------------------------

describe('TINView — onDispatch prop', () => {
  it('is rendered with the correct test id for the button', () => {
    const html = renderToStaticMarkup(
      <TINView
        points={POINTS}
        triangles={TRIANGLES}
        onDispatch={() => {}}
      />
    )
    expect(html).toContain('data-testid="tin-run-btn"')
  })

  it('button text is "Run terrain analysis"', () => {
    const html = renderToStaticMarkup(
      <TINView points={POINTS} triangles={TRIANGLES} onDispatch={() => {}} />
    )
    expect(html).toContain('Run terrain analysis')
  })
})

// ---------------------------------------------------------------------------
// 6. Custom dimensions
// ---------------------------------------------------------------------------

describe('TINView — custom dimensions', () => {
  it('respects width/height props', () => {
    const html = renderToStaticMarkup(
      <TINView points={POINTS} width={800} height={500} />
    )
    expect(html).toContain('width="800"')
    expect(html).toContain('height="500"')
  })
})
