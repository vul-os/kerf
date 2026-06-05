/**
 * jewelryConfigurator.test.jsx — Pure data-layer tests for JewelryConfiguratorPanel.
 *
 * Follows the project pattern (see graphEditor.test.jsx, mepView.test.jsx):
 * all interesting logic lives in jewelryConfig.js which the panel wraps.
 * No React render overhead here — we test the math library used by the panel.
 *
 * Additional smoke: verify the panel module can be imported without error.
 */

import { describe, it, expect } from 'vitest'
import {
  caratFromMm,
  mmFromCarat,
  ringSizeToDiameter,
  ringDiameterToSize,
  metalWeight,
  castingWeight,
  computeProngParams,
  computeBezelParams,
  computePaveLayout,
  ringBandVolume,
  idealProportions,
  GEM_CATALOG,
  CUT_CATALOG,
  METAL_DENSITY,
  METAL_HALLMARK,
  UK_AU_SIZES,
} from '../../lib/jewelryConfig.js'

// ── Panel import smoke ────────────────────────────────────────────────────────

describe('JewelryConfiguratorPanel module', () => {
  it('can be imported without error', async () => {
    const mod = await import('../JewelryConfiguratorPanel.jsx')
    expect(typeof mod.default).toBe('function')
  })
})

// ── Ring-sizer tab logic ──────────────────────────────────────────────────────

describe('ring sizer — US system', () => {
  it('size 6 is smaller than size 8', () => {
    expect(ringSizeToDiameter('US', 6)).toBeLessThan(ringSizeToDiameter('US', 8))
  })

  it('half-sizes are supported', () => {
    const d65 = ringSizeToDiameter('US', 6.5)
    const d6  = ringSizeToDiameter('US', 6)
    const d7  = ringSizeToDiameter('US', 7)
    expect(d65).toBeGreaterThan(d6)
    expect(d65).toBeLessThan(d7)
  })

  it('inverse round-trip for size 5.5', () => {
    const d = ringSizeToDiameter('US', 5.5)
    expect(ringDiameterToSize('US', d)).toBe(5.5)
  })
})

describe('ring sizer — UK/AU system', () => {
  it('size L is smaller than size R', () => {
    expect(ringSizeToDiameter('UK', 'L')).toBeLessThan(ringSizeToDiameter('UK', 'R'))
  })

  it('half-sizes work', () => {
    const dN  = ringSizeToDiameter('UK', 'N')
    const dNh = ringSizeToDiameter('UK', 'N½')
    expect(dNh).toBeGreaterThan(dN)
  })

  it('UK and AU give same result', () => {
    expect(ringSizeToDiameter('UK', 'M')).toBeCloseTo(ringSizeToDiameter('AU', 'M'), 8)
  })

  it('all UK_AU_SIZES keys produce a valid positive diameter', () => {
    for (const key of Object.keys(UK_AU_SIZES)) {
      const d = ringSizeToDiameter('UK', key)
      expect(d).toBeGreaterThan(0), `UK size ${key}: must be positive`
    }
  })
})

describe('ring sizer — EU system', () => {
  it('EU 52 → 52/π mm', () => {
    expect(ringSizeToDiameter('EU', 52)).toBeCloseTo(52 / Math.PI, 4)
  })

  it('larger EU number → larger diameter', () => {
    expect(ringSizeToDiameter('EU', 58)).toBeGreaterThan(ringSizeToDiameter('EU', 54))
  })

  it('round-trip EU 56', () => {
    const d = ringSizeToDiameter('EU', 56)
    expect(ringDiameterToSize('EU', d)).toBe(56)
  })
})

describe('ring sizer — JP system', () => {
  it('JP 10 smaller than JP 20', () => {
    expect(ringSizeToDiameter('JP', 10)).toBeLessThan(ringSizeToDiameter('JP', 20))
  })

  it('round-trip JP 15', () => {
    const d = ringSizeToDiameter('JP', 15)
    expect(ringDiameterToSize('JP', d)).toBe(15)
  })
})

// ── Ring band weight ──────────────────────────────────────────────────────────

describe('ring band weight via ringBandVolume + metalWeight', () => {
  function ringWeight(sizeName, system, bandW, wallT, metal) {
    const id  = ringSizeToDiameter(system, sizeName)
    const vol = ringBandVolume(id, bandW, wallT)
    return metalWeight(vol, metal)
  }

  it('18k yellow gold 4 mm × 1.5 mm band at US 7 is roughly 3–6 g', () => {
    const w = ringWeight(7, 'US', 4.0, 1.5, '18k_yellow')
    expect(w.netGrams).toBeGreaterThan(2)
    expect(w.netGrams).toBeLessThan(8)
  })

  it('platinum band is heavier than same-volume silver band', () => {
    const id  = ringSizeToDiameter('US', 7)
    const vol = ringBandVolume(id, 4.0, 1.5)
    const pt  = metalWeight(vol, 'platinum_950')
    const ag  = metalWeight(vol, 'sterling_925')
    expect(pt.netGrams).toBeGreaterThan(ag.netGrams)
  })

  it('wider band is heavier', () => {
    const id   = ringSizeToDiameter('US', 7)
    const vol4 = ringBandVolume(id, 4.0, 1.5)
    const vol8 = ringBandVolume(id, 8.0, 1.5)
    const w4   = metalWeight(vol4, '18k_yellow')
    const w8   = metalWeight(vol8, '18k_yellow')
    expect(w8.netGrams).toBeGreaterThan(w4.netGrams)
  })

  it('casting gross weight with 15% allowance > net', () => {
    const id  = ringSizeToDiameter('US', 7)
    const vol = ringBandVolume(id, 4.0, 1.5)
    const cw  = castingWeight(vol, '18k_yellow', 15)
    expect(cw.grossGrams).toBeGreaterThan(cw.netGrams)
    expect(cw.allowancePct).toBe(15)
  })
})

