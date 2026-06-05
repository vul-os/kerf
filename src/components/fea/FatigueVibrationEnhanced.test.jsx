// FatigueVibrationEnhanced.test.jsx — vitest coverage for the enhanced
// FatiguePanel (S-N curve, Haigh diagram) and VibrationPanel (dual FRF,
// mode table, SDOF preview).
//
// Pattern: renderToStaticMarkup + contract unit tests (no RTL).

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// ── mocks ─────────────────────────────────────────────────────────────────────
vi.mock('./feaApi.js', () => ({
  submitFemJob:  vi.fn(),
  pollFemStatus: vi.fn(),
  runAndPoll:    vi.fn(),
}))
vi.mock('../../store/auth.js', () => ({
  useAuth: Object.assign(
    vi.fn(() => ({ accessToken: 'test-token' })),
    { getState: () => ({ accessToken: 'test-token' }) }
  ),
}))

import FatiguePanel   from './FatiguePanel.jsx'
import VibrationPanel from './VibrationPanel.jsx'

const PID = 'proj-123'
const FID = 'file-456'

// ===========================================================================
// FatiguePanel — enhanced structure
// ===========================================================================

describe('FatiguePanel enhanced', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    ).not.toThrow()
  })

  it('has data-testid="fatigue-panel"', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toContain('data-testid="fatigue-panel"')
  })

  it('renders S-N curve SVG element', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    // Should render an SVG for the S-N curve
    expect(html).toMatch(/<svg/)
    expect(html).toMatch(/S-N/i)
  })

  it('renders Wöhler/curve section title', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/S-N Curve|Wöhler|Woehler/i)
  })

  it('renders Basquin equation annotation', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Basquin/i)
  })

  it('renders endurance limit Se annotation', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    // Se label should appear in the curve annotation
    expect(html).toMatch(/Se\s*=\s*\d/)
  })

  it('renders Su annotation', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Su\s*=\s*\d/)
  })

  it('renders Haigh/Goodman toggle button', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Haigh/i)
  })

  it('renders S-N material select', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Steel 1045/i)
    expect(html).toMatch(/Aluminium 6061/i)
    expect(html).toMatch(/Titanium/i)
  })

  it('renders mean-stress correction select', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Goodman/i)
    expect(html).toMatch(/Gerber/i)
    expect(html).toMatch(/Smith-Watson|SWT/i)
  })

  it('renders damage parameter select', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/von Mises/i)
    expect(html).toMatch(/Max principal/i)
  })

  it('renders target life input', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Target life/i)
  })

  it('renders load history textarea', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Load history/i)
    expect(html).toMatch(/<textarea/)
  })

  it('renders Run Fatigue button', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Run Fatigue/i)
  })

  it('renders with null fileId gracefully', () => {
    expect(() =>
      renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={null} />)
    ).not.toThrow()
  })

  it('Run button disabled when no fileId', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={null} />)
    expect(html).toMatch(/disabled/)
  })
})

// ---------------------------------------------------------------------------
// FatiguePanel S-N curve generator contract (unit test, pure JS)
// ---------------------------------------------------------------------------

describe('FatiguePanel S-N curve data contract', () => {
  // Mirror the generateSNCurve logic from the component
  function generateSNCurve(mat, nPoints = 40) {
    const { sf_prime, b, Se, Su } = mat
    const sfp = sf_prime || 1.5 * Su
    const logMin = 2, logMax = 8
    return Array.from({ length: nPoints }, (_, i) => {
      const logN = logMin + (i / (nPoints - 1)) * (logMax - logMin)
      const N = Math.pow(10, logN)
      const sigma_a = sfp * Math.pow(2 * N, b)
      return { N, sigma_a_mpa: sigma_a / 1e6 }
    })
  }

  const MAT = { Su: 600e6, Sy: 450e6, Se: 300e6, b: -0.085, sf_prime: 900e6 }

  it('generates correct number of points', () => {
    const pts = generateSNCurve(MAT, 40)
    expect(pts).toHaveLength(40)
  })

  it('amplitudes are positive', () => {
    const pts = generateSNCurve(MAT, 20)
    pts.forEach(p => expect(p.sigma_a_mpa).toBeGreaterThan(0))
  })

  it('amplitudes decrease monotonically (b < 0)', () => {
    const pts = generateSNCurve(MAT, 20)
    for (let i = 1; i < pts.length; i++) {
      expect(pts[i].sigma_a_mpa).toBeLessThanOrEqual(pts[i - 1].sigma_a_mpa + 0.01)
    }
  })

  it('Basquin closed form: σ_a = sf_prime * (2N)^b', () => {
    // Use n_points=20 to get a mid-range point with a meaningful N value
    const pts = generateSNCurve(MAT, 20)
    const mid = pts[10]  // pick a middle point (N around 1e5)
    const expected = MAT.sf_prime * Math.pow(2 * mid.N, MAT.b) / 1e6
    expect(expected).toBeGreaterThan(0)
    expect(Math.abs(mid.sigma_a_mpa - expected) / expected).toBeLessThan(1e-9)
  })

  it('N values span [1e2, 1e8]', () => {
    const pts = generateSNCurve(MAT, 20)
    expect(pts[0].N).toBeCloseTo(1e2, 0)
    expect(pts[pts.length - 1].N).toBeCloseTo(1e8, 0)
  })
})

