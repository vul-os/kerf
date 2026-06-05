/**
 * MoldCoolingWarpagePanel.test.jsx
 *
 * Tests for pure helpers + basic rendering of the mold cooling/warpage panel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import MoldCoolingWarpagePanel, {
  parseMoldResult,
  detectTool,
  warpageColor,
  balanceColor,
  fmtVal,
} from './MoldCoolingWarpagePanel.jsx'

// ---------------------------------------------------------------------------
// parseMoldResult
// ---------------------------------------------------------------------------

describe('parseMoldResult', () => {
  it('returns empty for blank content', () => {
    expect(parseMoldResult('').kind).toBe('empty')
  })

  it('returns invalid for bad JSON', () => {
    expect(parseMoldResult('not json').kind).toBe('invalid')
  })

  it('returns invalid when ok is false', () => {
    const r = parseMoldResult(JSON.stringify({ ok: false, reason: 'error' }))
    expect(r.kind).toBe('invalid')
  })

  it('returns invalid for unknown tool format', () => {
    const r = parseMoldResult(JSON.stringify({ foo: 'bar' }))
    expect(r.kind).toBe('invalid')
  })

  it('parses a cooling analysis result', () => {
    const doc = {
      ok: true,
      htc_w_m2_k: 8500.0,
      reynolds: 15000,
      cooling_time_s: 8.2,
      coolant_temp_rise_c: 2.1,
      flow_regime: 'turbulent',
      honest_caveat: 'Dittus-Boelter correlation',
    }
    const r = parseMoldResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.tool).toBe('cooling')
    expect(r.data.htc_w_m2_k).toBe(8500.0)
  })

  it('parses a runner balance result', () => {
    const doc = {
      ok: true,
      balanced: true,
      max_imbalance_pct: 0.0,
      cavity_paths: [
        { cavity_id: 'G1', fill_ratio: 1.0, total_resistance: 1.234 },
        { cavity_id: 'G2', fill_ratio: 1.0, total_resistance: 1.234 },
      ],
      honest_caveat: 'Hagen-Poiseuille geometric resistance',
    }
    const r = parseMoldResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.tool).toBe('runner_balance')
    expect(r.data.balanced).toBe(true)
  })

  it('parses a warpage index result', () => {
    const doc = {
      ok: true,
      warpage_index: 35.5,
      risk_level: 'moderate',
      primary_warp_driver: 'wall_uniformity',
      sub_scores: { wall_uniformity: 12, gate_location: 5, polymer_grade: 8, cooling_time: 6, mold_temperature: 4 },
      mitigation_suggestions: ['Increase cooling time', 'Use Moldflow simulation'],
      honest_caveat: 'Heuristic screening tool',
    }
    const r = parseMoldResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.tool).toBe('warpage')
    expect(r.data.warpage_index).toBe(35.5)
  })

  it('unwraps { result: {...} } wrapper', () => {
    const doc = {
      tool: 'mold_compute_warpage_index',
      result: {
        ok: true,
        warpage_index: 20.0,
        risk_level: 'low',
        primary_warp_driver: 'polymer_grade',
        sub_scores: {},
        mitigation_suggestions: [],
      },
    }
    const r = parseMoldResult(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.tool).toBe('warpage')
  })
})

// ---------------------------------------------------------------------------
// detectTool
// ---------------------------------------------------------------------------

describe('detectTool', () => {
  it('returns cooling for htc_w_m2_k field', () => {
    expect(detectTool({ htc_w_m2_k: 9000, cooling_time_s: 8 })).toBe('cooling')
  })

  it('returns cooling for cooling_time_s + reynolds', () => {
    expect(detectTool({ cooling_time_s: 5.0, reynolds: 12000 })).toBe('cooling')
  })

  it('returns runner_balance for balanced + cavity_paths', () => {
    expect(detectTool({ balanced: true, cavity_paths: [] })).toBe('runner_balance')
  })

  it('returns warpage for warpage_index + risk_level', () => {
    expect(detectTool({ warpage_index: 40, risk_level: 'moderate' })).toBe('warpage')
  })

  it('returns unknown for empty object', () => {
    expect(detectTool({})).toBe('unknown')
  })

  it('returns unknown for null', () => {
    expect(detectTool(null)).toBe('unknown')
  })
})

// ---------------------------------------------------------------------------
// warpageColor
// ---------------------------------------------------------------------------

describe('warpageColor', () => {
  it('returns green for index 0', () => {
    expect(warpageColor(0)).toBe('#34d399')
  })

  it('returns green for index 25', () => {
    expect(warpageColor(25)).toBe('#34d399')
  })

  it('returns amber for index 40', () => {
    expect(warpageColor(40)).toBe('#fbbf24')
  })

  it('returns orange for index 60', () => {
    expect(warpageColor(60)).toBe('#f97316')
  })

  it('returns red for index 80', () => {
    expect(warpageColor(80)).toBe('#f87171')
  })

  it('returns grey for null', () => {
    expect(warpageColor(null)).toBe('#9ca3af')
  })
})

// ---------------------------------------------------------------------------
// balanceColor
// ---------------------------------------------------------------------------

describe('balanceColor', () => {
  it('returns green for 0 % imbalance', () => {
    expect(balanceColor(0)).toBe('#34d399')
  })

  it('returns green for 4 % imbalance', () => {
    expect(balanceColor(4)).toBe('#34d399')
  })

  it('returns amber for 8 % imbalance', () => {
    expect(balanceColor(8)).toBe('#fbbf24')
  })

  it('returns red for 20 % imbalance', () => {
    expect(balanceColor(20)).toBe('#f87171')
  })

  it('returns grey for null', () => {
    expect(balanceColor(null)).toBe('#9ca3af')
  })
})

// ---------------------------------------------------------------------------
// fmtVal
// ---------------------------------------------------------------------------

describe('fmtVal', () => {
  it('formats to 2 decimal places by default', () => {
    expect(fmtVal(8500.0)).toBe('8500.00')
  })

  it('appends unit when provided', () => {
    expect(fmtVal(8.2, 1, 's')).toBe('8.2 s')
  })

  it('returns — for null', () => {
    expect(fmtVal(null)).toBe('—')
  })

  it('returns — for undefined', () => {
    expect(fmtVal(undefined)).toBe('—')
  })

  it('returns — for Infinity', () => {
    expect(fmtVal(Infinity)).toBe('—')
  })
})

// ---------------------------------------------------------------------------
// Component rendering
// ---------------------------------------------------------------------------

describe('MoldCoolingWarpagePanel rendering', () => {
  it('renders empty state when content is blank', () => {
    const html = renderToStaticMarkup(MoldCoolingWarpagePanel({ parsedContent: '' }))
    expect(html).toContain('No mold analysis result loaded')
  })

  it('renders error state for invalid JSON', () => {
    const html = renderToStaticMarkup(MoldCoolingWarpagePanel({ parsedContent: 'bad json' }))
    expect(html).toContain('Could not parse')
  })

  it('renders Cooling Channel Analysis title for cooling result', () => {
    const doc = {
      ok: true,
      htc_w_m2_k: 8500,
      reynolds: 15000,
      cooling_time_s: 8.2,
      coolant_temp_rise_c: 2.1,
      flow_regime: 'turbulent',
    }
    const html = renderToStaticMarkup(MoldCoolingWarpagePanel({ parsedContent: JSON.stringify(doc) }))
    expect(html).toContain('Cooling Channel Analysis')
    expect(html).toContain('8500')
    expect(html).toContain('15000')
  })

  it('renders turbulent badge for high Reynolds number', () => {
    const doc = {
      ok: true,
      htc_w_m2_k: 9200,
      reynolds: 20000,
      cooling_time_s: 7.5,
      coolant_temp_rise_c: 1.8,
      flow_regime: 'turbulent',
    }
    const html = renderToStaticMarkup(MoldCoolingWarpagePanel({ parsedContent: JSON.stringify(doc) }))
    expect(html).toContain('Turbulent')
    expect(html).toContain('Dittus-Boelter')
  })

  it('renders Runner Balance title for runner balance result', () => {
    const doc = {
      ok: true,
      balanced: true,
      max_imbalance_pct: 0.0,
      cavity_paths: [
        { cavity_id: 'G1', fill_ratio: 1.0, total_resistance: 1.5 },
        { cavity_id: 'G2', fill_ratio: 1.0, total_resistance: 1.5 },
      ],
      honest_caveat: 'Hagen-Poiseuille geometric balance',
    }
    const html = renderToStaticMarkup(MoldCoolingWarpagePanel({ parsedContent: JSON.stringify(doc) }))
    expect(html).toContain('Runner Balance')
    expect(html).toContain('G1')
    expect(html).toContain('G2')
  })

  it('renders Warpage Index title for warpage result', () => {
    const doc = {
      ok: true,
      warpage_index: 42.0,
      risk_level: 'moderate',
      primary_warp_driver: 'gate_location',
      sub_scores: { wall_uniformity: 6, gate_location: 12, polymer_grade: 8, cooling_time: 10, mold_temperature: 6 },
      mitigation_suggestions: ['Relocate gate to centre', 'Run Moldflow simulation'],
    }
    const html = renderToStaticMarkup(MoldCoolingWarpagePanel({ parsedContent: JSON.stringify(doc) }))
    expect(html).toContain('Warpage Index')
    expect(html).toContain('42.0')
    expect(html).toContain('moderate')
    expect(html).toContain('gate_location')
    expect(html).toContain('Relocate gate')
    expect(html).toContain('Moldflow')
  })

  it('renders honest caveat when present', () => {
    const doc = {
      ok: true,
      warpage_index: 30.0,
      risk_level: 'low',
      primary_warp_driver: 'wall_uniformity',
      sub_scores: {},
      mitigation_suggestions: [],
      honest_caveat: 'Heuristic screening tool only — real warpage needs FEM',
    }
    const html = renderToStaticMarkup(MoldCoolingWarpagePanel({ parsedContent: JSON.stringify(doc) }))
    expect(html).toContain('Heuristic screening')
  })

  it('accepts object prop directly', () => {
    const doc = {
      ok: true,
      balanced: false,
      max_imbalance_pct: 25.0,
      cavity_paths: [],
    }
    const html = renderToStaticMarkup(MoldCoolingWarpagePanel({ parsedContent: doc }))
    expect(html).toContain('Runner Balance')
  })
})
