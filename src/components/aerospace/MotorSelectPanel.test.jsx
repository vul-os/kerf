/**
 * MotorSelectPanel.test.jsx — Vitest assertions for MotorSelectPanel.
 *
 * Strategy: render to static markup via react-dom/server (SSR-compatible).
 * Tests cover:
 *  1. Renders without crash in default/empty state.
 *  2. Shows motor list when motors prop provided.
 *  3. Shows motor class badges with correct classes.
 *  4. Shows motor detail panel when selectedMotor provided.
 *  5. Thrust curve chart renders when thrust_curve data present.
 *  6. Eng paste input visible when toggled (SSR default: hidden).
 *  7. Filter bar renders class options.
 *  8. Loading state renders spinner.
 *  9. Footnote cites NAR/Thrustcurve.
 */

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import MotorSelectPanel from './MotorSelectPanel.jsx'

function render(props = {}) {
  return renderToStaticMarkup(<MotorSelectPanel {...props} />)
}

// Fixture motor list
const MOTORS = [
  { name: 'A8',  manufacturer: 'Estes',    impulse_class: 'A', total_impulse_ns: 2.40,  average_thrust_n: 5.0,   burn_time_s: 0.49, isp_s: 80,  diameter_mm: 18, propellant_mass_g: 3.1  },
  { name: 'G79', manufacturer: 'Aerotech', impulse_class: 'G', total_impulse_ns: 87.5,  average_thrust_n: 83.3,  burn_time_s: 1.05, isp_s: 223, diameter_mm: 29, propellant_mass_g: 40.0 },
  { name: 'K711',manufacturer: 'Cesaroni', impulse_class: 'K', total_impulse_ns: 1298.0, average_thrust_n: 763.5, burn_time_s: 1.70, isp_s: 201, diameter_mm: 75, propellant_mass_g: 660.0 },
]

const MOTOR_DETAIL = {
  ...MOTORS[1],
  length_mm: 124,
  total_mass_g: 72,
  delays_s: [10],
  n_thrust_points: 9,
  thrust_curve: [
    { time_s: 0.00, thrust_n:   0 },
    { time_s: 0.06, thrust_n: 110 },
    { time_s: 0.50, thrust_n:  80 },
    { time_s: 1.05, thrust_n:   0 },
  ],
}

// ── 1. Default renders ────────────────────────────────────────────────────────

describe('MotorSelectPanel — default state', () => {
  it('renders without throwing', () => {
    expect(() => render()).not.toThrow()
  })

  it('renders title "Motor Database"', () => {
    const html = render()
    expect(html).toContain('Motor Database')
  })

  it('shows Thrustcurve subtitle', () => {
    const html = render()
    expect(html).toContain('Thrustcurve')
  })

  it('shows empty state text when no motors', () => {
    const html = render()
    expect(html).toContain('No motors loaded')
  })
})

// ── 2. Motor list ─────────────────────────────────────────────────────────────

describe('MotorSelectPanel — with motors prop', () => {
  it('does not show empty state when motors provided', () => {
    const html = render({ motors: MOTORS })
    expect(html).not.toContain('No motors loaded')
  })

  it('shows motor names in table', () => {
    const html = render({ motors: MOTORS })
    expect(html).toContain('A8')
    expect(html).toContain('G79')
    expect(html).toContain('K711')
  })

  it('shows manufacturer names', () => {
    const html = render({ motors: MOTORS })
    expect(html).toContain('Estes')
    expect(html).toContain('Aerotech')
    expect(html).toContain('Cesaroni')
  })

  it('shows table header columns', () => {
    const html = render({ motors: MOTORS })
    expect(html).toContain('Impulse')
    expect(html).toContain('Isp')
    expect(html).toContain('Burn')
  })
})

// ── 3. Impulse class badges ───────────────────────────────────────────────────

describe('MotorSelectPanel — impulse class badges', () => {
  it('shows class A badge for A8', () => {
    const html = render({ motors: MOTORS })
    // The class badge shows the class letter
    expect(html).toContain('>A<') // in badge span
  })

  it('shows class G badge for G79', () => {
    const html = render({ motors: MOTORS })
    expect(html).toContain('>G<')
  })

  it('shows class K badge for K711', () => {
    const html = render({ motors: MOTORS })
    expect(html).toContain('>K<')
  })
})

// ── 4. Motor detail panel ─────────────────────────────────────────────────────

describe('MotorSelectPanel — selectedMotor detail', () => {
  it('renders motor detail when selectedMotor provided', () => {
    const html = render({ motors: MOTORS, selectedMotor: MOTOR_DETAIL })
    expect(html).toContain('Manufacturer')
    expect(html).toContain('Aerotech')
  })

  it('shows total impulse in detail panel', () => {
    const html = render({ motors: MOTORS, selectedMotor: MOTOR_DETAIL })
    expect(html).toContain('Total impulse')
    expect(html).toContain('87.5')
  })

  it('shows Isp in detail panel', () => {
    const html = render({ motors: MOTORS, selectedMotor: MOTOR_DETAIL })
    expect(html).toContain('Isp')
    expect(html).toContain('223')
  })

  it('shows diameter and length', () => {
    const html = render({ motors: MOTORS, selectedMotor: MOTOR_DETAIL })
    expect(html).toContain('Diameter')
    expect(html).toContain('29')
    expect(html).toContain('Length')
    expect(html).toContain('124')
  })
})

// ── 5. Thrust curve chart ─────────────────────────────────────────────────────

describe('MotorSelectPanel — thrust curve chart', () => {
  it('renders an SVG with path when thrust_curve data is present', () => {
    const html = render({ selectedMotor: MOTOR_DETAIL })
    expect(html).toContain('<svg')
    expect(html).toContain('<path')
  })

  it('shows "Thrust curve" label', () => {
    const html = render({ selectedMotor: MOTOR_DETAIL })
    expect(html).toContain('Thrust curve')
  })
})

// ── 6. Filter bar ─────────────────────────────────────────────────────────────

describe('MotorSelectPanel — filter bar', () => {
  it('renders class select dropdown', () => {
    const html = render()
    expect(html).toContain('All classes')
  })

  it('renders class options A through M', () => {
    const html = render()
    // Options include class letters
    expect(html).toContain('>G<')
    expect(html).toContain('>K<')
  })

  it('renders manufacturer filter input', () => {
    const html = render()
    expect(html).toContain('Manufacturer')
  })
})

// ── 7. Loading state ──────────────────────────────────────────────────────────

describe('MotorSelectPanel — loading', () => {
  it('shows loading text when loading=true', () => {
    const html = render({ loading: true })
    expect(html).toContain('Loading motors')
  })

  it('hides motor table while loading', () => {
    const html = render({ loading: true, motors: MOTORS })
    // Motor table should not render while loading
    expect(html).not.toContain('<table')
  })
})

// ── 8. Eng parse toggle (default hidden) ──────────────────────────────────────

describe('MotorSelectPanel — eng paste', () => {
  it('shows Parse .eng file button', () => {
    const html = render()
    expect(html).toContain('Parse .eng file')
  })
})

// ── 9. Footnote ───────────────────────────────────────────────────────────────

describe('MotorSelectPanel — footnote', () => {
  it('cites NAR in footnote', () => {
    const html = render()
    expect(html).toContain('NAR')
  })

  it('cites Thrustcurve in footnote', () => {
    const html = render()
    expect(html).toContain('Thrustcurve')
  })

  it('cites Sutton Biblarz in footnote', () => {
    const html = render()
    expect(html).toContain('Sutton')
  })
})
