// SeakeepingRAOPanel.test.jsx — vitest smoke tests for the seakeeping RAO panel.

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SeakeepingRAOPanel from './SeakeepingRAOPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const RAO_RESULT = {
  rao_points: [
    {
      omega_rad_s: 0.3, omega_e_rad_s: 0.3,
      rao_heave_amp: 0.92, rao_heave_phase_deg: -5.2,
      rao_pitch_amp: 0.015, rao_pitch_phase_deg: 12.1,
      rao_roll_amp: 0.008, rao_roll_phase_deg: 8.5,
    },
    {
      omega_rad_s: 0.6, omega_e_rad_s: 0.6,
      rao_heave_amp: 0.87, rao_heave_phase_deg: -18.4,
      rao_pitch_amp: 0.023, rao_pitch_phase_deg: 28.3,
      rao_roll_amp: 0.031, rao_roll_phase_deg: 45.1,
    },
    {
      omega_rad_s: 1.0, omega_e_rad_s: 1.0,
      rao_heave_amp: 1.12, rao_heave_phase_deg: -85.2,
      rao_pitch_amp: 0.042, rao_pitch_phase_deg: 91.5,
      rao_roll_amp: 0.287, rao_roll_phase_deg: 88.2,
    },
    {
      omega_rad_s: 1.5, omega_e_rad_s: 1.5,
      rao_heave_amp: 0.65, rao_heave_phase_deg: -142.3,
      rao_pitch_amp: 0.038, rao_pitch_phase_deg: 148.7,
      rao_roll_amp: 0.112, rao_roll_phase_deg: 155.2,
    },
    {
      omega_rad_s: 2.0, omega_e_rad_s: 2.0,
      rao_heave_amp: 0.24, rao_heave_phase_deg: -175.1,
      rao_pitch_amp: 0.019, rao_pitch_phase_deg: 172.4,
      rao_roll_amp: 0.045, rao_roll_phase_deg: 168.3,
    },
  ],
  n_sections: 21,
  L_m: 100.0,
}

const STATS_RESULT = {
  Hs_input_m: 2.5,
  Tp_input_s: 8.0,
  spectrum: 'jonswap',
  motions: [
    {
      motion: 'heave',
      m0: 0.0025,
      m2: 0.0041,
      significant_amplitude: 0.1,
      mean_zero_crossing_period_s: 7.8,
      mpm_100_amplitude: 0.24,
    },
    {
      motion: 'pitch',
      m0: 0.000012,
      m2: 0.000021,
      significant_amplitude: 0.0069,
      mean_zero_crossing_period_s: 7.5,
      mpm_100_amplitude: 0.016,
    },
    {
      motion: 'roll',
      m0: 0.0081,
      m2: 0.0123,
      significant_amplitude: 0.18,
      mean_zero_crossing_period_s: 7.2,
      mpm_100_amplitude: 0.42,
    },
  ],
}

// ---------------------------------------------------------------------------
// Tests — RAO-only
// ---------------------------------------------------------------------------

describe('SeakeepingRAOPanel — RAO curves', () => {
  it('renders without crashing', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={RAO_RESULT} loading={false} error={null} />)
    expect(html).toBeTruthy()
  })

  it('shows hull length', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={RAO_RESULT} loading={false} error={null} />)
    expect(html).toContain('100')
  })

  it('shows n_sections', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={RAO_RESULT} loading={false} error={null} />)
    expect(html).toContain('21')
  })

  it('renders SVG chart', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={RAO_RESULT} loading={false} error={null} />)
    expect(html).toContain('<svg')
  })

  it('shows heave label', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={RAO_RESULT} loading={false} error={null} />)
    expect(html.toLowerCase()).toContain('heave')
  })

  it('shows pitch label', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={RAO_RESULT} loading={false} error={null} />)
    expect(html.toLowerCase()).toContain('pitch')
  })

  it('shows roll label', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={RAO_RESULT} loading={false} error={null} />)
    expect(html.toLowerCase()).toContain('roll')
  })

  it('shows STF method reference', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={RAO_RESULT} loading={false} error={null} />)
    expect(html).toContain('STF')
  })
})

// ---------------------------------------------------------------------------
// Tests — with stats
// ---------------------------------------------------------------------------

describe('SeakeepingRAOPanel — with stats', () => {
  it('renders with stats result', () => {
    const html = renderToStaticMarkup(
      <SeakeepingRAOPanel result={RAO_RESULT} statsResult={STATS_RESULT} loading={false} error={null} />
    )
    expect(html).toBeTruthy()
  })

  it('shows Hs and Tp', () => {
    const html = renderToStaticMarkup(
      <SeakeepingRAOPanel result={RAO_RESULT} statsResult={STATS_RESULT} loading={false} error={null} />
    )
    expect(html).toContain('2.5')
    // Tp=8 may render as "8" or "8.0" depending on JS number formatting
    expect(html).toMatch(/Tp=8/)
  })

  it('shows spectrum type', () => {
    const html = renderToStaticMarkup(
      <SeakeepingRAOPanel result={RAO_RESULT} statsResult={STATS_RESULT} loading={false} error={null} />
    )
    expect(html.toLowerCase()).toContain('jonswap')
  })

  it('shows significant amplitude', () => {
    const html = renderToStaticMarkup(
      <SeakeepingRAOPanel result={RAO_RESULT} statsResult={STATS_RESULT} loading={false} error={null} />
    )
    // heave significant_amplitude = 0.1 — shown as "sig: 0.1000"
    expect(html).toContain('0.1000')
  })

  it('shows MPM values', () => {
    const html = renderToStaticMarkup(
      <SeakeepingRAOPanel result={RAO_RESULT} statsResult={STATS_RESULT} loading={false} error={null} />
    )
    expect(html).toContain('MPM')
  })
})

// ---------------------------------------------------------------------------
// Tests — loading / error / null
// ---------------------------------------------------------------------------

describe('SeakeepingRAOPanel — loading state', () => {
  it('shows loading message', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={null} loading={true} error={null} />)
    expect(html).toContain('RAO')
  })
})

describe('SeakeepingRAOPanel — error state', () => {
  it('shows error message', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={null} loading={false} error="Hull error" />)
    expect(html).toContain('Hull error')
  })
})

describe('SeakeepingRAOPanel — null result', () => {
  it('renders nothing', () => {
    const html = renderToStaticMarkup(<SeakeepingRAOPanel result={null} loading={false} error={null} />)
    expect(html).toBe('')
  })
})
