/**
 * SPCChartPanel.test.jsx
 *
 * Tests for pure helpers + basic rendering of the SPC chart panel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SPCChartPanel, {
  parseSPCFile,
  fmtSigma,
  flagColor,
  oocCount,
} from './SPCChartPanel.jsx'

// ---------------------------------------------------------------------------
// parseSPCFile
// ---------------------------------------------------------------------------

describe('parseSPCFile', () => {
  it('returns empty for blank content', () => {
    expect(parseSPCFile('').kind).toBe('empty')
    expect(parseSPCFile('  \n  ').kind).toBe('empty')
  })

  it('returns invalid for bad JSON', () => {
    const r = parseSPCFile('not-json{')
    expect(r.kind).toBe('invalid')
    expect(typeof r.error).toBe('string')
  })

  it('returns invalid when ok is false', () => {
    const r = parseSPCFile(JSON.stringify({ ok: false, reason: 'bad input' }))
    expect(r.kind).toBe('invalid')
    expect(r.error).toContain('bad input')
  })

  it('accepts wrapped { tool, result } format', () => {
    const r = parseSPCFile(JSON.stringify({
      tool: 'spc_xbar_r_chart',
      result: { ok: true, grand_mean: 10.0 },
    }))
    expect(r.kind).toBe('ok')
    expect(r.tool).toBe('spc_xbar_r_chart')
    expect(r.result.grand_mean).toBe(10.0)
  })

  it('accepts direct tool-output objects (no wrapper)', () => {
    const r = parseSPCFile(JSON.stringify({ ok: true, grand_mean: 5.0, subgroup_means: [5, 5] }))
    expect(r.kind).toBe('ok')
    expect(r.tool).toBeNull()
    expect(r.result.grand_mean).toBe(5.0)
  })

  it('handles nested ok:true correctly', () => {
    const r = parseSPCFile(JSON.stringify({
      tool: 'spc_cusum_chart',
      result: { ok: true, c_pos: [0, 1], c_neg: [0, -1], target: 10 },
    }))
    expect(r.kind).toBe('ok')
    expect(r.result.c_pos).toHaveLength(2)
  })
})

// ---------------------------------------------------------------------------
// fmtSigma
// ---------------------------------------------------------------------------

describe('fmtSigma', () => {
  it('formats positive sigma', () => {
    expect(fmtSigma(1.5)).toBe('+1.50 σ')
  })

  it('formats negative sigma using minus sign', () => {
    const s = fmtSigma(-2.03)
    expect(s).toContain('2.03')
    expect(s).toContain('σ')
  })

  it('returns — for null/undefined/NaN', () => {
    expect(fmtSigma(null)).toBe('—')
    expect(fmtSigma(undefined)).toBe('—')
    expect(fmtSigma(NaN)).toBe('—')
  })

  it('formats zero as +0.00 σ', () => {
    expect(fmtSigma(0)).toBe('+0.00 σ')
  })
})

// ---------------------------------------------------------------------------
// flagColor
// ---------------------------------------------------------------------------

describe('flagColor', () => {
  it('returns red for OOC=true', () => {
    expect(flagColor(true)).toContain('87171')  // #f87171
  })

  it('returns green for OOC=false', () => {
    expect(flagColor(false)).toContain('34d399') // #34d399
  })
})

// ---------------------------------------------------------------------------
// oocCount
// ---------------------------------------------------------------------------

describe('oocCount', () => {
  it('returns 0 for null', () => {
    expect(oocCount(null)).toBe(0)
    expect(oocCount(undefined)).toBe(0)
  })

  it('counts array length', () => {
    expect(oocCount([1, 3, 7])).toBe(3)
    expect(oocCount([])).toBe(0)
  })

  it('counts sum of values in object-of-arrays', () => {
    expect(oocCount({ nelson1: [0, 5], nelson2: [3] })).toBe(3)
    expect(oocCount({ nelson1: [], weco4: [2, 4] })).toBe(2)
  })

  it('handles mixed non-array values in object gracefully', () => {
    expect(oocCount({ nelson1: [1], center: 3.0 })).toBe(1)
  })
})

// ---------------------------------------------------------------------------
// Component rendering (renderToStaticMarkup)
// ---------------------------------------------------------------------------

describe('SPCChartPanel — render', () => {
  it('renders empty state for null content', () => {
    const html = renderToStaticMarkup(<SPCChartPanel rawContent="" />)
    expect(html).toContain('SPC')
    // Should not show chart content
    expect(html).not.toContain('Grand mean')
  })

  it('renders error state for invalid content', () => {
    const html = renderToStaticMarkup(<SPCChartPanel rawContent="{{bad json" />)
    // Should render the error box with the parse error message
    expect(html).toContain('JSON')
  })

  it('renders x-bar-R chart from tool output', () => {
    const data = {
      tool: 'spc_xbar_r_chart',
      result: {
        ok: true,
        grand_mean: 25.01,
        r_bar: 0.52,
        ucl_xbar: 25.56,
        lcl_xbar: 24.46,
        ucl_r: 1.10,
        lcl_r: 0.0,
        sigma: 0.22,
        subgroup_means: [25.0, 25.1, 24.9, 25.2, 25.0],
        subgroup_ranges: [0.5, 0.4, 0.6, 0.5, 0.5],
        ooc_xbar: [],
        ooc_r: [],
      },
    }
    const html = renderToStaticMarkup(
      <SPCChartPanel rawContent={JSON.stringify(data)} />
    )
    expect(html).toContain('X̄-R')
    expect(html).toContain('25.0100')  // grand_mean formatted
    expect(html).toContain('Grand mean')
  })

  it('renders CUSUM chart', () => {
    const data = {
      tool: 'spc_cusum_chart',
      result: {
        ok: true,
        target: 10.0,
        sigma: 0.5,
        K: 0.25,
        H: 2.5,
        c_pos: [0, 0.1, 0, 0.2],
        c_neg: [0, -0.1, 0, -0.2],
        ooc_pos: [],
        ooc_neg: [],
      },
    }
    const html = renderToStaticMarkup(
      <SPCChartPanel rawContent={JSON.stringify(data)} />
    )
    expect(html).toContain('CUSUM')
    expect(html).toContain('Target')
  })

  it('renders EWMA chart', () => {
    const data = {
      tool: 'spc_ewma_chart',
      result: {
        ok: true,
        target: 50.0,
        sigma: 1.0,
        lam: 0.2,
        ucl: 53.0,
        lcl: 47.0,
        ewma: [50.1, 50.0, 49.9, 50.2],
        ooc: [],
      },
    }
    const html = renderToStaticMarkup(
      <SPCChartPanel rawContent={JSON.stringify(data)} />
    )
    expect(html).toContain('EWMA')
    expect(html).toContain('Lambda')
  })

  it('renders run rules analysis', () => {
    const data = {
      tool: 'spc_run_rules',
      result: {
        ok: true,
        any_violation: false,
        center: 10.0,
        sigma: 0.5,
        violations: { nelson1: [], nelson2: [], weco4: [] },
      },
    }
    const html = renderToStaticMarkup(
      <SPCChartPanel rawContent={JSON.stringify(data)} />
    )
    expect(html).toContain('Run Rules')
    expect(html).toContain('all clear')
  })

  it('shows run rules violation count when violations exist', () => {
    const data = {
      tool: 'spc_run_rules',
      result: {
        ok: true,
        any_violation: true,
        center: 10.0,
        sigma: 0.5,
        violations: { nelson1: [3, 7], nelson2: [] },
      },
    }
    const html = renderToStaticMarkup(
      <SPCChartPanel rawContent={JSON.stringify(data)} />
    )
    expect(html).toContain('violation')
  })

  it('renders filename in header', () => {
    const html = renderToStaticMarkup(
      <SPCChartPanel rawContent="" fileName="process_data.spc" />
    )
    expect(html).toContain('process_data.spc')
  })
})
