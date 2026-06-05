/**
 * composites.test.jsx
 *
 * Vitest / RTL tests for the four composites manufacturing panels:
 *   - LaminateStackup
 *   - AFPToolpathView
 *   - FiberOrientationContour
 *   - LaminateFailureEnvelope
 *
 * Uses renderToStaticMarkup (react-dom/server) — no jsdom canvas needed.
 * API calls are stubbed via vi.stubGlobal('fetch', ...).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import LaminateStackup from './LaminateStackup.jsx'
import AFPToolpathView from './AFPToolpathView.jsx'
import FiberOrientationContour from './FiberOrientationContour.jsx'
import LaminateFailureEnvelope from './LaminateFailureEnvelope.jsx'

// ---------------------------------------------------------------------------
// Shared mock plies fixture
// ---------------------------------------------------------------------------
const MOCK_PLIES = [
  { id: 'p1', material: 'T300/Epoxy', thickness: 0.125, angle: 0,   E1: 181, E2: 10.3, G12: 7.17, nu12: 0.28, rho: 1.6, costPerKg: 45 },
  { id: 'p2', material: 'T300/Epoxy', thickness: 0.125, angle: 45,  E1: 181, E2: 10.3, G12: 7.17, nu12: 0.28, rho: 1.6, costPerKg: 45 },
  { id: 'p3', material: 'T300/Epoxy', thickness: 0.125, angle: -45, E1: 181, E2: 10.3, G12: 7.17, nu12: 0.28, rho: 1.6, costPerKg: 45 },
  { id: 'p4', material: 'T300/Epoxy', thickness: 0.125, angle: 90,  E1: 181, E2: 10.3, G12: 7.17, nu12: 0.28, rho: 1.6, costPerKg: 45 },
]

// ---------------------------------------------------------------------------
// Mock useAuth store — composites panels read the auth token
// ---------------------------------------------------------------------------
vi.mock('../../store/auth.js', () => ({
  useAuth: Object.assign(
    (selector) => selector({ accessToken: 'test-token' }),
    { getState: () => ({ accessToken: 'test-token' }) },
  ),
}))

// ---------------------------------------------------------------------------
// Stub fetch so API calls don't hit real network
// ---------------------------------------------------------------------------
const CLT_RESPONSE = {
  name: 'ui_layup',
  num_plies: 4,
  total_thickness_mm: 0.5,
  is_symmetric: false,
  A_matrix_N_per_mm: [[1,0,0],[0,1,0],[0,0,1]],
  B_matrix_N: [[0,0,0],[0,0,0],[0,0,0]],
  D_matrix_N_mm: [[1,0,0],[0,1,0],[0,0,1]],
  effective_moduli: { Ex: 50.3, Ey: 50.3, Gxy: 19.2 },
}

function makeFetch(payload, ok = true) {
  return vi.fn(() =>
    Promise.resolve({
      ok,
      status: ok ? 200 : 500,
      json: () => Promise.resolve(payload),
      text: () => Promise.resolve(JSON.stringify(payload)),
    }),
  )
}

// ---------------------------------------------------------------------------
// LaminateStackup tests
// ---------------------------------------------------------------------------

describe('LaminateStackup', () => {
  let fetchSpy

  beforeEach(() => {
    fetchSpy = makeFetch(CLT_RESPONSE)
    vi.stubGlobal('fetch', fetchSpy)
    vi.stubGlobal('crypto', {
      randomUUID: (() => {
        let n = 0
        return () => `uuid-${n++}`
      })(),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllTimers()
  })

  it('mounts without throwing', () => {
    expect(() => renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)).not.toThrow()
  })

  it('renders the data-testid root', () => {
    const html = renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)
    expect(html).toContain('data-testid="laminate-stackup"')
  })

  it('renders a row for each ply', () => {
    const html = renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)
    // Four plies → four numbered cells (1, 2, 3, 4) — checked via ply count label
    expect(html).toContain('>4<')
  })

  it('shows ply angles in the output', () => {
    const html = renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)
    // Angle 45 should appear somewhere in the rendered output
    expect(html).toMatch(/45/)
  })

  it('shows material names in the output', () => {
    const html = renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)
    expect(html).toContain('T300/Epoxy')
  })

  it('renders the rollup bar with expected labels', () => {
    const html = renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)
    expect(html).toMatch(/Plies/i)
    expect(html).toMatch(/Thickness/i)
    expect(html).toMatch(/Areal/i)
    expect(html).toMatch(/cost/i)
  })

  it('renders the CLT result section', () => {
    const html = renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)
    expect(html).toMatch(/CLT Stiffness/i)
  })

  it('renders balance indicator', () => {
    const html = renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)
    expect(html).toMatch(/[Bb]al/)
  })

  it('renders symmetry indicator', () => {
    const html = renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)
    expect(html).toMatch(/[Ss]ym/)
  })

  it('renders the Run Analysis button', () => {
    const html = renderToStaticMarkup(<LaminateStackup initialPlies={MOCK_PLIES} />)
    expect(html).toMatch(/Run Analysis/i)
  })
})

// ---------------------------------------------------------------------------
// AFPToolpathView tests
// ---------------------------------------------------------------------------

describe('AFPToolpathView', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', makeFetch({ courses: [], num_courses: 0 }))
    // Stub canvas getContext so SSR doesn't crash on canvas ops
    if (typeof HTMLCanvasElement !== 'undefined') {
      HTMLCanvasElement.prototype.getContext = vi.fn(() => null)
    }
  })
  afterEach(() => vi.unstubAllGlobals())

  it('mounts without throwing', () => {
    expect(() => renderToStaticMarkup(<AFPToolpathView />)).not.toThrow()
  })

  it('renders the data-testid root', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toContain('data-testid="afp-toolpath-view"')
  })

  it('renders the AFP Toolpath Planner title', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toMatch(/AFP Toolpath/i)
  })

  it('renders Plan Paths button', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toMatch(/Plan Paths/i)
  })

  it('renders AFP parameter controls', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toMatch(/AFP Parameters/i)
    expect(html).toMatch(/Course/i)
    expect(html).toMatch(/Tow/i)
  })

  it('renders cure cycle controls', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toMatch(/Cure Cycle/i)
    expect(html).toMatch(/Dwell/i)
  })

  it('renders the tape layout section', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toMatch(/Tape Layout/i)
  })

  it('renders the cure cycle profile section', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toMatch(/Cure Cycle Profile/i)
  })

  it('renders an SVG for the cure cycle chart', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toMatch(/<svg\b/)
  })

  it('renders the DWELL label inside SVG', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toMatch(/DWELL/)
  })

  it('renders a canvas element for the toolpath', () => {
    const html = renderToStaticMarkup(<AFPToolpathView />)
    expect(html).toMatch(/<canvas\b/)
  })
})

// ---------------------------------------------------------------------------
// FiberOrientationContour tests
// ---------------------------------------------------------------------------

describe('FiberOrientationContour', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', makeFetch({
      surface: 'flat',
      nu: 10,
      nv: 10,
      shear_angle_deg: { mean: 0.5, max: 2.1, min: 0.0 },
    }))
    if (typeof HTMLCanvasElement !== 'undefined') {
      HTMLCanvasElement.prototype.getContext = vi.fn(() => null)
    }
  })
  afterEach(() => vi.unstubAllGlobals())

  it('mounts without throwing', () => {
    expect(() => renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)).not.toThrow()
  })

  it('renders the data-testid root', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    expect(html).toContain('data-testid="fiber-orientation-contour"')
  })

  it('renders the title', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    expect(html).toMatch(/Fiber Orientation/i)
  })

  it('renders the ply stack section', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    expect(html).toMatch(/Ply Stack/i)
  })

  it('renders the drape simulation section', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    expect(html).toMatch(/Drape Sim/i)
  })

  it('renders the Run Drape button', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    expect(html).toMatch(/Run Drape/i)
  })

  it('renders surface selector options', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    expect(html).toMatch(/Flat/)
    expect(html).toMatch(/Cyl/)
  })

  it('renders the contour canvas element', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    expect(html).toMatch(/<canvas\b/)
  })

  it('renders an aria-label on the contour canvas', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    expect(html).toMatch(/aria-label="Fiber orientation contour map"/)
  })

  it('renders ply angle labels in the exploded stack', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    // Should include angle° labels for 0°, 45°, −45°, 90°
    expect(html).toMatch(/0°/)
    expect(html).toMatch(/45°/)
    expect(html).toMatch(/90°/)
  })

  it('renders the color legend', () => {
    const html = renderToStaticMarkup(<FiberOrientationContour plies={MOCK_PLIES} />)
    expect(html).toMatch(/−90°/)
    expect(html).toMatch(/\+90°/)
  })

  it('falls back to default plies when none provided', () => {
    expect(() => renderToStaticMarkup(<FiberOrientationContour />)).not.toThrow()
    const html = renderToStaticMarkup(<FiberOrientationContour />)
    expect(html).toContain('data-testid="fiber-orientation-contour"')
  })
})

// ---------------------------------------------------------------------------
// LaminateFailureEnvelope tests
// ---------------------------------------------------------------------------

const ENVELOPE_PLIES = [
  { angle: 0,   E1: 181, E2: 10.3, G12: 7.17, nu12: 0.28, thickness: 0.125,
    Xt: 1500, Xc: 1500, Yt: 40, Yc: 246, S12: 68 },
  { angle: 90,  E1: 181, E2: 10.3, G12: 7.17, nu12: 0.28, thickness: 0.125,
    Xt: 1500, Xc: 1500, Yt: 40, Yc: 246, S12: 68 },
  { angle: 0,   E1: 181, E2: 10.3, G12: 7.17, nu12: 0.28, thickness: 0.125,
    Xt: 1500, Xc: 1500, Yt: 40, Yc: 246, S12: 68 },
]

const ENVELOPE_RESPONSE = {
  envelope_points: [
    { theta_deg: 0,   Nx_fail_N_per_mm: 500, Ny_fail_N_per_mm: 0,   lambda_crit: 500 },
    { theta_deg: 90,  Nx_fail_N_per_mm: 0,   Ny_fail_N_per_mm: 200, lambda_crit: 200 },
    { theta_deg: 180, Nx_fail_N_per_mm: -500, Ny_fail_N_per_mm: 0,  lambda_crit: 500 },
    { theta_deg: 270, Nx_fail_N_per_mm: 0,   Ny_fail_N_per_mm: -200, lambda_crit: 200 },
  ],
  max_uniaxial_Nx_N_per_mm: 500,
  max_uniaxial_Ny_N_per_mm: 200,
  num_plies: 3,
  n_angles: 4,
}

describe('LaminateFailureEnvelope', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', makeFetch(ENVELOPE_RESPONSE))
    if (typeof HTMLCanvasElement !== 'undefined') {
      HTMLCanvasElement.prototype.getContext = vi.fn(() => null)
    }
  })
  afterEach(() => vi.unstubAllGlobals())

  it('mounts without throwing', () => {
    expect(() => renderToStaticMarkup(<LaminateFailureEnvelope plies={ENVELOPE_PLIES} />)).not.toThrow()
  })

  it('renders the data-testid root', () => {
    const html = renderToStaticMarkup(<LaminateFailureEnvelope plies={ENVELOPE_PLIES} />)
    expect(html).toContain('data-testid="laminate-failure-envelope"')
  })

  it('renders the FPF title', () => {
    const html = renderToStaticMarkup(<LaminateFailureEnvelope plies={ENVELOPE_PLIES} />)
    expect(html).toMatch(/Failure Envelope/i)
    expect(html).toMatch(/FPF/i)
  })

  it('renders the Run Envelope button', () => {
    const html = renderToStaticMarkup(<LaminateFailureEnvelope plies={ENVELOPE_PLIES} />)
    expect(html).toMatch(/Run Envelope/i)
  })

  it('renders operating point inputs (Nx, Ny)', () => {
    const html = renderToStaticMarkup(<LaminateFailureEnvelope plies={ENVELOPE_PLIES} />)
    expect(html).toMatch(/Operating Point/i)
    expect(html).toMatch(/Nx/i)
    expect(html).toMatch(/Ny/i)
  })

  it('renders the SVG envelope plot placeholder', () => {
    const html = renderToStaticMarkup(<LaminateFailureEnvelope plies={ENVELOPE_PLIES} />)
    expect(html).toMatch(/<svg\b/)
  })

  it('renders axis labels Nx and Ny', () => {
    const html = renderToStaticMarkup(<LaminateFailureEnvelope plies={ENVELOPE_PLIES} />)
    expect(html).toMatch(/N\/mm/)
  })

  it('renders parameters section with F12 control', () => {
    const html = renderToStaticMarkup(<LaminateFailureEnvelope plies={ENVELOPE_PLIES} />)
    expect(html).toMatch(/F12/)
    expect(html).toMatch(/Parameters/i)
  })

  it('falls back to default plies when none provided', () => {
    expect(() => renderToStaticMarkup(<LaminateFailureEnvelope />)).not.toThrow()
    const html = renderToStaticMarkup(<LaminateFailureEnvelope />)
    expect(html).toContain('data-testid="laminate-failure-envelope"')
  })
})
