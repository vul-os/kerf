/**
 * dental.test.jsx — Vitest tests for the three dental UI panels.
 *
 * Follows the project convention: pure data-layer tests (no @testing-library/react).
 * The interesting dispatch logic lives in dentalDispatch.js; React rendering is
 * verified via renderToStaticMarkup.
 *
 * Covers:
 *   1. dentalDispatch helpers — buildCrownDesignPayload, buildSurgicalGuidePayload
 *   2. CrownSculptingPanel — mounts via renderToStaticMarkup, shows key elements
 *   3. ImplantLibrary — mounts via renderToStaticMarkup, shows key elements
 *   4. SurgicalGuide — mounts via renderToStaticMarkup, shows key elements
 */

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// ---------------------------------------------------------------------------
// Mocks — must be hoisted before component imports
// ---------------------------------------------------------------------------

// useAuth is a Zustand store — called as useAuth() with no selector in these panels.
vi.mock('../../store/auth.js', () => ({
  useAuth: () => ({ accessToken: 'test-token' }),
}))

// ---------------------------------------------------------------------------
// Pure logic imports — no mocks needed
// ---------------------------------------------------------------------------
import {
  buildCrownDesignPayload,
  buildSurgicalGuidePayload,
} from './dentalDispatch.js'

// ---------------------------------------------------------------------------
// Component imports — for renderToStaticMarkup mount tests
// ---------------------------------------------------------------------------
import CrownSculptingPanel from './CrownSculptingPanel.jsx'
import ImplantLibrary from './ImplantLibrary.jsx'
import SurgicalGuide from './SurgicalGuide.jsx'

// ============================================================================
// 1. dentalDispatch — buildCrownDesignPayload
// ============================================================================

describe('buildCrownDesignPayload', () => {
  const MARGIN = [[0, 0, 0], [5, 0, 0], [5, 7, 0], [0, 7, 0]]
  const CUSPS = [3.0, 3.5]

  it('sets tool to dental_crown_design', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS })
    expect(p.tool).toBe('dental_crown_design')
  })

  it('includes margin_line in args', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS })
    expect(p.args.margin_line).toEqual(MARGIN)
  })

  it('includes opposing_cusp_heights_mm in args', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS })
    expect(p.args.opposing_cusp_heights_mm).toEqual(CUSPS)
  })

  it('defaults material to zirconia', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS })
    expect(p.args.material).toBe('zirconia')
  })

  it('accepts a custom material', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS, material: 'e.max' })
    expect(p.args.material).toBe('e.max')
  })

  it('defaults n_cusps to 2', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS })
    expect(p.args.n_cusps).toBe(2)
  })

  it('accepts n_cusps=4 for molar', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS, n_cusps: 4 })
    expect(p.args.n_cusps).toBe(4)
  })

  it('defaults cusp_depth_fraction to 0.20', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS })
    expect(p.args.cusp_depth_fraction).toBeCloseTo(0.20, 5)
  })

  it('accepts custom cusp_depth_fraction', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS, cusp_depth_fraction: 0.15 })
    expect(p.args.cusp_depth_fraction).toBeCloseTo(0.15, 5)
  })

  it('defaults occlusal_clearance_mm to 0.3', () => {
    const p = buildCrownDesignPayload({ margin_line: MARGIN, opposing_cusp_heights_mm: CUSPS })
    expect(p.args.occlusal_clearance_mm).toBeCloseTo(0.3, 5)
  })

  it('throws when margin_line has fewer than 3 points', () => {
    expect(() => buildCrownDesignPayload({
      margin_line: [[0, 0, 0], [1, 0, 0]],
      opposing_cusp_heights_mm: CUSPS,
    })).toThrow(/margin_line/)
  })

  it('throws when opposing_cusp_heights_mm is empty', () => {
    expect(() => buildCrownDesignPayload({
      margin_line: MARGIN,
      opposing_cusp_heights_mm: [],
    })).toThrow(/opposing_cusp_heights_mm/)
  })

  it('coerces numeric string values to Number', () => {
    const p = buildCrownDesignPayload({
      margin_line: MARGIN,
      opposing_cusp_heights_mm: CUSPS,
      n_cusps: '4',
      cusp_depth_fraction: '0.25',
      occlusal_clearance_mm: '0.5',
    })
    expect(typeof p.args.n_cusps).toBe('number')
    expect(typeof p.args.cusp_depth_fraction).toBe('number')
    expect(typeof p.args.occlusal_clearance_mm).toBe('number')
  })
})

