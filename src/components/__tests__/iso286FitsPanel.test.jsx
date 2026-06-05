/**
 * iso286FitsPanel.test.jsx
 *
 * Source-level assertions + pure-helper unit tests for Iso286FitsPanel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 *
 * Coverage:
 *  1. fmtNum helper
 *  2. fitTypeClass — classifies fit type strings
 *  3. buildFitParams — maps form state to api params
 *  4. buildPreferFitParams — maps form state to api params
 *  5. buildPressParams — maps form state to api params
 *  6. Source structure — data-testid markers
 *  7. api.callTool invocations (source scan)
 *  8. renderToStaticMarkup smoke test
 */

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import Iso286FitsPanel, {
  fmtNum,
  fitTypeClass,
  buildFitParams,
  buildPreferFitParams,
  buildPressParams,
} from '../Iso286FitsPanel.jsx'

const SRC = readFileSync(
  resolve(__dirname, '../Iso286FitsPanel.jsx'),
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

  it('formats to 3dp by default', () => {
    expect(fmtNum(12.3456)).toBe('12.346')
  })

  it('respects custom dp', () => {
    expect(fmtNum(12.3456, 1)).toBe('12.3')
  })

  it('formats zero correctly', () => {
    expect(fmtNum(0)).toBe('0.000')
  })
})

// ---------------------------------------------------------------------------
// 2. fitTypeClass
// ---------------------------------------------------------------------------

describe('fitTypeClass', () => {
  it('returns emerald for clearance', () => {
    expect(fitTypeClass('clearance')).toMatch(/emerald/)
  })

  it('returns amber for transition', () => {
    expect(fitTypeClass('transition')).toMatch(/amber/)
  })

  it('returns red for interference', () => {
    expect(fitTypeClass('interference')).toMatch(/red/)
  })

  it('returns neutral for unknown', () => {
    const cls = fitTypeClass('unknown')
    expect(cls).not.toMatch(/emerald/)
    expect(cls).not.toMatch(/red/)
  })

  it('returns neutral for null', () => {
    const cls = fitTypeClass(null)
    expect(cls).not.toMatch(/emerald/)
  })
})

// ---------------------------------------------------------------------------
// 3. buildFitParams
// ---------------------------------------------------------------------------

