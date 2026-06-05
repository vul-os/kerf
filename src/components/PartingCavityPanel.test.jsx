/**
 * PartingCavityPanel.test.jsx
 *
 * Tests for pure helpers + basic rendering of the parting-cavity panel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PartingCavityPanel, {
  parsePartingResult,
  detectMode,
  classifyColor,
  fmtMm,
} from './PartingCavityPanel.jsx'

// ---------------------------------------------------------------------------
// parsePartingResult
// ---------------------------------------------------------------------------

describe('parsePartingResult', () => {
  it('returns empty for blank content', () => {
    expect(parsePartingResult('').kind).toBe('empty')
  })

  it('returns invalid for bad JSON', () => {
    expect(parsePartingResult('not json').kind).toBe('invalid')
  })

  it('returns invalid when ok is false', () => {
    const r = parsePartingResult(JSON.stringify({ ok: false, reason: 'BAD_ARGS' }))
    expect(r.kind).toBe('invalid')
  })

  it('returns invalid when mode is unknown', () => {
    const r = parsePartingResult(JSON.stringify({ ok: true, foo: 'bar' }))
    expect(r.kind).toBe('invalid')
  })

  it('parses a parting-line result', () => {
    const doc = {
      ok: true,
      segments: [
        { edge_id: 'E0', classification: 'silhouette', p_start: [0,0,0], p_end: [10,0,0], length_mm: 10 },
      ],
      total_length_mm: 10.0,
      closed_loops: 1,
      has_undercuts: false,
      undercut_face_ids: [],
      draft_deficient_face_ids: [],
      honest_caveat: 'Planar pull only',
    }
    const r = parsePartingResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.mode).toBe('parting_line')
    expect(r.data.total_length_mm).toBe(10.0)
  })

  it('parses a split result', () => {
    const doc = {
      ok: true,
      parting_surface: { surface_type: 'planar', plane_point: [0,0,5] },
      cavity_body: { min_z: 5 },
      core_body: { max_z: 5 },
      insert_count: 2,
      parting_surface_complexity: 'planar',
      has_sliders_needed: false,
      has_lifters_needed: false,
      honest_caveat: 'Bbox descriptors only',
    }
    const r = parsePartingResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.mode).toBe('split')
    expect(r.data.insert_count).toBe(2)
  })

  it('unwraps { result: {...} } wrapper', () => {
    const doc = {
      tool: 'mold_detect_parting_line',
      result: {
        ok: true,
        segments: [],
        total_length_mm: 0,
        closed_loops: 0,
        has_undercuts: false,
        undercut_face_ids: [],
        draft_deficient_face_ids: [],
      },
    }
    const r = parsePartingResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.mode).toBe('parting_line')
  })
})

// ---------------------------------------------------------------------------
// detectMode
// ---------------------------------------------------------------------------

describe('detectMode', () => {
  it('returns parting_line when segments + closed_loops present', () => {
    expect(detectMode({ segments: [], closed_loops: 0 })).toBe('parting_line')
  })

  it('returns split when parting_surface + cavity_body present', () => {
    expect(detectMode({ parting_surface: {}, cavity_body: {} })).toBe('split')
  })

  it('returns unknown for empty object', () => {
    expect(detectMode({})).toBe('unknown')
  })

  it('returns unknown for null', () => {
    expect(detectMode(null)).toBe('unknown')
  })
})

// ---------------------------------------------------------------------------
// classifyColor
// ---------------------------------------------------------------------------

describe('classifyColor', () => {
  it('returns green for silhouette', () => {
    expect(classifyColor('silhouette')).toBe('#34d399')
  })

  it('returns red for undercut_boundary', () => {
    expect(classifyColor('undercut_boundary')).toBe('#f87171')
  })

  it('returns amber for sharp_edge', () => {
    expect(classifyColor('sharp_edge')).toBe('#fbbf24')
  })

  it('returns grey for unknown classification', () => {
    expect(classifyColor('whatever')).toBe('#94a3b8')
  })
})

// ---------------------------------------------------------------------------
// fmtMm
// ---------------------------------------------------------------------------

describe('fmtMm', () => {
  it('formats to 2 decimal places by default', () => {
    expect(fmtMm(123.456)).toBe('123.46 mm')
  })

  it('respects digits param', () => {
    expect(fmtMm(10.0, 0)).toBe('10 mm')
  })

  it('returns — for null', () => {
    expect(fmtMm(null)).toBe('—')
  })

  it('returns — for undefined', () => {
    expect(fmtMm(undefined)).toBe('—')
  })
})

// ---------------------------------------------------------------------------
// Component rendering
// ---------------------------------------------------------------------------

describe('PartingCavityPanel rendering', () => {
  it('renders empty state when content is blank', () => {
    const html = renderToStaticMarkup(PartingCavityPanel({ parsedContent: '' }))
    expect(html).toContain('No parting-line result loaded')
  })

  it('renders error state for invalid JSON', () => {
    const html = renderToStaticMarkup(PartingCavityPanel({ parsedContent: 'bad json' }))
    expect(html).toContain('Could not parse')
  })

  it('renders Parting-Line Detection title for parting_line mode', () => {
    const doc = {
      ok: true,
      segments: [
        { edge_id: 'E0', classification: 'silhouette', p_start: [0,0,0], p_end: [10,0,0], length_mm: 10 },
      ],
      total_length_mm: 120.5,
      closed_loops: 1,
      has_undercuts: false,
      undercut_face_ids: [],
      draft_deficient_face_ids: [],
    }
    const html = renderToStaticMarkup(PartingCavityPanel({ parsedContent: JSON.stringify(doc) }))
    expect(html).toContain('Parting-Line Detection')
    expect(html).toContain('120.50 mm')
    expect(html).toContain('silhouette')
  })

  it('renders undercut warning when undercuts detected', () => {
    const doc = {
      ok: true,
      segments: [
        { edge_id: 'E1', classification: 'undercut_boundary', p_start: [0,0,0], p_end: [5,0,0], length_mm: 5 },
      ],
      total_length_mm: 5,
      closed_loops: 0,
      has_undercuts: true,
      undercut_face_ids: ['F2', 'F3'],
      draft_deficient_face_ids: [],
    }
    const html = renderToStaticMarkup(PartingCavityPanel({ parsedContent: JSON.stringify(doc) }))
    expect(html).toContain('Undercut')
    expect(html).toContain('F2')
  })

  it('renders Cavity / Core Split title for split mode', () => {
    const doc = {
      ok: true,
      parting_surface: { surface_type: 'planar', plane_point: [0,0,5] },
      cavity_body: { min_z: 5, label: 'cavity' },
      core_body: { max_z: 5, label: 'core' },
      insert_count: 3,
      parting_surface_complexity: 'planar',
      has_sliders_needed: true,
      has_lifters_needed: false,
      honest_caveat: 'Bbox only',
    }
    const html = renderToStaticMarkup(PartingCavityPanel({ parsedContent: JSON.stringify(doc) }))
    expect(html).toContain('Cavity / Core Split')
    expect(html).toContain('Sliders')
    expect(html).toContain('planar')
  })

  it('renders honest caveat when present', () => {
    const doc = {
      ok: true,
      segments: [],
      total_length_mm: 0,
      closed_loops: 0,
      has_undercuts: false,
      undercut_face_ids: [],
      draft_deficient_face_ids: [],
      honest_caveat: 'Hayrettin 2003 §3 — planar pull only',
    }
    const html = renderToStaticMarkup(PartingCavityPanel({ parsedContent: JSON.stringify(doc) }))
    expect(html).toContain('Hayrettin')
  })

  it('accepts object prop directly', () => {
    const doc = {
      ok: true,
      parting_surface: { surface_type: 'free-form' },
      cavity_body: {},
      core_body: {},
      insert_count: 1,
      parting_surface_complexity: 'free-form',
      has_sliders_needed: false,
      has_lifters_needed: false,
    }
    const html = renderToStaticMarkup(PartingCavityPanel({ parsedContent: doc }))
    expect(html).toContain('Cavity / Core Split')
  })
})