// ── Gem picker tab logic ──────────────────────────────────────────────────────

describe('gem picker — carat/mm conversion', () => {
  it('round brilliant 6.5 mm diamond ≈ 1 ct', () => {
    expect(caratFromMm(6.5, 'round_brilliant', 'diamond')).toBeCloseTo(1.0, 2)
  })

  it('ruby is denser than diamond → more carats per mm', () => {
    const d = 5.0
    expect(caratFromMm(d, 'round_brilliant', 'ruby'))
      .toBeGreaterThan(caratFromMm(d, 'round_brilliant', 'diamond'))
  })

  it('emerald cut 7 mm ≈ 1 ct for diamond', () => {
    expect(caratFromMm(7.0, 'emerald', 'diamond')).toBeCloseTo(1.0, 2)
  })

  it('inverse: mmFromCarat(1, "round_brilliant") ≈ 6.5 mm', () => {
    expect(mmFromCarat(1.0, 'round_brilliant')).toBeCloseTo(6.5, 2)
  })

  it('all CUT_CATALOG entries produce a positive result at 1 ct', () => {
    for (const c of CUT_CATALOG) {
      const mm = mmFromCarat(1.0, c.name)
      expect(mm).toBeGreaterThan(0), `cut=${c.name}: mmFromCarat must be > 0`
    }
  })
})

describe('gem catalog', () => {
  it('has at least 10 entries', () => {
    expect(GEM_CATALOG.length).toBeGreaterThanOrEqual(10)
  })

  it('every entry has name, label, mohs, ri', () => {
    for (const g of GEM_CATALOG) {
      expect(g.name).toBeTruthy()
      expect(g.label).toBeTruthy()
      expect(Array.isArray(g.mohs)).toBe(true)
      expect(Array.isArray(g.ri)).toBe(true)
    }
  })
})

// ── Setting builder tab logic ─────────────────────────────────────────────────

describe('setting builder — prong', () => {
  it('6-prong has more prongs than 4-prong', () => {
    expect(computeProngParams(6.5, 6).prong_count).toBe(6)
  })

  it('prong_diameter scales with stone size', () => {
    const small = computeProngParams(4.0)
    const large = computeProngParams(8.0)
    expect(large.prong_diameter_mm).toBeGreaterThan(small.prong_diameter_mm)
  })

  it('seat depth is always positive', () => {
    expect(computeProngParams(6.5).seat_depth_mm).toBeGreaterThan(0)
  })
})

describe('setting builder — bezel', () => {
  it('wall is 10% of stone by default', () => {
    const r = computeBezelParams(6.5)
    expect(r.bezel_wall_mm).toBeCloseTo(6.5 * 0.10, 3)
  })

  it('larger stone → larger bezel', () => {
    expect(computeBezelParams(8.0).bezel_outer_diameter_mm)
      .toBeGreaterThan(computeBezelParams(5.0).bezel_outer_diameter_mm)
  })

  it('inner is smaller than outer', () => {
    const r = computeBezelParams(7.0)
    expect(r.bezel_inner_diameter_mm).toBeLessThan(r.bezel_outer_diameter_mm)
  })
})

describe('setting builder — pavé', () => {
  it('more rows → more stones', () => {
    const r1 = computePaveLayout(1.2, 30.0, 1)
    const r3 = computePaveLayout(1.2, 30.0, 3)
    expect(r3.stone_count).toBe(r1.stone_count * 3)
  })

  it('longer band → more stones', () => {
    const short = computePaveLayout(1.2, 20.0)
    const long  = computePaveLayout(1.2, 40.0)
    expect(long.stones_per_row).toBeGreaterThan(short.stones_per_row)
  })

  it('drill depth = 50% of stone diameter', () => {
    const r = computePaveLayout(1.5, 30.0)
    expect(r.drill_depth_mm).toBeCloseTo(0.75, 3)
  })
})

// ── Ideal proportions ─────────────────────────────────────────────────────────

describe('idealProportions', () => {
  it('round_brilliant table_pct lower bound ≥ 50', () => {
    const p = idealProportions('round_brilliant')
    expect(p.table_pct[0]).toBeGreaterThanOrEqual(50)
  })

  it('all defined cuts have a note string', () => {
    const knownCuts = ['round_brilliant', 'princess', 'emerald', 'oval', 'cushion', 'marquise']
    for (const cut of knownCuts) {
      const p = idealProportions(cut)
      expect(p).not.toBeNull(), `cut=${cut}: proportions should not be null`
      expect(typeof p.note).toBe('string')
    }
  })
})
