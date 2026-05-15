// jewelryCostPanel.test.js — unit tests for JewelryCostPanel data model
// and cost math.
//
// No React rendering required. We test the pure-JS model logic copied from
// JewelryCostPanel.jsx, matching the Python model in metal_cost.py.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// ---------------------------------------------------------------------------
// Source inspection helpers
// ---------------------------------------------------------------------------

const panelSrc = readFileSync(
  path.resolve(__dirname, '../components/JewelryCostPanel.jsx'), 'utf8',
)

const apiSrc = readFileSync(
  path.resolve(__dirname, '../lib/api.js'), 'utf8',
)

const llmDocSrc = (() => {
  try {
    return readFileSync(
      path.resolve(__dirname, '../../packages/kerf-chat/llm_docs/jewelry_metal_cost.md'), 'utf8',
    )
  } catch { return '' }
})()

// ---------------------------------------------------------------------------
// Pure-JS cost model (mirrors JewelryCostPanel.jsx)
// ---------------------------------------------------------------------------

const GRAMS_PER_DWT = 1.55517384
const GRAMS_PER_OZT = 31.1034768

const DENSITY = {
  '10k_yellow': 11.57, '14k_yellow': 13.07, '18k_yellow': 15.58,
  '22k_yellow': 17.80, '24k_yellow': 19.32,
  '10k_white':  11.61, '14k_white':  13.25, '18k_white':  15.60,
  '10k_rose':   11.59, '14k_rose':   13.20, '18k_rose':   15.45,
  platinum_950: 21.40, palladium_950: 11.00,
  sterling_925: 10.36, fine_silver:   10.49,
  titanium:     4.51,  brass:         8.53,  bronze: 8.78,
}

function localEstimate(volumeMm3, metalKey, pricePerGram = 0, labor = 0, finishing = 0, allowancePct = 15) {
  const d = DENSITY[metalKey]
  if (!d || volumeMm3 <= 0) return null
  const netG   = d * (volumeMm3 / 1000)
  const grossG = netG * (1 + allowancePct / 100)
  const metalCost = grossG * pricePerGram
  const total = metalCost + labor + finishing
  return {
    net_grams:   netG,
    net_dwt:     netG / GRAMS_PER_DWT,
    net_ozt:     netG / GRAMS_PER_OZT,
    gross_grams: grossG,
    gross_dwt:   grossG / GRAMS_PER_DWT,
    gross_ozt:   grossG / GRAMS_PER_OZT,
    metal_cost:  metalCost,
    labor,
    finishing,
    total_cost:  total,
    allowance_pct: allowancePct,
  }
}

// ---------------------------------------------------------------------------
// Helper: approximate equality
// ---------------------------------------------------------------------------

function near(a, b, rel = 1e-4) {
  if (b === 0) return Math.abs(a) < 1e-10
  return Math.abs(a - b) / Math.abs(b) < rel
}

// ---------------------------------------------------------------------------
// 1. Density table sanity
// ---------------------------------------------------------------------------

describe('DENSITY table', () => {
  it('has positive densities for all metals', () => {
    for (const [k, v] of Object.entries(DENSITY)) {
      expect(v).toBeGreaterThan(0)
    }
  })

  it('platinum_950 is heavier than 18k_yellow', () => {
    expect(DENSITY.platinum_950).toBeGreaterThan(DENSITY['18k_yellow'])
  })

  it('sterling_925 density is ~10.36', () => {
    expect(DENSITY.sterling_925).toBeCloseTo(10.36, 1)
  })

  it('24k_yellow (pure gold) density ~19.32', () => {
    expect(DENSITY['24k_yellow']).toBeCloseTo(19.32, 1)
  })

  it('gold karat density increases with purity', () => {
    const d = (k) => DENSITY[k]
    expect(d('10k_yellow')).toBeLessThan(d('14k_yellow'))
    expect(d('14k_yellow')).toBeLessThan(d('18k_yellow'))
    expect(d('18k_yellow')).toBeLessThan(d('22k_yellow'))
    expect(d('22k_yellow')).toBeLessThan(d('24k_yellow'))
  })
})

// ---------------------------------------------------------------------------
// 2. Unit conversion constants
// ---------------------------------------------------------------------------

