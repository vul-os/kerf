/**
 * CostBreakdownPanel.test.jsx
 *
 * Tests for pure helpers + basic rendering of the cost breakdown panel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CostBreakdownPanel, {
  parseCostFile,
  fmtCurrency,
  pctBar,
  detectCostTool,
} from './CostBreakdownPanel.jsx'

// ---------------------------------------------------------------------------
// parseCostFile
// ---------------------------------------------------------------------------

describe('parseCostFile', () => {
  it('returns empty for blank content', () => {
    expect(parseCostFile('').kind).toBe('empty')
    expect(parseCostFile('   ').kind).toBe('empty')
  })

  it('returns invalid for malformed JSON', () => {
    expect(parseCostFile('{bad}').kind).toBe('invalid')
  })

  it('returns invalid when ok is false', () => {
    const r = parseCostFile(JSON.stringify({ ok: false, reason: 'bad input' }))
    expect(r.kind).toBe('invalid')
    expect(r.error).toContain('bad input')
  })

  it('accepts wrapped { tool, result } format', () => {
    const r = parseCostFile(JSON.stringify({
      tool: 'costing_cnc',
      result: { ok: true, unit_cost: 12.34 },
    }))
    expect(r.kind).toBe('ok')
    expect(r.tool).toBe('costing_cnc')
    expect(r.result.unit_cost).toBeCloseTo(12.34)
  })

  it('accepts direct tool output (no wrapper)', () => {
    const r = parseCostFile(JSON.stringify({ ok: true, unit_price: 25.0, full_cost: 20.0 }))
    expect(r.kind).toBe('ok')
    expect(r.result.unit_price).toBe(25.0)
  })
})

// ---------------------------------------------------------------------------
// fmtCurrency
// ---------------------------------------------------------------------------

describe('fmtCurrency', () => {
  it('formats with dollar sign and 2 decimals', () => {
    expect(fmtCurrency(12.5)).toBe('$12.50')
    expect(fmtCurrency(0)).toBe('$0.00')
    expect(fmtCurrency(1234.567)).toBe('$1234.57')
  })

  it('returns — for null/undefined/NaN', () => {
    expect(fmtCurrency(null)).toBe('—')
    expect(fmtCurrency(undefined)).toBe('—')
    expect(fmtCurrency(NaN)).toBe('—')
  })
})

// ---------------------------------------------------------------------------
// pctBar
// ---------------------------------------------------------------------------

describe('pctBar', () => {
  it('computes percentage correctly', () => {
    expect(pctBar(25, 100)).toBe(25)
    expect(pctBar(50, 200)).toBe(25)
  })

  it('clamps to 0–100', () => {
    expect(pctBar(150, 100)).toBe(100)
    expect(pctBar(-5, 100)).toBe(0)
  })

  it('returns 0 for zero/null total', () => {
    expect(pctBar(10, 0)).toBe(0)
    expect(pctBar(10, null)).toBe(0)
  })

  it('returns 0 for null value', () => {
    expect(pctBar(null, 100)).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// detectCostTool
// ---------------------------------------------------------------------------

describe('detectCostTool', () => {
  it('detects from tool name', () => {
    expect(detectCostTool('costing_cnc', {})).toBe('cnc')
    expect(detectCostTool('costing_casting', {})).toBe('casting')
    expect(detectCostTool('costing_injection', {})).toBe('injection')
    expect(detectCostTool('costing_sheet_metal', {})).toBe('sheet_metal')
    expect(detectCostTool('costing_printing', {})).toBe('printing')
    expect(detectCostTool('costing_assembly', {})).toBe('assembly')
    expect(detectCostTool('costing_rollup', {})).toBe('rollup')
    expect(detectCostTool('costing_batch_curve', {})).toBe('batch_curve')
    expect(detectCostTool('costing_learning_curve', {})).toBe('learning_curve')
    expect(detectCostTool('costing_make_vs_buy', {})).toBe('make_vs_buy')
  })

  it('detects from result keys when tool is null', () => {
    expect(detectCostTool(null, { breakpoints: [] })).toBe('batch_curve')
    expect(detectCostTool(null, { unit_cost_at_n: 5.0 })).toBe('learning_curve')
    expect(detectCostTool(null, { break_even_volume: 100 })).toBe('make_vs_buy')
    expect(detectCostTool(null, { unit_price: 20.0 })).toBe('rollup')
    expect(detectCostTool(null, { operations: [] })).toBe('assembly')
  })

  it('returns unknown for unrecognised result', () => {
    expect(detectCostTool(null, { foo: 'bar' })).toBe('unknown')
  })
})

// ---------------------------------------------------------------------------
// Component rendering (renderToStaticMarkup)
// ---------------------------------------------------------------------------

describe('CostBreakdownPanel — render', () => {
  it('renders empty state for blank content', () => {
    const html = renderToStaticMarkup(<CostBreakdownPanel rawContent="" />)
    expect(html).toContain('Cost')
    expect(html).toContain('costing_')
  })

  it('renders error state for invalid JSON', () => {
    const html = renderToStaticMarkup(<CostBreakdownPanel rawContent="{not valid}" />)
    // error box shows the parse error message
    expect(html).toContain('JSON')
  })

  it('renders CNC should-cost result', () => {
    const data = {
      tool: 'costing_cnc',
      result: {
        ok: true,
        unit_cost: 23.45,
        material: 8.0,
        cycle_cost: 12.0,
        setup_cost_per_unit: 1.5,
        tooling_amortisation: 0.5,
        overhead: 1.45,
        warnings: [],
      },
    }
    const html = renderToStaticMarkup(<CostBreakdownPanel rawContent={JSON.stringify(data)} />)
    expect(html).toContain('CNC')
    expect(html).toContain('Unit cost')
    expect(html).toContain('23.45')
    expect(html).toContain('Material')
  })

  it('renders rollup result with waterfall', () => {
    const data = {
      tool: 'costing_rollup',
      result: {
        ok: true,
        unit_price: 30.00,
        full_cost: 24.00,
        manufacturing_cost: 21.00,
        direct_cost: 17.50,
        direct_material: 8.0,
        direct_labour: 5.0,
        machine_cost: 4.5,
        overhead: 3.5,
        gross_margin_rate: 0.20,
        warnings: [],
      },
    }
    const html = renderToStaticMarkup(<CostBreakdownPanel rawContent={JSON.stringify(data)} />)
    expect(html).toContain('Roll-Up')
    expect(html).toContain('Unit price')
    expect(html).toContain('30.00')
  })

  it('renders batch curve breakpoints', () => {
    const data = {
      tool: 'costing_batch_curve',
      result: {
        ok: true,
        breakpoints: [
          { batch_size: 1,   unit_cost: 50.0 },
          { batch_size: 10,  unit_cost: 20.0 },
          { batch_size: 100, unit_cost: 12.0 },
        ],
        min_unit_cost: 12.0,
        max_unit_cost: 50.0,
      },
    }
    const html = renderToStaticMarkup(<CostBreakdownPanel rawContent={JSON.stringify(data)} />)
    expect(html).toContain('Batch')
    expect(html).toContain('batch size')
    // Should show n=1, n=10, n=100
    expect(html).toContain('n = 1')
    expect(html).toContain('n = 100')
  })

  it('renders make vs. buy analysis', () => {
    const data = {
      tool: 'costing_make_vs_buy',
      result: {
        ok: true,
        make_unit_cost: 5.0,
        buy_unit_price: 7.0,
        make_annual_total: 5500.0,
        buy_annual_total: 7000.0,
        break_even_volume: 200,
        annual_volume: 1000,
        preferred: 'make',
      },
    }
    const html = renderToStaticMarkup(<CostBreakdownPanel rawContent={JSON.stringify(data)} />)
    expect(html).toContain('Make vs. Buy')
    expect(html).toContain('make')
    expect(html).toContain('Break-even')
  })

  it('renders learning curve result', () => {
    const data = {
      tool: 'costing_learning_curve',
      result: {
        ok: true,
        unit_cost_at_n: 3.20,
        t1: 5.0,
        cumulative_volume: 100,
        learning_rate: 0.80,
        b: -0.322,
      },
    }
    const html = renderToStaticMarkup(<CostBreakdownPanel rawContent={JSON.stringify(data)} />)
    expect(html).toContain('Learning')
    expect(html).toContain('3.20')
  })

  it('renders injection moulding result as generic process', () => {
    const data = {
      tool: 'costing_injection',
      result: {
        ok: true,
        unit_cost_per_good_part: 0.45,
        material: 0.10,
        machine_time: 0.20,
        mould_amortisation: 0.05,
        overhead: 0.10,
        warnings: [],
      },
    }
    const html = renderToStaticMarkup(<CostBreakdownPanel rawContent={JSON.stringify(data)} />)
    expect(html).toContain('Injection')
    expect(html).toContain('Unit cost')
  })

  it('renders filename in header', () => {
    const html = renderToStaticMarkup(
      <CostBreakdownPanel rawContent="" fileName="bracket_cost.cost_report" />
    )
    expect(html).toContain('bracket_cost.cost_report')
  })
})
