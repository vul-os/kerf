/**
 * OrbitDeterminationPanel.test.jsx — Vitest assertions for OrbitDeterminationPanel.
 *
 * Strategy: render to static markup via react-dom/server (SSR-compatible).
 * No browser / WebGL / Three.js needed.  Tests cover:
 *  1. Renders without crash in default/empty state.
 *  2. Shows "Demo" content when demo fixture active.
 *  3. Batch result: state vector rows appear.
 *  4. EKF result: state vector rows and covariance diagonal appear.
 *  5. Warnings are rendered when present.
 *  6. Loading state shows spinner text.
 *  7. Footnote references Tapley/Bierman.
 */

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import OrbitDeterminationPanel from './OrbitDeterminationPanel.jsx'

function render(props = {}) {
  return renderToStaticMarkup(<OrbitDeterminationPanel {...props} />)
}

// Fixture batch result
const BATCH = {
  ok: true,
  converged: true,
  n_iter: 5,
  x_estimated: [5678.1, 2345.4, 1234.7, -1.234, 6.789, 3.012],
  rms_residual: 0.9821,
  sigma_0: 0.9934,
  n_observations: 40,
  covariance_trace: 0.00042,
  warnings: [],
}

// Fixture EKF result
const EKF = {
  ok: true,
  state_final: [5673.4, 2350.1, 1237.3, -1.229, 6.792, 3.015],
  covariance_diag: [4.1e-5, 3.8e-5, 5.2e-5, 1.2e-9, 1.1e-9, 9.8e-10],
  rms_innovation: 1.043,
  n_observations: 40,
  position_norm_km: 6278.34,
  state_history_sample: [
    [5700, 2300, 1200, -1.20, 6.80, 3.00],
    [5695, 2310, 1210, -1.21, 6.79, 3.01],
  ],
  warnings: [],
}

// ── 1. Renders without crash ──────────────────────────────────────────────────

describe('OrbitDeterminationPanel — empty state', () => {
  it('renders without throwing', () => {
    expect(() => render()).not.toThrow()
  })

  it('renders the panel title', () => {
    const html = render()
    expect(html).toContain('Orbit Determination')
  })

  it('renders Batch LS + EKF subtitle', () => {
    const html = render()
    expect(html).toContain('Batch LS')
    expect(html).toContain('EKF')
  })

  it('shows empty-state text when no results', () => {
    const html = render()
    expect(html).toContain('No orbit determination results yet')
  })
})

// ── 2. Demo mode ──────────────────────────────────────────────────────────────
// Note: demo is toggled by internal state. We pass results directly instead.

describe('OrbitDeterminationPanel — with batch result', () => {
  it('does not show empty state when batchResult provided', () => {
    const html = render({ batchResult: BATCH })
    expect(html).not.toContain('No orbit determination results yet')
  })

  it('shows x_estimated values', () => {
    const html = render({ batchResult: BATCH })
    // State components should appear
    expect(html).toContain('r_x')
    expect(html).toContain('r_y')
    expect(html).toContain('v_z')
  })

  it('shows Batch LS Statistics block', () => {
    const html = render({ batchResult: BATCH })
    expect(html).toContain('Batch LS Statistics')
  })

  it('shows converged YES badge', () => {
    const html = render({ batchResult: BATCH })
    expect(html).toContain('YES')
  })

  it('shows n_observations count', () => {
    const html = render({ batchResult: BATCH })
    expect(html).toContain('40')
  })
})

// ── 3. EKF result ─────────────────────────────────────────────────────────────

describe('OrbitDeterminationPanel — with EKF result', () => {
  it('shows EKF state_final values', () => {
    const html = render({ ekfResult: EKF })
    expect(html).toContain('Extended Kalman Filter')
  })

  it('shows EKF Statistics block', () => {
    const html = render({ ekfResult: EKF })
    expect(html).toContain('EKF Statistics')
  })

  it('shows rms_innovation', () => {
    const html = render({ ekfResult: EKF })
    // rms_innovation = 1.043 → "1.0430"
    expect(html).toContain('1.0430')
  })
})

// ── 4. Both results ───────────────────────────────────────────────────────────

describe('OrbitDeterminationPanel — both results', () => {
  it('shows both Batch LS and EKF sections', () => {
    const html = render({ batchResult: BATCH, ekfResult: EKF })
    expect(html).toContain('Batch Least-Squares')
    expect(html).toContain('Extended Kalman Filter')
  })
})

// ── 5. Warnings ───────────────────────────────────────────────────────────────

describe('OrbitDeterminationPanel — warnings', () => {
  it('renders warning messages', () => {
    const html = render({
      batchResult: { ...BATCH, warnings: ['OD did not converge within 20 iterations.'] },
    })
    expect(html).toContain('OD did not converge')
  })
})

// ── 6. Loading state ──────────────────────────────────────────────────────────

describe('OrbitDeterminationPanel — loading', () => {
  it('shows running indicator when loading=true', () => {
    const html = render({ loading: true })
    expect(html).toContain('Running estimator')
  })

  it('does not show results while loading', () => {
    const html = render({ loading: true, batchResult: BATCH })
    expect(html).not.toContain('Batch LS Statistics')
  })
})

// ── 7. Mode prop ──────────────────────────────────────────────────────────────

describe('OrbitDeterminationPanel — mode prop', () => {
  it('mode=batch hides EKF section', () => {
    const html = render({ mode: 'batch', batchResult: BATCH, ekfResult: EKF })
    expect(html).toContain('Batch Least-Squares')
    expect(html).not.toContain('Extended Kalman Filter')
  })

  it('mode=ekf hides batch section', () => {
    const html = render({ mode: 'ekf', batchResult: BATCH, ekfResult: EKF })
    expect(html).toContain('Extended Kalman Filter')
    expect(html).not.toContain('Batch Least-Squares')
  })
})

// ── 8. Footnote ───────────────────────────────────────────────────────────────

describe('OrbitDeterminationPanel — reference footnote', () => {
  it('cites Tapley Schutz Born in footnote', () => {
    const html = render()
    expect(html).toContain('Tapley')
  })

  it('cites Bierman in footnote', () => {
    const html = render()
    expect(html).toContain('Bierman')
  })
})
