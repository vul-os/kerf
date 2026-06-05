/**
 * gearRatingPanel.test.jsx
 *
 * Source-level assertions + pure-helper unit tests for GearRatingPanel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 *
 * Coverage:
 *  1. fmtNum helper
 *  2. buildPowerParams — maps form state correctly
 *  3. buildBendingParams — maps form state correctly
 *  4. buildServiceLifeParams — maps form state correctly
 *  5. Source structure — data-testid markers
 *  6. api.callTool invocations (source scan)
 *  7. renderToStaticMarkup smoke test
 */

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import GearRatingPanel, {
  fmtNum,
  buildPowerParams,
  buildBendingParams,
  buildServiceLifeParams,
} from '../GearRatingPanel.jsx'

const SRC = readFileSync(
  resolve(__dirname, '../GearRatingPanel.jsx'),
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
})

// ---------------------------------------------------------------------------
// 2. buildPowerParams
// ---------------------------------------------------------------------------

describe('buildPowerParams', () => {
  const state = {
    S_t: '55000', S_c: '170000', Cp: '2300',
    b: '1.5', m_or_Pd: '8', d_p: '3.0',
    N_p: '20', N_g: '60', psi_deg: '0',
    n_rpm: '1750', metric: 'false',
    Ko: '1.0', Ks: '1.0', Km: '1.3', KB: '1.0',
    Qv: '6', K_T: '1.0', K_R: '1.0',
    pressure_angle_deg: '20',
  }

  it('parses S_t', () => {
    expect(buildPowerParams(state).S_t).toBe(55000)
  })

  it('parses N_p as integer', () => {
    expect(buildPowerParams(state).N_p).toBe(20)
  })

  it('parses N_g as integer', () => {
    expect(buildPowerParams(state).N_g).toBe(60)
  })

  it('parses helix angle', () => {
    expect(buildPowerParams(state).psi_deg).toBe(0)
  })

  it('metric=false resolves to false boolean', () => {
    expect(buildPowerParams(state).metric).toBe(false)
  })

  it('metric=true resolves to true boolean', () => {
    expect(buildPowerParams({ ...state, metric: 'true' }).metric).toBe(true)
  })

  it('parses Qv', () => {
    expect(buildPowerParams(state).Qv).toBe(6)
  })

  it('falls back to 0 for empty S_t', () => {
    expect(buildPowerParams({ ...state, S_t: '' }).S_t).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// 3. buildBendingParams
// ---------------------------------------------------------------------------

describe('buildBendingParams', () => {
  const state = {
    Wt: '200', Ko: '1.0', Kv: '1.2', Ks: '1.0',
    Km: '1.3', KB: '1.0', b: '1.5', m_or_Pd: '8',
    J: '0.36', metric: 'false',
  }

  it('parses Wt', () => {
    expect(buildBendingParams(state).Wt).toBe(200)
  })

  it('parses J', () => {
    expect(buildBendingParams(state).J).toBeCloseTo(0.36)
  })

  it('parses Kv', () => {
    expect(buildBendingParams(state).Kv).toBeCloseTo(1.2)
  })
})

// ---------------------------------------------------------------------------
// 4. buildServiceLifeParams
// ---------------------------------------------------------------------------

describe('buildServiceLifeParams', () => {
  const state = { N_cycles: '1e7', hardness_HB: '200', gear_type: 'spur' }

  it('parses N_cycles', () => {
    expect(buildServiceLifeParams(state).N_cycles).toBe(1e7)
  })

  it('parses hardness_HB', () => {
    expect(buildServiceLifeParams(state).hardness_HB).toBe(200)
  })

  it('passes gear_type through', () => {
    expect(buildServiceLifeParams(state).gear_type).toBe('spur')
  })
})

// ---------------------------------------------------------------------------
// 5. Source structure
// ---------------------------------------------------------------------------

describe('GearRatingPanel — source structure', () => {
  it('exports a default GearRatingPanel function', () => {
    expect(SRC).toMatch(/export default function GearRatingPanel/)
  })

  it('has gear-rating-panel data-testid', () => {
    expect(SRC).toMatch(/data-testid="gear-rating-panel"/)
  })

  it('has gear-panel-toggle data-testid', () => {
    expect(SRC).toMatch(/data-testid="gear-panel-toggle"/)
  })

  it('has gear-panel-body data-testid', () => {
    expect(SRC).toMatch(/data-testid="gear-panel-body"/)
  })

  it('has mode tab template for power/life', () => {
    expect(SRC).toMatch(/data-testid=\{`gear-mode-\$\{k\}`\}/)
  })

  it('has power mode section testid', () => {
    expect(SRC).toMatch(/data-testid="gear-power-mode"/)
  })

  it('has life mode section testid', () => {
    expect(SRC).toMatch(/data-testid="gear-life-mode"/)
  })

  it('has gear-power-run button', () => {
    expect(SRC).toMatch(/gear-power-run/)
  })

  it('has gear-life-run button', () => {
    expect(SRC).toMatch(/gear-life-run/)
  })

  it('mentions AGMA 2001 in header label', () => {
    expect(SRC).toMatch(/AGMA 2001/)
  })

  it('has SF and SH safety factor display', () => {
    expect(SRC).toMatch(/SF.*bending|bending.*SF/)
    expect(SRC).toMatch(/SH.*contact|contact.*SH/)
  })

  it('has SafetyBadge component', () => {
    expect(SRC).toMatch(/SafetyBadge/)
  })
})

// ---------------------------------------------------------------------------
// 6. api.callTool
// ---------------------------------------------------------------------------

describe('GearRatingPanel — api.callTool', () => {
  it('calls api.callTool', () => {
    expect(SRC).toMatch(/api\.callTool/)
  })

  it('invokes agma_power_rating', () => {
    expect(SRC).toMatch(/['"]agma_power_rating['"]/)
  })

  it('invokes agma_service_life', () => {
    expect(SRC).toMatch(/['"]agma_service_life['"]/)
  })
})

// ---------------------------------------------------------------------------
// 7. Smoke render
// ---------------------------------------------------------------------------

describe('GearRatingPanel — renderToStaticMarkup', () => {
  it('renders without crashing (collapsed)', () => {
    vi.mock('../../../lib/api.js', () => ({ api: { callTool: vi.fn() } }))
    const html = renderToStaticMarkup(<GearRatingPanel />)
    expect(html).toContain('gear-rating-panel')
  })
})
