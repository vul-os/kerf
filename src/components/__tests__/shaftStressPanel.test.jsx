/**
 * shaftStressPanel.test.jsx
 *
 * Source-level assertions + pure-helper unit tests for ShaftStressPanel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 *
 * Coverage:
 *  1. fmtNum helper
 *  2. buildShaftDiamParams
 *  3. buildCritSpeedParams
 *  4. Source structure — data-testid markers
 *  5. api.callTool invocations (source scan)
 *  6. renderToStaticMarkup smoke test
 */

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import ShaftStressPanel, {
  fmtNum,
  buildShaftDiamParams,
  buildCritSpeedParams,
} from '../ShaftStressPanel.jsx'

const SRC = readFileSync(
  resolve(__dirname, '../ShaftStressPanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// 1. fmtNum
// ---------------------------------------------------------------------------

describe('fmtNum', () => {
  it('returns — for null', () => {
    expect(fmtNum(null)).toBe('—')
  })

  it('returns — for NaN', () => {
    expect(fmtNum(NaN)).toBe('—')
  })

  it('formats to 3dp by default', () => {
    expect(fmtNum(1.23456)).toBe('1.235')
  })

  it('respects custom dp', () => {
    expect(fmtNum(3.14159, 2)).toBe('3.14')
  })

  it('formats 0', () => {
    expect(fmtNum(0, 2)).toBe('0.00')
  })
})

// ---------------------------------------------------------------------------
// 2. buildShaftDiamParams
// ---------------------------------------------------------------------------

describe('buildShaftDiamParams', () => {
  const state = {
    M: '200', T: '150', sigma_allow: '200e6',
    method: 'DE-Goodman', Kf: '1.5', Kfs: '1.3', safety_factor: '1.5',
  }

  it('parses M as float', () => {
    expect(buildShaftDiamParams(state).M).toBe(200)
  })

  it('parses T as float', () => {
    expect(buildShaftDiamParams(state).T).toBe(150)
  })

  it('parses sigma_allow', () => {
    expect(buildShaftDiamParams(state).sigma_allow).toBe(200e6)
  })

  it('passes method through', () => {
    expect(buildShaftDiamParams(state).method).toBe('DE-Goodman')
  })

  it('parses Kf', () => {
    expect(buildShaftDiamParams(state).Kf).toBeCloseTo(1.5)
  })

  it('falls back to 0 for empty M', () => {
    expect(buildShaftDiamParams({ ...state, M: '' }).M).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// 3. buildCritSpeedParams
// ---------------------------------------------------------------------------

describe('buildCritSpeedParams', () => {
  const state = {
    length_m: '1.0', mass_per_m: '7.85',
    E: '200e9', I: '1e-7',
    supports: 'simply-supported',
  }

  it('parses length_m', () => {
    expect(buildCritSpeedParams(state).length_m).toBe(1.0)
  })

  it('parses mass_per_m', () => {
    expect(buildCritSpeedParams(state).mass_per_m).toBeCloseTo(7.85)
  })

  it('parses E', () => {
    expect(buildCritSpeedParams(state).E).toBe(200e9)
  })

  it('parses I', () => {
    expect(buildCritSpeedParams(state).I).toBeCloseTo(1e-7)
  })

  it('passes supports through', () => {
    expect(buildCritSpeedParams(state).supports).toBe('simply-supported')
  })
})

// ---------------------------------------------------------------------------
// 4. Source structure
// ---------------------------------------------------------------------------

describe('ShaftStressPanel — source structure', () => {
  it('exports a default ShaftStressPanel function', () => {
    expect(SRC).toMatch(/export default function ShaftStressPanel/)
  })

  it('has shaft-stress-panel data-testid', () => {
    expect(SRC).toMatch(/data-testid="shaft-stress-panel"/)
  })

  it('has shaft-panel-toggle data-testid', () => {
    expect(SRC).toMatch(/data-testid="shaft-panel-toggle"/)
  })

  it('has shaft-panel-body data-testid', () => {
    expect(SRC).toMatch(/data-testid="shaft-panel-body"/)
  })

  it('has mode tab template for stress/critical', () => {
    expect(SRC).toMatch(/data-testid=\{`shaft-mode-\$\{k\}`\}/)
  })

  it('has stress mode section testid', () => {
    expect(SRC).toMatch(/data-testid="shaft-stress-mode"/)
  })

  it('has critspeed mode section testid', () => {
    expect(SRC).toMatch(/data-testid="shaft-critspeed-mode"/)
  })

  it('has shaft-stress-run button', () => {
    expect(SRC).toMatch(/shaft-stress-run/)
  })

  it('has shaft-critspeed-run button', () => {
    expect(SRC).toMatch(/shaft-critspeed-run/)
  })

  it('has input for bending moment M', () => {
    expect(SRC).toMatch(/sd-M/)
  })

  it('has input for torsion T', () => {
    expect(SRC).toMatch(/sd-T/)
  })

  it('has input for shaft length', () => {
    expect(SRC).toMatch(/cs-length/)
  })
})

// ---------------------------------------------------------------------------
// 5. api.callTool usage
// ---------------------------------------------------------------------------

describe('ShaftStressPanel — api.callTool', () => {
  it('calls api.callTool', () => {
    expect(SRC).toMatch(/api\.callTool/)
  })

  it('invokes shaft_diameter tool', () => {
    expect(SRC).toMatch(/['"]shaft_diameter['"]/)
  })

  it('invokes shaft_critical_speed tool', () => {
    expect(SRC).toMatch(/['"]shaft_critical_speed['"]/)
  })
})

// ---------------------------------------------------------------------------
// 6. Smoke render
// ---------------------------------------------------------------------------

describe('ShaftStressPanel — renderToStaticMarkup', () => {
  it('renders without crashing (collapsed)', () => {
    vi.mock('../../../lib/api.js', () => ({ api: { callTool: vi.fn() } }))
    const html = renderToStaticMarkup(<ShaftStressPanel />)
    expect(html).toContain('shaft-stress-panel')
  })
})
