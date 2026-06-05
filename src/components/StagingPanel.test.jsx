// StagingPanel.test.jsx — vitest smoke tests for the multi-stage rocket staging panel.

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import StagingPanel from './StagingPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const EXPLICIT_RESULT = {
  ok: true,
  mode: 'explicit',
  total_delta_v_m_s: 6847.2,
  total_delta_v_km_s: 6.8472,
  n_stages: 2,
  payload_mass_kg: 800,
  stage_results: [
    {
      stage: 'Stage 1',
      isp: 350,
      m0: 10000,
      mf: 4000,
      mass_ratio: 2.5,
      delta_v_ms: 3251.0,
      delta_v_kms: 3.251,
      propellant_fraction: 0.6,
    },
    {
      stage: 'Stage 2',
      isp: 350,
      m0: 2000,
      mf: 800,
      mass_ratio: 2.5,
      delta_v_ms: 3596.2,
      delta_v_kms: 3.5962,
      propellant_fraction: 0.6,
    },
  ],
}

const OPTIMAL_RESULT = {
  ok: true,
  mode: 'optimal_split',
  total_delta_v_m_s: 9200.0,
  total_delta_v_km_s: 9.2,
  n_stages: 2,
  payload_fraction: 0.0421,
  total_wet_mass_kg: 23756.3,
  optimal_dv_split_m_s: [4600.0, 4600.0],
  stage_mass_ratios: [3.85, 3.85],
  equal_split: true,
  stage_results: [
    {
      stage: 'Stage 1',
      delta_v_ms: 4600,
      delta_v_kms: 4.6,
      mass_ratio: 3.85,
      m0: 23756,
      mf: 6171,
      isp: 350,
      structural_fraction: 0.1,
    },
    {
      stage: 'Stage 2',
      delta_v_ms: 4600,
      delta_v_kms: 4.6,
      mass_ratio: 3.85,
      m0: 5554,
      mf: 1442,
      isp: 350,
      structural_fraction: 0.1,
    },
  ],
  inputs: { total_delta_v_m_s: 9200, n_stages: 2, isp_per_stage: 350, payload_mass_kg: 1000 },
}

// ---------------------------------------------------------------------------
// Tests — explicit mode
// ---------------------------------------------------------------------------

describe('StagingPanel — explicit mode', () => {
  it('renders without crashing', () => {
    const html = renderToStaticMarkup(<StagingPanel result={EXPLICIT_RESULT} loading={false} error={null} />)
    expect(html).toBeTruthy()
  })

  it('shows total ΔV', () => {
    const html = renderToStaticMarkup(<StagingPanel result={EXPLICIT_RESULT} loading={false} error={null} />)
    expect(html).toContain('6.847')
  })

  it('shows number of stages', () => {
    const html = renderToStaticMarkup(<StagingPanel result={EXPLICIT_RESULT} loading={false} error={null} />)
    expect(html).toContain('2')
  })

  it('shows stage names in table', () => {
    const html = renderToStaticMarkup(<StagingPanel result={EXPLICIT_RESULT} loading={false} error={null} />)
    expect(html).toContain('Stage 1')
    expect(html).toContain('Stage 2')
  })

  it('shows Isp values', () => {
    const html = renderToStaticMarkup(<StagingPanel result={EXPLICIT_RESULT} loading={false} error={null} />)
    expect(html).toContain('350')
  })

  it('renders bar chart (SVG)', () => {
    const html = renderToStaticMarkup(<StagingPanel result={EXPLICIT_RESULT} loading={false} error={null} />)
    expect(html).toContain('<svg')
  })

  it('shows Tsiolkovsky reference', () => {
    const html = renderToStaticMarkup(<StagingPanel result={EXPLICIT_RESULT} loading={false} error={null} />)
    expect(html).toContain('Tsiolkovsky')
  })
})

// ---------------------------------------------------------------------------
// Tests — optimal mode
// ---------------------------------------------------------------------------

describe('StagingPanel — optimal split mode', () => {
  it('renders without crashing', () => {
    const html = renderToStaticMarkup(<StagingPanel result={OPTIMAL_RESULT} loading={false} error={null} />)
    expect(html).toBeTruthy()
  })

  it('shows total ΔV', () => {
    const html = renderToStaticMarkup(<StagingPanel result={OPTIMAL_RESULT} loading={false} error={null} />)
    expect(html).toContain('9.200')
  })

  it('shows payload fraction', () => {
    const html = renderToStaticMarkup(<StagingPanel result={OPTIMAL_RESULT} loading={false} error={null} />)
    expect(html).toContain('4.21')  // 0.0421 → 4.21%
  })

  it('shows total wet mass', () => {
    const html = renderToStaticMarkup(<StagingPanel result={OPTIMAL_RESULT} loading={false} error={null} />)
    expect(html).toContain('23756.3')
  })

  it('shows equal split note', () => {
    const html = renderToStaticMarkup(<StagingPanel result={OPTIMAL_RESULT} loading={false} error={null} />)
    expect(html.toLowerCase()).toContain('equal')
  })
})

// ---------------------------------------------------------------------------
// Tests — loading / error / null
// ---------------------------------------------------------------------------

describe('StagingPanel — loading state', () => {
  it('shows loading message', () => {
    const html = renderToStaticMarkup(<StagingPanel result={null} loading={true} error={null} />)
    expect(html).toContain('staging')
  })
})

describe('StagingPanel — error state', () => {
  it('shows error message', () => {
    const html = renderToStaticMarkup(<StagingPanel result={null} loading={false} error="Staging failed" />)
    expect(html).toContain('Staging failed')
  })
})

describe('StagingPanel — null result', () => {
  it('renders nothing', () => {
    const html = renderToStaticMarkup(<StagingPanel result={null} loading={false} error={null} />)
    expect(html).toBe('')
  })
})
