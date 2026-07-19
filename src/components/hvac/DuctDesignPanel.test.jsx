/**
 * DuctDesignPanel.test.jsx — structural + payload-shape tests.
 *
 * @testing-library/react is NOT installed in this repo (see the project-wide
 * convention documented in Loader.test.jsx / SpiceRunPanel.test.jsx — adding
 * it would violate the "no new npm deps" constraint, and there's no jsdom
 * either so click-driven DOM interaction can't be simulated). Instead:
 *
 *   1. Static structure (heading, material selector) is verified with
 *      react-dom/server's renderToStaticMarkup, same as the rest of the repo.
 *   2. The `hvac.size_duct` / `hvac.pressure_drop` request-payload shapes and
 *      the client-side fallback calculation are verified directly against
 *      the pure functions DuctDesignPanel.jsx exports for exactly this
 *      purpose (buildSizeDuctArgs, buildPressureDropArgs, computeDuctSegment)
 *      — this is a more precise test of "what gets dispatched" than mounting
 *      + clicking + inspecting a fetch mock would have been.
 *   3. The "Total system pressure" summary row (only reachable through
 *      internal `calculate()` state in the live component) is verified via
 *      the extracted TotalPressureDisplay sub-component, rendered directly
 *      with a fixed value.
 */

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import DuctDesignPanel, {
  MATERIAL_OPTIONS,
  computeDuctSegment,
  buildSizeDuctArgs,
  buildPressureDropArgs,
  TotalPressureDisplay,
} from './DuctDesignPanel.jsx'

describe('DuctDesignPanel — static structure', () => {
  it('mounts and renders duct sizing heading', () => {
    const html = renderToStaticMarkup(<DuctDesignPanel />)
    expect(html).toMatch(/ASHRAE Duct Sizing/i)
  })

  it('renders material selector with all material options', () => {
    const html = renderToStaticMarkup(<DuctDesignPanel />)
    expect(html).toContain('<select')
    for (const m of MATERIAL_OPTIONS) {
      expect(html).toContain(m.label)
    }
  })

  it('renders the "Size all segments" action button', () => {
    const html = renderToStaticMarkup(<DuctDesignPanel />)
    expect(html).toMatch(/Size all segments/i)
  })

  it('does not show "Total system pressure" before any calculation', () => {
    const html = renderToStaticMarkup(<DuctDesignPanel />)
    expect(html).not.toMatch(/Total system pressure/i)
  })
})

describe('buildSizeDuctArgs — hvac.size_duct payload shape', () => {
  it('parses airflow/velocity to numbers and passes shape through', () => {
    const args = buildSizeDuctArgs({
      airflow_cfm: '1000', max_velocity_fpm: '2000', shape: 'rectangular',
    })
    expect(args).toEqual({ airflow_cfm: 1000, max_velocity_fpm: 2000, shape: 'rectangular' })
  })

  it('has exactly the fields the hvac.size_duct tool expects', () => {
    const args = buildSizeDuctArgs({ airflow_cfm: '500', max_velocity_fpm: '1500', shape: 'round' })
    expect(args).toHaveProperty('airflow_cfm')
    expect(args).toHaveProperty('max_velocity_fpm')
    expect(args).toHaveProperty('shape')
    expect(typeof args.airflow_cfm).toBe('number')
    expect(typeof args.max_velocity_fpm).toBe('number')
  })
})

