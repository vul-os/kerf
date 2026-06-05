/**
 * bearingLifePanel.test.jsx
 *
 * Source-level assertions + pure-helper unit tests for BearingLifePanel.
 * Uses renderToStaticMarkup (no @testing-library/react) — same pattern as
 * CMMInspectionPanel.test.jsx and clashPanel.test.jsx.
 *
 * Coverage:
 *  1. fmtNum helper — null / NaN / finite values / decimal places
 *  2. resultTagClass — ok/false/null
 *  3. buildSelectParams — maps form state to API params
 *  4. buildLifeParams   — maps form state to API params
 *  5. buildIso16281Params — maps form state to API params
 *  6. BearingLifePanel source structure — data-testid markers
 *  7. BearingLifePanel renders without crashing (renderToStaticMarkup)
 *  8. api.callTool is invoked (source scan)
 *  9. Three mode tabs present (select / life / iso16281)
 */

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import BearingLifePanel, {
  fmtNum,
  resultTagClass,
  buildSelectParams,
  buildLifeParams,
  buildIso16281Params,
} from '../BearingLifePanel.jsx'

const SRC = readFileSync(
  resolve(__dirname, '../BearingLifePanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// 1. fmtNum
// ---------------------------------------------------------------------------

describe('fmtNum', () => {
  it('returns — for null', () => {
    expect(fmtNum(null)).toBe('—')
  })

  it('returns — for undefined', () => {
    expect(fmtNum(undefined)).toBe('—')
  })

  it('returns — for NaN', () => {
    expect(fmtNum(NaN)).toBe('—')
  })

  it('returns — for Infinity', () => {
    expect(fmtNum(Infinity)).toBe('—')
  })

  it('formats a finite number to 2 dp by default', () => {
    expect(fmtNum(123.456)).toBe('123.46')
  })

  it('respects custom decimal places', () => {
    expect(fmtNum(3.14159, 4)).toBe('3.1416')
  })

  it('formats zero correctly', () => {
    expect(fmtNum(0)).toBe('0.00')
  })

  it('formats negative correctly', () => {
    expect(fmtNum(-5.5, 1)).toBe('-5.5')
  })
})

// ---------------------------------------------------------------------------
// 2. resultTagClass
// ---------------------------------------------------------------------------

describe('resultTagClass', () => {
  it('returns emerald class for true', () => {
    expect(resultTagClass(true)).toMatch(/emerald/)
  })

  it('returns red class for false', () => {
    expect(resultTagClass(false)).toMatch(/red/)
  })

  it('returns neutral for null', () => {
    const cls = resultTagClass(null)
    expect(cls).not.toMatch(/emerald/)
    expect(cls).not.toMatch(/red/)
  })
})

// ---------------------------------------------------------------------------
// 3. buildSelectParams
// ---------------------------------------------------------------------------

describe('buildSelectParams', () => {
  const state = {
    series: '6200', Fr: '5000', Fa: '1000', n_rpm: '1450',
    Lh_min: '20000', bearing_type: 'ball', a1: '1.0', a23: '1.0',
  }

  it('maps series correctly', () => {
    expect(buildSelectParams(state).series).toBe('6200')
  })

  it('parses Fr as float', () => {
    expect(buildSelectParams(state).Fr).toBe(5000)
  })

  it('parses Fa as float', () => {
    expect(buildSelectParams(state).Fa).toBe(1000)
  })

  it('parses Lh_min as float', () => {
    expect(buildSelectParams(state).Lh_min).toBe(20000)
  })

  it('maps bearing_type', () => {
    expect(buildSelectParams(state).bearing_type).toBe('ball')
  })

  it('falls back to 0 when Fr is empty', () => {
    expect(buildSelectParams({ ...state, Fr: '' }).Fr).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// 4. buildLifeParams
// ---------------------------------------------------------------------------

describe('buildLifeParams', () => {
  const state = {
    C: '29100', P: '5000', n_rpm: '1450',
    bearing_type: 'ball', a1: '1.0', a23: '1.0',
  }

  it('parses C', () => {
    expect(buildLifeParams(state).C).toBe(29100)
  })

  it('parses P', () => {
    expect(buildLifeParams(state).P).toBe(5000)
  })

  it('parses n_rpm', () => {
    expect(buildLifeParams(state).n_rpm).toBe(1450)
  })

  it('passes bearing_type through', () => {
    expect(buildLifeParams(state).bearing_type).toBe('ball')
  })
})

// ---------------------------------------------------------------------------
// 5. buildIso16281Params
// ---------------------------------------------------------------------------

describe('buildIso16281Params', () => {
  const state = {
    C: '29100', P: '5000', n_rpm: '1450',
    kappa: '1.5', eC: '0.3', Cu_N: '600',
    bearing_type: 'ball', a1: '1.0', fatigue_limited: false,
  }

  it('parses kappa', () => {
    expect(buildIso16281Params(state).kappa).toBeCloseTo(1.5)
  })

  it('parses eC', () => {
    expect(buildIso16281Params(state).eC).toBeCloseTo(0.3)
  })

  it('parses Cu_N', () => {
    expect(buildIso16281Params(state).Cu_N).toBe(600)
  })

  it('passes fatigue_limited through', () => {
    expect(buildIso16281Params(state).fatigue_limited).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 6. Source structure
// ---------------------------------------------------------------------------

describe('BearingLifePanel — source structure', () => {
  it('exports a default BearingLifePanel function', () => {
    expect(SRC).toMatch(/export default function BearingLifePanel/)
  })

  it('has bearing-life-panel data-testid', () => {
    expect(SRC).toMatch(/data-testid="bearing-life-panel"/)
  })

  it('has bearing-panel-toggle data-testid', () => {
    expect(SRC).toMatch(/data-testid="bearing-panel-toggle"/)
  })

  it('has bearing-panel-body data-testid', () => {
    expect(SRC).toMatch(/data-testid="bearing-panel-body"/)
  })

  it('has mode tab template for select/life/iso16281', () => {
    // Mode tabs use a dynamic data-testid={`bearing-mode-${k}`}
    expect(SRC).toMatch(/data-testid=\{`bearing-mode-\$\{k\}`\}/)
  })

  it('has select mode section testid', () => {
    expect(SRC).toMatch(/data-testid="bearing-select-mode"/)
  })

  it('has life mode section testid', () => {
    expect(SRC).toMatch(/data-testid="bearing-life-mode"/)
  })

  it('has iso16281 mode section testid', () => {
    expect(SRC).toMatch(/data-testid="bearing-iso16281-mode"/)
  })

  it('renders select bearing run button', () => {
    expect(SRC).toMatch(/bearing-select-run/)
  })

  it('renders life run button', () => {
    expect(SRC).toMatch(/bearing-life-run/)
  })

  it('renders iso16281 run button', () => {
    expect(SRC).toMatch(/bearing-iso16281-run/)
  })
})

// ---------------------------------------------------------------------------
// 7. api.callTool invocation
// ---------------------------------------------------------------------------

describe('BearingLifePanel — api.callTool usage', () => {
  it('calls api.callTool', () => {
    expect(SRC).toMatch(/api\.callTool/)
  })

  it('calls bearing_select tool', () => {
    expect(SRC).toMatch(/['"]bearing_select['"]/)
  })

  it('calls bearing_adjusted_life tool', () => {
    expect(SRC).toMatch(/['"]bearing_adjusted_life['"]/)
  })

  it('calls bearing_modified_reference_life tool', () => {
    expect(SRC).toMatch(/['"]bearing_modified_reference_life['"]/)
  })
})

// ---------------------------------------------------------------------------
// 8. renderToStaticMarkup (closed/collapsed state — no api calls)
// ---------------------------------------------------------------------------

describe('BearingLifePanel — renderToStaticMarkup', () => {
  it('renders without crashing (collapsed)', () => {
    // In collapsed mode, only the header row renders — no api calls
    vi.mock('../../../lib/api.js', () => ({ api: { callTool: vi.fn() } }))
    const html = renderToStaticMarkup(<BearingLifePanel />)
    expect(html).toContain('bearing-life-panel')
    expect(html).toContain('bearing-panel-toggle')
  })
})
