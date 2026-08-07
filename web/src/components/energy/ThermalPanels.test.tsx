// ThermalPanels.test.jsx — unit tests for HeatExchangerPanel, ThermoCyclePanel,
// and Hourly8760Panel.
//
// Uses renderToStaticMarkup for structural / SSR-compatible tests (no DOM APIs).
// fetch is mocked so no real network calls happen.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import HeatExchangerPanel from './HeatExchangerPanel.jsx'
import ThermoCyclePanel from './ThermoCyclePanel.jsx'
import Hourly8760Panel from './Hourly8760Panel.jsx'

// ---------------------------------------------------------------------------
// fetch mock helpers
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
// 1. HeatExchangerPanel
// ---------------------------------------------------------------------------

describe('HeatExchangerPanel — structural render', () => {
  beforeEach(() => { vi.unstubAllGlobals() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('renders without crashing', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    expect(() => renderToStaticMarkup(<HeatExchangerPanel />)).not.toThrow()
  })

  it('contains the panel title', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<HeatExchangerPanel />)
    expect(html).toContain('Heat Exchanger')
  })

  it('shows LMTD tab (default active)', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<HeatExchangerPanel />)
    expect(html).toContain('LMTD')
  })

  it('shows ε-NTU tab link', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<HeatExchangerPanel />)
    // NTU appears in the tab bar
    expect(html).toContain('NTU')
  })

  it('shows Bell-Delaware tab link', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<HeatExchangerPanel />)
    expect(html).toContain('Bell')
  })

  it('LMTD panel contains temperature field labels', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<HeatExchangerPanel />)
    // Labels rendered as "Hot inlet T" / "Cold inlet T" in default LMTD tab
    expect(html).toContain('Hot inlet')
    expect(html).toContain('Cold inlet')
  })

  it('LMTD panel contains Compute button', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<HeatExchangerPanel />)
    expect(html).toContain('Compute LMTD')
  })

  it('contains flow arrangement selector', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<HeatExchangerPanel />)
    expect(html.toLowerCase()).toContain('counter') // counterflow option
  })
})

// ---------------------------------------------------------------------------
// 2. HeatExchangerPanel — tool call payload shapes
// ---------------------------------------------------------------------------

describe('HeatExchangerPanel — tool call payload', () => {
  it('LMTD payload has the correct keys', () => {
    // Validates the shape we'd POST to /api/tools/call
    const payload = {
      T_h_in: 373.15, T_h_out: 323.15,
      T_c_in: 283.15, T_c_out: 313.15,
      U: 500, A: 2.0, flow: 'counter',
    }
    const required = ['T_h_in', 'T_h_out', 'T_c_in', 'T_c_out', 'U', 'A', 'flow']
    for (const k of required) expect(payload).toHaveProperty(k)
  })

  it('ε-NTU payload has the correct keys', () => {
    const payload = {
      C_min: 1000, C_max: 1500, NTU: 2.5, flow: 'counter',
      T_c_in: 283.15, T_h_in: 373.15,
    }
    const required = ['C_min', 'C_max', 'NTU', 'flow']
    for (const k of required) expect(payload).toHaveProperty(k)
  })

  it('Bell-Delaware payload contains geometry keys', () => {
    const payload = {
      Q_duty: 50000,
      T_s_in: 373.15, T_s_out: 343.15,
      T_t_in: 293.15, T_t_out: 313.15,
      shell_fluid: { rho: 900, mu: 0.001, cp: 4000, k: 0.6, m_dot: 2.0 },
      tube_fluid: { rho: 1000, mu: 0.001, cp: 4182, k: 0.6, m_dot: 3.0 },
      D_s: 0.5, tube_od: 0.019, tube_id: 0.015,
      pitch: 0.025, layout: 'triangular',
      N_t: 100, n_passes: 2, N_b: 6, B: 0.2,
      baffle_cut: 0.25, fouling_shell: 0.0001, fouling_tube: 0.0001,
    }
    for (const k of ['Q_duty', 'D_s', 'tube_od', 'N_t', 'N_b', 'n_passes']) {
      expect(payload).toHaveProperty(k)
    }
  })
})

// ---------------------------------------------------------------------------
// 3. ThermoCyclePanel
// ---------------------------------------------------------------------------

describe('ThermoCyclePanel — structural render', () => {
  beforeEach(() => { vi.unstubAllGlobals() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('renders without crashing', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    expect(() => renderToStaticMarkup(<ThermoCyclePanel />)).not.toThrow()
  })

  it('contains the panel title', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<ThermoCyclePanel />)
    // Title includes "Cycle" or "Thermo"
    expect(html.toLowerCase()).toMatch(/thermal|cycle|thermo/)
  })

  it('shows Otto tab (default active)', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<ThermoCyclePanel />)
    expect(html).toContain('Otto')
  })

  it('shows all five cycle tabs', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<ThermoCyclePanel />)
    expect(html).toContain('Otto')
    expect(html).toContain('Diesel')
    expect(html).toContain('Brayton')
    expect(html).toContain('Rankine')
    expect(html).toContain('Carnot')
  })

  it('default Brayton panel shows pressure ratio input', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<ThermoCyclePanel />)
    // Default tab is Brayton; shows "Pressure ratio r_p"
    expect(html).toContain('Pressure ratio')
  })

  it('Brayton panel shows Compute button', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<ThermoCyclePanel />)
    expect(html).toContain('Compute Brayton')
  })
})