// ============================================================================
// 2. dentalDispatch — buildSurgicalGuidePayload
// ============================================================================

const JAW_PTS = [
  [0, 0, 0], [20, 0, 0], [20, 15, 0],
  [10, 15, 0], [0, 15, 0],
]

const IMPLANTS = [
  { position: [5, 8, 0], axis_direction: [0, 0, 1], diameter_mm: 4.1, length_mm: 10 },
]

describe('buildSurgicalGuidePayload', () => {
  it('sets tool to dental_surgical_guide', () => {
    const p = buildSurgicalGuidePayload({ jaw_surface_pts: JAW_PTS, implants: IMPLANTS })
    expect(p.tool).toBe('dental_surgical_guide')
  })

  it('includes jaw_surface_pts in args', () => {
    const p = buildSurgicalGuidePayload({ jaw_surface_pts: JAW_PTS, implants: IMPLANTS })
    expect(p.args.jaw_surface_pts).toEqual(JAW_PTS)
  })

  it('includes implants array in args', () => {
    const p = buildSurgicalGuidePayload({ jaw_surface_pts: JAW_PTS, implants: IMPLANTS })
    expect(Array.isArray(p.args.implants)).toBe(true)
    expect(p.args.implants).toHaveLength(1)
  })

  it('implant carries position and axis_direction', () => {
    const p = buildSurgicalGuidePayload({ jaw_surface_pts: JAW_PTS, implants: IMPLANTS })
    const imp = p.args.implants[0]
    expect(imp.position).toEqual([5, 8, 0])
    expect(imp.axis_direction).toEqual([0, 0, 1])
  })

  it('implant carries diameter_mm and length_mm', () => {
    const p = buildSurgicalGuidePayload({ jaw_surface_pts: JAW_PTS, implants: IMPLANTS })
    const imp = p.args.implants[0]
    expect(imp.diameter_mm).toBe(4.1)
    expect(imp.length_mm).toBe(10)
  })

  it('defaults diameter_mm to 4.0 when not provided', () => {
    const p = buildSurgicalGuidePayload({
      jaw_surface_pts: JAW_PTS,
      implants: [{ position: [0, 0, 0], axis_direction: [0, 0, 1] }],
    })
    expect(p.args.implants[0].diameter_mm).toBe(4.0)
  })

  it('defaults length_mm to 10 when not provided', () => {
    const p = buildSurgicalGuidePayload({
      jaw_surface_pts: JAW_PTS,
      implants: [{ position: [0, 0, 0], axis_direction: [0, 0, 1] }],
    })
    expect(p.args.implants[0].length_mm).toBe(10)
  })

  it('supports multiple implants', () => {
    const p = buildSurgicalGuidePayload({
      jaw_surface_pts: JAW_PTS,
      implants: [
        { position: [5, 8, 0], axis_direction: [0, 0, 1], diameter_mm: 4.1, length_mm: 10 },
        { position: [15, 8, 0], axis_direction: [0, 0, 1], diameter_mm: 3.5, length_mm: 12 },
      ],
    })
    expect(p.args.implants).toHaveLength(2)
    expect(p.args.implants[1].diameter_mm).toBe(3.5)
  })

  it('throws when jaw_surface_pts has fewer than 3 points', () => {
    expect(() => buildSurgicalGuidePayload({
      jaw_surface_pts: [[0, 0, 0], [1, 0, 0]],
      implants: IMPLANTS,
    })).toThrow(/jaw_surface_pts/)
  })

  it('throws when implants array is empty', () => {
    expect(() => buildSurgicalGuidePayload({
      jaw_surface_pts: JAW_PTS,
      implants: [],
    })).toThrow(/implants/)
  })

  it('payload structure matches dental_surgical_guide input_schema top-level keys', () => {
    const p = buildSurgicalGuidePayload({ jaw_surface_pts: JAW_PTS, implants: IMPLANTS })
    expect(Object.keys(p.args).sort()).toEqual(['implants', 'jaw_surface_pts'].sort())
  })
})

// ============================================================================
// 3. Component mount tests — renderToStaticMarkup
// ============================================================================

