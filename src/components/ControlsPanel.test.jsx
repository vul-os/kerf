/**
 * ControlsPanel.test.jsx
 *
 * Vitest tests for ControlsPanel — Bode / Nyquist / step-response SVG charts.
 * Uses renderToStaticMarkup (react-dom/server) to avoid jsdom requirement.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ControlsPanel from './ControlsPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const BODE = {
  omega: [0.1, 1.0, 10.0, 100.0],
  mag_db: [20.0, 0.0, -20.0, -40.0],
  phase_deg: [-90.0, -90.0, -90.0, -90.0],
  gain_margin_db: 12.5,
  phase_margin_deg: 45.2,
  omega_gc: 1.0,
  omega_pc: 10.0,
}

const NYQUIST = {
  omega: [0.1, 1.0, 10.0],
  real_g: [0.9, 0.5, 0.1],
  imag_g: [-0.1, -0.5, -0.1],
  mag: [0.91, 0.71, 0.14],
  phase_deg: [-10.0, -45.0, -80.0],
  encirclements_approx: 0,
}

const STEP = {
  t: [0, 1, 2, 3, 4, 5],
  y: [0, 0.63, 0.86, 0.95, 0.98, 0.99],
  steady_state: 1.0,
  response_type: 'step',
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ControlsPanel', () => {
  it('renders without crashing with all three data sets', () => {
    expect(() =>
      renderToStaticMarkup(<ControlsPanel bode={BODE} nyquist={NYQUIST} step={STEP} />)
    ).not.toThrow()
  })

  it('renders a bode tab button', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toMatch(/Bode/)
  })

  it('renders a nyquist tab button', () => {
    const html = renderToStaticMarkup(<ControlsPanel nyquist={NYQUIST} />)
    expect(html).toMatch(/Nyquist/)
  })

  it('renders a step response tab button', () => {
    const html = renderToStaticMarkup(<ControlsPanel step={STEP} />)
    expect(html).toMatch(/Step Response/)
  })

  it('renders an SVG element for bode chart', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toMatch(/<svg\b/)
  })

  it('renders role="img" on bode SVG', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toMatch(/role="img"/)
  })

  it('renders Bode label in chart', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toContain('Bode')
  })

  it('renders gain margin value in margins summary', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toContain('12.5')
  })

  it('renders phase margin value in margins summary', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toContain('45.2')
  })

  it('renders polyline for Bode magnitude curve', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toMatch(/<polyline\b/)
  })

  it('renders width/height on first SVG', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} width={640} height={250} />)
    expect(html).toMatch(/width="640"/)
    expect(html).toMatch(/height="250"/)
  })

  it('renders empty state when bode is null', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={null} />)
    expect(html).toContain('No Bode data')
  })

  it('accepts a custom className', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} className="my-controls" />)
    expect(html).toContain('my-controls')
  })

  it('renders GM label on Bode magnitude chart', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toMatch(/GM/)
  })

  it('renders PM label on Bode phase chart', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toMatch(/PM/)
  })

  it('renders dB axis label', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toContain('dB')
  })

  it('renders rad/s axis label', () => {
    const html = renderToStaticMarkup(<ControlsPanel bode={BODE} />)
    expect(html).toMatch(/rad/)
  })
})