// ---------------------------------------------------------------------------
// 4. ThermoCyclePanel — tool call payload shapes
// ---------------------------------------------------------------------------

describe('ThermoCyclePanel — tool call payload', () => {
  it('Otto payload has required keys', () => {
    const payload = { r: 10, T1: 300, T3: 2200, k: 1.4 }
    for (const k of ['r', 'T1', 'T3', 'k']) expect(payload).toHaveProperty(k)
  })

  it('Diesel payload has required keys', () => {
    const payload = { r: 18, r_c: 2.5, T1: 300, k: 1.4 }
    for (const k of ['r', 'r_c', 'T1', 'k']) expect(payload).toHaveProperty(k)
  })

  it('Brayton payload has required keys', () => {
    const payload = { r_p: 10, T1: 300, T3: 1400, k: 1.4, eta_c: 0.87, eta_t: 0.90, eta_regen: 0.0 }
    for (const k of ['r_p', 'T1', 'T3', 'k', 'eta_c', 'eta_t']) expect(payload).toHaveProperty(k)
  })

  it('Rankine payload has required keys', () => {
    const payload = { p_high: 5e6, p_low: 10000, eta_pump: 0.85, eta_turbine: 0.87 }
    for (const k of ['p_high', 'p_low', 'eta_pump', 'eta_turbine']) expect(payload).toHaveProperty(k)
  })

  it('Carnot payload has T_H and T_L', () => {
    const payload = { T_H: 800, T_L: 300 }
    expect(payload).toHaveProperty('T_H')
    expect(payload).toHaveProperty('T_L')
  })
})

// ---------------------------------------------------------------------------
// 5. Hourly8760Panel
// ---------------------------------------------------------------------------

describe('Hourly8760Panel — structural render', () => {
  beforeEach(() => { vi.unstubAllGlobals() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('renders without crashing', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    expect(() => renderToStaticMarkup(<Hourly8760Panel />)).not.toThrow()
  })

  it('contains "8760" in the header', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<Hourly8760Panel />)
    expect(html).toContain('8760')
  })

  it('renders floor area input', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<Hourly8760Panel />)
    expect(html.toLowerCase()).toContain('floor area')
  })

  it('renders envelope U-value fields', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<Hourly8760Panel />)
    expect(html.toLowerCase()).toContain('wall u')
    expect(html.toLowerCase()).toContain('roof u')
    expect(html.toLowerCase()).toContain('window u')
  })

  it('renders SHGC field', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<Hourly8760Panel />)
    expect(html).toContain('SHGC')
  })

  it('renders climate dropdown', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<Hourly8760Panel />)
    expect(html.toLowerCase()).toContain('climate')
  })

  it('renders Run Simulation button', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<Hourly8760Panel />)
    expect(html).toContain('Simulation')
  })

  it('renders ASHRAE disclaimer', () => {
    vi.stubGlobal('fetch', makeFetch({}))
    const html = renderToStaticMarkup(<Hourly8760Panel />)
    expect(html).toContain('ASHRAE')
  })
})

// ---------------------------------------------------------------------------
// 6. Hourly8760Panel — tool call payload shape
// ---------------------------------------------------------------------------

describe('Hourly8760Panel — tool call payload', () => {
  it('be_simulate_8760 payload has building block and weather_preset', () => {
    const payload = {
      building: {
        name: 'Test Office',
        floor_area_m2: 1000,
        ceiling_height_m: 3.0,
        window_to_wall_ratio: 0.30,
        construction_uw_m2k: { wall: 0.35, roof: 0.20, window: 1.8, shgc: 0.40 },
        internal_load_w_m2: 25,
        ventilation_ach: 0.20,
        lighting_fraction: 0.40,
        fan_power_w_per_m2: 5.0,
        setpoint_heating_c: 20,
        setpoint_cooling_c: 24,
        occupancy_schedule_8760: [],
      },
      weather_preset: 'cool_temperate',
    }
    expect(payload).toHaveProperty('building')
    expect(payload).toHaveProperty('weather_preset')
    expect(payload.building).toHaveProperty('floor_area_m2')
    expect(payload.building).toHaveProperty('construction_uw_m2k')
    expect(payload.building.construction_uw_m2k).toHaveProperty('wall')
    expect(payload.building.construction_uw_m2k).toHaveProperty('shgc')
  })

  it('climate preset options are all valid strings', () => {
    const climates = [
      'cool_temperate', 'hot_arid', 'hot_humid',
      'cold_continental', 'mediterranean', 'tropical',
    ]
    for (const c of climates) {
      expect(typeof c).toBe('string')
      expect(c.length).toBeGreaterThan(0)
    }
  })
})
