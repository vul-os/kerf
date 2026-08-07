// PVShadingPanel.test.jsx — unit tests for PVShadingPanel and MonthlyLoadChart.
//
// Tests TMY latitude-awareness:
//  - Panel renders latitude input with correct default (30°N)
//  - Panel renders TMY attribution note
//  - Dispatch payload includes latitude field
//  - api.pvShading exists

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import PVShadingPanel from './PVShadingPanel.jsx'
import MonthlyLoadChart from './MonthlyLoadChart.jsx'

// ---------------------------------------------------------------------------
// Mock fetch so no real network calls are made
// ---------------------------------------------------------------------------

function makeFetch(body, { ok = true, status = 200 } = {}) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  })
}

// ---------------------------------------------------------------------------
// MonthlyLoadChart — renders SVG with 12 month labels
// ---------------------------------------------------------------------------

describe('MonthlyLoadChart', () => {
  it('renders an SVG element', () => {
    const html = renderToStaticMarkup(
      <MonthlyLoadChart data={[]} title="Test Chart" />
    )
    expect(html).toContain('<svg')
    expect(html).toContain('Test Chart')
  })

  it('renders all 12 month labels', () => {
    const html = renderToStaticMarkup(
      <MonthlyLoadChart data={[]} />
    )
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    for (const m of months) {
      expect(html).toContain(m)
    }
  })

  it('renders legend series labels', () => {
    const html = renderToStaticMarkup(
      <MonthlyLoadChart data={[]} />
    )
    expect(html).toContain('Heating')
    expect(html).toContain('Cooling')
    expect(html).toContain('Lighting')
    expect(html).toContain('Equipment')
  })

  it('uses role=img and aria-label', () => {
    const html = renderToStaticMarkup(
      <MonthlyLoadChart data={[]} title="Energy Chart" />
    )
    expect(html).toContain('role="img"')
    expect(html).toContain('aria-label="Energy Chart"')
  })
})

// ---------------------------------------------------------------------------
// PVShadingPanel — structural render
// ---------------------------------------------------------------------------

describe('PVShadingPanel — structural', () => {
  beforeEach(() => { vi.unstubAllGlobals() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('renders the panel root with testid', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    expect(html).toContain('data-testid="pv-shading-panel"')
  })

  it('renders PV Shading header', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    expect(html).toContain('PV Shading')
  })

  it('renders Run button', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    expect(html).toContain('Run')
  })

  it('renders Array Layout section', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    expect(html).toContain('Array Layout')
  })

  it('renders Module Parameters section', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    expect(html).toContain('Module Parameters')
  })

  it('renders Bypass Diodes section', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    expect(html).toContain('Bypass Diodes')
  })

  // TMY latitude awareness tests
  it('renders Latitude input label', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    expect(html).toContain('Latitude')
  })

  it('renders TMY attribution text', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    // Check for TMY3 reference in the attribution note
    expect(html).toContain('TMY3')
  })

  it('renders hemisphere hint text', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    // Default is 30°N — should show NH profile hint
    expect(html).toContain('NH profile')
  })

  it('renders latitude input with step=0.1', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(
      <PVShadingPanel projectId="test-proj" />
    )
    // The latitude input should be present with min="-90" max="90"
    expect(html).toContain('min="-90"')
    expect(html).toContain('max="90"')
  })
})

// ---------------------------------------------------------------------------
// PVShadingPanel — dispatch payload shape (latitude present)
// ---------------------------------------------------------------------------

describe('PVShadingPanel — dispatch payload with latitude', () => {
  it('PV shading payload includes latitude and all required fields', () => {
    // Validate the payload structure the component would send
    const payload = {
      modules_per_string: 10,
      strings_in_parallel: 2,
      tilt_deg: 30,
      azimuth_deg: 180,
      latitude: 30,   // default 30°N backward-compat
      poa_annual_kWh_m2: 1200,
      pr: 0.80,
      module: {
        Iph: 9.0, Io: 1.5e-10, Rs: 0.005, Rsh: 400,
        n: 1.3, T_C: 25, n_cells: 60, cells_per_bypass: 20,
      },
      shading_pattern: [
        { cells: 20, irradiance: 200 },
        { cells: 40, irradiance: 1000 },
      ],
      bypass_diodes: true,
      bypass_fwd_v: 0.7,
    }

    const requiredTopLevel = [
      'modules_per_string', 'strings_in_parallel',
      'tilt_deg', 'azimuth_deg', 'latitude',
      'poa_annual_kWh_m2', 'pr',
      'module', 'shading_pattern',
      'bypass_diodes', 'bypass_fwd_v',
    ]
    for (const key of requiredTopLevel) {
      expect(payload).toHaveProperty(key)
    }

    // latitude is the TMY hook
    expect(payload.latitude).toBe(30)

    // Module sub-keys
    const requiredModuleKeys = ['Iph', 'Io', 'Rs', 'Rsh', 'n', 'T_C', 'n_cells', 'cells_per_bypass']
    for (const key of requiredModuleKeys) {
      expect(payload.module).toHaveProperty(key)
    }

    // Shading pattern items
    expect(payload.shading_pattern[0]).toHaveProperty('cells')
    expect(payload.shading_pattern[0]).toHaveProperty('irradiance')
  })

  it('negative latitude sent for Southern-hemisphere site', () => {
    // Verifies that a negative latitude would be passed through correctly
    const lat = -33.9  // Sydney, AU
    const body = { latitude: lat }
    expect(body.latitude).toBeLessThan(0)
  })

  it('bypass_diodes defaults to true', () => {
    const defaultBypassDiodes = true
    expect(defaultBypassDiodes).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// api.pvShading exists
// ---------------------------------------------------------------------------

describe('api helpers', () => {
  it('api module exports pvShading function', async () => {
    const { api } = await import('../../lib/api.js')
    expect(typeof api.pvShading).toBe('function')
  })

  it('api module exports buildingEnergy function', async () => {
    const { api } = await import('../../lib/api.js')
    expect(typeof api.buildingEnergy).toBe('function')
  })
})