describe('buildFitParams', () => {
  const state = {
    nominal_mm: '50', hole_code: 'H', hole_grade: 'IT7',
    shaft_code: 'g', shaft_grade: 'IT6',
  }

  it('parses nominal_mm', () => {
    expect(buildFitParams(state).nominal_mm).toBe(50)
  })

  it('passes hole_code', () => {
    expect(buildFitParams(state).hole_code).toBe('H')
  })

  it('passes hole_grade', () => {
    expect(buildFitParams(state).hole_grade).toBe('IT7')
  })

  it('passes shaft_code', () => {
    expect(buildFitParams(state).shaft_code).toBe('g')
  })

  it('passes shaft_grade', () => {
    expect(buildFitParams(state).shaft_grade).toBe('IT6')
  })

  it('falls back to 0 for empty nominal_mm', () => {
    expect(buildFitParams({ ...state, nominal_mm: '' }).nominal_mm).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// 4. buildPreferFitParams
// ---------------------------------------------------------------------------

describe('buildPreferFitParams', () => {
  const state = { nominal_mm: '50', fit_name: 'H7/g6' }

  it('parses nominal_mm', () => {
    expect(buildPreferFitParams(state).nominal_mm).toBe(50)
  })

  it('passes fit_name', () => {
    expect(buildPreferFitParams(state).fit_name).toBe('H7/g6')
  })
})

// ---------------------------------------------------------------------------
// 5. buildPressParams
// ---------------------------------------------------------------------------

describe('buildPressParams', () => {
  const state = {
    nominal_mm: '50', interference_mm: '0.05',
    hub_outer_mm: '100', E_shaft_GPa: '200',
    E_hub_GPa: '200', nu_shaft: '0.3',
    nu_hub: '0.3', mu: '0.12',
    length_mm: '80', yield_shaft_MPa: '350',
    yield_hub_MPa: '350',
  }

  it('parses interference_mm', () => {
    expect(buildPressParams(state).interference_mm).toBeCloseTo(0.05)
  })

  it('parses hub_outer_mm', () => {
    expect(buildPressParams(state).hub_outer_mm).toBe(100)
  })

  it('parses E_shaft_GPa', () => {
    expect(buildPressParams(state).E_shaft_GPa).toBe(200)
  })

  it('parses mu', () => {
    expect(buildPressParams(state).mu).toBeCloseTo(0.12)
  })

  it('parses length_mm', () => {
    expect(buildPressParams(state).length_mm).toBe(80)
  })
})

// ---------------------------------------------------------------------------
// 6. Source structure
// ---------------------------------------------------------------------------

describe('Iso286FitsPanel — source structure', () => {
  it('exports a default Iso286FitsPanel function', () => {
    expect(SRC).toMatch(/export default function Iso286FitsPanel/)
  })

  it('has iso286-fits-panel data-testid', () => {
    expect(SRC).toMatch(/data-testid="iso286-fits-panel"/)
  })

  it('has iso286-panel-toggle data-testid', () => {
    expect(SRC).toMatch(/data-testid="iso286-panel-toggle"/)
  })

  it('has iso286-panel-body data-testid', () => {
    expect(SRC).toMatch(/data-testid="iso286-panel-body"/)
  })

  it('has mode tab template for fit/prefer/press', () => {
    expect(SRC).toMatch(/data-testid=\{`iso286-mode-\$\{k\}`\}/)
  })

  it('has fit mode section testid', () => {
    expect(SRC).toMatch(/data-testid="iso286-fit-mode"/)
  })

  it('has prefer mode section testid', () => {
    expect(SRC).toMatch(/data-testid="iso286-prefer-mode"/)
  })

  it('has press mode section testid', () => {
    expect(SRC).toMatch(/data-testid="iso286-press-mode"/)
  })

  it('has iso286-fit-run button', () => {
    expect(SRC).toMatch(/iso286-fit-run/)
  })

  it('has iso286-prefer-run button', () => {
    expect(SRC).toMatch(/iso286-prefer-run/)
  })

  it('has iso286-press-run button', () => {
    expect(SRC).toMatch(/iso286-press-run/)
  })

  it('has fit-type-badge', () => {
    expect(SRC).toMatch(/fit-type-badge/)
  })

  it('mentions ISO 286 in the header', () => {
    expect(SRC).toMatch(/ISO 286/)
  })

  it('mentions Lamé press-fit analysis', () => {
    expect(SRC).toMatch(/Lam/)  // 'Lamé' or 'Lame'
  })
})

// ---------------------------------------------------------------------------
// 7. api.callTool
// ---------------------------------------------------------------------------

describe('Iso286FitsPanel — api.callTool', () => {
  it('calls api.callTool', () => {
    expect(SRC).toMatch(/api\.callTool/)
  })

  it('invokes iso286_fit_analysis', () => {
    expect(SRC).toMatch(/['"]iso286_fit_analysis['"]/)
  })

  it('invokes iso286_preferred_fits', () => {
    expect(SRC).toMatch(/['"]iso286_preferred_fits['"]/)
  })

  it('invokes iso286_press_fit', () => {
    expect(SRC).toMatch(/['"]iso286_press_fit['"]/)
  })
})

// ---------------------------------------------------------------------------
// 8. Smoke render
// ---------------------------------------------------------------------------

describe('Iso286FitsPanel — renderToStaticMarkup', () => {
  it('renders without crashing (collapsed)', () => {
    vi.mock('../../../lib/api.js', () => ({ api: { callTool: vi.fn() } }))
    const html = renderToStaticMarkup(<Iso286FitsPanel />)
    expect(html).toContain('iso286-fits-panel')
  })
})
