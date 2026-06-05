// QuantitySchedulePanel.test.jsx — tests for the material quantity take-off panel.
//
// Uses renderToStaticMarkup (react-dom/server) — no browser DOM, no fetch.
// Mirrors the pattern in CostBreakdownPanel.test.jsx.

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import QuantitySchedulePanel, {
  parseScheduleFile,
  fmtQty,
  fmtCostUsd,
} from './QuantitySchedulePanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function _qtyResult() {
  return {
    ok: true,
    by_category: [
      { category: 'Wall', element_count: 3, total_area_m2: 60.0, total_volume_m3: 18.0 },
      { category: 'Slab', element_count: 1, total_area_m2: 50.0, total_volume_m3: 12.5 },
    ],
    by_material: [
      { material: 'Concrete', element_count: 4, total_volume_m3: 30.5 },
    ],
    element_lines: [
      { element_id: 'W1', element_name: 'Wall-01', category: 'Wall', material: 'Concrete',
        area_m2: 20.0, volume_m3: 6.0, length_m: 10.0, count: 1 },
      { element_id: 'W2', element_name: 'Wall-02', category: 'Wall', material: 'Concrete',
        area_m2: 20.0, volume_m3: 6.0, length_m: 10.0, count: 1 },
      { element_id: 'W3', element_name: 'Wall-03', category: 'Wall', material: 'Concrete',
        area_m2: 20.0, volume_m3: 6.0, length_m: 10.0, count: 1 },
      { element_id: 'S1', element_name: 'Slab-01', category: 'Slab', material: 'Concrete',
        area_m2: 50.0, volume_m3: 12.5, length_m: null, count: 1 },
    ],
    warnings: [],
  }
}

function _costResult() {
  return {
    ok: true,
    total_material_cost_usd: 3030.30,
    by_category: [
      { category: 'Slab', element_count: 1, total_area_m2: 50.0, total_volume_m3: 12.5,
        total_gross_mass_kg: 31500.0, total_material_cost_usd: 2047.50 },
      { category: 'Wall', element_count: 3, total_area_m2: 60.0, total_volume_m3: 18.0,
        total_gross_mass_kg: 45360.0, total_material_cost_usd: 982.80 },
    ],
    by_material: [
      { material: 'Concrete', element_count: 4, total_volume_m3: 30.5,
        total_gross_mass_kg: 76860.0, total_material_cost_usd: 3030.30 },
    ],
    element_lines: [
      { element_id: 'S1', element_name: 'Slab-01', category: 'Slab', material: 'Concrete',
        area_m2: 50.0, volume_m3: 12.5, length_m: null, count: 1,
        gross_mass_kg: 31500.0, material_cost_usd: 2047.50, flagged: false, flag_reason: '' },
    ],
    warnings: [],
  }
}

function wrap(result) {
  return JSON.stringify({ result })
}

// ---------------------------------------------------------------------------
// parseScheduleFile
// ---------------------------------------------------------------------------

describe('parseScheduleFile', () => {
  it('returns empty for blank content', () => {
    expect(parseScheduleFile('').kind).toBe('empty')
    expect(parseScheduleFile('  ').kind).toBe('empty')
  })

  it('returns invalid for malformed JSON', () => {
    expect(parseScheduleFile('{bad}').kind).toBe('invalid')
  })

  it('returns invalid when ok is false', () => {
    const r = parseScheduleFile(JSON.stringify({ result: { ok: false, reason: 'oops' } }))
    expect(r.kind).toBe('invalid')
  })

  it('returns ok for valid qty-only result', () => {
    const r = parseScheduleFile(wrap(_qtyResult()))
    expect(r.kind).toBe('ok')
    expect(r.hasCost).toBe(false)
  })

  it('hasCost is true when total_material_cost_usd is present', () => {
    const r = parseScheduleFile(wrap(_costResult()))
    expect(r.kind).toBe('ok')
    expect(r.hasCost).toBe(true)
  })

  it('accepts top-level result dict (no wrapper)', () => {
    const r = parseScheduleFile(JSON.stringify(_qtyResult()))
    expect(r.kind).toBe('ok')
  })
})

// ---------------------------------------------------------------------------
// fmtQty
// ---------------------------------------------------------------------------

describe('fmtQty', () => {
  it('formats integer correctly', () => {
    expect(fmtQty(5)).toBe('5')
  })

  it('formats decimal with trailing zero stripped', () => {
    expect(fmtQty(6.0)).toBe('6')
  })

  it('formats precise decimal', () => {
    expect(fmtQty(12.5)).toBe('12.5')
  })

  it('appends unit when provided', () => {
    expect(fmtQty(30.5, 'm²')).toBe('30.5 m²')
  })

  it('returns — for null', () => {
    expect(fmtQty(null)).toBe('—')
  })

  it('returns — for NaN', () => {
    expect(fmtQty(NaN)).toBe('—')
  })

  it('returns — for Infinity', () => {
    expect(fmtQty(Infinity)).toBe('—')
  })
})

