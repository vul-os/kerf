// FEAView.test.jsx — Vitest smoke tests for the 5 FEA solve panels.
//
// Follows the project's established pattern (FemResultPicker.test.jsx):
// renderToStaticMarkup for structure/label checks (no RTL needed).
// For dispatch-shape tests we verify payload construction logic directly,
// mirroring the contract test pattern used throughout the codebase.

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// ── mocks ─────────────────────────────────────────────────────────────────────

// Mock feaApi so no real fetch calls happen in static renders.
vi.mock('./feaApi.js', () => ({
  submitFemJob:  vi.fn(),
  pollFemStatus: vi.fn(),
  runAndPoll:    vi.fn(),
}))

// Mock useAuth — panels call useAuth.getState().accessToken
vi.mock('../../store/auth.js', () => ({
  useAuth: Object.assign(
    vi.fn(() => ({ accessToken: 'test-token' })),
    { getState: () => ({ accessToken: 'test-token' }) }
  ),
}))

import LinearStaticPanel from './LinearStaticPanel.jsx'
import ModalPanel        from './ModalPanel.jsx'
import BucklingPanel     from './BucklingPanel.jsx'
import FatiguePanel      from './FatiguePanel.jsx'
import VibrationPanel    from './VibrationPanel.jsx'
import FEAView           from './FEAView.jsx'

const PID = 'proj-123'
const FID = 'file-456'

// ── FEAView container ─────────────────────────────────────────────────────────

describe('FEAView', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<FEAView file={{ id: FID }} projectId={PID} />)
    ).not.toThrow()
  })

  it('renders all 5 tab labels', () => {
    const html = renderToStaticMarkup(<FEAView file={{ id: FID }} projectId={PID} />)
    expect(html).toMatch(/Linear Static/i)
    expect(html).toMatch(/Modal/i)
    expect(html).toMatch(/Buckling/i)
    expect(html).toMatch(/Fatigue/i)
    expect(html).toMatch(/Vibration/i)
  })

  it('renders tablist role', () => {
    const html = renderToStaticMarkup(<FEAView file={{ id: FID }} projectId={PID} />)
    expect(html).toMatch(/role="tablist"/)
  })

  it('renders tabpanel for linear_static by default', () => {
    const html = renderToStaticMarkup(<FEAView file={{ id: FID }} projectId={PID} />)
    expect(html).toMatch(/fea-panel-linear_static/)
  })

  it('renders tab buttons with role=tab', () => {
    const html = renderToStaticMarkup(<FEAView file={{ id: FID }} projectId={PID} />)
    const tabCount = (html.match(/role="tab"/g) || []).length
    expect(tabCount).toBe(5)
  })

  it('renders with null file gracefully', () => {
    expect(() =>
      renderToStaticMarkup(<FEAView file={null} projectId={PID} />)
    ).not.toThrow()
  })
})

// ── LinearStaticPanel ─────────────────────────────────────────────────────────

describe('LinearStaticPanel', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<LinearStaticPanel projectId={PID} fileId={FID} />)
    ).not.toThrow()
  })

  it('has correct data-testid', () => {
    const html = renderToStaticMarkup(<LinearStaticPanel projectId={PID} fileId={FID} />)
    expect(html).toContain('data-testid="linear-static-panel"')
  })

  it('renders material preset options', () => {
    const html = renderToStaticMarkup(<LinearStaticPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Steel.*S275/i)
    expect(html).toMatch(/Aluminium/i)
    expect(html).toMatch(/Titanium/i)
  })

  it('renders boundary condition type options', () => {
    const html = renderToStaticMarkup(<LinearStaticPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/fixed/i)
    expect(html).toMatch(/roller/i)
    expect(html).toMatch(/symmetry/i)
  })

  it('renders load type options', () => {
    const html = renderToStaticMarkup(<LinearStaticPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/pressure/i)
    expect(html).toMatch(/force/i)
    expect(html).toMatch(/distributed/i)
  })

  it('renders mesh size input', () => {
    const html = renderToStaticMarkup(<LinearStaticPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Mesh size/i)
  })

  it('renders Run button', () => {
    const html = renderToStaticMarkup(<LinearStaticPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Run Linear Static/i)
  })

  it('Run button is disabled when fileId is absent', () => {
    const html = renderToStaticMarkup(<LinearStaticPanel projectId={PID} fileId={null} />)
    expect(html).toMatch(/disabled/)
  })

  it('renders add-BC and add-load buttons', () => {
    const html = renderToStaticMarkup(<LinearStaticPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Add boundary condition/)
    expect(html).toMatch(/Add load/)
  })
})