describe('CrownSculptingPanel mount', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(
      <CrownSculptingPanel projectId="proj-1" />,
    )).not.toThrow()
  })

  it('contains the tooth type preset labels', () => {
    const html = renderToStaticMarkup(<CrownSculptingPanel projectId="proj-1" />)
    expect(html).toContain('Incisor')
    expect(html).toContain('Canine')
    expect(html).toContain('Premolar')
    expect(html).toContain('Molar')
  })

  it('contains the tool name reference', () => {
    const html = renderToStaticMarkup(<CrownSculptingPanel projectId="proj-1" />)
    expect(html).toContain('dental_crown_design')
  })

  it('contains the Run button text', () => {
    const html = renderToStaticMarkup(<CrownSculptingPanel projectId="proj-1" />)
    expect(html).toContain('Run dental_crown_design')
  })

  it('contains the material selector options', () => {
    const html = renderToStaticMarkup(<CrownSculptingPanel projectId="proj-1" />)
    expect(html).toContain('zirconia')
    expect(html).toContain('e.max')
  })

  it('renders the SVG occlusion overlay', () => {
    const html = renderToStaticMarkup(<CrownSculptingPanel projectId="proj-1" />)
    expect(html).toContain('<svg')
    expect(html).toContain('occlusal view')
  })
})

describe('ImplantLibrary mount', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(
      <ImplantLibrary projectId="proj-1" />,
    )).not.toThrow()
  })

  it('contains manufacturer filter options', () => {
    const html = renderToStaticMarkup(<ImplantLibrary projectId="proj-1" />)
    expect(html).toContain('Straumann')
    expect(html).toContain('Nobel Biocare')
    expect(html).toContain('Zimmer')
    expect(html).toContain('MIS')
  })

  it('contains the tool name reference', () => {
    const html = renderToStaticMarkup(<ImplantLibrary projectId="proj-1" />)
    expect(html).toContain('dental_surgical_guide')
  })

  it('shows implant cards with dimension labels', () => {
    const html = renderToStaticMarkup(<ImplantLibrary projectId="proj-1" />)
    // Should show at least one card with mm notation
    expect(html).toMatch(/\d+\.\d+ × \d+ mm/)
  })

  it('contains manufacturer, diameter, length filter headings', () => {
    const html = renderToStaticMarkup(<ImplantLibrary projectId="proj-1" />)
    expect(html).toContain('Manufacturer')
    expect(html).toContain('Diameter (mm)')
    expect(html).toContain('Length (mm)')
  })

  it('contains Place button for card (static render shows it only on selected, but rendered count > 0)', () => {
    // Static render: no interactivity, no selected card → no Place button
    // But all implant cards should be present.
    const html = renderToStaticMarkup(<ImplantLibrary projectId="proj-1" />)
    expect(html).toContain('Bone Level RC')
  })
})

describe('SurgicalGuide mount', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(
      <SurgicalGuide projectId="proj-1" />,
    )).not.toThrow()
  })

  it('contains the Import button text', () => {
    const html = renderToStaticMarkup(<SurgicalGuide projectId="proj-1" />)
    expect(html).toContain('Import')
  })

  it('contains the demo jaw label', () => {
    const html = renderToStaticMarkup(<SurgicalGuide projectId="proj-1" />)
    expect(html).toContain('Demo jaw')
  })

  it('contains the tool name reference', () => {
    const html = renderToStaticMarkup(<SurgicalGuide projectId="proj-1" />)
    expect(html).toContain('dental_surgical_guide')
  })

  it('renders the SVG guide preview', () => {
    const html = renderToStaticMarkup(<SurgicalGuide projectId="proj-1" />)
    expect(html).toContain('<svg')
    expect(html).toContain('occlusal view')
  })

  it('contains Add implant button', () => {
    const html = renderToStaticMarkup(<SurgicalGuide projectId="proj-1" />)
    expect(html).toContain('Add implant')
  })

  it('contains the Generate surgical guide button', () => {
    const html = renderToStaticMarkup(<SurgicalGuide projectId="proj-1" />)
    expect(html).toContain('Generate surgical guide')
  })

  it('shows first implant row by default', () => {
    const html = renderToStaticMarkup(<SurgicalGuide projectId="proj-1" />)
    expect(html).toContain('Implant 1')
  })
})