// ---------------------------------------------------------------------------
// fmtCostUsd
// ---------------------------------------------------------------------------

describe('fmtCostUsd', () => {
  it('formats 982.8 as $982.80', () => {
    expect(fmtCostUsd(982.8)).toBe('$982.80')
  })

  it('formats 0 as $0.00', () => {
    expect(fmtCostUsd(0)).toBe('$0.00')
  })

  it('returns — for null', () => {
    expect(fmtCostUsd(null)).toBe('—')
  })

  it('returns — for NaN', () => {
    expect(fmtCostUsd(NaN)).toBe('—')
  })
})

// ---------------------------------------------------------------------------
// Panel — empty state
// ---------------------------------------------------------------------------

describe('QuantitySchedulePanel — empty state', () => {
  it('renders without error for empty content', () => {
    const html = renderToStaticMarkup(<QuantitySchedulePanel content="" />)
    expect(html.length).toBeGreaterThan(0)
  })

  it('has data-testid="quantity-schedule-panel"', () => {
    const html = renderToStaticMarkup(<QuantitySchedulePanel content="" />)
    expect(html).toContain('data-testid="quantity-schedule-panel"')
  })

  it('shows empty state testid', () => {
    const html = renderToStaticMarkup(<QuantitySchedulePanel content="" />)
    expect(html).toContain('data-testid="qty-empty-state"')
  })

  it('shows header label', () => {
    const html = renderToStaticMarkup(<QuantitySchedulePanel content="" />)
    expect(html).toContain('Quantity Schedule')
  })
})

// ---------------------------------------------------------------------------
// Panel — error state
// ---------------------------------------------------------------------------

describe('QuantitySchedulePanel — error state', () => {
  it('shows error state for invalid JSON', () => {
    const html = renderToStaticMarkup(<QuantitySchedulePanel content="{bad}" />)
    expect(html).toContain('data-testid="qty-error-state"')
  })

  it('shows error state when ok=false', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={JSON.stringify({ result: { ok: false, reason: 'fail' } })} />
    )
    expect(html).toContain('data-testid="qty-error-state"')
  })
})

// ---------------------------------------------------------------------------
// Panel — quantity-only schedule
// ---------------------------------------------------------------------------

describe('QuantitySchedulePanel — quantity only', () => {
  it('renders summary section', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).toContain('data-testid="qty-summary"')
  })

  it('shows element type count in summary', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).toContain('Element types')
    expect(html).toContain('>2<')
  })

  it('renders category table', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).toContain('data-testid="qty-category-table"')
  })

  it('shows Wall category row', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).toContain('data-testid="qty-cat-row-Wall"')
  })

  it('shows Slab category row', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).toContain('data-testid="qty-cat-row-Slab"')
  })

  it('renders material table', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).toContain('data-testid="qty-material-table"')
  })

  it('shows Concrete material row', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).toContain('data-testid="qty-mat-row-Concrete"')
  })

  it('does NOT show "with cost" badge in qty-only mode', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).not.toContain('with cost')
  })

  it('does NOT show total material cost in qty-only mode', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).not.toContain('Total material cost')
  })
})

// ---------------------------------------------------------------------------
// Panel — with cost schedule
// ---------------------------------------------------------------------------

describe('QuantitySchedulePanel — with cost', () => {
  it('shows "with cost" badge', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_costResult())} />
    )
    expect(html).toContain('with cost')
  })

  it('shows total material cost row in summary', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_costResult())} />
    )
    expect(html).toContain('Total material cost')
  })

  it('shows formatted total cost $3030.30', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_costResult())} />
    )
    expect(html).toContain('$3030.30')
  })

  it('shows cost column in category table', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_costResult())} />
    )
    expect(html).toContain('$2047.50')
  })

  it('shows mass column in material table', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_costResult())} />
    )
    // 76860 kg gross mass for Concrete
    expect(html).toContain('76860')
  })
})

// ---------------------------------------------------------------------------
// Panel — file name
// ---------------------------------------------------------------------------

describe('QuantitySchedulePanel — fileName prop', () => {
  it('uses filename without extension as header', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content="" fileName="ground-floor.qty_schedule" />
    )
    expect(html).toContain('ground-floor')
  })

  it('strips .json extension', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content="" fileName="takeoff.json" />
    )
    expect(html).toContain('takeoff')
  })
})

// ---------------------------------------------------------------------------
// Panel — warnings
// ---------------------------------------------------------------------------

describe('QuantitySchedulePanel — warnings', () => {
  it('does not render warnings section when empty', () => {
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(_qtyResult())} />
    )
    expect(html).not.toContain('data-testid="qty-warnings"')
  })

  it('renders warnings when present', () => {
    const result = { ..._qtyResult(), warnings: ["unknown material 'ExoticAlloy'"] }
    const html = renderToStaticMarkup(
      <QuantitySchedulePanel content={wrap(result)} />
    )
    expect(html).toContain('data-testid="qty-warnings"')
    expect(html).toContain('ExoticAlloy')
  })
})
