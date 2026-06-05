/**
 * CMMInspectionPanel.test.jsx
 *
 * Tests for pure helpers + basic rendering of the CMM inspection panel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CMMInspectionPanel, {
  parseCMMFile,
  fmtMm,
  inTolerance,
  detectCMMTool,
} from './CMMInspectionPanel.jsx'

// ---------------------------------------------------------------------------
// parseCMMFile
// ---------------------------------------------------------------------------

describe('parseCMMFile', () => {
  it('returns empty for blank content', () => {
    expect(parseCMMFile('').kind).toBe('empty')
  })

  it('returns invalid for bad JSON', () => {
    const r = parseCMMFile('not json')
    expect(r.kind).toBe('invalid')
  })

  it('returns invalid when ok is false', () => {
    const r = parseCMMFile(JSON.stringify({ ok: false, reason: 'no points' }))
    expect(r.kind).toBe('invalid')
    expect(r.error).toContain('no points')
  })

  it('accepts wrapped { tool, result } format', () => {
    const r = parseCMMFile(JSON.stringify({
      tool: 'cmm_fit_geometry',
      result: { ok: true, shape: 'plane', form_error: 0.005 },
    }))
    expect(r.kind).toBe('ok')
    expect(r.tool).toBe('cmm_fit_geometry')
    expect(r.result.form_error).toBeCloseTo(0.005)
  })

  it('accepts direct tool-output objects', () => {
    const r = parseCMMFile(JSON.stringify({ ok: true, cpk: 1.45, ppk: 1.38, usl: 10.1, lsl: 9.9, mean: 10.0, sigma: 0.02 }))
    expect(r.kind).toBe('ok')
    expect(r.result.cpk).toBe(1.45)
  })
})

// ---------------------------------------------------------------------------
// fmtMm
// ---------------------------------------------------------------------------

describe('fmtMm', () => {
  it('formats to 4 decimal places by default', () => {
    expect(fmtMm(1.23456)).toBe('1.2346 mm')
  })

  it('respects custom digits', () => {
    expect(fmtMm(1.23, 2)).toBe('1.23 mm')
  })

  it('returns — for null/undefined/NaN', () => {
    expect(fmtMm(null)).toBe('—')
    expect(fmtMm(undefined)).toBe('—')
    expect(fmtMm(NaN)).toBe('—')
  })

  it('formats zero correctly', () => {
    expect(fmtMm(0)).toBe('0.0000 mm')
  })
})

// ---------------------------------------------------------------------------
// inTolerance
// ---------------------------------------------------------------------------

describe('inTolerance', () => {
  it('returns true when value within tolerance', () => {
    expect(inTolerance(0.003, 0.005)).toBe(true)
  })

  it('returns false when value exceeds tolerance', () => {
    expect(inTolerance(0.006, 0.005)).toBe(false)
  })

  it('returns null when tolerance is missing', () => {
    expect(inTolerance(0.003, null)).toBeNull()
    expect(inTolerance(0.003, undefined)).toBeNull()
  })

  it('returns null when value is missing', () => {
    expect(inTolerance(null, 0.01)).toBeNull()
  })

  it('handles negative values (uses abs)', () => {
    expect(inTolerance(-0.003, 0.005)).toBe(true)
    expect(inTolerance(-0.007, 0.005)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// detectCMMTool
// ---------------------------------------------------------------------------

describe('detectCMMTool', () => {
  it('detects from tool name prefix', () => {
    expect(detectCMMTool('cmm_fit_geometry', {})).toBe('fit_geometry')
    expect(detectCMMTool('cmm_eval_gdt', {})).toBe('eval_gdt')
    expect(detectCMMTool('cmm_gauge_rr', {})).toBe('gauge_rr')
    expect(detectCMMTool('cmm_process_capability', {})).toBe('process_capability')
    expect(detectCMMTool('cmm_recommend_samples', {})).toBe('recommend_samples')
  })

  it('detects from result keys when tool is null', () => {
    expect(detectCMMTool(null, { form_error: 0.001, shape: 'plane' })).toBe('fit_geometry')
    expect(detectCMMTool(null, { zone_width: 0.02, characteristic: 'flatness' })).toBe('eval_gdt')
    expect(detectCMMTool(null, { positional_deviation: 0.03 })).toBe('eval_position')
    expect(detectCMMTool(null, { profile_value: 0.04 })).toBe('eval_profile')
    expect(detectCMMTool(null, { expanded_uncertainty: 0.001 })).toBe('gum_uncertainty')
    expect(detectCMMTool(null, { compensated_pts: [] })).toBe('probe_compensate')
    expect(detectCMMTool(null, { n_recommended: 20 })).toBe('recommend_samples')
    expect(detectCMMTool(null, { grr: 0.05 })).toBe('gauge_rr')
    expect(detectCMMTool(null, { cpk: 1.5, ppk: 1.4 })).toBe('process_capability')
  })

  it('returns unknown for unrecognised result', () => {
    expect(detectCMMTool(null, { foo: 'bar' })).toBe('unknown')
  })
})

// ---------------------------------------------------------------------------
// Component rendering (renderToStaticMarkup)
// ---------------------------------------------------------------------------

describe('CMMInspectionPanel — render', () => {
  it('renders empty state when no content', () => {
    const html = renderToStaticMarkup(<CMMInspectionPanel rawContent="" />)
    expect(html).toContain('CMM')
    expect(html).toContain('cmm_')
  })

  it('renders error state for invalid JSON', () => {
    const html = renderToStaticMarkup(<CMMInspectionPanel rawContent="{{" />)
    // error box shows the JSON parse error message
    expect(html).toContain('JSON')
  })

  it('renders geometry fit result', () => {
    const data = {
      tool: 'cmm_fit_geometry',
      result: { ok: true, shape: 'plane', form_error: 0.0043, rms: 0.0015 },
    }
    const html = renderToStaticMarkup(<CMMInspectionPanel rawContent={JSON.stringify(data)} />)
    expect(html).toContain('Geometry Fit')
    expect(html).toContain('Form error')
    expect(html).toContain('0.0043')
  })

  it('renders GD&T eval result with pass/fail', () => {
    const data = {
      tool: 'cmm_eval_gdt',
      result: {
        ok: true,
        characteristic: 'flatness',
        zone_width: 0.003,
        tolerance: 0.005,
        in_tolerance: true,
      },
    }
    const html = renderToStaticMarkup(<CMMInspectionPanel rawContent={JSON.stringify(data)} />)
    // HTML-entity encodes & → &amp;
    expect(html).toContain('GD&amp;T')
    expect(html).toContain('Zone width')
    expect(html).toContain('PASS')
  })

  it('renders process capability result', () => {
    const data = {
      tool: 'cmm_process_capability',
      result: {
        ok: true,
        cpk: 1.45,
        ppk: 1.38,
        mean: 25.01,
        sigma: 0.015,
        usl: 25.1,
        lsl: 24.9,
        defect_ppm: 3.4,
        yield_pct: 99.9997,
        warnings: [],
      },
    }
    const html = renderToStaticMarkup(<CMMInspectionPanel rawContent={JSON.stringify(data)} />)
    expect(html).toContain('Process Capability')
    expect(html).toContain('Cpk')
    expect(html).toContain('1.450')
    expect(html).toContain('CAPABLE')
  })

  it('renders gauge R&R result', () => {
    const data = {
      tool: 'cmm_gauge_rr',
      result: {
        ok: true,
        grr: 0.045,
        ev: 0.03,
        av: 0.033,
        pv: 0.21,
        tv: 0.215,
        pct_study_var: 8.9,
        ndc: 6,
      },
    }
    const html = renderToStaticMarkup(<CMMInspectionPanel rawContent={JSON.stringify(data)} />)
    // HTML-entity encodes & → &amp;
    expect(html).toContain('Gauge R&amp;R')
    expect(html).toContain('CAPABLE')
  })

  it('renders GUM uncertainty result', () => {
    const data = {
      tool: 'cmm_gum_uncertainty',
      result: {
        ok: true,
        uc: 0.00234,
        U: 0.00468,
        coverage_factor: 2.0,
      },
    }
    const html = renderToStaticMarkup(<CMMInspectionPanel rawContent={JSON.stringify(data)} />)
    expect(html).toContain('Uncertainty')
    expect(html).toContain('0.00234')
  })

  it('renders filename in header', () => {
    const html = renderToStaticMarkup(
      <CMMInspectionPanel rawContent="" fileName="bracket_inspection.cmm" />
    )
    expect(html).toContain('bracket_inspection.cmm')
  })
})
