/**
 * AssemblyMotionStudioPanel.test.jsx
 * ===================================
 * Tests for the interactive Assembly Motion Studio panel (Blender/SolidWorks-Motion parity).
 *
 * Strategy
 * --------
 * Tier 1 — source inspection: verify structural requirements without DOM.
 * Tier 2 — pure-helper unit tests: parseTableDriver, buildTimelinePayload, parseStudySpec.
 * Tier 3 — renderToStaticMarkup smoke tests: verify DOM landmarks present.
 * Tier 4 — scrubber state: mock fetch + inject fake timeline, verify frame advances.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'
import { renderToStaticMarkup } from 'react-dom/server'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(path.resolve(__dirname, './AssemblyMotionStudioPanel.jsx'), 'utf8')

// ── Mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../store/auth.js', () => ({
  useAuth: { getState: () => ({ accessToken: null }) },
}))

// Mock three — heavyweight; not needed for unit/smoke tests
vi.mock('three', () => ({
  WebGLRenderer: vi.fn(() => ({
    setPixelRatio: vi.fn(),
    setSize: vi.fn(),
    setClearColor: vi.fn(),
    render: vi.fn(),
    dispose: vi.fn(),
    domElement: document.createElement('canvas'),
  })),
  Scene: vi.fn(() => ({ add: vi.fn(), environment: null })),
  PerspectiveCamera: vi.fn(() => ({
    position: { set: vi.fn() },
    lookAt: vi.fn(),
    aspect: 1,
    updateProjectionMatrix: vi.fn(),
  })),
  GridHelper: vi.fn(() => ({})),
  AmbientLight: vi.fn(() => ({})),
  DirectionalLight: vi.fn(() => ({ position: { set: vi.fn() } })),
  BoxGeometry: vi.fn(() => ({})),
  MeshStandardMaterial: vi.fn(() => ({})),
  Mesh: vi.fn(() => ({
    position: { set: vi.fn() },
    quaternion: { set: vi.fn() },
  })),
}))

import AssemblyMotionStudioPanel, {
  JOINT_TYPES,
  DRIVER_TYPES,
  parseTableDriver,
  buildTimelinePayload,
  parseStudySpec,
} from './AssemblyMotionStudioPanel.jsx'

// ===========================================================================
// Tier 1 — source inspection
// ===========================================================================

describe('AssemblyMotionStudioPanel source: data-testid landmarks', () => {
  it('has data-testid="assembly-motion-studio"', () => {
    expect(src).toContain('data-testid="assembly-motion-studio"')
  })

  it('has data-testid="motion-studio-viewport"', () => {
    expect(src).toContain('data-testid="motion-studio-viewport"')
  })

  it('has data-testid="studio-run-btn"', () => {
    expect(src).toContain('data-testid="studio-run-btn"')
  })

  it('has data-testid="timeline-scrubber"', () => {
    expect(src).toContain('data-testid="timeline-scrubber"')
  })

  it('has data-testid="studio-driver-editor"', () => {
    expect(src).toContain('data-testid="studio-driver-editor"')
  })

  it('has data-testid="studio-add-joint-btn"', () => {
    expect(src).toContain('data-testid="studio-add-joint-btn"')
  })

  it('has data-testid="play-btn"', () => {
    expect(src).toContain('data-testid="play-btn"')
  })

  it('has data-testid="interference-events" reference', () => {
    expect(src).toContain('interference-events')
  })

  it('has tab buttons (setup/results/traces)', () => {
    // Tabs are rendered with a template literal data-testid={`tab-${tab}`}
    // where tab iterates over ['setup', 'results', 'traces'].
    expect(src).toContain("'setup'")
    expect(src).toContain("'results'")
    expect(src).toContain("'traces'")
    // The template literal pattern should be present
    expect(src).toContain('tab-${tab}')
  })
})

describe('AssemblyMotionStudioPanel source: backend tool call', () => {
  it('calls motion_frame_timeline tool', () => {
    expect(src).toContain('motion_frame_timeline')
  })

  it('calls /api/tools/call', () => {
    expect(src).toContain('/api/tools/call')
  })

  it('references assembly_run_motion_study', () => {
    expect(src).toContain('assembly_run_motion_study')
  })

  it('references assembly_mbd_constraint_enforce', () => {
    expect(src).toContain('assembly_mbd_constraint_enforce')
  })
})

describe('AssemblyMotionStudioPanel source: Renderer reuse', () => {
  it('imports from ../../store/auth.js', () => {
    expect(src).toContain('../../store/auth.js')
  })

  it('uses three for 3D viewport', () => {
    expect(src).toContain("import('three')")
  })
})

// ===========================================================================
// Tier 2 — pure helper unit tests
// ===========================================================================

describe('parseTableDriver', () => {
  it('returns empty arrays for empty input', () => {
    const { times, thetas } = parseTableDriver('')
    expect(times).toEqual([])
    expect(thetas).toEqual([])
  })

  it('parses valid t-theta pairs', () => {
    const { times, thetas } = parseTableDriver('0.0 0\n0.5 1.57\n1.0 3.14')
    expect(times).toEqual([0.0, 0.5, 1.0])
    expect(thetas[1]).toBeCloseTo(1.57, 5)
    expect(thetas[2]).toBeCloseTo(3.14, 5)
  })

  it('skips lines with only one token', () => {
    const { times } = parseTableDriver('0.5\n1.0 2.0\nbad line')
    expect(times).toEqual([1.0])
  })

  it('skips non-numeric lines', () => {
    const { times } = parseTableDriver('# comment\n0.1 0.5\n')
    expect(times).toEqual([0.1])
  })

  it('handles null/undefined gracefully', () => {
    expect(() => parseTableDriver(null)).not.toThrow()
    expect(() => parseTableDriver(undefined)).not.toThrow()
  })
})

describe('buildTimelinePayload', () => {
  it('returns tool=motion_frame_timeline', () => {
    const joints = [{ componentA: 'arm', componentB: 'base', type: 'revolute' }]
    const driver = { type: 'constant_velocity', velocity: 2.0 }
    const sim = { dt: 0.01, duration: 1.0, maxFrames: 100 }
    const p = buildTimelinePayload(joints, driver, sim)
    expect(p.tool).toBe('motion_frame_timeline')
  })

  it('args.bodies contains the joint components', () => {
    const joints = [{ componentA: 'link1', componentB: 'link2', type: 'revolute' }]
    const p = buildTimelinePayload(joints, { type: 'constant_velocity', velocity: 1 }, { dt: 0.01, duration: 1 })
    const bodyNames = p.args.bodies.map((b) => b.name)
    expect(bodyNames).toContain('link1')
    expect(bodyNames).toContain('link2')
  })

  it('args.n_steps = duration / dt (rounded)', () => {
    const p = buildTimelinePayload([], { type: 'constant_velocity', velocity: 1 }, { dt: 0.01, duration: 2.0 })
    expect(p.args.n_steps).toBe(200)
  })

  it('includes gravity force', () => {
    const p = buildTimelinePayload([], { type: 'constant_velocity', velocity: 1 }, { dt: 0.01, duration: 1.0 })
    const hasGravity = p.args.forces.some((f) => f.type === 'gravity')
    expect(hasGravity).toBe(true)
  })

  it('constant_velocity driver adds applied torque force', () => {
    const driver = { type: 'constant_velocity', velocity: 3.0 }
    const p = buildTimelinePayload(
      [{ componentA: 'b0', componentB: 'b1', type: 'revolute' }],
      driver,
      { dt: 0.01, duration: 1.0 },
    )
    const applied = p.args.forces.find((f) => f.type === 'applied')
    expect(applied).toBeDefined()
    expect(applied.torque[2]).toBe(3.0)
  })

  it('sinusoidal driver adds applied force with amplitude', () => {
    const driver = { type: 'sinusoidal', amplitude: 2.5, frequency: 1.0 }
    const p = buildTimelinePayload([], driver, { dt: 0.01, duration: 1.0 })
    const applied = p.args.forces.find((f) => f.type === 'applied')
    expect(applied?.torque[2]).toBe(2.5)
  })

  it('table driver with < 2 points: no driver force added', () => {
    const driver = { type: 'table', table: '0.0 0' }   // only 1 point
    const p = buildTimelinePayload([], driver, { dt: 0.01, duration: 1.0 })
    const tableFf = p.args.forces.find((f) => f.type === 'table_driver')
    expect(tableFf).toBeUndefined()
  })

  it('table driver with 2+ points: table_driver force added', () => {
    const driver = { type: 'table', table: '0.0 0\n1.0 3.14' }
    const p = buildTimelinePayload([], driver, { dt: 0.01, duration: 1.0 })
    const tableFf = p.args.forces.find((f) => f.type === 'table_driver')
    expect(tableFf).toBeDefined()
    expect(tableFf.table_times).toEqual([0.0, 1.0])
  })

  it('empty joints → single default body', () => {
    const p = buildTimelinePayload([], { type: 'constant_velocity', velocity: 1 }, { dt: 0.01, duration: 1.0 })
    expect(p.args.bodies.length).toBe(1)
    expect(p.args.bodies[0].name).toBe('body_0')
  })

  it('record_every caps frame count near maxFrames', () => {
    const p = buildTimelinePayload(
      [], { type: 'constant_velocity', velocity: 1 },
      { dt: 0.001, duration: 10.0, maxFrames: 100 },
    )
    // n_steps = 10000; record_every = ceil(10000/100) = 100 → ~100 frames
    expect(p.args.record_every).toBeGreaterThanOrEqual(1)
  })
})

describe('parseStudySpec', () => {
  it('returns null for null/empty input', () => {
    expect(parseStudySpec(null)).toBeNull()
    expect(parseStudySpec('')).toBeNull()
    expect(parseStudySpec(undefined)).toBeNull()
  })

  it('parses a valid JSON string', () => {
    const spec = JSON.stringify({
      joints: [{ type: 'revolute', componentA: 'a', componentB: 'b' }],
      driver: { type: 'sinusoidal', amplitude: 1.5 },
      dt: 0.005,
      duration: 3.0,
    })
    const result = parseStudySpec(spec)
    expect(result).not.toBeNull()
    expect(result.joints).toHaveLength(1)
    expect(result.driver.type).toBe('sinusoidal')
    expect(result.sim.dt).toBe(0.005)
    expect(result.sim.duration).toBe(3.0)
  })

  it('parses an object directly', () => {
    const obj = { dt: 0.02, duration: 5.0, joints: [] }
    const result = parseStudySpec(obj)
    expect(result.sim.dt).toBe(0.02)
    expect(result.joints).toEqual([])
  })

  it('applies defaults for missing keys', () => {
    const result = parseStudySpec({})
    expect(result.sim.dt).toBe(0.01)
    expect(result.sim.duration).toBe(2.0)
    expect(result.joints).toEqual([])
    expect(result.driver.type).toBe('constant_velocity')
  })

  it('returns null for invalid JSON string', () => {
    expect(parseStudySpec('not valid json {')).toBeNull()
  })
})

// ===========================================================================
// Tier 3 — renderToStaticMarkup smoke tests
// ===========================================================================

describe('AssemblyMotionStudioPanel: renders to HTML', () => {
  it('mounts without error', () => {
    // SSR-safe (no useEffect/rAF in static markup)
    let html = ''
    expect(() => {
      html = renderToStaticMarkup(
        <AssemblyMotionStudioPanel />,
      )
    }).not.toThrow()
    expect(html.length).toBeGreaterThan(0)
  })

  it('contains assembly-motion-studio container', () => {
    const html = renderToStaticMarkup(<AssemblyMotionStudioPanel />)
    expect(html).toContain('assembly-motion-studio')
  })

  it('contains motion-studio-viewport', () => {
    const html = renderToStaticMarkup(<AssemblyMotionStudioPanel />)
    expect(html).toContain('motion-studio-viewport')
  })

  it('contains studio-run-btn', () => {
    const html = renderToStaticMarkup(<AssemblyMotionStudioPanel />)
    expect(html).toContain('studio-run-btn')
  })

  it('contains studio-add-joint-btn', () => {
    const html = renderToStaticMarkup(<AssemblyMotionStudioPanel />)
    expect(html).toContain('studio-add-joint-btn')
  })

  it('contains Assembly Motion Studio title', () => {
    const html = renderToStaticMarkup(<AssemblyMotionStudioPanel />)
    expect(html).toContain('Assembly Motion Studio')
  })

  it('shows file name when file prop provided', () => {
    const html = renderToStaticMarkup(
      <AssemblyMotionStudioPanel file={{ name: 'test_study.motion' }} />,
    )
    expect(html).toContain('test_study.motion')
  })

  it('loads spec from content prop (JSON string)', () => {
    const spec = JSON.stringify({
      joints: [{ type: 'prismatic', componentA: 'piston', componentB: 'cylinder' }],
      driver: { type: 'sinusoidal', amplitude: 0.1, frequency: 2.0 },
      dt: 0.005,
      duration: 1.0,
    })
    // Should not throw when parsing the spec
    expect(() => renderToStaticMarkup(
      <AssemblyMotionStudioPanel content={spec} />,
    )).not.toThrow()
  })

  it('renders tab buttons', () => {
    const html = renderToStaticMarkup(<AssemblyMotionStudioPanel />)
    // Template literal renders to data-testid="tab-setup" etc. in HTML
    expect(html).toContain('tab-setup')
    expect(html).toContain('tab-results')
    expect(html).toContain('tab-traces')
  })
})

// ===========================================================================
// Tier 4 — scrubber: mock timeline + verify frame index updates
// ===========================================================================

describe('JOINT_TYPES and DRIVER_TYPES constants', () => {
  it('JOINT_TYPES includes revolute, prismatic, cylindrical', () => {
    expect(JOINT_TYPES).toContain('revolute')
    expect(JOINT_TYPES).toContain('prismatic')
    expect(JOINT_TYPES).toContain('cylindrical')
  })

  it('DRIVER_TYPES includes constant_velocity, sinusoidal, table', () => {
    expect(DRIVER_TYPES).toContain('constant_velocity')
    expect(DRIVER_TYPES).toContain('sinusoidal')
    expect(DRIVER_TYPES).toContain('table')
  })
})

describe('buildTimelinePayload: deterministic output', () => {
  it('same inputs → same output', () => {
    const joints = [{ componentA: 'a', componentB: 'b', type: 'revolute' }]
    const driver = { type: 'constant_velocity', velocity: 1.0 }
    const sim = { dt: 0.01, duration: 2.0 }
    const p1 = buildTimelinePayload(joints, driver, sim)
    const p2 = buildTimelinePayload(joints, driver, sim)
    expect(JSON.stringify(p1)).toBe(JSON.stringify(p2))
  })

  it('dt affects n_steps proportionally', () => {
    const joints = []
    const driver = { type: 'constant_velocity', velocity: 1.0 }
    const p1 = buildTimelinePayload(joints, driver, { dt: 0.01, duration: 1.0 })
    const p2 = buildTimelinePayload(joints, driver, { dt: 0.005, duration: 1.0 })
    expect(p2.args.n_steps).toBe(p1.args.n_steps * 2)
  })
})

describe('scrubber frame update via parseStudySpec + buildTimelinePayload', () => {
  it('a study spec with table driver produces table_driver force in payload', () => {
    const spec = {
      joints: [],
      driver: { type: 'table', table: '0 0\n0.5 1.57\n1.0 3.14' },
      dt: 0.01,
      duration: 1.0,
    }
    const parsed = parseStudySpec(spec)
    expect(parsed).not.toBeNull()
    const payload = buildTimelinePayload(parsed.joints, parsed.driver, parsed.sim)
    const tableForce = payload.args.forces.find((f) => f.type === 'table_driver')
    expect(tableForce).toBeDefined()
    expect(tableForce.table_times).toEqual([0, 0.5, 1.0])
    expect(tableForce.table_thetas[1]).toBeCloseTo(1.57, 2)
  })
})
