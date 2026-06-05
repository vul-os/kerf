// SixDOFPanel.test.jsx — vitest smoke tests for the 6-DOF flight dynamics panel.

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SixDOFPanel from './SixDOFPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SIXDOF_RESULT = {
  ok: true,
  n_steps: 200,
  duration_s: 10.0,
  dt_s: 0.05,
  final_state: {
    x_n_m: 950.2,
    y_e_m: 0.0,
    altitude_m: 998.5,
    u_m_s: 99.8,
    v_m_s: 0.0,
    w_m_s: 2.1,
    quaternion: [0.9998, 0.0, 0.018, 0.0],
    p_rad_s: 0.0,
    q_rad_s: 0.0,
    r_rad_s: 0.0,
  },
  final_altitude_m: 998.5,
  final_airspeed_m_s: 99.8,
  final_euler_deg: [0.0, 2.15, 0.0],
  max_altitude_m: 1001.2,
  min_altitude_m: 995.0,
  trajectory_summary: [
    { t_s: 0.0,  x_n_m: 0,    y_e_m: 0, altitude_m: 1000.0, airspeed_m_s: 100.0 },
    { t_s: 0.5,  x_n_m: 50,   y_e_m: 0, altitude_m: 999.8,  airspeed_m_s: 100.0 },
    { t_s: 1.0,  x_n_m: 100,  y_e_m: 0, altitude_m: 999.5,  airspeed_m_s: 100.0 },
    { t_s: 5.0,  x_n_m: 500,  y_e_m: 0, altitude_m: 998.8,  airspeed_m_s: 99.9  },
    { t_s: 10.0, x_n_m: 950,  y_e_m: 0, altitude_m: 998.5,  airspeed_m_s: 99.8  },
  ],
  inputs: { mass_kg: 1000, ixx: 100, iyy: 500, izz: 500, ixz: 0 },
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SixDOFPanel — nominal flight', () => {
  it('renders without crashing', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={SIXDOF_RESULT} loading={false} error={null} />)
    expect(html).toBeTruthy()
  })

  it('shows final altitude', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={SIXDOF_RESULT} loading={false} error={null} />)
    expect(html).toContain('998.5')
  })

  it('shows final airspeed', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={SIXDOF_RESULT} loading={false} error={null} />)
    expect(html).toContain('99.80')
  })

  it('shows Euler angles', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={SIXDOF_RESULT} loading={false} error={null} />)
    // Roll, Pitch, Yaw cards
    expect(html).toContain('Roll')
    expect(html).toContain('Pitch')
    expect(html).toContain('Yaw')
  })

  it('shows pitch angle value', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={SIXDOF_RESULT} loading={false} error={null} />)
    expect(html).toContain('2.15')
  })

  it('renders two SVG charts', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={SIXDOF_RESULT} loading={false} error={null} />)
    const count = (html.match(/<svg/g) || []).length
    expect(count).toBeGreaterThanOrEqual(2)
  })

  it('shows n_steps', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={SIXDOF_RESULT} loading={false} error={null} />)
    expect(html).toContain('200')
  })

  it('shows altitude range', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={SIXDOF_RESULT} loading={false} error={null} />)
    expect(html).toContain('995')
    expect(html).toContain('1001')
  })

  it('shows 6-DOF label', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={SIXDOF_RESULT} loading={false} error={null} />)
    expect(html).toContain('6-DOF')
  })
})

describe('SixDOFPanel — loading state', () => {
  it('shows loading message', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={null} loading={true} error={null} />)
    expect(html).toContain('6-DOF')
  })
})

describe('SixDOFPanel — error state', () => {
  it('shows error message', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={null} loading={false} error="Simulation failed" />)
    expect(html).toContain('Simulation failed')
  })
})

describe('SixDOFPanel — null result', () => {
  it('renders nothing', () => {
    const html = renderToStaticMarkup(<SixDOFPanel result={null} loading={false} error={null} />)
    expect(html).toBe('')
  })
})
