/**
 * EquipmentSelectPanel.test.jsx — structural + filter-logic tests.
 *
 * @testing-library/react is NOT installed in this repo (see the project-wide
 * convention documented in Loader.test.jsx / SpiceRunPanel.test.jsx — adding
 * it would violate the "no new npm deps" constraint, and there's no jsdom
 * either so click-driven DOM interaction can't be simulated). Instead:
 *
 *   1. Static structure (heading, category buttons, full initial list) is
 *      verified with react-dom/server's renderToStaticMarkup, same as the
 *      rest of the repo — this panel's default render already shows every
 *      catalogue entry, so no interaction is needed for that coverage.
 *   2. Category/capacity/efficiency filtering is verified directly against
 *      filterEquipment, the pure function EquipmentSelectPanel.jsx exports
 *      for exactly this purpose — a more precise test of "what gets
 *      filtered" than clicking a button + re-reading the DOM would have
 *      been.
 *   3. The "Selected unit" detail card and the "N selected" count (only
 *      reachable through internal EquipmentSelectPanel state) are verified
 *      via the extracted SelectedUnitDetail / ResultsCount sub-components,
 *      rendered directly with a fixed equipment record.
 */

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import EquipmentSelectPanel, {
  EQUIPMENT_CATALOGUE,
  CATEGORIES,
  filterEquipment,
  EquipmentCard,
  ResultsCount,
  SelectedUnitDetail,
} from './EquipmentSelectPanel.jsx'

describe('EquipmentSelectPanel — static structure', () => {
  it('mounts and renders heading', () => {
    const html = renderToStaticMarkup(<EquipmentSelectPanel />)
    expect(html).toMatch(/HVAC Equipment Selector/i)
  })

  it('renders category filter buttons', () => {
    const html = renderToStaticMarkup(<EquipmentSelectPanel />)
    for (const c of CATEGORIES) {
      expect(html).toContain(`>${c.label}<`)
    }
  })

  it('shows all equipment items by default', () => {
    const html = renderToStaticMarkup(<EquipmentSelectPanel />)
    expect(html).toContain('AHU-10 Standard')
    expect(html).toContain('WCFX-200 Centrifugal')
    expect(html).toContain('FCB-150 Condensing Gas')
    expect(html).toContain('GSHP-50 Ground Source')
  })

  it('does not show a "Selected unit" card before any selection', () => {
    const html = renderToStaticMarkup(<EquipmentSelectPanel />)
    expect(html).not.toMatch(/Selected unit/i)
  })
})

describe('filterEquipment — category/capacity/efficiency filtering', () => {
  it('filters to the chiller category', () => {
    const result = filterEquipment(EQUIPMENT_CATALOGUE, { category: 'chiller', minCap: '', maxCap: '', minEff: '' })
    expect(result.every(eq => eq.category === 'chiller')).toBe(true)
    expect(result.some(eq => eq.model === 'WCFX-200 Centrifugal')).toBe(true)
    expect(result.some(eq => eq.model === 'AHU-10 Standard')).toBe(false)
  })

  it('"all" category returns the full catalogue', () => {
    const result = filterEquipment(EQUIPMENT_CATALOGUE, { category: 'all', minCap: '', maxCap: '', minEff: '' })
    expect(result).toHaveLength(EQUIPMENT_CATALOGUE.length)
  })

  it('capacity min filter removes equipment below threshold', () => {
    const result = filterEquipment(EQUIPMENT_CATALOGUE, { category: 'all', minCap: '200', maxCap: '', minEff: '' })
    // AHU-10 (10 kW) should be excluded
    expect(result.some(eq => eq.model === 'AHU-10 Standard')).toBe(false)
    // WCFX-200 (200 kW) should still be included
    expect(result.some(eq => eq.model === 'WCFX-200 Centrifugal')).toBe(true)
    expect(result.every(eq => eq.capacity_kW >= 200)).toBe(true)
  })

  it('capacity max filter removes equipment above threshold', () => {
    const result = filterEquipment(EQUIPMENT_CATALOGUE, { category: 'all', minCap: '', maxCap: '50', minEff: '' })
    expect(result.every(eq => eq.capacity_kW <= 50)).toBe(true)
    expect(result.some(eq => eq.model === 'WCFX-500 Centrifugal HE')).toBe(false)
  })

  it('minimum efficiency filter removes equipment below threshold', () => {
    const result = filterEquipment(EQUIPMENT_CATALOGUE, { category: 'all', minCap: '', maxCap: '', minEff: '6' })
    expect(result.every(eq => eq.efficiency_rated >= 6)).toBe(true)
  })
})

describe('EquipmentCard — renders "Selected" badge only when selected', () => {
  const eq = EQUIPMENT_CATALOGUE.find(e => e.model === 'AHU-10 Standard')

  it('does not show "Selected" when not selected', () => {
    const html = renderToStaticMarkup(<EquipmentCard eq={eq} selected={false} onSelect={() => {}} />)
    expect(html).not.toContain('Selected')
  })

  it('shows "Selected" when selected', () => {
    const html = renderToStaticMarkup(<EquipmentCard eq={eq} selected={true} onSelect={() => {}} />)
    expect(html).toContain('Selected')
  })
})

describe('ResultsCount — shows "N selected" count after selection', () => {
  it('shows no selection suffix when nothing is selected', () => {
    const html = renderToStaticMarkup(<ResultsCount count={12} hasSelection={false} />)
    expect(html).toContain('12 units match')
    expect(html).not.toMatch(/selected/i)
  })

  it('shows "1 selected" once something is selected', () => {
    const html = renderToStaticMarkup(<ResultsCount count={12} hasSelection={true} />)
    expect(html).toMatch(/1 selected/i)
  })
})

describe('SelectedUnitDetail — shows selected unit detail when an equipment card is selected', () => {
  const eq = EQUIPMENT_CATALOGUE.find(e => e.model === 'AHU-10 Standard')

  it('renders "Selected unit" header and model/manufacturer/capacity fields', () => {
    const html = renderToStaticMarkup(<SelectedUnitDetail eq={eq} />)
    expect(html).toMatch(/Selected unit/i)
    expect(html).toContain(eq.model)
    expect(html).toContain(eq.manufacturer)
    expect(html).toContain(`${eq.capacity_kW} kW`)
  })

  it('renders the part-load efficiency curve section', () => {
    const html = renderToStaticMarkup(<SelectedUnitDetail eq={eq} />)
    expect(html).toMatch(/Part-load efficiency/i)
  })
})
