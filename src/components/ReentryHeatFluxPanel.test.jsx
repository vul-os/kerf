// ReentryHeatFluxPanel.test.jsx — vitest smoke tests for the re-entry heat flux panel.

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ReentryHeatFluxPanel from './ReentryHeatFluxPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const POINT_RESULT = {
  ok: true,
  altitude_km: 70,
  velocity_m_s: 7800,
  density_kg_m3: 8.28e-5,
  q_convective_W_m2: 1.17e9,
  q_radiative_W_m2: 0.0,
  q_total_W_m2: 1.17e9,
  q_total_W_cm2: 117000,
  nose_radius_m: 0.2,
  include_radiative: true,
  method: 'Sutton-Graves convective (NASA TR R-376) + Tauber-Sutton radiative',
  note: 'Radiative flux estimate valid above ~10 km/s.',
}

const TRAJ_RESULT = {
  ok: true,
  n_points: 5,
  nose_radius_m: 0.2,
  include_radiative: true,
  trajectory: [
    { altitude_km: 80, velocity_m_s: 5000, density_kg_m3: 1.8e-5,
      q_convective_W_m2: 1.5e7, q_radiative_W_m2: 0, q_total_W_m2: 1.5e7, q_total_W_cm2: 1500 },
    { altitude_km: 70, velocity_m_s: 7000, density_kg_m3: 8.28e-5,
      q_convective_W_m2: 5e8, q_radiative_W_m2: 0, q_total_W_m2: 5e8, q_total_W_cm2: 50000 },
    { altitude_km: 60, velocity_m_s: 8000, density_kg_m3: 3e-4,
      q_convective_W_m2: 2e9, q_radiative_W_m2: 0, q_total_W_m2: 2e9, q_total_W_cm2: 200000 },
    { altitude_km: 50, velocity_m_s: 7500, density_kg_m3: 1e-3,
      q_convective_W_m2: 8e8, q_radiative_W_m2: 0, q_total_W_m2: 8e8, q_total_W_cm2: 80000 },
    { altitude_km: 40, velocity_m_s: 5000, density_kg_m3: 4e-3,
      q_convective_W_m2: 1e8, q_radiative_W_m2: 0, q_total_W_m2: 1e8, q_total_W_cm2: 10000 },
  ],
}

// ---------------------------------------------------------------------------
// Tests — point mode
// ---------------------------------------------------------------------------

describe('ReentryHeatFluxPanel — point mode', () => {
  it('renders without crashing', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={POINT_RESULT} loading={false} error={null} />)
    expect(html).toBeTruthy()
  })

  it('shows altitude', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={POINT_RESULT} loading={false} error={null} />)
    expect(html).toContain('70')
  })

  it('shows velocity in km/s', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={POINT_RESULT} loading={false} error={null} />)
    expect(html).toContain('7.80')
  })

  it('shows Sutton-Graves in method', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={POINT_RESULT} loading={false} error={null} />)
    expect(html.toLowerCase()).toContain('sutton')
  })

  it('shows nose radius', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={POINT_RESULT} loading={false} error={null} />)
    expect(html).toContain('0.2')
  })
})

// ---------------------------------------------------------------------------
// Tests — trajectory mode
// ---------------------------------------------------------------------------

describe('ReentryHeatFluxPanel — trajectory mode', () => {
  it('renders without crashing', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={TRAJ_RESULT} loading={false} error={null} />)
    expect(html).toBeTruthy()
  })

  it('shows trajectory label', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={TRAJ_RESULT} loading={false} error={null} />)
    expect(html.toLowerCase()).toContain('trajectory')
  })

  it('shows n_points', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={TRAJ_RESULT} loading={false} error={null} />)
    expect(html).toContain('5')
  })

  it('renders an SVG chart', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={TRAJ_RESULT} loading={false} error={null} />)
    expect(html).toContain('<svg')
  })

  it('shows MW/m² unit in peak', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={TRAJ_RESULT} loading={false} error={null} />)
    expect(html).toContain('MW/m')
  })
})

// ---------------------------------------------------------------------------
// Tests — loading / error / null
// ---------------------------------------------------------------------------

describe('ReentryHeatFluxPanel — loading state', () => {
  it('shows loading message', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={null} loading={true} error={null} />)
    expect(html).toContain('heat flux')
  })
})

describe('ReentryHeatFluxPanel — error state', () => {
  it('shows error message', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={null} loading={false} error="Bad inputs" />)
    expect(html).toContain('Bad inputs')
  })
})

describe('ReentryHeatFluxPanel — null result', () => {
  it('renders nothing', () => {
    const html = renderToStaticMarkup(<ReentryHeatFluxPanel result={null} loading={false} error={null} />)
    expect(html).toBe('')
  })
})
