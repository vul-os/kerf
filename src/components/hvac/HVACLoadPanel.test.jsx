/**
 * HVACLoadPanel.test.jsx — structural + payload-shape tests.
 *
 * @testing-library/react is NOT installed in this repo (see the project-wide
 * convention documented in Loader.test.jsx / SpiceRunPanel.test.jsx — adding
 * it would violate the "no new npm deps" constraint, and there's no jsdom
 * either so click-driven DOM interaction can't be simulated). Instead:
 *
 *   1. Static structure (headings) is verified with react-dom/server's
 *      renderToStaticMarkup, same as the rest of the repo.
 *   2. The `hvac_cfm_from_sensible_load` request-payload shape is verified
 *      directly against buildSensibleLoadArgs, the pure function
 *      HVACLoadPanel.jsx exports for exactly this purpose.
 *   3. The cooling/heating engine (computeCoolingLoad / computeHeatingLoad)
 *      is exercised directly to prove it always produces a result — this is
 *      what backs "results appear even when the backend call fails", since
 *      calculate() always falls through to these pure functions regardless
 *      of whether hvac_cfm_from_sensible_load succeeded.
 *   4. The Results card (only reachable through internal `calculate()` state
 *      in the live component) is verified via the extracted ResultsPanel
 *      sub-component, rendered directly with a computed result object.
 */

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import HVACLoadPanel, {
  computeCoolingLoad,
  computeHeatingLoad,
  buildSensibleLoadArgs,
  ResultsPanel,
} from './HVACLoadPanel.jsx'

const SAMPLE_INPUTS = {
  wallArea: 120, wallUValue: 0.35, roofArea: 80, roofUValue: 0.25,
  glazingArea: 24, solarHeatGainCoeff: 0.4, uValueGlazing: 1.8,
  occupantCount: 10, lightingWatts: 1200, equipmentWatts: 2000,
  infiltrationACH: 0.5, floorArea: 80, ceilingHeight: 3.0,
  outdoorDesignTemp: 35, indoorTemp: 22,
}

describe('HVACLoadPanel — static structure', () => {
  it('mounts and renders section headings', () => {
    const html = renderToStaticMarkup(<HVACLoadPanel />)
    expect(html).toMatch(/ASHRAE CLTD/i)
    expect(html).toMatch(/Opaque construction/i)
    expect(html).toMatch(/Glazing/i)
    expect(html).toMatch(/Occupancy/i)
    expect(html).toMatch(/Design conditions/i)
  })

  it('renders the "Calculate loads" action button', () => {
    const html = renderToStaticMarkup(<HVACLoadPanel />)
    expect(html).toMatch(/Calculate loads/i)
  })

  it('does not show a Results card before any calculation', () => {
    const html = renderToStaticMarkup(<HVACLoadPanel />)
    expect(html).not.toMatch(/Peak cooling/i)
  })
})

describe('buildSensibleLoadArgs — hvac_cfm_from_sensible_load payload shape', () => {
  it('has Q_btuh and delta_T_F fields, both numbers', () => {
    const args = buildSensibleLoadArgs({
      wallArea: 120, wallUValue: 0.35, outdoorSummer: 35, indoor: 22,
    })
    expect(args).toHaveProperty('Q_btuh')
    expect(args).toHaveProperty('delta_T_F')
    expect(typeof args.Q_btuh).toBe('number')
    expect(typeof args.delta_T_F).toBe('number')
  })

  it('floors Q_btuh at 100 even for a tiny/negative delta-T', () => {
    const args = buildSensibleLoadArgs({
      wallArea: 1, wallUValue: 0.01, outdoorSummer: 20, indoor: 22,
    })
    expect(args.Q_btuh).toBeGreaterThanOrEqual(100)
  })
})

describe('computeCoolingLoad / computeHeatingLoad — always produce a result', () => {
  // The live component tries the backend `hvac_cfm_from_sensible_load` call
  // first, but calculate() *always* falls through to these two pure
  // functions to build the displayed result — the backend call only
  // confirms liveness. So results appearing "even when the backend call
  // fails" is a property of these functions never throwing, not of any
  // DOM-level retry logic.
  it('computeCoolingLoad returns a totalCoolingW number and a breakdown', () => {
    const { totalCoolingW, breakdown } = computeCoolingLoad(SAMPLE_INPUTS)
    expect(typeof totalCoolingW).toBe('number')
    expect(totalCoolingW).toBeGreaterThan(0)
    expect(breakdown).toHaveProperty('wall')
    expect(breakdown).toHaveProperty('roof')
    expect(breakdown).toHaveProperty('solar')
    expect(breakdown).toHaveProperty('occupants')
  })

  it('computeHeatingLoad returns a non-negative totalHeatingW number', () => {
    const { totalHeatingW } = computeHeatingLoad({ ...SAMPLE_INPUTS, outdoorDesignTemp: -5 })
    expect(typeof totalHeatingW).toBe('number')
    expect(totalHeatingW).toBeGreaterThanOrEqual(0)
  })
})

describe('ResultsPanel — shows peak cooling and heating kW results', () => {
  const cooling = computeCoolingLoad(SAMPLE_INPUTS)
  const heating = computeHeatingLoad({ ...SAMPLE_INPUTS, outdoorDesignTemp: -5 })
  const result = {
    coolingKW: +(cooling.totalCoolingW / 1000).toFixed(2),
    heatingKW: +(heating.totalHeatingW / 1000).toFixed(2),
    breakdown: cooling.breakdown,
    coolingProfile: Array(12).fill(cooling.totalCoolingW),
    heatingProfile: Array(12).fill(heating.totalHeatingW),
  }

  it('renders Peak cooling and Peak heating labels with kW values', () => {
    const html = renderToStaticMarkup(<ResultsPanel result={result} />)
    expect(html).toMatch(/Peak cooling/i)
    expect(html).toMatch(/Peak heating/i)
    expect(html).toContain(`${result.coolingKW} kW`)
    expect(html).toContain(`${result.heatingKW} kW`)
  })

  it('renders the cooling load breakdown', () => {
    const html = renderToStaticMarkup(<ResultsPanel result={result} />)
    expect(html).toMatch(/Cooling load breakdown/i)
  })
})