// ---------------------------------------------------------------------------
// FatiguePanel Haigh diagram generator contract
// ---------------------------------------------------------------------------

describe('FatiguePanel Haigh diagram contract', () => {
  function generateHaighGoodman(mat, nPts = 40) {
    const { Su, Se } = mat
    return Array.from({ length: nPts }, (_, i) => {
      const sigma_m = (i / (nPts - 1)) * Su
      return { sigma_m_mpa: sigma_m / 1e6, sigma_a_mpa: Math.max(Se * (1 - sigma_m / Su), 0) / 1e6 }
    })
  }

  const MAT = { Su: 600e6, Sy: 450e6, Se: 300e6 }

  it('at σ_m=0, allowable = Se', () => {
    const pts = generateHaighGoodman(MAT)
    expect(pts[0].sigma_a_mpa).toBeCloseTo(MAT.Se / 1e6, 5)
  })

  it('at σ_m=Su, allowable = 0', () => {
    const pts = generateHaighGoodman(MAT)
    expect(pts[pts.length - 1].sigma_a_mpa).toBeLessThan(0.01)
  })

  it('monotone decreasing', () => {
    const pts = generateHaighGoodman(MAT, 20)
    for (let i = 1; i < pts.length; i++) {
      expect(pts[i].sigma_a_mpa).toBeLessThanOrEqual(pts[i - 1].sigma_a_mpa + 0.001)
    }
  })
})

// ---------------------------------------------------------------------------
// FatiguePanel dispatch payload contract
// ---------------------------------------------------------------------------

describe('FatiguePanel dispatch payload contract', () => {
  it('payload has material S-N params and options', () => {
    const mat = { Su: 690e6, Sy: 580e6, Se: 241.5e6, b: -0.085, c: -0.600, E: 207e9 }
    const body = {
      analysis_type: 'fatigue',
      material: {
        Su: mat.Su, Sy: mat.Sy, Se: mat.Se,
        b: mat.b, c: mat.c, E: mat.E,
        sf_prime: 1.5 * mat.Su,
        ef_prime: 0.59,
      },
      options: {
        correction: 'goodman',
        damage_param: 'von_mises',
        life_curve: 'basquin',
        target_life: 1e6,
      },
      load_history: [-200, 400, -200, 350, -100, 300, 0, 300, -100, 200],
    }

    expect(body.analysis_type).toBe('fatigue')
    expect(body.material.Su).toBeGreaterThan(0)
    expect(body.material.b).toBeLessThan(0)        // Basquin exponent negative
    expect(body.material.sf_prime).toBeGreaterThan(body.material.Su)  // sf_prime > Su typical
    expect(body.options.correction).toMatch(/goodman|gerber|swt/)
    expect(Array.isArray(body.load_history)).toBe(true)
  })
})

// ===========================================================================
// VibrationPanel — enhanced structure
// ===========================================================================

