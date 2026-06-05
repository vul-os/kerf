// FlutterPanel.test.jsx — vitest smoke tests for the V-g/V-f flutter panel.

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import FlutterPanel from './FlutterPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FLUTTER_RESULT = {
  ok: true,
  flutter_speed_m_s: 21.3,
  flutter_speed_nd: 2.13,
  flutter_freq_rad_s: 14.8,
  flutter_freq_hz: 2.35,
  velocities_m_s: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25],
  damping_mode0: [-0.15, -0.14, -0.13, -0.12, -0.11, -0.10, -0.09, -0.08, -0.07, -0.06,
                  -0.05, -0.04, -0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04,
                  0.05, 0.06, 0.07, 0.08, 0.09],
  damping_mode1: [-0.20, -0.19, -0.18, -0.17, -0.16, -0.15, -0.14, -0.13, -0.12, -0.11,
                  -0.10, -0.09, -0.08, -0.07, -0.06, -0.05, -0.04, -0.03, -0.02, -0.01,
                  0.00, 0.01, 0.02, 0.03, 0.04],
  freq_mode0_rad_s: [10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9,
                     11, 11.5, 12, 12.5, 13, 13.5, 14, 14.5, 15, 15.5,
                     14.8, 14.7, 14.6, 14.5, 14.4],
  freq_mode1_rad_s: [20, 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9,
                     21, 21.5, 22, 22.5, 23, 23.5, 24, 24.5, 25, 25.5,
                     25.4, 25.3, 25.2, 25.1, 25.0],
  method: 'Theodorsen p-k (Hassig 1971) with Hankel-function C(k)',
  reference: 'Bisplinghoff, Ashley & Halfman (1955)',
}

const NO_FLUTTER_RESULT = {
  ok: true,
  flutter_speed_m_s: null,
  flutter_speed_nd: null,
  flutter_freq_rad_s: null,
  flutter_freq_hz: null,
  velocities_m_s: [1, 2, 3, 4, 5],
  damping_mode0: [-0.1, -0.1, -0.1, -0.1, -0.1],
  damping_mode1: [-0.2, -0.2, -0.2, -0.2, -0.2],
  freq_mode0_rad_s: [10, 10, 10, 10, 10],
  freq_mode1_rad_s: [20, 20, 20, 20, 20],
  method: 'Theodorsen p-k',
  reference: 'Bisplinghoff (1955)',
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FlutterPanel — with flutter speed', () => {
  it('renders without crashing', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={FLUTTER_RESULT} loading={false} error={null} />)
    expect(html).toBeTruthy()
  })

  it('shows flutter speed', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={FLUTTER_RESULT} loading={false} error={null} />)
    expect(html).toContain('21.3')
  })

  it('shows flutter frequency', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={FLUTTER_RESULT} loading={false} error={null} />)
    expect(html).toContain('2.35')
  })

  it('shows non-dimensional flutter speed', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={FLUTTER_RESULT} loading={false} error={null} />)
    expect(html).toContain('2.130')
  })

  it('renders SVG charts', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={FLUTTER_RESULT} loading={false} error={null} />)
    expect(html.match(/<svg/g)?.length).toBeGreaterThanOrEqual(2)
  })

  it('shows method label', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={FLUTTER_RESULT} loading={false} error={null} />)
    expect(html.toLowerCase()).toContain('theodorsen')
  })

  it('shows V-g and V-f labels', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={FLUTTER_RESULT} loading={false} error={null} />)
    expect(html).toContain('V-g')
    expect(html).toContain('V-f')
  })
})

describe('FlutterPanel — no flutter found', () => {
  it('shows Not found when flutter speed is null', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={NO_FLUTTER_RESULT} loading={false} error={null} />)
    expect(html).toContain('Not found')
  })

  it('still renders charts', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={NO_FLUTTER_RESULT} loading={false} error={null} />)
    expect(html).toContain('<svg')
  })
})

describe('FlutterPanel — loading state', () => {
  it('shows loading message', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={null} loading={true} error={null} />)
    expect(html).toContain('flutter')
  })
})

describe('FlutterPanel — error state', () => {
  it('shows error message', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={null} loading={false} error="Computation failed" />)
    expect(html).toContain('Computation failed')
  })
})

describe('FlutterPanel — null result', () => {
  it('returns null for null result', () => {
    const html = renderToStaticMarkup(<FlutterPanel result={null} loading={false} error={null} />)
    expect(html).toBe('')
  })
})
