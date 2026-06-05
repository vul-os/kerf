/**
 * SolarPVPanel.test.jsx
 *
 * Vitest tests for SolarPVPanel — PV I-V and P-V curve chart.
 * Uses renderToStaticMarkup (react-dom/server).
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SolarPVPanel from './SolarPVPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures — synthetic I-V data for a 60-cell STC module
// ---------------------------------------------------------------------------

function buildIVCurve() {
  // Simple first-order model: I = Isc * (1 - exp((V - Voc) / Vt))
  const Isc = 9.0, Voc = 36.0, Vt = 2.5
  const curve = []
  for (let i = 0; i <= 50; i++) {
    const v = (Voc * i) / 50
    const current = Math.max(0, Isc * (1 - Math.exp((v - Voc) / Vt)))
    curve.push({ v: +v.toFixed(3), i: +current.toFixed(5), p: +(v * current).toFixed(4) })
  }
  return curve
}

const IV_CURVE = buildIVCurve()

const IV_DATA = {
  iv_curve: IV_CURVE,
  isc_a: 9.0,
  voc_v: 36.0,
  mpp: { p_w: 245.5, v_v: 29.2, i_a: 8.41 },
}

const IV_DATA_SHADED = {
  iv_curve: IV_CURVE.map((d) => ({ ...d, p: d.p * 0.8 })),
  isc_a: 7.2,
  voc_v: 36.0,
  mpp: { p_w: 196.4, v_v: 28.1, i_a: 6.99 },
  power_loss_vs_uniform_pct: 20.0,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SolarPVPanel', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    ).not.toThrow()
  })

  it('renders an SVG element', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toMatch(/<svg\b/)
  })

  it('renders role="img"', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toMatch(/role="img"/)
  })

  it('renders the title', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} title="STC 60-cell" />)
    expect(html).toContain('STC 60-cell')
  })

  it('uses default title when not supplied', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toContain('PV I-V / P-V Curve')
  })

  it('renders I-V polyline', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toMatch(/<polyline\b/)
  })

  it('renders P-V polyline by default (showPV=true)', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    const polylines = (html.match(/<polyline\b/g) || []).length
    expect(polylines).toBeGreaterThanOrEqual(2)   // I-V + P-V
  })

  it('renders only one polyline when showPV=false', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} showPV={false} />)
    const polylines = (html.match(/<polyline\b/g) || []).length
    expect(polylines).toBe(1)
  })

  it('renders width and height on SVG', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} width={640} height={400} />)
    expect(html).toMatch(/width="640"/)
    expect(html).toMatch(/height="400"/)
  })

  it('defaults to 560 x 340', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toMatch(/width="560"/)
    expect(html).toMatch(/height="340"/)
  })

  it('renders empty state when ivData is null', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={null} />)
    expect(html).toContain('No PV data')
    expect(html).not.toMatch(/<svg\b/)
  })

  it('renders empty state when iv_curve is empty', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={{ iv_curve: [] }} />)
    expect(html).toContain('No PV data')
  })

  it('renders MPP power in summary bar', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toContain('245.5')
  })

  it('renders Vmpp in summary bar', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toContain('29.2')
  })

  it('renders Isc label on the chart', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toMatch(/Isc/)
  })

  it('renders Voc label on the chart', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toMatch(/Voc/)
  })

  it('renders shading loss when present', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA_SHADED} />)
    expect(html).toMatch(/Shading loss/)
    expect(html).toContain('20.0')
  })

  it('renders voltage axis label', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toContain('Voltage')
  })

  it('renders current axis label', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toContain('Current')
  })

  it('renders power axis label when showPV', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} showPV />)
    expect(html).toContain('Power')
  })

  it('renders MPP marker circle', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} />)
    expect(html).toMatch(/<circle\b/)
  })

  it('accepts a custom className', () => {
    const html = renderToStaticMarkup(<SolarPVPanel ivData={IV_DATA} className="my-pv" />)
    expect(html).toContain('my-pv')
  })
})