describe('VibrationPanel enhanced', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    ).not.toThrow()
  })

  it('has data-testid="vibration-panel"', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toContain('data-testid="vibration-panel"')
  })

  it('renders FRF preview SVG', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/<svg/)
  })

  it('renders FRF Preview section title', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/FRF Preview|SDOF/i)
  })

  it('renders DAF peak annotation', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/DAF/i)
  })

  it('renders fn preview input', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Preview fn|fn.*Hz/i)
  })

  it('renders analysis type selector', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Harmonic.*FRF/i)
    expect(html).toMatch(/Random Vibration.*PSD/i)
  })

  it('renders damping ratio input', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Damping ratio/i)
  })

  it('renders frequency range inputs', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/f_min/i)
    expect(html).toMatch(/f_max/i)
  })

  it('renders sweep points input in harmonic mode', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Sweep points/i)
  })

  it('renders Run Harmonic button', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Run Harmonic/i)
  })

  it('renders with null fileId gracefully', () => {
    expect(() =>
      renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={null} />)
    ).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// VibrationPanel SDOF analytical DAF contract
// ---------------------------------------------------------------------------

describe('VibrationPanel SDOF DAF contract', () => {
  // Mirror the sdofDaf function from the component
  function sdofDaf(r, zeta) {
    const den = Math.sqrt(Math.pow(1 - r * r, 2) + Math.pow(2 * zeta * r, 2))
    return den < 1e-30 ? Infinity : 1 / den
  }

  function sdofPhaseDeg(r, zeta) {
    return (Math.atan2(2 * zeta * r, 1 - r * r) * 180) / Math.PI
  }

  it('DAF at r=0 (static) equals 1.0', () => {
    expect(sdofDaf(0, 0.05)).toBeCloseTo(1.0, 9)
  })

  it('DAF at resonance (r=1) equals 1/(2ζ)', () => {
    const zeta = 0.05
    const daf = sdofDaf(1.0, zeta)
    expect(daf).toBeCloseTo(1 / (2 * zeta), 9)
  })

  it('DAF decreases beyond resonance', () => {
    const zeta = 0.05
    expect(sdofDaf(2.0, zeta)).toBeLessThan(sdofDaf(1.0, zeta))
  })

  it('phase at resonance is ±90°', () => {
    const phase = sdofPhaseDeg(1.0, 0.05)
    expect(Math.abs(Math.abs(phase) - 90)).toBeLessThan(1e-9)
  })

  it('phase below resonance is in [0°, 90°]', () => {
    const phase = sdofPhaseDeg(0.5, 0.05)
    expect(phase).toBeGreaterThanOrEqual(0)
    expect(phase).toBeLessThanOrEqual(90)
  })

  it('phase above resonance is in [90°, 180°]', () => {
    const phase = sdofPhaseDeg(1.5, 0.05)
    expect(phase).toBeGreaterThanOrEqual(90)
    expect(phase).toBeLessThanOrEqual(180)
  })

  it('higher damping gives lower peak DAF', () => {
    expect(sdofDaf(1.0, 0.1)).toBeLessThan(sdofDaf(1.0, 0.02))
  })

  it('DAF formula matches closed form for arbitrary r', () => {
    const r = 0.7, zeta = 0.05
    const expected = 1 / Math.sqrt(Math.pow(1 - r * r, 2) + Math.pow(2 * zeta * r, 2))
    expect(sdofDaf(r, zeta)).toBeCloseTo(expected, 10)
  })
})

// ---------------------------------------------------------------------------
// VibrationPanel SDOF preview curve generation contract
// ---------------------------------------------------------------------------

describe('VibrationPanel SDOF preview curve contract', () => {
  function sdofDaf(r, zeta) {
    const den = Math.sqrt(Math.pow(1 - r * r, 2) + Math.pow(2 * zeta * r, 2))
    return den < 1e-30 ? Infinity : 1 / den
  }

  function generateSDOFPreview(fn, zeta, fMin, fMax, nPts = 120) {
    const d = (fMax - fMin) / (nPts - 1)
    return Array.from({ length: nPts }, (_, i) => {
      const f = fMin + i * d
      const r = f / fn
      return { f, daf: sdofDaf(r, zeta) }
    })
  }

  it('generates correct number of points', () => {
    const pts = generateSDOFPreview(100, 0.05, 1, 2000, 120)
    expect(pts).toHaveLength(120)
  })

  it('resonant peak is near fn', () => {
    const fn = 100, zeta = 0.02
    const pts = generateSDOFPreview(fn, zeta, 10, 300, 500)
    const peakIdx = pts.reduce((best, p, i) => p.daf > pts[best].daf ? i : best, 0)
    expect(Math.abs(pts[peakIdx].f - fn)).toBeLessThan(2)
  })

  it('DAF_peak ≈ 1/(2ζ)', () => {
    const fn = 100, zeta = 0.05
    const pts = generateSDOFPreview(fn, zeta, fn * 0.9999, fn * 1.0001, 3)
    const peakDaf = Math.max(...pts.map(p => p.daf))
    const expected = 1 / (2 * zeta)
    expect(Math.abs(peakDaf - expected) / expected).toBeLessThan(0.001)
  })

  it('all DAF values are positive', () => {
    const pts = generateSDOFPreview(50, 0.05, 1, 200, 50)
    pts.forEach(p => expect(p.daf).toBeGreaterThan(0))
  })
})

// ---------------------------------------------------------------------------
// VibrationPanel dispatch payload contract
// ---------------------------------------------------------------------------

describe('VibrationPanel dispatch payload contract', () => {
  it('harmonic payload has freq_range and modal_damping', () => {
    const body = {
      analysis_type: 'harmonic',
      modal_damping: 0.02,
      freq_range: { f_min: 1, f_max: 2000, n_pts: 200 },
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: 1.0 }],
      mesh_size: 0.01,
      solver: 'fenicsx',
    }

    expect(body.analysis_type).toBe('harmonic')
    expect(typeof body.modal_damping).toBe('number')
    expect(body.modal_damping).toBeGreaterThan(0)
    expect(body.freq_range.f_max).toBeGreaterThan(body.freq_range.f_min)
  })

  it('PSD payload has psd_table', () => {
    const body = {
      analysis_type: 'random_vibration',
      modal_damping: 0.02,
      psd_table: [[10, 0.04], [40, 0.04], [500, 0.0158], [2000, 0.0158]],
    }

    expect(body.analysis_type).toBe('random_vibration')
    expect(Array.isArray(body.psd_table)).toBe(true)
    expect(body.psd_table[0]).toHaveLength(2)
  })
})