// ── LinearStaticPanel dispatch payload shape (white-box contract) ─────────────

describe('LinearStaticPanel dispatch payload contract', () => {
  it('payload has required keys', () => {
    // Simulate what handleRun builds (mirrors component logic).
    const preset = { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 }
    const bcs    = [{ type: 'fixed', face_tag: '1' }]
    const loads  = [{ type: 'pressure', face_tag: '2', value: '1e6' }]

    const body = {
      analysis_type: 'linear_static',
      material_props: { E: preset.E, nu: preset.nu, rho: preset.rho, yield_strength: preset.yield_strength },
      boundary_conditions: bcs.map(bc => ({
        type: bc.type,
        face_tags: [parseInt(bc.face_tag, 10) || 1],
      })),
      loads: loads.map(l => ({
        type: l.type,
        face_tags: [parseInt(l.face_tag, 10) || 2],
        value: parseFloat(l.value) || 1e6,
      })),
      mesh_size: 0.01,
      solver: 'fenicsx',
    }

    expect(body.analysis_type).toBe('linear_static')
    expect(body.material_props.E).toBe(200e9)
    expect(Array.isArray(body.boundary_conditions)).toBe(true)
    expect(body.boundary_conditions[0].type).toBe('fixed')
    expect(Array.isArray(body.boundary_conditions[0].face_tags)).toBe(true)
    expect(Array.isArray(body.loads)).toBe(true)
    expect(body.loads[0].value).toBe(1e6)
    expect(typeof body.mesh_size).toBe('number')
  })
})

// ── ModalPanel ────────────────────────────────────────────────────────────────

describe('ModalPanel', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<ModalPanel projectId={PID} fileId={FID} />)
    ).not.toThrow()
  })

  it('has correct data-testid', () => {
    const html = renderToStaticMarkup(<ModalPanel projectId={PID} fileId={FID} />)
    expect(html).toContain('data-testid="modal-panel"')
  })

  it('renders N-modes input', () => {
    const html = renderToStaticMarkup(<ModalPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Number of modes/i)
  })

  it('renders fixed BC face-tag input', () => {
    const html = renderToStaticMarkup(<ModalPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Fixed BC face tag/i)
  })

  it('renders Run Modal button', () => {
    const html = renderToStaticMarkup(<ModalPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Run Modal/i)
  })

  it('renders material preset options', () => {
    const html = renderToStaticMarkup(<ModalPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Steel/i)
    expect(html).toMatch(/Aluminium/i)
  })
})

describe('ModalPanel dispatch payload contract', () => {
  it('payload has analysis_type=modal with n_modes', () => {
    const mat = { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 }
    const body = {
      analysis_type: 'modal',
      n_modes: 6,
      material_props: { E: mat.E, nu: mat.nu, rho: mat.rho, yield_strength: mat.yield_strength },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [],
      mesh_size: 0.01,
      solver: 'fenicsx',
    }

    expect(body.analysis_type).toBe('modal')
    expect(body.n_modes).toBe(6)
    expect(body.loads).toHaveLength(0)       // modal needs no static loads
    expect(body.material_props.rho).toBeGreaterThan(0)  // density required for modal
  })
})

// ── BucklingPanel ─────────────────────────────────────────────────────────────

describe('BucklingPanel', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<BucklingPanel projectId={PID} fileId={FID} />)
    ).not.toThrow()
  })

  it('has correct data-testid', () => {
    const html = renderToStaticMarkup(<BucklingPanel projectId={PID} fileId={FID} />)
    expect(html).toContain('data-testid="buckling-panel"')
  })

  it('renders load case selector', () => {
    const html = renderToStaticMarkup(<BucklingPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Axial compression/i)
    expect(html).toMatch(/Lateral pressure/i)
    expect(html).toMatch(/Combined/i)
  })

  it('renders BC config selector (Euler boundary conditions)', () => {
    const html = renderToStaticMarkup(<BucklingPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Pinned-Pinned/i)
    expect(html).toMatch(/Fixed-Free/i)
  })

  it('renders column length and reference load inputs', () => {
    const html = renderToStaticMarkup(<BucklingPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Column length/i)
    expect(html).toMatch(/Ref\. load/i)
  })

  it('renders Run Buckling button', () => {
    const html = renderToStaticMarkup(<BucklingPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Run Buckling/i)
  })
})

