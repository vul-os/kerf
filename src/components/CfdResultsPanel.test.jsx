/**
 * CfdResultsPanel.test.jsx
 *
 * SSR render tests using react-dom/server (same pattern as CfdViewport.test.jsx).
 * Tests structure, prop handling, and conditional rendering.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CfdResultsPanel from './CfdResultsPanel.jsx'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const FIELD_STATS = {
  U: { min_mag: 0.1, max_mag: 5.2, mean_mag: 2.1, rms_mag: 2.3, n_cells: 5000 },
  p: { min: -10.5, max: 15.2, mean: 0.3, rms: 5.1, n_cells: 5000 },
  k: { min: 0.001, max: 0.5, mean: 0.12, rms: 0.15, n_cells: 5000 },
}

const RESIDUALS = {
  Ux: { initial: 0.1, final: 1e-7, last_5: [1e-5, 5e-6, 2e-6, 1e-6, 1e-7], converged: true },
  p:  { initial: 0.05, final: 2e-6, last_5: [1e-4, 5e-5, 1e-5, 5e-6, 2e-6], converged: true },
}

const PROBES = [
  { probe_id: 0, x: 0.1, y: 0.5, z: 0.0, U_mag: 3.1, p: -2.5, k: 0.08, distance_m: 0.002 },
  { probe_id: 1, x: 0.5, y: 0.5, z: 0.0, U_mag: 4.2, p: -1.0, k: 0.12, distance_m: 0.001 },
]

const YPLUS = {
  Re_L: 666666,
  Cf_schlichting: 0.0034,
  u_tau_m_s: 0.412,
  target_yplus: 30.0,
  first_cell_height_m: 1.094e-3,
  note: 'Schlichting turbulent flat-plate Cf correlation.',
}

// ── Basic render ──────────────────────────────────────────────────────────────

describe('CfdResultsPanel — render without crash', () => {
  it('renders with no props (empty state)', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel />)
    expect(html).toContain('No CFD results')
  })

  it('renders with fieldStats without throwing', () => {
    expect(() =>
      renderToStaticMarkup(<CfdResultsPanel fieldStats={FIELD_STATS} />)
    ).not.toThrow()
  })

  it('renders with all props without throwing', () => {
    expect(() =>
      renderToStaticMarkup(
        <CfdResultsPanel
          fieldStats={FIELD_STATS}
          residuals={RESIDUALS}
          probes={PROBES}
          yplus={YPLUS}
          n_cells={5000}
          time_value={500}
          turbulenceModel="kOmegaSST"
          converged={true}
        />
      )
    ).not.toThrow()
  })
})

// ── Field stats table ─────────────────────────────────────────────────────────

describe('CfdResultsPanel — field statistics', () => {
  it('shows Field Statistics heading when fieldStats provided', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel fieldStats={FIELD_STATS} />)
    expect(html.toLowerCase()).toContain('field statistics')
  })

  it('shows U field data', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel fieldStats={FIELD_STATS} />)
    expect(html).toContain('Velocity U')
    expect(html).toContain('m/s')
  })

  it('shows pressure field data', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel fieldStats={FIELD_STATS} />)
    expect(html).toContain('Pressure p')
    expect(html).toContain('Pa')
  })

  it('shows TKE k field data', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel fieldStats={FIELD_STATS} />)
    expect(html).toContain('TKE k')
  })

  it('does not show field table when fieldStats is null', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel />)
    expect(html).not.toContain('Field Statistics')
  })
})

// ── Residuals panel ───────────────────────────────────────────────────────────

describe('CfdResultsPanel — residuals', () => {
  it('shows Solver Residuals section when residuals provided', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel residuals={RESIDUALS} converged={true} />)
    expect(html.toLowerCase()).toContain('solver residuals')
  })

  it('shows CONVERGED badge when converged=true', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel residuals={RESIDUALS} converged={true} />)
    expect(html).toContain('CONVERGED')
  })

  it('shows NOT CONVERGED badge when converged=false', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel residuals={RESIDUALS} converged={false} />)
    expect(html).toContain('NOT CONVERGED')
  })

  it('shows field names Ux and p', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel residuals={RESIDUALS} />)
    expect(html).toContain('Ux')
    expect(html).toContain('p')
  })

  it('does not show residuals section when residuals is null', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel />)
    expect(html).not.toContain('Solver Residuals')
  })
})

// ── Probes table ──────────────────────────────────────────────────────────────

describe('CfdResultsPanel — probes', () => {
  it('shows Probe Samples section when probes provided', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel probes={PROBES} />)
    expect(html.toLowerCase()).toContain('probe samples')
    expect(html).toContain('2 points')
  })

  it('shows probe coordinates', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel probes={PROBES} />)
    expect(html).toContain('0.1')
    expect(html).toContain('0.5')
  })

  it('does not show probes section when probes is null', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel />)
    expect(html).not.toContain('Probe Samples')
  })

  it('does not show probes section when probes is empty array', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel probes={[]} />)
    expect(html).not.toContain('Probe Samples')
  })
})

// ── Wall y⁺ card ──────────────────────────────────────────────────────────────

describe('CfdResultsPanel — y+ card', () => {
  it('shows Wall y⁺ section when yplus provided', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel yplus={YPLUS} />)
    expect(html).toContain('y')
    expect(html).toContain('Estimate')
  })

  it('shows Re_L value', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel yplus={YPLUS} />)
    expect(html).toContain('Re_L')
  })

  it('shows first_cell_height_m', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel yplus={YPLUS} />)
    expect(html).toContain('Δy₁')
  })

  it('does not show yplus section when yplus is null', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel />)
    expect(html).not.toContain('Wall y')
  })
})

// ── Header bar ────────────────────────────────────────────────────────────────

describe('CfdResultsPanel — header bar', () => {
  it('shows cell count chip', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel n_cells={5000} />)
    expect(html).toContain('5,000')
  })

  it('shows turbulence model chip', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel turbulenceModel="kOmegaSST" />)
    expect(html).toContain('kOmegaSST')
  })

  it('shows time/iteration chip', () => {
    const html = renderToStaticMarkup(<CfdResultsPanel time_value={500} />)
    expect(html).toContain('500')
  })

  it('renders without header chips when no header props', () => {
    // Should not crash with empty header
    expect(() =>
      renderToStaticMarkup(<CfdResultsPanel />)
    ).not.toThrow()
  })
})

// ── Edge cases ────────────────────────────────────────────────────────────────

describe('CfdResultsPanel — edge cases', () => {
  it('handles yplus with error gracefully', () => {
    const yp = { error: 'Re_L < 1 — not turbulent' }
    expect(() =>
      renderToStaticMarkup(<CfdResultsPanel yplus={yp} />)
    ).not.toThrow()
  })

  it('handles empty fieldStats object gracefully', () => {
    expect(() =>
      renderToStaticMarkup(<CfdResultsPanel fieldStats={{}} />)
    ).not.toThrow()
  })

  it('handles single probe', () => {
    const probe = [{ probe_id: 0, x: 1.0, y: 2.0, z: 0.0, p: 5.0 }]
    const html = renderToStaticMarkup(<CfdResultsPanel probes={probe} />)
    expect(html).toContain('1 points')
  })
})
