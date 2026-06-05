/**
 * InteriorSpacePanel.test.jsx — SSR smoke tests for interior space planning panel.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import InteriorSpacePanel from './InteriorSpacePanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ROOM = {
  name: 'Conference Room',
  width_mm: 8000,
  depth_mm: 5000,
  ceiling_height_mm: 2700,
}

const ITEMS = [
  { id: 'D1', kind: 'desk',  x_mm: 200,  y_mm: 200,  width_mm: 1500, depth_mm: 750,  label: 'Desk A' },
  { id: 'C1', kind: 'chair', x_mm: 200,  y_mm: 1100, width_mm: 500,  depth_mm: 500,  label: 'Chair 1' },
  { id: 'T1', kind: 'table', x_mm: 3000, y_mm: 1500, width_mm: 2400, depth_mm: 1200, label: 'Conf Table' },
]

const CIRC_PATHS = [
  {
    name: 'Main aisle',
    start: [0, 2500],
    end: [8000, 2500],
    clear_width_mm: 1200,
  },
  {
    name: 'Narrow passage',
    start: [4000, 0],
    end: [4000, 5000],
    clear_width_mm: 800,  // < 914 ADA minimum → non-compliant
  },
]

const FINISHES = {
  floor: 'Polished concrete 150mm slab on grade',
  ceiling: 'Suspended acoustic tile — Armstrong Cortega 600×600',
  walls: 'Painted gypsum board — Dulux White Glow',
}

// ---------------------------------------------------------------------------
// 1. Default / empty state
// ---------------------------------------------------------------------------

describe('InteriorSpacePanel — default state', () => {
  it('renders without crashing with no props', () => {
    expect(() => renderToStaticMarkup(<InteriorSpacePanel />)).not.toThrow()
  })

  it('has data-testid="interior-space-panel"', () => {
    const html = renderToStaticMarkup(<InteriorSpacePanel />)
    expect(html).toContain('data-testid="interior-space-panel"')
  })

  it('renders SVG canvas', () => {
    const html = renderToStaticMarkup(<InteriorSpacePanel />)
    expect(html).toMatch(/<svg\b/)
    expect(html).toContain('data-testid="interior-svg"')
  })

  it('has aria-label on SVG', () => {
    const html = renderToStaticMarkup(<InteriorSpacePanel />)
    expect(html).toContain('aria-label="Interior floor plan"')
  })

  it('shows header label', () => {
    const html = renderToStaticMarkup(<InteriorSpacePanel />)
    expect(html).toContain('Interior Space Plan')
  })
})

// ---------------------------------------------------------------------------
// 2. With room data
// ---------------------------------------------------------------------------

describe('InteriorSpacePanel — with room', () => {
  let html

  it('renders without crashing', () => {
    expect(() => renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} />
    )).not.toThrow()
  })

  it('shows room name in plan', () => {
    html = renderToStaticMarkup(<InteriorSpacePanel room={ROOM} />)
    expect(html).toContain('Conference Room')
  })

  it('shows room dimensions', () => {
    html = renderToStaticMarkup(<InteriorSpacePanel room={ROOM} />)
    expect(html).toContain('8.0 × 5.0 m')
  })

  it('shows area schedule with correct area', () => {
    html = renderToStaticMarkup(<InteriorSpacePanel room={ROOM} />)
    expect(html).toContain('data-testid="area-schedule"')
    expect(html).toContain('40.0 m²')
  })

  it('shows ceiling height', () => {
    html = renderToStaticMarkup(<InteriorSpacePanel room={ROOM} />)
    expect(html).toContain('2.70 m')
  })
})

// ---------------------------------------------------------------------------
// 3. With furniture items
// ---------------------------------------------------------------------------

describe('InteriorSpacePanel — with items', () => {
  it('renders furniture rectangles', () => {
    const html = renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} items={ITEMS} />
    )
    expect(html).toContain('Desk A')
    expect(html).toContain('Chair 1')
    expect(html).toContain('Conf Table')
  })

  it('shows item count in area schedule', () => {
    const html = renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} items={ITEMS} />
    )
    // Should show Items: 3
    expect(html).toContain('3')
  })
})

// ---------------------------------------------------------------------------
// 4. Circulation paths
// ---------------------------------------------------------------------------

describe('InteriorSpacePanel — circulation paths', () => {
  it('renders circulation paths without crashing', () => {
    expect(() => renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} circPaths={CIRC_PATHS} />
    )).not.toThrow()
  })

  it('shows path names', () => {
    const html = renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} circPaths={CIRC_PATHS} />
    )
    expect(html).toContain('Main aisle')
    expect(html).toContain('Narrow passage')
  })

  it('shows path count in area schedule', () => {
    const html = renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} circPaths={CIRC_PATHS} />
    )
    expect(html).toContain('Paths:')
  })
})

// ---------------------------------------------------------------------------
// 5. Finishes schedule
// ---------------------------------------------------------------------------

describe('InteriorSpacePanel — finishes schedule', () => {
  it('renders finishes schedule when provided', () => {
    const html = renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} finishes={FINISHES} />
    )
    expect(html).toContain('data-testid="finishes-schedule"')
    expect(html).toContain('Finishes Schedule')
  })

  it('shows floor finish', () => {
    const html = renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} finishes={FINISHES} />
    )
    expect(html).toContain('Polished concrete')
  })

  it('shows ceiling finish', () => {
    const html = renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} finishes={FINISHES} />
    )
    expect(html).toContain('Armstrong')
  })

  it('shows wall finish', () => {
    const html = renderToStaticMarkup(
      <InteriorSpacePanel room={ROOM} finishes={FINISHES} />
    )
    expect(html).toContain('Dulux')
  })

  it('does not render finishes section when none provided', () => {
    const html = renderToStaticMarkup(<InteriorSpacePanel room={ROOM} />)
    expect(html).not.toContain('data-testid="finishes-schedule"')
  })
})

// ---------------------------------------------------------------------------
// 6. ADA audit button
// ---------------------------------------------------------------------------

describe('InteriorSpacePanel — ADA audit button', () => {
  it('renders ADA audit button', () => {
    const html = renderToStaticMarkup(<InteriorSpacePanel />)
    expect(html).toContain('data-testid="interior-audit-btn"')
    expect(html).toContain('ADA audit')
  })

  it('renders with onDispatch prop without crashing', () => {
    expect(() => renderToStaticMarkup(
      <InteriorSpacePanel
        room={ROOM}
        items={ITEMS}
        circPaths={CIRC_PATHS}
        finishes={FINISHES}
        onDispatch={() => {}}
      />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 7. Custom SVG dimensions
// ---------------------------------------------------------------------------

describe('InteriorSpacePanel — custom dimensions', () => {
  it('respects svgWidth/svgHeight props', () => {
    const html = renderToStaticMarkup(
      <InteriorSpacePanel svgWidth={700} svgHeight={500} />
    )
    expect(html).toContain('width="700"')
    expect(html).toContain('height="500"')
  })
})