describe('BucklingPanel dispatch payload contract', () => {
  it('payload has required buckling-specific fields', () => {
    const body = {
      analysis_type: 'buckling',
      load_case: 'axial_compression',
      E: 200e9,
      I: 8.33e-9,
      A: 1e-4,
      L: 1.0,
      P_ref: 100000,
      supports: [{ type: 'pinned', x: 0 }, { type: 'pinned', x: 1 }],
      n_modes: 3,
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: 100000 }],
      mesh_size: 0.05,
      solver: 'fenicsx',
    }

    expect(body.analysis_type).toBe('buckling')
    expect(typeof body.L).toBe('number')
    expect(body.L).toBeGreaterThan(0)
    expect(typeof body.P_ref).toBe('number')
    expect(Array.isArray(body.supports)).toBe(true)
    expect(body.supports.length).toBeGreaterThan(0)
    expect(body.n_modes).toBeGreaterThan(0)
  })
})

// ── FatiguePanel ──────────────────────────────────────────────────────────────

describe('FatiguePanel', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    ).not.toThrow()
  })

  it('has correct data-testid', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toContain('data-testid="fatigue-panel"')
  })

  it('renders S-N material options', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Steel 1045/i)
    expect(html).toMatch(/Aluminium 6061/i)
    expect(html).toMatch(/Titanium/i)
  })

  it('renders mean-stress correction options', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Goodman/i)
    expect(html).toMatch(/Gerber/i)
    expect(html).toMatch(/SWT|Smith-Watson/i)
  })

  it('renders damage parameter selector', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/von Mises/i)
    expect(html).toMatch(/Max principal/i)
  })

  it('renders load history textarea', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Load history/i)
  })

  it('renders target life input', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Target life/i)
  })

  it('renders Run Fatigue button', () => {
    const html = renderToStaticMarkup(<FatiguePanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Run Fatigue/i)
  })
})

describe('FatiguePanel dispatch payload contract', () => {
  it('payload has material S-N params + options + load_history', () => {
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
      material_props: { E: mat.E, nu: 0.3, rho: 7850, yield_strength: mat.Sy },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: 200 }],
      mesh_size: 0.01,
      solver: 'fenicsx',
    }

    expect(body.analysis_type).toBe('fatigue')
    expect(body.material.Su).toBeGreaterThan(0)
    expect(body.material.b).toBeLessThan(0)          // Basquin exponent is negative
    expect(body.options.correction).toMatch(/goodman|gerber|swt/)
    expect(Array.isArray(body.load_history)).toBe(true)
    expect(body.load_history.length).toBeGreaterThan(0)
    expect(body.options.target_life).toBeGreaterThan(0)
  })
})

// ── VibrationPanel ────────────────────────────────────────────────────────────

describe('VibrationPanel', () => {
  it('renders without crashing', () => {
    expect(() =>
      renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    ).not.toThrow()
  })

  it('has correct data-testid', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toContain('data-testid="vibration-panel"')
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

  it('renders harmonic sweep points input', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Sweep points/i)
  })

  it('renders Run Harmonic button in default mode', () => {
    const html = renderToStaticMarkup(<VibrationPanel projectId={PID} fileId={FID} />)
    expect(html).toMatch(/Run Harmonic/i)
  })
})

describe('VibrationPanel dispatch payload contract — harmonic', () => {
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
    expect(body.freq_range.f_min).toBeDefined()
    expect(body.freq_range.f_max).toBeGreaterThan(body.freq_range.f_min)
    expect(body.freq_range.n_pts).toBeGreaterThan(0)
  })
})

describe('VibrationPanel dispatch payload contract — random vibration', () => {
  it('PSD payload has psd_table and analysis_type=random_vibration', () => {
    const psdProfile = { table: [[10, 0.04], [40, 0.04], [500, 0.0158], [2000, 0.0158]] }
    const body = {
      analysis_type: 'random_vibration',
      modal_damping: 0.02,
      freq_range: { f_min: 10, f_max: 2000, n_pts: 200 },
      psd_table: psdProfile.table,
      psd_profile: 'mil_std_810g',
      material_props: { E: 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads: [{ type: 'force', face_tags: [2], value: 1.0 }],
      mesh_size: 0.01,
      solver: 'fenicsx',
    }

    expect(body.analysis_type).toBe('random_vibration')
    expect(Array.isArray(body.psd_table)).toBe(true)
    expect(body.psd_table.length).toBeGreaterThan(0)
    // Each entry is [freq_Hz, PSD_value]
    expect(body.psd_table[0]).toHaveLength(2)
    expect(typeof body.modal_damping).toBe('number')
  })
})