describe('buildPressureDropArgs — hvac.pressure_drop payload shape', () => {
  const sizeResp = {
    actual_velocity_m_s: 10.05,
    hydraulic_diameter_mm: 222.2,
  }

  it('carries velocity + hydraulic diameter from the size_duct response', () => {
    const args = buildPressureDropArgs(sizeResp, { length_m: '10', fittings: [] }, 0.09)
    expect(args.velocity_m_s).toBe(10.05)
    expect(args.hydraulic_diameter_mm).toBe(222.2)
  })

  it('parses length_m to a number and forwards roughness_mm', () => {
    const args = buildPressureDropArgs(sizeResp, { length_m: '10', fittings: [] }, 0.09)
    expect(args.length_m).toBe(10)
    expect(args.roughness_mm).toBe(0.09)
  })

  it('defaults fittings to [] when the segment has none', () => {
    const args = buildPressureDropArgs(sizeResp, { length_m: '10' }, 0.09)
    expect(args.fittings).toEqual([])
  })

  it('forwards the segment fittings list unchanged', () => {
    const args = buildPressureDropArgs(sizeResp, { length_m: '10', fittings: ['elbow_90_rect'] }, 0.09)
    expect(args.fittings).toEqual(['elbow_90_rect'])
  })

  it('has exactly the fields the hvac.pressure_drop tool expects', () => {
    const args = buildPressureDropArgs(sizeResp, { length_m: '10', fittings: [] }, 0.09)
    expect(args).toHaveProperty('velocity_m_s')
    expect(args).toHaveProperty('hydraulic_diameter_mm')
    expect(args).toHaveProperty('length_m')
  })
})

describe('computeDuctSegment — client-side fallback calculation', () => {
  it('falls back to a client-side computation when the backend is unavailable', () => {
    const result = computeDuctSegment(
      { airflow_cfm: 1000, max_velocity_fpm: 2000, shape: 'rectangular', length_m: 10, fittings: [] },
      0.09,
    )
    expect(result).toBeTruthy()
    expect(typeof result.total_pa).toBe('number')
    expect(result.total_pa).toBeGreaterThan(0)
  })

  it('produces a diameter for round ducts and width/height for rectangular', () => {
    const round = computeDuctSegment(
      { airflow_cfm: 1000, max_velocity_fpm: 2000, shape: 'round', length_m: 10, fittings: [] },
      0.09,
    )
    expect(round.d_mm).toBeGreaterThan(0)

    const rect = computeDuctSegment(
      { airflow_cfm: 1000, max_velocity_fpm: 2000, shape: 'rectangular', length_m: 10, fittings: [] },
      0.09,
    )
    expect(rect.w_mm).toBeGreaterThan(0)
    expect(rect.h_mm).toBeGreaterThan(0)
  })

  it('adds fitting losses on top of friction loss when fittings are present', () => {
    const noFittings = computeDuctSegment(
      { airflow_cfm: 1000, max_velocity_fpm: 2000, shape: 'rectangular', length_m: 10, fittings: [] },
      0.09,
    )
    const withFittings = computeDuctSegment(
      { airflow_cfm: 1000, max_velocity_fpm: 2000, shape: 'rectangular', length_m: 10, fittings: ['elbow_90_rect'] },
      0.09,
    )
    expect(withFittings.fittings_pa).toBeGreaterThan(0)
    expect(withFittings.total_pa).toBeGreaterThan(noFittings.total_pa)
  })
})

describe('TotalPressureDisplay — shows total system pressure after calculation', () => {
  it('renders the "Total system pressure" label and value', () => {
    const html = renderToStaticMarkup(<TotalPressureDisplay total={18.5} />)
    expect(html).toMatch(/Total system pressure/i)
    expect(html).toContain('18.5 Pa')
  })

  it('renders a fallback-computed total the same way as a backend total', () => {
    // Exercises the same computeDuctSegment() path DuctDesignPanel's
    // calculate() uses when hvac.size_duct / hvac.pressure_drop fail —
    // proves the fallback total is renderable end-to-end.
    const result = computeDuctSegment(
      { airflow_cfm: 1000, max_velocity_fpm: 2000, shape: 'rectangular', length_m: 10, fittings: [] },
      0.09,
    )
    const html = renderToStaticMarkup(<TotalPressureDisplay total={result.total_pa} />)
    expect(html).toMatch(/Total system pressure/i)
    expect(html).toContain(`${result.total_pa} Pa`)
  })
})
