/**
 * LandscapeView.test.jsx — SSR smoke tests for the landscape plan viewport.
 */
import { describe, it, expect, beforeAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import LandscapeView from './LandscapeView.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const PLANTS = [
  { id: 'T1', x: 5,  y: 5,  type: 'tree',  species: 'Quercus robur',  canopy_m: 4 },
  { id: 'S1', x: 15, y: 8,  type: 'shrub', species: 'Buxus sempervirens', canopy_m: 1 },
  { id: 'G1', x: 10, y: 20, type: 'groundcover', canopy_m: 0.5 },
]

const ZONES = [
  {
    id: 'Z1',
    label: 'Lawn',
    points: [[0, 0], [20, 0], [20, 25], [0, 25]],
    area_m2: 500,
    precipitation_rate_mm_hr: 20,
    soil_type: 'loam',
  },
  {
    id: 'Z2',
    label: 'Beds',
    points: [[20, 0], [35, 0], [35, 25], [20, 25]],
    area_m2: 375,
    precipitation_rate_mm_hr: 30,
    soil_type: 'clay',
  },
]

const HARDSCAPE = [
  {
    id: 'Patio1',
    type: 'patio',
    points: [[5, 8], [12, 8], [12, 14], [5, 14]],
  },
]

// ---------------------------------------------------------------------------
// 1. Empty state
// ---------------------------------------------------------------------------

describe('LandscapeView — empty state', () => {
  it('renders without crashing with no props', () => {
    expect(() => renderToStaticMarkup(<LandscapeView />)).not.toThrow()
  })

  it('shows fallback text when no data', () => {
    const html = renderToStaticMarkup(<LandscapeView />)
    expect(html).toContain('No landscape data')
  })

  it('renders an SVG root', () => {
    const html = renderToStaticMarkup(<LandscapeView />)
    expect(html).toMatch(/<svg\b/)
  })

  it('has aria-label on SVG', () => {
    const html = renderToStaticMarkup(<LandscapeView />)
    expect(html).toContain('aria-label="Landscape plan view"')
  })

  it('has data-testid="landscape-view"', () => {
    const html = renderToStaticMarkup(<LandscapeView />)
    expect(html).toContain('data-testid="landscape-view"')
  })
})

// ---------------------------------------------------------------------------
// 2. With full data
// ---------------------------------------------------------------------------

describe('LandscapeView — with plants, zones, hardscape', () => {
  let html

  beforeAll(() => {
    html = renderToStaticMarkup(
      <LandscapeView
        plants={PLANTS}
        zones={ZONES}
        hardscape={HARDSCAPE}
        area_m2={875}
      />
    )
  })

  it('renders without crashing', () => {
    expect(html).toBeTruthy()
  })

  it('does not show the empty fallback', () => {
    expect(html).not.toContain('No landscape data')
  })

  it('renders zone polygon paths', () => {
    expect(html).toMatch(/<path\b/)
  })

  it('renders plant circles', () => {
    const circles = html.match(/<circle\b/g) || []
    expect(circles.length).toBeGreaterThanOrEqual(3)
  })

  it('renders zone labels', () => {
    expect(html).toContain('Lawn')
    expect(html).toContain('Beds')
  })

  it('renders plant legend entries', () => {
    expect(html).toContain('tree')
    expect(html).toContain('shrub')
  })
})

// ---------------------------------------------------------------------------
// 3. Dispatch buttons
// ---------------------------------------------------------------------------

describe('LandscapeView — dispatch buttons', () => {
  it('renders Spec plants button', () => {
    const html = renderToStaticMarkup(
      <LandscapeView plants={PLANTS} zones={ZONES} />
    )
    expect(html).toContain('Spec plants')
    expect(html).toContain('data-testid="landscape-plants-btn"')
  })

  it('renders Irrigation schedule button', () => {
    const html = renderToStaticMarkup(
      <LandscapeView plants={PLANTS} zones={ZONES} />
    )
    expect(html).toContain('Irrigation schedule')
    expect(html).toContain('data-testid="landscape-irrigation-btn"')
  })

  it('renders with onDispatch prop without crashing', () => {
    expect(() => renderToStaticMarkup(
      <LandscapeView
        plants={PLANTS}
        zones={ZONES}
        onDispatch={() => {}}
      />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 4. Plant-only data
// ---------------------------------------------------------------------------

describe('LandscapeView — plants only', () => {
  it('renders plants without zones', () => {
    const html = renderToStaticMarkup(<LandscapeView plants={PLANTS} />)
    expect(html).not.toContain('No landscape data')
    const circles = html.match(/<circle\b/g) || []
    expect(circles.length).toBeGreaterThanOrEqual(3)
  })
})

// ---------------------------------------------------------------------------
// 5. Custom dimensions
// ---------------------------------------------------------------------------

describe('LandscapeView — custom dimensions', () => {
  it('respects width/height props', () => {
    const html = renderToStaticMarkup(
      <LandscapeView plants={PLANTS} zones={ZONES} width={800} height={500} />
    )
    expect(html).toContain('width="800"')
    expect(html).toContain('height="500"')
  })
})
