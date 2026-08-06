/**
 * PlantSchedulePanel.test.jsx — SSR smoke tests for plant schedule panel.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PlantSchedulePanel from './PlantSchedulePanel.jsx'

const PLANTS = [
  { id: 'T1', species: 'Quercus robur',         type: 'tree',       count: 3 },
  { id: 'S1', species: 'Lavandula angustifolia', type: 'shrub',      count: 12 },
  { id: 'G1', species: 'Echinacea purpurea',     type: 'perennial',  count: 25 },
]

// ---------------------------------------------------------------------------
// 1. Empty state
// ---------------------------------------------------------------------------

describe('PlantSchedulePanel — empty state', () => {
  it('renders without crashing', () => {
    expect(() => renderToStaticMarkup(<PlantSchedulePanel />)).not.toThrow()
  })

  it('has data-testid="plant-schedule-panel"', () => {
    const html = renderToStaticMarkup(<PlantSchedulePanel />)
    expect(html).toContain('data-testid="plant-schedule-panel"')
  })

  it('shows empty state message', () => {
    const html = renderToStaticMarkup(<PlantSchedulePanel />)
    expect(html).toContain('No plants to display')
  })

  it('renders toolbar label', () => {
    const html = renderToStaticMarkup(<PlantSchedulePanel />)
    expect(html).toContain('Plant Schedule')
  })
})

// ---------------------------------------------------------------------------
// 2. With plant data
// ---------------------------------------------------------------------------

describe('PlantSchedulePanel — with plants', () => {
  it('renders without crashing', () => {
    expect(() => renderToStaticMarkup(
      <PlantSchedulePanel plants={PLANTS} />
    )).not.toThrow()
  })

  it('shows plant schedule table', () => {
    const html = renderToStaticMarkup(<PlantSchedulePanel plants={PLANTS} />)
    expect(html).toContain('data-testid="plant-schedule-table"')
  })

  it('shows plant species names', () => {
    const html = renderToStaticMarkup(<PlantSchedulePanel plants={PLANTS} />)
    expect(html).toContain('Quercus robur')
  })
})

// ---------------------------------------------------------------------------
// 3. Toolbar buttons
// ---------------------------------------------------------------------------

describe('PlantSchedulePanel — toolbar', () => {
  it('renders zone catalog button with zone number', () => {
    const html = renderToStaticMarkup(<PlantSchedulePanel usdaZone={7} />)
    expect(html).toContain('data-testid="plant-filter-btn"')
    expect(html).toContain('Zone 7')
  })

  it('renders lookup input and button', () => {
    const html = renderToStaticMarkup(<PlantSchedulePanel />)
    expect(html).toContain('data-testid="plant-lookup-input"')
    expect(html).toContain('data-testid="plant-lookup-btn"')
    expect(html).toContain('Lookup')
  })

  it('renders with onDispatch prop without crashing', () => {
    expect(() => renderToStaticMarkup(
      <PlantSchedulePanel plants={PLANTS} onDispatch={() => {}} />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 4. Props
// ---------------------------------------------------------------------------

describe('PlantSchedulePanel — USDA zone prop', () => {
  it('renders for zone 4', () => {
    expect(() => renderToStaticMarkup(
      <PlantSchedulePanel usdaZone={4} />
    )).not.toThrow()
  })

  it('renders for zone 10', () => {
    expect(() => renderToStaticMarkup(
      <PlantSchedulePanel usdaZone={10} />
    )).not.toThrow()
  })
})
