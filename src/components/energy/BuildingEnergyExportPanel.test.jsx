// BuildingEnergyExportPanel.test.jsx — structural + dispatch tests.
//
// Tests:
//   1. Renders "Building Energy Model Export" heading.
//   2. Renders gbXML and IDF format options.
//   3. Renders climate zone select with ASHRAE 90.1 zones.
//   4. Renders "Apply defaults" button for climate zone U-values.
//   5. Renders zone editor with floor_area and ceiling_height fields.
//   6. Renders Export button.
//   7. Renders gbXML schema reference text.
//   8. Renders EnergyPlus IDF reference text.
//   9. Renders "Add Zone" button.
//  10. Panel renders without crashing.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import BuildingEnergyExportPanel from './BuildingEnergyExportPanel.jsx'

// ---------------------------------------------------------------------------
// Mock fetch
// ---------------------------------------------------------------------------

function makeFetch(body, { ok = true } = {}) {
  return vi.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 400,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  })
}

// ---------------------------------------------------------------------------
// 1. Heading
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel heading', () => {
  it('renders the building energy export heading', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Building Energy Model Export')
  })

  it('renders gbXML reference', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('gbXML')
  })
})

// ---------------------------------------------------------------------------
// 2. Format options
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel format options', () => {
  it('renders gbxml option', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('gbXML v0.37')
  })

  it('renders EnergyPlus IDF option', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('EnergyPlus IDF')
  })
})

// ---------------------------------------------------------------------------
// 3. Climate zone select
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel climate zones', () => {
  it('renders multiple ASHRAE climate zone options', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('4A')
    expect(html).toContain('3A')
    expect(html).toContain('5B')
  })

  it('renders ASHRAE Climate Zone label', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('ASHRAE Climate Zone')
  })
})

// ---------------------------------------------------------------------------
// 4. Apply defaults button
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel climate defaults', () => {
  it('renders Apply defaults button', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Apply defaults')
  })

  it('renders ASHRAE 90.1 reference in tooltip/title', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('ASHRAE 90.1')
  })
})

// ---------------------------------------------------------------------------
// 5. Zone editor fields
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel zone editor', () => {
  it('renders Floor Area field', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Floor Area')
  })

  it('renders Ceiling Height field', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Ceiling Height')
  })

  it('renders Window Area field', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Window Area')
  })

  it('renders Wall U-value field', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Wall U')
  })
})

// ---------------------------------------------------------------------------
// 6. Export button
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel export button', () => {
  it('renders Export button', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Export')
  })
})

// ---------------------------------------------------------------------------
// 7. gbXML schema reference
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel references', () => {
  it('references TRACE 3D Plus as import target', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('TRACE 3D')
  })

  it('references eQUEST as import target', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('eQUEST')
  })

  it('references OpenStudio', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('OpenStudio')
  })
})

// ---------------------------------------------------------------------------
// 8. Setpoint fields
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel setpoints', () => {
  it('renders Heating SP field', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Heating SP')
  })

  it('renders Cooling SP field', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Cooling SP')
  })
})

// ---------------------------------------------------------------------------
// 9. Add Zone button
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel add zone', () => {
  it('renders Add Zone button', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Add Zone')
  })

  it('renders Thermal Zones count label', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).toContain('Thermal Zones')
  })
})

// ---------------------------------------------------------------------------
// 10. No crash
// ---------------------------------------------------------------------------

describe('BuildingEnergyExportPanel stability', () => {
  it('renders without crashing', () => {
    expect(() => {
      renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    }).not.toThrow()
  })

  it('renders without undefined text', () => {
    const html = renderToStaticMarkup(<BuildingEnergyExportPanel projectId="proj_1" />)
    expect(html).not.toContain('>undefined<')
  })
})
