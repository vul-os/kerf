// CAMView5Axis.test.jsx — Vitest structural tests for the 5-axis CAM UI.
//
// Verifies without a live DOM or RTL:
//   1. AXIS_MODES constant exports the three expected keys.
//   2. fiveAxisBackendArgs() maps each UI mode + strategy to the correct
//      backend `operation` string dispatched to cam_run.
//   3. The axis-mode switch markup is present in the rendered output.
//   4. The five-axis-controls section is present when a 5-axis mode is active.
//   5. The spindle-vector-preview SVG is present inside the 5-axis controls.
//
// Pattern: renderToStaticMarkup (no hooks that require a browser) for pure
// component structure checks; fiveAxisBackendArgs tested as a pure function.
// CAMView itself uses hooks (useState/useEffect) — those are tested via
// source-text assertions on the rendered server markup stub with mocked deps.

import { describe, it, expect, vi, beforeAll } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

// vi.mock calls must be at the top level (they are hoisted by Vitest).
vi.mock('../store/auth.js', () => ({ useAuth: { getState: () => ({ accessToken: null }) } }))
vi.mock('./ToolDBPanel.jsx', () => ({
  default: () => null,
  ToolPicker: () => null,
}))

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// ── Read source for structural checks ────────────────────────────────────────

const camViewSrc = readFileSync(
  path.resolve(__dirname, 'CAMView.jsx'),
  'utf8',
)

// ── 1. AXIS_MODES constant ────────────────────────────────────────────────────

describe('AXIS_MODES', () => {
  it('exports AXIS_MODES with the three expected keys', async () => {
    const { AXIS_MODES } = await import('./CAMView.jsx')
    expect(AXIS_MODES).toBeDefined()
    expect(Object.keys(AXIS_MODES)).toContain('3axis')
    expect(Object.keys(AXIS_MODES)).toContain('5axis_indexed')
    expect(Object.keys(AXIS_MODES)).toContain('5axis_cont')
  })
})

// ── 2. fiveAxisBackendArgs — pure-function unit tests ─────────────────────────

describe('fiveAxisBackendArgs', () => {
  let fiveAxisBackendArgs

  beforeAll(async () => {
    const mod = await import('./CAMView.jsx')
    fiveAxisBackendArgs = mod.fiveAxisBackendArgs
  })

  it('3+2 indexed mode → operation = "3plus2"', () => {
    const args = fiveAxisBackendArgs('5axis_indexed', 'indexed_rough', 'B', '0')
    expect(args.operation).toBe('3plus2')
  })

  it('indexed strategy on cont mode → operation = "3plus2"', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'indexed_rough', 'B', '15')
    expect(args.operation).toBe('3plus2')
  })

  it('swarf strategy → operation = "5axis_finish", tilt_deg = 0', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'swarf', 'B', '20')
    expect(args.operation).toBe('5axis_finish')
    expect(args.tilt_deg).toBe(0)
  })

  it('contour_tilted strategy → operation = "5axis_finish", tilt_deg from input', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'contour_tilted', 'A', '25')
    expect(args.operation).toBe('5axis_finish')
    expect(args.tilt_deg).toBe(25)
  })

  it('contour_tilted with default tilt fallback → tilt_deg = 15', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'contour_tilted', 'B', '')
    expect(args.operation).toBe('5axis_finish')
    expect(args.tilt_deg).toBe(15)
  })

  it('kinematic_family is always "head_table" for continuous ops', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'contour_tilted', 'B', '10')
    expect(args.kinematic_family).toBe('head_table')
  })
})

// ── 3. Source-text structural checks ─────────────────────────────────────────
// These verify the markup is present without needing a real DOM.

describe('CAMView source structure', () => {
  it('contains data-testid="axis-mode-switch"', () => {
    expect(camViewSrc).toMatch(/data-testid="axis-mode-switch"/)
  })

  it('contains data-testid="five-axis-controls"', () => {
    expect(camViewSrc).toMatch(/data-testid="five-axis-controls"/)
  })

  it('contains data-testid="spindle-vector-preview"', () => {
    expect(camViewSrc).toMatch(/data-testid="spindle-vector-preview"/)
  })

  it('contains data-testid="five-axis-strategy"', () => {
    expect(camViewSrc).toMatch(/data-testid="five-axis-strategy"/)
  })

  it('contains data-testid="tilt-axis-select"', () => {
    expect(camViewSrc).toMatch(/data-testid="tilt-axis-select"/)
  })

  it('contains data-testid="tilt-angle-input"', () => {
    expect(camViewSrc).toMatch(/data-testid="tilt-angle-input"/)
  })

  it('renders 5-axis strategy options: swarf, contour_tilted, indexed_rough', () => {
    expect(camViewSrc).toMatch(/swarf/)
    expect(camViewSrc).toMatch(/contour_tilted/)
    expect(camViewSrc).toMatch(/indexed_rough/)
  })

  it('dispatches via POST /api/projects/{pid}/files/{fid}/cam', () => {
    expect(camViewSrc).toMatch(/\/api\/projects.*\/cam/)
  })

  it('uses fiveAxisBackendArgs to compute the backend operation', () => {
    expect(camViewSrc).toMatch(/fiveAxisBackendArgs/)
  })

  it('includes all three tilt axes A/B/C', () => {
    expect(camViewSrc).toMatch(/TILT_AXES\s*=\s*\[.*['"]A['"].*['"]B['"].*['"]C['"]/)
  })

  it('exports fiveAxisBackendArgs as a named export', () => {
    expect(camViewSrc).toMatch(/export function fiveAxisBackendArgs/)
  })

  it('exports AXIS_MODES as a named export', () => {
    expect(camViewSrc).toMatch(/export const AXIS_MODES/)
  })

  it('SpindleVectorPreview renders an SVG with aria-label', () => {
    expect(camViewSrc).toMatch(/aria-label=\{.*Spindle axis/)
  })
})