describe('Unit conversion constants', () => {
  it('GRAMS_PER_DWT matches NIST value', () => {
    expect(GRAMS_PER_DWT).toBeCloseTo(1.55517384, 6)
  })

  it('GRAMS_PER_OZT matches NIST value', () => {
    expect(GRAMS_PER_OZT).toBeCloseTo(31.1034768, 5)
  })

  it('20 dwt == 1 ozt', () => {
    expect(20 * GRAMS_PER_DWT).toBeCloseTo(GRAMS_PER_OZT, 6)
  })
})

// ---------------------------------------------------------------------------
// 3. Weight math
// ---------------------------------------------------------------------------

describe('localEstimate — weight', () => {
  it('1 cm³ (1000 mm³) of sterling silver ≈ 10.36 g', () => {
    const r = localEstimate(1000, 'sterling_925')
    expect(r.net_grams).toBeCloseTo(10.36, 1)
  })

  it('300 mm³ of 18k_yellow ≈ 4.674 g', () => {
    const r = localEstimate(300, '18k_yellow')
    expect(r.net_grams).toBeCloseTo(4.674, 2)
  })

  it('dwt is grams / GRAMS_PER_DWT', () => {
    const r = localEstimate(500, '14k_yellow')
    expect(r.net_dwt).toBeCloseTo(r.net_grams / GRAMS_PER_DWT, 5)
  })

  it('ozt is grams / GRAMS_PER_OZT', () => {
    const r = localEstimate(500, '14k_yellow')
    expect(r.net_ozt).toBeCloseTo(r.net_grams / GRAMS_PER_OZT, 5)
  })

  it('unknown metal returns null', () => {
    expect(localEstimate(1000, 'unobtanium')).toBeNull()
  })

  it('zero volume returns null', () => {
    expect(localEstimate(0, '14k_yellow')).toBeNull()
  })

  it('negative volume returns null', () => {
    expect(localEstimate(-100, '14k_yellow')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// 4. Casting allowance
// ---------------------------------------------------------------------------

describe('localEstimate — casting allowance', () => {
  it('default 15% allowance: gross = net * 1.15', () => {
    const r = localEstimate(1000, '14k_yellow', 0, 0, 0, 15)
    expect(r.gross_grams).toBeCloseTo(r.net_grams * 1.15, 5)
  })

  it('0% allowance: gross == net', () => {
    const r = localEstimate(1000, '14k_yellow', 0, 0, 0, 0)
    expect(r.gross_grams).toBeCloseTo(r.net_grams, 5)
  })

  it('20% allowance: gross = net * 1.20', () => {
    const r = localEstimate(1000, '14k_yellow', 0, 0, 0, 20)
    expect(r.gross_grams).toBeCloseTo(r.net_grams * 1.20, 5)
  })

  it('allowance_pct stored in result', () => {
    const r = localEstimate(1000, '14k_yellow', 0, 0, 0, 12)
    expect(r.allowance_pct).toBe(12)
  })
})

// ---------------------------------------------------------------------------
// 5. Cost math
// ---------------------------------------------------------------------------

describe('localEstimate — cost', () => {
  it('metal_cost = gross_grams * price_per_gram', () => {
    const r = localEstimate(1000, '18k_yellow', 38, 0, 0)
    expect(r.metal_cost).toBeCloseTo(r.gross_grams * 38, 4)
  })

  it('total_cost = metal_cost + labor + finishing', () => {
    const r = localEstimate(300, '18k_yellow', 38, 80, 20)
    expect(r.total_cost).toBeCloseTo(r.metal_cost + r.labor + r.finishing, 4)
  })

  it('zero price gives zero metal_cost', () => {
    const r = localEstimate(1000, 'platinum_950', 0, 0, 0)
    expect(r.metal_cost).toBe(0)
  })

  it('worked example: 300 mm³ 18k yellow at $38/g + $80 labor + $20 finishing', () => {
    const r = localEstimate(300, '18k_yellow', 38, 80, 20)
    // net ≈ 4.674g, gross ≈ 5.375g, metal_cost ≈ $204.26, total ≈ $304.26
    expect(r.net_grams).toBeCloseTo(4.674, 2)
    expect(r.gross_grams).toBeCloseTo(5.375, 2)
    expect(r.metal_cost).toBeCloseTo(r.gross_grams * 38, 2)
    expect(r.total_cost).toBeCloseTo(r.metal_cost + 80 + 20, 2)
  })

  it('platinum heavier and costlier than sterling for same volume and price', () => {
    const pt  = localEstimate(1000, 'platinum_950', 1)
    const ag  = localEstimate(1000, 'sterling_925', 1)
    expect(pt.net_grams).toBeGreaterThan(ag.net_grams)
    expect(pt.metal_cost).toBeGreaterThan(ag.metal_cost)
  })
})

// ---------------------------------------------------------------------------
// 6. JewelryCostPanel.jsx source checks
// ---------------------------------------------------------------------------

describe('JewelryCostPanel.jsx — component source', () => {
  it('file exists and is non-empty', () => {
    expect(panelSrc.length).toBeGreaterThan(0)
  })

  it('imports Scale icon from lucide-react', () => {
    expect(panelSrc).toContain('Scale')
    expect(panelSrc).toContain('lucide-react')
  })

  it('imports api from lib/api.js', () => {
    expect(panelSrc).toContain("from '../lib/api.js'")
  })

  it('calls api.jewelryMetalCost', () => {
    expect(panelSrc).toContain('api.jewelryMetalCost')
  })

  it('exports default JewelryCostPanel function', () => {
    expect(panelSrc).toContain('export default function JewelryCostPanel')
  })

  it('includes volume_mm3 input', () => {
    expect(panelSrc).toContain('volumeMm3')
  })

  it('includes casting allowance input', () => {
    expect(panelSrc).toContain('allowancePct')
  })

  it('displays net weight in grams, dwt, and ozt', () => {
    expect(panelSrc).toContain('net_grams')
    expect(panelSrc).toContain('net_dwt')
    expect(panelSrc).toContain('net_ozt')
  })

  it('displays gross casting weight', () => {
    expect(panelSrc).toContain('gross_grams')
  })

  it('renders metal selector with gold options', () => {
    expect(panelSrc).toContain('18k_yellow')
    expect(panelSrc).toContain('platinum_950')
    expect(panelSrc).toContain('sterling_925')
  })

  it('renders labor and finishing inputs', () => {
    expect(panelSrc).toContain('labor')
    expect(panelSrc).toContain('finishing')
  })

  it('includes multi-metal comparison table component', () => {
    expect(panelSrc).toContain('CompareTable')
  })

  it('has DENSITY table with all key metals', () => {
    const denseIdx = panelSrc.indexOf('const DENSITY')
    const block = panelSrc.slice(denseIdx, denseIdx + 2000)
    for (const key of ['18k_yellow', 'platinum_950', 'sterling_925', 'titanium']) {
      expect(block).toContain(key)
    }
  })
})

// ---------------------------------------------------------------------------
// 7. api.js jewelryMetalCost entry
// ---------------------------------------------------------------------------

describe('api.js — jewelryMetalCost', () => {
  it('method exists in api object', () => {
    expect(apiSrc).toContain('jewelryMetalCost')
  })

  it('calls the /jewelry/metal-cost endpoint', () => {
    const idx = apiSrc.indexOf('jewelryMetalCost')
    const block = apiSrc.slice(idx, idx + 200)
    expect(block).toContain('jewelry/metal-cost')
  })

  it('uses POST method', () => {
    const idx = apiSrc.indexOf('jewelryMetalCost')
    const block = apiSrc.slice(idx, idx + 200)
    expect(block).toContain("'POST'")
  })
})

// ---------------------------------------------------------------------------
// 8. LLM doc
// ---------------------------------------------------------------------------

describe('LLM doc jewelry_metal_cost.md', () => {
  it('file exists', () => {
    expect(llmDocSrc.length).toBeGreaterThan(0)
  })

  it('documents the jewelry_metal_cost tool name', () => {
    expect(llmDocSrc).toContain('jewelry_metal_cost')
  })

  it('documents dwt conversion', () => {
    expect(llmDocSrc).toContain('dwt')
    expect(llmDocSrc).toContain('1.55517384')
  })

  it('documents troy ounce conversion', () => {
    expect(llmDocSrc).toContain('31.1034768')
  })

  it('documents casting allowance rationale', () => {
    expect(llmDocSrc).toContain('casting')
    expect(llmDocSrc).toContain('sprue')
  })

  it('includes worked example', () => {
    expect(llmDocSrc).toContain('300')
    expect(llmDocSrc).toContain('18k')
  })

  it('documents density table with platinum_950', () => {
    expect(llmDocSrc).toContain('platinum_950')
    expect(llmDocSrc).toContain('21.40')
  })
})

// ---------------------------------------------------------------------------
// 9. Python plugin registration
// ---------------------------------------------------------------------------

describe('Python plugin — tool module registration', () => {
  const pluginSrc = readFileSync(
    path.resolve(__dirname, '../../packages/kerf-cad-core/src/kerf_cad_core/plugin.py'),
    'utf8',
  )

  it("_TOOL_MODULES includes 'kerf_cad_core.jewelry.tool_metal_cost'", () => {
    expect(pluginSrc).toContain('kerf_cad_core.jewelry.tool_metal_cost')
  })
})

// ===========================================================================
// Full-quote model tests (new functionality)
// ===========================================================================

// ---------------------------------------------------------------------------
// Mirrors of the new helper functions from JewelryCostPanel.jsx
// ---------------------------------------------------------------------------

const MM_TO_CARAT_FACTOR = {
  round_brilliant: 0.00370, princess: 0.00390, oval: 0.00280,
  cushion: 0.00350, pear: 0.00240, marquise: 0.00200, emerald: 0.00240,
  asscher: 0.00350, radiant: 0.00360, heart: 0.00230,
}

function mmToCarat(mm, cut) {
  const factor = MM_TO_CARAT_FACTOR[cut] ?? 0.00370
  return mm ** 3 * factor
}

const SETTING_FEE = {
  prong: 12.0, bezel: 18.0, pave: 5.0, channel: 8.0,
  flush: 10.0, invisible: 22.0, tension: 25.0, bar: 10.0,
}

const FINISHING_COST_MAP = {
  '': 0.0, polish: 0.0, satin: 15.0, hammer: 20.0,
  rhodium: 35.0, black_rhodium: 45.0, gold_plate: 25.0,
  antique: 20.0, sandblast: 18.0,
}

function stonesTotal(stones) {
  if (!stones || stones.length === 0) {
    return { line_items: [], total_carats: 0, total_stones: 0, total_cost: 0 }
  }
  const line_items = []
  let total_carats = 0; let total_cost = 0; let total_stones = 0
  for (const s of stones) {
    const ppc = parseFloat(s.price_per_carat) || 0
    const count = parseInt(s.count, 10) || 1
    let carat_each = parseFloat(s.carat)
    if (!carat_each && s.mm) {
      const mm = parseFloat(s.mm)
      carat_each = mm > 0 ? mmToCarat(mm, s.cut || 'round_brilliant') : 0
    }
    if (!(carat_each > 0)) continue
    const line_total = carat_each * ppc * count
    line_items.push({ cut: s.cut || 'round_brilliant', carat_each, count, price_per_carat: ppc, line_total, note: s.note || '' })
    total_carats += carat_each * count
    total_cost += line_total
    total_stones += count
  }
  return { line_items, total_carats, total_stones, total_cost }
}

function labourTotal({ bench_hours, hourly_rate, stones, setting_type, setting_fee_per_stone, finishing_type, finishing_cost_override }) {
  const bench = (parseFloat(bench_hours) || 0) * (parseFloat(hourly_rate) || 0)
  const stoneCount = stones ? stones.reduce((acc, s) => acc + (parseInt(s.count, 10) || 1), 0) : 0
  const feePerStone = setting_fee_per_stone != null
    ? parseFloat(setting_fee_per_stone)
    : (SETTING_FEE[setting_type] ?? SETTING_FEE.prong)
  const settingCost = feePerStone * stoneCount
  let finCost = 0
  if (finishing_cost_override != null && finishing_cost_override !== '') {
    finCost = parseFloat(finishing_cost_override) || 0
  } else if (finishing_type) {
    finCost = FINISHING_COST_MAP[finishing_type] ?? 0
  }
  return {
    bench_hours: parseFloat(bench_hours) || 0,
    hourly_rate: parseFloat(hourly_rate) || 0,
    bench_labour_cost: bench,
    setting_type: setting_type || 'prong',
    setting_fee_per_stone: feePerStone,
    stone_count: stoneCount,
    setting_cost: settingCost,
    finishing_type: finishing_type || 'none',
    finishing_cost: finCost,
    total_labour: bench + settingCost + finCost,
  }
}

const DENSITY_FULL = {
  '10k_yellow': 11.57, '14k_yellow': 13.07, '18k_yellow': 15.58,
  '22k_yellow': 17.80, '24k_yellow': 19.32,
  '10k_white': 11.61,  '14k_white': 13.25,  '18k_white': 15.60, '22k_white': 17.60,
  '10k_rose': 11.59,   '14k_rose': 13.20,   '18k_rose': 15.45,  '22k_rose': 17.75,
  platinum_950: 21.40, platinum_900: 21.30,
  palladium_950: 11.00, palladium_500: 10.60,
  sterling_925: 10.36, fine_silver: 10.49, argentium_935: 10.40,
  titanium: 4.51, brass: 8.53, bronze: 8.78,
}

function localFullQuote({ volumeMm3, metalKey, pricePerGram, allowancePct, stones, labourParams, markupPct }) {
  const d = DENSITY_FULL[metalKey]
  if (!d || volumeMm3 <= 0) return null
  const netG = d * (volumeMm3 / 1000)
  const grossG = netG * (1 + allowancePct / 100)
  const metalCost = grossG * pricePerGram
  const stonesResult = stonesTotal(stones)
  const labourResult = labourTotal({ ...labourParams, stones })
  const subtotal = metalCost + stonesResult.total_cost + labourResult.total_labour
  const markupAmount = subtotal * markupPct / 100
  const total = subtotal + markupAmount
  return {
    mode: 'full_quote',
    metal: metalKey,
    net_grams: netG,
    net_dwt: netG / GRAMS_PER_DWT,
    net_ozt: netG / GRAMS_PER_OZT,
    allowance_pct: allowancePct,
    gross_grams: grossG,
    metal_cost: metalCost,
    casting_cost: metalCost,
    stones: stonesResult,
    stone_cost: stonesResult.total_cost,
    labour: labourResult,
    labour_total: labourResult.total_labour,
    subtotal,
    markup_pct: markupPct,
    markup_amount: markupAmount,
    total,
  }
}

// ---------------------------------------------------------------------------
// 10. New alloys in METAL_OPTIONS
// ---------------------------------------------------------------------------

describe('JewelryCostPanel.jsx — new alloy catalogue', () => {
  it('includes 22k_white gold', () => {
    expect(panelSrc).toContain('22k_white')
  })

  it('includes 22k_rose gold', () => {
    expect(panelSrc).toContain('22k_rose')
  })

  it('includes platinum_900', () => {
    expect(panelSrc).toContain('platinum_900')
  })

  it('includes palladium_500', () => {
    expect(panelSrc).toContain('palladium_500')
  })

  it('includes argentium_935', () => {
    expect(panelSrc).toContain('argentium_935')
  })

  it('includes hallmark information for 18k (750)', () => {
    expect(panelSrc).toContain('750')
  })

  it('includes hallmark information for sterling silver (925)', () => {
    expect(panelSrc).toContain('925')
  })
})

// ---------------------------------------------------------------------------
// 11. Full-quote math — worked example from jewelry_metal_cost.md
// ---------------------------------------------------------------------------

describe('localFullQuote — worked example', () => {
  // 18k yellow, 300 mm³, $48/g, 15% allowance
  // net = 15.58 × 0.3 = 4.674 g; gross = 4.674 × 1.15 = 5.375 g
  // metal_cost = 5.375 × 48 = 258.00
  // stone: 0.5 ct round brilliant at $2000/ct × 1 = $1000.00
  // labour: 4h × $75 = $300; prong × 1 = $12; rhodium = $35; total_labour = $347
  // subtotal = 258 + 1000 + 347 = $1605
  // markup 20% = $321, total = $1926

  const stones = [{ cut: 'round_brilliant', carat: 0.5, price_per_carat: 2000, count: 1 }]
  const labourParams = {
    bench_hours: 4,
    hourly_rate: 75,
    setting_type: 'prong',
    setting_fee_per_stone: null,
    finishing_type: 'rhodium',
    finishing_cost_override: null,
  }

  const result = localFullQuote({
    volumeMm3: 300,
    metalKey: '18k_yellow',
    pricePerGram: 48,
    allowancePct: 15,
    stones,
    labourParams,
    markupPct: 20,
  })

  it('net_grams ≈ 4.674', () => {
    expect(result.net_grams).toBeCloseTo(4.674, 2)
  })

  it('gross_grams ≈ 5.375', () => {
    expect(result.gross_grams).toBeCloseTo(5.375, 2)
  })

  it('metal_cost ≈ 258.00', () => {
    expect(result.metal_cost).toBeCloseTo(258.0, 1)
  })

  it('stone_cost == 1000.00', () => {
    expect(result.stone_cost).toBeCloseTo(1000.0, 2)
  })

  it('stone line item has correct carat_each and count', () => {
    expect(result.stones.line_items).toHaveLength(1)
    expect(result.stones.line_items[0].carat_each).toBeCloseTo(0.5, 4)
    expect(result.stones.line_items[0].count).toBe(1)
  })

  it('bench_labour_cost ≈ 300.00', () => {
    expect(result.labour.bench_labour_cost).toBeCloseTo(300.0, 2)
  })

  it('setting_cost ≈ 12.00 (prong × 1)', () => {
    expect(result.labour.setting_cost).toBeCloseTo(12.0, 2)
  })

  it('finishing_cost ≈ 35.00 (rhodium)', () => {
    expect(result.labour.finishing_cost).toBeCloseTo(35.0, 2)
  })

  it('labour_total ≈ 347.00', () => {
    expect(result.labour_total).toBeCloseTo(347.0, 2)
  })

  it('subtotal ≈ 1605.00', () => {
    expect(result.subtotal).toBeCloseTo(1605.0, 1)
  })

  it('markup_amount ≈ 321.00', () => {
    expect(result.markup_amount).toBeCloseTo(321.0, 1)
  })

  it('total ≈ 1926.00', () => {
    expect(result.total).toBeCloseTo(1926.0, 0)
  })

  it('total = subtotal + markup_amount', () => {
    expect(result.total).toBeCloseTo(result.subtotal + result.markup_amount, 4)
  })

  it('subtotal = metal_cost + stone_cost + labour_total', () => {
    expect(result.subtotal).toBeCloseTo(
      result.metal_cost + result.stone_cost + result.labour_total,
      4,
    )
  })
})

// ---------------------------------------------------------------------------
// 12. Stones table — add / remove
// ---------------------------------------------------------------------------

describe('stonesTotal — add/remove rows', () => {
  it('empty array returns zeros', () => {
    const r = stonesTotal([])
    expect(r.total_cost).toBe(0)
    expect(r.total_stones).toBe(0)
    expect(r.line_items).toHaveLength(0)
  })

  it('single stone computed correctly', () => {
    const r = stonesTotal([{ cut: 'round_brilliant', carat: 1.0, price_per_carat: 5000, count: 1 }])
    expect(r.total_cost).toBeCloseTo(5000.0, 2)
    expect(r.total_stones).toBe(1)
    expect(r.line_items[0].line_total).toBeCloseTo(5000.0, 2)
  })

  it('count multiplies line_total', () => {
    const r = stonesTotal([{ cut: 'pave', carat: 0.05, price_per_carat: 200, count: 10 }])
    expect(r.total_cost).toBeCloseTo(0.05 * 200 * 10, 4)
    expect(r.total_stones).toBe(10)
  })

  it('multiple stones sum correctly', () => {
    const stones = [
      { cut: 'round_brilliant', carat: 0.5, price_per_carat: 2000, count: 1 },
      { cut: 'pave', carat: 0.03, price_per_carat: 100, count: 5 },
    ]
    const r = stonesTotal(stones)
    const expected = 0.5 * 2000 * 1 + 0.03 * 100 * 5
    expect(r.total_cost).toBeCloseTo(expected, 4)
    expect(r.total_stones).toBe(6)
    expect(r.line_items).toHaveLength(2)
  })

  it('stone with mm diameter uses mm→carat formula', () => {
    // 6.5mm round brilliant: 6.5^3 × 0.00370 ≈ 1.016 ct
    const r = stonesTotal([{ cut: 'round_brilliant', mm: 6.5, price_per_carat: 1000, count: 1 }])
    const expectedCarat = 6.5 ** 3 * 0.00370
    expect(r.line_items[0].carat_each).toBeCloseTo(expectedCarat, 4)
    expect(r.total_cost).toBeCloseTo(expectedCarat * 1000, 3)
  })

  it('stone with zero/missing price_per_carat contributes zero cost', () => {
    const r = stonesTotal([{ cut: 'round_brilliant', carat: 1.0, price_per_carat: 0, count: 1 }])
    expect(r.total_cost).toBe(0)
  })

  it('removing stone by filtering reduces total', () => {
    let stones = [
      { cut: 'round_brilliant', carat: 0.5, price_per_carat: 2000, count: 1 },
      { cut: 'emerald', carat: 0.3, price_per_carat: 800, count: 2 },
    ]
    const before = stonesTotal(stones)
    // Simulate removing index 1
    stones = stones.filter((_, i) => i !== 1)
    const after = stonesTotal(stones)
    expect(after.total_cost).toBeLessThan(before.total_cost)
    expect(after.line_items).toHaveLength(1)
  })
})

// ---------------------------------------------------------------------------
// 13. Labour cost calculation
// ---------------------------------------------------------------------------

describe('labourTotal', () => {
  it('bench hours × rate', () => {
    const r = labourTotal({ bench_hours: 4, hourly_rate: 75, stones: [], setting_type: 'prong' })
    expect(r.bench_labour_cost).toBeCloseTo(300, 2)
  })

  it('setting_cost = fee × stone_count', () => {
    const stones = [{ count: 3 }]
    const r = labourTotal({ bench_hours: 0, hourly_rate: 0, stones, setting_type: 'pave' })
    expect(r.setting_cost).toBeCloseTo(SETTING_FEE.pave * 3, 4)
  })

  it('setting fee override overrides default', () => {
    const stones = [{ count: 2 }]
    const r = labourTotal({ bench_hours: 0, hourly_rate: 0, stones, setting_type: 'prong', setting_fee_per_stone: 20 })
    expect(r.setting_fee_per_stone).toBe(20)
    expect(r.setting_cost).toBeCloseTo(40, 4)
  })

  it('named finishing_type applies correct cost', () => {
    const r = labourTotal({ bench_hours: 0, hourly_rate: 0, stones: [], setting_type: 'prong', finishing_type: 'rhodium' })
    expect(r.finishing_cost).toBeCloseTo(35.0, 2)
  })

  it('finishing_cost_override beats named type', () => {
    const r = labourTotal({ bench_hours: 0, hourly_rate: 0, stones: [], setting_type: 'prong', finishing_type: 'rhodium', finishing_cost_override: '50' })
    expect(r.finishing_cost).toBeCloseTo(50.0, 2)
  })

  it('total_labour = bench + setting + finishing', () => {
    const stones = [{ count: 1 }]
    const r = labourTotal({ bench_hours: 2, hourly_rate: 80, stones, setting_type: 'bezel', finishing_type: 'satin' })
    expect(r.total_labour).toBeCloseTo(r.bench_labour_cost + r.setting_cost + r.finishing_cost, 4)
  })

  it('no stones → setting_cost = 0', () => {
    const r = labourTotal({ bench_hours: 0, hourly_rate: 0, stones: [], setting_type: 'prong' })
    expect(r.setting_cost).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// 14. Markup
// ---------------------------------------------------------------------------

describe('localFullQuote — markup', () => {
  it('zero markup: total == subtotal', () => {
    const r = localFullQuote({
      volumeMm3: 500, metalKey: '14k_yellow', pricePerGram: 37.5,
      allowancePct: 15, stones: [], labourParams: { bench_hours: 0, hourly_rate: 0, setting_type: 'prong' },
      markupPct: 0,
    })
    expect(r.total).toBeCloseTo(r.subtotal, 4)
    expect(r.markup_amount).toBeCloseTo(0, 4)
  })

  it('10% markup: markup_amount = subtotal * 0.1', () => {
    const r = localFullQuote({
      volumeMm3: 500, metalKey: '14k_yellow', pricePerGram: 37.5,
      allowancePct: 15, stones: [], labourParams: { bench_hours: 0, hourly_rate: 0, setting_type: 'prong' },
      markupPct: 10,
    })
    expect(r.markup_amount).toBeCloseTo(r.subtotal * 0.1, 4)
  })
})

// ---------------------------------------------------------------------------
// 15. Legacy casting_cost mode still works
// ---------------------------------------------------------------------------

describe('legacy casting_cost mode', () => {
  it('localEstimate still computes metal_cost correctly', () => {
    const r = localEstimate(1000, 'sterling_925', 0.80, 0, 0)
    expect(r.metal_cost).toBeCloseTo(r.gross_grams * 0.80, 4)
  })

  it('localEstimate total_cost = metal + labor + finishing', () => {
    const r = localEstimate(500, 'platinum_950', 32.0, 100, 50)
    expect(r.total_cost).toBeCloseTo(r.metal_cost + 100 + 50, 4)
  })

  it('does not include stone / labour / markup fields', () => {
    const r = localEstimate(300, '18k_yellow', 48, 80, 20)
    expect(r.stone_cost).toBeUndefined()
    expect(r.markup_pct).toBeUndefined()
    expect(r.subtotal).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// 16. Multi-metal compare — component source checks
// ---------------------------------------------------------------------------

describe('JewelryCostPanel.jsx — full quote UI source checks', () => {
  it('includes stonesTotal function', () => {
    expect(panelSrc).toContain('stonesTotal')
  })

  it('includes labourTotal function', () => {
    expect(panelSrc).toContain('labourTotal')
  })

  it('includes localFullQuote function', () => {
    expect(panelSrc).toContain('localFullQuote')
  })

  it('includes SETTING_FEE table', () => {
    expect(panelSrc).toContain('SETTING_FEE')
  })

  it('includes FINISHING_COST_MAP table', () => {
    expect(panelSrc).toContain('FINISHING_COST_MAP')
  })

  it('includes StoneRow subcomponent', () => {
    expect(panelSrc).toContain('StoneRow')
  })

  it('includes markup_pct state', () => {
    expect(panelSrc).toContain('markupPct')
  })

  it('full quote breakdown renders subtotal field', () => {
    expect(panelSrc).toContain('subtotal')
  })

  it('full quote renders markup_amount', () => {
    expect(panelSrc).toContain('markup_amount')
  })

  it('includes mode toggle (full_quote / casting_cost)', () => {
    expect(panelSrc).toContain('full_quote')
    expect(panelSrc).toContain('casting_cost')
  })

  it('includes bench_hours input', () => {
    expect(panelSrc).toContain('benchHours')
  })

  it('includes setting type selector', () => {
    expect(panelSrc).toContain('settingType')
    expect(panelSrc).toContain('prong')
  })

  it('includes finishing type selector', () => {
    expect(panelSrc).toContain('finishingType')
    expect(panelSrc).toContain('rhodium')
  })

  it('stone add/remove buttons present', () => {
    expect(panelSrc).toContain('handleStoneAdd')
    expect(panelSrc).toContain('handleStoneRemove')
  })

  it('hallmark displayed in UI', () => {
    expect(panelSrc).toContain('hallmark')
  })
})

// ---------------------------------------------------------------------------
// 17. api.js — jewelryQuote method
// ---------------------------------------------------------------------------

describe('api.js — jewelryQuote', () => {
  it('method jewelryQuote exists in api object', () => {
    expect(apiSrc).toContain('jewelryQuote')
  })

  it('jewelryQuote calls the /jewelry/metal-cost endpoint', () => {
    // find the actual method assignment: `jewelryQuote: (projectId`
    const idx = apiSrc.indexOf('jewelryQuote: (projectId')
    expect(idx).toBeGreaterThan(-1)
    const block = apiSrc.slice(idx, idx + 300)
    expect(block).toContain('jewelry/metal-cost')
  })

  it('jewelryQuote uses POST method', () => {
    const idx = apiSrc.indexOf('jewelryQuote: (projectId')
    expect(idx).toBeGreaterThan(-1)
    const block = apiSrc.slice(idx, idx + 300)
    expect(block).toContain("'POST'")
  })

  it('both jewelryMetalCost and jewelryQuote are present', () => {
    expect(apiSrc).toContain('jewelryMetalCost')
    expect(apiSrc).toContain('jewelryQuote')
  })
})
